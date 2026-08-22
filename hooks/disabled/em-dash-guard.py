r"""
Em-Dash Guard - Stop Hook

Blocks the assistant from shipping a response that contains a "fancy" dash
character in PROSE. the owner never uses these characters in writing and finds them
unnatural in generated text; he wants them impossible in Claude's output, not
merely discouraged. Soft instructions land ~25% compliance per CLAUDE.md Working
Philosophy, so this hook is the runtime enforcement.

Sibling of prose-codes-check.py (same transcript-parse + strip-noise idiom and
exit-2 block style). This file keeps its OWN source free of the literal glyphs
(it uses \uXXXX escapes) so it never trips the rule it enforces.

BLOCKED in prose (anything that is a dash but is NOT the plain keyboard hyphen):
  * U+2012 figure dash
  * U+2013 en dash
  * U+2014 em dash
  * U+2015 horizontal bar
  * U+2212 minus sign            (the common LLM substitute when told "no em dash")
  * U+2E3A two-em dash
  * U+2E3B three-em dash
  * U+FE58 small em dash
  * U+FF0D fullwidth hyphen-minus

ALLOWED (never triggers a block):
  * Plain hyphen-minus U+002D ("-"), e.g. day-to-day, self-hosted
  * The literal words "em dash" / "em-dash" / "en dash"
  * Any blocked glyph inside backticks, fenced code blocks, real markdown table
    rows, or frontmatter, so the assistant can still display the characters or
    paste code and quoted material verbatim.

REMEDIATION
  The block message tells the assistant to rewrite, replacing each dash with a
  comma, a colon, parentheses, or a sentence break, and explicitly NOT to swap in
  a different dash-like glyph. The message itself contains no blocked glyph.

LOOP-SAFETY
  Honors stop_hook_active (returns 0 immediately when the stop is already a
  hook-induced continuation), identical to every other vault Stop hook. The guard
  therefore fires on the FIRST stop of a turn; removing a dash on the rewrite is
  trivial, so first-stop enforcement is effective in practice. (A bounded per-turn
  retry counter would make it airtight at the cost of a state file; deferred.)

FAIL-OPEN
  Any internal error (no stdin, bad JSON, missing transcript) returns 0 (allow)
  so the hook can never wedge the session.

EXIT CODES
  0 = clean, allow Stop
  2 = block, message in stderr is shown to the assistant
"""

import sys
import json
import os
import re

# 200KB tail window (matches process-step-check). A Stop hook runs on every
# response, so keep the read bounded, but give long structured turns headroom.
READ_BYTES = 204800

# Dash-like glyphs that are NOT the plain hyphen. Stored as escapes so this
# source file does not itself contain the characters it blocks.
BLOCKED_DASHES = [
    ("‒", "figure dash (U+2012)"),
    ("–", "en dash (U+2013)"),
    ("—", "em dash (U+2014)"),
    ("―", "horizontal bar (U+2015)"),
    ("−", "minus sign (U+2212)"),
    ("⸺", "two-em dash (U+2E3A)"),
    ("⸻", "three-em dash (U+2E3B)"),
    ("﹘", "small em dash (U+FE58)"),
    ("－", "fullwidth hyphen-minus (U+FF0D)"),
]

# A real markdown table row: optional leading whitespace, a pipe, content, a
# trailing pipe. Only these are stripped, so a prose line that merely contains
# pipes (e.g. "insert | update | delete") is still scanned for dashes.
TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def strip_noise(text):
    """Remove fenced code blocks, inline code, real markdown table rows, and
    frontmatter. Content inside these is legitimate code or quoted material, not
    the assistant's own prose, so dashes there must not trigger a block."""
    # Leading frontmatter block
    text = re.sub(r"^---\n[\s\S]*?\n---\n", "", text, count=1)
    # Fenced code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Inline code spans
    text = re.sub(r"`[^`\n]+`", "", text)
    # Real markdown table rows only
    kept = [ln for ln in text.split("\n") if not TABLE_ROW.match(ln)]
    return "\n".join(kept)


def get_last_assistant_text(transcript_path):
    """Read the transcript tail, locate the last assistant message, return its
    text content joined into one string."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()
    lines = tail.split("\n")
    for line in reversed(lines):
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
        text_parts = []
        for block in message.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        if text_parts:
            return "\n".join(text_parts)
    return ""


def find_fancy_dashes(prose):
    """Return the list of distinct offending dash names present in prose."""
    return [name for glyph, name in BLOCKED_DASHES if glyph in prose]


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return 0
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return 0
    if payload.get("stop_hook_active"):
        return 0

    def _log(decision, detail=None):
        """Record this verdict to hook-activity.jsonl. Never raises (contract C2)."""
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _governance_logger import log_fire, session_from
            log_fire("em-dash-guard", decision=decision, detail=detail,
                     session=session_from(payload))
        except Exception:
            pass

    transcript_path = payload.get("transcript_path") or ""
    text = get_last_assistant_text(transcript_path)
    if not text:
        _log("skip", "no-assistant-text")
        return 0
    prose = strip_noise(text)
    found = find_fancy_dashes(prose)
    if not found:
        _log("allow")
        return 0

    # Block first, log second. Nothing between the verdict and the block may be
    # able to swallow it (idiom inherited from routing-table-validation.py).
    sys.stderr.write(
        "[em-dash-guard BLOCK] Your response contains a dash character the owner "
        "never uses in writing: " + ", ".join(found) + ". Rewrite the whole "
        "response so it contains NONE of these glyphs. Replace each one with a "
        "comma, a colon, a pair of parentheses, or split the sentence in two. Do "
        "NOT swap in a different dash-like character such as a minus sign or a "
        "horizontal bar; that will also be blocked. Plain keyboard hyphens (the "
        "'-' key) are fine and need no change. These glyphs are allowed only "
        "inside backticks, fenced code blocks, table rows, or frontmatter, so if "
        "you must keep one verbatim (quoting a source or showing code) move it "
        "into a code span.\n"
    )
    _log("block", ", ".join(found))
    return 2


if __name__ == "__main__":
    sys.exit(main())
