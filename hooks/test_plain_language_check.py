"""Tests for plain_language_check.py, the T1 plain-language checker module.

Written BEFORE the module (declarative-first, CLAUDE.md Build doctrine).
Fixtures reuse the plan of record's own positive and negative examples per rule
([[2026-08-10-plain-language-standard-plan]] section 2). pytest style, no unittest.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "plain_language_check",
    str(Path(__file__).parent / "plain_language_check.py"),
)
plc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plc)

ALL_RULES = [f"PL-{i}" for i in range(1, 11)]


def counts(text):
    return plc.scan(text)["per_rule_finding_counts"]


# ---------------------------------------------------------------- rule fixtures

def test_pl1_positive_zero_findings():
    text = "Run the indexer. Then read the last 20 lines of the log.\n"
    assert counts(text)["PL-1"] == 0


def test_pl1_negative_flags_long_sentence():
    text = ("In order to make sure that the indexer has completed successfully "
            "it is recommended that the log file be examined carefully for any "
            "errors that may have occurred at any point during the run.\n")
    assert counts(text)["PL-1"] >= 1


def test_pl1_step_threshold_is_tighter():
    # 22 words: legal as prose (<= 25), over the 20-word numbered-step cap.
    words = " ".join(["word"] * 21)
    prose = f"This {words}.\n"
    step = f"1. This {words}.\n"
    assert counts(prose)["PL-1"] == 0
    assert counts(step)["PL-1"] == 1


def test_pl2_positive_zero_findings():
    text = "1. Stop the workflow.\n2. Export the JSON.\n3. Check the credentials.\n"
    assert counts(text)["PL-2"] == 0


def test_pl2_negative_flags_chained_step():
    text = ("1. Stop the workflow and then export the JSON and check the "
            "credentials before continuing.\n")
    assert counts(text)["PL-2"] >= 1


def test_pl3_positive_zero_findings():
    text = "The hook blocks the write and logs the event.\n"
    assert counts(text)["PL-3"] == 0


def test_pl3_negative_flags_passive():
    text = "The write is blocked and the event is logged.\n"
    assert counts(text)["PL-3"] >= 1


def test_pl4_positive_zero_findings():
    text = "Three hooks failed: `a.py`, `b.py`, `c.py`.\n"
    assert counts(text)["PL-4"] == 0


def test_pl4_negative_flags_vague_quantifiers():
    text = "Several hooks appear to have various issues.\n"
    assert counts(text)["PL-4"] >= 2


def test_pl5_positive_zero_findings():
    text = "Use the API (Application Programming Interface) before you start the export.\n"
    assert counts(text)["PL-5"] == 0


def test_pl5_negative_flags_formal_words():
    text = "Utilize the API prior to commencing the export.\n"
    assert counts(text)["PL-5"] >= 3


def test_pl7_positive_zero_findings():
    text = "The guard fails open on internal error.\n"
    assert counts(text)["PL-7"] == 0


def test_pl7_negative_flags_filler():
    text = ("It should be noted that the guard essentially fails open whenever "
            "an internal error happens to occur.\n")
    assert counts(text)["PL-7"] >= 2


def test_pl8_positive_expanded_abbreviation_silent():
    text = ("WDAC (Windows Defender Application Control) blocks the import. "
            "Later mentions may say WDAC.\n")
    assert counts(text)["PL-8"] == 0


def test_pl8_negative_flags_unexpanded_abbreviation():
    text = "The fix is gated on WDAC and the redist.\n"
    assert counts(text)["PL-8"] >= 1


def test_pl8_flags_each_distinct_token_once():
    text = "WDAC blocks it. WDAC still blocks it. WDAC forever.\n"
    assert counts(text)["PL-8"] == 1


# ------------------------------------------------- structural zeros (PL-6, PL-9)

def test_pl6_and_pl9_structurally_zero():
    text = "the hook warn rate calibration window measurement plan is used here\n"
    c = counts(text)
    assert c["PL-6"] == 0
    assert c["PL-9"] == 0


# ---------------------------------------------------------- all-ten-keys contract

def test_clean_document_returns_all_ten_keys_all_zero():
    result = plc.scan("The hook works.\n")
    c = result["per_rule_finding_counts"]
    assert sorted(c.keys()) == sorted(ALL_RULES)
    assert all(v == 0 for v in c.values())
    assert result["total_findings"] == 0


def test_total_findings_is_sum_of_per_rule_counts():
    result = plc.scan("Utilize this. Several various issues furthermore basically.\n")
    c = result["per_rule_finding_counts"]
    assert result["total_findings"] == sum(c.values())


# ------------------------------------------------------------------- exemptions

def test_fenced_code_exempt():
    text = "```\nUtilize the API prior to commencing the export. Several various.\n```\n"
    assert plc.scan(text)["total_findings"] == 0


def test_inline_code_exempt():
    text = "The word `utilize` and the phrase `prior to` are banned.\n"
    assert counts(text)["PL-5"] == 0


def test_table_rows_exempt():
    text = "| word | fix |\n|---|---|\n| utilize | use |\n| several | three |\n"
    assert plc.scan(text)["total_findings"] == 0


def test_frontmatter_exempt():
    text = "---\ntitle: several various utilize prior to commencing\n---\nClean prose.\n"
    assert plc.scan(text)["total_findings"] == 0


# --------------------------------------------------------- MM1 marker behavior

MM1_CONFIRMATION = (
    "This command permanently deletes the production table and it cannot be "
    "undone by any later action, so you must confirm that a verified backup "
    "exists before you run the command and you must utilize it only after the "
    "owner has approved the deletion in writing.\n"
)


def test_mm1_marked_block_total_exemption():
    """No rule, PL-1 included, may fire inside a marked MM1 block."""
    text = "<!-- MM1 -->\n" + MM1_CONFIRMATION + "<!-- /MM1 -->\n"
    result = plc.scan(text)
    assert result["total_findings"] == 0
    assert all(v == 0 for v in result["per_rule_finding_counts"].values())
    assert result["marker_advisories"] == []


def test_unmarked_mm1_class_content_still_flagged():
    """The accepted residual risk, made visible: same content unmarked gets findings."""
    result = plc.scan(MM1_CONFIRMATION)
    assert result["per_rule_finding_counts"]["PL-1"] >= 1
    assert result["total_findings"] >= 1


def test_unclosed_mm1_exempts_to_eof_with_hygiene_advisory():
    text = "<!-- MM1 -->\n" + MM1_CONFIRMATION + "More exempt text with several various issues.\n"
    result = plc.scan(text)
    assert result["total_findings"] == 0
    assert all(v == 0 for v in result["per_rule_finding_counts"].values())
    assert len(result["marker_advisories"]) == 1
    assert "MM1" in result["marker_advisories"][0]


def test_nested_mm1_markers_one_span_to_outermost_close():
    text = (
        "<!-- MM1 -->\nouter exempt start\n<!-- MM1 -->\ninner utilize prior to commencing\n"
        "<!-- /MM1 -->\nstill exempt because the outermost close has not yet arrived even "
        "though this particular sentence runs well past the twenty five word cap for prose\n"
        "<!-- /MM1 -->\nUtilize the API prior to commencing the export.\n"
    )
    result = plc.scan(text)
    c = result["per_rule_finding_counts"]
    assert c["PL-1"] == 0, "text between outermost markers must stay exempt"
    assert c["PL-5"] >= 3, "text after the outermost close must be scanned"
    assert result["marker_advisories"] == []


def test_mm1_marker_inside_inline_code_does_not_open_span():
    text = "The marker `<!-- MM1 -->` is written in backticks here.\nUtilize the export.\n"
    assert counts(text)["PL-5"] >= 1


# ------------------------------------------------------------- PL-10 doctrine drift

def test_pl10_every_rule_block_carries_provenance():
    rules_path = Path(__file__).resolve().parents[1] / "plain-language-rules.md"
    text = rules_path.read_text(encoding="utf-8")
    blocks = [b for b in re.split(r"(?=^### PL-)", text, flags=re.M) if b.startswith("### PL-")]
    assert len(blocks) == 10
    for block in blocks:
        body = re.split(r"\n#{2,3} ", block)[0]
        assert "**Provenance**:" in body, block.splitlines()[0]


# -------------------------------------------------------------------- CLI mode

def test_cli_exits_zero_and_survives_unreadable_file(tmp_path, capsys):
    good = tmp_path / "good.md"
    good.write_text("Utilize the API prior to commencing the export.\n", encoding="utf-8")
    rc = plc.cli([str(good), str(tmp_path / "does-not-exist.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "good.md" in out
    assert "PL-5" in out


def test_cli_exit_zero_on_clean_file(tmp_path, capsys):
    clean = tmp_path / "clean.md"
    clean.write_text("The hook works.\n", encoding="utf-8")
    rc = plc.cli([str(clean)])
    assert rc == 0
    assert "clean.md" in capsys.readouterr().out


def test_cli_double_star_glob_recurses_into_nested_dirs(tmp_path, capsys):
    """Regression for the 2026-08-11 post-review Finding 1 undercount: a
    `docs/**/*.md` argument must reach files nested under subdirectories, not
    just top-level `docs/*.md` matches. Root cause was the invocation scope
    (a non-recursive single-star pattern), not this glob call, but this test
    locks the correct recursive behavior in so a future caller trusts it."""
    docs = tmp_path / "docs"
    (docs / "adr").mkdir(parents=True)
    (docs / "concepts").mkdir(parents=True)
    (docs / "top.md").write_text("Top level.\n", encoding="utf-8")
    (docs / "adr" / "nested.md").write_text("Nested one.\n", encoding="utf-8")
    (docs / "concepts" / "nested2.md").write_text("Nested two.\n", encoding="utf-8")

    rc = plc.cli([str(docs / "*.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TOTALS (1 files)" in out, "single-star must NOT reach nested files"

    rc = plc.cli([str(docs / "**" / "*.md")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "TOTALS (3 files)" in out, "double-star must reach all nested files"
    assert "nested.md" in out and "nested2.md" in out


def test_cli_bare_directory_argument_errors_instead_of_silently_skipping(tmp_path, capsys):
    """A bare directory (no glob wildcard) is not walked; the CLI reports it
    as an unreadable path rather than silently contributing zero files with
    no visible signal. Documents current behavior so a caller who passes a
    directory by mistake gets a loud ERROR row, not a quiet undercount."""
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "file.md").write_text("Text.\n", encoding="utf-8")

    rc = plc.cli([str(docs)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "ERROR" in out
    assert "TOTALS (0 files)" in out


# ------------------------------------------------------------ threshold constants

def test_pl1_thresholds_are_named_module_constants():
    """Calibration starting values, retunable as a one-line diff (Stage 3)."""
    assert plc.PROSE_SENTENCE_MAX == 25
    assert plc.STEP_SENTENCE_MAX == 20
