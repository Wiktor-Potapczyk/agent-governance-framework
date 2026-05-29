#!/usr/bin/env python3
"""wiki-citation-check.py — PostToolUse Write hook (M2 Layer 2).

Karpathy LLM-Wiki adoption fabrication mitigation. Validates that any Write to a
wiki-layer file (Resources/KB/, Notes/ with #wiki tag, Projects/*/archive/ with
#wiki tag) carries a valid `source:` frontmatter field with SHA-256 hash that
matches the cited source file's current bytes.

Behavior:
- Activates on Write|Edit tool to wiki-layer paths AND content contains #wiki tag
- Reads written content's frontmatter
- Validates source: field present + non-empty
- For each source[].path: file exists on disk
- For each source[].sha256: hash matches file content (truth gate, not just format gate)
- Mismatches → emit additionalContext warning (advisory; not blocking on first iteration)
- Logs all decisions to .claude/hooks/aggregates/wiki-citation-violations.jsonl

Exit codes:
- 0 = pass
- 0 with additionalContext = soft warning
- 2 = hard block (currently DISABLED — too risky for v1; activate after empirical baseline)

Schema:
- input: PostToolUse hook payload via stdin
- output: stdout JSON {hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: str}}

Refactored 2026-05-14 (CC-AUTOMATION-LEARN Step 1): pure logic now lives in
`_wiki_citation_logic.py`. This file is the thin I/O wrapper — stdin parsing,
filesystem reads of the written file, governance-log writing, stdout emission.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Make sibling logic module importable
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)

from _wiki_citation_logic import (  # noqa: E402
    EXCLUDE_FILES,
    format_findings_message,
    has_wiki_tag,
    is_wiki_path,
    is_wiki_path_by_tag,
    is_wiki_path_unconditional,
    parse_source_field,
    validate_source_entries,
)

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
LOG = VAULT / ".claude" / "hooks" / "aggregates" / "wiki-citation-violations.jsonl"


def log_decision(file_path, findings, blocked):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "file": file_path,
            "findings": findings,
            "blocked": blocked,
        }
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    try:
        rel_path = str(Path(file_path).resolve().relative_to(VAULT)).replace("\\", "/")
    except Exception:
        return 0

    if not is_wiki_path(rel_path):
        return 0

    try:
        content = Path(file_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0

    # For unconditional wiki paths (Resources/KB/), check applies regardless of tag.
    # For by-tag paths (Notes/, Projects/*/archive/), require #wiki tag.
    if is_wiki_path_by_tag(rel_path) and not is_wiki_path_unconditional(rel_path):
        if not has_wiki_tag(content):
            return 0
    elif is_wiki_path_unconditional(rel_path):
        # KB files SHOULD have #wiki tag; missing it gets flagged separately by validate
        # but proceed with check anyway (the file is wiki-layer by location)
        pass

    entries = parse_source_field(content)
    findings, has_blocking = validate_source_entries(entries or [], VAULT)

    log_decision(rel_path, findings, blocked=False)

    if findings:
        msg = format_findings_message(rel_path, findings, has_blocking)
        try:
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": msg,
                }
            }
            print(json.dumps(out))
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
