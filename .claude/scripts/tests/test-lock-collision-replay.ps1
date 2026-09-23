# test-lock-collision-replay.ps1 - collision replay harness (spec Step 6 /
# implementation plan Step 7). Launches auto-commit.ps1 and
# vault-backup.ps1 -DryRun at the same instant, 10 rounds per batch, against
# the live repo. Reproduces the 2026-08-17 09:12 collision shape with the lock
# in place. The backup side is -DryRun (no commit, no push from that side);
# the auto-commit side may create real snapshot commits through its own normal
# path. Asserts: zero index.lock collision signatures in either log over the
# replay window, and at least one observed contention event (SKIP lock or a
# backup retry line). If a batch shows no contention it reruns up to 3 more
# batches before reporting an inconclusive failure. Exit 0 = pass.
# Windows PowerShell 5.1 syntax only.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$ps51       = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$vault      = 'C:\Users\WiktorPotapczyk\Desktop\Vault'
$autoCommit = Join-Path $vault '.claude\scripts\auto-commit.ps1'
$backup     = Join-Path $vault '.claude\scripts\vault-backup.ps1'
$backupLog  = Join-Path $vault '.claude\logs\vault-backup.log'
$acLog      = Join-Path $env:LOCALAPPDATA 'vault-auto-commit.log'
$lockDir    = Join-Path $env:LOCALAPPDATA 'vault-repo-lock'

$fail = 0
function Check([bool]$cond, [string]$label) {
    if ($cond) { Write-Output "PASS $label" } else { Write-Output "FAIL $label"; $script:fail++ }
}

function Get-NewLines([string]$Path, [int]$Baseline) {
    if (-not (Test-Path $Path)) { return @() }
    $all = @(Get-Content -Path $Path)
    if ($all.Count -le $Baseline) { return @() }
    return @($all | Select-Object -Skip $Baseline)
}

$acBase = 0
if (Test-Path $acLog) { $acBase = @(Get-Content $acLog).Count }
$buBase = 0
if (Test-Path $backupLog) { $buBase = @(Get-Content $backupLog).Count }

Write-Output ("replay window opens: " + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))

$contentionTotal = 0
$roundsRun = 0
$maxBatches = 4   # 1 primary + up to 3 reruns if no contention observed

for ($batch = 1; $batch -le $maxBatches; $batch++) {
    Write-Output "--- batch $batch (10 rounds) ---"
    for ($round = 1; $round -le 10; $round++) {
        $pA = Start-Process -FilePath $ps51 -ArgumentList @('-NoProfile', '-NonInteractive',
            '-ExecutionPolicy', 'Bypass', '-File', $autoCommit) -WindowStyle Hidden -PassThru
        $pB = Start-Process -FilePath $ps51 -ArgumentList @('-NoProfile', '-NonInteractive',
            '-ExecutionPolicy', 'Bypass', '-File', $backup, '-DryRun') -WindowStyle Hidden -PassThru
        $pA.WaitForExit(300000) | Out-Null
        $pB.WaitForExit(300000) | Out-Null
        $roundsRun++
        Write-Output ("round {0}.{1} done at {2} (auto-commit exit {3}, backup exit {4})" -f `
            $batch, $round, (Get-Date).ToString('HH:mm:ss'), $pA.ExitCode, $pB.ExitCode)
    }

    $acNew = Get-NewLines -Path $acLog -Baseline $acBase
    $buNew = Get-NewLines -Path $backupLog -Baseline $buBase
    $acContention = @($acNew | Where-Object { $_ -like '*SKIP lock held by*' })
    $buContention = @($buNew | Where-Object { ($_ -like '*Lock retry*') -or ($_ -like '*held by*') })
    $contentionTotal = $acContention.Count + $buContention.Count
    Write-Output ("contention events so far: {0} (auto-commit skips {1}, backup retries/holds {2})" -f `
        $contentionTotal, $acContention.Count, $buContention.Count)
    if ($contentionTotal -ge 1) { break }
    if ($batch -lt $maxBatches) { Write-Output 'no contention observed; rerunning another batch' }
}

$acNew = Get-NewLines -Path $acLog -Baseline $acBase
$buNew = Get-NewLines -Path $backupLog -Baseline $buBase

Write-Output '--- new auto-commit log lines over the window ---'
$acNew | ForEach-Object { Write-Output $_ }
Write-Output '--- new backup log lines over the window (contention/collision lines only) ---'
$buNew | Where-Object { ($_ -like '*lock*') -or ($_ -like '*Lock*') -or ($_ -like '*File exists*') } |
    ForEach-Object { Write-Output $_ }

$collisionAc = @($acNew | Where-Object { $_ -like "*index.lock': File exists*" })
$collisionBu = @($buNew | Where-Object { $_ -like "*index.lock': File exists*" })

Check ($roundsRun -ge 10) "at least 10 concurrent rounds completed (ran $roundsRun)"
Check ($collisionAc.Count -eq 0) 'zero collision signatures in auto-commit log'
Check ($collisionBu.Count -eq 0) 'zero collision signatures in backup log'
Check (-not (Test-Path $lockDir)) 'no lock directory remains after the harness'

if ($contentionTotal -ge 1) {
    Check $true "at least one observed contention event ($contentionTotal total)"
} else {
    Write-Output 'FAIL inconclusive: 4 batches produced zero observed contention events'
    $fail++
}

Write-Output "failures: $fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
