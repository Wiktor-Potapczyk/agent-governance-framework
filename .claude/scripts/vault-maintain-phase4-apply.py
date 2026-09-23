#!/usr/bin/env python3
"""vault-maintain-phase4-apply.py

Bulk-write `summary:` into frontmatter for vault notes that lack one.

Walk scan dirs (Inbox/, Notes/, Projects/, Resources/, Clippings/) and for
each .md file:
  1. Skip exempt paths (source-data, repos, etc.)
  2. Skip excluded class (basename in EXCLUDE_BASENAMES or path in EXCLUDE_PATH_FRAGMENTS)
  3. Skip files with no frontmatter at all — do NOT auto-create (R3 mitigation)
  4. Skip files that already have a `summary:` key
  5. Generate summary candidate via same heuristic as phase4-sample.py
  6. Skip low-quality shapes (short, no-h1, mixed) or candidate contains [no prose body]
  7. Write `summary:` into frontmatter

Idempotent: re-running after --apply produces 0 writes.

Usage:
  python vault-maintain-phase4-apply.py            # dry-run (default)
  python vault-maintain-phase4-apply.py --apply    # write to disk
"""

import argparse
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Inbox", "Notes", "Projects", "Resources", "Clippings"]

# Paths containing these fragments are skipped entirely (source / repo content).
EXEMPT_SUBSTRINGS = ["source-data", "source-assets", "/repo/", "/framework-repo/"]

# Files excluded by basename — structural/infra notes that should not get summaries.
# README.md is INTENTIONALLY OMITTED: Resources/KB/README.md scored GOOD in prior sample.
EXCLUDE_BASENAMES = {"STATE.md", "PROJECT.md", "task_plan.md", "MEMORY.md", "SKILL.md", "CLAUDE.md"}

# Files excluded by path fragment — archive dirs and MOC files.
EXCLUDE_PATH_FRAGMENTS = ["/archive/", "/Resources/KB/moc-"]

# Low-quality shapes: do not write summaries for these.
LOW_QUALITY_SHAPES = {"short", "no-h1", "mixed"}

# ---------------------------------------------------------------------------
# Frontmatter parsing  (duplicated from phase4-sample — no import; hyphenated
# filenames make Python imports unreliable)
# ---------------------------------------------------------------------------

FM_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n)", re.DOTALL)

_FM_DELIM = re.compile(r"^---\s*$", re.MULTILINE)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Minimal key: value frontmatter scanner. No PyYAML dependency.

    Returns (fields_dict, body_str). body_str is everything after the closing
    `---` delimiter. If no valid frontmatter block found, returns ({}, text).
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


# ---------------------------------------------------------------------------
# Shape-extraction logic (duplicated from patched phase4-sample)
# ---------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(r"^\|")
_FENCE_START_RE = re.compile(r"^```")
_HTML_COMMENT_RE = re.compile(r"^<!--")
_LIST_ITEM_RE = re.compile(r"^(\s*[-*+]|\s*\d+\.)\s")
_HEADING_RE = re.compile(r"^#{1,6}\s")
_BLOCKQUOTE_RE = re.compile(r"^>")
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SEP_RE = re.compile(r"^---\s*$")


def _is_fence_line(line: str) -> bool:
    return bool(_FENCE_START_RE.match(line))


def extract_h1(body: str) -> tuple[str | None, int | None]:
    lines = body.splitlines()
    for idx, line in enumerate(lines):
        m = re.match(r"^#\s+(.+)$", line)
        if m:
            return m.group(1).strip(), idx
    return None, None


def extract_first_prose_paragraph(body: str, h1_line_index: int | None) -> tuple[str, str]:
    """Dominant-shape classifier. Returns (paragraph_text, shape).

    NOTE: operates on body returned by parse_frontmatter — frontmatter `---`
    delimiters are not in scope here. The _SEP_RE guard only fires on body-level
    `---` separators (e.g. Obsidian section breaks).
    """
    lines = body.splitlines()
    start = (h1_line_index + 1) if h1_line_index is not None else 0

    in_fence = False
    prose_chunks: list[str] = []
    prose_paragraph_done = False

    n_table = 0
    n_list = 0
    n_code = 0
    n_prose = 0

    i = start
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()

        # Body-level `---` separator: paragraph break, never counted.
        if _SEP_RE.match(stripped):
            if prose_chunks and not prose_paragraph_done:
                prose_paragraph_done = True
            i += 1
            continue

        if not stripped:
            if prose_chunks and not prose_paragraph_done:
                prose_paragraph_done = True
            i += 1
            continue

        if _is_fence_line(stripped):
            in_fence = not in_fence
            i += 1
            continue

        if in_fence:
            n_code += 1
            i += 1
            continue

        if _HTML_COMMENT_RE.match(stripped):
            i += 1
            continue

        is_table = bool(_TABLE_ROW_RE.match(stripped))
        is_list = bool(_LIST_ITEM_RE.match(stripped))
        is_heading = bool(_HEADING_RE.match(stripped))
        is_blockquote = bool(_BLOCKQUOTE_RE.match(stripped))

        if is_table:
            n_table += 1
        elif is_list:
            n_list += 1
        elif is_heading or is_blockquote:
            n_prose += 1
            if prose_chunks and not prose_paragraph_done:
                prose_paragraph_done = True
        else:
            n_prose += 1
            if not prose_paragraph_done:
                prose_chunks.append(stripped)

        if (is_table or is_list) and prose_chunks and not prose_paragraph_done:
            prose_paragraph_done = True

        i += 1

    paragraph = " ".join(prose_chunks).strip()
    total = n_table + n_list + n_code + n_prose

    if h1_line_index is None:
        shape = "no-h1"
    elif total == 0:
        shape = "no-h1"
    else:
        best_count = max(n_prose, n_list, n_code, n_table)
        counts = [("prose", n_prose), ("list", n_list), ("code", n_code), ("table", n_table)]
        best_label = "prose"
        for label, count in counts:  # prose checked first (highest tie-break priority)
            if count == best_count:
                best_label = label
                break

        if best_count / total < 0.60:
            shape = "mixed"
        else:
            shape = best_label

        if shape == "prose" and len(paragraph) < 80:
            shape = "short"

    return paragraph, shape


def strip_markdown(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\[([^\]\|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    text = re.sub(r"`+([^`]+)`+", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    text = re.sub(r"(?m)^[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\d+\.\s+", "", text)
    text = re.sub(r"(?m)^#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^>\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate_at_word_boundary(text: str, limit: int = 280) -> str:
    if len(text) <= limit:
        return text
    truncated = text[: limit - 1]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated.rstrip() + "…"


def build_candidate(file_path: Path, body: str) -> tuple[str | None, str | None]:
    """Generate (candidate_text, shape) or (None, shape) if low-quality."""
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
    return candidate, shape


# ---------------------------------------------------------------------------
# Frontmatter write
# ---------------------------------------------------------------------------

def quote_summary_value(summary: str) -> str:
    """Return a YAML-safe summary line value, single-quoted when needed."""
    needs_quote = (
        ":" in summary
        or summary.startswith(("&", "*", "?", "|", ">", "!", "%", "@", "`", "-",
                               "[", "{", "#"))
        or (summary[:1].isdigit())
    )
    if needs_quote:
        escaped = summary.replace("'", "''")
        return f"'{escaped}'"
    return summary


def write_summary_into_frontmatter(file_path: Path, summary: str, dry_run: bool) -> bool:
    """Insert `summary: <text>` into frontmatter. Body unchanged.

    Returns True if the file was (or would be) written.
    Raises RuntimeError on body-integrity failure.
    """
    text = file_path.read_text(encoding="utf-8", errors="replace")
    fm_m = FM_RE.match(text)
    if not fm_m:
        return False  # no frontmatter — caller should have skipped

    fm_open = fm_m.group(1)       # "---\n"
    fm_block = fm_m.group(2)      # frontmatter content between delimiters
    fm_close = fm_m.group(3)      # "\n---\n"
    body = text[fm_m.end():]      # everything after closing ---

    # Body-integrity pre-check (R10 mitigation)
    assert body == text[fm_m.end():], "Pre-write body-integrity assertion failed"

    summary_value = quote_summary_value(summary)
    summary_line = f"summary: {summary_value}"

    new_fm_block = fm_block.rstrip() + "\n" + summary_line
    new_fm_with_delims = f"{fm_open}{new_fm_block}{fm_close}"
    prefix = text[: fm_m.start()]  # almost always empty
    new_text = prefix + new_fm_with_delims + body

    if dry_run:
        return True

    file_path.write_text(new_text, encoding="utf-8", newline="\n")

    # Body-integrity post-check: re-read and verify body portion is unchanged
    written = file_path.read_text(encoding="utf-8", errors="replace")
    written_fm_m = FM_RE.match(written)
    if not written_fm_m:
        raise RuntimeError(f"Post-write FM parse failed on {file_path}")
    written_body = written[written_fm_m.end():]
    if written_body != body:
        raise RuntimeError(
            f"Body-integrity FAIL after write on {file_path}:\n"
            f"  original body len={len(body)}, written body len={len(written_body)}"
        )

    return True


# ---------------------------------------------------------------------------
# Main scan loop
# ---------------------------------------------------------------------------

def is_exempt(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/")
    return any(s in norm for s in EXEMPT_SUBSTRINGS)


def is_excluded_class(file_path: Path, norm_path: str) -> tuple[bool, str]:
    """Return (True, reason) if the file is in the excluded class, else (False, '')."""
    if file_path.name in EXCLUDE_BASENAMES:
        return True, f"basename {file_path.name} in EXCLUDE_BASENAMES"
    for fragment in EXCLUDE_PATH_FRAGMENTS:
        if fragment in norm_path:
            return True, f"path matches {fragment}"
    return False, ""


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bulk-write summary: into vault note frontmatter."
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to disk. Default is dry-run (prints WOULD WRITE lines).",
    )
    args = ap.parse_args()
    dry_run = not args.apply

    if dry_run:
        print("DRY-RUN mode — pass --apply to write files.\n")

    counts = {
        "touched": 0,
        "excluded-class": 0,
        "excluded-path": 0,
        "skipped-no-frontmatter": 0,
        "skipped-has-summary": 0,
        "skipped-low-quality": 0,
        "errored": 0,
    }

    for dir_name in SCAN_DIRS:
        scan_root = VAULT / dir_name
        if not scan_root.exists():
            continue
        for file_path in sorted(scan_root.rglob("*.md")):
            rel = str(file_path.relative_to(VAULT)).replace("\\", "/")
            norm_path = "/" + rel  # ensure leading slash for fragment matching

            # 1. Exempt path (source-data, repos)
            if is_exempt(rel):
                counts["excluded-path"] += 1
                continue

            # 2. Excluded class (basename / path fragment)
            excluded, _reason = is_excluded_class(file_path, norm_path)
            if excluded:
                counts["excluded-class"] += 1
                continue

            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                print(f"ERROR reading {rel}: {exc}", file=sys.stderr)
                counts["errored"] += 1
                continue

            # 3. No frontmatter at all — do NOT auto-create (R3 mitigation)
            fields, body = parse_frontmatter(text)
            if not fields and not FM_RE.match(text):
                counts["skipped-no-frontmatter"] += 1
                continue

            # 4. Already has summary
            if "summary" in fields:
                counts["skipped-has-summary"] += 1
                continue

            # 5. Generate candidate; skip low-quality shapes
            try:
                candidate, shape = build_candidate(file_path, body)
            except Exception as exc:
                print(f"ERROR generating summary for {rel}: {exc}", file=sys.stderr)
                counts["errored"] += 1
                continue

            if shape in LOW_QUALITY_SHAPES or "[no prose body]" in candidate:
                counts["skipped-low-quality"] += 1
                continue

            # 6. Write (or dry-run report)
            try:
                write_summary_into_frontmatter(file_path, candidate, dry_run=dry_run)
                counts["touched"] += 1
                if dry_run:
                    print(f"WOULD WRITE: {rel} | summary: {candidate[:80]}{'…' if len(candidate) > 80 else ''}")
                else:
                    print(f"WROTE: {rel} | summary: {candidate[:80]}{'…' if len(candidate) > 80 else ''}")
            except RuntimeError as exc:
                print(f"INTEGRITY ERROR on {rel}: {exc}", file=sys.stderr)
                counts["errored"] += 1
            except Exception as exc:
                print(f"ERROR writing {rel}: {exc}", file=sys.stderr)
                counts["errored"] += 1

    print()
    print("=== Counts ===")
    for key, val in counts.items():
        print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
