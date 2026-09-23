"""Contract tests for write-style-guard.py, the PreToolUse companion.

The reply guard blocks what Wiktor reads. This one blocks what gets saved, and
it is the half that plain-language-guard.py structurally cannot do: that hook
runs PostToolUse, so by the time it speaks the file is already on disk.

BOLD_PER_1000 = 33 is the tightest value clearing the vault's own documented bar
for turning a rule into a block (a fire rate at or below 10 percent). Measured
over 365 files with code, tables and structured blocks stripped: median 15.6
bold spans per 1000 prose words, p75 23.7, p90 32.0, max 75.3; 33 fires on 9.0
percent. It first shipped at 25 (22.5 percent) on my own argument for an
exception, which a PM checkpoint correctly refused as self-certification.
"""

import importlib.util
import json
import os
import subprocess
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_PATH = os.path.join(HOOKS_DIR, "write-style-guard.py")


def _load():
    spec = importlib.util.spec_from_file_location("write_style_guard", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(path, content, tool="Write"):
    """Drive it as a real PreToolUse hook. Returns (rc, decision, reason)."""
    payload = {
        "tool_name": tool,
        "tool_input": {"file_path": path, "content": content}
        if tool == "Write"
        else {"file_path": path, "new_string": content},
        "session_id": "test-session",
    }
    env = dict(os.environ, PYTHONIOENCODING="utf-8", WRITE_STYLE_GUARD_TESTING="1")
    p = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30,
    )
    decision, reason = None, ""
    if p.stdout.strip():
        try:
            out = json.loads(p.stdout)
            decision = out["hookSpecificOutput"]["permissionDecision"]
            reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        except Exception:
            pass
    return p.returncode, decision, reason


IN = "C:/Users/X/Desktop/Vault/Projects/Demo/work/2026-08-27-note.md"
FILLER = ("The guard reads the content before the write lands and decides. " * 12)


def _prose(bold_spans, words=400):
    body = " ".join("word%d" % i for i in range(words))
    return " ".join("**b%d**" % i for i in range(bold_spans)) + " " + body


# --------------------------------------------------------------------- scope

def test_out_of_scope_paths_are_ignored():
    for path in [
        "C:/Vault/Projects/Demo/STATE.md",
        "C:/Vault/Projects/Demo/task_plan.md",
        "C:/Vault/.claude/hooks/thing.py",
        "C:/Vault/Projects/Demo/work/backups/old.md",
        "C:/Vault/Notes/personal.md",
    ]:
        rc, decision, _ = _run(path, _prose(200))
        assert decision is None, path
        assert rc == 0


def test_in_scope_surfaces_are_guarded():
    mod = _load()
    for path in [
        "C:/Vault/Projects/Demo/work/note.md",
        "C:/Vault/Resources/KB/page.md",
        "C:/Vault/Projects/X/framework-repo/docs/architecture.md",
        "C:/Vault/Projects/X/framework-repo/README.md",
    ]:
        assert mod.in_scope(path), path


# ------------------------------------------------------------- bold density

def test_dense_bold_is_denied():
    rc, decision, reason = _run(IN, _prose(20, words=400))
    assert decision == "deny"
    assert "per 1000" in reason
    assert rc == 0, "a deny is expressed in JSON, not an exit code"


def test_sparse_bold_is_allowed():
    """A long file with a few bold spans is normal and must pass. This is the
    case a raw count would have failed: 8 spans is over the reply limit of 4."""
    rc, decision, _ = _run(IN, _prose(8, words=1000))
    assert decision is None


def test_short_files_are_skipped():
    """A density ratio over a handful of words is noise, so under 50 prose words
    nothing is judged on density."""
    rc, decision, _ = _run(IN, "**a** **b** **c** **d** **e** short note.")
    assert decision is None


def test_bold_inside_code_and_tables_is_not_counted():
    content = (
        "Real prose here that is long enough to be scored properly. " * 8
        + "\n```\n"
        + " ".join("**x%d**" % i for i in range(60))
        + "\n```\n"
        + "| **a** | **b** |\n|---|---|\n| **c** | **d** |\n"
    )
    rc, decision, _ = _run(IN, content)
    assert decision is None


# ----------------------------------------------------------------- wordlist

def test_stock_word_is_denied_regardless_of_length():
    rc, decision, reason = _run(IN, FILLER + " This is a testament to the design.")
    assert decision == "deny"
    assert "testament" in reason


def test_stock_word_in_backticks_is_allowed():
    rc, decision, _ = _run(IN, FILLER + " The wordlist holds `testament` and `delve`.")
    assert decision is None


# ---------------------------------------------------------- one rule engine

def test_it_imports_the_reply_guards_engine_rather_than_copying_it():
    """PM asked for this reconciliation before the hook was built: the two
    surfaces must not drift apart in what they call prose or a stock word."""
    src = open(HOOK_PATH, encoding="utf-8").read()
    assert "reply-style-guard.py" in src
    assert "WORDLIST = [" not in src, "the wordlist must not be redefined here"
    assert "def strip_noise" not in src, "strip_noise must not be redefined here"
    mod = _load()
    engine = mod._engine()
    assert hasattr(engine, "strip_noise") and hasattr(engine, "WORDLIST")


# ------------------------------------------------------- safety and contract

def test_edit_tool_scores_only_the_replacement_text():
    rc, decision, _ = _run(IN, _prose(20, words=400), tool="Edit")
    assert decision == "deny"


def test_malformed_stdin_allows():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", WRITE_STYLE_GUARD_TESTING="1")
    p = subprocess.run(
        [sys.executable, HOOK_PATH],
        input="{not json", capture_output=True, text=True, env=env, timeout=30,
    )
    assert p.returncode == 0
    assert p.stdout.strip() == ""


def test_empty_content_allows():
    rc, decision, _ = _run(IN, "   \n  ")
    assert decision is None


def test_missing_file_path_allows():
    env = dict(os.environ, PYTHONIOENCODING="utf-8", WRITE_STYLE_GUARD_TESTING="1")
    p = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=json.dumps({"tool_name": "Write", "tool_input": {"content": _prose(50)}}),
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert p.returncode == 0
    assert p.stdout.strip() == ""


def test_deny_reason_contains_no_bold_itself():
    _, _, reason = _run(IN, _prose(20, words=400))
    assert "**" not in reason


def test_threshold_is_a_named_constant():
    mod = _load()
    assert mod.BOLD_PER_1000 == 33
    assert mod.MIN_WORDS == 50


def test_allow_is_logged_not_only_block():
    src = open(HOOK_PATH, encoding="utf-8").read()
    assert '_log("allow"' in src
    assert '_log("block"' in src
