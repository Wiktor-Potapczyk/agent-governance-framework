# One-time registration of the "Vault-WATCHDOG-hourly" scheduled task.
# Run manually (Claude's permission layer blocks task registration):
#   powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\scripts\register_scheduler_watchdog.ps1"
# Runs scheduler_watchdog.py hourly: enumerates every Vault* scheduled task,
# writes Resources/Observability/harness-alerts.md, appends one row to
# .claude/hooks/_state/scheduler-watchdog.jsonl. Read-only against the
# scheduler and the vault's artifacts; the only write outside those two
# files happens when --retry-backup is passed to scheduler_watchdog.py,
# which this registration does not pass.
#
# Idempotent: unregisters any prior "Vault-WATCHDOG-hourly" task before
# registering, matching register-auto-commit-task.ps1's shape (PAT-001).
#
# Principal and Settings provenance (2026-09-15): exported live via
# Export-ScheduledTask -TaskName 'Vault-MON-V2-1-observability-collector'
# (a task that has run reliably every day per the fleet evidence in the
# watchdog build plan). Copied verbatim from that export:
#   - Principal LogonType: InteractiveToken -> -LogonType Interactive
#     (RunLevel absent from the export, which means LeastPrivilege/Limited;
#     matched by omitting -RunLevel, whose default is Limited)
#   - Settings DisallowStartIfOnBatteries: true, StopIfGoingOnBatteries: true
#     in the export, DELIBERATELY NOT COPIED (2026-09-15, main session): a watchdog
#     that skips battery hours misses exactly the unplugged evenings when the
#     other tasks fail; the check is a few seconds of PowerShell and one git fetch.
#   - Settings IdleSettings Duration: PT10M, WaitTimeout: PT1H,
#     StopOnIdleEnd: true, RestartOnIdle: false (StopOnIdleEnd true and
#     RestartOnIdle false are also New-ScheduledTaskSettingsSet's own
#     defaults; IdleDuration/IdleWaitTimeout are set explicitly below to
#     match the export regardless)
#   - Settings WakeToRun: absent from the export XML, which means the
#     platform default of False (see reference_task_scheduler_waketorun_default_false);
#     set explicitly below (-WakeToRun:$false) so the value is not left
#     implicit.
# Not copied from the export (task-specific, not part of the four named
# fields): ExecutionTimeLimit, MultipleInstancesPolicy. This task gets its
# own values below, sized for a fleet check that includes a network fetch.

$scriptPath = "C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\scripts\scheduler_watchdog.py"
$pythonExe = "C:\Program Files\Python314\python.exe"
$taskName = "Vault-WATCHDOG-hourly"

Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

$action = New-ScheduledTaskAction -Execute "`"$pythonExe`"" `
    -Argument "`"$scriptPath`"" -WorkingDirectory "C:\Users\WiktorPotapczyk\Desktop\Vault"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Days 3650)

$principal = New-ScheduledTaskPrincipal -LogonType Interactive

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -IdleDuration (New-TimeSpan -Minutes 10) -IdleWaitTimeout (New-TimeSpan -Hours 1) `
    -WakeToRun:$false

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description "Hourly fleet health check for every Vault* scheduled task. Writes Resources/Observability/harness-alerts.md and appends .claude/hooks/_state/scheduler-watchdog.jsonl. Script: .claude/scripts/scheduler_watchdog.py. Registered per the 2026-09-15 watchdog-docs-stamp plan, TASK-008 approval." | Out-Null

"Registered. Next run: " + (Get-ScheduledTaskInfo -TaskName $taskName).NextRunTime
