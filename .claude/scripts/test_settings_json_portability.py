"""Portability test for .claude/settings.json (TASK-001, migration plan Phase 1).

CHECK (2026-09-15-scheduled-jobs-off-laptop-plan.md, TASK-001, revision 2026-09-15
evening): a parse of .claude/settings.json shows zero absolute
C:\\Users\\WiktorPotapczyk\\Desktop\\Vault vault-root-prefix substrings in any
`command` field. The interpreter-path token (C:\\Program Files\\Python314\\python.exe)
and the two shell-only hooks (bash, powershell) are explicitly NOT part of this
CHECK's pass condition per CON-005/GUD-002 -- they stay out of scope.

Read-only: parses the live settings.json, asserts on its command strings.
"""
import json
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = VAULT / ".claude" / "settings.json"

VAULT_ROOT_TOKENS = (
    r"C:\Users\WiktorPotapczyk\Desktop\Vault",
    "C:/Users/WiktorPotapczyk/Desktop/Vault",
)


def _iter_commands(settings: dict):
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command")
                if cmd is not None:
                    yield event, cmd


def test_settings_json_parses():
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    assert "hooks" in data


def test_nine_hook_commands_present():
    """Sanity: the population this CHECK covers is the 9 commands named in
    TASK-001 (CON-005's own count). A population change here would silently
    invalidate the CHECK below."""
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    commands = list(_iter_commands(data))
    assert len(commands) == 9, commands


def test_no_vault_root_prefix_token_in_any_command_field():
    """TASK-001's own CHECK, verbatim. A runtime Self-Modification permission
    guard denied the first two attempts to edit the 2 remaining forward-slash
    SessionStart commands (bash-invoked) in this session, after an earlier
    edit fixed the other 7 (backslash-form Python/PowerShell commands); a
    third attempt, in a later Edit call, went through. See the Phase 1 build
    record for the full account."""
    data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    offenders = [
        (event, cmd) for event, cmd in _iter_commands(data)
        if any(token in cmd for token in VAULT_ROOT_TOKENS)
    ]
    assert offenders == [], (
        f"{len(offenders)} command field(s) still carry the vault-root-prefix "
        f"token: {offenders}"
    )
