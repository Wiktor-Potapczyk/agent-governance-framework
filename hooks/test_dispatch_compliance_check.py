"""Boundary-test suite for dispatch-compliance-check (improvement-loop sprint 5).

Priority-1 hook in the enforcement boundary-test harness
([[2026-06-02-enforcement-boundary-test-design]]). 271 block events in
governance-log, ZERO FP-guard tests before this file.

Structure follows the harness schema:
- DispatchComplianceTPTests: positive cases (detection SHOULD fire / catch)
- DispatchComplianceBoundaryTests: FP-guards (adjacent-safe, must NOT block)

Each FP-guard method docstring names its boundary_axis (the ONE dimension that
distinguishes the safe case from the target) per the design. `adjacent_to` notes
which TP case it guards.

Run: python .claude/hooks/test_dispatch_compliance_check.py
"""
import os
import sys
import tempfile
import unittest

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOK_DIR not in sys.path:
    sys.path.insert(0, _HOOK_DIR)

from _dispatch_compliance_logic import (  # noqa: E402
    compute_missing,
    extract_dispatch_names,
    find_must_dispatch_raw,
    find_task_type,
    is_trackable_process_skill,
    scan_assistant_text_block,
    strip_fences,
    SKILL_AGENT_ALIASES,
)


# --------------------------------------------------------------------------
# Positive (TP) cases: the detection SHOULD catch the target
# --------------------------------------------------------------------------
class DispatchComplianceTPTests(unittest.TestCase):
    def test_tp_extract_known_names(self):
        """TP-DC-01: a real MUST DISPATCH line yields its declared known names."""
        names = extract_dispatch_names("process-qa, pm, architect-reviewer")
        self.assertEqual(names, ["process-qa", "pm", "architect-reviewer"])

    def test_tp_missing_is_detected(self):
        """TP-DC-02: a declared item never dispatched (no alias) is reported missing."""
        missing = compute_missing(["process-qa", "pm"], {"process-qa"})
        self.assertEqual(missing, ["pm"])

    def test_tp_task_type_parsed(self):
        """TP-DC-03: TASK TYPE token is parsed lowercase from a classification block."""
        self.assertEqual(find_task_type("TASK TYPE: Planning"), "planning")

    def test_tp_classification_block_sets_contract(self):
        """TP-DC-04: a classification block with MUST DISPATCH sets found_contract."""
        state = {"must_dispatch": [], "dispatched": set(),
                 "found_contract": False, "task_type": ""}
        text = "TASK TYPE: Analysis\nMUST DISPATCH: process-qa, pm"
        new = scan_assistant_text_block(text, state)
        self.assertTrue(new["found_contract"])
        self.assertEqual(new["task_type"], "analysis")
        self.assertIn("process-qa", new["must_dispatch"])


# --------------------------------------------------------------------------
# Negative / boundary (FP-guard) cases: adjacent-safe, must NOT block
# --------------------------------------------------------------------------
class DispatchComplianceBoundaryTests(unittest.TestCase):

    def test_fp_alias_satisfies_skill_for_agent_silent(self):
        """FP-DC-01 boundary_axis: 'declared short-name vs dispatched full agent (alias)'.
        adjacent_to TP-DC-02. Declaring 'pm' and dispatching the agent 'pm-orchestrator'
        must be SATISFIED (the documented Skill-vs-Agent boundary), not reported missing."""
        self.assertEqual(compute_missing(["pm"], {"pm-orchestrator"}), [])
        self.assertEqual(compute_missing(["architect-review"], {"architect-reviewer"}), [])

    def test_fp_process_skill_alias_members_satisfy_silent(self):
        """FP-DC-02 boundary_axis: 'process-skill declared vs its alias members dispatched'.
        Declaring 'process-planning' is satisfied when its alias members
        (implementation-plan / adversarial-reviewer) were dispatched, even if the
        literal token 'process-planning' is not in the dispatched set."""
        self.assertEqual(
            compute_missing(["process-planning"], {"implementation-plan", "adversarial-reviewer"}),
            [],
        )

    def test_fp_fenced_example_not_a_real_contract_silent(self):
        """FP-DC-03 boundary_axis: 'MUST DISPATCH inside a fenced code example vs a live field'.
        adjacent_to TP-DC-04. A MUST DISPATCH line that appears only inside a ``` fenced
        block (docs/examples: e.g. quoting the classifier template) must be stripped
        before detection, so it does not create a phantom contract."""
        text = (
            "Here is the classifier template:\n"
            "```\nTASK TYPE: Build\nMUST DISPATCH: process-qa, pm\n```\n"
            "But this turn is just conversation."
        )
        stripped = strip_fences(text)
        self.assertEqual(find_must_dispatch_raw(stripped), "")
        self.assertEqual(find_task_type(stripped), "")

    def test_fp_trailing_reasoning_text_not_a_name_silent(self):
        """FP-DC-04 boundary_axis: 'known agent name vs trailing reasoning prose'.
        adjacent_to TP-DC-01. extract_dispatch_names must keep only KNOWN names and
        discard trailing justification prose, so a reasoning tail does not become a
        phantom 'missing' dispatch that blocks."""
        names = extract_dispatch_names(
            "process-qa, pm because this is a planning task that needs oversight"
        )
        self.assertEqual(names, ["process-qa", "pm"])
        # The reasoning words must NOT appear as declared names
        self.assertNotIn("because", names)
        self.assertNotIn("planning", names)

    def test_fp_none_dispatch_is_empty_silent(self):
        """FP-DC-05 boundary_axis: 'literal none/n-a vs a real declared list'.
        'none' (valid for Quick) must extract to an EMPTY list, not be treated as a
        name to dispatch: otherwise every Quick task would block."""
        self.assertEqual(extract_dispatch_names("none"), [])
        self.assertEqual(extract_dispatch_names("N/A"), [])
        self.assertEqual(extract_dispatch_names("none: Quick task"), [])

    def test_fp_quick_task_no_contract_silent(self):
        """FP-DC-06 boundary_axis: 'Quick task (no MUST DISPATCH field) vs non-Quick'.
        adjacent_to TP-DC-04. A Quick classification with no MUST DISPATCH field must
        leave found_contract False, so the wrapper returns without ever reaching the
        block path (Quick legitimately has no dispatch)."""
        state = {"must_dispatch": [], "dispatched": set(),
                 "found_contract": False, "task_type": ""}
        text = "IMPLIES: trivial rename\nTASK TYPE: Quick\nJUSTIFICATION: one-field edit"
        new = scan_assistant_text_block(text, state)
        self.assertEqual(new["task_type"], "quick")
        self.assertFalse(new["found_contract"])  # no contract → wrapper returns, no block

    def test_fp_agent_named_in_prose_not_dispatched_against_silent(self):
        """FP-DC-07 boundary_axis: 'agent named in explanatory prose vs in MUST DISPATCH'.
        An agent name mentioned in ordinary prose (e.g. explaining why NOT to use it) is
        not inside a MUST DISPATCH field, so it never enters must_dispatch and cannot
        produce a missing-dispatch block."""
        state = {"must_dispatch": [], "dispatched": set(),
                 "found_contract": False, "task_type": ""}
        text = "I considered dispatching debugger here but the bug is already understood."
        new = scan_assistant_text_block(text, state)
        # No TASK TYPE token → not a classification block → state unchanged
        self.assertFalse(new["found_contract"])
        self.assertEqual(new["must_dispatch"], [])

    def test_fp_terminal_skill_not_trackable_silent(self):
        """FP-DC-08 boundary_axis: 'terminal skill (process-qa) vs trackable process-* skill'.
        process-qa / process-pentest are terminal and must NOT register as the
        'recent process skill' that triggers the H11 sidecar-fallback contract: else a
        QA-only turn would inherit a phantom mandatory-dispatch contract and block."""
        self.assertFalse(is_trackable_process_skill("process-qa"))
        self.assertFalse(is_trackable_process_skill("process-pentest"))
        self.assertTrue(is_trackable_process_skill("process-planning"))
        self.assertTrue(is_trackable_process_skill("task-classifier"))


# --------------------------------------------------------------------------
# Workflow tool_use cases (adopted 2026-06-11)
# --------------------------------------------------------------------------
class DispatchComplianceWorkflowTests(unittest.TestCase):

    def test_workflow_name_field_satisfies_process_planning(self):
        """A Workflow tool_use with name='process-planning' satisfies a MUST DISPATCH
        declaration of process-planning (direct name match, no alias needed)."""
        # Simulate what dispatch-compliance-check.py does in the tool_use branch:
        # extract dispatched_name from {"name": "process-planning"}
        inp = {"name": "process-planning"}
        dispatched_name = (inp.get("name") or "").lower()
        self.assertEqual(dispatched_name, "process-planning")
        # Alias-aware missing check: process-planning declared, process-planning dispatched
        missing = compute_missing(["process-planning"], {dispatched_name}, SKILL_AGENT_ALIASES)
        self.assertEqual(missing, [], "Workflow name='process-planning' must satisfy process-planning declaration")

    def test_workflow_scriptpath_fallback_satisfies_process_planning(self):
        """A Workflow tool_use with no 'name' but scriptPath='.claude/workflows/process-planning.js'
        must resolve to 'process-planning' via basename-strip and satisfy the declaration."""
        import os
        inp = {"scriptPath": ".claude/workflows/process-planning.js"}
        dispatched_name = (inp.get("name") or "").lower()
        if not dispatched_name:
            sp = inp.get("scriptPath") or ""
            base = os.path.basename(sp)
            dispatched_name = base[:-3].lower() if base.endswith(".js") else base.lower()
        self.assertEqual(dispatched_name, "process-planning")
        missing = compute_missing(["process-planning"], {dispatched_name}, SKILL_AGENT_ALIASES)
        self.assertEqual(missing, [], "Workflow scriptPath fallback must satisfy process-planning declaration")

    def test_workflow_scriptpath_fallback_satisfies_process_pentest(self):
        """Same scriptPath fallback logic works for process-pentest.js."""
        import os
        inp = {"scriptPath": ".claude/workflows/process-pentest.js"}
        dispatched_name = (inp.get("name") or "").lower()
        if not dispatched_name:
            sp = inp.get("scriptPath") or ""
            base = os.path.basename(sp)
            dispatched_name = base[:-3].lower() if base.endswith(".js") else base.lower()
        self.assertEqual(dispatched_name, "process-pentest")
        missing = compute_missing(["process-pentest"], {dispatched_name}, SKILL_AGENT_ALIASES)
        self.assertEqual(missing, [], "Workflow scriptPath fallback must satisfy process-pentest declaration")

    def test_workflow_name_field_does_not_satisfy_unrelated_declaration(self):
        """A Workflow name='process-planning' does NOT satisfy a MUST DISPATCH for
        'process-pentest' (no cross-alias between the two)."""
        inp = {"name": "process-planning"}
        dispatched_name = (inp.get("name") or "").lower()
        missing = compute_missing(["process-pentest"], {dispatched_name}, SKILL_AGENT_ALIASES)
        self.assertEqual(missing, ["process-pentest"])


# --------------------------------------------------------------------------
# GAP-4 dual-emit schema fields (2026-07-10): wrapper emit path
# --------------------------------------------------------------------------
class DualEmitSchemaFieldTests(unittest.TestCase):
    """Every governance-log entry the wrapper emits must carry the NEW fields
    (schema_version / correlation_id / retirement_date) alongside the UNTOUCHED
    legacy `schema: 2` int. Tested directly against stamp_and_append with a temp
    log path: no subprocess run, so the live governance-log stays clean."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dispatch_compliance_check_wrapper",
            os.path.join(_HOOK_DIR, "dispatch-compliance-check.py"),
        )
        cls.wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.wrapper)

    def _emit(self, tmp_log, correlation_id, event="pass"):
        self.wrapper.stamp_and_append({
            "ts": "2026-07-10 12:00:00",
            "event": event,
            "hook": "dispatch-compliance",
            "session": "test-session",
            "schema": 2,
        }, tmp_log, correlation_id)

    def test_dual_emit_fields_present_and_valid(self):
        import json as _json
        import tempfile
        import uuid as _uuid
        with tempfile.TemporaryDirectory() as td:
            tmp_log = os.path.join(td, "governance-log.jsonl")
            cid = str(_uuid.uuid4())
            self._emit(tmp_log, cid)
            with open(tmp_log, encoding="utf-8") as f:
                entry = _json.loads(f.readline())
            # New fields present and well-formed
            self.assertTrue(entry.get("schema_version"))
            _uuid.UUID(entry["correlation_id"])  # raises if not a UUID
            self.assertRegex(entry["retirement_date"], r"^\d{4}-\d{2}-\d{2}$")
            # Legacy field UNTOUCHED: dual-emit, nothing renamed or removed
            self.assertEqual(entry.get("schema"), 2)

    def test_same_invocation_entries_share_correlation_id(self):
        import json as _json
        import tempfile
        import uuid as _uuid
        with tempfile.TemporaryDirectory() as td:
            tmp_log = os.path.join(td, "governance-log.jsonl")
            cid = str(_uuid.uuid4())
            self._emit(tmp_log, cid, event="block")
            self._emit(tmp_log, cid, event="warning")
            with open(tmp_log, encoding="utf-8") as f:
                entries = [_json.loads(line) for line in f if line.strip()]
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["correlation_id"], entries[1]["correlation_id"])
            self.assertEqual(entries[0]["correlation_id"], cid)


class WrapperSessionWiringTests(unittest.TestCase):
    """Defect 2 (2026-08-07): the wrapper's entry-point log_fire() call fired
    before session was ever wired in, always logging session=None even
    though `payload` (with session_id) was already in scope. Reproduces the
    broken shape first (a synthetic Stop-hook invocation with a populated
    session_id and no transcript, isolated via HOOK_ACTIVITY_LOG_PATH so it
    cannot pollute the live log), then asserts session populates."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dispatch_compliance_check_wrapper_sessiontest",
            os.path.join(_HOOK_DIR, "dispatch-compliance-check.py"),
        )
        cls.wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.wrapper)

    def test_session_populates_from_payload(self):
        import io
        import json as _json
        import tempfile
        from contextlib import redirect_stdout
        from unittest import mock

        with tempfile.TemporaryDirectory() as td:
            activity_log = os.path.join(td, "hook-activity.jsonl")
            payload = {
                "session_id": "test-dispatchcompliance-1",
                "transcript_path": os.path.join(td, "no-such-transcript.jsonl"),
            }
            captured = io.StringIO()
            with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": activity_log}), \
                 mock.patch.object(sys, "stdin", io.StringIO(_json.dumps(payload))), \
                 redirect_stdout(captured):
                self.wrapper.main()
            self.assertTrue(os.path.exists(activity_log))
            with open(activity_log, encoding="utf-8") as f:
                records = [_json.loads(l) for l in f if l.strip()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["hook"], "dispatch-compliance-check")
        self.assertEqual(records[0]["session"], "test-dispatchcompliance-1")


class PluginDispatchNameTests(unittest.TestCase):
    """Defect 5 (2026-08-07): KNOWN_DISPATCH_NAMES did not know any plugin
    agent name, making plugin dispatches invisible to compliance parsing.
    Reproduces the broken shape first (a plain plugin agent name that used to
    have no membership), then asserts recognition, including the
    plugin-namespaced form named in the acceptance instrument."""

    def test_plain_plugin_agent_name_recognized(self):
        from _dispatch_compliance_logic import KNOWN_DISPATCH_NAMES
        self.assertIn("silent-failure-hunter", KNOWN_DISPATCH_NAMES)

    def test_synthetic_dispatch_record_naming_plugin_agent_recognized(self):
        self.assertEqual(
            extract_dispatch_names("pr-review-toolkit:silent-failure-hunter"),
            ["silent-failure-hunter"],
        )

    def test_unknown_namespace_still_rejected(self):
        self.assertEqual(
            extract_dispatch_names("some-plugin:totally-made-up-agent"),
            [],
        )


class PrunedGenericWordTests(unittest.TestCase):
    """Defect 5 post-review, silent-failure lens (2026-08-07): the 54-name
    import included bare or near-bare common-English compounds that
    extract_dispatch_names could match inside ordinary prose, letting a word
    like "analyzer" become a phantom DECLARED item unrelated to any real
    dispatch. Pruned: analyzer, comparator, compliance_agent, formatter_agent,
    grader, intake_agent, monitoring_agent. These tests assert the prune
    actually took (absent from the vocabulary, unmatched by extraction)."""

    PRUNED = (
        "analyzer", "comparator", "compliance_agent",
        "formatter_agent", "grader", "intake_agent", "monitoring_agent",
    )

    def test_pruned_words_absent_from_vocabulary(self):
        from _dispatch_compliance_logic import KNOWN_DISPATCH_NAMES
        for word in self.PRUNED:
            self.assertNotIn(word, KNOWN_DISPATCH_NAMES, f"{word!r} should have been pruned")

    def test_pruned_word_in_ordinary_prose_not_extracted(self):
        # "the analyzer showed clean results" is a plausible sentence a model
        # might write; must not surface "analyzer" as a declared name.
        names = extract_dispatch_names("the analyzer showed clean results")
        self.assertEqual(names, [])
        self.assertNotIn("analyzer", names)

    def test_real_declaration_survives_pruned_word_in_trailing_prose(self):
        # A real declared item followed by a comma-led sentence that happens
        # to start with a pruned word must keep the real item and drop the
        # pruned one, not silently inject it as a second declared name.
        names = extract_dispatch_names(
            "silent-failure-hunter, analyzer showed clean output on the prior pass"
        )
        self.assertEqual(names, ["silent-failure-hunter"])
        self.assertNotIn("analyzer", names)


class DispatchNormalizationTests(unittest.TestCase):
    """Defect 5 follow-up (2026-08-07): normalize_dispatched_name reduces a
    plugin-namespaced tool_use dispatch to the same bare suffix
    extract_dispatch_names already reduces a namespaced DECLARATION to."""

    def test_namespaced_name_reduced_to_suffix(self):
        from _dispatch_compliance_logic import normalize_dispatched_name
        self.assertEqual(
            normalize_dispatched_name("pr-review-toolkit:silent-failure-hunter"),
            "silent-failure-hunter",
        )

    def test_bare_name_unchanged(self):
        from _dispatch_compliance_logic import normalize_dispatched_name
        self.assertEqual(normalize_dispatched_name("silent-failure-hunter"), "silent-failure-hunter")

    def test_empty_string_unchanged(self):
        from _dispatch_compliance_logic import normalize_dispatched_name
        self.assertEqual(normalize_dispatched_name(""), "")


# --------------------------------------------------------------------------
# End-to-end decision tests (defect 5 post-review, architect BLOCKING
# finding 2026-08-07): the vocabulary change feeds dispatch-compliance-check's
# Stop-hook BLOCK/PASS decision, not just telemetry. These run main() through
# a synthetic transcript file and inspect the actual stdout decision, rather
# than testing extract_dispatch_names / compute_missing in isolation.
# --------------------------------------------------------------------------
class PluginDispatchEndToEndTests(unittest.TestCase):
    """Builds a temp transcript (one assistant turn per test) and runs the
    wrapper's main() against it, asserting the stdout decision. governance-log
    writes are isolated to a temp dir (wrapper._HOOK_DIR patched) and
    hook-activity writes to a temp file (HOOK_ACTIVITY_LOG_PATH env override,
    same mechanism WrapperSessionWiringTests uses) so no live log is touched."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "dispatch_compliance_check_e2e",
            os.path.join(_HOOK_DIR, "dispatch-compliance-check.py"),
        )
        cls.wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.wrapper)

    @staticmethod
    def _assistant_line(blocks):
        import json as _json
        return _json.dumps({"type": "assistant", "message": {"content": blocks}})

    @staticmethod
    def _text_block(text):
        return {"type": "text", "text": text}

    @staticmethod
    def _agent_block(subagent_type):
        return {"type": "tool_use", "name": "Agent", "input": {"subagent_type": subagent_type}}

    def _run(self, td, blocks, session_id):
        import io
        import json as _json
        import tempfile as _tempfile
        from contextlib import redirect_stdout
        from unittest import mock

        transcript_path = os.path.join(td, "transcript.jsonl")
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(self._assistant_line(blocks) + "\n")

        activity_log = os.path.join(td, "hook-activity.jsonl")
        payload = _json.dumps({"session_id": session_id, "transcript_path": transcript_path})
        captured = io.StringIO()
        with mock.patch.dict(os.environ, {"HOOK_ACTIVITY_LOG_PATH": activity_log}), \
             mock.patch.object(self.wrapper, "_HOOK_DIR", td), \
             mock.patch.object(sys, "stdin", io.StringIO(payload)), \
             redirect_stdout(captured):
            self.wrapper.main()
        return captured.getvalue()

    def test_namespaced_declared_and_dispatched_passes(self):
        """(i) MUST DISPATCH declares a plugin agent by its namespaced form and
        the transcript shows that exact namespaced Agent dispatch: PASS
        (no block output)."""
        with tempfile.TemporaryDirectory() as td:
            text = "TASK TYPE: Build\nMUST DISPATCH: pr-review-toolkit:silent-failure-hunter"
            out = self._run(
                td,
                [self._text_block(text), self._agent_block("pr-review-toolkit:silent-failure-hunter")],
                "e2e-pass-namespaced",
            )
        self.assertEqual(out, "")

    def test_declared_but_never_dispatched_blocks(self):
        """(ii) MUST DISPATCH declares a plugin agent and no matching dispatch
        occurs anywhere in the transcript: BLOCK."""
        with tempfile.TemporaryDirectory() as td:
            text = "TASK TYPE: Build\nMUST DISPATCH: pr-review-toolkit:silent-failure-hunter"
            out = self._run(td, [self._text_block(text)], "e2e-block-missing")
        self.assertIn('"decision": "block"', out)
        self.assertIn("silent-failure-hunter", out)

    def test_pruned_word_in_prose_does_not_satisfy_declared_obligation(self):
        """(iii) A real declared item plus trailing prose containing a pruned
        generic word ("analyzer") must still BLOCK on the real missing item.
        The prose mention is neither recognized as a declared name nor as a
        dispatch, so it cannot manufacture a false PASS."""
        with tempfile.TemporaryDirectory() as td:
            text = (
                "TASK TYPE: Build\nMUST DISPATCH: silent-failure-hunter, "
                "analyzer showed clean output on the prior pass"
            )
            out = self._run(td, [self._text_block(text)], "e2e-block-pruned-prose")
        self.assertIn('"decision": "block"', out)
        self.assertIn("silent-failure-hunter", out)
        self.assertNotIn("analyzer", out)

    def test_short_declared_matches_namespaced_dispatch(self):
        """(iv) Live-probe finding: MUST DISPATCH declares the bare/short form
        ("silent-failure-hunter") but the actual Agent dispatch uses the
        plugin-namespaced runtime name ("pr-review-toolkit:silent-failure-hunter").
        Before the normalize_dispatched_name fix this spuriously BLOCKED (the
        declared side is reduced to the bare suffix by extract_dispatch_names,
        but the dispatched side kept the full namespaced string, so the two
        never compared equal). Chosen fix: make the dispatched side normalize
        to the same bare suffix (smaller than requiring every declaration to
        spell out a plugin namespace the classifier can't reliably know).
        Verified behavior after the fix: PASS."""
        with tempfile.TemporaryDirectory() as td:
            text = "TASK TYPE: Build\nMUST DISPATCH: silent-failure-hunter"
            out = self._run(
                td,
                [self._text_block(text), self._agent_block("pr-review-toolkit:silent-failure-hunter")],
                "e2e-pass-short-declared-namespaced-dispatch",
            )
        self.assertEqual(out, "")


# --- pm trackable + H11 fallback contract-union (2026-08-31) ------------------

def test_pm_is_a_trackable_skill_for_the_h11_fallback():
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from _dispatch_compliance_logic import is_trackable_process_skill
    assert is_trackable_process_skill("pm") is True
    assert is_trackable_process_skill("task-classifier") is True
    assert is_trackable_process_skill("process-qa") is False  # terminal


def _merged():
    import os as _os
    import sys as _sys
    _sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
    from _dispatch_compliance_logic import merged_sidecar_contract
    return merged_sidecar_contract


def test_merged_contract_unions_substantive_skill_with_trailing_pm():
    """A pm dispatch after process-build must ADD pm-orchestrator, not replace
    the build skill's contract (the last-wins overwrite the review flagged)."""
    contracts = {
        "process-build": ["implementation-plan", "architect-reviewer"],
        "pm": ["pm-orchestrator"],
    }
    merged = _merged()(["process-build", "pm"], lambda s: contracts[s])
    assert merged == ["implementation-plan", "architect-reviewer", "pm-orchestrator"]


def test_merged_contract_dedupes_and_survives_single_lookup_failure():
    def lookup(s):
        if s == "broken":
            raise RuntimeError("no sidecar")
        return {"process-qa-like": ["architect-reviewer"],
                "pm": ["pm-orchestrator", "architect-reviewer"]}[s]
    merged = _merged()(["process-qa-like", "broken", "pm"], lookup)
    assert merged == ["architect-reviewer", "pm-orchestrator"]


def test_merged_contract_empty_input_yields_empty():
    assert _merged()([], lambda s: ["x"]) == []


if __name__ == "__main__":
    unittest.main(verbosity=2)
