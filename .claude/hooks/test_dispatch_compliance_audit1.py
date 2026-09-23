"""Harness audit 1 (2026-09-21): dispatch-compliance findings A1, A2, A4, A5, A6,
A12, S2, S4, S5, S6, S11 from the two reviews of the gate, each reproduced
against the real hook before the change. Fix plan:
[[2026-09-21-dispatch-and-work-verification-fix-plan]]."""
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

from _hooktest import run_isolated  # noqa: E402
from _dispatch_compliance_logic import (  # noqa: E402
    NON_ALIASABLE, KNOWN_DISPATCH_NAMES, compute_missing, extract_dispatch_names,
    extract_dispatch_names_detail, find_task_type, scan_assistant_text_block,
)

CLS = ("IMPLIES: build x\nTASK TYPE: Build\nDOMAIN: general\nREVERSIBILITY: reversible\n"
       "DETECTABILITY: self-detectable\nAPPROACH: process-build\nMISSED: nothing\nMUST DISPATCH: process-build, process-qa")


def u(text):
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def a(blocks):
    return json.dumps({"type": "assistant", "message": {"content": blocks}})


def txt(t):
    return {"type": "text", "text": t}


def tool(name, inp):
    return {"type": "tool_use", "id": "t", "name": name, "input": inp}


def run(tmp_path, lines):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    proc, hooks_dir = run_isolated("dispatch-compliance-check.py", {"transcript_path": str(p)}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    gov = hooks_dir / "governance-log.jsonl"
    events = [json.loads(l) for l in gov.read_text(encoding="utf-8").splitlines() if l.strip()] if gov.exists() else []
    return proc.stdout, proc.stderr, events


def fresh_state():
    return {"must_dispatch": [], "dispatched": set(), "found_contract": False, "task_type": ""}


# --- A2: a process skill is discharged only by its own invocation --------------

def test_every_process_skill_needs_its_own_invocation():
    for skill, members in [("process-build", {"blueprint-mode", "architect-reviewer", "implementation-plan"}),
                           ("process-planning", {"implementation-plan", "adversarial-reviewer"}),
                           ("process-research", {"research-orchestrator", "technical-researcher", "research-analyst"}),
                           ("process-analysis", {"architect-reviewer", "adversarial-reviewer"}),
                           ("architect-loop", {"architect-reviewer", "adversarial-reviewer"})]:
        assert skill in NON_ALIASABLE
        assert compute_missing([skill], members) == [skill]
        assert compute_missing([skill], members | {skill}) == []


def test_pm_and_architect_review_stay_aliasable():
    assert compute_missing(["pm", "architect-review"], {"pm-orchestrator", "architect-reviewer"}) == []


def test_alias_only_process_build_blocks_end_to_end(tmp_path):
    """Review A2 fixture G: MUST DISPATCH process-build, three bare Agent calls,
    never Skill(process-build): a silent pass before the change."""
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-build")]),
             a([tool("Agent", {"subagent_type": "implementation-plan", "prompt": "p"})]),
             a([tool("Agent", {"subagent_type": "blueprint-mode", "prompt": "p"})]),
             a([tool("Agent", {"subagent_type": "architect-reviewer", "prompt": "p"})]), a([txt("done")])]
    out, _, _ = run(tmp_path, lines)
    assert '"block"' in out and "process-build" in out


# --- A1 / S7: fences -------------------------------------------------------------

def test_a_fenced_classification_is_not_a_contract():
    state = scan_assistant_text_block("Here is the template:\n```\nTASK TYPE: Build\nMUST DISPATCH: process-qa\n```\nJust conversation.", fresh_state())
    assert not state["found_contract"] and state["task_type"] == ""


def test_a_fenced_template_quote_does_not_block_end_to_end(tmp_path):
    lines = [u("what does the classifier block look like?"),
             a([txt("Like this:\n```\nIMPLIES: x\nTASK TYPE: Build\nMUST DISPATCH: implementation-plan, architect-reviewer, process-qa\n```\nThat is documentation, not this turn.")])]
    out, _, _ = run(tmp_path, lines)
    assert out == "", out


# --- A4: a dispatch before its classification in the same message ---------------

def test_a_dispatch_that_precedes_its_classification_in_one_message_counts(tmp_path):
    lines = [u("build it"), a([tool("Skill", {"skill": "process-build"}), tool("Skill", {"skill": "process-qa"}), txt(CLS)]), a([txt("done")])]
    out, _, events = run(tmp_path, lines)
    assert out == "", out
    assert any(e.get("event") == "pass" for e in events)


# --- A5: the sidecar fallback does not re-arm on a later TASK TYPE mention -------

def test_a_later_task_type_mention_does_not_arm_the_sidecar_fallback(tmp_path):
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-build")]),
             a([tool("Skill", {"skill": "process-build"})]),
             a([txt("A trivial version of this would be TASK TYPE: Quick, but it is not.")]), a([txt("done")])]
    out, _, events = run(tmp_path, lines)
    assert out == "", out
    assert not any(e.get("event") == "h11_sidecar_fallback_activated" for e in events)


# --- A6: a misspelt TASK TYPE is loud, not silent --------------------------------

def test_find_task_type_returns_a_misspelt_token():
    assert find_task_type("IMPLIES: x\nTASK TYPE: Bild\nMUST DISPATCH: process-build") == "bild"
    assert find_task_type("TASK TYPE: **Build**") == "build"


def test_a_misspelt_task_type_still_enforces_the_contract(tmp_path):
    lines = [u("implement retry logic"), a([txt("IMPLIES: x\nTASK TYPE: Bild\nMUST DISPATCH: process-build, process-qa")]), a([txt("shipped")])]
    out, _, _ = run(tmp_path, lines)
    assert '"block"' in out and "process-build" in out


def test_a_misspelt_task_type_with_no_dispatch_list_names_the_value(tmp_path):
    lines = [u("implement retry logic"), a([txt("IMPLIES: x\nTASK TYPE: Bild\nMUST DISPATCH: none")]), a([txt("shipped")])]
    out, _, _ = run(tmp_path, lines)
    assert '"block"' in out and "bild" in out.lower() and "not a recognised" in out


# --- S2 / S5 / S6: declared names are not dropped silently ----------------------

def test_names_split_on_newlines_bullets_plus_slash_then_and_arrows():
    raw = "- process-qa\n- architect-reviewer + adversarial-reviewer / pm then implementation-plan -> blueprint-mode"
    assert extract_dispatch_names(raw) == ["process-qa", "architect-reviewer", "adversarial-reviewer", "pm", "implementation-plan", "blueprint-mode"]


def test_a_typo_within_reach_of_a_known_name_binds_to_it():
    found, unrecognised = extract_dispatch_names_detail("process-qa, architect-reveiwer")
    assert found == ["process-qa", "architect-reviewer"] and unrecognised == []


def test_an_unknown_kebab_name_is_reported_not_dropped():
    found, unrecognised = extract_dispatch_names_detail("process-qa, some-agent-nobody-has")
    assert found == ["process-qa"] and unrecognised == ["some-agent-nobody-has"]


def test_trailing_prose_is_still_not_a_name():
    assert extract_dispatch_names("process-qa, pm because this is a planning task that needs oversight") == ["process-qa", "pm"]


def test_built_in_agent_types_are_known():
    for name in ("explore", "general-purpose", "plan", "web-fetch", "fork", "claude"):
        assert name in KNOWN_DISPATCH_NAMES


def test_a_bullet_list_declaration_is_not_read_as_empty(tmp_path):
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH:\n- process-build\n- process-qa")]), a([txt("done")])]
    out, _, _ = run(tmp_path, lines)
    assert '"block"' in out and "missing: [process-build, process-qa]" in out


def test_an_unrecognised_declared_name_is_in_the_event_and_on_stderr(tmp_path):
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-qa, some-agent-nobody-has")]),
             a([tool("Skill", {"skill": "process-qa"})]), a([txt("done")])]
    out, err, events = run(tmp_path, lines)
    assert "some-agent-nobody-has" in err
    ev = [e for e in events if e.get("event") in ("pass", "block")][-1]
    assert ev.get("unrecognised_declared") == ["some-agent-nobody-has"]


# --- S4: TASK TYPE in one block, MUST DISPATCH in the next -----------------------

def test_a_contract_split_over_two_text_blocks_is_one_contract():
    s = scan_assistant_text_block("IMPLIES: x\nTASK TYPE: Build\nAPPROACH: a", fresh_state())
    assert not s["found_contract"]
    s = scan_assistant_text_block("MISSED: m\nMUST DISPATCH: process-build, process-qa", s)
    assert s["found_contract"] and s["must_dispatch"] == ["process-build", "process-qa"] and s["task_type"] == "build"


# --- A12 / S1: telemetry and the window ------------------------------------------

def test_the_pass_event_says_how_each_name_was_satisfied(tmp_path):
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-build, pm")]),
             a([tool("Skill", {"skill": "process-build"}), tool("Agent", {"subagent_type": "pm-orchestrator", "prompt": "p"})]), a([txt("done")])]
    out, _, events = run(tmp_path, lines)
    assert out == "", out
    ev = [e for e in events if e.get("event") == "pass"][-1]
    assert ev["matched_by"] == {"process-build": "direct", "pm": "alias"}
    assert ev["task_type"] == "build" and ev["window_bytes"] > 0


def test_the_contract_survives_a_tool_result_larger_than_the_old_window(tmp_path):
    """Silent-failure review item 1: one 300 KB tool_result hid the classification."""
    big = json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t", "content": "x" * 300_000}]}})
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-build, process-qa")]), a([tool("Bash", {"command": "cat big"})]), big, a([txt("done")])]
    out, _, events = run(tmp_path, lines)
    assert '"block"' in out and "process-build" in out
    ev = [e for e in events if e.get("event") == "block"][-1]
    assert ev["window_bytes"] > 204800


# --- architect review of the build, finding 1 -----------------------------------

def test_a_later_task_type_mention_does_not_discard_an_unsatisfied_contract(tmp_path):
    """The A5 fix stopped the sidecar re-arm and, as a side effect, the whole
    hook went silent: the incidental mention reset the contract to nothing."""
    lines = [u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-build")]),
             a([txt("A trivial version of this would be TASK TYPE: Quick, but it is not.")]), a([txt("done")])]
    out, _, events = run(tmp_path, lines)
    assert '"block"' in out and "process-build" in out
    assert any(e.get("event") == "block" for e in events)


def test_an_incidental_mention_keeps_the_contract_but_a_new_block_replaces_it():
    s = scan_assistant_text_block("TASK TYPE: Build\nMUST DISPATCH: process-build", fresh_state())
    s = scan_assistant_text_block("It is not TASK TYPE: Quick work.", s)
    assert s["found_contract"] and s["must_dispatch"] == ["process-build"]
    s = scan_assistant_text_block("IMPLIES: y\nTASK TYPE: Analysis\nMUST DISPATCH: process-analysis, process-qa", s)
    assert s["must_dispatch"] == ["process-analysis", "process-qa"] and s["task_type"] == "analysis"


def test_a_missing_boundary_helper_is_said_on_stderr(tmp_path):
    """Architect finding 3: the fallback to the old fixed tail was silent."""
    import shutil
    from _hooktest import isolate
    hook = isolate("dispatch-compliance-check.py", tmp_path)
    (hook.parent / "_turn_boundary.py").unlink()
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([u("build it"), a([txt("TASK TYPE: Build\nMUST DISPATCH: process-build")]), a([txt("done")])]) + "\n", encoding="utf-8")
    import subprocess, os
    env = dict(os.environ, PYTHONIOENCODING="utf-8", GOVERNANCE_LOG_PATH=str(hook.parent / "governance-log.jsonl"), HOOK_ACTIVITY_LOG_PATH=str(hook.parent / "hook-activity.jsonl"))
    r = subprocess.run([sys.executable, str(hook)], input=json.dumps({"transcript_path": str(p)}), capture_output=True, text=True, timeout=60, env=env)
    assert '"block"' in r.stdout
    assert "_turn_boundary" in r.stderr and "fixed" in r.stderr


# --- live false block, 2026-09-21 19:05 ------------------------------------------

def test_a_quick_block_does_not_wait_for_a_dispatch_list():
    """Caught live: a Quick classification (no MUST DISPATCH by design) left the
    split-block state waiting, and a later prose mention "MUST DISPATCH: a, b"
    in a status reply completed it into a phantom contract that blocked."""
    s = scan_assistant_text_block("IMPLIES: status\nTASK TYPE: Quick\nJUSTIFICATION: a summary", fresh_state())
    assert not s.get("awaiting_must_dispatch")
    s = scan_assistant_text_block("Classification inherited (Build; MUST DISPATCH: adversarial-reviewer, architect-reviewer).", s)
    assert not s["found_contract"]


def test_the_wait_for_a_dispatch_list_lasts_one_text_block():
    s = scan_assistant_text_block("IMPLIES: x\nTASK TYPE: Build\nAPPROACH: a", fresh_state())
    assert s.get("awaiting_must_dispatch")
    s = scan_assistant_text_block("BUILD SCOPE\nGoal: y", s)
    assert not s.get("awaiting_must_dispatch")
    s = scan_assistant_text_block("MUST DISPATCH: process-build", s)
    assert not s["found_contract"]
