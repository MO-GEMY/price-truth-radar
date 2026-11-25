<#
.SYNOPSIS
    Zero-CU Offline Local Scraper Runner for Price Truth Radar (`region_mode: local_only`).

.DESCRIPTION
    Minimizes Neon Compute Hours (CU-hrs) by enforcing a strict 2-phase offline architecture:
      1. OFFLINE SCRAPE (0 CU): Unsets DATABASE_URL* and scrapes ALL enabled `local_only`
         stores (including `extra_verticals` such as `amazon_eg:core` + `amazon_eg:groceries`)
         concurrently in parallel workers into a compact `.jsonl.gz` staging artifact on disk.
         Neon stays 100% SUSPENDED during all HTTP requests, retries, and rate-limit waits.
      2. SINGLE NEON SESSION (~25s): Opens Neon ONCE at the end via
         `scripts/offline_tiered_pipeline.py load-and-transform` to stream-load the entire batch
         via PostgreSQL `COPY`, run incremental `dbt`, optionally run RAM `--match-db` +
         `dbt test` + `check_price_alerts.py`, and `TRUNCATE raw.raw_product_snapshots`.
#>

[CmdletBinding()]
param(
    [string[]]$Stores = @(),
    [ValidateSet("daily", "discover", "discovery", "expand")]
    [string]$Mode = "daily",
    [switch]$Discovery,
    [int]$Limit = 0,
    [int]$Workers = 4,
    [double]$Delay = 0.9,
    [switch]$DryRun,
    [switch]$SkipMatchDb,
    [switch]$RunDbt,
    [switch]$RunAlerts,
    [int]$LogRetentionDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if ($Discovery) {
    $Mode = "discover"
} elseif ($Mode -eq "discovery") {
    $Mode = "discover"
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PipelineScript = Join-Path $RepoRoot "scripts\offline_tiered_pipeline.py"
$StagingDir = Join-Path $RepoRoot "data\local_offline_staging"
$LogDir = Join-Path $RepoRoot "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Prune local scraper logs older than $LogRetentionDays days
$Cutoff = (Get-Date).AddDays(-[Math]::Abs($LogRetentionDays))
Get-ChildItem -Path $LogDir -Filter "local_scraper*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $Cutoff } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$DateStamp = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "local_scraper_$DateStamp.log"

function Write-Log {
    param([string]$Message)
    $Line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Output $Line
    Add-Content -Path $LogFile -Value $Line -Encoding UTF8
}

function Resolve-PythonExe {
    $candidates = @(
        (Join-Path $RepoRoot "venv\Scripts\python.exe"),
        "D:\anaconda3\python.exe"
    )
    $cmdPy = Get-Command python -ErrorAction SilentlyContinue
    if ($cmdPy -and $cmdPy.Source) {
        $candidates += $cmdPy.Source
    }

    foreach ($py in $candidates) {
        if (-not $py -or -not (Test-Path $py)) { continue }
        & $py -c "import psycopg2, curl_cffi, httpx, bs4, yaml" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $py }
    }
    return $null
}

$PythonExe = Resolve-PythonExe
if (-not $PythonExe) {
    Write-Log "ERROR: Could not find Python interpreter with required scraper dependencies."
    exit 1
}

if (-not (Test-Path $PipelineScript)) {
    Write-Log "ERROR: Offline pipeline script not found at $PipelineScript"
    exit 1
}

# Prepare clean offline staging directory
if (Test-Path $StagingDir) {
    Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $StagingDir -Force | Out-Null
$ArtifactPath = Join-Path $StagingDir "local_only_${Mode}_${DateStamp}.jsonl.gz"

$ExplicitCsv = if ($Stores -and $Stores.Count -gt 0) { ($Stores -join ",") } else { "" }

Write-Log "======================================================================"
Write-Log "Price Truth Radar Local Runner — 100% OFFLINE SCRAPE -> SINGLE COPY"
Write-Log "RepoRoot   : $RepoRoot"
Write-Log "PythonExe  : $PythonExe"
Write-Log "Stores     : $(if ($ExplicitCsv) { $ExplicitCsv } else { 'ALL enabled local_only (from stores_registry.yaml)' })"
Write-Log "Mode       : $Mode | Workers=$Workers | Delay=${Delay}s"
Write-Log "SkipMatchDb: $SkipMatchDb | RunDbt=$RunDbt | RunAlerts=$RunAlerts | DryRun=$DryRun"
Write-Log "======================================================================"

Push-Location $RepoRoot
$FinalExit = 0

try {
    # PHASE 1: 100% OFFLINE PARALLEL HTTP SCRAPING (ZERO NEON CONNECTIONS / 0 CU)
    $ScrapeArgs = @(
        $PipelineScript, "scrape-shard",
        "--shard", "local_only",
        "--priority", "p1_major_brands",
        "--mode", $Mode,
        "--workers", "$Workers",
        "--delay", "$Delay",
        "--out", $ArtifactPath
    )
    if ($ExplicitCsv) {
        $ScrapeArgs += @("--stores", $ExplicitCsv)
    } else {
        $ScrapeArgs += "--local-only"
    }
    if ($Limit -gt 0) {
        $ScrapeArgs += @("--limit", "$Limit")
    }

    Write-Log "PHASE 1 (OFFLINE / 0 CU): Starting parallel scrape-shard -> $ArtifactPath ..."
    & $PythonExe @ScrapeArgs 2>&1 | ForEach-Object {
        $text = $_.ToString()
        Write-Output $text
        Add-Content -Path $LogFile -Value $text -Encoding UTF8
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "WARNING: Offline scrape-shard exited with code $LASTEXITCODE."
        $FinalExit = $LASTEXITCODE
    }

    # PHASE 2: SINGLE NEON BULK-COPY SESSION -> DBT -> TRUNCATE RAW -> DISCONNECT
    if (Test-Path $ArtifactPath) {
        $LoadArgs = @(
            $PipelineScript, "load-and-transform",
            "--artifacts-dir", $StagingDir,
            "--warn-mb", "900",
            "--stop-mb", "970",
            "--soft-exit-on-stop"
        )
        if ($DryRun) {
            $LoadArgs += "--dry-run"
        }
        if ($SkipMatchDb -or (-not $RunDbt)) {
            $LoadArgs += "--skip-match"
        }
        if ($RunAlerts -and (-not $DryRun)) {
            $LoadArgs += "--run-alerts"
        }

        Write-Log "PHASE 2 (SINGLE NEON COPY): Loading $ArtifactPath into Neon ..."
        & $PythonExe @LoadArgs 2>&1 | ForEach-Object {
            $text = $_.ToString()
            Write-Output $text
            Add-Content -Path $LogFile -Value $text -Encoding UTF8
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "ERROR: Single-session load-and-transform failed with exit code $LASTEXITCODE."
            $FinalExit = $LASTEXITCODE
        } else {
            Write-Log "SUCCESS: Single-session COPY + dbt + TRUNCATE raw completed cleanly."
        }
    } else {
        Write-Log "No staged artifact produced; skipping Neon wake cleanly (0 CU)."
    }
} finally {
    if (Test-Path $StagingDir) {
        Remove-Item -Recurse -Force $StagingDir -ErrorAction SilentlyContinue
    }
    Pop-Location
}

Write-Log "======================================================================"
Write-Log "Local offline pipeline finished (exit=$FinalExit)"
Write-Log "======================================================================"
exit $FinalExit
