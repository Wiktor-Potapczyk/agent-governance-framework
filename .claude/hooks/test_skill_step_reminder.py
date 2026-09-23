"""Tests for skill-step-reminder.py.

Written 2026-09-10; this guard had no suite. It fires after a Skill call and
re-states the mandatory steps of the five process skills. Its value is entirely
in WHICH clause each reminder carries: the reminders exist because these are
the steps that get skipped under pressure, so a reminder that degraded into a
generic "follow the process" would still look like it was working.

The selectivity matters in both directions. Reminding on every skill would
train the reader to ignore the block; reminding on none would remove the only
runtime restatement of the synthesis and review mandates.
"""
import json

import pytest
from _hooktest import run_isolated

HOOK = "skill-step-reminder.py"

PROCESS_SKILLS = ["process-research", "process-analysis", "process-build",
                  "process-planning", "process-qa"]


def context_for(skill, tmp_path, tool_input=None):
    payload = {"tool_name": "Skill",
               "tool_input": tool_input if tool_input is not None
               else {"skill": skill}}
    proc, _ = run_isolated(HOOK, payload, tmp_path)
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return ""
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("skill", PROCESS_SKILLS)
def test_every_process_skill_gets_its_reminder(skill, tmp_path):
    assert "PROCESS REMINDER" in context_for(skill, tmp_path)


@pytest.mark.parametrize("skill", ["save", "task-classifier", "hookify",
                                   "process-ingest", "n8n-patterns", ""])
def test_other_skills_pass_through_silently(skill, tmp_path):
    """process-ingest and process-lint are deliberately absent from the table;
    reminding on every skill would train the reader to skip the block."""
    assert context_for(skill, tmp_path) == ""


def test_skill_matching_is_case_insensitive(tmp_path):
    assert "PROCESS REMINDER" in context_for("Process-QA", tmp_path)


def test_a_json_encoded_tool_input_is_parsed(tmp_path):
    """tool_input arrives as a JSON string on some paths. Failing to parse it
    would silence the hook everywhere without any error."""
    ctx = context_for(None, tmp_path,
                      tool_input=json.dumps({"skill": "process-build"}))
    assert "PROCESS REMINDER" in ctx


# --- the clause each reminder exists to restate ------------------------------

def test_build_reminder_names_the_review_mandate(tmp_path):
    ctx = context_for("process-build", tmp_path)
    assert "architect-reviewer" in ctx
    assert "violation" in ctx.lower()


def test_planning_reminder_names_both_reviewers(tmp_path):
    ctx = context_for("process-planning", tmp_path)
    assert "architect-reviewer" in ctx
    assert "adversarial-reviewer" in ctx


@pytest.mark.parametrize("skill", ["process-research", "process-analysis"])
def test_the_synthesis_mandate_survives(skill, tmp_path):
    """Both skills route through research-synthesizer when 2+ agents ran, and
    that is the step most often dropped."""
    ctx = context_for(skill, tmp_path)
    assert "research-synthesizer" in ctx
    assert "synthes" in ctx.lower()


def test_qa_reminder_insists_on_execution_over_reasoning(tmp_path):
    """QA that reasons about passing instead of running is the failure this
    clause exists to prevent."""
    ctx = context_for("process-qa", tmp_path).lower()
    assert "actually run it" in ctx
    assert "do not fix them" in ctx


# --- degradation --------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "not json at all"])
def test_empty_or_malformed_input_is_silent_and_clean(raw, tmp_path):
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_a_missing_tool_input_does_not_crash(tmp_path):
    proc, _ = run_isolated(HOOK, {"tool_name": "Skill"}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_only_matched_skills_are_logged(tmp_path):
    """The hook fires on EVERY Skill call, so logging before the filter would
    bury the signal under one record per skill invocation in the vault."""
    log_name = "hook-activity.jsonl"
    _, hooks_dir = run_isolated(
        HOOK, {"tool_name": "Skill", "tool_input": {"skill": "save"}}, tmp_path)
    unmatched = hooks_dir / log_name
    unmatched_records = (unmatched.read_text(encoding="utf-8").strip()
                         if unmatched.is_file() else "")
    assert "skill-step-reminder" not in unmatched_records
