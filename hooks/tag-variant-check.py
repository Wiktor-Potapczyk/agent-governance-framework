#!/usr/bin/env python3
"""tag-variant-check.py — PostToolUse Write hook (ADVISORY v1, 2026-05-11).

Wave 1.6 pre-migration enforcement for Vault-Maintenance Phase 5 Sticky Structure spec.

Scope:
  - Reads frontmatter tags from any .md write
  - For each tag NOT in canonical set: emit a canonical-form SUGGESTION if known alias
  - Distinct from H-9 vault-structure-check.py: this hook focuses ONLY on tag canonicality
    and SUGGESTS the canonical form (H-9 generically warns "no canonical tag found")

Behavior:
  - PostToolUse event payload arrives via stdin (JSON)
  - Activates on Write|Edit to .md files (any vault path)
  - Excludes .claude/, .obsidian/, .git/ paths
  - Excludes the canonical taxonomy file itself (CLAUDE.md) to avoid recursive flagging
  - Emit additionalContext via stdout JSON; never exit non-zero

Override: TAG_VARIANT_CHECK_DISABLED=1 to disable; TAG_VARIANT_CHECK_VERBOSE=1 to log PASSes.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
LOG_DIR = VAULT / ".claude" / "hooks" / "logs"
LOG_PATH = LOG_DIR / "tag-variant-check.log"

DISABLED = os.environ.get("TAG_VARIANT_CHECK_DISABLED", "0") == "1"
VERBOSE = os.environ.get("TAG_VARIANT_CHECK_VERBOSE", "0") == "1"

# Source of truth: Projects/Vault-Maintenance/work/2026-05-11-target-structure-spec.md § R4
CANONICAL_TAGS = {
    "idea", "research", "analysis", "planning", "task", "personal",
    "moc", "wiki", "vault", "vault-log",
    "n8n", "claude-code", "hooks", "agent", "ralph-loop",
    "active", "waiting", "done", "archived",
    "observability-v2", "ab-test", "memory", "handoff", "meta", "prep-section",
    "audit", "spec", "reference", "repo-investigation", "task-plan",
    "architecture", "agents", "s2b", "second-brain", "draft",
    "unclassified-pending",
    # Admitted v2.1 (2026-05-26 vault-tag-scan +5 frequency-promoted; spec R4 row "v2.1 admits"):
    "automation", "learning", "pitch", "dataview", "monitoring",
}

# Known aliases — map variant to canonical (from spec R4 v2 alias table)
ALIASES = {
    "awards-automation": "project/awards-automation",
    "complete": "done",
    "done.": "done",
    "review": "analysis",
    "company-research": "research",
    "vault-stewardship": "vault",
    "agent-governance": "project/agent-governance-research",
    "plan": "planning",
    "inventory": "analysis",
    "blueprint": "planning",
    "diagnostic": "analysis",
    "prompt-engineer": "agent",
    "autonomous-agents": "agent",
    "pending-review": "waiting",
    "peer-review": "waiting",
    "comparison": "analysis",
    "vault-design": "vault",
    "state": "",  # DELETE (mistagging of infrastructure files)
}

EXCLUDE_PATH_PREFIXES = (".claude/", ".obsidian/", ".git/")
EXCLUDE_FILES = {"CLAUDE.md"}  # canonical taxonomy file


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
    return True


def parse_frontmatter_tags(text: str):
    """Extract tag tokens from frontmatter. Handles YAML list + comma-separated formats."""
    if not text.startswith("---"):
        return []
    end = text.find("\n---", 3)
    if end < 0:
        return []
    fm_text = text[3:end]
    tags = []
    in_tags_block = False
    for line in fm_text.split("\n"):
        if line.lstrip().startswith("tags:"):
            raw = line.partition(":")[2].strip()
            # Inline list: tags: [a, b, c] OR tags: a, b, c OR tags: #a, #b
            if raw.startswith("["):
                raw = raw.strip("[]")
                for piece in re.split(r"[,\s]+", raw):
                    p = piece.strip().lstrip("#").strip("\"'")
                    if p:
                        tags.append(p)
            elif raw:
                for piece in re.split(r"[,\s]+", raw):
                    p = piece.strip().lstrip("#").strip("\"'")
                    if p:
                        tags.append(p)
            else:
                in_tags_block = True
            continue
        # YAML block-list style: tags:\n  - a\n  - b
        if in_tags_block:
            s = line.strip()
            if s.startswith("- "):
                p = s[2:].strip().lstrip("#").strip("\"'")
                if p:
                    tags.append(p)
            else:
                if line and not line.startswith((" ", "\t")):
                    in_tags_block = False
    return tags


def emit_advisory(suggestions, file_path):
    if not suggestions:
        return
    short_path = str(file_path).replace(str(VAULT) + os.sep, "").replace("\\", "/")
    msg = f"[TAG-VARIANT-CHECK — ADVISORY] {short_path}\n"
    msg += "Non-canonical tags detected:\n"
    for variant, canonical_suggest in suggestions:
        if canonical_suggest == "":
            msg += f"  - `{variant}` → DELETE (no semantic value; remove from tags)\n"
        elif canonical_suggest is None:
            msg += f"  - `{variant}` → unknown variant (no alias mapping); consider canonical-set match or `unclassified-pending`\n"
        else:
            msg += f"  - `{variant}` → use `{canonical_suggest}` (canonical)\n"
    msg += (
        "\nReference: Projects/Vault-Maintenance/work/2026-05-11-target-structure-spec.md § R4 "
        "for the full canonical taxonomy + alias table."
    )
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
    file_tags = parse_frontmatter_tags(text)
    if not file_tags:
        return  # no tags to check
    suggestions = []
    for t in file_tags:
        t_lower = t.lower()
        if t_lower in CANONICAL_TAGS:
            continue
        # Numeric garbage tags
        if re.match(r"^\d+$", t_lower) or re.match(r"^\d+[\d-]*$", t_lower):
            suggestions.append((t, ""))
            continue
        # project/<name> nested OK
        if t_lower.startswith("project/"):
            if len(t_lower.split("/", 1)[1]) > 0:
                continue
        # Known alias?
        if t_lower in ALIASES:
            suggestions.append((t, ALIASES[t_lower]))
            continue
        # Unknown variant
        suggestions.append((t, None))
    if suggestions:
        emit_advisory(suggestions, fp)
        if VERBOSE:
            log(f"WARN {fp.name}: {len(suggestions)} variant(s)")
    elif VERBOSE:
        log(f"PASS {fp.name}")


if __name__ == "__main__":
    main()
