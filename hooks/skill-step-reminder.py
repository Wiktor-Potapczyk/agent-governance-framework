"""
Skill Step Reminder - PostToolUse Hook (matcher: Skill)
Fires after a process skill loads. Injects additionalContext reminding
about mandatory steps for that specific process skill.
Only fires for process-* skills. Non-process skills pass through silently.
"""

import sys
import json


# Mandatory steps per process skill
PROCESS_REMINDERS = {
    "process-research": (
        "PROCESS REMINDER: You MUST follow these steps in order. "
        "Step 1: Write RESEARCH SCOPE block. "
        "Step 2: Choose path (Ralph Loop or Direct). "
        "Step 3: Dispatch agents. "
        "Step 4: MUST synthesize if 2+ agents dispatched (research-synthesizer). "
        "Step 5: Save findings to work file. "
        "Do NOT skip synthesis when multiple agents contribute."
    ),
    "process-analysis": (
        "PROCESS REMINDER: You MUST follow these steps in order. "
        "Step 1: Write ANALYSIS SCOPE block (mode: Evaluation/Investigation/Decomposition). "
        "Step 2: Dispatch specialist agent(s) from the routing table. "
        "Step 3: MUST synthesize if 2+ agents dispatched (research-synthesizer). "
        "Step 4: Report findings. "
        "Do NOT skip synthesis when multiple agents contribute."
    ),
    "process-build": (
        "PROCESS REMINDER: You MUST follow these steps in order. "
        "Step 1: Write BUILD SCOPE block. "
        "Step 2: Delegate to implementation-plan. "
        "Step 3: Delegate to blueprint-mode (or domain specialist). "
        "Step 4: MUST dispatch architect-review. Skipping review is a process violation. "
        "Step 5: Quality check (live verification for n8n). "
        "Do NOT skip the review step."
    ),
    "process-planning": (
        "PROCESS REMINDER: You MUST follow these steps in order. "
        "Step 1: Write PLANNING SCOPE block. "
        "Step 2: Research if unknowns exist. "
        "Step 3: Delegate to implementation-plan. "
        "Step 4: MUST dispatch architect-review. Skipping review is a process violation. "
        "Step 5: Revise based on review. "
        "For high-stakes plans: MUST also dispatch adversarial-reviewer."
    ),
    "process-qa": (
        "PROCESS REMINDER: You MUST follow these steps in order. "
        "Step 1: List every verifiable claim (QA SCOPE block). "
        "Step 2: Choose verification method per claim. "
        "Step 3: Execute each test — do NOT reason about passing, actually run it. "
        "Step 4: Output QA REPORT with PASS/FAIL per claim. "
        "Step 5: Escalate failures — do NOT fix them, report them."
    ),
}


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # Get the skill that just loaded
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    skill_name = (tool_input.get("skill") or "").lower()

    # Only inject for process skills
    reminder = PROCESS_REMINDERS.get(skill_name)
    if not reminder:
        return

    result = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reminder
        }
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
