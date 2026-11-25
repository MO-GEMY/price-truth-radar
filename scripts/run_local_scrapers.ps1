<#
.SYNOPSIS
    Run all enabled local/residential (`region_mode: local_only`) Price Truth Radar scrapers,
    upsert snapshots to Neon, refresh DB-level cross-store canonical keys (`--match-db`),
    optionally run `dbt run` + `dbt test`, and perform zero-rest raw snapshot truncation.

.DESCRIPTION
    Designed for Windows Task Scheduler or manual Egypt-residential execution for all
    stores that block/geo-redirect cloud/datacenter IPs (`amazon_eg`, `egyptlaptop`,
    `dubaiphone`, `elaraby`, `spinneys`, `okhtein`, `azza_fahmy`, `2b`, `sigma`, etc.).

    When `-Stores` is omitted, targets are dynamically loaded from
    `data_platform/ingestion/stores_registry.yaml` (`enabled: true` & `region_mode: local_only`),
    including every configured `extra_verticals` (e.g., `amazon_eg` runs both `core` and
    `groceries`), keeping `stores_registry.yaml` as the single source of truth.
#>

[CmdletBinding()]
param(
    [string[]]$Stores = @(),
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
        & $py -c "import psycopg2, curl_cffi, httpx, bs4, yaml" 2>$null | Out-Null
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

$PythonExe = Resolve-PythonExe
if (-not $PythonExe) {
    Write-Log "ERROR: Could not find a working Python interpreter with psycopg2 (checked venv, D:\anaconda3\python.exe, PATH)."
    exit 1
}

if (-not (Test-Path $RunnerScript)) {
    Write-Log "ERROR: Scraper runner not found at $RunnerScript"
    exit 1
}

# Resolve (store_key, vertical) pairs dynamically from stores_registry.yaml
$ExplicitCsv = ""
if ($Stores -and $Stores.Count -gt 0) {
    $ExplicitCsv = ($Stores -join ",")
}
$IncludeFallbackFlag = if ($IncludeFallback) { "1" } else { "0" }

$TargetJson = & $PythonExe -c @"
import json, sys
from pathlib import Path
sys.path.insert(0, r'$RepoRoot')
from data_platform.ingestion.scrapers.registry_loader import load_stores_registry

explicit = [s.strip().lower() for s in '$ExplicitCsv'.split(',') if s.strip()]
all_entries = {e.store_key: e for e in load_stores_registry(enabled_only=True)}
targets = []
seen = set()

if explicit:
    for sk in explicit:
        e = all_entries.get(sk)
        verts = e.all_verticals if e else ('core',)
        for v in verts:
            if (sk, v) not in seen:
                seen.add((sk, v))
                targets.append({'store': sk, 'vertical': v})
else:
    for e in load_stores_registry(enabled_only=True, region_mode='local_only'):
        for v in e.all_verticals:
            if (e.store_key, v) not in seen:
                seen.add((e.store_key, v))
                targets.append({'store': e.store_key, 'vertical': v})

if '$IncludeFallbackFlag' == '1':
    for sk in ('egyptlaptop', 'dubaiphone', 'elaraby', 'dalydress'):
        e = all_entries.get(sk)
        verts = e.all_verticals if e else ('core',)
        for v in verts:
            if (sk, v) not in seen:
                seen.add((sk, v))
                targets.append({'store': sk, 'vertical': v})

print(json.dumps(targets))
"@

if ($LASTEXITCODE -ne 0 -or -not $TargetJson) {
    Write-Log "ERROR: Failed to resolve local_only targets from stores_registry.yaml."
    exit 1
}

$Targets = @($TargetJson | ConvertFrom-Json)
if ($Targets.Count -eq 0) {
    Write-Log "ERROR: No local_only stores resolved."
    exit 1
}

$TargetLabels = ($Targets | ForEach-Object { "$($_.store):$($_.vertical)" }) -join ", "

Write-Log "======================================================================"
Write-Log "Price Truth Radar Local Scraper Runner (Registry-Driven local_only)"
Write-Log "RepoRoot        : $RepoRoot"
Write-Log "PythonExe       : $PythonExe"
Write-Log "Targets ($($Targets.Count))    : $TargetLabels"
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
    foreach ($item in $Targets) {
        $store = $item.store
        $vertical = $item.vertical
        $label = "${store}:${vertical}"
        $ArgsList = @($RunnerScript, "--store", $store, "--vertical", $vertical, "--mode", $Mode, "--delta")
        if ($Limit -gt 0) {
            $ArgsList += @("--limit", "$Limit")
        }
        if ($DryRun) {
            $ArgsList += "--dry-run"
        }

        Write-Log "Starting target='$label' (mode=$Mode) ..."
        & $PythonExe @ArgsList 2>&1 | ForEach-Object {
            $text = $_.ToString()
            Write-Output $text
            Add-Content -Path $LogFile -Value $text -Encoding UTF8
        }
        $code = $LASTEXITCODE
        if ($code -eq 0) {
            Write-Log "SUCCESS: target='$label' completed (exit=0)."
            $SucceededStores += $label
        } else {
            Write-Log "WARNING: target='$label' failed (exit=$code); continuing with remaining targets."
            $FailedStores += $label
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
            $DbtOk = $true
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
                    $DbtOk = $false
                    break
                }
                Write-Log "SUCCESS: dbt $dbtCmd completed."
            }
            if ($DbtOk) {
                Write-Log "Running zero-rest raw snapshot cleanup (--truncate-raw) ..."
                & $PythonExe $RunnerScript --truncate-raw 2>&1 | ForEach-Object {
                    $text = $_.ToString()
                    Write-Output $text
                    Add-Content -Path $LogFile -Value $text -Encoding UTF8
                }
                if ($LASTEXITCODE -eq 0) {
                    Write-Log "SUCCESS: raw.raw_product_snapshots truncated after clean dbt run + test."
                }
            }
        }
    }
} finally {
    Pop-Location
}

Write-Log "======================================================================"
Write-Log "Run complete | Succeeded ($($SucceededStores.Count)): $($SucceededStores -join ', ') | Failed: $(if ($FailedStores.Count -gt 0) { $FailedStores -join ', ' } else { 'none' })"
Write-Log "======================================================================"

if ($FailedStores.Count -gt 0) {
    exit 1
}
exit 0
