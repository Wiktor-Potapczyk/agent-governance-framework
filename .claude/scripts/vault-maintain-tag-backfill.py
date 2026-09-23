#!/usr/bin/env python3
"""Phase 3: tag-backfill for untagged vault files (per 2026-05-10 tag taxonomy audit).

Targets the 703 .md files (~50.6%) with NO tags. Inference rules:
  1. Folder→tag: `Projects/<Name>/...` files get `#project/<name-kebab>`
  2. Filename→type: pattern matching on stem
     - audit | review | sweep            → #analysis
     - research | sweep | inventory      → #research
     - plan | design | spec | blueprint  → #planning
     - n8n*                              → #n8n
     - hook* | hooks*                    → #hooks
     - moc-*                             → #moc
     - state.md / task_plan.md / etc.    → SKIP (special files, separate conventions)
     - daily-note YYYY-MM-DD pattern     → #daily (skip Daily Notes/ entirely)
  3. Status default: `#active` for files in active project STATE.md projects, `#archived`
     for files under /archive/ subdirs

If a file already has frontmatter but missing `tags`, ADD the tags field.
If a file has no frontmatter at all, ADD a minimal frontmatter block at the top.

Usage:
  python vault-maintain-tag-backfill.py            # dry-run (shows planned changes)
  python vault-maintain-tag-backfill.py --apply    # write changes

Idempotent: rerunning skips files that now have any tags.
Excluded: Inbox/, Daily Notes/, Templates/, source-data/, source-assets/, repo/, framework-repo/, .obsidian/, .claude/, .git/, MEMORY.md, Home.md, STATE.md, task_plan.md, PROJECT.md
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS = ["Projects", "Notes", "Resources", "Areas", "Clippings"]
EXCLUDE_SUBSTRINGS = [
    "/source-data/", "/source-assets/", "/repo/", "/framework-repo/",
    "/.obsidian/", "/.claude/", "/.git/",
    "/Inbox/", "/Daily Notes/", "/Templates/",
]
EXCLUDE_FILENAMES = {
    "STATE.md", "task_plan.md", "PROJECT.md",
    "MEMORY.md", "Home.md", "CLAUDE.md", "README.md",
}

FRONTMATTER_RE = re.compile(r"^(---\s*\n)(.*?)(\n---\s*\n)", re.DOTALL)
TAGS_FIELD_RE = re.compile(r"^tags:", re.MULTILINE)


def file_has_tags(text: str) -> bool:
    """Check if file has ANY tag (frontmatter or inline #tag)."""
    fm_match = FRONTMATTER_RE.match(text)
    if fm_match:
        fm_body = fm_match.group(2)
        if TAGS_FIELD_RE.search(fm_body):
            # Has tags field — check if it has actual content
            for line in fm_body.split("\n"):
                if line.strip().startswith("tags:"):
                    val = line.split(":", 1)[1].strip()
                    if val and val not in ("[]", "[ ]", "''", '""'):
                        return True
            # tags: line exists but empty — treat as untagged
        body = text[fm_match.end():]
    else:
        body = text
    # Check inline #tag (excluding markdown headings — # at line start)
    if re.search(r"(?<![#\w])#[a-z][a-z0-9_/-]*", body):
        return True
    return False


def infer_project_tag(rel_path: str) -> str | None:
    """Projects/X/... → #project/<x-kebab>."""
    rel = rel_path.replace("\\", "/")
    m = re.match(r"^Projects/([^/]+)/", rel)
    if m:
        proj_name = m.group(1)
        # Kebab-case + lowercase
        proj_kebab = re.sub(r"[^a-z0-9]+", "-", proj_name.lower()).strip("-")
        return f"project/{proj_kebab}"
    return None


def infer_type_tags(stem: str, rel_path: str) -> list[str]:
    """Infer type tags from filename stem patterns. Order: most specific first."""
    stem_lower = stem.lower()
    tags = []
    if stem_lower.startswith("moc-"):
        tags.append("moc")
    if "audit" in stem_lower or "review" in stem_lower:
        tags.append("analysis")
    if "research" in stem_lower or "sweep" in stem_lower or "inventory" in stem_lower:
        tags.append("research")
    if "plan" in stem_lower or "design" in stem_lower or "spec" in stem_lower or "blueprint" in stem_lower:
        tags.append("planning")
    if "n8n" in stem_lower or "workflow" in stem_lower:
        tags.append("n8n")
    if "hook" in stem_lower:
        tags.append("hooks")
    if "agent" in stem_lower or "skill" in stem_lower:
        tags.append("agent")
    return tags


def infer_status(rel_path: str) -> str:
    rel_low = rel_path.replace("\\", "/").lower()
    if "/archive/" in rel_low or "/archives/" in rel_low:
        return "archived"
    return "active"


def is_excluded(rel_path: str) -> bool:
    rel_norm = "/" + rel_path.replace("\\", "/").strip("/")
    if any(s in rel_norm for s in EXCLUDE_SUBSTRINGS):
        return True
    if Path(rel_path).name in EXCLUDE_FILENAMES:
        return True
    return False


def build_inferred_tags(path: Path) -> list[str]:
    rel = str(path.relative_to(VAULT)).replace("\\", "/")
    tags = []
    proj = infer_project_tag(rel)
    if proj:
        tags.append(proj)
    tags.extend(infer_type_tags(path.stem, rel))
    status = infer_status(rel)
    tags.append(status)
    # Dedup, preserve order
    seen = set()
    out = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def apply_tags_to_file(path: Path, inferred: list[str], apply: bool) -> tuple[bool, str]:
    """Add tags to file's frontmatter (or create frontmatter if missing).
    Returns (changed, action). Action ∈ {'add-fm', 'add-tags', 'replace-empty-tags', 'no-op'}.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    tags_value = "[" + ", ".join(inferred) + "]"

    fm_match = FRONTMATTER_RE.match(text)
    if not fm_match:
        # No frontmatter — create one
        today = date.today().isoformat()
        new_fm = f"---\ndate: {today}\ntags: {tags_value}\nstatus: {inferred[-1] if inferred else 'active'}\n---\n\n"
        new_text = new_fm + text.lstrip("\n")
        if apply:
            path.write_text(new_text, encoding="utf-8")
        return True, "add-fm"

    fm_body = fm_match.group(2)
    has_tags_line = bool(TAGS_FIELD_RE.search(fm_body))

    if not has_tags_line:
        # Add tags line at end of frontmatter body
        new_fm_body = fm_body.rstrip() + f"\ntags: {tags_value}"
        new_text = fm_match.group(1) + new_fm_body + fm_match.group(3) + text[fm_match.end():]
        if apply:
            path.write_text(new_text, encoding="utf-8")
        return True, "add-tags"

    # Has tags line — check if empty
    new_fm_lines = []
    replaced = False
    for line in fm_body.split("\n"):
        if line.strip().startswith("tags:") and not replaced:
            val = line.split(":", 1)[1].strip()
            if not val or val in ("[]", "[ ]", "''", '""'):
                indent = re.match(r"^(\s*)", line).group(1)
                new_fm_lines.append(f"{indent}tags: {tags_value}")
                replaced = True
                continue
        new_fm_lines.append(line)

    if replaced:
        new_text = fm_match.group(1) + "\n".join(new_fm_lines) + fm_match.group(3) + text[fm_match.end():]
        if apply:
            path.write_text(new_text, encoding="utf-8")
        return True, "replace-empty-tags"

    return False, "no-op"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write changes to disk")
    ap.add_argument("--limit", type=int, default=None, help="Cap files processed (for testing)")
    args = ap.parse_args()

    candidates = []
    for d in SCAN_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            if is_excluded(rel):
                continue
            candidates.append(p)

    print(f"Scanned: {len(candidates)} candidate .md files")

    untagged = []
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not file_has_tags(text):
            untagged.append(p)

    print(f"Untagged: {len(untagged)} files")
    if args.limit:
        untagged = untagged[: args.limit]
        print(f"Limited to first {args.limit}")

    print()
    print("=== Action distribution (preview) ===")
    actions_count = {"add-fm": 0, "add-tags": 0, "replace-empty-tags": 0, "no-op": 0}
    samples = {"add-fm": [], "add-tags": [], "replace-empty-tags": []}

    for p in untagged:
        inferred = build_inferred_tags(p)
        if not inferred:
            actions_count["no-op"] += 1
            continue
        # Simulate by reading + computing action without writing
        text = p.read_text(encoding="utf-8", errors="replace")
        fm_match = FRONTMATTER_RE.match(text)
        if not fm_match:
            action = "add-fm"
        else:
            fm_body = fm_match.group(2)
            if not TAGS_FIELD_RE.search(fm_body):
                action = "add-tags"
            else:
                # Check if empty tags
                empty = False
                for line in fm_body.split("\n"):
                    if line.strip().startswith("tags:"):
                        val = line.split(":", 1)[1].strip()
                        if not val or val in ("[]", "[ ]", "''", '""'):
                            empty = True
                action = "replace-empty-tags" if empty else "no-op"
        actions_count[action] += 1
        if action != "no-op" and len(samples[action]) < 3:
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            samples[action].append((rel, inferred))

    for action, count in actions_count.items():
        print(f"  {action}: {count}")
    print()
    print("=== Samples (first 3 per action) ===")
    for action, items in samples.items():
        if not items:
            continue
        print(f"  {action}:")
        for rel, tags in items:
            print(f"    {rel}")
            print(f"      -> tags: [{', '.join(tags)}]")

    if args.apply:
        print()
        print("=== APPLYING ===")
        applied = {"add-fm": 0, "add-tags": 0, "replace-empty-tags": 0, "no-op": 0}
        for p in untagged:
            inferred = build_inferred_tags(p)
            if not inferred:
                continue
            changed, action = apply_tags_to_file(p, inferred, apply=True)
            applied[action] += 1
        print(f"Applied: {sum(applied.values())} writes ({applied})")
        # Idempotency check
        leftover = 0
        for p in untagged:
            text = p.read_text(encoding="utf-8", errors="replace")
            if not file_has_tags(text):
                leftover += 1
        if leftover:
            print(f"WARN: {leftover} files still untagged after apply")
        else:
            print("PASS: 0 untagged files remain in processed set")


if __name__ == "__main__":
    main()
