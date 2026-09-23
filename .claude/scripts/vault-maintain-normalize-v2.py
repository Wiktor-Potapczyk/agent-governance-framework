#!/usr/bin/env python3
"""vault-maintain-normalize-v2.py

Normalize frontmatter `tags: [#a, #b]` (bracket form with hash prefixes) to
`tags: [a, b]` (bracket form without hashes). This is the v2 normalizer:
vault-maintain-normalize-tags.py handles the no-bracket → bracket conversion;
this script handles the remaining bracket-with-hashes form.

R7 mitigation: only processes lines that actually contain `#` inside the
bracket — lines already in clean form are untouched.

Idempotent: re-running after --apply produces 0 rewrites.

Usage:
  python vault-maintain-normalize-v2.py            # dry-run (default)
  python vault-maintain-normalize-v2.py --apply    # write to disk
"""

import argparse
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Inbox", "Notes", "Projects", "Resources", "Clippings"]

# Paths containing these fragments are skipped entirely.
EXEMPT_SUBSTRINGS = ["source-data", "source-assets", "/repo/", "/framework-repo/"]

# Frontmatter block regex: captures the content between the --- delimiters.
FM_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n)", re.DOTALL)

# Match a `tags: [...]` line inside frontmatter.
# Captures the content inside the brackets.
TAGS_BRACKET_RE = re.compile(r"^(tags:\s*\[)([^\]]*?)(\]\s*)$", re.MULTILINE)


def is_exempt(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    return any(s in norm for s in EXEMPT_SUBSTRINGS)


def normalize_bracket_tags(captured: str) -> tuple[str, bool]:
    """Strip leading `#` from each token inside a `tags: [...]` value.

    Returns (new_value, changed). Only called when captured contains `#`.
    Tokens are split on commas; whitespace is preserved around the join.
    """
    tokens = [t.strip() for t in captured.split(",")]
    new_tokens = [t.lstrip("#") for t in tokens if t]
    new_value = ", ".join(new_tokens)
    changed = new_value != captured.strip()
    return new_value, changed


def process_file(path: Path, apply: bool) -> dict | None:
    """Process one file. Returns change record if file would change, else None."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm_m = FM_RE.match(text)
    if not fm_m:
        return None  # no frontmatter

    fm_open = fm_m.group(1)    # "---\n"
    fm_block = fm_m.group(2)   # content between delimiters
    fm_close = fm_m.group(3)   # "\n---\n"
    body = text[fm_m.end():]   # everything after closing ---

    # Find the tags line inside frontmatter
    tags_m = TAGS_BRACKET_RE.search(fm_block)
    if not tags_m:
        return None  # no bracket tags line

    captured = tags_m.group(2)  # content inside [...]

    # R7 mitigation: skip if no # present — already clean form
    if "#" not in captured:
        return None

    new_value, changed = normalize_bracket_tags(captured)
    if not changed:
        return None  # nothing to do (e.g. only stray # in an edge case)

    old_line = tags_m.group(0).rstrip()
    new_line = f"{tags_m.group(1)}{new_value}{tags_m.group(3)}".rstrip()

    # Rebuild frontmatter block with the replacement
    new_fm_block = fm_block[: tags_m.start(2)] + new_value + fm_block[tags_m.end(2) :]
    new_fm_with_delims = f"{fm_open}{new_fm_block}{fm_close}"
    prefix = text[: fm_m.start()]  # almost always empty
    new_text = prefix + new_fm_with_delims + body

    # Body-integrity assertion: body portion must be unchanged
    reconstructed_body = new_text[len(prefix) + len(new_fm_with_delims) :]
    if reconstructed_body != body:
        raise RuntimeError(
            f"Body-integrity FAIL (pre-write) on {path}: "
            f"original body len={len(body)}, reconstructed len={len(reconstructed_body)}"
        )

    if apply:
        path.write_text(new_text, encoding="utf-8", newline="\n")

        # Post-write body-integrity check
        written = path.read_text(encoding="utf-8", errors="replace")
        written_fm_m = FM_RE.match(written)
        if not written_fm_m:
            raise RuntimeError(f"Post-write FM parse failed on {path}")
        written_body = written[written_fm_m.end():]
        if written_body != body:
            raise RuntimeError(
                f"Body-integrity FAIL (post-write) on {path}: "
                f"original len={len(body)}, written len={len(written_body)}"
            )

    return {
        "path": str(path.relative_to(VAULT)).replace("\\", "/"),
        "old": old_line,
        "new": new_line,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Normalize tags: [#a, #b] → tags: [a, b] in frontmatter."
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to disk. Default is dry-run.",
    )
    args = ap.parse_args()
    dry_run = not args.apply

    if dry_run:
        print("DRY-RUN mode — pass --apply to write files.\n")

    candidates: list[Path] = []
    for dir_name in SCAN_DIRS:
        scan_root = VAULT / dir_name
        if not scan_root.exists():
            continue
        for fp in sorted(scan_root.rglob("*.md")):
            rel = str(fp.relative_to(VAULT)).replace("\\", "/")
            if is_exempt(rel):
                continue
            candidates.append(fp)

    matched: list[dict] = []
    errors = 0

    for fp in candidates:
        try:
            result = process_file(fp, apply=False)  # always dry-scan first
        except RuntimeError as exc:
            print(f"INTEGRITY ERROR on {fp}: {exc}", file=sys.stderr)
            errors += 1
            continue
        except Exception as exc:
            print(f"ERROR on {fp}: {exc}", file=sys.stderr)
            errors += 1
            continue
        if result:
            matched.append(result)

    print(f"Scanned: {len(candidates)} files")
    print(f"Would rewrite: {len(matched)} files")
    if errors:
        print(f"Errors during scan: {errors}")
    print()

    if matched:
        print("=== Sample (first 8) ===")
        for d in matched[:8]:
            print(f"  {d['path']}")
            print(f"    - {d['old']}")
            print(f"    + {d['new']}")
            print()

    if not args.apply:
        return

    print("=== APPLYING ===")
    applied = 0
    apply_errors = 0
    for d in matched:
        fp = VAULT / d["path"]
        try:
            result = process_file(fp, apply=True)
            if result:
                applied += 1
                print(f"  WROTE: {d['path']}")
        except RuntimeError as exc:
            print(f"INTEGRITY ERROR (apply) on {d['path']}: {exc}", file=sys.stderr)
            apply_errors += 1
        except Exception as exc:
            print(f"ERROR (apply) on {d['path']}: {exc}", file=sys.stderr)
            apply_errors += 1

    print(f"Applied: {applied} files")
    if apply_errors:
        print(f"Apply errors: {apply_errors}", file=sys.stderr)

    # Idempotency verify
    print()
    print("=== Idempotency verify (re-scan) ===")
    leftover = []
    for fp in candidates:
        try:
            result = process_file(fp, apply=False)
            if result:
                leftover.append(result["path"])
        except Exception:
            pass

    if leftover:
        print(f"FAIL: {len(leftover)} files still have hash-prefixed bracket tags after apply")
        for f in leftover[:5]:
            print(f"  {f}")
        sys.exit(1)
    else:
        print("PASS: 0 files match hash-bracket pattern after apply")


if __name__ == "__main__":
    main()
