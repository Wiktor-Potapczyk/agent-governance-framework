"""
Token Breakdown - Stop Hook
Aggregates token usage for the current turn: main session + per-subagent breakdown.
Emits a single 'token_breakdown' event to governance-log.jsonl via _event_emit.py.
Does NOT block — telemetry only.

Schema v2 event fields (extra dict passed to emit_event):
  turn_total_tokens           int   — RAW sum of all four token fields (input+output+cache_read+cache_creation)
                                       plus subagent totalTokens. Fields are non-overlapping per Anthropic API
                                       (input_tokens is fresh-only, cache_read_input_tokens is separate),
                                       so this is a workload-size proxy — NOT equivalent to billable cost
                                       (cache-read tokens are priced differently).
  main_session                dict  — aggregated message.usage across all assistant entries in turn
  by_subagent                 list  — one entry per Agent tool call, resolved from toolUseResult.usage.
                                       Entries with no matching Agent dispatch in the current turn are SKIPPED
                                       (prevents cross-turn attribution pollution).
  tool_calls                  dict  — {tool_name: count} for every tool_use block this turn
  skill_names                 list  — (only if Skill calls > 0) list of invoked skill names
"""

import sys
import json
import os
import traceback
from datetime import datetime
from collections import defaultdict

# ---------------------------------------------------------------------------
# Shared event-emit helper (observability v2)
# ---------------------------------------------------------------------------
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _event_emit import emit_event  # type: ignore
except Exception:
    emit_event = None  # type: ignore

# Read last 200 KB — same window as other Stop hooks
READ_BYTES = 204800

LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "token-breakdown.log",
)

GOVERNANCE_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "governance-log.jsonl",
)


def _log_error(msg: str) -> None:
    """Write timestamped error + traceback to token-breakdown.log. Silent on failure."""
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
            f.write(traceback.format_exc())
            f.write("\n")
    except Exception:
        pass


def _safe_int(val) -> int:
    """Return int(val) or 0 on any error."""
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _latest_classification_type(session_id: str) -> str | None:
    """Return the most recent classification_emitted.type for this session, or None.

    Scans governance-log.jsonl for classification_emitted events matching the session.
    Returns the last (most recent) type field found, or None if:
    - session_id is empty/falsy
    - no matching events exist
    - file does not exist
    - any IO error occurs (silently caught)
    """
    if not session_id:
        return None

    try:
        with open(GOVERNANCE_LOG_PATH, "r", encoding="utf-8") as f:
            latest = None
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("event") == "classification_emitted" and r.get("session") == session_id:
                        latest = r.get("type")  # most recent wins (last line iterated)
                except (json.JSONDecodeError, ValueError):
                    # Skip malformed lines
                    continue
            return latest
    except FileNotFoundError:
        return None
    except Exception:
        # Silent on any unexpected IO error; don't break token_breakdown emission
        return None


def aggregate_turn(lines: list) -> dict:
    """
    Parse JSONL lines into a token breakdown for the current turn.

    Turn boundary: reverse-scan to find the first non-tool_result user entry.
    Everything from that index onward is 'this turn'.

    Two-pass within the turn slice:
      Pass 1 — assistant entries: build agent_map {tool_use_id -> subagent_type},
               accumulate main_session usage, count tool calls.
      Pass 2 — user entries: match toolUseResult to agent_map via tool_use_id found
               in message.content[0] (first tool_result block's tool_use_id).
    """
    # ------------------------------------------------------------------
    # Step 1: parse all non-empty lines into entry objects
    # ------------------------------------------------------------------
    entries = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entries.append(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            continue

    # ------------------------------------------------------------------
    # Step 2: find turn boundary (reverse scan for first non-tool_result user entry)
    # ------------------------------------------------------------------
    turn_start_idx = 0
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if entry.get("type") != "user":
            continue
        # Check if this user entry is NOT a pure tool_result entry
        msg = entry.get("message", {})
        content = msg.get("content", [])
        if not content:
            turn_start_idx = i
            break
        # A tool_result user entry has ALL blocks of type "tool_result"
        is_all_tool_result = all(
            isinstance(b, dict) and b.get("type") == "tool_result"
            for b in content
        )
        if not is_all_tool_result:
            turn_start_idx = i
            break

    turn_entries = entries[turn_start_idx:]

    # ------------------------------------------------------------------
    # Step 3: Pass 1 — scan assistant entries in the turn slice
    # ------------------------------------------------------------------
    agent_map: dict = {}           # tool_use_id -> subagent_type
    main_session = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    tool_calls: dict = defaultdict(int)
    skill_names: list = []

    for entry in turn_entries:
        if entry.get("type") != "assistant":
            continue
        msg = entry.get("message", {})

        # Accumulate message.usage (present on every assistant entry)
        usage = msg.get("usage") or {}
        main_session["input_tokens"] += _safe_int(usage.get("input_tokens", 0))
        main_session["output_tokens"] += _safe_int(usage.get("output_tokens", 0))
        main_session["cache_read_input_tokens"] += _safe_int(
            usage.get("cache_read_input_tokens", 0)
        )
        main_session["cache_creation_input_tokens"] += _safe_int(
            usage.get("cache_creation_input_tokens", 0)
        )

        # Scan tool_use blocks
        for block in msg.get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue

            name = block.get("name", "")
            tool_calls[name] += 1

            inp = block.get("input", {})
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except (json.JSONDecodeError, TypeError):
                    inp = {}

            if name == "Agent":
                # Record tool_use_id -> subagent_type for later resolution
                tool_use_id = block.get("id") or block.get("tool_use_id")
                subagent_type = (
                    inp.get("subagent_type")
                    or inp.get("description")
                    or "unknown"
                )
                if tool_use_id:
                    agent_map[tool_use_id] = subagent_type

            elif name == "Skill":
                skill = inp.get("skill") or "unknown"
                skill_names.append(skill)

    # ------------------------------------------------------------------
    # Step 4: Pass 2 — scan user entries for toolUseResult
    # ------------------------------------------------------------------
    by_subagent: list = []

    for entry in turn_entries:
        if entry.get("type") != "user":
            continue

        # toolUseResult is a top-level key on the JSONL line object
        tool_use_result = entry.get("toolUseResult")
        if not tool_use_result or not isinstance(tool_use_result, dict):
            continue

        result_usage = tool_use_result.get("usage")
        if not result_usage or not isinstance(result_usage, dict):
            continue

        # Resolve subagent_type from the first tool_result block's tool_use_id
        msg = entry.get("message", {})
        content = msg.get("content", [])
        matched_tool_use_id = None
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                matched_tool_use_id = block.get("tool_use_id")
                break  # Take first block only (RISK-P2-B)

        # Skip entries whose tool_use_id doesn't map to an Agent dispatch in this turn.
        # This can happen when an Agent dispatched in a prior turn returns in this turn —
        # attributing those tokens to the current turn with subagent_type="unknown" would
        # pollute by_subagent. Better to lose the data point than corrupt attribution.
        if matched_tool_use_id is None or matched_tool_use_id not in agent_map:
            continue
        subagent_type = agent_map[matched_tool_use_id]

        by_subagent.append({
            "subagent_type": subagent_type,
            "input_tokens": _safe_int(result_usage.get("input_tokens", 0)),
            "output_tokens": _safe_int(result_usage.get("output_tokens", 0)),
            "cache_read_input_tokens": _safe_int(
                result_usage.get("cache_read_input_tokens", 0)
            ),
            "cache_creation_input_tokens": _safe_int(
                result_usage.get("cache_creation_input_tokens", 0)
            ),
            "totalTokens": _safe_int(
                tool_use_result.get("totalTokens", 0)
            ),
        })

    # ------------------------------------------------------------------
    # Step 5: compute turn_total_tokens
    # ------------------------------------------------------------------
    turn_total = (
        main_session["input_tokens"]
        + main_session["output_tokens"]
        + main_session["cache_read_input_tokens"]
        + main_session["cache_creation_input_tokens"]
    )
    for agent in by_subagent:
        turn_total += agent.get("totalTokens", 0)

    return {
        "turn_total_tokens": turn_total,
        "main_session": main_session,
        "by_subagent": by_subagent,
        "tool_calls": dict(tool_calls),
        "skill_names": skill_names,
    }


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # Don't run during stop-hook-active retries
    if payload.get("stop_hook_active"):
        return

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    # Extract session_id from transcript filename (same pattern as governance-log.py)
    session_id = os.path.splitext(os.path.basename(transcript_path))[0]

    # Read last 200 KB of transcript
    try:
        file_size = os.path.getsize(transcript_path)
        read_bytes = min(READ_BYTES, file_size)
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(max(0, file_size - read_bytes))
            tail = f.read()
    except OSError:
        return

    lines = tail.split("\n")

    # ------------------------------------------------------------------
    # Aggregation — wrapped in try/except per spec; log on exception
    # ------------------------------------------------------------------
    try:
        result = aggregate_turn(lines)
    except Exception:
        _log_error("aggregate_turn raised an exception")
        return

    # Skip emission if all zeros and no subagents
    ms = result["main_session"]
    all_zero = (
        ms["input_tokens"] == 0
        and ms["output_tokens"] == 0
        and ms["cache_read_input_tokens"] == 0
        and ms["cache_creation_input_tokens"] == 0
        and result["turn_total_tokens"] == 0
    )
    if all_zero and not result["by_subagent"]:
        return

    # Build extra dict — omit skill_names if no Skill calls
    extra = {
        "turn_total_tokens": result["turn_total_tokens"],
        "main_session": result["main_session"],
        "by_subagent": result["by_subagent"],
        "tool_calls": result["tool_calls"],
    }
    if result["skill_names"]:
        extra["skill_names"] = result["skill_names"]

    # Add task_type from most recent classification_emitted event for this session
    extra["task_type"] = _latest_classification_type(session_id)

    if emit_event is not None:
        emit_event(
            event="token_breakdown",
            hook="token-breakdown",
            session=session_id,
            extra=extra,
        )


if __name__ == "__main__":
    main()
