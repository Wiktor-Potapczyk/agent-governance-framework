#!/usr/bin/env python3
"""Governance-log failure miner: v1-minimal (REV-1..REV-6, 2026-06-08).

Pure-stdlib helper. Scans .claude/hooks/governance-log.jsonl for recurring
failure patterns keyed by (event_label, agent_type, hook, normalized_reason).
Returns flagged sig records sorted severity-high-first then count-desc.

Spec: Projects/your-project/work/archive/2026-06-07-governance-miner-spec.md
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
# SESSION ADMISSION  (REV-7, 2026-07-30: owner-authorized)
# ---------------------------------------------------------------------------
# The log is shared with hook test suites, which stamp synthetic session values
# ("unknown" = subprocess default, "session" = fixture literal). In the live
# 30d window at adoption time, 14,491 of 15,792 admitted lines were synthetic
# (92%), inflating 6 of 16 flagged sigs into pure test artifacts.
# Doctrine: filter TO real UUID sessions, not merely exclude "session"
# (finding_governance_deny_log_dominated_by_test_pollution).
#
# Rule: if a record CARRIES a session field, it must look like a real session id
# (uuid-ish hex prefix). A record with NO session field is still admitted :
# every live admitted record carries the field, so lenience only preserves
# older log shapes and existing test fixtures, and cannot re-admit the two
# observed pollution markers. sig_id derivation is untouched (REV-6 safe).
_RE_REAL_SESSION = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{3,}", re.IGNORECASE)


def _real_session(record: dict) -> bool:
    """False iff the record carries a session field that is not a real session id."""
    if "session" not in record:
        return True
    s = record.get("session")
    return isinstance(s, str) and bool(_RE_REAL_SESSION.match(s))

# ---------------------------------------------------------------------------
# NORMALIZATION  (light v1: applied to reason text for sig_key)
# ---------------------------------------------------------------------------

_RE_DIGITS = re.compile(r"\d+")
# Path normalization: collapse real filesystem paths to <PATH>.
# Requires an unambiguous path indicator to avoid collapsing bare fractions
# like "50/100" or "3/10".
#
# Three accepted forms:
#   [A-Za-z]:[/\\]: Windows drive letter (C:\, D:/)
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
# SHA-256 prefix or bare hex runs ≥8 chars
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
    if not _real_session(record):  # REV-7 session gate: synthetic lines never enter
        return False
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
# FAILURE LABEL: most-specific label for the sig_key
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
# REASON TEXT: best reason text for normalization
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
        Path to miner-resolved.jsonl. None or missing file → no suppression.

    Returns
    -------
    list of dict: flagged (or regression-surfaced) sig records,
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
                #   fabrication_detected (and any other ALWAYS_HIGH_SEVERITY_EVENTS) → high.
                #   dark-zone → determined per-record below (starts normal, upgraded if any
                #               admitted record carries severity=="high").
                #   everything else → normal.
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
# HERMES P4 - WARN-EVENT MINING PASS (2026-08-18)
#
# Plan of record: Projects/your-project/work/
#   2026-08-17-hermes-p4-warn-event-miner-plan.md (revision 2, approved)
# Build plan: .../2026-08-18-hermes-p4-build-implementation-plan.md
#
# Second pass over the same log. mine(), _admitted(), _normalize_reason(),
# _sig_key(), _sig_id(), _load_resolved() are NOT edited (REV-6: every
# existing failure sig_id stays byte-stable).
#
# Safety properties (constitutional, approved plan section 1):
#   1. Proposal-only forever. This pass computes and returns; it writes nothing.
#   2. The Gate-1 irreversible surface is never proposed for loosening. Every
#      deny-tier value is derived AT RUN TIME from the live guard and surface
#      modules; no private copy of any pattern, description, or suffix exists
#      here (a copy can drift and silently open a floor hole). If derivation
#      fails for ANY reason, the pass fails CLOSED: zero candidates plus the
#      exclusion_unavailable sentinel. There is no fallback snapshot.
# ---------------------------------------------------------------------------

# Warn-specific gates (C and D are reused from the failure pass above).
WARN_MIN_SESSIONS = 3     # distinct-session floor: one long session cannot promote alone
WARN_ACCEPT_WINDOW_MIN = 10  # acceptance-proxy lookforward window, minutes

# Fixed synthetic probe for call-deriving the curl deny reason. TEST-NET-3
# address (RFC 5737), never routable; the predicate is pure (tokenize + return).
_WARN_PROBE_COMMAND = "curl -X POST https://203.0.113.7/hermes-probe -d x=1"

# Loud-note module constants: the renderer (process-governance-mine Step 3b)
# and the tests reference these exact strings.
WARN_DERIVATION_UNAVAILABLE_NOTE = (
    "WARN MINING SKIPPED THIS RUN: canonical-surface derivation failed, "
    "zero proposals emitted."
)
WARN_DENY_TIER_DRIFT_PREFIX = "DENY-TIER PATTERN SEEN IN WARN LOG"

# One-sentence blindness statement, embedded verbatim in every candidate's
# acceptance_note (approved plan section 3).
WARN_ACCEPTANCE_BLINDNESS_NOTE = (
    "Acceptance figures are an upper bound: the log cannot see abandonment "
    "after a warn, later human regret such as a git revert, or the different "
    "semantics of advisory Stop-hook warns versus PreToolUse action-gating warns."
)

_MINER_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_module_from_path(mod_name, path):
    """importlib load of a hooks-dir module file. The hooks dir goes on
    sys.path first so the guard's own `from _irreversible_surface import ...`
    lines resolve. Raises on any failure (caller decides fail-closed)."""
    import importlib.util
    if _MINER_HOOKS_DIR not in sys.path:
        sys.path.insert(0, _MINER_HOOKS_DIR)
    if not os.path.isfile(path):
        raise ImportError("module file not found: %s" % path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("cannot build import spec for %s" % path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_guard_module(path=None):
    """Load bash-safety-guard.py (hyphenated filename, so plain import cannot
    reach it) under a private module name."""
    return _load_module_from_path(
        "_warn_miner_guard",
        path or os.path.join(_MINER_HOOKS_DIR, "bash-safety-guard.py"))


def _load_surface_module(path=None):
    """Load _irreversible_surface.py under a private module name."""
    return _load_module_from_path(
        "_warn_miner_surface",
        path or os.path.join(_MINER_HOOKS_DIR, "_irreversible_surface.py"))


def _derive_exclusion_sets(guard_module=None, surface_module=None,
                           guard_path=None, surface_path=None):
    """Derive (W, D) live from the canonical modules. Approved plan 4.2:

      W = description strings of the guard's own WARN_PATTERNS partition.
      curl_reason = second element of surface.curl_external_write(PROBE),
        valid ONLY when the call returns (True, <non-empty str>).
      D = ({descriptions of surface.IRREVERSIBLE_BASH_PATTERNS}
           | {tool names of surface.IRREVERSIBLE_MCP_TOOLS}
           | {curl_reason}) - W.

    The subtraction mirrors the guard's own lift-out and is load-bearing: the
    push description exists in IRREVERSIBLE_BASH_PATTERNS too.

    The surface loads FIRST: if it is broken, we fail before ever loading the
    guard, whose own broken-surface fallback would alarm to the live log.

    Any exception propagates; mine_warns() converts it to the fail-closed
    sentinel. The module-object parameters exist for test injection only."""
    S = surface_module if surface_module is not None else _load_surface_module(surface_path)
    probe = S.curl_external_write(_WARN_PROBE_COMMAND)
    if not (isinstance(probe, tuple) and len(probe) == 2 and probe[0] is True
            and isinstance(probe[1], str) and probe[1]):
        raise ValueError("curl_external_write probe did not yield (True, reason)")
    curl_reason = probe[1]
    G = guard_module if guard_module is not None else _load_guard_module(guard_path)
    W = set(desc for _pat, desc in G.WARN_PATTERNS)
    d_bash = set(desc for _pat, desc in S.IRREVERSIBLE_BASH_PATTERNS)
    d_mcp = set(S.IRREVERSIBLE_MCP_TOOLS.keys())
    D = (d_bash | d_mcp | {curl_reason}) - W
    return (W, D)


def _warn_parse_dt(ts):
    """Full-datetime parse of a log ts; None when unparseable."""
    from datetime import datetime
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def mine_warns(
    log_path,
    now_date,
    window_days: int = WINDOW_DAYS,
    resolved_ledger_path: str = None,
    _derive=None,
) -> dict:
    """Mine governance-log.jsonl for recurring warn-tier promotion candidates.

    Returns a dict with EXACTLY these keys (frozen contract, build-plan flag 4):
      candidates           list of candidate dicts (see below), count-desc
      exclusion_unavailable  True iff derivation failed (fail-closed sentinel)
      drift_lines          loud notes: deny-tier pattern seen in warn-tier data
      warn_variant_counts  {pattern: count} startswith-a-D-member variants
      unrecognized_counts  {pattern: count} everything else non-proposable
      family_counts        {hook: count} real-session warns with NO pattern field

    Candidate fields: sig_id, pattern, hook, agent_type, severity ("normal"),
    count, distinct_days, distinct_sessions, top_session_share, first_seen,
    last_seen, accepted_count, acceptance_note, command_prefix_samples (<=3),
    suppressed, regression.

    Admission (structural): event == "warn" AND non-empty pattern AND the
    record passes the existing _real_session filter (REV-7, reused).
    Gates: DEFAULT_C occurrences, DEFAULT_D distinct days, WARN_MIN_SESSIONS
    distinct sessions. Always severity "normal" (HIGH_SEV_C never applies).
    Suppression/regression: same ledger, same _load_resolved, same semantics
    as mine().

    Acceptance proxy (approved plan section 3): a warn is "accepted" when the
    same session logs no deny/block from the same hook within the
    WARN_ACCEPT_WINDOW_MIN minutes after it. Figures are an upper bound (see
    WARN_ACCEPTANCE_BLINDNESS_NOTE).

    _derive is a test-injection hook returning (W, D); production always uses
    _derive_exclusion_sets. Any derivation failure returns the fail-closed
    sentinel: NO fallback snapshot exists by design."""
    result = {
        "candidates": [],
        "exclusion_unavailable": False,
        "drift_lines": [],
        "warn_variant_counts": {},
        "unrecognized_counts": {},
        "family_counts": {},
    }

    try:
        W, D = (_derive or _derive_exclusion_sets)()
        if not isinstance(W, (set, frozenset)) or not isinstance(D, (set, frozenset)):
            raise ValueError("derivation returned non-set exclusion data")
    except Exception:
        return {
            "candidates": [],
            "exclusion_unavailable": True,
            "drift_lines": [],
            "warn_variant_counts": {},
            "unrecognized_counts": {},
            "family_counts": {},
        }

    if isinstance(now_date, str):
        now_date = date.fromisoformat(now_date)
    window_start = now_date - timedelta(days=window_days)
    resolved = _load_resolved(resolved_ledger_path)

    warn_meta = {}     # sid -> aggregates
    deny_index = {}    # (session, hook) -> [datetime, ...]
    drift_counts = {}  # deny-tier pattern -> count

    try:
        fh = open(log_path, "r", encoding="utf-8")
    except OSError:
        return result

    with fh:
        for raw_line in fh:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except Exception:
                continue
            if not isinstance(record, dict):
                continue
            # Coerce string-ish fields (mirrors mine(); mine() itself untouched).
            for _f in ("event", "agent_type", "hook", "pattern"):
                _v = record.get(_f)
                if _v is not None and not isinstance(_v, str):
                    record[_f] = str(_v)

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

            event = record.get("event", "") or ""
            hook_val = record.get("hook", "") or ""
            session = record.get("session", "")
            if not isinstance(session, str):
                session = str(session)

            # Collect deny/block events for the acceptance-proxy lookforward.
            if event in ("deny", "block"):
                dt = _warn_parse_dt(ts)
                if dt is not None:
                    deny_index.setdefault((session, hook_val), []).append(dt)
                continue

            if event != "warn":
                continue
            if not _real_session(record):
                continue  # REV-7 reuse: synthetic sessions never enter

            pattern = record.get("pattern", "") or ""
            if not pattern.strip():
                # Non-pattern warn family (advisory Stop-hook / dispatch
                # semantics): measured only, never proposable in v1.
                key = hook_val or "(no hook)"
                result["family_counts"][key] = result["family_counts"].get(key, 0) + 1
                continue

            # Classification, exact-match first (approved plan 4.2 point 5).
            if pattern in D:
                drift_counts[pattern] = drift_counts.get(pattern, 0) + 1
                continue  # hard exclusion: zero sigs, zero candidates, any count
            if pattern not in W:
                if any(pattern.startswith(d) and len(pattern) > len(d) for d in D):
                    result["warn_variant_counts"][pattern] = (
                        result["warn_variant_counts"].get(pattern, 0) + 1)
                else:
                    result["unrecognized_counts"][pattern] = (
                        result["unrecognized_counts"].get(pattern, 0) + 1)
                continue  # measured, not proposable

            # Candidate-eligible (pattern in W).
            agent_type = record.get("agent_type", "") or ""
            key = _sig_key("warn", agent_type, hook_val, _normalize_reason(pattern))
            sid = _sig_id(key)

            if sid not in warn_meta:
                warn_meta[sid] = {
                    "sig_id": sid,
                    "pattern": pattern,
                    "hook": hook_val,
                    "agent_type": agent_type,
                    "count": 0,
                    "dates": set(),
                    "sessions": {},
                    "first_seen": ts[:10],
                    "last_seen": ts[:10],
                    "command_prefix_samples": [],
                    "events": [],  # (session, hook, datetime|None) for the proxy
                }
            m = warn_meta[sid]
            m["count"] += 1
            m["dates"].add(ts[:10])
            m["sessions"][session] = m["sessions"].get(session, 0) + 1
            if ts[:10] < m["first_seen"]:
                m["first_seen"] = ts[:10]
            if ts[:10] > m["last_seen"]:
                m["last_seen"] = ts[:10]
            cp = record.get("command_prefix", "")
            if cp and len(m["command_prefix_samples"]) < 3:
                m["command_prefix_samples"].append(cp)
            m["events"].append((session, hook_val, _warn_parse_dt(ts)))

            # Post-resolved tracking (same semantics as mine()).
            resolved_date = resolved.get(sid, "")
            if resolved_date and ts[:10] > resolved_date:
                if "post_resolved_dates" not in m:
                    m["post_resolved_dates"] = set()
                    m["post_resolved_count"] = 0
                m["post_resolved_dates"].add(ts[:10])
                m["post_resolved_count"] = m.get("post_resolved_count", 0) + 1

    # Drift notes: one loud line per deny-tier pattern sighted in warn data.
    for pat in sorted(drift_counts):
        result["drift_lines"].append(
            "%s: '%s' seen %dx in warn-tier records; deny-tier reasons are never "
            "promotion candidates. Investigate log spoofing, fixture pollution, "
            "or an un-owner-gated demotion."
            % (WARN_DENY_TIER_DRIFT_PREFIX, pat, drift_counts[pat]))

    # Gates + suppression + candidate assembly.
    window_seconds = WARN_ACCEPT_WINDOW_MIN * 60
    for sid, m in warn_meta.items():
        count = m["count"]
        distinct_days = len(m["dates"])
        distinct_sessions = len(m["sessions"])
        if not (count >= DEFAULT_C and distinct_days >= DEFAULT_D
                and distinct_sessions >= WARN_MIN_SESSIONS):
            continue

        resolved_date = resolved.get(sid, "")
        suppressed = False
        regression = False
        if resolved_date:
            post_count = m.get("post_resolved_count", 0)
            post_days = len(m.get("post_resolved_dates", set()))
            if post_count >= DEFAULT_C and post_days >= DEFAULT_D:
                regression = True
            else:
                suppressed = True
        if suppressed and not regression:
            continue

        # Acceptance proxy: a warn is accepted unless a same-session same-hook
        # deny/block lands within the lookforward window after it. An
        # unparseable warn timestamp counts as accepted (upper-bound behavior).
        accepted = 0
        for session, hook_val, wdt in m["events"]:
            if wdt is None:
                accepted += 1
                continue
            hits = deny_index.get((session, hook_val), [])
            if any(0 <= (ddt - wdt).total_seconds() <= window_seconds
                   for ddt in hits):
                continue
            accepted += 1

        top_session_share = (max(m["sessions"].values()) / float(count)) if count else 0.0

        result["candidates"].append({
            "sig_id": sid,
            "pattern": m["pattern"],
            "hook": m["hook"],
            "agent_type": m["agent_type"],
            "severity": "normal",
            "count": count,
            "distinct_days": distinct_days,
            "distinct_sessions": distinct_sessions,
            "top_session_share": top_session_share,
            "first_seen": m["first_seen"],
            "last_seen": m["last_seen"],
            "accepted_count": accepted,
            "acceptance_note": (
                "%d of %d warns accepted by the %d-minute same-hook proxy. %s"
                % (accepted, count, WARN_ACCEPT_WINDOW_MIN,
                   WARN_ACCEPTANCE_BLINDNESS_NOTE)),
            "command_prefix_samples": m["command_prefix_samples"],
            "suppressed": suppressed,
            "regression": regression,
        })

    result["candidates"].sort(key=lambda c: (-c["count"], c["sig_id"]))
    return result


# ---------------------------------------------------------------------------
# CLI ENTRY POINT
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from datetime import date as _date

    _VAULT = os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    _LOG = os.path.join(_VAULT, ".claude", "hooks", "governance-log.jsonl")
    _LEDGER = os.path.join(
        _VAULT, ".claude", "hooks", "aggregates", "miner-resolved.jsonl"
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
