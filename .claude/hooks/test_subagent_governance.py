"""Tests for subagent-governance.py.

Written 2026-09-10; this guard had no suite. It fires at SubagentStart and
injects the house rules every dispatched agent works under: cite evidence, use
multiple perspectives, state uncertainty rather than guessing, and do not
anchor when evaluating. If it silently stopped, every subagent would keep
running and nothing would look wrong, which is the failure worth catching.

Note the deliberate contrast with bias-guard.py, which fires on the same event.
bias-guard is SELECTIVE (only the seven evaluator agent types); this one is
UNIVERSAL. Confusing the two would either strip the rules from most agents or
tell builders to ignore their own spec, so the universality is pinned below.

Runs from an isolated copy (see _hooktest) because the hook appends to a log
beside itself.
"""
import json

import pytest
from _hooktest import run_isolated

HOOK = "subagent-governance.py"


def context_for(payload, tmp_path):
    proc, _ = run_isolated(HOOK, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "hook emitted nothing on stdout"
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


def test_emits_a_subagentstart_envelope(tmp_path):
    proc, _ = run_isolated(HOOK, {"agent_type": "debugger"}, tmp_path)
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart"


@pytest.mark.parametrize("agent", ["debugger", "blueprint-mode", "architect-reviewer",
                                   "vault-keeper", "some-agent-invented-later"])
def test_the_rules_reach_every_agent_type_not_a_chosen_few(agent, tmp_path):
    """Universality is the contract. bias-guard.py is the selective one."""
    assert "AGENT GOVERNANCE" in context_for({"agent_type": agent}, tmp_path)


def test_the_context_carries_its_load_bearing_instructions(tmp_path):
    """Each clause here earns its place: without evidence citation the output
    is unverifiable, without the uncertainty clause guesses arrive as facts,
    and without the blind-analysis clause an evaluator anchors on the caller."""
    ctx = context_for({"agent_type": "debugger"}, tmp_path).lower()
    assert "evidence" in ctx
    assert "uncertain" in ctx
    assert "blind analysis" in ctx
    assert "perspectives" in ctx


def test_the_firing_is_logged_with_agent_type_and_id(tmp_path):
    """The log is how anyone shows the hook still fires at all."""
    _, hooks_dir = run_isolated(
        HOOK, {"agent_type": "debugger", "agent_id": "agent-42"}, tmp_path)
    log = hooks_dir / "subagent-governance.log"
    assert log.is_file(), "no log written"
    text = log.read_text(encoding="utf-8")
    assert "agent_type=debugger" in text
    assert "agent_id=agent-42" in text


def test_a_payload_without_identity_still_logs_and_injects(tmp_path):
    """Missing fields must degrade to 'unknown', never suppress the rules."""
    proc, hooks_dir = run_isolated(HOOK, {}, tmp_path)
    assert proc.returncode == 0
    assert "AGENT GOVERNANCE" in proc.stdout
    assert "unknown" in (hooks_dir / "subagent-governance.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("raw", ["", "not json at all"])
def test_empty_or_malformed_input_exits_clean_and_silent(raw, tmp_path):
    """SubagentStart is on the dispatch path; a crash here risks the dispatch."""
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_a_log_write_failure_does_not_suppress_the_rules(tmp_path):
    """The log is instrumentation; the injection is the job. If the log cannot
    be written the agent must still receive its rules."""
    proc, hooks_dir = run_isolated(HOOK, {"agent_type": "debugger"}, tmp_path)
    # Make the log path un-writable by replacing it with a directory, then rerun
    # in the same tree.
    log = hooks_dir / "subagent-governance.log"
    log.unlink(missing_ok=True)
    log.mkdir()
    import subprocess, sys, os
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"
    proc2 = subprocess.run([sys.executable, str(hooks_dir / HOOK)],
                           input=json.dumps({"agent_type": "debugger"}),
                           capture_output=True, text=True, timeout=60, env=env)
    assert proc2.returncode == 0, proc2.stderr
    assert "AGENT GOVERNANCE" in proc2.stdout
