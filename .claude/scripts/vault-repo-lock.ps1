# vault-repo-lock.ps1 - shared cross-task lock for the vault git repository.
#
# Dot-sourced by auto-commit.ps1 and vault-backup.ps1, the two Windows Scheduled
# Tasks that write to the same git index. Design per
# Projects/Agent-Governance-Research/work/2026-08-17-hermes-p1-scheduled-run-safety-plan.md
# (design decisions 2 to 5) on the verdict of
# Projects/Agent-Governance-Research/work/2026-08-17-hermes-p1-lock-primitive-research.md.
#
# The lock is a DIRECTORY. New-Item -ItemType Directory is the atomic acquire.
# Never add -Force to that call: -Force succeeds on an existing directory and
# silently destroys atomicity. The holder writes owner.json (pid, task, started)
# inside the directory so a human debugging a stuck run can see who holds it
# with a plain "dir %LOCALAPPDATA%\vault-repo-lock".
#
# Staleness is the two-part rule reused from vault-backup.ps1's index.lock
# self-heal, applied to this lock:
#   1. Dead payload PID: stale regardless of age. Remove and re-acquire.
#   2. Live or unreadable PID: fall back to the age ceiling, default 60 minutes.
#      KEEP THIS DEFAULT EQUAL to $StaleLockAge in vault-backup.ps1 (line 41 of
#      that script); the two constants are cross-referenced by design decision 6.
# A lock directory whose owner.json is missing or unparseable is treated as an
# unreadable PID, and the ceiling runs against the directory's CreationTime
# (reviewer note N1). A bad payload never throws out of Lock-VaultRepo.
#
# Known accepted residual (reviewer note N2): Windows reuses PIDs, so a dead
# holder's recorded PID can belong to an unrelated live process. In that case
# takeover waits for the ceiling instead of firing on the dead-PID rule. The
# worst case is a delayed takeover, never a corrupted repo.
#
# Windows PowerShell 5.1 syntax only. No ??, no && chains, no ternary.

function Lock-VaultRepo {
    param(
        [string]$LockPath = (Join-Path $env:LOCALAPPDATA 'vault-repo-lock'),
        [Parameter(Mandatory = $true)][string]$TaskName,
        [int]$CeilingMinutes = 60   # keep equal to $StaleLockAge in vault-backup.ps1
    )

    $messages = @()

    for ($attempt = 1; $attempt -le 2; $attempt++) {

        # ---- Atomic acquire attempt --------------------------------
        $acquired = $false
        try {
            New-Item -ItemType Directory -Path $LockPath -ErrorAction Stop | Out-Null
            $acquired = $true
        }
        catch {
            $acquired = $false
        }

        if ($acquired) {
            # Write the owner payload. If this fails, back out rather than
            # hold the lock anonymously: an anonymous hold can only be cleared
            # by the ceiling, never by the dead-PID rule.
            try {
                $payload = [ordered]@{
                    pid     = $PID
                    task    = $TaskName
                    started = (Get-Date).ToString('o')
                }
                $utf8NoBom = New-Object System.Text.UTF8Encoding $false
                [System.IO.File]::WriteAllText(
                    (Join-Path $LockPath 'owner.json'),
                    ($payload | ConvertTo-Json),
                    $utf8NoBom)
                return [pscustomobject]@{
                    Acquired   = $true
                    LockPath   = $LockPath
                    HolderPid  = $PID
                    HolderTask = $TaskName
                    Messages   = $messages
                }
            }
            catch {
                $writeError = $_.Exception.Message
                try { Remove-Item -Path $LockPath -Recurse -Force -ErrorAction Stop } catch { }
                $messages += "Lock acquired but owner.json could not be written ($writeError); backed out."
                return [pscustomobject]@{
                    Acquired   = $false
                    LockPath   = $LockPath
                    HolderPid  = $null
                    HolderTask = 'payload-write-failed'
                    Messages   = $messages
                }
            }
        }

        # ---- Held by someone: read the payload defensively ---------
        if (-not (Test-Path -Path $LockPath)) {
            # Holder released between our failed acquire and now; retry.
            continue
        }

        $ownerPid     = $null
        $ownerTask    = 'unknown'
        $ownerStarted = $null
        try {
            $payloadRaw = [System.IO.File]::ReadAllText((Join-Path $LockPath 'owner.json'))
            $payloadObj = $payloadRaw | ConvertFrom-Json
            if ($payloadObj.PSObject.Properties['pid'])     { $ownerPid     = [int]$payloadObj.pid }
            if ($payloadObj.PSObject.Properties['task'])    { $ownerTask    = [string]$payloadObj.task }
            if ($payloadObj.PSObject.Properties['started']) { $ownerStarted = [string]$payloadObj.started }
        }
        catch {
            # Missing or unparseable owner.json: treat as unreadable PID
            # (reviewer note N1). Defaults above already say so.
        }

        if ($attempt -ge 2) {
            # We already cleared a stale lock once and lost the re-acquire
            # race to another process. Report held rather than fight.
            return [pscustomobject]@{
                Acquired   = $false
                LockPath   = $LockPath
                HolderPid  = $ownerPid
                HolderTask = $ownerTask
                Messages   = $messages
            }
        }

        # ---- Staleness rule part 1: dead PID means stale -----------
        if ($null -ne $ownerPid) {
            $ownerProc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
            if ($null -eq $ownerProc) {
                $messages += "Stale lock cleared: holder pid $ownerPid (task $ownerTask) is dead; removing and re-acquiring."
                try { Remove-Item -Path $LockPath -Recurse -Force -ErrorAction Stop } catch { }
                continue
            }
        }

        # ---- Staleness rule part 2: live or unreadable PID, ceiling -
        $ageBasis = $null
        if ($null -ne $ownerStarted) {
            try {
                $ageBasis = [datetime]::Parse(
                    $ownerStarted,
                    [System.Globalization.CultureInfo]::InvariantCulture,
                    [System.Globalization.DateTimeStyles]::RoundtripKind)
            }
            catch { }
        }
        if ($null -eq $ageBasis) {
            try { $ageBasis = (Get-Item -Path $LockPath -ErrorAction Stop).CreationTime } catch { }
        }
        if ($null -eq $ageBasis) {
            # Directory vanished mid-inspection; retry the acquire.
            continue
        }

        $ageMinutes = ((Get-Date) - $ageBasis).TotalMinutes
        if ($ageMinutes -ge $CeilingMinutes) {
            $messages += "CEILING TAKEOVER: lock held $([int]$ageMinutes) minute(s) (ceiling $CeilingMinutes) by pid $ownerPid task $ownerTask; removing and taking over."
            try { Remove-Item -Path $LockPath -Recurse -Force -ErrorAction Stop } catch { }
            continue
        }

        # Held legitimately: live (or unreadable) holder inside the ceiling.
        return [pscustomobject]@{
            Acquired   = $false
            LockPath   = $LockPath
            HolderPid  = $ownerPid
            HolderTask = $ownerTask
            Messages   = $messages
        }
    }

    # Both attempts failed without an early return (each takeover or vanish
    # path re-raced and lost). Report held with whatever is known.
    return [pscustomobject]@{
        Acquired   = $false
        LockPath   = $LockPath
        HolderPid  = $null
        HolderTask = 'unknown'
        Messages   = $messages
    }
}

function Unlock-VaultRepo {
    param(
        [string]$LockPath = (Join-Path $env:LOCALAPPDATA 'vault-repo-lock')
    )

    if (-not (Test-Path -Path $LockPath)) {
        return [pscustomobject]@{
            Released = $false
            Reason   = 'no lock directory on disk (nothing to release)'
        }
    }

    # PID-guarded release (design decision 4): only the recorded owner may
    # remove the directory. This stops a script whose lock was declared stale,
    # taken over, and re-payloaded by another process from removing that other
    # process's lock on its way out.
    $ownerPid = $null
    try {
        $payloadObj = [System.IO.File]::ReadAllText((Join-Path $LockPath 'owner.json')) | ConvertFrom-Json
        if ($payloadObj.PSObject.Properties['pid']) { $ownerPid = [int]$payloadObj.pid }
    }
    catch { }

    if ($null -eq $ownerPid) {
        return [pscustomobject]@{
            Released = $false
            Reason   = 'owner.json missing or unreadable; refusing to release a lock this process cannot prove it owns'
        }
    }
    if ($ownerPid -ne $PID) {
        return [pscustomobject]@{
            Released = $false
            Reason   = "lock is owned by pid $ownerPid, not this process (pid $PID); refusing"
        }
    }

    try {
        Remove-Item -Path $LockPath -Recurse -Force -ErrorAction Stop
        return [pscustomobject]@{ Released = $true; Reason = 'released' }
    }
    catch {
        return [pscustomobject]@{
            Released = $false
            Reason   = "removal failed: $($_.Exception.Message)"
        }
    }
}
