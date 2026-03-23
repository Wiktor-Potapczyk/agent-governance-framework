#!/usr/bin/env python3
"""SubagentStart Hook - Inject governance context into subagent."""
import json
import sys
import os
from datetime import datetime

def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return

    if not raw:
        return

    try:
        payload = json.loads(raw)
    except Exception:
        return

    # Log to prove hook fired
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    agent_type = payload.get("agent_type", "unknown")
    agent_id = payload.get("agent_id", "unknown")

    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "subagent-governance.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} | agent_type={agent_type} | agent_id={agent_id}\n")
    except Exception:
        pass

    response = {
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": (
                "AGENT GOVERNANCE: Use multiple perspectives when analyzing - "
                "do not settle on the first answer. Cite specific evidence "
                "(file paths, line numbers, research findings) for claims. "
                "Structure output clearly with findings, evidence, and recommendations. "
                "Flag unexpected discoveries explicitly. State what you are uncertain "
                "about - do not present guesses as facts. Blind analysis rule: if "
                "evaluating something, do not anchor to a pre-existing conclusion."
            )
        }
    }
    print(json.dumps(response))

if __name__ == "__main__":
    main()
