"""Smoke tests for skill-routing-check.py — PreToolUse Skill hook.

Validates the last TASK TYPE from the transcript matches the routing table
for process-* skills. Allows non-process skills unconditionally. Denies misroutes.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "skill_routing_check",
    str(Path(__file__).parent / "skill-routing-check.py"),
)
src = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(src)


def _write_transcript(td: Path, events: list[dict]) -> str:
    p = td / "session.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return str(p)


def _assistant_text(text: str) -> dict:
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def _run(payload: dict) -> str:
    captured = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         redirect_stdout(captured):
        src.main()
    return captured.getvalue()


class StripFencesTests(unittest.TestCase):
    def test_strips_triple_backtick_block(self):
        text = "Before\n```\nTASK TYPE: Research\n```\nAfter"
        out = src.strip_fences(text)
        self.assertNotIn("TASK TYPE: Research", out)
        self.assertIn("Before", out)
        self.assertIn("After", out)

    def test_leaves_text_outside_fences(self):
        text = "TASK TYPE: Build\n\n```js\nconsole.log('x')\n```"
        out = src.strip_fences(text)
        self.assertIn("TASK TYPE: Build", out)


class GuardTests(unittest.TestCase):
    def test_empty_stdin_silent(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             redirect_stdout(captured):
            src.main()
        self.assertEqual(captured.getvalue(), "")

    def test_malformed_json_silent(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("garbage")), \
             redirect_stdout(captured):
            src.main()
        self.assertEqual(captured.getvalue(), "")

    def test_missing_skill_name_silent(self):
        out = _run({"tool_name": "Skill", "tool_input": {}})
        self.assertEqual(out, "")

    def test_non_process_skill_allowed(self):
        # task-classifier, save, ensemble — not in PROCESS_SKILLS — unconditional pass
        out = _run({"tool_name": "Skill", "tool_input": {"skill": "task-classifier"}})
        self.assertEqual(out, "")

    def test_process_skill_missing_transcript_allows(self):
        # Can't verify routing without transcript
        out = _run({"tool_name": "Skill", "tool_input": {"skill": "process-research"}})
        self.assertEqual(out, "")

    def test_process_skill_nonexistent_transcript_allows(self):
        out = _run({
            "tool_name": "Skill",
            "tool_input": {"skill": "process-research"},
            "transcript_path": "/no/such/file.jsonl",
        })
        self.assertEqual(out, "")


class RoutingValidationTests(unittest.TestCase):
    def test_correct_routing_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Research\n\nApproach: ..."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            self.assertEqual(out, "")

    def test_misroute_research_to_build_denies(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Research\n\nApproach: ..."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-build"},
                "transcript_path": tp,
            })
            result = json.loads(out)
            hso = result["hookSpecificOutput"]
            self.assertEqual(hso["permissionDecision"], "deny")
            self.assertIn("research", hso["permissionDecisionReason"].lower())
            self.assertIn("process-research", hso["permissionDecisionReason"])

    def test_quick_classification_allows_any(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Quick\n\nInline answer..."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            self.assertEqual(out, "")

    def test_no_classification_allows(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("Just some prose, no classification block."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            self.assertEqual(out, "")

    def test_classification_inside_fence_ignored(self):
        # TASK TYPE inside a fenced code block (e.g., example doc) must not bind routing
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("Example:\n```\nTASK TYPE: Research\n```\nNow building."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-build"},
                "transcript_path": tp,
            })
            # No real classification visible → allow
            self.assertEqual(out, "")

    def test_content_routes_to_build(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Content"),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-build"},
                "transcript_path": tp,
            })
            self.assertEqual(out, "")  # Content → process-build is correct routing

    def test_last_classification_wins(self):
        # Two classifications in the same transcript — the later one binds
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Research"),
                _assistant_text("TASK TYPE: Build"),
            ])
            # Build → process-build correct; process-research now wrong
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            result = json.loads(out)
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")


class WorkflowBoundaryResetTests(unittest.TestCase):
    """B-0 fix (2026-06-11): Workflow tool_use of a process skill resets routing context.

    A Workflow invocation of process-planning (or any process-* skill) consumes the
    TASK TYPE: planning classification that triggered it. The next Skill invocation of
    process-research must not be blocked by that stale residue.

    Acceptance criteria (plan Step 1):
    - Fixture must contain the full three-entry Workflow shape
      (assistant Workflow tool_use → user tool_result wrapper → assistant relay text).
    - After the three-entry shape, a Skill invocation of process-research → ALLOW.
    - A genuinely mis-routed Skill invocation with NO intervening Workflow → DENY.
    """

    def _workflow_tool_use(self, wf_name: str) -> dict:
        """assistant entry containing a Workflow tool_use block."""
        return {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Workflow",
                        "input": {"name": wf_name},
                    }
                ],
            },
        }

    def _workflow_tool_use_scriptpath(self, script_path: str) -> dict:
        """assistant entry using scriptPath (thin-invoker pattern from checklist item 12)."""
        return {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "name": "Workflow",
                        "input": {"scriptPath": script_path},
                    }
                ],
            },
        }

    def _tool_result_wrapper(self) -> dict:
        """user entry that is a tool_result wrapper — entry 2 of the three-entry shape.
        Must NOT be treated as a real user turn by the routing check."""
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "wf_abc123",
                        "content": [{"type": "text", "text": "workflow output"}],
                    }
                ],
            },
        }

    def _relay_text(self, text: str) -> dict:
        """assistant relay entry — entry 3 of the three-entry shape."""
        return _assistant_text(text)

    def test_workflow_process_planning_resets_routing_allows_research(self):
        """Live misfire replay: TASK TYPE: planning → Workflow process-planning (3-entry shape)
        → Skill process-research. Must ALLOW (routing context was consumed by the Workflow)."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                # Classification turn
                _assistant_text("TASK TYPE: Planning\n\nInvoking process-planning..."),
                # Three-entry Workflow shape (entry 1: tool_use)
                self._workflow_tool_use("process-planning"),
                # Entry 2: tool_result wrapper — must NOT reset routing or clear state
                self._tool_result_wrapper(),
                # Entry 3: relay text from the workflow
                self._relay_text("PLANNING SCOPE\nGoal: migrate skills\n\nPLANNING COMPLETE"),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            self.assertEqual(out, "", (
                "process-research must be ALLOWED after a Workflow process-planning run "
                "consumed the TASK TYPE: planning classification — B-0 routing reset"
            ))

    def test_workflow_via_scriptpath_resets_routing(self):
        """Thin-invoker uses scriptPath (checklist item 12). B-0 reset must resolve
        scriptPath basename to recognize process-planning and reset the context."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Planning"),
                self._workflow_tool_use_scriptpath(".claude/workflows/process-planning.js"),
                self._tool_result_wrapper(),
                self._relay_text("PLANNING SCOPE\nGoal: x"),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            self.assertEqual(out, "", "scriptPath-based Workflow must also trigger B-0 reset")

    def test_genuine_misroute_no_workflow_still_denied(self):
        """Negative fixture: TASK TYPE: planning + no Workflow between classification and Skill
        invocation. A genuine misroute must still be DENIED — B-0 reset is not a blanket pass."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Planning\n\nApproach: ..."),
                # No Workflow tool_use — direct mis-invocation of process-research
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            result = json.loads(out)
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
                "A genuine misroute with no intervening Workflow must still be DENIED",
            )

    def test_workflow_only_resets_if_it_is_process_skill(self):
        """A non-process Workflow (e.g. 'some-utility') does NOT reset routing context.
        Only process-* Workflow names trigger the reset."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Planning"),
                # Workflow with a non-process name — should NOT reset
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": "Workflow",
                                "input": {"name": "some-utility-workflow"},
                            }
                        ],
                    },
                },
                self._tool_result_wrapper(),
                self._relay_text("Utility done."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            # planning still active — research is mis-routed → deny
            result = json.loads(out)
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
                "Non-process Workflow must not reset routing context",
            )

    def test_task_type_after_workflow_still_binds(self):
        """A new TASK TYPE assertion AFTER a Workflow run re-establishes routing context.
        The most-recent routing event is the TASK TYPE, not the Workflow."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _assistant_text("TASK TYPE: Planning"),
                self._workflow_tool_use("process-planning"),
                self._tool_result_wrapper(),
                self._relay_text("PLANNING SCOPE\nGoal: x"),
                # New classification AFTER the workflow
                _assistant_text("TASK TYPE: Build\n\nNew task identified."),
            ])
            out = _run({
                "tool_name": "Skill",
                "tool_input": {"skill": "process-research"},
                "transcript_path": tp,
            })
            # Build is now active — research is still mis-routed
            result = json.loads(out)
            self.assertEqual(
                result["hookSpecificOutput"]["permissionDecision"],
                "deny",
                "TASK TYPE assertion after a Workflow re-establishes routing — still denies wrong skill",
            )


if __name__ == "__main__":
    unittest.main()
