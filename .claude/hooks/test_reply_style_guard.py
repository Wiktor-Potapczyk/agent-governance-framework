"""Contract tests for reply-style-guard.py.

Written BEFORE the hook, per the vault's declarative-first rule: the failing
test is the spec. Every threshold below is measured, not chosen by taste.

BOLD_LIMIT = 4 comes from the distribution over 1,522 of this assistant's own
message blocks in session 67e82ff4 (code, tables and structured blocks already
stripped): 4-or-more fires on 8.7% of them, 3-or-more on 13.2%. The vault's own
Stage 4 block-flip criterion in .claude/rules/plain-language.md requires a warn
rate at or below 10 percent, so 4 clears that bar and 3 does not.

The wordlist is the low-false-positive subset of the humanizer skill's patterns,
measured at 1.5% of the same corpus. Sentence length and abbreviation rules are
deliberately NOT here: they fire on 17.9% and 35.2% of in-scope writes under the
existing plain-language guard, and a guard that fires that often gets ignored,
which is how that guard produced 266 findings and changed nothing.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

import pytest

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_PATH = os.path.join(HOOKS_DIR, "reply-style-guard.py")


def _load():
    """Import the hyphenated module by path (same idiom as the em-dash guard's
    own test: a hyphen is not a legal identifier, so importlib is required)."""
    spec = importlib.util.spec_from_file_location("reply_style_guard", HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(assistant_text, stop_hook_active=False, transcript=True, raw_stdin=None):
    """Drive the hook end to end as a real Stop hook: build a one-line transcript
    holding the assistant message, feed the payload on stdin, return (rc, stderr)."""
    with tempfile.TemporaryDirectory() as td:
        tpath = os.path.join(td, "t.jsonl")
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": assistant_text}]},
        }
        with open(tpath, "w", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        payload = {
            "transcript_path": tpath if transcript else os.path.join(td, "missing.jsonl"),
            "stop_hook_active": stop_hook_active,
            "session_id": "test-session",
        }
        stdin = raw_stdin if raw_stdin is not None else json.dumps(payload)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", REPLY_STYLE_GUARD_TESTING="1")
        p = subprocess.run(
            [sys.executable, HOOK_PATH],
            input=stdin, capture_output=True, text=True, env=env, timeout=30,
        )
        return p.returncode, p.stderr


BOLD = "**a** **b** **c** **d**"


# ---------------------------------------------------------------- bold rule

def test_clean_prose_allows():
    rc, _ = _run("This is an ordinary sentence with no styling at all.")
    assert rc == 0


def test_four_bold_spans_blocks():
    rc, err = _run(f"Some prose. {BOLD} More prose.")
    assert rc == 2
    assert "bold" in err.lower()


def test_three_bold_spans_allows():
    """The boundary is load-bearing: 3 fires on 13.2% of real messages, which
    exceeds the vault's own 10% flip criterion. Emphasis stays available."""
    rc, _ = _run("Some prose. **a** **b** **c** More prose.")
    assert rc == 0


def test_bold_inside_fenced_code_is_not_counted():
    rc, _ = _run("Prose.\n```\n**a** **b** **c** **d** **e**\n```\nMore prose.")
    assert rc == 0


def test_bold_inside_table_rows_is_not_counted():
    table = "\n".join([
        "| **a** | **b** |",
        "|---|---|",
        "| **c** | **d** |",
        "| **e** | **f** |",
    ])
    rc, _ = _run("Prose.\n" + table + "\nMore prose.")
    assert rc == 0


def test_bold_inside_structured_blocks_is_not_counted():
    """QA REPORT and friends are exempt by CLAUDE.md. A guard that judged them
    would fight two Stop hooks that REQUIRE those blocks in the reply."""
    rc, _ = _run(
        "Prose here.\n\n"
        "QA REPORT\n"
        "PASS: **4** / **6**\n"
        "FAIL: **a** and **b**\n"
        "Untested: none deliberately\n"
    )
    assert rc == 0


def test_bold_inside_inline_code_is_not_counted():
    rc, _ = _run("Use `**a** **b** **c** **d**` as the literal pattern.")
    assert rc == 0


# ------------------------------------------------------------ wordlist rule

@pytest.mark.parametrize("word", [
    "delve", "tapestry", "showcases", "pivotal",
    "testament", "vibrant", "interplay",
])
def test_ai_words_block(word):
    rc, err = _run(f"This {word} is in the middle of an otherwise clean sentence.")
    assert rc == 2
    assert word.lower() in err.lower()


def test_chatbot_phrase_blocks():
    rc, err = _run("Here is the summary. I hope this helps!")
    assert rc == 2
    assert "hope this helps" in err.lower()


def test_wordlist_hit_inside_inline_code_allows():
    """Naming a banned token while discussing it is not using it."""
    rc, _ = _run("The pattern matches `delve` and `tapestry` in the wordlist.")
    assert rc == 0


def test_wordlist_hit_inside_fenced_code_allows():
    rc, _ = _run("Regex:\n```\n(delve|tapestry|pivotal)\n```\nThat is the set.")
    assert rc == 0


def test_substring_does_not_false_positive():
    """Word boundaries matter: 'fostering' is on the list, 'Foster' as a name
    and 'keyboard' containing 'key' must not fire."""
    rc, _ = _run("The keyboard shortcut is documented and the key is on file.")
    assert rc == 0


# ------------------------------------------------------- safety and contract

def test_stop_hook_active_allows():
    """Without this the guard would re-fire on its own block message forever."""
    rc, _ = _run(f"{BOLD} **e**", stop_hook_active=True)
    assert rc == 0


def test_missing_transcript_fails_open():
    rc, _ = _run(BOLD, transcript=False)
    assert rc == 0


def test_malformed_stdin_fails_open():
    rc, _ = _run("", raw_stdin="{not json at all")
    assert rc == 0


def test_empty_stdin_fails_open():
    rc, _ = _run("", raw_stdin="")
    assert rc == 0


def test_block_message_contains_no_bold_itself():
    """The em-dash guard's own rule: a block message must not contain the thing
    it blocks, or the rewrite it demands would trip the guard again."""
    _, err = _run(f"{BOLD} **e**")
    assert "**" not in err


def test_block_message_says_what_to_do():
    _, err = _run(f"{BOLD} **e**")
    assert "rewrite" in err.lower() or "remove" in err.lower()


# ------------------------------------------------------------ measurability

def test_allow_is_logged_not_only_block():
    """Today's Gate-1 finding, applied here: a guard that writes a record only
    when it blocks has a structurally unmeasurable false-negative rate, because
    a correct allow and a defeated guard are byte-identical silence."""
    mod = _load()
    assert hasattr(mod, "_log"), "hook must expose a _log helper"
    src = open(HOOK_PATH, encoding="utf-8").read()
    assert '_log("allow"' in src, "the allow path must write a log record"
    assert '_log("block"' in src, "the block path must write a log record"


def test_thresholds_are_named_constants():
    mod = _load()
    assert mod.BOLD_LIMIT == 4
    assert isinstance(mod.WORDLIST, (list, tuple))
    assert len(mod.WORDLIST) >= 5


def test_strip_noise_is_reusable_and_pure():
    mod = _load()
    src = "Prose **a**\n```\n**b**\n```\n| **c** |\n"
    once = mod.strip_noise(src)
    twice = mod.strip_noise(src)
    assert once == twice
    assert "**b**" not in once
    assert "**a**" in once

# ------------------------------------------------- architect review, 2026-08-27
# Each test below pins a defect the reviewer REPRODUCED against the real report
# templates. The original exemption test passed only because it used the one
# template shape (QA REPORT) specified as a single compact block with no
# internal blank line, which gave false confidence.
#
# SCOPE DECISION, taken here rather than left implicit. The reviewer recommended
# exempting a whole report from its header to its end. That is declined, with a
# reason: it would make the guard trivially defeatable by opening any message
# with a report header, and it is not what the CLAUDE.md exemption is for. The
# exemption exists so a REQUIRED FORMAT is not punished. So the structural parts
# of a report are exempt (its header, its field lines, its sub-headers, its
# tables) and free prose inside a report section is scanned like any other
# prose. Bad prose in a Recommendation section is still bad prose.


def test_pentest_scope_block_is_exempt():
    """PENTEST SCOPE was missing from the exempt list entirely, so a
    spec-shaped scope block was blocked outright while process-step-check.py
    requires it present and unfenced."""
    rc, err = _run(
        "Here is the scope.\n\n"
        "PENTEST SCOPE\n"
        "Increment: the **reply** **guard** and its **four** **new** rules\n"
        "Artifacts: reply-style-guard.py\n"
        "Attack surface: transcript parsing\n"
    )
    assert rc == 0, err


def test_multi_section_pentest_report_structure_is_exempt():
    """The canonical PENTEST REPORT is multi-section markdown with blank lines
    between its sub-headers. The skip used to end at the first blank line, so
    the sub-headers and tables from Findings onward were scanned as prose."""
    rc, err = _run(
        "Result below.\n\n"
        "PENTEST REPORT\n"
        "\n"
        "## Findings\n"
        "\n"
        "| id | **sev** | **note** |\n"
        "|---|---|---|\n"
        "| 1 | **high** | **leak** |\n"
        "\n"
        "## Untested Surface\n"
        "\n"
        "The parser was not driven with malformed input.\n"
        "\n"
        "## Recommendation\n"
        "\n"
        "FIX before shipping.\n"
    )
    assert rc == 0, err


def test_multi_section_pm_checkpoint_report_structure_is_exempt():
    rc, err = _run(
        "PM CHECKPOINT REPORT\n"
        "Project: Agent-Governance-Research\n"
        "Phase: 2\n"
        "\n"
        "## Detail\n"
        "\n"
        "| item | **state** |\n"
        "|---|---|\n"
        "| criterion-2 | **open** |\n"
        "\n"
        "Viability: PASS\n"
        "Next: resume criterion-2\n"
    )
    assert rc == 0, err


def test_free_prose_inside_a_report_section_is_still_scanned():
    """Deliberate, see the scope decision above. The exemption protects the
    required format, not everything typed after a report header."""
    rc, _ = _run(
        "PENTEST REPORT\n"
        "\n"
        "## Recommendation\n"
        "\n"
        "This **result** is a **clear** **pivotal** **win** for the harness.\n"
    )
    assert rc == 2


def test_prose_after_a_structured_block_is_still_scanned():
    """The skip must END. If it ran to end-of-text, everything after any report
    would be silently exempt and the guard would be defeated by opening with
    one."""
    rc, _ = _run(
        "QA REPORT\n"
        "PASS: 1 / 1\n"
        "FAIL: none\n"
        "Untested: none deliberately\n"
        "\n"
        "Now some ordinary prose that is a testament to nothing in particular.\n"
    )
    assert rc == 2


def test_frontmatter_regex_cannot_reach_into_a_fence():
    """A leading --- divider plus a --- inside a fenced block let the non-greedy
    frontmatter regex swallow the fence opener, leaving the code to be scanned
    as prose. Fences are stripped first now."""
    rc, err = _run(
        "---\n"
        "Some prose after a horizontal rule.\n"
        "\n"
        "```yaml\n"
        "---\n"
        "a: **one** **two** **three** **four** **five**\n"
        "```\n"
        "Closing prose.\n"
    )
    assert rc == 0, err


def test_underscores_in_technical_prose_are_allowed():
    """The underscore entry fired on this vault's own subject matter and was
    removed. These three sentences all blocked before the fix."""
    for sentence in [
        "The Python file uses underscores in variable names, not hyphens, per PEP 8.",
        "Rename the field to use an underscore so it matches the schema.",
        "Hook files are kebab-case while their test files use underscores throughout.",
    ]:
        rc, _ = _run(sentence)
        assert rc == 0, sentence


def test_block_message_offers_the_backtick_escape_hatch():
    """The guard cannot tell using a word from naming one. It fired on its first
    live response for quoting its own wordlist as examples. Inline code is the
    exemption, so the message has to say so."""
    _, err = _run("Words like delve are on the list.")
    assert "backtick" in err.lower()


def test_stderr_is_written_before_the_log_call():
    """em-dash-guard.py makes this ordering explicit: nothing between the
    verdict and the block may be able to swallow it."""
    src = open(HOOK_PATH, encoding="utf-8").read()
    assert src.index("sys.stderr.write") < src.index('_log("block"')


def test_bold_in_a_report_sub_header_is_exempt():
    """The discriminating test for the multi-section fix, added after QA found
    the two report-structure tests above passed against the PRE-FIX hook too and
    therefore proved nothing.

    Before the fix the skip ended at the first blank line, so a report's own
    "## " sub-headers were scanned as ordinary prose. Given the scope decision
    recorded above, that free prose inside a report IS scanned, the sub-header
    lines are the ONLY thing this fix changes. That makes the defect narrower
    than the review stated: its severity assessment assumed the whole report
    from header to end would become exempt, which was declined.
    """
    rc, err = _run(
        "PENTEST REPORT\n"
        "\n"
        "## **Findings**\n"
        "\n"
        "## **Severity Rubric**\n"
        "\n"
        "## **Untested Surface**\n"
        "\n"
        "## **Recommendation**\n"
    )
    assert rc == 0, err
