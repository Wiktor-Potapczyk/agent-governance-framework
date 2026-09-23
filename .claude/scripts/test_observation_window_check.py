"""
test_observation_window_check.py - pytest suite for observation_window_check.py (O12).

Run from inside .claude/scripts:
    "C:/Program Files/Python314/python.exe" -m pytest test_observation_window_check.py -v

Written BEFORE the implementation (declarative-first). Covers the four
spec-mandated branches (2026-08-31-harness-takeover-objectives.md O12 CHECK,
lines 103-121) plus adjacent fail-loud and semantics branches:

Mandated (spec line 111):
  1. pass branch: 12 in-window evaluations, one FAIL episode cleared within
     48h, empty ledger -> PASS, exit 0
  2. fail branch 1: ledger with one INCIDENT line -> FAIL
     (INCIDENT_LEDGER_NONEMPTY), exit 2
  3. fail branch 2: 9 evaluations -> FAIL (VACUITY), exit 2
  4. fail branch 3: FAIL episode unresolved past 48h -> FAIL
     (UNRESOLVED_FAIL_OVER_48H), exit 2

Adjacent: WARN never fails; error records not counted; window boundaries;
missing files exit 1; malformed INCIDENT exits 1; malformed warn pair exits 1;
INCONCLUSIVE_PENDING exit 3; incident-classified episode fails (b) only; late
clear violates (c); 200-char truncated detail parses complete pairs with a
notice; pre-window failing records ignored for episode start; --json
determinism.

Fixture record shape mirrors the live sink, verified 2026-09-02:
  {"ts": "YYYY-MM-DD HH:MM:SS", "event": "hook_fire",
   "hook": "staleness_check", "decision": "pass"|"warn"|"error",
   "detail": ..., "session": null}
Warn detail joins failing entries with "; " per staleness_check._run_hook_mode.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import observation_window_check as owc  # noqa: E402

WS = "2026-09-03 00:00:00"
WE = "2026-09-17 00:00:00"
AFTER_END = "2026-09-17 01:00:00"


def _rec(ts, decision, detail, hook="staleness_check"):
    return json.dumps({
        "ts": ts, "event": "hook_fire", "hook": hook,
        "decision": decision, "detail": detail, "session": None,
    })


def _pass_rec(ts, n=14):
    return _rec(ts, "pass", "%d entries all PASS" % n)


def _write_log(tmp_path, lines, name="hook-activity.jsonl"):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _write_ledger(tmp_path, incident_lines=(), name="ledger.md"):
    p = tmp_path / name
    body = [
        "---",
        "date: 2026-09-02",
        "tags: [project/agent-governance-research, vault-log]",
        "status: active",
        "---",
        "",
        "# O12 incident ledger (fixture)",
        "",
        "- Grammar (must start at column 0): `INCIDENT | YYYY-MM-DD HH:MM"
        " | <board-entry-id> | <claim> | <why stale or phantom>`",
        "",
    ]
    body.extend(incident_lines)
    p.write_text("\n".join(body) + "\n", encoding="utf-8")
    return p


def _clean_evals(count, start_day=3):
    """count pass records, one per day starting 2026-09-<start_day> 08:00."""
    return [_pass_rec("2026-09-%02d 08:00:00" % (start_day + i))
            for i in range(count)]


def _run(log, ledger, now=AFTER_END, extra=()):
    argv = ["--window-start", WS, "--window-end", WE,
            "--run-log", str(log), "--ledger", str(ledger),
            "--now", now, "--json"]
    argv.extend(extra)
    return owc.main(argv)


def _run_json(capsys, log, ledger, now=AFTER_END, extra=()):
    code = _run(log, ledger, now, extra)
    out = capsys.readouterr().out
    return code, json.loads(out)


# ---------------------------------------------------------------------------
# Mandated pass branch - spec line 111
# ---------------------------------------------------------------------------

def test_pass_branch_12_evals_cleared_episode_empty_ledger(tmp_path, capsys):
    lines = _clean_evals(12)
    # a FAIL episode: stale at 09-04 10:00, cleared by the 09-05 08:00 pass eval
    lines.append(_rec("2026-09-04 10:00:00", "warn", "stale-x:STALE"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 0
    assert rep["verdict"] == "PASS"
    assert rep["evaluation_count"] == 13
    assert rep["failed_branches"] == []
    assert rep["incident_count"] == 0
    eps = {e["id"]: e for e in rep["episodes"]}
    assert eps["stale-x"]["status"] == "cleared"


# ---------------------------------------------------------------------------
# Mandated fail branch 1: nonempty ledger
# ---------------------------------------------------------------------------

def test_fail_branch_1_incident_ledger_nonempty(tmp_path, capsys):
    lines = _clean_evals(12)
    lines.append(_rec("2026-09-04 10:00:00", "warn", "stale-x:STALE"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path, [
        "INCIDENT | 2026-09-05 10:00 | harness-self-model | board said fresh"
        " | manifest hash was three days stale",
    ])
    code, rep = _run_json(capsys, log, ledger)
    assert code == 2
    assert rep["verdict"] == "FAIL"
    assert "INCIDENT_LEDGER_NONEMPTY" in rep["failed_branches"]
    assert rep["incident_count"] == 1
    assert any("harness-self-model" in ln for ln in rep["incident_lines"])


# ---------------------------------------------------------------------------
# Mandated fail branch 2: vacuity
# ---------------------------------------------------------------------------

def test_fail_branch_2_vacuity_9_evaluations(tmp_path, capsys):
    log = _write_log(tmp_path, _clean_evals(9))
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 2
    assert rep["verdict"] == "FAIL"
    assert rep["failed_branches"] == ["VACUITY"]
    assert rep["evaluation_count"] == 9


# ---------------------------------------------------------------------------
# Mandated fail branch 3: unresolved FAIL past 48h
# ---------------------------------------------------------------------------

def test_fail_branch_3_unresolved_fail_over_48h(tmp_path, capsys):
    # 10 clean evals through 09-12, then the board fails from 09-13 on and
    # every later eval still shows it failing -> never clears
    lines = _clean_evals(10)
    lines.append(_rec("2026-09-13 10:00:00", "warn", "stale-x:STALE"))
    lines.append(_rec("2026-09-14 10:00:00", "warn", "stale-x:STALE"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 2
    assert rep["verdict"] == "FAIL"
    assert "UNRESOLVED_FAIL_OVER_48H" in rep["failed_branches"]
    eps = {e["id"]: e for e in rep["episodes"]}
    assert eps["stale-x"]["status"] == "unresolved_over_48h"


# ---------------------------------------------------------------------------
# WARN semantics (risk flag 3): a governing-entry WARN is not a FAIL
# ---------------------------------------------------------------------------

def test_warn_verdict_never_enters_fail_set(tmp_path, capsys):
    lines = _clean_evals(10)
    lines.append(_rec("2026-09-04 09:00:00", "warn", "governing-size:WARN"))
    lines.append(_rec("2026-09-05 09:00:00", "warn", "governing-size:WARN"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 0
    assert rep["verdict"] == "PASS"
    assert rep["episodes"] == []          # WARN opens no episode
    assert rep["evaluation_count"] == 12  # warn records still count as evals


def test_error_records_reported_but_not_counted_as_evaluations(tmp_path, capsys):
    lines = _clean_evals(9)
    lines.extend([_rec("2026-09-%02d 09:30:00" % d, "error", "ManifestError")
                  for d in (4, 5, 6)])
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 2
    assert rep["failed_branches"] == ["VACUITY"]
    assert rep["evaluation_count"] == 9
    assert rep["error_run_count"] == 3


# ---------------------------------------------------------------------------
# Window filtering
# ---------------------------------------------------------------------------

def test_out_of_window_records_excluded_both_sides(tmp_path, capsys):
    lines = _clean_evals(8)
    lines.append(_pass_rec("2026-09-01 08:00:00"))   # before start
    lines.append(_pass_rec("2026-09-18 08:00:00"))   # after end
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert rep["evaluation_count"] == 8
    assert code == 2 and rep["failed_branches"] == ["VACUITY"]


def test_boundary_start_inclusive_end_exclusive(tmp_path, capsys):
    lines = _clean_evals(9)
    lines.append(_pass_rec("2026-09-03 00:00:00"))   # == start: included (10th)
    lines.append(_pass_rec("2026-09-17 00:00:00"))   # == end: excluded
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert rep["evaluation_count"] == 10
    assert code == 0 and rep["verdict"] == "PASS"


def test_other_hooks_records_are_ignored(tmp_path, capsys):
    lines = _clean_evals(10)
    lines.append(_rec("2026-09-04 11:00:00", "warn", "whatever",
                      hook="em-dash-guard"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert rep["evaluation_count"] == 10
    assert code == 0


def test_pre_window_failing_record_does_not_start_episode(tmp_path, capsys):
    lines = _clean_evals(12)
    lines.append(_rec("2026-09-01 10:00:00", "warn", "stale-x:STALE"))  # pre-window
    lines.append(_rec("2026-09-04 10:00:00", "warn", "stale-x:STALE"))  # in-window start
    # cleared by the 09-05 08:00 pass eval: within 48h of the IN-window start,
    # over 48h after the pre-window record. PASS proves the episode started
    # in-window (DD-11).
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 0
    eps = {e["id"]: e for e in rep["episodes"]}
    assert eps["stale-x"]["start"] == "2026-09-04 10:00:00"
    assert eps["stale-x"]["status"] == "cleared"


# ---------------------------------------------------------------------------
# Record/usage errors exit 1
# ---------------------------------------------------------------------------

def test_missing_run_log_exits_1(tmp_path, capsys):
    ledger = _write_ledger(tmp_path)
    code = _run(tmp_path / "absent.jsonl", ledger)
    assert code == 1
    assert "RECORD ERROR" in capsys.readouterr().err


def test_missing_ledger_exits_1(tmp_path, capsys):
    log = _write_log(tmp_path, _clean_evals(12))
    code = _run(log, tmp_path / "absent.md")
    assert code == 1
    assert "RECORD ERROR" in capsys.readouterr().err


def test_malformed_incident_line_exits_1(tmp_path, capsys):
    log = _write_log(tmp_path, _clean_evals(12))
    ledger = _write_ledger(tmp_path, [
        "INCIDENT | 2026-09-05 10:00 | stale-x | only four fields",
    ])
    code = _run(log, ledger)
    assert code == 1
    assert "RECORD ERROR" in capsys.readouterr().err


def test_malformed_warn_pair_exits_1(tmp_path, capsys):
    lines = _clean_evals(12)
    lines.append(_rec("2026-09-04 10:00:00", "warn", "stale-x:BOGUSVERDICT"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code = _run(log, ledger)
    assert code == 1
    assert "RECORD ERROR" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# INCONCLUSIVE_PENDING (DD-7): young unresolved episode, exit 3
# ---------------------------------------------------------------------------

def test_pending_episode_younger_than_48h_is_inconclusive_exit_3(tmp_path, capsys):
    lines = _clean_evals(11)
    lines.append(_rec("2026-09-16 20:00:00", "warn", "stale-x:STALE"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger, now="2026-09-17 01:00:00")
    assert code == 3
    assert rep["verdict"] == "INCONCLUSIVE_PENDING"
    assert rep["failed_branches"] == []
    assert rep["rerun_after"] == "2026-09-18 20:00:00"
    eps = {e["id"]: e for e in rep["episodes"]}
    assert eps["stale-x"]["status"] == "pending"


# ---------------------------------------------------------------------------
# Incident-classified episode: satisfies (c), while the line fails (b)
# ---------------------------------------------------------------------------

def test_incident_classified_episode_fails_branch_b_only(tmp_path, capsys):
    # 10 clean evals through 09-12; phantom-x fails from 09-13 and never
    # clears mechanically, but a ledger line inside 48h classifies it
    lines = _clean_evals(10)
    lines.append(_rec("2026-09-13 10:00:00", "warn", "phantom-x:STALE"))
    lines.append(_rec("2026-09-14 10:00:00", "warn", "phantom-x:STALE"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path, [
        "INCIDENT | 2026-09-13 12:00 | phantom-x | board asserted fresh"
        " | artifact deleted, entry phantom",
    ])
    code, rep = _run_json(capsys, log, ledger)
    assert code == 2
    assert rep["verdict"] == "FAIL"
    assert rep["failed_branches"] == ["INCIDENT_LEDGER_NONEMPTY"]
    eps = {e["id"]: e for e in rep["episodes"]}
    assert eps["phantom-x"]["status"] == "incident_classified"


def test_clear_later_than_48h_is_still_a_violation(tmp_path, capsys):
    # explicit timeline: every evaluation between episode start and the clear
    # shows the failure, so the first clean evaluation lands 74h after start
    lines = [
        _pass_rec("2026-09-03 08:00:00"),
        _pass_rec("2026-09-04 08:00:00"),
        _rec("2026-09-04 10:00:00", "warn", "stale-x:STALE"),  # episode start
        _rec("2026-09-05 08:00:00", "warn", "stale-x:STALE"),
        _rec("2026-09-06 08:00:00", "warn", "stale-x:STALE"),
        _pass_rec("2026-09-07 12:00:00"),                      # clear at +74h
        _pass_rec("2026-09-08 08:00:00"),
        _pass_rec("2026-09-09 08:00:00"),
        _pass_rec("2026-09-10 08:00:00"),
        _pass_rec("2026-09-11 08:00:00"),
        _pass_rec("2026-09-12 08:00:00"),
    ]
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 2
    assert "UNRESOLVED_FAIL_OVER_48H" in rep["failed_branches"]
    eps = {e["id"]: e for e in rep["episodes"]}
    assert eps["stale-x"]["status"] == "cleared_late"


# ---------------------------------------------------------------------------
# Truncated detail (DD-11): exactly 200 chars, drop trailing partial pair
# ---------------------------------------------------------------------------

def test_truncated_200_char_detail_parses_complete_pairs_with_notice(tmp_path, capsys):
    full = "; ".join("entry-%02d:STALE" % i for i in range(30))
    detail = full[:200]
    assert len(detail) == 200
    assert not detail.endswith("STALE")  # cut mid-pair by construction
    lines = _clean_evals(12)
    lines.append(_rec("2026-09-04 10:00:00", "warn", detail))
    # the next clean eval (09-05 08:00) clears every parsed episode within 48h
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 0
    assert rep["verdict"] == "PASS"
    assert any("truncat" in n.lower() for n in rep["notices"])
    parsed_ids = {e["id"] for e in rep["episodes"]}
    assert all(i.startswith("entry-") for i in parsed_ids)
    # the partial trailing token never became an episode id
    complete = full[:200].rsplit("; ", 1)[0]
    n_complete = len(complete.split("; "))
    assert len(parsed_ids) == n_complete


def test_torn_non_json_line_is_skipped_with_a_loud_notice(tmp_path, capsys):
    # the live multi-writer sink holds torn lines (a bare brace from an
    # interleaved append); they carry no ts or hook, so the checker skips
    # them but says so loudly instead of aborting the real-record run
    lines = _clean_evals(10)
    lines.insert(4, "}")
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    code, rep = _run_json(capsys, log, ledger)
    assert code == 0
    assert rep["verdict"] == "PASS"
    assert rep["evaluation_count"] == 10
    assert any("unparseable" in n for n in rep["notices"])
    assert any("line(s) 5" in n for n in rep["notices"])


# ---------------------------------------------------------------------------
# Determinism: --json double run is byte-identical
# ---------------------------------------------------------------------------

def test_json_output_is_byte_identical_across_runs(tmp_path, capsys):
    lines = _clean_evals(12)
    lines.append(_rec("2026-09-04 10:00:00", "warn", "stale-x:STALE"))
    log = _write_log(tmp_path, lines)
    ledger = _write_ledger(tmp_path)
    _run(log, ledger)
    out1 = capsys.readouterr().out
    _run(log, ledger)
    out2 = capsys.readouterr().out
    assert out1 == out2
    assert out1  # non-empty
