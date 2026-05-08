@echo off
REM yeehee — start everything: MT5 + EA + 6 yeehee Task Scheduler tasks.
REM Idempotent: skips items already running. Double-click from Desktop.

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "Write-Host '=== yeehee — start all services ===' -ForegroundColor Cyan; ^
   $mt5_proc = Get-Process terminal64 -ErrorAction SilentlyContinue; ^
   if (-not $mt5_proc) { ^
     Write-Host '  [..] launching MT5 (terminal64.exe)' -ForegroundColor Yellow; ^
     Start-Process 'C:\Program Files\MetaTrader 5\terminal64.exe'; ^
     Start-Sleep -Seconds 5; ^
     Write-Host '  [OK] MT5 started' -ForegroundColor Green ^
   } else { ^
     Write-Host '  [OK] MT5 already running (PID' $mt5_proc.Id ')' -ForegroundColor Green ^
   }; ^
   Get-ScheduledTask -TaskName 'yeehee-*' | ForEach-Object { ^
     try { Start-ScheduledTask -TaskName $_.TaskName; Write-Host ('  [OK] ' + $_.TaskName) -ForegroundColor Green } ^
     catch { Write-Host ('  [FAIL] ' + $_.TaskName + ' :: ' + $_.Exception.Message) -ForegroundColor Red } ^
   }; ^
   Start-Sleep -Seconds 5; ^
   Write-Host ''; Write-Host '=== Status ===' -ForegroundColor Cyan; ^
   Get-ScheduledTask -TaskName 'yeehee-*' | Select-Object TaskName, State | Format-Table -AutoSize; ^
   Write-Host ''; ^
   $hb = Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue; ^
   if ($hb) { Write-Host '  FastAPI :8001 LISTEN' -ForegroundColor Green } else { Write-Host '  FastAPI :8001 NOT LISTENING' -ForegroundColor Red }; ^
   $w = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue; ^
   if ($w) { Write-Host '  Web :3000 LISTEN' -ForegroundColor Green } else { Write-Host '  Web :3000 NOT LISTENING' -ForegroundColor Red }; ^
   Write-Host ''; ^
   Write-Host 'Public URL: https://yeehee.clinix.id' -ForegroundColor Yellow; ^
   Write-Host 'Press any key to close...'; ^
   $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')"
