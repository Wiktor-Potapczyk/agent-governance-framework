"""Pure logic for wiki-citation-check.

Extracted from wiki-citation-check.py 2026-05-14 (CC-AUTOMATION-LEARN Step 1).
All functions are I/O-free except where explicitly noted (validate_source_entries
needs filesystem access to compute SHA-256 of source files; the rest are pure
string/path operations on content already in memory).

`vault_root` is passed as a function argument everywhere it is needed, never
read from a module-level constant. This makes the module testable with a
temporary directory in tests.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional


WIKI_PATH_PREFIXES = (
    "Resources/KB/",  # always wiki-layer regardless of #wiki tag
)
WIKI_BY_TAG_PREFIXES = (
    "Notes/",      # only when content carries #wiki tag
    "Projects/",   # only when path is .../archive/ AND content carries #wiki tag
)
EXCLUDE_FILES = frozenset({
    "index.md", "INDEX.md",
    "MEMORY.md", "STATE.md", "CLAUDE.md", "PROJECT.md",
})


def normalize_rel_path(rel_path: str) -> str:
    """Normalize a vault-relative path: forward slashes, no leading slash."""
    return rel_path.replace("\\", "/").lstrip("/")


def is_wiki_path_unconditional(rel_path: str) -> bool:
    """True if file is wiki-layer regardless of #wiki tag in content."""
    rel_norm = normalize_rel_path(rel_path)
    if Path(rel_norm).name in EXCLUDE_FILES:
        return False
    return any(rel_norm.startswith(p) for p in WIKI_PATH_PREFIXES)


def is_wiki_path_by_tag(rel_path: str) -> bool:
    """True if file is wiki-layer ONLY IF content carries #wiki tag.

    Caller must check has_wiki_tag(content) separately.
    """
    rel_norm = normalize_rel_path(rel_path)
    if Path(rel_norm).name in EXCLUDE_FILES:
        return False
    for prefix in WIKI_BY_TAG_PREFIXES:
        if rel_norm.startswith(prefix):
            if prefix == "Projects/" and "/archive/" not in rel_norm:
                continue
            return True
    return False


def is_wiki_path(rel_path: str) -> bool:
    """Combined check — True if path COULD be wiki-layer.

    Caller still checks has_wiki_tag for by-tag paths.
    """
    return is_wiki_path_unconditional(rel_path) or is_wiki_path_by_tag(rel_path)


def has_wiki_tag(content: str) -> bool:
    """True if content's frontmatter tags array contains 'wiki'.

    Handles both YAML forms:
    - Inline flow:     tags: [wiki, moc]
    - Multiline block: tags:
                         - wiki
                         - moc
    Token matching: strips quotes, leading '#', and whitespace, then
    compares case-insensitively to the bare string 'wiki' (exact match —
    'wiki-derived' and 'wikilink' do NOT match).
    """
    if not content.startswith("---"):
        return False
    end = content.find("\n---", 3)
    if end < 0:
        return False
    fm = content[3:end]
    lines = fm.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("tags:"):
            tagval = line.split(":", 1)[1].strip()
            if tagval.startswith("["):
                # Inline flow form: tags: [wiki, moc]
                tokens = re.split(r"[,\s]+", tagval.strip("[]"))
                for t in tokens:
                    if t.strip().strip("\"'").lstrip("#").lower() == "wiki":
                        return True
            else:
                # Multiline block-list form: scan following lines for list items
                i += 1
                while i < len(lines):
                    item_line = lines[i]
                    item_stripped = item_line.strip()
                    # Stop at a new top-level key (non-indented non-empty non-list line)
                    # or at a line that is not a list item
                    if not item_stripped:
                        i += 1
                        continue
                    if not item_stripped.startswith("-"):
                        break
                    # Extract token: strip leading '-', whitespace, quotes, '#'
                    token = item_stripped.lstrip("-").strip().strip("\"'").lstrip("#").lower()
                    if token == "wiki":
                        return True
                    i += 1
                continue  # already incremented i in the inner loop
        i += 1
    return False


def parse_source_field(content: str) -> Optional[list[dict]]:
    """Extract source: array from frontmatter. Returns list of dicts or None.

    Returns None if frontmatter is malformed (no opening or closing ---).
    Returns [] if frontmatter exists but has no source: field.
    """
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end < 0:
        return None
    fm = content[3:end]

    in_source = False
    source_lines: list[str] = []
    indent: Optional[int] = None
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

    entries: list[dict] = []
    current: dict = {}
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


def validate_source_entries(
    entries: list[dict],
    vault_root: Path,
) -> tuple[list[dict], bool]:
    """Validate source entries against vault filesystem.

    Returns (findings, has_blocking_error).

    `vault_root` is the absolute path to the vault root — source[].path is
    interpreted as vault-relative. Filesystem access happens here:
    - file existence check
    - SHA-256 computation of source bytes for drift detection
    """
    findings: list[dict] = []
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

        full_path = vault_root / path_str
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
                        "message": (
                            f"source[{i}].sha256 mismatch — committed "
                            f"{committed_hash[:8]}... but file currently "
                            f"{actual[:8]}..."
                        ),
                    })
            except OSError as e:
                findings.append({
                    "code": "HASH_COMPUTE_FAIL",
                    "severity": "warning",
                    "message": f"source[{i}].path read failed: {e}",
                })
        else:
            findings.append({
                "code": "MISSING_SHA",
                "severity": "warning",
                "message": (
                    f"source[{i}].sha256 absent — M2 crypto binding "
                    f"skipped for this entry"
                ),
            })

    return findings, has_blocking


def format_findings_message(rel_path: str, findings: list[dict], has_blocking: bool) -> str:
    """Format findings into a human-readable additionalContext message.

    Pure function — same input always produces same output.
    """
    msgs = [f"[wiki-citation-check] {rel_path}"]
    for f in findings:
        msgs.append(f"  - {f['code']} ({f['severity']}): {f['message']}")
    if has_blocking:
        msgs.append(
            "  ⚠️ Has blocking-level findings "
            "(currently advisory in v1; will block in v2 after baseline)"
        )
    return "\n".join(msgs)
