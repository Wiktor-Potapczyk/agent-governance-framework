"""Where the current turn starts in a Claude Code transcript, and how to read it.

Written 2026-09-21 for harness audit 1 ([[2026-09-21-dispatch-and-work-verification-evaluation]]).
work-verification-check.py took "the last user entry with a text block" as the start
of the turn. Two kinds of user entry that are not the user split the turn:

- the skill body that Claude Code appends after a Skill call (a user entry with a
  text block, `isMeta: true` and a `sourceToolUseID`), so on the Skill path the
  classification, the Skill call and every earlier tool fell outside the turn and a
  QA report with zero tools passed;
- the feedback a Stop hook prints on a block (a user entry whose text starts with
  `Stop hook feedback:`), so a retry was a fresh turn with no classification and no
  tools, and re-posting the blocked report passed.

`real_turn_start(lines)` returns the index of the last user entry that is the user:
string content, or a list with a text block, and none of the shapes above. Entries
that are only tool_result wrappers never count. Returns -1 when there is none.

`tail_to_turn_start(path)` reads the transcript's tail in growing steps until that
boundary is inside the text, capped at TAIL_CAP_BYTES. The fixed 200 KB tail the
gates used could not see a turn behind one large tool result (137 lines over
200 KB in the three newest transcripts, silent-failure review item 1).
"""
import json
import os

HOOK_FEEDBACK_PREFIX = "Stop hook feedback:"
TAIL_START_BYTES = 204800
TAIL_CAP_BYTES = 8 * 1024 * 1024


def _entry(line):
    line = line.strip()
    if not line:
        return None
    try:
        e = json.loads(line)
    except (json.JSONDecodeError, TypeError):
        return None
    return e if isinstance(e, dict) else None


def user_entry_kind(entry):
    """'user' for a real user message; otherwise the reason it is not one:
    'not-user', 'tool-result', 'skill-body', 'hook-feedback', 'empty'."""
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return "not-user"
    if entry.get("isMeta") or entry.get("sourceToolUseID"):
        return "skill-body"
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        blocks = [b for b in content if isinstance(b, dict)]
        if blocks and all(b.get("type") == "tool_result" for b in blocks):
            return "tool-result"
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        if not texts:
            return "empty"
        text = "\n".join(str(t) for t in texts)
    else:
        return "empty"
    if text.lstrip().startswith(HOOK_FEEDBACK_PREFIX):
        return "hook-feedback"
    return "user"


def real_turn_start(lines):
    """Index into `lines` of the last real user entry, or -1."""
    for i in range(len(lines) - 1, -1, -1):
        e = _entry(lines[i])
        if e is None:
            continue
        if user_entry_kind(e) == "user":
            return i
    return -1


def boundary_kind(lines):
    """What the naive rule (last user entry with text or string content) would have
    chosen, for telemetry: 'user', 'skill-body' or 'hook-feedback'."""
    for i in range(len(lines) - 1, -1, -1):
        e = _entry(lines[i])
        if e is None:
            continue
        k = user_entry_kind(e)
        if k in ("user", "skill-body", "hook-feedback"):
            return k
    return "none"


def tail_to_turn_start(path, start_bytes=TAIL_START_BYTES, cap_bytes=TAIL_CAP_BYTES):
    """Read the transcript tail, growing it until the real user boundary is inside.

    Returns (lines, info) where info = {"window_bytes": n, "file_size": s,
    "capped": bool, "turn_start": idx}. `turn_start` is -1 when no real user
    entry was found within the cap; callers then fall back to their old rule.
    The first line of a window that starts mid-file is a fragment and is never a
    valid JSON entry, so it is dropped."""
    file_size = os.path.getsize(path)
    window = min(start_bytes, file_size)
    while True:
        with open(path, "rb") as fh:
            fh.seek(max(0, file_size - window))
            raw = fh.read()
        text = raw.decode("utf-8", errors="replace")
        lines = text.split("\n")
        if window < file_size and lines:
            lines = lines[1:]
        idx = real_turn_start(lines)
        capped = window >= cap_bytes
        if idx >= 0 or window >= file_size or capped:
            return lines, {"window_bytes": window, "file_size": file_size, "capped": capped and idx < 0, "turn_start": idx}
        window = min(window * 4, cap_bytes, file_size)
