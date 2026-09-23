#!/usr/bin/env python3
"""Normalize frontmatter `tags: #a, #b` (no-bracket form) to `tags: [a, b]`
(YAML-compliant). Idempotent: rerunning produces no diff.

Usage:
  python vault-maintain-normalize-tags.py             # dry-run, prints diffs
  python vault-maintain-normalize-tags.py --apply     # writes to disk
  python vault-maintain-normalize-tags.py --sample N  # dry-run, first N files only
"""

import argparse
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Inbox", "Notes", "Projects", "Resources"]
EXEMPT_SUBSTRINGS = ["source-data", "source-assets", "/repo/", "/framework-repo/"]

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
# Match `tags:` followed by space then `#tag` content (no opening bracket).
# Captures the value portion after `tags: `.
NONSTD_TAGS_RE = re.compile(r"^(tags:[ \t]+)(#[^\n\[]+)$", re.MULTILINE)


def normalize_tags_value(raw: str) -> str:
    """Convert `#a, #b, #c` (or `#a #b #c`, mixed) to `[a, b, c]`."""
    parts = re.split(r"[,\s]+", raw.strip())
    tags = [p.lstrip("#").strip() for p in parts if p.strip()]
    return "[" + ", ".join(tags) + "]"


def is_exempt(rel_path: str) -> bool:
    rel_norm = rel_path.replace("\\", "/")
    return any(s in rel_norm for s in EXEMPT_SUBSTRINGS)


def process_file(path: Path, apply: bool) -> dict | None:
    """Returns dict with diff info if file would change, else None."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        return None
    fm = fm_match.group(0)  # full ---...--- block including delimiters
    fm_body = fm_match.group(1)  # inner content
    m = NONSTD_TAGS_RE.search(fm_body)
    if not m:
        return None
    old_line = m.group(0)
    prefix = m.group(1)
    raw_value = m.group(2)
    new_value = normalize_tags_value(raw_value)
    new_line = prefix + new_value
    new_fm_body = NONSTD_TAGS_RE.sub(prefix + new_value, fm_body, count=1)
    new_fm = "---\n" + new_fm_body + "\n---\n"
    new_text = new_fm + text[fm_match.end():]
    if apply:
        path.write_text(new_text, encoding="utf-8", newline="\n")
    return {
        "path": str(path.relative_to(VAULT)).replace("\\", "/"),
        "old": old_line,
        "new": new_line,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes to disk")
    ap.add_argument("--sample", type=int, default=0, help="Dry-run first N candidates only")
    args = ap.parse_args()

    candidates: list[Path] = []
    for d in SCAN_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            if is_exempt(rel):
                continue
            candidates.append(p)

    diffs = []
    for p in candidates:
        result = process_file(p, apply=False)  # always dry-run first
        if result:
            diffs.append(result)

    if args.sample:
        diffs = diffs[: args.sample]

    print(f"Scanned: {len(candidates)} files")
    print(f"Would normalize: {len(diffs)} files")
    print()
    print("=== Diff sample (first 8) ===")
    for d in diffs[:8]:
        print(f"  {d['path']}")
        print(f"    - {d['old']}")
        print(f"    + {d['new']}")
        print()

    if args.apply:
        print("=== APPLYING ===")
        applied = 0
        for d in diffs:
            p = VAULT / d["path"]
            res = process_file(p, apply=True)
            if res:
                applied += 1
        print(f"Applied: {applied} files")
        # Idempotency check
        print()
        print("=== Idempotency verify (re-scan) ===")
        leftover = []
        for d in diffs:
            p = VAULT / d["path"]
            res = process_file(p, apply=False)
            if res:
                leftover.append(d["path"])
        if leftover:
            print(f"FAIL: {len(leftover)} files still match nonstd pattern after apply")
            for f in leftover[:5]:
                print(f"  {f}")
            sys.exit(1)
        else:
            print("PASS: 0 files match nonstd pattern after apply")


if __name__ == "__main__":
    main()
