"""WORK-VERIFICATION-BLIND regression: a tool call must not hide the classification.

THE DEFECT
----------
`work-verification-check.py` finds its scan window by walking backwards to the
last transcript entry of type "user". Tool results are ALSO "user" entries, so on
any turn that used a tool the window starts after the last TOOL RESULT rather
than after the user's actual message. The classification header is written at the
top of a turn, before any tool runs, so it fell outside the window and
`is_non_quick` stayed False. Three gates then silently stopped firing: CHECK 1b
(an inline QA verdict written without invoking process-qa), the
premature-escalation gate, and the zero-tool gate.

WHY THE EXISTING 34 TESTS CANNOT CATCH IT
-----------------------------------------
Every existing fixture puts the classification header in the same final assistant
message as the report, so the header is inside the window either way and the bug
is invisible. This file's fixtures differ in exactly one respect: the header is
in an EARLIER assistant message, with a tool call and its result in between,
which is the normal shape of any real turn that did work.

The two transcripts below are byte-identical apart from that insertion. If the
verdict differs between them, the window is wrong.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "work-verification-check.py"
VAULT = Path(__file__).resolve().parent.parent.parent
PYTHON = sys.executable or r"C:\Program Files\Python314\python.exe"

CLASSIFICATION = "IMPLIES: something\nTASK TYPE: Build\nDOMAIN: general\n"
INLINE_QA = (
    "QA REPORT\n"
    "PASS: 3 / 3\n"
    "FAIL: none\n"
    "Untested: none deliberately\n"
)


def _assistant(text=None, tool=None):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool is not None:
        content.append({"type": "tool_use", "name": tool, "id": "t1", "input": {}})
    return {"type": "assistant", "message": {"content": content}}


def _tool_result():
    return {"type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": "t1",
                                     "content": "ok"}]}}


def _user(text):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def _write(tmp_path, entries):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return p


def _run(transcript, tmp_path):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["GOVERNANCE_LOG_PATH"] = str(tmp_path / "gov.jsonl")
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "act.jsonl")
    payload = json.dumps({"transcript_path": str(transcript)})
    p = subprocess.run([PYTHON, str(HOOK)], input=payload, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env,
                       cwd=str(VAULT), timeout=90)
    return (p.stdout or "") + (p.stderr or "")


def _fired(output):
    """Did any gate fire? Either a structured block or any emitted text."""
    return '"block"' in output or "WORK VERIFICATION" in output or bool(output.strip())


def test_classification_is_seen_when_no_tool_was_used(tmp_path):
    """Control. Without a tool call the header is inside the naive window, so this
    passed even before the fix. If it ever fails, the case below proves nothing."""
    t = _write(tmp_path, [
        _user("do the thing"),
        _assistant(CLASSIFICATION),
        _assistant(INLINE_QA),
    ])
    assert _fired(_run(t, tmp_path)), (
        "the control case did not fire, so this file cannot discriminate anything")


def test_classification_is_still_seen_when_a_tool_was_used(tmp_path):
    """The defect. Identical to the control apart from one tool call and its
    result sitting between the header and the report, which is what every real
    working turn looks like."""
    t = _write(tmp_path, [
        _user("do the thing"),
        _assistant(CLASSIFICATION),
        _assistant(text=None, tool="Read"),
        _tool_result(),
        _assistant(INLINE_QA),
    ])
    assert _fired(_run(t, tmp_path)), (
        "inserting a single tool call between the classification and the report "
        "silenced the gate. The scan window starts after the last tool_result, and "
        "tool results are 'user' entries, so the classification header falls outside "
        "it and is_non_quick stays False.")


def test_verdict_is_identical_with_and_without_the_tool_call(tmp_path):
    """The sharpest form: the two transcripts differ only by the insertion, so any
    difference in verdict is the window, not the content."""
    without = _write(tmp_path / "a", [
        _user("do the thing"), _assistant(CLASSIFICATION), _assistant(INLINE_QA),
    ]) if (tmp_path / "a").mkdir() or True else None
    with_tool = _write(tmp_path / "b", [
        _user("do the thing"), _assistant(CLASSIFICATION),
        _assistant(text=None, tool="Read"), _tool_result(), _assistant(INLINE_QA),
    ]) if (tmp_path / "b").mkdir() or True else None
    a = _fired(_run(without, tmp_path))
    b = _fired(_run(with_tool, tmp_path))
    assert a == b, (
        f"the same turn produces a different verdict depending only on whether a tool "
        f"was called: without tool fired={a}, with tool fired={b}")
