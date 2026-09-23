"""
MON-V2-1 — Temporary SessionEnd Empirical Probe

Question answered: Does the SessionEnd hook fire on this machine, what fields
does its stdin payload contain, and is the transcript file path present and readable?

This is NOT a collector. Remove this file once the vehicle decision for MON-V2
(SessionEnd-based vs Stop-based collection) has been made.

Added: 2026-05-22
"""

import sys
import json
import os
from datetime import datetime, timezone


_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_state")
_PROBE_LOG = os.path.join(_STATE_DIR, "sessionend-probe.jsonl")

# Keys whose values must never appear in probe records verbatim.
_REDACT_SUBSTRINGS = ("key", "token", "secret", "password")


def _is_sensitive_key(key_name):
    lower = key_name.lower()
    return any(s in lower for s in _REDACT_SUBSTRINGS)


def _truncate(value, limit=500):
    """Return value with long strings capped at `limit` chars."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "...[truncated]"
    return value


def _sanitize_value(v):
    """Recursively sanitize a value: truncate long strings, recurse into
    dicts/lists. Sensitive-key redaction happens in the dict branch."""
    if isinstance(v, str):
        return _truncate(v)
    if isinstance(v, dict):
        out = {}
        for k, sub in v.items():
            if _is_sensitive_key(k):
                out[k] = "[redacted]"
            else:
                out[k] = _sanitize_value(sub)
        return out
    if isinstance(v, list):
        return [_sanitize_value(item) for item in v]
    return v


def _sanitize_payload(payload):
    """
    Return a copy of payload with sensitive key values replaced by
    "[redacted]" and string values longer than 500 chars truncated, at
    every nesting depth (dicts and lists are recursed).
    """
    return _sanitize_value(payload)


def _probe_transcript(payload):
    """
    Check for a transcript path in the payload.
    Returns (field_name_or_null, found_bool, readable_bool, size_or_null).
    """
    transcript_field = None
    for candidate in ("transcript_path", "transcript", "transcriptPath"):
        if candidate in payload:
            transcript_field = candidate
            break

    if transcript_field is None:
        return None, False, False, None

    path = payload[transcript_field]
    if not isinstance(path, str) or not path:
        return transcript_field, False, False, None

    found = os.path.isfile(path)
    if not found:
        return transcript_field, False, False, None

    # Try reading 1 byte
    readable = False
    size = None
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            fh.read(1)
        readable = True
    except Exception:
        pass

    return transcript_field, found, readable, size


def main():
    record = {}

    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        record["ts"] = ts

        # --- Read stdin ---
        try:
            raw = sys.stdin.read()
        except Exception as exc:
            raw = ""
            record["stdin_error"] = str(exc)

        # --- Parse payload ---
        payload = None
        parse_error = None
        if not raw.strip():
            record["payload_keys"] = []
            record["payload_sample"] = None
            record["stdin_empty"] = True
        else:
            try:
                payload = json.loads(raw)
                record["stdin_empty"] = False
            except json.JSONDecodeError as exc:
                parse_error = str(exc)
                record["stdin_empty"] = False
                record["parse_error"] = parse_error
                record["payload_keys"] = []
                record["payload_sample"] = None

        if payload is not None:
            record["payload_keys"] = sorted(payload.keys())
            record["payload_sample"] = _sanitize_payload(payload)

        # --- Transcript probe ---
        if payload is not None:
            t_field, t_found, t_readable, t_size = _probe_transcript(payload)
        else:
            t_field, t_found, t_readable, t_size = None, False, False, None

        record["transcript_path_field"] = t_field
        record["transcript_found"] = t_found
        record["transcript_readable"] = t_readable
        record["transcript_size_bytes"] = t_size

        # --- Reason field (if CC supplies it) ---
        if payload is not None:
            for candidate in ("reason", "source"):
                if candidate in payload:
                    record["reason"] = _truncate(payload[candidate])
                    break

        # --- Write probe record ---
        try:
            os.makedirs(_STATE_DIR, exist_ok=True)
            with open(_PROBE_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:
            pass  # Swallow silently — never break session teardown

    except Exception:
        # Total failure — still exit 0, still attempt minimal write
        try:
            fallback = json.dumps({"ts": "unknown", "total_failure": True}) + "\n"
            with open(_PROBE_LOG, "a", encoding="utf-8") as fh:
                fh.write(fallback)
        except Exception:
            pass

    # CC hook contract: stdout must be valid JSON (or empty).
    print("{}")
    sys.exit(0)


if __name__ == "__main__":
    main()
