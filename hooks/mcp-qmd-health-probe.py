#!/usr/bin/env python3
"""mcp-qmd-health-probe.py: SessionStart health probe for the qmd recall layer.

GAP-1 (TA-3 Phase 2, spec Step 8 of 2026-07-09-harness-revision-spec): the MCP
circuit breaker only sees failures of calls the session already made: a qmd
server that is dead AT SESSION START stays invisible until the first wasted
call. This probe runs the qmd CLI once at SessionStart and, on failure, seeds
the circuit-breaker state + warns loudly so the session falls back to
Grep/Read (per CLAUDE.md Memory Recall doctrine) instead of burning turns.

CLI resolution is DYNAMIC from .mcp.json on every run (never hardcoded):
    mcpServers.qmd -> command + args; script path = first args element ending
    ".js"; probe command = [command, script_path, "status"]; env = os.environ
    merged with the qmd env block. Fail-loudly R8: if .mcp.json is missing or
    unparseable, the qmd entry is absent, or no ".js" arg resolves, the probe
    emits a LOUD warning ("recall-layer health UNKNOWN") and exits 0: a
    silent exit on unresolvable config is a defect.

KNOWN LIMITATION (spec R2): the CLI probe verifies the qmd binary + index on
disk, NOT the live MCP stdio transport. A transport that dies mid-session is
still only surfaced by the user-visible tool error (and the PostToolUse
breaker half). Residual accepted per spec.

State writes (consumer-compatible per Phase-2 plan D4 + Step-1 consumer
enumeration): failures are appended as ISO-8601 STRINGS (the shape
mcp-circuit-breaker.py prune/trip logic consumes); the probe's detail lands
under a sibling key `last_probe_failure` which no existing consumer reads.
Success stamps `last_probe_ok_at` and leaves `failures` UNTOUCHED (success
semantics belong to the PostToolUse record half, not the probe).

WARN/advisory-first (Phase-2 invariant 1): additionalContext + exit 0 always.
Never blocks, never denies.

Exit codes: 0 always.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
VAULT = os.path.normpath(os.path.join(HOOKS_DIR, "..", ".."))
MCP_JSON_PATH = os.path.join(VAULT, ".mcp.json")
STATE_DIR = os.path.join(HOOKS_DIR, "_state")
STATE_FILE = os.path.join(STATE_DIR, "mcp-circuit-breaker.json")
# 20s, not the spec's 8s: live calibration 2026-07-10 measured a HEALTHY
# `qmd status` at 6.08s bare (exit 0, 77.9MB index); python subprocess spawn
# overhead pushed the probed run past 8s, producing a false-positive failure
# on the first live run. 20s = ~3x warm-run headroom. Flagged deviation in
# the Phase-2 build record.
PROBE_TIMEOUT_SECONDS = 20
SERVER_KEY = "qmd"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_qmd_cli() -> tuple[list | None, dict, str]:
    """Resolve the qmd CLI probe command from .mcp.json.

    Returns (cmd, env, error). On success error == "" and cmd is
    [command, script_path, "status"]. On any resolution failure cmd is None
    and error carries the R8 reason (caller MUST warn loudly, never silently).
    """
    try:
        with open(MCP_JSON_PATH, encoding="utf-8") as fh:
            config = json.load(fh)
    except FileNotFoundError:
        return None, {}, f".mcp.json not found at {MCP_JSON_PATH}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, {}, f".mcp.json unreadable/unparseable: {exc}"

    server = (config.get("mcpServers") or {}).get(SERVER_KEY)
    if not isinstance(server, dict):
        return None, {}, "no 'qmd' entry under mcpServers in .mcp.json"

    command = server.get("command")
    args = server.get("args") or []
    if not command or not isinstance(args, list):
        return None, {}, "qmd entry has no command/args"

    script_path = next(
        (a for a in args if isinstance(a, str) and a.lower().endswith(".js")),
        None,
    )
    if script_path is None:
        return None, {}, "no '.js' element in the qmd args array"

    env = dict(os.environ)
    server_env = server.get("env")
    if isinstance(server_env, dict):
        env.update({k: str(v) for k, v in server_env.items()})

    return [command, script_path, "status"], env, ""


def run_probe(cmd: list, env: dict) -> tuple[bool, str]:
    """Run the probe command. Returns (ok, detail)."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"probe timed out after {PROBE_TIMEOUT_SECONDS}s"
    except (OSError, ValueError) as exc:
        return False, f"probe could not launch: {exc}"
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-200:]
        return False, f"probe exit {proc.returncode}: {tail}"
    return True, ""


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, sort_keys=True, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


def record_failure(error_detail: str) -> None:
    """Append an ISO-string failure (consumer shape) + probe detail sibling key."""
    state = load_state()
    server_state = state.get(SERVER_KEY) or {
        "failures": [], "tripped_at": None, "last_success_at": None,
    }
    failures = list(server_state.get("failures") or [])
    failures.append(_now_iso())
    if len(failures) > 50:  # same cap as mcp-circuit-breaker-record.py
        failures = failures[-50:]
    server_state["failures"] = failures
    server_state["last_probe_failure"] = {
        "source": "sessionstart-probe",
        "error": error_detail[:300],
        "at": _now_iso(),
    }
    state[SERVER_KEY] = server_state
    save_state(state)


def record_success() -> None:
    """Stamp last_probe_ok_at; leave failures/last_success_at untouched."""
    state = load_state()
    server_state = state.get(SERVER_KEY) or {
        "failures": [], "tripped_at": None, "last_success_at": None,
    }
    server_state["last_probe_ok_at"] = _now_iso()
    state[SERVER_KEY] = server_state
    save_state(state)


def _emit(context: str) -> None:
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))
    except Exception:
        pass


def _log_fire(decision: str, detail: str) -> None:
    try:
        sys.path.insert(0, HOOKS_DIR)
        from _governance_logger import log_fire
        log_fire("mcp-qmd-health-probe", decision=decision, detail=detail)
    except Exception:
        pass


def main() -> int:
    try:
        sys.stdin.read()
    except Exception:
        pass

    cmd, env, error = resolve_qmd_cli()
    if cmd is None:
        # R8 fail-loudly: unresolvable config must never pass silently.
        _emit(
            "[QMD HEALTH PROBE: R8] qmd probe cannot resolve CLI path from "
            f".mcp.json ({error}). Recall-layer health UNKNOWN. If mcp__qmd__* "
            "tools are missing this session, fall back to Grep/Read on the "
            "memory folder per CLAUDE.md and flag it."
        )
        _log_fire("warn", f"R8 unresolvable: {error[:150]}")
        return 0

    ok, detail = run_probe(cmd, env)
    if ok:
        record_success()
        _log_fire("quiet", "qmd CLI probe ok")
        return 0

    record_failure(detail)
    _emit(
        "[QMD HEALTH PROBE] qmd recall layer UNREACHABLE at session start "
        f"({detail}). Failure recorded to the circuit-breaker state. Fall back "
        "to Grep/Read on the memory folder per CLAUDE.md and flag qmd as down. "
        "Note: this CLI probe checks binary + index, not the live MCP transport."
    )
    _log_fire("warn", f"probe failure: {detail[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
