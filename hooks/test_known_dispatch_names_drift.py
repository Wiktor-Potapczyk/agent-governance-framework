"""Drift Guard Test - KNOWN_DISPATCH_NAMES consistency across hooks and the
generated data file (2026-04-12; architecture updated 2026-08-19).

Architecture change (2026-08-19, plugin-wiring-investigation fix): the three
hook files (governance-log.py, dispatch-compliance-check.py [via
_dispatch_compliance_logic.py], agent-dispatch-check.py) no longer each carry
an independent hand-typed KNOWN_DISPATCH_NAMES literal. All three now read
the same generated file (.claude/hooks/_known_dispatch_names.json, produced
by .claude/scripts/generate_known_dispatch_names.py from registry.json plus
a local disk scan) via the shared .claude/hooks/_known_dispatch_names_loader.py.

Projects/your-project/scripts/shared/known_names.py (the old
hand-maintained "canonical copy", outside .claude/ and out of scope for the
generator) is now a frozen historical snapshot, not the live source of
truth. This test no longer compares the three hooks against it for
KNOWN_DISPATCH_NAMES - that comparison would now report permanent, expected
drift (267 generated vs. 93 frozen), not a real bug. It does still assert
what actually matters post-migration: the three hooks must be identical to
each other and to the live generated file (the new single source of truth),
since a hook silently falling back (generated file missing or broken) while
the others succeed is real drift worth catching.

SKILL_AGENT_ALIASES (TestSkillAgentAliasesDrift below) is unchanged and out
of scope for this generator; it still compares against the canonical shared
module as before.

Run: python .claude/hooks/test_known_dispatch_names_drift.py
"""

import importlib.util
import os
import sys
import unittest

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
# Add scripts/ to path so we can import the shared canonical set
# LAYOUT ADAPTATION, not a token scrub. In the vault this file sits under
# .claude/hooks/ and the canonical module under Projects/<project>/scripts/, so the
# vault copy walks up two levels and back down. In this repo hooks/ and scripts/ are
# siblings at the root. Substituting the project name into the vault path produces a
# path correct in NEITHER tree, which is how this shipped broken once.
SCRIPTS_DIR = os.path.join(HOOKS_DIR, "..", "scripts")
sys.path.insert(0, os.path.normpath(SCRIPTS_DIR))


def load_hook(filename):
    """Load a hook module by filename (supports hyphenated names)."""
    path = os.path.join(HOOKS_DIR, filename)
    module_name = filename.replace(".py", "").replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestKnownDispatchNamesDrift(unittest.TestCase):
    """Ensure all 3 hooks stay in sync with each other and with the generated file."""

    @classmethod
    def setUpClass(cls):
        cls.gov = load_hook("governance-log.py")
        cls.disp = load_hook("dispatch-compliance-check.py")
        cls.agent = load_hook("agent-dispatch-check.py")
        # Load the generated data file directly (2026-08-19 architecture:
        # this replaces the old shared.known_names canonical-module load).
        import json
        generated_path = os.path.join(HOOKS_DIR, "_known_dispatch_names.json")
        with open(generated_path, "r", encoding="utf-8") as f:
            cls.generated = set(json.load(f)["known_dispatch_names"])

    def test_governance_log_has_set(self):
        self.assertTrue(hasattr(self.gov, "KNOWN_DISPATCH_NAMES"))
        self.assertIsInstance(self.gov.KNOWN_DISPATCH_NAMES, set)

    def test_dispatch_compliance_has_set(self):
        self.assertTrue(hasattr(self.disp, "KNOWN_DISPATCH_NAMES"))
        self.assertIsInstance(self.disp.KNOWN_DISPATCH_NAMES, set)

    def test_agent_dispatch_check_has_set(self):
        self.assertTrue(hasattr(self.agent, "KNOWN_DISPATCH_NAMES"))
        self.assertIsInstance(self.agent.KNOWN_DISPATCH_NAMES, set)

    def test_governance_vs_dispatch_compliance(self):
        """governance-log and dispatch-compliance sets must be identical."""
        extra_in_gov = self.gov.KNOWN_DISPATCH_NAMES - self.disp.KNOWN_DISPATCH_NAMES
        extra_in_disp = self.disp.KNOWN_DISPATCH_NAMES - self.gov.KNOWN_DISPATCH_NAMES
        self.assertEqual(extra_in_gov, set(),
                         f"governance-log has names missing from dispatch-compliance: {extra_in_gov}")
        self.assertEqual(extra_in_disp, set(),
                         f"dispatch-compliance has names missing from governance-log: {extra_in_disp}")

    def test_governance_vs_agent_dispatch(self):
        """governance-log and agent-dispatch-check sets must be identical."""
        extra_in_gov = self.gov.KNOWN_DISPATCH_NAMES - self.agent.KNOWN_DISPATCH_NAMES
        extra_in_agent = self.agent.KNOWN_DISPATCH_NAMES - self.gov.KNOWN_DISPATCH_NAMES
        self.assertEqual(extra_in_gov, set(),
                         f"governance-log has names missing from agent-dispatch-check: {extra_in_gov}")
        self.assertEqual(extra_in_agent, set(),
                         f"agent-dispatch-check has names missing from governance-log: {extra_in_agent}")

    def test_all_three_identical(self):
        """Belt-and-suspenders: all three must be exactly equal."""
        self.assertEqual(self.gov.KNOWN_DISPATCH_NAMES, self.disp.KNOWN_DISPATCH_NAMES)
        self.assertEqual(self.disp.KNOWN_DISPATCH_NAMES, self.agent.KNOWN_DISPATCH_NAMES)

    def test_reasonable_size(self):
        """Sanity: set should have 30+ entries (30 agents + 14+ skills)."""
        self.assertGreater(len(self.gov.KNOWN_DISPATCH_NAMES), 30)

    def test_generated_file_vs_governance(self):
        """Generated data file must match governance-log's loaded set."""
        extra_in_file = self.generated - self.gov.KNOWN_DISPATCH_NAMES
        extra_in_gov = self.gov.KNOWN_DISPATCH_NAMES - self.generated
        self.assertEqual(extra_in_file, set(),
                         f"Generated file has names missing from governance-log: {extra_in_file}")
        self.assertEqual(extra_in_gov, set(),
                         f"governance-log has names not in the generated file: {extra_in_gov}")

    def test_generated_file_vs_dispatch_compliance(self):
        """Generated data file must match dispatch-compliance's loaded set."""
        self.assertEqual(self.generated, self.disp.KNOWN_DISPATCH_NAMES)

    def test_generated_file_vs_agent_dispatch(self):
        """Generated data file must match agent-dispatch-check's loaded set."""
        self.assertEqual(self.generated, self.agent.KNOWN_DISPATCH_NAMES)


class TestSkillAgentAliasesDrift(unittest.TestCase):
    """Step 2.3 (2026-04-13): SKILL_AGENT_ALIASES must stay in sync between hooks + canonical."""

    @classmethod
    def setUpClass(cls):
        cls.disp = load_hook("dispatch-compliance-check.py")
        cls.agent = load_hook("agent-dispatch-check.py")
        from shared.known_names import SKILL_AGENT_ALIASES as canonical
        cls.canonical = canonical

    def test_dispatch_compliance_has_aliases(self):
        self.assertTrue(hasattr(self.disp, "SKILL_AGENT_ALIASES"))
        self.assertIsInstance(self.disp.SKILL_AGENT_ALIASES, dict)

    def test_agent_dispatch_has_aliases(self):
        self.assertTrue(hasattr(self.agent, "SKILL_AGENT_ALIASES"))
        self.assertIsInstance(self.agent.SKILL_AGENT_ALIASES, dict)

    def test_hooks_aliases_identical(self):
        """Both hooks must have identical SKILL_AGENT_ALIASES."""
        self.assertEqual(
            set(self.disp.SKILL_AGENT_ALIASES.keys()),
            set(self.agent.SKILL_AGENT_ALIASES.keys()),
            "SKILL_AGENT_ALIASES keys differ between hooks"
        )
        for key in self.disp.SKILL_AGENT_ALIASES:
            self.assertEqual(
                self.disp.SKILL_AGENT_ALIASES[key],
                self.agent.SKILL_AGENT_ALIASES[key],
                f"SKILL_AGENT_ALIASES['{key}'] differs between hooks"
            )

    def test_canonical_matches_hooks(self):
        """Canonical source must match both hooks."""
        for key in self.canonical:
            self.assertIn(key, self.agent.SKILL_AGENT_ALIASES,
                          f"Canonical key '{key}' missing from agent-dispatch-check")
            self.assertEqual(self.canonical[key], self.agent.SKILL_AGENT_ALIASES[key],
                             f"Canonical['{key}'] != agent-dispatch-check['{key}']")

    def test_all_keys_in_known_dispatch_names(self):
        """Every alias key must be a recognized name."""
        from shared.known_names import KNOWN_DISPATCH_NAMES
        for key in self.canonical:
            self.assertIn(key, KNOWN_DISPATCH_NAMES,
                          f"Alias key '{key}' not in KNOWN_DISPATCH_NAMES")

    def test_all_values_are_valid_agent_names(self):
        """Every alias value must be a recognized agent name (in KNOWN_DISPATCH_NAMES
        or a known runtime-only name like architect-reviewer)."""
        from shared.known_names import KNOWN_DISPATCH_NAMES
        # Runtime-only names: agent name: field values not in KNOWN_DISPATCH_NAMES
        RUNTIME_ONLY = {"architect-reviewer"}
        all_values = set()
        for agents in self.canonical.values():
            all_values.update(agents)
        for val in all_values:
            self.assertTrue(
                val in KNOWN_DISPATCH_NAMES or val in RUNTIME_ONLY,
                f"Alias value '{val}' not in KNOWN_DISPATCH_NAMES or RUNTIME_ONLY"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
