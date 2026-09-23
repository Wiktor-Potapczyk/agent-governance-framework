#!/usr/bin/env python3
"""Tag registry rebuild. Preserves scope + first-used columns from existing
registry where possible; computes them for new tags. Updates counts to current
post-normalization, post-merge state.

Usage:
  python vault-maintain-registry-rebuild.py             # dry-run, prints summary
  python vault-maintain-registry-rebuild.py --apply     # writes tag-registry.md
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from datetime import date

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Inbox", "Notes", "Projects", "Resources"]
EXEMPT_SUBSTRINGS = ["source-data", "source-assets", "/repo/", "/framework-repo/"]
REGISTRY = VAULT / "Resources" / "KB" / "tag-registry.md"

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TAGS_ARRAY_RE = re.compile(r"^tags:\s*\[([^\]]*)\]", re.MULTILINE)
TAGS_BLOCK_RE = re.compile(r"^tags:\s*\n((?:\s*-\s*[^\n]+\n)+)", re.MULTILINE)
DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def is_exempt(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    return any(s in norm for s in EXEMPT_SUBSTRINGS)


def parse_tags_from_fm(fm: str) -> list[str]:
    tags = []
    m = TAGS_ARRAY_RE.search(fm)
    if m:
        for t in m.group(1).split(","):
            t = t.strip().strip("'\"").lstrip("#")
            if t:
                tags.append(t)
    m = TAGS_BLOCK_RE.search(fm)
    if m:
        for line in m.group(1).splitlines():
            t = line.strip().lstrip("-").strip().strip("'\"").lstrip("#")
            if t:
                tags.append(t)
    return tags


def parse_existing_registry(path: Path) -> tuple[dict, list[str], str, str]:
    """Returns (tag_metadata_dict, pre_registered_tag_list, header_block, footer_block).
    tag_metadata_dict: tag -> (scope, first_used_note)
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    # Find boundaries
    table_start = None
    table_end = None
    for i, line in enumerate(lines):
        if line.startswith("| Tag") or line.startswith("|Tag"):
            table_start = i
        elif table_start is not None and table_end is None:
            if line.startswith("|"):
                continue
            table_end = i
            break
    if table_end is None:
        table_end = len(lines)

    header_lines = lines[:table_start]  # incl frontmatter + intro
    footer_lines = lines[table_end:]    # incl --- + pre-registered section

    metadata = {}
    for line in lines[table_start + 2 : table_end]:  # skip header row + separator
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) >= 4:
            tag, _count, scope, first_used = cells[0], cells[1], cells[2], cells[3]
            metadata[tag] = (scope, first_used)

    pre_registered = []
    in_pre = False
    for line in footer_lines:
        if line.startswith("|") and "Reserved for" not in line and not line.startswith("| Tag") and not line.startswith("|---"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) == 2 and cells[0]:
                pre_registered.append(cells[0])
        if "Pre-registered" in line:
            in_pre = True

    return metadata, pre_registered, "\n".join(header_lines), "\n".join(footer_lines)


def infer_scope(tag: str) -> str:
    if tag.startswith("project/"):
        return "project-scoped"
    if tag in {"meta", "moc", "tag-registry", "vault-governance", "vault-design", "vault"}:
        return "vault-governance"
    if tag in {"daily", "daily-log"}:
        return "Daily Notes/"
    return "cross-project"


def get_file_date(path: Path) -> str | None:
    """Get frontmatter date or fall back to filename date prefix."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    fm_m = FM_RE.match(text)
    if fm_m:
        d_m = DATE_RE.search(fm_m.group(1))
        if d_m:
            return d_m.group(1)
    # filename date prefix
    name = path.name
    fn_m = re.match(r"(\d{4}-\d{2}-\d{2})", name)
    if fn_m:
        return fn_m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    # Scan all files: tag -> [(date, rel_path)]
    tag_files: dict[str, list[tuple[str, str]]] = defaultdict(list)
    counter: Counter = Counter()
    file_count = 0

    for d in SCAN_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            if is_exempt(rel):
                continue
            file_count += 1
            text = p.read_text(encoding="utf-8", errors="replace")
            fm_m = FM_RE.match(text)
            fm_body = fm_m.group(1) if fm_m else ""
            tags = parse_tags_from_fm(fm_body)
            file_date = get_file_date(p)
            for t in tags:
                key = t.lower().rstrip("/")
                counter[key] += 1
                if file_date:
                    tag_files[key].append((file_date, rel))

    print(f"Scanned: {file_count} files")
    print(f"Unique tags: {len(counter)}")
    print(f"Total uses: {sum(counter.values())}")
    print()

    # Load existing metadata
    metadata, pre_registered, header, footer = parse_existing_registry(REGISTRY)
    print(f"Existing registry: {len(metadata)} tags + {len(pre_registered)} pre-registered")
    print()

    # Build new rows
    pre_reg_lower = {t.lower() for t in pre_registered}

    rows = []
    for tag, count in counter.most_common():
        if tag in pre_reg_lower:
            continue  # pre-registered handled separately
        meta = metadata.get(tag)
        if meta:
            scope, first_used = meta
        else:
            scope = infer_scope(tag)
            files = tag_files.get(tag, [])
            files.sort(key=lambda x: x[0])  # earliest date first
            first_used = files[0][1] if files else "(unknown)"
        rows.append((tag, count, scope, first_used))

    # Orphans (in registry, current count 0) — keep entries but mark count 0
    for tag, (scope, first_used) in metadata.items():
        if tag not in counter and tag not in pre_reg_lower:
            rows.append((tag, 0, scope, first_used))

    # Sort by count desc, then tag asc
    rows.sort(key=lambda r: (-r[1], r[0]))

    # Compute column widths
    tag_w = max(len("Tag"), max(len(r[0]) for r in rows))
    count_w = max(len("Count"), max(len(str(r[1])) for r in rows))
    scope_w = max(len("Scope"), max(len(r[2]) for r in rows))
    file_w = max(len("First-used note"), max(len(r[3]) for r in rows))

    # Build markdown table
    table_lines = []
    table_lines.append(f"| {'Tag':<{tag_w}} | {'Count':<{count_w}} | {'Scope':<{scope_w}} | {'First-used note':<{file_w}} |")
    table_lines.append(f"| {'-' * tag_w} | {'-' * count_w} | {'-' * scope_w} | {'-' * file_w} |")
    for tag, count, scope, fu in rows:
        table_lines.append(f"| {tag:<{tag_w}} | {count:<{count_w}} | {scope:<{scope_w}} | {fu:<{file_w}} |")

    # Reconstruct full file
    today = date.today().isoformat()
    new_text_parts = [header.rstrip(), "", "\n".join(table_lines), "", footer.lstrip()]
    new_text = "\n".join(new_text_parts).rstrip() + "\n"

    # Update frontmatter `date:` to today
    new_text = re.sub(
        r"^(date:\s*)\d{4}-\d{2}-\d{2}",
        rf"\g<1>{today}",
        new_text,
        count=1,
        flags=re.MULTILINE,
    )

    # Stats
    new_count = sum(1 for r in rows if metadata.get(r[0]) is None)
    orphan_count = sum(1 for r in rows if r[1] == 0)
    print(f"New tags added: {new_count}")
    print(f"Orphans (count=0): {orphan_count}")
    print(f"Total rows in new table: {len(rows)}")

    if args.apply:
        REGISTRY.write_text(new_text, encoding="utf-8", newline="\n")
        print()
        print(f"Written: {REGISTRY}")
    else:
        print()
        print("(dry-run — pass --apply to write)")


if __name__ == "__main__":
    main()
