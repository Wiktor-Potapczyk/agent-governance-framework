#!/usr/bin/env python3
"""Tests for mine_governance.py: REV-1..REV-6 acceptance criteria.

Two test classes:
  A) SyntheticFixtureTests: unit tests against a hand-authored fixture
     with known patterns; fully deterministic (fixed now_date).
  B) RealDataTests: property assertions against the live governance-log.jsonl
     (skipped gracefully if file absent).

Run: python .claude/hooks/test_mine_governance.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date

# Ensure the hooks dir is on the path
_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HOOKS_DIR)

from mine_governance import (
    DEFAULT_C,
    DEFAULT_D,
    HIGH_SEV_C,
    WINDOW_DAYS,
    mine,
    _sig_id,
    _sig_key,
    _normalize_reason,
)

_VAULT = os.path.normpath(os.path.join(_HOOKS_DIR, "..", ".."))
_FIXTURES_DIR = os.path.join(_HOOKS_DIR, "_test_fixtures")
_FIXTURE_LOG = os.path.join(_FIXTURES_DIR, "governance-log-sample.jsonl")
_FIXTURE_LEDGER = os.path.join(_FIXTURES_DIR, "miner-resolved-fixture.jsonl")
_REAL_LOG = os.path.join(_VAULT, ".claude", "hooks", "governance-log.jsonl")

# Fixed reference date: all synthetic tests use this for determinism
_NOW = date(2026, 6, 10)


class SyntheticFixtureTests(unittest.TestCase):
    """Unit tests against _test_fixtures/governance-log-sample.jsonl."""

    def _run(self, ledger=None):
        return mine(_FIXTURE_LOG, _NOW, window_days=WINDOW_DAYS, resolved_ledger_path=ledger)

    # ------------------------------------------------------------------
    # Helper: find a sig record by matching multiple criteria
    # ------------------------------------------------------------------
    def _find(self, results, **criteria):
        for r in results:
            if all(r.get(k) == v for k, v in criteria.items()):
                return r
        return None

    # ------------------------------------------------------------------
    # Fixture sanity
    # ------------------------------------------------------------------
    def test_fixture_file_exists(self):
        self.assertTrue(os.path.isfile(_FIXTURE_LOG), f"Fixture not found: {_FIXTURE_LOG}")

    def test_fixture_ledger_exists(self):
        self.assertTrue(os.path.isfile(_FIXTURE_LEDGER), f"Ledger fixture not found: {_FIXTURE_LEDGER}")

    # ------------------------------------------------------------------
    # CASE A: recurring failure count=12 across 4 days → FLAGGED
    # ------------------------------------------------------------------
    def test_recurring_failure_flagged(self):
        results = self._run()
        # dispatch-compliance / pm-orchestrator / block: count=12 across 4 days
        rec = self._find(results, event_label="block", hook="dispatch-compliance", agent_type="pm-orchestrator")
        self.assertIsNotNone(rec, "Expected block/dispatch-compliance/pm-orchestrator to be flagged")
        self.assertGreaterEqual(rec["count"], DEFAULT_C)
        self.assertGreaterEqual(rec["distinct_days"], DEFAULT_D)
        self.assertFalse(rec["suppressed"])
        self.assertFalse(rec["regression"])

    # ------------------------------------------------------------------
    # CASE A (normalization): char-count variants collapse to ONE sig_id
    # The fixture has block_reason="Missing must-dispatch declaration (N items)"
    # with varying N: 1, 2, 5, 3 → all should collapse to same normalized reason
    # ------------------------------------------------------------------
    def test_normalization_collapses_digit_variants(self):
        norm_variants = [
            _normalize_reason("Missing must-dispatch declaration (1 items)"),
            _normalize_reason("Missing must-dispatch declaration (2 items)"),
            _normalize_reason("Missing must-dispatch declaration (5 items)"),
            _normalize_reason("Missing must-dispatch declaration (3 items)"),
        ]
        # All should be identical after normalization
        self.assertEqual(len(set(norm_variants)), 1, f"Expected 1 unique, got: {set(norm_variants)}")
        # The miner should produce exactly ONE sig_id for this failure class
        results = self._run()
        block_pm = [r for r in results if r["event_label"] == "block" and r["agent_type"] == "pm-orchestrator"]
        self.assertEqual(len(block_pm), 1, f"Expected 1 block/pm-orchestrator sig, got {len(block_pm)}")

    # ------------------------------------------------------------------
    # REV-1: two different agent_types with no_classification → TWO sig_ids
    # Fixture lines use event='agent_dispatched' + outcome='no_classification'.
    # After D2 fix: _failure_label() returns 'no_classification' (not 'agent_dispatched')
    # because agent_dispatched is a noise event.  The sig_key still includes agent_type,
    # so the two sigs remain distinct.
    # ------------------------------------------------------------------
    def test_rev1_distinct_agent_types_produce_distinct_sig_ids(self):
        results = self._run()
        # Look up by hook + agent_type (label is now 'no_classification' after D2)
        pm_sig = self._find(results, hook="agent-dispatch-check", agent_type="pm-orchestrator")
        arch_sig = self._find(results, hook="agent-dispatch-check", agent_type="n8n-workflow-architect")
        self.assertIsNotNone(pm_sig, "pm-orchestrator agent-dispatch-check sig not flagged")
        self.assertIsNotNone(arch_sig, "n8n-workflow-architect agent-dispatch-check sig not flagged")
        self.assertNotEqual(
            pm_sig["sig_id"], arch_sig["sig_id"],
            "REV-1 FAIL: different agent_types collapsed to same sig_id"
        )
        # Verify the outcome is reflected in the normalized_signature or raw samples
        # (i.e. the no_classification outcome is not silently dropped)
        self.assertIn("agent_type", pm_sig)
        self.assertEqual(pm_sig["agent_type"], "pm-orchestrator")
        self.assertEqual(arch_sig["agent_type"], "n8n-workflow-architect")

    # ------------------------------------------------------------------
    # CASE C: one-off count=2 across 1 day → NOT flagged
    # ------------------------------------------------------------------
    def test_oneoff_not_flagged(self):
        results = self._run()
        # deny/bash-safety-guard/no-agent-type: only 2 occurrences on 1 day
        rec = self._find(results, event_label="deny", hook="bash-safety-guard", agent_type="")
        self.assertIsNone(rec, "One-off (count=2, 1 day) should NOT be flagged")

    # ------------------------------------------------------------------
    # REV-3: high-severity fabrication_detected at count=3 over 3 days → FLAGGED
    # ------------------------------------------------------------------
    def test_rev3_high_severity_flagged_at_low_count(self):
        results = self._run()
        rec = self._find(results, event_label="fabrication_detected", hook="work-verification-check")
        self.assertIsNotNone(rec, "fabrication_detected count=3/3days should be flagged (C=HIGH_SEV_C=3)")
        self.assertEqual(rec["severity"], "high")
        self.assertEqual(rec["count"], 3)
        self.assertEqual(rec["distinct_days"], 3)

    # ------------------------------------------------------------------
    # REV-3: normal event at count=3 → NOT flagged (needs DEFAULT_C=10)
    # ------------------------------------------------------------------
    def test_rev3_normal_severity_not_flagged_at_low_count(self):
        results = self._run()
        rec = self._find(results, event_label="classifier_field_missing", hook="classifier-field-check")
        self.assertIsNone(rec, "Normal-severity event at count=3 should NOT be flagged (DEFAULT_C=10)")

    # ------------------------------------------------------------------
    # CASE F: suppressed sig present in fixture ledger → SUPPRESSED (absent from results)
    # sig: reviewer_scope_violation / architect-reviewer / reviewer-scope-violation-check
    # resolved_ts = 2026-05-10, all occurrences are 2026-05-14..17 (after resolved_ts)
    # Wait: architect-reviewer occurrences ARE after resolved_ts. But with only 12
    # occurrences across 4 days, AND ledger entry present, regression check:
    # post_resolved_count must also meet threshold.
    # The fixture has 12 lines for architect-reviewer, all AFTER resolved_ts 2026-05-10.
    # So post_resolved_count=12, post_resolved_dates=4 days → meets C=10,D=3 → REGRESSION.
    # But the intent is suppression. We need the ledger resolved_ts AFTER all occurrences.
    # The fixture has resolved_ts=2026-05-10 but occurrences at 2026-05-14..17.
    # That makes them ALL post-resolved → regression, not suppression.
    # FIXED DESIGN: suppression test uses ledger resolved_ts AFTER all occurrences (2026-05-20).
    # The fixture ledger has 59c75cff3762 resolved_ts=2026-05-10: this becomes regression.
    # We test suppression with a fresh ledger where resolved_ts is after last occurrence (2026-05-18).
    # ------------------------------------------------------------------
    def test_suppressed_sig_absent_from_results(self):
        # Build a temp ledger where resolved_ts is 2026-05-18: AFTER all
        # architect-reviewer occurrences (2026-05-14..17). The sig has count=12/4days
        # but resolved_ts is past all of them, so no post-resolved occurrences → suppressed.
        nr = _normalize_reason("REVIEWER SCOPE: Edit blocked")
        key = _sig_key("reviewer_scope_violation", "architect-reviewer", "reviewer-scope-violation-check", nr)
        sid = _sig_id(key)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
            tf.write(json.dumps({
                "sig_id": sid,
                "resolved_ts": "2026-05-18",
                "resolution": "hook-tuned",
                "note": "suppression test",
            }) + "\n")
            ledger_path = tf.name
        try:
            results = mine(_FIXTURE_LOG, _NOW, window_days=WINDOW_DAYS, resolved_ledger_path=ledger_path)
            rec = self._find(results, event_label="reviewer_scope_violation", agent_type="architect-reviewer")
            self.assertIsNone(rec, f"sig_id={sid} should be SUPPRESSED (all occurrences before resolved_ts)")
        finally:
            os.unlink(ledger_path)

    # ------------------------------------------------------------------
    # CASE G: regression: suppressed sig with new occurrences AFTER resolved_ts → RE-SURFACES
    # sig: reviewer_scope_violation / blueprint-mode / reviewer-scope-violation-check
    # resolved_ts = 2026-05-17, new occurrences at 2026-05-22..25
    # ------------------------------------------------------------------
    def test_regression_resurfaces(self):
        results = mine(_FIXTURE_LOG, _NOW, window_days=WINDOW_DAYS, resolved_ledger_path=_FIXTURE_LEDGER)
        rec = self._find(results, event_label="reviewer_scope_violation", agent_type="blueprint-mode")
        self.assertIsNotNone(rec, "Regression sig should RE-SURFACE after new occurrences past resolved_ts")
        self.assertTrue(rec["regression"], "Record should carry regression=True")
        self.assertFalse(rec["suppressed"])

    # ------------------------------------------------------------------
    # Bad lines: unparseable JSON / missing fields / unknown schema → no crash
    # ------------------------------------------------------------------
    def test_bad_lines_skipped_no_error(self):
        # Should not raise; bad lines are silently skipped
        try:
            results = self._run()
        except Exception as e:
            self.fail(f"mine() raised on bad lines: {e}")
        # heartbeat / unknown-schema lines should not produce sig records
        # (the fixture includes a '{bad json line}' and an unknown-schema heartbeat)

    def test_unknown_schema_not_admitted_if_no_failure_field(self):
        # The fixture has a line with schema=99 and event='heartbeat': not admitted
        results = self._run()
        # heartbeat event is not in the failure allowlist; no sig for it
        heartbeat_sigs = [r for r in results if r.get("event_label") == "heartbeat"]
        self.assertEqual(len(heartbeat_sigs), 0)

    def test_unknown_schema_admitted_if_deny_event(self):
        # The fixture has a line with schema='v_unknown' and event='deny': ADMITTED
        # It only has count=1 so won't be flagged, but shouldn't crash
        try:
            results = self._run()
        except Exception as e:
            self.fail(f"Unknown-schema deny line caused error: {e}")

    # ------------------------------------------------------------------
    # REV-6: sig records carry expected fields
    # ------------------------------------------------------------------
    def test_sig_record_has_required_fields(self):
        results = self._run()
        self.assertTrue(len(results) > 0, "Expected at least one flagged sig")
        required = {
            "sig_id", "severity", "event_label", "agent_type", "hook",
            "normalized_signature", "count", "distinct_days", "first_seen",
            "last_seen", "top_tool_name", "raw_samples", "bucket",
            "suppressed", "regression",
        }
        for rec in results:
            missing = required - set(rec.keys())
            self.assertEqual(missing, set(), f"sig {rec['sig_id']} missing fields: {missing}")

    def test_raw_samples_max_3(self):
        results = self._run()
        for rec in results:
            self.assertLessEqual(len(rec["raw_samples"]), 3, f"sig {rec['sig_id']} has >3 samples")

    def test_high_severity_sorted_first(self):
        results = self._run()
        if len(results) < 2:
            return
        saw_normal = False
        for rec in results:
            if rec["severity"] == "normal":
                saw_normal = True
            elif rec["severity"] == "high" and saw_normal:
                self.fail("High-severity sig appears after a normal-severity sig: sort order wrong")

    # ------------------------------------------------------------------
    # now_date determinism: passing a string should work the same as a date
    # ------------------------------------------------------------------
    def test_now_date_accepts_string(self):
        r1 = mine(_FIXTURE_LOG, _NOW, window_days=WINDOW_DAYS)
        r2 = mine(_FIXTURE_LOG, _NOW.isoformat(), window_days=WINDOW_DAYS)
        self.assertEqual(len(r1), len(r2), "String and date now_date should produce same result")
        ids1 = {r["sig_id"] for r in r1}
        ids2 = {r["sig_id"] for r in r2}
        self.assertEqual(ids1, ids2)

    # ------------------------------------------------------------------
    # D1: dark-zone severity derived from per-record severity field
    # ------------------------------------------------------------------

    def test_d1_darkzone_low_records_produce_normal_severity_sig(self):
        """D1: dark-zone sig where ALL records have severity=low → sig severity must be normal."""
        results = self._run()
        rec = self._find(results, event_label="dark-zone", agent_type="low-sev-agent")
        self.assertIsNotNone(rec, "low-severity dark-zone sig (count=12/4days) must be flagged")
        self.assertEqual(
            rec["severity"], "normal",
            f"D1 FAIL: dark-zone sig with all low-sev records must have severity=normal, got {rec['severity']}"
        )
        # Must flag via normal C=10 gate (count ≥ 10, distinct_days ≥ 3)
        self.assertGreaterEqual(rec["count"], DEFAULT_C)
        self.assertGreaterEqual(rec["distinct_days"], DEFAULT_D)

    def test_d1_darkzone_high_records_produce_high_severity_sig(self):
        """D1: dark-zone sig where records have severity=high → sig severity must be high."""
        results = self._run()
        rec = self._find(results, event_label="dark-zone", agent_type="high-sev-agent")
        self.assertIsNotNone(rec, "high-severity dark-zone sig (count=3/3days) must be flagged (C=HIGH_SEV_C=3)")
        self.assertEqual(
            rec["severity"], "high",
            f"D1 FAIL: dark-zone sig with severity=high records must have severity=high, got {rec['severity']}"
        )
        # Must flag via HIGH_SEV_C=3 gate
        self.assertEqual(rec["count"], 3)
        self.assertEqual(rec["distinct_days"], 3)

    def test_d1_darkzone_low_sig_not_flagged_at_count_three(self):
        """D1: a dark-zone sig with only 3 low-sev records should NOT flag (needs C=10 not C=3)."""
        # Build a small temp log with 3 dark-zone low-sev records across 3 days
        import tempfile
        lines = [
            '{"ts": "2026-05-20 08:00:00", "event": "dark-zone", "hook": "dz", "severity": "low", "reason": "rate check"}\n',
            '{"ts": "2026-05-21 08:00:00", "event": "dark-zone", "hook": "dz", "severity": "low", "reason": "rate check"}\n',
            '{"ts": "2026-05-22 08:00:00", "event": "dark-zone", "hook": "dz", "severity": "low", "reason": "rate check"}\n',
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8") as tf:
            tf.writelines(lines)
            tmp_path = tf.name
        try:
            results = mine(tmp_path, _NOW, window_days=WINDOW_DAYS)
            dz_sigs = [r for r in results if r["event_label"] == "dark-zone"]
            self.assertEqual(
                len(dz_sigs), 0,
                "D1 FAIL: dark-zone with 3 low-sev records must NOT flag at C=3 (that gate is for high-sev only)"
            )
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # D2: noise-event (agent_dispatched) + outcome=no_classification → label is no_classification
    # ------------------------------------------------------------------

    def test_d2_agent_dispatched_label_is_no_classification(self):
        """D2: records with event=agent_dispatched + outcome=no_classification must produce
        event_label='no_classification', NOT 'agent_dispatched'."""
        results = self._run()
        # Locate the pm-orchestrator agent-dispatch-check sig (fixture lines 13-24)
        rec = self._find(results, hook="agent-dispatch-check", agent_type="pm-orchestrator")
        self.assertIsNotNone(rec, "pm-orchestrator agent-dispatch-check sig must be flagged")
        self.assertEqual(
            rec["event_label"], "no_classification",
            f"D2 FAIL: event_label must be 'no_classification', got '{rec['event_label']}'"
        )

    def test_d2_no_sig_labeled_agent_dispatched(self):
        """D2: no flagged sig should carry event_label='agent_dispatched': that is a noise event name."""
        results = self._run()
        bad = [r for r in results if r["event_label"] == "agent_dispatched"]
        self.assertEqual(
            len(bad), 0,
            f"D2 FAIL: {len(bad)} sigs still labeled 'agent_dispatched': {[r['sig_id'] for r in bad]}"
        )

    def test_d2_two_no_classification_sigs_still_distinct(self):
        """D2: after relabeling, the two agent_types (pm-orchestrator, n8n-workflow-architect)
        must still produce DISTINCT sig_ids (the per-agent split from REV-1 is preserved)."""
        results = self._run()
        pm_sig   = self._find(results, hook="agent-dispatch-check", agent_type="pm-orchestrator")
        arch_sig = self._find(results, hook="agent-dispatch-check", agent_type="n8n-workflow-architect")
        self.assertIsNotNone(pm_sig,   "pm-orchestrator no_classification sig must be flagged")
        self.assertIsNotNone(arch_sig, "n8n-workflow-architect no_classification sig must be flagged")
        self.assertNotEqual(
            pm_sig["sig_id"], arch_sig["sig_id"],
            "D2 FAIL: distinct agent_types collapsed to same sig_id after relabeling"
        )
        # Both must now show event_label = no_classification
        self.assertEqual(pm_sig["event_label"],   "no_classification")
        self.assertEqual(arch_sig["event_label"], "no_classification")

    # ------------------------------------------------------------------
    # D5: path normalization does not collapse fractions
    # ------------------------------------------------------------------

    def test_d5_fraction_not_collapsed(self):
        """D5: '50/100' and '3/10' must normalize without collapsing the fraction to <path>.
        Note: _normalize_reason lowercases output, so the token is '<path>' not '<PATH>'."""
        from mine_governance import _normalize_reason
        norm_50_100 = _normalize_reason("50/100 rate")
        norm_3_10   = _normalize_reason("3/10 rate")
        # Neither should contain '<path>' (the lowercased collapse token)
        self.assertNotIn("<path>", norm_50_100, "D5 FAIL: '50/100 rate' was collapsed to <path>")
        self.assertNotIn("<path>", norm_3_10,   "D5 FAIL: '3/10 rate' was collapsed to <path>")

    def test_d5_genuine_paths_still_collapsed(self):
        """D5: real Windows and relative paths must still normalize to '<path>' (lowercased)."""
        from mine_governance import _normalize_reason
        cases = [
            r"C:\Users\x\y\file.txt",
            "./rel/path/foo",
            "../up/path/bar",
        ]
        for path_str in cases:
            norm = _normalize_reason(path_str)
            self.assertIn(
                "<path>", norm,
                f"D5 FAIL: genuine path '{path_str}' was NOT collapsed; got '{norm}'"
            )

    def test_d5_posix_absolute_path_collapsed(self):
        """D5: POSIX absolute path /home/foo/bar must be collapsed to '<path>' (lowercased)."""
        from mine_governance import _normalize_reason
        norm = _normalize_reason("/home/foo/bar")
        self.assertIn("<path>", norm, f"D5 FAIL: '/home/foo/bar' was not collapsed; got '{norm}'")


class RealDataTests(unittest.TestCase):
    """REV-4: property assertions against the live governance-log.jsonl."""

    def setUp(self):
        if not os.path.isfile(_REAL_LOG):
            self.skipTest(f"Real log absent: {_REAL_LOG}")

    def _max_log_date(self):
        max_d = None
        with open(_REAL_LOG, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                ts = d.get("ts", "") or ""
                if len(ts) >= 10:
                    day = ts[:10]
                    if max_d is None or day > max_d:
                        max_d = day
        return date.fromisoformat(max_d) if max_d else date.today()

    def test_no_exception_on_real_data(self):
        now = self._max_log_date()
        try:
            results = mine(_REAL_LOG, now)
        except Exception as e:
            self.fail(f"mine() raised on real data: {e}")

    def test_result_is_list(self):
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        self.assertIsInstance(results, list)

    def test_at_least_one_flagged_sig(self):
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        self.assertGreater(len(results), 0, "Expected ≥1 flagged sig on real data")

    def test_rev1_no_classification_not_collapsed(self):
        """REV-1: no_classification sigs for different agent_types must have distinct sig_ids."""
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        # After D2: agent_dispatched records are relabeled to no_classification.
        # Only "no_classification" will appear; "agent_dispatched" is a noise event name.
        no_class_sigs = [r for r in results if r["event_label"] == "no_classification"
                         and r.get("agent_type")]
        if len(no_class_sigs) < 2:
            # Not enough data to assert; pass with a note
            return
        agent_types_seen = set(r["agent_type"] for r in no_class_sigs)
        if len(agent_types_seen) < 2:
            return
        sig_ids = [r["sig_id"] for r in no_class_sigs]
        # If multiple agent_types present, sig_ids must not all be the same
        self.assertGreater(
            len(set(sig_ids)), 1,
            "REV-1 FAIL on real data: multiple agent_types collapsed to one sig_id"
        )

    def test_all_results_have_required_fields(self):
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        required = {
            "sig_id", "severity", "event_label", "agent_type", "hook",
            "normalized_signature", "count", "distinct_days", "first_seen",
            "last_seen", "top_tool_name", "raw_samples", "bucket",
            "suppressed", "regression",
        }
        for rec in results:
            missing = required - set(rec.keys())
            self.assertEqual(missing, set(), f"Real-data sig {rec['sig_id']} missing fields: {missing}")

    def test_counts_are_sane(self):
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        for rec in results:
            self.assertGreaterEqual(rec["count"], DEFAULT_C if rec["severity"] != "high" else HIGH_SEV_C)
            self.assertGreaterEqual(rec["distinct_days"], DEFAULT_D)
            self.assertLessEqual(len(rec["raw_samples"]), 3)

    def test_severity_sort_order(self):
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        saw_normal = False
        for rec in results:
            if rec["severity"] == "normal":
                saw_normal = True
            elif rec["severity"] == "high" and saw_normal:
                self.fail("Real-data sort: high-severity sig after normal-severity sig")

    def test_reviewer_scope_keyed_by_agent_and_hook(self):
        """reviewer_scope_violation sigs should retain agent_type + hook in their key."""
        now = self._max_log_date()
        results = mine(_REAL_LOG, now)
        rv_sigs = [r for r in results if "reviewer_scope_violation" in r["event_label"]]
        # May be suppressed or aged out; if present, verify fields are set
        for r in rv_sigs:
            self.assertTrue(r["hook"] or r["agent_type"],
                            f"reviewer_scope_violation sig {r['sig_id']} has no hook or agent_type")


class AdversarialRobustnessTests(unittest.TestCase):
    """Pentest regression locks (2026-06-07): mine() must never crash on a
    malformed log line: the spec requires 'skip, never error'. Each of these
    crashed a pre-fix build; they must stay green."""

    def _mine_lines(self, lines, ledger_lines=None):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as f:
            f.write("\n".join(lines))
            logp = f.name
        ledp = None
        if ledger_lines is not None:
            with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                             encoding="utf-8") as f:
                f.write("\n".join(ledger_lines))
                ledp = f.name
        try:
            return mine(logp, _NOW, window_days=30, resolved_ledger_path=ledp)
        finally:
            os.unlink(logp)
            if ledp:
                os.unlink(ledp)

    def test_valid_json_but_not_dict_is_skipped(self):
        # bare list / string / number / null are valid JSON but not records
        try:
            res = self._mine_lines(['[1,2,3]', '"a string"', '42', 'null', '{}'])
        except Exception as e:
            self.fail(f"mine() crashed on valid-non-dict JSON lines: {e}")
        self.assertEqual(res, [])

    def test_nonstring_ts_is_coerced_not_crash(self):
        try:
            res = self._mine_lines([
                '{"event":"deny","block_reason":"r","ts":12345}',
                '{"event":"deny","block_reason":"r","ts":null}',
            ])
        except Exception as e:
            self.fail(f"mine() crashed on non-string ts: {e}")
        self.assertEqual(res, [])  # neither has a usable 10-char date

    def test_nonstring_failure_fields_are_coerced_not_crash(self):
        # agent_type:int, hook:dict, event:list, reason:dict: all must coerce
        lines = [
            ('{"event":"deny","agent_type":123,"hook":{"n":1},'
             '"block_reason":"x","ts":"2026-06-0%d 10:00:00"}' % d)
            for d in range(1, 9)
        ] * 2  # count 16 over 8 days -> would flag if it didn't crash
        try:
            res = self._mine_lines(lines)
        except Exception as e:
            self.fail(f"mine() crashed on non-string failure fields: {e}")
        # it should flag the (coerced) signature, proving it processed cleanly
        self.assertTrue(any(r["count"] >= DEFAULT_C for r in res))

    def test_huge_block_reason_does_not_crash(self):
        big = "x" * 100000
        try:
            res = self._mine_lines(
                ['{"event":"block","block_reason":"%s","ts":"2026-06-07 10:00:00"}' % big])
        except Exception as e:
            self.fail(f"mine() crashed on 100KB block_reason: {e}")
        self.assertIsInstance(res, list)

    def test_malformed_ledger_does_not_crash(self):
        lines = ['{"event":"deny","agent_type":"a","hook":"h",'
                 '"block_reason":"x","ts":"2026-06-0%d 10:00:00"}' % d
                 for d in range(1, 9)] * 2
        bad_ledger = ['GARBAGE', '{"sig_id":12345,"resolved_ts":"bad"}', '[1,2]',
                      '{"resolved_ts":"2026-06-01"}', '{"sig_id":"abc","resolved_ts":null}']
        try:
            res = self._mine_lines(lines, ledger_lines=bad_ledger)
        except Exception as e:
            self.fail(f"mine() crashed on malformed resolved-ledger: {e}")
        self.assertIsInstance(res, list)


# ---------------------------------------------------------------------------
# HERMES P4: warn-event miner (mine_warns) tests (2026-08-18)
# Plan: Projects/your-project/work/2026-08-17-hermes-p4-warn-event-miner-plan.md
# Build plan: .../2026-08-18-hermes-p4-build-implementation-plan.md
# Fixture: _test_fixtures/warn-miner-log-fixture.jsonl (reference date 2026-08-18)
# The pattern literals below are PERMITTED in this test file (fixtures need
# them); the literal ban applies to mine_governance.py source only.
# ---------------------------------------------------------------------------

_WARN_FIXTURE = os.path.join(_FIXTURES_DIR, "warn-miner-log-fixture.jsonl")
_WARN_NOW = date(2026, 8, 18)

_P4_PUSH = "git push (publication is effectively irreversible)"
_P4_RM = "rm on unflagged relative file (irreversible delete)"
_P4_CURL = "external curl write (remote state mutation)"
_P4_CURLV = _P4_CURL + " [self-hosted target]"


class _WarnMinerBase(unittest.TestCase):
    """Guarded per-test import (implementation-plan flag 3, done in setUp rather
    than setUpClass so EVERY new test individually reports red before mine_warns
    exists, without breaking collection of the pre-existing classes)."""

    def setUp(self):
        import mine_governance as mg
        self.mg = mg
        if not hasattr(mg, "mine_warns"):
            self.fail("mine_warns does not exist yet (B2 red state)")
        self.mine_warns = mg.mine_warns

    def _run(self, ledger=None, log=None):
        return self.mine_warns(log or _WARN_FIXTURE, _WARN_NOW, window_days=30,
                               resolved_ledger_path=ledger)

    def _push_candidate(self, result):
        for c in result["candidates"]:
            if c["pattern"] == _P4_PUSH and c.get("agent_type", "") == "":
                return c
        return None

    def _push_sig_id(self):
        key = _sig_key("warn", "", "bash-safety-guard", _normalize_reason(_P4_PUSH))
        return _sig_id(key)


class WarnMinerTests(_WarnMinerBase):
    """B2 red tests 1-11 of the implementation plan."""

    # -- threshold gating -------------------------------------------------
    def test_push_cluster_promotes(self):
        res = self._run()
        c = self._push_candidate(res)
        self.assertIsNotNone(c, "push-warn cluster (17/4d/3s) must promote")
        self.assertEqual(c["count"], 17)
        self.assertEqual(c["distinct_days"], 4)
        self.assertEqual(c["distinct_sessions"], 3)
        self.assertEqual(c["hook"], "bash-safety-guard")
        self.assertEqual(c["severity"], "normal")
        self.assertEqual(c["first_seen"], "2026-08-05")
        self.assertEqual(c["last_seen"], "2026-08-08")
        self.assertAlmostEqual(c["top_session_share"], 11.0 / 17.0, places=6)
        self.assertTrue(1 <= len(c["command_prefix_samples"]) <= 3)
        self.assertEqual(c["sig_id"], self._push_sig_id())

    def test_below_count_cluster_not_promoted(self):
        res = self._run()
        bad = [c for c in res["candidates"] if c.get("agent_type") == "builder-agent"]
        self.assertEqual(bad, [], "count-5 cluster must fail the C=10 gate")

    def test_session_floor_boundary_both_sides(self):
        self.assertEqual(self.mg.WARN_MIN_SESSIONS, 3)
        res = self._run()
        floor = [c for c in res["candidates"] if c.get("agent_type") == "floor-agent"]
        self.assertEqual(floor, [], "12/4d but only 2 sessions must fail the session floor")
        # boundary from the passing side: push cluster has EXACTLY 3 sessions
        c = self._push_candidate(res)
        self.assertIsNotNone(c)
        self.assertEqual(c["distinct_sessions"], self.mg.WARN_MIN_SESSIONS)

    # -- load-bearing negative -------------------------------------------
    def test_negative_deny_tier_cluster_yields_nothing_at_any_count(self):
        res = self._run()
        self.assertIsNone(
            next((c for c in res["candidates"] if c["pattern"] == _P4_RM), None),
            "deny-tier pattern must NEVER be a candidate")
        self.assertTrue(any(_P4_RM in ln for ln in res["drift_lines"]),
                        "drift note must name the deny-tier pattern")
        self.assertNotIn(_P4_RM, res["warn_variant_counts"])
        self.assertNotIn(_P4_RM, res["unrecognized_counts"])
        # parameterized 50 / 500 variants, preserving 10 distinct days + 6 sessions
        sessions = ["0c0c000%d-000%d-4001-8001-00000000000%d" % (i, i, i)
                    for i in range(1, 7)]
        for total in (50, 500):
            per_day = total // 10
            lines = []
            n = 0
            for i in range(10):
                for j in range(per_day):
                    n += 1
                    lines.append(json.dumps({
                        "ts": "2026-07-%02d %02d:%02d:00" % (20 + i, 8 + (j % 12), j % 60),
                        "schema": 2, "event": "warn", "hook": "bash-safety-guard",
                        "session": sessions[n % 6], "environment": "prod",
                        "pattern": _P4_RM, "command_prefix": "rm notes.md"}))
            fd, path = tempfile.mkstemp(suffix=".jsonl")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
                res_n = self._run(log=path)
                self.assertEqual(
                    res_n["candidates"], [],
                    "deny-tier warn cluster at count %d produced candidates" % total)
                self.assertTrue(any(_P4_RM in ln for ln in res_n["drift_lines"]))
            finally:
                os.unlink(path)

    # -- curl pair (fixture g) -------------------------------------------
    def test_curl_pair_classification(self):
        res = self._run()
        # bare deny reason: drift-alarms, never proposes
        self.assertTrue(
            any(("'" + _P4_CURL + "'") in ln for ln in res["drift_lines"]),
            "bare curl deny reason must drift-alarm")
        self.assertIsNone(
            next((c for c in res["candidates"] if c["pattern"].startswith(_P4_CURL)), None))
        self.assertNotIn(_P4_CURL, res["warn_variant_counts"])
        # suffixed variant: measured warn-variant, no drift line, no candidacy
        self.assertEqual(res["warn_variant_counts"].get(_P4_CURLV), 1)
        self.assertFalse(any(_P4_CURLV in ln for ln in res["drift_lines"]),
                         "suffixed warn variant must NOT drift-alarm")
        self.assertNotIn(_P4_CURLV, res["unrecognized_counts"])
        # drift lines carry the loud prefix
        for ln in res["drift_lines"]:
            self.assertTrue(ln.startswith(self.mg.WARN_DENY_TIER_DRIFT_PREFIX))

    # -- exclusions (fixtures d + e) --------------------------------------
    def test_patternless_family_counted_not_proposed(self):
        res = self._run()
        self.assertEqual(res["family_counts"].get("work-verification-check"), 3)
        self.assertIsNone(
            next((c for c in res["candidates"] if c["hook"] == "work-verification-check"),
                 None))

    def test_synthetic_sessions_excluded_from_candidacy(self):
        # 3 synthetic-session records (unknown/probe/qa) carry the push pattern;
        # admitted they would make the push count 20. The 17 proves exclusion via
        # the reused _real_session filter, with no new filter in the way.
        res = self._run()
        c = self._push_candidate(res)
        self.assertIsNotNone(c)
        self.assertEqual(c["count"], 17)
        for rec in ({"session": "unknown"}, {"session": "probe"}, {"session": "qa"}):
            self.assertFalse(self.mg._real_session(rec))

    # -- ledger suppression + regression ----------------------------------
    def test_ledger_suppression(self):
        sid = self._push_sig_id()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as tf:
            tf.write(json.dumps({"sig_id": sid, "resolved_ts": "2026-08-10",
                                 "resolution": "test", "note": "warn suppression"}) + "\n")
            ledger = tf.name
        try:
            res = self._run(ledger=ledger)
            self.assertIsNone(self._push_candidate(res),
                              "push sig must be SUPPRESSED (resolved after last occurrence)")
        finally:
            os.unlink(ledger)

    def test_ledger_regression_resurfaces(self):
        sid = self._push_sig_id()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False,
                                         encoding="utf-8") as tf:
            tf.write(json.dumps({"sig_id": sid, "resolved_ts": "2026-08-01",
                                 "resolution": "test", "note": "warn regression"}) + "\n")
            ledger = tf.name
        try:
            res = self._run(ledger=ledger)
            c = self._push_candidate(res)
            self.assertIsNotNone(c, "push sig must RE-SURFACE (17 occurrences after resolved_ts)")
            self.assertTrue(c["regression"])
            self.assertFalse(c["suppressed"])
        finally:
            os.unlink(ledger)

    # -- acceptance proxy (fixture h) -------------------------------------
    def test_acceptance_proxy_accepted_count(self):
        self.assertEqual(self.mg.WARN_ACCEPT_WINDOW_MIN, 10)
        res = self._run()
        c = self._push_candidate(res)
        self.assertIsNotNone(c)
        self.assertEqual(c["accepted_count"], 14,
                         "3 same-hook denies inside 10 min must subtract from 17")
        self.assertTrue(c["acceptance_note"])
        self.assertIn("upper bound", c["acceptance_note"])
        self.assertIn(self.mg.WARN_ACCEPTANCE_BLINDNESS_NOTE, c["acceptance_note"])

    # -- literal ban + call-derivation ------------------------------------
    def test_literal_ban_in_miner_source(self):
        src_path = os.path.join(_HOOKS_DIR, "mine_governance.py")
        with open(src_path, encoding="utf-8") as fh:
            src = fh.read()
        for banned in ("irreversible delete", "remote state mutation",
                       "self-hosted target"):
            self.assertNotIn(banned, src,
                             "banned literal %r found in mine_governance.py" % banned)

    def test_monkeypatch_call_derivation(self):
        import types
        real = self.mg._load_surface_module()
        stub = types.SimpleNamespace(
            IRREVERSIBLE_BASH_PATTERNS=real.IRREVERSIBLE_BASH_PATTERNS,
            IRREVERSIBLE_MCP_TOOLS=real.IRREVERSIBLE_MCP_TOOLS,
            curl_external_write=lambda cmd: (True, "HERMES-MARKER"),
        )
        W, D = self.mg._derive_exclusion_sets(surface_module=stub)
        self.assertIn("HERMES-MARKER", D,
                      "curl reason must flow from the predicate CALL into D")

    # -- mine() regression (REV-6 invariant) ------------------------------
    def test_mine_failure_pass_regression_unchanged(self):
        # Baseline captured at B0 (2026-08-18) over governance-log-sample.jsonl
        # with now=2026-06-10: byte-stable sig_ids, counts, severities, labels.
        expected = sorted([
            "1258d8ebe419:3:high:fabrication_detected",
            "1ebc570c6b46:12:normal:no_classification",
            "554f64f6aa37:12:normal:dark-zone",
            "59c75cff3762:12:normal:reviewer_scope_violation",
            "61fc20849104:12:normal:reviewer_scope_violation",
            "980a5789bfeb:12:normal:block",
            "9b65d39b3fe1:3:high:dark-zone",
            "fdc692f7b60f:12:normal:no_classification",
        ])
        res = mine(_FIXTURE_LOG, _NOW, window_days=WINDOW_DAYS)
        got = sorted("%s:%d:%s:%s" % (r["sig_id"], r["count"], r["severity"],
                                      r["event_label"]) for r in res)
        self.assertEqual(got, expected,
                         "mine() output over the existing fixture shifted (REV-6 violation)")

    # -- guard-load side effect -------------------------------------------
    def test_guard_load_no_live_log_side_effect(self):
        if not os.path.isfile(_REAL_LOG):
            self.skipTest("live governance log absent")

        def _count():
            with open(_REAL_LOG, "rb") as fh:
                return sum(1 for _ in fh)

        before = _count()
        mod = self.mg._load_guard_module()
        self.assertTrue(hasattr(mod, "WARN_PATTERNS"))
        after = _count()
        self.assertEqual(before, after,
                         "successful guard load must not write the live governance log")

    # -- return contract ---------------------------------------------------
    def test_return_contract_keys(self):
        res = self._run()
        self.assertEqual(
            set(res.keys()),
            {"candidates", "exclusion_unavailable", "drift_lines",
             "warn_variant_counts", "unrecognized_counts", "family_counts"})
        self.assertIs(res["exclusion_unavailable"], False)
        self.assertIsInstance(res["candidates"], list)
        self.assertIsInstance(res["drift_lines"], list)

    def test_candidate_field_schema(self):
        res = self._run()
        c = self._push_candidate(res)
        self.assertIsNotNone(c)
        required = {
            "sig_id", "pattern", "hook", "agent_type", "severity", "count",
            "distinct_days", "distinct_sessions", "top_session_share",
            "first_seen", "last_seen", "accepted_count", "acceptance_note",
            "command_prefix_samples", "suppressed", "regression",
        }
        missing = required - set(c.keys())
        self.assertEqual(missing, set(), "candidate missing fields: %s" % missing)


class WarnMinerFailClosedTests(_WarnMinerBase):
    """B4 breakage matrix: every broken derivation input fails CLOSED (zero
    candidates + sentinel), asserted positively; paired intact-derivation test."""

    def _assert_sentinel(self, res):
        self.assertIs(res["exclusion_unavailable"], True)
        self.assertEqual(res["candidates"], [])

    def test_guard_path_nonexistent_fails_closed(self):
        bad = os.path.join(_FIXTURES_DIR, "no-such-guard.py")
        res = self.mine_warns(
            _WARN_FIXTURE, _WARN_NOW, window_days=30,
            _derive=lambda: self.mg._derive_exclusion_sets(guard_path=bad))
        self._assert_sentinel(res)

    def test_surface_path_nonexistent_fails_closed(self):
        bad = os.path.join(_FIXTURES_DIR, "no-such-surface.py")
        res = self.mine_warns(
            _WARN_FIXTURE, _WARN_NOW, window_days=30,
            _derive=lambda: self.mg._derive_exclusion_sets(surface_path=bad))
        self._assert_sentinel(res)

    def test_curl_predicate_false_none_fails_closed(self):
        import types
        real = self.mg._load_surface_module()
        stub = types.SimpleNamespace(
            IRREVERSIBLE_BASH_PATTERNS=real.IRREVERSIBLE_BASH_PATTERNS,
            IRREVERSIBLE_MCP_TOOLS=real.IRREVERSIBLE_MCP_TOOLS,
            curl_external_write=lambda cmd: (False, None),
        )
        res = self.mine_warns(
            _WARN_FIXTURE, _WARN_NOW, window_days=30,
            _derive=lambda: self.mg._derive_exclusion_sets(surface_module=stub))
        self._assert_sentinel(res)

    def test_curl_predicate_raises_fails_closed(self):
        import types

        def _boom(cmd):
            raise RuntimeError("synthetic predicate failure")

        real = self.mg._load_surface_module()
        stub = types.SimpleNamespace(
            IRREVERSIBLE_BASH_PATTERNS=real.IRREVERSIBLE_BASH_PATTERNS,
            IRREVERSIBLE_MCP_TOOLS=real.IRREVERSIBLE_MCP_TOOLS,
            curl_external_write=_boom,
        )
        res = self.mine_warns(
            _WARN_FIXTURE, _WARN_NOW, window_days=30,
            _derive=lambda: self.mg._derive_exclusion_sets(surface_module=stub))
        self._assert_sentinel(res)

    def test_derive_callable_raises_fails_closed(self):
        def _boom():
            raise RuntimeError("synthetic derivation failure")

        res = self.mine_warns(_WARN_FIXTURE, _WARN_NOW, window_days=30, _derive=_boom)
        self._assert_sentinel(res)

    def test_intact_derivation_exactly_one_candidate(self):
        res = self._run()
        self.assertIs(res["exclusion_unavailable"], False)
        self.assertEqual(len(res["candidates"]), 1,
                         "intact derivation over the fixture yields exactly the push candidate")
        self.assertEqual(res["candidates"][0]["pattern"], _P4_PUSH)

    def test_loud_note_constants_exist(self):
        self.assertEqual(
            self.mg.WARN_DERIVATION_UNAVAILABLE_NOTE,
            "WARN MINING SKIPPED THIS RUN: canonical-surface derivation failed, "
            "zero proposals emitted.")
        self.assertEqual(self.mg.WARN_DENY_TIER_DRIFT_PREFIX,
                         "DENY-TIER PATTERN SEEN IN WARN LOG")
        self.assertTrue(self.mg.WARN_ACCEPTANCE_BLINDNESS_NOTE)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# REV-7: session admission (2026-07-30)
# ---------------------------------------------------------------------------

class TestRev7SessionAdmission(unittest.TestCase):
    """Synthetic-session lines must not enter mining; real/legacy shapes must."""

    NOW = date(2026, 6, 20)

    def _mine_records(self, records):
        import mine_governance as _mg
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                for r in records:
                    fh.write(json.dumps(r) + "\n")
            return _mg.mine(path, self.NOW, 30)
        finally:
            os.unlink(path)

    @staticmethod
    def _deny(day, session=None, include_session=True):
        rec = {"ts": "2026-06-%02d 10:00:00" % day, "event": "deny",
               "hook": "bash-safety-guard", "block_reason": "rm -rf guard"}
        if include_session:
            rec["session"] = session
        return rec

    def test_unknown_session_excluded(self):
        recs = [self._deny(d, "unknown") for d in range(1, 15)]
        self.assertEqual(self._mine_records(recs), [])

    def test_session_literal_excluded(self):
        recs = [self._deny(d, "session") for d in range(1, 15)]
        self.assertEqual(self._mine_records(recs), [])

    def test_uuid_session_admitted(self):
        recs = [self._deny(d, "692cfdb4-b18") for d in range(1, 15)]
        res = self._mine_records(recs)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["count"], 14)

    def test_missing_session_field_admitted(self):
        recs = [self._deny(d, include_session=False) for d in range(1, 15)]
        self.assertEqual(len(self._mine_records(recs)), 1)

    def test_mixed_counts_real_only(self):
        recs = ([self._deny(d, "692cfdb4-b18") for d in range(1, 13)]
                + [self._deny(d, "unknown") for d in range(1, 29)]
                + [self._deny(1, "test-sess"), self._deny(2, None)])
        res = self._mine_records(recs)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["count"], 12)
