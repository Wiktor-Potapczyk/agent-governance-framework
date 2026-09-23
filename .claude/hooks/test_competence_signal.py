"""Fixture tests for _competence_signal.py — Step-11 competence gate (Step B3).

All tests run on frozen string fixtures (no live-log dependency). Covers the
fail-open contract (no raise on any malformed input), the synthetic-session
pre-filter, cold-start NO_SIGNAL, the 50-event window boundary, exact score
arithmetic at the 0.8 threshold, and determinism.

Run: python -m pytest .claude/hooks/test_competence_signal.py -q
"""

import importlib.util
import json
import os
import tempfile
import unittest
from unittest import mock

_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_competence_signal.py"
)
_spec = importlib.util.spec_from_file_location("_competence_signal", _MODULE_PATH)
cs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cs)


def _pass(agent, session="real-session-1"):
    return json.dumps({
        "ts": "2026-07-13 12:00:00", "schema": 2, "event": "pass",
        "hook": "subagent-quality-check", "session": session,
        "agent_type": agent, "agent_id": "x", "message_len": 100,
    })


def _block(agent, session="real-session-1"):
    return json.dumps({
        "ts": "2026-07-13 12:00:00", "schema": 2, "event": "block",
        "hook": "subagent-quality-check", "session": session,
        "agent_type": agent, "agent_id": "x", "message_len": 3,
        "check_failed": "check_1_empty_output", "violation_excerpt": "",
        "block_reason": "empty",
    })


def _scope(agent, session="real-session-1"):
    return json.dumps({
        "ts": "2026-07-13 12:00:00", "schema": 2,
        "event": "reviewer_scope_violation",
        "hook": "reviewer-scope-violation-check", "session": session,
        "agent_type": agent, "tool_name": "Edit", "file_path": "/x",
        "block_reason": "scope",
    })


class ParseEventsTests(unittest.TestCase):
    def test_synthetic_session_entries_dropped(self):
        text = "\n".join([
            _pass("a", session="session"),   # synthetic — dropped
            _pass("a", session="real-1"),
            _block("a", session="session"),  # synthetic — dropped
        ])
        events = cs.parse_events(text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["session"], "real-1")

    def test_malformed_lines_skipped_without_raising(self):
        text = "\n".join([
            "not json at all",
            '{"truncated": ',
            '["a", "list", "not", "a", "dict"]',
            '42',
            _pass("a"),
            "",
            "   ",
        ])
        events = cs.parse_events(text)  # must not raise
        self.assertEqual(len(events), 1)

    def test_empty_text_gives_empty_list(self):
        self.assertEqual(cs.parse_events(""), [])


class ScoreAgentTests(unittest.TestCase):
    def _events(self, lines):
        return cs.parse_events("\n".join(lines))

    def test_cold_start_no_signal(self):
        events = self._events([_pass("a")] * 4)  # n=4 < WARMUP_N=5
        result = cs.score_agent(events, "a")
        self.assertEqual(result["verdict"], "NO_SIGNAL")
        self.assertEqual(result["n"], 4)
        self.assertIsNone(result["score"])

    def test_zero_events_no_signal(self):
        result = cs.score_agent([], "a")
        self.assertEqual(result["verdict"], "NO_SIGNAL")
        self.assertEqual(result["n"], 0)

    def test_threshold_boundary_ok(self):
        """4 pass + 1 block = 0.8 -> OK exactly at the threshold."""
        events = self._events([_pass("a")] * 4 + [_block("a")])
        result = cs.score_agent(events, "a")
        self.assertEqual(result["n"], 5)
        self.assertEqual(result["score"], 0.8)
        self.assertEqual(result["verdict"], "OK")

    def test_below_threshold(self):
        """3 pass + 2 block = 0.6 -> BELOW."""
        events = self._events([_pass("a")] * 3 + [_block("a")] * 2)
        result = cs.score_agent(events, "a")
        self.assertEqual(result["score"], 0.6)
        self.assertEqual(result["verdict"], "BELOW")

    def test_scope_violations_count_as_failures(self):
        """3 pass + 1 block + 1 scope = 0.6 -> BELOW."""
        events = self._events([_pass("a")] * 3 + [_block("a")] + [_scope("a")])
        result = cs.score_agent(events, "a")
        self.assertEqual(result["n"], 5)
        self.assertEqual(result["score"], 0.6)
        self.assertEqual(result["verdict"], "BELOW")

    def test_window_boundary_51st_oldest_excluded(self):
        """51-event fixture: oldest is a block; last 50 are all passes.
        Window must exclude the 51st-oldest -> score exactly 1.0."""
        lines = [_block("a")] + [_pass("a")] * 50
        events = self._events(lines)
        result = cs.score_agent(events, "a")
        self.assertEqual(result["n"], 50)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["verdict"], "OK")
        # Inverse control: block inside the window changes the score.
        lines2 = [_pass("a")] + [_block("a")] + [_pass("a")] * 49
        result2 = cs.score_agent(self._events(lines2), "a")
        self.assertEqual(result2["n"], 50)
        self.assertEqual(result2["score"], 49 / 50)

    def test_other_agents_events_ignored(self):
        events = self._events([_pass("a")] * 5 + [_block("b")] * 5)
        result = cs.score_agent(events, "a")
        self.assertEqual(result["n"], 5)
        self.assertEqual(result["score"], 1.0)

    def test_non_completion_events_ignored(self):
        noise = json.dumps({
            "ts": "2026-07-13 12:00:00", "schema": 2,
            "event": "agent_dispatched", "hook": "agent-dispatch-check",
            "session": "real-1", "agent_type": "a",
        })
        events = self._events([noise] * 10 + [_pass("a")] * 5)
        result = cs.score_agent(events, "a")
        self.assertEqual(result["n"], 5)

    def test_determinism_two_runs_equal(self):
        lines = ([_pass("a")] * 30 + [_block("a")] * 7 + [_scope("a")] * 3)
        r1 = cs.score_agent(self._events(lines), "a")
        r2 = cs.score_agent(self._events(lines), "a")
        self.assertEqual(r1, r2)


class ReadLogTailTests(unittest.TestCase):
    def test_missing_path_returns_empty_string(self):
        result = cs.read_log_tail(
            os.path.join(tempfile.gettempdir(), "does-not-exist-step11.jsonl")
        )
        self.assertEqual(result, "")

    def test_tail_bounded_read(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "log.jsonl")
            with open(p, "w", encoding="utf-8") as f:
                f.write("HEAD" + "x" * 100 + "TAIL")
            out = cs.read_log_tail(p, max_bytes=8)
            self.assertEqual(out, "xxxxTAIL")


class GetVerdictTests(unittest.TestCase):
    def test_end_to_end_on_fixture_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "log.jsonl")
            lines = [_pass("a")] * 4 + [_block("a")]
            with open(p, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            result = cs.get_verdict(p, "a")
            self.assertEqual(result["verdict"], "OK")
            self.assertEqual(result["score"], 0.8)

    def test_missing_log_gives_no_signal(self):
        result = cs.get_verdict("/nonexistent/step11.jsonl", "a")
        self.assertEqual(result["verdict"], "NO_SIGNAL")
        self.assertEqual(result["n"], 0)

    def test_injected_exception_returns_safe_object_never_raises(self):
        # The injection point moved when get_verdict stopped calling parse_events
        # (2026-08-01: the byte tail was replaced by a backwards completion read).
        # Both internals are exercised rather than just the one, so the fail-open
        # contract is now pinned more tightly than it was before the change.
        for target in ("iter_completions_backwards", "score_agent"):
            with self.subTest(internal=target):
                with mock.patch.object(cs, target, side_effect=RuntimeError("boom")):
                    result = cs.get_verdict("/any/path.jsonl", "a")
                self.assertEqual(result["verdict"], "NO_SIGNAL")
                self.assertEqual(result["n"], 0)
                self.assertIsNone(result["score"])
                self.assertTrue(result.get("error"))


class WindowIsMeasuredInCompletionsNotBytesTests(unittest.TestCase):
    """The backwards-counter defect, reproduced.

    WINDOW_PER_AGENT is defined in completion EVENTS, but the read that feeds it
    was bounded in BYTES. Completions for one agent are sparse in a stream that
    every hook writes to, so the two disagree the moment traffic grows: the same
    agent's warm-up count was observed going 5, then 3, then 0 with no code
    change. A low n then means "did not see", not "has not warmed up", and the
    counter runs backwards as unrelated records accumulate.

    The gate is ADVISORY (it prints and lets the dispatch proceed), so this is a
    wrong number rather than a wrong block. It is still wrong, and it silently
    erases warm-up history an agent already earned.
    """

    def _log_with_filler(self, path, agent, completions, filler_bytes):
        """Write `completions` for `agent`, then bury them under unrelated traffic."""
        with open(path, "w", encoding="utf-8") as fh:
            for line in completions:
                fh.write(line + "\n")
            written = 0
            i = 0
            while written < filler_bytes:
                line = json.dumps({
                    "ts": "2026-07-13 12:00:00", "schema": 2, "event": "hook_fire",
                    "hook": "prose-slop-check", "session": "real-session-2",
                    "detail": "x" * 200, "seq": i,
                }) + "\n"
                fh.write(line)
                written += len(line)
                i += 1

    def test_completions_are_found_even_when_buried_past_the_byte_window(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "step11.jsonl")
        # 10 clean passes, then 2MB of unrelated traffic on top of them.
        self._log_with_filler(p, "a", [_pass("a")] * 10, 2 * 1024 * 1024)
        result = cs.get_verdict(p, "a")
        self.assertEqual(result["n"], 10,
                         "completions older than the byte window must still count")
        self.assertEqual(result["verdict"], "OK")

    def test_the_count_does_not_regress_as_unrelated_records_accumulate(self):
        # The regression itself: same completions, more noise, same n.
        tmp = tempfile.mkdtemp()
        counts = []
        for filler in (0, 1024 * 1024, 3 * 1024 * 1024):
            p = os.path.join(tmp, "step11-%d.jsonl" % filler)
            self._log_with_filler(p, "a", [_pass("a")] * 8, filler)
            counts.append(cs.get_verdict(p, "a")["n"])
        self.assertEqual(counts, [8, 8, 8],
                         "n fell as unrelated traffic grew: %r" % (counts,))

    def test_the_window_still_caps_at_the_most_recent_events(self):
        # Correctness in the other direction: reading further back must not
        # widen the scoring window beyond WINDOW_PER_AGENT.
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "step11.jsonl")
        # 10 old blocks then 50 recent passes: the blocks fall outside the window.
        self._log_with_filler(p, "a", [_block("a")] * 10 + [_pass("a")] * 50, 0)
        result = cs.get_verdict(p, "a")
        self.assertEqual(result["n"], cs.WINDOW_PER_AGENT)
        self.assertEqual(result["score"], 1.0)

    def test_synthetic_session_prefilter_still_applies_to_the_new_reader(self):
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "step11.jsonl")
        self._log_with_filler(
            p, "a", [_pass("a", session="session")] * 20 + [_pass("a")] * 6, 0)
        result = cs.get_verdict(p, "a")
        self.assertEqual(result["n"], 6, "synthetic-session entries must stay dropped")

    def test_a_line_split_across_the_chunk_boundary_is_not_corrupted(self):
        # Reading backwards in chunks: the first fragment of each chunk is a
        # partial line and must be carried, not parsed. A silent JSONDecodeError
        # here would just drop completions and look like a low count.
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "step11.jsonl")
        self._log_with_filler(p, "a", [_pass("a")] * 40, 300 * 1024)
        result = cs.get_verdict(p, "a")
        self.assertEqual(result["n"], 40)

    def test_missing_and_empty_files_still_fail_open(self):
        self.assertEqual(cs.get_verdict("/nonexistent/x.jsonl", "a")["verdict"],
                         "NO_SIGNAL")
        tmp = tempfile.mkdtemp()
        p = os.path.join(tmp, "empty.jsonl")
        open(p, "w").close()
        self.assertEqual(cs.get_verdict(p, "a")["verdict"], "NO_SIGNAL")


class NoDenyCapabilityTests(unittest.TestCase):
    def test_no_permission_decision_string_in_module(self):
        with open(_MODULE_PATH, "r", encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("permission" + "Decision", src)

    def test_mode_is_advisory_constant(self):
        self.assertEqual(cs.MODE, "ADVISORY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
