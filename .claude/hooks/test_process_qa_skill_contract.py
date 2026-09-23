"""The process-qa skill text states the contract the hooks and the workflow
script enforce (2026-09-21 rebuild). These assertions pin the load-bearing
strings: the four hook-matched literals, the claim classes, the verifier
line, the deliverable arg, and the relay-to-log check. A drift in the prose
that drops one of them is a contract change, not an edit."""
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent / "skills" / "process-qa" / "SKILL.md"
SCRIPT = Path(__file__).resolve().parent.parent / "workflows" / "process-qa.js"


def _text():
    return " ".join(SKILL.read_text(encoding="utf-8").split())


def test_the_hook_matched_literals_are_present():
    t = _text()
    for literal in ("QA SCOPE", "QA REPORT:", "PASS: <n> / <N>", "no verifiable claims"):
        assert literal in t, literal


def test_the_skill_documents_the_four_classes_and_the_run_rule():
    t = _text()
    for cls in ("`run`", "`execute`", "`read`", "`mcp`"):
        assert cls in t, cls
    assert "When in doubt between `run` and `execute`, it is `run`" in t
    assert "a unit test, a validator, a grep, a read" in t


def test_the_skill_documents_the_verifier_and_the_deliverable_arg():
    t = _text()
    assert "Verifier: workflow" in t and "Verifier: main-session" in t
    assert "`deliverable`" in t
    assert "added by scope" in t


def test_the_skill_documents_that_the_relay_is_checked_against_the_log():
    t = _text()
    assert "opens the qa-log the relay names" in t
    assert "Nothing is weakened by this" not in t


def test_the_skill_cites_the_live_path_ruling():
    assert "feedback_test_every_live_path_before_calling_a_build_done" in _text()


def test_untested_is_paths_not_categories():
    t = _text()
    assert "as paths" in t and "never as categories" in t
    assert "needs a reason" in t


def test_the_script_agrees_on_the_classes_and_the_verifier():
    src = SCRIPT.read_text(encoding="utf-8")
    assert "const CLAIM_CLASSES = ['run', 'execute', 'read', 'mcp']" in src
    assert "Verifier: workflow" in src
    assert "isReadOnlyCommand" in src and "invokesArtifact" in src
