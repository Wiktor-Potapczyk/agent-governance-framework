"""Tests for user-prompt-submit.py.

REWRITTEN 2026-09-10 after the disarm probe found this suite BLIND: it passed
against a no-op stub of the hook. The previous version never imported or ran
the hook. It declared its own DEPTH_SIGNALS list and its own detect_depth_signal
function, then tested those, so nine tests stayed green no matter what the hook
did. Worse, the hook contains no DEPTH_SIGNALS at all, so the suite was pinning
a feature that is not there (see the FINDING note at the bottom of this file).

The binding here is a SUBPROCESS RUN, not an import. That is deliberate on two
counts. The filename has hyphens, so it is not importable as a module without
loader gymnastics; and more importantly the hook's real contract is exactly
what a subprocess exercises, namely a JSON object on stdin and one JSON object
on stdout. A stub that prints nothing fails every test here at the json.loads,
which is the property the old suite lacked.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent / "user-prompt-submit.py"


def run_hook(payload, tmp_path):
    """Run the real hook. Returns its parsed stdout envelope."""
    env = dict(os.environ)
    # Keep the suite out of the live telemetry sink. Without this every test
    # run appends real-looking records to hook-activity.jsonl.
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "hook-activity.jsonl")
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
        timeout=60, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip(), "hook emitted nothing on stdout"
    return json.loads(proc.stdout)


def context_of(envelope):
    return envelope["hookSpecificOutput"]["additionalContext"]


def compact(obj):
    """Render JSON the way a real transcript does.

    This matters and it is not cosmetic. The hook scans the transcript tail
    with regexes like "input_tokens":(\\d+) that allow no space after the
    colon, which is correct because Claude Code writes compact JSON. A fixture
    built with a default json.dumps inserts a space, matches nothing, and makes
    a working hook look broken. Verified against the live transcript on
    2026-09-10: "input_tokens":6 matches, the spaced variant finds zero.
    """
    return json.dumps(obj, separators=(",", ":"))


def write_transcript(tmp_path, model, tokens):
    """A minimal transcript tail carrying the fields the hook parses."""
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        compact({"model": model}) + "\n"
        + compact({"usage": {"input_tokens": tokens,
                             "cache_creation_input_tokens": 0,
                             "cache_read_input_tokens": 0}}) + "\n",
        encoding="utf-8")
    return str(path)


# --- envelope contract -------------------------------------------------------

def test_emits_a_well_formed_userpromptsubmit_envelope(tmp_path):
    out = run_hook({"prompt": "refactor the parser"}, tmp_path)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert isinstance(context_of(out), str)


# --- classifier mandate: the hook's reason for existing -----------------------

def test_injects_the_classifier_mandate_for_an_ordinary_prompt(tmp_path):
    ctx = context_of(run_hook({"prompt": "refactor the parser"}, tmp_path))
    assert "MANDATORY" in ctx
    assert "task-classifier" in ctx


@pytest.mark.parametrize("prompt", ["ok", "go", "yes", "continue", "thanks"])
def test_skip_list_prompts_suppress_the_mandate(prompt, tmp_path):
    """Conversational acknowledgements inherit the prior classification, so
    re-demanding one is noise. This is the hook's only suppression rule for
    main-session prompts."""
    ctx = context_of(run_hook({"prompt": prompt}, tmp_path))
    assert "MANDATORY" not in ctx


def test_skip_list_matching_ignores_case_and_surrounding_space(tmp_path):
    ctx = context_of(run_hook({"prompt": "  OK  "}, tmp_path))
    assert "MANDATORY" not in ctx


def test_a_prompt_merely_containing_a_skip_word_still_gets_the_mandate(tmp_path):
    """The skip list is whole-prompt equality, not substring. A bare ok
    suppresses; ok followed by real work must not."""
    ctx = context_of(run_hook({"prompt": "ok now rewrite the loader"}, tmp_path))
    assert "MANDATORY" in ctx


def test_subagent_invocations_get_no_mandate(tmp_path):
    """Subagents are dispatched with a task, not a classification duty. The
    discriminator is the presence of agent_id or agent_type on the payload."""
    for key in ("agent_id", "agent_type"):
        ctx = context_of(run_hook({"prompt": "refactor the parser", key: "x"},
                                  tmp_path))
        assert "MANDATORY" not in ctx, key


# --- context bar -------------------------------------------------------------

def test_context_bar_is_built_from_the_transcript(tmp_path):
    t = write_transcript(tmp_path, "claude-opus-5", 200000)
    ctx = context_of(run_hook({"prompt": "refactor", "transcript_path": t},
                              tmp_path))
    assert "CTX " in ctx
    assert "opus-5" in ctx
    assert "200K/1000K" in ctx


def test_million_context_models_are_scaled_to_1000k(tmp_path):
    t = write_transcript(tmp_path, "claude-sonnet-5", 100000)
    assert "/1000K" in context_of(
        run_hook({"prompt": "refactor", "transcript_path": t}, tmp_path))


def test_other_models_stay_at_200k_and_lose_the_date_suffix(tmp_path):
    t = write_transcript(tmp_path, "claude-haiku-4-5-20251001", 20000)
    ctx = context_of(run_hook({"prompt": "refactor", "transcript_path": t},
                              tmp_path))
    assert "20K/200K" in ctx
    assert "haiku-4-5" in ctx
    assert "20251001" not in ctx


def test_token_fields_are_summed_not_taken_singly(tmp_path):
    """Occupancy is input + cache_creation + cache_read. Reading only
    input_tokens would understate a cached session by most of its context."""
    path = tmp_path / "t.jsonl"
    path.write_text(compact({"model": "claude-opus-5"}) + "\n" + compact(
        {"usage": {"input_tokens": 100000,
                   "cache_creation_input_tokens": 50000,
                   "cache_read_input_tokens": 150000}}) + "\n", encoding="utf-8")
    ctx = context_of(run_hook({"prompt": "refactor",
                               "transcript_path": str(path)}, tmp_path))
    assert "300K/1000K" in ctx


def test_save_enforcement_appears_once_context_passes_half(tmp_path):
    t = write_transcript(tmp_path, "claude-opus-5", 600000)
    ctx = context_of(run_hook({"prompt": "refactor", "transcript_path": t},
                              tmp_path))
    assert "SAVE ENFORCEMENT" in ctx
    assert "60%" in ctx


def test_save_enforcement_is_absent_below_half(tmp_path):
    t = write_transcript(tmp_path, "claude-opus-5", 100000)
    ctx = context_of(run_hook({"prompt": "refactor", "transcript_path": t},
                              tmp_path))
    assert "SAVE ENFORCEMENT" not in ctx


def test_subagents_get_no_save_enforcement_either(tmp_path):
    t = write_transcript(tmp_path, "claude-opus-5", 600000)
    ctx = context_of(run_hook({"prompt": "refactor", "transcript_path": t,
                               "agent_type": "general-purpose"}, tmp_path))
    assert "SAVE ENFORCEMENT" not in ctx


# --- degradation -------------------------------------------------------------

def test_a_missing_transcript_degrades_the_bar_and_keeps_the_mandate(tmp_path):
    """Fail soft on the display half, never on the enforcement half.

    A vanished transcript does not suppress the bar; the hook still emits one,
    degraded to the unknown-model defaults. Pinning the degraded shape rather
    than the bar's absence is the point: the failure mode worth catching is a
    hook that goes silent and takes the classification mandate with it.
    """
    ctx = context_of(run_hook(
        {"prompt": "refactor", "transcript_path": str(tmp_path / "nope.jsonl")},
        tmp_path))
    assert "MANDATORY" in ctx
    assert "0K/200K" in ctx
    assert "| ?" in ctx


def test_empty_stdin_does_not_crash_the_hook(tmp_path):
    env = dict(os.environ)
    env["HOOK_ACTIVITY_LOG_PATH"] = str(tmp_path / "a.jsonl")
    proc = subprocess.run([sys.executable, str(HOOK)], input="",
                          capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0
    assert json.loads(proc.stdout)["hookSpecificOutput"]["hookEventName"] \
        == "UserPromptSubmit"


# --- FINDING, not a test -----------------------------------------------------
# The suite this file replaced tested a DEPTH_SIGNALS table (are you sure,
# think deeper, why did, ...) attributed to an S1/M1 fix dated 2026-04-13.
# The hook contains no such table: grep for DEPTH_SIGNALS in
# user-prompt-submit.py returns zero hits. Either the feature was removed and
# its suite was left behind, or it never landed and the suite pinned an
# intention. Depth-signal detection is NOT restored here, because adding a
# behaviour is a change to what the hook does and that is Wiktor's call, not a
# test-repair decision. Reported, not fixed.
