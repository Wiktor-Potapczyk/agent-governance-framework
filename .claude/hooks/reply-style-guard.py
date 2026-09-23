#!/usr/bin/env python
"""Stop hook. Refuses an assistant reply that over-uses bold or reaches for a
stock AI word, and makes the assistant rewrite it before the user sees it.

WHY A STOP HOOK AND NOT A WRITE HOOK. This vault already ran the experiment.
`em-dash-guard.py` is a Stop hook returning exit 2; its own activity log shows
153 blocks against 1,386 allows, and the behaviour it polices has held.
`plain-language-guard.py` is PostToolUse and warn-only; it logged 446 in-scope
writes, 266 of them carrying findings, and changed nothing. That guard's own
docstring records why flipping its block switch would not help either: it runs
PostToolUse, so "the write it is scanning has already landed on disk", and
"genuine write-time prevention would need a separate PreToolUse companion hook".
The reply surface had no guard at all: .claude/rules/plain-language.md marks
conversational replies Exempt in writing, and CLAUDE.md line 28 repeats it.

WHY THESE TWO RULES AND NOT THE PLAIN-LANGUAGE SET. Measured over 1,522 of this
assistant's own message blocks in session 67e82ff4, with code, tables and
structured blocks already stripped:

  4-or-more bold spans .......... 8.7% of messages   <- enforced
  3-or-more bold spans .......... 13.2%              <- rejected, over the bar
  stock-AI wordlist ............. 1.5%               <- enforced
  PL-1 sentence length .......... 17.9% of writes    <- not enforced
  PL-8 abbreviations ............ 35.2% of writes    <- not enforced

.claude/rules/plain-language.md sets this vault's own bar for turning a rule
into a block: a warn rate at or below 10 percent. Bold-at-4 clears it, bold-at-3
does not, and the two plain-language rules that would most reduce verbosity are
the furthest from it. A guard that fires on a third of everything gets worked
around, which is the failure mode already on the record here.

Choppiness (runs of very short sentences) is DELIBERATELY ABSENT. Two
independent implementations of the same written definition disagreed on this
corpus, 155 runs against 150, so the rule is not yet specified precisely enough
to block on. It is a real pattern and it needs a definition first.

EXEMPT SURFACES. Fenced code, inline code, real markdown table rows,
frontmatter, and the structured blocks (QA SCOPE, QA REPORT, PM CHECKPOINT
REPORT, PENTEST REPORT, PENTEST SCOPE, the other process-skill scope blocks, and
the classifier fields). Those blocks are exempt in CLAUDE.md, and two other Stop
hooks REQUIRE them unfenced in the reply, so a guard that judged them would
fight `process-step-check.py` and `dispatch-compliance-check.py` on every
non-Quick turn.

FIXES APPLIED AFTER ARCHITECT REVIEW (2026-08-27), all four reproduced by the
reviewer against the real templates rather than argued:
  1. PENTEST SCOPE was missing from the exempt list entirely, so a spec-shaped
     pentest scope block was blocked outright.
  2. The block skip ended at the FIRST blank line. The canonical PENTEST REPORT
     and PM CHECKPOINT REPORT are multi-section markdown with blank lines
     between their sub-headers and tables, so everything past the first blank
     line was still scanned. Only QA REPORT survived, because it happens to be
     specified as a single compact block. The skip now runs through internal
     blank lines and ends only when ordinary prose resumes.
  3. strip_noise stripped frontmatter before fenced code. A leading "---"
     divider plus a "---" inside a fence let the non-greedy frontmatter regex
     eat the fence opener, leaving that code to be scanned as prose. Fences are
     stripped first now.
  4. The "underscore" wordlist entry fired on ordinary technical prose in this
     vault (snake_case, underscores in filenames) and is removed.

FAIL-OPEN. Any internal error, missing transcript, or unparseable payload
returns 0. A broken guard must not be able to stop the assistant answering.

MEASURABILITY. This hook logs the ALLOW path as well as the BLOCK path. The
reason is a finding from 2026-08-26 about this vault's own Gate-1 guard: it
writes a record only when it denies, so a correct allow and a defeated guard are
byte-identical silence and its false-negative rate cannot be measured at all.
Logging both makes this hook's own precision auditable later.

EXIT CODES
  0 = allow (clean, or an internal error, or stop_hook_active)
  2 = block; the reason is on stderr and the assistant rewrites
"""

import json
import os
import re
import sys

READ_BYTES = 204800

# Measured threshold. See the docstring: 4 fires on 8.7% of real messages, 3 on
# 13.2%, and this vault's own flip criterion is 10%. Emphasis stays available;
# emphasising six things at once is what this stops.
BOLD_LIMIT = 4

BOLD_SPAN = re.compile(r"\*\*[^*\n]{1,80}\*\*")

# Low-false-positive subset of the humanizer skill's patterns. Judgment-heavy
# humanizer patterns (forced triples, dramatic fragments, phantom objections)
# are not here; regex cannot settle them. "underscore" was here and was removed
# after review: the same surface form covers the AI cliche verb and the ordinary
# technical noun, and this vault talks about snake_case constantly.
WORDLIST = [
    (r"\b(?:delve[sd]?|delving)\b", "stock AI verb"),
    (r"\btapestr(?:y|ies)\b", "stock AI metaphor"),
    (r"\bshowcas(?:e|es|ed|ing)\b", "stock AI verb"),
    (r"\bpivotal\b", "inflated importance"),
    (r"\btestament\b", "inflated importance"),
    (r"\bintricac(?:y|ies)\b", "stock AI noun"),
    (r"\bvibrant\b", "sales language"),
    (r"\binterplay\b", "stock AI noun"),
    (r"\bfoster(?:s|ed|ing)\b", "stock AI verb"),
    (r"\b(?:boasts|nestled|breathtaking|renowned|groundbreaking|stunning)\b", "sales language"),
    (r"\bI hope this helps\b", "chatbot artifact"),
    (r"\b(?:Would you like me to|Want me to)\b", "chatbot artifact"),
    (r"\b(?:Certainly|Of course)!", "chatbot artifact"),
    (r"\bYou're absolutely right\b", "sycophancy"),
    (r"\b(?:Great question|Excellent point)\b", "sycophancy"),
    (r"\b(?:Let's dive in|let's break this down|without further ado)\b", "announcing the point"),
]

TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")

# Structured blocks are exempt by CLAUDE.md and are REQUIRED unfenced in the
# reply by two other Stop hooks. Matching one starts a skip.
STRUCT_START = re.compile(
    r"^(?:QA SCOPE|QA REPORT|PM CHECKPOINT REPORT|PENTEST REPORT|PENTEST SCOPE"
    r"|BUILD SCOPE|ANALYSIS SCOPE|RESEARCH SCOPE|PLANNING SCOPE"
    r"|IMPLIES:|TASK TYPE:|DOMAIN:|REVERSIBILITY:|DETECTABILITY:|APPROACH:"
    r"|MISSED:|MUST DISPATCH:|JUSTIFICATION:|PASS:|FAIL:|Untested:|Source:"
    r"|Project:|Phase:|Viability:|Blockers:|Next:|Parallel-runnable:"
    r"|Parallel-blocked-by:|Increment:|Artifacts:|Attack surface:|Goal:"
    r"|Inputs:|Tech:|Output path:|Mode:|Subject:|Question:|Deliverable:"
    r"|Constraints:|Questions:|Sources available:)"
)

# A structured block may contain internal blank lines: the canonical PENTEST
# REPORT and PM CHECKPOINT REPORT are multi-section markdown with sub-headers
# and tables. A blank line inside one only ends the block when ordinary prose
# resumes, not when the next section starts.
CONTINUES_BLOCK = re.compile(r"^(?:#{1,6}\s|\|)")


def strip_noise(text):
    """Remove every surface this guard must not judge: fenced code, frontmatter,
    inline code, real markdown table rows, and structured blocks. Pure: same
    input, same output, no state.

    Fenced code is stripped FIRST. The frontmatter regex is non-greedy and does
    not validate that it matched real YAML, so with a leading "---" divider it
    could otherwise reach into a fence whose body contains its own "---" line,
    swallow the opening backticks, and leave that code to be scanned as prose.
    """
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"^---\n[\s\S]*?\n---\n", "", text, count=1)
    text = re.sub(r"`[^`\n]+`", "", text)
    lines = text.split("\n")
    kept = []
    skipping = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if TABLE_ROW.match(line):
            i += 1
            continue
        if STRUCT_START.match(line.strip()):
            skipping = True
            i += 1
            continue
        if skipping:
            if line.strip() == "":
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                nxt = lines[j].strip() if j < len(lines) else ""
                if nxt and (CONTINUES_BLOCK.match(nxt) or STRUCT_START.match(nxt)):
                    i += 1
                    continue
                skipping = False
                kept.append(line)
            i += 1
            continue
        kept.append(line)
        i += 1
    return "\n".join(kept)


def get_last_assistant_text(transcript_path):
    """Read the transcript tail and return the last assistant message's text."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()
    for line in reversed(tail.split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        parts = [
            b.get("text", "")
            for b in entry.get("message", {}).get("content", [])
            if isinstance(b, dict) and b.get("type") == "text"
        ]
        if parts:
            return "\n".join(parts)
    return ""


def find_violations(prose):
    """Return a list of (rule, detail) for everything wrong with this prose."""
    found = []
    bold = BOLD_SPAN.findall(prose)
    if len(bold) >= BOLD_LIMIT:
        found.append(("bold", "%d bold spans (limit is %d)" % (len(bold), BOLD_LIMIT)))
    for pattern, label in WORDLIST:
        m = re.search(pattern, prose, flags=re.IGNORECASE)
        if m:
            found.append(("wordlist", "%s (%s)" % (m.group(0), label)))
    return found


def _log(decision, detail=None):
    """Append one record per invocation, ALLOW as well as BLOCK. Never raises:
    a locked or missing log file must not break the assistant's reply."""
    if os.environ.get("REPLY_STYLE_GUARD_TESTING"):
        return
    try:
        # Converged onto the shared helper 2026-08-31; see write-style-guard._log
        # for the rationale (same sink, now via the route the matrix scan sees).
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("reply-style-guard", decision=decision, detail=detail,
                 session=_log.session)
    except Exception:
        pass


_log.session = None


def main():
    try:
        payload_text = sys.stdin.read()
    except Exception:
        return 0
    if not payload_text:
        return 0
    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError):
        return 0
    # Valid JSON of the wrong shape is still unusable input. Without this,
    # a bare array or scalar reached .get and printed an AttributeError
    # traceback. See test_hooks_survive_malformed_payload.py.
    if not isinstance(payload, dict):
        return 0
    if payload.get("stop_hook_active"):
        return 0
    _log.session = payload.get("session_id")

    try:
        text = get_last_assistant_text(payload.get("transcript_path"))
        if not text.strip():
            _log("skip", "no assistant text")
            return 0
        violations = find_violations(strip_noise(text))
    except Exception as exc:
        _log("skip", "internal error: %s" % type(exc).__name__)
        return 0

    if not violations:
        _log("allow")
        return 0

    detail = "; ".join("%s: %s" % (r, d) for r, d in violations)
    lines = ["REPLY STYLE: rewrite this response before sending it."]
    for rule, d in violations:
        if rule == "bold":
            lines.append(
                "  Too much bold: %s. Remove the emphasis and let the sentence "
                "carry the weight. Keep at most %d." % (d, BOLD_LIMIT - 1)
            )
        else:
            lines.append(
                "  Stock AI phrasing: %s. Use the plain word instead, or put it "
                "in backticks if you are naming the word rather than using it." % d
            )
    lines.append("  Code, tables and structured report blocks are exempt and were not counted.")
    # stderr first, then log. em-dash-guard.py makes this ordering explicit so
    # nothing between the verdict and the block can swallow it.
    sys.stderr.write("\n".join(lines) + "\n")
    _log("block", detail)
    return 2


if __name__ == "__main__":
    sys.exit(main())
