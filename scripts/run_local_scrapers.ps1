<#
.SYNOPSIS
    Run local/residential Price Truth Radar scrapers, upsert snapshots to Neon,
    and refresh DB-level cross-store canonical keys (`--match-db`).

.DESCRIPTION
    Designed for Windows Task Scheduler or manual residential execution whenever
    a store performs better from a local IP than from GitHub Actions runners.
    Logs full stdout/stderr to `logs/local_scrapers_<timestamp>.log`.

.EXAMPLE
    # Run default local store list (upserts to Neon + runs --match-db)
    .\scripts\run_local_scrapers.ps1

.EXAMPLE
    # Dry-run specific stores with a 30-product limit (no Neon writes)
    .\scripts\run_local_scrapers.ps1 -Stores sigma,noon -Limit 30 -DryRun

.EXAMPLE
    # Register a daily 05:30 AM Windows Task Scheduler job (run in PowerShell):
    schtasks /Create /TN "PriceTruthRadar-LocalScrapers" /SC DAILY /ST 05:30 /RL LIMITED /F ^
      /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"D:\price-truth-radar\scripts\run_local_scrapers.ps1\" -Stores sigma"
#>

[CmdletBinding()]
param(
    [string[]]$Stores = @("sigma"),
    [int]$Limit = 0,
    [switch]$DryRun,
    [switch]$SkipMatchDb
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

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

if (-not (Test-Path $PythonExe)) {
    Write-Log "ERROR: Virtualenv Python not found at $PythonExe"
    exit 1
}

if (-not (Test-Path $RunnerScript)) {
    Write-Log "ERROR: Scraper runner not found at $RunnerScript"
    exit 1
}

# Support comma-separated values passed as a single string (e.g. -Stores "sigma,noon")
$NormalizedStores = @()
foreach ($entry in $Stores) {
    foreach ($part in ($entry -split ",")) {
        $trimmed = $part.Trim()
        if ($trimmed) {
            $NormalizedStores += $trimmed
        }
    }
}

if ($NormalizedStores.Count -eq 0) {
    Write-Log "ERROR: No stores specified."
    exit 1
}

Write-Log "======================================================================"
Write-Log "Price Truth Radar Local Scraper Runner"
Write-Log "RepoRoot : $RepoRoot"
Write-Log "Stores   : $($NormalizedStores -join ', ')"
Write-Log "Limit    : $(if ($Limit -gt 0) { $Limit } else { 'store default' })"
Write-Log "DryRun   : $DryRun"
Write-Log "LogFile  : $LogFile"
Write-Log "======================================================================"

Push-Location $RepoRoot
$FailedStores = @()
$SucceededStores = @()

try {
    foreach ($store in $NormalizedStores) {
        $ArgsList = @($RunnerScript, "--store", $store)
        if ($Limit -gt 0) {
            $ArgsList += @("--limit", "$Limit")
        }
        if ($DryRun) {
            $ArgsList += "--dry-run"
        }

        Write-Log "Starting store='$store' ..."
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
