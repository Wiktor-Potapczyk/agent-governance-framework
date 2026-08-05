"""
Session Start Logger - SessionStart Hook Helper
P1-B (2026-04-09): Writes a session_start event to governance-log.jsonl so
analytics scripts can detect session boundaries cleanly (instead of inferring
from first classification entry).

Input: stdin with CC hook payload JSON (contains session_id, source, transcript_path)
Output: None (append-only write to governance-log.jsonl)
Does NOT block: logging only. Errors silently swallowed to avoid breaking session start.
"""

import sys
import json
import os
from datetime import datetime


LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "governance-log.jsonl"
)


def main():
    try:
        payload_text = sys.stdin.read()
        if not payload_text:
            return

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return

        # Extract session_id from payload or transcript_path
        session_id = payload.get("session_id") or ""
        transcript_path = payload.get("transcript_path") or ""
        if not session_id and transcript_path:
            session_id = os.path.splitext(os.path.basename(transcript_path))[0]
        if not session_id:
            session_id = "unknown"

        source = payload.get("source", "unknown")  # startup, resume, clear, compact

        # Observability v2: add environment field (detect test via env var)
        env = os.environ.get("OBSERVABILITY_ENV", "").strip().lower()
        environment = "test" if env == "test" else "prod"

        from _event_emit import emit_event
        emit_event(
            event="session_start",
            hook="session-start-log",
            session=session_id,
            environment=environment,
            extra={"source": source},
        )

        # Observability v2: dashboard summary: refresh yesterday's aggregate
        # (today's hasn't accumulated yet) and emit dashboard_alert event if any
        # threshold tripped. Never blocks session start.
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _daily_aggregate import write_aggregate  # type: ignore
            from datetime import timedelta
            # Test override: DASHBOARD_TARGET_DATE env var (YYYY-MM-DD) forces
            # aggregation for a specific historical date. Default: yesterday.
            yday = os.environ.get("DASHBOARD_TARGET_DATE") or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            agg = write_aggregate(yday)
            if agg and agg.get("alerts"):
                emit_event(
                    event="dashboard_alert",
                    hook="session-start-log",
                    session=session_id,
                    environment=environment,
                    extra={
                        "aggregate_date": yday,
                        "alerts": agg.get("alerts", []),
                        "sessions": agg.get("sessions", 0),
                        "qa_fails": agg.get("qa_fails", 0),
                        "classifier_blocks": agg.get("classifier_blocks", 0),
                        "agent_warns": agg.get("agent_warn_downgrades", 0),
                    },
                )
                # Also emit a one-liner to stderr so it surfaces in hook log
                # viewers without polluting stdout (PENTEST-FIX-1, 2026-05-06):
                # CC hook contract requires stdout to contain ONLY the JSON
                # hookSpecificOutput block: any trailing stdout content
                # breaks strict JSON parsers with "Extra data" error. The
                # dashboard_alert event above is the canonical record;
                # stderr is for human-visible surfacing only.
                print(f"DASHBOARD ({yday}): {' | '.join(agg['alerts'])}", file=sys.stderr)
        except Exception:
            pass  # dashboard is best-effort
    except Exception:
        pass  # Never break session start


if __name__ == "__main__":
    main()
