"""Tests for mcp-irreversible-guard.py — PreToolUse guard for irreversible MCP calls.

Two-Gate Gate-1 MCP fire point. Covers: name-sufficient deny, dual-use payload-
conditional deny (n8n activation flip / destructive datatable), benign-payload pass,
read-tool pass (proves NO blanket mcp__.* match), non-MCP pass, fail-open.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "mcp_irreversible_guard",
    str(Path(__file__).parent / "mcp-irreversible-guard.py"),
)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(mig, "_log", lambda *a, **k: None), \
         redirect_stdout(captured):
        mig.main()
    return captured.getvalue()


def _decision(out: str):
    if not out.strip():
        return None
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return None


class NameSufficientDenyTests(unittest.TestCase):
    def test_delete_workflow_denies(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_delete_workflow", "tool_input": {"id": "1"}})
        self.assertEqual(_decision(out), "deny")

    def test_github_merge_pr_denies(self):
        out = _run({"tool_name": "mcp__plugin_github_github__merge_pull_request",
                    "tool_input": {"pullNumber": 7}})
        self.assertEqual(_decision(out), "deny")

    def test_github_delete_file_denies(self):
        out = _run({"tool_name": "mcp__plugin_github_github__delete_file", "tool_input": {}})
        self.assertEqual(_decision(out), "deny")

    def test_hostinger_vps_delete_project_denies(self):
        out = _run({"tool_name": "mcp__hostinger-mcp__VPS_deleteProjectV1", "tool_input": {}})
        self.assertEqual(_decision(out), "deny")


class DualUsePayloadConditionalTests(unittest.TestCase):
    def test_partial_update_activation_flip_denies(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_update_partial_workflow",
                    "tool_input": {"id": "abc", "active": True}})
        self.assertEqual(_decision(out), "deny")

    def test_full_update_nested_settings_active_denies(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_update_full_workflow",
                    "tool_input": {"id": "abc", "settings": {"active": True}}})
        self.assertEqual(_decision(out), "deny")

    def test_datatable_drop_denies(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_manage_datatable",
                    "tool_input": {"operation": "deleteRows"}})
        self.assertEqual(_decision(out), "deny")

    # --- FP guards: dual-use tools on benign payloads must PASS ---
    def test_partial_update_normal_edit_passes(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_update_partial_workflow",
                    "tool_input": {"id": "abc", "operations": [{"type": "updateNode"}]}})
        self.assertIsNone(_decision(out))

    def test_partial_update_active_false_passes(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_update_partial_workflow",
                    "tool_input": {"id": "abc", "active": False}})
        self.assertIsNone(_decision(out))

    def test_datatable_read_passes(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_manage_datatable",
                    "tool_input": {"operation": "getRows"}})
        self.assertIsNone(_decision(out))


class NoBlanketMatchTests(unittest.TestCase):
    def test_read_tool_not_in_set_passes(self):
        # Proves there is NO blanket mcp__.* deny — a read tool sails through.
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_get_workflow", "tool_input": {"id": "1"}})
        self.assertIsNone(_decision(out))

    def test_health_check_passes(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_health_check", "tool_input": {}})
        self.assertIsNone(_decision(out))

    def test_non_mcp_tool_passes(self):
        out = _run({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertIsNone(_decision(out))


class FailOpenTests(unittest.TestCase):
    def test_malformed_payload_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json")), \
             redirect_stdout(captured):
            mig.main()
        self.assertEqual(captured.getvalue(), "")

    def test_tool_input_as_json_string_parsed(self):
        out = _run({"tool_name": "mcp__n8n-mcp__n8n_update_partial_workflow",
                    "tool_input": json.dumps({"active": True})})
        self.assertEqual(_decision(out), "deny")


if __name__ == "__main__":
    unittest.main()
