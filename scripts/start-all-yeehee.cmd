@echo off
REM yeehee — start all 6 services (web + tunnel + daemon + fastapi + mt5-attach + recalibrator).
REM Double-click this from Desktop shortcut. Idempotent: if a task is already
REM running, Start-ScheduledTask is a no-op.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Write-Host '=== Starting all yeehee services ===' -ForegroundColor Cyan; ^
   Get-ScheduledTask -TaskName 'yeehee-*' | ForEach-Object { ^
     try { Start-ScheduledTask -TaskName $_.TaskName; Write-Host ('  [OK] ' + $_.TaskName) -ForegroundColor Green } ^
     catch { Write-Host ('  [FAIL] ' + $_.TaskName + ' :: ' + $_.Exception.Message) -ForegroundColor Red } ^
   }; ^
   Start-Sleep -Seconds 4; ^
   Write-Host ''; Write-Host '=== Status ===' -ForegroundColor Cyan; ^
   Get-ScheduledTask -TaskName 'yeehee-*' | Select-Object TaskName, State | Format-Table -AutoSize; ^
   Write-Host ''; Write-Host 'Public URL: https://yeehee.clinix.id' -ForegroundColor Yellow; ^
   Write-Host 'Press any key to close...'; ^
   $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')"
