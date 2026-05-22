"""
Verifier Gate Check - Stop Hook
Enforces the contract of the `verification-gated-research` skill: if that skill
was invoked this session, completion is blocked until a SEPARATE verifier agent
was dispatched.

SCOPING DECISION (deliberate, documented):
This hook fires ONLY when the `verification-gated-research` skill was actually
invoked. It does NOT attempt to force every Research/depth task through a
verifier — that broader ambition is a false-positive minefield (normal
process-research dispatches research-synthesizer/report-generator, which are
not verifiers, and blocking those would be wrong). Instead this hook enforces
the skill's OWN internal contract: you cannot invoke the verification-gated
harness and then skip its separate-verifier step. Narrow, reliable, near-zero
false-positive. Forcing the harness onto all research is a doctrine/classifier
concern, not this hook's job.

Detection:
- skill invoked  = a Skill tool_use with skill == "verification-gated-research"
- verifier present = an Agent tool_use whose `description` contains "verifier",
  appearing AFTER the skill invocation in the transcript (ordering guard — a
  pre-existing "verifier"-described agent earlier in the session does not count).
  The skill mandates the verifier dispatch's description carry that word.

Block condition: skill invoked AND no post-skill verifier dispatch found.

Known limitation (accepted): the check keys off the description convention, not
the agent's subagent_type. It cannot structurally prove the verifier is a
different agent than the workers — and it deliberately does NOT try to: a
verifier legitimately CAN be the same agent type as a worker (e.g.,
technical-researcher used for both investigation and verification, in different
dispatches with different tasks). The separation that matters is generator-
dispatch vs verifier-dispatch as distinct tool_use blocks with distinct roles,
which the description signal captures. Enforcing subagent_type difference would
wrongly reject the legitimate same-type case. The skill's instruction layer
carries the orchestrator/worker-is-not-verifier rule; this hook enforces that a
separate verifier dispatch happened at all.
"""

import sys
import json
import os

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
READ_BYTES = 204800  # 200KB transcript tail — matches dispatch-compliance-check.py

SKILL_NAME = "verification-gated-research"


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    # Never recurse: if a prior Stop hook already fired, do not re-evaluate.
    if payload.get("stop_hook_active"):
        return

    transcript_path = payload.get("transcript_path")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    file_size = os.path.getsize(transcript_path)
    read_bytes = min(READ_BYTES, file_size)
    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
        f.seek(max(0, file_size - read_bytes))
        tail = f.read()

    skill_invoked = False
    verifier_dispatched = False

    for line in tail.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        for block in entry.get("message", {}).get("content", []):
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "")
            inp = block.get("input", {})
            if isinstance(inp, str):
                try:
                    inp = json.loads(inp)
                except (json.JSONDecodeError, TypeError):
                    inp = {}

            if name == "Skill" and (inp.get("skill") or "").lower() == SKILL_NAME:
                skill_invoked = True

            # Ordering guard: only count a verifier dispatch that appears AFTER
            # the skill invocation. The scan is chronological, so skill_invoked
            # being True here means the skill tool_use was seen earlier.
            elif name == "Agent" and skill_invoked:
                description = (inp.get("description") or "").lower()
                if "verifier" in description:
                    verifier_dispatched = True

    if not skill_invoked:
        return  # hook is dormant unless the harness skill was used

    if verifier_dispatched:
        _log("pass")
        return

    reason = (
        "VERIFIER GATE: the `verification-gated-research` skill was invoked but no "
        "separate verifier agent was dispatched. The harness requires a distinct "
        "Agent dispatch (description containing \"verifier\") that is neither a "
        "worker nor the orchestrator. Dispatch the verifier and let it gate the "
        "backlog ledger before completing — completion is the ledger state, not "
        "your assertion."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    _log("block")


def _log(event):
    try:
        from datetime import datetime
        log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
        entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "hook": "verifier-gate",
            "skill": SKILL_NAME,
            "schema": 2,
        })
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
