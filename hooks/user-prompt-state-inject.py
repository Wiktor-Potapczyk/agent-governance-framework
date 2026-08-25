#!/usr/bin/env python3
"""UserPromptSubmit state-injection hook (H-3, 2026-05-10).

Throttled re-orientation reminder for long-running sessions. Fires only when:
  (a) >30 min elapsed since last injection, OR
  (b) the active project's STATE.md mtime changed since last injection

Active project = most-recently-modified STATE.md among all projects discovered by
`_project_discovery` (bounded depth 2, keyed on the full relative identity, so
nested projects are candidates). Matches H-1 logic, which shares the helper.

Throttle state at .claude/hooks/_state/last-state-inject.json:
  {"last_emit_ts": <unix>, "last_state_mtime": <unix>, "last_project": "Name"}
`last_project` now stores a slash identity such as `Personal/Finance`. The
comparison in should_emit is plain string equality, so the first run after this
change sees a project-change and fires once. That is expected and harmless.

Output contract: stdout JSON per UserPromptSubmit spec.
Skip rules:
  - Subagent invocation (agent_id or agent_type set): skip: sub-context, no need
  - Trivial prompts (yes/no/ok/continue/etc.): skip: keep ack-only turns clean
  - No active project found: skip
"""
import json
import os
import re
import sys
import time
from datetime import datetime

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PROJECTS_DIR = os.path.join(VAULT, "Projects")
# Test seam added 2026-08-23, scoped to this hook rather than named generically,
# because no other hook honours it and a half-implemented generic override is a
# trap. Whether this hook emits is a function of elapsed time and of the throttle
# file, so a probe both depended on ambient state and, worse, WROTE it: every
# probe run stamped last_emit_ts=now on the live file and suppressed the next
# real state injection for 30 minutes. Probing the system must not steer it.
STATE_DIR = os.environ.get("STATE_INJECT_STATE_DIR") or os.path.join(
    VAULT, ".claude", "hooks", "_state")
THROTTLE_FILE = os.path.join(STATE_DIR, "last-state-inject.json")

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


def detect_active_project(raw=""):
    """Return (relative_identity, state_path, plan_path_or_None) for the most-recently-modified STATE.md.

    No override and no fallback, preserving this hook's current behaviour: an
    empty Projects/ still yields (None, None, None) and the caller emits empty
    context. What changes is that nested projects are now candidates, and the
    identity is the full relative path (`Personal/Finance`) rather than a leaf.

    `raw` is the raw stdin payload from main() (may be ""), used only to attach
    a session id to the degraded-path log record below.
    """
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _project_discovery import detect_active_project as _detect
    except Exception as e:
        # Observability for the total-loss case: an import failure here silently
        # empties the orientation reminder with no trace. Fail-open is preserved
        # (still returns None, None, None), this only adds a record of why.
        try:
            from _governance_logger import log_fire, session_from
            log_fire("user-prompt-state-inject", decision="degraded",
                     detail="_project_discovery unavailable: %s" % e,
                     session=session_from(raw))
        except Exception:
            pass
        return None, None, None
    return _detect(PROJECTS_DIR)


def load_throttle_state():
    if not os.path.isfile(THROTTLE_FILE):
        return {}
    try:
        with open(THROTTLE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_throttle_state(state):
    """Atomic write: temp file + os.replace handles concurrent sessions on NTFS."""
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = THROTTLE_FILE + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, THROTTLE_FILE)
    except Exception:
        pass


def should_emit(project, state_mtime, throttle_state):
    """Return (bool, reason): fire if mtime changed OR >30min elapsed OR project changed."""
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
            # Size guard: read at most 512KB (any real STATE.md is well under this)
            sz = os.path.getsize(state_path)
            cap = 512_000
            with open(state_path, "r", encoding="utf-8") as f:
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
            with open(plan_path, "r", encoding="utf-8") as f:
                plan_text = f.read()
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
    parts = [f"[STATE REMINDER {ts}: trigger: {reason}]"]
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
        "Re-read STATE.md / task_plan.md from disk before acting on project-specific work: this is orientation only."
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

    project, state_path, plan_path = detect_active_project(raw)
    if not project or not state_path:
        emit_empty()
        return

    try:
        state_mtime = os.path.getmtime(state_path)
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
        # Never break the prompt submission: emit empty on any failure
        try:
            emit_empty()
        except Exception:
            pass
