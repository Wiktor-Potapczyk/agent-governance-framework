#!/usr/bin/env python3
"""SubagentStart Hook - Check registry for better specialist agents.

When a general-purpose or untyped agent is dispatched, checks the prompt
against the agent registry keywords. If a specialist agent matches well,
injects a suggestion into additionalContext.

Does NOT block dispatches: advisory only.

Workspace detection: walks up from this file's location to find CLAUDE.md,
then resolves registry.json relative to that root.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def find_workspace_root(start: Path) -> Path:
    """Walk up directory tree until we find a directory containing CLAUDE.md."""
    current = start.resolve()
    for _ in range(10):
        if (current / "CLAUDE.md").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: two levels above the hooks/ directory (hooks/ -> .claude/ -> root)
    return start.parent.parent


WORKSPACE_ROOT = find_workspace_root(Path(__file__).parent)
REGISTRY_PATH = WORKSPACE_ROOT / ".claude" / "registry.json"
LOG_PATH = Path(__file__).parent / "agent-registry-check.log"

# Agent types that indicate "no specialist was chosen"
GENERIC_TYPES = {"general-purpose", "explore", "plan", "", "unknown"}

# Minimum keyword overlap to suggest a specialist
MIN_MATCH_SCORE = 3


def load_registry():
    """Load registry.json, return agents dict or empty."""
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("agents", {})
    except Exception:
        return {}


def extract_words(text: str) -> set[str]:
    """Extract lowercase words from text for matching."""
    return set(re.findall(r"[a-z][a-z0-9\-]+", text.lower()))


def find_specialists(prompt_words: set[str], agents: dict, current_type: str) -> list[tuple[str, int, str]]:
    """Find specialist agents whose keywords overlap with the prompt.

    Returns list of (agent_name, score, description) sorted by score desc.
    """
    matches = []
    for name, info in agents.items():
        # Skip generic agents and the agent being dispatched
        if name in GENERIC_TYPES or name == current_type:
            continue
        # Skip plugin meta-agents (creator, validator, etc.)
        if name in {"agent-creator", "plugin-validator", "skill-reviewer", "code-simplifier"}:
            continue

        keywords = set(info.get("keywords", []))
        if not keywords:
            continue

        overlap = prompt_words & keywords
        score = len(overlap)

        if score >= MIN_MATCH_SCORE:
            desc = info.get("description", "")[:100]
            matches.append((name, score, desc))

    matches.sort(key=lambda x: -x[1])
    return matches[:3]  # Top 3 suggestions


def main():
    try:
        raw = sys.stdin.buffer.read(204800)
        payload = json.loads(raw)
    except Exception:
        return

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("agent-registry-check",
                 detail=payload.get("subagent_type", payload.get("agent_type", "")))
    except Exception:
        pass

    agent_type = payload.get("subagent_type", payload.get("agent_type", "")).lower()
    agent_id = payload.get("agent_id", "unknown")

    # Only check generic dispatches
    if agent_type not in GENERIC_TYPES:
        return

    # Get the prompt/description
    prompt = payload.get("prompt", "") or payload.get("description", "") or ""
    if not prompt:
        return

    agents = load_registry()
    if not agents:
        return

    prompt_words = extract_words(prompt)
    specialists = find_specialists(prompt_words, agents, agent_type)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if specialists:
        suggestions = "; ".join(f"{name} (score:{score})" for name, score, _ in specialists)

        # Log the suggestion
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} | type={agent_type} | id={agent_id} | suggestions={suggestions}\n")
        except Exception:
            pass

        # Build suggestion text
        lines = ["SPECIALIST SUGGESTION: The following specialist agents may be better suited for this task:"]
        for name, score, desc in specialists:
            lines.append(f"  - {name}: {desc}")
        lines.append("Consider whether a specialist dispatch would produce better results.")
        suggestion_text = "\n".join(lines)

        response = {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": suggestion_text,
            }
        }
        print(json.dumps(response))
    else:
        # No suggestions: log silently
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} | type={agent_type} | id={agent_id} | no_match\n")
        except Exception:
            pass


if __name__ == "__main__":
    main()
