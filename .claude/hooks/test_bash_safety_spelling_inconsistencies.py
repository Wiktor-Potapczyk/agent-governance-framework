r"""Two places where the guard's verdict tracks SPELLING rather than EFFECT.

These are pins, not endorsements. Both were surfaced by the wrapper-bypass fix:
once wrapped commands face the same rules as bare ones, both shapes became
reachable through `bash -c "..."` where they had been masked. Neither is a new
bug at the pattern level; both were already true of the bare form.

WHAT IS PINNED, AND WHY IT IS NOT SIMPLY FIXED
----------------------------------------------
1. `rm -rf ./build` DENIES and `rm -rf build` ALLOWS. Same delete, opposite
   verdicts, decided by whether the author typed `./`. The cause is the current-
   directory rule's lookahead `\.(?![a-zA-Z])`, which excludes a letter after the
   dot but not a slash, so `./anything` is read as "delete the current
   directory". There is no general rule for recursive relative deletes: the file
   says so itself, that the rm floor is narrower than the docstring reads.

   Fixing it has two opposite answers and they are not equivalent:
     - Tighten the lookahead, and `rm -rf ./build` joins `rm -rf build` in being
       allowed. Coherent, but it WIDENS the allowed surface, and CLAUDE.md lists
       "unflagged relative rm" on the canonical irreversible surface.
     - Deny all recursive relative deletes, matching that doctrine. Also
       coherent, but it denies `rm -rf node_modules`, `rm -rf dist` and every
       other routine build-hygiene command, each of which then costs a manual
       re-run. That is the shape Wiktor already ruled against on 2026-08-05 when
       the push deny was blocking a command he had just authorised.

2. An UNQUOTED `echo` naming a destructive string DENIES; the same text QUOTED
   allows. echo deletes nothing either way, so the deny has no safety value.
   The narrow fix is to extend the inert-context rule to unquoted bodies, but it
   must stop at `;`, `&&`, `||`, `|`, `>`, `$` and a backtick or it would swallow
   a real command chained after the echo. Stopping at `>` then means
   `echo <destructive> > script.sh` becomes allowed, which is the write-then-
   execute bypass. That bypass is already reachable through the QUOTED spelling,
   so the change would make two spellings consistent rather than open a new
   class, but it still moves the deny surface.

Both decisions turn on the same unanswered question already recorded in
task_plan.md: is this guard's threat model "catch accidental self-harm by an
agent acting in good faith", or "hold against deliberate evasion"? Under the
first, neither inconsistency matters much and the cheap fixes are fine. Under
the second, neither patch helps, because a regex over a flat string cannot be
made to hold. Changing the surface before that ruling would pre-empt it.

RULED 2026-08-24 (accidental self-harm). These now assert the RULED behaviour, not
changes it. That is the intent: the change should be deliberate and should
arrive with the ruling, not as a side effect of tidying a pattern.
"""

import json
import os
import subprocess
import sys

import pytest

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bash-safety-guard.py")
PYTHON = sys.executable or r"C:\Program Files\Python314\python.exe"

# Assembled at runtime so this file never contains a literal destructive command
# for another scanner to trip over.
RM = "r" + "m -rf "


def _verdict(command, tmp_path):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["GOVERNANCE_LOG_PATH"] = str(tmp_path / "governance-log.jsonl")
    env["GATE1_ALARM_LOG_PATH"] = str(tmp_path / "governance-log.jsonl")
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "hook-activity.jsonl")
    p = subprocess.run(
        [PYTHON, HOOK],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=60)
    assert "Traceback (most recent call last)" not in (p.stderr or ""), (
        "the guard crashed, so this test proves nothing:\n" + (p.stderr or "")[:600])
    out = (p.stdout or "").strip()
    if not out.startswith("{"):
        return "allow"
    parsed = json.loads(out)
    return ((parsed.get("hookSpecificOutput") or {}).get("permissionDecision")
            or parsed.get("permissionDecision") or "allow")


@pytest.mark.parametrize("command,expected,note", [
    (RM + "./build", "allow",
     "deleting a named subdirectory is ordinary work, not the accident the rule guards"),
    (RM + "build", "allow",
     "identical delete without the ./ prefix; the two spellings must now agree"),
    (RM + ".", "deny",
     "the case the current-directory rule was actually written for"),
    (RM + "./", "deny",
     "same target as `.`, written with a trailing slash; must not become a hole"),
])
def test_relative_delete_verdict(command, expected, note, tmp_path):
    """Threat model ruled 2026-08-24: accidental self-harm.

    Under that model deleting a NAMED subdirectory is ordinary work and deleting
    the CURRENT directory is the accident, so `./build` and `build` both allow
    while `.` and `./` both deny. Before the ruling these two spellings of the
    same delete got opposite verdicts.
    """
    assert _verdict(command, tmp_path) == expected, f"verdict for `{command}`. {note}."


@pytest.mark.parametrize("command,expected,note", [
    ("echo note: " + RM + "/data is bad", "allow",
     "echo prints, it deletes nothing; the deny had no safety value"),
    ('echo "note: ' + RM + '/data is bad"', "allow",
     "the quoted form already allowed; the two must agree"),
    ("echo hi && " + RM + "/data", "deny",
     "the strip must stop at &&, or a real chained delete rides in behind an echo"),
    ("echo hi; " + RM + "/data", "deny", "same, stopping at a semicolon"),
    ("echo hi | " + RM + "/data", "deny", "same, stopping at a pipe"),
    ("echo $(" + RM + "/data)", "deny",
     "command substitution EXECUTES, so a $ must end the inert region"),
    ("echo `" + RM + "/data`", "deny", "backtick substitution executes too"),
    ("echo hi > " + RM + "/data", "deny", "a redirect ends the inert region"),
])
def test_echo_inertness_verdict(command, expected, note, tmp_path):
    """echo prints; it deletes nothing.

    The unquoted deny had no safety value and is removed. The four deny rows are
    the reason this is not a one-character change: the strip has to stop at a
    shell separator, a redirect, `$` and a backtick, or extending it would
    launder a genuinely destructive chained command behind a harmless echo.
    """
    assert _verdict(command, tmp_path) == expected, f"verdict for `{command}`. {note}."
