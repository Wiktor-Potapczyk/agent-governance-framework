#!/usr/bin/env python3
"""Generate per-project work-layer INDEX.md for the FILE-ORG-3 pilot projects.

Mechanism M-A of the 2026-06-23 FILE-ORG increment-1 spec
(Projects/Agent-Governance-Research/work/2026-06-23-fileorg-increment1-spec.md, section 2).

Behavior:
  - Flat, NON-recursive glob over Projects/<pilot>/work/*.md. The flat glob is
    the section-1 exclusion mechanism: it cannot descend into work/backups/,
    work/archive/, work/__pycache__/, or work/inventory/, and *.md excludes
    tooling artifacts. Do NOT widen the pattern.
  - Additionally skips INDEX.md itself and any file whose frontmatter tags
    contain the exact tag "wiki" (wiki-layer files are out of work-layer scope).
  - Renders a 7-column Markdown table (path, title, date, type, status,
    lifecycle, purpose), sorted date descending with filename ascending as the
    stable tiebreak.
  - Writes Projects/<pilot>/work/INDEX.md with frontmatter carrying ONLY
    `date:` (generation date) and `status: active` — no `wiki` tag, no
    `source:` field (the wiki-citation hook must never engage; INDEX.md is an
    operational artifact, not a wiki page).
  - Deterministic and idempotent: wholesale regeneration; two same-day runs
    produce byte-identical output.

Frontmatter parsing: PyYAML when importable, else a documented regex fallback
reading `key: value` pairs between the leading `---` delimiters. Known regex
fallback limitations (spec section 2): multi-line YAML values (block scalars)
parse incorrectly and colons inside quoted values produce false splits. This
is acceptable for the fields in scope (date, type, status, lifecycle,
lifecycle_updated, summary, tags), none of which use multi-line values in
practice.

stdlib-only (+ optional PyYAML, pure-Python). encoding='utf-8' on every open().
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timezone

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# Increment 1 hardcodes the two pilots (spec section 1). Vault-wide
# generalization (Projects/*/work/*.md) is a future increment.
PILOTS = [
    "Projects/Vault-Maintenance",
    "Projects/Agent-Governance-Research",
]

COLUMNS = ["path", "title", "date", "type", "status", "lifecycle", "purpose"]


def parse_frontmatter(text):
    """Return the frontmatter dict of a markdown document, {} if none/unparseable."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    if HAVE_YAML:
        try:
            data = yaml.safe_load(block)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            return _regex_frontmatter(block)
    return _regex_frontmatter(block)


def _regex_frontmatter(block):
    """Documented regex fallback (spec section 2). See module docstring for limits."""
    return dict(re.findall(r"^(\w[\w_-]*):\s*(.+)$", block, re.MULTILINE))


def tags_of(fm):
    """Normalize frontmatter tags to a list of strings."""
    raw = fm.get("tags")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw]
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [t.strip().strip("'\"") for t in s.split(",") if t.strip()]


def scalar(fm, key, default=""):
    """Frontmatter value as a plain string (PyYAML may yield datetime.date)."""
    v = fm.get(key)
    if v is None:
        return default
    return str(v).strip()


def cell(s):
    """Escape a value for a Markdown table cell."""
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def first_heading(body, level):
    """First heading of the given level ('#' or '##') in the document body."""
    m = re.search(r"^%s\s+(.+)$" % re.escape(level), body, re.MULTILINE)
    return m.group(1).strip() if m else ""


def collect_rows(work_dir):
    rows = []
    for path in sorted(glob.glob(os.path.join(work_dir, "*.md"))):
        fname = os.path.basename(path)
        if fname == "INDEX.md":
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(f"WARN: cannot read {path}: {e}", file=sys.stderr)
            continue
        fm = parse_frontmatter(text)
        if "wiki" in tags_of(fm):
            continue  # wiki-layer file: out of work-layer scope (spec section 1)
        # strip frontmatter for heading extraction
        body = re.sub(r"^---\s*\n.*?\n---\s*\n?", "", text, count=1, flags=re.DOTALL)
        title = first_heading(body, "#") or fname
        purpose = first_heading(body, "##") or scalar(fm, "summary") or fname
        rows.append({
            "path": fname,
            "title": title,
            "date": scalar(fm, "date"),
            "type": scalar(fm, "type"),
            "status": scalar(fm, "status"),
            "lifecycle": scalar(fm, "lifecycle", "active"),
            "purpose": purpose,
            "_file": fname,
        })
    # stable sort: filename ascending, then date descending (missing date last)
    rows.sort(key=lambda r: r["_file"])
    rows.sort(key=lambda r: r["date"], reverse=True)
    return rows


def render_index(project, rows):
    today = date.today().isoformat()
    lines = [
        "---",
        f"date: {today}",
        "status: active",
        "---",
        "",
        f"# Work INDEX — {os.path.basename(project)}",
        "",
        f"Static catalog of the flat work-layer corpus (`{project}/work/*.md`). "
        "Regenerated wholesale by `.claude/scripts/generate_work_index.py`; "
        "never edited as narrative. Excludes subdirectories (backups/, archive/, "
        "inventory/, __pycache__/), non-md files, wiki-tagged files, and this "
        "index itself. INDEX.md answers \"what artifacts exist\"; STATE.md "
        "answers \"where are we now\".",
        "",
        f"{len(rows)} files.",
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "|".join(["---"] * len(COLUMNS)) + "|",
    ]
    for r in rows:
        lines.append("| " + " | ".join(cell(r[c]) for c in COLUMNS) + " |")
    lines.append("")
    return "\n".join(lines)


def write_stamp(project, file_count):
    """ROAD-7 (2026-09-08): staleness stamp read by lint_pass_work_index_stale.py.

    Written on every regeneration; shape mirrors lint-cadence.json
    (last_iso plus flat fields). Slug is the lowercased project basename.
    """
    state_dir = os.path.join(VAULT, ".claude", "hooks", "_state")
    os.makedirs(state_dir, exist_ok=True)
    slug = os.path.basename(project.rstrip("/")).lower()
    stamp_path = os.path.join(state_dir, f"work-index-{slug}.json")
    stamp = {
        "last_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_count": file_count,
        "project": project,
    }
    with open(stamp_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(stamp, f, indent=2)
        f.write("\n")


def main():
    for project in PILOTS:
        work_dir = os.path.join(VAULT, *project.split("/"), "work")
        if not os.path.isdir(work_dir):
            print(f"WARN: missing work dir, skipping: {work_dir}", file=sys.stderr)
            continue
        rows = collect_rows(work_dir)
        out_path = os.path.join(work_dir, "INDEX.md")
        content = render_index(project, rows)
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        except OSError as e:
            print(f"ERROR: cannot write {out_path}: {e}", file=sys.stderr)
            return 1
        try:
            write_stamp(project, len(rows))
        except OSError as e:
            print(f"ERROR: cannot write work-index stamp for {project}: {e}",
                  file=sys.stderr)
            return 1
        print(f"{project}/work/INDEX.md: {len(rows)} rows"
              + ("" if HAVE_YAML else " (regex frontmatter fallback)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
