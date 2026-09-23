# Vault auto-commit: rolling 30-minute local snapshot. COMMIT-ONLY, never pushes.
# Registered as scheduled task "Vault Auto-Commit 30min" (user context, logged-on only).
# Design per Projects/Agent-Governance-Research/work/2026-08-11-self-committing-vault-research.md:
# a second short-interval task beside the 18:00 backup task (which keeps sole ownership of push).
# Log lives OUTSIDE the vault on purpose: a log inside would dirty the tree every run.
#
# Cross-task lock (added 2026-08-17, Hermes P1): dot-sources vault-repo-lock.ps1
# and acquires %LOCALAPPDATA%\vault-repo-lock before touching the index, so this
# task and Vault-BACKUP-daily can no longer race each other's git writes (the
# 2026-08-17 09:12 index.lock collision). On contention this script skips the
# cycle: its next fire is 30 minutes away. The git-native index.lock and
# MERGE_HEAD guards below stay unchanged; they cover live sessions, which do
# not take this lock. Design:
# Projects/Agent-Governance-Research/work/2026-08-17-hermes-p1-scheduled-run-safety-plan.md
#
# VaultPath parameter (added 2026-09-16, self-heal phase (a) TASK-004): defaults
# to the real vault path, so the registered scheduled task (which calls this
# script with no arguments) behaves exactly as before. A test harness can pass
# -VaultPath to point the whole script at a scratch repo.
#
# Commit-then-pull (added 2026-09-16, self-heal phase (a) TASK-004): after a
# successful local commit, fetches origin explicitly, then rebases onto the
# freshly fetched ref, so a fetch failure (network down, remote unreachable)
# is diagnosed separately from a genuine rebase conflict instead of both
# being reported as "rebase conflict" (fix pass item 4, adversarial review
# probe 4, "BREAKS on the unreachable-origin misdiagnosis"):
#   - fetch fails: FAIL-LOUD "origin unreachable during autosave pull", no
#     rebase is ever attempted.
#   - fetch succeeds, rebase fails, .git/rebase-merge or rebase-apply exists:
#     a genuine conflict. Conflicting paths are read BEFORE the abort (abort
#     restores the pre-rebase tree), then FAIL-LOUD "rebase conflict",
#     matching .github/actions/vault-commit/commit_and_push.sh line 85.
#   - fetch succeeds, rebase fails, no rebase directory exists: an
#     unclassified pull failure, FAIL-LOUD "autosave pull failed".
# Never force-pushes or retries. Add-HarnessAlertRow never appends a row
# that already exists verbatim (fix pass item 5a); a successful pull clears
# this script's own earlier FAIL-LOUD rows via Remove-HarnessAlertRowsByPrefix.
# Design: Projects/Vault-Maintenance/work/2026-09-16-self-healing-loop-spec.md
# section 3.5 / TASK-004; plan detail: Projects/Vault-Maintenance/work/backups/
# 2026-09-16-self-heal-phase-a-plan.md.

param(
    [string]$VaultPath = "C:\Users\WiktorPotapczyk\Desktop\Vault",
    [string]$LogPath = (Join-Path $env:LOCALAPPDATA "vault-auto-commit.log")
)

$vault = $VaultPath
$log = $LogPath

function Write-Log($msg) {
    Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg)
}

# Appends one bullet line to harness-alerts.md's "## Current alerts" section,
# creating the file (with a minimal, render_markdown-compatible shell) if it
# does not exist yet. A bare "None." placeholder is replaced, never kept
# alongside a real alert. Never appends a row that already exists verbatim
# (fix pass item 5a): repeated identical failures produce one row, not an
# unbounded pile. Known accepted race (spec RISK-002, mitigated but not
# fully closed by fix pass item 5b): scheduler_watchdog.py's own
# render_markdown rewrites this whole file on its next local run; it now
# preserves any foreign "- FAIL-LOUD:" row it did not itself generate, but a
# row written between that read and this script's next run can still race.
function Add-HarnessAlertRow {
    param(
        [Parameter(Mandatory = $true)][string]$VaultRoot,
        [Parameter(Mandatory = $true)][string]$AlertLine
    )
    $heading = "## Current alerts"
    $alertsPath = Join-Path $VaultRoot "Resources\Observability\harness-alerts.md"

    if (Test-Path $alertsPath) {
        $lines = @(Get-Content -Path $alertsPath -Encoding UTF8)
    } else {
        New-Item -ItemType Directory -Path (Split-Path $alertsPath -Parent) -Force | Out-Null
        $lines = @("# Harness Alerts", "", $heading, "", "None.", "")
    }

    $headingIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].TrimEnd() -eq $heading) { $headingIndex = $i; break }
    }

    if ($headingIndex -eq -1) {
        $lines += @("", $heading, "", $AlertLine, "")
    } else {
        $bodyStart = $headingIndex + 1
        $sectionEnd = $lines.Count
        for ($j = $bodyStart; $j -lt $lines.Count; $j++) {
            if ($lines[$j] -match '^##\s') { $sectionEnd = $j; break }
        }

        $before = @()
        if ($headingIndex -ge 0) { $before = @($lines[0..$headingIndex]) }
        $after = @()
        if ($sectionEnd -lt $lines.Count) { $after = @($lines[$sectionEnd..($lines.Count - 1)]) }

        $bulletLines = @()
        for ($k = $bodyStart; $k -lt $sectionEnd; $k++) {
            $t = $lines[$k].Trim()
            if ($t -eq "" -or $t -eq "None.") { continue }
            $bulletLines += $lines[$k]
        }
        if ($bulletLines -notcontains $AlertLine) {
            $bulletLines += $AlertLine
        }

        $newSection = @("") + $bulletLines + @("")
        $lines = $before + $newSection + $after
    }

    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($alertsPath, (($lines -join "`n") + "`n"), $utf8NoBom)
}

# Removes any existing bullet line under "## Current alerts" that starts
# with one of the given prefixes (fix pass item 5a): used to clear this
# script's OWN prior rebase/pull-failure rows once a later pull succeeds,
# so a stale alert does not outlive the condition that caused it. A file
# that does not exist, has no "## Current alerts" heading, or has no
# matching rows is a silent no-op.
function Remove-HarnessAlertRowsByPrefix {
    param(
        [Parameter(Mandatory = $true)][string]$VaultRoot,
        [Parameter(Mandatory = $true)][string[]]$Prefixes
    )
    $heading = "## Current alerts"
    $alertsPath = Join-Path $VaultRoot "Resources\Observability\harness-alerts.md"
    if (-not (Test-Path $alertsPath)) { return }
    $lines = @(Get-Content -Path $alertsPath -Encoding UTF8)

    $headingIndex = -1
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i].TrimEnd() -eq $heading) { $headingIndex = $i; break }
    }
    if ($headingIndex -eq -1) { return }

    $bodyStart = $headingIndex + 1
    $sectionEnd = $lines.Count
    for ($j = $bodyStart; $j -lt $lines.Count; $j++) {
        if ($lines[$j] -match '^##\s') { $sectionEnd = $j; break }
    }

    $before = @($lines[0..$headingIndex])
    $after = @()
    if ($sectionEnd -lt $lines.Count) { $after = @($lines[$sectionEnd..($lines.Count - 1)]) }

    $bulletLines = @()
    $removedAny = $false
    for ($k = $bodyStart; $k -lt $sectionEnd; $k++) {
        $t = $lines[$k].Trim()
        if ($t -eq "" -or $t -eq "None.") { continue }
        $matchesPrefix = $false
        foreach ($p in $Prefixes) {
            if ($t.StartsWith($p)) { $matchesPrefix = $true; break }
        }
        if ($matchesPrefix) { $removedAny = $true; continue }
        $bulletLines += $lines[$k]
    }
    if (-not $removedAny) { return }

    if ($bulletLines.Count -eq 0) { $bulletLines = @("None.") }
    $newSection = @("") + $bulletLines + @("")
    $lines = $before + $newSection + $after

    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($alertsPath, (($lines -join "`n") + "`n"), $utf8NoBom)
}

try {
    if (-not (Test-Path (Join-Path $vault ".git"))) { Write-Log "SKIP no .git"; exit 0 }

    # Cross-task lock. Helper missing: quiet skip (spec design decision 9).
    $lockHelper = Join-Path $vault ".claude\scripts\vault-repo-lock.ps1"
    if (-not (Test-Path $lockHelper)) { Write-Log "SKIP no lock helper"; exit 0 }
    . $lockHelper

    $lock = Lock-VaultRepo -TaskName 'auto-commit'
    foreach ($m in $lock.Messages) { Write-Log ("LOCK " + $m) }
    if (-not $lock.Acquired) {
        Write-Log ("SKIP lock held by {0} pid {1}" -f $lock.HolderTask, $lock.HolderPid)
        exit 0
    }
    try {
        # Another git process (live session mid-write) owns the index: skip this cycle.
        if (Test-Path (Join-Path $vault ".git\index.lock")) { Write-Log "SKIP index.lock"; exit 0 }
        if (Test-Path (Join-Path $vault ".git\MERGE_HEAD")) { Write-Log "SKIP merge in progress"; exit 0 }

        $branch = (& git -C $vault rev-parse --abbrev-ref HEAD 2>$null | Out-String).Trim()
        if ($branch -ne "main") { Write-Log "SKIP branch=$branch"; exit 0 }

        # Refresh the ~/.claude mirror before staging, so the memory folder and
        # user skills ride this snapshot (added 2026-09-09: ~/.claude is not a
        # git repo and has no other backup). FAIL-OPEN by design: a mirror
        # problem must never stop the vault's own autosave, so failures are
        # logged and the commit proceeds. The mirror script refuses
        # credential-bearing files itself; do not add a scrub step here.
        $mirror = Join-Path $vault ".claude\scripts\mirror_user_claude.py"
        if (Test-Path $mirror) {
            try {
                $out = & "C:\Program Files\Python314\python.exe" $mirror 2>&1 | Out-String
                $line = ($out -split "`n" | Where-Object { $_ -match '^MIRROR ' } | Select-Object -First 1)
                if ($line) { Write-Log ("MIRROR " + $line.Trim()) } else { Write-Log "MIRROR no summary line" }
                foreach ($r in ($out -split "`n" | Where-Object { $_ -match '^REFUSED ' })) { Write-Log $r.Trim() }
            } catch {
                Write-Log ("MIRROR ERROR " + $_.Exception.Message)
            }
        }

        # Refresh the committed plugin-cache snapshot before staging (TASK-033,
        # 2026-09-15-scheduled-jobs-off-laptop-plan.md), same pre-stage slot and
        # FAIL-OPEN contract as the mirror step above: a snapshot problem must
        # never stop the vault's own autosave.
        $pluginSnapshot = Join-Path $vault ".claude\scripts\snapshot_plugin_cache.py"
        if (Test-Path $pluginSnapshot) {
            try {
                $out = & "C:\Program Files\Python314\python.exe" $pluginSnapshot 2>&1 | Out-String
                $line = ($out -split "`n" | Where-Object { $_ -match '^SNAPSHOT ' } | Select-Object -First 1)
                if ($line) { Write-Log ("PLUGIN-SNAPSHOT " + $line.Trim()) } else { Write-Log "PLUGIN-SNAPSHOT no summary line" }
            } catch {
                Write-Log ("PLUGIN-SNAPSHOT ERROR " + $_.Exception.Message)
            }
        }

        # Refresh the daily self-heal experience export before staging (self-heal
        # phase (a) TASK-003/TASK-004), same pre-stage slot and FAIL-OPEN contract
        # as the two blocks above: an exporter problem must never stop the
        # vault's own autosave.
        $experienceExporter = Join-Path $vault ".claude\scripts\experience_export.py"
        if (Test-Path $experienceExporter) {
            try {
                $out = & "C:\Program Files\Python314\python.exe" $experienceExporter 2>&1 | Out-String
                $line = ($out -split "`n" | Where-Object { $_ -match '^EXPERIENCE ' } | Select-Object -First 1)
                if ($line) { Write-Log ("EXPERIENCE " + $line.Trim()) } else { Write-Log "EXPERIENCE no summary line" }
            } catch {
                Write-Log ("EXPERIENCE ERROR " + $_.Exception.Message)
            }
        }

        # git add -A's own exit code is checked (fix pass item 11): a
        # failure here (e.g. an index lock acquired during the ~8s
        # mirror/plugin/experience pre-stage window above) must skip the
        # commit rather than proceed on a possibly-incomplete stage. The
        # index.lock race window itself is NOT closed by this check --
        # only the single check performed before the pre-stage scripts run
        # covers that; a lock acquired mid-window still races, this just
        # stops it from silently committing a partial stage. Known,
        # disclosed, accepted gap (adversarial review probe 4, NEEDS
        # CHANGE, reasoned from code, not reproduced: timing-dependent).
        & git -C $vault add -A 2>$null | Out-Null
        $addExitCode = $LASTEXITCODE
        if ($addExitCode -ne 0) {
            Write-Log "SKIP git-add-failed exit=$addExitCode"
            exit 0
        }
        & git -C $vault diff --cached --quiet 2>$null
        if ($LASTEXITCODE -eq 0) { Write-Log "SKIP clean"; exit 0 }

        $stamp = Get-Date -Format "yyyy-MM-dd HH:mm"
        & git -C $vault commit -m "chore(autosave): rolling snapshot $stamp" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            $sha = (& git -C $vault rev-parse --short HEAD | Out-String).Trim()
            Write-Log "COMMIT $sha"

            # Commit-then-pull (TASK-004, revised fix pass item 4): keep the
            # laptop current with origin between cycles. Re-check the lock
            # file: a new one can appear in the window between the earlier
            # check and now. Fetch and rebase are two separate steps so a
            # fetch failure (network down, remote unreachable) is diagnosed
            # distinctly from a genuine rebase conflict.
            if (Test-Path (Join-Path $vault ".git\index.lock")) {
                Write-Log "SKIP-PULL index.lock"
            } else {
                & git -C $vault fetch origin $branch 2>$null | Out-Null
                $fetchExitCode = $LASTEXITCODE
                if ($fetchExitCode -ne 0) {
                    $alertLine = "- FAIL-LOUD: origin unreachable during autosave pull (git fetch exit $fetchExitCode); no rebase attempted"
                    Write-Log ("PULL-FETCH " + $alertLine)
                    try {
                        Add-HarnessAlertRow -VaultRoot $vault -AlertLine $alertLine
                    } catch {
                        Write-Log ("ALERT-WRITE ERROR " + $_.Exception.Message)
                    }
                } else {
                    & git -C $vault rebase --autostash "origin/$branch" 2>$null | Out-Null
                    $rebaseExitCode = $LASTEXITCODE
                    if ($rebaseExitCode -eq 0) {
                        Write-Log "PULL-REBASE ok"
                        try {
                            Remove-HarnessAlertRowsByPrefix -VaultRoot $vault -Prefixes @(
                                "- FAIL-LOUD: rebase conflict",
                                "- FAIL-LOUD: origin unreachable",
                                "- FAIL-LOUD: autosave pull failed"
                            )
                        } catch {
                            Write-Log ("ALERT-CLEAR ERROR " + $_.Exception.Message)
                        }
                    } else {
                        $rebaseDir = Join-Path $vault ".git\rebase-merge"
                        $rebaseApplyDir = Join-Path $vault ".git\rebase-apply"
                        $rebaseInProgress = (Test-Path $rebaseDir) -or (Test-Path $rebaseApplyDir)
                        if ($rebaseInProgress) {
                            # Conflicting paths must be read BEFORE the abort:
                            # `git rebase --abort` restores the pre-rebase
                            # working tree, so the unmerged (diff-filter=U)
                            # paths are gone once it runs. Matches
                            # commit_and_push.sh's own order (line 83-85).
                            $conflictPaths = @(& git -C $vault diff --name-only --diff-filter=U 2>$null)
                            & git -C $vault rebase --abort 2>$null | Out-Null
                            $conflicts = ($conflictPaths -join ", ")
                            if (-not $conflicts) { $conflicts = "(unknown)" }
                            $alertLine = "- FAIL-LOUD: rebase conflict against origin/$branch; aborted, no force-push, no retry. Conflicting path(s): $conflicts"
                        } else {
                            $alertLine = "- FAIL-LOUD: autosave pull failed (exit $rebaseExitCode) without a rebase in progress"
                        }
                        Write-Log ("PULL-REBASE " + $alertLine)
                        try {
                            Add-HarnessAlertRow -VaultRoot $vault -AlertLine $alertLine
                        } catch {
                            Write-Log ("ALERT-WRITE ERROR " + $_.Exception.Message)
                        }
                    }
                }
            }
        } else {
            Write-Log "FAIL commit exit=$LASTEXITCODE"
        }
    } finally {
        $release = Unlock-VaultRepo
        if (-not $release.Released) { Write-Log ("WARN lock release refused: " + $release.Reason) }
    }
} catch {
    Write-Log ("ERROR " + $_.Exception.Message)
}
exit 0
