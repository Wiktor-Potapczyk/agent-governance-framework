"""
Daily aggregate builder for observability v2 (2026-04-19).

Reads governance-log.jsonl, filters by today's date + environment=prod +
non-test session IDs, writes a summary JSON to aggregates/daily/<YYYY-MM-DD>.json.

Summary schema:
{
  "date": "YYYY-MM-DD",
  "generated_at": "ISO timestamp",
  "sessions": int,
  "classifications": int,
  "quick_ratio": float,
  "classifier_blocks": int,
  "qa_fails": int,
  "agent_warn_downgrades": int,
  "agent_dispatches": int,
  "alerts": [ "human-readable threshold breach strings" ]
}

Thresholds (kept simple; tuneable later):
- classifier_blocks >= 1     → alert "N classifier blocks today"
- qa_fails >= 1              → alert "N QA FAILs today"
- agent_warn_downgrades >= 3 → alert "N off-contract dispatches today"
- quick_ratio > 0.95         → alert "Quick-only share is N% (classifier too lax?)"
"""

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime


HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HOOKS_DIR, "governance-log.jsonl")
AGG_DIR = os.path.join(HOOKS_DIR, "aggregates", "daily")
# 2026-09-21: lint_pass_qa_health.py (process-lint Pass W) writes its last
# measurement here; a finding younger than QA_HEALTH_MAX_AGE_DAYS becomes a
# dashboard alert, which is the only route into the daily digest.
QA_HEALTH_STATE = os.path.join(HOOKS_DIR, "_state", "qa-health.json")
QA_HEALTH_MAX_AGE_DAYS = 8
QA_HEALTH_STALE_DAYS = 14    # a pass that has not run is not a clean pass
QA_HEALTH_REGISTERED = "2026-09-21"  # the day Pass W joined the sweep; earlier sweeps could not have run it
LINT_CADENCE_STATE = os.path.join(HOOKS_DIR, "_state", "lint-cadence.json") if 'HOOKS_DIR' in dir() else os.path.join(os.path.dirname(os.path.abspath(__file__)), "_state", "lint-cadence.json")

TEST_RE = re.compile(
    r"^(?:fixture-|pentest-|h5-|h3-|fake-|test$|test[-_]|unknown$)",
    re.IGNORECASE,
)


def is_test(sid):
    return not sid or bool(TEST_RE.match(sid))


def _lint_sweep_date(lint_state_path):
    """The date of the last /process-lint sweep from its cadence state, or None."""
    try:
        with open(lint_state_path, "r", encoding="utf-8") as fh:
            return str(json.load(fh).get("last_iso", ""))[:10] or None
    except (OSError, ValueError, AttributeError):
        return None


def qa_health_alerts(date_str, state_path=None, lint_state_path=None):
    """Alert strings from the QA-health lint pass's state file. A stale run
    (older than QA_HEALTH_STALE_DAYS) is itself an alert. No state file is an
    alert only when the weekly sweep ran within QA_HEALTH_MAX_AGE_DAYS of
    date_str on or after the day the pass was registered (architect review N1,
    2026-09-21: an unconditional never-run alert fired on every session start
    and broke test_session_start_log, whose dead 1970 date must see nothing)."""
    path = state_path or QA_HEALTH_STATE
    try:
        ref = datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return []
    if not os.path.isfile(path):
        sweep = _lint_sweep_date(lint_state_path or LINT_CADENCE_STATE)
        if sweep and sweep >= QA_HEALTH_REGISTERED:
            try:
                gap = (ref - datetime.strptime(sweep, "%Y-%m-%d")).days
            except ValueError:
                return []
            if 0 <= gap <= QA_HEALTH_MAX_AGE_DAYS:
                return [f"QA health: lint pass W has never run although the sweep ran on {sweep}"]
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return ["QA health: lint pass W state file is unreadable"]
    try:
        last = datetime.strptime(str(state.get("last_run", "")), "%Y-%m-%d")
    except ValueError:
        return ["QA health: lint pass W state file is unreadable"]
    age = (ref - last).days
    if age > QA_HEALTH_STALE_DAYS:
        return [f"QA health: lint pass W has not run for {age} days (last {state.get('last_run')})"]
    if abs(age) > QA_HEALTH_MAX_AGE_DAYS:
        return []
    out = []
    for f in state.get("findings") or []:
        try:
            out.append(f"QA health: {f['metric']} at {f['value']} against {f['threshold']} (lint pass W, {state.get('last_run')})")
        except (KeyError, TypeError):
            continue
    return out


def aggregate_for_date(date_str):
    """Aggregate governance-log for the given YYYY-MM-DD. Returns dict."""
    sessions = set()
    classifications = 0
    quick_count = 0
    non_quick_count = 0
    classifier_blocks = 0
    qa_fails = 0
    agent_warns = 0
    agent_dispatches = 0

    if not os.path.exists(LOG_PATH):
        return None

    with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = e.get("ts", "")
            if not ts_str.startswith(date_str):
                continue
            if is_test(e.get("session")):
                continue
            if e.get("environment", "prod") != "prod":
                continue

            sid = e.get("session")
            if sid:
                sessions.add(sid)

            evt = e.get("event")

            # Classifications: explicit event 1 OR legacy implicit (type + no event)
            if evt == "classification_emitted":
                classifications += 1
                t = (e.get("type") or "").lower()
                if t == "quick":
                    quick_count += 1
                elif t:
                    non_quick_count += 1
            elif not evt and e.get("type"):  # legacy row
                classifications += 1
                t = (e.get("type") or "").lower()
                if t == "quick":
                    quick_count += 1
                elif t:
                    non_quick_count += 1

            if evt == "classifier_field_missing" or (evt == "block" and e.get("hook") == "classifier-field-check"):
                classifier_blocks += 1
            if evt == "qa_fail_reported":
                qa_fails += (e.get("fail_count") or 1)
            if evt == "agent_dispatched":
                agent_dispatches += 1
                if e.get("warn_downgrade"):
                    agent_warns += 1
            elif evt == "warn" and e.get("hook") == "agent-dispatch-check":
                agent_warns += 1

    total_class = quick_count + non_quick_count
    quick_ratio = (quick_count / total_class) if total_class else 0.0

    alerts = []
    if classifier_blocks >= 1:
        alerts.append(f"{classifier_blocks} classifier block(s) today")
    if qa_fails >= 1:
        alerts.append(f"{qa_fails} QA FAIL claim(s) today")
    if agent_warns >= 3:
        alerts.append(f"{agent_warns} off-contract agent dispatch warning(s) today")
    if quick_ratio > 0.95 and total_class >= 10:
        alerts.append(f"Quick-only share is {round(quick_ratio*100)}% (classifier lax?)")
    alerts.extend(qa_health_alerts(date_str))

    return {
        "date": date_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sessions": len(sessions),
        "classifications": classifications,
        "quick_count": quick_count,
        "non_quick_count": non_quick_count,
        "quick_ratio": round(quick_ratio, 3),
        "classifier_blocks": classifier_blocks,
        "qa_fails": qa_fails,
        "agent_warn_downgrades": agent_warns,
        "agent_dispatches": agent_dispatches,
        "alerts": alerts,
    }


def write_aggregate(date_str=None):
    """Build and persist the aggregate for date_str (default: today)."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    agg = aggregate_for_date(date_str)
    if agg is None:
        return None
    os.makedirs(AGG_DIR, exist_ok=True)
    out_path = os.path.join(AGG_DIR, f"{date_str}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(agg, f, indent=2)
    except Exception:
        return agg  # even if write fails, return the data
    return agg


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = write_aggregate(date_arg)
    print(json.dumps(result, indent=2) if result else "{}")
