"""
Unit tests for agent-dispatch-check.py: Iteration 1 bug fix (2026-04-10).

Covers:
- SKILL_AGENT_ALIASES mapping: pm → pm-orchestrator, architect-review → architect-reviewer
- Alias expansion: declared skill allows dispatching its agent
- Exact match still works: declaring the agent name directly is allowed
- Unrelated agents still blocked: aliases don't weaken strict checking
- Always-allowed agents bypass the check entirely
- P0 parsing fix (via extract_dispatch_names) still works

Run: python .claude/hooks/test_agent_dispatch_check.py
"""

import importlib.util
import os
import unittest

HOOK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent-dispatch-check.py")
spec = importlib.util.spec_from_file_location("agent_dispatch_check", HOOK_PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

SKILL_AGENT_ALIASES = mod.SKILL_AGENT_ALIASES
ALWAYS_ALLOWED = mod.ALWAYS_ALLOWED
extract_dispatch_names = mod.extract_dispatch_names
KNOWN_DISPATCH_NAMES = mod.KNOWN_DISPATCH_NAMES


def resolve_allowed(must_dispatch):
    """Replicate the main() allowed-set expansion logic for testing."""
    allowed = set(must_dispatch)
    for declared in list(must_dispatch):
        if declared in SKILL_AGENT_ALIASES:
            allowed.update(SKILL_AGENT_ALIASES[declared])
    return allowed


class TestSkillAgentAliases(unittest.TestCase):
    """Bug fix 2026-04-10: declared skill should allow dispatching its agent."""

    def test_pm_alias_to_pm_orchestrator(self):
        """MUST DISPATCH: [pm] → pm-orchestrator must be allowed."""
        allowed = resolve_allowed(["pm"])
        self.assertIn("pm-orchestrator", allowed)
        self.assertIn("pm", allowed)  # original still allowed

    def test_architect_review_alias(self):
        """MUST DISPATCH: [architect-review] → architect-reviewer must be allowed."""
        allowed = resolve_allowed(["architect-review"])
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("architect-review", allowed)

    def test_multi_skill_all_aliased(self):
        """Multiple skills in MUST DISPATCH each expand their aliases."""
        allowed = resolve_allowed(["pm", "architect-review", "process-qa"])
        self.assertIn("pm-orchestrator", allowed)
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("process-qa", allowed)  # no alias, but still present

    def test_process_planning_expands(self):
        """process-planning should allow implementation-plan + adversarial-reviewer."""
        allowed = resolve_allowed(["process-planning"])
        self.assertIn("implementation-plan", allowed)
        self.assertIn("adversarial-reviewer", allowed)

    def test_process_build_expands(self):
        """process-build should allow blueprint-mode + architect-reviewer + implementation-plan."""
        allowed = resolve_allowed(["process-build"])
        self.assertIn("blueprint-mode", allowed)
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("implementation-plan", allowed)

    def test_process_research_expands(self):
        """process-research should allow research-orchestrator + technical-researcher + research-analyst."""
        allowed = resolve_allowed(["process-research"])
        self.assertIn("research-orchestrator", allowed)
        self.assertIn("technical-researcher", allowed)
        self.assertIn("research-analyst", allowed)

    def test_process_analysis_expands(self):
        """process-analysis should allow architect-reviewer + adversarial-reviewer."""
        allowed = resolve_allowed(["process-analysis"])
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("adversarial-reviewer", allowed)

    def test_process_qa_expands_to_debugger(self):
        """process-qa should allow debugger (dispatched on QA failure)."""
        allowed = resolve_allowed(["process-qa"])
        self.assertIn("debugger", allowed)

    def test_process_pentest_expands(self):
        """process-pentest should allow debugger only (skill says 'execute yourself')."""
        allowed = resolve_allowed(["process-pentest"])
        self.assertIn("debugger", allowed)
        self.assertNotIn("architect-reviewer", allowed)  # pentest doesn't delegate reviews

    def test_architect_loop_expands(self):
        """architect-loop should allow architect-reviewer + adversarial-reviewer."""
        allowed = resolve_allowed(["architect-loop"])
        self.assertIn("architect-reviewer", allowed)
        self.assertIn("adversarial-reviewer", allowed)

    def test_process_research_includes_core_researchers(self):
        """process-research dispatches research-orchestrator and direct researchers."""
        allowed = resolve_allowed(["process-research"])
        self.assertIn("research-orchestrator", allowed)
        self.assertIn("technical-researcher", allowed)
        self.assertIn("research-analyst", allowed)
        # Note: research-synthesizer/report-generator reach is now via registry
        # exemption in agent-dispatch-check.py (H1 + A+B 2026-04-18 design), not
        # via SKILL_AGENT_ALIASES. See test_registry_exemption below.

    def test_unrelated_agent_still_blocked(self):
        """Alias expansion must NOT let arbitrary agents through."""
        allowed = resolve_allowed(["pm", "architect-review"])
        self.assertNotIn("debugger", allowed)
        self.assertNotIn("blueprint-mode", allowed)
        self.assertNotIn("content-marketer", allowed)

    def test_exact_agent_name_still_works(self):
        """Declaring pm-orchestrator directly (no skill alias) still works."""
        allowed = resolve_allowed(["pm-orchestrator"])
        self.assertIn("pm-orchestrator", allowed)

    def test_no_aliases_for_non_aliased_names(self):
        """Skills without aliases should not magically expand."""
        allowed = resolve_allowed(["verify"])
        # verify has no alias in SKILL_AGENT_ALIASES
        self.assertEqual(allowed, {"verify"})

    def test_empty_must_dispatch(self):
        """Empty list stays empty: caller handles the 'allow all' case."""
        allowed = resolve_allowed([])
        self.assertEqual(allowed, set())


class TestAlwaysAllowed(unittest.TestCase):
    """Infrastructure agents bypass the check entirely."""

    def test_general_purpose_in_always_allowed(self):
        self.assertIn("general-purpose", ALWAYS_ALLOWED)

    def test_explore_in_always_allowed(self):
        self.assertIn("explore", ALWAYS_ALLOWED)


class TestExtractDispatchNamesStillWorks(unittest.TestCase):
    """Regression: P0 parsing fix should still work after this edit."""

    def test_filters_trailing_reasoning(self):
        self.assertEqual(
            extract_dispatch_names("process-qa, pm let me think about this"),
            ["process-qa", "pm"],
        )

    def test_known_names_unchanged(self):
        """Drift guard: set must still match the other two hooks."""
        self.assertIn("pm", KNOWN_DISPATCH_NAMES)
        self.assertIn("architect-review", KNOWN_DISPATCH_NAMES)
        self.assertIn("process-qa", KNOWN_DISPATCH_NAMES)


class TestAliasMappingIntegrity(unittest.TestCase):
    """Sanity checks on the alias map itself."""

    def test_all_keys_are_known_dispatch_names(self):
        """Every alias key should be a recognized declared name."""
        for key in SKILL_AGENT_ALIASES:
            self.assertIn(key, KNOWN_DISPATCH_NAMES, f"{key} alias key not in KNOWN_DISPATCH_NAMES")

    def test_all_values_are_known_or_plugin_agents(self):
        """Every alias value should be either in KNOWN_DISPATCH_NAMES or a known plugin agent.
        Plugin agents (architect-reviewer) may not be in KNOWN_DISPATCH_NAMES because they're
        provided by the system, not declared in MUST DISPATCH. This test ensures we don't
        have typos in alias values."""
        # Known plugin/system agent names that are valid dispatch targets
        # but not in KNOWN_DISPATCH_NAMES (they're never declared, only dispatched)
        KNOWN_PLUGIN_AGENTS = {"architect-reviewer"}
        all_values = set()
        for agents in SKILL_AGENT_ALIASES.values():
            all_values.update(agents)
        for val in all_values:
            self.assertTrue(
                val in KNOWN_DISPATCH_NAMES or val in KNOWN_PLUGIN_AGENTS,
                f"Alias value '{val}' not in KNOWN_DISPATCH_NAMES or KNOWN_PLUGIN_AGENTS"
            )

    def test_pm_maps_to_pm_orchestrator(self):
        self.assertEqual(SKILL_AGENT_ALIASES["pm"], {"pm-orchestrator"})

    def test_architect_review_maps_to_architect_reviewer(self):
        self.assertEqual(SKILL_AGENT_ALIASES["architect-review"], {"architect-reviewer"})

    # OBSOLETE DESIGN REMOVED (2026-04-18): The 4 tests formerly here asserted an
    # abandoned alias-expansion design that would have put every possible specialist
    # (prompt-engineer, debugger, api-designer, workflow-orchestrator, etc.) into
    # SKILL_AGENT_ALIASES for process-analysis/process-build/process-planning.
    # That design was superseded by the 2026-04-18 A+B patch: when MUST DISPATCH
    # contains any process-* skill, agent-dispatch-check.py's load_registry_agents()
    # allows any agent listed in .claude/registry.json through, without requiring
    # each specialist to be enumerated in SKILL_AGENT_ALIASES. See the
    # PROCESS_ROUTING_SKILLS set in agent-dispatch-check.py for current behavior.
    # The registry-exemption mechanism is structurally tested via hook simulation
    # in the audit work at Projects/your-project/work/
    # infra-audit-2026-04-18/ (pentest case 1).


class TestMultilineMustDispatch(unittest.TestCase):
    """B4 fix 2026-04-13: multiline MUST DISPATCH extraction."""

    def test_multiline_must_dispatch_extracts_all_names(self):
        """Agent names on line 2+ of MUST DISPATCH should be in allowed set."""
        import re
        FIELD_LABELS = r'(?:IMPLIES|TASK TYPE|CLASSIFICATION|DOMAIN|APPROACH|MISSED)'
        text = (
            "TASK TYPE: Build\n"
            "MUST DISPATCH:\n"
            "  process-build,\n"
            "  pm,\n"
            "  process-qa\n"
            "MISSED: nothing"
        )
        m = re.search(
            r'MUST DISPATCH:\s*(.*?)(?=\n\s*' + FIELD_LABELS + r'\s*:|\Z)',
            text, re.DOTALL | re.IGNORECASE
        )
        self.assertIsNotNone(m)
        raw = re.sub(r'\s+', ' ', m.group(1).strip().strip('`'))
        names = extract_dispatch_names(raw)
        self.assertIn("process-build", names)
        self.assertIn("pm", names)
        self.assertIn("process-qa", names)


class CompetenceGateTestBase(unittest.TestCase):
    """Shared fixtures for the Step-11 advisory competence gate (2026-07-13).

    Repoints the module-level GATE_SIDECAR_PATH / GATE_LOG_PATH constants at
    tmpdir fixtures (the constants exist for exactly this: same pattern as
    REGISTRY_PATH) and silences emit_event so main()-driven tests never write
    to the live governance log.
    """

    HIGH_AGENT = "fixture-high-agent"
    LOW_AGENT = "fixture-low-agent"

    def setUp(self):
        import json as _json
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.sidecar_path = os.path.join(self._tmp.name, "tiers.json")
        self.log_path = os.path.join(self._tmp.name, "gov-log.jsonl")
        with open(self.sidecar_path, "w", encoding="utf-8") as f:
            _json.dump({
                self.HIGH_AGENT: {"tier": "high", "reason": "fixture"},
                self.LOW_AGENT: {"tier": "low", "reason": "fixture"},
            }, f)
        open(self.log_path, "w", encoding="utf-8").close()
        self._orig_sidecar = mod.GATE_SIDECAR_PATH
        self._orig_log = mod.GATE_LOG_PATH
        self._orig_emit = mod.emit_event
        mod.GATE_SIDECAR_PATH = self.sidecar_path
        mod.GATE_LOG_PATH = self.log_path
        mod.emit_event = None  # main()-driven tests must not touch the live log

    def tearDown(self):
        mod.GATE_SIDECAR_PATH = self._orig_sidecar
        mod.GATE_LOG_PATH = self._orig_log
        mod.emit_event = self._orig_emit
        self._tmp.cleanup()

    def write_completions(self, agent_type, passes, blocks):
        """Append pass/block completion fixtures (real-shaped session id)."""
        import json as _json
        with open(self.log_path, "a", encoding="utf-8") as f:
            for _ in range(passes):
                f.write(_json.dumps({
                    "event": "pass", "hook": "subagent-quality-check",
                    "session": "fixture-uuid", "agent_type": agent_type,
                }) + "\n")
            for _ in range(blocks):
                f.write(_json.dumps({
                    "event": "block", "hook": "subagent-quality-check",
                    "session": "fixture-uuid", "agent_type": agent_type,
                }) + "\n")

    def gate_events(self):
        """Return all competence_gate_decision entries in the fixture log."""
        import json as _json
        out = []
        with open(self.log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = _json.loads(line)
                if entry.get("event") == "competence_gate_decision":
                    out.append(entry)
        return out

    def run_gate(self, agent_type, session="test-session"):
        """Call the gate capturing stderr; return captured stderr text."""
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            mod._competence_gate(session, agent_type)
        return buf.getvalue()

    def run_main(self, payload):
        """Run main() with payload on stdin, capturing stderr. Returns stderr."""
        import contextlib
        import io
        import json as _json
        import sys as _sys
        old_stdin = _sys.stdin
        buf = io.StringIO()
        try:
            _sys.stdin = io.StringIO(_json.dumps(payload))
            with contextlib.redirect_stderr(buf):
                mod.main()
        finally:
            _sys.stdin = old_stdin
        return buf.getvalue()


class TestCompetenceGateBelow(CompetenceGateTestBase):
    """(a) high-tier + BELOW-scoring fixture log -> stderr warn + warn event."""

    def test_below_warns_and_logs_decision(self):
        self.write_completions(self.HIGH_AGENT, passes=3, blocks=7)  # 0.30
        stderr = self.run_gate(self.HIGH_AGENT)
        self.assertIn("structural reliability signal", stderr)
        self.assertIn("0.30", stderr)
        self.assertIn("n=10", stderr)
        events = self.gate_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["action_taken"], "warn")
        self.assertEqual(ev["mode"], "advisory")
        self.assertEqual(ev["verdict"], "BELOW")
        self.assertEqual(ev["agent_type"], self.HIGH_AGENT)
        self.assertEqual(ev["risk_tier"], "high")
        self.assertEqual(ev["n"], 10)
        self.assertAlmostEqual(ev["score"], 0.3)


class TestCompetenceGateNoSignal(CompetenceGateTestBase):
    """(b) n < warm-up -> no warn text; informational NO_SIGNAL event."""

    def test_no_signal_is_informational_only(self):
        self.write_completions(self.HIGH_AGENT, passes=2, blocks=0)  # n=2 < 5
        stderr = self.run_gate(self.HIGH_AGENT)
        self.assertEqual(stderr, "")
        events = self.gate_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        self.assertEqual(ev["verdict"], "NO_SIGNAL")
        self.assertEqual(ev["action_taken"], "none")
        self.assertIsNone(ev["score"])


class TestCompetenceGateScope(CompetenceGateTestBase):
    """(c) non-high tier and ALWAYS_ALLOWED types -> zero gate work."""

    def test_low_tier_no_gate_work(self):
        self.write_completions(self.LOW_AGENT, passes=0, blocks=10)
        stderr = self.run_gate(self.LOW_AGENT)
        self.assertEqual(stderr, "")
        self.assertEqual(self.gate_events(), [])

    def test_agent_absent_from_sidecar_no_gate_work(self):
        stderr = self.run_gate("agent-not-in-sidecar")
        self.assertEqual(stderr, "")
        self.assertEqual(self.gate_events(), [])

    def test_always_allowed_types_never_reach_the_gate(self):
        """The ALWAYS_ALLOWED early return precedes the call site in main()."""
        calls = []
        orig_gate = mod._competence_gate
        mod._competence_gate = lambda s, a: calls.append(a)
        try:
            for generic in sorted(ALWAYS_ALLOWED):
                self.run_main({
                    "tool_input": {"subagent_type": generic},
                    "transcript_path": None,
                })
        finally:
            mod._competence_gate = orig_gate
        self.assertEqual(calls, [])

    def test_named_specialist_does_reach_the_gate(self):
        """Wiring proof: a named agent dispatch calls the gate exactly once."""
        calls = []
        orig_gate = mod._competence_gate
        mod._competence_gate = lambda s, a: calls.append(a)
        try:
            self.run_main({
                "tool_input": {"subagent_type": self.HIGH_AGENT},
                "transcript_path": None,
            })
        finally:
            mod._competence_gate = orig_gate
        self.assertEqual(calls, [self.HIGH_AGENT])


class TestCompetenceGateNoDenyProof(CompetenceGateTestBase):
    """(d) structural no-deny proof: grep + AST level."""

    @staticmethod
    def _source():
        with open(HOOK_PATH, encoding="utf-8") as f:
            return f.read()

    @staticmethod
    def _functions(source):
        import ast
        tree = ast.parse(source)
        return {n.name: n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef)}

    @staticmethod
    def _stdout_print_count(fn_node):
        import ast
        count = 0
        for node in ast.walk(fn_node):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "print":
                to_stderr = any(
                    kw.arg == "file"
                    and isinstance(kw.value, ast.Attribute)
                    and kw.value.attr == "stderr"
                    for kw in node.keywords
                )
                if not to_stderr:
                    count += 1
        return count

    @staticmethod
    def _sys_exit_count(fn_node):
        import ast
        count = 0
        for node in ast.walk(fn_node):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "exit" \
                    and isinstance(f.value, ast.Name) and f.value.id == "sys":
                count += 1
            elif isinstance(f, ast.Name) and f.id == "exit":
                count += 1
        return count

    def test_no_permission_decision_string_anywhere(self):
        self.assertNotIn("permissionDecision", self._source())

    def test_gate_has_no_stdout_write_and_no_sys_exit(self):
        funcs = self._functions(self._source())
        self.assertIn("_competence_gate", funcs)
        gate = funcs["_competence_gate"]
        self.assertEqual(self._stdout_print_count(gate), 0)
        self.assertEqual(self._sys_exit_count(gate), 0)

    def test_main_stdout_print_count_unchanged_at_zero(self):
        funcs = self._functions(self._source())
        self.assertIn("main", funcs)
        self.assertEqual(self._stdout_print_count(funcs["main"]), 0)


class TestCompetenceGateFailOpen(CompetenceGateTestBase):
    """(e) corrupt sidecar / raising signal module -> silent allow, flow proceeds."""

    def test_corrupt_sidecar_silent_allow(self):
        with open(self.sidecar_path, "w", encoding="utf-8") as f:
            f.write("{{{ not json")
        stderr = self.run_gate(self.HIGH_AGENT)
        self.assertEqual(stderr, "")
        self.assertEqual(self.gate_events(), [])

    def test_missing_sidecar_silent_allow(self):
        mod.GATE_SIDECAR_PATH = os.path.join(self._tmp.name, "nope.json")
        stderr = self.run_gate(self.HIGH_AGENT)
        self.assertEqual(stderr, "")
        self.assertEqual(self.gate_events(), [])

    def test_get_verdict_raising_does_not_break_dispatch_flow(self):
        import sys as _sys
        if os.path.dirname(HOOK_PATH) not in _sys.path:
            _sys.path.insert(0, os.path.dirname(HOOK_PATH))
        import _competence_signal as cs

        def _boom(*args, **kwargs):
            raise RuntimeError("injected for fail-open test")

        orig = cs.get_verdict
        cs.get_verdict = _boom
        try:
            stderr = self.run_main({
                "tool_input": {"subagent_type": self.HIGH_AGENT},
                "transcript_path": None,
            })
        finally:
            cs.get_verdict = orig
        # No warn, no crash; main() ran to its post-gate no-transcript return.
        self.assertNotIn("COMPETENCE GATE", stderr)
        self.assertEqual(self.gate_events(), [])


class TestFamilyBResearchDirectWarn(CompetenceGateTestBase):
    """Family-B (2026-07-15): guarded downstream research-pipeline agent dispatched
    directly WITHOUT process-research in MUST DISPATCH -> advisory stderr warn.

    Subclasses CompetenceGateTestBase to inherit run_main + the tmpdir fixture that
    repoints GATE_* paths and nulls emit_event (so main()-driven tests don't touch
    the live governance log via the competence gate / _emit_dispatch). The Family-B
    block itself writes to the LIVE governance-log.jsonl (hardcoded path, not a
    module constant), so per the plan's log-isolation note we assert on STDERR only,
    not on the live log file (mirrors how the pre-existing 'warn' path is untested
    at the log level).
    """

    ADVISORY_MARK = "RESEARCH DISPATCH (advisory)"

    def _write_transcript(self, must_dispatch_text):
        import json as _json
        path = os.path.join(self._tmp.name, "abc123.jsonl")
        msg = {
            "type": "assistant",
            "message": {"content": [{"type": "text",
                "text": f"TASK TYPE: Research\nMUST DISPATCH: {must_dispatch_text}"}]},
        }
        with open(path, "w", encoding="utf-8") as f:
            f.write(_json.dumps(msg) + "\n")
        return path

    def _run(self, agent_type, must_dispatch_text):
        transcript = self._write_transcript(must_dispatch_text)
        return self.run_main({
            "tool_input": {"subagent_type": agent_type},
            "transcript_path": transcript,
        })

    def test_guarded_agent_without_process_research_warns(self):
        """research-orchestrator + MUST DISPATCH=[pm] (no process-research) -> warn."""
        stderr = self._run("research-orchestrator", "pm")
        self.assertIn(self.ADVISORY_MARK, stderr)
        self.assertIn("research-orchestrator", stderr)

    def test_guarded_agent_with_process_research_no_warn(self):
        """research-orchestrator + MUST DISPATCH=[process-research] -> NO warn."""
        stderr = self._run("research-orchestrator", "process-research")
        self.assertNotIn(self.ADVISORY_MARK, stderr)

    def test_all_seven_guarded_agents_warn_without_process_research(self):
        """Each of the 7 guarded agents warns when process-research is absent."""
        for agent in sorted(mod.GUARDED_RESEARCH_AGENTS):
            stderr = self._run(agent, "pm")
            self.assertIn(self.ADVISORY_MARK, stderr,
                          f"{agent} should trigger the Family-B advisory")
            self.assertIn(agent, stderr, f"{agent} name should appear in the warn")

    def test_non_research_specialist_unaffected(self):
        """architect-reviewer + MUST DISPATCH=[pm] -> NO Family-B warn."""
        stderr = self._run("architect-reviewer", "pm")
        self.assertNotIn(self.ADVISORY_MARK, stderr)

    def test_general_purpose_unaffected(self):
        """general-purpose is ALWAYS_ALLOWED -> returns before the Family-B block."""
        stderr = self._run("general-purpose", "pm")
        self.assertNotIn(self.ADVISORY_MARK, stderr)

    def test_no_classification_block_does_not_family_b_warn(self):
        """research-orchestrator dispatched with NO classification block in the
        transcript -> must_dispatch=[] -> returns at no_classification, before the
        Family-B block. Pins the section-3 boundary decision."""
        import json as _json
        path = os.path.join(self._tmp.name, "abc123.jsonl")
        msg = {"type": "assistant",
               "message": {"content": [{"type": "text", "text": "just some prose"}]}}
        with open(path, "w", encoding="utf-8") as f:
            f.write(_json.dumps(msg) + "\n")
        stderr = self.run_main({
            "tool_input": {"subagent_type": "research-orchestrator"},
            "transcript_path": path,
        })
        self.assertNotIn(self.ADVISORY_MARK, stderr)

    def test_guarded_set_matches_doctrine(self):
        """Drift guard: GUARDED_RESEARCH_AGENTS is the exact 7-name doctrine set and
        a subset of KNOWN_DISPATCH_NAMES."""
        expected = {
            "research-orchestrator", "research-analyst", "technical-researcher",
            "research-synthesizer", "report-generator", "research-coordinator",
            "query-clarifier",
        }
        self.assertEqual(mod.GUARDED_RESEARCH_AGENTS, expected)
        self.assertTrue(mod.GUARDED_RESEARCH_AGENTS <= mod.KNOWN_DISPATCH_NAMES)


class TestFamilyBNoDenyProof(unittest.TestCase):
    """Structural no-deny + no-stdout proof for the Family-B additive warn.
    Reuses the AST helpers from TestCompetenceGateNoDenyProof."""

    def test_main_still_zero_stdout_prints(self):
        src = TestCompetenceGateNoDenyProof._source()
        funcs = TestCompetenceGateNoDenyProof._functions(src)
        self.assertIn("main", funcs)
        self.assertEqual(
            TestCompetenceGateNoDenyProof._stdout_print_count(funcs["main"]), 0)

    def test_main_still_zero_sys_exit(self):
        src = TestCompetenceGateNoDenyProof._source()
        funcs = TestCompetenceGateNoDenyProof._functions(src)
        self.assertEqual(
            TestCompetenceGateNoDenyProof._sys_exit_count(funcs["main"]), 0)

    def test_no_permission_decision_string(self):
        with open(HOOK_PATH, encoding="utf-8") as f:
            self.assertNotIn("permissionDecision", f.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
