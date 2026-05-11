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
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def _find_workspace_root() -> Path:
    """Walk up from this file's directory until we find CLAUDE.md (workspace root).

    Falls back to the directory one level above hooks/ (the conventional layout
    is <root>/hooks/<this-file> or <root>/.claude/hooks/<this-file>).
    """
    here = Path(os.path.abspath(__file__)).parent
    candidate = here
    for _ in range(8):  # cap at 8 levels to avoid runaway
        if (candidate / "CLAUDE.md").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    # Fallback: hooks/ sits one level inside workspace root
    return here.parent


WORKSPACE = _find_workspace_root()
LOG = WORKSPACE / ".claude" / "hooks" / "aggregates" / "wiki-citation-violations.jsonl"
WIKI_PATH_PREFIXES = [
    "Resources/KB/",  # always wiki layer, regardless of #wiki tag
]
WIKI_BY_TAG_PREFIXES = [
    "Notes/",      # only when content carries #wiki tag (user's own untagged notes are raw)
    "Projects/",   # only when path is .../archive/ AND content carries #wiki tag
]
EXCLUDE_FILES = {"index.md", "INDEX.md", "MEMORY.md", "STATE.md", "CLAUDE.md", "PROJECT.md"}


def is_wiki_path_unconditional(rel_path):
    """Returns True if file is wiki-layer regardless of #wiki tag in content."""
    rel_norm = rel_path.replace("\\", "/").lstrip("/")
    if Path(rel_norm).name in EXCLUDE_FILES:
        return False
    return any(rel_norm.startswith(p) for p in WIKI_PATH_PREFIXES)


def is_wiki_path_by_tag(rel_path):
    """Returns True if file is wiki-layer ONLY IF content carries #wiki tag.
    Caller must check has_wiki_tag(content) separately."""
    rel_norm = rel_path.replace("\\", "/").lstrip("/")
    if Path(rel_norm).name in EXCLUDE_FILES:
        return False
    for prefix in WIKI_BY_TAG_PREFIXES:
        if rel_norm.startswith(prefix):
            if prefix == "Projects/" and "/archive/" not in rel_norm:
                continue
            return True
    return False


def is_wiki_path(rel_path):
    """Combined check — returns True if path COULD be wiki-layer (unconditional OR by-tag).
    Caller still checks has_wiki_tag for by-tag paths."""
    return is_wiki_path_unconditional(rel_path) or is_wiki_path_by_tag(rel_path)


def has_wiki_tag(content):
    """Check if content's frontmatter tags array contains 'wiki'."""
    if not content.startswith("---"):
        return False
    end = content.find("\n---", 3)
    if end < 0:
        return False
    fm = content[3:end]
    for line in fm.split("\n"):
        if line.strip().startswith("tags:"):
            tagval = line.split(":", 1)[1].strip().strip("[]")
            tokens = re.split(r"[,\s]+", tagval)
            for t in tokens:
                if t.strip().lstrip("#").lower() == "wiki":
                    return True
    return False


def parse_source_field(content):
    """Extract source: array from frontmatter. Returns list of dicts or None."""
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end < 0:
        return None
    fm = content[3:end]

    in_source = False
    source_lines = []
    indent = None
    for line in fm.split("\n"):
        if re.match(r"^source\s*:", line):
            in_source = True
            continue
        if in_source:
            stripped = line.lstrip()
            if not stripped:
                continue
            this_indent = len(line) - len(stripped)
            if indent is None and this_indent > 0:
                indent = this_indent
            if this_indent == 0 and stripped:
                in_source = False
                continue
            source_lines.append(line)

    if not source_lines:
        return []

    entries = []
    current = {}
    for line in source_lines:
        stripped = line.strip()
        m = re.match(r"^-\s*(.+)$", stripped)
        if m:
            if current:
                entries.append(current)
            current = {}
            field_match = re.match(r"^(\w+)\s*:\s*(.+)$", m.group(1))
            if field_match:
                key = field_match.group(1).strip()
                val = field_match.group(2).strip().strip('"').strip("'")
                current[key] = val
        else:
            field_match = re.match(r"^(\w+)\s*:\s*(.+)$", stripped)
            if field_match:
                key = field_match.group(1).strip()
                val = field_match.group(2).strip().strip('"').strip("'")
                current[key] = val
    if current:
        entries.append(current)
    return entries


def validate_source_entries(entries):
    """Return (findings, has_blocking_error). Findings is list of dicts."""
    findings = []
    has_blocking = False

    if not entries:
        findings.append({
            "code": "MISSING_SOURCE",
            "severity": "error",
            "message": "wiki page has no source: entries",
        })
        return findings, True

    for i, entry in enumerate(entries):
        path_str = entry.get("path", "")
        if not path_str:
            findings.append({
                "code": "EMPTY_SOURCE_PATH",
                "severity": "error",
                "message": f"source[{i}] missing path field",
            })
            has_blocking = True
            continue

        full_path = WORKSPACE / path_str
        if not full_path.exists():
            findings.append({
                "code": "ORPHAN_CITATION",
                "severity": "error",
                "message": f"source[{i}].path '{path_str}' does not exist on disk",
            })
            has_blocking = True
            continue

        committed_hash = entry.get("sha256", "")
        if committed_hash:
            try:
                actual = hashlib.sha256(full_path.read_bytes()).hexdigest()
                if actual != committed_hash:
                    findings.append({
                        "code": "SOURCE_DRIFT",
                        "severity": "warning",
                        "message": f"source[{i}].sha256 mismatch — committed {committed_hash[:8]}... but file currently {actual[:8]}...",
                    })
            except Exception as e:
                findings.append({
                    "code": "HASH_COMPUTE_FAIL",
                    "severity": "warning",
                    "message": f"source[{i}].path read failed: {e}",
                })
        else:
            findings.append({
                "code": "MISSING_SHA",
                "severity": "warning",
                "message": f"source[{i}].sha256 absent — M2 crypto binding skipped for this entry",
            })

    return findings, has_blocking


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
        rel_path = str(Path(file_path).resolve().relative_to(WORKSPACE)).replace("\\", "/")
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
    findings, has_blocking = validate_source_entries(entries or [])

    log_decision(rel_path, findings, blocked=False)

    if findings:
        msgs = [f"[wiki-citation-check] {rel_path}"]
        for f in findings:
            msgs.append(f"  - {f['code']} ({f['severity']}): {f['message']}")
        if has_blocking:
            msgs.append("  Has blocking-level findings (currently advisory in v1; will block in v2 after baseline)")
        msg = "\n".join(msgs)

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
