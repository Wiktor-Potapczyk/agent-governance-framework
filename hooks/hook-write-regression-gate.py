#!/usr/bin/env python3
"""hook-write-regression-gate.py: PostToolUse Write|Edit regression gate for harness hook edits.

GAP-3a (TA-3 Phase 2, spec Step 9 of 2026-07-09-harness-revision-spec): an edit to
any `.claude/hooks/*.py` file lands silently today: nothing forces the held-out
oracle suite to run before the session reports success. This gate closes that:
on every Write/Edit to a hook `.py` file it runs the full pytest suite and, if
red, emits a LOUD PostToolUse warning into context. It never blocks and never
auto-reverts: the evaluator stays outside the loop (WARN/advisory-first,
Phase-2 invariant 1).

Scope decisions (explicit, per plan Step 2):
  - `test_*.py` files ARE included: the tests are part of the held-out oracle;
    an edit that breaks a test file is exactly the regression class this gate
    exists to surface. Cost: one suite run (~19s at 764 tests) per test-file
    edit. Narrowing path if latency bites (spec R3): exclude `test_*.py` by
    path filter in a later increment.
  - Excluded: anything under `_state/`, `archive/`, `aggregates/`,
    `__pycache__/`, and every non-`.py` path. Non-hook writes exit 0 instantly
    with no pytest run (fast path).

Latency budget (spec R3 / acceptance criterion): full-suite wall clock <= 60s;
registered timeout must be >= measured latency + margin.

Test isolation (like the GATE1_ALARM_LOG_PATH precedent): unit tests override
  HOOK_REGRESSION_GATE_TARGET_DIR: the directory pytest runs against
  HOOK_REGRESSION_GATE_LOG_PATH: where the suite output lands
so they exercise a temp mini-suite, never the live one.

Exit codes: 0 always (clean, warn, or internal error). This hook never blocks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

# Path segments under .claude/hooks/ that never gate (state, archives, caches).
_EXCLUDED_SEGMENTS = ("_state", "archive", "aggregates", "__pycache__")

# Forward/back-slash tolerant matcher for the .claude/hooks/ directory segment.
_HOOKS_SEGMENT_RE = re.compile(r"[\\/]\.claude[\\/]hooks[\\/]", re.IGNORECASE)

SUITE_TIMEOUT_SECONDS = 120  # hard cap on the pytest child; gate warns on timeout
_TAIL_LINES = 12


def _target_dir() -> str:
    return os.environ.get("HOOK_REGRESSION_GATE_TARGET_DIR") or HOOKS_DIR


def _log_path() -> str:
    p = os.environ.get("HOOK_REGRESSION_GATE_LOG_PATH")
    if p:
        return p
    return os.path.join(tempfile.gettempdir(), "hook-write-regression-gate.log")


def is_gated_hook_write(file_path: str) -> bool:
    """True iff file_path is a .py file inside .claude/hooks/ and not excluded."""
    if not file_path or not file_path.lower().endswith(".py"):
        return False
    norm = file_path.replace("\\", "/")
    m = _HOOKS_SEGMENT_RE.search("/" + norm if not norm.startswith("/") else norm)
    if m is None:
        # Also accept a path that *starts* with .claude/hooks/ (relative form)
        if not norm.lower().startswith(".claude/hooks/"):
            return False
        rest = norm[len(".claude/hooks/"):]
    else:
        # Everything after the matched ".claude/hooks/" segment
        probe = "/" + norm if not norm.startswith("/") else norm
        rest = probe[m.end():]
    parts = [p for p in rest.replace("\\", "/").split("/") if p]
    for seg in parts[:-1]:
        if seg.lower() in _EXCLUDED_SEGMENTS:
            return False
    return True


def run_suite(target_dir: str, log_path: str) -> tuple[int, str]:
    """Run pytest -q against target_dir, stdout+stderr to log_path.

    Returns (exit_code, tail_text). Never raises; internal failure returns
    (-1, reason) so the caller can warn about the gate itself failing.
    """
    try:
        with open(log_path, "w", encoding="utf-8") as fh:
            # -p no:cacheprovider: the gate never needs --lf state, and on this
            # machine cacheprovider + auto-rootdir on a non-project target dir
            # can stall the run indefinitely (empirically bisected 2026-07-10:
            # bare `pytest <tempdir>` hung >120s; either `-p no:cacheprovider`
            # or a forced --rootdir made it 0.08s). Disabling the cache is the
            # conftest-safe variant of the two.
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", target_dir, "-q",
                 "-p", "no:cacheprovider"],
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=SUITE_TIMEOUT_SECONDS,
            )
        code = proc.returncode
    except subprocess.TimeoutExpired:
        return -1, f"pytest timed out after {SUITE_TIMEOUT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001: gate must never crash the turn
        return -1, f"gate could not run pytest: {exc}"
    try:
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
        tail = "\n".join(lines[-_TAIL_LINES:])
    except OSError:
        tail = "(suite output unreadable)"
    return code, tail


def _emit(context: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": context,
        }
    }))


def _log_fire(decision: str, detail: str) -> None:
    try:
        sys.path.insert(0, HOOKS_DIR)
        from _governance_logger import log_fire
        log_fire("hook-write-regression-gate", decision=decision, detail=detail)
    except Exception:
        pass


def _matrix_findings_text() -> str:
    """Contract C5, per-edit placement. Returns the rendered findings, or ""
    when the matrix is clean or the check itself could not run.

    Fail-open by construction: a broken checker must never turn into a warning
    about the edit, which would be a false accusation against the author.
    """
    try:
        scripts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
        )
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_har_for_gate", os.path.join(scripts_dir, "hook_activity_report.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if not mod.matrix_findings():
            return ""
        return mod.findings_text()
    except Exception:
        return ""


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0  # fail-open: gate never crashes the turn

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0
    file_path = (payload.get("tool_input") or {}).get("file_path", "")
    if not is_gated_hook_write(file_path):
        return 0  # fast path: no pytest run

    code, tail = run_suite(_target_dir(), _log_path())

    matrix = _matrix_findings_text()

    if code == 0:
        if matrix:
            _emit(
                "[MATRIX GATE] The regression suite is green, but the generated "
                f"asset matrix reports findings after the edit to {file_path}:\n{matrix}"
            )
            _log_fire("warn", f"matrix findings after edit of {os.path.basename(file_path)}")
            return 0
        _log_fire("quiet", f"suite green after edit of {os.path.basename(file_path)}")
        return 0

    if code == -1:
        _emit(
            "[HOOK-WRITE REGRESSION GATE: GATE ERROR] Edit to "
            f"{file_path} could not be regression-checked ({tail}). "
            "Run the suite manually before reporting success: "
            "python -m pytest .claude/hooks/ -q"
        )
        _log_fire("warn", f"gate error on {os.path.basename(file_path)}: {tail[:120]}")
        return 0

    _emit(
        "[HOOK-WRITE REGRESSION GATE: SUITE RED] The edit to "
        f"{file_path} landed with a FAILING regression suite (pytest exit {code}). "
        "DO NOT report success. Root-cause and fix before proceeding. Suite tail:\n"
        f"{tail}"
    )
    _log_fire("warn", f"suite red (exit {code}) after edit of {os.path.basename(file_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
