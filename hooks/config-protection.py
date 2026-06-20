"""
config-protection.py: PreToolUse Write/Edit/MultiEdit guard (ECC-LEARN-A3)

Hard-blocks edits to vault load-bearing config files unless an explicit override
env var is set. Inspired by ECC's `config-protection.js`.

Protected paths (any path whose basename matches one of these, anywhere on disk):
  - .claude/settings.local.json    : agent allow/deny + hook chain registration
  - .claude/registry.json          : agent/skill registry catalog
  - MEMORY.md                      : root memory-index file

Override mechanism:
  - Set env var CONFIG_PROTECTION_ALLOW=1 in the parent shell to permit subsequent
    Write/Edit/MultiEdit to protected files.
  - The override is SESSION-SCOPED, not single-use. Once set, every subsequent write
    in that shell session is allowed until the user explicitly `unset`s the variable
    (or restarts the shell). The hook does not auto-clear it.
  - Rationale: an env override is more deliberate than a CLI flag (visible in shell
    history). It is NOT designed to be airtight against an adversarial agent; it is
    designed to keep a confused agent (or main session in a long context) from
    quietly clobbering a load-bearing file.

Case-sensitivity:
  - The basename comparison is case-INsensitive. On Windows (the production
    machine for this hook) the filesystem treats `settings.local.json` and
    `SETTINGS.LOCAL.JSON` as the same file; the hook must too.

Schema:
  - input: PreToolUse hook payload via stdin
      {"tool_name": "Write" | "Edit" | "MultiEdit", "tool_input": {"file_path": "..."}}
  - output (block): stdout JSON
      {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                              "permissionDecisionReason": "..."}}
  - output (pass): silent (no stdout)

Exit codes: 0 always. Hook never crashes the parent session: fail-open.

Logging: appends one line per deny to `.claude/hooks/governance-log.jsonl` with
schema=2, event="deny", hook="config-protection".
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import PurePath

PROTECTED_BASENAMES = frozenset({
    "settings.local.json",
    "registry.json",
    "MEMORY.md",
})

# Additional containment: for settings.local.json and registry.json, only block if the
# parent directory is '.claude' (so a project-specific 'settings.local.json' inside an
# unrelated tooling directory isn't accidentally protected). MEMORY.md has no parent
# constraint: any MEMORY.md anywhere is treated as the index.
PARENT_CONSTRAINED = {
    "settings.local.json": ".claude",
    "registry.json": ".claude",
}

OVERRIDE_ENV_VAR = "CONFIG_PROTECTION_ALLOW"


def _normalise_path(p: str) -> PurePath:
    """Build a PurePath that handles either forward or backslash separators."""
    return PurePath(p.replace("\\", "/"))


_PROTECTED_BASENAMES_LOWER = {b.lower() for b in PROTECTED_BASENAMES}
_PARENT_CONSTRAINED_LOWER = {k.lower(): v.lower() for k, v in PARENT_CONSTRAINED.items()}


def _is_protected(file_path: str) -> tuple[bool, str]:
    """
    Returns (is_protected, canonical_basename_or_empty).

    Match is case-INsensitive on basename and parent dir. On Windows (the production
    machine) NTFS treats `settings.local.json` and `SETTINGS.LOCAL.JSON` as the same
    file, so the hook does too. The canonical lowercase basename is returned so log
    entries and deny messages have a stable identifier regardless of input casing.

    settings.local.json and registry.json additionally require the parent dir name
    to be `.claude` (avoids blocking unrelated tooling files of the same name).
    MEMORY.md is protected anywhere: there is only ever one MEMORY index file.
    """
    if not file_path:
        return (False, "")
    path = _normalise_path(file_path)
    basename_lc = path.name.lower()
    if basename_lc not in _PROTECTED_BASENAMES_LOWER:
        return (False, "")
    parent_required_lc = _PARENT_CONSTRAINED_LOWER.get(basename_lc)
    if parent_required_lc is None:
        return (True, basename_lc)
    parent_name_lc = path.parent.name.lower()
    if parent_name_lc == parent_required_lc:
        return (True, basename_lc)
    return (False, "")


def _is_overridden() -> bool:
    """Override is active when CONFIG_PROTECTION_ALLOW is set to a truthy value."""
    val = os.environ.get(OVERRIDE_ENV_VAR, "").strip().lower()
    return val in ("1", "true", "yes", "on")


def _log_deny(basename: str, file_path: str, tool_name: str, payload: dict) -> None:
    """Append one deny record to governance-log.jsonl. Silent on I/O failure."""
    try:
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "governance-log.jsonl",
        )
        transcript_path = payload.get("transcript_path", "")
        session_id = (
            os.path.splitext(os.path.basename(transcript_path))[0]
            if transcript_path
            else "unknown"
        )
        entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schema": 2,
            "event": "deny",
            "hook": "config-protection",
            "session": session_id,
            "tool": tool_name,
            "basename": basename,
            "file_prefix": file_path[:120],
        })
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(entry + "\n")
    except Exception:
        pass


def _emit_deny(basename: str, file_path: str, tool_name: str) -> None:
    reason = (
        f"CONFIG PROTECTION: Blocked {tool_name} to '{basename}'. "
        f"This file is load-bearing for vault behavior. "
        f"To proceed, set the env var {OVERRIDE_ENV_VAR}=1 in the parent shell, "
        f"then re-run the action. The override is SESSION-SCOPED: it stays in effect "
        f"until you `unset {OVERRIDE_ENV_VAR}` or restart the shell. "
        f"Target was: {file_path}"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit", "MultiEdit"):
        return 0

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    file_path = tool_input.get("file_path") or ""
    if not isinstance(file_path, str):
        return 0

    is_prot, basename = _is_protected(file_path)
    if not is_prot:
        return 0

    if _is_overridden():
        # Override active: let it through (and log the override for observability)
        try:
            log_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "governance-log.jsonl",
            )
            transcript_path = payload.get("transcript_path", "")
            session_id = (
                os.path.splitext(os.path.basename(transcript_path))[0]
                if transcript_path
                else "unknown"
            )
            entry = json.dumps({
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "schema": 2,
                "event": "override",
                "hook": "config-protection",
                "session": session_id,
                "tool": tool_name,
                "basename": basename,
                "file_prefix": file_path[:120],
            })
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(entry + "\n")
        except Exception:
            pass
        return 0

    _emit_deny(basename, file_path, tool_name)
    _log_deny(basename, file_path, tool_name, payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
