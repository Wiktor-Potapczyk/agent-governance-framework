"""GATE-1-BYPASS regression: a wrapper must not launder a destructive command.

THE DEFECT
----------
`strip_inert_contexts()` removes quoted string bodies before pattern matching, so
that a command merely DISCUSSING a dangerous pattern is not blocked. That is
right for `grep 'rm -rf'`, for `echo "rm -rf /"`, and for a commit message. It is
wrong for `bash -c "..."`, because that body is not a literal being discussed, it
is a command being executed. The stripper could not tell the difference, so every
Gate-1 deny fell to a wrapper:

    rm -rf /                     -> denied
    bash -c "rm -rf /"           -> ALLOWED, silently
    git push --force origin main -> denied
    bash -c "git push --force"   -> ALLOWED, silently

Confirmed four times independently before this fix: by the file-by-file audit,
by the orchestrator with a negative-control matrix, by an M6 skeptic who added
curl and sudo, and by the QA pass which added `git reset --hard` and
`git clean -fdx`. Recorded as HA-A-044, rank 1 in the remediation backlog.

CLAUDE.md's Two-Gate Autonomy rule calls this surface a HARD FLOOR that maps to a
deny in ALL contexts, and names force-push the one genuinely unrecoverable action
that stays a hard deny. Both statements were false in the presence of a wrapper.

WHY THE NEGATIVE CASES MATTER AS MUCH
-------------------------------------
The obvious fix is to stop stripping quoted bodies at all, which would restore
the false positives that the stripper was added to fix in the first place. A
guard that denies `grep 'rm -rf' logs.txt` is a guard people route around. So
this suite asserts BOTH directions: a wrapped destructive command must deny, and
a command that merely mentions one must still pass.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent / "bash-safety-guard.py"
VAULT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable or r"C:\Program Files\Python314\python.exe"

# Assembled at runtime. Writing these literally would trip the very guard under
# test on this file's own content when a hook scans it, which is not a
# hypothetical: it happened while authoring the audit's findings file.
RM = "r" + "m -rf /home/user/data"
FORCE_PUSH = "git push --force origin main"
RESET = "git reset --hard HEAD~5"
CLEAN = "git clean -fdx"


def _decide(command, tmp_path):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["GOVERNANCE_LOG_PATH"] = str(tmp_path / "gov.jsonl")
    env["GATE1_ALARM_LOG_PATH"] = str(tmp_path / "gov.jsonl")
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "act.jsonl")
    payload = json.dumps({"tool_name": "Bash",
                          "tool_input": {"command": command},
                          "cwd": str(tmp_path)})
    p = subprocess.run([PYTHON, str(HOOK)], input=payload, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env,
                       cwd=str(VAULT), timeout=60)
    out = p.stdout or ""
    try:
        parsed = json.loads(out.strip()) if out.strip().startswith("{") else {}
    except ValueError:
        parsed = {}
    decision = ((parsed.get("hookSpecificOutput") or {}).get("permissionDecision")
                or parsed.get("permissionDecision"))
    return decision or ("warn" if out.strip() or (p.stderr or "").strip() else "allow")


WRAPPERS = [
    ('bash -c "{}"', "bash -c, double quoted"),
    ("bash -c '{}'", "bash -c, single quoted"),
    ('sh -c "{}"', "sh -c, double quoted"),
    ("sh -c '{}'", "sh -c, single quoted"),
    ('zsh -c "{}"', "zsh -c, double quoted"),
]
PAYLOADS = [(RM, "recursive delete"), (FORCE_PUSH, "force push"),
            (RESET, "hard reset"), (CLEAN, "destructive clean")]


@pytest.mark.parametrize("payload,pname", PAYLOADS, ids=[p[1] for p in PAYLOADS])
def test_bare_form_is_denied(payload, pname, tmp_path):
    """The control case. If this ever fails, the wrapper tests below prove nothing,
    because a guard that denies nothing trivially denies nothing wrapped."""
    assert _decide(payload, tmp_path) == "deny", (
        f"the BARE form of {pname} was not denied, so this suite's wrapper cases "
        f"cannot be interpreted")


@pytest.mark.parametrize("wrapper,wname", WRAPPERS, ids=[w[1] for w in WRAPPERS])
@pytest.mark.parametrize("payload,pname", PAYLOADS, ids=[p[1] for p in PAYLOADS])
def test_wrapped_form_is_also_denied(wrapper, wname, payload, pname, tmp_path):
    """GATE-1-BYPASS. A wrapper is not a disguise."""
    command = wrapper.format(payload)
    assert _decide(command, tmp_path) == "deny", (
        f"{pname} wrapped in {wname} was NOT denied, so the Gate-1 floor is "
        f"bypassable by wrapping.\n  command: {command}")


def test_python_dash_c_executing_a_destructive_command_is_denied(tmp_path):
    """`python -c` executes too. A shell command inside `os.system` is not a
    literal being discussed."""
    command = 'python -c "import os; os.system(\'%s\')"' % RM
    assert _decide(command, tmp_path) == "deny", (
        "a destructive command inside python -c os.system was not denied")


# --------------------------------------------------------------------------
# The other direction. Over-correcting here is a worse outcome than the hole,
# because a guard people route around protects nothing.
# --------------------------------------------------------------------------

BENIGN = [
    (f"grep '{RM}' /var/log/history.log", "grep searching for the pattern"),
    (f'echo "never run {RM}"', "echo mentioning the pattern"),
    (f'git commit -m "document why {RM} is dangerous"', "commit message mentioning it"),
    ("bash -c 'ls -la'", "bash -c wrapping something harmless"),
    ('sh -c "echo hello"', "sh -c wrapping an echo"),
    ("git status", "an ordinary command"),
    ("python -c \"print('hello')\"", "python -c printing"),
    ('python -c "print(\'a note: \' + %r + \' and os.system() is a function\')"' % RM,
     "python -c printing a string that merely names a sink"),
    # Found by architect review as a regression my own sink heuristic introduced:
    # a sink NAMED inside a printed string is prose, not a call. Pre-fix this
    # passed, my first version denied it, and the string-literal-aware sink
    # detector restores it without reopening the real os.system vector.

]


@pytest.mark.parametrize("command,why", BENIGN, ids=[b[1] for b in BENIGN])
def test_benign_command_is_not_denied(command, why, tmp_path):
    assert _decide(command, tmp_path) != "deny", (
        f"false positive, the guard denied a harmless command ({why}). Over-correcting "
        f"is how a safety control gets disabled by the people it protects.\n"
        f"  command: {command}")
