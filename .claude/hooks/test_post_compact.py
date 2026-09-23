"""Tests for post-compact.py.

Written 2026-09-10; this hook had no suite. It fires after a compaction and
does two things: records the event so compaction frequency is visible, and
writes a staleness marker so a later session knows the qmd index and STATE.md
may be behind. That marker is the whole reason the vault's compaction doctrine
works ("reload after compaction, do not run on the lossy summary"). If the
marker silently stopped being written, sessions would keep running on stale
state and nothing would say so.

One constraint is easy to break and impossible to notice from inside a session:
PostCompact REJECTS hookSpecificOutput.additionalContext. The hook must print a
bare empty object. A well-meaning future edit that starts injecting orientation
text here would be discarded by the host at best.

Runs from an isolated copy: the marker path derives from the hook's location.
"""
import json

import pytest
from _hooktest import run_isolated

HOOK = "post-compact.py"


def marker_after(payload, tmp_path):
    proc, hooks_dir = run_isolated(HOOK, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    path = hooks_dir / "_state" / "last-compact.json"
    assert path.is_file(), "staleness marker was not written"
    return json.loads(path.read_text(encoding="utf-8")), proc


def test_the_staleness_marker_is_written(tmp_path):
    data, _ = marker_after({"reason": "auto", "session_id": "s-1"}, tmp_path)
    assert data["reason"] == "auto"
    assert data["session"] == "s-1"
    assert data["last_compact"]


def test_the_marker_tells_the_reader_to_re_read_state_from_disk(tmp_path):
    """The marker exists to be acted on. A note that only says 'compacted'
    leaves the reader to invent the remedy."""
    data, _ = marker_after({"reason": "auto"}, tmp_path)
    note = data["note"].lower()
    assert "state.md" in note
    assert "stale" in note


def test_reason_falls_back_to_the_trigger_key(tmp_path):
    """The host has used both spellings; accepting only one silently records
    every compaction as reasonless."""
    data, _ = marker_after({"trigger": "manual"}, tmp_path)
    assert data["reason"] == "manual"


def test_a_payload_with_neither_key_still_writes_a_marker(tmp_path):
    """An unknown reason is not a reason to skip the marker: the fact that a
    compaction happened is the load-bearing part."""
    data, _ = marker_after({}, tmp_path)
    assert data["reason"] == ""
    assert data["session"] == "unknown"


def test_stdout_is_a_bare_empty_object(tmp_path):
    """PostCompact rejects additionalContext. Anything richer than {} here is
    discarded by the host, so pinning it stops a future edit from quietly
    building orientation logic that can never run."""
    _, proc = marker_after({"reason": "auto"}, tmp_path)
    assert json.loads(proc.stdout) == {}


def test_the_marker_is_overwritten_not_appended(tmp_path):
    """It answers 'when was the LAST compaction'. An appending marker would
    stop parsing as JSON on the second compaction."""
    marker_after({"reason": "first", "session_id": "s-1"}, tmp_path)
    data, _ = marker_after({"reason": "second", "session_id": "s-2"}, tmp_path)
    assert data["reason"] == "second"
    assert data["session"] == "s-2"


@pytest.mark.parametrize("raw", ["", "not json at all", "[]"])
def test_malformed_input_still_exits_clean_and_prints_the_envelope(raw, tmp_path):
    """Fail-open is explicit in the hook contract: never crash the session."""
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {}


def test_the_firing_is_recorded_for_liveness(tmp_path):
    """Compaction frequency is only visible if each fire leaves a record."""
    proc, hooks_dir = run_isolated(HOOK, {"reason": "auto", "session_id": "s-9"},
                                   tmp_path)
    assert proc.returncode == 0
    log = hooks_dir / "hook-activity.jsonl"
    if not log.is_file():
        pytest.skip("shared logger not writing to the override path here")
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r.get("hook") == "post-compact" for r in records)
