"""
Read-Before-Edit Check - Stop Hook (instrumentation layer)

Owner note (SA-1 closure, 2026-05-25): "edit their system prompts to
not edit existing files i guess. then we could use a stop hook to first read a
file before editing it or something like this."

NOTE on redundancy with built-in Claude Code enforcement:
Edit tool spec requires prior Read of the same file in the conversation. Write
tool spec requires prior Read if the path exists. So in normal usage, Edit/Write
without prior Read errors at the tool layer before reaching this hook. THIS hook
is therefore INSTRUMENTATION: it emits governance-log entries documenting any
Edit-without-Read patterns that escape the tool layer (edge cases: MultiEdit,
tool errors retried, sub-agent transcripts with different context boundary).

Behavior:
- Walks last assistant turn (after the last user message).
- For each Edit/MultiEdit tool_use, captures file_path from input.
- Checks whether a Read tool_use with the same file_path appeared earlier in the
  same turn.
- On miss: emits governance-log entry (event="edit_without_read") and prints
  WARN to stderr. Does NOT block: built-in enforcement is the behavioral gate.
- Exit code always 0.

Reviewer-scope-violation-check (REV-2b: separate hook to be built later) is the
real prevention layer for reviewer-tampering. This hook is the visibility layer
for blind-edit instrumentation.
"""

import sys
import json
import os

READ_BYTES = 204800  # 200KB window: matches other hardened hooks

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _event_emit import emit_event  # type: ignore
except Exception:
    emit_event = None  # type: ignore


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

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)

    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    lines = tail.split("\n")

    # Walk backwards to find last user message
    last_user_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        line = lines[i].strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if entry.get("type") == "user":
                last_user_idx = i
                break
        except json.JSONDecodeError:
            continue

    if last_user_idx < 0:
        return

    # Collect tool_use blocks in order: Read paths (with timestamps), Edit/MultiEdit attempts.
    read_paths = set()
    edits_without_read = []  # list of (tool_name, file_path)

    for i in range(last_user_idx + 1, len(lines)):
        line = lines[i].strip()
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
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input", {})
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except (json.JSONDecodeError, TypeError):
                    inp = {}

            if name == "Read":
                p = inp.get("file_path")
                if p:
                    read_paths.add(p)
            elif name in ("Edit", "MultiEdit"):
                p = inp.get("file_path")
                if p and p not in read_paths:
                    edits_without_read.append((name, p))

    # Emit governance + warn (non-blocking)
    if edits_without_read:
        session_id = (
            os.path.splitext(os.path.basename(transcript_path))[0]
            if transcript_path else "unknown"
        )
        for tool, path in edits_without_read:
            if emit_event is not None:
                try:
                    emit_event(
                        event="edit_without_read",
                        hook="read-before-edit-check",
                        session=session_id,
                        extra={"tool": tool, "file_path": path},
                    )
                except Exception:
                    pass
            print(
                f"WARN: {tool} on {path} without prior Read in this turn. "
                f"Built-in tool spec requires Read first; this hook logged the event "
                f"as instrumentation (governance-log).",
                file=sys.stderr,
            )

    return  # exit 0


if __name__ == "__main__":
    main()
