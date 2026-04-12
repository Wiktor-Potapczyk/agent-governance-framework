"""
Drift Guard Test — KNOWN_DISPATCH_NAMES consistency across hooks + shared module (2026-04-12)

The same KNOWN_DISPATCH_NAMES set is duplicated in 3 hook files (hooks must be self-contained):
- governance-log.py
- dispatch-compliance-check.py
- agent-dispatch-check.py

The canonical source is: scripts/shared/known_names.py

These MUST stay in sync. If a new agent is added to one but not the others,
behavior will drift: governance-log will log it correctly but dispatch-compliance
will not match it (causing false blocks), and agent-dispatch-check will not
recognize it (causing false denies).

This test asserts all four copies are identical. Fails loudly on drift.

Run: python .claude/hooks/test_known_dispatch_names_drift.py
"""

import importlib.util
import os
import sys
import unittest


HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
# Add scripts/ to path so we can import the shared canonical set
SCRIPTS_DIR = os.path.join(HOOKS_DIR, "..", "..", "Projects", "Agent-Governance-Research", "scripts")
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
    """Ensure all 3 hook copies + shared canonical set stay in sync."""

    @classmethod
    def setUpClass(cls):
        cls.gov = load_hook("governance-log.py")
        cls.disp = load_hook("dispatch-compliance-check.py")
        cls.agent = load_hook("agent-dispatch-check.py")
        # Load the canonical shared module
        from shared.known_names import KNOWN_DISPATCH_NAMES as canonical
        cls.canonical = canonical

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

    def test_canonical_vs_governance(self):
        """Shared canonical set must match governance-log."""
        extra_in_canon = self.canonical - self.gov.KNOWN_DISPATCH_NAMES
        extra_in_gov = self.gov.KNOWN_DISPATCH_NAMES - self.canonical
        self.assertEqual(extra_in_canon, set(),
                         f"Canonical has names missing from governance-log: {extra_in_canon}")
        self.assertEqual(extra_in_gov, set(),
                         f"governance-log has names not in canonical: {extra_in_gov}")

    def test_canonical_vs_dispatch_compliance(self):
        """Shared canonical set must match dispatch-compliance."""
        self.assertEqual(self.canonical, self.disp.KNOWN_DISPATCH_NAMES)

    def test_canonical_vs_agent_dispatch(self):
        """Shared canonical set must match agent-dispatch-check."""
        self.assertEqual(self.canonical, self.agent.KNOWN_DISPATCH_NAMES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
