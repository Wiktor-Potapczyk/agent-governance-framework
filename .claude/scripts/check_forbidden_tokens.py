#!/usr/bin/env python3
"""PreToolUse hook (matcher: Write|Edit) — block writes containing forbidden tokens.

Reads a forbidden-tokens config JSON and denies any Write/Edit whose content
contains a listed pattern. Config lookup order:

Note: the governance log block logs ONLY deny events. Allow events are
intentionally not logged (no log entry = implicit allow).
  1. Project-level:  <project_root>/.forbidden-tokens.json
     (derived from the file_path being written — walks up to Projects/<Name>/)
  2. Vault-wide fallback: <vault_root>/.claude/forbidden-tokens.json
     (same directory as this script's parent .claude/)

Config JSON schema:
  {
    "tokens": [
      {
        "pattern": "DO_NOT_COMMIT",
        "reason": "Commit-guard marker — remove before shipping",
        "case_sensitive": false   // optional, default false
      }
    ]
  }

If no config is found → allow silently.
"""

import json
import os
import sys
from datetime import datetime

# Force UTF-8 stdout on Windows — `reference_python_windows_encoding.md`
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Config discovery
# ---------------------------------------------------------------------------

def _find_vault_root(script_path: str) -> str:
    """Return the vault root by going up from this script's location.

    Script lives at: <vault>/.claude/scripts/check_forbidden_tokens.py
    Vault root is:   <vault>/
    """
    # scripts/ -> .claude/ -> vault/
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(script_path))))


def _find_project_config(file_path: str) -> str | None:
    """Walk up from file_path to find a .forbidden-tokens.json in a Projects/<Name>/ dir."""
    normalized = file_path.replace("\\", "/")
    # Locate the Projects/ segment.
    # Case-insensitive find on /projects/ is safe because Windows FS is case-insensitive;
    # path reconstruction uses original casing for display but filesystem lookups work either way.
    idx = normalized.lower().find("/projects/")
    if idx == -1:
        return None
    # Find the project root: up to and including the next path component
    remainder = normalized[idx + len("/projects/"):]
    project_name = remainder.split("/")[0]
    if not project_name:
        return None

    project_root = normalized[:idx + len("/projects/") + len(project_name)]
    candidate = project_root + "/.forbidden-tokens.json"
    # Convert back to OS path for filesystem access
    candidate_os = candidate.replace("/", os.sep)
    return candidate_os if os.path.isfile(candidate_os) else None


def _find_vault_config(script_path: str) -> str | None:
    """Return vault-wide config path if it exists."""
    vault_root = _find_vault_root(script_path)
    candidate = os.path.join(vault_root, ".claude", "forbidden-tokens.json")
    return candidate if os.path.isfile(candidate) else None


def load_config(file_path: str, script_path: str) -> list[dict] | None:
    """Return list of token dicts, or None if no config found."""
    config_path = _find_project_config(file_path) or _find_vault_config(script_path)
    if not config_path:
        return None
    try:
        with open(config_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        tokens = data.get("tokens", [])
        if not isinstance(tokens, list):
            return None
        return tokens
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# Token matching
# ---------------------------------------------------------------------------

def find_violations(content: str, tokens: list[dict]) -> list[dict]:
    """Return list of token entries that match content."""
    violations = []
    for entry in tokens:
        pattern = entry.get("pattern", "")
        if not pattern:
            continue
        case_sensitive = entry.get("case_sensitive", False)
        haystack = content if case_sensitive else content.lower()
        needle = pattern if case_sensitive else pattern.lower()
        if needle in haystack:
            violations.append(entry)
    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        print("{}")
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        print("{}")
        return

    # Valid JSON of the wrong shape is still unusable input. Matches the
    # unparseable-stdin branch above, including its empty-object stdout, so the
    # harness reads the same "nothing to say" answer either way.
    #
    # This file was MISSED by the 2026-09-11 house-wide pass, and the reason is
    # worth keeping: it is a registered PreToolUse hook that lives in
    # .claude/scripts/ rather than .claude/hooks/, and the check scoped itself to
    # the hooks directory. The pass was not house-wide until this landed.
    # See test_hooks_survive_malformed_payload.py.
    if not isinstance(payload, dict):
        print("{}")
        return

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    # Extract the content being written based on tool type
    if tool_name == "Write":
        content = tool_input.get("content", "")
        file_path = tool_input.get("file_path", "")
    elif tool_name == "Edit":
        # Only new_string is checked; existing file content is intentionally out of scope (hook blocks NEW introductions only).
        content = tool_input.get("new_string", "")
        file_path = tool_input.get("file_path", "")
    else:
        print("{}")
        return

    # Empty content / empty new_string passes silently — deletion cannot introduce forbidden tokens.
    if not content or not file_path:
        print("{}")
        return

    script_path = __file__
    tokens = load_config(file_path, script_path)
    if tokens is None:
        # No config found — allow
        print("{}")
        return

    violations = find_violations(content, tokens)
    if not violations:
        print("{}")
        return

    # Build human-readable summary
    summary_lines = []
    for v in violations:
        reason = v.get("reason", "no reason given")
        summary_lines.append(f"  • \"{v['pattern']}\" — {reason}")
    summary = "\n".join(summary_lines)

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"FORBIDDEN TOKEN: Write blocked — {len(violations)} forbidden token(s) found in content:\n"
                f"{summary}\n"
                f"Remove the token(s) before writing, or update .forbidden-tokens.json if this is intentional."
            ),
        }
    }
    print(json.dumps(result))

    # Governance log entry (best-effort, never crash)
    try:
        # This script lives under scripts/, so the shared writer in hooks/ is not
        # importable without putting that directory on the path first.
        hooks_dir = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks")
        )
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from _event_emit import emit_event
        transcript_path = payload.get("transcript_path", "")
        session_id = (
            os.path.splitext(os.path.basename(transcript_path))[0]
            if transcript_path else "unknown"
        )
        emit_event(
            event="deny",
            hook="check-forbidden-tokens",
            session=session_id,
            extra={
                "file": file_path,
                "violations": [v.get("pattern") for v in violations],
            },
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Self-test  (python check_forbidden_tokens.py --test)
# ---------------------------------------------------------------------------

def _run_self_tests():
    import io
    import contextlib

    SCRIPT = __file__

    # Locate vault-wide config for test (assume it exists next to this script's .claude parent)
    vault_root = _find_vault_root(SCRIPT)
    vault_config = os.path.join(vault_root, ".claude", "forbidden-tokens.json")

    print(f"Vault config path: {vault_config}")
    print(f"Config exists: {os.path.isfile(vault_config)}")
    print()

    # ---------- Test 1: content contains forbidden token (should DENY) ----------
    test1_payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {
            "file_path": os.path.join(vault_root, "Projects", "Test", "work", "test.md"),
            "content": "# Draft\n\nDO_NOT_COMMIT this value before review.",
        },
        "transcript_path": "/tmp/fake-session.jsonl",
    })

    old_stdin = sys.stdin
    sys.stdin = io.StringIO(test1_payload)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main()
    finally:
        sys.stdin = old_stdin
    result1 = buf.getvalue().strip()
    parsed1 = json.loads(result1) if result1 else {}
    decision1 = parsed1.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    status1 = "PASS" if decision1 == "deny" else "FAIL"
    print(f"Test 1 (forbidden token present) → {decision1.upper()} [{status1}]")
    if decision1 == "deny":
        print(f"  Reason: {parsed1['hookSpecificOutput']['permissionDecisionReason'][:120]}...")
    print()

    # ---------- Test 2: content is clean (should ALLOW) ----------
    test2_payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {
            "file_path": os.path.join(vault_root, "Projects", "Test", "work", "test.md"),
            "content": "# Clean file\n\nNo forbidden tokens here.",
        },
        "transcript_path": "/tmp/fake-session.jsonl",
    })

    sys.stdin = io.StringIO(test2_payload)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main()
    finally:
        sys.stdin = old_stdin
    result2 = buf.getvalue().strip()
    parsed2 = json.loads(result2) if result2 else {}
    decision2 = parsed2.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    status2 = "PASS" if decision2 == "allow" else "FAIL"
    print(f"Test 2 (no forbidden token)     → ALLOW [{status2}]")
    print()

    # ---------- Test 3: Edit with forbidden token in new_string ----------
    test3_payload = json.dumps({
        "tool_name": "Edit",
        "tool_input": {
            "file_path": os.path.join(vault_root, "Projects", "Test", "work", "test.md"),
            "old_string": "# Clean file",
            "new_string": "# TODO_FIXME_BLOCKER — must resolve",
        },
        "transcript_path": "/tmp/fake-session.jsonl",
    })

    sys.stdin = io.StringIO(test3_payload)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main()
    finally:
        sys.stdin = old_stdin
    result3 = buf.getvalue().strip()
    parsed3 = json.loads(result3) if result3 else {}
    decision3 = parsed3.get("hookSpecificOutput", {}).get("permissionDecision", "allow")
    status3 = "PASS" if decision3 == "deny" else "FAIL"
    print(f"Test 3 (Edit new_string blocked) → {decision3.upper()} [{status3}]")
    if decision3 == "deny":
        print(f"  Reason: {parsed3['hookSpecificOutput']['permissionDecisionReason'][:120]}...")

    all_pass = all(s == "PASS" for s in [status1, status2, status3])
    print()
    print(f"Overall: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] == "--test":
        _run_self_tests()
    else:
        main()
