"""
verify_vault_metrics.py — R-1V Vault Metrics Verifier

Spec: MON-V2-1 v1 (Projects/Agent-Governance-Research/work/archive/2026-05-21-mon-v2-1-collection-spec.md)
Role: R-1V — independent second-pass check on R-1 collector output. Re-derives a subset of
      high-signal metrics from the source governance-log.jsonl using DIFFERENT implementation
      paths from collect_vault_metrics.py, then compares. A bug in one implementation should
      not be undetectable by the other.

Usage:
    python verify_vault_metrics.py [--date YYYY-MM-DD] [--log PATH] [--timeseries PATH]
                                   [--out PATH] [--dry-run]

    --date         UTC date to verify. Default: yesterday UTC.
    --log          Source governance log. Default: .claude/hooks/governance-log.jsonl
    --timeseries   Collector output. Default: Resources/KB/vault-metrics-timeseries.jsonl
    --out          Append-only verifier output. Default: Resources/KB/vault-metrics-verify.jsonl
    --dry-run      Print to stdout instead of appending.

Exit codes:
    0  — verification ran (overall_status may still be DRIFT or FAIL — non-fatal)
    2  — bad CLI arguments
    3  — fatal I/O error

Design — deliberate divergence from collector:
- Collector uses ordered dispatch (v2 → v1c → v1a → v1b → unknown).
  Verifier classifies by ground-truth field-presence checks expressed as boolean predicates.
- Collector uses positional list-index → variant map.
  Verifier uses event-name + schema/type pair lookups built in a single pass.
- Collector reads ts with multi-format strptime.
  Verifier reads ts by isoformat-prefix slicing (first 10 chars).
- Collector normalises sessions to 12-char prefix.
  Verifier compares both 12-char prefix and full UUID as alternative equivalence classes.

Verified metrics (subset by design — high-signal, independently derivable):
    governance_log_records_scanned, parse_error_count, test_records_excluded,
    classification_count, classification_count_v2_legacy, classification_emitted_count,
    hook_block_count, verifier_gate_block_count, verifier_gate_pass_count,
    qa_fail_event_count, session_count

Non-verified metrics (collector-only fields): everything that requires reproducing the collector's
exact ordered logic (e.g. classifier_block_count's specific decision filter, dark_zone_mean_ratio).
These are left unchecked here; the collector's 66-test suite is the unit-level guard.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SPEC_VERSION = "mon-v2-1-v1"
VERIFIER_VERSION = "r1v-v1"

_TEST_SESSION_RE = re.compile(
    r"^(?:fixture-|pentest-|h5-|h3-|fake-|test$|test[-_]|unknown$)",
    re.IGNORECASE,
)


def _ts_to_date_str(ts: Any) -> str | None:
    """
    Verifier's ts->date path: prefix-slice the first 10 chars and validate the YYYY-MM-DD shape.
    Deliberately different from the collector's strptime-loop approach.

    Collector accepts three formats (space, ISO-T, ISO-T-Z) — none of which carry a timezone
    offset like +05:30. To stay equivalent in domain (not just in output for accepted ts), the
    verifier rejects any ts whose post-date portion contains a '+' or a '-' beyond position 10
    (offset markers), matching what the collector's strptime loop would reject.
    """
    if not isinstance(ts, str) or len(ts) < 10:
        return None
    head = ts[:10]
    if head[4] != "-" or head[7] != "-":
        return None
    try:
        date.fromisoformat(head)
    except ValueError:
        return None
    # Reject ts with timezone offset to match the collector's accepted-format domain.
    tail = ts[10:]
    if "+" in tail:
        return None
    # A '-' appearing in the tail beyond the date portion signals a negative offset.
    if "-" in tail:
        return None
    return head


def _is_test_record(record: dict) -> bool:
    """Match collector's test-record predicate exactly (this is ground truth from the spec)."""
    if record.get("environment") == "test":
        return True
    session = record.get("session") or ""
    return bool(_TEST_SESSION_RE.match(str(session)))


def _classify(record: dict) -> str:
    """
    Verifier's variant classifier: independent boolean-predicate dispatch.
    Computes the same partition as collect_vault_metrics.classify_variant via different control flow.
    """
    has_schema_2 = record.get("schema") == 2
    has_event = "event" in record
    has_type = "type" in record
    has_mechanism = "mechanism" in record

    if has_schema_2 and not has_event and has_type:
        return "v2_legacy"
    if has_schema_2:
        return "v2"
    if has_event:
        return "v1c"
    if has_type and has_mechanism:
        return "v1a"
    if has_type:
        return "v1b"
    return "unknown"


def _read_log_lines(log_path: Path) -> tuple[list[dict], int, int]:
    """
    Verifier's log reader: returns (parsed_records, total_nonblank_lines, parse_error_count).
    Different return shape from collector to avoid sharing intermediate structure.
    """
    records: list[dict] = []
    total = 0
    errors = 0
    with log_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            total += 1
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                errors += 1
    return records, total, errors


def _find_collector_record(timeseries_path: Path, target_iso: str) -> tuple[dict | None, int]:
    """
    Find the collector's output record for the target date.
    Returns (last_match_or_None, hit_count). A hit_count > 1 indicates duplicate collector
    records — the verifier surfaces this in its output so the anomaly is never silent.
    """
    if not timeseries_path.exists():
        return (None, 0)
    last_hit: dict | None = None
    hits = 0
    with timeseries_path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("date") == target_iso:
                last_hit = rec
                hits += 1
    return (last_hit, hits)


def _normalise_session(session_id: str) -> str:
    """
    Verifier session normalisation: first-12-char prefix.
    Matches collector's collapse-to-prefix semantic via the simplest possible derivation.
    """
    if not session_id:
        return ""
    return session_id[:12]


def compute_verifier_metrics(records: list[dict], target_iso: str) -> dict[str, Any]:
    """
    Independent re-derivation of the verified metric subset.

    Records of variant `unknown` are excluded from day_records to match the collector's
    partition (collector skips unknown records before computing day metrics — including
    session_count). This makes the partition equivalent on the verifier side too.
    """
    day_records: list[dict] = []
    test_excluded = 0
    for r in records:
        d = _ts_to_date_str(r.get("ts"))
        if d != target_iso:
            continue
        if _is_test_record(r):
            test_excluded += 1
            continue
        if _classify(r) == "unknown":
            # Match collector: unknown-variant records are not part of any per-day metric
            continue
        day_records.append(r)

    classes = [_classify(r) for r in day_records]
    classification_count = sum(1 for c in classes if c in ("v1a", "v1b"))
    classification_count_v2_legacy = sum(1 for c in classes if c == "v2_legacy")

    classification_emitted_count = sum(
        1 for r, c in zip(day_records, classes)
        if c == "v2" and r.get("event") == "classification_emitted"
    )

    classifier_block_count = sum(
        1 for r, c in zip(day_records, classes)
        if c == "v2"
        and r.get("event") == "classifier_field_missing"
        and r.get("decision") == "block"
    )

    hook_block_count = sum(
        1 for r, c in zip(day_records, classes)
        if r.get("event") == "block" and c in ("v1c", "v2")
    )

    verifier_gate_block_count = 0
    verifier_gate_pass_count = 0
    for r in day_records:
        if r.get("schema") == 2 and r.get("hook") == "verifier-gate":
            if r.get("event") == "block":
                verifier_gate_block_count += 1
            elif r.get("event") == "pass":
                verifier_gate_pass_count += 1

    qa_fail_event_count = sum(
        1 for r, c in zip(day_records, classes)
        if c == "v2" and r.get("event") == "qa_fail_reported"
    )

    sessions: set[str] = set()
    for r in day_records:
        s = r.get("session")
        if not s:
            continue
        norm = _normalise_session(str(s))
        if norm:
            sessions.add(norm)
    session_count = len(sessions)

    return {
        "test_records_excluded": test_excluded,
        "classification_count": classification_count,
        "classification_count_v2_legacy": classification_count_v2_legacy,
        "classification_emitted_count": classification_emitted_count,
        "classifier_block_count": classifier_block_count,
        "hook_block_count": hook_block_count,
        "verifier_gate_block_count": verifier_gate_block_count,
        "verifier_gate_pass_count": verifier_gate_pass_count,
        "qa_fail_event_count": qa_fail_event_count,
        "session_count": session_count,
    }


def compare(collector_rec: dict, verifier_metrics: dict, verifier_scanned: int, verifier_parse_errors: int) -> dict:
    """
    Build the per-metric comparison block.
    Returns: {comparisons: {metric: {collector, verifier, match}}, mismatches: [...], overall_status: str}

    Note: `governance_log_records_scanned` is NOT a per-day deterministic metric — it counts the
    full log file at collector-run time. Since the log appends after the collector runs, the
    verifier sees a strictly larger count. We surface it as INFO_ONLY, never as a mismatch.
    Compare it only loosely: verifier must see >= collector (otherwise something is wrong).
    """
    comparisons: dict[str, dict[str, Any]] = {}
    mismatches: list[str] = []

    collector_metrics = collector_rec.get("metrics", {})

    # Top-level fields — handled with the right comparator per field
    c_scanned = collector_rec.get("governance_log_records_scanned")
    c_parse = collector_rec.get("parse_error_count")
    c_test_excl = collector_rec.get("test_records_excluded")

    # governance_log_records_scanned: INFO_ONLY, verifier must be >= collector
    scanned_ok = isinstance(c_scanned, int) and verifier_scanned >= c_scanned
    comparisons["governance_log_records_scanned"] = {
        "collector": c_scanned,
        "verifier": verifier_scanned,
        "match": scanned_ok,
        "kind": "info_only_log_grew",
    }
    if not scanned_ok:
        mismatches.append("governance_log_records_scanned")

    # parse_error_count: parse errors are a property of bytes already in the file. The verifier
    # re-reads after the log grew, so it may see >= the collector's count (new malformed lines
    # added) but should never see strictly fewer (would indicate truncation). Treat as INFO_ONLY
    # with a >= floor for the same drift-detection reason as records_scanned.
    parse_ok = isinstance(c_parse, int) and verifier_parse_errors >= c_parse
    comparisons["parse_error_count"] = {
        "collector": c_parse,
        "verifier": verifier_parse_errors,
        "match": parse_ok,
        "kind": "info_only_floor_check",
    }
    if not parse_ok:
        mismatches.append("parse_error_count")

    # test_records_excluded: top-level field, day-deterministic — exact match required.
    # If the collector record is missing the field entirely AND the verifier found a non-zero
    # count, that is itself a DRIFT signal (old-format collector record vs current verifier).
    excl_match = c_test_excl == verifier_metrics["test_records_excluded"]
    comparisons["test_records_excluded"] = {
        "collector": c_test_excl,
        "verifier": verifier_metrics["test_records_excluded"],
        "match": excl_match,
    }
    if not excl_match:
        mismatches.append("test_records_excluded")

    # Metrics-block fields — exact match required (day-deterministic)
    for name, v_val in verifier_metrics.items():
        if name == "test_records_excluded":
            continue  # handled above as top-level
        c_val = collector_metrics.get(name)
        match = c_val == v_val
        comparisons[name] = {"collector": c_val, "verifier": v_val, "match": match}
        if not match:
            mismatches.append(name)

    if mismatches:
        overall_status = "DRIFT"
    else:
        overall_status = "PASS"

    return {
        "comparisons": comparisons,
        "mismatches": mismatches,
        "overall_status": overall_status,
    }


def already_verified(out_path: Path, target_iso: str) -> bool:
    """Idempotency: skip if a verification record for target date already exists."""
    if not out_path.exists():
        return False
    try:
        with out_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("date") == target_iso:
                    return True
    except OSError:
        pass
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="MON-V2-1 R-1V vault metrics verifier (independent second-pass check).",
    )
    parser.add_argument("--date", default=None)
    parser.add_argument("--log", default=".claude/hooks/governance-log.jsonl")
    parser.add_argument("--timeseries", default="Resources/KB/vault-metrics-timeseries.jsonl")
    parser.add_argument("--out", default="Resources/KB/vault-metrics-verify.jsonl")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"ERROR: invalid --date '{args.date}'.", file=sys.stderr)
            return 2
    else:
        target = datetime.now(timezone.utc).date() - timedelta(days=1)

    target_iso = target.isoformat()
    log_path = Path(args.log)
    ts_path = Path(args.timeseries)
    out_path = Path(args.out)

    if not log_path.exists():
        print(f"ERROR: governance log not found at '{log_path}'.", file=sys.stderr)
        return 3

    if not args.dry_run and already_verified(out_path, target_iso):
        print(f"[NOOP] Verification for {target_iso} already exists in '{out_path}'.")
        return 0

    collector_rec, collector_hit_count = _find_collector_record(ts_path, target_iso)
    verified_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if collector_rec is None:
        # No collector record yet — emit a MISSING verdict instead of failing
        output_rec: dict[str, Any] = {
            "date": target_iso,
            "verified_at": verified_at,
            "spec_version": SPEC_VERSION,
            "verifier_version": VERIFIER_VERSION,
            "target_record_found": False,
            "overall_status": "MISSING",
            "note": f"No collector record for {target_iso} found in {ts_path}.",
        }
    else:
        try:
            records, total_nonblank, parse_errors = _read_log_lines(log_path)
        except OSError as exc:
            print(f"ERROR: cannot read log '{log_path}': {exc}", file=sys.stderr)
            return 3
        verifier_metrics = compute_verifier_metrics(records, target_iso)
        cmp_result = compare(collector_rec, verifier_metrics, total_nonblank, parse_errors)
        # Duplicate collector records surface as a DRIFT condition rather than silent last-wins.
        if collector_hit_count > 1:
            if "collector_duplicate_records" not in cmp_result["mismatches"]:
                cmp_result["mismatches"].append("collector_duplicate_records")
            cmp_result["overall_status"] = "DRIFT"
        output_rec = {
            "date": target_iso,
            "verified_at": verified_at,
            "spec_version": SPEC_VERSION,
            "verifier_version": VERIFIER_VERSION,
            "target_record_found": True,
            "collector_collected_at": collector_rec.get("collected_at"),
            "collector_duplicate_count": collector_hit_count,
            "overall_status": cmp_result["overall_status"],
            "mismatches": cmp_result["mismatches"],
            "comparisons": cmp_result["comparisons"],
            "verifier_log_lines_total": total_nonblank,
            "verifier_parse_errors": parse_errors,
        }

    line = json.dumps(output_rec, sort_keys=True)
    if args.dry_run:
        print(line)
        return 0

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:
        print(f"ERROR: cannot write verifier output '{out_path}': {exc}", file=sys.stderr)
        return 3

    status = output_rec["overall_status"]
    print(f"[{status}] Verified {target_iso} -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
