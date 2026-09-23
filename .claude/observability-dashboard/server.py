"""
server.py — Observability dashboard HTTP server.

Serves static files (index.html, app.js, styles.css) and two JSON APIs:
  GET  /api/events            — stream parsed governance-log.jsonl as JSON
  POST /api/analyze           — invoke _haiku_summarize.py for a session/since-ts window

Usage:
    python server.py [--port 7654] [--log-path /path/to/governance-log.jsonl]

Security:
- Static file serving uses an explicit whitelist; no directory traversal.
- /api/analyze parameters are validated against strict regexes before subprocess.
- Content-Security-Policy header on HTML responses.
- All event field rendering is textContent-based in the frontend (no innerHTML).
"""

import argparse
import collections
import datetime
import http.server
import json
import mimetypes
import os
import re
import subprocess
import sys
import urllib.parse
from http import HTTPStatus


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.join(_HERE, "..", "hooks")
_DEFAULT_LOG_PATH = os.path.normpath(os.path.join(_HOOKS_DIR, "governance-log.jsonl"))
_HAIKU_WORKER = os.path.normpath(os.path.join(_HOOKS_DIR, "_haiku_summarize.py"))

# Populated at startup from --log-path arg
_LOG_PATH: str = _DEFAULT_LOG_PATH

# Static file whitelist: URL path → filesystem filename
_STATIC_FILES: dict[str, str] = {
    "/":                                "index.html",
    "/index.html":                      "index.html",
    "/app.js":                          "app.js",
    "/styles.css":                      "styles.css",
    "/vendor/chart.umd.min.js":         "vendor/chart.umd.min.js",
}

# ---------------------------------------------------------------------------
# /api/query — parameter validation
# ---------------------------------------------------------------------------

VALID_GROUP_BY = {"hook", "event", "agent_type", "session", "severity", "outcome", "tool_type"}
VALID_METRICS  = {"count", "turn_total_tokens", "block_count", "run_count", "ratio_avg", "ratio_max"}
VALID_WINDOWS  = {"all", "7d", "today"}

# Wired combination matrix: (group_by, metric) → True/False/str("approximate")
# False = unsupported (returns 400); True = supported; "approximate" = supported but sparse
_WIRED = {
    ("hook",       "count"):             True,
    ("hook",       "block_count"):       True,
    ("hook",       "run_count"):         True,
    ("event",      "count"):             True,
    ("agent_type", "count"):             True,
    ("agent_type", "run_count"):         True,
    ("agent_type", "turn_total_tokens"): "approximate",
    ("session",    "count"):             True,
    ("session",    "turn_total_tokens"): True,
    ("session",    "block_count"):       True,
    ("session",    "ratio_avg"):         True,
    ("session",    "ratio_max"):         True,
    ("severity",   "count"):             True,
    ("outcome",    "count"):             True,
    ("tool_type",  "count"):             True,
}

# ---------------------------------------------------------------------------
# Parameter validation regexes for /api/analyze
# ---------------------------------------------------------------------------

_RE_SESSION = re.compile(r"^[a-zA-Z0-9_\-]+$")
_RE_SINCE_TS = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

# ---------------------------------------------------------------------------
# JSONL reader
# ---------------------------------------------------------------------------

def _read_events(log_path: str) -> list[dict]:
    """
    Parse governance-log.jsonl and return all valid event rows.
    Skips blank lines, non-JSON rows, and legacy rows that predate
    the schema-2 'event' field (those have no 'event' key).
    """
    events: list[dict] = []
    if not os.path.exists(log_path):
        return events
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                # Skip legacy rows that have no 'event' key
                if "event" not in obj or obj["event"] is None:
                    continue
                events.append(obj)
    except OSError:
        pass
    return events


def _count_legacy_rows(log_path: str) -> int:
    """Count rows where schema != 2 OR event is None (pre-v2 legacy entries)."""
    n = 0
    if not os.path.exists(log_path):
        return n
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if obj.get("schema") != 2 or obj.get("event") is None:
                    n += 1
    except OSError:
        pass
    return n


# ---------------------------------------------------------------------------
# /api/query helpers
# ---------------------------------------------------------------------------

def _read_all_rows(log_path: str) -> list[dict]:
    """Read ALL rows including legacy; return raw parsed objects."""
    rows: list[dict] = []
    if not os.path.exists(log_path):
        return rows
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rows.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return rows


def _ingest_filter(rows: list[dict], window: str) -> tuple[list[dict], int]:
    """
    Apply ingestion filters per §4.4:
      1. Warn/warning coalesce (in-memory, no mutation of source)
      2. NULL_EVENT labeling (rows without 'event')
      3. Zombie session exclusion (duration_sec > 86400)
      4. Window filter (all / 7d / today)

    Returns (filtered_rows, legacy_null_count).
    """
    # Build zombie session set from session_end rows
    zombie_sessions: set[str] = set()
    for row in rows:
        if row.get("event") == "session_end":
            dur = row.get("duration_sec")
            sess = row.get("session")
            if sess and isinstance(dur, (int, float)) and dur > 86400:
                zombie_sessions.add(sess)

    # Window cutoff
    now = datetime.datetime.utcnow()
    if window == "today":
        cutoff_str = now.strftime("%Y-%m-%d")
    elif window == "7d":
        cutoff_str = (now - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    else:
        cutoff_str = None

    filtered: list[dict] = []
    legacy_count = 0

    for row in rows:
        # Deep-copy to avoid mutating the source
        r = dict(row)

        # NULL_EVENT labeling
        if not r.get("event"):
            r["event"] = "legacy_classification"
            legacy_count += 1

        # Warn/warning coalesce
        if r["event"] == "warning":
            r["event"] = "warn"

        # Zombie exclusion
        sess = r.get("session")
        if sess and sess in zombie_sessions:
            continue

        # Window filter
        if cutoff_str:
            ts = r.get("ts", "")
            if ts[:10] < cutoff_str:
                continue

        filtered.append(r)

    return filtered, legacy_count


def _aggregate(rows: list[dict], group_by: str, metric: str, top_n: int, approximate: bool) -> list[dict]:
    """Aggregate rows by group_by field, computing the given metric."""

    if group_by == "tool_type":
        # Special: unpack token_breakdown.tool_calls dict
        counts: dict[str, int] = collections.Counter()
        for r in rows:
            if r.get("event") == "token_breakdown":
                tc = r.get("tool_calls") or {}
                if isinstance(tc, dict):
                    for tool, cnt in tc.items():
                        counts[tool] += int(cnt)
        result = [
            {"key": k, "value": v, "approximate": False, "row_count": v}
            for k, v in counts.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if group_by == "session" and metric == "turn_total_tokens":
        totals: dict[str, float] = collections.defaultdict(float)
        row_counts: dict[str, int] = collections.defaultdict(int)
        for r in rows:
            if r.get("event") == "token_breakdown":
                sess = r.get("session") or "__unknown__"
                totals[sess] += r.get("turn_total_tokens", 0) or 0
                row_counts[sess] += 1
        result = [
            {"key": k, "value": round(v), "approximate": approximate, "row_count": row_counts[k]}
            for k, v in totals.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if group_by == "session" and metric == "block_count":
        counts: dict[str, int] = collections.defaultdict(int)
        for r in rows:
            if r.get("event") in ("block", "deny"):
                sess = r.get("session") or "__unknown__"
                counts[sess] += 1
        result = [
            {"key": k, "value": v, "approximate": approximate, "row_count": v}
            for k, v in counts.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if group_by == "session" and metric == "ratio_avg":
        totals: dict[str, list] = collections.defaultdict(list)
        for r in rows:
            if r.get("event") == "dark-zone":
                sess = r.get("session") or "__unknown__"
                ratio = r.get("ratio")
                if ratio is not None:
                    totals[sess].append(ratio)
        result = [
            {"key": k, "value": round(sum(v) / len(v), 3), "approximate": approximate, "row_count": len(v)}
            for k, v in totals.items() if v
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if group_by == "session" and metric == "ratio_max":
        maxes: dict[str, float] = {}
        row_counts: dict[str, int] = collections.defaultdict(int)
        for r in rows:
            if r.get("event") == "dark-zone":
                sess = r.get("session") or "__unknown__"
                ratio = r.get("ratio")
                if ratio is not None:
                    if sess not in maxes or ratio > maxes[sess]:
                        maxes[sess] = ratio
                    row_counts[sess] += 1
        result = [
            {"key": k, "value": v, "approximate": approximate, "row_count": row_counts[k]}
            for k, v in maxes.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if group_by == "session" and metric == "count":
        counts: dict[str, int] = collections.defaultdict(int)
        for r in rows:
            sess = r.get("session") or "__unknown__"
            counts[sess] += 1
        result = [
            {"key": k, "value": v, "approximate": False, "row_count": v}
            for k, v in counts.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if metric == "count":
        counts: dict[str, int] = collections.Counter()
        for r in rows:
            key_val = r.get(group_by) or "__unknown__"
            if isinstance(key_val, list):
                key_val = str(key_val)
            counts[str(key_val)] += 1
        result = [
            {"key": k, "value": v, "approximate": approximate, "row_count": v}
            for k, v in counts.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if metric == "block_count" and group_by == "hook":
        counts: dict[str, int] = collections.defaultdict(int)
        for r in rows:
            if r.get("event") in ("block", "deny"):
                hook = r.get("hook") or "__unknown__"
                counts[hook] += 1
        result = [
            {"key": k, "value": v, "approximate": False, "row_count": v}
            for k, v in counts.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if metric == "run_count":
        counts: dict[str, int] = collections.Counter()
        for r in rows:
            key_val = r.get(group_by) or "__unknown__"
            counts[str(key_val)] += 1
        result = [
            {"key": k, "value": v, "approximate": approximate, "row_count": v}
            for k, v in counts.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    if metric == "turn_total_tokens" and group_by == "agent_type":
        # Approximate: subagent token attribution via by_subagent
        totals: dict[str, float] = collections.defaultdict(float)
        row_counts: dict[str, int] = collections.defaultdict(int)
        for r in rows:
            if r.get("event") == "token_breakdown":
                by_sub = r.get("by_subagent") or []
                for sub in by_sub:
                    agent = sub.get("agent_type") or sub.get("agentType") or "__unknown__"
                    toks = sub.get("totalTokens") or sub.get("total_tokens") or 0
                    totals[agent] += toks
                    row_counts[agent] += 1
        result = [
            {"key": k, "value": round(v), "approximate": True, "row_count": row_counts[k]}
            for k, v in totals.items()
        ]
        result.sort(key=lambda x: -x["value"])
        return result[:top_n]

    return []


def _compute_kpis(rows: list[dict]) -> dict:
    """Compute the 4 top-strip KPIs."""
    total_tokens = 0
    distinct_sessions: set = set()
    enforcement_events = 0
    total_hook_events = 0
    agent_dispatched_total = 0
    agent_dispatched_no_class = 0

    for r in rows:
        ev = r.get("event", "")
        sess = r.get("session")
        if sess:
            distinct_sessions.add(sess)

        if ev == "token_breakdown":
            total_tokens += r.get("turn_total_tokens", 0) or 0

        if r.get("hook"):
            total_hook_events += 1
            if ev in ("block", "deny", "warn", "warning"):
                enforcement_events += 1

        if ev == "agent_dispatched":
            agent_dispatched_total += 1
            if r.get("outcome") == "no_classification":
                agent_dispatched_no_class += 1

    etr = round(enforcement_events / total_hook_events * 100, 1) if total_hook_events > 0 else 0.0
    udr = round(agent_dispatched_no_class / agent_dispatched_total * 100, 1) if agent_dispatched_total > 0 else 0.0

    return {
        "total_tokens": total_tokens,
        "distinct_sessions": len(distinct_sessions),
        "enforcement_trigger_rate": etr,
        "enforcement_trigger_rate_label": "Enforcement Trigger Rate",
        "enforcement_numerator": enforcement_events,
        "enforcement_denominator": total_hook_events,
        "ungoverned_dispatch_rate": udr,
        "ungoverned_dispatch_rate_label": "Ungoverned Dispatch Rate",
        "ungoverned_numerator": agent_dispatched_no_class,
        "ungoverned_denominator": agent_dispatched_total,
    }


def _compute_session_ledger(rows: list[dict]) -> list[dict]:
    """Compute per-session aggregate for Session Ledger."""
    session_data: dict[str, dict] = {}

    def _get(sess):
        if sess not in session_data:
            session_data[sess] = {
                "session": sess,
                "duration_sec": None,
                "turn_count": 0,
                "total_tokens": 0,
                "block_count": 0,
                "dark_zone_count": 0,
                "classification_complete": 0,
                "classification_total": 0,
            }
        return session_data[sess]

    for r in rows:
        ev = r.get("event", "")
        sess = r.get("session") or "__unknown__"
        d = _get(sess)

        if ev == "session_end":
            dur = r.get("duration_sec")
            if dur is not None:
                d["duration_sec"] = dur
            d["turn_count"] = r.get("turn_count", d["turn_count"]) or d["turn_count"]

        if ev == "token_breakdown":
            d["total_tokens"] += r.get("turn_total_tokens", 0) or 0

        if ev in ("block", "deny"):
            d["block_count"] += 1

        if ev == "dark-zone":
            d["dark_zone_count"] += 1

        if ev == "classification_emitted":
            d["classification_total"] += 1
            if r.get("complete") is True:
                d["classification_complete"] += 1

    result = []
    for sess, d in session_data.items():
        ct = d["classification_total"]
        cc = d["classification_complete"]
        if ct > 0:
            cls_pct = round(cc / ct * 100, 1)
        else:
            cls_pct = None  # → UI renders "—"
        result.append({
            "session": d["session"],
            "duration_sec": d["duration_sec"],
            "turn_count": d["turn_count"],
            "total_tokens": d["total_tokens"],
            "block_count": d["block_count"],
            "dark_zone_count": d["dark_zone_count"],
            "classification_complete_pct": cls_pct,
        })

    result.sort(key=lambda x: x["total_tokens"], reverse=True)
    return result


def _compute_governance_health(rows: list[dict]) -> dict:
    """Compute dark-zone ratio histogram + severity counts."""
    ratios = []
    severity_counts: dict[str, int] = collections.Counter()
    per_session_ratios: dict[str, list] = collections.defaultdict(list)

    for r in rows:
        if r.get("event") == "dark-zone":
            ratio = r.get("ratio")
            sev = r.get("severity", "unknown")
            sess = r.get("session") or "__unknown__"
            if ratio is not None:
                ratios.append(ratio)
                per_session_ratios[sess].append(ratio)
            severity_counts[sev] += 1

    # Build 10-bin histogram
    if ratios:
        mn, mx = min(ratios), max(ratios)
        bin_size = (mx - mn) / 10 if mx > mn else 1.0
        bins = [0] * 10
        labels = []
        for i in range(10):
            lo = mn + i * bin_size
            hi = mn + (i + 1) * bin_size
            labels.append(f"{lo:.1f}–{hi:.1f}")
        for v in ratios:
            idx = min(int((v - mn) / bin_size), 9)
            bins[idx] += 1
        histogram = {"labels": labels, "counts": bins}
    else:
        histogram = {"labels": [], "counts": []}

    # Per-session aggregates
    session_agg = []
    for sess, rs in per_session_ratios.items():
        session_agg.append({
            "session": sess,
            "mean_ratio": round(sum(rs) / len(rs), 3),
            "max_ratio": max(rs),
        })
    session_agg.sort(key=lambda x: -x["mean_ratio"])

    return {
        "histogram": histogram,
        "severity_counts": dict(severity_counts),
        "total_dark_zone": len(ratios),
        "session_aggregates": session_agg[:20],
    }


def _count_error_summaries() -> int:
    """Fast count of existing error_summary rows (for pre/post-analyze diff)."""
    n = 0
    if not os.path.exists(_LOG_PATH):
        return n
    try:
        with open(_LOG_PATH, "r", encoding="utf-8") as fh:
            for raw in fh:
                # Cheap string check before JSON parse
                if '"event":"error_summary"' not in raw and '"event": "error_summary"' not in raw:
                    continue
                try:
                    obj = json.loads(raw.strip())
                except json.JSONDecodeError:
                    continue
                if obj.get("event") == "error_summary":
                    n += 1
    except OSError:
        pass
    return n


# ---------------------------------------------------------------------------
# Request handler
# ---------------------------------------------------------------------------

class DashboardHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        """Suppress default access log; keeps terminal clean."""
        pass

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/events":
            self._handle_events(parsed.query)
        elif path == "/api/query":
            self._handle_query(parsed.query)
        elif path in _STATIC_FILES or path == "/":
            self._handle_static(path if path != "" else "/")
        else:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/analyze":
            self._handle_analyze()
        elif path == "/api/reask":
            self._send_json(
                {"error": "not_implemented", "detail": "Re-ask is a Sprint 4 candidate."},
                HTTPStatus.NOT_IMPLEMENTED,
            )
        else:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)

    # ------------------------------------------------------------------
    # Static file handler — whitelist only, no traversal
    # ------------------------------------------------------------------

    def _handle_static(self, url_path: str) -> None:
        filename = _STATIC_FILES.get(url_path)
        if not filename:
            self._send_json({"error": "not_found"}, HTTPStatus.NOT_FOUND)
            return

        file_path = os.path.join(_HERE, filename)
        if not os.path.exists(file_path):
            self._send_json({"error": "file_missing", "detail": filename}, HTTPStatus.NOT_FOUND)
            return

        mime, _ = mimetypes.guess_type(filename)
        if mime is None:
            mime = "application/octet-stream"

        with open(file_path, "rb") as fh:
            body = fh.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        if mime == "text/html":
            # Belt-and-suspenders: prevents any injected log value from
            # executing as script even if innerHTML were accidentally used.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'"
            )
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    # GET /api/events
    # ------------------------------------------------------------------

    def _handle_events(self, query_string: str) -> None:
        params = urllib.parse.parse_qs(query_string)
        since = params.get("since", [None])[0]
        # Support both "since_ts" (plan name) and "since" (current) for compat
        if not since:
            since = params.get("since_ts", [None])[0]
        try:
            limit = int(params.get("limit", [500])[0])
        except (TypeError, ValueError):
            limit = 500
        # Clamp: [1, 5000]
        limit = max(1, min(limit, 5000))

        events = _read_events(_LOG_PATH)
        total = len(events)
        # Count legacy (schema != 2) rows separately — they're filtered in _read_events
        # but we want to surface the count for the UI's stats strip.
        legacy_count = _count_legacy_rows(_LOG_PATH)

        if since:
            events = [e for e in events if e.get("ts", "") > since]

        # Sort newest-first, then slice to limit
        events.sort(key=lambda e: e.get("ts", ""), reverse=True)
        events = events[:limit]

        self._send_json({
            "events": events,
            "total": total,
            "legacy_count": legacy_count,
        })

    # ------------------------------------------------------------------
    # GET /api/query
    # ------------------------------------------------------------------

    def _handle_query(self, query_string: str) -> None:
        params = urllib.parse.parse_qs(query_string)

        def _first(key, default=None):
            vals = params.get(key)
            return vals[0] if vals else default

        group_by = _first("group_by", "")
        metric   = _first("metric", "count")
        window   = _first("window", "all")
        filter_key = _first("filter_key", "")
        filter_val = _first("filter_val", "")

        # Special mode: KPIs
        if _first("mode") == "kpis":
            rows_all, _ = _ingest_filter(_read_all_rows(_LOG_PATH), window)
            # D1: apply session filter before aggregation when requested
            if filter_key == "session_id" and filter_val:
                rows_all = [r for r in rows_all if str(r.get("session_id", "")) == filter_val]
            self._send_json(_compute_kpis(rows_all))
            return

        # Special mode: session_ledger
        if _first("mode") == "session_ledger":
            rows_all, _ = _ingest_filter(_read_all_rows(_LOG_PATH), window)
            # D1: session_ledger is intentionally NOT filtered by session_id —
            # it is the cross-session index and its rows ARE the sessions.
            self._send_json({"rows": _compute_session_ledger(rows_all)})
            return

        # Special mode: governance_health
        if _first("mode") == "governance_health":
            rows_all, _ = _ingest_filter(_read_all_rows(_LOG_PATH), window)
            # D1: apply session filter before aggregation when requested
            if filter_key == "session_id" and filter_val:
                rows_all = [r for r in rows_all if str(r.get("session_id", "")) == filter_val]
            self._send_json(_compute_governance_health(rows_all))
            return

        # Validate group_by + metric
        if group_by not in VALID_GROUP_BY:
            self._send_json(
                {"error": f"invalid group_by '{group_by}'; must be one of: {sorted(VALID_GROUP_BY)}"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if metric not in VALID_METRICS:
            self._send_json(
                {"error": f"invalid metric '{metric}'; must be one of: {sorted(VALID_METRICS)}"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        if window not in VALID_WINDOWS:
            self._send_json(
                {"error": f"invalid window '{window}'; must be one of: {sorted(VALID_WINDOWS)}"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        # Check wired combination matrix (§4.2)
        combo_support = _WIRED.get((group_by, metric))
        if combo_support is None:
            self._send_json(
                {
                    "error": (
                        f"combination {group_by}+{metric} not supported; "
                        "see /api/query matrix"
                    )
                },
                HTTPStatus.BAD_REQUEST,
            )
            return

        approximate = combo_support == "approximate"

        # top_n — clamp [1, 500]
        try:
            top_n = int(_first("top", "15"))
        except (TypeError, ValueError):
            top_n = 15
        top_n = max(1, min(top_n, 500))

        # Load + ingest filter
        all_rows = _read_all_rows(_LOG_PATH)
        rows, legacy_count = _ingest_filter(all_rows, window)

        # Optional event-type filter
        if filter_key and filter_val:
            rows = [r for r in rows if str(r.get(filter_key, "")) == filter_val]

        result = _aggregate(rows, group_by, metric, top_n, approximate)
        self._send_json({"data": result, "legacy_count": legacy_count, "total_rows": len(rows)})

    # ------------------------------------------------------------------
    # POST /api/analyze
    # ------------------------------------------------------------------

    def _handle_analyze(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b""

        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            self._send_json(
                {"error": "invalid_json", "detail": "request body"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        session: str | None = body.get("session")
        since_ts: str | None = body.get("since_ts")
        max_raw = body.get("max", 5)

        # Validate — reject with structured error on regex mismatch
        if session is not None:
            if not isinstance(session, str) or not _RE_SESSION.match(session):
                self._send_json(
                    {"error": "invalid_params", "detail": "session"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

        if since_ts is not None:
            if not isinstance(since_ts, str) or not _RE_SINCE_TS.match(since_ts):
                self._send_json(
                    {"error": "invalid_params", "detail": "since_ts"},
                    HTTPStatus.BAD_REQUEST,
                )
                return

        if not session and not since_ts:
            self._send_json(
                {"error": "invalid_params", "detail": "require session or since_ts"},
                HTTPStatus.BAD_REQUEST,
            )
            return

        # Max — coerce + clamp to [1, 20]. Hard ceiling enforced server-side
        # regardless of worker's internal default (cost safety per user's escape clause).
        try:
            max_n = int(max_raw)
        except (TypeError, ValueError):
            self._send_json(
                {"error": "invalid_params", "detail": "max must be integer"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        max_n = max(1, min(max_n, 20))

        if not os.path.exists(_HAIKU_WORKER):
            self._send_json(
                {"error": "worker_missing", "detail": _HAIKU_WORKER},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )
            return

        # Count error_summary rows BEFORE run, to diff new summaries from worker output.
        pre_summary_count = _count_error_summaries()

        # Build args as a list — never shell=True
        cmd = [sys.executable, _HAIKU_WORKER, "--max", str(max_n)]
        if session:
            cmd += ["--session", session]
        if since_ts:
            cmd += ["--since-ts", since_ts]

        # Inherit environment so OAuth (HOME, PATH, etc.) is available
        env = os.environ.copy()

        # Use Popen + communicate() so we can kill orphaned child on timeout
        # (subprocess.run leaves the child alive on Windows timeout).
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=env,
            )
            try:
                stdout, stderr = proc.communicate(timeout=600)
                returncode = proc.returncode
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", "worker did not exit after SIGKILL"
                returncode = -1
                timed_out = True

            post_summary_count = _count_error_summaries()
            summaries_created = max(0, post_summary_count - pre_summary_count)

            if timed_out:
                self._send_json(
                    {
                        "error": "worker_timeout",
                        "detail": "exceeded 600s; child killed",
                        "summaries_created": summaries_created,
                        "stdout": stdout,
                        "stderr": stderr,
                    },
                    HTTPStatus.GATEWAY_TIMEOUT,
                )
            else:
                self._send_json({
                    "ok": returncode == 0 and summaries_created > 0,
                    "summaries_created": summaries_created,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                    "max_requested": max_n,
                })
        except Exception as exc:
            self._send_json(
                {"error": "worker_error", "detail": str(exc)},
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Observability dashboard server")
    parser.add_argument("--port", type=int, default=7654, help="Port to listen on (default 7654)")
    parser.add_argument(
        "--log-path",
        default=_DEFAULT_LOG_PATH,
        help=f"Path to governance-log.jsonl (default: {_DEFAULT_LOG_PATH})",
    )
    args = parser.parse_args()

    global _LOG_PATH
    _LOG_PATH = args.log_path

    if not os.path.exists(args.log_path):
        print(f"WARNING: log file not found: {args.log_path}", file=sys.stderr)

    server_address = ("127.0.0.1", args.port)
    httpd = http.server.HTTPServer(server_address, DashboardHandler)

    print(f"Dashboard: http://127.0.0.1:{args.port}/")
    print(f"Log path:  {args.log_path}")
    print("Press Ctrl+C to stop.")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        httpd.server_close()


if __name__ == "__main__":
    main()
