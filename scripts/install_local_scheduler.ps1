<#
.SYNOPSIS
    Install or uninstall the non-admin user-level Windows Scheduled Task that runs
    local residential scrapers (`2b`, `sigma`) daily at 04:15 Cairo time.

.DESCRIPTION
    Idempotently registers a Limited (non-admin) Scheduled Task under the current
    Windows user account using `Register-ScheduledTask`. Automatically creates the
    `logs/` directory and prunes `logs/local_scraper*.log` files older than 14 days.
    Logs are written daily to `logs/local_scraper_YYYY-MM-DD.log`.

.EXAMPLE
    # Install / update the daily 04:15 Cairo time scheduled task (no admin required)
    .\scripts\install_local_scheduler.ps1

.EXAMPLE
    # Install with dbt refresh enabled after local scrape + match-db
    .\scripts\install_local_scheduler.ps1 -RunDbt

.EXAMPLE
    # Uninstall the scheduled task cleanly
    .\scripts\install_local_scheduler.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$TaskName = "PriceTruthRadar-LocalScrapers",
    [string]$Time = "04:15",
    [string[]]$Stores = @(),
    [ValidateSet("", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")]
    [string]$WeeklyDay = "",
    [switch]$IncludeFallback,
    [switch]$Discovery,
    [switch]$RunDbt,
    [int]$TimeoutHours = 3,
    [int]$LogRetentionDays = 14,
    [switch]$Uninstall
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RunnerPs1 = Join-Path $RepoRoot "scripts\run_local_scrapers.ps1"
$LogDir = Join-Path $RepoRoot "logs"

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Uninstalled Scheduled Task '$TaskName'."
    } else {
        Write-Output "Scheduled Task '$TaskName' is not installed (nothing to remove)."
    }
    exit 0
}

if (-not (Test-Path $RunnerPs1)) {
    throw "Local scraper script not found at: $RunnerPs1"
}

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Prune stale local scraper logs older than $LogRetentionDays days
$Cutoff = (Get-Date).AddDays(-[Math]::Abs($LogRetentionDays))
Get-ChildItem -Path $LogDir -Filter "local_scraper*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $Cutoff } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Parse trigger time (HH:mm in local Windows / Cairo time)
try {
    $TriggerAt = [DateTime]::ParseExact($Time, "HH:mm", [System.Globalization.CultureInfo]::InvariantCulture)
} catch {
    throw "Invalid -Time '$Time'. Expected 24-hour HH:mm format (e.g. '04:15')."
}

$StoreArg = ($Stores | ForEach-Object { $_.Trim() } | Where-Object { $_ }) -join ","
$ArgParts = @(
    "-NoProfile",
    "-WindowStyle", "Hidden",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$RunnerPs1`"",
    "-LogRetentionDays", "$LogRetentionDays"
)
if ($StoreArg) { $ArgParts += @("-Stores", "`"$StoreArg`"") }
if ($IncludeFallback) { $ArgParts += "-IncludeFallback" }
if ($Discovery) { $ArgParts += "-Discovery" }
if ($RunDbt) { $ArgParts += "-RunDbt" }

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ($ArgParts -join " ") `
    -WorkingDirectory $RepoRoot

if ($WeeklyDay) {
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeeklyDay -At $TriggerAt
    $ScheduleDesc = "Weekly ($WeeklyDay) at $Time local time"
} else {
    $Trigger = New-ScheduledTaskTrigger -Daily -At $TriggerAt
    $ScheduleDesc = "Daily at $Time local time"
}

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours $TimeoutHours) `
    -MultipleInstances IgnoreNew

$CurrentUser = if ($env:USERDOMAIN) { "$($env:USERDOMAIN)\$($env:USERNAME)" } else { $env:USERNAME }
$Principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

$StoresSummary = if ($StoreArg) { $StoreArg } else { "all 26 default local_only stores" }

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Asarak local residential scrapers ($StoresSummary) — $ScheduleDesc; logs to logs/local_scraper_YYYY-MM-DD.log ($LogRetentionDays-day retention)." `
    -Force | Out-Null

$Registered = Get-ScheduledTask -TaskName $TaskName
$TaskInfo = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Output "======================================================================"
Write-Output "Installed/Updated Scheduled Task (non-admin Limited user task)"
Write-Output "  TaskName   : $($Registered.TaskName)"
Write-Output "  User       : $CurrentUser"
Write-Output "  Schedule   : $ScheduleDesc"
Write-Output "  NextRun    : $($TaskInfo.NextRunTime)"
Write-Output "  Stores     : $StoresSummary"
Write-Output "  Logs       : $LogDir\local_scraper_YYYY-MM-DD.log ($LogRetentionDays-day retention)"
Write-Output "  Command    : powershell.exe $($ArgParts -join ' ')"
Write-Output "======================================================================"
