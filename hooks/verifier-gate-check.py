"""
Verifier Gate Check - Stop Hook
Enforces the contract of the `verification-gated-research` skill (SOTA-RECON-2,
Candidate 1E): if that skill was invoked this session, completion is blocked
until a SEPARATE verifier agent was dispatched.

SCOPING DECISION (deliberate, documented):
This hook fires ONLY when the `verification-gated-research` skill was actually
invoked. It does NOT attempt to force every Research/depth task through a
verifier: that broader ambition is a false-positive minefield (normal
process-research dispatches research-synthesizer/report-generator, which are
not verifiers, and blocking those would be wrong). Instead this hook enforces
the skill's OWN internal contract: you cannot invoke the verification-gated
harness and then skip its separate-verifier step. Narrow, reliable, near-zero
false-positive. Forcing the harness onto all research is a doctrine/classifier
concern, not this hook's job.

Detection (3-part structural check: upgraded 2026-06-16, two-gate Gate-2):
- skill invoked  = a Skill tool_use with skill == "verification-gated-research"
- A VALID verifier is an Agent tool_use that satisfies ALL THREE structural parts,
  all readable from the transcript tail:
    1. it carries "verifier" in its `description` AND appears AFTER all worker
       dispatches (and after the skill invocation: ordering guard kept);
    2. its task `prompt` is NOT byte-identical to any worker `prompt` (proves a
       different task, not just a relabel of a worker dispatch);
    3. its `prompt` contains a RE-DERIVATION contract: one of the keywords
       (re-derive / independently verify / re-run / re-check / recompute) OR a
       reference to a worker output-artifact path (a *.md/.py/.json/... token) :
       not mere re-reading.
  (Workers = post-skill Agent dispatches whose description does NOT contain
  "verifier".)

Block condition: skill invoked AND no VALID verifier dispatch found. This defeats
the trivial relabel-a-worker gaming the old description-only check permitted (a
dispatch described "verifier" but carrying a worker's prompt, or no re-derivation
task, no longer satisfies the gate).

Audit (NOT a block condition): each post-skill dispatch's `subagent_type` is recorded
to governance-log.jsonl. Type-difference is deliberately NOT enforced: a verifier
legitimately CAN be the same subagent_type as a worker (e.g. technical-researcher
used for both, in different dispatches with different tasks). Enforcing a type
difference would wrongly reject the legitimate same-type case.

Honest feasibility ceiling (refines the accepted limitation, per architect-review
2026-05-21 and the 2026-06-15 two-gate spec axis c): a Stop hook reads name /
description / subagent_type / prompt per dispatch but CANNOT prove model-instance
independence (fresh context): the transcript does not expose model-instance
identity. So this remains a CONVENTION check, now a materially stronger one, not a
proof of structural agent identity.
"""

import sys
import json
import os
import re

# Part-3 re-derivation contract: keyword set OR an artifact-path reference.
_REDERIVATION_KEYWORDS = re.compile(
    r"re-?deriv|independent(?:ly)?\s+verif|re-?run|re-?check|re-?comput|recomput",
    re.IGNORECASE,
)
_ARTIFACT_PATH = re.compile(
    r"[\w./-]+\.(?:md|py|json|jsonl|txt|csv|ya?ml)\b",
    re.IGNORECASE,
)


def _has_rederivation_contract(prompt: str) -> bool:
    """Part 3: the verifier prompt re-derives, not merely re-reads."""
    if not prompt:
        return False
    return bool(_REDERIVATION_KEYWORDS.search(prompt) or _ARTIFACT_PATH.search(prompt))

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
READ_BYTES = 204800  # 200KB transcript tail: matches dispatch-compliance-check.py

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
    dispatches = []  # post-skill Agent dispatches, in chronological order
    dispatch_index = 0

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

            # Ordering guard: only collect dispatches that appear AFTER the skill
            # invocation. The scan is chronological, so skill_invoked being True
            # here means the skill tool_use was seen earlier.
            elif name == "Agent" and skill_invoked:
                description = (inp.get("description") or "").lower()
                dispatches.append({
                    "idx": dispatch_index,
                    "is_verifier": "verifier" in description,
                    "subagent_type": inp.get("subagent_type") or "",
                    "prompt": inp.get("prompt") or "",
                })
                dispatch_index += 1

    if not skill_invoked:
        return  # hook is dormant unless the harness skill was used

    worker_prompts = [d["prompt"] for d in dispatches if not d["is_verifier"]]
    worker_indices = [d["idx"] for d in dispatches if not d["is_verifier"]]
    last_worker_idx = max(worker_indices) if worker_indices else -1
    # Audit only: recorded, never a block condition.
    subagent_types = [d["subagent_type"] for d in dispatches]

    # A VALID verifier satisfies all 3 structural parts.
    valid_verifier = False
    for d in dispatches:
        if not d["is_verifier"]:
            continue
        prompt = d["prompt"]
        # part 1: appears after all worker dispatches
        if d["idx"] <= last_worker_idx:
            continue
        # part 2: prompt not byte-identical to any worker prompt (not a relabel)
        if any(prompt == wp for wp in worker_prompts):
            continue
        # part 3: re-derivation contract (not mere re-reading)
        if not _has_rederivation_contract(prompt):
            continue
        valid_verifier = True
        break

    session_id = _session_id(payload)

    if valid_verifier:
        _log("pass", session_id, {"subagent_types": subagent_types})
        return

    reason = (
        "VERIFIER GATE: the `verification-gated-research` skill was invoked but no "
        "VALID separate verifier agent was dispatched. A valid verifier is a distinct "
        "Agent dispatch (description containing \"verifier\") that appears AFTER the "
        "workers, whose prompt is NOT byte-identical to a worker prompt, and whose "
        "prompt RE-DERIVES (keywords: re-derive / independently verify / re-run / "
        "re-check / recompute, OR a reference to the worker output-artifact path) "
        "rather than merely re-reading. Dispatch a re-deriving verifier and let it "
        "gate the backlog ledger before completing: completion is the ledger state, "
        "not your assertion."
    )
    print(json.dumps({"decision": "block", "reason": reason}))
    _log("block", session_id, {"subagent_types": subagent_types})


def _session_id(payload):
    """Best-effort session id from the Stop payload. Never raises.

    Defect 2 fix (2026-08-07): _log() carried no session key at all, so every
    record this hook ever wrote was structurally unclassifiable as real (a
    missing session is read as synthetic by the gate-yield classifier)."""
    try:
        sys.path.insert(0, _HOOK_DIR)
        from _governance_logger import session_from
        return session_from(payload)
    except Exception:
        return None


def _log(event, session=None, extra=None):
    try:
        from datetime import datetime
        log_path = os.path.join(_HOOK_DIR, "governance-log.jsonl")
        record = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": event,
            "hook": "verifier-gate",
            "skill": SKILL_NAME,
            "schema": 2,
            "session": session,
        }
        if extra:
            record.update(extra)
        entry = json.dumps(record)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


if __name__ == "__main__":
    main()
