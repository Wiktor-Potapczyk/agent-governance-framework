"""Cross-hook regression guard: a hook that logs must not discard a real session.

Written 2026-08-01 after measuring the session-field folklore. Seventeen of the
eighteen hooks that derive a session did it from the transcript filename stem
alone and never read `payload["session_id"]`; only session-start-log.py read the
field, which is where `_governance_logger.session_from`'s documented fallback
order came from in the first place.

Why this is a correctness problem and not a tidiness one: `_event_emit` coerces a
falsy session to the literal "unknown", and `is_test_session` MATCHES "unknown".
So a hook that drops a valid session_id does not merely lose a label, it files
its own record as synthetic and every consumer using that filter discards it.
Measured across the 77,534-record governance log at the time of writing: 43,601
records (56%) carried unknown/null, led by reviewer-scope-violation-check at
23,976 and bash-safety-guard at 19,267.

These tests drive each hook as a real subprocess with a payload that carries a
session_id and NO transcript_path, which is the exact shape the old derivation
threw away. Subprocess rather than import because the defect lives in how the
hook reads its own stdin payload, which an in-process call would bypass.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
_SID = "8a2cd9c6-c88e-47f6-8763-3bd98706c6d1"


def _run(hook, payload, extra_env=None):
    """Run a hook as a subprocess with its governance-log writes redirected."""
    tmp = tempfile.mkdtemp()
    log = os.path.join(tmp, "governance-log.jsonl")
    env = dict(os.environ, GOVERNANCE_LOG_PATH=log)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, os.path.join(_HOOK_DIR, hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=_HOOK_DIR,
    )
    records = []
    if os.path.exists(log):
        with open(log, encoding="utf-8") as fh:
            records = [json.loads(line) for line in fh if line.strip()]
    return proc, records


class SessionIdIsPreferredTests(unittest.TestCase):
    """session_id present, transcript_path absent: the record must carry the id."""

    def test_bash_safety_guard_keeps_session_id_without_a_transcript(self):
        _, recs = _run("bash-safety-guard.py", {
            "session_id": _SID,
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /c/Users/exampleuser/Workspace/Projects"},
        })
        self.assertTrue(recs, "the deny path must still emit a record")
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))

    def test_reviewer_scope_check_keeps_session_id_without_a_transcript(self):
        # HOOK_SMOKE_TEST=1 is required, not optional dressing. This hook and
        # transition-gate-check embed their own smoke-test suite under
        # `if __name__ == "__main__"`, and without the flag a direct subprocess
        # runs THAT suite rather than main(). The suite invokes the hook as its
        # own children with its own payloads, so the log fills with records that
        # look like this test's output but answer a different question. Reading
        # the failing assertion alone would have blamed the fix.
        _, recs = _run("reviewer-scope-violation-check.py", {
            "session_id": _SID,
            "agent_type": "adversarial-reviewer",
            "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(_HOOK_DIR, "bash-safety-guard.py")},
        }, extra_env={"HOOK_SMOKE_TEST": "1"})
        self.assertTrue(recs, "the scope-violation path must still emit a record")
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))

    def test_reviewer_scope_check_still_denies_the_out_of_scope_edit(self):
        proc, _ = _run("reviewer-scope-violation-check.py", {
            "session_id": _SID,
            "agent_type": "adversarial-reviewer",
            "tool_name": "Edit",
            "tool_input": {"file_path": os.path.join(_HOOK_DIR, "bash-safety-guard.py")},
        }, extra_env={"HOOK_SMOKE_TEST": "1"})
        self.assertIn("permissionDecision", proc.stdout)


class SweptHooksKeepSessionIdTests(unittest.TestCase):
    """The 2026-08-01 sweep across the remaining hooks, for the ones a payload
    can actually reach. Hooks whose log branch needs a real transcript to parse
    are covered by their own suites instead; they always receive a transcript in
    production, which is why they were never a large share of the unattributed
    records in the first place.
    """

    _VAULT = "C:/Users/exampleuser/Workspace"

    def test_mcp_irreversible_guard_keeps_session_id(self):
        _, recs = _run("mcp-irreversible-guard.py", {
            "session_id": _SID,
            "tool_name": "mcp__n8n-mcp__n8n_delete_workflow",
            "tool_input": {"id": "x"},
        })
        self.assertTrue(recs)
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))

    def test_mcp_irreversible_guard_still_denies(self):
        # Gate-1 surface. A session-attribution edit that softened this would be
        # far worse than the defect it fixes, so the verdict is asserted, not
        # inferred from the log record's existence.
        proc, _ = _run("mcp-irreversible-guard.py", {
            "session_id": _SID,
            "tool_name": "mcp__n8n-mcp__n8n_delete_workflow",
            "tool_input": {"id": "x"},
        })
        self.assertIn("deny", proc.stdout)

    def test_agent_dispatch_check_keeps_session_id(self):
        _, recs = _run("agent-dispatch-check.py", {
            "session_id": _SID,
            "tool_name": "Task",
            "tool_input": {"subagent_type": "general-purpose",
                           "prompt": "design an n8n workflow"},
        })
        self.assertTrue(recs)
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))

    def test_subagent_quality_check_keeps_session_id(self):
        # Regression guard for the one site the bulk sweep could not fix on its
        # own: the assignment sat inside an `if transcript_path:` guard, so
        # replacing the expression left it unreachable for exactly this payload.
        _, recs = _run("subagent-quality-check.py", {
            "session_id": _SID,
            "agent_type": "general-purpose",
            "tool_name": "Task",
        })
        self.assertTrue(recs)
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))

    def test_subagent_quality_check_falls_back_and_degrades_honestly(self):
        _, recs = _run("subagent-quality-check.py", {
            "transcript_path": "C:/x/%s.jsonl" % _SID,
            "agent_type": "general-purpose", "tool_name": "Task",
        })
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))
        _, recs2 = _run("subagent-quality-check.py", {
            "agent_type": "general-purpose", "tool_name": "Task",
        })
        self.assertEqual([r.get("session") for r in recs2], ["unknown"] * len(recs2))


class GovernanceLogWriterConvergenceTests(unittest.TestCase):
    """C7 writer decision (a): governance-log.py migrates onto _event_emit.

    The audit filed the migration as a cost, on the grounds that it widens an
    `except OSError` to a bare Exception and starts swallowing serialization
    failures that currently propagate. Reading the code inverts that: json.dumps
    sits INSIDE the try, so a serialization failure today does not surface as a
    clean diagnostic, it escapes the narrow clause and crashes the Stop hook,
    which crashes the turn. The existing comment ("Don't crash on write failure")
    states the intent the narrow clause fails to implement.

    This hook returns early when transcript_path is missing, so it always has a
    transcript and the session_id-versus-stem question is moot for it. What the
    migration buys is the `environment` field, one redirectable write path, and
    the never-crash guarantee every other writer already has.
    """

    def _transcript(self, tmpdir):
        path = os.path.join(tmpdir, "%s.jsonl" % _SID)
        turn = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text":
                "IMPLIES: a probe turn\n"
                "TASK TYPE: Build\n"
                "DOMAIN: vault hooks\n"
                "MUST DISPATCH: process-qa, pm\n"}]},
        }
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(turn) + "\n")
        return path

    def test_turn_summary_carries_the_environment_field(self):
        tmp = tempfile.mkdtemp()
        _, recs = _run("governance-log.py", {
            "session_id": _SID,
            "transcript_path": self._transcript(tmp),
        })
        self.assertTrue(recs, "a classified turn must produce a turn_summary")
        rec = recs[0]
        self.assertEqual(rec["event"], "turn_summary")
        self.assertEqual(rec["hook"], "governance-log")
        self.assertIn("environment", rec)

    def test_turn_summary_keeps_its_payload_fields_and_real_session(self):
        tmp = tempfile.mkdtemp()
        _, recs = _run("governance-log.py", {
            "session_id": _SID,
            "transcript_path": self._transcript(tmp),
        })
        rec = recs[0]
        self.assertEqual(rec["session"], _SID)
        self.assertEqual(rec["type"], "Build")
        # The fields the dashboards join on must survive the migration.
        for field in ("schema", "domain", "must_dispatch", "agents", "skills",
                      "agent_count", "skill_count", "wiki_queried",
                      "memory_searched_raw", "memory_forgot_qmd"):
            self.assertIn(field, rec, "migration dropped %r" % field)

    def test_an_unwritable_destination_does_not_crash_the_stop_hook(self):
        # The point of the widened catch. A crashed Stop hook crashes the turn;
        # a lost log line does not.
        tmp = tempfile.mkdtemp()
        transcript = self._transcript(tmp)
        env = dict(os.environ,
                   GOVERNANCE_LOG_PATH=os.path.join(tmp, "no-such-dir", "g.jsonl"))
        proc = subprocess.run(
            [sys.executable, os.path.join(_HOOK_DIR, "governance-log.py")],
            input=json.dumps({"session_id": _SID, "transcript_path": transcript}),
            capture_output=True, text=True, env=env, cwd=_HOOK_DIR,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])


class NoHookDerivesSessionFromTheTranscriptStemAloneTests(unittest.TestCase):
    """Structural guard, deliberately NOT wired into a blocking gate.

    Adding a fourth check to the C5 hook-write gate would change enforcement
    semantics, which the loop autonomy boundary reserves for the owner. This is
    the same property as a test instead: it fails loudly in the suite when a new
    hook reintroduces the pattern, and blocks nothing at write time.

    session-start-log.py is the reference implementation: it read session_id
    first when every other hook did not, and session_from's fallback order was
    taken from it. It is the only exemption. governance-log.py was exempt while
    its migration was pending and lost the exemption when 0ea3156 landed; a
    stale exemption is a hole in this check, so it is removed rather than kept
    for tidiness.
    """

    _EXEMPT = {"session-start-log.py"}

    def test_no_hook_reintroduces_the_transcript_only_derivation(self):
        import glob
        offenders = []
        for path in glob.glob(os.path.join(_HOOK_DIR, "*.py")):
            name = os.path.basename(path)
            if name.startswith("test_") or name in self._EXEMPT:
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                src = fh.read()
            if "splitext(os.path.basename(transcript_path))" in src:
                offenders.append(name)
        self.assertEqual(
            offenders, [],
            "these hooks derive a session from the transcript stem alone and will "
            "discard a real session_id; use _governance_logger.session_from",
        )


class TranscriptFallbackStillWorksTests(unittest.TestCase):
    """The stem fallback is the behaviour that exists today; it must survive."""

    def test_bash_safety_guard_falls_back_to_the_transcript_stem(self):
        _, recs = _run("bash-safety-guard.py", {
            "transcript_path": "C:/x/projects/vault/%s.jsonl" % _SID,
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /c/Users/exampleuser/Workspace/Projects"},
        })
        self.assertTrue(recs)
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))

    def test_session_id_wins_when_both_are_present(self):
        other = "11111111-2222-3333-4444-555555555555"
        _, recs = _run("bash-safety-guard.py", {
            "session_id": _SID,
            "transcript_path": "C:/x/%s.jsonl" % other,
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /c/Users/exampleuser/Workspace/Projects"},
        })
        self.assertTrue(recs)
        self.assertEqual([r.get("session") for r in recs], [_SID] * len(recs))


class AbsentIdentityIsUnchangedTests(unittest.TestCase):
    """No identity at all must still produce a record, exactly as before.

    session_from returns None where the old bespoke code returned "unknown", and
    emit_event coerces both to "unknown", so this path is non-regressive by
    construction. Pinned anyway: it is the half of the change most likely to be
    broken silently by a later refactor of the helper's fallback order.
    """

    def test_no_identity_still_emits_with_the_unknown_placeholder(self):
        _, recs = _run("bash-safety-guard.py", {
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /c/Users/exampleuser/Workspace/Projects"},
        })
        self.assertTrue(recs, "an unidentifiable turn must still be logged")
        self.assertEqual([r.get("session") for r in recs], ["unknown"] * len(recs))


class DenyBehaviourIsUnchangedTests(unittest.TestCase):
    """The guard's actual job must be byte-identical across this change.

    A session-attribution fix that quietly altered a Gate-1 verdict would be far
    worse than the defect it fixes, so the deny decision is asserted here rather
    than assumed from the log record's existence.
    """

    def test_the_irreversible_command_is_still_denied(self):
        proc, _ = _run("bash-safety-guard.py", {
            "session_id": _SID,
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /c/Users/exampleuser/Workspace/Projects"},
        })
        self.assertIn("deny", proc.stdout)

    def test_a_harmless_command_is_not_denied(self):
        proc, _ = _run("bash-safety-guard.py", {
            "session_id": _SID,
            "tool_name": "Bash",
            "tool_input": {"command": "git status --porcelain"},
        })
        self.assertNotIn('"permissionDecision": "deny"', proc.stdout)


if __name__ == "__main__":
    unittest.main()
