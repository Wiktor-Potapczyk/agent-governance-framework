"""Tests for token-breakdown.py.

Written 2026-09-10; this guard had no suite. It turns a turn's token counts
into a USD figure, which is the number that ends up in session orientation and
in any cost comparison across turns. A silently wrong rate does not look like a
bug, it looks like a cheap turn.

Note on binding. The module is loaded once at import here, but every attribute
is reached INSIDE a test, deliberately. Touching them at module level would
make a disarmed hook fail at collection time, which pytest reports as an error
rather than a failure, and the disarm probe scores that as the weaker ERRORED
verdict. Reaching them inside tests keeps the verdict honest at DETECTED.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from _hooktest import run_isolated

HOOK = "token-breakdown.py"
_spec = importlib.util.spec_from_file_location(
    "token_breakdown", str(Path(__file__).resolve().parent / HOOK))
tb = importlib.util.module_from_spec(_spec)
sys.modules["token_breakdown"] = tb
_spec.loader.exec_module(tb)


# --- model key normalisation --------------------------------------------------

def test_the_million_context_suffix_is_stripped_before_lookup(tmp_path):
    """A 1m-context model is the same model at the same price. Without this the
    entire Opus-on-1m population would price at zero."""
    assert tb._normalise_model_key("claude-opus-4-7[1m]") == "claude-opus-4-7"


@pytest.mark.parametrize("bad", [None, 123, [], {}])
def test_a_non_string_model_normalises_to_empty_not_a_crash(bad):
    assert tb._normalise_model_key(bad) == ""


# --- rate lookup --------------------------------------------------------------

def test_an_exact_model_gets_its_rate():
    assert tb._lookup_rate("claude-opus-4-7") == (15.00, 75.00, 1.50, 18.75)


def test_a_dated_variant_falls_back_to_its_family_prefix():
    """Model ids gain date suffixes; without the prefix fallback every dated
    release would price at nothing until someone hand-added it."""
    assert tb._lookup_rate("claude-sonnet-4-6-20260101") == (3.00, 15.00, 0.30, 3.75)


def test_an_unknown_model_returns_none_rather_than_a_guess():
    """Returning a default rate would put an invented number into a cost
    surface, which is worse than reporting nothing."""
    assert tb._lookup_rate("some-other-vendor-model") is None


# --- cost arithmetic ----------------------------------------------------------

def test_cost_is_computed_per_million_tokens():
    rate = (15.00, 75.00, 1.50, 18.75)
    assert tb._compute_cost_usd(1_000_000, 0, 0, 0, rate) == 15.0
    assert tb._compute_cost_usd(0, 1_000_000, 0, 0, rate) == 75.0


def test_the_four_token_classes_are_priced_separately(tmp_path):
    """Cache reads are an order of magnitude cheaper than input and cache
    creation is more expensive than input. Collapsing them into one rate is the
    single easiest way to be badly wrong on a cached session."""
    rate = (15.00, 75.00, 1.50, 18.75)
    assert tb._compute_cost_usd(0, 0, 1_000_000, 0, rate) == 1.5
    assert tb._compute_cost_usd(0, 0, 0, 1_000_000, rate) == 18.75


def test_costs_sum_across_classes():
    rate = (15.00, 75.00, 1.50, 18.75)
    total = tb._compute_cost_usd(1_000_000, 1_000_000, 1_000_000, 1_000_000, rate)
    assert total == pytest.approx(15.0 + 75.0 + 1.5 + 18.75)


def test_zero_tokens_cost_nothing():
    assert tb._compute_cost_usd(0, 0, 0, 0, (15.0, 75.0, 1.5, 18.75)) == 0.0


@pytest.mark.parametrize("bad", [None, "", "abc", [], {}])
def test_unparseable_token_counts_become_zero_not_an_exception(bad):
    """Usage fields go missing on streamed and errored turns. A crash in a Stop
    hook over a missing count would strand the turn."""
    assert tb._safe_int(bad) == 0


def test_a_numeric_string_token_count_is_accepted():
    assert tb._safe_int("1234") == 1234


# --- FINDING, pinned rather than fixed ----------------------------------------

@pytest.mark.parametrize("model", ["claude-opus-5", "claude-opus-5[1m]",
                                   "claude-sonnet-5", "claude-fable-5"])
def test_no_claude_5_model_has_a_price(model):
    """LIVE GAP, reported not fixed (measured 2026-09-10).

    The rate table stops at the 4.x families and is stamped
    PRICE_RATES_AS_OF 2026-05-23. Nothing in the Claude 5 generation resolves,
    and the family-prefix fallback does not help because claude-opus-5 does not
    start with claude-opus-4. So every turn on the models actually in use
    produces NO cost figure at all.

    Deliberately not fixed here: I do not know the published Claude 5 rates,
    and inventing plausible ones would put fabricated numbers into a cost
    surface that people compare turns with. Silence is the safer wrong answer;
    a made-up rate is the dangerous one. Needs the real published pricing,
    which is an owner action.

    This test fails the day rates are added, which is the intended signal to
    delete it.
    """
    assert tb._lookup_rate(model) is None


def test_the_rate_table_carries_an_as_of_date():
    """A price table without a date cannot be audited for staleness."""
    assert tb.PRICE_RATES_AS_OF


# --- end to end: it is a Stop hook and must never block -----------------------

def transcript(tmp_path, model="claude-opus-4-7"):
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps({"type": "user", "message": {"content": "go"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {
            "model": model,
            "usage": {"input_tokens": 100, "output_tokens": 50,
                      "cache_read_input_tokens": 10,
                      "cache_creation_input_tokens": 5}}}) + "\n",
        encoding="utf-8")
    return str(path)


def test_a_normal_turn_exits_clean(tmp_path):
    proc, _ = run_isolated(HOOK, {"transcript_path": transcript(tmp_path),
                                  "session_id": "s-1"}, tmp_path)
    assert proc.returncode == 0, proc.stderr


def test_a_missing_transcript_does_not_block(tmp_path):
    proc, _ = run_isolated(HOOK, {"transcript_path": str(tmp_path / "no.jsonl")},
                           tmp_path)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("raw", ["", "not json at all"])
def test_malformed_input_does_not_block(raw, tmp_path):
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
