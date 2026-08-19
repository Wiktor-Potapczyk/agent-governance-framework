"""Tests for aggregate-write-guard.py: PreToolUse guard on Write/Edit to the
memory-layer aggregates (MEMORY.md head index, governance-log.jsonl,
hook-activity.jsonl).

Written before the implementation (declarative-first): every assertion below
states the required behavior; aggregate-write-guard.py is built to satisfy it.

Covers the block/pass matrix from the ticket (task_plan.md, "cross-session
singleton write guard", consolidated v2 direction) and its acceptance test:
the 2026-08-07 incident (311/409 memory citations dropped in one Write) must
deny when replayed through BOTH the Write shape and the Edit-whole-file shape.

All protected paths are monkeypatched to a per-test tempdir. No test touches
the real MEMORY.md or the real governance-log.jsonl / hook-activity.jsonl.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "aggregate_write_guard",
    str(Path(__file__).parent / "aggregate-write-guard.py"),
)
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
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


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class _TempMemoryFolderTestCase(unittest.TestCase):
    """Base class: builds a scratch memory folder and points the guard's
    protected-path constants at files inside it. Restores the real constants
    on teardown so no other test file in this suite is affected."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="agg-write-guard-test-")
        self.memory_dir = os.path.join(self._tmp, "memory")
        os.makedirs(self.memory_dir, exist_ok=True)
        self.memory_path = os.path.join(self.memory_dir, "MEMORY.md")
        self.gov_log_path = os.path.join(self._tmp, "governance-log.jsonl")
        self.hook_log_path = os.path.join(self._tmp, "hook-activity.jsonl")

        self._orig_memory_path = guard.MEMORY_PATH
        self._orig_gov_log_path = guard.GOVERNANCE_LOG_PATH
        self._orig_hook_log_path = guard.HOOK_ACTIVITY_LOG_PATH
        guard.MEMORY_PATH = self.memory_path
        guard.GOVERNANCE_LOG_PATH = self.gov_log_path
        guard.HOOK_ACTIVITY_LOG_PATH = self.hook_log_path

        # Route _governance_logger's own writes into the same tempdir so
        # log-emission assertions (TEST-007) never touch the real file.
        self._orig_hal_env = os.environ.get("HOOK_ACTIVITY_LOG_PATH")
        os.environ["HOOK_ACTIVITY_LOG_PATH"] = self.hook_log_path

    def tearDown(self):
        guard.MEMORY_PATH = self._orig_memory_path
        guard.GOVERNANCE_LOG_PATH = self._orig_gov_log_path
        guard.HOOK_ACTIVITY_LOG_PATH = self._orig_hook_log_path
        if self._orig_hal_env is None:
            os.environ.pop("HOOK_ACTIVITY_LOG_PATH", None)
        else:
            os.environ["HOOK_ACTIVITY_LOG_PATH"] = self._orig_hal_env
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_memory(self, content: str) -> None:
        _write_file(self.memory_path, content)

    def _write_sibling(self, filename: str, content: str) -> None:
        _write_file(os.path.join(self.memory_dir, filename), content)

    def _activity_lines(self) -> list:
        if not os.path.isfile(self.hook_log_path):
            return []
        with open(self.hook_log_path, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


def _synthetic_incident_current(n_citations: int = 20) -> str:
    """A small stand-in for the 97KB / 409-citation shape: N index lines,
    each citing a distinct topic file."""
    lines = ["# Vault Project Memory", ""]
    for i in range(n_citations):
        lines.append(
            f"- **Fact {i}.** [finding_fact_{i}.md](finding_fact_{i}.md)"
        )
    return "\n".join(lines) + "\n"


def _synthetic_incident_new(keep: int) -> str:
    """The post-incident shape: only the first `keep` citations survive."""
    lines = ["# Vault Project Memory", ""]
    for i in range(keep):
        lines.append(
            f"- **Fact {i}.** [finding_fact_{i}.md](finding_fact_{i}.md)"
        )
    return "\n".join(lines) + "\n"


class ReplayedIncidentViaWriteTests(_TempMemoryFolderTestCase):
    """TEST-001: the 2026-08-07 incident shape (most citations dropped, none
    of the dropped targets covered by any sibling file) replayed as a Write.
    Target files for the dropped citations exist on disk (so they are not
    exempt) but no other memory file mentions them (so they are uncovered).
    Must deny."""

    def test_incident_replay_write_denies(self):
        current = _synthetic_incident_current(n_citations=20)
        self._write_memory(current)
        # Every citation target exists on disk as its own topic file, but
        # none of them is mentioned by any OTHER sibling, so all 15 dropped
        # citations below are uncovered.
        for i in range(20):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i} detail.\n")

        proposed = _synthetic_incident_new(keep=5)
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(_decision(out), "deny")
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("finding_fact_19.md", reason)

    def test_deny_message_names_uncovered_citations_and_safe_order(self):
        current = _synthetic_incident_current(n_citations=3)
        self._write_memory(current)
        for i in range(3):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i} detail.\n")
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": "# Vault Project Memory\n"},
        })
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("finding_fact_0.md", reason)
        self.assertIn("topic file", reason)

    def test_deny_reason_caps_listed_citations_around_ten(self):
        current = _synthetic_incident_current(n_citations=25)
        self._write_memory(current)
        for i in range(25):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i} detail.\n")
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": "# Vault Project Memory\n"},
        })
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        listed = reason.count(".md](")  # not present; count literal ".md" mentions instead
        md_mentions = reason.count("finding_fact_")
        self.assertLessEqual(md_mentions, 11)  # 10 named + "N more" style overflow note
        self.assertIn("more", reason)


class ReplayedIncidentViaEditTests(_TempMemoryFolderTestCase):
    """TEST-002: the identical incident shape expressed as an Edit whose
    old_string spans the entire current file (a wholesale replace disguised
    as an anchored diff). Must deny exactly like the Write case: content
    shape drives the verdict, not tool identity."""

    def test_whole_file_edit_denies(self):
        current = _synthetic_incident_current(n_citations=20)
        self._write_memory(current)
        for i in range(20):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i} detail.\n")

        proposed = _synthetic_incident_new(keep=5)
        out = _run({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": self.memory_path,
                "old_string": current,
                "new_string": proposed,
            },
        })
        self.assertEqual(_decision(out), "deny")


class SafeOrderCompactionTests(_TempMemoryFolderTestCase):
    """TEST-003: dropped citations all pre-exist in sibling topic files
    (write-topics-first-shrink-head-second). Must allow regardless of how
    much shrinks."""

    def test_dropped_citations_covered_by_siblings_allows(self):
        current = _synthetic_incident_current(n_citations=10)
        self._write_memory(current)
        for i in range(10):
            # Each topic file's own body CITES the other topic file via the
            # same markdown-link syntax CITATION_RE parses (post-review
            # Finding 2: a bare filename mention no longer counts as
            # coverage, only a real parsed citation does).
            other = (i + 1) % 10
            self._write_sibling(
                f"finding_fact_{i}.md",
                f"Fact {i} detail. See also [finding_fact_{other}.md](finding_fact_{other}.md).\n",
            )

        proposed = "# Vault Project Memory\n\n(compacted, see topic files)\n"
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))

    def test_safe_order_compaction_via_edit_allows(self):
        current = _synthetic_incident_current(n_citations=4)
        self._write_memory(current)
        for i in range(4):
            other = (i + 1) % 4
            self._write_sibling(
                f"finding_fact_{i}.md",
                f"Fact {i}. Cross-ref [finding_fact_{other}.md](finding_fact_{other}.md).\n",
            )
        out = _run({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": self.memory_path,
                "old_string": current,
                "new_string": "# Vault Project Memory\n\n(compacted)\n",
            },
        })
        self.assertEqual(out, "")


class GrowthOnlyRewriteTests(_TempMemoryFolderTestCase):
    """TEST-004: every current citation retained, content only added. No
    citation is dropped, so the guard has nothing to evaluate. Must allow."""

    def test_growth_only_write_allows(self):
        current = _synthetic_incident_current(n_citations=8)
        self._write_memory(current)
        proposed = current + "- **New fact.** [finding_new.md](finding_new.md)\n"
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))

    def test_the_2026_08_08_restoration_shape_allows(self):
        """The ratified restoration grew the on-disk file (17KB -> 20KB);
        the architect review's own correction. A pure-growth Write against
        a real MEMORY.md-shaped file must not deny."""
        current = _synthetic_incident_current(n_citations=60)
        self._write_memory(current)
        proposed = current + "".join(
            f"- **Restored fact {i}.** [finding_restored_{i}.md](finding_restored_{i}.md)\n"
            for i in range(15)
        )
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(out, "")


class DroppedTargetGoneTests(_TempMemoryFolderTestCase):
    """TEST-005: a dropped citation whose target file no longer exists on
    disk is exempt (delete-a-dead-memory-and-its-index-line stays legal).
    Must allow even with zero sibling coverage."""

    def test_dropped_citation_with_missing_target_allows(self):
        current = _synthetic_incident_current(n_citations=5)
        self._write_memory(current)
        # Only create 4 of the 5 target files; finding_fact_4.md never
        # existed on disk (or was already deleted before this write).
        for i in range(4):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i}.\n")

        proposed = _synthetic_incident_new(keep=4)  # drops fact 4 only
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))


class SiblingCoverageBoundaryTests(_TempMemoryFolderTestCase):
    """Post-review Finding 2 (MAJOR) regression: coverage must be a real
    parsed citation, not a bare substring test. A sibling that only cites
    'governance-log.md' must NOT count as coverage for a dropped 'log.md'
    citation (the old bare `filename in text` check would match 'log.md'
    as a substring of 'governance-log.md')."""

    def test_substring_lookalike_sibling_does_not_cover_denies(self):
        current = "# Vault Project Memory\n\n- **Entry.** [log.md](log.md)\n"
        self._write_memory(current)
        # Target file exists on disk, so it is not exempt via missing-target.
        self._write_sibling("log.md", "The log file itself.\n")
        # The only sibling MENTION of the dropped filename is as a substring
        # of a different, real citation target: governance-log.md.
        self._write_sibling(
            "other.md",
            "See [governance-log.md](governance-log.md) for details.\n",
        )

        proposed = "# Vault Project Memory\n\n(compacted)\n"
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(_decision(out), "deny")
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("log.md", reason)

    def test_real_citation_to_the_exact_filename_does_cover_allows(self):
        """Control case: a sibling that cites the exact dropped filename
        (not a lookalike substring) DOES count as coverage."""
        current = "# Vault Project Memory\n\n- **Entry.** [log.md](log.md)\n"
        self._write_memory(current)
        self._write_sibling("log.md", "The log file itself.\n")
        self._write_sibling(
            "other.md",
            "Cross-ref [log.md](log.md) directly.\n",
        )

        proposed = "# Vault Project Memory\n\n(compacted)\n"
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))


class MultiEditTests(_TempMemoryFolderTestCase):
    """Post-review Finding 3 (MAJOR) regression: the matcher now includes
    MultiEdit, and the guard must actually compute effective content for it
    (tool_input.edits, applied sequentially), not silently allow via the
    fail-open exception path."""

    def test_multiedit_whole_file_replace_with_uncovered_drops_denies(self):
        current = _synthetic_incident_current(n_citations=5)
        self._write_memory(current)
        for i in range(5):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i}.\n")

        proposed = _synthetic_incident_new(keep=0)
        out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": self.memory_path,
                "edits": [
                    {"old_string": current, "new_string": proposed},
                ],
            },
        })
        self.assertEqual(_decision(out), "deny")

    def test_multiedit_sequential_edits_apply_in_order_for_memory(self):
        """Two edits in sequence: the second edit's old_string only exists
        after the first edit has already been applied, proving edits are
        applied against each other's result, not each independently against
        the original disk content."""
        current = _synthetic_incident_current(n_citations=3)
        self._write_memory(current)
        for i in range(3):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i}.\n")

        step1 = current.replace(
            "# Vault Project Memory", "# Vault Project Memory (staged)"
        )
        out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": self.memory_path,
                "edits": [
                    {
                        "old_string": "# Vault Project Memory",
                        "new_string": "# Vault Project Memory (staged)",
                    },
                    {
                        "old_string": step1,
                        "new_string": "# Vault Project Memory (staged)\n\n(fully compacted)\n",
                    },
                ],
            },
        })
        self.assertEqual(_decision(out), "deny")  # drops all 3, none covered

    def test_multiedit_append_shaped_on_jsonl_allows(self):
        current = '{"a": 1}\n{"a": 2}\n'
        _write_file(self.gov_log_path, current)
        out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": self.gov_log_path,
                "edits": [
                    {"old_string": '{"a": 2}\n', "new_string": '{"a": 2}\n{"a": 3}\n'},
                ],
            },
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))

    def test_multiedit_non_append_on_jsonl_denies(self):
        current = '{"a": 1}\n{"a": 2}\n{"a": 3}\n'
        _write_file(self.gov_log_path, current)
        out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": self.gov_log_path,
                "edits": [
                    {"old_string": current, "new_string": '{"a": 1}\n{"a": 3}\n'},
                ],
            },
        })
        self.assertEqual(_decision(out), "deny")

    def test_multiedit_missing_edits_list_allows(self):
        current = _synthetic_incident_current(n_citations=2)
        self._write_memory(current)
        out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": self.memory_path},
        })
        self.assertEqual(out, "")

    def test_multiedit_unrelated_path_is_silent(self):
        out = _run({
            "tool_name": "MultiEdit",
            "tool_input": {
                "file_path": os.path.join(self._tmp, "notes.md"),
                "edits": [{"old_string": "a", "new_string": "b"}],
            },
        })
        self.assertEqual(out, "")


class SiblingScanIoErrorFailsOpenTests(_TempMemoryFolderTestCase):
    """Post-review Finding 4 (MINOR) regression: a listdir failure inside
    the sibling-coverage scan must fail toward allow (aligning with
    _read_current's own fail-open direction), not toward deny, and must log
    an anomaly record distinguishable from a real allow/deny verdict."""

    def test_listdir_failure_during_coverage_scan_allows_and_logs_anomaly(self):
        current = _synthetic_incident_current(n_citations=3)
        self._write_memory(current)
        for i in range(3):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i}.\n")

        proposed = "# Vault Project Memory\n\n(compacted)\n"
        real_listdir = os.listdir

        def _boom(path):
            if os.path.normcase(os.path.normpath(path)) == os.path.normcase(
                os.path.normpath(self.memory_dir)
            ):
                raise OSError("simulated listdir failure")
            return real_listdir(path)

        before = len(self._activity_lines())
        with mock.patch("os.listdir", side_effect=_boom):
            out = _run({
                "tool_name": "Write",
                "tool_input": {"file_path": self.memory_path, "content": proposed},
            })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))

        after = self._activity_lines()
        anomalies = [r for r in after[before:] if r.get("decision") == "anomaly"]
        self.assertGreaterEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["hook"], "aggregate-write-guard")


class JsonlAggregateLogTests(_TempMemoryFolderTestCase):
    """TEST-006: governance-log.jsonl / hook-activity.jsonl are append-only.
    A full-replace Write denies; an append-shaped Write allows. Edit variants
    included for the same content-shape logic."""

    def test_full_replace_write_denies(self):
        current = '{"a": 1}\n{"a": 2}\n{"a": 3}\n'
        _write_file(self.gov_log_path, current)
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.gov_log_path, "content": '{"a": 9}\n'},
        })
        self.assertEqual(_decision(out), "deny")

    def test_append_shaped_write_allows(self):
        current = '{"a": 1}\n{"a": 2}\n'
        _write_file(self.gov_log_path, current)
        proposed = current + '{"a": 3}\n'
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.gov_log_path, "content": proposed},
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))

    def test_hook_activity_log_full_replace_denies(self):
        current = '{"hook": "a"}\n{"hook": "b"}\n'
        _write_file(self.hook_log_path, current)
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.hook_log_path, "content": '{"hook": "z"}\n'},
        })
        self.assertEqual(_decision(out), "deny")

    def test_edit_that_drops_a_line_denies(self):
        current = '{"a": 1}\n{"a": 2}\n{"a": 3}\n'
        _write_file(self.gov_log_path, current)
        out = _run({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": self.gov_log_path,
                "old_string": current,
                "new_string": '{"a": 1}\n{"a": 3}\n',
            },
        })
        self.assertEqual(_decision(out), "deny")

    def test_edit_that_only_appends_a_line_allows(self):
        current = '{"a": 1}\n{"a": 2}\n'
        _write_file(self.gov_log_path, current)
        out = _run({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": self.gov_log_path,
                "old_string": '{"a": 2}\n',
                "new_string": '{"a": 2}\n{"a": 3}\n',
            },
        })
        self.assertEqual(out, "")

    def test_edit_reorder_plus_forged_record_denies(self):
        """Post-review Finding 1 (BLOCKER) regression: the reviewer's own
        reproduction. Reordering existing lines and splicing a forged record
        in between them, expressed as a whole-file Edit, must deny exactly
        like the byte-identical content would as a Write. Before the fix,
        the Edit branch only checked line PRESENCE (a multiset comparison),
        so this reorder-plus-forge passed with empty stdout."""
        current = '{"seq": 1}\n{"seq": 2}\n{"seq": 3}\n'
        _write_file(self.gov_log_path, current)
        reordered_and_forged = (
            '{"seq": 2}\n{"seq": 1}\n{"seq": 99, "forged": true}\n{"seq": 3}\n'
        )
        out = _run({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": self.gov_log_path,
                "old_string": current,
                "new_string": reordered_and_forged,
            },
        })
        self.assertEqual(_decision(out), "deny")

        # The identical resulting content, expressed as a Write, must also
        # deny (it always did): proves the rule is now uniform across tools.
        out_write = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.gov_log_path, "content": reordered_and_forged},
        })
        self.assertEqual(_decision(out_write), "deny")

    def test_empty_jsonl_file_allows_any_write_bootstrap(self):
        # gov_log_path is never created: os.path missing == bootstrap allow.
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.gov_log_path, "content": '{"a": 1}\n'},
        })
        self.assertEqual(out, "")
        self.assertIsNone(_decision(out))


class LoggingOnBothOutcomesTests(_TempMemoryFolderTestCase):
    """TEST-007: both allow and deny verdicts on a protected path emit a
    hook-activity.jsonl record via the shared _governance_logger helper (the
    governance miner needs allow-side data too)."""

    def test_allow_path_emits_a_log_record(self):
        current = _synthetic_incident_current(n_citations=3)
        self._write_memory(current)
        proposed = current + "- **New.** [finding_new.md](finding_new.md)\n"
        before = len(self._activity_lines())
        _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": proposed},
        })
        after = self._activity_lines()
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[-1]["hook"], "aggregate-write-guard")
        self.assertEqual(after[-1]["decision"], "allow")

    def test_deny_path_emits_a_log_record(self):
        current = _synthetic_incident_current(n_citations=5)
        self._write_memory(current)
        for i in range(5):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i}.\n")
        before = len(self._activity_lines())
        _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": "# empty\n"},
        })
        after = self._activity_lines()
        self.assertEqual(len(after), before + 1)
        self.assertEqual(after[-1]["hook"], "aggregate-write-guard")
        self.assertEqual(after[-1]["decision"], "deny")


class NonProtectedPathTests(_TempMemoryFolderTestCase):
    """TEST-008: any path other than the configured MEMORY.md / jsonl logs
    (including a differently located MEMORY.md, and a sibling topic file)
    leaves the hook silent: no stdout, no log record, allow by omission."""

    def test_unrelated_write_is_silent(self):
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": os.path.join(self._tmp, "notes.md"), "content": "hi"},
        })
        self.assertEqual(out, "")
        self.assertEqual(self._activity_lines(), [])

    def test_differently_located_memory_md_is_not_protected(self):
        """v2 scope is an EXACT path match, not any file named MEMORY.md
        anywhere (the v1 design's basename-only heuristic is superseded)."""
        lookalike = os.path.join(self._tmp, "elsewhere", "MEMORY.md")
        _write_file(lookalike, "# Not the real one\n")
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": lookalike, "content": "wiped\n"},
        })
        self.assertEqual(out, "")

    def test_sibling_topic_file_is_not_protected(self):
        self._write_sibling("feedback_example.md", "old content\n")
        out = _run({
            "tool_name": "Write",
            "tool_input": {
                "file_path": os.path.join(self.memory_dir, "feedback_example.md"),
                "content": "wholly different content\n",
            },
        })
        self.assertEqual(out, "")


class EditOldStringNotFoundTests(_TempMemoryFolderTestCase):
    """An Edit whose old_string is not present in the current content is not
    double-guarded here; the Edit tool itself will fail on that mismatch."""

    def test_old_string_not_found_allows(self):
        current = _synthetic_incident_current(n_citations=3)
        self._write_memory(current)
        out = _run({
            "tool_name": "Edit",
            "tool_input": {
                "file_path": self.memory_path,
                "old_string": "text that is not in the file",
                "new_string": "replacement",
            },
        })
        self.assertEqual(out, "")


class FailOpenTests(unittest.TestCase):
    def test_unparseable_stdin_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("{not json")), \
             redirect_stdout(captured):
            rc = guard.main()
        self.assertEqual(rc, 0)
        self.assertEqual(captured.getvalue(), "")

    def test_non_write_edit_tool_noops(self):
        out = _run({"tool_name": "Read", "tool_input": {"file_path": "x.md"}})
        self.assertEqual(out, "")

    def test_string_tool_input_is_parsed(self):
        out = _run({
            "tool_name": "Write",
            "tool_input": json.dumps({"file_path": "z:\\nowhere.md", "content": "x"}),
        })
        self.assertEqual(out, "")

    def test_missing_file_path_noops(self):
        out = _run({"tool_name": "Write", "tool_input": {"content": "x"}})
        self.assertEqual(out, "")


class DenyShapeTests(_TempMemoryFolderTestCase):
    """Deny payload shape must match the rest of the hook suite exactly:
    hookSpecificOutput.{hookEventName, permissionDecision,
    permissionDecisionReason}, no extra/missing keys."""

    def test_deny_payload_shape(self):
        current = _synthetic_incident_current(n_citations=3)
        self._write_memory(current)
        for i in range(3):
            self._write_sibling(f"finding_fact_{i}.md", f"Fact {i}.\n")
        out = _run({
            "tool_name": "Write",
            "tool_input": {"file_path": self.memory_path, "content": "# empty\n"},
        })
        parsed = json.loads(out)
        hso = parsed["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIsInstance(hso["permissionDecisionReason"], str)
        self.assertGreater(len(hso["permissionDecisionReason"]), 0)
        self.assertEqual(sorted(hso), sorted(
            ["hookEventName", "permissionDecision", "permissionDecisionReason"]
        ))


if __name__ == "__main__":
    unittest.main()
