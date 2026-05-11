#!/usr/bin/env python3
"""PreCompact hook — comprehensive state save before compaction.

Writes recovery file that SessionStart(compact) injects via restore-compact.sh.
Collects STATE.md files, active task plans, and recent transcript context.

Workspace detection: walks up from this file's location to find CLAUDE.md,
then resolves the Projects/ directory relative to that root.
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


WORKSPACE_ROOT = str(find_workspace_root(Path(__file__).parent))
RECOVERY = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), ".claude", "pre-compact-recovery.md")

# --- Read stdin payload ---
transcript_path = None
try:
    raw = sys.stdin.read()
    if raw:
        data = json.loads(raw)
        transcript_path = data.get("transcript_path")
except Exception:
    pass

# --- Collect STATE.md files ---
states_section = ""
projects_dir = os.path.join(WORKSPACE_ROOT, "Projects")
if os.path.isdir(projects_dir):
    for proj in os.listdir(projects_dir):
        state_path = os.path.join(projects_dir, proj, "STATE.md")
        if os.path.isfile(state_path):
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    content = f.read()
                states_section += f"\n--- {proj}/STATE.md ---\n{content}\n"
            except Exception:
                pass

# --- Collect task_plan.md files (In Progress + Shaped sections only) ---
plans_section = ""
if os.path.isdir(projects_dir):
    for proj in os.listdir(projects_dir):
        plan_path = os.path.join(projects_dir, proj, "task_plan.md")
        if os.path.isfile(plan_path):
            try:
                with open(plan_path, "r", encoding="utf-8") as f:
                    content = f.read()
                relevant = []
                capture = False
                for line in content.split("\n"):
                    if re.match(r"^## (In Progress|Shaped)", line):
                        capture = True
                    elif re.match(r"^## (Done|After|Medium|Parked|Blockers|Reference)", line):
                        capture = False
                    if capture:
                        relevant.append(line)
                if relevant:
                    text = "\n".join(relevant).strip()
                    if text:
                        plans_section += f"\n--- {proj}/task_plan.md (active items) ---\n{text}\n"
            except Exception:
                pass

# --- Extract transcript context (JSONL parsing) ---
transcript_section = ""
if transcript_path and os.path.isfile(transcript_path):
    try:
        file_size = os.path.getsize(transcript_path)
        tail_size = min(51200, file_size)

        with open(transcript_path, "rb") as f:
            f.seek(max(0, file_size - tail_size))
            tail = f.read().decode("utf-8", errors="replace")

        recent_user = []
        recent_files = []
        last_class = ""

        for jline in tail.split("\n"):
            jline = jline.strip()
            if not jline:
                continue
            try:
                entry = json.loads(jline)
            except json.JSONDecodeError:
                continue

            # User messages — extract text content
            if entry.get("type") == "human":
                msg = entry.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        text = block["text"]
                        if len(text) > 500:
                            text = text[:500] + "..."
                        recent_user.append(text)

            # Assistant messages — extract classification + file writes
            if entry.get("type") == "assistant":
                msg = entry.get("message", {})
                for block in msg.get("content", []):
                    if block.get("type") == "text" and block.get("text"):
                        m = re.search(
                            r"TASK TYPE:\s*(Quick|Research|Analysis|Content|Build|Planning|Compound)[^\n]*",
                            block["text"],
                        )
                        if m:
                            last_class = m.group(0)
                    if block.get("type") == "tool_use" and block.get("name") in ("Write", "Edit"):
                        inp = block.get("input", {})
                        fp = inp.get("file_path", "")
                        if fp and fp not in recent_files:
                            recent_files.append(fp)

        # Keep only last 3 user messages and 10 file paths
        recent_user = recent_user[-3:]
        recent_files = recent_files[-10:]

        # Build transcript section
        transcript_section = "\n## Recent Context\n"
        if recent_user:
            transcript_section += "\nLast user messages:\n"
            for msg in recent_user:
                clean = re.sub(r"[\r\n]+", " ", msg)
                transcript_section += f"- {clean}\n"
        if last_class:
            transcript_section += f"\nLast classification: {last_class}\n"
        if recent_files:
            transcript_section += "\nRecently modified files:\n"
            for fp in recent_files:
                transcript_section += f"- {fp}\n"
    except Exception:
        pass

# --- Write recovery file ---
timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
recovery = f"# Pre-Compaction Recovery ({timestamp})\n\n"
recovery += "Context was just compacted. Here is the state saved before compaction:\n\n"
recovery += f"## Project States\n{states_section}\n"
recovery += f"## Active Task Plans\n{plans_section}\n"
recovery += f"{transcript_section}\n"
recovery += "## Instructions\n"
recovery += "- Read the above state to understand what was happening before compaction\n"
recovery += "- Continue where you left off -- the recent context section shows what you were working on\n"
recovery += "- If state seems stale, re-read the STATE.md and task_plan.md files from disk\n"
recovery += "- Check recently modified files list to pick up where you left off\n"

os.makedirs(os.path.dirname(RECOVERY), exist_ok=True)
with open(RECOVERY, "w", encoding="utf-8") as f:
    f.write(recovery)

# Reset checkpoint timer
checkpoint_file = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")), ".claude", "last-checkpoint"
)
import time
with open(checkpoint_file, "w") as f:
    f.write(str(int(time.time())))

# --- H-2 stdout block REMOVED ---
# Empirical finding: PreCompact JSON output schema does NOT accept
# hookSpecificOutput.additionalContext (only PreToolUse / UserPromptSubmit /
# PostToolUse / PostToolBatch do). Hook was failing schema validation on every fire.
# Recovery file write above remains the working orientation mechanism (consumed by
# SessionStart(compact) via restore-compact.sh on next session).
