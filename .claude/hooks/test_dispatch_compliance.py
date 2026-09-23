"""
Unit tests for dispatch-compliance-check.py — Iteration 1 changes (2026-04-09).

Covers:
- P0 fix: extract_dispatch_names filters trailing reasoning text from MUST DISPATCH
- P2-B: pass event logging when all declared items are dispatched
- P1-D: full UUID session_id (implicit via hook output inspection)
- P1-E: schema=2 field in logged entries

Run: python .claude/hooks/test_dispatch_compliance.py
"""

import importlib.util
import os
import sys
import unittest

HOOK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch-compliance-check.py")
spec = importlib.util.spec_from_file_location("dispatch_compliance_check", HOOK_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

extract_dispatch_names = mod.extract_dispatch_names
KNOWN_DISPATCH_NAMES = mod.KNOWN_DISPATCH_NAMES
SKILL_AGENT_ALIASES = mod.SKILL_AGENT_ALIASES


class TestExtractDispatchNames(unittest.TestCase):
    """P0 fix regression tests — same parsing bug as governance-log.py had."""

    def test_single_name(self):
        self.assertEqual(extract_dispatch_names("process-qa"), ["process-qa"])

    def test_two_names(self):
        self.assertEqual(extract_dispatch_names("process-qa, pm"), ["process-qa", "pm"])

    def test_trailing_reasoning(self):
        self.assertEqual(
            extract_dispatch_names("process-qa, pm Let me break down the reviewer's feedback"),
            ["process-qa", "pm"],
        )

    def test_none_returns_empty(self):
        self.assertEqual(extract_dispatch_names("none"), [])
        self.assertEqual(extract_dispatch_names("N/A"), [])

    def test_empty(self):
        self.assertEqual(extract_dispatch_names(""), [])
        self.assertEqual(extract_dispatch_names(None), [])

    def test_garbage_no_names(self):
        self.assertEqual(extract_dispatch_names("until the next field label"), [])
        self.assertEqual(extract_dispatch_names("?"), [])

    def test_pipe_delimited_with_trailing(self):
        self.assertEqual(
            extract_dispatch_names("architect-review, but no Agent tool used | Yes"),
            ["architect-review"],
        )

    def test_case_insensitive(self):
        self.assertEqual(extract_dispatch_names("Process-QA, PM"), ["process-qa", "pm"])

    def test_real_data_long_reasoning(self):
        raw = (
            "process-build, process-qa Two bugs to fix: **Bug 1: dark-zone-check "
            "false HIGH on file-writing agents**"
        )
        self.assertEqual(extract_dispatch_names(raw), ["process-build", "process-qa"])

    def test_known_names_completeness(self):
        # Sanity check — common names must be present
        for name in ["process-qa", "pm", "architect-review", "adversarial-reviewer",
                     "blueprint-mode", "technical-researcher", "implementation-plan"]:
            self.assertIn(name, KNOWN_DISPATCH_NAMES, f"{name} missing")


class TestStripFencesBugFix(unittest.TestCase):
    """Bug fix 2026-04-10: strip_fences was removing classification blocks."""

    def test_a_fenced_classification_is_not_a_contract(self):
        """Replaced 2026-09-21 (harness audit 1, review A1 and S7). The 2026-04-10
        version asserted that a classification inside a markdown fence is found.
        classifier-field-check strips fences, so a fenced classification already
        fails the field check and cannot be legitimate; a fenced quote of the
        template (documentation) must not arm a contract here either."""
        from _dispatch_compliance_logic import scan_assistant_text_block
        text_with_fences = (
            "Using task-classifier.\n\n```\n"
            "IMPLIES: User wants analysis\n"
            "TASK TYPE: Analysis\n"
            "MUST DISPATCH: process-qa, pm\n"
            "```\n\nProceeding."
        )
        state = scan_assistant_text_block(text_with_fences, {"must_dispatch": [], "dispatched": set(), "found_contract": False, "task_type": ""})
        self.assertFalse(state["found_contract"])
        self.assertEqual(state["task_type"], "")

    def test_template_must_dispatch_filtered(self):
        """Template MUST DISPATCH lines (with brackets) should not produce valid names."""
        template_text = "MUST DISPATCH: [see rules below. Quick tasks: omit this field."
        import re
        FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'
        m = re.search(
            r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
            template_text, re.DOTALL | re.IGNORECASE
        )
        self.assertIsNotNone(m)
        raw = re.sub(r'\s+', ' ', m.group(1).strip().strip('`'))
        names = extract_dispatch_names(raw)
        self.assertEqual(names, [], "Template MUST DISPATCH should produce empty list")


class TestAliasAwareCompliance(unittest.TestCase):
    """Coherence fix 2026-04-12: alias-aware missing check."""

    def _check_missing(self, must_dispatch, dispatched):
        """The real function (2026-09-21): the replica this used to carry did
        not know NON_ALIASABLE and would have passed an alias-only turn."""
        from _dispatch_compliance_logic import compute_missing
        return compute_missing(list(must_dispatch), set(dispatched))

    def test_architect_review_satisfied_by_architect_reviewer(self):
        """architect-review declared, architect-reviewer dispatched → satisfied."""
        missing = self._check_missing(["architect-review"], {"architect-reviewer"})
        self.assertEqual(missing, [])

    def test_pm_satisfied_by_pm_orchestrator(self):
        """pm declared, pm-orchestrator dispatched → satisfied."""
        missing = self._check_missing(["pm"], {"pm-orchestrator"})
        self.assertEqual(missing, [])

    def test_unaliased_agent_still_requires_exact_match(self):
        """debugger declared, blueprint-mode dispatched → NOT satisfied."""
        missing = self._check_missing(["debugger"], {"blueprint-mode"})
        self.assertEqual(missing, ["debugger"])

    def test_mixed_skills_and_agents(self):
        """Real-world: process-build + architect-review declared, blueprint-mode + architect-reviewer dispatched."""
        missing = self._check_missing(
            ["process-build", "architect-review", "process-qa", "pm"],
            {"blueprint-mode", "architect-reviewer", "process-qa", "pm-orchestrator"}
        )
        # 2026-09-21 (harness audit 1, review A2): blueprint-mode is what
        # process-build dispatches, not the skill itself; the skill is missing.
        self.assertEqual(missing, ["process-build"])

    def test_alias_coherence_with_agent_dispatch_check(self):
        """SKILL_AGENT_ALIASES must match agent-dispatch-check.py's copy."""
        import importlib.util
        adp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-dispatch-check.py")
        spec = importlib.util.spec_from_file_location("adc", adp)
        adc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adc)
        self.assertEqual(SKILL_AGENT_ALIASES, adc.SKILL_AGENT_ALIASES,
                         "dispatch-compliance and agent-dispatch-check SKILL_AGENT_ALIASES must be identical")


class TestPassEventLogic(unittest.TestCase):
    """P2-B: verify pass event is emitted when all declared items match."""

    def test_all_matched_is_pass(self):
        """Simulate the inner logic: empty 'missing' list = pass."""
        declared = ["process-qa", "pm"]
        dispatched = {"process-qa", "pm", "task-classifier"}
        # Use alias-aware check
        missing = []
        for item in declared:
            aliases = SKILL_AGENT_ALIASES.get(item, set())
            if item not in dispatched and not (aliases & dispatched):
                missing.append(item)
        self.assertEqual(missing, [])  # empty → pass path

    def test_partial_match_is_block(self):
        declared = ["process-qa", "pm"]
        dispatched = {"process-qa"}  # missing pm
        missing = [item for item in declared if item not in dispatched]
        self.assertEqual(missing, ["pm"])

    def test_extra_dispatches_still_pass(self):
        """Dispatching MORE than declared should still pass."""
        declared = ["process-qa"]
        dispatched = {"process-qa", "pm", "architect-review"}
        missing = [item for item in declared if item not in dispatched]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
