@echo off
REM yeehee-daemon wrapper for Task Scheduler.
REM
REM 2026-05-07: replaces direct python invocation in yeehee-daemon task.
REM Three reasons:
REM   1. Stdout/stderr capture: previous task ran python.exe directly with
REM      no log redirect — silent crashes were invisible.
REM   2. Auto-restart loop: if daemon Python process exits (crash, bug),
REM      this .cmd respawns it after a short delay. RestartCount on the
REM      Task Scheduler entry only fires when the TASK exits, not the
REM      child process. Loop here makes it self-healing.
REM   3. Log rotation: append-only to a daily-named file.
REM
REM Exit conditions:
REM   - User stops the scheduled task (Stop-ScheduledTask) — kills cmd + python
REM   - PC shutdown — kills both
REM   - Otherwise: daemon respawns indefinitely

set REPO=C:\Users\Administrator\yeehee-daemon
set PY=%REPO%\.venv\Scripts\python.exe
set LOGDIR=%REPO%\logs

cd /d "%REPO%"

:loop
REM Daily log filename: daemon-task-YYYYMMDD.log (rotates per day)
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value ^| find "="') do set DT=%%a
set TODAY=%DT:~0,8%
set LOGFILE=%LOGDIR%\daemon-task-%TODAY%.log

echo [%date% %time%] starting daemon.main >> "%LOGFILE%"
"%PY%" -X utf8 -u -m daemon.main >> "%LOGFILE%" 2>&1
echo [%date% %time%] daemon exited code=%ERRORLEVEL%, restarting in 30s >> "%LOGFILE%"

REM Brief sleep before respawn to avoid CPU spike on rapid crashes
ping -n 31 127.0.0.1 > nul

goto loop
