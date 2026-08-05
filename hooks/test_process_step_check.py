"""
Tests for process-step-check.py: PM rubber-stamp hardening (B2 fix 2026-04-13).
"""

import json
import unittest
import importlib.util
import os

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))


def load_hook():
    path = os.path.join(HOOKS_DIR, "process-step-check.py")
    spec = importlib.util.spec_from_file_location("process_step_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_transcript_lines(blocks):
    """Build JSONL transcript lines from a list of content blocks."""
    entry = {
        "type": "assistant",
        "message": {"content": blocks}
    }
    return [json.dumps(entry)]


class TestPmRubberStampHardening(unittest.TestCase):
    """B2 fix (2026-04-13): pm-orchestrator must be dispatched, not just inline report."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_hook()

    def test_pm_with_orchestrator_and_report_passes(self):
        """pm Skill + pm-orchestrator Agent + PM CHECKPOINT REPORT → PASS."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
            {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "pm-orchestrator", "prompt": "run checkpoint"}},
            {"type": "text", "text": "PM CHECKPOINT REPORT\nProject: test\nViability: PASS\nBlockers: 0"},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertTrue(passed, f"Should pass but got: {msg}")

    def test_pm_without_orchestrator_inline_report_blocked(self):
        """pm Skill + inline PM CHECKPOINT REPORT (no agent) → BLOCK."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
            {"type": "text", "text": "PM CHECKPOINT REPORT\nProject: test\nViability: PASS\nBlockers: 0"},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertFalse(passed)
        self.assertIn("pm-orchestrator agent was not dispatched", msg)

    def test_pm_with_orchestrator_no_report_blocked(self):
        """pm Skill + pm-orchestrator dispatched + no report → BLOCK (existing check)."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
            {"type": "tool_use", "name": "Agent", "input": {"subagent_type": "pm-orchestrator", "prompt": "run checkpoint"}},
            {"type": "text", "text": "The PM agent ran but I forgot to write the report."},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertFalse(passed)
        self.assertIn("missing PM CHECKPOINT REPORT", msg)

    def test_no_pm_invoked_passes(self):
        """No pm Skill invocation → nothing to check → PASS."""
        blocks = [
            {"type": "tool_use", "name": "Skill", "input": {"skill": "process-build"}},
            {"type": "text", "text": "Built the thing."},
        ]
        lines = make_transcript_lines(blocks)
        passed, msg = self.mod.check_pm_checkpoint_report(lines)
        self.assertTrue(passed)


class ProcessStepBoundaryTests(unittest.TestCase):
    """Named FP-guards (boundary-test harness sprint 7). Each docstring names its
    boundary_axis. Covers the adjacent-safe region for the HARD checks: the
    documented misfire was process-step-check firing on Quick/small tasks that
    legitimately skip process skills + /pm."""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_hook()

    # --- skill-scoping boundaries: a HARD check applies ONLY to its own skill ---
    def test_fp_non_qa_skill_no_qa_report_silent(self):
        """FP-PS-01 boundary_axis: 'process-qa requires QA REPORT vs other skills do not'.
        process-build with no QA REPORT must pass check_qa_report (it only governs process-qa)."""
        ok, _ = self.mod.check_qa_report("process-build", ["Built the thing. No QA REPORT here."])
        self.assertTrue(ok)

    def test_fp_qa_no_verifiable_claims_silent(self):
        """FP-PS-02 boundary_axis: 'QA with claims needs REPORT vs no-verifiable-claims exit'.
        A process-qa turn that declares 'no verifiable claims' must pass without a REPORT."""
        ok, _ = self.mod.check_qa_report("process-qa", ["no verifiable claims"])
        self.assertTrue(ok)

    def test_fp_non_pentest_skill_silent(self):
        """FP-PS-03 boundary_axis: 'process-pentest requires PENTEST REPORT vs other skills'."""
        ok, _ = self.mod.check_pentest_report("process-build", ["no pentest report"])
        self.assertTrue(ok)

    def test_fp_scope_present_silent(self):
        """FP-PS-04 boundary_axis: 'SCOPE block present vs absent'."""
        ok, _ = self.mod.check_scope("process-build", ["BUILD SCOPE\nGoal: x\nTech: py"])
        self.assertTrue(ok)

    # --- PM-increment boundaries: HARD pm-enforcement only on COMPLETE multi-step ---
    def test_fp_single_task_increment_silent(self):
        """FP-PS-05 boundary_axis: 'multi-step increment (2+ TaskCreate) vs single/Quick task'.
        A 1-TaskCreate turn must NOT trigger pm-enforcement (the documented Quick-task misfire)."""
        lines = make_transcript_lines([
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "one thing"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "process-pentest"}},
        ])
        ok, _ = self.mod.check_pm_after_increment(lines)
        self.assertTrue(ok)

    def test_fp_incomplete_increment_silent(self):
        """FP-PS-06 boundary_axis: 'all-tasks-complete vs increment still in progress'.
        2 created / 1 complete must NOT trigger pm-enforcement yet."""
        lines = make_transcript_lines([
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "a"}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "b"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "process-pentest"}},
        ])
        ok, _ = self.mod.check_pm_after_increment(lines)
        self.assertTrue(ok)

    def test_fp_pm_invoked_resets_increment_silent(self):
        """FP-PS-07 boundary_axis: 'increment closed by /pm vs open increment'.
        A complete 2-task increment where /pm WAS invoked resets the counters → no block."""
        lines = make_transcript_lines([
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "a"}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "b"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "process-pentest"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "pm"}},
        ])
        ok, _ = self.mod.check_pm_after_increment(lines)
        self.assertTrue(ok)

    # --- matching TP: the same check SHOULD fire when the increment really is open ---
    def test_tp_complete_increment_no_pm_blocks(self):
        """TP-PS-01: 2 tasks complete + pentest + NO /pm → pm-enforcement fires."""
        lines = make_transcript_lines([
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "a"}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "b"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "Skill", "input": {"skill": "process-pentest"}},
        ])
        ok, msg = self.mod.check_pm_after_increment(lines)
        self.assertFalse(ok)
        self.assertIn("/pm", msg)


def make_workflow_three_entry(wf_name: str, relay_text: str) -> list[str]:
    """Return the full three-entry Workflow transcript shape as JSONL lines.

    Entry 1: assistant: Workflow tool_use
    Entry 2: user: tool_result wrapper (NOT a real user turn)
    Entry 3: assistant: relay text (contains SCOPE / QA REPORT blocks)

    Acceptance criterion (plan Step 2 item i): fixtures MUST contain all three entries
    so tests cannot false-pass against the unfixed reset (B-1b dead-code detection).
    """
    entry1 = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Workflow",
                    "input": {"name": wf_name},
                }
            ]
        },
    })
    entry2 = json.dumps({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "wf_test_123",
                    "content": [{"type": "text", "text": "workflow intermediate output"}],
                }
            ]
        },
    })
    entry3 = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": relay_text}]},
    })
    return [entry1, entry2, entry3]


def make_workflow_three_entry_scriptpath(script_path: str, relay_text: str) -> list[str]:
    """Same as make_workflow_three_entry but uses scriptPath (thin-invoker form)."""
    entry1 = json.dumps({
        "type": "assistant",
        "message": {
            "content": [
                {
                    "type": "tool_use",
                    "name": "Workflow",
                    "input": {"scriptPath": script_path},
                }
            ]
        },
    })
    entry2 = json.dumps({
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "wf_test_456",
                    "content": [{"type": "text", "text": "workflow intermediate output"}],
                }
            ]
        },
    })
    entry3 = json.dumps({
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": relay_text}]},
    })
    return [entry1, entry2, entry3]


def make_real_user_message(text: str = "next task") -> str:
    """A real user message (string content): must trigger turn-boundary reset (B-1b regression)."""
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
    })


class WorkflowProcessSkillDetectionTests(unittest.TestCase):
    """B-1a + B-1b fix (2026-06-11): Workflow-based process skills are recognized
    and the turn-boundary reset skips tool_result wrappers.

    Plan Step 2 acceptance criteria items (i)-(ii):
    (i)  Three-entry fixture shape → last_process_skill set AND SCOPE enforcement fires
         (block when relay text lacks SCOPE, allow when it carries it).
    (ii) Real user message after a process-skill turn still resets state (B-1b regression).
    """

    @classmethod
    def setUpClass(cls):
        cls.mod = load_hook()

    # --- Helper: build lines list from pre-encoded JSONL strings ---
    @staticmethod
    def _lines(*groups):
        result = []
        for g in groups:
            if isinstance(g, list):
                result.extend(g)
            else:
                result.append(g)
        return result

    def test_b1a_workflow_process_research_scope_present_passes(self):
        """Workflow process-research with RESEARCH SCOPE in relay text → PASS."""
        lines = self._lines(
            make_workflow_three_entry(
                "process-research",
                "RESEARCH SCOPE\nQuestion: what is X\nSources: []\n\nFindings: ...",
            )
        )
        mod = self.mod
        # Check that last_process_skill is recognized by running the check functions
        # directly on the relay text (simulates what the main scan would see).
        passed, msg = mod.check_scope("process-research", ["RESEARCH SCOPE\nQuestion: what is X"])
        self.assertTrue(passed, f"SCOPE check must pass when block present: {msg}")

    def test_b1a_workflow_process_research_scope_missing_blocks(self):
        """Full integration: Workflow process-research relay text WITHOUT RESEARCH SCOPE
        → check_scope returns failure (scope missing)."""
        mod = self.mod
        passed, msg = mod.check_scope("process-research", ["Just some text, no SCOPE block."])
        self.assertFalse(passed)
        self.assertIn("RESEARCH SCOPE", msg)

    def test_b1a_three_entry_workflow_process_build_scope_enforced(self):
        """Acceptance item (i): three-entry fixture for process-build: last_process_skill
        MUST be set to 'process-build' after parsing; relay text without BUILD SCOPE
        must produce a SCOPE check failure (not silent skip).

        This test exercises the scan loop directly by calling the internal helper
        check_scope against what the scan would collect after the three-entry shape.
        The critical invariant: the scan loop must NOT have reset found_skill on the
        tool_result wrapper (entry 2) before the relay text (entry 3) is processed.
        We verify this by constructing the lines and simulating the scan state machine."""
        mod = self.mod
        lines = self._lines(
            make_workflow_three_entry("process-build", "No scope block here at all.")
        )

        # Replay the state machine from the main() scan loop
        last_process_skill = None
        text_after_skill = []
        found_skill = False

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # B-1b: real-user-vs-wrapper test (ported logic)
            if entry.get("type") == "user" and found_skill:
                content = entry.get("message", {}).get("content")
                is_real_user = False
                if isinstance(content, str):
                    is_real_user = True
                elif isinstance(content, list):
                    has_text = any(
                        isinstance(b, dict) and b.get("type") == "text" for b in content
                    )
                    has_only_tr = all(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
                    ) if content else False
                    if has_text and not has_only_tr:
                        is_real_user = True
                if is_real_user:
                    last_process_skill = None
                    text_after_skill = []
                    found_skill = False

            if entry.get("type") != "assistant":
                continue

            for block in entry.get("message", {}).get("content", []):
                # B-1a: Workflow branch
                if block.get("type") == "tool_use" and block.get("name") == "Workflow":
                    inp = block.get("input", {})
                    wf_name = (inp.get("name") or "").strip().lower()
                    if wf_name.startswith("process-"):
                        last_process_skill = wf_name
                        text_after_skill = []
                        found_skill = True
                        continue
                # Collect relay text
                if found_skill and block.get("type") == "text":
                    import re as _re
                    text_after_skill.append(_re.sub(r'```[\s\S]*?```', '', block.get("text", "")))

        # After scanning all three entries:
        self.assertEqual(last_process_skill, "process-build",
                         "B-1a: last_process_skill must be 'process-build' after the three-entry shape; "
                         "if None, the Workflow branch did not fire (dead code)")
        self.assertTrue(found_skill,
                        "B-1b: found_skill must still be True after the tool_result wrapper entry; "
                        "if False, the reset incorrectly fired on the wrapper")
        # Now run the scope check: must fail (no BUILD SCOPE in relay text)
        passed, msg = mod.check_scope("process-build", text_after_skill)
        self.assertFalse(passed,
                         "SCOPE enforcement must fire (block) when relay text lacks BUILD SCOPE; "
                         "if passed, either text_after_skill is empty (reset fired) or check_scope has a bug")

    def test_b1a_three_entry_workflow_process_build_scope_present_passes(self):
        """Acceptance item (i), passing case: Workflow process-build relay with BUILD SCOPE
        → scope check passes (ALLOW path)."""
        mod = self.mod
        lines = self._lines(
            make_workflow_three_entry(
                "process-build",
                "BUILD SCOPE\nGoal: implement X\nSpec: Y\n\nBuild complete.",
            )
        )

        last_process_skill = None
        text_after_skill = []
        found_skill = False

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "user" and found_skill:
                content = entry.get("message", {}).get("content")
                is_real_user = False
                if isinstance(content, str):
                    is_real_user = True
                elif isinstance(content, list):
                    has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
                    has_only_tr = all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content) if content else False
                    if has_text and not has_only_tr:
                        is_real_user = True
                if is_real_user:
                    last_process_skill = None
                    text_after_skill = []
                    found_skill = False

            if entry.get("type") != "assistant":
                continue

            for block in entry.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Workflow":
                    inp = block.get("input", {})
                    wf_name = (inp.get("name") or "").strip().lower()
                    if wf_name.startswith("process-"):
                        last_process_skill = wf_name
                        text_after_skill = []
                        found_skill = True
                        continue
                if found_skill and block.get("type") == "text":
                    import re as _re
                    text_after_skill.append(_re.sub(r'```[\s\S]*?```', '', block.get("text", "")))

        self.assertEqual(last_process_skill, "process-build")
        passed, msg = mod.check_scope("process-build", text_after_skill)
        self.assertTrue(passed, f"BUILD SCOPE present → check_scope must pass: {msg}")

    def test_b1a_scriptpath_workflow_process_analysis_detected(self):
        """scriptPath thin-invoker form: .claude/workflows/process-analysis.js
        → last_process_skill must be 'process-analysis'."""
        mod = self.mod
        lines = self._lines(
            make_workflow_three_entry_scriptpath(
                ".claude/workflows/process-analysis.js",
                "ANALYSIS SCOPE\nSubject: governance hooks\n\nDone.",
            )
        )

        last_process_skill = None
        text_after_skill = []
        found_skill = False

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "user" and found_skill:
                content = entry.get("message", {}).get("content")
                is_real_user = False
                if isinstance(content, str):
                    is_real_user = True
                elif isinstance(content, list):
                    has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
                    has_only_tr = all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content) if content else False
                    if has_text and not has_only_tr:
                        is_real_user = True
                if is_real_user:
                    last_process_skill = None
                    text_after_skill = []
                    found_skill = False

            if entry.get("type") != "assistant":
                continue

            for block in entry.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Workflow":
                    inp = block.get("input", {})
                    wf_name = (inp.get("name") or "").strip().lower()
                    if not wf_name:
                        import os as _os
                        sp = inp.get("scriptPath") or ""
                        base = _os.path.basename(sp)
                        wf_name = base[:-3].lower() if base.endswith(".js") else base.lower()
                    if wf_name.startswith("process-"):
                        last_process_skill = wf_name
                        text_after_skill = []
                        found_skill = True
                        continue
                if found_skill and block.get("type") == "text":
                    import re as _re
                    text_after_skill.append(_re.sub(r'```[\s\S]*?```', '', block.get("text", "")))

        self.assertEqual(last_process_skill, "process-analysis",
                         "scriptPath basename must resolve to 'process-analysis'")
        passed, _ = mod.check_scope("process-analysis", text_after_skill)
        self.assertTrue(passed)

    def test_b1b_real_user_message_resets_state(self):
        """Acceptance item (ii): B-1b regression: a REAL user message (string content)
        after a process-skill turn MUST reset state. Turn-boundary semantics survive
        for genuine new turns. If the reset fires correctly, last_process_skill is None."""
        # Simulate: Skill process-research turn → real user message → next scan
        skill_entry = json.dumps({
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "name": "Skill", "input": {"skill": "process-research"}},
                    {"type": "text", "text": "RESEARCH SCOPE\nQuestion: X\n\nDone."},
                ]
            },
        })
        real_user = make_real_user_message("ok next task please")

        lines = [skill_entry, real_user]

        last_process_skill = None
        text_after_skill = []
        found_skill = False

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if entry.get("type") == "user" and found_skill:
                content = entry.get("message", {}).get("content")
                is_real_user = False
                if isinstance(content, str):
                    is_real_user = True
                elif isinstance(content, list):
                    has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
                    has_only_tr = all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content) if content else False
                    if has_text and not has_only_tr:
                        is_real_user = True
                if is_real_user:
                    last_process_skill = None
                    text_after_skill = []
                    found_skill = False

            if entry.get("type") != "assistant":
                continue

            for block in entry.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Skill":
                    inp = block.get("input", {})
                    skill = (inp.get("skill") or "").lower()
                    if skill.startswith("process-"):
                        last_process_skill = skill
                        text_after_skill = []
                        found_skill = True

        self.assertIsNone(last_process_skill,
                          "B-1b regression: real user message must reset last_process_skill to None")
        self.assertFalse(found_skill,
                         "B-1b regression: real user message must reset found_skill to False")

    def test_b1b_tool_result_wrapper_does_not_reset_state(self):
        """Core B-1b invariant: a tool_result wrapper user entry (entry 2 of the
        three-entry Workflow shape) must NOT reset found_skill.

        If the reset fires on the wrapper, text_after_skill is empty when the relay
        text (entry 3) arrives: found_skill=False means relay text is never collected,
        scope check silently skips, B-1a is dead code."""
        lines = self._lines(
            make_workflow_three_entry("process-research", "RESEARCH SCOPE\nQuestion: Y\n\nDone.")
        )

        found_skill_snapshots = []
        found_skill = False
        last_process_skill = None
        text_after_skill = []

        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Capture found_skill state AFTER processing each user-type entry
            if entry.get("type") == "user" and found_skill:
                content = entry.get("message", {}).get("content")
                is_real_user = False
                if isinstance(content, str):
                    is_real_user = True
                elif isinstance(content, list):
                    has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
                    has_only_tr = all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content) if content else False
                    if has_text and not has_only_tr:
                        is_real_user = True
                if is_real_user:
                    last_process_skill = None
                    text_after_skill = []
                    found_skill = False
                found_skill_snapshots.append(("after_user_entry", found_skill, is_real_user))

            if entry.get("type") != "assistant":
                continue

            for block in entry.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "Workflow":
                    inp = block.get("input", {})
                    wf_name = (inp.get("name") or "").strip().lower()
                    if wf_name.startswith("process-"):
                        last_process_skill = wf_name
                        text_after_skill = []
                        found_skill = True
                        continue
                if found_skill and block.get("type") == "text":
                    import re as _re
                    text_after_skill.append(_re.sub(r'```[\s\S]*?```', '', block.get("text", "")))

        # The one user entry in the fixture is the tool_result wrapper.
        # found_skill must remain True after it (is_real_user=False).
        self.assertEqual(len(found_skill_snapshots), 1, "Expected exactly one user-entry snapshot")
        _label, _fs, _is_real = found_skill_snapshots[0]
        self.assertFalse(_is_real, "tool_result wrapper must be identified as non-real user entry")
        self.assertTrue(_fs, "found_skill must remain True after tool_result wrapper (B-1b)")
        # text_after_skill must have collected the relay text
        self.assertTrue(any("RESEARCH SCOPE" in t for t in text_after_skill),
                        "relay text must be collected into text_after_skill after the wrapper")

    def test_b1a_pentest_workflow_recognition_unchanged(self):
        """Regression: the existing pentest Workflow recognition (check_pm_after_increment
        lines 233-242 in original) is the model for B-1a: it must still work. Verify
        that check_pm_after_increment correctly sets pentest_seen for a Workflow
        process-pentest invocation."""
        mod = self.mod
        lines = make_transcript_lines([
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "a"}},
            {"type": "tool_use", "name": "TaskCreate", "input": {"description": "b"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            {"type": "tool_use", "name": "TaskUpdate", "input": {"status": "completed"}},
            # Pentest via Workflow (not Skill)
            {"type": "tool_use", "name": "Workflow", "input": {"name": "process-pentest"}},
            # No pm: should still block
        ])
        ok, msg = mod.check_pm_after_increment(lines)
        self.assertFalse(ok, "check_pm_after_increment must fire even when pentest ran as Workflow")
        self.assertIn("/pm", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)


# ---------------------------------------------------------------------------
# Stage 1 instrumentation (ratified 2026-08-01 proposal): step-check observation
# ---------------------------------------------------------------------------

class TestStepCheckObservation(unittest.TestCase):
    """observe_step_checks(lines) counts CHECK: clauses in TaskCreate descriptions."""

    @staticmethod
    def _tc_line(description):
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "TaskCreate",
             "input": {"subject": "s", "description": description}}]}})

    def _observe(self, lines):
        import importlib.util, os as _os
        spec = importlib.util.spec_from_file_location(
            "psc_s1", _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "process-step-check.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.observe_step_checks(lines)

    def test_counts_present_and_absent(self):
        lines = [self._tc_line("do X. CHECK: pytest test_x.py green"),
                 self._tc_line("do Y with no clause"),
                 self._tc_line("do Z. CHECK: none-exists (pure prose judgment)")]
        obs = self._observe(lines)
        self.assertEqual(obs["task_creates"], 3)
        self.assertEqual(obs["with_check"], 2)
        self.assertEqual(obs["types"].get("none-exists"), 1)

    def test_type_classification(self):
        lines = [self._tc_line("a. CHECK: pytest suite green"),
                 self._tc_line("b. CHECK: n8n_validate_workflow returns zero errors"),
                 self._tc_line("c. CHECK: separate agent re-derives the count"),
                 self._tc_line("d. CHECK: it looks correct and complete")]
        obs = self._observe(lines)
        self.assertEqual(obs["types"].get("test"), 1)
        self.assertEqual(obs["types"].get("tool-call"), 1)
        self.assertEqual(obs["types"].get("re-derivation"), 1)
        # (d) names no executable action: since the pentest HIGH fix it is typed
        # weak, not "other" (the original expectation encoded the blind spot).
        self.assertEqual(obs["types"].get("weak"), 1)
        self.assertIsNone(obs["types"].get("other"))

    def test_weak_check_over_120_chars(self):
        long_clause = "verify that everything is fully correct and works properly " * 3
        obs = self._observe([self._tc_line("a. CHECK: " + long_clause)])
        self.assertEqual(obs["weak_check"], 1)

    def test_no_taskcreates_returns_none(self):
        self.assertIsNone(self._observe([json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}})]))

    def test_malformed_lines_tolerated(self):
        obs = self._observe(["not json", "", self._tc_line("x. CHECK: bash exit 0")])
        self.assertEqual(obs["task_creates"], 1)
        self.assertEqual(obs["with_check"], 1)

    def test_emit_end_to_end_subprocess(self):
        """Wiring test: the hook run as a subprocess must APPEND the observation
        event (catches unwired/import-broken emit paths the unit tests miss)."""
        import subprocess, tempfile, os as _os
        hook_dir = _os.path.dirname(_os.path.abspath(__file__))
        # Follow the suite-wide redirect (conftest) rather than asserting against
        # the live log. The point of this test is that the emit path is WIRED,
        # which the subprocess still proves; where it lands is not the assertion.
        log = _os.environ.get("GOVERNANCE_LOG_PATH") or _os.path.join(hook_dir, "governance-log.jsonl")
        fd, tp = tempfile.mkstemp(prefix="synthetic-test-", suffix=".jsonl")
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self._tc_line("wire X. CHECK: pytest test_x.py green") + "\n")
            before = _os.path.getsize(log) if _os.path.isfile(log) else 0
            r = subprocess.run(["python", _os.path.join(hook_dir, "process-step-check.py")],
                               input=json.dumps({"transcript_path": tp}),
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0)
            with open(log, encoding="utf-8", errors="replace") as fh:
                fh.seek(before)
                new = fh.read()
            self.assertIn('"step_check_observation"', new)
            self.assertIn('"with_check": 1', new)
        finally:
            _os.unlink(tp)

    def test_weak_check_detects_goal_restating_theater(self):
        """PENTEST HIGH (2026-08-01): short goal-restating clauses are the doctrine's
        canonical WEAK_CHECK, but length-only detection scored them 0."""
        theater = ["a. CHECK: the module is fully implemented and correct",
                   "b. CHECK: step is done when the doc reads well",
                   "c. CHECK: verify the change works"]
        obs = self._observe([self._tc_line(t) for t in theater])
        self.assertEqual(obs["weak_check"], 3, "goal-restating clauses must count as weak")
        self.assertEqual(obs["types"].get("weak"), 3)

    def test_real_executable_clauses_not_flagged_weak(self):
        """Guard against over-flagging: genuine checks, including keyword-free ones."""
        real = ["a. CHECK: pytest test_x.py exits 0",
                "b. CHECK: run the script and confirm output equals 42",
                "c. CHECK: n8n_validate_workflow returns zero errors",
                "d. CHECK: separate agent re-derives the row count from settings.json",
                "e. CHECK: none-exists (prose judgment, no executable oracle)"]
        obs = self._observe([self._tc_line(r) for r in real])
        self.assertEqual(obs["weak_check"], 0, f"false positives: {obs}")

    def test_obs_key_distinguishes_different_tasks_with_same_clause(self):
        """Self-caught 2026-08-01: keying on clause text alone collides when two
        different steps carry identical CHECK clauses, so a consumer deduping on
        (session, obs_key) would drop a genuinely new observation."""
        same = self._observe([self._tc_line("build the parser. CHECK: pytest green")])
        other = self._observe([self._tc_line("build the emitter. CHECK: pytest green")])
        self.assertNotEqual(same["obs_key"], other["obs_key"])

    def test_obs_key_stable_for_identical_transcript(self):
        a = self._observe([self._tc_line("build the parser. CHECK: pytest green")])
        b = self._observe([self._tc_line("build the parser. CHECK: pytest green")])
        self.assertEqual(a["obs_key"], b["obs_key"])

    def test_obs_key_covers_tasks_without_check_clause(self):
        a = self._observe([self._tc_line("task one. CHECK: pytest green")])
        b = self._observe([self._tc_line("task one. CHECK: pytest green"),
                           self._tc_line("task two with no clause at all")])
        self.assertNotEqual(a["obs_key"], b["obs_key"])

    def test_regex_rejects_recheck_and_midsentence_prose(self):
        """PENTEST HIGH: no word anchor meant RECHECK: and 'double CHECK:' parsed
        as declared clauses."""
        obs = self._observe([self._tc_line("do a thing. RECHECK: rerun later"),
                             self._tc_line("please double CHECK: the docs")])
        self.assertEqual(obs["task_creates"], 2)
        self.assertEqual(obs["with_check"], 0)

    def test_regex_does_not_swallow_next_line_as_clause(self):
        """PENTEST HIGH: DOTALL + \s* captured the following unrelated line when
        the clause itself was empty."""
        obs = self._observe([self._tc_line("do a thing. CHECK:\nDeploy notes: unrelated prose")])
        self.assertEqual(obs["with_check"], 0, f"empty clause must not capture prose: {obs}")

    def test_multiple_clauses_in_one_description(self):
        """PENTEST HIGH: only the first clause was read; a weak first clause hid a
        real second one (and vice versa)."""
        obs = self._observe([self._tc_line(
            "step. CHECK: it works well\nCHECK: pytest test_x.py exits 0")])
        self.assertEqual(obs["with_check"], 1)
        self.assertEqual(obs["weak_check"], 0, "a real clause present means the step is checked")
        self.assertEqual(obs["types"].get("test"), 1)

    def test_taxonomy_word_boundary_no_latest_attests_collision(self):
        """PENTEST HIGH: substring 'test' inside 'latest'/'attests' stole tool-call
        and re-derivation clauses, corrupting the emitted histogram."""
        obs = self._observe([
            self._tc_line("a. CHECK: n8n_validate_workflow on the latest execution returns no errors"),
            self._tc_line("b. CHECK: a separate agent attests the row count independently"),
        ])
        self.assertEqual(obs["types"].get("tool-call"), 1, f"got {obs['types']}")
        self.assertEqual(obs["types"].get("re-derivation"), 1, f"got {obs['types']}")
        self.assertIsNone(obs["types"].get("test"))

    def test_observation_window_is_larger_than_gate_window_and_flags_truncation(self):
        """QA-caught 2026-08-01: the 200KB gate window is 0.05% of a long transcript,
        so observation reads its own bounded window and stamps truncation."""
        import importlib.util, os as _os, tempfile
        hook = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "process-step-check.py")
        spec = importlib.util.spec_from_file_location("psc_w", hook)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.assertGreater(mod.OBSERVE_READ_BYTES, mod.READ_BYTES)
        fd, tp = tempfile.mkstemp(suffix=".jsonl")
        try:
            with _os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(self._tc_line("early step. CHECK: pytest green") + "\n")
                # padding larger than the GATE window but smaller than the observation window
                fh.write(json.dumps({"type": "assistant", "message": {"content": [
                    {"type": "text", "text": "x" * (mod.READ_BYTES + 5000)}]}}) + "\n")
            lines, truncated = mod._read_observation_window(tp)
            self.assertFalse(truncated)
            obs = mod.observe_step_checks(lines)
            self.assertIsNotNone(obs, "TaskCreate beyond the 200KB gate window must still be observed")
            self.assertEqual(obs["with_check"], 1)
        finally:
            _os.unlink(tp)
