"""
test_collect_vault_metrics.py — Unit tests for collect_vault_metrics.py

Spec: MON-V2-1 (Projects/Agent-Governance-Research/work/archive/2026-05-21-mon-v2-1-collection-spec.md)

Fixtures are hand-crafted to cover:
  - All 4 schema variants (v1a, v1b, v1c, v2) plus v2_legacy
  - An unclassifiable line (unknown variant)
  - A date with zero records
  - Idempotency: running twice for the same date produces no duplicate

Ground truth for all assertions is derived from manual counting of the fixture data,
NOT from the script's own output.
"""

import importlib.util
import json
import sys
import tempfile
import textwrap
import unittest
from datetime import date, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Dynamic import of the module under test so this file can live next to it
# ---------------------------------------------------------------------------
_SCRIPT = Path(__file__).parent / "collect_vault_metrics.py"
_spec = importlib.util.spec_from_file_location("collect_vault_metrics", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

classify_variant = _mod.classify_variant
is_test_record = _mod.is_test_record
compute_metrics = _mod.compute_metrics
compute_rolling = _mod.compute_rolling
build_output_record = _mod.build_output_record
date_already_in_out = _mod.date_already_in_out
read_log = _mod.read_log
main = _mod.main

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

TARGET_DATE = "2026-01-15"
OTHER_DATE = "2026-01-14"

# --- v1a record: no event, no schema, has type AND mechanism (mechanism may be null) ---
V1A_QUICK = {
    "ts": f"{TARGET_DATE} 10:00:00",
    "session": "abc123abc123",
    "type": "Quick",
    "domain": None,
    "mechanism": None,   # null — key present, value null
    "must_dispatch": None,
    "agents": [],
    "skills": [],
    "agent_count": 0,
    "skill_count": 0,
}

V1A_RESEARCH = {
    "ts": f"{TARGET_DATE} 10:01:00",
    "session": "abc123abc123",
    "type": "Research",
    "domain": "general",
    "mechanism": None,
    "must_dispatch": "process-research",
    "agents": [],
    "skills": [],
    "agent_count": 0,
    "skill_count": 0,
}

# --- v1b record: no event, no schema, has type AND implies ---
V1B_ANALYSIS = {
    "ts": f"{TARGET_DATE} 11:00:00",
    "session": "def456def456",
    "type": "Analysis",
    "implies": "User wants deep analysis.",
    "domain": "general",
    "must_dispatch": "process-analysis",
    "agents": [],
    "skills": [],
    "agent_count": 0,
    "skill_count": 0,
}

V1B_QUICK = {
    "ts": f"{TARGET_DATE} 11:05:00",
    "session": "def456def456",
    "type": "Quick",
    "implies": "Simple question.",
    "domain": None,
    "must_dispatch": None,
    "agents": [],
    "skills": [],
    "agent_count": 0,
    "skill_count": 0,
}

# --- v2_legacy record: schema==2, no event, has type ---
V2_LEGACY_BUILD = {
    "ts": f"{TARGET_DATE} 12:00:00",
    "schema": 2,
    "session": "692cfdb4-b180-4b4b-84b9-2ec163df7ab3",
    "type": "Build",
    "implies": "Build the feature.",
    "domain": "n8n",
    "must_dispatch": "process-build",
    "agents": [],
    "skills": [],
    "agent_count": 0,
    "skill_count": 0,
}

# --- v1c record: no schema, has event ---
V1C_BLOCK = {
    "ts": f"{TARGET_DATE} 13:00:00",
    "event": "block",
    "hook": "dispatch-compliance",
    "session": "legacy-session-01",
}

# --- v2 records ---
V2_AGENT_DISPATCHED_ALLOW = {
    "ts": f"{TARGET_DATE} 14:00:00",
    "schema": 2,
    "event": "agent_dispatched",
    "hook": "agent-dispatch-check",
    "session": "11111111-1111-1111-1111-111111111111",
    "environment": "prod",
    "agent_type": "blueprint-mode",
    "skill_context": [],
    "exempted_via_registry": False,
    "warn_downgrade": False,
    "outcome": "allow",
}

V2_AGENT_DISPATCHED_WARN = {
    "ts": f"{TARGET_DATE} 14:10:00",
    "schema": 2,
    "event": "agent_dispatched",
    "hook": "agent-dispatch-check",
    "session": "22222222-2222-2222-2222-222222222222",
    "environment": "prod",
    "agent_type": "general-purpose",
    "skill_context": [],
    "exempted_via_registry": False,
    "warn_downgrade": True,
    "outcome": "warn",
}

V2_BLOCK_PROCESS_STEP = {
    "ts": f"{TARGET_DATE} 14:20:00",
    "schema": 2,
    "event": "block",
    "hook": "process-step-check",
    "session": "11111111-1111-1111-1111-111111111111",
    "environment": "prod",
}

V2_DARK_ZONE_HIGH = {
    "ts": f"{TARGET_DATE} 14:30:00",
    "event": "dark-zone",
    "hook": "dark-zone-check",
    "session": "11111111-1111-1111-1111-111111111111",
    "agents": ["general-purpose"],
    "agent_count": 1,
    "citation_count": 0,
    "files_written": 10,
    "ratio": 10.0,
    "severity": "high",
    "schema": 2,
}

V2_DARK_ZONE_LOW = {
    "ts": f"{TARGET_DATE} 14:35:00",
    "event": "dark-zone",
    "hook": "dark-zone-check",
    "session": "11111111-1111-1111-1111-111111111111",
    "agents": ["blueprint-mode"],
    "agent_count": 1,
    "citation_count": 1,
    "files_written": 3,
    "ratio": 3.0,
    "severity": "low",
    "schema": 2,
}

V2_CLASSIFICATION_EMITTED_COMPLETE = {
    "ts": f"{TARGET_DATE} 15:00:00",
    "schema": 2,
    "event": "classification_emitted",
    "hook": "classifier-field-check",
    "session": "33333333-3333-3333-3333-333333333333",
    "environment": "prod",
    "type": "Quick",
    "is_quick": True,
    "implies": "Simple task.",
    "domain": None,
    "approach": None,
    "missed": None,
    "must_dispatch_raw": None,
    "missing_fields": [],
    "complete": True,
}

V2_CLASSIFICATION_EMITTED_INCOMPLETE = {
    "ts": f"{TARGET_DATE} 15:05:00",
    "schema": 2,
    "event": "classification_emitted",
    "hook": "classifier-field-check",
    "session": "33333333-3333-3333-3333-333333333333",
    "environment": "prod",
    "type": "Build",
    "is_quick": False,
    "implies": "Build something.",
    "domain": "n8n",
    "approach": None,
    "missed": None,
    "must_dispatch_raw": None,
    "missing_fields": ["approach"],
    "complete": False,
}

V2_CLASSIFIER_BLOCK = {
    "ts": f"{TARGET_DATE} 15:10:00",
    "schema": 2,
    "event": "classifier_field_missing",
    "hook": "classifier-field-check",
    "session": "33333333-3333-3333-3333-333333333333",
    "environment": "prod",
    "missing": ["MUST DISPATCH"],
    "is_quick": False,
    "decision": "block",
}

V2_SESSION_START = {
    "ts": f"{TARGET_DATE} 09:00:00",
    "schema": 2,
    "event": "session_start",
    "hook": "session-start-log",
    "session": "11111111-1111-1111-1111-111111111111",
    "environment": "prod",
}

V2_SESSION_END_1 = {
    "ts": f"{TARGET_DATE} 16:00:00",
    "schema": 2,
    "event": "session_end",
    "hook": "work-verification-check",
    "session": "11111111-1111-1111-1111-111111111111",
    "environment": "prod",
    "turn_count": 10,
    "heartbeat": True,
}

V2_SESSION_END_2 = {
    "ts": f"{TARGET_DATE} 17:00:00",
    "schema": 2,
    "event": "session_end",
    "hook": "work-verification-check",
    "session": "22222222-2222-2222-2222-222222222222",
    "environment": "prod",
    "turn_count": 5,
    "heartbeat": True,
}

V2_VERIFIER_GATE_BLOCK = {
    "ts": f"{TARGET_DATE} 16:30:00",
    "event": "block",
    "hook": "verifier-gate",
    "skill": "verification-gated-research",
    "schema": 2,
}

V2_VERIFIER_GATE_PASS = {
    "ts": f"{TARGET_DATE} 16:31:00",
    "event": "pass",
    "hook": "verifier-gate",
    "skill": "verification-gated-research",
    "schema": 2,
}

V2_DASHBOARD_ALERT = {
    "ts": f"{TARGET_DATE} 09:05:00",
    "schema": 2,
    "event": "dashboard_alert",
    "hook": "session-start-log",
    "session": "11111111-1111-1111-1111-111111111111",
    "environment": "prod",
    "aggregate_date": OTHER_DATE,
    "alerts": ["2 classifier block(s) today", "1 QA FAIL claim(s) today"],
    "sessions": 5,
    "qa_fails": 1,
    "classifier_blocks": 2,
    "agent_warns": 0,
}

V2_QA_FAIL = {
    "ts": f"{TARGET_DATE} 16:45:00",
    "schema": 2,
    "event": "qa_fail_reported",
    "hook": "qa-check",
    "session": "11111111-1111-1111-1111-111111111111",
    "environment": "prod",
    "fail_count": 3,
}

# Test-session record (should be excluded)
TEST_SESSION_RECORD = {
    "ts": f"{TARGET_DATE} 10:30:00",
    "schema": 2,
    "event": "agent_dispatched",
    "hook": "agent-dispatch-check",
    "session": "test-session-abc",
    "environment": "prod",
    "agent_type": "blueprint-mode",
    "outcome": "allow",
}

TEST_ENV_RECORD = {
    "ts": f"{TARGET_DATE} 10:31:00",
    "schema": 2,
    "event": "agent_dispatched",
    "hook": "agent-dispatch-check",
    "session": "99999999-9999-9999-9999-999999999999",
    "environment": "test",
    "agent_type": "general-purpose",
    "outcome": "allow",
}

# Record on OTHER_DATE (should not appear in target-day metrics)
OTHER_DAY_RECORD = {
    "ts": f"{OTHER_DATE} 10:00:00",
    "schema": 2,
    "event": "agent_dispatched",
    "hook": "agent-dispatch-check",
    "session": "55555555-5555-5555-5555-555555555555",
    "environment": "prod",
    "agent_type": "blueprint-mode",
    "outcome": "allow",
}

# Unclassifiable record: no event, no schema, no type
UNCLASSIFIABLE = {
    "ts": f"{TARGET_DATE} 11:30:00",
    "session": "xyz",
    "some_unknown_field": True,
}

# --- Full fixture log (all records for test) ---
ALL_FIXTURE_RECORDS = [
    V1A_QUICK,
    V1A_RESEARCH,
    V1B_ANALYSIS,
    V1B_QUICK,
    V2_LEGACY_BUILD,
    V1C_BLOCK,
    V2_AGENT_DISPATCHED_ALLOW,
    V2_AGENT_DISPATCHED_WARN,
    V2_BLOCK_PROCESS_STEP,
    V2_DARK_ZONE_HIGH,
    V2_DARK_ZONE_LOW,
    V2_CLASSIFICATION_EMITTED_COMPLETE,
    V2_CLASSIFICATION_EMITTED_INCOMPLETE,
    V2_CLASSIFIER_BLOCK,
    V2_SESSION_START,
    V2_SESSION_END_1,
    V2_SESSION_END_2,
    V2_VERIFIER_GATE_BLOCK,
    V2_VERIFIER_GATE_PASS,
    V2_DASHBOARD_ALERT,
    V2_QA_FAIL,
    TEST_SESSION_RECORD,
    TEST_ENV_RECORD,
    OTHER_DAY_RECORD,
    UNCLASSIFIABLE,
]


def _make_log_file(records: list[dict], extra_malformed: int = 0) -> Path:
    """Write records as JSONL to a temp file and return its Path."""
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    for r in records:
        tf.write(json.dumps(r) + "\n")
    for _ in range(extra_malformed):
        tf.write("{this is not json\n")
    tf.close()
    return Path(tf.name)


def _make_out_file(existing_records: list[dict] | None = None) -> Path:
    """Create a temp output JSONL file, optionally pre-populated."""
    tf = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    if existing_records:
        for r in existing_records:
            tf.write(json.dumps(r) + "\n")
    tf.close()
    return Path(tf.name)


# ---------------------------------------------------------------------------
# Helper: run the full pipeline on the fixture
# ---------------------------------------------------------------------------

def _run_fixture(
    target_date_str: str = TARGET_DATE,
    extra_malformed: int = 0,
    records: list[dict] | None = None,
) -> dict:
    """Run main() in dry-run mode on fixture and return the parsed record."""
    import io
    from contextlib import redirect_stdout

    log_path = _make_log_file(
        records if records is not None else ALL_FIXTURE_RECORDS,
        extra_malformed,
    )
    out_path = _make_out_file()

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = main([
                "--date", target_date_str,
                "--log", str(log_path),
                "--out", str(out_path),
                "--dry-run",
            ])
    finally:
        log_path.unlink(missing_ok=True)
        out_path.unlink(missing_ok=True)

    assert rc == 0, f"main() returned non-zero: {rc}"
    output = buf.getvalue().strip()
    assert output, "dry-run produced no output"
    return json.loads(output)


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestClassifyVariant(unittest.TestCase):
    """Tests for schema-variant detection (MON-V2-1 §2)."""

    def test_v2_full(self):
        r = {"schema": 2, "event": "agent_dispatched", "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v2")

    def test_v2_legacy(self):
        r = {"schema": 2, "type": "Quick", "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v2_legacy")

    def test_v1c(self):
        r = {"event": "block", "hook": "dispatch-compliance", "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v1c")

    def test_v1a_mechanism_null(self):
        """v1a detector fires when mechanism key present, even if value is null."""
        r = {"type": "Quick", "mechanism": None, "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v1a")

    def test_v1a_mechanism_value(self):
        r = {"type": "Research", "mechanism": "some-value", "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v1a")

    def test_v1b_with_implies(self):
        r = {"type": "Analysis", "implies": "Deep analysis.", "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v1b")

    def test_v1b_type_only(self):
        """type present, no mechanism, no implies → still v1b."""
        r = {"type": "Quick", "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "v1b")

    def test_unknown(self):
        r = {"some_field": True, "ts": "2026-01-01 10:00:00"}
        self.assertEqual(classify_variant(r), "unknown")

    def test_v2_no_event_no_type_is_v2(self):
        """schema==2 with no event and no type → v2 (not v2_legacy, no type field)."""
        r = {"schema": 2, "ts": "2026-01-01 10:00:00", "hook": "some-hook"}
        self.assertEqual(classify_variant(r), "v2")


class TestTestSessionExclusion(unittest.TestCase):
    def test_test_prefix(self):
        self.assertTrue(is_test_record({"session": "test-something", "environment": "prod"}))

    def test_test_exact(self):
        self.assertTrue(is_test_record({"session": "test", "environment": "prod"}))

    def test_fixture_prefix(self):
        self.assertTrue(is_test_record({"session": "fixture-abc", "environment": "prod"}))

    def test_pentest_prefix(self):
        self.assertTrue(is_test_record({"session": "pentest-run-1"}))

    def test_environment_test(self):
        self.assertTrue(is_test_record({"session": "real-session-abc", "environment": "test"}))

    def test_prod_not_excluded(self):
        self.assertFalse(is_test_record({"session": "11111111-1111-1111-1111-111111111111", "environment": "prod"}))

    def test_no_session_field(self):
        """Missing session field → not excluded (per spec §8: handle missing session)."""
        r = {"schema": 2, "event": "block", "hook": "verifier-gate"}
        self.assertFalse(is_test_record(r))


class TestMetricsComputation(unittest.TestCase):
    """
    Test §4.1 – §4.4 metric families against hand-calculated fixture ground truth.
    """

    @classmethod
    def setUpClass(cls):
        """Run full pipeline once, share the result."""
        cls.result = _run_fixture()
        cls.metrics = cls.result["metrics"]

    # --- §4.1 Classification ---

    def test_classification_count(self):
        # spec §4.1: v1a + v1b legacy classification records on target day
        # v1a: V1A_QUICK, V1A_RESEARCH = 2
        # v1b: V1B_ANALYSIS, V1B_QUICK = 2
        # total = 4
        self.assertEqual(self.metrics["classification_count"], 4)

    def test_classification_count_v2_legacy(self):
        # v2_legacy: V2_LEGACY_BUILD = 1 record on target day
        self.assertEqual(self.metrics["classification_count_v2_legacy"], 1)

    def test_classification_mix(self):
        # v1a: Quick (V1A_QUICK), Research (V1A_RESEARCH)
        # v1b: Analysis (V1B_ANALYSIS), Quick (V1B_QUICK)
        # v2_legacy: Build (V2_LEGACY_BUILD)
        # Quick count = V1A_QUICK + V1B_QUICK = 2; Research = 1; Analysis = 1; Build = 1
        mix = self.metrics["classification_mix"]
        self.assertEqual(mix["Quick"], 2)
        self.assertEqual(mix["Research"], 1)
        self.assertEqual(mix["Analysis"], 1)
        self.assertEqual(mix["Build"], 1)

    def test_quick_ratio(self):
        # total = classification_count(4) + classification_count_v2_legacy(1) = 5
        # Quick = 2 (V1A_QUICK + V1B_QUICK; V2_LEGACY is Build)
        # ratio = 2/5 = 0.4
        expected = round(2 / 5, 6)
        self.assertAlmostEqual(self.metrics["quick_ratio"], expected, places=5)

    def test_classification_emitted_count(self):
        # V2_CLASSIFICATION_EMITTED_COMPLETE + V2_CLASSIFICATION_EMITTED_INCOMPLETE = 2
        self.assertEqual(self.metrics["classification_emitted_count"], 2)

    def test_classification_complete_count(self):
        # Only V2_CLASSIFICATION_EMITTED_COMPLETE has complete==True
        self.assertEqual(self.metrics["classification_complete_count"], 1)

    def test_classifier_block_count(self):
        # V2_CLASSIFIER_BLOCK has decision=="block"
        self.assertEqual(self.metrics["classifier_block_count"], 1)

    # --- §4.2 Dispatch / governance ---

    def test_agent_dispatch_count(self):
        # V2_AGENT_DISPATCHED_ALLOW + V2_AGENT_DISPATCHED_WARN = 2
        # TEST_SESSION_RECORD and TEST_ENV_RECORD are excluded; OTHER_DAY_RECORD is other day
        self.assertEqual(self.metrics["agent_dispatch_count"], 2)

    def test_agent_dispatch_outcomes(self):
        outcomes = self.metrics["agent_dispatch_outcomes"]
        self.assertEqual(outcomes.get("allow"), 1)
        self.assertEqual(outcomes.get("warn"), 1)

    def test_agent_type_counts(self):
        atc = self.metrics["agent_type_counts"]
        self.assertEqual(atc.get("blueprint-mode"), 1)
        self.assertEqual(atc.get("general-purpose"), 1)

    def test_agent_warn_count(self):
        # Derived from outcomes["warn"] = 1
        self.assertEqual(self.metrics["agent_warn_count"], 1)

    def test_hook_block_count(self):
        # All event=="block" records on target day (v1c + v2):
        # V1C_BLOCK (v1c) + V2_BLOCK_PROCESS_STEP (v2) + V2_VERIFIER_GATE_BLOCK (v2) = 3
        self.assertEqual(self.metrics["hook_block_count"], 3)

    def test_blocks_by_hook(self):
        bbh = self.metrics["blocks_by_hook"]
        self.assertEqual(bbh.get("dispatch-compliance"), 1)   # v1c
        self.assertEqual(bbh.get("process-step-check"), 1)    # v2
        self.assertEqual(bbh.get("verifier-gate"), 1)         # v2

    def test_dark_zone_count(self):
        # V2_DARK_ZONE_HIGH + V2_DARK_ZONE_LOW = 2
        self.assertEqual(self.metrics["dark_zone_count"], 2)

    def test_dark_zone_high_med_count(self):
        # Only V2_DARK_ZONE_HIGH has severity=="high"
        self.assertEqual(self.metrics["dark_zone_high_med_count"], 1)

    def test_dark_zone_mean_ratio(self):
        # ratio values: 10.0 + 3.0 → mean = 6.5
        self.assertAlmostEqual(self.metrics["dark_zone_mean_ratio"], 6.5, places=4)

    def test_verifier_gate_block_count(self):
        # V2_VERIFIER_GATE_BLOCK: schema==2, hook==verifier-gate, event==block
        self.assertEqual(self.metrics["verifier_gate_block_count"], 1)

    def test_verifier_gate_pass_count(self):
        # V2_VERIFIER_GATE_PASS: schema==2, hook==verifier-gate, event==pass
        self.assertEqual(self.metrics["verifier_gate_pass_count"], 1)

    # --- §4.3 QA / process ---

    def test_qa_fail_event_count(self):
        # V2_QA_FAIL = 1
        self.assertEqual(self.metrics["qa_fail_event_count"], 1)

    def test_qa_fail_total(self):
        # V2_QA_FAIL.fail_count = 3
        self.assertEqual(self.metrics["qa_fail_total"], 3)

    def test_process_step_block_count(self):
        # V2_BLOCK_PROCESS_STEP has hook==process-step-check and event==block
        self.assertEqual(self.metrics["process_step_block_count"], 1)

    # --- §4.4 Session ---

    def test_session_count(self):
        # Distinct sessions on target day (after test exclusion):
        # V1A: "abc123abc123" (normalised: "abc123abc123")
        # V1B: "def456def456"
        # V2_LEGACY: "692cfdb4-b180..." → normalised "692cfdb4-b1"
        # V1C_BLOCK: "legacy-session-01" → normalised "legacy-sessi"
        # V2_AGENT_ALLOW: "11111111-..." → normalised "11111111-111"
        # V2_AGENT_WARN: "22222222-..." → normalised "22222222-222"
        # V2_CLASSIFICATION records: "33333333-..." → normalised "33333333-333"
        # SESSION_START: "11111111-..." → collapses with V2_AGENT_ALLOW
        # SESSION_END_1: "11111111-..." → collapses
        # SESSION_END_2: "22222222-..." → collapses
        # VERIFIER_GATE records: no session field → not added
        # DASHBOARD_ALERT: "11111111-..." → collapses
        # QA_FAIL: "11111111-..." → collapses
        # TEST records: excluded
        # UNCLASSIFIABLE: unknown variant → not in day_records
        # Expected distinct: abc123abc123, def456def456, 692cfdb4-b1, legacy-sessi,
        #                     11111111-111, 22222222-222, 33333333-333 = 7
        self.assertEqual(self.metrics["session_count"], 7)

    def test_session_start_count(self):
        # V2_SESSION_START = 1
        self.assertEqual(self.metrics["session_start_count"], 1)

    def test_session_end_count(self):
        # V2_SESSION_END_1 (session 11111...) + V2_SESSION_END_2 (session 22222...) = 2 distinct
        self.assertEqual(self.metrics["session_end_count"], 2)

    def test_dashboard_alert_count(self):
        # V2_DASHBOARD_ALERT has ts=TARGET_DATE but aggregate_date=OTHER_DATE.
        # Spec §4.4: bucketed by aggregate_date. So it must NOT appear in TARGET_DATE's count.
        self.assertEqual(self.metrics["dashboard_alert_count"], 0)

    def test_dashboard_alert_count_on_aggregate_date(self):
        # When collecting for OTHER_DATE, V2_DASHBOARD_ALERT (aggregate_date=OTHER_DATE)
        # should be counted — exactly 1.
        result = _run_fixture(target_date_str=OTHER_DATE)
        self.assertEqual(result["metrics"]["dashboard_alert_count"], 1)

    def test_dashboard_alerts_content_on_aggregate_date(self):
        # Alerts list content is populated from V2_DASHBOARD_ALERT when collecting for OTHER_DATE.
        result = _run_fixture(target_date_str=OTHER_DATE)
        alerts = result["metrics"]["dashboard_alerts"]
        self.assertIn("2 classifier block(s) today", alerts)
        self.assertIn("1 QA FAIL claim(s) today", alerts)


class TestIntegrityCounters(unittest.TestCase):
    """Test the integrity counters at record top level."""

    @classmethod
    def setUpClass(cls):
        cls.result = _run_fixture(extra_malformed=2)

    def test_parse_error_count(self):
        self.assertEqual(self.result["parse_error_count"], 2)

    def test_test_records_excluded(self):
        # TEST_SESSION_RECORD + TEST_ENV_RECORD = 2 on target day
        self.assertEqual(self.result["test_records_excluded"], 2)

    def test_unknown_variant_count(self):
        # UNCLASSIFIABLE = 1 on target day
        self.assertEqual(self.result["unknown_variant_count"], 1)

    def test_records_scanned(self):
        # ALL_FIXTURE_RECORDS = 25; + 2 malformed → total lines = 27
        # scanned = parsed successfully = 25
        self.assertEqual(self.result["governance_log_records_scanned"], 25)

    def test_spec_version(self):
        self.assertEqual(self.result["spec_version"], "mon-v2-1-v1")


class TestZeroActivityDay(unittest.TestCase):
    """A date with zero records still produces a valid all-zero entry."""

    def test_zero_day(self):
        result = _run_fixture(target_date_str="2020-01-01")
        self.assertEqual(result["metrics"]["classification_count"], 0)
        self.assertEqual(result["metrics"]["agent_dispatch_count"], 0)
        self.assertEqual(result["metrics"]["hook_block_count"], 0)
        self.assertIsNone(result["metrics"]["quick_ratio"])
        self.assertEqual(result["metrics"]["session_count"], 0)


class TestRollingFields(unittest.TestCase):
    """Rolling §4.5 fields."""

    def setUp(self):
        self.result = _run_fixture()
        self.metrics = self.result["metrics"]

    def test_classification_count_7d_type(self):
        # Must be an integer
        self.assertIsInstance(self.metrics["classification_count_7d"], int)

    def test_hook_block_count_7d_type(self):
        self.assertIsInstance(self.metrics["hook_block_count_7d"], int)

    def test_classification_count_7d_includes_target_day(self):
        # All fixture records are on TARGET_DATE, so the 7-day window contains only TARGET_DATE.
        # classification_count_7d counts v1a + v1b records (test-excluded records filtered out):
        #   v1a: V1A_QUICK, V1A_RESEARCH = 2
        #   v1b: V1B_ANALYSIS, V1B_QUICK = 2
        # Total = 4.
        self.assertEqual(self.metrics["classification_count_7d"], 4)

    def test_hook_block_count_7d_includes_target_day(self):
        # All fixture records are on TARGET_DATE, so the 7-day window contains only TARGET_DATE.
        # hook_block_count_7d counts event=="block" in v1c + v2 (test-excluded records filtered out):
        #   V1C_BLOCK (v1c), V2_BLOCK_PROCESS_STEP (v2), V2_VERIFIER_GATE_BLOCK (v2) = 3.
        self.assertEqual(self.metrics["hook_block_count_7d"], 3)

    def test_quick_ratio_30d_null_when_low_sample(self):
        # Fixture has <10 legacy classification records in 30d window → null
        # (3 classification records: V1A_QUICK, V1A_RESEARCH, V1B_ANALYSIS, V1B_QUICK, V2_LEGACY_BUILD = 5 total — still <10)
        self.assertIsNone(self.metrics["quick_ratio_30d"])

    def test_quick_ratio_30d_computed_when_sufficient(self):
        """Generate >10 classification records across 30 days → quick_ratio_30d is non-null."""
        base_date = date(2026, 2, 15)
        records = []
        for i in range(12):
            d = base_date - timedelta(days=i)
            records.append({
                "ts": f"{d.isoformat()} 10:00:00",
                "session": f"sess-{i:04d}-abc123",
                "type": "Quick" if i % 3 != 0 else "Research",
                "mechanism": None,
            })
        result = _run_fixture(target_date_str=base_date.isoformat(), records=records)
        # 12 legacy classification records in 30d → quick_ratio_30d should be non-null
        self.assertIsNotNone(result["metrics"]["quick_ratio_30d"])
        self.assertGreater(result["metrics"]["quick_ratio_30d"], 0.0)
        self.assertLessEqual(result["metrics"]["quick_ratio_30d"], 1.0)


class TestISOTTimestampParsing(unittest.TestCase):
    """Fix 1 verification: _parse_ts must parse ISO-T format (2026-...T..:..:..Z) correctly."""

    def test_iso_t_record_bucketed_to_correct_date(self):
        """A record whose ts uses ISO-T format must be bucketed to the right calendar date."""
        iso_t_record = {
            "ts": "2026-03-10T08:30:00Z",
            "schema": 2,
            "event": "agent_dispatched",
            "hook": "agent-dispatch-check",
            "session": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "environment": "prod",
            "agent_type": "blueprint-mode",
            "outcome": "allow",
        }
        result = _run_fixture(target_date_str="2026-03-10", records=[iso_t_record])
        # The record's ts date is 2026-03-10; it should appear in agent_dispatch_count.
        self.assertEqual(result["metrics"]["agent_dispatch_count"], 1)
        # Sanity: wrong date produces zero
        result_other = _run_fixture(target_date_str="2026-03-11", records=[iso_t_record])
        self.assertEqual(result_other["metrics"]["agent_dispatch_count"], 0)


class TestIdempotency(unittest.TestCase):
    """Running twice for the same date must not produce a duplicate."""

    def test_no_duplicate_on_second_run(self):
        import io
        from contextlib import redirect_stdout

        log_path = _make_log_file(ALL_FIXTURE_RECORDS)
        out_path = _make_out_file()

        try:
            # First run
            rc1 = main(["--date", TARGET_DATE, "--log", str(log_path), "--out", str(out_path)])
            self.assertEqual(rc1, 0)

            # Second run for same date
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc2 = main(["--date", TARGET_DATE, "--log", str(log_path), "--out", str(out_path)])
            self.assertEqual(rc2, 0)
            self.assertIn("NOOP", buf.getvalue().upper())

            # Verify only one entry in output file
            with out_path.open("r", encoding="utf-8") as fh:
                lines = [l.strip() for l in fh if l.strip()]
            self.assertEqual(len(lines), 1, f"Expected 1 entry, got {len(lines)}")
        finally:
            log_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)


class TestAllVariantsPresent(unittest.TestCase):
    """Smoke-test that all 4 spec variants are exercised and independently classifiable."""

    def test_all_variants_classified(self):
        variants = {classify_variant(r) for r in ALL_FIXTURE_RECORDS}
        self.assertIn("v1a", variants)
        self.assertIn("v1b", variants)
        self.assertIn("v1c", variants)
        self.assertIn("v2", variants)
        self.assertIn("v2_legacy", variants)
        self.assertIn("unknown", variants)

    def test_unclassifiable_counted_not_crashed(self):
        result = _run_fixture()
        # UNCLASSIFIABLE record on target day → unknown_variant_count >= 1
        self.assertGreaterEqual(result["unknown_variant_count"], 1)


class TestMalformedLineHandling(unittest.TestCase):
    """Malformed JSON lines must not crash the run."""

    def test_malformed_lines_counted(self):
        result = _run_fixture(extra_malformed=5)
        self.assertEqual(result["parse_error_count"], 5)

    def test_exit_zero_with_malformed(self):
        """The run must exit 0 even with malformed lines present."""
        import io
        from contextlib import redirect_stdout

        log_path = _make_log_file(ALL_FIXTURE_RECORDS, extra_malformed=3)
        out_path = _make_out_file()
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                rc = main([
                    "--date", TARGET_DATE,
                    "--log", str(log_path),
                    "--out", str(out_path),
                    "--dry-run",
                ])
        finally:
            log_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)
        self.assertEqual(rc, 0)


class TestOutputRecordStructure(unittest.TestCase):
    """Output record must contain all required top-level and metrics keys."""

    REQUIRED_TOP_KEYS = {
        "date", "collected_at", "spec_version", "routine_version",
        "governance_log_records_scanned", "test_records_excluded",
        "unknown_variant_count", "parse_error_count", "metrics", "source_excerpts",
    }

    REQUIRED_METRIC_KEYS = {
        "classification_count", "classification_count_v2_legacy", "classification_mix",
        "quick_ratio", "classification_emitted_count", "classification_complete_count",
        "classifier_block_count", "agent_dispatch_count", "agent_dispatch_outcomes",
        "agent_type_counts", "agent_warn_count", "hook_block_count", "blocks_by_hook",
        "dark_zone_count", "dark_zone_high_med_count", "dark_zone_mean_ratio",
        "verifier_gate_block_count", "verifier_gate_pass_count",
        "qa_fail_event_count", "qa_fail_total", "process_step_block_count",
        "session_count", "session_start_count", "session_end_count",
        "dashboard_alert_count", "dashboard_alerts",
        "classification_count_7d", "hook_block_count_7d", "quick_ratio_30d",
    }

    @classmethod
    def setUpClass(cls):
        cls.result = _run_fixture()

    def test_top_level_keys_present(self):
        missing = self.REQUIRED_TOP_KEYS - self.result.keys()
        self.assertEqual(missing, set(), f"Missing top-level keys: {missing}")

    def test_metric_keys_present(self):
        missing = self.REQUIRED_METRIC_KEYS - self.result["metrics"].keys()
        self.assertEqual(missing, set(), f"Missing metric keys: {missing}")

    def test_date_value(self):
        self.assertEqual(self.result["date"], TARGET_DATE)

    def test_collected_at_is_iso(self):
        ca = self.result["collected_at"]
        # Should parse without error
        from datetime import datetime, timezone
        dt = datetime.strptime(ca, "%Y-%m-%dT%H:%M:%SZ")
        self.assertIsNotNone(dt)

    def test_source_excerpts_is_dict(self):
        self.assertIsInstance(self.result["source_excerpts"], dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
