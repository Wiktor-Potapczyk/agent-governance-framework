"""Tests for config-protection.py PreToolUse hook."""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

import importlib.util
spec = importlib.util.spec_from_file_location(
    "config_protection",
    str(Path(__file__).parent / "config-protection.py"),
)
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def _run(payload: dict, env: dict | None = None) -> tuple[int, str]:
    """Invoke main() with stdin set to payload JSON; return (rc, stdout)."""
    env = env or {}
    payload_str = json.dumps(payload)
    captured = io.StringIO()
    with mock.patch.dict(os.environ, env, clear=False), \
         mock.patch.object(sys, "stdin", io.StringIO(payload_str)), \
         redirect_stdout(captured):
        # Defensive: ensure override is absent unless test set it
        if "CONFIG_PROTECTION_ALLOW" not in env:
            os.environ.pop("CONFIG_PROTECTION_ALLOW", None)
        # Stub the deny logger so tests don't touch governance-log.jsonl
        with mock.patch.object(cp, "_log_deny", lambda *a, **k: None):
            rc = cp.main()
    return rc, captured.getvalue()


class IsProtectedTests(unittest.TestCase):
    def test_settings_local_json_in_dot_claude(self):
        prot, name = cp._is_protected("/vault/.claude/settings.local.json")
        self.assertTrue(prot)
        self.assertEqual(name, "settings.local.json")

    def test_settings_local_json_outside_dot_claude_not_protected(self):
        # Unrelated tooling settings.local.json should not be caught
        prot, _ = cp._is_protected("/some/other/tool/settings.local.json")
        self.assertFalse(prot)

    def test_registry_json_in_dot_claude(self):
        prot, name = cp._is_protected("C:/vault/.claude/registry.json")
        self.assertTrue(prot)
        self.assertEqual(name, "registry.json")

    def test_registry_json_outside_dot_claude_not_protected(self):
        prot, _ = cp._is_protected("/somewhere/registry.json")
        self.assertFalse(prot)

    def test_memory_md_protected_anywhere(self):
        # Canonical basename is now returned lowercase per the case-insensitive match
        prot, name = cp._is_protected("/anywhere/MEMORY.md")
        self.assertTrue(prot)
        self.assertEqual(name, "memory.md")

    def test_memory_md_in_vault_root(self):
        prot, _ = cp._is_protected("C:/vault/MEMORY.md")
        self.assertTrue(prot)

    def test_lowercase_memory_md_protected_on_case_insensitive_fs(self):
        # Architect MED-1 fix: NTFS treats memory.md and MEMORY.md as the same file,
        # so the hook does too. Returned basename is the canonical lowercase.
        prot, name = cp._is_protected("/anywhere/memory.md")
        self.assertTrue(prot)
        self.assertEqual(name, "memory.md")

    def test_uppercase_settings_local_protected_on_windows(self):
        # Architect MED-1 fix
        prot, name = cp._is_protected(r"C:\vault\.claude\SETTINGS.LOCAL.JSON")
        self.assertTrue(prot)
        self.assertEqual(name, "settings.local.json")

    def test_uppercase_registry_in_uppercase_dot_claude_protected(self):
        prot, name = cp._is_protected("C:/vault/.CLAUDE/REGISTRY.JSON")
        self.assertTrue(prot)
        self.assertEqual(name, "registry.json")

    def test_empty_path(self):
        prot, _ = cp._is_protected("")
        self.assertFalse(prot)

    def test_unrelated_file(self):
        prot, _ = cp._is_protected("/vault/Projects/X/STATE.md")
        self.assertFalse(prot)

    def test_windows_backslash_paths(self):
        prot, name = cp._is_protected(r"C:\vault\.claude\settings.local.json")
        self.assertTrue(prot)
        self.assertEqual(name, "settings.local.json")


class OverrideTests(unittest.TestCase):
    def test_override_off_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONFIG_PROTECTION_ALLOW", None)
            self.assertFalse(cp._is_overridden())

    def test_override_1(self):
        with mock.patch.dict(os.environ, {"CONFIG_PROTECTION_ALLOW": "1"}, clear=False):
            self.assertTrue(cp._is_overridden())

    def test_override_true(self):
        with mock.patch.dict(os.environ, {"CONFIG_PROTECTION_ALLOW": "true"}, clear=False):
            self.assertTrue(cp._is_overridden())

    def test_override_random_value_is_falsey(self):
        with mock.patch.dict(os.environ, {"CONFIG_PROTECTION_ALLOW": "maybe"}, clear=False):
            self.assertFalse(cp._is_overridden())


class MainFlowTests(unittest.TestCase):
    def test_write_to_protected_file_is_blocked(self):
        rc, out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": "/vault/.claude/settings.local.json"},
        })
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("CONFIG PROTECTION", result["hookSpecificOutput"]["permissionDecisionReason"])

    def test_edit_to_protected_file_is_blocked(self):
        rc, out = _run({
            "tool_name": "Edit",
            "tool_input": {"file_path": "C:/vault/MEMORY.md"},
        })
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_multiedit_to_protected_file_is_blocked(self):
        rc, out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": "/vault/.claude/registry.json"},
        })
        self.assertEqual(rc, 0)
        result = json.loads(out)
        self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_override_lets_write_through(self):
        rc, out = _run(
            {
                "tool_name": "Write",
                "tool_input": {"file_path": "/vault/.claude/settings.local.json"},
            },
            env={"CONFIG_PROTECTION_ALLOW": "1"},
        )
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")  # silent pass

    def test_unrelated_file_passes_silently(self):
        rc, out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": "/vault/Projects/X/work/draft.md"},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_non_write_tool_passes(self):
        rc, out = _run({
            "tool_name": "Read",
            "tool_input": {"file_path": "/vault/.claude/settings.local.json"},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_bash_tool_passes(self):
        rc, out = _run({
            "tool_name": "Bash",
            "tool_input": {"command": "cat .claude/settings.local.json"},
        })
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_malformed_payload_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json")), \
             redirect_stdout(captured):
            rc = cp.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")

    def test_missing_file_path_fails_open(self):
        rc, out = _run({"tool_name": "Write", "tool_input": {}})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_tool_input_not_dict_fails_open(self):
        rc, out = _run({"tool_name": "Write", "tool_input": "not a dict"})
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
