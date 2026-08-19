#!/usr/bin/env python3
"""mcp-qmd-health-probe.py: SessionStart health probe for the qmd recall layer.

GAP-1 (TA-3 Phase 2, spec Step 8 of 2026-07-09-harness-revision-spec): the MCP
circuit breaker only sees failures of calls the session already made; a qmd
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

# --- R2 (CE-1 qmd substrate repair, 2026-08-07): query-path check ---------
# TASK-013: repro term reverified live at build time against agr-kb (the
# smallest/fastest of the four collections per `qmd status`):
# `node qmd.js search "hook" -c agr-kb` returned multiple nonzero-score hits
# 2026-08-07. A zero-hit term would produce a fast, meaningless pass, since a
# no-match query returns "No results found" quickly without engaging the
# stage this check exists to exercise.
QUERY_PROBE_TERM = "hook"
QUERY_PROBE_COLLECTION = "agr-kb"

# TASK-014: calibrated live 2026-08-07 on this machine, invocation
# `node qmd.js query "hook" --no-rerank -c agr-kb -n 3`, 6 consecutive runs:
# 5.86s, 5.78s, 6.24s, 5.78s, 5.86s, 5.95s (max 6.24s). No cold-cache spike
# observed: the query-expansion model
# (hf_tobil_qmd-query-expansion-1.7B-q4_k_m.gguf, 1.28GB) already existed on
# disk from 2026-08-03 (file mtime verified at build time), so this
# calibration session's first run was already warm, and the one-time download
# risk documented in reference_qmd_embed_vcruntime_applocal_workaround.md had
# already resolved before this build and could not be reproduced live.
# Applying the SAME 3x-warm-headroom convention PROBE_TIMEOUT_SECONDS itself
# uses above: ceil(6.24 * 3) = 19. This deliberately calibrates to the live
# warm ceiling rather than the plan's stale historical cold-case figure
# (~56s); see the Phase-3 build record for the full reasoning (RISK-004).
QUERY_PROBE_TIMEOUT_SECONDS = 19


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_qmd_base() -> tuple[list | None, dict, str]:
    """Shared .mcp.json resolution used by BOTH probe commands (status,
    query). Returns ([command, script_path], env, error); cmd is None on any
    resolution failure and error carries the R8 reason (caller MUST warn
    loudly, never silently)."""
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

    return [command, script_path], env, ""


def resolve_qmd_cli() -> tuple[list | None, dict, str]:
    """Resolve the qmd CLI probe command from .mcp.json.

    Returns (cmd, env, error). On success error == "" and cmd is
    [command, script_path, "status"]. On any resolution failure cmd is None
    and error carries the R8 reason (caller MUST warn loudly, never silently).
    """
    base, env, error = _resolve_qmd_base()
    if base is None:
        return None, env, error
    return base + ["status"], env, ""


def resolve_qmd_query_cli() -> tuple[list | None, dict, str]:
    """R2 (TASK-015): resolve the query-path probe command. Same .mcp.json
    resolution as resolve_qmd_cli(), same (cmd, env, error) contract, but the
    CLI subcommand is `query` against QUERY_PROBE_TERM in
    QUERY_PROBE_COLLECTION, with --no-rerank -- the probe itself must not be
    the one caller that skips R3's enforced flag and pays the LLM-rerank
    hang it exists to catch."""
    base, env, error = _resolve_qmd_base()
    if base is None:
        return None, env, error
    return (
        base + [
            "query", QUERY_PROBE_TERM, "--no-rerank",
            "-c", QUERY_PROBE_COLLECTION, "-n", "3",
        ],
        env,
        "",
    )


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


def run_query_probe(cmd: list, env: dict) -> tuple[bool, str]:
    """R2 (TASK-015): run the query-path probe command. Returns (ok, detail).
    Independent subprocess.run call AND independent timeout from run_probe()
    above -- the status check's existing 20s budget (PROBE_TIMEOUT_SECONDS)
    stays completely untouched in every case."""
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=QUERY_PROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"query-probe timed out after {QUERY_PROBE_TIMEOUT_SECONDS}s"
    except (OSError, ValueError) as exc:
        return False, f"query-probe could not launch: {exc}"
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or "")).strip()[-200:]
        return False, f"query-probe exit {proc.returncode}: {tail}"
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


def record_query_success() -> None:
    """R2 (TASK-016): stamp last_query_probe_ok_at, sibling to
    last_probe_ok_at. Leaves failures/last_success_at/last_probe_ok_at
    untouched -- this is a structurally distinct signal from the status
    check, not a replacement for it."""
    state = load_state()
    server_state = state.get(SERVER_KEY) or {
        "failures": [], "tripped_at": None, "last_success_at": None,
    }
    server_state["last_query_probe_ok_at"] = _now_iso()
    state[SERVER_KEY] = server_state
    save_state(state)


def record_query_failure(error_detail: str) -> None:
    """R2 (TASK-016): sibling of record_failure() for the query-path check.
    Deliberately does NOT append to the shared `failures` list -- that list
    is the status check's consumer-compatible shape (D4) that
    mcp-circuit-breaker.py's trip logic reads; the query-path check is a
    separate signal and gets its OWN sibling key instead of overloading
    that list or driving circuit-breaker trip state the plan never asked
    it to drive."""
    state = load_state()
    server_state = state.get(SERVER_KEY) or {
        "failures": [], "tripped_at": None, "last_success_at": None,
    }
    server_state["last_query_probe_failure"] = {
        "source": "sessionstart-query-probe",
        "error": error_detail[:300],
        "at": _now_iso(),
    }
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


_SESSION: str | None = None  # set from the payload in main(); None when absent


def _log_fire(decision: str, detail: str) -> None:
    try:
        sys.path.insert(0, HOOKS_DIR)
        from _governance_logger import log_fire
        log_fire("mcp-qmd-health-probe", decision=decision, detail=detail,
                  session=_SESSION)
    except Exception:
        pass


def main() -> int:
    # Defect 2 fix (2026-08-07): stdin was read and discarded, so every
    # _log_fire() call logged session=None; the payload was never parsed at
    # all, even though CC's SessionStart payload carries session_id.
    global _SESSION
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        sys.path.insert(0, HOOKS_DIR)
        from _governance_logger import session_from
        _SESSION = session_from(payload)
    except Exception:
        _SESSION = None

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
    if not ok:
        record_failure(detail)
        _emit(
            "[QMD HEALTH PROBE] qmd recall layer UNREACHABLE at session start "
            f"({detail}). Failure recorded to the circuit-breaker state. Fall back "
            "to Grep/Read on the memory folder per CLAUDE.md and flag qmd as down. "
            "Note: this CLI probe checks binary + index, not the live MCP transport."
        )
        _log_fire("warn", f"probe failure: {detail[:150]}")
        # R2 (TASK-015): status failed -> skip the query-path check entirely.
        # The failure-path latency and the existing 20s budget stay completely
        # unchanged in this branch.
        return 0

    record_success()
    _log_fire("quiet", "qmd CLI probe ok")

    # R2 (TASK-015): only reached on a passing status check. Independent,
    # separate resolution + subprocess call from the status check above; the
    # added cost only ever applies on this success path.
    query_cmd, query_env, query_error = resolve_qmd_query_cli()
    if query_cmd is None:
        # .mcp.json already resolved cleanly for the status check above (cmd
        # was not None there), so this should be unreachable in practice --
        # fail loudly rather than silently if it ever is.
        _emit(
            "[QMD HEALTH PROBE: QUERY-PATH: R8] query-path probe cannot resolve "
            f"CLI path from .mcp.json ({query_error}). Query-path health UNKNOWN."
        )
        _log_fire("warn", f"query-probe R8 unresolvable: {query_error[:150]}")
        return 0

    query_ok, query_detail = run_query_probe(query_cmd, query_env)
    if query_ok:
        record_query_success()
        _log_fire("quiet", "qmd query-path probe ok")
        return 0

    record_query_failure(query_detail)
    _emit(
        "[QMD HEALTH PROBE: QUERY-PATH] qmd query path UNHEALTHY at session start "
        f"({query_detail}). This probe already runs with rerank disabled, so a "
        "failure here is NOT the rerank-default hang class; likely causes are a "
        "cold model/cache load, index lock contention with a concurrent qmd "
        "process (embed/update), or a genuine query-path regression. Fall back "
        "to Grep/Read for recall this session and check qmd status by hand. "
        "Unrelated reminder: live mcp__qmd__query calls must still pass "
        "rerank: false (enforced by qmd-rerank-default-guard)."
    )
    _log_fire("warn", f"query-probe failure: {query_detail[:150]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
