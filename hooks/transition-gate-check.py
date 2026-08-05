"""
transition-gate-check.py: PreToolUse guard for SDLC phase-sentinel advances (Layer 1).

Autonomous SDLC State-Machine, Layer 1 (transition-gate hook).
Spec: Projects/your-project/work/2026-06-18-autonomous-sdlc-state-machine-spec.md
      (§4.1 state-file schema, §4.2 transition-gate pseudocode: implemented verbatim here).
Build plan: Projects/your-project/work/2026-06-18-sdlc-enforcement-build.md

Fires on Write (and Edit, to deny) tool calls to `.claude/hooks/_state/sdlc-phase-<project>.json`
sentinel files. Reads the proposed `current_phase` advance, checks the prior ENFORCED phase has
recorded passing external-oracle evidence, and DENIES the write if that evidence is absent.

Write-only restriction (spec §4.2): agents must always OVERWRITE the whole sentinel: never
patch it with an Edit OR a MultiEdit. An Edit to the sentinel is itself a violation -> deny.
A MultiEdit to the sentinel is the same violation -> deny: its tool_input carries only
old_string/new_string fragments (no `content`), so it can never overwrite the whole file; the
deny keys solely off file_path, independent of the edits-array contents or length. For a Write,
tool_input.content is the full new file content, so the proposed current_phase is parseable
directly.

Why `deny` (not `ask`): the vault runs universal `bypassPermissions`; a `permissionDecision:"ask"`
AUTO-ALLOWS and gates nothing. Only `deny` actually stops the action (spec §4.2; same reasoning
as Gate-1 of the two-gate enforcement floor).

Fail-CLOSED on sentinel parse/read errors (deny), but fail-OPEN on a truly unparseable stdin
payload (silent exit 0: matches every other hook in this directory). Exit code: 0 always; the
structured hookSpecificOutput JSON carries the deny.

stdlib-only. Every open() passes encoding="utf-8" (reference_python_windows_open_defaults_to_locale_not_utf8).
"""

import sys
import json
import os

# Spec §4.2: copied verbatim.
PHASE_ORDER = [
    "discovery", "requirements", "design",
    "build", "verify", "review", "release",
    "operate", "monitor", "iterate",
]

ADVISORY_PHASES = {"discovery", "requirements", "design"}

# Governance log lives alongside all other hook artefacts.
_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
_GOVERNANCE_LOG = os.path.join(_HOOK_DIR, "governance-log.jsonl")


def _norm_path(p):
    """Return path with OS separators replaced by forward slashes.

    Used before the sentinel-name test so the match works on both Windows
    (backslash) and Unix (forward slash) paths. Mirrors reviewer-scope-violation-check._norm_path.
    """
    return (p or "").replace(os.sep, "/").replace("\\", "/")


def _is_sentinel(path):
    """True iff path is an SDLC phase sentinel (sdlc-phase-*.json)."""
    norm = _norm_path(path)
    return "sdlc-phase-" in norm and norm.endswith(".json")


def _deny(reason):
    """Emit the PreToolUse deny wrapper (verbatim shape from the other Gate-1 hooks)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _log_block(session_id, tool_name, file_path, reason):
    """Append a transition_gate_block entry to governance-log.jsonl.

    Wrapped so a log failure never breaks the deny itself.
    """
    try:
        from _event_emit import emit_event
        emit_event(
            event="transition_gate_block",
            hook="transition-gate-check",
            session=session_id,
            extra={
                "tool_name": tool_name,
                "file_path": file_path,
                "block_reason": reason,
            },
        )
    except Exception:
        pass


def check(tool_name, tool_input):
    """Return a deny-reason string to block, or None to allow.

    Implements spec §4.2 pseudocode verbatim, branch order preserved.
    """
    # (a) Edit to a sentinel is a violation by construction (Write-only restriction, R3).
    if tool_name == "Edit":
        path = tool_input.get("file_path", "")
        if _is_sentinel(path):
            return "sdlc-phase sentinel: Edit to sentinel is a violation; must Write the whole file"
        return None  # Edit on a non-sentinel: not our concern

    # (a2) MultiEdit to a sentinel is a violation by construction (Write-only restriction, R3).
    # MultiEdit's tool_input is {file_path, edits:[{old_string,new_string},...]} with NO `content`,
    # so it can never overwrite the whole sentinel: it only patches fragments. Any MultiEdit
    # targeting a sentinel therefore denies, keyed SOLELY off file_path (the edits array is never
    # parsed, so single-edit, multi-edit, and enforced-advance-fragment payloads deny identically).
    # Branch placed BEFORE the Write path so it never touches the absent tool_input["content"].
    if tool_name == "MultiEdit":
        path = tool_input.get("file_path", "")
        if _is_sentinel(path):
            return "sdlc-phase sentinel: MultiEdit to sentinel is a violation; must Write the whole file"
        return None  # MultiEdit on a non-sentinel: not our concern

    # (b) Only intercept writes.
    if tool_name != "Write":
        return None

    path = tool_input.get("file_path", "")

    # (c) Fast-path: non-sentinel Write: the dominant case.
    if not _is_sentinel(path):
        return None

    # (d) Parse proposed state from full file content.
    try:
        proposed = json.loads(tool_input["content"])
        if not isinstance(proposed, dict):
            raise ValueError("sentinel content is not a JSON object")
    except Exception:
        return "sdlc-phase sentinel: malformed JSON"

    # (e) Validate the proposed phase.
    proposed_phase = proposed.get("current_phase")
    if proposed_phase not in PHASE_ORDER:
        return "sdlc-phase sentinel: unknown phase '{}'".format(proposed_phase)

    # (f) Read current on-disk state. FileNotFoundError -> first write allowed (R4 bootstrap).
    #     Any other read/parse error -> deny (fail-closed, R2).
    try:
        with open(path, "r", encoding="utf-8") as f:
            current = json.loads(f.read())
        # current_phase is read for completeness/parity with the spec pseudocode;
        # the evidence gate below reads from `proposed`, which carries completed_gates.
        _ = current.get("current_phase") if isinstance(current, dict) else None
    except FileNotFoundError:
        pass  # first write allowed
    except Exception:
        return "sdlc-phase sentinel: cannot read current state"

    # (g) Advisory target phase: advance allowed without oracle evidence.
    if proposed_phase in ADVISORY_PHASES:
        return None

    # (h) Determine the prior phase that must carry passing evidence.
    idx = PHASE_ORDER.index(proposed_phase)
    if idx == 0:
        return None  # advancing to the first phase is always allowed
    prior_phase = PHASE_ORDER[idx - 1]
    if prior_phase in ADVISORY_PHASES:
        return None  # advisory prior phases require no evidence

    # (i) Enforced prior phase must have recorded external-oracle evidence.
    completed = proposed.get("completed_gates", {})
    if not isinstance(completed, dict):
        completed = {}
    prior_gate = completed.get(prior_phase, {})
    if not isinstance(prior_gate, dict):
        prior_gate = {}
    if not prior_gate or prior_gate.get("evidence_type") != "external_oracle":
        return (
            "sdlc-phase sentinel: cannot advance to '{}': "
            "prior phase '{}' has no recorded external-oracle evidence. "
            "Run the {} DoD oracle and record its evidence first.".format(
                proposed_phase, prior_phase, prior_phase
            )
        )

    return None


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    # Truly unparseable stdin -> fail-open silent exit (matches every hook).
    try:
        payload = json.loads(payload_text)
    except Exception:
        return

    tool_name = payload.get("tool_name", "")

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    transcript_path = payload.get("transcript_path") or ""
    from _governance_logger import session_from
    session_id = session_from(payload)

    reason = check(tool_name, tool_input)
    if reason:
        _deny(reason)
        _log_block(session_id, tool_name, tool_input.get("file_path", ""), reason)
    # Allow: emit nothing, exit 0.
    return


if __name__ == "__main__":
    # Production: Claude Code invokes `python hook.py` with the payload on stdin and NO
    # flag, so the DEFAULT path must process the payload via main(). The in-file smoke
    # suite runs ONLY on an explicit `--selftest` arg.
    # Bug fixed 2026-06-18: the prior guard ran the smoke suite UNLESS HOOK_SMOKE_TEST=1,
    # so CC's flagless invocation ran the tests instead of main() and the hook enforced
    # NOTHING in production (finding_transition_gate_hook_selftest_branch_inert_in_production).
    # The suite's child subprocesses are spawned without --selftest, so they now run main()
    # (the HOOK_SMOKE_TEST env the runner still sets is harmless/unused).
    if "--selftest" not in sys.argv:
        main()
        sys.exit(0)

    import subprocess

    hook_path = os.path.abspath(__file__)
    _candidate = sys.executable
    python_exe = (
        _candidate
        if os.path.basename(_candidate).lower().startswith("python")
        else r"C:\Program Files\Python314\python.exe"
    )
    passed = 0
    failed = 0

    def run_hook(payload_dict):
        stdin_bytes = json.dumps(payload_dict).encode("utf-8")
        env = os.environ.copy()
        env["HOOK_SMOKE_TEST"] = "1"
        result = subprocess.run(
            [python_exe, hook_path],
            input=stdin_bytes,
            capture_output=True,
            timeout=10,
            env=env,
        )
        return (
            result.returncode,
            result.stdout.decode("utf-8", errors="replace"),
            result.stderr.decode("utf-8", errors="replace"),
        )

    def decision(out):
        if not out.strip():
            return None
        try:
            return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
        except Exception:
            return None

    def assert_test(name, condition, detail=""):
        global passed, failed
        status = "PASS" if condition else "FAIL"
        suffix = ": {}".format(detail) if detail else ""
        print("  [{}] {}{}".format(status, name, suffix))
        if condition:
            passed += 1
        else:
            failed += 1

    print("\nSmoke tests: transition-gate-check.py")
    print("=" * 60)

    # Missing-evidence enforced advance -> deny.
    rc, out, err = run_hook({
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/x/.claude/hooks/_state/sdlc-phase-foo.json",
            "content": json.dumps({"current_phase": "verify", "completed_gates": {}}),
        },
    })
    assert_test(
        "missing-evidence Write build->verify -> deny",
        rc == 0 and decision(out) == "deny",
        "rc={} decision={}".format(rc, decision(out)),
    )

    # Advisory advance with no evidence -> allow (no output).
    rc, out, err = run_hook({
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/x/.claude/hooks/_state/sdlc-phase-foo.json",
            "content": json.dumps({"current_phase": "design", "completed_gates": {}}),
        },
    })
    assert_test(
        "advisory advance design -> allow (silent)",
        rc == 0 and out.strip() == "",
        "rc={} stdout={}".format(rc, repr(out[:80])),
    )

    print("=" * 60)
    print("Results: {} passed, {} failed out of {} tests".format(passed, failed, passed + failed))
    if failed:
        sys.exit(1)
