<#
.SYNOPSIS
    Price Truth Radar — Unified Catalog Growth & Delta Price-Refresh Orchestrator.

.DESCRIPTION
    Supports two explicit operating modes with an automatic Neon storage hard guardrail (default 380 MB / 512 MB cap):

      -Mode refresh : Daily delta-only price & stock refresh across enabled stores (`--mode daily --delta`).
                      Skips unchanged rows without inserting duplicate snapshots, records real price/stock
                      changes, skips disabled/empty batches cleanly, and rebuilds + tests dbt marts.

      -Mode expand  : Controlled catalog expansion (`--mode discover --delta`) with configurable `-Limit`
                      and automatic Neon DB size check before starting and after every batch/store
                      (hard stops immediately at `-MaxDbSizeMb`, default 380 MB), then runs dbt.

.EXAMPLE
    # Daily delta-only price refresh across all active stores + dbt run & test:
    .\run_all_batches.ps1 -Mode refresh -IncludeLocal

.EXAMPLE
    # Controlled catalog expansion wave with 380 MB hard storage guardrail:
    .\run_all_batches.ps1 -Mode expand -Limit 1000 -MaxDbSizeMb 380
#>

[CmdletBinding()]
param(
    [ValidateSet("refresh", "expand")]
    [string]$Mode = "refresh",

    [string[]]$Batches = @(),

    [string[]]$Stores = @(),

    [int]$Limit = 0,

    [double]$MaxDbSizeMb = 380.0,

    [switch]$IncludeLocal,

    [switch]$MatchDb,

    [switch]$SkipDbt,

    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot "venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

$GuardScript = Join-Path $RepoRoot "data_platform\ingestion\scrapers\db_size_guard.py"
$RunnerScript = Join-Path $RepoRoot "data_platform\ingestion\scrapers\run_scrapers.py"
$DbtScript = Join-Path $RepoRoot "data_platform\run_dbt.py"

$LogDir = Join-Path $RepoRoot "logs"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "pipeline_${Mode}_${Timestamp}.log"

function Write-Log {
    param([string]$Message, [string]$Color = "Gray")
    $line = "[$(Get-Date -Format 'HH:mm:ss')] $Message"
    Write-Host $line -ForegroundColor $Color
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Test-NeonStorageGuardrail {
    param([string]$StageLabel)
    $rawOut = & $PythonExe $GuardScript --check-size --max-mb $MaxDbSizeMb 2>&1
    $exitCode = $LASTEXITCODE
    $sizeMb = ($rawOut | Select-Object -First 1).ToString().Trim()
    if ($exitCode -eq 42) {
        Write-Log "STORAGE GUARDRAIL REACHED ($StageLabel): Neon DB = $sizeMb MB >= $MaxDbSizeMb MB cap (512 MB limit). Stopping safely." "Yellow"
        return $false
    }
    if ($exitCode -ne 0) {
        Write-Log "Warning: Could not read Neon DB size ($StageLabel): $rawOut" "Yellow"
        return $true
    }
    Write-Log "Neon DB size ($StageLabel): $sizeMb MB / 512 MB (hard stop = $MaxDbSizeMb MB)" "Cyan"
    return $true
}

$ScrapeMode = if ($Mode -eq "expand") { "discover" } else { "daily" }

Write-Log "========================================================================" "Cyan"
Write-Log "PRICE TRUTH RADAR PIPELINE | Mode=$Mode (scrape_mode=$ScrapeMode) | MaxDbSizeMb=$MaxDbSizeMb | DryRun=$DryRun" "Cyan"
Write-Log "Log file: $LogFile" "DarkGray"
Write-Log "========================================================================" "Cyan"

# Initial Neon DB size check BEFORE any scraping
if (-not (Test-NeonStorageGuardrail -StageLabel "start")) {
    Write-Log "Aborting scrape wave before starting because Neon storage guardrail is already reached." "Yellow"
    exit 0
}

# Aggregated counters across all units
$TotalScraped = 0
$TotalNew = 0
$TotalChanged = 0
$TotalSkippedUnchanged = 0
$UnitsCompleted = 0
$UnitsSkipped = 0
$UnitsFailed = 0
$StoppedByGuardrail = $false

function Invoke-ScrapeUnit {
    param(
        [string]$Label,
        [string[]]$ScraperArgs
    )
    Write-Log "--- Running $Label ---" "White"
    $output = & $PythonExe $RunnerScript @ScraperArgs 2>&1
    $exitCode = $LASTEXITCODE

    foreach ($line in $output) {
        $text = $line.ToString()
        Add-Content -Path $LogFile -Value $text -Encoding UTF8
        if ($text -match "^BATCH_SKIPPED \|") {
            Write-Log "  $text" "Yellow"
            $script:UnitsSkipped++
        }
        elseif ($text -match "^DELTA_SUMMARY \| total_scraped=(\d+) \| new=(\d+) \| changed=(\d+) \| skipped_unchanged=(\d+) \| savings_pct=([0-9.]+)%") {
            $s = [int]$Matches[1]
            $n = [int]$Matches[2]
            $c = [int]$Matches[3]
            $u = [int]$Matches[4]
            $pct = $Matches[5]
            $script:TotalScraped += $s
            $script:TotalNew += $n
            $script:TotalChanged += $c
            $script:TotalSkippedUnchanged += $u
            Write-Log "  DELTA | scraped=$s | new=$n | changed=$c | unchanged_skipped=$u | saved=${pct}%" "Green"
        }
        elseif ($text -match "^DELTA SNAPSHOT PREVIEW \|") {
            Write-Log "  $text" "Green"
        }
        elseif ($text -match "^Upserted \d+ live rows") {
            Write-Log "  $text" "DarkGreen"
        }
    }

    if ($exitCode -ne 0) {
        Write-Log "  WARNING: $Label exited with code $exitCode (continuing remaining units)." "Yellow"
        $script:UnitsFailed++
    } else {
        $script:UnitsCompleted++
    }
}

# Resolve target units: either explicit -Stores OR batches (explicit -Batches or dynamic active batches)
if ($Stores.Count -gt 0) {
    foreach ($store in $Stores) {
        $storeClean = $store.Trim().ToLower()
        if (-not $storeClean) { continue }
        $vertical = (& $PythonExe $GuardScript --resolve-store $storeClean).ToString().Trim()
        if (-not $vertical) { $vertical = "core" }

        $unitArgs = @("--store", $storeClean, "--vertical", $vertical, "--mode", $ScrapeMode, "--delta")
        if ($Limit -gt 0) { $unitArgs += @("--limit", "$Limit") }
        if ($DryRun) { $unitArgs += "--dry-run" }

        Invoke-ScrapeUnit -Label "store=$storeClean (vertical=$vertical)" -ScraperArgs $unitArgs

        if (-not $DryRun) {
            if (-not (Test-NeonStorageGuardrail -StageLabel "after store=$storeClean")) {
                $StoppedByGuardrail = $true
                break
            }
        }
    }
} else {
    $TargetBatches = $Batches
    if ($TargetBatches.Count -eq 0) {
        $listArgs = @("--list-batches")
        if ($IncludeLocal) { $listArgs += "--include-local" }
        $TargetBatches = & $PythonExe $GuardScript @listArgs | Where-Object { $_.Trim() -ne "" }
    }

    Write-Log "Active batches queued ($($TargetBatches.Count)): $($TargetBatches -join ', ')" "Cyan"

    foreach ($batch in $TargetBatches) {
        $batchClean = $batch.Trim()
        if (-not $batchClean) { continue }

        $unitArgs = @("--batch", $batchClean, "--mode", $ScrapeMode, "--delta")
        if ($Limit -gt 0) { $unitArgs += @("--limit", "$Limit") }
        if ($DryRun) { $unitArgs += "--dry-run" }

        Invoke-ScrapeUnit -Label "batch=$batchClean" -ScraperArgs $unitArgs

        if (-not $DryRun) {
            if (-not (Test-NeonStorageGuardrail -StageLabel "after batch=$batchClean")) {
                $StoppedByGuardrail = $true
                break
            }
        }
    }
}

$SavingsPct = if ($TotalScraped -gt 0) { [math]::Round(($TotalSkippedUnchanged / $TotalScraped) * 100.0, 1) } else { 0.0 }
Write-Log "========================================================================" "Cyan"
Write-Log "INGESTION COMPLETE | mode=$Mode | completed=$UnitsCompleted | skipped=$UnitsSkipped | warnings=$UnitsFailed | guardrail_stop=$StoppedByGuardrail" "Cyan"
Write-Log "DELTA TOTALS       | scraped=$TotalScraped | new=$TotalNew | price_or_stock_changed=$TotalChanged | unchanged_skipped=$TotalSkippedUnchanged (storage_saved=${SavingsPct}%)" "Green"
Write-Log "========================================================================" "Cyan"

if ($DryRun) {
    Write-Log "Dry-run enabled; skipping --match-db and dbt run/test." "Yellow"
    exit 0
}

if ($MatchDb) {
    if (Test-NeonStorageGuardrail -StageLabel "pre-match-db") {
        Write-Log "--- Running cross-store matching (--match-db) ---" "White"
        & $PythonExe $RunnerScript --match-db 2>&1 | Tee-Object -FilePath $LogFile -Append | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "WARNING: --match-db exited with code $LASTEXITCODE" "Yellow"
        }
    }
}

if (-not $SkipDbt) {
    Write-Log "--- Running dbt run ---" "White"
    & $PythonExe $DbtScript run 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: dbt run failed with exit code $LASTEXITCODE" "Red"
        exit $LASTEXITCODE
    }

    Write-Log "--- Running dbt test ---" "White"
    & $PythonExe $DbtScript test 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: dbt test failed with exit code $LASTEXITCODE" "Red"
        exit $LASTEXITCODE
    }
}

$FinalSummary = & $PythonExe $GuardScript --summary
Write-Log "FINAL NEON SUMMARY: $FinalSummary" "Cyan"
exit 0
