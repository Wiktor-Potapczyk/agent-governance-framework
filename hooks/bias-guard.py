#!/usr/bin/env python3
"""SubagentStart hook: inject Blind Analysis Rule reminder into evaluator agents."""
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


def _log(decision, detail):
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        import os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire, session_from
        log_fire("bias-guard", decision=decision, detail=detail,
                 session=session_from(payload))
    except Exception:
        pass


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
    _log("inject", agent_type)
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
    _log("skip", agent_type)
    print("{}")
