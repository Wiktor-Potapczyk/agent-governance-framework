# Delegation Check - Stop Hook
# Scans transcript for: classifier said delegate but no Agent tool was used.
# Block: JSON { "decision": "block" } on stdout.

# Read stdin payload
$jsonInput = ""
while ($line = [Console]::In.ReadLine()) { $jsonInput += $line }
if (-not $jsonInput) { exit 0 }

try { $payload = $jsonInput | ConvertFrom-Json } catch { exit 0 }

# Prevent infinite loop - if we already blocked and got re-triggered, allow
if ($payload.stop_hook_active -eq $true) { exit 0 }

$transcriptPath = $payload.transcript_path
if (-not $transcriptPath -or -not (Test-Path $transcriptPath)) { exit 0 }

# Read last ~50KB from transcript (fast .NET seek, no full-file scan)
$approachLine = ""
$agentUsed = $false
$classifierFound = $false

try {
    $fileInfo = [System.IO.FileInfo]$transcriptPath
    $readBytes = [Math]::Min(51200, $fileInfo.Length)
    $stream = [System.IO.FileStream]::new($transcriptPath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    $stream.Seek(-$readBytes, [System.IO.SeekOrigin]::End) | Out-Null
    $reader = New-Object System.IO.StreamReader($stream, [System.Text.Encoding]::UTF8)
    $tail = $reader.ReadToEnd()
    $reader.Close()
    $stream.Close()

    $lines = $tail -split "`n"

    foreach ($l in $lines) {
        if (-not $l.Trim()) { continue }
        try {
            $entry = $l | ConvertFrom-Json -ErrorAction SilentlyContinue
            if (-not $entry -or $entry.type -ne 'assistant') { continue }
            if (-not $entry.message -or -not $entry.message.content) { continue }

            foreach ($block in $entry.message.content) {
                if ($block.type -eq 'text' -and $block.text -match 'TASK TYPE:') {
                    $classifierFound = $true
                    $m = [regex]::Match($block.text, 'APPROACH:\s*(.+)')
                    if ($m.Success) { $approachLine = $m.Groups[1].Value.Trim() }
                    if ($block.text -match 'TASK TYPE:\s*Quick') { exit 0 }
                }
                if ($block.type -eq 'tool_use' -and $block.name -eq 'Agent') {
                    $agentUsed = $true
                }
            }
        } catch {}
    }
} catch { exit 0 }

if (-not $classifierFound) { exit 0 }
if (-not $approachLine) { exit 0 }

# Check if APPROACH names a delegation keyword
$keywords = @('delegate', 'dispatch', 'prompt-engineer', 'blueprint-mode',
    'architect-review', 'research-analyst', 'research-orchestrator', 'adversarial-reviewer',
    'debugger', 'content-marketer', 'data-engineer', 'implementation-plan',
    'technical-researcher', 'research-synthesizer', 'llm-architect', 'api-designer',
    'workflow-orchestrator', 'mcp-developer', 'powershell-7-expert', 'postgres-pro')
$shouldDelegate = $false
foreach ($kw in $keywords) {
    if ($approachLine -imatch [regex]::Escape($kw)) { $shouldDelegate = $true; break }
}

if (-not $shouldDelegate) { exit 0 }

if (-not $agentUsed) {
    $reason = "DELEGATION CHECK: APPROACH said delegate ($approachLine) but no Agent tool was used. Delegate now."
    $blockJson = @{ decision = "block"; reason = $reason } | ConvertTo-Json -Compress
    Write-Output $blockJson
}

exit 0
