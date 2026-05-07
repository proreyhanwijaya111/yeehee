# yeehee persistence installer -- registers Task Scheduler at-logon tasks
# for daemon, FastAPI, recalibrator. Adds MT5 shortcut to shell:startup.
# Idempotent -- safe to run multiple times.
#
# Runs as current user (NOT admin). Tasks execute in user session context --
# RunLevel Limited. Sufficient for python services that bind localhost port.
# (Earlier draft used RunLevel Highest -> required admin -> UAC prompt cancel.)
#
# After install: reboot or logoff/login → all 3 services autostart + MT5
# launches → user only needs to attach EA once (or use attach_ea_mt5.py).

[CmdletBinding()]
param(
  [string]$Repo   = "$env:USERPROFILE\yeehee-daemon",
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$python = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv not found at $python" }

$tasks = @(
  @{
    name    = 'yeehee-fastapi'
    desc    = 'yeehee FastAPI execution_api on :8001 (EA polling endpoint)'
    args    = '-X utf8 -u -m uvicorn rcs.src.execution_api:app --host 0.0.0.0 --port 8001'
    workdir = $Repo
    delay   = $null
  },
  @{
    name    = 'yeehee-daemon'
    desc    = 'yeehee daemon (signal_loop + mira + heartbeat + telegram_bot)'
    args    = '-X utf8 -u -m daemon.main'
    workdir = $Repo
    delay   = '00:00:30'
  },
  @{
    name    = 'yeehee-recalibrator'
    desc    = 'yeehee gap recalibrator (data_cache/futures_premium_gap.txt)'
    args    = '-X utf8 -u scripts\recalibrate_gap.py'
    workdir = $Repo
    delay   = '00:00:45'
  },
  @{
    # Safety-net: if MT5 profile autosave fails to restore EA on logon,
    # this task re-attaches via pywinauto. --wait-seconds 90 lets MT5
    # (started by shell:startup shortcut) fully load chart before attempt.
    # Script also polls Supabase heartbeat after attach -- exit code 0 only
    # if heartbeat verified, exit 7 on timeout (alarm).
    name    = 'yeehee-mt5-attach'
    desc    = 'yeehee EA attach safety-net (re-attach DextradeEA if MT5 profile lost it)'
    args    = '-X utf8 -u scripts\attach_ea_mt5.py --wait-seconds 90'
    workdir = $Repo
  }
)

if ($Uninstall) {
  foreach ($t in $tasks) {
    if (Get-ScheduledTask -TaskName $t.name -ErrorAction SilentlyContinue) {
      Unregister-ScheduledTask -TaskName $t.name -Confirm:$false
      "uninstalled: $($t.name)"
    } else {
      "not installed: $($t.name)"
    }
  }
  $startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
  $mt5Shortcut = Join-Path $startup "MetaTrader 5.lnk"
  if (Test-Path $mt5Shortcut) { Remove-Item $mt5Shortcut; "removed MT5 startup shortcut" }
  return
}

# Install tasks
foreach ($t in $tasks) {
  $action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $t.args `
    -WorkingDirectory $t.workdir
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  # Note: AtLogOn delay handled at script-level via time.sleep() inside the
  # Python script if needed (yeehee-mt5-attach has its own ~90s wait built-in
  # via pywinauto retries). Avoid PS Add-Member fragility on Trigger.Delay.
  $settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365) `
    -StartWhenAvailable
  $principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

  if (Get-ScheduledTask -TaskName $t.name -ErrorAction SilentlyContinue) {
    Set-ScheduledTask -TaskName $t.name -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
    "updated: $($t.name)"
  } else {
    Register-ScheduledTask `
      -TaskName $t.name `
      -Description $t.desc `
      -Action $action `
      -Trigger $trigger `
      -Settings $settings `
      -Principal $principal `
      | Out-Null
    "installed: $($t.name)"
  }
}

# MT5 shell:startup shortcut
$mt5Path = "C:\Program Files\MetaTrader 5\terminal64.exe"
if (Test-Path $mt5Path) {
  $startup = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
  if (-not (Test-Path $startup)) { New-Item -Path $startup -ItemType Directory -Force | Out-Null }
  $lnkPath = Join-Path $startup "MetaTrader 5.lnk"
  $shell = New-Object -ComObject WScript.Shell
  $sc = $shell.CreateShortcut($lnkPath)
  $sc.TargetPath = $mt5Path
  $sc.WorkingDirectory = "C:\Program Files\MetaTrader 5"
  $sc.Description = "yeehee -- MT5 autostart"
  $sc.Save()
  "MT5 startup shortcut: $lnkPath"
} else {
  "MT5 not at expected path; skip shortcut"
}

"--- INSTALLED. Verify: Get-ScheduledTask | Where TaskName -like 'yeehee-*' ---"
Get-ScheduledTask | Where-Object { $_.TaskName -like 'yeehee-*' } | Select-Object TaskName, State | Format-Table -AutoSize
