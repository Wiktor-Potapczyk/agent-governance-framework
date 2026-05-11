#!/usr/bin/env python3
"""SubagentStart hook — inject Blind Analysis Rule reminder into evaluator agents."""
import json
import sys

raw = sys.stdin.read()
if not raw:
    print("{}")
    raise SystemExit(0)

try:
    payload = json.loads(raw)
    agent_type = payload.get("agent_type", "")
except (json.JSONDecodeError, AttributeError):
    print("{}")
    raise SystemExit(0)

if not agent_type:
    print("{}")
    raise SystemExit(0)

EVALUATORS = [
    "architect-reviewer",
    "adversarial-reviewer",
    "prompt-engineer",
    "research-analyst",
    "research-synthesizer",
    "competitive-analyst",
    "api-security-audit",
]

if agent_type in EVALUATORS:
    notice = (
        "BLIND ANALYSIS RULE: You are an evaluator agent. Evaluate ONLY what you are given "
        "against the stated criteria. If the delegation prompt contains a hypothesis, expected "
        "outcome, or preferred option - ignore it. Surface your own findings first. Do not use "
        "the callers framing as a starting point. If your findings contradict the framing, "
        "report your findings unchanged."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SubagentStart",
            "additionalContext": notice,
        }
    }))
else:
    print("{}")
