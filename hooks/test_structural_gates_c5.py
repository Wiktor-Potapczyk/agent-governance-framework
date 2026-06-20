"""Tests for structural_gates C5: dispatch-name -> registry resolution gate.

C5 fails only on TRUE phantoms (dispatch names resolving to nothing). Its
exemptions (registered agents/skills, SKILL_AGENT_ALIASES keys, documented
deprecation aliases) are the FP-guards: without them C5 false-positives on
deliberate entries (architect-review alias, workflow-orchestrator deprecation).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "structural_gates",
    str(Path(__file__).resolve().parent.parent / "scripts" / "structural_gates.py"),
)
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)


class C5LiveTests(unittest.TestCase):
    def test_live_gate_passes_no_true_phantoms(self):
        """The live KNOWN_DISPATCH_NAMES has 0 unresolved names after exemptions."""
        r = sg.check_c5_dispatch_name_resolution()
        self.assertEqual(r["check"], "C5")
        self.assertTrue(r["ok"], f"unexpected phantoms: {r['findings']}")

    def test_severity_is_warn(self):
        r = sg.check_c5_dispatch_name_resolution()
        self.assertEqual(r["severity"], "WARN")

    def test_run_gates_exit_unaffected_by_warn(self):
        """C5 is WARN-class: even a finding must not flip the HARD exit code."""
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            rc = sg.run_gates()
        self.assertEqual(rc, 0)


class C5BoundaryTests(unittest.TestCase):
    """Named FP-guards. The exemption classes ARE the boundary axes."""

    def test_fp_alias_key_not_phantom(self):
        """FP-C5-01 boundary_axis: 'SKILL_AGENT_ALIASES key vs unresolved name'.
        architect-review is an alias key (-> architect-reviewer); it must NOT be
        flagged even though it is not a registered agent name."""
        dcl = sg._load_dispatch_logic()
        self.assertIsNotNone(dcl)
        self.assertIn("architect-review", dcl.SKILL_AGENT_ALIASES)
        r = sg.check_c5_dispatch_name_resolution()
        self.assertNotIn("architect-review", " ".join(r["findings"]))

    def test_fp_deprecation_alias_not_phantom(self):
        """FP-C5-02 boundary_axis: 'documented deprecation alias vs live agent'.
        workflow-orchestrator is a deprecated alias (CLAUDE.md safety net), exempt
        via _DEPRECATED_DISPATCH_ALIASES: must NOT be flagged."""
        self.assertIn("workflow-orchestrator", sg._DEPRECATED_DISPATCH_ALIASES)
        r = sg.check_c5_dispatch_name_resolution()
        self.assertNotIn("workflow-orchestrator", " ".join(r["findings"]))

    def test_tp_unknown_name_would_be_phantom(self):
        """TP-C5-01: a name that is neither registered, alias, nor deprecation
        resolves to nothing. Verify the resolution set logic directly (the live
        list has none, so synthesize the membership test)."""
        dcl = sg._load_dispatch_logic()
        import json
        reg = json.loads(sg.REGISTRY.read_text(encoding="utf-8"))
        resolvable = (set(reg.get("agents", {}))
                      | set(reg.get("skills", {}))
                      | set(dcl.SKILL_AGENT_ALIASES.keys())
                      | sg._DEPRECATED_DISPATCH_ALIASES)
        self.assertNotIn("totally-made-up-agent-xyz", resolvable)


if __name__ == "__main__":
    unittest.main(verbosity=2)
