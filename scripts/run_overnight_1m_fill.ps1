<#
.SYNOPSIS
    Launch the Autonomous Overnight 1M Catalog Fill Runner for Asarak (أسعارك).

.DESCRIPTION
    Zero-DB offline HTTP scraping per category tier (keeping Neon suspended at 0 CU),
    single batched Neon flush per tier, stop at 890 MB pg_database_size (~950 MB Neon
    console) or <500 new SKUs/wave, Windows sleep prevention, and ONE final --match-db
    + incremental dbt run + dbt test at session end.

.EXAMPLE
    # Launch detached in the background (default overnight settings)
    .\scripts\run_overnight_1m_fill.ps1 -Detached

.EXAMPLE
    # Run in foreground
    .\scripts\run_overnight_1m_fill.ps1
#>

[CmdletBinding()]
param(
    [int]$Limit = 2500,
    [int]$MaxPages = 30,
    [int]$Workers = 4,
    [int]$MaxWaves = 10,
    [double]$MaxDbMb = 890,
    [int]$MinWaveNew = 500,
    [double]$Delay = 1.0,
    [int]$StoreTimeout = 210,
    [string]$Categories = "",
    [switch]$Detached,
    [switch]$SkipFinalPipeline
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ScriptPy = Join-Path $RepoRoot "scripts\run_overnight_1m_fill.py"
$VenvPython = Join-Path $RepoRoot "venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python).Source }

$ArgsList = @(
    "`"$ScriptPy`"",
    "--limit", "$Limit",
    "--max-pages", "$MaxPages",
    "--workers", "$Workers",
    "--max-waves", "$MaxWaves",
    "--max-db-mb", "$MaxDbMb",
    "--min-wave-new", "$MinWaveNew",
    "--delay", "$Delay",
    "--store-timeout", "$StoreTimeout"
)
if ($Categories) { $ArgsList += @("--categories", "`"$Categories`"") }
if ($SkipFinalPipeline) { $ArgsList += "--skip-final-pipeline" }

if ($Detached) {
    $LogDir = Join-Path $RepoRoot "logs"
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    $TaskName = "PriceTruthRadar-OvernightFill"
    $Action = New-ScheduledTaskAction `
        -Execute $PythonExe `
        -Argument ($ArgsList -join " ") `
        -WorkingDirectory $RepoRoot
    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 24) `
        -MultipleInstances IgnoreNew
    $CurrentUser = if ($env:USERDOMAIN) { "$($env:USERDOMAIN)\$($env:USERNAME)" } else { $env:USERNAME }
    $Principal = New-ScheduledTaskPrincipal `
        -UserId $CurrentUser `
        -LogonType Interactive `
        -RunLevel Limited
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Settings $Settings `
        -Principal $Principal `
        -Description "Asarak on-demand autonomous overnight 1M catalog fill (zero-DB offline scraping, 890 MB ceiling, no recurring trigger)." `
        -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "DETACHED_TASK=$TaskName"
    Write-Output "STARTED=True"
    exit 0
}

Push-Location $RepoRoot
try {
    & $PythonExe $ScriptPy `
        --limit $Limit `
        --max-pages $MaxPages `
        --workers $Workers `
        --max-waves $MaxWaves `
        --max-db-mb $MaxDbMb `
        --min-wave-new $MinWaveNew `
        --delay $Delay `
        --store-timeout $StoreTimeout `
        $(if ($Categories) { "--categories"; $Categories }) `
        $(if ($SkipFinalPipeline) { "--skip-final-pipeline" })
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
