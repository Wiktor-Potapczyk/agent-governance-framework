#!/usr/bin/env python3
"""raw-frontmatter-check.py: PostToolUse Write hook (ADVISORY v1, 2026-05-11).

Wave 1.6 pre-migration enforcement for Vault-Maintenance Phase 5 Sticky Structure spec.

Scope:
  - Checks raw-layer .md writes for required frontmatter fields (date, tags, status)
  - Distinct from H-9 vault-structure-check.py: this hook focuses ONLY on raw-layer
    frontmatter presence; does NOT check tag canonicality (that's tag-variant-check.py)
    and does NOT check wiki-link presence (anti-orphan check is for wiki layer, not raw)
  - Narrower than H-9: fires on raw layer only, not Notes-with-#wiki or Resources/KB

Raw-layer paths checked:
  - Projects/**/*.md (excluding /work/-archive, /source-data, /archive)
  - Notes/**/*.md WITHOUT #wiki tag
  - Resources/**/*.md outside KB/
  - Areas/**/*.md

Excluded:
  - Inbox/, Templates/, Clippings/, Daily Notes/, .claude/, .obsidian/
  - STATE.md, PROJECT.md, task_plan.md, MEMORY.md, Home.md, CLAUDE.md, README.md
  - Resources/KB/ (wiki layer: wiki-citation-check.py handles)
  - Notes/ with #wiki tag (wiki layer)

Override: RAW_FRONTMATTER_CHECK_DISABLED=1 to disable; RAW_FRONTMATTER_CHECK_VERBOSE=1 to log PASSes.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
LOG_DIR = VAULT / ".claude" / "hooks" / "logs"
LOG_PATH = LOG_DIR / "raw-frontmatter-check.log"

DISABLED = os.environ.get("RAW_FRONTMATTER_CHECK_DISABLED", "0") == "1"
VERBOSE = os.environ.get("RAW_FRONTMATTER_CHECK_VERBOSE", "0") == "1"

EXCLUDE_PATH_PREFIXES = (
    ".claude/", ".obsidian/", "daily notes/", "inbox/", "templates/",
    "clippings/", "archives/",
)
# Substring exclusions: any path containing one of these is out of scope.
# Plugin dev directories nested under Projects/<X>/plugin/ have their own
# format rules (plugin.json + slash-command frontmatter), not vault rules.
EXCLUDE_PATH_SUBSTRINGS = (
    "/plugin/",
    "/skill/",
)
EXCLUDE_FILES = {
    "STATE.md", "PROJECT.md", "task_plan.md", "MEMORY.md", "Home.md",
    "CLAUDE.md", "README.md", "ARCHITECTURE.md", "INDEX.md", "log.md",
}
# Wiki-layer paths: excluded; wiki-citation-check.py handles
WIKI_LAYER_PREFIXES = ("resources/kb/",)

REQUIRED_FIELDS = ("date", "tags", "status")


def log(msg):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


def is_in_scope(file_path: Path) -> bool:
    try:
        rel = file_path.resolve().relative_to(VAULT.resolve()).as_posix()
    except Exception:
        return False
    if file_path.name in EXCLUDE_FILES:
        return False
    if not rel.endswith(".md"):
        return False
    rel_lower = rel.lower()
    if any(rel_lower.startswith(p) for p in EXCLUDE_PATH_PREFIXES):
        return False
    if any(s in "/" + rel_lower for s in EXCLUDE_PATH_SUBSTRINGS):
        return False
    if any(rel_lower.startswith(p) for p in WIKI_LAYER_PREFIXES):
        return False
    # Excluded sub-paths: */work/ artifacts get a softer pass since they're transient
    # Still include in check: the owner's `feedback_framework_overhead_on_small_tasks.md`
    # is acknowledged; this is warn-only and stays out of the way
    return True


def has_wiki_tag(text: str) -> bool:
    """Quick check: does frontmatter contain #wiki tag in tags list?"""
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end < 0:
        return False
    fm_text = text[3:end].lower()
    # Check tags line
    for line in fm_text.split("\n"):
        if line.lstrip().startswith("tags:"):
            if "wiki" in line:
                # disambiguate from wiki-status, wiki_status
                tokens = re.findall(r"[\w/-]+", line.partition(":")[2])
                if "wiki" in tokens:
                    return True
    return False


def parse_frontmatter_fields(text: str) -> set:
    """Return set of top-level field names present in frontmatter."""
    if not text.startswith("---"):
        return set()
    end = text.find("\n---", 3)
    if end < 0:
        return set()
    fm_text = text[3:end]
    fields = set()
    for line in fm_text.split("\n"):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" in s and not s.startswith("- "):
            key = s.split(":", 1)[0].strip()
            if key:
                fields.add(key.lower())
    return fields


def emit_advisory(missing, file_path, has_frontmatter):
    short_path = str(file_path).replace(str(VAULT) + os.sep, "").replace("\\", "/")
    msg = f"[RAW-FRONTMATTER-CHECK: ADVISORY] {short_path}\n"
    if not has_frontmatter:
        msg += "No frontmatter block: raw-layer files require `date`, `tags`, `status`.\n"
        msg += "Add a `---`-delimited YAML block at top of file.\n"
    else:
        msg += f"Frontmatter missing required fields: {', '.join(sorted(missing))}\n"
        msg += "Spec R3 requires `date` (ISO YYYY-MM-DD), `tags` (YAML list of canonical), `status` (enum).\n"
    msg += "Reference: Projects/Vault-Maintenance/work/2026-05-11-target-structure-spec.md § R3"
    try:
        out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}}
        print(json.dumps(out))
    except Exception:
        pass


def main():
    if DISABLED:
        return
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return
    tool_name = payload.get("tool_name") or payload.get("tool", "")
    if tool_name not in ("Write", "Edit"):
        return
    file_path_str = (
        (payload.get("tool_input") or {}).get("file_path")
        or (payload.get("input") or {}).get("file_path")
        or ""
    )
    if not file_path_str:
        return
    fp = Path(file_path_str)
    if not is_in_scope(fp):
        return
    if not fp.is_file():
        return
    try:
        text = fp.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    # Skip files that are wiki-layer (have #wiki tag): wiki-citation-check.py handles
    if has_wiki_tag(text):
        return
    has_frontmatter = text.startswith("---")
    fields = parse_frontmatter_fields(text) if has_frontmatter else set()
    missing = [f for f in REQUIRED_FIELDS if f not in fields]
    if missing or not has_frontmatter:
        emit_advisory(set(missing), fp, has_frontmatter)
        if VERBOSE:
            log(f"WARN {fp.name}: missing={missing}")
    elif VERBOSE:
        log(f"PASS {fp.name}")


if __name__ == "__main__":
    main()
