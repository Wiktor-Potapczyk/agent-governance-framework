#!/usr/bin/env python3
"""Stop hook: detect idle-wait verdicts and block them when reversible task_plan items exist.

Purpose
-------
Wiktor 2026-05-11: "we need to find a way to make you REMEMBER to be proactive."

The pattern this catches: assistant ends a turn with STAND-DOWN / awaiting Wiktor /
surface to Wiktor / PM CHECKPOINT Next: STAND-DOWN, while reversible (not Wiktor-gated)
task_plan items exist.

The override conditions (when STAND-DOWN is legitimate):
- All open task_plan items across active projects carry explicit Wiktor-gate markers
- The session is at a compaction boundary (no way to know from Stop payload — covered
  by the user explicitly invoking /save or /compact, both of which produce different
  assistant text patterns)
- The user explicitly directed "stop" / "stand down" / "wait" in the current turn
  (heuristic: assistant says "per request" / "per directive" / "as you asked" near
  an idle marker)

Implementation
--------------
- Reads the Stop hook stdin payload to find transcript_path
- Parses last few assistant text blocks for idle-wait markers
- Scans Projects/*/task_plan.md for `- [ ] ...` lines lacking Wiktor-gate markers
- If idle-marker present AND reversible items exist AND no user-stop-directive
  near the idle marker -> emit {"decision":"block", "reason": <list>}

Failure mode tolerance
----------------------
Hook errors out silently (exit 0) on any unexpected condition. Better to let the
turn complete than to block on hook bugs.
"""

import json
import os
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
PROJECTS = VAULT / "Projects"

# Phrases that signal idle-wait in assistant output
IDLE_MARKERS = [
    r"\bSTAND[- ]?DOWN\b",
    r"\bawaiting\s+(Wiktor|ratification|approval|input)\b",
    r"\bblocked\s+on\s+Wiktor\b",
    r"\bsurface\s+to\s+Wiktor\b",
    r"\bpending\s+Wiktor\s+(input|approval|ratification|decision|review)\b",
    r"Next\s*[:\-]\s*STAND[- ]?DOWN",
    r"\bWiktor\s+decides\s+whether\b",
    r"\bidle[- ]wait\b",
    r"\bawaiting\s+ratification\b",
    r"\bStanding\s+by\b\.?",  # "Standing by" idle-wait sign-off (any position)
]

# Markers inside a task_plan.md line that mean "this is legitimately Wiktor-gated"
WIKTOR_GATE_MARKERS = [
    r"Wiktor\s+ratifies",
    r"Wiktor\s+approves",
    r"Wiktor\s+decides?",            # decide / decides
    r"Wiktor\s+reviews?",            # review / reviews
    r"Wiktor\s+input",
    r"Wiktor\s+gate",
    r"Wiktor\s+confirmation",
    r"Wiktor\s+provides?",           # project notes often use "Wiktor: provide"
    r"Wiktor\s+upload",
    r"\bWiktor\s*:",                 # assignee form ("Wiktor: do X")
    r"\bWiktor\s*\(",                # parenthesized-qualifier assignee form ("Wiktor (Phase 6):", "**Wiktor (quick verify):**")
    r"awaiting\s+Wiktor",
    r"pending\s+Wiktor",
    r"YES\s*[—\-]\s*Wiktor",
    r"#pending[-_]wiktor",
    r"#wiktor[-_]gate",
    r"\(no\s+action\s+(required|needed)\b",  # explicitly self-marked as non-actionable
    # --- Boundary tests (GOV-3, 2026-05-31): items that are open but NOT
    # autonomously executable — blocked on external state, not on a Wiktor
    # ratification decision. Without these, an autonomous loop nags to "execute"
    # a his-machine test or an install it physically cannot run. Conservative,
    # specific patterns to keep false-positive suppression low.
    r"verify[\s-]before[\s-]adopt",
    r"\b(his|Wiktor'?s|vault)\s+machine\b",   # empirical test on Wiktor's hardware
    r"WDAC\s+(test|whitelist)",
    r"#parked\b",
    r"requires?\s+(install|installation|a\s+plugin\s+install)",  # install = conscious decision, not autonomous
    r"\bhis[\s-]machine\b",
]

# Heuristic: if the assistant text near an idle marker contains these, the user
# explicitly directed the stop and idle-wait is legitimate.
USER_STOP_PROXIMITY = [
    r"per\s+(your\s+)?request",
    r"per\s+(your\s+)?directive",
    r"as\s+(you\s+)?asked",
    r"as\s+(you\s+)?requested",
    r"as\s+directed",
    r"you\s+(said|told\s+me|asked\s+me)\s+to\s+(stop|wait|stand[- ]?down)",
]


def read_last_assistant_text(transcript_path: str) -> str:
    """Return text from the most recent assistant TURN only.

    A turn is bounded by user messages. Read the transcript backwards, collect
    assistant text blocks, stop at the first user message. This prevents the
    hook from firing on idle markers in prior turns' assistant output (e.g.,
    educational text or Edit tool inputs that mention the trigger words).
    """
    p = Path(transcript_path)
    if not p.exists():
        return ""
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    text_blocks = []
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        t = obj.get("type")
        if t == "user":
            break
        if t != "assistant":
            continue
        content = obj.get("message", {}).get("content", [])
        if not isinstance(content, list):
            continue
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                txt = c.get("text", "")
                if txt:
                    text_blocks.append(txt)
    return "\n".join(reversed(text_blocks))


def find_idle_marker(text: str):
    """Return (match_object, marker_pattern) of the first idle marker, or (None, None)."""
    for pat in IDLE_MARKERS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m, pat
    return None, None


def has_user_stop_directive_near(text: str, idle_match) -> bool:
    """Check if the user explicitly directed a stop within ~200 chars of the idle marker."""
    start = max(0, idle_match.start() - 200)
    end = min(len(text), idle_match.end() + 200)
    window = text[start:end]
    for pat in USER_STOP_PROXIMITY:
        if re.search(pat, window, re.IGNORECASE):
            return True
    return False


def find_reversible_open_items(limit: int = 5):
    """Scan all Projects/*/task_plan.md for open `- [ ]` lines that aren't Wiktor-gated."""
    reversible = []
    if not PROJECTS.exists():
        return reversible
    for tp in PROJECTS.glob("*/task_plan.md"):
        try:
            content = tp.read_text(encoding="utf-8")
        except Exception:
            continue
        # Skip archived/done projects
        # (heuristic: frontmatter status: #done — coarse but cheap)
        head = content[:500].lower()
        if "status: \"#done\"" in head or "status: #done" in head:
            continue
        for m in re.finditer(r"^-\s*\[\s*\]\s*(.+)$", content, re.MULTILINE):
            line = m.group(1).strip()
            if any(re.search(p, line, re.IGNORECASE) for p in WIKTOR_GATE_MARKERS):
                continue
            try:
                rel = tp.relative_to(VAULT)
            except ValueError:
                rel = tp
            reversible.append((str(rel), line[:140]))
            if len(reversible) >= limit:
                return reversible
    return reversible


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    # This hook's own docstring promises it "errors out silently (exit 0) on any
    # unexpected condition". Valid JSON of the wrong shape was the one unexpected
    # condition that broke that promise: a bare array reached .get and printed an
    # AttributeError traceback. See test_hooks_survive_malformed_payload.py.
    if not isinstance(payload, dict):
        sys.exit(0)

    transcript_path = payload.get("transcript_path", "")
    if not transcript_path:
        sys.exit(0)

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire, session_from
        log_fire("proactivity-check", session=session_from(payload))
    except Exception:
        pass

    text = read_last_assistant_text(transcript_path)
    if not text:
        sys.exit(0)

    idle_match, _pat = find_idle_marker(text)
    if not idle_match:
        sys.exit(0)

    if has_user_stop_directive_near(text, idle_match):
        sys.exit(0)

    reversible = find_reversible_open_items()
    if not reversible:
        sys.exit(0)

    matched_snippet = text[max(0, idle_match.start() - 40):idle_match.end() + 40]
    matched_snippet = re.sub(r"\s+", " ", matched_snippet).strip()

    msg_lines = [
        "PROACTIVITY CHECK: response contains an idle-wait marker but reversible task_plan items exist.",
        f"  matched: \"{matched_snippet}\"",
        "  reversible (non-Wiktor-gated) open items:",
    ]
    for path, line in reversible:
        msg_lines.append(f"    - {path}: {line}")
    msg_lines.append("")
    msg_lines.append(
        "Either execute a reversible item or, if the stop is genuinely warranted, "
        "tag it explicitly (irreversible action ahead, compaction boundary, or user-stop "
        "directive nearby). Per feedback_be_proactive_self_sustainable.md clause B: "
        "ratification gates are for irreversible-action increments only."
    )
    reason = "\n".join(msg_lines)

    try:
        from _governance_logger import log_fire, session_from
        log_fire("proactivity-check", decision="block",
                 detail=f"{len(reversible)} reversible items",
                 session=session_from(payload))
    except Exception:
        pass

    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


if __name__ == "__main__":
    main()
