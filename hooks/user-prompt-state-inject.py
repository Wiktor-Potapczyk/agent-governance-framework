#!/usr/bin/env python3
"""UserPromptSubmit state-injection hook (H-3, 2026-05-10).

Throttled re-orientation reminder for long-running sessions. Fires only when:
  (a) >30 min elapsed since last injection, OR
  (b) the active project's STATE.md mtime changed since last injection

Active project = most-recently-modified Projects/*/STATE.md (matches H-1 logic).

Throttle state at .claude/hooks/_state/last-state-inject.json:
  {"last_emit_ts": <unix>, "last_state_mtime": <unix>, "last_project": "Name"}

Output contract: stdout JSON per UserPromptSubmit spec.
Skip rules:
  - Subagent invocation (agent_id or agent_type set): skip — sub-context, no need
  - Trivial prompts (yes/no/ok/continue/etc.): skip — keep ack-only turns clean
  - No active project found: skip
"""
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path


def _find_workspace_root() -> Path:
    """Walk up from this file's directory until we find CLAUDE.md (workspace root).

    Falls back to the directory two levels above hooks/ (the conventional layout
    is <root>/.claude/hooks/<this-file> or <root>/hooks/<this-file>).
    """
    here = Path(os.path.abspath(__file__)).parent
    # Walk up looking for CLAUDE.md
    candidate = here
    for _ in range(8):  # cap at 8 levels to avoid runaway
        if (candidate / "CLAUDE.md").exists():
            return candidate
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent
    # Fallback: assume hooks/ is directly inside workspace root
    return here.parent


WORKSPACE = _find_workspace_root()
PROJECTS_DIR = WORKSPACE / "Projects"
STATE_DIR = WORKSPACE / ".claude" / "hooks" / "_state"
THROTTLE_FILE = STATE_DIR / "last-state-inject.json"

THROTTLE_SECONDS = 30 * 60  # 30 min
OPEN_TASKS_LIMIT = 5
LAST_ACTION_CHAR_LIMIT = 350

TRIVIAL_PROMPTS = {
    "yes", "no", "ok", "okay", "proceed", "continue", "done",
    "go ahead", "go", "sure", "hi", "hello", "hey", "thanks",
    "thank you", "got it", "sounds good", "confirmed", "nice",
    "great", "perfect", "y", "n",
}


def emit_empty():
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "",
        }
    }))


def detect_active_project():
    """Return (name, state_path, plan_path_or_None) for most-recently-modified STATE.md."""
    if not PROJECTS_DIR.is_dir():
        return None, None, None
    best = None
    best_mtime = 0
    for entry in PROJECTS_DIR.iterdir():
        sp = entry / "STATE.md"
        if sp.is_file():
            try:
                mt = sp.stat().st_mtime
                if mt > best_mtime:
                    best_mtime = mt
                    best = (entry.name, sp, mt)
            except Exception:
                continue
    if not best:
        return None, None, None
    name, sp, _ = best
    plan = sp.parent / "task_plan.md"
    return name, sp, (plan if plan.is_file() else None)


def load_throttle_state():
    if not THROTTLE_FILE.is_file():
        return {}
    try:
        return json.loads(THROTTLE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_throttle_state(state):
    """Atomic write — temp file + os.replace handles concurrent sessions on NTFS."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = THROTTLE_FILE.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(THROTTLE_FILE)
    except Exception:
        pass


def should_emit(project, state_mtime, throttle_state):
    """Return (bool, reason) — fire if mtime changed OR >30min elapsed OR project changed."""
    last_ts = throttle_state.get("last_emit_ts", 0)
    last_mtime = throttle_state.get("last_state_mtime", 0)
    last_project = throttle_state.get("last_project", "")
    now = time.time()

    if project != last_project:
        return True, "project-change"
    if state_mtime != last_mtime:
        return True, "state-changed"
    if (now - last_ts) >= THROTTLE_SECONDS:
        return True, "elapsed"
    return False, ""


def build_orientation(project, state_path, plan_path, reason):
    state_text = ""
    if state_path:
        try:
            # Size guard — read at most 512KB (any real STATE.md is well under this)
            sp = Path(state_path)
            sz = sp.stat().st_size
            cap = 512_000
            with sp.open("r", encoding="utf-8") as f:
                state_text = f.read(cap if sz > cap else -1)
        except Exception:
            pass

    status = ""
    last_action = ""
    m = re.search(r"^status:\s*[\"']?([^\"'\n]+)[\"']?", state_text, re.MULTILINE)
    if m:
        status = m.group(1).strip()
    m = re.search(r"^last_action:\s*[\"']?(.+?)[\"']?\s*$", state_text, re.MULTILINE)
    if m:
        last_action = m.group(1).strip()
        if len(last_action) > LAST_ACTION_CHAR_LIMIT:
            last_action = last_action[:LAST_ACTION_CHAR_LIMIT] + "..."

    open_tasks = []
    if plan_path:
        try:
            plan_text = Path(plan_path).read_text(encoding="utf-8")
            for line in plan_text.split("\n"):
                m = re.match(r"^\s*-\s*\[\s\]\s*(.+)$", line)
                if m:
                    text = m.group(1).strip()
                    if len(text) > 150:
                        text = text[:150] + "..."
                    open_tasks.append(text)
                    if len(open_tasks) >= OPEN_TASKS_LIMIT:
                        break
        except Exception:
            pass

    ts = datetime.now().strftime("%H:%M")
    parts = [f"[STATE REMINDER {ts} — trigger: {reason}]"]
    parts.append(f"Active project: {project}")
    if status:
        parts.append(f"Status: {status}")
    if last_action:
        parts.append(f"Last action: {last_action}")
    if open_tasks:
        parts.append(f"Top {len(open_tasks)} open task(s):")
        for t in open_tasks:
            parts.append(f"  - {t}")
    parts.append(
        "Re-read STATE.md / task_plan.md from disk before acting on project-specific work — this is orientation only."
    )
    return "\n".join(parts)


def main():
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:
        pass

    # Skip subagent invocations + read effort.level for low-effort skip
    is_subagent = False
    prompt_text = ""
    effort_level = ""
    if raw:
        try:
            data = json.loads(raw)
            prompt_text = (data.get("prompt") or "").strip()
            is_subagent = bool(data.get("agent_id") or data.get("agent_type"))
            # effort.level is an object per Anthropic Week 19 hook payload spec
            effort = data.get("effort") or {}
            if isinstance(effort, dict):
                effort_level = (effort.get("level") or "").strip().lower()
        except Exception:
            pass

    if is_subagent:
        emit_empty()
        return

    # Skip on low-effort turns (per Week 19 effort.level field) to reduce noise on conversational follow-ups
    if effort_level == "low":
        emit_empty()
        return

    # Skip trivial prompts to keep ack-only turns clean
    if prompt_text and prompt_text.lower() in TRIVIAL_PROMPTS:
        emit_empty()
        return

    project, state_path, plan_path = detect_active_project()
    if not project or not state_path:
        emit_empty()
        return

    try:
        state_mtime = Path(state_path).stat().st_mtime
    except Exception:
        emit_empty()
        return

    throttle_state = load_throttle_state()
    fire, reason = should_emit(project, state_mtime, throttle_state)
    if not fire:
        emit_empty()
        return

    orientation = build_orientation(project, state_path, plan_path, reason)

    save_throttle_state({
        "last_emit_ts": int(time.time()),
        "last_state_mtime": state_mtime,
        "last_project": project,
    })

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": orientation,
        }
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never break the prompt submission — emit empty on any failure
        try:
            emit_empty()
        except Exception:
            pass
