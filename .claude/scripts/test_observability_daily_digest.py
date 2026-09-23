"""Smoke tests for observability_daily_digest.py.

Covers: empty data (no-op pass), single-record render, idempotent upsert,
section replacement on same-date re-run, append on new-date run,
missing verifier record (PASS without verifier line).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "observability_daily_digest",
    str(Path(__file__).parent / "observability_daily_digest.py"),
)
odd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(odd)


def _fixture_ts(date: str, **overrides) -> dict:
    return {
        "date": date,
        "collected_at": f"{date}T10:00:00Z",
        "metrics": {
            "classification_emitted_count": 5,
            "classification_complete_count": 4,
            "classifier_block_count": 1,
            "agent_dispatch_count": 12,
            "agent_dispatch_outcomes": {"allow": 8, "always_allowed": 4},
            "agent_type_counts": {"explore": 6, "general-purpose": 4, "pm-orchestrator": 2},
            "hook_block_count": 3,
            "hook_block_count_7d": 21,
            "blocks_by_hook": {"verifier-gate": 2, "subagent-quality-check": 1},
            "dark_zone_count": 4,
            "dark_zone_high_med_count": 1,
            "verifier_gate_block_count": 1,
            "verifier_gate_pass_count": 2,
            "qa_fail_event_count": 0,
            "qa_fail_total": 0,
            "session_count": 4,
            "session_start_count": 5,
            "session_end_count": 3,
            "quick_ratio_30d": 0.5,
            "dashboard_alerts": ["1 classifier block(s) today"],
        },
        "parse_error_count": 2,
        "governance_log_records_scanned": 1000,
        **overrides,
    }


def _fixture_ver(date: str, status: str = "PASS", mismatches: list | None = None) -> dict:
    return {
        "date": date,
        "overall_status": status,
        "mismatches": mismatches or [],
        "verified_at": f"{date}T11:00:00Z",
    }


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


class ReadLastRecordTests(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(odd._read_last_record_for_date(Path("/no/such")))

    def test_latest_by_date(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ts.jsonl"
            _write_jsonl(p, [
                _fixture_ts("2026-05-20"),
                _fixture_ts("2026-05-22"),
                _fixture_ts("2026-05-21"),
            ])
            rec = odd._read_last_record_for_date(p)
            self.assertEqual(rec["date"], "2026-05-22")

    def test_filter_by_date(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ts.jsonl"
            _write_jsonl(p, [
                _fixture_ts("2026-05-20"),
                _fixture_ts("2026-05-22"),
            ])
            rec = odd._read_last_record_for_date(p, date="2026-05-20")
            self.assertEqual(rec["date"], "2026-05-20")

    def test_filter_by_date_no_match_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ts.jsonl"
            _write_jsonl(p, [_fixture_ts("2026-05-20")])
            self.assertIsNone(odd._read_last_record_for_date(p, date="2026-05-21"))

    def test_malformed_lines_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "ts.jsonl"
            p.write_text("garbage\n" + json.dumps(_fixture_ts("2026-05-22")) + "\n", encoding="utf-8")
            rec = odd._read_last_record_for_date(p)
            self.assertEqual(rec["date"], "2026-05-22")


class RenderSectionTests(unittest.TestCase):
    def test_contains_required_markers(self):
        ts = _fixture_ts("2026-05-22")
        ver = _fixture_ver("2026-05-22")
        section = odd.render_section(ts, ver)
        self.assertIn("<!-- digest:section --> date=2026-05-22", section)
        self.assertIn("## 2026-05-22", section)
        self.assertIn("<!-- digest:end -->", section)
        self.assertIn("Verifier: PASS", section)
        self.assertIn("Emitted: **5**", section)
        self.assertIn("Quick-ratio 30d: **50%**", section)

    def test_no_verifier_record(self):
        ts = _fixture_ts("2026-05-22")
        section = odd.render_section(ts, None)
        self.assertIn("no verifier record", section)

    def test_verifier_fail_with_mismatches(self):
        ts = _fixture_ts("2026-05-22")
        ver = _fixture_ver("2026-05-22", status="FAIL", mismatches=[{"key": "x"}])
        section = odd.render_section(ts, ver)
        self.assertIn("FAIL: 1 mismatch", section)


class UpsertSectionTests(unittest.TestCase):
    def test_creates_file_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "digest.md"
            ts = _fixture_ts("2026-05-22")
            ver = _fixture_ver("2026-05-22")
            section = odd.render_section(ts, ver)
            action = odd.upsert_section(path, "2026-05-22", section)
            self.assertEqual(action, "created")
            self.assertTrue(path.is_file())
            text = path.read_text(encoding="utf-8")
            self.assertIn("# Vault Observability — Daily Digest", text)
            self.assertIn("## 2026-05-22", text)

    def test_replaces_existing_date(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "digest.md"
            ts = _fixture_ts("2026-05-22")
            ver = _fixture_ver("2026-05-22")
            section_v1 = odd.render_section(ts, ver)
            odd.upsert_section(path, "2026-05-22", section_v1)

            ts2 = _fixture_ts("2026-05-22", metrics={**ts["metrics"], "session_count": 99})
            section_v2 = odd.render_section(ts2, ver)
            action = odd.upsert_section(path, "2026-05-22", section_v2)
            self.assertEqual(action, "replaced")
            text = path.read_text(encoding="utf-8")
            # Only ONE section for this date
            self.assertEqual(text.count("<!-- digest:section --> date=2026-05-22"), 1)
            self.assertIn("Count: **99**", text)

    def test_appends_new_date(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "digest.md"
            ts1 = _fixture_ts("2026-05-22")
            ver1 = _fixture_ver("2026-05-22")
            odd.upsert_section(path, "2026-05-22", odd.render_section(ts1, ver1))

            ts2 = _fixture_ts("2026-05-23")
            ver2 = _fixture_ver("2026-05-23")
            action = odd.upsert_section(path, "2026-05-23", odd.render_section(ts2, ver2))
            self.assertEqual(action, "appended")
            text = path.read_text(encoding="utf-8")
            self.assertIn("## 2026-05-22", text)
            self.assertIn("## 2026-05-23", text)


class MainEndToEndTests(unittest.TestCase):
    def test_no_timeseries_returns_zero(self):
        with tempfile.TemporaryDirectory() as td:
            ts_p = Path(td) / "missing.jsonl"
            ver_p = Path(td) / "missing-v.jsonl"
            digest_p = Path(td) / "digest.md"
            with mock.patch.object(odd, "TIMESERIES_PATH", ts_p), \
                 mock.patch.object(odd, "VERIFY_PATH", ver_p), \
                 mock.patch.object(odd, "DIGEST_PATH", digest_p):
                rc = odd.main()
            self.assertEqual(rc, 0)
            self.assertFalse(digest_p.exists())

    def test_with_data_writes_digest(self):
        with tempfile.TemporaryDirectory() as td:
            ts_p = Path(td) / "ts.jsonl"
            ver_p = Path(td) / "ver.jsonl"
            digest_p = Path(td) / "digest.md"
            _write_jsonl(ts_p, [_fixture_ts("2026-05-22")])
            _write_jsonl(ver_p, [_fixture_ver("2026-05-22")])
            with mock.patch.object(odd, "TIMESERIES_PATH", ts_p), \
                 mock.patch.object(odd, "VERIFY_PATH", ver_p), \
                 mock.patch.object(odd, "DIGEST_PATH", digest_p):
                rc = odd.main()
            self.assertEqual(rc, 0)
            self.assertTrue(digest_p.is_file())
            text = digest_p.read_text(encoding="utf-8")
            self.assertIn("## 2026-05-22", text)
            self.assertIn("Verifier: PASS", text)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Observability-contract matrix generator (contract C6, 2026-08-01)
# ---------------------------------------------------------------------------

class MatrixGeneratorTests(unittest.TestCase):
    """The matrix must be GENERATED and must agree with the audited dark set, or
    it is not a trustworthy replacement for the hand file.

    The audited set was these twelve hooks. All twelve were instrumented in the
    2026-08-01 wave, so the expected dark set is now empty and the list below is
    the regression guard: strip log_fire back out of any of them and
    test_audited_dark_set_stays_instrumented names the one that regressed.
    """

    FORMERLY_DARK = [
        "bias-guard", "checkpoint", "git-credential-scope-check",
        "mcp-circuit-breaker-record", "memory-schema-check", "pre-compact",
        "registry-staleness-check", "repo-sync-cadence-trigger",
        "routing-table-validation", "session-start-orientation",
        "skill-step-reminder", "user-prompt-submit",
    ]

    def _mod(self):
        import importlib.util, os
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_activity_report.py")
        spec = importlib.util.spec_from_file_location("har", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    def test_dark_set_is_empty(self):
        self.assertEqual(self._mod().dark_hooks(), [])

    def test_audited_dark_set_stays_instrumented(self):
        dark = set(self._mod().dark_hooks())
        regressed = sorted(dark.intersection(self.FORMERLY_DARK))
        self.assertEqual(regressed, [], "instrumentation removed from: %s" % regressed)

    def test_every_registered_hook_gets_a_row_with_a_class(self):
        rows = self._mod().matrix_rows()
        self.assertGreaterEqual(len(rows), 50)
        for r in rows:
            self.assertTrue(r["classes"], f"{r['hook']} has no class")
            self.assertTrue(r["events"], f"{r['hook']} has no registered event")

    def test_markdown_renders_table_and_summary(self):
        md = self._mod().matrix_markdown()
        self.assertIn("| Hook | Event(s) | Class | Sink(s) |", md)
        self.assertIn("Dark set:", md)
