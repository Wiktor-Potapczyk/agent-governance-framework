# Ralph Loop Stop Hook - Windows PowerShell reimplementation
# Replaces bash stop-hook.sh which requires jq/cat/sed unavailable in hook context.
# Registered in .claude/settings.json as a Stop hook alongside the plugin's bash hook.
# The bash hook fails (non-blocking); this hook succeeds and blocks the session.

# Read hook input from stdin — try both $input (pipeline) and Console::In (redirect)
$stdinLines = @($input)
if ($stdinLines.Count -gt 0) {
    $stdinContent = $stdinLines -join "`n"
} else {
    $stdinContent = [System.Console]::In.ReadToEnd()
}

$hookInput = $null
if ($stdinContent -and $stdinContent.Trim()) {
    try { $hookInput = $stdinContent | ConvertFrom-Json } catch {}
}

# Helper: convert MSYS2/Git Bash Unix paths to Windows paths
function ConvertPath($p) {
    if (-not $p) { return $p }
    # /c/Users/... -> C:\Users\...
    if ($p -match '^/([a-zA-Z])/(.+)$') {
        return "$($Matches[1].ToUpper()):\$($Matches[2] -replace '/', '\')"
    }
    return $p
}

# Check if ralph-loop state file exists
$stateFile = Join-Path (Get-Location) ".claude\ralph-loop.local.md"
if (-not (Test-Path $stateFile)) { exit 0 }

# Read state file
$rawContent = Get-Content $stateFile -Raw -Encoding UTF8

# Parse YAML frontmatter (between --- markers)
$fm = [regex]::Match($rawContent, '(?s)^---\r?\n(.*?)\r?\n---\r?\n(.*)')
if (-not $fm.Success) { exit 0 }

$frontmatter = $fm.Groups[1].Value
$promptText  = $fm.Groups[2].Value.Trim()

# Helper: extract a YAML scalar field value
function Get-Field($yaml, $key) {
    $m = [regex]::Match($yaml, "(?m)^${key}:\s*(.+)$")
    if ($m.Success) { return $m.Groups[1].Value.Trim() }
    return ""
}

$iteration         = Get-Field $frontmatter "iteration"
$maxIterations     = Get-Field $frontmatter "max_iterations"
$completionPromise = Get-Field $frontmatter "completion_promise"
$stateSession      = Get-Field $frontmatter "session_id"

# Strip surrounding quotes from completion_promise
if ($completionPromise -match '^"(.*)"$') { $completionPromise = $Matches[1] }

# Session isolation: if state has a session_id and it differs from current, allow exit
$hookSession = if ($hookInput -and $hookInput.session_id) { $hookInput.session_id } else { "" }
if ($stateSession -and $stateSession -ne "" -and $hookSession -and $stateSession -ne $hookSession) {
    exit 0
}

# Validate numeric fields
if ($iteration -notmatch '^\d+$') {
    [Console]::Error.WriteLine("Ralph loop: State file corrupted - invalid iteration '$iteration'")
    Remove-Item $stateFile -ErrorAction SilentlyContinue
    exit 0
}
if ($maxIterations -notmatch '^\d+$') {
    [Console]::Error.WriteLine("Ralph loop: State file corrupted - invalid max_iterations '$maxIterations'")
    Remove-Item $stateFile -ErrorAction SilentlyContinue
    exit 0
}

$iter    = [int]$iteration
$maxIter = [int]$maxIterations

# Check max iterations
if ($maxIter -gt 0 -and $iter -ge $maxIter) {
    Write-Output "Ralph loop: Max iterations ($maxIter) reached."
    Remove-Item $stateFile -ErrorAction SilentlyContinue
    exit 0
}

# Get transcript path (convert Unix-style paths from hook input)
$transcriptPath = if ($hookInput -and $hookInput.transcript_path) {
    ConvertPath $hookInput.transcript_path
} else { "" }

if (-not $transcriptPath -or -not (Test-Path $transcriptPath)) {
    # Non-fatal: if transcript unavailable, still continue the loop
    # (can't check promise, so just feed prompt back)
    [Console]::Error.WriteLine("Ralph loop: Transcript not found at '$transcriptPath' - continuing loop without promise check")
    # Don't delete state file — just continue
    $transcriptPath = $null
}

# Read last assistant text block from JSONL transcript (only if transcript available)
$lastOutput = ""
if ($transcriptPath) {
    try {
        $lines = Get-Content $transcriptPath -Encoding UTF8
        $assistantLines = @($lines | Where-Object { $_ -match '"role":"assistant"' } | Select-Object -Last 100)
        foreach ($line in $assistantLines) {
            try {
                $obj = $line | ConvertFrom-Json
                if ($obj.message -and $obj.message.content) {
                    foreach ($block in $obj.message.content) {
                        if ($block.type -eq "text") { $lastOutput = $block.text }
                    }
                }
            } catch {}
        }
    } catch {
        [Console]::Error.WriteLine("Ralph loop: Failed to read transcript - $_")
    }
}

# Check for completion promise tag
if ($completionPromise -and $completionPromise -ne "null" -and $completionPromise -ne "") {
    if ($lastOutput -match '(?s)<promise>(.*?)<\/promise>') {
        $promiseText = ($Matches[1].Trim() -replace '\s+', ' ')
        if ($promiseText -eq $completionPromise) {
            Write-Output "Ralph loop: Detected <promise>$completionPromise</promise>"
            Remove-Item $stateFile -ErrorAction SilentlyContinue
            exit 0
        }
    }
}

# Validate prompt text exists
if (-not $promptText) {
    [Console]::Error.WriteLine("Ralph loop: No prompt text found in state file")
    Remove-Item $stateFile -ErrorAction SilentlyContinue
    exit 0
}

# Increment iteration counter in state file
$nextIteration = $iter + 1
$newContent = $rawContent -replace "(?m)^iteration: .*$", "iteration: $nextIteration"
[System.IO.File]::WriteAllText($stateFile, $newContent, (New-Object System.Text.UTF8Encoding $false))

# Build system message
if ($completionPromise -and $completionPromise -ne "null" -and $completionPromise -ne "") {
    $systemMsg = "Ralph iteration $nextIteration | To stop: output <promise>$completionPromise</promise> (ONLY when TRUE - do not lie to exit!)"
} else {
    $systemMsg = "Ralph iteration $nextIteration | No completion promise set - loop runs infinitely"
}

# Output block decision JSON to stdout
$result = [ordered]@{
    decision      = "block"
    reason        = $promptText
    systemMessage = $systemMsg
} | ConvertTo-Json -Compress

Write-Output $result
exit 0
