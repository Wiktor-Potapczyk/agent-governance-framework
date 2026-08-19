r"""
Plain-Language Checker (T1 rules PL-1 to PL-10) - importable module + CLI lint mode.

Spec of record: .claude/plain-language-rules.md (PL-1 to PL-10, matrix, MM1 marker
convention). Plan of record: Projects/your-project/work/
2026-08-10-plain-language-standard-plan.md (v2, owner-approved 2026-08-11).
Build record: Projects/your-project/work/
2026-08-11-plain-language-stage1-build.md.

WHAT THIS MODULE IS
  Pure scan functions per T1 rule, no I/O in the scan path. The PostToolUse hook
  plain-language-guard.py wraps scan(); the CLI mode lints a corpus for the
  Stage 1 baseline. Architecture template: em-dash-guard.py / prose-slop-check.py
  (strip_noise lineage), extended with the MM1 structural-marker exemption.

RULES BUILT HERE (all warn-material only; this module never blocks anything)
  PL-1  sentence length cap (25 prose / 20 numbered-step words; named constants,
        calibration starting values for Stage 3 retuning)
  PL-2  one action per numbered step (chained-imperative heuristic, advisory)
  PL-3  active voice prefilter (be-verb + -ed word, advisory, known-crude)
  PL-4  vague-quantifier list
  PL-5  everyday-word substitution list (vault-authored, nothing ASD-derived)
  PL-7  filler-phrase list
  PL-8  unexpanded all-caps abbreviation at first use (advisory, known-noisy)
  PL-6  NOT built (T2, Stage 5 gate) - structural zero in every result
  PL-9  checker exemption, not a scan (MM1 carve-out) - structural zero
  PL-10 doctrine-drift pytest over the rules file (test_plain_language_check.py),
        not a scan-path rule - structural zero here

MM1 CARVE-OUT (PL-9, TOTAL exemption)
  Content between <!-- MM1 --> and <!-- /MM1 --> is stripped before any rule
  runs, so NO rule (PL-1 included) can produce a finding inside it. Edge
  behavior (spec: rules file, "MM1 marker convention"): unclosed open marker
  exempts to end of document AND emits a marker-hygiene advisory (returned in
  marker_advisories, never counted in per_rule_finding_counts); nested markers
  are one span to the outermost close (depth-tracked). Inline/fenced code is
  stripped BEFORE marker processing, so a marker quoted in backticks never
  opens a span. The marker, not the content, drives the exemption.

RESULT CONTRACT
  scan(text) -> {
    "per_rule_finding_counts": dict with ALL ten keys PL-1..PL-10, zeros included,
    "total_findings": sum of the counts,
    "findings": [{"rule", "line", "text"}...],
    "marker_advisories": [str, ...],
  }

CLI
  python plain_language_check.py PATH [PATH...]   (paths or globs)
  Prints a per-rule per-file count table plus totals. Always exits 0; each file
  is guarded so one unreadable file cannot abort a corpus run.
"""

from __future__ import annotations

import glob as _glob
import re
import sys

# --------------------------------------------------------------------- constants

# PL-1 thresholds: calibration starting values, NOT spec constants (Stage 3
# retunes them as a one-line diff). Plan-of-record risk flag: search-only source.
PROSE_SENTENCE_MAX = 25
STEP_SENTENCE_MAX = 20

RULE_IDS = [f"PL-{i}" for i in range(1, 11)]

# PL-4: vault-authored vague-quantifier list (rules file, PL-4).
VAGUE_QUANTIFIERS = [
    "several", "various", "numerous", "a number of", "appropriate",
    "as needed", "some issues",
]

# PL-5: vault-authored substitution list (rules file, PL-5). Regex stem -> plain word.
SUBSTITUTIONS = [
    (r"utiliz(?:e|es|ed|ing)", "use"),
    (r"commenc(?:e|es|ed|ing)", "start"),
    (r"terminat(?:e|es|ed|ing)", "stop"),
    (r"endeavou?r(?:s|ed|ing)?", "try"),
    (r"facilitat(?:e|es|ed|ing)", "help"),
    (r"leverag(?:e|es|ed|ing)", "use"),
    (r"prior\s+to", "before"),
    (r"subsequent\s+to", "after"),
    (r"in\s+order\s+to", "to"),
    (r"sufficient(?:ly)?", "enough"),
    (r"demonstrat(?:e|es|ed|ing)", "show"),
]

# PL-7: vault-authored filler-phrase list (rules file, PL-7).
FILLER_PHRASES = [
    "it should be noted that", "it is important to note", "essentially",
    "basically", "as mentioned above", "needless to say",
]

_VAGUE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(q).replace(r"\ ", r"\s+") for q in VAGUE_QUANTIFIERS) + r")\b",
    re.IGNORECASE,
)
_SUB_RES = [(re.compile(r"\b" + stem + r"\b", re.IGNORECASE), plain) for stem, plain in SUBSTITUTIONS]
_FILLER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in FILLER_PHRASES) + r")\b",
    re.IGNORECASE,
)
_PASSIVE_RE = re.compile(r"\b(?:is|are|was|were|been|being|be)\s+([A-Za-z]{3,}ed)\b")
_ABBREV_RE = re.compile(r"\b[A-Z]{3,}\b")
_STEP_RE = re.compile(r"^\s*\d+[.)]\s+")
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
_MM1_OPEN = re.compile(r"<!--\s*MM1\s*-->")
_MM1_CLOSE = re.compile(r"<!--\s*/MM1\s*-->")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


# ------------------------------------------------------------------ noise stripping

def _mask_keep_newlines(match):
    """Replace a matched span with its newlines only, preserving line numbers."""
    return "\n" * match.group(0).count("\n")


def _strip_mm1(text):
    """Strip MM1 spans per the rules-file edge table. Returns (text, advisories).

    Depth-tracked: nested opens extend one span to the outermost close. An
    unclosed open exempts to end of document and yields one hygiene advisory.
    Stray closes (no open span) are inert HTML comments and are ignored.
    """
    advisories = []
    events = sorted(
        [(m.start(), m.end(), "open") for m in _MM1_OPEN.finditer(text)]
        + [(m.start(), m.end(), "close") for m in _MM1_CLOSE.finditer(text)]
    )
    spans = []
    depth = 0
    span_start = None
    for start, end, kind in events:
        if kind == "open":
            if depth == 0:
                span_start = start
            depth += 1
        elif depth > 0:
            depth -= 1
            if depth == 0:
                spans.append((span_start, end))
                span_start = None
    if depth > 0 and span_start is not None:
        line_no = text.count("\n", 0, span_start) + 1
        advisories.append(
            f"unclosed <!-- MM1 --> marker opened at line {line_no}; "
            f"exemption extends to end of document. Close it with <!-- /MM1 -->."
        )
        spans.append((span_start, len(text)))
    out = []
    prev = 0
    for start, end in spans:
        out.append(text[prev:start])
        out.append("\n" * text.count("\n", start, end))
        prev = end
    out.append(text[prev:])
    return "".join(out), advisories


def strip_noise(text):
    """Remove frontmatter, fenced code, inline code, MM1 spans, and table rows.

    Line numbers are preserved (masked spans keep their newlines). Order matters:
    code is stripped before MM1 processing so a marker quoted in backticks or a
    fence never opens a span. Returns (clean_text, marker_advisories).
    """
    text = re.sub(r"^---\n[\s\S]*?\n---\n", _mask_keep_newlines, text, count=1)
    text = re.sub(r"```[\s\S]*?```", _mask_keep_newlines, text)
    text = re.sub(r"`[^`\n]+`", "", text)
    text, advisories = _strip_mm1(text)
    lines = [
        "" if _TABLE_ROW_RE.match(ln) else ln
        for ln in text.split("\n")
    ]
    return "\n".join(lines), advisories


# ------------------------------------------------------------------- rule checks
# Each check takes noise-stripped text and returns a list of findings:
# {"rule": id, "line": 1-based line, "text": short offending sample}.

def _sample(s, limit=90):
    s = " ".join(s.split())
    return s if len(s) <= limit else s[: limit - 3] + "..."


def check_pl1(text):
    findings = []
    for line_no, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        is_step = bool(_STEP_RE.match(line))
        limit = STEP_SENTENCE_MAX if is_step else PROSE_SENTENCE_MAX
        body = _STEP_RE.sub("", line) if is_step else re.sub(r"^\s*[-*+]\s+", "", line)
        for sentence in _SENT_SPLIT_RE.split(body):
            words = sentence.split()
            if len(words) > limit:
                kind = "numbered step" if is_step else "prose"
                findings.append({
                    "rule": "PL-1", "line": line_no,
                    "text": f"{len(words)}-word {kind} sentence (cap {limit}): {_sample(sentence)}",
                })
    return findings


def check_pl2(text):
    findings = []
    for line_no, line in enumerate(text.split("\n"), 1):
        if not _STEP_RE.match(line):
            continue
        body = _STEP_RE.sub("", line)
        chained = re.search(r"\band\s+then\b", body, re.IGNORECASE)
        multi_and = len(re.findall(r"\band\b", body, re.IGNORECASE)) >= 2
        if chained or multi_and:
            findings.append({
                "rule": "PL-2", "line": line_no,
                "text": f"chained actions in one numbered step: {_sample(body)}",
            })
    return findings


def check_pl3(text):
    findings = []
    for line_no, line in enumerate(text.split("\n"), 1):
        for m in _PASSIVE_RE.finditer(line):
            findings.append({
                "rule": "PL-3", "line": line_no,
                "text": f"possible passive voice (name the actor): {_sample(m.group(0))}",
            })
    return findings


def check_pl4(text):
    findings = []
    for line_no, line in enumerate(text.split("\n"), 1):
        for m in _VAGUE_RE.finditer(line):
            findings.append({
                "rule": "PL-4", "line": line_no,
                "text": f"vague quantifier '{m.group(0)}' (state the concrete value)",
            })
    return findings


def check_pl5(text):
    findings = []
    for line_no, line in enumerate(text.split("\n"), 1):
        for pattern, plain in _SUB_RES:
            for m in pattern.finditer(line):
                findings.append({
                    "rule": "PL-5", "line": line_no,
                    "text": f"'{m.group(0)}' -> '{plain}'",
                })
    return findings


def check_pl7(text):
    findings = []
    for line_no, line in enumerate(text.split("\n"), 1):
        for m in _FILLER_RE.finditer(line):
            findings.append({
                "rule": "PL-7", "line": line_no,
                "text": f"filler phrase '{m.group(0)}' (delete it)",
            })
    return findings


def check_pl8(text):
    findings = []
    resolved = set()
    for m in _ABBREV_RE.finditer(text):
        token = m.group(0)
        if token in resolved:
            continue
        resolved.add(token)
        tail = text[m.end(): m.end() + 3]
        if tail.lstrip().startswith("("):
            continue  # expanded at first use
        line_no = text.count("\n", 0, m.start()) + 1
        findings.append({
            "rule": "PL-8", "line": line_no,
            "text": f"abbreviation '{token}' not expanded at first use",
        })
    return findings


_CHECKS = [
    ("PL-1", check_pl1),
    ("PL-2", check_pl2),
    ("PL-3", check_pl3),
    ("PL-4", check_pl4),
    ("PL-5", check_pl5),
    ("PL-7", check_pl7),
    ("PL-8", check_pl8),
]


# ------------------------------------------------------------------- entry points

def scan(text):
    """Scan one document's text. Pure function, no I/O.

    Returns the result contract described in the module docstring: all ten PL
    keys with zeros included (PL-6, PL-9, PL-10 are structural zeros in this
    build), total_findings as the sum, per-finding samples, and any MM1
    marker-hygiene advisories (which are NOT findings and NOT counted).
    """
    clean, advisories = strip_noise(text)
    per_rule = {rule_id: 0 for rule_id in RULE_IDS}
    findings = []
    for rule_id, checker in _CHECKS:
        rule_findings = checker(clean)
        per_rule[rule_id] = len(rule_findings)
        findings.extend(rule_findings)
    return {
        "per_rule_finding_counts": per_rule,
        "total_findings": sum(per_rule.values()),
        "findings": findings,
        "marker_advisories": advisories,
    }


def cli(argv=None):
    """Lint-mode CLI over file paths or globs. Always exits 0; per-file guarded."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: plain_language_check.py PATH_OR_GLOB [PATH_OR_GLOB ...]")
        return 0
    paths = []
    for arg in args:
        matched = sorted(_glob.glob(arg, recursive=True))
        paths.extend(matched if matched else [arg])
    active_rules = [rule_id for rule_id, _ in _CHECKS]
    header = ["file"] + active_rules + ["total"]
    print("\t".join(header))
    totals = {rule_id: 0 for rule_id in active_rules}
    grand_total = 0
    scanned = 0
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            result = scan(text)
        except Exception as exc:  # one unreadable file must not abort the corpus run
            print(f"{path}\tERROR: {exc}")
            continue
        scanned += 1
        counts = result["per_rule_finding_counts"]
        row = [path] + [str(counts[rule_id]) for rule_id in active_rules] + [str(result["total_findings"])]
        print("\t".join(row))
        for advisory in result["marker_advisories"]:
            print(f"{path}\tMARKER-HYGIENE: {advisory}")
        for rule_id in active_rules:
            totals[rule_id] += counts[rule_id]
        grand_total += result["total_findings"]
    summary = [f"TOTALS ({scanned} files)"] + [str(totals[r]) for r in active_rules] + [str(grand_total)]
    print("\t".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(cli())
