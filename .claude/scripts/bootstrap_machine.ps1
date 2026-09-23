# Thin PowerShell wrapper for bootstrap_machine.py (Implementation Phase A4).
#
# Resolves Python the same way .claude/bin/py does, then forwards every
# argument unchanged. No logic lives here beyond interpreter resolution and
# forwarding: CON-004 keeps one interpreter order, not a fourth resolver.
#
# Resolution order, identical to .claude/bin/py lines 25 to 39 and to
# bootstrap_machine.py's resolve_python():
#   1. $env:VAULT_PYTHON, if set, an existing FILE, and executable
#   2. C:\Program Files\Python314\python.exe, if it exists
#   3. python3 on PATH
#   4. python on PATH
# Exits 127 with a one-line message when no interpreter resolves.
#
# The candidate-1 branch needs BOTH checks, not just the file check. In
# .claude/bin/py that pair is `[ -f ]` plus `[ -x ]`, added by a named
# adversarial-review fix: `-x` alone is true for a directory, and exec-ing a
# directory hard-crashes the resolver instead of falling through to the
# remaining candidates, which would take every hook routed through it down
# on one stale VAULT_PYTHON value. PowerShell has no -x, so the Windows
# equivalent is used: the path must be a Leaf (not a directory) AND carry an
# extension PATHEXT considers executable. This wrapper previously tested
# Test-Path alone, which reproduced -f and dropped -x.

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $scriptDir "bootstrap_machine.py"

function Test-ExecutableLeaf([string]$Path) {
    if (-not $Path) { return $false }
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    $ext = [System.IO.Path]::GetExtension($Path)
    if (-not $ext) { return $false }
    $pathext = ($env:PATHEXT -split ';') | Where-Object { $_ }
    return ($pathext -contains $ext)
}

$python = $null
if (Test-ExecutableLeaf $env:VAULT_PYTHON) {
    $python = $env:VAULT_PYTHON
} elseif (Test-Path -LiteralPath "C:\Program Files\Python314\python.exe" -PathType Leaf) {
    $python = "C:\Program Files\Python314\python.exe"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $python = "python3"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    Write-Error "bootstrap_machine.ps1: no Python interpreter found (checked VAULT_PYTHON, C:\Program Files\Python314\python.exe, python3, python)"
    exit 127
}

$env:PYTHONIOENCODING = "utf-8"
& $python $target @args
exit $LASTEXITCODE
