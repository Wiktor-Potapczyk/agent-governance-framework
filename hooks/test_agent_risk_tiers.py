"""Schema tests for _agent_risk_tiers.json — Step-11 competence gate (Step B1).

The sidecar is HAND-OWNED (never script-regenerated); these tests guard its
contract: valid JSON, every non-meta entry carries tier + reason, tier is in
the {high, medium, low} enum, every high entry cites the derivation rubric,
and at least one high-tier entry exists so the gate has a non-empty scope.

Run: python -m pytest .claude/hooks/test_agent_risk_tiers.py -q
"""

import json
import os
import unittest

SIDECAR_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_agent_risk_tiers.json"
)

VALID_TIERS = {"high", "medium", "low"}


def load_sidecar():
    with open(SIDECAR_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def agent_entries(data):
    """Non-meta entries only (keys starting with '_' are metadata)."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


class SidecarSchemaTests(unittest.TestCase):
    def test_file_exists_and_parses_as_json(self):
        self.assertTrue(os.path.exists(SIDECAR_PATH))
        data = load_sidecar()
        self.assertIsInstance(data, dict)

    def test_every_entry_has_tier_and_reason(self):
        data = load_sidecar()
        entries = agent_entries(data)
        self.assertGreater(len(entries), 0)
        for name, entry in entries.items():
            self.assertIsInstance(entry, dict, f"{name}: entry not a dict")
            self.assertIn("tier", entry, f"{name}: missing tier")
            self.assertIn("reason", entry, f"{name}: missing reason")

    def test_tier_values_in_enum(self):
        data = load_sidecar()
        for name, entry in agent_entries(data).items():
            self.assertIn(
                entry["tier"], VALID_TIERS,
                f"{name}: tier '{entry['tier']}' not in {VALID_TIERS}",
            )

    def test_reasons_are_non_empty_strings(self):
        data = load_sidecar()
        for name, entry in agent_entries(data).items():
            self.assertIsInstance(entry["reason"], str, f"{name}: reason not str")
            self.assertTrue(entry["reason"].strip(), f"{name}: empty reason")

    def test_at_least_one_high_tier_entry(self):
        data = load_sidecar()
        highs = [
            name for name, e in agent_entries(data).items() if e["tier"] == "high"
        ]
        self.assertGreaterEqual(len(highs), 1)

    def test_every_high_entry_cites_rubric(self):
        """Spec Step-1 acceptance: each high assignment cites >=1 rubric criterion."""
        data = load_sidecar()
        for name, entry in agent_entries(data).items():
            if entry["tier"] == "high":
                self.assertIn(
                    "Rubric", entry["reason"],
                    f"{name}: high tier without a rubric citation",
                )

    def test_keys_are_lowercase(self):
        """agent-dispatch-check lowercases subagent_type before lookup —
        sidecar keys must already be lowercase or the lookup silently misses."""
        data = load_sidecar()
        for name in agent_entries(data):
            self.assertEqual(name, name.lower(), f"{name}: key not lowercase")


if __name__ == "__main__":
    unittest.main(verbosity=2)
