"""Tests for read-before-edit-check.py.

Written 2026-09-10; this guard had no suite at all. It is INSTRUMENTATION, not
a gate: the Edit and Write tool specs already require a prior Read, so this hook
exists to record the edge cases that escape that layer (MultiEdit, retried tool
errors, subagent transcripts with a different context boundary). Its whole value
is the record, so the failure worth catching is it going quiet.

Two properties carry the weight and both are easy to break silently:

  1. The window is THE CURRENT TURN. A Read that happened before the last user
     message does not license an edit now. Widening that window to the whole
     transcript would make the hook agree with everything and report nothing,
     which is the disarmed-check shape.
  2. It never blocks. Exit code stays 0 even while warning, because a Stop hook
     that fails here would strand a real turn over a bookkeeping observation.

Binding is a subprocess run against a real transcript fixture on disk.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent / "read-before-edit-check.py"


def entry_user(text="do the thing"):
    return {"type": "user", "message": {"role": "user", "content": text}}


def entry_tool(name, file_path):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": name, "input": {"file_path": file_path}}]}}


def write_transcript(tmp_path, entries):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n",
                    encoding="utf-8")
    return str(path)


def run_hook(tmp_path, entries=None, payload=None):
    env = dict(os.environ)
    env["GOVERNANCE_LOG_PATH"] = str(tmp_path / "governance-log.jsonl")
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "hook-activity.jsonl")
    env["PYTHONIOENCODING"] = "utf-8"
    if payload is None:
        payload = {"transcript_path": write_transcript(tmp_path, entries)}
    proc = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, f"hook must never block: {proc.stderr}"
    return proc


# --- the property the hook exists for ---------------------------------------

def test_an_edit_with_no_read_this_turn_is_reported(tmp_path):
    proc = run_hook(tmp_path, [entry_user(), entry_tool("Edit", "/vault/a.py")])
    assert "WARN" in proc.stderr
    assert "/vault/a.py" in proc.stderr
    assert "Edit" in proc.stderr


def test_an_edit_preceded_by_a_read_is_silent(tmp_path):
    proc = run_hook(tmp_path, [entry_user(),
                               entry_tool("Read", "/vault/a.py"),
                               entry_tool("Edit", "/vault/a.py")])
    assert "WARN" not in proc.stderr


def test_a_read_from_a_previous_turn_does_not_license_this_edit(tmp_path):
    """The load-bearing one. Widening the window to the whole transcript would
    make this hook agree with everything and report nothing."""
    proc = run_hook(tmp_path, [entry_user("earlier"),
                               entry_tool("Read", "/vault/a.py"),
                               entry_user("now edit it"),
                               entry_tool("Edit", "/vault/a.py")])
    assert "WARN" in proc.stderr
    assert "/vault/a.py" in proc.stderr


def test_reading_a_different_file_does_not_license_the_edit(tmp_path):
    proc = run_hook(tmp_path, [entry_user(),
                               entry_tool("Read", "/vault/other.py"),
                               entry_tool("Edit", "/vault/a.py")])
    assert "WARN" in proc.stderr
    assert "/vault/a.py" in proc.stderr


def test_multiedit_is_covered_not_just_edit(tmp_path):
    """MultiEdit is named in the hook docstring as one of the escapes the tool
    layer does not catch, so it is the case most worth pinning."""
    proc = run_hook(tmp_path, [entry_user(), entry_tool("MultiEdit", "/vault/b.py")])
    assert "WARN" in proc.stderr
    assert "MultiEdit" in proc.stderr


def test_several_unread_edits_are_each_reported(tmp_path):
    proc = run_hook(tmp_path, [entry_user(),
                               entry_tool("Edit", "/vault/a.py"),
                               entry_tool("Edit", "/vault/b.py")])
    assert "/vault/a.py" in proc.stderr
    assert "/vault/b.py" in proc.stderr


def test_a_turn_with_no_edits_at_all_is_silent(tmp_path):
    proc = run_hook(tmp_path, [entry_user(), entry_tool("Read", "/vault/a.py")])
    assert "WARN" not in proc.stderr


# --- it must never block, and never crash -----------------------------------

def test_stop_hook_active_short_circuits(tmp_path):
    """Re-entry guard. Without it a Stop hook can re-trigger itself."""
    path = write_transcript(tmp_path, [entry_user(), entry_tool("Edit", "/vault/a.py")])
    proc = run_hook(tmp_path, payload={"transcript_path": path,
                                       "stop_hook_active": True})
    assert "WARN" not in proc.stderr


def test_a_missing_transcript_is_silent_and_clean(tmp_path):
    proc = run_hook(tmp_path, payload={"transcript_path": str(tmp_path / "nope.jsonl")})
    assert "WARN" not in proc.stderr


@pytest.mark.parametrize("raw", ["", "not json", "{}"])
def test_malformed_or_empty_payloads_exit_clean(raw, tmp_path):
    env = dict(os.environ)
    env["GOVERNANCE_LOG_PATH"] = str(tmp_path / "g.jsonl")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, str(HOOK)], input=raw,
                          capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr


def test_a_corrupt_transcript_line_does_not_stop_the_scan(tmp_path):
    """Transcripts are appended live and can be read mid-write. One unparsable
    line must not make the hook miss the edits around it."""
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(entry_user()) + "\n"
        + "{ this is not valid json\n"
        + json.dumps(entry_tool("Edit", "/vault/a.py")) + "\n",
        encoding="utf-8")
    proc = run_hook(tmp_path, payload={"transcript_path": str(path)})
    assert "/vault/a.py" in proc.stderr
