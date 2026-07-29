"""Smoke tests for verifier-gate-check.py — Stop hook.

Fires only when `verification-gated-research` skill was invoked in the session.
Blocks completion if no separate verifier Agent was dispatched after the skill.
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

_spec = importlib.util.spec_from_file_location(
    "verifier_gate_check",
    str(Path(__file__).parent / "verifier-gate-check.py"),
)
vgc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vgc)


def _write_transcript(tmp: Path, events: list[dict]) -> str:
    """Write JSONL transcript and return its path."""
    p = tmp / "session.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")
    return str(p)


def _run(payload: dict) -> tuple[int | None, str]:
    captured = io.StringIO()
    rc = None
    with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         mock.patch.object(vgc, "_log", lambda *a, **k: None), \
         redirect_stdout(captured):
        try:
            rc = vgc.main()
        except SystemExit as e:
            rc = e.code
    return rc, captured.getvalue()


def _tool_use(name: str, tool_input: dict) -> dict:
    """Build a transcript line shaped like a Claude Code assistant tool_use event."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": name, "input": tool_input}
            ],
        },
    }


class StopHookActiveGuardTests(unittest.TestCase):
    def test_stop_hook_active_returns_silently(self):
        rc, out = _run({"stop_hook_active": True, "transcript_path": "/x"})
        self.assertEqual(out, "")


class NoTranscriptTests(unittest.TestCase):
    def test_missing_transcript_path_returns_silently(self):
        rc, out = _run({})
        self.assertEqual(out, "")

    def test_nonexistent_transcript_returns_silently(self):
        rc, out = _run({"transcript_path": "/no/such/file.jsonl"})
        self.assertEqual(out, "")


class SkillInvocationDetectionTests(unittest.TestCase):
    def test_no_skill_invocation_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Read", {"file_path": "/x"}),
                _tool_use("Grep", {"pattern": "foo"}),
            ])
            rc, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_other_skill_invocation_passes(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "process-research"}),
            ])
            rc, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class VerifierDispatchTests(unittest.TestCase):
    def test_skill_without_verifier_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "worker bee", "subagent_type": "general-purpose"}),
            ])
            rc, out = _run({"transcript_path": tp})
            self.assertNotEqual(out, "")
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")
            self.assertIn("VERIFIER GATE", result["reason"])

    def test_skill_with_verifier_after_passes(self):
        # Intended-contract update (B4 2026-06-16): the 3-part check reads the verifier
        # PROMPT, so this fixture now carries a distinct re-derivation prompt (previously
        # description-only). This is a contract update, NOT a regression.
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "worker harness", "subagent_type": "general-purpose",
                                    "prompt": "Investigate the backlog items from source materials."}),
                _tool_use("Agent", {"description": "verifier — gate the ledger", "subagent_type": "general-purpose",
                                    "prompt": "Independently verify and re-derive each ledger claim from work/ledger.md."}),
            ])
            rc, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_verifier_before_skill_still_blocks(self):
        # Ordering guard: verifier dispatched BEFORE skill doesn't satisfy the gate.
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Agent", {"description": "verifier — earlier task", "subagent_type": "general-purpose"}),
                _tool_use("Skill", {"skill": "verification-gated-research"}),
            ])
            rc, out = _run({"transcript_path": tp})
            self.assertNotEqual(out, "")
            result = json.loads(out)
            self.assertEqual(result["decision"], "block")

    def test_verifier_match_is_case_insensitive(self):
        # Description normalized via .lower() in source
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "VERIFIER ROUND 1", "subagent_type": "general-purpose",
                                    "prompt": "Re-run the checks and re-derive the result."}),
            ])
            rc, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


class MalformedLinesTests(unittest.TestCase):
    def test_garbage_lines_skipped_gracefully(self):
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "session.jsonl"
            with open(tp, "w", encoding="utf-8") as f:
                f.write("not json at all\n")
                f.write(json.dumps(_tool_use("Skill", {"skill": "verification-gated-research"})) + "\n")
                f.write("{broken\n")
                f.write(json.dumps(_tool_use("Agent", {"description": "verifier — round",
                                                       "prompt": "Re-derive the findings from work/out.md."})) + "\n")
            rc, out = _run({"transcript_path": str(tp)})
            self.assertEqual(out, "")  # malformed lines skipped, valid skill+verifier => pass

    def test_empty_transcript_returns_silently(self):
        with tempfile.TemporaryDirectory() as td:
            tp = Path(td) / "session.jsonl"
            tp.write_text("", encoding="utf-8")
            rc, out = _run({"transcript_path": str(tp)})
            self.assertEqual(out, "")


class VerifierGateBoundaryTests(unittest.TestCase):
    """Named FP-guards (boundary-test harness sprint 9). Each docstring names its
    boundary_axis. The hook is deliberately narrow (fires ONLY when the
    verification-gated-research skill was invoked) — these lock that scoping so it
    never expands into the 'force every research through a verifier' false-positive
    minefield the source warns against."""

    def test_fp_ordinary_research_skill_silent(self):
        """FP-VG-01 boundary_axis: 'verification-gated-research skill vs ordinary process-research'.
        process-research must NOT trigger the verifier gate."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "process-research"}),
                _tool_use("Agent", {"description": "research-analyst pass", "subagent_type": "research-analyst"}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_fp_synthesizer_not_a_verifier_but_no_gate_silent(self):
        """FP-VG-02 boundary_axis: 'synthesizer/report-generator dispatch vs verifier dispatch'.
        A normal research pass that dispatches research-synthesizer (NOT a verifier) must
        not block, because the gate is dormant unless the harness skill was invoked."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "process-research"}),
                _tool_use("Agent", {"description": "synthesize the findings", "subagent_type": "research-synthesizer"}),
                _tool_use("Agent", {"description": "generate the report", "subagent_type": "report-generator"}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_fp_skill_with_verifier_silent(self):
        """FP-VG-03 boundary_axis: 'verifier dispatched after skill vs absent'.
        Intended-contract update (B4 2026-06-16): verifier now carries a distinct
        re-derivation prompt (3-part structural check reads the prompt)."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "worker harness", "subagent_type": "general-purpose",
                                    "prompt": "Investigate the backlog from sources."}),
                _tool_use("Agent", {"description": "verifier — gate the ledger", "subagent_type": "general-purpose",
                                    "prompt": "Independently verify and re-derive each claim from work/ledger.md."}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")

    def test_tp_skill_without_verifier_blocks(self):
        """TP-VG-01: the harness skill invoked with no separate verifier dispatch blocks."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "just a worker", "subagent_type": "general-purpose"}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertIn("VERIFIER GATE", out)


class ThreePartStructuralCheckTests(unittest.TestCase):
    """B4 (2026-06-16): the 3-part structural check defeats relabel-gaming while
    keeping the legitimate same-subagent_type re-deriving verifier legal."""

    def test_tp_relabel_byte_identical_prompt_blocks(self):
        """A 'verifier'-described dispatch whose prompt is byte-identical to a worker
        prompt is a relabel, not a verifier — must BLOCK (part 2 fails)."""
        identical = "Investigate the backlog items from source materials."
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "worker", "subagent_type": "general-purpose",
                                    "prompt": identical}),
                _tool_use("Agent", {"description": "verifier — gate", "subagent_type": "general-purpose",
                                    "prompt": identical}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertIn("VERIFIER GATE", out)

    def test_tp_no_rederivation_keyword_blocks(self):
        """A 'verifier' dispatch whose prompt only re-reads (no re-derivation contract,
        no artifact path) must BLOCK (part 3 fails)."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "worker", "subagent_type": "general-purpose",
                                    "prompt": "Investigate X from sources."}),
                _tool_use("Agent", {"description": "verifier — look again", "subagent_type": "general-purpose",
                                    "prompt": "Please read the work again and confirm it looks fine."}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertIn("VERIFIER GATE", out)

    def test_fp_same_subagent_type_rederiving_verifier_passes(self):
        """A legitimate verifier of the SAME subagent_type as the worker, with a
        distinct re-derivation prompt, must PASS — type-difference is NOT required."""
        with tempfile.TemporaryDirectory() as td:
            tp = _write_transcript(Path(td), [
                _tool_use("Skill", {"skill": "verification-gated-research"}),
                _tool_use("Agent", {"description": "worker", "subagent_type": "technical-researcher",
                                    "prompt": "Investigate X from source materials."}),
                _tool_use("Agent", {"description": "verifier round", "subagent_type": "technical-researcher",
                                    "prompt": "Independently verify and re-derive the findings from work/x-findings.md."}),
            ])
            _, out = _run({"transcript_path": tp})
            self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
