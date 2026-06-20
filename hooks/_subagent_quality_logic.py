"""Pure logic for subagent-quality-check (extracted 2026-06-02, boundary-test harness sprint 6).

Behavior-preserving extraction of the three structural checks, so they can be
unit-tested without running the I/O wrapper (which appends to governance-log.jsonl
on every block: testing the live wrapper would pollute the log with fake block
events and inflate the harvest counts). Mirrors the dispatch-compliance-check ->
_dispatch_compliance_logic.py split.

The wrapper keeps stdin parsing, logging, and stdout block emission; this module
is the decision function that gets the boundary tests.
"""
from __future__ import annotations

import re

# CHECK 2 refusal/error patterns: matched only on short (<100 char) messages.
ERROR_PATTERNS = [
    "unable to complete",
    "i cannot",
    "i can't",
    "i don't have access",
    "i apologize",
]

# CHECK 2 discriminator (fix 2026-06-02, finding_subagent_quality_check_overfires):
# a short message can contain a refusal keyword yet be a valid NEGATIVE FINDING
# ("I cannot reproduce the bug; it works on main."). If the message carries a
# result-signal token, it is a finding, not a refusal: do not block it.
RESULT_SIGNAL = re.compile(
    r"\b(found|works?|working|pass(es|ed)?|reproduc\w*|verif\w*|confirm\w*"
    r"|results?|succeed\w*|no (defects?|bugs?|issues?|errors?))\b",
    re.IGNORECASE,
)

# CHECK 3 structure additions (fix 2026-06-02): the vault's own QA / PENTEST /
# PM CHECKPOINT / POSTMORTEM REPORT blocks are unfenced `Label: value` text
# (CLAUDE.md REQUIRES them unfenced: the Stop hook strips fences). That is a
# valid structure type, not "no structure."
LABEL_VALUE_LINE = re.compile(r"(?m)^[A-Z][A-Za-z][A-Za-z ]*:\s")
REPORT_HEADER = re.compile(
    r"(?im)^\s*(QA REPORT|QA SCOPE|PENTEST REPORT|PM CHECKPOINT REPORT|"
    r"POSTMORTEM REPORT|CLASSIFICATION|BUILD SCOPE|ANALYSIS SCOPE|"
    r"PLANNING SCOPE|RESEARCH SCOPE)\b"
)


def classify_subagent_output(message: str) -> tuple[bool, str, str]:
    """Return (blocked, check_failed, reason) for a sub-agent's last message.

    Exact behavior of the original inline checks, preserved:
      CHECK 1: len < 5            -> empty
      CHECK 2: len < 100 + refusal/error keyword -> error_refusal
      CHECK 3: len > 500 + no structural markup   -> no_structure
    Returns (False, "", "") when the output passes all checks.
    """
    message_len = len(message)

    # CHECK 1: truly empty output
    if message_len < 5:
        return (True, "check_1_empty",
                f"Agent output is empty ({message_len} chars). Produce a substantive response.")

    # CHECK 2: pure error/refusal output (very short + error keywords).
    # A refusal keyword alongside a result-signal token is a valid negative
    # FINDING, not a refusal: don't block it (fix 2026-06-02).
    if message_len < 100 and not RESULT_SIGNAL.search(message):
        lower_msg = message.lower()
        for pattern in ERROR_PATTERNS:
            if pattern in lower_msg:
                return (True, "check_2_error_refusal",
                        f"Agent output appears to be an error or refusal ({message_len} chars, "
                        f"matched: '{pattern}'). Retry the task or report what specifically failed.")

    # CHECK 3: substantial output without structure
    if message_len > 500:
        has_headers = bool(re.search(r'(?m)^#{1,4}\s', message))
        has_bullets = bool(re.search(r'(?m)^[\s]*[-*]\s', message))
        has_tables = bool(re.search(r'\|.*\|', message))
        has_code_blocks = '```' in message
        has_numbered_list = bool(re.search(r'(?m)^\s*\d+[.)]\s', message))
        has_label_value = len(LABEL_VALUE_LINE.findall(message)) >= 3
        has_report_header = bool(REPORT_HEADER.search(message))
        if not (has_headers or has_bullets or has_tables or has_code_blocks
                or has_numbered_list or has_label_value or has_report_header):
            return (True, "check_3_no_structure",
                    f"Agent produced {message_len} chars with no structure (no headers, bullets, "
                    f"tables, or code blocks). Structure your output with clear sections and formatting.")

    return (False, "", "")
