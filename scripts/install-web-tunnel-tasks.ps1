# Install yeehee-web + yeehee-tunnel as Task Scheduler at-logon tasks.
# RUN THIS AS ADMINISTRATOR (right-click PowerShell → Run as Administrator).
# Idempotent: re-register over existing entries via -Force.

$ErrorActionPreference = 'Stop'
$user = "$env:USERNAME"

$webAction    = New-ScheduledTaskAction -Execute "C:\Users\Administrator\yeehee-daemon\scripts\start-web.cmd"
$tunnelAction = New-ScheduledTaskAction -Execute "C:\Users\Administrator\yeehee-daemon\scripts\start-tunnel.cmd"
$trigger      = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings     = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 30) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
$principal    = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName "yeehee-web"    -Action $webAction    -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Register-ScheduledTask -TaskName "yeehee-tunnel" -Action $tunnelAction -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Start-ScheduledTask -TaskName "yeehee-web"
Start-Sleep -Seconds 8
Start-ScheduledTask -TaskName "yeehee-tunnel"
Start-Sleep -Seconds 4

Write-Host "=== yeehee-* tasks ==="
Get-ScheduledTask -TaskName "yeehee-*" | Select-Object TaskName, State | Format-Table -AutoSize
