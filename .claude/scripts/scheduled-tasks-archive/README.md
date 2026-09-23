# Windows Task Scheduler recipes for the laptop-only jobs

Exported 2026-09-16 with `Export-ScheduledTask` (read-only) as part of the migration plan
[[2026-09-15-scheduled-jobs-off-laptop-plan]] (TASK-028). The `<UserId>` value was replaced
with a placeholder so the files carry no machine identity; the vault path inside each `<Arguments>`
element is this laptop's and must be edited for another machine.

Re-create one task on a fresh machine (elevated PowerShell, from the vault root):

    Register-ScheduledTask -TaskName 'Vault-BACKUP-daily' -Xml (Get-Content .claude\scripts\scheduled-tasks-archive\Vault-BACKUP-daily.xml -Raw) -User "$env:USERDOMAIN\$env:USERNAME"

Which of these still belong on a laptop after the migration: only `Vault-Auto-Commit-30min` and
`Vault-BACKUP-daily` (they act on this machine's own working tree) and the two observability jobs
that read the local, git-ignored `governance-log.jsonl` (collector, verifier). The lint sweep, lint
verifier and observability digest have GitHub Actions replacements under `.github/workflows/`;
their XML stays here as history only.
