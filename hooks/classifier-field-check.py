"""
Classifier Field Check - Stop Hook
Verifies that all mandatory classifier fields are present in the response.
Block: JSON { "decision": "block" } on stdout if fields are missing.

Regex hardening (2026-03-22):
- 200KB window (up from 80KB) to capture large agent outputs
- Fence stripping: ignores content inside ``` blocks (prevents false matches on docs/examples)
- Case-insensitive field detection
"""

import sys
import json
import os
import re

# 200KB window: covers even 10+ agent outputs per turn
READ_BYTES = 204800

# Observability v2: shared event-emit helper (silent on import failure)
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _event_emit import emit_event  # type: ignore
except Exception:  # pragma: no cover
    emit_event = None  # type: ignore


def strip_fences(text):
    """Remove markdown fenced code blocks to prevent false matches on examples/docs."""
    return re.sub(r'```[\s\S]*?```', '', text)


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    if payload.get("stop_hook_active"):
        return

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("classifier-field-check")
    except Exception:
        pass

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    # Read last 200KB
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    # Find the last assistant text block that contains TASK TYPE
    lines = tail.split("\n")
    last_classifier_text = None

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue
        message = entry.get("message", {})
        for block in message.get("content", []):
            if block.get("type") == "text":
                btext = block.get("text", "")
                # Strip fenced code blocks to avoid matching examples/docs
                clean = strip_fences(btext)
                # Only match real classifications with valid type names (case-insensitive)
                if re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*(?:Quick|Research|Analysis|Content|Build|Planning|Compound)', clean, re.IGNORECASE):
                    last_classifier_text = clean

    if not last_classifier_text:
        return

    # Check if it's Quick (case-insensitive)
    is_quick = bool(re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*Quick', last_classifier_text, re.IGNORECASE))

    # Check required fields (case-insensitive)
    has_implies = bool(re.search(r'IMPLIES:', last_classifier_text, re.IGNORECASE))
    has_type = bool(re.search(r'(?:TASK TYPE|CLASSIFICATION):', last_classifier_text, re.IGNORECASE))
    has_approach = bool(re.search(r'APPROACH:', last_classifier_text, re.IGNORECASE))
    has_missed = bool(re.search(r'MISSED:', last_classifier_text, re.IGNORECASE))
    has_must_dispatch = bool(re.search(r'MUST DISPATCH:', last_classifier_text, re.IGNORECASE))

    missing = []
    if not has_implies:
        missing.append("IMPLIES")
    if not has_type:
        missing.append("TASK TYPE")

    if not is_quick:
        if not has_approach:
            missing.append("APPROACH")
        if not has_missed:
            missing.append("MISSED")
        if not has_must_dispatch:
            missing.append("MUST DISPATCH")

    # --- PM enforcement (every non-Quick task) ---
    if not is_quick and has_must_dispatch and not missing:
        dispatch_match = re.search(r'MUST DISPATCH:\s*(.+)', last_classifier_text, re.IGNORECASE)
        if dispatch_match:
            dispatch_text = dispatch_match.group(1).lower()
            if not re.search(r'\bpm\b', dispatch_text):
                missing.append("pm in MUST DISPATCH (every non-Quick task requires PM oversight)")

    # --- Observability v2: event 1 classification_emitted (every classification, Quick or not) ---
    if emit_event is not None:
        session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
        type_match = re.search(r'(?:TASK TYPE|CLASSIFICATION):\s*(Quick|Research|Analysis|Content|Build|Planning|Compound)', last_classifier_text, re.IGNORECASE)
        domain_match = re.search(r'DOMAIN:\s*([^\n]+)', last_classifier_text, re.IGNORECASE)
        implies_match = re.search(r'IMPLIES:\s*([^\n]+)', last_classifier_text, re.IGNORECASE)
        approach_match = re.search(r'APPROACH:\s*([^\n]+)', last_classifier_text, re.IGNORECASE)
        missed_match = re.search(r'MISSED:\s*([^\n]+)', last_classifier_text, re.IGNORECASE)
        must_dispatch_match_e = re.search(r'MUST DISPATCH:\s*([^\n]+)', last_classifier_text, re.IGNORECASE)
        emit_event(
            event="classification_emitted",
            hook="classifier-field-check",
            session=session_id,
            extra={
                "type": type_match.group(1) if type_match else None,
                "is_quick": is_quick,
                "implies": (implies_match.group(1).strip()[:200] if implies_match else None),
                "domain": (domain_match.group(1).strip()[:100] if domain_match else None),
                "approach": (approach_match.group(1).strip()[:200] if approach_match else None),
                "missed": (missed_match.group(1).strip()[:200] if missed_match else None),
                "must_dispatch_raw": (must_dispatch_match_e.group(1).strip()[:300] if must_dispatch_match_e else None),
                "missing_fields": missing,
                "complete": len(missing) == 0,
            },
        )

    if missing:
        reason = f"INCOMPLETE CLASSIFICATION: Missing fields: {', '.join(missing)}. All classifier fields are mandatory. Re-classify with all fields before proceeding."
        block_json = json.dumps({"decision": "block", "reason": reason})
        print(block_json)
        # Observability v2: emit event 2 classifier_field_missing (replaces legacy "block" emit).
        session_id = os.path.splitext(os.path.basename(transcript_path))[0] if transcript_path else "unknown"
        if emit_event is not None:
            emit_event(
                event="classifier_field_missing",
                hook="classifier-field-check",
                session=session_id,
                extra={
                    "missing": missing,
                    "is_quick": is_quick,
                    "decision": "block",
                },
            )
        else:
            # Fallback: preserve legacy emit shape if helper unavailable.
            try:
                from datetime import datetime
                log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")
                entry = json.dumps({"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "event": "classifier_field_missing", "hook": "classifier-field-check", "session": session_id, "missing": missing, "schema": 2, "environment": "prod"})
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(entry + "\n")
            except Exception:
                pass


if __name__ == "__main__":
    main()
