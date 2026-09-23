"""
ceremony_cost_report.py - Criterion 2 measurement instrument (ceremony cost).

Spec: Projects/Agent-Governance-Research/work/2026-08-26-criterion-2-metric-definition.md
      (committed BEFORE this instrument, so the metric could not be shaped to
      flatter the data)

Ceremony cost is forced overhead on turns whose recorded classification is
Quick, the class the harness itself says needs no process skill, no agents
and no QA. Three measures are reported, kept SEPARATE and never folded into
one index:

  dispatches  turn_summary.agent_count + turn_summary.skill_count
  tool_calls  sum(token_breakdown.tool_calls.values())
  tokens      token_breakdown.turn_total_tokens

token_breakdown and turn_summary are two independent event populations in the
log; they carry the turn classification under different field names
(task_type vs type) and are never joined by session/ts, since the log gives
no reliable turn identifier that spans both. Every measure and every segment
mix below is therefore computed, and reported, against the one event
population that actually carries it.

Usage:
    python ceremony_cost_report.py             # human-readable table
    python ceremony_cost_report.py --json       # machine-readable, to stdout
    python ceremony_cost_report.py --since 2026-08-20

The log path is resolved relative to THIS FILE's own location
(.claude/scripts/ -> ../hooks/governance-log.jsonl), never the caller's cwd,
so the report is the same regardless of where it is invoked from.

Exit codes: 0 = report printed. 1 = a filter (or the source data itself) left
zero usable records; see "Why fail loudly" below. 2 = bad CLI arguments
(argparse's own convention).

Stdlib only.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

HEADLINE_SEGMENT = "Quick"
_EVENT_TOKEN_BREAKDOWN = "token_breakdown"
_EVENT_TURN_SUMMARY = "turn_summary"
_TEST_ENVIRONMENT = "test"
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


class EmptyPopulationError(Exception):
    """Raised when a filter, or the source data itself, leaves zero usable
    records for the report to summarize.

    Why fail loudly: a broken selector (a schema that drifted, a filter that
    matched nothing, a population that silently went missing) still produces
    a runnable script if it is allowed to print zero, a dash, or an empty
    table. That output reads as "measured: no ceremony" when what actually
    happened is "measured: nothing". This codebase has shipped that exact
    vacuous-pass class more than once, so every place the population can go
    to zero is checked explicitly and raises here instead of falling through
    to a clean-looking report. The message always names which filter (or
    which of the two event populations) is responsible, so the fix is
    findable from the error alone.
    """


@dataclass
class ParseStats:
    total_lines: int = 0
    malformed_json: int = 0
    schema_incomplete: int = 0
    other_event: int = 0
    usable_before_since: dict = field(
        default_factory=lambda: {_EVENT_TOKEN_BREAKDOWN: 0, _EVENT_TURN_SUMMARY: 0})
    since_excluded: dict = field(
        default_factory=lambda: {_EVENT_TOKEN_BREAKDOWN: 0, _EVENT_TURN_SUMMARY: 0})
    usable_after_since: dict = field(
        default_factory=lambda: {_EVENT_TOKEN_BREAKDOWN: 0, _EVENT_TURN_SUMMARY: 0})
    test_env_excluded: dict = field(
        default_factory=lambda: {_EVENT_TOKEN_BREAKDOWN: 0, _EVENT_TURN_SUMMARY: 0})
    usable: dict = field(
        default_factory=lambda: {_EVENT_TOKEN_BREAKDOWN: 0, _EVENT_TURN_SUMMARY: 0})


def default_log_path():
    """The real log, resolved from this file's own location, not the cwd."""
    return Path(__file__).resolve().parent.parent / "hooks" / "governance-log.jsonl"


def _is_number(value):
    # bool is a subclass of int in Python; a stray true/false must not be
    # accepted as a token or dispatch count.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, _TS_FORMAT)
    except ValueError:
        return None


def _validate_token_breakdown(record):
    """Return the fields this instrument needs, or None if the record is
    missing or mistyped one of them. Only fields this script actually reads
    are required; a record missing an unrelated field (session, skill_names,
    by_subagent, ...) is still usable here.
    """
    ts = _parse_ts(record.get("ts"))
    environment = record.get("environment")
    segment = record.get("task_type")
    tokens = record.get("turn_total_tokens")
    tool_calls = record.get("tool_calls")
    if ts is None:
        return None
    if not isinstance(environment, str) or not environment:
        return None
    if not isinstance(segment, str) or not segment:
        return None
    if not _is_number(tokens):
        return None
    if not isinstance(tool_calls, dict):
        return None
    tool_call_count = 0
    for v in tool_calls.values():
        if not _is_number(v):
            return None
        tool_call_count += v
    return {
        "ts": ts, "environment": environment, "segment": segment,
        "tokens": tokens, "tool_call_count": tool_call_count,
    }


def _validate_turn_summary(record):
    ts = _parse_ts(record.get("ts"))
    environment = record.get("environment")
    segment = record.get("type")
    agent_count = record.get("agent_count")
    skill_count = record.get("skill_count")
    if ts is None:
        return None
    if not isinstance(environment, str) or not environment:
        return None
    if not isinstance(segment, str) or not segment:
        return None
    if not _is_number(agent_count) or not _is_number(skill_count):
        return None
    return {
        "ts": ts, "environment": environment, "segment": segment,
        "dispatch_count": agent_count + skill_count,
    }


def _aggregate(log_path, since_date):
    """Single streaming pass over the log. Reads one line at a time (never
    the whole file into memory) and accumulates only the small per-segment
    numeric lists the report needs, which is what keeps this safe to run
    against a 39.8 MB file.
    """
    stats = ParseStats()
    tb_segments = defaultdict(list)  # segment -> [(tokens, tool_call_count), ...]
    ts_segments = defaultdict(list)  # segment -> [dispatch_count, ...]

    with open(log_path, "r", encoding="utf-8") as f:
        for raw_line in f:
            stats.total_lines += 1
            line = raw_line.strip()
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                stats.malformed_json += 1
                continue
            if not isinstance(record, dict):
                stats.malformed_json += 1
                continue

            event = record.get("event")
            if event == _EVENT_TOKEN_BREAKDOWN:
                parsed = _validate_token_breakdown(record)
                kind = _EVENT_TOKEN_BREAKDOWN
            elif event == _EVENT_TURN_SUMMARY:
                parsed = _validate_turn_summary(record)
                kind = _EVENT_TURN_SUMMARY
            else:
                stats.other_event += 1
                continue

            if parsed is None:
                stats.schema_incomplete += 1
                continue

            stats.usable_before_since[kind] += 1

            if since_date is not None and parsed["ts"].date() < since_date:
                stats.since_excluded[kind] += 1
                continue
            stats.usable_after_since[kind] += 1

            if parsed["environment"] == _TEST_ENVIRONMENT:
                stats.test_env_excluded[kind] += 1
                continue
            stats.usable[kind] += 1

            if kind == _EVENT_TOKEN_BREAKDOWN:
                tb_segments[parsed["segment"]].append(
                    (parsed["tokens"], parsed["tool_call_count"]))
            else:
                ts_segments[parsed["segment"]].append(parsed["dispatch_count"])

    return stats, tb_segments, ts_segments


def _check_population(stats, since_date):
    """Raise EmptyPopulationError, naming the exact filter responsible, at
    the first point in the pipeline where the population has gone to zero.
    Checked in the order the filters are actually applied, so the message
    names the earliest true cause rather than a downstream symptom.
    """
    if stats.total_lines == 0:
        raise EmptyPopulationError("log file has zero lines; nothing to measure")

    before_since = (stats.usable_before_since[_EVENT_TOKEN_BREAKDOWN]
                     + stats.usable_before_since[_EVENT_TURN_SUMMARY])
    if before_since == 0:
        raise EmptyPopulationError(
            "no usable token_breakdown or turn_summary records found in "
            "%d lines (malformed JSON: %d, schema-incomplete: %d, other "
            "events: %d); the log format may have changed" % (
                stats.total_lines, stats.malformed_json,
                stats.schema_incomplete, stats.other_event,
            )
        )

    after_since = (stats.usable_after_since[_EVENT_TOKEN_BREAKDOWN]
                    + stats.usable_after_since[_EVENT_TURN_SUMMARY])
    if after_since == 0:
        raise EmptyPopulationError(
            "the --since %s filter excluded all %d usable records; none "
            "remain on or after that date" % (since_date.isoformat(), before_since)
        )

    usable = stats.usable[_EVENT_TOKEN_BREAKDOWN] + stats.usable[_EVENT_TURN_SUMMARY]
    if usable == 0:
        raise EmptyPopulationError(
            "environment=test exclusion removed all %d remaining records; "
            "no non-test records left" % after_since
        )

    if stats.usable[_EVENT_TOKEN_BREAKDOWN] == 0:
        raise EmptyPopulationError(
            "no usable token_breakdown records after filters; the tool_calls "
            "and tokens measures cannot be computed"
        )
    if stats.usable[_EVENT_TURN_SUMMARY] == 0:
        raise EmptyPopulationError(
            "no usable turn_summary records after filters; the dispatches "
            "measure cannot be computed"
        )


def safe_median(values):
    """statistics.median() raises on an empty list; a segment that simply has
    no records this window is a legitimate data fact (e.g. no Quick turns
    logged before a --since date), not the broken-population case
    EmptyPopulationError guards against. Report it as null, not a crash.
    """
    if not values:
        return None
    return statistics.median(values)


def _build_mix(segments, total):
    mix = {}
    for name in sorted(segments.keys()):
        count = len(segments[name])
        mix[name] = {"count": count, "proportion": count / total}
    return mix


def _build_measure(segments, extractor, source_event, source_fields):
    """One measure's segment table: a headline row for Quick (present or not)
    plus a control list, alphabetically sorted so output order never depends
    on dict insertion order (which itself would depend on file read order).
    """
    control_names = sorted(n for n in segments if n != HEADLINE_SEGMENT)

    def summarize(name):
        values = [extractor(v) for v in segments.get(name, [])]
        return {"count": len(values), "median": safe_median(values)}

    return {
        "source_event": source_event,
        "source_fields": source_fields,
        "headline_segment": HEADLINE_SEGMENT,
        "headline": summarize(HEADLINE_SEGMENT),
        "control": [dict(segment=n, **summarize(n)) for n in control_names],
    }


def compute_report(log_path, since_date=None):
    """Build the full report dict for the log at log_path.

    Raises EmptyPopulationError if any filter (or the data itself) leaves
    zero usable records overall, or zero for either event population.
    """
    stats, tb_segments, ts_segments = _aggregate(log_path, since_date)
    _check_population(stats, since_date)

    tb_total = stats.usable[_EVENT_TOKEN_BREAKDOWN]
    ts_total = stats.usable[_EVENT_TURN_SUMMARY]

    report = {
        "metadata": {
            "log_path": str(log_path),
            "since_filter": since_date.isoformat() if since_date else None,
            "total_lines_read": stats.total_lines,
            "malformed_lines_skipped": stats.malformed_json,
            "schema_incomplete_records_skipped": stats.schema_incomplete,
            "other_event_records_skipped": stats.other_event,
            "since_filter_excluded": dict(stats.since_excluded),
            "test_environment_excluded": dict(stats.test_env_excluded),
            "usable_records": dict(stats.usable),
        },
        "segment_mix": {
            _EVENT_TOKEN_BREAKDOWN: _build_mix(tb_segments, tb_total),
            _EVENT_TURN_SUMMARY: _build_mix(ts_segments, ts_total),
        },
        "measures": {
            "dispatches": _build_measure(
                ts_segments, lambda v: v,
                source_event=_EVENT_TURN_SUMMARY,
                source_fields="agent_count + skill_count"),
            "tool_calls": _build_measure(
                tb_segments, lambda pair: pair[1],
                source_event=_EVENT_TOKEN_BREAKDOWN,
                source_fields="sum(tool_calls.values())"),
            "tokens": _build_measure(
                tb_segments, lambda pair: pair[0],
                source_event=_EVENT_TOKEN_BREAKDOWN,
                source_fields="turn_total_tokens"),
        },
    }
    return report


def format_number(value):
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, float):
        return "%.1f" % value
    return str(value)


def render_json(report):
    # Every dict in `report` is built with a fixed key order and pre-sorted
    # segment names (see _build_mix / _build_measure), so this is stable
    # across runs without needing sort_keys=True to force it.
    return json.dumps(report, indent=2)


def render_table(report):
    lines = []
    meta = report["metadata"]
    lines.append("Ceremony Cost Report")
    lines.append("=====================")
    lines.append("Log: %s" % meta["log_path"])
    lines.append("Since filter: %s" % (meta["since_filter"] or "none"))
    lines.append("Total lines read: %d" % meta["total_lines_read"])
    lines.append("Malformed lines skipped: %d" % meta["malformed_lines_skipped"])
    lines.append("Schema-incomplete records skipped: %d"
                  % meta["schema_incomplete_records_skipped"])
    lines.append("Other-event records skipped: %d" % meta["other_event_records_skipped"])
    since_excl = meta["since_filter_excluded"]
    lines.append("Since-filter excluded: token_breakdown=%d, turn_summary=%d"
                  % (since_excl[_EVENT_TOKEN_BREAKDOWN], since_excl[_EVENT_TURN_SUMMARY]))
    test_excl = meta["test_environment_excluded"]
    lines.append("Test-environment excluded: token_breakdown=%d, turn_summary=%d"
                  % (test_excl[_EVENT_TOKEN_BREAKDOWN], test_excl[_EVENT_TURN_SUMMARY]))
    usable = meta["usable_records"]
    lines.append("Usable records: token_breakdown=%d, turn_summary=%d"
                  % (usable[_EVENT_TOKEN_BREAKDOWN], usable[_EVENT_TURN_SUMMARY]))
    lines.append("")

    for population in (_EVENT_TOKEN_BREAKDOWN, _EVENT_TURN_SUMMARY):
        mix = report["segment_mix"][population]
        lines.append("Segment mix (%s population):" % population)
        if not mix:
            lines.append("  (no segments)")
        for segment in sorted(mix.keys()):
            entry = mix[segment]
            pct = entry["proportion"] * 100
            lines.append("  %s: count=%d (%.1f%%)" % (segment, entry["count"], pct))
        lines.append("")

    measure_titles = {
        "dispatches": "Dispatches (agent_count + skill_count, from turn_summary)",
        "tool_calls": "Tool calls (sum of tool_calls values, from token_breakdown)",
        "tokens": "Tokens (turn_total_tokens, from token_breakdown)",
    }
    for measure_key in ("dispatches", "tool_calls", "tokens"):
        measure = report["measures"][measure_key]
        lines.append("%s, medians:" % measure_titles[measure_key])
        headline = measure["headline"]
        lines.append("  HEADLINE %s: n=%d median=%s"
                      % (measure["headline_segment"], headline["count"],
                         format_number(headline["median"])))
        for entry in measure["control"]:
            lines.append("  control  %s: n=%d median=%s"
                          % (entry["segment"], entry["count"],
                             format_number(entry["median"])))
        lines.append("")

    return "\n".join(lines).rstrip("\n")


def _valid_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(
            "invalid date '%s', expected YYYY-MM-DD" % value)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Ceremony cost report: forced overhead on Quick turns, "
                     "measured against the harness's own governance log.")
    parser.add_argument(
        "--since", type=_valid_date, default=None,
        help="only include records on or after this date (YYYY-MM-DD), matched against ts")
    parser.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON to stdout instead of a human-readable table")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    log_path = default_log_path()

    try:
        report = compute_report(log_path, since_date=args.since)
    except EmptyPopulationError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("ERROR: log file not found: %s" % log_path, file=sys.stderr)
        return 1

    if args.json:
        print(render_json(report))
    else:
        print(render_table(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
