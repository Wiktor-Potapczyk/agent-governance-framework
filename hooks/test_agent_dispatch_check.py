"""
Unit tests for agent-dispatch-check.py — Iteration 1 bug fix (2026-04-10).

Covers:
- SKILL_AGENT_ALIASES mapping: pm → pm-orchestrator, architect-review → architect-reviewer
- Alias expansion: declared skill allows dispatching its agent
- Exact match still works: declaring the agent name directly is allowed
- Unrelated agents still blocked: aliases don't weaken strict checking
- Always-allowed agents bypass the check entirely
- P0 parsing fix (via extract_dispatch_names) still works

Run: python .claude/hooks/test_agent_dispatch_check.py
"""

import importlib.util
import os
import unittest

HOOK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-dispatch-check.py")
spec = importlib.util.spec_from_file_location("agent_dispatch_check", HOOK_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SKILL_AGENT_ALIASES = mod.SKILL_AGENT_ALIASES
ALWAYS_ALLOWED = mod.ALWAYS_ALLOWED
extract_dispatch_names = mod.extract_dispatch_names
KNOWN_DISPATCH_NAMES = mod.KNOWN_DISPATCH_NAMES


def resolve_allowed(must_dispatch):
    """Replicate the main() allowed-set expansion logic for testing."""
    allowed = set(must_dispatch)
    for declared in list(must_dispatch):
        if declared in SKILL_AGENT_ALIASES:
            allowed.update(SKILL_AGENT_ALIASES[declared])
    return allowed


class TestSkillAgentAliases(unittest.TestCase):
    """Bug fix 2026-04-10: declared skill should allow dispatching its agent."""

    def test_pm_alias_to_pm_orchestrator(self):
        """MUST DISPATCH: [pm] → pm-orchestrator must be allowed."""
        allowed = resolve_allowed(["pm"])
        self.assertIn("pm-orchestrator", allowed)
        self.assertIn("pm", allowed)  # original still allowed

    def test_architect_review_alias(self):
        """MUST DISPATCH: [architect-review] → architect-reviewer must be allowed."""
        allowed = resolve_allowed(["architect-review"])
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("architect-review", allowed)

    def test_multi_skill_all_aliased(self):
        """Multiple skills in MUST DISPATCH each expand their aliases."""
        allowed = resolve_allowed(["pm", "architect-review", "process-qa"])
        self.assertIn("pm-orchestrator", allowed)
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("process-qa", allowed)  # no alias, but still present

    def test_process_planning_expands(self):
        """process-planning should allow implementation-plan + adversarial-reviewer."""
        allowed = resolve_allowed(["process-planning"])
        self.assertIn("implementation-plan", allowed)
        self.assertIn("adversarial-reviewer", allowed)

    def test_process_build_expands(self):
        """process-build should allow blueprint-mode + architect-reviewer + implementation-plan."""
        allowed = resolve_allowed(["process-build"])
        self.assertIn("blueprint-mode", allowed)
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("implementation-plan", allowed)

    def test_process_research_expands(self):
        """process-research should allow research-orchestrator + technical-researcher + research-analyst."""
        allowed = resolve_allowed(["process-research"])
        self.assertIn("research-orchestrator", allowed)
        self.assertIn("technical-researcher", allowed)
        self.assertIn("research-analyst", allowed)

    def test_process_analysis_expands(self):
        """process-analysis should allow architect-reviewer + adversarial-reviewer."""
        allowed = resolve_allowed(["process-analysis"])
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("adversarial-reviewer", allowed)

    def test_process_qa_expands_to_debugger(self):
        """process-qa should allow debugger (dispatched on QA failure)."""
        allowed = resolve_allowed(["process-qa"])
        self.assertIn("debugger", allowed)

    def test_process_pentest_expands(self):
        """process-pentest should allow debugger only (skill says 'execute yourself')."""
        allowed = resolve_allowed(["process-pentest"])
        self.assertIn("debugger", allowed)
        self.assertNotIn("architect-reviewer", allowed)  # pentest doesn't delegate reviews

    def test_architect_loop_expands(self):
        """architect-loop should allow architect-reviewer + adversarial-reviewer."""
        allowed = resolve_allowed(["architect-loop"])
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("adversarial-reviewer", allowed)

    def test_process_research_does_not_include_downstream(self):
        """process-research must NOT alias research-synthesizer or report-generator.
        Those are dispatched by research-orchestrator internally, not by main session."""
        allowed = resolve_allowed(["process-research"])
        self.assertNotIn("research-synthesizer", allowed)
        self.assertNotIn("report-generator", allowed)

    def test_unrelated_agent_still_blocked(self):
        """Alias expansion must NOT let arbitrary agents through."""
        allowed = resolve_allowed(["pm", "architect-review"])
        self.assertNotIn("debugger", allowed)
        self.assertNotIn("blueprint-mode", allowed)
        self.assertNotIn("content-marketer", allowed)

    def test_exact_agent_name_still_works(self):
        """Declaring pm-orchestrator directly (no skill alias) still works."""
        allowed = resolve_allowed(["pm-orchestrator"])
        self.assertIn("pm-orchestrator", allowed)

    def test_no_aliases_for_non_aliased_names(self):
        """Skills without aliases should not magically expand."""
        allowed = resolve_allowed(["verify"])
        # verify has no alias in SKILL_AGENT_ALIASES
        self.assertEqual(allowed, {"verify"})

    def test_empty_must_dispatch(self):
        """Empty list stays empty — caller handles the 'allow all' case."""
        allowed = resolve_allowed([])
        self.assertEqual(allowed, set())


class TestAlwaysAllowed(unittest.TestCase):
    """Infrastructure agents bypass the check entirely."""

    def test_general_purpose_in_always_allowed(self):
        self.assertIn("general-purpose", ALWAYS_ALLOWED)

    def test_explore_in_always_allowed(self):
        self.assertIn("explore", ALWAYS_ALLOWED)


class TestExtractDispatchNamesStillWorks(unittest.TestCase):
    """Regression: P0 parsing fix should still work after this edit."""

    def test_filters_trailing_reasoning(self):
        self.assertEqual(
            extract_dispatch_names("process-qa, pm let me think about this"),
            ["process-qa", "pm"],
        )

    def test_known_names_unchanged(self):
        """Drift guard: set must still match the other two hooks."""
        self.assertIn("pm", KNOWN_DISPATCH_NAMES)
        self.assertIn("architect-review", KNOWN_DISPATCH_NAMES)
        self.assertIn("process-qa", KNOWN_DISPATCH_NAMES)


class TestAliasMappingIntegrity(unittest.TestCase):
    """Sanity checks on the alias map itself."""

    def test_all_keys_are_known_dispatch_names(self):
        """Every alias key should be a recognized declared name."""
        for key in SKILL_AGENT_ALIASES:
            self.assertIn(key, KNOWN_DISPATCH_NAMES, f"{key} alias key not in KNOWN_DISPATCH_NAMES")

    def test_all_values_are_known_or_plugin_agents(self):
        """Every alias value should be either in KNOWN_DISPATCH_NAMES or a known plugin agent.
        Plugin agents (architect-reviewer) may not be in KNOWN_DISPATCH_NAMES because they're
        provided by the system, not declared in MUST DISPATCH. This test ensures we don't
        have typos in alias values."""
        # Known plugin/system agent names that are valid dispatch targets
        # but not in KNOWN_DISPATCH_NAMES (they're never declared, only dispatched)
        KNOWN_PLUGIN_AGENTS = {"architect-reviewer"}
        all_values = set()
        for agents in SKILL_AGENT_ALIASES.values():
            all_values.update(agents)
        for val in all_values:
            self.assertTrue(
                val in KNOWN_DISPATCH_NAMES or val in KNOWN_PLUGIN_AGENTS,
                f"Alias value '{val}' not in KNOWN_DISPATCH_NAMES or KNOWN_PLUGIN_AGENTS"
            )

    def test_pm_maps_to_pm_orchestrator(self):
        self.assertEqual(SKILL_AGENT_ALIASES["pm"], {"pm-orchestrator"})

    def test_architect_review_maps_to_architect_reviewer(self):
        self.assertEqual(SKILL_AGENT_ALIASES["architect-review"], {"architect-reviewer"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
