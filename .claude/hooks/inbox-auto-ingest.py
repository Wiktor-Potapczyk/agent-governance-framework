#!/usr/bin/env python3
"""inbox-auto-ingest.py — PostToolUse Write|Edit hook (M1 auto-trigger).

Karpathy LLM-Wiki adoption auto-trigger. When a file is written or edited in
Inbox/ or Clippings/, emit additionalContext signaling that process-ingest
should run on the file. The next conversation turn sees the context and
routes to ingest. Both directories are named as ingest sources in
.claude/rules/wiki-architecture.md (moved there from CLAUDE.md by the O16 trim).

Bypasses OneDrive file-watcher unreliability (CON-005) by using Claude Code's
own tool-event trigger.

Schema:
- input: PostToolUse hook payload via stdin
- output: stdout JSON {hookSpecificOutput: {hookEventName: "PostToolUse", additionalContext: str}}

Logged to: .claude/hooks/aggregates/inbox-ingest-triggers.jsonl
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# VAULT_ROOT override added 2026-09-10 so this hook can be tested at all. The
# path was hardcoded to one machine's absolute path, which meant (a) no suite
# could exercise the trigger branch without appending to the live aggregate,
# which is why this hook had no tests, and (b) the hook silently no-ops in a
# clone or worktree, since resolve().relative_to(VAULT) raises and returns 0.
# Same convention as HOOK_ACTIVITY_LOG_PATH / GOVERNANCE_LOG_PATH elsewhere.
VAULT = Path(os.environ.get("VAULT_ROOT")
             or Path(__file__).resolve().parent.parent.parent)
LOG = VAULT / ".claude" / "hooks" / "aggregates" / "inbox-ingest-triggers.jsonl"
INGEST_PREFIXES = ("Inbox/", "Clippings/")
EXCLUDE_FILES = {".gitkeep", ".DS_Store", "Thumbs.db", "desktop.ini"}


def is_ingest_trigger_path(rel_path):
    rel_norm = rel_path.replace("\\", "/").lstrip("/")
    return any(rel_norm.startswith(p) for p in INGEST_PREFIXES)


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

    # A JSON array or scalar payload reached payload.get() and raised
    # AttributeError, exiting 1 from a hook whose every other branch returns 0
    # (found by its first test suite, 2026-09-10). Same isinstance guard
    # pretooluse-payload-probe.py already carries; this is consistency with the
    # existing fail-open contract, not new behaviour.
    if not isinstance(payload, dict):
        return 0

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = payload.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    try:
        rel_path = str(Path(file_path).resolve().relative_to(VAULT)).replace("\\", "/")
    except Exception:
        return 0

    if not is_ingest_trigger_path(rel_path):
        return 0

    if Path(rel_path).name in EXCLUDE_FILES:
        return 0

    log_trigger(rel_path, tool_name)

    source_dir = rel_path.split("/", 1)[0]
    msg = (
        f"[inbox-auto-ingest] New/edited file in {source_dir}/: {rel_path}\n"
        f"Per Karpathy LLM-Wiki adoption (.claude/rules/wiki-architecture.md, "
        f".claude/rules/inbox-processing.md Rule 6), invoke `process-ingest` skill on this file "
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
