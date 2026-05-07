# Re-register yeehee-daemon Task Scheduler with wrapper .cmd that has
# log redirect + auto-restart loop. RUN AS ADMINISTRATOR.
#
# Why: 2026-05-07 found daemon dying silently under Task Scheduler at 18:12
# (yfinance corrupt data → process exit). Old task config ran python.exe
# directly with no stdout/stderr capture and no restart on crash.
#
# This script:
#   1. Stops existing yeehee-daemon (graceful)
#   2. Re-registers task to call scripts/start-daemon.cmd instead
#   3. start-daemon.cmd has stdout/stderr → logs/daemon-task-YYYYMMDD.log
#      and inifinite respawn loop
#   4. Starts the new task

$ErrorActionPreference = 'Stop'
$user = "$env:USERNAME"
$repo = "C:\Users\Administrator\yeehee-daemon"

# Stop existing daemon python processes (any leftover from prior crashed runs)
Get-CimInstance Win32_Process -Filter 'Name = "python.exe"' -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*daemon.main*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# Stop existing scheduled task
Stop-ScheduledTask -TaskName "yeehee-daemon" -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# Unregister to fully reset (preserves trigger inheritance). -Confirm:$false avoids prompt.
Unregister-ScheduledTask -TaskName "yeehee-daemon" -Confirm:$false -ErrorAction SilentlyContinue

# Re-register pointing to wrapper .cmd
$action    = New-ScheduledTaskAction -Execute "$repo\scripts\start-daemon.cmd"
$trigger   = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings  = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 30) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "yeehee-daemon" `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "yeehee daemon (signal_loop + mira + heartbeat + telegram_bot) via wrapper with log+respawn" `
    -Force | Out-Null

# Kick it off now
Start-ScheduledTask -TaskName "yeehee-daemon"
Start-Sleep -Seconds 8

Write-Host "=== yeehee-daemon re-registered with wrapper ==="
Get-ScheduledTask -TaskName "yeehee-daemon" | Select-Object TaskName, State | Format-Table -AutoSize
Write-Host "=== latest log ==="
$today = Get-Date -Format 'yyyyMMdd'
$logfile = "$repo\logs\daemon-task-$today.log"
if (Test-Path $logfile) {
    Get-Content $logfile -Tail 5
} else {
    Write-Host "(log file not yet written; check after 30s)"
}
