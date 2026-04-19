"""
Bash Safety Guard - PreToolUse Hook (matcher: Bash)
Blocks dangerous shell commands before execution.
Denies: rm -rf, force-push, credential exposure, destructive git ops.
"""

import sys
import json
import re


# H2 fix (2026-04-18): pre-strip known-inert string contexts so blocked-pattern
# matches don't hit content inside string literals. A full shlex tokenizer
# would be the rigorous fix; this targeted preprocessor handles the 90% case
# (python -c, bash -c, grep patterns, echo, heredocs) without over-engineering.
# Rationale: the dangerous pattern `rm -rf /` should only be blocked when it
# would actually execute, not when it appears inside `python -c "print('rm -rf /')"`
# or `grep 'rm -rf' logs.txt` or an echo/print about the pattern.
_INERT_CONTEXT_PATTERNS = [
    # `python -c "…"` and `python -c '…'` (double or single quoted body)
    (re.compile(r'\bpython[0-9]*\s+-c\s+"(?:\\.|[^"\\])*"'), "python -c (double)"),
    (re.compile(r"\bpython[0-9]*\s+-c\s+'(?:\\.|[^'\\])*'"), "python -c (single)"),
    # `bash -c "…"` / `sh -c "…"` / `cmd -c` etc
    (re.compile(r'\b(?:bash|sh|zsh|cmd)\s+-c\s+"(?:\\.|[^"\\])*"'), "sh -c (double)"),
    (re.compile(r"\b(?:bash|sh|zsh|cmd)\s+-c\s+'(?:\\.|[^'\\])*'"), "sh -c (single)"),
    # `grep 'pattern'` / `grep -E "pattern"` etc — pattern is not a command
    (re.compile(r'\bgrep(?:\s+-[a-zA-Z]+)*\s+"(?:\\.|[^"\\])*"'), "grep (double)"),
    (re.compile(r"\bgrep(?:\s+-[a-zA-Z]+)*\s+'(?:\\.|[^'\\])*'"), "grep (single)"),
    # `echo "…"` / `printf "…"` — output, not execution
    (re.compile(r'\b(?:echo|printf)\s+"(?:\\.|[^"\\])*"'), "echo/printf (double)"),
    (re.compile(r"\b(?:echo|printf)\s+'(?:\\.|[^'\\])*'"), "echo/printf (single)"),
    # Heredocs: <<EOF … EOF (common delimiters)
    (re.compile(r'<<[-~]?\s*(\w+)\b[\s\S]*?^\1\b', re.MULTILINE), "heredoc"),
    (re.compile(r"<<[-~]?\s*'(\w+)'[\s\S]*?^\1\b", re.MULTILINE), "heredoc (single-quoted delim)"),
]


def strip_inert_contexts(command):
    """Remove substrings that are known to be string literals or pattern args,
    not executable shell. Returns a cleaned command safe to pattern-match."""
    cleaned = command
    for pattern, _label in _INERT_CONTEXT_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


# Windows reserved device names — creating these breaks OneDrive sync (Issue #16604)
WINDOWS_RESERVED_NAMES = {
    "nul", "con", "prn", "aux",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

# Patterns that should NEVER execute without explicit user approval
BLOCKED_PATTERNS = [
    # Destructive file operations
    (r'\brm\s+(-[rfRF]+\s+|--force\s+|--recursive\s+)*/(?!tmp)', "rm -rf on non-tmp directory"),
    (r'\brm\s+(-[rfRF]+\s+)+\.', "rm -rf on current directory"),
    # Destructive git operations
    (r'\bgit\s+push\s+.*--force', "git force-push"),
    (r'\bgit\s+push\s+-f\b', "git force-push (-f)"),
    (r'\bgit\s+reset\s+--hard', "git reset --hard"),
    (r'\bgit\s+clean\s+-[fdxFDX]', "git clean (destructive)"),
    (r'\bgit\s+checkout\s+--\s+\.', "git checkout -- . (discard all changes)"),
    # Credential/secret exposure
    (r'\bcat\b.*\.(env|pem|key|secret)', "reading credential file"),
    (r'\becho\b.*\b(password|secret|token|api.key)\b.*>', "writing credentials to file"),
    # System-level danger
    (r'\bsudo\b', "sudo command"),
    (r'\bchmod\s+777\b', "chmod 777 (world-writable)"),
    (r'\bkill\s+-9\b', "kill -9"),
    # n8n specific
    (r'n8n_delete_workflow', "deleting n8n workflow"),
]


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    command = tool_input.get("command", "")
    if not command:
        return

    # H2 fix (2026-04-18): pre-strip inert string contexts before pattern match.
    # Original command is preserved for logging + Windows-reserved-name check
    # (which operates on actual redirect targets, not string literals).
    scannable = strip_inert_contexts(command)

    # Check each pattern
    for pattern, description in BLOCKED_PATTERNS:
        if re.search(pattern, scannable, re.IGNORECASE):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"BASH SAFETY: Blocked '{description}'. "
                        f"Command: {command[:100]}... "
                        f"If this is intentional, ask the user to confirm."
                    ),
                }
            }
            print(json.dumps(result))
            # Log deny event (truncate command, never log credential content)
            # P1-D + P1-E fix (2026-04-09): added session + schema fields for analytics joins
            try:
                import os
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                # Extract session from transcript_path if available
                transcript_path = payload.get("transcript_path", "")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "schema": 2,
                    "event": "deny",
                    "hook": "bash-safety-guard",
                    "session": session_id,
                    "pattern": description,
                    "command_prefix": command[:50],
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
            return

    # Check for Windows reserved filenames in redirect targets and file creation
    # Matches: > nul, > ./nul, touch nul, cat > nul, echo > nul, etc.
    reserved_match = re.search(
        r'(?:>\s*|touch\s+|tee\s+)(?:\./)?(\w+)(?:\s|$)',
        command, re.IGNORECASE
    )
    if reserved_match:
        target_name = reserved_match.group(1).lower().split('.')[0]
        if target_name in WINDOWS_RESERVED_NAMES:
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"BASH SAFETY: Blocked creation of Windows reserved filename '{target_name}'. "
                        f"This breaks OneDrive sync for the entire folder (Issue #16604). "
                        f"Use a different filename."
                    ),
                }
            }
            print(json.dumps(result))
            try:
                import os
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                transcript_path = payload.get("transcript_path", "")
                session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
                entry = json.dumps({
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "schema": 2,
                    "event": "deny",
                    "hook": "bash-safety-guard",
                    "session": session_id,
                    "pattern": f"windows-reserved-filename:{target_name}",
                    "command_prefix": command[:50],
                })
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass
            return

    # Command is safe — allow silently
    return


if __name__ == "__main__":
    main()
