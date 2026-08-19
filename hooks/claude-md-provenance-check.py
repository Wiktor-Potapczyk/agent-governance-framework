r"""
CLAUDE.md Provenance Check (Guard A) - PostToolUse Write|Edit hook  [warn-only]

Mechanism A countermeasure from the caveman postmortem
(Projects/your-project/work/2026-08-10-caveman-postmortem.md):
the caveman-lite rule survived four months while the pointer to its own origin
died, because CLAUDE.md requires no inline provenance the way wiki pages
require a source: field. This guard extends that discipline to the
constitution: a rule-shaped change to the vault-root CLAUDE.md with no inline
origin citation gets a one-line warning.

SCOPE: the vault-root CLAUDE.md ONLY (exact path match against this vault's
  root). Nested CLAUDE.md files (framework-repo/, other repos) are out of
  scope.

HEURISTIC, precision-first (the prose-slop-check calibration lesson:
  deliberate exclusions over recall). Examined text: new_string for Edit,
  full content for Write.
  Rule-shaped signal (any of):
    - a new markdown heading line
    - a "CRITICAL RULE" marker
    - a bold rule-statement line carrying a modal rule verb
      (never / always / must / mandatory / do not / required)
  Provenance signal (any of, in the same added text):
    - a [[wikilink]]
    - a feedback_* / finding_* / decision_* / reference_* memo name
    - a Projects/**/work/ path
    - a parenthetical date-stamped origin such as (2026-08-11, ...)
  Rule-shaped present AND provenance absent -> one-line WARN. Everything else
  is silent. Trivial maintenance edits (typo, count update) carry no
  rule-shaped signal and stay silent.

SEVERITY: WARN only (stderr + exit 0). NEVER blocks. False positives on
  maintenance edits are cheap by design; enforcement stays advisory.

FAIL-OPEN: malformed payload or any internal error exits 0.

Built by the plain-language Stage 1 build (2026-08-11); spec:
.claude/plain-language-rules.md (Guards section). Tests:
test_claude_md_provenance_check.py.

EXIT CODES
  0 = always. This hook never blocks.
"""

import json
import os
import re
import sys

VAULT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_RULE_SHAPED_RES = [
    re.compile(r"(?m)^#{1,4}\s+\S"),
    re.compile(r"CRITICAL RULE", re.IGNORECASE),
    re.compile(
        r"(?m)^\s*(?:[-*]\s+)?\*\*[^*\n]+\*\*.*?\b(?:never|always|must|mandatory|do not|don't|required)\b",
        re.IGNORECASE,
    ),
]
_PROVENANCE_RES = [
    re.compile(r"\[\[[^\]\n]+\]\]"),
    re.compile(r"\b(?:feedback|finding|decision|reference)_[a-z0-9_]+", re.IGNORECASE),
    re.compile(r"Projects[\\/][^\s\\/]+[\\/]work[\\/]", re.IGNORECASE),
    re.compile(r"\(20\d{2}-\d{2}-\d{2}[^)]*\)"),
]


def is_vault_root_claude_md(file_path):
    if not file_path:
        return False
    target = os.path.normcase(os.path.normpath(os.path.join(VAULT_ROOT, "CLAUDE.md")))
    candidate = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))
    return candidate == target


def rule_shaped(text):
    return any(p.search(text) for p in _RULE_SHAPED_RES)


def has_provenance(text):
    return any(p.search(text) for p in _PROVENANCE_RES)


def _log_fire(payload, decision, detail=None):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire, session_from
        log_fire("claude-md-provenance-check", decision=decision, detail=detail,
                 session=session_from(payload))
    except Exception:
        pass


def _main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return 0
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or {}
    if not is_vault_root_claude_md(tool_input.get("file_path") or ""):
        return 0

    added = tool_input.get("new_string")
    if added is None:
        added = tool_input.get("content") or ""
    if not added:
        return 0

    if rule_shaped(added) and not has_provenance(added):
        sys.stderr.write(
            "[claude-md-provenance-check WARN] behavioral-rule change without a "
            "one-line origin citation; add the originating decision or research "
            "file inline (a [[wikilink]], a feedback_*/finding_*/decision_*/"
            "reference_* memo name, a Projects/*/work/ path, or a dated "
            "parenthetical origin). Mechanism A countermeasure; see "
            ".claude/plain-language-rules.md, Guards. (advisory - edit was kept.)\n"
        )
        _log_fire(payload, "warn", "rule-shaped change without provenance")
        return 0

    _log_fire(payload, "allow")
    return 0


def main():
    try:
        return _main()
    except Exception:
        return 0  # fail-open


if __name__ == "__main__":
    sys.exit(main())
