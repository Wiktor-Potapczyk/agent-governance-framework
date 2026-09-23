"""Tests for reviewer-scope-violation-check.py.

Written 2026-09-10; this guard had no suite despite being one of the few that
actually DENIES a tool call. It keeps reviewer agents from editing the artifact
they are reviewing: a reviewer that fixes what it finds destroys the
independence that made its review worth having.

The single most important assertion in this file is the DENIAL PROTOCOL. This
hook once logged "blocked" for fourteen days while blocking nothing, because it
emitted the SubagentStop-shaped {"decision": "block"} form, which PreToolUse
silently ignores. Nothing in the logs looked wrong. A test that only checked
"did it produce output" would have passed throughout, so the shape of the
output is asserted explicitly.

The two allow-rules are equally load-bearing in the other direction. A reviewer
whose own report file gets denied cannot do its job at all, and a hook that
blocks legitimate work is one that gets switched off.
"""
import json

import pytest
from _hooktest import run_isolated


HOOK = "reviewer-scope-violation-check.py"
REVIEWERS = ["adversarial-reviewer", "architect-reviewer", "code-reviewer"]


def call(tmp_path, agent_type, file_path, tool_name="Edit", extra=None):
    payload = {"agent_type": agent_type, "tool_name": tool_name,
               "tool_input": {"file_path": str(file_path)}}
    payload.update(extra or {})
    proc, _ = run_isolated(HOOK, payload, tmp_path)
    assert proc.returncode == 0, f"must exit 0, JSON carries the decision: {proc.stderr}"
    return proc


def decision_of(proc):
    if not proc.stdout.strip():
        return None
    return json.loads(proc.stdout)


def existing(tmp_path, rel):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("the artifact under review\n", encoding="utf-8")
    return p


# --- it denies ----------------------------------------------------------------

@pytest.mark.parametrize("agent", REVIEWERS)
def test_a_reviewer_editing_an_existing_artifact_is_denied(agent, tmp_path):
    target = existing(tmp_path, "src/module.py")
    out = decision_of(call(tmp_path, agent, target))
    assert out is not None, "no decision emitted"
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_the_denial_uses_the_pretooluse_protocol_not_the_legacy_form(tmp_path):
    """The fourteen-day silent failure. PreToolUse ignores the SubagentStop
    shape {"decision": "block"} outright, so a hook using it logs blocks while
    blocking nothing. Pin the wrapper, the event name and the field."""
    target = existing(tmp_path, "src/module.py")
    out = decision_of(call(tmp_path, "architect-reviewer", target))
    assert "hookSpecificOutput" in out, "legacy top-level form is silently ignored"
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert "permissionDecision" in out["hookSpecificOutput"]
    assert "decision" not in out


def test_the_denial_reason_names_the_agent_the_tool_and_the_path(tmp_path):
    """A denial the agent cannot act on becomes a retry loop."""
    target = existing(tmp_path, "src/module.py")
    out = decision_of(call(tmp_path, "code-reviewer", target, tool_name="Write"))
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "code-reviewer" in reason
    assert "Write" in reason
    assert "module.py" in reason
    assert "review-" in reason  # tells it where it MAY write


# --- it allows the reviewer's own output --------------------------------------

def test_a_new_file_is_allowed(tmp_path):
    """Rule C. The artifact under review already exists; a reviewer's output is
    always new, so non-existence is the cheapest correct signal."""
    proc = call(tmp_path, "architect-reviewer", tmp_path / "work" / "brand-new.md")
    assert decision_of(proc) is None


def test_an_existing_report_path_is_allowed(tmp_path):
    """Rule A, and it must come before Rule C. Re-running a review overwrites
    its own previous report, which exists, and would otherwise be denied."""
    report = existing(tmp_path, "work/2026-09-10-thing-review-adversarial.md")
    assert decision_of(call(tmp_path, "adversarial-reviewer", report)) is None


def test_the_report_convention_matches_without_a_suffix(tmp_path):
    report = existing(tmp_path, "work/2026-09-10-thing-review.md")
    assert decision_of(call(tmp_path, "architect-reviewer", report)) is None


def test_backslash_paths_still_match_the_report_convention(tmp_path):
    """Windows hands over backslashes; matching only forward slashes would deny
    every report write on this machine."""
    report = existing(tmp_path, "work/2026-09-10-thing-review.md")
    windows_style = str(report).replace("/", "\\")
    assert decision_of(call(tmp_path, "architect-reviewer", windows_style)) is None


# --- it must not touch anyone else --------------------------------------------

@pytest.mark.parametrize("agent", ["blueprint-mode", "debugger", "general-purpose",
                                   "implementation-plan", "vault-keeper"])
def test_non_reviewer_agents_are_never_denied(agent, tmp_path):
    """The fast path, and the difference between a targeted guard and one that
    stops all subagent work."""
    target = existing(tmp_path, "src/module.py")
    assert decision_of(call(tmp_path, agent, target)) is None


def test_a_main_session_write_is_never_denied(tmp_path):
    """No agent_type at all is the dominant case: the main session. It must
    cost nothing and deny nothing."""
    target = existing(tmp_path, "src/module.py")
    proc, _ = run_isolated(HOOK, {"tool_name": "Edit",
                                  "tool_input": {"file_path": str(target)}},
                           tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_agent_type_matching_is_case_insensitive(tmp_path):
    target = existing(tmp_path, "src/module.py")
    out = decision_of(call(tmp_path, "Architect-Reviewer", target))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


# --- degradation --------------------------------------------------------------

def test_a_call_with_no_file_path_is_allowed(tmp_path):
    """Safe failure: unable to determine the target means allow, not deny."""
    proc, _ = run_isolated(HOOK, {"agent_type": "architect-reviewer",
                                  "tool_name": "Edit", "tool_input": {}},
                           tmp_path)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


def test_a_json_encoded_tool_input_is_parsed(tmp_path):
    target = existing(tmp_path, "src/module.py")
    out = decision_of(call(tmp_path, "architect-reviewer", target,
                           extra={"tool_input": json.dumps(
                               {"file_path": str(target)})}))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("raw", ["", "not json at all"])
def test_malformed_input_never_denies(raw, tmp_path):
    """A PreToolUse hook that denies on its own bad input stops all writes."""
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""
