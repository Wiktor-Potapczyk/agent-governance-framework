"""
Unit tests for memory-schema-check.py.

Covers:
  1. Valid memory file with all required fields → no warning (silent {}).
  2. Memory file with unquoted colon-space in a value (SCHEMA-1 defect) →
     [MEMORY YAML INVALID] warning emitted.
  3. Memory file with valid YAML but a missing required field →
     [MEMORY SCHEMA] warning still emitted (regression guard).
  4. Non-memory file path → silent {} (hook does not fire).

Run: python .claude/hooks/test_memory_schema_check.py
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

HOOK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "memory-schema-check.py")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory_path(tmp_dir, filename):
    """Return a path that satisfies is_memory_file(): must contain
    .claude/projects/<id>/memory/<filename>.md."""
    mem_dir = os.path.join(tmp_dir, ".claude", "projects", "test-project-id", "memory")
    os.makedirs(mem_dir, exist_ok=True)
    return os.path.join(mem_dir, filename)


def _run_hook(file_path):
    """Feed the hook a CC-style JSON payload on stdin and return parsed stdout."""
    payload = json.dumps({"tool_input": {"file_path": file_path}})
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Hook exited {result.returncode}: {result.stderr}"
    return json.loads(result.stdout.strip())


def _write_file(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Valid frontmatter block used across tests
# ---------------------------------------------------------------------------

VALID_FRONTMATTER = """\
---
name: test_memory
type: reference
confidence: high
last_verified: 2026-05-22
expires: 2027-05-22
description: "A clean test memory file."
---

Body text.
"""

# Defective frontmatter: unquoted value contains ": ": valid to naive parser,
# invalid to YAML (mapping value in a plain scalar context).
INVALID_YAML_FRONTMATTER = """\
---
name: test_memory_bad
type: reference
confidence: high
last_verified: 2026-05-22
expires: 2027-05-22
description: foo: bar baz
---

Body text.
"""

# Valid YAML but missing the required "description" field.
MISSING_FIELD_FRONTMATTER = """\
---
name: test_memory_missing
type: reference
confidence: high
last_verified: 2026-05-22
expires: 2027-05-22
---

Body text.
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMemorySchemaCheck(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        # Clean up temp tree
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Test 1: valid file, all fields present
    # ------------------------------------------------------------------
    def test_valid_file_no_warning(self):
        path = _make_memory_path(self.tmp_dir, "test_valid.md")
        _write_file(path, VALID_FRONTMATTER)
        output = _run_hook(path)
        self.assertEqual(output, {}, f"Expected silent {{}}, got: {output}")

    # ------------------------------------------------------------------
    # Test 2: unquoted colon-space → YAML INVALID warning
    # ------------------------------------------------------------------
    def test_unquoted_colon_space_yaml_invalid_warning(self):
        path = _make_memory_path(self.tmp_dir, "test_bad_yaml.md")
        _write_file(path, INVALID_YAML_FRONTMATTER)
        output = _run_hook(path)
        ctx = output.get("additionalContext", "")
        self.assertIn(
            "[MEMORY YAML INVALID]",
            ctx,
            f"Expected [MEMORY YAML INVALID] in additionalContext, got: {ctx!r}",
        )
        self.assertIn(
            "Quote any value containing a colon-space",
            ctx,
            f"Expected hint text in additionalContext, got: {ctx!r}",
        )

    # ------------------------------------------------------------------
    # Test 3: valid YAML but missing required field → SCHEMA warning
    # ------------------------------------------------------------------
    def test_valid_yaml_missing_field_schema_warning(self):
        path = _make_memory_path(self.tmp_dir, "test_missing_field.md")
        _write_file(path, MISSING_FIELD_FRONTMATTER)
        output = _run_hook(path)
        ctx = output.get("additionalContext", "")
        self.assertIn(
            "[MEMORY SCHEMA]",
            ctx,
            f"Expected [MEMORY SCHEMA] in additionalContext, got: {ctx!r}",
        )
        self.assertIn(
            "description",
            ctx,
            f"Expected 'description' named in warning, got: {ctx!r}",
        )

    # ------------------------------------------------------------------
    # Test 4: non-memory file path → silent {}
    # ------------------------------------------------------------------
    def test_non_memory_file_silent(self):
        # A path that does NOT contain .claude/projects/.../memory/
        path = os.path.join(self.tmp_dir, "Projects", "SomeProject", "work", "note.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_file(path, VALID_FRONTMATTER)
        output = _run_hook(path)
        self.assertEqual(output, {}, f"Expected silent {{}} for non-memory file, got: {output}")

    # ------------------------------------------------------------------
    # Test 5: memory file with no frontmatter at all → SCHEMA no-frontmatter
    # warning (exercises the fm-is-None early-return branch)
    # ------------------------------------------------------------------
    def test_no_frontmatter_memory_file_warning(self):
        path = _make_memory_path(self.tmp_dir, "test_no_fm.md")
        _write_file(path, "Just a body, no YAML frontmatter at all.\n")
        output = _run_hook(path)
        ctx = output.get("additionalContext", "")
        self.assertIn(
            "no YAML frontmatter",
            ctx,
            f"Expected no-frontmatter warning, got: {ctx!r}",
        )


# ---------------------------------------------------------------------------
# New frontmatter fixtures for nested-metadata tests
# ---------------------------------------------------------------------------

# All schema fields live under metadata:: only name+description at top level.
NESTED_ALL_FIELDS_FRONTMATTER = """\
---
name: test_nested_all
description: "Memory with all schema fields inside metadata block."
metadata:
  node_type: memory
  type: reference
  confidence: high
  last_verified: 2026-05-22
  expires: 2027-05-22
---

Body text.
"""

# Nested metadata: block but genuinely missing expires (not at top level either).
NESTED_MISSING_EXPIRES_FRONTMATTER = """\
---
name: test_nested_missing_expires
description: "Nested metadata, expires absent everywhere."
metadata:
  node_type: memory
  type: reference
  confidence: high
  last_verified: 2026-05-22
---

Body text.
"""

# type at top level (valid) AND a different (invalid) type inside metadata:.
NESTED_TYPE_CONFLICT_FRONTMATTER = """\
---
name: test_nested_type_conflict
description: "Top-level type wins over metadata type."
type: reference
metadata:
  node_type: memory
  type: not-a-valid-type
  confidence: high
  last_verified: 2026-05-22
  expires: 2027-05-22
---

Body text.
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNestedMetadataSupport(unittest.TestCase):
    """Tests for the _flatten_metadata fix (nested metadata: block tolerance)."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Test N1: all schema fields nested under metadata: → NO warning
    # ------------------------------------------------------------------
    def test_nested_all_fields_no_warning(self):
        """Bug-fix regression: nested-metadata files must not produce
        a false missing-field warning."""
        path = _make_memory_path(self.tmp_dir, "test_nested_all.md")
        _write_file(path, NESTED_ALL_FIELDS_FRONTMATTER)
        output = _run_hook(path)
        self.assertEqual(
            output, {},
            f"Expected silent {{}} for fully-nested metadata file, got: {output}",
        )

    # ------------------------------------------------------------------
    # Test N2: nested metadata: but expires absent everywhere → warning
    # ------------------------------------------------------------------
    def test_nested_missing_field_still_warns(self):
        """Merge must NOT mask a field that is absent from BOTH top level
        and metadata:."""
        path = _make_memory_path(self.tmp_dir, "test_nested_missing_expires.md")
        _write_file(path, NESTED_MISSING_EXPIRES_FRONTMATTER)
        output = _run_hook(path)
        ctx = output.get("additionalContext", "")
        self.assertIn(
            "[MEMORY SCHEMA]",
            ctx,
            f"Expected [MEMORY SCHEMA] warning for missing expires, got: {ctx!r}",
        )
        self.assertIn(
            "expires",
            ctx,
            f"Expected 'expires' named in warning, got: {ctx!r}",
        )

    # ------------------------------------------------------------------
    # Test N3: flat file still works (regression guard)
    # ------------------------------------------------------------------
    def test_flat_file_still_no_warning(self):
        """Flattening must be a no-op for files with no metadata: block."""
        path = _make_memory_path(self.tmp_dir, "test_flat_regression.md")
        _write_file(path, VALID_FRONTMATTER)
        output = _run_hook(path)
        self.assertEqual(
            output, {},
            f"Flat-file regression: expected silent {{}}, got: {output}",
        )

    # ------------------------------------------------------------------
    # Test N4: top-level type wins over metadata: type on conflict
    # ------------------------------------------------------------------
    def test_top_level_type_wins_over_metadata_type(self):
        """When type exists at both levels, top-level value is validated.
        Top-level has a valid type; metadata has an invalid one: no
        invalid-type warning expected."""
        path = _make_memory_path(self.tmp_dir, "test_type_conflict.md")
        _write_file(path, NESTED_TYPE_CONFLICT_FRONTMATTER)
        output = _run_hook(path)
        ctx = output.get("additionalContext", "")
        self.assertNotIn(
            "Invalid type",
            ctx,
            f"Expected no invalid-type warning (top-level type wins), got: {ctx!r}",
        )
        # Stronger: the fixture has every required field, so the hook must be
        # fully silent: guards against this test passing for an unrelated
        # reason (e.g. all warnings suppressed by a future change).
        self.assertEqual(
            output, {}, f"Expected silent {{}} (fixture is complete + valid), got: {output}"
        )


# ---------------------------------------------------------------------------
# Unit tests for _flatten_metadata directly (in-process)
# ---------------------------------------------------------------------------

class TestFlattenMetadataUnit(unittest.TestCase):
    """Direct unit tests for the _flatten_metadata helper."""

    def test_nested_dict_merges_up(self):
        fm = {
            "name": "foo",
            "description": "bar",
            "metadata": {
                "type": "reference",
                "confidence": "high",
                "last_verified": "2026-05-22",
                "expires": "2027-05-22",
            },
        }
        result = mod._flatten_metadata(fm)
        # All metadata sub-keys must appear at top level.
        self.assertEqual(result["type"], "reference")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["last_verified"], "2026-05-22")
        self.assertEqual(result["expires"], "2027-05-22")
        # The metadata wrapper key itself must be removed.
        self.assertNotIn("metadata", result)
        # Existing top-level keys preserved.
        self.assertEqual(result["name"], "foo")

    def test_no_metadata_key_returns_equivalent(self):
        fm = {"name": "foo", "type": "reference", "confidence": "high"}
        result = mod._flatten_metadata(fm)
        self.assertEqual(result, fm)
        # Must be a copy, not the same object.
        self.assertIsNot(result, fm)

    def test_top_level_wins_on_conflict(self):
        fm = {
            "type": "reference",          # top-level: valid
            "metadata": {
                "type": "not-a-valid-type",  # metadata: invalid; must be ignored
                "confidence": "high",
            },
        }
        result = mod._flatten_metadata(fm)
        self.assertEqual(result["type"], "reference",
                         "Top-level value must win over metadata value on conflict.")
        self.assertEqual(result["confidence"], "high")

    def test_metadata_non_dict_is_noop(self):
        """If metadata: value is not a dict (e.g. a string), treat as no-op."""
        fm = {
            "name": "foo",
            "metadata": "some-string-not-a-dict",
            "type": "reference",
        }
        result = mod._flatten_metadata(fm)
        # No merging: result should equal the input.
        self.assertEqual(result["metadata"], "some-string-not-a-dict")
        self.assertEqual(result["type"], "reference")


# ---------------------------------------------------------------------------
# Also load the module directly and test validate_yaml() + is_memory_file()
# in-process (faster, no subprocess overhead).
# ---------------------------------------------------------------------------

spec = importlib.util.spec_from_file_location("memory_schema_check", HOOK_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TestValidateYamlUnit(unittest.TestCase):
    """Unit tests for validate_yaml() and is_memory_file() in isolation."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_tmp(self, content, filename="tmp.md"):
        path = os.path.join(self.tmp_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_validate_yaml_ok_on_valid(self):
        path = self._write_tmp(VALID_FRONTMATTER)
        result = mod.validate_yaml(path)
        self.assertEqual(result, "OK")

    def test_validate_yaml_error_on_colon_space(self):
        path = self._write_tmp(INVALID_YAML_FRONTMATTER)
        result = mod.validate_yaml(path)
        # Should return a non-None, non-"OK" string describing the error.
        self.assertIsNotNone(result)
        self.assertNotEqual(result, "OK")
        self.assertIsInstance(result, str)

    def test_validate_yaml_none_on_no_frontmatter(self):
        path = self._write_tmp("Just a body, no frontmatter.\n")
        result = mod.validate_yaml(path)
        self.assertIsNone(result)

    def test_is_memory_file_true(self):
        path = "/some/vault/.claude/projects/abc123/memory/feedback_foo.md"
        self.assertTrue(mod.is_memory_file(path))

    def test_is_memory_file_false_for_work_dir(self):
        path = "/some/vault/Projects/SomeProject/work/note.md"
        self.assertFalse(mod.is_memory_file(path))

    def test_is_memory_file_false_for_memory_md_index(self):
        path = "/some/vault/.claude/projects/abc123/memory/MEMORY.md"
        self.assertFalse(mod.is_memory_file(path))


if __name__ == "__main__":
    unittest.main(verbosity=2)
