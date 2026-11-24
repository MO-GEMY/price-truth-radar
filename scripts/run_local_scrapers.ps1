<#
.SYNOPSIS
    Run local/residential Price Truth Radar scrapers, upsert snapshots to Neon,
    refresh DB-level cross-store canonical keys (`--match-db`), and optionally run dbt.

.DESCRIPTION
    Designed for Windows Task Scheduler or manual residential execution whenever
    a store blocks cloud/datacenter IPs (such as `2b` and `sigma`, plus optional
    geo-restricted fallback stores via `-IncludeFallback`).
    Logs full stdout/stderr to `logs/local_scraper_YYYY-MM-DD.log` and prunes
    logs older than 14 days automatically.

.EXAMPLE
    # Run default local residential stores (`2b`, `sigma`) in daily mode
    .\scripts\run_local_scrapers.ps1

.EXAMPLE
    # Run deep catalog discovery for `2b` and `sigma` from Egypt residential IP
    .\scripts\run_local_scrapers.ps1 -Discovery

.EXAMPLE
    # Run daily scrape + dbt run/test
    .\scripts\run_local_scrapers.ps1 -RunDbt

.EXAMPLE
    # Include fallback stores (`egyptlaptop`, `dubaiphone`, `elaraby`, `dalydress`)
    .\scripts\run_local_scrapers.ps1 -IncludeFallback

.EXAMPLE
    # Dry-run specific stores with a 15-product limit (no Neon writes)
    .\scripts\run_local_scrapers.ps1 -Stores 2b,sigma -Discovery -Limit 15 -DryRun
#>

[CmdletBinding()]
param(
    [string[]]$Stores = @(
        "2b", "sigma",
        "jumia", "carrefour_eg", "elghazawy", "fresh_eg",
        "homzmart", "ikea_eg", "oriental_weavers",
        "decathlon_eg", "pets_egypt",
        "misr_pharmacies", "tdawi", "el_ezaby", "chefaa", "seif_pharmacies",
        "faces_eg", "mazaya_eg",
        "adidas_eg", "lc_waikiki_eg", "defacto_eg",
        "elnekhely", "maximum_hardware", "gamesworldegypt", "mobilaty_eg",
        "hedeya"
    ),
    [switch]$IncludeFallback,
    [ValidateSet("daily", "discover", "discovery")]
    [string]$Mode = "daily",
    [switch]$Discovery,
    [int]$Limit = 0,
    [switch]$DryRun,
    [switch]$SkipMatchDb,
    [switch]$RunDbt,
    [int]$LogRetentionDays = 14
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

if ($Discovery) {
    $Mode = "discovery"
}

$FallbackStores = @("egyptlaptop", "dubaiphone", "elaraby", "dalydress")
$FashionOnlyStores = @("town_team", "dejavu", "dalydress", "activ", "carina", "khotwh", "concrete", "mobaco", "hedeya", "lc_waikiki_eg", "defacto_eg", "adidas_eg")
$GroceriesOnlyStores = @("spinneys", "hyperone", "seoudi", "abu_auf", "gourmet", "imtenan", "metro_market")

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunnerScript = Join-Path $RepoRoot "data_platform\ingestion\scrapers\run_scrapers.py"
$DbtRunnerScript = Join-Path $RepoRoot "data_platform\run_dbt.py"
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

    $fallbackWithPsycopg2 = $null
    foreach ($py in $candidates) {
        if (-not $py -or -not (Test-Path $py)) {
            continue
        }
        & $py -c "import psycopg2, curl_cffi, httpx, bs4" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            return $py
        }
        if (-not $fallbackWithPsycopg2) {
            & $py -c "import psycopg2" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                $fallbackWithPsycopg2 = $py
            }
        }
    }
    return $fallbackWithPsycopg2
}

function Resolve-Vertical {
    param([string]$StoreSlug)
    if ($FashionOnlyStores -contains $StoreSlug) {
        return "fashion"
    }
    if ($GroceriesOnlyStores -contains $StoreSlug) {
        return "groceries"
    }
    return "core"
}

$PythonExe = Resolve-PythonExe
if (-not $PythonExe) {
    Write-Log "ERROR: Could not find a working Python interpreter with psycopg2 (checked venv, D:\anaconda3\python.exe, PATH)."
    exit 1
}

if (-not (Test-Path $RunnerScript)) {
    Write-Log "ERROR: Scraper runner not found at $RunnerScript"
    exit 1
}

# Support comma-separated values passed as a single string (e.g. -Stores "2b,sigma")
$NormalizedStores = @()
$SeenStores = @{}
foreach ($entry in $Stores) {
    foreach ($part in ($entry -split ",")) {
        $trimmed = $part.Trim().ToLowerInvariant()
        if ($trimmed -and -not $SeenStores.ContainsKey($trimmed)) {
            $SeenStores[$trimmed] = $true
            $NormalizedStores += $trimmed
        }
    }
}

if ($IncludeFallback) {
    foreach ($fb in $FallbackStores) {
        if (-not $SeenStores.ContainsKey($fb)) {
            $SeenStores[$fb] = $true
            $NormalizedStores += $fb
        }
    }
}

if ($NormalizedStores.Count -eq 0) {
    Write-Log "ERROR: No stores specified."
    exit 1
}

Write-Log "======================================================================"
Write-Log "Price Truth Radar Local Scraper Runner"
Write-Log "RepoRoot        : $RepoRoot"
Write-Log "PythonExe       : $PythonExe"
Write-Log "Stores          : $($NormalizedStores -join ', ')"
Write-Log "IncludeFallback : $IncludeFallback"
Write-Log "Mode            : $Mode"
Write-Log "Limit           : $(if ($Limit -gt 0) { $Limit } else { 'store default' })"
Write-Log "DryRun          : $DryRun"
Write-Log "RunDbt          : $RunDbt"
Write-Log "LogFile         : $LogFile"
Write-Log "======================================================================"

Push-Location $RepoRoot
$FailedStores = @()
$SucceededStores = @()

try {
    foreach ($store in $NormalizedStores) {
        $vertical = Resolve-Vertical -StoreSlug $store
        $ArgsList = @($RunnerScript, "--store", $store, "--vertical", $vertical, "--mode", $Mode, "--delta")
        if ($Limit -gt 0) {
            $ArgsList += @("--limit", "$Limit")
        }
        if ($DryRun) {
            $ArgsList += "--dry-run"
        }

        Write-Log "Starting store='$store' (vertical=$vertical, mode=$Mode) ..."
        & $PythonExe @ArgsList 2>&1 | ForEach-Object {
            $text = $_.ToString()
            Write-Output $text
            Add-Content -Path $LogFile -Value $text -Encoding UTF8
        }
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            Write-Log "SUCCESS: store='$store' completed (exit=0)."
            $SucceededStores += $store
        } else {
            Write-Log "WARNING: store='$store' failed (exit=$code); continuing with remaining stores."
            $FailedStores += $store
        }
    }

    if (-not $DryRun -and -not $SkipMatchDb -and $SucceededStores.Count -gt 0) {
        Write-Log "Running DB-level cross-store canonical matching (--match-db) ..."
        & $PythonExe $RunnerScript --match-db 2>&1 | ForEach-Object {
            $text = $_.ToString()
            Write-Output $text
            Add-Content -Path $LogFile -Value $text -Encoding UTF8
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Log "WARNING: --match-db exited with code $LASTEXITCODE."
            $FailedStores += "match-db"
        } else {
            Write-Log "SUCCESS: --match-db completed."
        }
    } else {
        Write-Log "Skipping --match-db (DryRun=$DryRun, SkipMatchDb=$SkipMatchDb, Succeeded=$($SucceededStores.Count))."
    }

    if ($RunDbt -and -not $DryRun -and $SucceededStores.Count -gt 0) {
        if (-not (Test-Path $DbtRunnerScript)) {
            Write-Log "WARNING: dbt runner not found at $DbtRunnerScript; skipping dbt."
        } else {
            foreach ($dbtCmd in @("run", "test")) {
                Write-Log "Running dbt $dbtCmd ..."
                & $PythonExe $DbtRunnerScript $dbtCmd 2>&1 | ForEach-Object {
                    $text = $_.ToString()
                    Write-Output $text
                    Add-Content -Path $LogFile -Value $text -Encoding UTF8
                }
                if ($LASTEXITCODE -ne 0) {
                    Write-Log "WARNING: dbt $dbtCmd exited with code $LASTEXITCODE."
                    $FailedStores += "dbt-$dbtCmd"
                    break
                }
                Write-Log "SUCCESS: dbt $dbtCmd completed."
            }
        }
    }
} finally {
    Pop-Location
}

Write-Log "======================================================================"
Write-Log "Run complete | Succeeded: $($SucceededStores -join ', ') | Failed: $(if ($FailedStores.Count -gt 0) { $FailedStores -join ', ' } else { 'none' })"
Write-Log "======================================================================"

if ($FailedStores.Count -gt 0) {
    exit 1
}
exit 0
