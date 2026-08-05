#!/usr/bin/env python3
"""PreToolUse(Grep) nudge: raise qmd-recall consciousness (2026-06-01).

Problem: qmd (the local hybrid search engine over the `memory` + `agr-kb`
collections) is the doctrinally-correct way to SEARCH the memory folder and
Resources/KB, but a soft CLAUDE.md mention decays to ~25% adherence: the main
session "forgets" qmd exists and reaches for raw `Grep` instead.

This hook fires on a `Grep` whose path targets either qmd-indexed corpus and
injects a one-line reminder to use `mcp__qmd__query` first. WARN-ONLY: it never
blocks; the Grep still runs. The reminder rides in via PreToolUse additionalContext.

Boundary test (deliberate, to avoid the over-nag failure mode):
- Fires ONLY on `Grep` (search intent: qmd's job) over the memory/KB dirs.
- Does NOT fire on `Read` (fetching a known file by path is legitimate; qmd's
  `get` is optional there, not a correction).
- Does NOT fire on Grep elsewhere in the vault (code, projects, etc.: qmd
  doesn't index those).

The two qmd collections this maps to:
- `memory`  → the `.claude/projects/<id>/memory/` one-fact files
- `agr-kb`  → `Resources/KB/` wiki pages

Exit 0 always. Fail-open: never crashes the turn.
"""
import json
import os
import sys


def _targets_qmd_corpus(path: str) -> str | None:
    """Return 'memory' or 'agr-kb' if the path is inside a qmd-indexed corpus, else None."""
    if not path:
        return None
    norm = path.replace("\\", "/").lower()
    if "/memory" in norm and "/projects/" in norm:
        return "memory"
    if "resources/kb" in norm:
        return "agr-kb"
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open

    tool_name = payload.get("tool_name", "")
    if tool_name != "Grep":
        return 0

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return 0
    # Grep's directory/file scope is in `path` (optional; defaults to cwd).
    path = tool_input.get("path", "") or ""
    corpus = _targets_qmd_corpus(path)
    if corpus is None:
        return 0

    # Self-log the fire (silent-zero instrument).
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("qmd-recall-nudge", decision="nudge", detail=corpus)
    except Exception:
        pass

    collection = "memory" if corpus == "memory" else "agr-kb"
    nudge = (
        f"qmd-recall: you're about to Grep the '{corpus}' corpus. qmd indexes this as "
        f"the '{collection}' collection: `mcp__qmd__query` (hybrid lex+vec, BM25 + "
        f"semantic) usually serves a SEARCH better than raw Grep, and is the "
        f"doctrinally-correct first move (CLAUDE.md Memory Recall / wiki-first). "
        f"If you need a SPECIFIC known file, Grep/Read is fine: ignore this. "
        f"The Grep will proceed; this is a reminder, not a block."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": nudge,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
