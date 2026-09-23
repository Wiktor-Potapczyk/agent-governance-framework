"""Tests for pretooluse-payload-probe.py.

Written 2026-09-10; this probe had no suite. It answers one empirical question
(does `agent_type` reach PreToolUse payloads for non-reviewer agent types?) by
appending one metadata-only record per matched Write/Edit/MultiEdit call.

Two properties are worth real assertions and both fail silently if broken:

  1. An absent agent_type is recorded as the explicit marker "<ABSENT>", never
     as a missing key or null. The whole finding is the difference between
     "present and empty" and "not delivered at all"; a probe that drops the key
     answers its own question with silence.
  2. METADATA ONLY. This probe sits on the write path, so its payloads carry
     file bodies and prompts. If content ever leaked into the record, the log
     would become a copy of everything written, in a file nobody treats as
     sensitive. That is a disclosure bug, not a tidiness one.

Runs from an isolated copy: the sink is derived from the hook's own location.
"""
import json

import pytest
from _hooktest import read_jsonl, run_isolated

HOOK = "pretooluse-payload-probe.py"


def records_after(payload, tmp_path):
    proc, hooks_dir = run_isolated(HOOK, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    return read_jsonl(hooks_dir / "_state" / "pretooluse-payload-probe.jsonl")


def test_one_record_is_written_per_call(tmp_path):
    recs = records_after({"tool_name": "Write", "agent_type": "debugger"}, tmp_path)
    assert len(recs) == 1


def test_an_absent_agent_type_is_marked_explicitly(tmp_path):
    """The finding IS this distinction. Dropping the key would make an
    unanswered question look like an answered one."""
    recs = records_after({"tool_name": "Write"}, tmp_path)
    assert recs[0]["agent_type"] == "<ABSENT>"


def test_an_empty_agent_type_is_also_marked_absent(tmp_path):
    recs = records_after({"tool_name": "Edit", "agent_type": ""}, tmp_path)
    assert recs[0]["agent_type"] == "<ABSENT>"


def test_a_present_agent_type_is_recorded_verbatim(tmp_path):
    recs = records_after({"tool_name": "Edit", "agent_type": "code-reviewer"}, tmp_path)
    assert recs[0]["agent_type"] == "code-reviewer"


def test_the_record_is_metadata_only(tmp_path):
    """The load-bearing one. This probe runs on the write path, so its input
    carries file bodies. None of that may reach the log."""
    secret_body = "SENTINEL_FILE_BODY_THAT_MUST_NOT_BE_LOGGED"
    recs = records_after({
        "tool_name": "Write",
        "agent_type": "debugger",
        "transcript_path": "/some/transcript.jsonl",
        "tool_input": {"file_path": "/vault/x.md", "content": secret_body},
        "prompt": "SENTINEL_PROMPT_TEXT",
    }, tmp_path)
    blob = json.dumps(recs[0])
    assert secret_body not in blob
    assert "SENTINEL_PROMPT_TEXT" not in blob
    # Key NAMES are the point of the probe and are expected to survive.
    assert "tool_input" in recs[0]["payload_keys"]


def test_payload_keys_are_names_only_and_sorted(tmp_path):
    recs = records_after({"tool_name": "Write", "b_key": 1, "a_key": 2}, tmp_path)
    keys = recs[0]["payload_keys"]
    assert keys == sorted(keys)
    assert "a_key" in keys and "b_key" in keys


def test_transcript_presence_is_a_boolean_not_the_path(tmp_path):
    """Recording the path would put a machine-specific location in the log for
    no analytic gain; the question is only whether it was delivered."""
    recs = records_after({"tool_name": "Write",
                          "transcript_path": "/home/someone/secret-project.jsonl"},
                         tmp_path)
    assert recs[0]["transcript_path_present"] is True
    assert "secret-project" not in json.dumps(recs[0])


def test_absent_transcript_records_false(tmp_path):
    recs = records_after({"tool_name": "Write"}, tmp_path)
    assert recs[0]["transcript_path_present"] is False


@pytest.mark.parametrize("raw", ["not json", "[]", "null", '"a string"'])
def test_non_object_payloads_write_nothing_and_exit_clean(raw, tmp_path):
    """PreToolUse sits in front of every write. Fail-open is the contract."""
    proc, hooks_dir = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert read_jsonl(hooks_dir / "_state" / "pretooluse-payload-probe.jsonl") == []


def test_empty_stdin_records_an_empty_payload_row(tmp_path):
    """Pinning ACTUAL behaviour, which differs from the other malformed inputs.

    The hook reads `json.loads(stdin or "{}")`, so empty stdin becomes a valid
    empty dict and is recorded rather than skipped. The row is harmless but
    contentless (no keys, agent_type <ABSENT>, tool_name ""), so it inflates
    the probe's row count slightly above the number of real matched calls.
    Reported, not changed: anyone counting rows should know, and the fix is a
    behaviour decision for the probe's owner, not a test repair.
    """
    proc, hooks_dir = run_isolated(HOOK, "", tmp_path)
    assert proc.returncode == 0, proc.stderr
    recs = read_jsonl(hooks_dir / "_state" / "pretooluse-payload-probe.jsonl")
    assert len(recs) == 1
    assert recs[0]["payload_keys"] == []
    assert recs[0]["agent_type"] == "<ABSENT>"


def test_the_probe_is_silent_on_stdout(tmp_path):
    """A PreToolUse hook that prints unexpected text can be read as a decision.
    This one only appends to its log."""
    proc, _ = run_isolated(HOOK, {"tool_name": "Write"}, tmp_path)
    assert proc.stdout.strip() == ""
