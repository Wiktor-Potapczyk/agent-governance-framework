#!/usr/bin/env python3
"""inbox-auto-ingest.py — PostToolUse Write|Edit hook (M1 auto-trigger).

Karpathy LLM-Wiki adoption auto-trigger. When a file is written or edited in
Inbox/, emit additionalContext signaling that process-ingest should run on the
file. The next conversation turn sees the context and routes to ingest.

Bypasses file-watcher unreliability by using Claude Code's own tool-event trigger.

Schema:
- input: PostToolUse hook payload via stdin
- output: stdout JSON {hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: str}}

Logged to: .claude/hooks/aggregates/inbox-ingest-triggers.jsonl

Workspace root detection: walks up from this file's location until a directory
containing CLAUDE.md is found (standard framework-repo convention).
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def find_workspace_root() -> Path:
    """Walk up from this file's location to find the workspace root (dir containing CLAUDE.md)."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "CLAUDE.md").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    # Fallback: 3 levels up from hooks/ → .claude/ → workspace root
    return Path(__file__).resolve().parents[2]


WORKSPACE = find_workspace_root()
LOG = WORKSPACE / ".claude" / "hooks" / "aggregates" / "inbox-ingest-triggers.jsonl"
INBOX = WORKSPACE / "Inbox"
EXCLUDE_FILES = {".gitkeep", ".DS_Store", "Thumbs.db", "desktop.ini"}


def is_inbox_path(rel_path):
    rel_norm = rel_path.replace("\\", "/").lstrip("/")
    return rel_norm.startswith("Inbox/")


def log_trigger(rel_path, tool_name):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "file": rel_path,
            "tool": tool_name,
        }
        with LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return 0

    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    try:
        rel_path = str(Path(file_path).resolve().relative_to(WORKSPACE)).replace("\\", "/")
    except Exception:
        return 0

    if not is_inbox_path(rel_path):
        return 0

    if Path(rel_path).name in EXCLUDE_FILES:
        return 0

    log_trigger(rel_path, tool_name)

    msg = (
        f"[inbox-auto-ingest] New/edited file in Inbox: {rel_path}\n"
        f"Per Karpathy LLM-Wiki adoption (CLAUDE.md ## Karpathy LLM-Wiki Architecture, "
        f"## Inbox Processing Rules Rule 6), invoke `process-ingest` skill on this file "
        f"to integrate it into the wiki layer. Steps: read source, compute SHA, identify "
        f"3-10 related wiki pages, write summary with source: + SHA, update index.md + log.md, "
        f"move per Inbox Rules 1-5."
    )

    try:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": msg,
            }
        }
        print(json.dumps(out))
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
