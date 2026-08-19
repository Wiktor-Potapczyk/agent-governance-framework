"""
Prose Slop Check - PostToolUse Write|Edit hook  [LIVE, registered]

Sibling to prose-codes-check.py. That hook catches invented shorthand CODES
(T-C1, AR-F5, B-1). This one catches LLM-register VOCABULARY SLOP: the
hallmark words an LLM reaches for that a terse human technical writer never
does (delve, tapestry, multifaceted, furthermore, ...). The two are disjoint:
prose-codes-check has zero vocabulary coverage (verified 2026-06-02).

SCOPE: generated prose written to the wiki/work layer :
  Resources/KB/**.md  and  Projects/*/work/**.md
NOT chat responses (those are already terse per CLAUDE.md minimum-length rule)
and NOT raw-layer files (Inbox/Clippings/Daily Notes: owner- or externally-
authored, never LLM-linted).

CALIBRATION (2026-06-02, the pilot's calibration gate):
  Scanned the 24-word candidate list across the 19 legit Resources/KB wiki
  pages. Result: every HIGH-confidence word below occurs ZERO times in real
  vault prose. `fundamental` (4), `landscape` (3), `leverage` (1), and the
  borderline technical-register words (robust, comprehensive, crucial,
  significant, seamless, pivotal, nuanced, additionally) are DELIBERATELY
  EXCLUDED: they have legitimate technical uses, so flagging them would
  produce false positives. Precision-first per feedback_low_false_positive_fixes.

SEVERITY: WARN only (stderr + exit 0). NEVER blocks a Write. Slop is a quality
nudge, not a correctness gate: a false positive must never interrupt a real
write. (Contrast: prose-codes-check hard-blocks because the owner literally cannot
parse the codes.)

STATUS: LIVE (header reconciled 2026-08-11 by the plain-language Stage 1
discovery gate). Registered in .claude/settings.local.json as the third command
entry of a PostToolUse "Write|Edit" matcher block. hook-activity.jsonl held
4,256 firing records for this hook (100 warn) at reconciliation time. Earlier
revisions of this header claimed DORMANT / NOT REGISTERED; registration plus
the firing log falsify that claim.

OVERLAP VERDICT (2026-08-11 discovery gate): DISJOINT from
plain-language-guard.py. Scripted set intersection of SLOP_WORDS against the
PL-4/PL-5/PL-7 lists returned zero shared entries and zero substring
near-misses; both hooks are warn-only; this hook warns only past its
2-distinct/3-total thresholds (measured warn rate 100/4,256 firings), so a
double advisory on one write is rare and never about the same word. The
plain-language layer lives in .claude/plain-language-rules.md and
plain-language-guard.py.
Boundary tests: test_prose_slop_check.py (C4 FP-guard coverage).

EXIT CODES
  0 = always (clean OR warn). This hook never blocks.
"""

import sys
import json
import os
import re

# HIGH-confidence LLM-register slop. Every word here scored 0 occurrences in the
# 19 legit Resources/KB wiki pages on 2026-06-02. Words with legitimate technical
# register (robust, comprehensive, crucial, significant, seamless, pivotal,
# nuanced, additionally, fundamental, landscape, leverage) are EXCLUDED by design.
SLOP_WORDS = [
    "delve", "tapestry", "multifaceted", "vibrant", "realm", "testament",
    "foster", "showcase", "underscore", "intricate", "furthermore", "moreover",
    "paramount", "myriad", "plethora", "bustling", "interplay", "nestled",
    "elevate", "embark", "unleash", "harness the power",
]
# Multi-word phrases need their own pattern; single words use \b...\b.
_SINGLE = [w for w in SLOP_WORDS if " " not in w]
_PHRASE = [w for w in SLOP_WORDS if " " in w]
_SLOP_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _SINGLE) + r")\b",
    re.IGNORECASE,
)
_PHRASE_RES = [re.compile(re.escape(p), re.IGNORECASE) for p in _PHRASE]

# Warn only when slop is real, not a one-off. >=2 distinct slop words OR the same
# word >=3 times in one generated file. A single stray "showcase" stays silent.
DISTINCT_THRESHOLD = 2
TOTAL_THRESHOLD = 3

# Only lint the wiki/work layer. Forward- and back-slash tolerant.
_TARGET_RE = re.compile(
    r"(?:resources[\\/]kb[\\/].*\.md$)|(?:projects[\\/][^\\/]+[\\/]work[\\/].*\.md$)",
    re.IGNORECASE,
)


def strip_noise(text):
    """Remove frontmatter, fenced/inline code, and tables: slop only counts in
    prose. (Same approach as prose-codes-check.strip_noise.)"""
    text = re.sub(r"^---\n[\s\S]*?\n---\n", "", text, count=1)
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`[^`\n]+`", "", text)
    kept = [ln for ln in text.split("\n") if ln.count("|") < 2]
    return "\n".join(kept)


def find_slop(text):
    """Return (distinct_count, total_count, sorted_hits[(word,count)]) for prose.

    Pure function: no I/O: so test_prose_slop_check.py can exercise it directly."""
    prose = strip_noise(text)
    counts = {}
    for m in _SLOP_RE.finditer(prose):
        w = m.group(0).lower()
        counts[w] = counts.get(w, 0) + 1
    for pat, phrase in zip(_PHRASE_RES, _PHRASE):
        n = len(pat.findall(prose))
        if n:
            counts[phrase.lower()] = counts.get(phrase.lower(), 0) + n
    total = sum(counts.values())
    distinct = len(counts)
    hits = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return distinct, total, hits


def should_warn(distinct, total):
    return distinct >= DISTINCT_THRESHOLD or total >= TOTAL_THRESHOLD


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return 0
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or ""
    norm = file_path.replace("\\", "/")
    if not _TARGET_RE.search(norm):
        return 0  # not a wiki/work .md: out of scope

    # PostToolUse Write carries the written content; Edit carries new_string.
    content = tool_input.get("content")
    if content is None:
        content = tool_input.get("new_string") or ""
    if not content:
        return 0

    def _log(decision, detail=None):
        """Record this verdict to hook-activity.jsonl. Never raises (contract C2)."""
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _governance_logger import log_fire, session_from
            log_fire("prose-slop-check", decision=decision, detail=detail,
                     session=session_from(payload))
        except Exception:
            pass

    distinct, total, hits = find_slop(content)
    if not should_warn(distinct, total):
        _log("allow")
        return 0

    # Warn first, log second. Nothing between the verdict and the advisory may
    # be able to swallow it (idiom inherited from routing-table-validation.py).
    pretty = ", ".join(f"`{w}`x{n}" if n > 1 else f"`{w}`" for w, n in hits[:8])
    sys.stderr.write(
        f"[prose-slop-check WARN] {os.path.basename(file_path)} contains "
        f"LLM-register slop in prose: {pretty}. Prefer plain technical wording "
        f"(e.g. 'delve into' -> 'examine'; 'foster' -> 'support'; 'underscore' "
        f"-> 'show'; 'furthermore/moreover' -> just continue the sentence). "
        f"Codes/tables/fences are not checked. (advisory: write was kept.)\n"
    )
    _log("warn", pretty)
    return 0


if __name__ == "__main__":
    sys.exit(main())
