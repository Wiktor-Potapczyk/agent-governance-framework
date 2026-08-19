"""Tests for qmd-rerank-default-guard.py: PreToolUse guard for mcp__qmd__query.

R3, CE-1 qmd substrate repair (2026-08-07). Covers the four TASK-010 cases:
  (a) rerank absent            -> deny
  (b) rerank: true explicit    -> deny (true is exactly the hang-triggering value)
  (c) rerank: false explicit   -> allow, no deny emitted
  (d) a different MCP tool     -> hook no-ops (matcher-scope leak test)
Plus a JSON-shape assertion that the deny payload matches mcp-irreversible-guard.py's
already-production-proven schema (hookEventName/permissionDecision/
permissionDecisionReason under hookSpecificOutput).
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
    "qmd_rerank_default_guard",
    str(Path(__file__).parent / "qmd-rerank-default-guard.py"),
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(guard, "_log", lambda *a, **k: None), \
         redirect_stdout(captured):
        guard.main()
    return captured.getvalue()


def _decision(out: str):
    if not out.strip():
        return None
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return None


class RerankAbsentTests(unittest.TestCase):
    """Case (a): no `rerank` key at all in tool_input -> deny."""

    def test_missing_rerank_key_denies(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": {
            "searches": [{"type": "lex", "query": "hook"}],
        }})
        self.assertEqual(_decision(out), "deny")

    def test_empty_tool_input_denies(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": {}})
        self.assertEqual(_decision(out), "deny")


class RerankExplicitTrueTests(unittest.TestCase):
    """Case (b): rerank: true is still the hang-triggering value -> deny."""

    def test_rerank_true_denies(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": {
            "searches": [{"type": "lex", "query": "hook"}],
            "rerank": True,
        }})
        self.assertEqual(_decision(out), "deny")

    def test_rerank_truthy_non_bool_denies(self):
        # A stray non-boolean truthy value (e.g. a string "true") must not
        # accidentally satisfy the guard: only the exact boolean False passes.
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": {
            "searches": [{"type": "lex", "query": "hook"}],
            "rerank": "true",
        }})
        self.assertEqual(_decision(out), "deny")


class RerankExplicitFalseTests(unittest.TestCase):
    """Case (c): rerank: false explicit -> allow, no deny emitted."""

    def test_rerank_false_allows_silently(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": {
            "searches": [{"type": "lex", "query": "hook"}],
            "rerank": False,
        }})
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))


class MatcherScopeLeakTests(unittest.TestCase):
    """Case (d): any other tool name -> hook no-ops, even with a matching payload
    shape (proves the EXACT-name matcher, not a substring/prefix match)."""

    def test_different_mcp_tool_noops(self):
        out = _run({"tool_name": "mcp__qmd__search", "tool_input": {"query": "hook"}})
        self.assertEqual(out, "")

    def test_non_mcp_tool_noops(self):
        out = _run({"tool_name": "Read", "tool_input": {"file_path": "x.md"}})
        self.assertEqual(out, "")

    def test_unrelated_qmd_tool_with_rerank_absent_still_noops(self):
        out = _run({"tool_name": "mcp__qmd__status", "tool_input": {}})
        self.assertEqual(out, "")


class DenyShapeMatchesIrreversibleGuardTests(unittest.TestCase):
    """The deny payload must match mcp-irreversible-guard.py's already-production-
    proven schema exactly: hookSpecificOutput.{hookEventName, permissionDecision,
    permissionDecisionReason}."""

    def test_deny_payload_shape(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": {}})
        parsed = json.loads(out)
        self.assertIn("hookSpecificOutput", parsed)
        hso = parsed["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIsInstance(hso["permissionDecisionReason"], str)
        self.assertGreater(len(hso["permissionDecisionReason"]), 0)
        self.assertEqual(sorted(hso), sorted(
            ["hookEventName", "permissionDecision", "permissionDecisionReason"]
        ))


class FailOpenTests(unittest.TestCase):
    def test_unparseable_stdin_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{not json")), \
             redirect_stdout(captured):
            rc = guard.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")

    def test_string_tool_input_is_parsed(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": json.dumps({"rerank": False})})
        self.assertEqual(out, "")

    def test_unparseable_string_tool_input_denies_fail_toward_deny(self):
        out = _run({"tool_name": "mcp__qmd__query", "tool_input": "{not json"})
        self.assertEqual(_decision(out), "deny")


if __name__ == "__main__":
    unittest.main()
