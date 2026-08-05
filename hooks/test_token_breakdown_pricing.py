"""Tests for the ECC-LEARN-E2 USD cost surface added to token-breakdown.py."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "token_breakdown",
    str(Path(__file__).parent / "token-breakdown.py"),
)
tb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tb)


class NormaliseModelKeyTests(unittest.TestCase):
    def test_strips_1m_suffix(self):
        self.assertEqual(tb._normalise_model_key("claude-opus-4-7[1m]"), "claude-opus-4-7")

    def test_plain_key(self):
        self.assertEqual(tb._normalise_model_key("claude-sonnet-4-6"), "claude-sonnet-4-6")

    def test_non_string(self):
        self.assertEqual(tb._normalise_model_key(None), "")
        self.assertEqual(tb._normalise_model_key(42), "")

    def test_empty(self):
        self.assertEqual(tb._normalise_model_key(""), "")

    def test_strips_whitespace(self):
        self.assertEqual(tb._normalise_model_key("  claude-opus-4-7  "), "claude-opus-4-7")


class LookupRateTests(unittest.TestCase):
    def test_opus_exact(self):
        self.assertEqual(tb._lookup_rate("claude-opus-4-7"), (15.00, 75.00, 1.50, 18.75))

    def test_sonnet_exact(self):
        self.assertEqual(tb._lookup_rate("claude-sonnet-4-6"), (3.00, 15.00, 0.30, 3.75))

    def test_haiku_exact(self):
        self.assertEqual(tb._lookup_rate("claude-haiku-4-5"), (1.00, 5.00, 0.10, 1.25))

    def test_opus_with_1m_suffix(self):
        # _lookup_rate normalises first, then strips [1m]
        self.assertEqual(tb._lookup_rate("claude-opus-4-7[1m]"), (15.00, 75.00, 1.50, 18.75))

    def test_unknown_model_returns_none(self):
        self.assertIsNone(tb._lookup_rate("not-a-real-model"))

    def test_haiku_dated_variant(self):
        # The dated variant should match its own entry
        self.assertEqual(
            tb._lookup_rate("claude-haiku-4-5-20251001"),
            (1.00, 5.00, 0.10, 1.25),
        )


class ComputeCostTests(unittest.TestCase):
    def test_opus_costs(self):
        # 1M input @ $15 = $15.00
        rate = tb._lookup_rate("claude-opus-4-7")
        self.assertEqual(tb._compute_cost_usd(1_000_000, 0, 0, 0, rate), 15.0)

    def test_mixed_token_types(self):
        # 1000 in + 500 out + 2000 cache_read + 100 cache_creation @ opus
        # = 1000*15/1M + 500*75/1M + 2000*1.5/1M + 100*18.75/1M
        # = 0.015 + 0.0375 + 0.003 + 0.001875 = 0.057375
        rate = tb._lookup_rate("claude-opus-4-7")
        self.assertEqual(tb._compute_cost_usd(1000, 500, 2000, 100, rate), 0.057375)

    def test_zero_tokens_zero_cost(self):
        rate = tb._lookup_rate("claude-sonnet-4-6")
        self.assertEqual(tb._compute_cost_usd(0, 0, 0, 0, rate), 0.0)

    def test_sonnet_costs(self):
        # 100k input @ $3 = $0.30
        rate = tb._lookup_rate("claude-sonnet-4-6")
        self.assertEqual(tb._compute_cost_usd(100_000, 0, 0, 0, rate), 0.30)


class AggregateTurnCostTests(unittest.TestCase):
    def test_single_assistant_entry_opus(self):
        lines = [json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-opus-4-7[1m]",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                "content": [],
            },
        })]
        result = tb.aggregate_turn(lines)
        self.assertEqual(result["turn_total_tokens"], 1500)
        # 1000*15/1M + 500*75/1M = 0.015 + 0.0375 = 0.0525
        self.assertEqual(result["turn_cost_usd"], 0.0525)
        self.assertEqual(result["cost_by_model"], {"claude-opus-4-7": 0.0525})
        self.assertEqual(result["subagent_cost_usd_estimated"], 0.0)
        self.assertEqual(result["price_rates_as_of"], tb.PRICE_RATES_AS_OF)

    def test_multi_model_main_session(self):
        # Simulate compaction: turn spans opus then sonnet
        lines = [
            json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-7",
                    "usage": {"input_tokens": 1000, "output_tokens": 500,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                    "content": [],
                },
            }),
            json.dumps({
                "type": "assistant",
                "message": {
                    "model": "claude-sonnet-4-6",
                    "usage": {"input_tokens": 2000, "output_tokens": 1000,
                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                    "content": [],
                },
            }),
        ]
        result = tb.aggregate_turn(lines)
        # opus: 1000*15/1M + 500*75/1M = 0.0525
        # sonnet: 2000*3/1M + 1000*15/1M = 0.006 + 0.015 = 0.021
        # total: 0.0735
        self.assertAlmostEqual(result["turn_cost_usd"], 0.0735, places=6)
        self.assertAlmostEqual(result["cost_by_model"]["claude-opus-4-7"], 0.0525, places=6)
        self.assertAlmostEqual(result["cost_by_model"]["claude-sonnet-4-6"], 0.021, places=6)

    def test_unknown_model_records_null_cost_does_not_crash(self):
        lines = [json.dumps({
            "type": "assistant",
            "message": {
                "model": "exotic-future-model",
                "usage": {"input_tokens": 1000, "output_tokens": 500,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                "content": [],
            },
        })]
        result = tb.aggregate_turn(lines)
        # No rate found → cost_by_model entry is None
        # The normalised key keeps the model name visible for diagnostics
        self.assertEqual(result["cost_by_model"]["exotic-future-model"], None)
        # main session cost is 0 since no rates applied
        self.assertEqual(result["turn_cost_usd"], 0.0)

    def test_no_model_field_falls_back_to_unknown_bucket(self):
        lines = [json.dumps({
            "type": "assistant",
            "message": {
                "usage": {"input_tokens": 1000, "output_tokens": 500,
                          "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                "content": [],
            },
        })]
        result = tb.aggregate_turn(lines)
        self.assertIn("unknown", result["main_session_by_model"])
        self.assertEqual(result["cost_by_model"]["unknown"], None)


if __name__ == "__main__":
    unittest.main()
