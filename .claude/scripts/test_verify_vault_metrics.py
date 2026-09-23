"""Tests for verify_vault_metrics.py — R-1V verifier."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from verify_vault_metrics import (  # noqa: E402
    _classify,
    _find_collector_record,
    _is_test_record,
    _normalise_session,
    _read_log_lines,
    _ts_to_date_str,
    already_verified,
    compare,
    compute_verifier_metrics,
    main,
)


class TimestampParserTests(unittest.TestCase):
    def test_iso_t_form(self):
        self.assertEqual(_ts_to_date_str("2026-05-22T14:30:00Z"), "2026-05-22")

    def test_space_form(self):
        self.assertEqual(_ts_to_date_str("2026-05-22 14:30:00"), "2026-05-22")

    def test_subsecond_ignored(self):
        self.assertEqual(_ts_to_date_str("2026-05-22T14:30:00.123456Z"), "2026-05-22")

    def test_returns_none_for_non_string(self):
        self.assertIsNone(_ts_to_date_str(None))
        self.assertIsNone(_ts_to_date_str(12345))

    def test_returns_none_for_invalid_date(self):
        self.assertIsNone(_ts_to_date_str("2026-13-40 00:00:00"))

    def test_returns_none_for_short(self):
        self.assertIsNone(_ts_to_date_str("2026"))

    def test_returns_none_for_wrong_separator(self):
        self.assertIsNone(_ts_to_date_str("2026/05/22 14:30:00"))

    def test_rejects_positive_tz_offset(self):
        # Collector's strptime formats don't accept +HH:MM offsets, verifier must match
        self.assertIsNone(_ts_to_date_str("2026-05-22T14:30:00+05:30"))

    def test_rejects_negative_tz_offset(self):
        self.assertIsNone(_ts_to_date_str("2026-05-22T14:30:00-04:00"))

    def test_accepts_z_suffix(self):
        self.assertEqual(_ts_to_date_str("2026-05-22T14:30:00Z"), "2026-05-22")


class TestRecordExclusionTests(unittest.TestCase):
    def test_test_environment_excluded(self):
        self.assertTrue(_is_test_record({"environment": "test"}))

    def test_prod_environment_not_excluded(self):
        self.assertFalse(_is_test_record({"environment": "prod"}))

    def test_fixture_session_prefix(self):
        self.assertTrue(_is_test_record({"session": "fixture-abc"}))

    def test_pentest_session_prefix(self):
        self.assertTrue(_is_test_record({"session": "pentest-001"}))

    def test_test_session_exact(self):
        self.assertTrue(_is_test_record({"session": "test"}))

    def test_unknown_session_exact(self):
        self.assertTrue(_is_test_record({"session": "unknown"}))

    def test_real_session_not_excluded(self):
        self.assertFalse(_is_test_record({"session": "692cfdb4-b180"}))

    def test_no_session_no_environment(self):
        self.assertFalse(_is_test_record({}))


class ClassifierTests(unittest.TestCase):
    """Verifier's _classify must produce the same partition as collector's classify_variant."""

    def test_v2_with_event(self):
        self.assertEqual(_classify({"schema": 2, "event": "block"}), "v2")

    def test_v2_legacy(self):
        self.assertEqual(_classify({"schema": 2, "type": "Quick"}), "v2_legacy")

    def test_v2_with_both_event_and_type(self):
        # Has event → v2 (not v2_legacy)
        self.assertEqual(_classify({"schema": 2, "event": "x", "type": "y"}), "v2")

    def test_v1c_event_no_schema(self):
        self.assertEqual(_classify({"event": "block"}), "v1c")

    def test_v1a_with_mechanism(self):
        self.assertEqual(_classify({"type": "Quick", "mechanism": "stop"}), "v1a")

    def test_v1a_with_null_mechanism(self):
        # Spec: mechanism key present even if null still triggers v1a
        self.assertEqual(_classify({"type": "Quick", "mechanism": None}), "v1a")

    def test_v1b_type_only(self):
        self.assertEqual(_classify({"type": "Quick"}), "v1b")

    def test_unknown(self):
        self.assertEqual(_classify({"foo": "bar"}), "unknown")


class SessionNormaliserTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_normalise_session(""), "")

    def test_uuid(self):
        self.assertEqual(
            _normalise_session("692cfdb4-b180-4b4b-84b9-2ec163df7ab3"),
            "692cfdb4-b18",
        )

    def test_short(self):
        self.assertEqual(_normalise_session("abc"), "abc")

    def test_uuid_and_prefix_collapse_to_same_value(self):
        full = "692cfdb4-b180-4b4b-84b9-2ec163df7ab3"
        prefix = "692cfdb4-b18"
        self.assertEqual(_normalise_session(full), _normalise_session(prefix))


class LogReaderTests(unittest.TestCase):
    def test_reads_valid_lines(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "log.jsonl"
            log.write_text(
                '{"a": 1}\n{"b": 2}\n\n{"c": 3}\n',
                encoding="utf-8",
            )
            recs, total, errors = _read_log_lines(log)
            self.assertEqual(len(recs), 3)
            self.assertEqual(total, 3)
            self.assertEqual(errors, 0)

    def test_counts_parse_errors(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "log.jsonl"
            log.write_text(
                '{"ok": 1}\nnot-json\n{"ok": 2}\n',
                encoding="utf-8",
            )
            recs, total, errors = _read_log_lines(log)
            self.assertEqual(len(recs), 2)
            self.assertEqual(total, 3)
            self.assertEqual(errors, 1)


class FindCollectorRecordTests(unittest.TestCase):
    def test_finds_record_for_date(self):
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "ts.jsonl"
            ts.write_text(
                json.dumps({"date": "2026-05-20", "metrics": {}}) + "\n"
                + json.dumps({"date": "2026-05-21", "metrics": {"hook_block_count": 5}}) + "\n",
                encoding="utf-8",
            )
            rec, hits = _find_collector_record(ts, "2026-05-21")
            self.assertIsNotNone(rec)
            self.assertEqual(hits, 1)
            self.assertEqual(rec["metrics"]["hook_block_count"], 5)

    def test_returns_last_match_and_counts_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "ts.jsonl"
            ts.write_text(
                json.dumps({"date": "2026-05-21", "v": 1}) + "\n"
                + json.dumps({"date": "2026-05-21", "v": 2}) + "\n",
                encoding="utf-8",
            )
            rec, hits = _find_collector_record(ts, "2026-05-21")
            self.assertEqual(rec["v"], 2)
            self.assertEqual(hits, 2)

    def test_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            ts = Path(td) / "ts.jsonl"
            ts.write_text(json.dumps({"date": "2026-05-20"}) + "\n", encoding="utf-8")
            rec, hits = _find_collector_record(ts, "2026-05-21")
            self.assertIsNone(rec)
            self.assertEqual(hits, 0)

    def test_returns_none_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            rec, hits = _find_collector_record(Path(td) / "missing.jsonl", "2026-05-21")
            self.assertIsNone(rec)
            self.assertEqual(hits, 0)


class ComputeVerifierMetricsTests(unittest.TestCase):
    def _make_records(self):
        # Mix of records on target day and other days
        return [
            # Target day (2026-05-21) records:
            {"ts": "2026-05-21T01:00:00Z", "type": "Quick"},  # v1b classification
            {"ts": "2026-05-21T02:00:00Z", "type": "Build", "mechanism": "stop"},  # v1a classification
            {"ts": "2026-05-21T03:00:00Z", "schema": 2, "type": "Analysis"},  # v2_legacy
            {"ts": "2026-05-21T04:00:00Z", "schema": 2, "event": "classification_emitted"},
            {"ts": "2026-05-21T05:00:00Z", "schema": 2, "event": "block", "hook": "x"},  # block v2
            {"ts": "2026-05-21T06:00:00Z", "event": "block", "hook": "y"},  # block v1c
            {"ts": "2026-05-21T07:00:00Z", "schema": 2, "hook": "verifier-gate", "event": "block"},
            {"ts": "2026-05-21T08:00:00Z", "schema": 2, "hook": "verifier-gate", "event": "pass"},
            {"ts": "2026-05-21T09:00:00Z", "schema": 2, "hook": "verifier-gate", "event": "pass"},
            {"ts": "2026-05-21T10:00:00Z", "schema": 2, "event": "qa_fail_reported"},
            {"ts": "2026-05-21T11:00:00Z", "session": "abc1234567890", "event": "x"},  # v1c
            {"ts": "2026-05-21T12:00:00Z", "session": "abc1234567890", "event": "x"},  # dup session, v1c
            {"ts": "2026-05-21T13:00:00Z", "session": "def4567890123", "event": "x"},  # v1c
            # Test-excluded record:
            {"ts": "2026-05-21T14:00:00Z", "session": "fixture-test-1", "type": "Quick"},
            # Wrong day:
            {"ts": "2026-05-20T01:00:00Z", "type": "Quick"},
        ]

    def test_classification_counts(self):
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        self.assertEqual(m["classification_count"], 2)  # v1a + v1b
        self.assertEqual(m["classification_count_v2_legacy"], 1)
        self.assertEqual(m["classification_emitted_count"], 1)

    def test_hook_block_count(self):
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        # 3 blocks: v2 block (hook=x), v1c block (hook=y), v2 verifier-gate block.
        # Matches collector: hook_block_count counts ALL event=="block" in v1c+v2 partitions
        # regardless of which hook fired (verifier-gate block contributes to both counters).
        self.assertEqual(m["hook_block_count"], 3)

    def test_verifier_gate_counts(self):
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        self.assertEqual(m["verifier_gate_block_count"], 1)
        self.assertEqual(m["verifier_gate_pass_count"], 2)

    def test_qa_fail_event_count(self):
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        self.assertEqual(m["qa_fail_event_count"], 1)

    def test_session_count_distinct(self):
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        # Sessions: abc1234567890 (dup → 1), def4567890123 — fixture-test-1 excluded
        # Plus sessions on the records that don't carry session field: 0 contribution
        self.assertEqual(m["session_count"], 2)

    def test_test_records_excluded(self):
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        self.assertEqual(m["test_records_excluded"], 1)

    def test_wrong_day_not_counted(self):
        # The 2026-05-20 record should not contribute to any 2026-05-21 metric
        m = compute_verifier_metrics(self._make_records(), "2026-05-21")
        # If wrong day leaked, classification_count would be 3 not 2
        self.assertEqual(m["classification_count"], 2)

    def test_unknown_variant_records_excluded_from_session_count(self):
        # HIGH fix: unknown-variant records carrying session fields must NOT contribute to
        # session_count (collector excludes them).
        records = [
            {"ts": "2026-05-21T01:00:00Z", "session": "real-session-aa", "type": "Quick"},
            # Unknown-variant record with a session — neither schema nor event nor type
            {"ts": "2026-05-21T02:00:00Z", "session": "ghost-session-bb", "foo": "bar"},
        ]
        m = compute_verifier_metrics(records, "2026-05-21")
        self.assertEqual(m["session_count"], 1)  # only the v1b record's session

    def test_classifier_block_count_independently_computed(self):
        records = [
            {"ts": "2026-05-21T01:00:00Z", "schema": 2, "event": "classifier_field_missing", "decision": "block"},
            {"ts": "2026-05-21T02:00:00Z", "schema": 2, "event": "classifier_field_missing", "decision": "warn"},
            {"ts": "2026-05-21T03:00:00Z", "schema": 2, "event": "classifier_field_missing", "decision": "block"},
        ]
        m = compute_verifier_metrics(records, "2026-05-21")
        self.assertEqual(m["classifier_block_count"], 2)  # decision==block only

    def test_tz_offset_records_dropped_to_match_collector(self):
        # A record with +05:30 offset is dropped by the collector; verifier must drop too
        records = [
            {"ts": "2026-05-21T01:00:00Z", "type": "Quick"},
            {"ts": "2026-05-21T02:00:00+05:30", "type": "Build", "mechanism": "stop"},
        ]
        m = compute_verifier_metrics(records, "2026-05-21")
        self.assertEqual(m["classification_count"], 1)  # only the Z-suffixed record


class CompareTests(unittest.TestCase):
    def _make_collector_rec(self, **overrides):
        base = {
            "governance_log_records_scanned": 100,
            "parse_error_count": 0,
            "test_records_excluded": 2,
            "metrics": {
                "classification_count": 5,
                "classification_count_v2_legacy": 2,
                "classification_emitted_count": 1,
                "classifier_block_count": 1,
                "hook_block_count": 3,
                "verifier_gate_block_count": 0,
                "verifier_gate_pass_count": 1,
                "qa_fail_event_count": 0,
                "session_count": 4,
            },
        }
        base.update(overrides)
        return base

    def _matching_verifier_metrics(self):
        return {
            "test_records_excluded": 2,
            "classification_count": 5,
            "classification_count_v2_legacy": 2,
            "classification_emitted_count": 1,
            "classifier_block_count": 1,
            "hook_block_count": 3,
            "verifier_gate_block_count": 0,
            "verifier_gate_pass_count": 1,
            "qa_fail_event_count": 0,
            "session_count": 4,
        }

    def test_all_match_pass(self):
        result = compare(self._make_collector_rec(), self._matching_verifier_metrics(), 100, 0)
        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["mismatches"], [])

    def test_one_mismatch_drift(self):
        v = self._matching_verifier_metrics()
        v["hook_block_count"] = 5
        result = compare(self._make_collector_rec(), v, 100, 0)
        self.assertEqual(result["overall_status"], "DRIFT")
        self.assertIn("hook_block_count", result["mismatches"])

    def test_log_grew_is_pass(self):
        # Verifier sees more records than collector did — expected, not a mismatch
        result = compare(self._make_collector_rec(), self._matching_verifier_metrics(), 150, 0)
        self.assertEqual(result["overall_status"], "PASS")
        self.assertEqual(result["comparisons"]["governance_log_records_scanned"]["kind"], "info_only_log_grew")

    def test_log_shrank_is_drift(self):
        # If the verifier sees FEWER lines than the collector did, something is wrong
        result = compare(self._make_collector_rec(), self._matching_verifier_metrics(), 50, 0)
        self.assertEqual(result["overall_status"], "DRIFT")
        self.assertIn("governance_log_records_scanned", result["mismatches"])

    def test_parse_errors_grew_is_pass(self):
        result = compare(self._make_collector_rec(), self._matching_verifier_metrics(), 100, 3)
        self.assertEqual(result["overall_status"], "PASS")

    def test_test_records_excluded_mismatch_is_drift(self):
        v = self._matching_verifier_metrics()
        v["test_records_excluded"] = 99
        result = compare(self._make_collector_rec(), v, 100, 0)
        self.assertEqual(result["overall_status"], "DRIFT")
        self.assertIn("test_records_excluded", result["mismatches"])

    def test_test_records_excluded_missing_in_collector_flags_drift(self):
        # MED-2 fix: when collector lacks the field but verifier found non-zero, must DRIFT
        rec = self._make_collector_rec()
        del rec["test_records_excluded"]  # simulate old collector format
        v = self._matching_verifier_metrics()
        v["test_records_excluded"] = 2  # verifier found 2
        result = compare(rec, v, 100, 0)
        self.assertEqual(result["overall_status"], "DRIFT")
        self.assertIn("test_records_excluded", result["mismatches"])
        self.assertIsNone(result["comparisons"]["test_records_excluded"]["collector"])


class IdempotencyTests(unittest.TestCase):
    def test_skips_existing_date(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "verify.jsonl"
            out.write_text(json.dumps({"date": "2026-05-21", "overall_status": "PASS"}) + "\n", encoding="utf-8")
            self.assertTrue(already_verified(out, "2026-05-21"))
            self.assertFalse(already_verified(out, "2026-05-22"))

    def test_no_file(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "missing.jsonl"
            self.assertFalse(already_verified(out, "2026-05-21"))


class MainIntegrationTests(unittest.TestCase):
    """End-to-end main() flows."""

    def _setup_files(self, td: Path):
        log = td / "log.jsonl"
        ts = td / "ts.jsonl"
        out = td / "verify.jsonl"
        return log, ts, out

    def test_missing_collector_record_emits_missing(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            log, ts, out = self._setup_files(td_path)
            log.write_text("", encoding="utf-8")
            ts.write_text("", encoding="utf-8")
            rc = main([
                "--date", "2026-05-21",
                "--log", str(log),
                "--timeseries", str(ts),
                "--out", str(out),
            ])
            self.assertEqual(rc, 0)
            lines = out.read_text(encoding="utf-8").strip().split("\n")
            rec = json.loads(lines[0])
            self.assertEqual(rec["overall_status"], "MISSING")
            self.assertFalse(rec["target_record_found"])

    def test_end_to_end_pass(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            log, ts, out = self._setup_files(td_path)
            log_records = [
                {"ts": "2026-05-21T01:00:00Z", "type": "Quick"},
                {"ts": "2026-05-21T02:00:00Z", "schema": 2, "event": "block", "hook": "x"},
            ]
            log.write_text("\n".join(json.dumps(r) for r in log_records) + "\n", encoding="utf-8")
            collector_rec = {
                "date": "2026-05-21",
                "collected_at": "2026-05-22T01:00:00Z",
                "governance_log_records_scanned": 2,
                "parse_error_count": 0,
                "test_records_excluded": 0,
                "metrics": {
                    "classification_count": 1,
                    "classification_count_v2_legacy": 0,
                    "classification_emitted_count": 0,
                    "classifier_block_count": 0,
                    "hook_block_count": 1,
                    "verifier_gate_block_count": 0,
                    "verifier_gate_pass_count": 0,
                    "qa_fail_event_count": 0,
                    "session_count": 0,
                },
            }
            ts.write_text(json.dumps(collector_rec) + "\n", encoding="utf-8")
            rc = main([
                "--date", "2026-05-21",
                "--log", str(log),
                "--timeseries", str(ts),
                "--out", str(out),
            ])
            self.assertEqual(rc, 0)
            rec = json.loads(out.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["overall_status"], "PASS")
            self.assertEqual(rec["mismatches"], [])

    def test_end_to_end_drift(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            log, ts, out = self._setup_files(td_path)
            log_records = [
                {"ts": "2026-05-21T01:00:00Z", "type": "Quick"},
                {"ts": "2026-05-21T02:00:00Z", "type": "Build", "mechanism": "stop"},
            ]
            log.write_text("\n".join(json.dumps(r) for r in log_records) + "\n", encoding="utf-8")
            collector_rec = {
                "date": "2026-05-21",
                "governance_log_records_scanned": 2,
                "parse_error_count": 0,
                "test_records_excluded": 0,
                "metrics": {"classification_count": 99},  # bogus
            }
            ts.write_text(json.dumps(collector_rec) + "\n", encoding="utf-8")
            rc = main([
                "--date", "2026-05-21",
                "--log", str(log),
                "--timeseries", str(ts),
                "--out", str(out),
            ])
            self.assertEqual(rc, 0)
            rec = json.loads(out.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["overall_status"], "DRIFT")
            self.assertIn("classification_count", rec["mismatches"])

    def test_idempotent_rerun(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            log, ts, out = self._setup_files(td_path)
            log.write_text("", encoding="utf-8")
            ts.write_text("", encoding="utf-8")
            # First run
            main([
                "--date", "2026-05-21",
                "--log", str(log),
                "--timeseries", str(ts),
                "--out", str(out),
            ])
            first = out.read_text(encoding="utf-8")
            # Second run — should noop
            main([
                "--date", "2026-05-21",
                "--log", str(log),
                "--timeseries", str(ts),
                "--out", str(out),
            ])
            second = out.read_text(encoding="utf-8")
            self.assertEqual(first, second)

    def test_invalid_date_exits_2(self):
        rc = main(["--date", "not-a-date"])
        self.assertEqual(rc, 2)

    def test_missing_log_exits_3(self):
        with tempfile.TemporaryDirectory() as td:
            rc = main([
                "--log", str(Path(td) / "missing.jsonl"),
                "--date", "2026-05-21",
            ])
            self.assertEqual(rc, 3)

    def test_duplicate_collector_records_flag_drift(self):
        """LOW fix: when two collector records exist for the same date, surface as DRIFT."""
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            log, ts, out = self._setup_files(td_path)
            log.write_text("", encoding="utf-8")
            base_rec = {
                "date": "2026-05-21",
                "governance_log_records_scanned": 0,
                "parse_error_count": 0,
                "test_records_excluded": 0,
                "metrics": {},
            }
            ts.write_text(
                json.dumps(base_rec) + "\n"
                + json.dumps({**base_rec, "metrics": {"classification_count": 99}}) + "\n",
                encoding="utf-8",
            )
            rc = main([
                "--date", "2026-05-21",
                "--log", str(log),
                "--timeseries", str(ts),
                "--out", str(out),
            ])
            self.assertEqual(rc, 0)
            rec = json.loads(out.read_text(encoding="utf-8").strip())
            self.assertEqual(rec["overall_status"], "DRIFT")
            self.assertEqual(rec["collector_duplicate_count"], 2)
            self.assertIn("collector_duplicate_records", rec["mismatches"])


if __name__ == "__main__":
    unittest.main()
