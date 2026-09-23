"""Tests for lint_pass_qa_health.py (Pass W, 2026-09-21).

Declarative-first, on the test_lint_pass_work_index_stale.py fixture pattern:
a tmp vault with its own governance log, qa-logs, task plans and state dir,
so no live file is read or written.
"""
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import lint_pass_qa_health as pw  # noqa: E402

TODAY = "2026-09-21"


def gov_line(ts, **extra):
    rec = {"ts": ts, "schema": 2, "event": "pass", "hook": "work-verification-check", "session": "s"}
    rec.update(extra)
    return json.dumps(rec)


def entry(date, passed, total, untested="the 502 branch of the poster", fail="none", run=False, verifier=None):
    scope = "- [run] the script runs on real input\n" if run else "- [execute] the suite passes\n"
    ver = f"\nVerifier: {verifier}" if verifier else ""
    return (f"\n\n## {date} 10:00 local, build\n\nQA SCOPE\n{scope}Source: x\n\n"
            f"QA REPORT\nPASS: {passed} / {total}\nFAIL: {fail}\nUntested: {untested}{ver}\n")


def make_vault(tmp_path, gov_lines, entries, plan_text="- [ ] **T-1 open**\n"):
    (tmp_path / "Projects" / "Demo" / "work").mkdir(parents=True)
    (tmp_path / ".claude" / "hooks").mkdir(parents=True)
    (tmp_path / ".claude" / "hooks" / "governance-log.jsonl").write_text("\n".join(gov_lines) + "\n", encoding="utf-8")
    (tmp_path / "Projects" / "Demo" / "work" / "qa-log.md").write_text("# log" + "".join(entries), encoding="utf-8")
    (tmp_path / "Projects" / "Demo" / "task_plan.md").write_text(plan_text, encoding="utf-8")
    return tmp_path


def run(tmp_path, capsys, today=TODAY):
    rc = pw.main(["--vault", str(tmp_path), "--state-dir", str(tmp_path / ".claude" / "hooks" / "_state"), "--today", today])
    return rc, capsys.readouterr().out


def test_a_healthy_window_is_clean_and_prints_the_measurement(tmp_path, capsys):
    gov = [gov_line("2026-09-15 10:00:00", has_qa_report=True) for _ in range(12)]
    entries = [entry("2026-09-1" + str(i % 9 + 1), 2, 2, run=True, verifier="workflow") for i in range(12)]
    entries[0] = entry("2026-09-12", 1, 2, fail="claim 2 refuted", run=True)
    v = make_vault(tmp_path, gov, entries)
    rc, out = run(v, capsys)
    assert rc == 0, out
    assert "QA_HEALTH window_days=30 qa_turns=12 inline_qa=0 entries=12" in out
    assert "fail_entries=1 run_entries=12 verifier_stated=11 workflow_entries=11 workflow_null=0 partial_stamps=0 baseline_partial_stamps=none" in out
    assert "QA_HEALTH_DEGRADED" not in out


def test_inline_qa_share_over_threshold_is_a_finding(tmp_path, capsys):
    gov = [gov_line("2026-09-15 10:00:00", has_qa_report=True) for _ in range(8)]
    gov += [gov_line("2026-09-15 10:00:00", event="block", check="inline-qa-without-skill") for _ in range(4)]
    v = make_vault(tmp_path, gov, [])
    rc, out = run(v, capsys)
    assert rc == 1
    assert "QA_HEALTH_DEGRADED  metric=inline_qa value=0.333 threshold=0.1" in out


def test_the_null_untested_phrase_everywhere_is_a_finding(tmp_path, capsys):
    entries = [entry("2026-09-15", 2, 2, untested="none deliberately", run=True) for _ in range(10)]
    entries[0] = entry("2026-09-15", 1, 2, fail="x", untested="none deliberately", run=True)
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 1
    assert "metric=none_deliberately value=1.0 threshold=0.6" in out


def test_no_run_class_claims_is_a_finding(tmp_path, capsys):
    entries = [entry("2026-09-15", 2, 2) for _ in range(10)]
    entries[0] = entry("2026-09-15", 1, 2, fail="x")
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 1
    assert "metric=run_class value=0.0 threshold=0.2" in out


def test_an_instrument_that_never_fails_is_a_finding(tmp_path, capsys):
    entries = [entry("2026-09-15", 2, 2, run=True) for _ in range(10)]
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 1
    assert "metric=fail_entries value=0.0 threshold=0.02" in out


def test_rates_need_a_denominator(tmp_path, capsys):
    """Three entries, all null-phrase, no run claims: not enough to judge."""
    entries = [entry("2026-09-15", 2, 2, untested="none deliberately") for _ in range(3)]
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 0, out


def test_entries_outside_the_window_are_ignored(tmp_path, capsys):
    entries = [entry("2026-06-01", 2, 2, untested="none deliberately") for _ in range(10)]
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 0
    assert "entries=0" in out


def test_partial_stamps_first_run_is_the_baseline_and_only_growth_fires(tmp_path, capsys):
    plan = "- [x] **T-1 done**  ← PASS: 2 / 3\n- [x] **T-2 done**  ← QA PASS — x PASS: 3 / 3\n"
    v = make_vault(tmp_path, [], [], plan_text=plan)
    rc, out = run(v, capsys)
    assert rc == 0, out
    assert "partial_stamps=1 baseline_partial_stamps=none" in out
    state = json.loads((v / ".claude" / "hooks" / "_state" / "qa-health.json").read_text(encoding="utf-8"))
    assert state["baseline_partial_stamps"] == 1
    rc, out = run(v, capsys)
    assert rc == 0 and "baseline_partial_stamps=1" in out
    (v / "Projects" / "Demo" / "task_plan.md").write_text(plan + "- [x] **T-3 done**  ← PASS: 0 / 9\n", encoding="utf-8")
    rc, out = run(v, capsys)
    assert rc == 1
    assert "metric=partial_stamps_growth value=1 threshold=0" in out
    state = json.loads((v / ".claude" / "hooks" / "_state" / "qa-health.json").read_text(encoding="utf-8"))
    assert state["baseline_partial_stamps"] == 1, "the baseline is not moved by growth"


def test_missing_governance_log_is_a_derivation_failure(tmp_path, capsys):
    v = make_vault(tmp_path, [], [])
    (v / ".claude" / "hooks" / "governance-log.jsonl").unlink()
    rc, out = run(v, capsys)
    assert rc == 2 and "DERIVATION FAILURE" in out


def test_state_file_carries_the_findings_for_the_digest(tmp_path, capsys):
    gov = [gov_line("2026-09-15 10:00:00", has_qa_report=True) for _ in range(8)]
    gov += [gov_line("2026-09-15 10:00:00", event="block", check="inline-qa-without-skill") for _ in range(4)]
    v = make_vault(tmp_path, gov, [])
    run(v, capsys)
    state = json.loads((v / ".claude" / "hooks" / "_state" / "qa-health.json").read_text(encoding="utf-8"))
    assert state["last_run"] == TODAY
    assert {"metric": "inline_qa", "value": 0.333, "threshold": 0.1} in state["findings"]
    # twelve QA turns and an empty log is itself a finding (build review N6)
    assert {"metric": "entries_logged", "value": 0, "threshold": 10} in state["findings"]


# --- build review N6: four corpora that read green while degraded -------------

def test_the_workflows_own_null_phrase_is_counted_as_null(tmp_path, capsys):
    entries = [entry("2026-09-15", 2, 2, untested="none deliberately (scope node: every path has a claim)", run=True, verifier="workflow") for _ in range(10)]
    entries[0] = entry("2026-09-15", 1, 2, fail="x", untested="none deliberately (scope node: all covered)", run=True, verifier="workflow")
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 1
    assert "none_deliberately=10" in out
    assert "metric=none_deliberately" in out


def test_entries_are_counted_by_their_pass_line_not_the_literal_report_word(tmp_path, capsys):
    entries = [entry("2026-09-15", 3, 3, run=True).replace("QA REPORT\n", "") for _ in range(10)]
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert "entries=10" in out


def test_qa_reports_with_no_log_entries_is_a_finding(tmp_path, capsys):
    """QA reports were filed (governance log) but the qa-logs hold almost nothing:
    the record stopped, which the rate metrics cannot see."""
    gov = [gov_line("2026-09-15 10:00:00", has_qa_report=True) for _ in range(12)]
    v = make_vault(tmp_path, gov, [entry("2026-09-15", 2, 2, run=True)])
    rc, out = run(v, capsys)
    assert rc == 1
    assert "metric=entries_logged value=1 threshold=10" in out


def test_the_workflow_path_is_measured_on_its_own(tmp_path, capsys):
    """13 of 13 workflow-path entries were null on the original review while the
    prose path masked them in the whole-corpus rate."""
    prose = [entry("2026-09-15", 2, 2, untested="the 502 branch", run=True, verifier="main-session") for _ in range(20)]
    wf = [entry("2026-09-15", 2, 2, untested="none deliberately (scope node: x)", run=True, verifier="workflow") for _ in range(10)]
    prose[0] = entry("2026-09-15", 1, 2, fail="x", untested="the 502 branch", run=True, verifier="main-session")
    v = make_vault(tmp_path, [], prose + wf)
    rc, out = run(v, capsys)
    assert rc == 1
    assert "workflow_entries=10 workflow_null=10" in out
    assert "metric=workflow_null_share value=1.0 threshold=0.6" in out


def test_a_corpus_that_never_states_its_verifier_is_a_finding(tmp_path, capsys):
    entries = [entry("2026-09-15", 2, 2, run=True) for _ in range(10)]
    entries[0] = entry("2026-09-15", 1, 2, fail="x", run=True)
    v = make_vault(tmp_path, [], entries)
    rc, out = run(v, capsys)
    assert rc == 1
    assert "metric=verifier_stated value=0.0 threshold=0.5" in out
