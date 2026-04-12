"""
Session Start Logger - SessionStart Hook Helper
P1-B (2026-04-09): Writes a session_start event to governance-log.jsonl so
analytics scripts can detect session boundaries cleanly (instead of inferring
from first classification entry).

Input: stdin with CC hook payload JSON (contains session_id, source, transcript_path)
Output: None (append-only write to governance-log.jsonl)
Does NOT block — logging only. Errors silently swallowed to avoid breaking session start.
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

        entry = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schema": 2,
            "event": "session_start",
            "hook": "session-start-log",
            "session": session_id,
            "source": source,
        }

        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never break session start


if __name__ == "__main__":
    main()
