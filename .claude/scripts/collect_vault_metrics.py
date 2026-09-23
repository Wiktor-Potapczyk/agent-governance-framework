"""
collect_vault_metrics.py — Vault Governance Observability Collector (R-1 engine)

Spec: MON-V2-1 v1 (Projects/Agent-Governance-Research/work/archive/2026-05-21-mon-v2-1-collection-spec.md)
Role: R-1 Nightly Observability Collector engine (vehicle-agnostic — runs identically under a
      cloud Routine scheduler, a local cron, or direct invocation).

Usage:
    python collect_vault_metrics.py [--date YYYY-MM-DD] [--log PATH] [--out PATH] [--dry-run]

    --date   Target UTC calendar day to collect metrics for.
             Default: yesterday (UTC). A nightly collector runs after midnight for the day just
             ended; do not use today's date for an in-progress day — the sample is incomplete.
    --log    Path to governance-log.jsonl.
             Default: .claude/hooks/governance-log.jsonl (relative to CWD, i.e. vault root).
    --out    Append-only JSONL output file.
             Default: Resources/KB/vault-metrics-timeseries.jsonl
    --dry-run  Print the record to stdout instead of appending to --out.

Exit codes: 0 = success (including noop / dry-run). Non-zero only on fatal errors
(log file unreadable, output directory uncreatable).

Idempotency: if a record for --date already exists in --out, the run is a noop (skip with
message). Duplicate-prevention is the correct behaviour per MON-V2-1 §3; the spec is silent on
replace-vs-skip so skip-with-message is chosen as the safer default for an append-only series.

Schema variants classified per MON-V2-1 §2:
    v2          schema == 2  AND  "event" present  (or schema==2 with no "type" — full v2 records)
    v2_legacy   schema == 2  AND  "event" absent   AND  "type" present
    v1c         no schema,        "event" present
    v1b         no schema,  no event,  "type" present  AND  "implies" present  (or just "type")
    v1a         no schema,  no event,  "type" present  AND  "mechanism" present
    (note: v1a/v1b share type; v1a detector fires first when mechanism key exists, even null)
    unknown     none of the above → counted, not extracted

Test-session exclusion regex (MON-V2-1 §2):
    ^(?:fixture-|pentest-|h5-|h3-|fake-|test$|test[-_]|unknown$)   (case-insensitive)
Records with environment == "test" are also excluded.

Rolling fields (§4.5) are re-computed from the raw log each run to prevent gap-day corruption.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SPEC_VERSION = "mon-v2-1-v1"
ROUTINE_VERSION = "r1-v1"

_TEST_SESSION_RE = re.compile(
    r"^(?:fixture-|pentest-|h5-|h3-|fake-|test$|test[-_]|unknown$)",
    re.IGNORECASE,
)

# Timestamp formats to try, in order
_TS_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _parse_ts(ts_str: str) -> datetime | None:
    """Parse a governance-log ts value to a UTC datetime. Returns None on failure."""
    if not ts_str:
        return None
    # Strip sub-second precision (e.g. ".123456") before trying formats; keep the rest
    # intact so that each format in _TS_FORMATS is genuinely attempted.
    ts_clean = ts_str.split(".")[0]
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(ts_clean, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _ts_date(ts_str: str) -> date | None:
    """Return just the UTC calendar date from a ts string, or None."""
    dt = _parse_ts(ts_str)
    return dt.date() if dt else None


# ---------------------------------------------------------------------------
# Schema variant classifier (MON-V2-1 §2 exact rule)
# ---------------------------------------------------------------------------


def classify_variant(record: dict) -> str:
    """
    Returns one of: "v2", "v2_legacy", "v1c", "v1a", "v1b", "unknown".

    Spec §2 rule (verbatim logic, adapted):
        if schema == 2:
            if "event" absent and "type" present  → v2_legacy
            else                                   → v2
        elif "event" in record:                    → v1c
        elif "type" in record and "mechanism" in record:  → v1a
        elif "type" in record:                     → v1b
        else:                                      → unknown
    """
    if record.get("schema") == 2:
        if "event" not in record and "type" in record:
            return "v2_legacy"
        return "v2"
    if "event" in record:
        return "v1c"
    if "type" in record and "mechanism" in record:
        return "v1a"
    if "type" in record:
        return "v1b"
    return "unknown"


# ---------------------------------------------------------------------------
# Test-session exclusion (MON-V2-1 §2)
# ---------------------------------------------------------------------------


def is_test_record(record: dict) -> bool:
    """Return True if record should be excluded as a test/fixture record."""
    if record.get("environment") == "test":
        return True
    session = record.get("session") or ""
    return bool(_TEST_SESSION_RE.match(str(session)))


# ---------------------------------------------------------------------------
# Session ID normalisation (MON-V2-1 §4.4)
# ---------------------------------------------------------------------------


def _normalise_session_id(session_id: str) -> str:
    """
    Reconcile 12-char legacy IDs with full UUIDs.
    A 12-char prefix is treated as equal to a UUID that startswith it.
    We normalise by returning the first 12 chars for both forms so they
    collapse in a set.
    """
    if not session_id:
        return session_id
    # Remove hyphens for length check
    raw = session_id.replace("-", "")
    # Full UUID has 32 hex chars; legacy has 12 chars (may contain hyphens in original but
    # the live data shows legacy as "692cfdb4-b18" which is 12 chars without normalisation)
    # Use: if original length (with hyphens) <= 12, it is a legacy ID; return as-is.
    # If it is a full UUID, return the first 12 chars of the hex body for comparison.
    if len(session_id) <= 12:
        return session_id
    # Full UUID: "692cfdb4-b180-4b4b-84b9-2ec163df7ab3" → first block "692cfdb4"
    # Legacy "692cfdb4-b18" — prefix of the UUID.
    # Normalise to first 12 chars of the original string to allow startswith collapse.
    return session_id[:12]


# ---------------------------------------------------------------------------
# Log reader: reads all records, returns (parsed_records, parse_error_count)
# ---------------------------------------------------------------------------


def read_log(log_path: Path) -> tuple[list[dict], int]:
    """
    Read governance-log.jsonl. Malformed lines are counted and skipped.
    Returns (list_of_records, parse_error_count).
    Each record dict has an injected "_raw_line" key for source_excerpts use.
    """
    records: list[dict] = []
    errors = 0
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
                rec["_raw_line"] = raw  # injected; stripped before output
                records.append(rec)
            except json.JSONDecodeError:
                errors += 1
    return records, errors


# ---------------------------------------------------------------------------
# Core metric computation (MON-V2-1 §4.1 – §4.4)
# ---------------------------------------------------------------------------


def _safe_mean(values: list[float | int]) -> float | None:
    """Return arithmetic mean, or None if list is empty."""
    if not values:
        return None
    return sum(values) / len(values)


def compute_metrics(
    day_records: list[dict],
    variant_map: dict,  # list-index → variant string (for records in day_records)
    target: date | None = None,
    all_records: list[dict] | None = None,
    all_variants: dict | None = None,  # list-index → variant string (for all_records)
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """
    Compute all §4.1–§4.4 metrics for records on the target day.

    variant_map keys are integer indices into day_records (0-based).
    all_variants keys are integer indices into all_records (0-based).

    Returns (metrics_dict, source_excerpts_dict).
    source_excerpts: for each non-zero load-bearing metric, up to 3 raw lines as evidence.
    """
    metrics: dict[str, Any] = {}
    excerpts: dict[str, list[str]] = {}

    def _add_excerpt(key: str, raw_line: str) -> None:
        bucket = excerpts.setdefault(key, [])
        if len(bucket) < 3:
            # Truncate very long lines for the evidence block
            bucket.append(raw_line[:400] if len(raw_line) > 400 else raw_line)

    # -----------------------------------------------------------------------
    # §4.1 — Classification metrics
    # -----------------------------------------------------------------------

    # Legacy classification records (v1a + v1b)
    legacy_class = [r for idx, r in enumerate(day_records) if variant_map.get(idx) in ("v1a", "v1b")]
    metrics["classification_count"] = len(legacy_class)
    for r in legacy_class[:3]:
        _add_excerpt("classification_count", r["_raw_line"])

    # v2-legacy classification records (schema:2 + type but no event)
    v2leg_class = [r for idx, r in enumerate(day_records) if variant_map.get(idx) == "v2_legacy"]
    metrics["classification_count_v2_legacy"] = len(v2leg_class)
    for r in v2leg_class[:3]:
        _add_excerpt("classification_count_v2_legacy", r["_raw_line"])

    # classification_mix: type counts across v1a + v1b + v2_legacy
    mix_records = legacy_class + v2leg_class
    mix: dict[str, int] = defaultdict(int)
    for r in mix_records:
        t = r.get("type")
        if t:
            mix[str(t)] += 1
    metrics["classification_mix"] = dict(mix)

    # quick_ratio
    total_class = metrics["classification_count"] + metrics["classification_count_v2_legacy"]
    if total_class > 0:
        quick_n = mix.get("Quick", 0)
        metrics["quick_ratio"] = round(quick_n / total_class, 6)
    else:
        metrics["quick_ratio"] = None

    # v2 explicit classification events
    v2_class_emitted = [
        r for idx, r in enumerate(day_records)
        if variant_map.get(idx) == "v2" and r.get("event") == "classification_emitted"
    ]
    metrics["classification_emitted_count"] = len(v2_class_emitted)
    for r in v2_class_emitted[:3]:
        _add_excerpt("classification_emitted_count", r["_raw_line"])

    metrics["classification_complete_count"] = sum(
        1 for r in v2_class_emitted if r.get("complete") is True
    )

    # classifier_block_count: classifier_field_missing events with decision=="block"
    cfm_blocks = [
        r for idx, r in enumerate(day_records)
        if variant_map.get(idx) == "v2"
        and r.get("event") == "classifier_field_missing"
        and r.get("decision") == "block"
    ]
    metrics["classifier_block_count"] = len(cfm_blocks)
    for r in cfm_blocks[:3]:
        _add_excerpt("classifier_block_count", r["_raw_line"])

    # -----------------------------------------------------------------------
    # §4.2 — Dispatch / governance metrics
    # -----------------------------------------------------------------------

    dispatched = [
        r for idx, r in enumerate(day_records)
        if variant_map.get(idx) == "v2" and r.get("event") == "agent_dispatched"
    ]
    metrics["agent_dispatch_count"] = len(dispatched)
    for r in dispatched[:2]:
        _add_excerpt("agent_dispatch_count", r["_raw_line"])

    outcome_counts: dict[str, int] = defaultdict(int)
    for r in dispatched:
        oc = r.get("outcome")
        if oc:
            outcome_counts[str(oc)] += 1
    metrics["agent_dispatch_outcomes"] = dict(outcome_counts)

    agent_type_counts: dict[str, int] = defaultdict(int)
    for r in dispatched:
        at_ = r.get("agent_type")
        if at_:
            agent_type_counts[str(at_)] += 1
    metrics["agent_type_counts"] = dict(agent_type_counts)
    if agent_type_counts:
        _add_excerpt("agent_type_counts", dispatched[0]["_raw_line"])

    metrics["agent_warn_count"] = outcome_counts.get("warn", 0)

    # hook_block_count: all event=="block" records (v1c + v2)
    all_blocks = [
        r for idx, r in enumerate(day_records)
        if r.get("event") == "block"
        and variant_map.get(idx) in ("v1c", "v2")
    ]
    metrics["hook_block_count"] = len(all_blocks)
    for r in all_blocks[:3]:
        _add_excerpt("hook_block_count", r["_raw_line"])

    blocks_by_hook: dict[str, int] = defaultdict(int)
    for r in all_blocks:
        h = r.get("hook")
        if h:
            blocks_by_hook[str(h)] += 1
    metrics["blocks_by_hook"] = dict(blocks_by_hook)

    # dark_zone (event name in log is "dark-zone")
    dark_zone_records = [
        r for idx, r in enumerate(day_records)
        if r.get("event") == "dark-zone"
        and variant_map.get(idx) in ("v1c", "v2")
    ]
    metrics["dark_zone_count"] = len(dark_zone_records)
    for r in dark_zone_records[:2]:
        _add_excerpt("dark_zone_count", r["_raw_line"])

    metrics["dark_zone_high_med_count"] = sum(
        1 for r in dark_zone_records
        if r.get("severity") in ("high", "medium")
    )

    dz_ratios = [r["ratio"] for r in dark_zone_records if isinstance(r.get("ratio"), (int, float))]
    metrics["dark_zone_mean_ratio"] = round(_safe_mean(dz_ratios), 6) if dz_ratios else None

    # verifier_gate_block_count / verifier_gate_pass_count
    # Requires schema==2 AND hook=="verifier-gate" explicitly (§4.2)
    vg_records = [
        r for r in day_records
        if r.get("schema") == 2 and r.get("hook") == "verifier-gate"
    ]
    metrics["verifier_gate_block_count"] = sum(1 for r in vg_records if r.get("event") == "block")
    metrics["verifier_gate_pass_count"] = sum(1 for r in vg_records if r.get("event") == "pass")
    for r in vg_records[:3]:
        _add_excerpt("verifier_gate_block_count", r["_raw_line"])

    # -----------------------------------------------------------------------
    # §4.3 — QA / process metrics
    # -----------------------------------------------------------------------

    qa_fail_records = [
        r for idx, r in enumerate(day_records)
        if variant_map.get(idx) == "v2" and r.get("event") == "qa_fail_reported"
    ]
    metrics["qa_fail_event_count"] = len(qa_fail_records)
    for r in qa_fail_records[:3]:
        _add_excerpt("qa_fail_event_count", r["_raw_line"])
    metrics["qa_fail_total"] = sum(
        int(r.get("fail_count", 0)) for r in qa_fail_records
        if isinstance(r.get("fail_count"), (int, float))
    )

    psc_blocks = [
        r for idx, r in enumerate(day_records)
        if r.get("event") == "block"
        and r.get("hook") == "process-step-check"
        and variant_map.get(idx) in ("v1c", "v2")
    ]
    metrics["process_step_block_count"] = len(psc_blocks)
    for r in psc_blocks[:2]:
        _add_excerpt("process_step_block_count", r["_raw_line"])

    # -----------------------------------------------------------------------
    # §4.4 — Session metrics
    # -----------------------------------------------------------------------

    # session_count: distinct session values on target day, with 12-char/UUID reconciliation
    raw_sessions: set[str] = set()
    for r in day_records:
        s = r.get("session")
        if s:
            raw_sessions.add(str(s))
    # Build collapsed set: for each session ID, normalise to 12-char prefix
    norm_sessions: set[str] = {_normalise_session_id(s) for s in raw_sessions}
    metrics["session_count"] = len(norm_sessions)

    # session_start_count
    ss_records = [
        r for idx, r in enumerate(day_records)
        if variant_map.get(idx) == "v2" and r.get("event") == "session_start"
    ]
    metrics["session_start_count"] = len(ss_records)

    # session_end_count: distinct sessions whose MAX ts falls on target day
    # Collect all session_end records (not just today — session may have started yesterday)
    # Per spec: bucket by the date of MAX ts per session. We use only day_records here since
    # we only have day_records in this call; the full-file pass for rolling fields is separate.
    # Within target-day records, all session_end records contribute their session's end.
    se_records = [
        r for idx, r in enumerate(day_records)
        if variant_map.get(idx) == "v2" and r.get("event") == "session_end"
    ]
    # Per the spec: count of distinct sessions whose effective end falls on target day.
    # Since we only see target-day records, every session_end here by definition ends on target day.
    se_sessions: set[str] = set()
    for r in se_records:
        s = r.get("session")
        if s:
            se_sessions.add(_normalise_session_id(str(s)))
    metrics["session_end_count"] = len(se_sessions)

    # dashboard_alert_count: bucketed by aggregate_date per spec §4.4.
    # A dashboard_alert record is counted toward the day whose aggregate_date matches;
    # if aggregate_date is absent, fall back to ts date.
    # Scanning the full record set (not just ts-filtered day_records) is required because
    # aggregate_date and ts may differ.
    target_str = target.isoformat() if target is not None else None
    scan_records = all_records if all_records is not None else day_records
    scan_variants = all_variants if all_variants is not None else variant_map
    da_records: list[dict] = []
    if target_str is not None:
        for idx, r in enumerate(scan_records):
            v = scan_variants.get(idx, "unknown")
            if v != "v2" or r.get("event") != "dashboard_alert":
                continue
            agg_date = r.get("aggregate_date")
            if agg_date is not None:
                # Count this record toward its aggregate_date day
                if str(agg_date) == target_str:
                    da_records.append(r)
            else:
                # Fall back to ts date when aggregate_date is absent
                if _ts_date(r.get("ts", "")) == target:
                    da_records.append(r)
    else:
        # No target available (should not happen in normal flow); fall back to ts scan
        for idx, r in enumerate(day_records):
            if variant_map.get(idx, "unknown") == "v2" and r.get("event") == "dashboard_alert":
                da_records.append(r)
    metrics["dashboard_alert_count"] = len(da_records)
    all_alerts: list[str] = []
    for r in da_records:
        alerts = r.get("alerts") or []
        all_alerts.extend(str(a) for a in alerts)
        _add_excerpt("dashboard_alert_count", r["_raw_line"])
    metrics["dashboard_alerts"] = all_alerts

    return metrics, excerpts


def compute_rolling(
    all_records: list[dict],
    all_variants: dict,  # list-index → variant string
    target: date,
    window_days: int,
) -> dict[str, int | float | None]:
    """
    Compute rolling fields for the window ending on target (inclusive).
    Re-derived from raw log each run (spec §4.5, §3).
    """
    start = target - timedelta(days=window_days - 1)

    def in_window(r: dict) -> bool:
        d = _ts_date(r.get("ts", ""))
        return d is not None and start <= d <= target

    # Build per-day counts for the window
    day_class_counts: dict[date, int] = defaultdict(int)
    day_block_counts: dict[date, int] = defaultdict(int)
    total_class_30 = 0
    quick_class_30 = 0

    thirty_start = target - timedelta(days=29)

    for idx, r in enumerate(all_records):
        if is_test_record(r):
            continue
        v = all_variants.get(idx, "unknown")
        d = _ts_date(r.get("ts", ""))
        if d is None:
            continue

        # Rolling 7-day
        if in_window(r):
            # classification_count_7d: v1a + v1b legacy classification records
            if v in ("v1a", "v1b"):
                day_class_counts[d] += 1
            # hook_block_count_7d: event=="block" in v1c + v2
            if r.get("event") == "block" and v in ("v1c", "v2"):
                day_block_counts[d] += 1

        # Rolling 30-day quick_ratio_30d
        if thirty_start <= d <= target:
            if v in ("v1a", "v1b", "v2_legacy"):
                total_class_30 += 1
                if r.get("type") == "Quick":
                    quick_class_30 += 1

    rolling: dict[str, int | float | None] = {
        "classification_count_7d": sum(day_class_counts[d] for d in day_class_counts),
        "hook_block_count_7d": sum(day_block_counts[d] for d in day_block_counts),
        "quick_ratio_30d": (
            round(quick_class_30 / total_class_30, 6)
            if total_class_30 >= 10 else None
        ),
    }
    return rolling


# ---------------------------------------------------------------------------
# Idempotency check
# ---------------------------------------------------------------------------


def date_already_in_out(out_path: Path, target: date) -> bool:
    """Return True if the output file already has an entry for target date."""
    if not out_path.exists():
        return False
    target_str = target.isoformat()
    try:
        with out_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("date") == target_str:
                        return True
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Output record builder
# ---------------------------------------------------------------------------


def build_output_record(
    target: date,
    records_scanned: int,
    test_excluded: int,
    unknown_count: int,
    parse_error_count: int,
    metrics: dict[str, Any],
    rolling: dict[str, Any],
    excerpts: dict[str, list[str]],
) -> dict[str, Any]:
    """Assemble the full output record per MON-V2-1 §5."""
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged_metrics = {**metrics, **rolling}

    # Ensure all spec-defined metric keys are present (null if not computed)
    defaults: dict[str, Any] = {
        "classification_count": 0,
        "classification_count_v2_legacy": 0,
        "classification_mix": {},
        "quick_ratio": None,
        "classification_emitted_count": 0,
        "classification_complete_count": 0,
        "classifier_block_count": 0,
        "agent_dispatch_count": 0,
        "agent_dispatch_outcomes": {},
        "agent_type_counts": {},
        "agent_warn_count": 0,
        "hook_block_count": 0,
        "blocks_by_hook": {},
        "dark_zone_count": 0,
        "dark_zone_high_med_count": 0,
        "dark_zone_mean_ratio": None,
        "verifier_gate_block_count": 0,
        "verifier_gate_pass_count": 0,
        "qa_fail_event_count": 0,
        "qa_fail_total": 0,
        "process_step_block_count": 0,
        "session_count": 0,
        "session_start_count": 0,
        "session_end_count": 0,
        "dashboard_alert_count": 0,
        "dashboard_alerts": [],
        "classification_count_7d": 0,
        "hook_block_count_7d": 0,
        "quick_ratio_30d": None,
    }
    for k, v in defaults.items():
        if k not in merged_metrics:
            merged_metrics[k] = v

    return {
        "date": target.isoformat(),
        "collected_at": collected_at,
        "spec_version": SPEC_VERSION,
        "routine_version": ROUTINE_VERSION,
        "governance_log_records_scanned": records_scanned,
        "test_records_excluded": test_excluded,
        "unknown_variant_count": unknown_count,
        "parse_error_count": parse_error_count,
        "metrics": merged_metrics,
        "source_excerpts": excerpts,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MON-V2-1 vault governance observability collector (R-1 engine).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Target UTC date YYYY-MM-DD. Default: yesterday UTC.",
    )
    parser.add_argument(
        "--log",
        default=".claude/hooks/governance-log.jsonl",
        help="Path to governance-log.jsonl. Default: .claude/hooks/governance-log.jsonl",
    )
    parser.add_argument(
        "--out",
        default="Resources/KB/vault-metrics-timeseries.jsonl",
        help="Append-only output JSONL. Default: Resources/KB/vault-metrics-timeseries.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the output record to stdout instead of writing.",
    )
    args = parser.parse_args(argv)

    # --- Resolve target date ---
    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: invalid --date value '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            return 2
    else:
        target = datetime.now(timezone.utc).date() - timedelta(days=1)

    # --- Resolve paths ---
    log_path = Path(args.log)
    out_path = Path(args.out)

    if not log_path.exists():
        print(f"ERROR: governance log not found at '{log_path}'.", file=sys.stderr)
        return 3

    # --- Idempotency check ---
    if not args.dry_run and date_already_in_out(out_path, target):
        print(
            f"[NOOP] Record for {target} already exists in '{out_path}'. "
            "Skipping to preserve idempotency."
        )
        return 0

    # --- Read log ---
    try:
        all_records, parse_errors = read_log(log_path)
    except OSError as exc:
        print(f"ERROR: cannot read log file '{log_path}': {exc}", file=sys.stderr)
        return 3

    # --- Classify all records ---
    # Build variant map keyed by list index for stable, collision-free lookup.
    all_variants: dict[int, str] = {idx: classify_variant(r) for idx, r in enumerate(all_records)}

    # --- Partition: target day, test-excluded, other days ---
    records_scanned = len(all_records)
    test_excluded_total = 0
    unknown_count = 0
    day_records: list[dict] = []
    day_variant_map: dict[int, str] = {}

    for global_idx, r in enumerate(all_records):
        d = _ts_date(r.get("ts", ""))
        v = all_variants[global_idx]
        if d != target:
            continue
        # On target day: apply test exclusion
        if is_test_record(r):
            test_excluded_total += 1
            continue
        if v == "unknown":
            unknown_count += 1
            continue
        # day_records index is local (0-based within the day slice)
        local_idx = len(day_records)
        day_records.append(r)
        day_variant_map[local_idx] = v

    # --- Compute metrics ---
    # Pass the full record set and full variant map so dashboard_alert_count can be
    # bucketed by aggregate_date across the entire log (spec §4.4).
    metrics, excerpts = compute_metrics(
        day_records,
        day_variant_map,
        target=target,
        all_records=all_records,
        all_variants=all_variants,
    )

    # --- Compute rolling fields ---
    rolling = compute_rolling(all_records, all_variants, target, window_days=7)
    # 30-day quick_ratio is embedded in rolling; compute separately for 30d
    rolling_30 = compute_rolling(all_records, all_variants, target, window_days=30)
    rolling["quick_ratio_30d"] = rolling_30["quick_ratio_30d"]

    # --- Build output record ---
    out_record = build_output_record(
        target=target,
        records_scanned=records_scanned,
        test_excluded=test_excluded_total,
        unknown_count=unknown_count,
        parse_error_count=parse_errors,
        metrics=metrics,
        rolling=rolling,
        excerpts=excerpts,
    )

    # Strip _raw_line injection before output (was only for internal excerpt use)
    # (already stripped: records_in_out_record don't include record dicts)

    out_json = json.dumps(out_record, ensure_ascii=False)

    if args.dry_run:
        print(out_json)
        return 0

    # --- Ensure output directory exists ---
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create output directory '{out_path.parent}': {exc}", file=sys.stderr)
        return 4

    # --- Append (wrapped to surface disk-full / permission failures with a clean exit code) ---
    try:
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(out_json + "\n")
    except OSError as exc:
        print(f"ERROR: cannot write to output file '{out_path}': {exc}", file=sys.stderr)
        return 3

    print(f"[OK] Appended metrics record for {target} to '{out_path}'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
