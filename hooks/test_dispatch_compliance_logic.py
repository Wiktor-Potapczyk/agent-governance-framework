"""Unit tests for _dispatch_compliance_logic.

Run: pytest .claude/hooks/test_dispatch_compliance_logic.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

_HOOK_DIR = Path(__file__).parent
if str(_HOOK_DIR) not in sys.path:
    sys.path.insert(0, str(_HOOK_DIR))

import pytest  # noqa: E402
from _dispatch_compliance_logic import (  # noqa: E402
    KNOWN_DISPATCH_NAMES,
    SKILL_AGENT_ALIASES,
    compute_matched_alias_aware,
    compute_missing,
    extract_dispatch_names,
    find_must_dispatch_raw,
    find_task_type,
    format_empty_dispatch_reason,
    format_missing_reason,
    is_terminal_skill,
    is_trackable_process_skill,
    scan_assistant_text_block,
    strip_fences,
)

# ---------------------------------------------------------------------------
# extract_dispatch_names
# ---------------------------------------------------------------------------

class TestExtractDispatchNames:
    def test_empty_string(self):
        assert extract_dispatch_names("") == []

    def test_none_literal(self):
        assert extract_dispatch_names("none") == []
        assert extract_dispatch_names("None") == []
        assert extract_dispatch_names("n/a") == []

    def test_single_known_name(self):
        assert extract_dispatch_names("process-qa") == ["process-qa"]

    def test_comma_separated_known_names(self):
        result = extract_dispatch_names("process-qa, pm, blueprint-mode")
        assert result == ["process-qa", "pm", "blueprint-mode"]

    def test_filters_unknown_names(self):
        # P0 fix 2026-04-09: trailing reasoning text must be filtered
        result = extract_dispatch_names("process-qa, nonexistent-agent, pm")
        assert result == ["process-qa", "pm"]

    def test_strips_trailing_punctuation(self):
        result = extract_dispatch_names("process-qa.")
        assert result == ["process-qa"]

    def test_case_insensitive(self):
        result = extract_dispatch_names("Process-QA, PM")
        assert result == ["process-qa", "pm"]


# ---------------------------------------------------------------------------
# strip_fences
# ---------------------------------------------------------------------------

class TestStripFences:
    def test_removes_fenced_block(self):
        text = "before\n```python\ncode\n```\nafter"
        assert "code" not in strip_fences(text)
        assert "before" in strip_fences(text)
        assert "after" in strip_fences(text)

    def test_multiple_fences(self):
        text = "```a```\nmiddle\n```b```"
        result = strip_fences(text)
        assert "a" not in result
        assert "b" not in result
        assert "middle" in result

    def test_no_fences_unchanged(self):
        assert strip_fences("plain text") == "plain text"


# ---------------------------------------------------------------------------
# find_task_type / find_must_dispatch_raw
# ---------------------------------------------------------------------------

class TestFindTaskType:
    def test_valid_task_type(self):
        assert find_task_type("TASK TYPE: Build") == "build"

    def test_classification_alias(self):
        assert find_task_type("CLASSIFICATION: Analysis") == "analysis"

    def test_case_insensitive(self):
        assert find_task_type("task type: quick") == "quick"

    def test_invalid_task_type_returns_empty(self):
        assert find_task_type("TASK TYPE: Banana") == ""

    def test_no_task_type_returns_empty(self):
        assert find_task_type("just some text") == ""


class TestFindMustDispatchRaw:
    def test_single_line(self):
        text = "MUST DISPATCH: process-qa, pm"
        assert find_must_dispatch_raw(text) == "process-qa, pm"

    def test_multiline_until_next_field(self):
        text = "MUST DISPATCH: process-qa,\npm, blueprint-mode\nMISSED: N/A"
        result = find_must_dispatch_raw(text)
        assert "process-qa" in result
        assert "blueprint-mode" in result
        assert "MISSED" not in result

    def test_no_must_dispatch_returns_empty(self):
        assert find_must_dispatch_raw("nothing here") == ""

    def test_end_of_string_termination_no_trailing_newline(self):
        # MED-3: the regex alternation terminates on `\Z` when MUST DISPATCH is
        # the final field with no following field label and no trailing newline.
        text = "TASK TYPE: Build\nMUST DISPATCH: process-qa, pm"
        assert find_must_dispatch_raw(text) == "process-qa, pm"

    def test_end_of_string_termination_multiline_no_following_field(self):
        # `\Z` branch with a multiline value and no following field label.
        text = "MUST DISPATCH: process-qa,\npm,\nblueprint-mode"
        result = find_must_dispatch_raw(text)
        assert result == "process-qa, pm, blueprint-mode"


# ---------------------------------------------------------------------------
# compute_missing / compute_matched_alias_aware
# ---------------------------------------------------------------------------

class TestComputeMissing:
    def test_all_dispatched(self):
        assert compute_missing(["process-qa", "pm"], {"process-qa", "pm-orchestrator"}) == []

    def test_one_missing(self):
        assert compute_missing(["process-qa", "blueprint-mode"], {"process-qa"}) == ["blueprint-mode"]

    def test_alias_resolution(self):
        # "architect-review" declared but "architect-reviewer" dispatched → satisfied via alias
        assert compute_missing(["architect-review"], {"architect-reviewer"}) == []

    def test_pm_alias(self):
        # "pm" declared but "pm-orchestrator" dispatched → satisfied
        assert compute_missing(["pm"], {"pm-orchestrator"}) == []

    def test_empty_declared(self):
        assert compute_missing([], {"process-qa"}) == []

    def test_unknown_no_alias(self):
        # No alias entry → must match literal
        assert compute_missing(["foo"], {"bar"}) == ["foo"]


class TestComputeMatchedAliasAware:
    def test_direct_match(self):
        assert compute_matched_alias_aware(["process-qa"], {"process-qa"}) == ["process-qa"]

    def test_alias_match(self):
        assert compute_matched_alias_aware(["architect-review"], {"architect-reviewer"}) == ["architect-review"]

    def test_partial_match(self):
        result = compute_matched_alias_aware(["pm", "blueprint-mode"], {"pm-orchestrator"})
        assert result == ["pm"]


# ---------------------------------------------------------------------------
# format helpers
# ---------------------------------------------------------------------------

class TestFormatHelpers:
    def test_missing_reason_lists_both(self):
        msg = format_missing_reason(["a", "b"], ["b"])
        assert "[a, b]" in msg
        assert "[b]" in msg
        assert "DISPATCH COMPLIANCE" in msg

    def test_empty_dispatch_reason(self):
        msg = format_empty_dispatch_reason("build")
        assert "'build'" in msg
        assert "ONLY valid for Quick" in msg


# ---------------------------------------------------------------------------
# scan_assistant_text_block
# ---------------------------------------------------------------------------

class TestScanAssistantTextBlock:
    def _init_state(self):
        return {
            "must_dispatch": [],
            "dispatched": set(),
            "found_contract": False,
            "task_type": "",
        }

    def test_no_classification_returns_unchanged_state(self):
        state = self._init_state()
        result = scan_assistant_text_block("just some text", state)
        assert result["found_contract"] is False
        assert result["must_dispatch"] == []

    def test_classification_block_sets_state(self):
        text = "TASK TYPE: Build\nMUST DISPATCH: process-qa, pm"
        state = self._init_state()
        result = scan_assistant_text_block(text, state)
        assert result["found_contract"] is True
        assert result["task_type"] == "build"
        assert "process-qa" in result["must_dispatch"]
        assert "pm" in result["must_dispatch"]

    def test_new_classification_resets_previous(self):
        # Previous state has dispatched items; new classification block must reset
        state = {
            "must_dispatch": ["old"],
            "dispatched": {"a", "b"},
            "found_contract": True,
            "task_type": "analysis",
        }
        text = "TASK TYPE: Quick"
        result = scan_assistant_text_block(text, state)
        assert result["dispatched"] == set()
        assert result["must_dispatch"] == []
        assert result["task_type"] == "quick"


# ---------------------------------------------------------------------------
# is_terminal_skill / is_trackable_process_skill
# ---------------------------------------------------------------------------

class TestSkillClassification:
    def test_process_qa_is_terminal(self):
        assert is_terminal_skill("process-qa") is True

    def test_process_pentest_is_terminal(self):
        assert is_terminal_skill("process-pentest") is True

    def test_process_build_is_not_terminal(self):
        assert is_terminal_skill("process-build") is False

    def test_trackable_excludes_terminals(self):
        assert is_trackable_process_skill("process-qa") is False
        assert is_trackable_process_skill("process-pentest") is False

    def test_trackable_includes_classifier(self):
        assert is_trackable_process_skill("task-classifier") is True

    def test_trackable_includes_process_build(self):
        assert is_trackable_process_skill("process-build") is True

    def test_trackable_excludes_non_process(self):
        assert is_trackable_process_skill("blueprint-mode") is False


# ---------------------------------------------------------------------------
# Registry sanity / drift
# ---------------------------------------------------------------------------

class TestRegistrySanity:
    """Catches accidental drift between KNOWN_DISPATCH_NAMES and alias targets."""

    def test_alias_targets_are_known(self):
        # Every alias target should appear in KNOWN_DISPATCH_NAMES,
        # otherwise alias resolution can't fire correctly downstream.
        for skill_name, alias_set in SKILL_AGENT_ALIASES.items():
            for target in alias_set:
                assert target in KNOWN_DISPATCH_NAMES, (
                    f"alias target {target!r} (from {skill_name!r}) "
                    f"is not in KNOWN_DISPATCH_NAMES"
                )

    def test_alias_keys_are_known(self):
        # Alias keys should also be known names (they're declared in MUST DISPATCH).
        for skill_name in SKILL_AGENT_ALIASES:
            assert skill_name in KNOWN_DISPATCH_NAMES, (
                f"alias key {skill_name!r} is not in KNOWN_DISPATCH_NAMES"
            )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# Separator handling (2026-08-22, owner-approved strictness increase)
# ---------------------------------------------------------------------------
# Before this change the extractor split on commas only, so "process-qa and pm"
# declared just process-qa and the obligation on every name after the "and" was
# never checked. That was a silent bypass of the harness's own mandatory-dispatch
# rule reachable by ordinary English phrasing. These cases are the regression
# guard; they live here rather than in a scratch script because this file is one
# of the five governance-hooks-ci checks.


@pytest.mark.parametrize("raw,expected", [
    ("process-qa and pm", {"process-qa", "pm"}),
    ("pm and process-qa", {"pm", "process-qa"}),
    ("process-build, process-qa and pm", {"process-build", "process-qa", "pm"}),
    ("process-qa; pm", {"process-qa", "pm"}),
    ("process-qa & pm", {"process-qa", "pm"}),
    ("process-qa, pm", {"process-qa", "pm"}),
])
def test_separators_beyond_comma(raw, expected):
    assert set(extract_dispatch_names(raw)) == expected


def test_and_inside_a_word_does_not_split():
    """The rule requires whitespace on both sides, so a name containing the
    letters 'and' is not torn apart. Guards against a naive substring split."""
    assert set(extract_dispatch_names("brand, pm")) == {"pm"}


@pytest.mark.parametrize("raw", ["none", "n/a", "None deliberately", ""])
def test_none_forms_still_return_empty(raw):
    assert extract_dispatch_names(raw) == []
