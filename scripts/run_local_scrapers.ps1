<#
.SYNOPSIS
    Run local/residential Price Truth Radar scrapers, upsert snapshots to Neon,
    and refresh DB-level cross-store canonical keys (`--match-db`).

.DESCRIPTION
    Designed for Windows Task Scheduler or manual residential execution whenever
    a store blocks cloud/datacenter IPs (such as `2b` and `sigma`, plus optional
    geo-restricted fallback stores via `-IncludeFallback`).
    Logs full stdout/stderr to `logs/local_scrapers_<timestamp>.log`.

.EXAMPLE
    # Run default local residential stores (`2b`, `sigma`) + upsert to Neon + `--match-db`
    .\scripts\run_local_scrapers.ps1

.EXAMPLE
    # Include fallback stores (`egyptlaptop`, `dubaiphone`, `elaraby`, `dalydress`) in one command
    .\scripts\run_local_scrapers.ps1 -IncludeFallback

.EXAMPLE
    # Dry-run specific stores with a 5-product limit (no Neon writes)
    .\scripts\run_local_scrapers.ps1 -Stores 2b,sigma,elaraby -Limit 5 -DryRun

.EXAMPLE
    # Register a daily 02:30 AM Cairo time Windows Task Scheduler job (run in PowerShell):
    schtasks /Create /TN "PriceTruthRadar-LocalScrapers" /SC DAILY /ST 02:30 /RL LIMITED /F ^
      /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"D:\price-truth-radar\scripts\run_local_scrapers.ps1\" -Mode daily"
#>

[CmdletBinding()]
param(
    [string[]]$Stores = @("2b", "sigma"),
    [switch]$IncludeFallback,
    [ValidateSet("daily", "discover")]
    [string]$Mode = "daily",
    [int]$Limit = 0,
    [switch]$DryRun,
    [switch]$SkipMatchDb
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$FallbackStores = @("egyptlaptop", "dubaiphone", "elaraby", "dalydress")
$FashionOnlyStores = @("town_team", "dejavu", "dalydress", "activ", "carina", "khotwh", "concrete", "mobaco")
$GroceriesOnlyStores = @("spinneys", "hyperone", "seoudi", "abu_auf", "gourmet", "imtenan", "metro_market")

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$PythonExe = Join-Path $RepoRoot "venv\Scripts\python.exe"
$RunnerScript = Join-Path $RepoRoot "data_platform\ingestion\scrapers\run_scrapers.py"
$LogDir = Join-Path $RepoRoot "logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "local_scrapers_$Timestamp.log"

function Write-Log {
    param([string]$Message)
    $Line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Output $Line
    Add-Content -Path $LogFile -Value $Line -Encoding UTF8
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

if (-not (Test-Path $PythonExe)) {
    Write-Log "ERROR: Virtualenv Python not found at $PythonExe"
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
Write-Log "Stores          : $($NormalizedStores -join ', ')"
Write-Log "IncludeFallback : $IncludeFallback"
Write-Log "Mode            : $Mode"
Write-Log "Limit           : $(if ($Limit -gt 0) { $Limit } else { 'store default' })"
Write-Log "DryRun          : $DryRun"
Write-Log "LogFile         : $LogFile"
Write-Log "======================================================================"

Push-Location $RepoRoot
$FailedStores = @()
$SucceededStores = @()

try {
    foreach ($store in $NormalizedStores) {
        $vertical = Resolve-Vertical -StoreSlug $store
        $ArgsList = @($RunnerScript, "--store", $store, "--vertical", $vertical, "--mode", $Mode)
        if ($Limit -gt 0) {
            $ArgsList += @("--limit", "$Limit")
        }
        if ($DryRun) {
            $ArgsList += "--dry-run"
        }

        Write-Log "Starting store='$store' (vertical=$vertical) ..."
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
