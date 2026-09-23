#!/usr/bin/env python3
"""Phase 4 summary: auto-fill.

For each .md in Notes/ + Projects/ where:
  - frontmatter exists
  - `summary:` field is absent
  - `type:` is NOT "inbox"
generate a 1-2 sentence summary from H1 + first paragraph and INSERT into
frontmatter only. Body is never modified. `date:` is preserved.

Idempotent: re-running on a file with summary already set is a no-op.

Modes:
  --dry-run   list candidates + proposed summaries; no writes
  --apply     write summaries
Default: --dry-run
"""
import re
import sys
import argparse
import datetime
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Notes", "Projects"]

FM_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n)", re.DOTALL)
SUMMARY_RE = re.compile(r"^summary:\s*", re.MULTILINE)
TYPE_RE = re.compile(r"^type:\s*(.+)$", re.MULTILINE)
H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
H2_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


def clean_md(s: str) -> str:
    """Strip common markdown emphasis/code so the summary reads as plain text."""
    s = re.sub(r"`+([^`]+)`+", r"\1", s)         # `code` -> code
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)    # **bold** -> bold
    s = re.sub(r"__([^_]+)__", r"\1", s)        # __bold__ -> bold
    s = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", s)  # *italic*
    s = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", s)      # _italic_
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)       # [text](url) -> text
    s = re.sub(r"\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]", r"\1", s)  # [[wiki]] -> wiki
    s = re.sub(r"~~([^~]+)~~", r"\1", s)        # ~~strike~~ -> strike
    s = re.sub(r"\s+", " ", s).strip()
    return s


def first_paragraph(body: str) -> str:
    """Return the first non-heading, non-blockquote, non-list paragraph."""
    chunks = re.split(r"\n\s*\n", body)
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Skip headings, blockquotes, fenced code, lists, html, frontmatter remnants
        if chunk.startswith(("#", ">", "```", "- ", "* ", "1.", "<!--", "<", "---", "|", "[!")):
            continue
        # Skip lines that look like field-like (key: value) blocks (e.g. callouts)
        if re.match(r"^[A-Z][\w\s]+:\s", chunk) and "\n" not in chunk:
            continue
        # Take the first sentence boundary
        m = re.search(r"^(.+?[.!?])\s+(?=[A-Z])", chunk, re.DOTALL)
        first = m.group(1) if m else chunk
        first = re.sub(r"\s+", " ", first).strip()
        # Cap length
        if len(first) > 220:
            first = first[:217].rstrip() + "..."
        return first
    return ""


def synthesize_summary(text: str, body: str, fallback_title: str) -> str:
    h1 = H1_RE.search(body)
    title = clean_md(h1.group(1).strip()) if h1 else fallback_title
    para = clean_md(first_paragraph(body))
    if para:
        if title.lower() in para.lower()[: len(title) + 5]:
            summary = para
        else:
            summary = f"{title}. {para}"
    else:
        h2 = H2_RE.search(body)
        if h2:
            summary = f"{title} — covers {clean_md(h2.group(1).strip())}."
        else:
            summary = title
    if len(summary) > 280:
        summary = summary[:277].rstrip() + "..."
    return summary


def yaml_safe(s: str) -> str:
    """Escape a string to be a safe YAML value on a single line."""
    s = s.replace("\r", " ").replace("\n", " ").strip()
    if any(c in s for c in [":", "#", "[", "]", "{", "}", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]):
        # Use double-quoted style; escape backslashes and double-quotes
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return s


def insert_summary(fm_text: str, summary: str) -> str:
    """Insert `summary: <value>` into frontmatter. Place after `date:` if present;
    else after the opening line; before `tags:` ideally."""
    line = f"summary: {yaml_safe(summary)}"
    lines = fm_text.split("\n")
    insert_at = None
    # Prefer after date:
    for i, l in enumerate(lines):
        if l.startswith("date:"):
            insert_at = i + 1
            break
    if insert_at is None:
        # else before tags:
        for i, l in enumerate(lines):
            if l.startswith("tags:"):
                insert_at = i
                break
    if insert_at is None:
        insert_at = 0
    lines.insert(insert_at, line)
    return "\n".join(lines)


def process_file(path: Path, apply: bool):
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    m = FM_RE.match(text)
    if not m:
        return None
    fm_open, fm_text, fm_close = m.group(1), m.group(2), m.group(3)
    if SUMMARY_RE.search(fm_text):
        return None  # already has summary — idempotent skip
    type_m = TYPE_RE.search(fm_text)
    if type_m and type_m.group(1).strip().lower() == "inbox":
        return None
    body = text[m.end():]
    summary = synthesize_summary(text, body, path.stem)
    if not summary or summary == path.stem:
        return None
    new_fm = insert_summary(fm_text, summary)
    new_text = fm_open + new_fm + fm_close + body
    if apply:
        path.write_text(new_text, encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N files (0=all)")
    args = parser.parse_args()
    apply = args.apply

    candidates = []
    for d in SCAN_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            m = FM_RE.match(text)
            if not m:
                continue
            fm_text = m.group(2)
            if SUMMARY_RE.search(fm_text):
                continue
            type_m = TYPE_RE.search(fm_text)
            if type_m and type_m.group(1).strip().lower() == "inbox":
                continue
            candidates.append(p)

    print(f"CANDIDATES: {len(candidates)}")
    if args.limit:
        candidates = candidates[: args.limit]
    updated = []
    for p in candidates:
        summary = process_file(p, apply)
        if summary:
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            updated.append((rel, summary))
    mode = "WRITE" if apply else "DRY-RUN"
    print(f"MODE: {mode}")
    print(f"WOULD UPDATE: {len(updated)} files")
    for rel, s in updated[:30]:
        print(f"  {rel}")
        print(f"    -> {s[:120]}")
    if len(updated) > 30:
        print(f"  ... +{len(updated) - 30} more")


if __name__ == "__main__":
    main()
