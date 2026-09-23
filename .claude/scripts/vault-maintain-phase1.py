#!/usr/bin/env python3
"""Phase 1 tag hygiene: extract tags from frontmatter + inline, build frequency map,
detect Levenshtein <=2 near-duplicates against tag-registry, flag orphans."""

import os
import re
import sys
import json
from pathlib import Path
from collections import Counter

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Inbox", "Notes", "Projects", "Resources"]
REGISTRY = VAULT / "Resources" / "KB" / "tag-registry.md"

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TAGS_INLINE_LIST_RE = re.compile(r"^tags:\s*\[([^\]]*)\]", re.MULTILINE)
TAGS_BLOCK_RE = re.compile(r"^tags:\s*\n((?:\s*-\s*[^\n]+\n)+)", re.MULTILINE)
# Non-standard but common: `tags: #a, #b` or `tags: #a #b` (no brackets, no list).
# Captures the rest of the line after `tags:` when not bracketed and not a block.
TAGS_NONSTD_RE = re.compile(r"^tags:[ \t]+(#[^\n\[]+)$", re.MULTILINE)
INLINE_TAG_RE = re.compile(r"(?<![A-Za-z0-9_/-])#([A-Za-z][A-Za-z0-9/_-]*)")

# Known intentional pairs (NOT flagged as near-dup). Pre-registered in registry.
KNOWN_PAIRS = {
    frozenset(["t6", "t7"]),  # Sequential task IDs
    frozenset(["s2a", "s2b"]),  # Stage IDs
    frozenset(["v1", "v2"]),  # Version IDs
    frozenset(["v2", "v5"]),
    frozenset(["v1", "v5"]),
    frozenset(["t1", "t6"]),
    frozenset(["t1", "t7"]),
    frozenset(["s3", "t6"]),
    frozenset(["s3", "t7"]),
    frozenset(["s3", "t1"]),
    frozenset(["s3", "v2"]),
    frozenset(["s3", "v1"]),
    frozenset(["s3", "v5"]),
    frozenset(["s3", "s2a"]),
    frozenset(["s3", "s2b"]),
    frozenset(["s3", "r3"]),
    frozenset(["t1", "v1"]),
    frozenset(["t1", "v2"]),
    frozenset(["t6", "v5"]),
    frozenset(["t1", "v5"]),
    frozenset(["t6", "v1"]),
    frozenset(["t6", "v2"]),
    frozenset(["t7", "v1"]),
    frozenset(["t7", "v2"]),
    frozenset(["t7", "v5"]),
    frozenset(["v1", "r3"]),
    frozenset(["v2", "r3"]),
    frozenset(["v5", "r3"]),
    frozenset(["t1", "r3"]),
    frozenset(["t6", "r3"]),
    frozenset(["t7", "r3"]),
    frozenset(["t1", "s2a"]),
    frozenset(["t1", "s2b"]),
    frozenset(["t6", "s2a"]),
    frozenset(["t6", "s2b"]),
    frozenset(["t7", "s2a"]),
    frozenset(["t7", "s2b"]),
    frozenset(["v1", "s2a"]),
    frozenset(["v1", "s2b"]),
    frozenset(["v2", "s2a"]),
    frozenset(["v2", "s2b"]),
    frozenset(["v5", "s2a"]),
    frozenset(["v5", "s2b"]),
    frozenset(["part-1", "part-2"]),
    frozenset(["part-1", "part-3"]),
    frozenset(["part-1", "part-4"]),
    frozenset(["part-1", "part-5"]),
    frozenset(["part-2", "part-3"]),
    frozenset(["part-2", "part-4"]),
    frozenset(["part-2", "part-5"]),
    frozenset(["part-3", "part-4"]),
    frozenset(["part-3", "part-5"]),
    frozenset(["part-4", "part-5"]),
    frozenset(["t6", "t6-rerun"]),
    frozenset(["t7", "t7-migration"]),
}


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = curr
    return prev[-1]


def parse_tags_from_frontmatter(fm: str):
    tags = []
    nonstd = False
    m = TAGS_INLINE_LIST_RE.search(fm)
    if m:
        raw = m.group(1)
        for t in raw.split(","):
            t = t.strip().strip("'\"").lstrip("#")
            if t:
                tags.append(t)
    m = TAGS_BLOCK_RE.search(fm)
    if m:
        for line in m.group(1).split("\n"):
            t = line.strip().lstrip("-").strip().strip("'\"").lstrip("#")
            if t:
                tags.append(t)
    if not tags:
        m = TAGS_NONSTD_RE.search(fm)
        if m:
            nonstd = True
            raw = m.group(1)
            # Split on commas OR whitespace; strip leading #
            for t in re.split(r"[,\s]+", raw):
                t = t.strip().lstrip("#")
                if t:
                    tags.append(t)
    return tags, nonstd


def parse_inline_tags(body: str):
    return [m.group(1) for m in INLINE_TAG_RE.finditer(body)]


def scan_file(path: Path):
    """Frontmatter-only. Inline `#tag` in markdown prose produces too many
    false positives (template placeholders, discussions of tagging, hex codes
    matched as literals). Curated tags live in YAML frontmatter."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [], False, f"read_error: {e}"
    fm_match = FRONTMATTER_RE.match(text)
    fm = fm_match.group(1) if fm_match else ""
    tags, nonstd = parse_tags_from_frontmatter(fm)
    return tags, nonstd, None


def parse_registry():
    text = REGISTRY.read_text(encoding="utf-8", errors="replace")
    rows = []
    in_table = False
    for line in text.splitlines():
        if line.startswith("| ---"):
            in_table = True
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) >= 4 and cells[0] != "Tag":
                tag = cells[0]
                try:
                    count = int(cells[1])
                except ValueError:
                    continue
                rows.append((tag, count))
        elif in_table and not line.startswith("|"):
            in_table = False
    # Pre-registered zero-usage section
    pre_registered = []
    for line in text.splitlines():
        if line.startswith("| ") and "|" in line[2:]:
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == 2 and cells[0] not in ("Tag",) and "Reserved for" not in cells[1] and not cells[1].startswith("---"):
                pre_registered.append(cells[0])
    return rows, pre_registered


def main():
    counter = Counter()
    file_count = 0
    nonstd_files = []
    for d in SCAN_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            file_count += 1
            tags, nonstd, err = scan_file(p)
            if nonstd:
                nonstd_files.append(str(p.relative_to(VAULT)).replace("\\", "/"))
            for t in tags:
                key = t.lower().rstrip("/")
                counter[key] += 1
    registry_rows, pre_registered = parse_registry()
    registry_set = {t.lower(): c for t, c in registry_rows}

    # Near-duplicate detection: pairs with Lev distance <= 2
    # Filter rules:
    #   - both tags must be >= 4 chars (short tags hit too many false positives at Lev<=2)
    #   - at least one tag must have count >= 3 (noise pair signal)
    #   - skip known intentional pairs
    keys = sorted(counter.keys())
    near_dups = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            if abs(len(a) - len(b)) > 2:
                continue
            if min(len(a), len(b)) < 4:
                continue
            if max(counter[a], counter[b]) < 3:
                continue
            if levenshtein(a, b) <= 2:
                if frozenset([a, b]) in KNOWN_PAIRS:
                    continue
                # Skip if one is a substring of a project-scoped path (e.g. project/x vs y)
                if "/" in a and "/" in b:
                    aa = a.split("/")[-1]
                    bb = b.split("/")[-1]
                    if levenshtein(aa, bb) > 2:
                        continue
                near_dups.append((a, counter[a], b, counter[b]))

    # Orphan detection: tags in registry with count 0 in current scan
    # Exclude pre-registered intentional zeros.
    pre_set = set(t.lower() for t in pre_registered)
    orphans = []
    for tag, declared_count in registry_rows:
        observed = counter.get(tag.lower(), 0)
        if observed == 0 and tag.lower() not in pre_set:
            orphans.append((tag, declared_count))

    # Stale-count detection: registry count diverges from current
    stale = []
    for tag, declared in registry_rows:
        observed = counter.get(tag.lower(), 0)
        if observed != declared and observed > 0:
            diff = observed - declared
            if abs(diff) >= 1:
                stale.append((tag, declared, observed, diff))

    # New tags: in scan, not in registry, count >= 1
    new_tags = []
    for tag, count in sorted(counter.items(), key=lambda x: -x[1]):
        if tag not in registry_set and tag not in pre_set:
            new_tags.append((tag, count))

    out = {
        "file_count": file_count,
        "unique_tags": len(counter),
        "total_uses": sum(counter.values()),
        "near_dups": near_dups,
        "orphans": orphans,
        "stale_counts": stale,
        "new_tags": new_tags,
        "nonstd_files": nonstd_files,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
