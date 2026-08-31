"""Tests for hook_activity_report.py --exit-cost (criterion-2 baseline instrument).

Fixtures write temp sinks and point the script at them via the existing
GOVERNANCE_LOG_PATH / HOOK_ACTIVITY_LOG_PATH overrides. Repo adaptation
(2026-08-31): this published copy has no live settings.local.json, so a
session-scoped fixture settings file supplies the Stop-chain set via
SETTINGS_LOCAL_PATH; the private twin exercises the live settings parse
path instead, a documented divergence with reason.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "hook_activity_report.py"
PY = sys.executable

WINDOW = ["--since=2026-01-01", "--until=2026-01-08"]


def _act(ts, hook, session):
    return {"ts": ts, "event": "hook_fire", "hook": hook, "decision": "pass",
            "detail": "", "session": session}


def _gov(ts, hook, session, event="turn_summary", **kw):
    rec = {"ts": ts, "schema": 2, "event": event, "hook": hook,
           "session": session, "environment": "prod"}
    rec.update(kw)
    return rec


def _write_sinks(tmp_path, act_records, gov_records):
    act = tmp_path / "hook-activity.jsonl"
    gov = tmp_path / "governance-log.jsonl"
    act.write_text("".join(json.dumps(r) + "\n" for r in act_records),
                   encoding="utf-8")
    gov.write_text("".join(json.dumps(r) + "\n" for r in gov_records),
                   encoding="utf-8")
    return act, gov


_FIXTURE_SETTINGS = None


def _fixture_settings_path():
    """A minimal Stop-registration settings file, created once per session."""
    global _FIXTURE_SETTINGS
    if _FIXTURE_SETTINGS is None:
        import tempfile
        hooks = ["classifier-field-check", "dispatch-compliance-check",
                 "work-verification-check", "governance-log"]
        payload = {"hooks": {"Stop": [
            {"hooks": [{"command": "python %s.py" % h} for h in hooks]}
        ]}}
        d = tempfile.mkdtemp(prefix="exit-cost-settings-")
        p = os.path.join(d, "settings.local.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        _FIXTURE_SETTINGS = p
    return _FIXTURE_SETTINGS


def _run(act, gov, extra=None):
    env = dict(os.environ)
    env["HOOK_ACTIVITY_LOG_PATH"] = str(act)
    env["GOVERNANCE_LOG_PATH"] = str(gov)
    env["SETTINGS_LOCAL_PATH"] = _fixture_settings_path()
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [PY, str(SCRIPT), "--exit-cost"] + WINDOW + (extra or [])
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          timeout=120)


def _fixture_records():
    s1, s2 = "real-sess-1", "real-sess-2"
    act = [
        # chain A (s1): 4s wall-clock, Quick via turn_summary inside
        _act("2026-01-02 10:00:00", "classifier-field-check", s1),
        _act("2026-01-02 10:00:02", "dispatch-compliance-check", s1),
        _act("2026-01-02 10:00:04", "work-verification-check", s1),
        # chain B (s1): 6s, no turn_summary -> unclassified
        _act("2026-01-02 10:05:00", "classifier-field-check", s1),
        _act("2026-01-02 10:05:06", "work-verification-check", s1),
        # chain C (s2): 10s, Build
        _act("2026-01-02 11:00:00", "classifier-field-check", s2),
        _act("2026-01-02 11:00:10", "work-verification-check", s2),
        # single-record turn (s2)
        _act("2026-01-02 12:00:00", "work-verification-check", s2),
        # excluded: synthetic session
        _act("2026-01-02 13:00:00", "work-verification-check", "fixture-abc"),
        # excluded: non-chain hook must not enter any cluster
        _act("2026-01-02 10:00:01", "bash-safety-guard", s1),
    ]
    gov = [
        _gov("2026-01-02 10:00:03", "governance-log", s1, type="Quick"),
        _gov("2026-01-02 11:00:05", "governance-log", s2, type="Build"),
        # excluded: test environment
        _gov("2026-01-02 14:00:00", "governance-log", "real-sess-3",
             type="Quick", environment="test"),
        # excluded: synthetic session id
        _gov("2026-01-02 15:00:00", "governance-log", "unknown", type="Quick"),
    ]
    return act, gov


def test_empty_population_fails_loud(tmp_path):
    act, gov = _write_sinks(tmp_path, [], [])
    r = _run(act, gov)
    assert r.returncode == 2
    assert "EMPTY POPULATION" in r.stdout


def test_clusters_buckets_and_medians(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run(act, gov)
    assert r.returncode == 0, r.stdout + r.stderr
    out = r.stdout
    # Quick bucket: one chain, 4s, 4 distinct chain hooks (incl. governance-log)
    assert "Quick" in out
    assert "p50=4.0s" in out and "p95=4.0s" in out
    # Build bucket: one chain, 10s
    assert "p50=10.0s" in out
    # unclassified bucket exists for chain B (6s)
    assert "unclassified" in out and "p50=6.0s" in out
    # single-record turns reported, not silently folded into wall-clock stats
    assert "single-record turns: 1" in out


def test_exclusions_are_counted_not_silent(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run(act, gov)
    assert r.returncode == 0
    # 1 synthetic activity record + 1 test-env gov record + 1 synthetic gov session
    assert "excluded records: 3" in r.stdout


def test_coverage_note_names_dark_chain_members(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run(act, gov)
    assert r.returncode == 0
    # the note must state observed vs registered chain size, lower-bound honesty
    assert "lower bound" in r.stdout
    assert "chain members observed" in r.stdout


def test_byte_identical_across_runs(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r1 = _run(act, gov)
    r2 = _run(act, gov)
    assert r1.returncode == r2.returncode == 0
    assert r1.stdout == r2.stdout


def test_gap_splits_chains(tmp_path):
    s = "real-sess-9"
    act_recs = [
        _act("2026-01-03 09:00:00", "classifier-field-check", s),
        _act("2026-01-03 09:00:05", "work-verification-check", s),
        # 31s gap: new chain
        _act("2026-01-03 09:00:36", "classifier-field-check", s),
        _act("2026-01-03 09:00:38", "work-verification-check", s),
    ]
    act, gov = _write_sinks(tmp_path, act_recs, [])
    r = _run(act, gov)
    assert r.returncode == 0
    assert "turns measured: 2" in r.stdout
    assert "p50=3.5s" in r.stdout  # median of 5s and 2s


def test_quick_vs_nonquick_rollup_present(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run(act, gov)
    assert r.returncode == 0
    assert "ROLLUP" in r.stdout
    assert "non-Quick" in r.stdout


def _run_raw(act, gov, args, extra_env=None):
    env = dict(os.environ)
    env["HOOK_ACTIVITY_LOG_PATH"] = str(act)
    env["GOVERNANCE_LOG_PATH"] = str(gov)
    env["SETTINGS_LOCAL_PATH"] = _fixture_settings_path()
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra_env or {})
    cmd = [PY, str(SCRIPT), "--exit-cost"] + args
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          timeout=120)


def test_space_form_args_match_equals_form(tmp_path):
    # the spec's CHECK clause uses the space form; both must behave identically
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r_eq = _run_raw(act, gov, ["--since=2026-01-01", "--until=2026-01-08"])
    r_sp = _run_raw(act, gov, ["--since", "2026-01-01", "--until",
                               "2026-01-08"])
    assert r_eq.returncode == r_sp.returncode == 0
    assert r_eq.stdout == r_sp.stdout


def test_flag_without_value_fails_loud(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run_raw(act, gov, ["--since"])
    assert r.returncode == 2
    assert "ERROR" in r.stdout and "--since" in r.stdout


def test_bad_since_value_fails_loud(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run_raw(act, gov, ["--since=not-a-date", "--until=2026-01-08"])
    assert r.returncode == 2
    assert "ERROR" in r.stdout


def test_boundary_straddling_turn_excluded_and_counted(tmp_path):
    s = "real-sess-8"
    act_recs = [
        # one real 20s turn straddling the until boundary (2026-01-08 00:00)
        _act("2026-01-07 23:59:55", "classifier-field-check", s),
        _act("2026-01-08 00:00:05", "work-verification-check", s),
        _act("2026-01-08 00:00:15", "dispatch-compliance-check", s),
        # one clean in-window turn so the population is non-empty
        _act("2026-01-07 10:00:00", "classifier-field-check", s),
        _act("2026-01-07 10:00:02", "work-verification-check", s),
    ]
    act, gov = _write_sinks(tmp_path, act_recs, [])
    r = _run(act, gov)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "turns measured: 1" in r.stdout
    assert "boundary-clipped turns: 1" in r.stdout


def test_malformed_ts_is_counted(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act_recs.append(_act("not-a-timestamp", "work-verification-check",
                         "real-sess-1"))
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run(act, gov)
    assert r.returncode == 0
    assert "unparseable-ts records: 1" in r.stdout


def test_missing_settings_fails_loud(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    r = _run_raw(act, gov, WINDOW,
                 {"SETTINGS_LOCAL_PATH": str(tmp_path / "absent.json")})
    assert r.returncode == 2
    assert "ERROR" in r.stdout and "Stop chain" in r.stdout


def test_empty_stop_list_fails_loud(tmp_path):
    act_recs, gov_recs = _fixture_records()
    act, gov = _write_sinks(tmp_path, act_recs, gov_recs)
    empty = tmp_path / "settings-empty.json"
    empty.write_text(json.dumps({"hooks": {"Stop": []}}), encoding="utf-8")
    r = _run_raw(act, gov, WINDOW, {"SETTINGS_LOCAL_PATH": str(empty)})
    assert r.returncode == 2
    assert "ERROR" in r.stdout
