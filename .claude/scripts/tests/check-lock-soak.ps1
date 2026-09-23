# check-lock-soak.ps1 - soak measurement script (spec Step 9 / implementation
# plan Step 11). Read-only: greps both task logs for the index.lock collision
# signature over a given window (expected count 0 after the lock shipped) and
# lists every real (DryRun=False) nightly backup outcome in the window, which
# must all be success or no-changes for the soak to pass. Also prints the
# current status file. Windows PowerShell 5.1 syntax only.
#
# Usage:
#   powershell -NonInteractive -File check-lock-soak.ps1 `
#       -WindowStart '2026-08-17 20:00' [-WindowEnd '2026-08-24 20:00']

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][datetime]$WindowStart,
    [datetime]$WindowEnd = (Get-Date)
)

$ErrorActionPreference = 'Stop'

$vault      = 'C:\Users\WiktorPotapczyk\Desktop\Vault'
$backupLog  = Join-Path $vault '.claude\logs\vault-backup.log'
$statusPath = Join-Path $vault '.claude\hooks\_state\vault-backup.json'
$acLog      = Join-Path $env:LOCALAPPDATA 'vault-auto-commit.log'

Write-Output ("soak window: {0} to {1}" -f $WindowStart.ToString('yyyy-MM-dd HH:mm:ss'), $WindowEnd.ToString('yyyy-MM-dd HH:mm:ss'))

function Get-WindowLines([string]$Path, [string]$StampPattern) {
    # Returns log lines whose leading timestamp falls inside the window.
    if (-not (Test-Path $Path)) { return @() }
    $out = @()
    foreach ($line in @(Get-Content -Path $Path)) {
        if ($line -match $StampPattern) {
            $stamp = $null
            try { $stamp = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', $null) } catch { }
            if ($null -ne $stamp) {
                if (($stamp -ge $WindowStart) -and ($stamp -le $WindowEnd)) { $out += $line }
            }
        }
    }
    return $out
}

# Backup log lines look like: [2026-08-17 09:12:06] [ERROR] message
$buLines = Get-WindowLines -Path $backupLog -StampPattern '^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]'
# Auto-commit log lines look like: 2026-08-17 09:12:09 COMMIT d8ae9bb
$acLines = Get-WindowLines -Path $acLog -StampPattern '^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) '

$signature = "index.lock': File exists"
$buCollisions = @($buLines | Where-Object { $_.Contains($signature) })
$acCollisions = @($acLines | Where-Object { $_.Contains($signature) })
$collisionCount = $buCollisions.Count + $acCollisions.Count

Write-Output ("collision signatures in backup log: {0}" -f $buCollisions.Count)
$buCollisions | ForEach-Object { Write-Output ("  " + $_) }
Write-Output ("collision signatures in auto-commit log: {0}" -f $acCollisions.Count)
$acCollisions | ForEach-Object { Write-Output ("  " + $_) }

# Real nightly outcomes: pair each DryRun=False start with its terminal line.
Write-Output '--- real (DryRun=False) backup runs in window ---'
$nightlyBad = 0
$pendingStart = $null
foreach ($line in $buLines) {
    if ($line -like '*=== vault-backup start (DryRun=False) ===*') {
        if ($null -ne $pendingStart) {
            Write-Output ("  {0} -> NO TERMINAL LINE FOUND" -f $pendingStart)
            $nightlyBad++
        }
        $pendingStart = $line
        continue
    }
    if ($null -eq $pendingStart) { continue }
    if ($line -like '*BACKUP FAILED*') {
        Write-Output ("  {0} -> FAILED" -f $pendingStart)
        $nightlyBad++
        $pendingStart = $null
    }
    elseif ($line -like '*Backup complete.*') {
        Write-Output ("  {0} -> success" -f $pendingStart)
        $pendingStart = $null
    }
    elseif ($line -like '*Backup already current.*') {
        Write-Output ("  {0} -> no-changes" -f $pendingStart)
        $pendingStart = $null
    }
}
if ($null -ne $pendingStart) {
    Write-Output ("  {0} -> STILL RUNNING OR NO TERMINAL LINE" -f $pendingStart)
}

# Lock activity in window (these are the lock working, not failures; the build
# record lists them with timestamps per spec Step 9 acceptance criteria).
Write-Output '--- lock events in window ---'
$acLines | Where-Object { ($_ -like '*SKIP lock*') -or ($_ -like '*LOCK *') } | ForEach-Object { Write-Output ("  " + $_) }
$buLines | Where-Object { ($_ -like '*Repo lock*') -or ($_ -like '*lock held*') } | ForEach-Object { Write-Output ("  " + $_) }

Write-Output '--- current status file ---'
if (Test-Path $statusPath) { Write-Output (Get-Content $statusPath -Raw) } else { Write-Output 'status file missing' }

if ($collisionCount -eq 0) {
    Write-Output 'RESULT: PASS (zero collision signatures in window)'
    if ($nightlyBad -gt 0) {
        Write-Output ("NOTE: {0} real backup run(s) in window did not end success/no-changes; soak streak criterion not met" -f $nightlyBad)
        exit 1
    }
    exit 0
} else {
    Write-Output ("RESULT: FAIL ({0} collision signature(s) in window)" -f $collisionCount)
    exit 1
}
