"""
test_competence_gate_report.py — Unit tests for competence_gate_report.py

Spec: Projects/Agent-Governance-Research/work/2026-07-10-step11-competence-gate-spec.md §5 Step 5

Fixtures are hand-crafted to cover:
  - Synthetic-session exclusion proven by EXACT count (the load-bearing
    pre-filter test: session == 'session' decision events must not count)
  - Zero-decision high-tier agent still listed in the table (sparsity
    visibility for the Step-6 window / kill criterion 1)
  - Non-gate events and malformed lines skipped without raising
  - Agent types seen in gate events but absent from the sidecar listed
  - Score distribution min/p50/max and warn/NO_SIGNAL rates computed only
    from surviving (real-shaped) events

Ground truth for all assertions is manual counting of the fixture data,
NOT the script's own output.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

# ---------------------------------------------------------------------------
# Dynamic import of the module under test so this file can live next to it
# ---------------------------------------------------------------------------
_SCRIPT = Path(__file__).parent / "competence_gate_report.py"
_spec = importlib.util.spec_from_file_location("competence_gate_report", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

read_decisions = _mod.read_decisions
load_high_tier_agents = _mod.load_high_tier_agents
summarize = _mod.summarize
format_table = _mod.format_table
main = _mod.main


def _decision(agent, verdict, score, action, session="11111111-2222-3333-4444-555555555555"):
    return {
        "ts": "2026-07-13 12:00:00", "schema": 2,
        "event": "competence_gate_decision", "hook": "agent-dispatch-check",
        "session": session, "agent_type": agent, "risk_tier": "high",
        "score": score, "n": 10, "verdict": verdict, "mode": "advisory",
        "action_taken": action,
    }


class CompetenceGateReportTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.log_path = tmp / "gov-log.jsonl"
        self.tiers_path = tmp / "tiers.json"
        self.tiers_path.write_text(json.dumps({
            "_meta": {"derived": "fixture"},
            "agent-a": {"tier": "high", "reason": "fixture"},
            "agent-zero": {"tier": "high", "reason": "fixture; never dispatched"},
            "agent-low": {"tier": "low", "reason": "fixture"},
        }), encoding="utf-8")

        # Fixture log: 3 real agent-a decisions (2 scored + 1 NO_SIGNAL),
        # 2 SYNTHETIC agent-a decisions (must be excluded), 1 real decision
        # from an agent absent from the sidecar, plus noise lines.
        lines = [
            json.dumps(_decision("agent-a", "BELOW", 0.3, "warn")),
            json.dumps(_decision("agent-a", "OK", 0.9, "none")),
            json.dumps(_decision("agent-a", "NO_SIGNAL", None, "none")),
            json.dumps(_decision("agent-a", "BELOW", 0.1, "warn", session="session")),
            json.dumps(_decision("agent-a", "BELOW", 0.2, "warn", session="session")),
            json.dumps(_decision("agent-ghost", "OK", 1.0, "none")),
            json.dumps({"event": "pass", "hook": "subagent-quality-check",
                        "session": "real-uuid", "agent_type": "agent-a"}),
            "{{{ malformed line",
            "",
        ]
        self.log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _summary(self):
        decisions = read_decisions(str(self.log_path))
        high, sidecar = load_high_tier_agents(str(self.tiers_path))
        return decisions, high, summarize(decisions, high, sidecar)

    def test_synthetic_session_excluded_by_exact_count(self):
        """5 agent-a decision lines in the fixture; exactly 3 survive."""
        decisions, _, summary = self._summary()
        agent_a = [d for d in decisions if d["agent_type"] == "agent-a"]
        self.assertEqual(len(agent_a), 3)  # NOT 5 — both synthetic dropped
        self.assertEqual(summary["rows"]["agent-a"]["total"], 3)
        # The synthetic BELOW events must not inflate the warn count:
        self.assertEqual(summary["rows"]["agent-a"]["warn_count"], 1)

    def test_zero_decision_high_tier_agent_still_listed(self):
        _, high, summary = self._summary()
        self.assertIn("agent-zero", high)
        self.assertIn("agent-zero", summary["rows"])
        row = summary["rows"]["agent-zero"]
        self.assertEqual(row["total"], 0)
        self.assertEqual(row["n_scored"], 0)
        self.assertIsNone(row["score_p50"])
        # And it renders in the table:
        table = format_table(summary, high)
        self.assertIn("agent-zero", table)

    def test_non_gate_events_and_malformed_lines_skipped(self):
        decisions, _, _ = self._summary()
        self.assertTrue(all(
            d["event"] == "competence_gate_decision" for d in decisions
        ))
        self.assertEqual(len(decisions), 4)  # 3 agent-a + 1 agent-ghost

    def test_score_distribution_and_rates(self):
        _, _, summary = self._summary()
        row = summary["rows"]["agent-a"]
        self.assertEqual(row["n_scored"], 2)          # BELOW 0.3 + OK 0.9
        self.assertEqual(row["score_min"], 0.3)
        self.assertEqual(row["score_max"], 0.9)
        self.assertAlmostEqual(row["score_p50"], 0.6)  # mean of two middles
        self.assertAlmostEqual(row["warn_rate"], 1 / 3)
        self.assertEqual(row["no_signal_count"], 1)
        self.assertAlmostEqual(row["no_signal_rate"], 1 / 3)
        self.assertEqual(row["verdict_counts"],
                         {"BELOW": 1, "OK": 1, "NO_SIGNAL": 1})

    def test_agent_absent_from_sidecar_surfaced(self):
        _, high, summary = self._summary()
        self.assertIn("agent-ghost", summary["unknown_agents"])
        table = format_table(summary, high)
        self.assertIn("ABSENT from the sidecar", table)
        self.assertIn("agent-ghost", table)

    def test_low_tier_agent_without_decisions_not_listed(self):
        """Only high-tier agents get zero-decision rows; low tier does not."""
        _, _, summary = self._summary()
        self.assertNotIn("agent-low", summary["rows"])

    def test_main_exit_zero_on_fixture(self):
        rc = main(["--log", str(self.log_path), "--tiers", str(self.tiers_path)])
        self.assertEqual(rc, 0)

    def test_main_exit_nonzero_on_missing_log(self):
        rc = main(["--log", str(Path(self._tmp.name) / "missing.jsonl"),
                   "--tiers", str(self.tiers_path)])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
