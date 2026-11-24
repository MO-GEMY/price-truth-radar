<#
.SYNOPSIS
    One-Day Manual High-Volume Catalog Expansion Runner for Asarak (أسعارك).

.DESCRIPTION
    Wrapper around `scripts/run_manual_1m_push.py` that resolves the repository
    Python environment and runs prioritized catalog expansion across high-demand
    Egyptian categories (Electronics/Appliances -> Fashion -> Groceries ->
    Beauty/Health -> Home -> Lifestyle), resuming cleanly from Neon's
    `raw.scraper_discovery_state` table with `--delta`, `--match-db`, and
    incremental `dbt run` milestones.

.EXAMPLE
    # Dry-run: live Neon stats + 950 MB storage headroom + 1M catalog feasibility report
    .\scripts\run_manual_1m_push.ps1 -DryRun

.EXAMPLE
    # High-demand push (Electronics, Fashion, Groceries) with 950 MB Neon guard & CU-hr savings
    .\scripts\run_manual_1m_push.ps1 -Categories "electronics_appliances,fashion,groceries" -Limit 1500 -MaxPages 15 -Workers 3 -MilestoneEvery 40 -MaxDbMb 950

.EXAMPLE
    # Full 200-store multi-wave push stopping safely before 950 MB (1 GB Neon plan)
    .\scripts\run_manual_1m_push.ps1 -Limit 2000 -MaxPages 20 -Workers 3 -Waves 2 -MilestoneEvery 40 -MaxDbMb 950
#>

[CmdletBinding()]
param(
    [switch]$DryRun,
    [int]$Limit = 1500,
    [int]$MaxPages = 15,
    [int]$Workers = 3,
    [int]$Waves = 1,
    [double]$Delay = 1.2,
    [int]$StoreTimeout = 240,
    [string]$Categories = "",
    [ValidateSet("all", "cloud", "local_only")]
    [string]$RegionMode = "all",
    [int]$MilestoneEvery = 40,
    [double]$MaxDbMb = 950,
    [switch]$SkipMatchDb,
    [switch]$SkipDbt,
    [switch]$SkipFinalTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ScriptPy = Join-Path $RepoRoot "scripts\run_manual_1m_push.py"
$VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python).Source }

$ArgsList = @(
    $ScriptPy,
    "--limit", "$Limit",
    "--max-pages", "$MaxPages",
    "--workers", "$Workers",
    "--waves", "$Waves",
    "--delay", "$Delay",
    "--store-timeout", "$StoreTimeout",
    "--region-mode", "$RegionMode",
    "--milestone-every", "$MilestoneEvery"
)

if ($DryRun) { $ArgsList += "--dry-run" }
if ($Categories) { $ArgsList += @("--categories", $Categories) }
$ArgsList += @("--max-db-mb", "$MaxDbMb")
if ($SkipMatchDb) { $ArgsList += "--skip-match-db" }
if ($SkipDbt) { $ArgsList += "--skip-dbt" }
if ($SkipFinalTest) { $ArgsList += "--skip-final-test" }

Push-Location $RepoRoot
try {
    & $PythonExe @ArgsList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
