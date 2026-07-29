r"""
Prose Codes Check - Stop Hook

Blocks the assistant from shipping a response that uses invented internal codes
in prose. Wiktor repeatedly cannot parse codes like T-C1, T-W2, D-T3, AR-F5 —
they read as gibberish. Two memos already document this preference:
  feedback_no_internal_queue_codes_in_prose.md
  feedback_no_abbreviations_in_prose.md
Soft instructions land ~25% compliance per CLAUDE.md Working Philosophy.
This hook is the runtime enforcement.

PATTERNS BLOCKED (in prose only — not inside code blocks, tables, frontmatter)
  - `\bT-[A-Z]+\d+\b`                  e.g. T-C1, T-W2, T-G1, T-NOTE
  - `\bD-T\d+\b`                       e.g. D-T1, D-T2 (decision-point codes)
  - `\bD-\d+\b`                        e.g. D-1, D-3 (numbered decisions in prose)
  - `\bAR-[A-Z]?\d+\b`                 e.g. AR-F5, AR-1 (architect-reviewer findings)
  - `\b[BLR]-\d+[A-Z]?\b`              e.g. B-1, R-2V, L20, L32 from the explicit memo

PATTERNS ALLOWED (NEVER triggered)
  - Real Jira keys for the org: PROJ-, TEAM-, OPS-, PLAT-, etc.
  - Workflow shorthand Wiktor uses: W1..W9, S0..S9, M1..M9 (milestones)
  - Domain vocabulary: FA-N (Focus Areas), Phase N
  - Anything inside backticks, fenced code blocks, markdown tables, or frontmatter

REMEDIATION
The block message tells the assistant to rephrase the offending code as plain
language description ("the critical finding about the missing disclosure marker"
instead of "T-C1"). Allow at most 1 offending token to slip with a warning before
hard-blocking — bias toward unblocking when the prose is otherwise compliant.

EXIT CODES
  0 = clean, allow Stop
  2 = block, message in stderr is shown to the assistant
"""

import sys
import json
import os
import re

# 100KB window — Stop hook runs on every response, keep it cheap
READ_BYTES = 102400

# Block patterns — invented prose codes
BLOCK_PATTERNS = [
    (re.compile(r"\bT-[A-Z]+\d+\b"), "T-style code (T-C1, T-W2, etc.)"),
    (re.compile(r"\bD-T\d+\b"), "D-T style decision code"),
    (re.compile(r"\bAR-[A-Z]?\d+\b"), "AR-style finding code"),
    (re.compile(r"\b[BLR]-\d+[A-Z]?\b"), "single-letter queue code (B-1, R-2V, L20)"),
]

# Allow-list — real Jira/domain identifiers that should NEVER trigger.
# Ticket-key prefixes for your org, plus n8n workflow shorthand, plus
# milestone/step/phase numbering. These patterns match identifiers we want
# to LET THROUGH even if they coincidentally look code-like.
ALLOW_PREFIXES = re.compile(
    r"\b(?:"
    r"PROJ|TEAM|OPS|PLAT|JIRA|"      # Jira keys
    r"FA|"                                       # Focus Area
    r"W\d|S\d|M\d|"                              # workflow / step / milestone
    r"OQ"                                        # open question (Wiktor uses this)
    r")-?\d+\b"
)

# D-NN that is part of a Jira-style or domain pattern (e.g. "D-1 ticket" in
# Wiktor's own prose) is harder to disambiguate. Conservative call: only block
# bare "D-N" / "D-NN" that's NOT preceded by another identifier-word context.
# Implemented by also requiring D-N is NOT immediately followed by a hyphen
# (which would indicate a longer Jira-style key).
D_PATTERN = re.compile(r"\bD-\d{1,2}\b(?!-)")


def strip_noise(text):
    """Remove fenced code blocks, inline code, tables, frontmatter — content
    inside these is legitimate technical material, not prose."""
    # Frontmatter
    text = re.sub(r"^---\n[\s\S]*?\n---\n", "", text, count=1)
    # Fenced code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Inline code
    text = re.sub(r"`[^`\n]+`", "", text)
    # Markdown tables — lines with 2+ pipes
    table_lines = []
    for ln in text.split("\n"):
        if ln.count("|") >= 2:
            continue
        table_lines.append(ln)
    return "\n".join(table_lines)


def find_violations(prose):
    """Return list of (matched_token, label) tuples for violations in prose."""
    violations = []
    for pat, label in BLOCK_PATTERNS:
        for m in pat.finditer(prose):
            tok = m.group(0)
            # Skip if also matches the allow-list
            if ALLOW_PREFIXES.match(tok):
                continue
            violations.append((tok, label))
    # Bare D-N pattern
    for m in D_PATTERN.finditer(prose):
        tok = m.group(0)
        if ALLOW_PREFIXES.match(tok):
            continue
        violations.append((tok, "bare D-N decision code"))
    return violations


def get_last_assistant_text(transcript_path):
    """Read transcript tail, locate last assistant message, return its text."""
    if not os.path.exists(transcript_path):
        return ""
    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    # Walk lines backward, find last assistant message with text content
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

    try:
        import os as _gho, sys as _ghs
        _ghs.path.insert(0, _gho.path.dirname(_gho.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("prose-codes-check")
    except Exception:
        pass
    transcript_path = payload.get("transcript_path") or ""
    text = get_last_assistant_text(transcript_path)
    if not text:
        return 0
    prose = strip_noise(text)
    violations = find_violations(prose)
    if not violations:
        return 0

    # Dedupe tokens — multiple occurrences of the same code count once
    seen = set()
    deduped = []
    for tok, label in violations:
        key = (tok, label)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((tok, label))

    # Bias toward unblocking when only one token slips — warn (stderr without
    # exit 2 is shown to the user but does NOT block).
    if len(deduped) <= 1:
        tok, label = deduped[0]
        sys.stderr.write(
            f"[prose-codes-check WARN] One invented code in prose: `{tok}` ({label}). "
            f"Rephrase as plain-language description for Wiktor. (Allowed once; "
            f"hard-block on 2+ in a single response.)\n"
        )
        return 0

    # Hard block — 2+ codes
    pretty = ", ".join(f"`{t}` ({l})" for t, l in deduped[:6])
    if len(deduped) > 6:
        pretty += f", +{len(deduped) - 6} more"
    sys.stderr.write(
        "[prose-codes-check BLOCK] Your response contains invented prose codes "
        "Wiktor cannot parse. Codes found: " + pretty + ".\n\n"
        "Rewrite the prose to describe each item in plain language. Codes are "
        "OK inside backticks, code blocks, tables, and frontmatter — but in "
        "prose use the noun phrase, not the label. Examples:\n"
        "  bad : 'T-C1 needs a one-line fix'\n"
        "  good: 'the missing disclosure-marker finding needs a one-line fix'\n"
        "  bad : 'D-3 is a budget call'\n"
        "  good: 'the sample-size decision is a budget call'\n\n"
        "Allowed identifiers (never blocked): real Jira keys (PROJ-N, TEAM-N, "
        "OPS-N), workflow shorthand (W1-W9, S0-S9, M1-M9), Focus Areas (FA-N), "
        "open-questions (OQ-N), phase numbering (Phase N).\n\n"
        "Memos this rule comes from: feedback_no_internal_queue_codes_in_prose, "
        "feedback_no_abbreviations_in_prose.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
