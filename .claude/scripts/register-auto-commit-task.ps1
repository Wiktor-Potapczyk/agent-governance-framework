# One-time registration of the "Vault Auto-Commit 30min" scheduled task.
# Run manually (Claude's permission layer blocks task registration):
#   powershell -NoProfile -ExecutionPolicy Bypass -File "C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\scripts\register-auto-commit-task.ps1"
# Commit-only snapshots every 30 minutes while logged on; never pushes.
# Note: RepetitionDuration must be finite on this Windows build; [TimeSpan]::MaxValue
# is rejected as out-of-range (verified 2026-08-12), hence the 10-year window.

$scriptPath = "C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\scripts\auto-commit.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$scriptPath`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
Register-ScheduledTask -TaskName "Vault Auto-Commit 30min" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Rolling 30-minute local snapshot of Desktop\Vault. Commit-only, never pushes. Script: .claude\scripts\auto-commit.ps1. Approved by Wiktor 2026-08-12." | Out-Null
"Registered. Next run: " + (Get-ScheduledTaskInfo -TaskName "Vault Auto-Commit 30min").NextRunTime
