#!/usr/bin/env python3
"""Governance-log failure miner: v1-minimal (REV-1..REV-6).

Pure-stdlib helper. Scans governance-log.jsonl for recurring failure patterns
keyed by (event_label, agent_type, hook, normalized_reason).
Returns flagged sig records sorted severity-high-first then count-desc.

Used by the process-governance-mine skill and callable standalone via __main__.
"""

import hashlib
import json
import os
import re
import sys
from datetime import date, timedelta

# ---------------------------------------------------------------------------
# CONFIG CONSTANTS  (tunable: change here, nowhere else)
# ---------------------------------------------------------------------------

# Recurrence gate defaults
DEFAULT_C = 10       # min occurrence count for normal-severity sigs
DEFAULT_D = 3        # min distinct-day count
HIGH_SEV_C = 3       # min occurrence count for high-severity sigs
WINDOW_DAYS = 30     # rolling window in calendar days

# Events that are unconditionally high-severity regardless of per-record severity field.
# fabrication_detected has no per-record severity field: always high.
ALWAYS_HIGH_SEVERITY_EVENTS = {"fabrication_detected"}

# dark-zone records carry their own `severity` field ("low"/"medium"/"high").
# A dark-zone sig is high-severity only when at least one admitted record for that
# sig_id carries severity=="high".  Low/medium dark-zone records are normal severity.
DARK_ZONE_EVENT = "dark-zone"

# ---------------------------------------------------------------------------
# FAILURE-EVENT ALLOWLIST  (REV-2)
# A line is admitted into mining iff it passes ANY of these conditions.
# Extend this set as new named failure events are added to the log schema.
# ---------------------------------------------------------------------------

# Named events admitted unconditionally.
# Extend here when new named failure events are added to the log schema.
# reviewer_scope_violation_blocked is the *_blocked twin of reviewer_scope_violation;
# both are listed explicitly rather than relying on a substring guard.
FAILURE_EVENTS_EXACT = {
    "reviewer_scope_violation",
    "reviewer_scope_violation_blocked",
    "deny",
    "dark-zone",
    "fabrication_detected",
    "classifier_field_missing",
    "block",          # generic block event
}

# Suffix guard: any event ending with "_blocked" is also admitted (covers future twin pairs).
# IMPORTANT: this is a suffix match (endswith), NOT a substring match, to avoid over-admission
# of events like "unblock" or "reblock".  Do not revert to a bare FAILURE_EVENT_CONTAINS check.

# Outcome value that triggers admission
FAILURE_OUTCOME = "no_classification"

# Reason value that triggers admission
FAILURE_REASON = "empty_must_dispatch_on_non_quick"

# ---------------------------------------------------------------------------
# NORMALIZATION  (light v1: applied to reason text for sig_key)
# ---------------------------------------------------------------------------

_RE_DIGITS = re.compile(r"\d+")
# Path normalization: collapse real filesystem paths to <PATH>.
# Requires an unambiguous path indicator to avoid collapsing bare fractions
# like "50/100" or "3/10".
#
# Three accepted forms:
#   [A-Za-z]:[/\\]  : Windows drive letter (C:\, D:/)
#   (?:\.\.?|~)[/\\]: explicit relative (./), parent-relative (../), or home-dir (~/)
#   (?<!\d)/[^\s'"]{3,}: POSIX absolute path (/home/foo): bare leading /
#                         but NOT preceded by a digit (excludes "50/100", "3/10")
#
# The negative lookbehind (?<!\d) is the key guard: a fraction like "50/100" has
# a digit immediately before the slash, so it does NOT match the third form.
_RE_PATH = re.compile(
    r"""(?:[A-Za-z]:[/\\]|(?:\.\.?|~)[/\\])[^\s'"]{2,}"""
    r"""|(?<!\d)/[^\s'"]{3,}"""
)
# Quoted paths
_RE_QUOTED_PATH = re.compile(r"'[^']{3,}'")
# SHA-256 prefix or bare hex runs >=8 chars
_RE_HASH = re.compile(r"(?:sha256:)?[0-9a-f]{8,}", re.IGNORECASE)

_NORM_MAX = 200


def _normalize_reason(text: str) -> str:
    """Collapse variable parts of a reason string into stable tokens."""
    if not text:
        return ""
    t = _RE_HASH.sub("<HASH>", text)
    t = _RE_PATH.sub("<PATH>", t)
    t = _RE_QUOTED_PATH.sub("'<PATH>'", t)
    t = _RE_DIGITS.sub("N", t)
    t = " ".join(t.lower().split())
    return t[:_NORM_MAX]


# ---------------------------------------------------------------------------
# SIG-KEY + SIG-ID  (REV-1: includes agent_type + hook)
# ---------------------------------------------------------------------------

def _sig_key(event_label: str, agent_type: str, hook: str, norm_reason: str):
    """Stable 4-tuple that uniquely identifies a failure class."""
    return (
        event_label or "",
        agent_type or "",
        hook or "",
        norm_reason or "",
    )


def _sig_id(key: tuple) -> str:
    """12-char hex prefix of sha256(repr(key))."""
    return hashlib.sha256(repr(key).encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# ADMISSION FILTER  (REV-2)
# ---------------------------------------------------------------------------

def _admitted(record: dict) -> bool:
    """Return True iff this log record should enter the miner."""
    event = record.get("event", "") or ""
    outcome = record.get("outcome", "") or ""
    reason = record.get("reason", "") or ""
    block_reason = record.get("block_reason", "") or ""

    if event in FAILURE_EVENTS_EXACT:
        return True
    if event.endswith("_blocked"):
        return True
    if outcome == FAILURE_OUTCOME:
        return True
    if reason == FAILURE_REASON:
        return True
    if block_reason.strip():
        return True
    return False


# ---------------------------------------------------------------------------
# FAILURE LABEL : most-specific label for the sig_key
# ---------------------------------------------------------------------------

def _failure_label(record: dict) -> str:
    """Return the most specific failure label for this record.

    The label reflects WHY the record was admitted, not just which event fired:
    - If the event is itself a named failure event (in FAILURE_EVENTS_EXACT or
      endswith "_blocked"), the event name IS the failure class: use it.
    - If the record was admitted via outcome=="no_classification" (i.e. the event
      is a noise event like "agent_dispatched"), the failure class is the outcome
      value: use "no_classification" so the sig reads correctly.
    - Fall through to reason, then "block_reason" marker, then "unknown".

    This ensures that noise-event records (agent_dispatched + outcome=no_classification)
    are keyed on "no_classification", not on the noise event name.
    """
    event = record.get("event", "") or ""
    outcome = record.get("outcome", "") or ""
    reason = record.get("reason", "") or ""
    block_reason = record.get("block_reason", "") or ""

    # Use event only when it is itself a named failure event
    if event and (event in FAILURE_EVENTS_EXACT or event.endswith("_blocked")):
        return event
    # Record admitted via outcome path: label is the outcome value
    if outcome:
        return outcome
    if reason:
        return reason
    if block_reason:
        return "block_reason"
    return "unknown"


# ---------------------------------------------------------------------------
# REASON TEXT : best reason text for normalization
# ---------------------------------------------------------------------------

def _reason_text(record: dict) -> str:
    # Prefer block_reason (most descriptive), then reason, then outcome
    for key in ("block_reason", "reason", "outcome"):
        v = record.get(key, "") or ""
        if v.strip():
            return v
    return ""


# ---------------------------------------------------------------------------
# RESOLVED-LEDGER READER
# ---------------------------------------------------------------------------

def _load_resolved(ledger_path: str) -> dict:
    """Return {sig_id: resolved_ts_date_str} from the ledger. Tolerates missing file."""
    result = {}
    if not ledger_path or not os.path.isfile(ledger_path):
        return result
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception:
                    continue
                sid = entry.get("sig_id", "")
                rts = entry.get("resolved_ts", "") or ""
                if sid:
                    # Keep the LATEST resolved_ts if a sig appears multiple times
                    if sid not in result or rts > result[sid]:
                        result[sid] = rts[:10]  # date portion only
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# BUCKET HYPOTHESIS  (§3 heuristic)
# ---------------------------------------------------------------------------

def _bucket(
    sig: dict,
    total_admitted_in_window: int,
    hook: str,
    event_label: str,
    hook_total_counts: dict,
) -> str:
    """
    (b) over-firing: if this sig's hook accounts for >50% of all admitted lines in window.
    (a) doctrine-gap: classifier/compliance outcome with no dominating hook.
    (c) genuine: default.
    """
    if hook and hook_total_counts.get(hook, 0) > 0.5 * total_admitted_in_window:
        return "b over-firing"
    if event_label in ("no_classification", "empty_must_dispatch_on_non_quick") and not hook:
        return "a doctrine-gap"
    if event_label in ("no_classification", "empty_must_dispatch_on_non_quick"):
        # Has a hook but is compliance-class: check if no single hook dominates
        if not hook or hook_total_counts.get(hook, 0) <= 0.5 * total_admitted_in_window:
            return "a doctrine-gap"
    return "c genuine"


# ---------------------------------------------------------------------------
# MAIN PUBLIC API
# ---------------------------------------------------------------------------

def mine(
    log_path: str,
    now_date,
    window_days: int = WINDOW_DAYS,
    resolved_ledger_path: str = None,
) -> list:
    """Mine governance-log.jsonl for recurring failure patterns.

    Parameters
    ----------
    log_path : str
        Path to governance-log.jsonl.
    now_date : datetime.date or "YYYY-MM-DD" str
        Reference date for the rolling window. MUST be passed in: mine()
        never reads the clock internally (determinism for tests).
    window_days : int
        Rolling window width in calendar days (default WINDOW_DAYS=30).
    resolved_ledger_path : str or None
        Path to miner-resolved.jsonl. None or missing file -> no suppression.

    Returns
    -------
    list of dict : flagged (or regression-surfaced) sig records,
                    sorted severity-high-first then count-desc.
    """
    if isinstance(now_date, str):
        now_date = date.fromisoformat(now_date)

    window_start = now_date - timedelta(days=window_days)
    resolved = _load_resolved(resolved_ledger_path)

    # ------------------------------------------------------------------
    # Single-pass ingestion
    # ------------------------------------------------------------------
    # Per-sig data collected during the pass
    sig_meta = {}       # sig_id -> dict with running aggregates
    total_admitted = 0  # total admitted lines within window
    hook_totals = {}    # hook -> count of admitted lines in window

    try:
        fh = open(log_path, "r", encoding="utf-8")
    except OSError:
        return []

    with fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except Exception:
                continue  # silently skip unparseable lines
            if not isinstance(record, dict):
                continue  # valid JSON but not an object (bare list/string/number): skip
            # Harden against malformed records: coerce non-string string-ish fields
            # (a log line could carry agent_type:int, hook:{nested}, reason:list, etc.).
            # Leave None as None so the "non-empty block_reason" admission check is unaffected.
            for _f in ("event", "agent_type", "hook", "outcome", "reason", "block_reason"):
                _v = record.get(_f)
                if _v is not None and not isinstance(_v, str):
                    record[_f] = str(_v)

            # Window filter: parse date from first 10 chars of ts.
            # Coerce to str: ts may be a non-string (int/null) in a malformed line.
            ts = record.get("ts", "") or ""
            if not isinstance(ts, str):
                ts = str(ts)
            if len(ts) < 10:
                continue
            try:
                rec_date = date.fromisoformat(ts[:10])
            except (ValueError, TypeError):
                continue
            if rec_date < window_start:
                continue

            if not _admitted(record):
                continue

            total_admitted += 1

            # Track per-hook totals for bucket hypothesis
            hook_val = record.get("hook", "") or ""
            if hook_val:
                hook_totals[hook_val] = hook_totals.get(hook_val, 0) + 1

            # Build sig key
            label = _failure_label(record)
            agent_type = record.get("agent_type", "") or ""
            norm_reason = _normalize_reason(_reason_text(record))
            key = _sig_key(label, agent_type, hook_val, norm_reason)
            sid = _sig_id(key)

            if sid not in sig_meta:
                # Initial severity:
                #   fabrication_detected (and any other ALWAYS_HIGH_SEVERITY_EVENTS) -> high.
                #   dark-zone -> determined per-record below (starts normal, upgraded if any
                #               admitted record carries severity=="high").
                #   everything else -> normal.
                initial_sev = "high" if label in ALWAYS_HIGH_SEVERITY_EVENTS else "normal"
                sig_meta[sid] = {
                    "sig_id": sid,
                    "key": key,
                    "event_label": label,
                    "agent_type": agent_type,
                    "hook": hook_val,
                    "normalized_signature": norm_reason or label,
                    "severity": initial_sev,
                    "count": 0,
                    "dates": set(),
                    "first_seen": ts[:10],
                    "last_seen": ts[:10],
                    "tool_names": {},
                    "raw_samples": [],
                }

            m = sig_meta[sid]
            m["count"] += 1
            m["dates"].add(ts[:10])
            if ts[:10] < m["first_seen"]:
                m["first_seen"] = ts[:10]
            if ts[:10] > m["last_seen"]:
                m["last_seen"] = ts[:10]
            tool_name = record.get("tool_name", "") or record.get("tool", "") or ""
            if tool_name:
                m["tool_names"][tool_name] = m["tool_names"].get(tool_name, 0) + 1
            if len(m["raw_samples"]) < 3:
                m["raw_samples"].append(raw_line)

            # D1: dark-zone severity is record-derived.
            # Upgrade the sig to high if this dark-zone record has severity=="high".
            # Take the maximum across all records: one high record makes the sig high.
            if label == DARK_ZONE_EVENT and m["severity"] != "high":
                rec_sev = (record.get("severity", "") or "").lower()
                if rec_sev == "high":
                    m["severity"] = "high"

            # Track post-resolved occurrences for regression detection
            resolved_date = resolved.get(sid, "")
            if resolved_date and ts[:10] > resolved_date:
                if "post_resolved_dates" not in m:
                    m["post_resolved_dates"] = set()
                    m["post_resolved_count"] = 0
                m["post_resolved_dates"].add(ts[:10])
                m["post_resolved_count"] = m.get("post_resolved_count", 0) + 1

    # ------------------------------------------------------------------
    # Apply recurrence gate + suppression + build output records
    # ------------------------------------------------------------------
    results = []

    for sid, m in sig_meta.items():
        severity = m["severity"]
        effective_c = HIGH_SEV_C if severity == "high" else DEFAULT_C
        count = m["count"]
        distinct_days = len(m["dates"])

        flagged = count >= effective_c and distinct_days >= DEFAULT_D

        if not flagged:
            continue

        # Suppression check
        resolved_date = resolved.get(sid, "")
        suppressed = False
        regression = False

        if resolved_date:
            # Check if it regresses after the resolved_ts
            post_count = m.get("post_resolved_count", 0)
            post_days = len(m.get("post_resolved_dates", set()))
            if post_count >= effective_c and post_days >= DEFAULT_D:
                regression = True
                suppressed = False
            else:
                suppressed = True

        if suppressed and not regression:
            continue  # suppressed: don't include

        # Top tool_name
        top_tool = ""
        if m["tool_names"]:
            top_tool = max(m["tool_names"], key=m["tool_names"].get)

        # Bucket hypothesis
        bucket = _bucket(
            m,
            total_admitted,
            m["hook"],
            m["event_label"],
            hook_totals,
        )

        results.append({
            "sig_id": sid,
            "severity": severity,
            "event_label": m["event_label"],
            "agent_type": m["agent_type"],
            "hook": m["hook"],
            "normalized_signature": m["normalized_signature"],
            "count": count,
            "distinct_days": distinct_days,
            "first_seen": m["first_seen"],
            "last_seen": m["last_seen"],
            "top_tool_name": top_tool,
            "raw_samples": m["raw_samples"],
            "bucket": bucket,
            "suppressed": suppressed,
            "regression": regression,
        })

    # Sort: high severity first, then count descending
    results.sort(key=lambda r: (0 if r["severity"] == "high" else 1, -r["count"]))
    return results


# ---------------------------------------------------------------------------
# CLI ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date as _date

    # Resolve the repo root: hooks/ is one level below the repo root
    # (hooks/mine_governance.py -> repo root)
    _REPO = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
    )
    _LOG = os.path.join(_REPO, ".claude", "hooks", "governance-log.jsonl")
    _LEDGER = os.path.join(
        _REPO, ".claude", "hooks", "aggregates", "miner-resolved.jsonl"
    )

    _today = _date.today()
    print(f"mine_governance.py: running against real log, window={WINDOW_DAYS}d, now={_today}")
    print(f"  log:    {_LOG}")
    print(f"  ledger: {_LEDGER} (present={os.path.isfile(_LEDGER)})")
    print()

    flagged = mine(_LOG, _today, WINDOW_DAYS, _LEDGER if os.path.isfile(_LEDGER) else None)

    if not flagged:
        print("No flagged signatures.")
    else:
        print(f"Flagged signatures: {len(flagged)}")
        print()
        for rec in flagged:
            reg_tag = " [REGRESSION]" if rec["regression"] else ""
            print(
                f"  {rec['sig_id']}  sev={rec['severity']:<6}  "
                f"cnt={rec['count']:>4}  days={rec['distinct_days']}  "
                f"bucket={rec['bucket']:<18}  "
                f"label={rec['event_label']}"
                f"{reg_tag}"
            )
            if rec["agent_type"]:
                print(f"    agent_type: {rec['agent_type']}")
            if rec["hook"]:
                print(f"    hook:       {rec['hook']}")
            print(f"    sig:        {rec['normalized_signature'][:80]}")
            print(f"    window:     {rec['first_seen']} to {rec['last_seen']}")
            print()
