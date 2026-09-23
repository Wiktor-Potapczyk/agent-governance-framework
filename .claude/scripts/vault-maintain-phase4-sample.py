#!/usr/bin/env python3
"""vault-maintain-phase4-sample.py

Generate a Phase 4 summary-candidate sample report for human review.

For each input markdown file:
  - Skip if frontmatter already contains a `summary:` field (idempotent).
  - Extract H1 title (fallback: filename stem).
  - Extract first prose paragraph from body, skipping tables, fenced code,
    HTML comments, list items, and other non-prose blocks.
  - Strip inline markdown from the paragraph.
  - Concatenate H1 + " " + stripped paragraph; truncate at 280 chars on a
    word boundary.
  - Classify body shape: prose | table | list | code | short | no-h1 | mixed.

Outputs a single Obsidian-compatible markdown file at --out with:
  - One `##` section per input file (with verdict placeholder or skip note).
  - Footer with reviewer instructions.

Usage:
    python vault-maintain-phase4-sample.py \\
        --files "path/a.md,path/b.md" \\
        --out "Projects/Vault-Maintenance/work/YYYY-MM-DD-phase4-sample.md" \\
        --date 2026-05-07      # optional; defaults to today

Paths in --files are resolved against VAULT_ROOT if not absolute.
Pure read on source files; only write is --out path.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]

# Files excluded by basename — never generate summaries for structural/infra notes.
# README.md is INTENTIONALLY OMITTED: Resources/KB/README.md scored GOOD in prior sample.
EXCLUDE_BASENAMES = {"STATE.md", "PROJECT.md", "task_plan.md", "MEMORY.md", "SKILL.md", "CLAUDE.md"}
# Files excluded by path fragment — archive dirs and MOC files that aren't content.
EXCLUDE_PATH_FRAGMENTS = ["/archive/", "/Resources/KB/moc-"]

# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

_FM_DELIM = re.compile(r"^---\s*$", re.MULTILINE)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal key: value frontmatter scanner. No PyYAML dependency.

    Returns (fields_dict, body_str). body_str is everything after the closing
    `---` delimiter. If no valid frontmatter block is found, returns ({}, text).
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != "---":
        return {}, text

    fields: dict[str, str] = {}
    close_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == "---":
            close_idx = i
            break
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*):\s*(.*)", line)
        if m:
            fields[m.group(1).lower()] = m.group(2).strip()

    if close_idx is None:
        return {}, text

    body = "".join(lines[close_idx + 1 :])
    return fields, body


def has_summary(fields: dict) -> bool:
    """Return True if the frontmatter already contains a `summary:` key."""
    return "summary" in fields


# ---------------------------------------------------------------------------
# H1 extraction
# ---------------------------------------------------------------------------

_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def extract_h1(body: str) -> tuple[str | None, int | None]:
    """Return (title_text, line_index) for the first H1 in body.

    Line index is 0-based into body.splitlines(). Returns (None, None) if
    no H1 is found.
    """
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip(), idx
    return None, None


# ---------------------------------------------------------------------------
# First prose paragraph extraction
# ---------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\|")
_FENCE_START_RE = re.compile(r"^```")
_HTML_COMMENT_RE = re.compile(r"^<!--")
_LIST_ITEM_RE = re.compile(r"^(\s*[-*+]|\s*\d+\.)\s")
_HEADING_RE = re.compile(r"^#{1,6}\s")
_BLOCKQUOTE_RE = re.compile(r"^>")


def _is_fence_line(line: str) -> bool:
    return bool(_FENCE_START_RE.match(line))


def extract_first_prose_paragraph(
    body: str, h1_line_index: int | None
) -> tuple[str, str]:
    """Scan body for the first prose paragraph after h1_line_index.

    Returns (paragraph_text, shape).

    Shape is determined by dominant-shape line counting over ALL non-blank,
    non-skipped lines in the body (not first-prose-wins). Counts:
      n_table — lines matching ^\\s*\\|
      n_list  — lines matching ^\\s*[-*]\\s+ OR ^\\s*\\d+\\.\\s+
      n_code  — lines inside fenced code blocks (between ``` markers)
      n_prose — everything else non-blank, non-skipped, non-separator

    Shape assignment rules (in priority order):
      1. no-h1  — h1_line_index is None (overrides all counts)
      2. mixed  — no class exceeds 60% of total non-blank counted lines
      3. winner — class with max count; tie-breaker: prose > list > code > table
      4. short  — overrides prose when final candidate text < 80 chars

    The first prose paragraph (prose_chunks) is still collected for the
    candidate text, using the same blank-line and heading/table/list/blockquote
    stop signals as before.

    NOTE: This function operates on `body` returned by parse_frontmatter, so
    the opening and closing `---` frontmatter delimiters are NOT in scope here.
    The `^---\\s*$` separator guard below only fires on bare `---` dividers in
    the body (e.g., Obsidian section breaks), never on frontmatter markers.
    """
    lines = body.splitlines()
    start = (h1_line_index + 1) if h1_line_index is not None else 0

    in_fence = False
    prose_chunks: list[str] = []
    prose_paragraph_done = False  # set True when blank/stop line ends first para

    # Dominant-shape counters (F1 fix)
    n_table = 0
    n_list = 0
    n_code = 0
    n_prose = 0

    _sep_re = re.compile(r"^---\s*$")  # F2 fix: body-level `---` separator lines

    i = start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # F2 fix: bare `---` separator lines act as paragraph breaks and are
        # never counted into any shape bucket.  This guard only fires inside
        # `body` (after parse_frontmatter strips the frontmatter block), so
        # the frontmatter opening/closing `---` markers are never in scope.
        if _sep_re.match(stripped):
            if prose_chunks and not prose_paragraph_done:
                prose_paragraph_done = True
            i += 1
            continue

        if not stripped:
            # Blank line: end of current prose paragraph
            if prose_chunks and not prose_paragraph_done:
                prose_paragraph_done = True
            i += 1
            continue

        # Track fence state; fence markers themselves don't go into any bucket
        if _is_fence_line(stripped):
            in_fence = not in_fence
            i += 1
            continue

        if in_fence:
            n_code += 1
            i += 1
            continue

        # Skip HTML comments (single-line <!-- ... -->)
        if _HTML_COMMENT_RE.match(stripped):
            i += 1
            continue

        # Classify this non-blank, non-fence, non-comment line
        is_table = bool(_TABLE_ROW_RE.match(stripped))
        is_list = bool(_LIST_ITEM_RE.match(stripped))
        is_heading = bool(_HEADING_RE.match(stripped))
        is_blockquote = bool(_BLOCKQUOTE_RE.match(stripped))

        if is_table:
            n_table += 1
        elif is_list:
            n_list += 1
        elif is_heading or is_blockquote:
            # Headings and blockquotes: count as prose-adjacent but stop para
            n_prose += 1
            if prose_chunks and not prose_paragraph_done:
                prose_paragraph_done = True
        else:
            # Pure prose line
            n_prose += 1
            if not prose_paragraph_done:
                prose_chunks.append(stripped)

        # Table and list lines also stop an in-progress prose paragraph
        if (is_table or is_list) and prose_chunks and not prose_paragraph_done:
            prose_paragraph_done = True

        i += 1

    paragraph = " ".join(prose_chunks).strip()

    # --- Dominant-shape determination (F1 fix) ---
    total = n_table + n_list + n_code + n_prose

    if h1_line_index is None:
        shape = "no-h1"
    elif total == 0:
        # Body has no classifiable lines at all → treat as no-h1 fallthrough
        shape = "no-h1"
    else:
        # Find dominant class; tie-break: prose > list > code > table
        counts = [("prose", n_prose), ("list", n_list), ("code", n_code), ("table", n_table)]
        best_label, best_count = max(counts, key=lambda x: (x[1], ["prose", "list", "code", "table"].index(x[0]) == 0))
        # Re-select with explicit tie-break (max picks last on tie; we want prose-first)
        best_count = max(n_prose, n_list, n_code, n_table)
        for label, count in counts:  # prose checked first
            if count == best_count:
                best_label = label
                break

        if best_count / total < 0.60:
            shape = "mixed"
        else:
            shape = best_label

        # short override: prose shape with candidate < 80 chars
        if shape == "prose" and len(paragraph) < 80:
            shape = "short"

    return paragraph, shape


# ---------------------------------------------------------------------------
# Markdown stripping
# ---------------------------------------------------------------------------

def strip_markdown(text: str) -> str:
    """Remove common inline markdown to produce plain-text summary candidates."""
    # [text](url) → text
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    # [[wiki|alias]] → alias; [[wiki]] → wiki
    text = re.sub(r"\[\[([^\]\|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    # **bold** → bold
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    # __bold__ → bold
    text = re.sub(r"__([^_]+)__", r"\1", text)
    # *italic* → italic (non-greedy, not crossing *)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    # _italic_ → italic
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    # `code` → code
    text = re.sub(r"`+([^`]+)`+", r"\1", text)
    # ~~strike~~ → strike
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # List markers at line start
    text = re.sub(r"(?m)^[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\d+\.\s+", "", text)
    # Heading markers at line start
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    # Blockquote markers
    text = re.sub(r"(?m)^>\s*", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def truncate_at_word_boundary(text: str, limit: int = 280) -> str:
    """Truncate text to at most `limit` chars at the last word boundary.

    Appends '…' (U+2026) when truncated. Does not truncate if already within
    limit.
    """
    if len(text) <= limit:
        return text
    # Work within limit - 1 to leave room for the ellipsis character
    truncated = text[: limit - 1]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


# ---------------------------------------------------------------------------
# Top-level per-file generation
# ---------------------------------------------------------------------------

def generate_summary(file_path: Path, vault_root: Path) -> dict:
    """Process one file and return a result record.

    Keys: path (str, relative), skipped (bool), excluded (bool),
          exclusion_reason (str|None), shape (str|None),
          char_count (int|None), candidate (str|None), error (str|None).
    """
    try:
        rel = str(file_path.relative_to(vault_root)).replace("\\", "/")
    except ValueError:
        rel = str(file_path).replace("\\", "/")

    # --- Exclusion checks (before reading file content) ---
    basename = file_path.name
    norm_path = str(file_path).replace("\\", "/")

    if basename in EXCLUDE_BASENAMES:
        return {
            "path": rel,
            "skipped": False,
            "excluded": True,
            "exclusion_reason": f"basename {basename} in EXCLUDE_BASENAMES",
            "shape": None,
            "char_count": None,
            "candidate": None,
            "error": None,
        }
    for fragment in EXCLUDE_PATH_FRAGMENTS:
        if fragment in norm_path:
            return {
                "path": rel,
                "skipped": False,
                "excluded": True,
                "exclusion_reason": f"path matches {fragment}",
                "shape": None,
                "char_count": None,
                "candidate": None,
                "error": None,
            }

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {
            "path": rel,
            "skipped": False,
            "excluded": False,
            "exclusion_reason": None,
            "shape": None,
            "char_count": None,
            "candidate": None,
            "error": f"read error: {exc}",
        }

    fields, body = parse_frontmatter(text)

    if has_summary(fields):
        return {
            "path": rel,
            "skipped": True,
            "excluded": False,
            "exclusion_reason": None,
            "shape": None,
            "char_count": None,
            "candidate": None,
            "error": None,
        }

    title, h1_idx = extract_h1(body)
    fallback_title = file_path.stem

    paragraph, shape = extract_first_prose_paragraph(body, h1_idx)
    stripped_para = strip_markdown(paragraph) if paragraph else ""

    display_title = strip_markdown(title) if title else fallback_title

    if stripped_para:
        raw_candidate = f"{display_title} {stripped_para}"
    else:
        raw_candidate = f"{display_title} [no prose body]"

    candidate = truncate_at_word_boundary(raw_candidate, limit=280)

    return {
        "path": rel,
        "skipped": False,
        "excluded": False,
        "exclusion_reason": None,
        "shape": shape,
        "char_count": len(candidate),
        "candidate": candidate,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Output writer
# ---------------------------------------------------------------------------

def write_sample_md(records: list[dict], out_path: Path, run_date: str) -> None:
    """Write the review sample markdown to out_path."""
    lines: list[str] = []

    # Frontmatter
    lines += [
        "---",
        f"date: {run_date}",
        "tags: [phase4-sample, project/vault-maintenance]",
        "type: investigation",
        "status: pending-review",
        "---",
        "",
    ]

    for rec in records:
        lines.append(f"## {rec['path']}")
        lines.append("")

        if rec.get("error"):
            lines.append(f"- **Error:** {rec['error']}")
        elif rec.get("excluded"):
            lines.append(f"- **Excluded:** {rec['exclusion_reason']}")
        elif rec["skipped"]:
            lines.append(
                "- **Skipped:** frontmatter already contains `summary:` field"
            )
        else:
            lines.append(f"- **Shape:** {rec['shape']}")
            lines.append(f"- **Char count:** {rec['char_count']}")
            lines.append(f"- **Summary candidate:** > {rec['candidate']}")
            lines.append("- **Reviewer verdict:** ")

        lines.append("")
        lines.append("---")
        lines.append("")

    # Footer
    lines += [
        "## Reviewer instructions",
        "",
        'Mark each "Reviewer verdict" with one of:',
        "- GOOD — accept as-is",
        "- ACCEPT-WITH-EDIT — describe edit",
        "- REJECT — quality too poor, do not bulk-apply this shape class",
        "",
        "Then surface aggregate verdict (a/b/c/d): apply all 619 / scoped ~150 / skip / iterate.",
        "",
    ]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Phase 4 summary-candidate sample for human review."
    )
    parser.add_argument(
        "--files",
        required=True,
        help="Comma-separated list of markdown file paths (relative to VAULT_ROOT or absolute).",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output markdown path (relative to VAULT_ROOT or absolute).",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="Run date in YYYY-MM-DD format (default: today). Controls frontmatter date field.",
    )
    args = parser.parse_args()

    run_date = args.date if args.date else datetime.date.today().isoformat()

    # Resolve output path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = VAULT_ROOT / out_path

    # Resolve and deduplicate input files
    raw_paths = [p.strip() for p in args.files.split(",") if p.strip()]
    input_paths: list[Path] = []
    for raw in raw_paths:
        p = Path(raw)
        if not p.is_absolute():
            p = VAULT_ROOT / p
        input_paths.append(p)

    records: list[dict] = []
    for fp in input_paths:
        if not fp.exists():
            print(f"WARNING: file not found, skipping: {fp}", file=sys.stderr)
            records.append(
                {
                    "path": str(fp.relative_to(VAULT_ROOT) if fp.is_relative_to(VAULT_ROOT) else fp).replace("\\", "/"),
                    "skipped": False,
                    "excluded": False,
                    "exclusion_reason": None,
                    "shape": None,
                    "char_count": None,
                    "candidate": None,
                    "error": "file not found",
                }
            )
            continue
        rec = generate_summary(fp, VAULT_ROOT)
        records.append(rec)

    write_sample_md(records, out_path, run_date)
    print(f"Written: {out_path}")

    # Print shape distribution summary to stdout
    from collections import Counter
    shape_counts: Counter = Counter()
    skipped = 0
    excluded = 0
    errors = 0
    for r in records:
        if r.get("error") and not r.get("skipped") and not r.get("excluded"):
            errors += 1
        elif r.get("excluded"):
            excluded += 1
        elif r["skipped"]:
            skipped += 1
        else:
            shape_counts[r["shape"]] += 1

    print(f"Files processed: {len(records)}")
    print(f"  Excluded (basename/path filter): {excluded}")
    print(f"  Skipped (has summary): {skipped}")
    print(f"  Errors: {errors}")
    print(f"  Shape distribution:")
    for shape, count in sorted(shape_counts.items()):
        print(f"    {shape}: {count}")


if __name__ == "__main__":
    main()
