# test-vault-repo-lock.ps1 - isolation test suite for vault-repo-lock.ps1.
# Spec Step 3 / implementation plan Step 4, six-case matrix including reviewer
# note N1 (case f). Runs ONLY against throwaway lock paths under %TEMP%; never
# touches the live %LOCALAPPDATA%\vault-repo-lock path or the vault tree.
# Cleans up every artifact it creates. Windows PowerShell 5.1 syntax only.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$helperPath = 'C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\scripts\vault-repo-lock.ps1'
. $helperPath

$base     = Join-Path $env:TEMP ("hermes-p1-lock-tests-" + $PID)
$lockPath = Join-Path $base 'lock'
$fail     = 0

function Check([bool]$cond, [string]$label) {
    if ($cond) { Write-Output "PASS $label" } else { Write-Output "FAIL $label"; $script:fail++ }
}

function Reset-LockDir {
    if (Test-Path $lockPath) { Remove-Item -Path $lockPath -Recurse -Force }
}

function Write-Payload([int]$OwnerPid, [string]$Task, [datetime]$Started) {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $payload = [ordered]@{ pid = $OwnerPid; task = $Task; started = $Started.ToString('o') }
    [System.IO.File]::WriteAllText((Join-Path $lockPath 'owner.json'), ($payload | ConvertTo-Json), $utf8)
}

if (Test-Path $base) { Remove-Item -Path $base -Recurse -Force }
New-Item -ItemType Directory -Path $base | Out-Null

Write-Output "lock path: $lockPath"
Check ($lockPath.StartsWith($env:TEMP)) 'lock path starts with %TEMP%'

# ---- Case (a): five concurrent processes race one acquire ----------

Write-Output '--- case (a): 5-process race ---'
$goFile = Join-Path $base 'go.flag'
$childScript = Join-Path $base 'race-child.ps1'
$childBody = @'
param([string]$LockPath, [string]$GoFile, [string]$OutFile, [string]$HelperPath)
. $HelperPath
$deadline = (Get-Date).AddSeconds(15)
while (-not (Test-Path $GoFile)) {
    if ((Get-Date) -gt $deadline) { Set-Content -Path $OutFile -Value 'TIMEOUT'; exit 1 }
    Start-Sleep -Milliseconds 20
}
$r = Lock-VaultRepo -LockPath $LockPath -TaskName 'race'
if ($r.Acquired) {
    Set-Content -Path $OutFile -Value 'WIN'
    Start-Sleep -Seconds 5
    Unlock-VaultRepo -LockPath $LockPath | Out-Null
} else {
    Set-Content -Path $OutFile -Value ('LOSE holder=' + $r.HolderPid)
}
exit 0
'@
Set-Content -Path $childScript -Value $childBody -Encoding utf8

$procs = @()
for ($i = 1; $i -le 5; $i++) {
    $outFile = Join-Path $base ("race-out-$i.txt")
    $procArgs = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-File', $childScript, $lockPath, $goFile, $outFile, $helperPath)
    $procs += Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
        -ArgumentList $procArgs -WindowStyle Hidden -PassThru
}
Start-Sleep -Seconds 2   # let all five reach the go-file wait
New-Item -ItemType File -Path $goFile | Out-Null
foreach ($p in $procs) { $p.WaitForExit(30000) | Out-Null }

$results = @()
for ($i = 1; $i -le 5; $i++) {
    $results += (Get-Content (Join-Path $base ("race-out-$i.txt")) -Raw).Trim()
}
$wins   = @($results | Where-Object { $_ -eq 'WIN' })
$losses = @($results | Where-Object { $_ -like 'LOSE*' })
Write-Output ("race results: " + ($results -join ' | '))
Check ($wins.Count -eq 1) "exactly one winner (got $($wins.Count))"
Check ($losses.Count -eq 4) "exactly four losers (got $($losses.Count))"
Check (-not (Test-Path $lockPath)) 'winner released; no lock directory remains'
Reset-LockDir

# ---- Case (b): dead PID clears immediately -------------------------

Write-Output '--- case (b): dead PID clears on next acquire ---'
$deadProc = Start-Process -FilePath "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -ArgumentList @('-NoProfile', '-NonInteractive', '-Command', 'exit 0') -WindowStyle Hidden -PassThru
$deadPid = $deadProc.Id
$deadProc.WaitForExit(15000) | Out-Null
Check ($null -eq (Get-Process -Id $deadPid -ErrorAction SilentlyContinue)) "fixture pid $deadPid confirmed dead"
New-Item -ItemType Directory -Path $lockPath | Out-Null
Write-Payload -OwnerPid $deadPid -Task 'dead-fixture' -Started (Get-Date)
$rb = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-b'
Check ($rb.Acquired -eq $true) 'acquire over dead-PID lock succeeds immediately'
Check (@($rb.Messages | Where-Object { $_ -like '*Stale lock cleared*' }).Count -eq 1) 'stale-clear message emitted'
Unlock-VaultRepo -LockPath $lockPath | Out-Null
Check (-not (Test-Path $lockPath)) 'case (b) cleanup'

# ---- Case (c): live PID younger than ceiling is honored ------------

Write-Output '--- case (c): live PID inside ceiling held ---'
New-Item -ItemType Directory -Path $lockPath | Out-Null
Write-Payload -OwnerPid $PID -Task 'live-fixture' -Started (Get-Date)
$rc = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-c' -CeilingMinutes 2
Check ($rc.Acquired -eq $false) 'live young holder honored (held)'
Check ($rc.HolderPid -eq $PID) 'held result names the live holder pid'
Check ($rc.HolderTask -eq 'live-fixture') 'held result names the holder task'
Reset-LockDir

# ---- Case (d): live PID older than the test ceiling is taken over --

Write-Output '--- case (d): live PID past 2-minute test ceiling taken over ---'
New-Item -ItemType Directory -Path $lockPath | Out-Null
Write-Payload -OwnerPid $PID -Task 'live-old-fixture' -Started (Get-Date).AddMinutes(-3)
(Get-Item $lockPath).CreationTime = (Get-Date).AddMinutes(-3)
$rd = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-d' -CeilingMinutes 2
Check ($rd.Acquired -eq $true) 'ceiling takeover of live-but-old holder succeeds'
Check (@($rd.Messages | Where-Object { $_ -like '*CEILING TAKEOVER*' }).Count -eq 1) 'ceiling takeover message emitted'
Unlock-VaultRepo -LockPath $lockPath | Out-Null
Check (-not (Test-Path $lockPath)) 'case (d) cleanup'

# ---- Case (e): release by a non-owner refuses ----------------------

Write-Output '--- case (e): non-owner release refuses ---'
New-Item -ItemType Directory -Path $lockPath | Out-Null
Write-Payload -OwnerPid 4 -Task 'other-owner' -Started (Get-Date)   # pid 4 = System, never this test
$re = Unlock-VaultRepo -LockPath $lockPath
Check ($re.Released -eq $false) 'non-owner release refused'
Check ($re.Reason -like '*owned by pid 4*') 'refusal names the true owner'
Check (Test-Path $lockPath) 'lock directory untouched by refused release'
Reset-LockDir

# ---- Case (f): N1, owner.json absent and corrupt -------------------

Write-Output '--- case (f): N1 payload-missing and payload-corrupt ---'
# f1: absent payload, fresh directory: held
New-Item -ItemType Directory -Path $lockPath | Out-Null
$rf1 = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-f1' -CeilingMinutes 2
Check ($rf1.Acquired -eq $false) 'f1 absent payload, fresh: held (not treated as free, no throw)'
Reset-LockDir
# f2: absent payload, CreationTime older than ceiling: taken over
New-Item -ItemType Directory -Path $lockPath | Out-Null
(Get-Item $lockPath).CreationTime = (Get-Date).AddMinutes(-3)
$rf2 = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-f2' -CeilingMinutes 2
Check ($rf2.Acquired -eq $true) 'f2 absent payload, old CreationTime: taken over'
Check (@($rf2.Messages | Where-Object { $_ -like '*CEILING TAKEOVER*' }).Count -eq 1) 'f2 takeover message emitted'
Unlock-VaultRepo -LockPath $lockPath | Out-Null
# f3: corrupt payload, fresh directory: held
New-Item -ItemType Directory -Path $lockPath | Out-Null
Set-Content -Path (Join-Path $lockPath 'owner.json') -Value '{this is not json' -Encoding utf8
$rf3 = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-f3' -CeilingMinutes 2
Check ($rf3.Acquired -eq $false) 'f3 corrupt payload, fresh: held (no throw)'
Reset-LockDir
# f4: corrupt payload, CreationTime older than ceiling: taken over
New-Item -ItemType Directory -Path $lockPath | Out-Null
Set-Content -Path (Join-Path $lockPath 'owner.json') -Value '{this is not json' -Encoding utf8
(Get-Item $lockPath).CreationTime = (Get-Date).AddMinutes(-3)
$rf4 = Lock-VaultRepo -LockPath $lockPath -TaskName 'test-f4' -CeilingMinutes 2
Check ($rf4.Acquired -eq $true) 'f4 corrupt payload, old CreationTime: taken over'
Unlock-VaultRepo -LockPath $lockPath | Out-Null
Check (-not (Test-Path $lockPath)) 'case (f) cleanup'

# ---- Cleanup -------------------------------------------------------

Remove-Item -Path $base -Recurse -Force
Check (-not (Test-Path $base)) 'no test artifact remains in %TEMP%'

Write-Output "failures: $fail"
if ($fail -gt 0) { exit 1 } else { exit 0 }
