"""
Bash Safety Guard - PreToolUse Hook (matcher: Bash)
Blocks dangerous shell commands before execution.
Denies: rm -rf, force-push, credential exposure, destructive git ops.
"""

import sys
import json
import re


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

    # Check each pattern
    for pattern, description in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
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

    # Command is safe — allow silently
    return


if __name__ == "__main__":
    main()
