"""
test_ceremony_cost_report.py - pytest suite for ceremony_cost_report.py.

Spec: Projects/Agent-Governance-Research/work/2026-08-26-criterion-2-metric-definition.md

Written BEFORE ceremony_cost_report.py exists. The first run of this suite must
fail with a collection error (module not found), proving the tests exercise
real behaviour rather than an implementation shaped to already pass.

Ground truth for every assertion is manual counting of the fixture data laid
out in this file, not the script's own output.

Covers:
  - streaming JSONL parse: malformed lines, non-dict JSON, schema-incomplete
    records, and unrelated (`block`) events, each skipped and counted
    separately
  - environment == test exclusion, counted
  - --since filtering by ts date
  - medians (never means) per segment, record count reported alongside every
    median, computed on integers so a median can legitimately land on a .5
  - the three measures (dispatches, tool_calls, tokens) reported as separate
    keys, never folded into one index
  - segment mix (proportion per classification) for each of the two event
    populations, since token_breakdown and turn_summary carry the
    classification under different field names and are never joined
  - fail-loud behaviour on every way the population can go to zero: empty
    file, all-malformed file, --since excluding everything, environment=test
    excluding everything, and one of the two event populations being absent
    entirely (which would otherwise silently zero out one whole measure)
  - byte-for-byte determinism across repeated runs, both in-process and via a
    real subprocess invocation, and independence from the caller's cwd
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_SCRIPT = SCRIPT_DIR / "ceremony_cost_report.py"

sys.path.insert(0, str(SCRIPT_DIR))

import ceremony_cost_report as ccr  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _tb(ts, task_type, tokens, tool_calls, environment="prod", session="s1"):
    """A token_breakdown record shaped like the real log."""
    return {
        "ts": ts, "event": "token_breakdown", "session": session,
        "environment": environment, "task_type": task_type,
        "turn_total_tokens": tokens, "tool_calls": tool_calls,
        "turn_cost_usd": 0.01, "skill_names": [], "by_subagent": {},
    }


def _ts(ts, seg_type, agent_count, skill_count, environment="prod", session="s1"):
    """A turn_summary record shaped like the real log."""
    return {
        "ts": ts, "event": "turn_summary", "session": session, "type": seg_type,
        "agent_count": agent_count, "skill_count": skill_count,
        "environment": environment, "domain": "vault", "must_dispatch": [],
    }


def _write_log(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write((line if isinstance(line, str) else json.dumps(line)) + "\n")


@pytest.fixture
def basic_log(tmp_path):
    """12 lines: 5 usable token_breakdown, 3 usable turn_summary, 1 malformed,
    1 unrelated event, 1 test-environment token_breakdown, 1 test-environment
    turn_summary. Counts below are the manually-derived ground truth used by
    every assertion against this fixture.
    """
    path = tmp_path / "governance-log.jsonl"
    lines = [
        _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1}),
        _tb("2026-08-10 09:05:00", "Quick", 700, {"Read": 1, "Bash": 1}),
        _tb("2026-08-10 09:10:00", "Quick", 900, {}),
        _tb("2026-08-11 10:00:00", "Analysis", 5000, {"Read": 3, "Bash": 2}),
        _tb("2026-08-11 10:05:00", "Analysis", 6000, {"Read": 4}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
        _ts("2026-08-10 09:05:05", "Quick", 1, 0),
        _ts("2026-08-11 10:00:05", "Analysis", 1, 2),
        "{not valid json",
        {"ts": "2026-08-10 09:00:00", "event": "block", "session": "s1", "hook": "x"},
        _tb("2026-08-10 09:15:00", "Quick", 100, {}, environment="test"),
        _ts("2026-08-10 09:15:05", "Quick", 0, 0, environment="test"),
    ]
    _write_log(path, lines)
    return path


# ---------------------------------------------------------------------------
# Parsing accounting: every line must land in exactly one bucket
# ---------------------------------------------------------------------------

def test_malformed_line_counted(basic_log):
    report = ccr.compute_report(basic_log)
    assert report["metadata"]["malformed_lines_skipped"] == 1


def test_other_event_records_counted(basic_log):
    report = ccr.compute_report(basic_log)
    assert report["metadata"]["other_event_records_skipped"] == 1


def test_test_environment_exclusion_counted(basic_log):
    report = ccr.compute_report(basic_log)
    excluded = report["metadata"]["test_environment_excluded"]
    assert excluded == {"token_breakdown": 1, "turn_summary": 1}


def test_total_lines_reconciles_to_all_buckets(basic_log):
    report = ccr.compute_report(basic_log)
    m = report["metadata"]
    usable = m["usable_records"]
    since_excl = m["since_filter_excluded"]
    test_excl = m["test_environment_excluded"]
    accounted = (
        m["malformed_lines_skipped"]
        + m["schema_incomplete_records_skipped"]
        + m["other_event_records_skipped"]
        + usable["token_breakdown"] + usable["turn_summary"]
        + since_excl["token_breakdown"] + since_excl["turn_summary"]
        + test_excl["token_breakdown"] + test_excl["turn_summary"]
    )
    assert accounted == m["total_lines_read"] == 12


def test_non_dict_json_line_counted_as_malformed(tmp_path):
    path = tmp_path / "log.jsonl"
    lines = [
        [1, 2, 3],
        _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
    ]
    _write_log(path, lines)
    report = ccr.compute_report(path)
    assert report["metadata"]["malformed_lines_skipped"] == 1


def test_schema_incomplete_record_counted_separately_from_malformed(tmp_path):
    path = tmp_path / "log.jsonl"
    bad_tb = _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1})
    del bad_tb["turn_total_tokens"]
    lines = [
        bad_tb,
        _tb("2026-08-10 09:05:00", "Quick", 500, {"Read": 1}),
        _ts("2026-08-10 09:05:05", "Quick", 0, 0),
    ]
    _write_log(path, lines)
    report = ccr.compute_report(path)
    assert report["metadata"]["schema_incomplete_records_skipped"] == 1
    assert report["metadata"]["malformed_lines_skipped"] == 0


def test_environment_wrong_type_is_schema_incomplete_not_crash(tmp_path):
    path = tmp_path / "log.jsonl"
    bad = _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1})
    bad["environment"] = 123
    lines = [
        bad,
        _tb("2026-08-10 09:05:00", "Quick", 600, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
    ]
    _write_log(path, lines)
    report = ccr.compute_report(path)
    assert report["metadata"]["schema_incomplete_records_skipped"] == 1
    assert report["measures"]["tokens"]["headline"]["count"] == 1


def test_tool_calls_dict_with_non_numeric_value_is_schema_incomplete(tmp_path):
    path = tmp_path / "log.jsonl"
    bad = _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": "many"})
    lines = [
        bad,
        _tb("2026-08-10 09:05:00", "Quick", 600, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
    ]
    _write_log(path, lines)
    report = ccr.compute_report(path)
    assert report["metadata"]["schema_incomplete_records_skipped"] == 1
    assert report["measures"]["tokens"]["headline"]["count"] == 1


# ---------------------------------------------------------------------------
# Medians and record counts (manually computed ground truth)
# ---------------------------------------------------------------------------

def test_tokens_median_and_count_per_segment(basic_log):
    report = ccr.compute_report(basic_log)
    tokens = report["measures"]["tokens"]
    assert tokens["headline_segment"] == "Quick"
    assert tokens["headline"] == {"count": 3, "median": 700}  # [500, 700, 900]
    control = {c["segment"]: c for c in tokens["control"]}
    assert control["Analysis"]["count"] == 2
    assert control["Analysis"]["median"] == 5500.0  # mean of 5000, 6000


def test_tool_calls_median_and_count_per_segment(basic_log):
    report = ccr.compute_report(basic_log)
    tool_calls = report["measures"]["tool_calls"]
    assert tool_calls["headline"] == {"count": 3, "median": 1}  # [1, 2, 0] -> 1
    control = {c["segment"]: c for c in tool_calls["control"]}
    assert control["Analysis"]["count"] == 2
    assert control["Analysis"]["median"] == 4.5  # [5, 4]


def test_dispatches_median_and_count_per_segment(basic_log):
    report = ccr.compute_report(basic_log)
    dispatches = report["measures"]["dispatches"]
    assert dispatches["headline"] == {"count": 2, "median": 0.5}  # [0, 1]
    control = {c["segment"]: c for c in dispatches["control"]}
    assert control["Analysis"] == {"segment": "Analysis", "count": 1, "median": 3}


def test_median_is_resistant_to_outliers(tmp_path):
    """The exact defect the spec names: a mean would report the outlier."""
    path = tmp_path / "log.jsonl"
    token_values = [100, 110, 105, 95, 1885577]
    lines = [
        _tb(f"2026-08-10 09:0{i}:00", "Quick", v, {"Read": 1})
        for i, v in enumerate(token_values)
    ]
    lines.append(_ts("2026-08-10 09:00:05", "Quick", 0, 0))
    _write_log(path, lines)
    report = ccr.compute_report(path)
    median = report["measures"]["tokens"]["headline"]["median"]
    mean = sum(token_values) / len(token_values)
    assert median == 105
    assert median < mean / 100


def test_quick_segment_absent_reports_null_median_not_crash(tmp_path):
    path = tmp_path / "log.jsonl"
    lines = [
        _tb("2026-08-10 09:00:00", "Analysis", 1000, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Analysis", 1, 0),
    ]
    _write_log(path, lines)
    report = ccr.compute_report(path)
    assert report["measures"]["tokens"]["headline"] == {"count": 0, "median": None}
    assert report["measures"]["dispatches"]["headline"] == {"count": 0, "median": None}


# ---------------------------------------------------------------------------
# Three measures kept separate; never combined into an index
# ---------------------------------------------------------------------------

def test_measures_are_three_separate_keys_never_an_index(basic_log):
    report = ccr.compute_report(basic_log)
    assert set(report["measures"].keys()) == {"dispatches", "tool_calls", "tokens"}
    for key, measure in report["measures"].items():
        assert "index" not in measure
        assert "combined" not in measure
        assert "score" not in measure


def test_dispatches_sourced_from_turn_summary_only(basic_log):
    report = ccr.compute_report(basic_log)
    assert report["measures"]["dispatches"]["source_event"] == "turn_summary"


def test_tool_calls_and_tokens_sourced_from_token_breakdown_only(basic_log):
    report = ccr.compute_report(basic_log)
    assert report["measures"]["tool_calls"]["source_event"] == "token_breakdown"
    assert report["measures"]["tokens"]["source_event"] == "token_breakdown"


# ---------------------------------------------------------------------------
# Segment mix: proportion per classification, per event population
# ---------------------------------------------------------------------------

def test_segment_mix_proportions_sum_to_one(basic_log):
    report = ccr.compute_report(basic_log)
    for population in ("token_breakdown", "turn_summary"):
        mix = report["segment_mix"][population]
        total = sum(entry["proportion"] for entry in mix.values())
        assert abs(total - 1.0) < 1e-9


def test_segment_mix_counts_match_measure_counts(basic_log):
    report = ccr.compute_report(basic_log)
    tb_mix = report["segment_mix"]["token_breakdown"]
    assert tb_mix["Quick"]["count"] == 3
    assert tb_mix["Analysis"]["count"] == 2
    ts_mix = report["segment_mix"]["turn_summary"]
    assert ts_mix["Quick"]["count"] == 2
    assert ts_mix["Analysis"]["count"] == 1


# ---------------------------------------------------------------------------
# --since filtering
# ---------------------------------------------------------------------------

def test_since_filter_includes_on_or_after_date(tmp_path):
    path = tmp_path / "log.jsonl"
    lines = [
        _tb("2026-08-09 09:00:00", "Quick", 100, {}),
        _tb("2026-08-10 09:00:00", "Quick", 200, {}),
        _ts("2026-08-09 09:00:05", "Quick", 0, 0),
        _ts("2026-08-10 09:00:05", "Quick", 1, 0),
    ]
    _write_log(path, lines)
    report = ccr.compute_report(path, since_date=date(2026, 8, 10))
    tokens = report["measures"]["tokens"]["headline"]
    assert tokens == {"count": 1, "median": 200}
    assert report["metadata"]["since_filter_excluded"]["token_breakdown"] == 1


def test_since_none_excludes_nothing(basic_log):
    with_since = ccr.compute_report(basic_log, since_date=None)
    assert with_since["metadata"]["since_filter_excluded"] == {
        "token_breakdown": 0, "turn_summary": 0,
    }


# ---------------------------------------------------------------------------
# Fail loudly on empty population, at every stage it can happen
# ---------------------------------------------------------------------------

def test_compute_report_raises_on_empty_file(tmp_path):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ccr.EmptyPopulationError, match="zero lines"):
        ccr.compute_report(path)


def test_compute_report_raises_when_all_lines_malformed(tmp_path):
    path = tmp_path / "log.jsonl"
    _write_log(path, ["not json", "{also not json", "[1,2]"])
    with pytest.raises(ccr.EmptyPopulationError):
        ccr.compute_report(path)


def test_compute_report_raises_when_since_excludes_everything(basic_log):
    with pytest.raises(ccr.EmptyPopulationError, match="--since"):
        ccr.compute_report(basic_log, since_date=date(2099, 1, 1))


def test_compute_report_raises_when_only_test_environment_present(tmp_path):
    path = tmp_path / "log.jsonl"
    lines = [
        _tb("2026-08-10 09:00:00", "Quick", 500, {}, environment="test"),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0, environment="test"),
    ]
    _write_log(path, lines)
    with pytest.raises(ccr.EmptyPopulationError, match="environment=test"):
        ccr.compute_report(path)


def test_compute_report_raises_when_turn_summary_population_absent(tmp_path):
    path = tmp_path / "log.jsonl"
    lines = [
        _tb("2026-08-10 09:00:00", "Quick", 500, {}),
        _tb("2026-08-10 09:05:00", "Analysis", 5000, {}),
    ]
    _write_log(path, lines)
    with pytest.raises(ccr.EmptyPopulationError, match="turn_summary"):
        ccr.compute_report(path)


def test_compute_report_raises_when_token_breakdown_population_absent(tmp_path):
    path = tmp_path / "log.jsonl"
    lines = [
        _ts("2026-08-10 09:00:00", "Quick", 0, 0),
        _ts("2026-08-10 09:05:00", "Analysis", 1, 1),
    ]
    _write_log(path, lines)
    with pytest.raises(ccr.EmptyPopulationError, match="token_breakdown"):
        ccr.compute_report(path)


def test_main_exits_nonzero_and_names_the_filter_on_empty_file(tmp_path, monkeypatch, capsys):
    path = tmp_path / "empty.jsonl"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(ccr, "default_log_path", lambda: path)
    exit_code = ccr.main([])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert captured.out == ""
    assert "zero lines" in captured.err.lower()


def test_main_exits_nonzero_on_missing_log_file(tmp_path, monkeypatch, capsys):
    missing = tmp_path / "does_not_exist.jsonl"
    monkeypatch.setattr(ccr, "default_log_path", lambda: missing)
    exit_code = ccr.main([])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "not found" in captured.err.lower()


def test_main_exits_nonzero_naming_missing_turn_summary(tmp_path, monkeypatch, capsys):
    path = tmp_path / "log.jsonl"
    _write_log(path, [_tb("2026-08-10 09:00:00", "Quick", 500, {})])
    monkeypatch.setattr(ccr, "default_log_path", lambda: path)
    exit_code = ccr.main([])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "turn_summary" in captured.err
    assert "dispatches" in captured.err


# ---------------------------------------------------------------------------
# CLI surface: --json, default table, --since
# ---------------------------------------------------------------------------

def test_main_json_flag_emits_valid_json(tmp_path, monkeypatch, capsys):
    path = tmp_path / "log.jsonl"
    _write_log(path, [
        _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
    ])
    monkeypatch.setattr(ccr, "default_log_path", lambda: path)
    exit_code = ccr.main(["--json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    parsed = json.loads(captured.out)
    assert parsed["measures"]["tokens"]["headline"]["count"] == 1


def test_main_default_output_is_a_human_readable_table(tmp_path, monkeypatch, capsys):
    path = tmp_path / "log.jsonl"
    _write_log(path, [
        _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
    ])
    monkeypatch.setattr(ccr, "default_log_path", lambda: path)
    exit_code = ccr.main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Ceremony Cost Report" in captured.out
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)


def test_main_since_flag_filters(tmp_path, monkeypatch, capsys):
    path = tmp_path / "log.jsonl"
    _write_log(path, [
        _tb("2026-08-09 09:00:00", "Quick", 100, {}),
        _tb("2026-08-10 09:00:00", "Quick", 200, {}),
        _ts("2026-08-09 09:00:05", "Quick", 0, 0),
        _ts("2026-08-10 09:00:05", "Quick", 1, 0),
    ])
    monkeypatch.setattr(ccr, "default_log_path", lambda: path)
    exit_code = ccr.main(["--json", "--since", "2026-08-10"])
    captured = capsys.readouterr()
    assert exit_code == 0
    parsed = json.loads(captured.out)
    assert parsed["measures"]["tokens"]["headline"]["count"] == 1


def test_invalid_since_date_format_raises_system_exit():
    with pytest.raises(SystemExit):
        ccr.parse_args(["--since", "not-a-date"])


def test_render_table_labels_headline_and_control(basic_log):
    report = ccr.compute_report(basic_log)
    table = ccr.render_table(report)
    assert "HEADLINE Quick" in table
    assert "control  Analysis" in table


def test_render_json_round_trips_the_report(basic_log):
    report = ccr.compute_report(basic_log)
    parsed = json.loads(ccr.render_json(report))
    assert parsed == report


# ---------------------------------------------------------------------------
# Determinism: same input, same output, byte for byte
# ---------------------------------------------------------------------------

def test_json_output_deterministic_in_process(basic_log):
    report_a = ccr.compute_report(basic_log)
    report_b = ccr.compute_report(basic_log)
    assert ccr.render_json(report_a) == ccr.render_json(report_b)


def test_table_output_deterministic_in_process(basic_log):
    report_a = ccr.compute_report(basic_log)
    report_b = ccr.compute_report(basic_log)
    assert ccr.render_table(report_a) == ccr.render_table(report_b)


def _build_isolated_layout(base_dir, log_lines):
    """Recreate the real .claude/scripts + .claude/hooks sibling layout so the
    script's own default_log_path() resolution can be exercised as a real
    subprocess, independent of pytest's cwd.
    """
    scripts_dir = base_dir / ".claude" / "scripts"
    hooks_dir = base_dir / ".claude" / "hooks"
    scripts_dir.mkdir(parents=True)
    hooks_dir.mkdir(parents=True)
    shutil.copy2(SOURCE_SCRIPT, scripts_dir / "ceremony_cost_report.py")
    _write_log(hooks_dir / "governance-log.jsonl", log_lines)
    return scripts_dir / "ceremony_cost_report.py"


def _run_cli(script_path, args, cwd):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(script_path)] + args,
        cwd=str(cwd), capture_output=True, env=env,
    )


@pytest.mark.skipif(not SOURCE_SCRIPT.exists(), reason="implementation not built yet")
def test_cli_subprocess_output_is_byte_identical_across_runs(tmp_path):
    log_lines = [
        _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1}),
        _tb("2026-08-11 10:00:00", "Analysis", 5000, {"Read": 3}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
        _ts("2026-08-11 10:00:05", "Analysis", 1, 1),
    ]
    layout = tmp_path / "run"
    layout.mkdir()
    script = _build_isolated_layout(layout, log_lines)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()

    result_1 = _run_cli(script, ["--json"], cwd=other_cwd)
    result_2 = _run_cli(script, ["--json"], cwd=other_cwd)

    assert result_1.returncode == 0, result_1.stderr
    assert result_2.returncode == 0, result_2.stderr
    assert result_1.stdout == result_2.stdout


@pytest.mark.skipif(not SOURCE_SCRIPT.exists(), reason="implementation not built yet")
def test_cli_log_path_resolves_relative_to_script_not_cwd(tmp_path):
    log_lines = [
        _tb("2026-08-10 09:00:00", "Quick", 500, {"Read": 1}),
        _ts("2026-08-10 09:00:05", "Quick", 0, 0),
    ]
    layout = tmp_path / "run"
    layout.mkdir()
    script = _build_isolated_layout(layout, log_lines)

    cwd_one = tmp_path / "cwd_one"
    cwd_two = tmp_path / "cwd_two" / "nested"
    cwd_one.mkdir()
    cwd_two.mkdir(parents=True)

    result_one = _run_cli(script, ["--json"], cwd=cwd_one)
    result_two = _run_cli(script, ["--json"], cwd=cwd_two)

    assert result_one.returncode == 0, result_one.stderr
    assert result_two.returncode == 0, result_two.stderr
    assert result_one.stdout == result_two.stdout


# ---------------------------------------------------------------------------
# default_log_path resolution
# ---------------------------------------------------------------------------

def test_default_log_path_points_at_hooks_governance_log():
    path = ccr.default_log_path()
    assert path.name == "governance-log.jsonl"
    assert path.parent.name == "hooks"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
