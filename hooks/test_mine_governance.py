#!/usr/bin/env python3
"""Tests for mine_governance.py: REV-1..REV-6 acceptance criteria.

Two test classes:
  A) SyntheticFixtureTests: unit tests against a hand-authored fixture
     with known patterns; fully deterministic (fixed now_date).
  B) RealDataTests: property assertions against the live governance-log.jsonl
     (skipped gracefully if file absent).

Run: python hooks/test_mine_governance.py
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

# Repo root: hooks/ is one level below the repo root
_REPO = os.path.normpath(os.path.join(_HOOKS_DIR, ".."))
_FIXTURES_DIR = os.path.join(_HOOKS_DIR, "_test_fixtures")
_FIXTURE_LOG = os.path.join(_FIXTURES_DIR, "governance-log-sample.jsonl")
_FIXTURE_LEDGER = os.path.join(_FIXTURES_DIR, "miner-resolved-fixture.jsonl")
_REAL_LOG = os.path.join(_REPO, ".claude", "hooks", "governance-log.jsonl")

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
    # CASE A: recurring failure count=12 across 4 days -> FLAGGED
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
    # with varying N: 1, 2, 5, 3 -> all should collapse to same normalized reason
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
    # REV-1: two different agent_types with no_classification -> TWO sig_ids
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
    # CASE C: one-off count=2 across 1 day -> NOT flagged
    # ------------------------------------------------------------------
    def test_oneoff_not_flagged(self):
        results = self._run()
        # deny/bash-safety-guard/no-agent-type: only 2 occurrences on 1 day
        rec = self._find(results, event_label="deny", hook="bash-safety-guard", agent_type="")
        self.assertIsNone(rec, "One-off (count=2, 1 day) should NOT be flagged")

    # ------------------------------------------------------------------
    # REV-3: high-severity fabrication_detected at count=3 over 3 days -> FLAGGED
    # ------------------------------------------------------------------
    def test_rev3_high_severity_flagged_at_low_count(self):
        results = self._run()
        rec = self._find(results, event_label="fabrication_detected", hook="work-verification-check")
        self.assertIsNotNone(rec, "fabrication_detected count=3/3days should be flagged (C=HIGH_SEV_C=3)")
        self.assertEqual(rec["severity"], "high")
        self.assertEqual(rec["count"], 3)
        self.assertEqual(rec["distinct_days"], 3)

    # ------------------------------------------------------------------
    # REV-3: normal event at count=3 -> NOT flagged (needs DEFAULT_C=10)
    # ------------------------------------------------------------------
    def test_rev3_normal_severity_not_flagged_at_low_count(self):
        results = self._run()
        rec = self._find(results, event_label="classifier_field_missing", hook="classifier-field-check")
        self.assertIsNone(rec, "Normal-severity event at count=3 should NOT be flagged (DEFAULT_C=10)")

    # ------------------------------------------------------------------
    # CASE F: suppressed sig present in fixture ledger -> SUPPRESSED (absent from results)
    # sig: reviewer_scope_violation / architect-reviewer / reviewer-scope-violation-check
    # resolved_ts = 2026-05-10, all occurrences are 2026-05-14..17 (after resolved_ts)
    # Wait: architect-reviewer occurrences ARE after resolved_ts. But with only 12
    # occurrences across 4 days, AND ledger entry present, regression check:
    # post_resolved_count must also meet threshold.
    # The fixture has 12 lines for architect-reviewer, all AFTER resolved_ts 2026-05-10.
    # So post_resolved_count=12, post_resolved_dates=4 days -> meets C=10,D=3 -> REGRESSION.
    # But the intent is suppression. We need the ledger resolved_ts AFTER all occurrences.
    # The fixture has resolved_ts=2026-05-10 but occurrences at 2026-05-14..17.
    # That makes them ALL post-resolved -> regression, not suppression.
    # FIXED DESIGN: suppression test uses ledger resolved_ts AFTER all occurrences (2026-05-20).
    # The fixture ledger has 59c75cff3762 resolved_ts=2026-05-10: this becomes regression.
    # We test suppression with a fresh ledger where resolved_ts is after last occurrence (2026-05-18).
    # ------------------------------------------------------------------
    def test_suppressed_sig_absent_from_results(self):
        # Build a temp ledger where resolved_ts is 2026-05-18: AFTER all
        # architect-reviewer occurrences (2026-05-14..17). The sig has count=12/4days
        # but resolved_ts is past all of them, so no post-resolved occurrences -> suppressed.
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
    # CASE G: regression: suppressed sig with new occurrences AFTER resolved_ts -> RE-SURFACES
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
    # Bad lines: unparseable JSON / missing fields / unknown schema -> no crash
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
        """D1: dark-zone sig where ALL records have severity=low -> sig severity must be normal."""
        results = self._run()
        rec = self._find(results, event_label="dark-zone", agent_type="low-sev-agent")
        self.assertIsNotNone(rec, "low-severity dark-zone sig (count=12/4days) must be flagged")
        self.assertEqual(
            rec["severity"], "normal",
            f"D1 FAIL: dark-zone sig with all low-sev records must have severity=normal, got {rec['severity']}"
        )
        # Must flag via normal C=10 gate (count >= 10, distinct_days >= 3)
        self.assertGreaterEqual(rec["count"], DEFAULT_C)
        self.assertGreaterEqual(rec["distinct_days"], DEFAULT_D)

    def test_d1_darkzone_high_records_produce_high_severity_sig(self):
        """D1: dark-zone sig where records have severity=high -> sig severity must be high."""
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
    # D2: noise-event (agent_dispatched) + outcome=no_classification -> label is no_classification
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
        self.assertGreater(len(results), 0, "Expected >=1 flagged sig on real data")

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
    """Pentest regression locks: mine() must never crash on a malformed log line 
    the spec requires 'skip, never error'. Each of these crashed a pre-fix build;
    they must stay green."""

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
