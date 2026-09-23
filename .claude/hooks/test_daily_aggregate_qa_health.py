"""The QA-health lint pass reaches the daily digest through _daily_aggregate's
alert list (2026-09-21). The digest renders dashboard_alerts and nothing else
from lint, so this hop is the whole route."""
import importlib.util
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("_daily_aggregate", str(HOOKS / "_daily_aggregate.py"))
agg = importlib.util.module_from_spec(_spec)
sys.modules["_daily_aggregate_under_test"] = agg
_spec.loader.exec_module(agg)


def _state(tmp_path, last_run, findings):
    p = tmp_path / "qa-health.json"
    p.write_text(json.dumps({"last_run": last_run, "findings": findings}), encoding="utf-8")
    return p


def test_a_fresh_finding_becomes_an_alert(tmp_path):
    p = _state(tmp_path, "2026-09-21", [{"metric": "inline_qa", "value": 0.203, "threshold": 0.1}])
    out = agg.qa_health_alerts("2026-09-22", state_path=p)
    assert out == ["QA health: inline_qa at 0.203 against 0.1 (lint pass W, 2026-09-21)"]


def test_a_stale_finding_is_replaced_by_the_staleness_alert(tmp_path):
    p = _state(tmp_path, "2026-08-01", [{"metric": "inline_qa", "value": 0.5, "threshold": 0.1}])
    assert agg.qa_health_alerts("2026-09-22", state_path=p) == ["QA health: lint pass W has not run for 52 days (last 2026-08-01)"]


def test_a_clean_run_is_silent(tmp_path):
    p = _state(tmp_path, "2026-09-21", [])
    assert agg.qa_health_alerts("2026-09-21", state_path=p) == []


def test_a_broken_state_file_is_an_alert(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    assert agg.qa_health_alerts("2026-09-21", state_path=p) == ["QA health: lint pass W state file is unreadable"]


def test_the_aggregate_carries_the_alert(tmp_path, monkeypatch):
    """End to end through aggregate_for_date on an empty governance log."""
    log = tmp_path / "governance-log.jsonl"
    log.write_text("", encoding="utf-8")
    monkeypatch.setattr(agg, "LOG_PATH", str(log))
    monkeypatch.setattr(agg, "QA_HEALTH_STATE", str(_state(tmp_path, "2026-09-21", [{"metric": "run_class", "value": 0.0, "threshold": 0.2}])))
    result = agg.aggregate_for_date("2026-09-21")
    assert any(a.startswith("QA health: run_class") for a in result["alerts"]), result


def test_a_pass_that_has_not_run_for_two_weeks_is_itself_an_alert(tmp_path):
    """Build review N6: a pass never run was indistinguishable from a clean one."""
    p = _state(tmp_path, "2026-09-01", [])
    out = agg.qa_health_alerts("2026-09-21", state_path=p)
    assert out == ["QA health: lint pass W has not run for 20 days (last 2026-09-01)"]


def _lint(tmp_path, last_iso):
    p = tmp_path / "lint-cadence.json"
    p.write_text(json.dumps({"last_iso": last_iso}), encoding="utf-8")
    return p


def test_a_missing_state_file_is_silent_until_the_sweep_has_run(tmp_path):
    """Architect review N1: a never-run alert with no state file fired on every
    session start in production, where the file does not exist yet, and broke
    test_session_start_log. The pass is part of the weekly sweep; it has not run
    only when the sweep ran without it."""
    out = agg.qa_health_alerts("2026-09-21", state_path=tmp_path / "nope.json",
                               lint_state_path=_lint(tmp_path, "2026-09-06T11:24:52Z"))
    assert out == []
    out = agg.qa_health_alerts("2026-09-21", state_path=tmp_path / "nope.json",
                               lint_state_path=tmp_path / "no-lint.json")
    assert out == []


def test_a_sweep_that_ran_without_the_pass_is_an_alert(tmp_path):
    out = agg.qa_health_alerts("2026-09-30", state_path=tmp_path / "nope.json",
                               lint_state_path=_lint(tmp_path, "2026-09-28T09:00:00Z"))
    assert out == ["QA health: lint pass W has never run although the sweep ran on 2026-09-28"]


def test_a_dead_aggregate_date_never_sees_the_never_run_alert(tmp_path):
    """test_session_start_log pins DASHBOARD_TARGET_DATE to 1970-01-01 to get an
    empty alert list; date-independent alerts break that isolation."""
    out = agg.qa_health_alerts("1970-01-01", state_path=tmp_path / "nope.json",
                               lint_state_path=_lint(tmp_path, "2026-09-28T09:00:00Z"))
    assert out == []
