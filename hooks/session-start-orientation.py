#!/usr/bin/env python3
"""SessionStart orientation reader (H-1, 2026-05-10).

Detects active project + reads STATE.md + open task_plan.md items + last 3 decisions.
Emits hookSpecificOutput.additionalContext as plain-English orientation summary.

Active project detection (in order), delegated to `_project_discovery`:
1. Override file `.claude/active-project.txt` holding the full relative
   identity of a project, e.g. `Personal/Finance` (not the bare leaf)
2. Most-recently-modified STATE.md among all discovered projects
3. Fallback: 'your-project' (vault stewardship hub)

Discovery is bounded at depth 2 below Projects/ and keyed on the relative
identity, so nested projects are visible here. FALLBACK_PROJECT is compared as
a relative identity too; it stays a bare name only because that project is
still top-level.

Output contract: stdout JSON per Anthropic SessionStart hook spec.
Never blocks: errors silently swallowed, empty additionalContext on failure.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

def find_workspace_root() -> str:
    """Walk up from this file's location to find workspace root (dir containing CLAUDE.md)."""
    candidate = Path(__file__).resolve().parent
    for _ in range(10):
        if (candidate / "CLAUDE.md").exists():
            return str(candidate)
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    # Fallback: 3 levels up from hooks/ → .claude/ → workspace root
    return str(Path(__file__).resolve().parents[2])


VAULT = find_workspace_root()
PROJECTS_DIR = os.path.join(VAULT, "Projects")
OVERRIDE_FILE = os.path.join(VAULT, ".claude", "active-project.txt")
FALLBACK_PROJECT = "your-project"

OPEN_ITEMS_LIMIT = 10
DECISIONS_LIMIT = 3
STATE_SUMMARY_CHAR_LIMIT = 600


def detect_active_project():
    """Return (relative_identity, state_path, plan_path) tuple. Either path may be None.

    Three-tier order (override, most-recent STATE.md, fallback) is unchanged;
    the scan behind it now lives in the shared helper. Fail-open: if the helper
    cannot be imported the hook still returns the fallback rather than raising,
    because this runs at SessionStart.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _project_discovery import detect_active_project as _detect
    except Exception:
        sp = os.path.join(PROJECTS_DIR, FALLBACK_PROJECT, "STATE.md")
        plan = os.path.join(PROJECTS_DIR, FALLBACK_PROJECT, "task_plan.md")
        return (FALLBACK_PROJECT,
                sp if os.path.isfile(sp) else None,
                plan if os.path.isfile(plan) else None)

    return _detect(PROJECTS_DIR, override_file=OVERRIDE_FILE, fallback=FALLBACK_PROJECT)


def extract_status_summary(state_text):
    """Pull status indicator + last_action from STATE.md frontmatter + first body section."""
    lines = state_text.split("\n")
    status = ""
    last_action = ""
    in_frontmatter = False
    fm_lines = []
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if i == 0:
                in_frontmatter = True
                continue
            elif in_frontmatter:
                in_frontmatter = False
                break
        if in_frontmatter:
            fm_lines.append(line)

    fm_text = "\n".join(fm_lines)
    m = re.search(r"^status:\s*[\"']?([^\"'\n]+)[\"']?", fm_text, re.MULTILINE)
    if m:
        status = m.group(1).strip()
    m = re.search(r"^last_action:\s*[\"']?(.+?)[\"']?$", fm_text, re.MULTILINE)
    if m:
        last_action = m.group(1).strip()
    return status, last_action


def extract_open_tasks(plan_text, limit=OPEN_ITEMS_LIMIT):
    """Pull open `[ ]` items from task_plan.md, capped at limit."""
    if not plan_text:
        return []
    # Match `- [ ] **TASK-ID**: text` or `- [ ] text`
    items = []
    for line in plan_text.split("\n"):
        m = re.match(r"^\s*-\s*\[\s\]\s*(.+)$", line)
        if m:
            text = m.group(1).strip()
            # Truncate long items
            if len(text) > 180:
                text = text[:180] + "..."
            items.append(text)
            if len(items) >= limit:
                break
    return items


def extract_recent_decisions(state_text, limit=DECISIONS_LIMIT):
    """Pull entries from `## Recent Decisions` section."""
    if not state_text:
        return []
    m = re.search(r"##\s*Recent Decisions\s*\n(.+?)(?:\n##\s|\Z)", state_text, re.DOTALL)
    if not m:
        return []
    decisions = []
    for line in m.group(1).split("\n"):
        line = line.strip()
        if not line or line.startswith("##"):
            continue
        # Match dash-bulleted lines OR ISO-date-prefixed lines (avoids false-positive on bare digits)
        if re.match(r"^(?:-\s+|\d{4}-\d{2}-\d{2})", line):
            text = line.lstrip("-").strip()
            if len(text) > 200:
                text = text[:200] + "..."
            decisions.append(text)
            if len(decisions) >= limit:
                break
    return decisions


def get_cost_line():
    """Best-effort: call cost-summary.py for last-24h API-equivalent value. Returns one short line or empty."""
    try:
        import subprocess
        script = os.path.join(VAULT, ".claude", "scripts", "cost-summary.py")
        if not os.path.isfile(script):
            return ""
        result = subprocess.run(
            ["C:/Program Files/Python314/python.exe", script, "--hours", "24", "--json"],
            capture_output=True, text=True, timeout=4,
        )
        if result.returncode != 0:
            return ""
        data = json.loads(result.stdout)
        totals = data.get("totals", {})
        cost = totals.get("total_cost_usd", 0)
        turns = totals.get("turn_count", 0)
        if turns == 0:
            return ""
        return f"Last 24h: ${cost:.2f} API-equivalent ({turns} turns; Max 5x flat-billed, this is usage proxy)"
    except Exception:
        return ""


def build_orientation_text(project, status, last_action, open_tasks, decisions):
    """Compose plain-English orientation block for additionalContext."""
    parts = [f"[VAULT ORIENTATION: {datetime.now().strftime('%Y-%m-%d %H:%M')}]"]
    parts.append(f"Active project: {project}")
    cost_line = get_cost_line()
    if cost_line:
        parts.append(cost_line)
    if status:
        parts.append(f"Status: {status}")
    if last_action:
        # Truncate last_action to fit budget
        la = last_action[:STATE_SUMMARY_CHAR_LIMIT]
        if len(last_action) > STATE_SUMMARY_CHAR_LIMIT:
            la += "..."
        parts.append(f"Last action: {la}")

    if open_tasks:
        parts.append(f"\nOpen tasks ({len(open_tasks)} of top-{OPEN_ITEMS_LIMIT}):")
        for t in open_tasks:
            parts.append(f"  - {t}")
    else:
        parts.append("\nNo open tasks found in task_plan.md.")

    if decisions:
        parts.append(f"\nRecent decisions:")
        for d in decisions:
            parts.append(f"  - {d}")

    parts.append(
        "\nRecall stack (use the right tool: don't default to raw Grep):"
        "\n  - qmd `mcp__qmd__query`: hybrid lex+vec SEARCH over the memory files + Resources/KB. "
        "Use BEFORE grepping the memory folder; it's the doctrinally-correct first move for 'find what I wrote about X'."
        "\n  - memory graph `mcp__memory__*`: RELATIONAL queries: what's connected to / blocks / depends-on X. Not semantic search."
        "\n  - memory/*.md + MEMORY.md: durable one-fact recall; MEMORY.md is the index, qmd serves the bodies."
    )
    parts.append(
        "\nReminder: STATE.md / task_plan.md / PROJECT.md are the canonical state. "
        "Read them in full when tackling project-specific work: this summary is orientation only."
    )
    return "\n".join(parts)


_SESSION = None  # set from the payload in main(); None when identity is absent


def _log_fire(decision, detail=None):
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("session-start-orientation", decision=decision, detail=detail,
                 session=_SESSION)
    except Exception:
        pass


def main():
    global _SESSION
    # Read stdin payload. Orientation itself does not need the content; the
    # session id in it is what makes the fire record attributable.
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(raw)
    except Exception:
        _SESSION = None

    try:
        project, state_path, plan_path = detect_active_project()

        # Size guard: read at most 512KB; any real STATE.md/task_plan.md is well under this
        cap = 512_000
        state_text = ""
        if state_path and os.path.isfile(state_path):
            try:
                sz = os.path.getsize(state_path)
                with open(state_path, "r", encoding="utf-8") as f:
                    state_text = f.read(cap if sz > cap else -1)
            except Exception:
                pass

        plan_text = ""
        if plan_path and os.path.isfile(plan_path):
            try:
                sz = os.path.getsize(plan_path)
                with open(plan_path, "r", encoding="utf-8") as f:
                    plan_text = f.read(cap if sz > cap else -1)
            except Exception:
                pass

        status, last_action = extract_status_summary(state_text)
        open_tasks = extract_open_tasks(plan_text)
        decisions = extract_recent_decisions(state_text)

        orientation = build_orientation_text(project, status, last_action, open_tasks, decisions)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": orientation,
            }
        }
        print(json.dumps(output))
        _log_fire("orient", "project=%s chars=%d" % (project, len(orientation)))
    except Exception:
        # Never break session start: emit empty additional context on failure
        _log_fire("error")
        try:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "",
                }
            }))
        except Exception:
            pass


if __name__ == "__main__":
    main()
