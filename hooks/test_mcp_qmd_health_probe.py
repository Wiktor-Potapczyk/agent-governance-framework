"""Tests for mcp-qmd-health-probe.py (GAP-1, TA-3 Phase 2 Step 3).

Polarity contract (plan Step-3 acceptance criterion):
  (a) dead CLI stub (nonzero exit) AND timeout stub -> failure entry MUST land
      (failures != []), warning text present. A probe that silently passes on
      a dead stub FAILS these tests.
  (b) exit-0 stub -> no failure entry, no warning.
  (c) unresolvable .mcp.json fixture -> R8 warning emitted (never silent).
  (d) resulting state file parses with json.load and round-trips through
      the circuit-breaker's load_state (consumer compatibility, D4/R10).

All state writes go to a temp dir via module-constant patching (established
test_mcp_circuit_breaker.py pattern). The CLI "stub.js" files contain Python
and are launched with sys.executable, so no Node dependency in the suite.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


def _load(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, str(Path(__file__).parent / filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load("mcp-qmd-health-probe.py", "mcp_qmd_health_probe")
cb = _load("mcp-circuit-breaker.py", "mcp_circuit_breaker_for_probe_tests")


def _write_mcp_json(td: Path, stub_body: str | None, command: str | None = None) -> Path:
    """Build a fixture .mcp.json. stub_body=None -> qmd entry omitted entirely."""
    cfg: dict = {"mcpServers": {}}
    if stub_body is not None:
        stub = td / "stub.js"  # .js name, Python body, launched via sys.executable
        stub.write_text(stub_body, encoding="utf-8")
        cfg["mcpServers"]["qmd"] = {
            "command": command or sys.executable,
            "args": [str(stub), "mcp", "--dir", str(td)],
            "env": {"QMD_TEST_MARKER": "1"},
        }
    p = td / "mcp.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")
    return p


def _point_at_temp(td: Path, mcp_json: Path):
    probe.MCP_JSON_PATH = str(mcp_json)
    probe.STATE_DIR = str(td / "_state")
    probe.STATE_FILE = str(td / "_state" / "mcp-circuit-breaker.json")


def _run_main() -> tuple[int, str]:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO("{}")), \
         redirect_stdout(captured):
        rc = probe.main()
    return rc, captured.getvalue()


class ResolutionTests(unittest.TestCase):
    def test_resolves_js_and_merges_env(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(td, "import sys; sys.exit(0)\n")
            _point_at_temp(td, mcp)
            cmd, env, error = probe.resolve_qmd_cli()
            self.assertEqual(error, "")
            self.assertEqual(cmd[0], sys.executable)
            self.assertTrue(cmd[1].endswith("stub.js"))
            self.assertEqual(cmd[2], "status")
            self.assertEqual(env.get("QMD_TEST_MARKER"), "1")

    def test_missing_file_is_error(self):
        probe.MCP_JSON_PATH = os.path.join(tempfile.gettempdir(), "nope-no-mcp.json")
        cmd, _env, error = probe.resolve_qmd_cli()
        self.assertIsNone(cmd)
        self.assertIn("not found", error)

    def test_missing_qmd_entry_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(td, None)
            _point_at_temp(td, mcp)
            cmd, _env, error = probe.resolve_qmd_cli()
            self.assertIsNone(cmd)
            self.assertIn("qmd", error)

    def test_no_js_arg_is_error(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            p = td / "mcp.json"
            p.write_text(json.dumps({
                "mcpServers": {"qmd": {"command": "cmd", "args": ["/c", "npx", "-y", "qmd"]}}
            }), encoding="utf-8")
            _point_at_temp(td, p)
            cmd, _env, error = probe.resolve_qmd_cli()
            self.assertIsNone(cmd)
            self.assertIn(".js", error)


class DeadStubTests(unittest.TestCase):
    """Case (a): a dead qmd MUST produce a failure entry + a loud warning."""

    def test_nonzero_exit_records_failure_and_warns(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(
                td, "import sys; sys.stderr.write('index corrupt'); sys.exit(3)\n"
            )
            _point_at_temp(td, mcp)
            rc, out = _run_main()
            self.assertEqual(rc, 0)  # WARN-first, never nonzero
            self.assertIn("UNREACHABLE", out)
            self.assertIn("Grep/Read", out)
            state = json.loads(Path(probe.STATE_FILE).read_text(encoding="utf-8"))
            self.assertNotEqual(state["qmd"]["failures"], [])
            self.assertIsInstance(state["qmd"]["failures"][0], str)  # D4 shape
            self.assertEqual(
                state["qmd"]["last_probe_failure"]["source"], "sessionstart-probe"
            )

    def test_timeout_records_failure_and_warns(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(td, "import time; time.sleep(30)\n")
            _point_at_temp(td, mcp)
            old_timeout = probe.PROBE_TIMEOUT_SECONDS
            probe.PROBE_TIMEOUT_SECONDS = 1
            try:
                rc, out = _run_main()
            finally:
                probe.PROBE_TIMEOUT_SECONDS = old_timeout
            self.assertEqual(rc, 0)
            self.assertIn("UNREACHABLE", out)
            state = json.loads(Path(probe.STATE_FILE).read_text(encoding="utf-8"))
            self.assertNotEqual(state["qmd"]["failures"], [])
            self.assertIn("timed out", state["qmd"]["last_probe_failure"]["error"])


class HealthyStubTests(unittest.TestCase):
    """Case (b): a healthy qmd must stay quiet and add NO failure entry."""

    def test_exit_zero_is_quiet_and_leaves_failures_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(td, "import sys; sys.exit(0)\n")
            _point_at_temp(td, mcp)
            # Pre-seed a state file to prove failures are not touched on success
            os.makedirs(probe.STATE_DIR, exist_ok=True)
            pre = {"qmd": {"failures": [], "tripped_at": None,
                           "last_success_at": "2026-07-06T13:14:29Z"}}
            Path(probe.STATE_FILE).write_text(json.dumps(pre), encoding="utf-8")
            rc, out = _run_main()
            self.assertEqual(rc, 0)
            self.assertEqual(out, "")  # a warning on a healthy probe is a defect
            state = json.loads(Path(probe.STATE_FILE).read_text(encoding="utf-8"))
            self.assertEqual(state["qmd"]["failures"], [])
            self.assertEqual(state["qmd"]["last_success_at"], "2026-07-06T13:14:29Z")
            self.assertIn("last_probe_ok_at", state["qmd"])


class R8Tests(unittest.TestCase):
    """Case (c): unresolvable config MUST warn loudly (silent exit = defect)."""

    def test_unparseable_mcp_json_warns_r8(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            p = td / "mcp.json"
            p.write_text("{broken json", encoding="utf-8")
            _point_at_temp(td, p)
            rc, out = _run_main()
            self.assertEqual(rc, 0)
            self.assertIn("R8", out)
            self.assertIn("UNKNOWN", out)

    def test_missing_qmd_entry_warns_r8(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(td, None)
            _point_at_temp(td, mcp)
            rc, out = _run_main()
            self.assertEqual(rc, 0)
            self.assertIn("R8", out)


class ConsumerCompatibilityTests(unittest.TestCase):
    """Case (d): probe-written state round-trips through the breaker's load_state."""

    def test_state_round_trips_through_breaker_load_state(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            mcp = _write_mcp_json(td, "import sys; sys.exit(2)\n")
            _point_at_temp(td, mcp)
            rc, _out = _run_main()
            self.assertEqual(rc, 0)
            # Raw json.load parses
            raw = json.loads(Path(probe.STATE_FILE).read_text(encoding="utf-8"))
            self.assertIn("qmd", raw)
            # Breaker consumer parses the same file and its prune logic accepts
            # the failures shape (ISO strings survive a prune pass)
            cb.STATE_FILE = probe.STATE_FILE
            loaded = cb.load_state()
            self.assertEqual(loaded, raw)
            from datetime import datetime, timezone
            pruned = cb.prune_old_failures(
                dict(loaded["qmd"]), datetime.now(timezone.utc)
            )
            self.assertEqual(len(pruned["failures"]), 1)  # fresh entry survives


if __name__ == "__main__":
    unittest.main()
