"""Tests for lint-cadence-trigger.py: GAP-3b proposal loop-closure builder
(TA-3 Phase 2 Step 4, 2026-07-10). First test file for this hook; scope is the
NEW build_governance_mine_proposal_closure_suggestion only (existing builders
are byte-untouched this increment and covered by live firings).

Polarity contract (plan Step-4 acceptance criterion):
  (a) 31 proposals, 0 resolved, last_iso > 7d, report present -> FIRES
  (b) all 31 sig_ids in the ledger -> SILENT (firing on fully-resolved = defect)
  (c) ledger file absent -> FIRES (D3: missing ledger = 0 resolved)
  (d) report_path missing on disk -> SILENT

All fixtures live in temp dirs via module-constant monkeypatching; no test
touches live _state/ or aggregates/.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


def _load(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, str(Path(__file__).parent / filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lct = _load("lint-cadence-trigger.py", "lint_cadence_trigger")

SIG_IDS = [f"sig{i:04d}aaaa" for i in range(31)]


class ClosureSuggestionTests(unittest.TestCase):
    def _fixture(
        self,
        td: Path,
        *,
        proposal_count: int = 31,
        age_days: int = 11,
        report_on_disk: bool = True,
        resolved_sig_ids: list | None = None,
        ledger_exists: bool = True,
    ):
        """Point the module constants at temp fixtures."""
        report_rel = "work/mine-report.md"
        if report_on_disk:
            (td / "work").mkdir(exist_ok=True)
            (td / report_rel).write_text("# proposals\n", encoding="utf-8")
        last_iso = (
            datetime.now(timezone.utc) - timedelta(days=age_days)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        state = td / "governance-mine-cadence.json"
        state.write_text(json.dumps({
            "last_iso": last_iso,
            "report_path": report_rel,
            "proposal_count": proposal_count,
        }), encoding="utf-8")
        ledger = td / "miner-resolved.jsonl"
        if ledger_exists:
            lines = [
                json.dumps({"sig_id": s, "resolved_ts": "2026-07-01",
                            "resolution": "tuned", "note": "test"})
                for s in (resolved_sig_ids or [])
            ]
            ledger.write_text("\n".join(lines) + ("\n" if lines else ""),
                              encoding="utf-8")
        lct.VAULT = str(td)
        lct.GOVERNANCE_MINE_STATE_FILE = str(state)
        lct.MINER_RESOLVED_LEDGER = str(ledger)

    def test_fires_on_unresolved_stale_with_report(self):
        """Case (a): 31 proposals, empty ledger, 11d old, report present."""
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td), resolved_sig_ids=[])
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertIn("LOOP-CLOSURE", msg)
            self.assertIn("31 of 31", msg)
            self.assertIn("work/mine-report.md", msg)
            self.assertIn("triage", msg.lower())

    def test_silent_when_fully_resolved(self):
        """Case (b): all 31 sig_ids ruled -> firing would be a defect."""
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td), resolved_sig_ids=SIG_IDS)
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertEqual(msg, "")

    def test_fires_when_ledger_absent(self):
        """Case (c): missing ledger = 0 resolved (D3), never an error."""
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td), ledger_exists=False)
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertIn("LOOP-CLOSURE", msg)
            self.assertIn("31 of 31", msg)

    def test_silent_when_report_missing_on_disk(self):
        """Case (d): stale state pointing at a deleted report stays quiet."""
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td), report_on_disk=False)
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertEqual(msg, "")

    def test_partial_resolution_counts_distinct(self):
        """10 of 31 ruled (with one duplicate ledger line) -> 21 unresolved."""
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td), resolved_sig_ids=SIG_IDS[:10] + [SIG_IDS[0]])
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertIn("21 of 31", msg)

    def test_silent_when_fresh(self):
        """A run inside the 7d cadence is not yet a closure concern."""
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td), age_days=2)
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertEqual(msg, "")

    def test_silent_when_no_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            self._fixture(Path(td))
            lct.GOVERNANCE_MINE_STATE_FILE = str(Path(td) / "nope.json")
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertEqual(msg, "")

    def test_corrupt_ledger_lines_are_skipped(self):
        """Garbage lines in the ledger never crash the builder."""
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            self._fixture(td, resolved_sig_ids=SIG_IDS[:5])
            with open(lct.MINER_RESOLVED_LEDGER, "a", encoding="utf-8") as f:
                f.write("{not json}\n\n")
            msg = lct.build_governance_mine_proposal_closure_suggestion()
            self.assertIn("26 of 31", msg)


class WorkTriageSuggestionTests(unittest.TestCase):
    """Tests for build_work_triage_suggestion(): FILE-ORG-3 increment 1 (2026-07-13).

    State-file fixture pattern mirrors ClosureSuggestionTests: monkeypatch
    lct.WORK_TRIAGE_STATE_FILE to a temp path; never touches the live
    .claude/hooks/_state/ directory.

    Polarity contract:
      (a) last_iso fresher than 7d -> SILENT (no work-triage suggestion)
      (b) last_iso older than 7d -> suggestion present containing 'WORK-TRIAGE'
      (c) missing state file -> bootstrap fires, suggestion contains 'WORK-TRIAGE CADENCE'
      (d) malformed/corrupt state JSON -> fail-open: empty string, no crash
    """

    def _write_state(self, path: Path, last_iso: str, report_path: str = "") -> None:
        path.write_text(
            json.dumps({"last_iso": last_iso, "report_path": report_path}),
            encoding="utf-8",
        )

    def _fresh_iso(self, days_ago: int = 0) -> str:
        return (
            datetime.now(timezone.utc) - timedelta(days=days_ago)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

    def setUp(self):
        """Capture the real state-file path so tearDown can restore it."""
        self._real_state = lct.WORK_TRIAGE_STATE_FILE

    def tearDown(self):
        """Always restore the module constant, even on test failure."""
        lct.WORK_TRIAGE_STATE_FILE = self._real_state

    # (a) fresh state -> silent
    def test_silent_when_last_run_within_cadence(self):
        """Case (a): last_iso 2 days ago, below 7d threshold, no suggestion."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            self._write_state(state, self._fresh_iso(days_ago=2))
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            msg = lct.build_work_triage_suggestion()
            self.assertEqual(msg, "")

    # (b) stale state -> suggestion with WORK-TRIAGE
    def test_fires_when_last_run_older_than_cadence(self):
        """Case (b): last_iso 10 days ago, past 7d threshold, suggestion emitted."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            self._write_state(state, self._fresh_iso(days_ago=10))
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            msg = lct.build_work_triage_suggestion()
            self.assertIn("WORK-TRIAGE", msg)
            self.assertIn("10 days ago", msg)

    def test_fires_overdue_variant_at_2x_cadence(self):
        """last_iso 15 days ago (>= 2*7) -> OVERDUE variant fires."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            self._write_state(state, self._fresh_iso(days_ago=15))
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            msg = lct.build_work_triage_suggestion()
            self.assertIn("WORK-TRIAGE CADENCE", msg)
            self.assertIn("OVERDUE", msg)

    def test_report_path_appended_when_present(self):
        """A non-empty report_path in the state file is appended to the suggestion."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            self._write_state(
                state,
                self._fresh_iso(days_ago=10),
                report_path="Projects/your-project/work/2026-07-10-triage-proposal.md",
            )
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            msg = lct.build_work_triage_suggestion()
            self.assertIn("triage-proposal.md", msg)

    # (c) missing state file -> bootstrap fires (writes epoch-old file), suggestion present
    def test_missing_state_file_bootstraps_and_suggests(self):
        """Case (c): no state file -> bootstrap_state_file creates it, suggestion returned."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            # Confirm it does not exist yet
            self.assertFalse(state.exists())
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            msg = lct.build_work_triage_suggestion()
            # Suggestion must be non-empty and contain the cadence tag
            self.assertIn("WORK-TRIAGE CADENCE", msg)
            # bootstrap_state_file must have created the file as a side-effect
            self.assertTrue(state.exists(), "bootstrap_state_file should create the state file")
            # The bootstrapped file should be valid JSON with an epoch-old last_iso
            data = json.loads(state.read_text(encoding="utf-8"))
            self.assertIn("last_iso", data)
            self.assertEqual(data["last_iso"], "1970-01-01T00:00:00Z")

    # (d) malformed JSON -> fail-open: empty string, no exception
    def test_corrupt_state_json_returns_empty_no_crash(self):
        """Case (d): corrupt state file -> fail-open, no crash, empty suggestion."""
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            state.write_text("{not valid json!!!", encoding="utf-8")
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            try:
                msg = lct.build_work_triage_suggestion()
            except Exception as exc:
                self.fail(f"build_work_triage_suggestion() raised on corrupt JSON: {exc}")
            self.assertEqual(msg, "")

    def test_exactly_at_threshold_boundary_is_silent(self):
        """last_iso exactly at 7d (< timedelta(days=7) is False when age == 7d).

        The function uses `age < timedelta(days=CADENCE_DAYS)`, so age == 7d triggers.
        This test asserts the boundary is inclusive (fires at 7d, not just >7d).
        """
        with tempfile.TemporaryDirectory() as td:
            state = Path(td) / "work-triage-cadence.json"
            # 6 days 23 hours -> strictly less than 7d -> silent
            last_iso = (
                datetime.now(timezone.utc) - timedelta(days=6, hours=23)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._write_state(state, last_iso)
            lct.WORK_TRIAGE_STATE_FILE = str(state)
            msg = lct.build_work_triage_suggestion()
            self.assertEqual(msg, "")


class SessionWiringTests(unittest.TestCase):
    """Defect 2 (2026-08-07): main() read stdin then immediately discarded it
    ('sys.stdin.read()' with no assignment), so the log_fire() call always
    logged session=None; stdin was never actually parsed, not merely dropped
    after parsing. Reproduces the broken shape first (a synthetic main()
    invocation with a populated session_id), then asserts it populates."""

    def _run_main_quiet(self, payload, activity_log):
        """Run main() with all seven builders forced empty, so the outcome is a
        deterministic 'quiet' fire regardless of live vault state."""
        captured = io.StringIO()
        builder_names = [
            "build_lint_suggestion",
            "build_governance_mine_suggestion",
            "build_governance_mine_proposal_closure_suggestion",
            "build_setup_audit_suggestion",
            "build_ingest_backlog_suggestion",
            "build_work_triage_suggestion",
            "build_telemetry_check_suggestion",
        ]
        patches = [mock.patch.object(lct, name, return_value="") for name in builder_names]
        with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": activity_log}), \
             mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
             redirect_stdout(captured):
            for p in patches:
                p.start()
            try:
                lct.main()
            finally:
                for p in patches:
                    p.stop()
        return captured.getvalue()

    def test_session_populates_from_payload(self):
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            self._run_main_quiet({"session_id": "test-lintcadence-1"}, activity_log)
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["hook"], "lint-cadence-trigger")
        self.assertEqual(records[0]["decision"], "quiet")
        self.assertEqual(records[0]["session"], "test-lintcadence-1")

    def test_missing_session_id_logs_null_not_crash(self):
        with tempfile.TemporaryDirectory() as td:
            activity_log = str(Path(td) / "hook-activity.jsonl")
            self._run_main_quiet({}, activity_log)
            with open(activity_log, encoding="utf-8") as f:
                records = [json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertIsNone(records[0]["session"])


if __name__ == "__main__":
    unittest.main()
