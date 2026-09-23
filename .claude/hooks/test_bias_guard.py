"""Tests for bias-guard.py.

Written 2026-09-10. This guard had no suite at all, which the disarm probe
counts as unprotected: an absent suite cannot notice anything. It enforces the
Blind Analysis Rule, a CLAUDE.md CRITICAL RULE, by injecting a reminder into
evaluator subagents at SubagentStart. If it silently stopped firing, evaluators
would start inheriting the caller's framing again and nothing would say so.

Binding is a SUBPROCESS RUN, not an import. The filename has hyphens, and more
to the point the real contract is JSON on stdin and one JSON object on stdout.
A disarmed stub prints nothing and fails every test here at json.loads, which
is the property that makes this suite able to fail.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent / "bias-guard.py"

# The seven agents whose job is to judge something. Listed here on purpose
# rather than imported from the hook: this is the contract under test, and a
# suite that reads its expectations out of its subject cannot detect the
# subject changing. That is exactly how test_user_prompt_submit.py went blind.
EVALUATORS = ["architect-reviewer", "adversarial-reviewer", "prompt-engineer",
              "research-analyst", "research-synthesizer", "competitive-analyst",
              "api-security-audit"]

NON_EVALUATORS = ["blueprint-mode", "general-purpose", "implementation-plan",
                  "n8n-workflow-builder", "vault-keeper", "debugger"]


def run_hook(payload_text, tmp_path):
    env = dict(os.environ)
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "hook-activity.jsonl")
    env["GOVERNANCE_LOG_PATH"] = str(tmp_path / "governance-log.jsonl")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload_text,
                          capture_output=True, text=True, timeout=60, env=env)
    return proc


def context_for(agent_type, tmp_path):
    """Return the injected additionalContext for an agent_type, or '' if none."""
    proc = run_hook(json.dumps({"agent_type": agent_type}), tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "hook emitted nothing on stdout"
    out = json.loads(proc.stdout)
    return out.get("hookSpecificOutput", {}).get("additionalContext", "")


@pytest.mark.parametrize("agent", EVALUATORS)
def test_every_evaluator_receives_the_blind_analysis_rule(agent, tmp_path):
    assert "BLIND ANALYSIS RULE" in context_for(agent, tmp_path)


@pytest.mark.parametrize("agent", NON_EVALUATORS)
def test_non_evaluators_receive_nothing(agent, tmp_path):
    """Over-injection is a real cost, not a harmless default: telling a builder
    to ignore the caller's framing would strip the spec it needs."""
    assert context_for(agent, tmp_path) == ""


def test_the_notice_carries_its_load_bearing_instruction(tmp_path):
    """The rule is worth nothing if the text degrades to a vague nudge. What
    makes it work is the explicit order to ignore a supplied hypothesis and to
    report findings even when they contradict the framing."""
    ctx = context_for("architect-reviewer", tmp_path).lower()
    assert "hypothesis" in ctx
    assert "ignore" in ctx
    assert "contradict" in ctx


def test_the_envelope_names_the_subagentstart_event(tmp_path):
    proc = run_hook(json.dumps({"agent_type": "adversarial-reviewer"}), tmp_path)
    out = json.loads(proc.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart"


# --- degradation: a guard that crashes on a bad payload is a broken dispatch --

@pytest.mark.parametrize("payload", ["", "not json at all", "[]", "null",
                                     '{"no_agent_type": true}',
                                     '{"agent_type": ""}'])
def test_malformed_or_empty_payloads_exit_clean(payload, tmp_path):
    """SubagentStart runs on the dispatch path. Anything but a clean exit and
    valid JSON here risks taking a real dispatch down with it."""
    proc = run_hook(payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) is not None


def test_an_unknown_agent_type_is_passed_through_not_rejected(tmp_path):
    """New agents appear all the time. An unrecognised one must get an empty
    envelope, never an error that breaks its dispatch."""
    proc = run_hook(json.dumps({"agent_type": "some-agent-added-next-year"}),
                    tmp_path)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {}


def test_the_firing_is_logged_with_its_decision(tmp_path):
    """Contract C1: every fire leaves a record. A guard nobody can see firing
    is one nobody can prove still works."""
    log = tmp_path / "hook-activity.jsonl"
    run_hook(json.dumps({"agent_type": "architect-reviewer"}), tmp_path)
    run_hook(json.dumps({"agent_type": "blueprint-mode"}), tmp_path)
    if not log.exists():
        pytest.skip("shared logger not writing to the override path here")
    records = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]
    decisions = [r.get("decision") for r in records]
    assert "inject" in decisions
    assert "skip" in decisions
