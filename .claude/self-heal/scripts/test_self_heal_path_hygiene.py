"""Tests for self_heal_path_hygiene.py, and for the rule that the three
loop steps (apply, stage, accept) give the same verdict on the same path.

Before 2026-09-20 each step had its own copy of the check. The parity
tests below failed against those copies: the staging guard let whitespace,
control characters, absolute paths and a '.' segment through, and the
accept step let a '.' segment, an empty segment and an absolute path
through.

The rules have two tiers (see the module docstring). Apply and stage use
the hard tier, because a violation there ends the round in a red run.
The mixed character script heuristic is the review tier: only the accept
step applies it, so a person decides. Architect review of 2026-09-20,
MEDIUM 1.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import self_heal_path_hygiene as hyg  # noqa: E402

BS = chr(92)
TAB = chr(9)
NL = chr(10)
CYR_A = chr(0x0430)      # Cyrillic small a
CYR_U = chr(0x0443)      # Cyrillic small u
FULLWIDTH_A = chr(0xFF41)
ZWSP = chr(0x200B)       # zero width space, category Cf

HOSTILE = {
    "empty": "",
    "absolute posix": "/etc/passwd",
    "absolute drive": "C:/Windows/x.py",
    "backslash": ".claude" + BS + "scripts" + BS + "x.py",
    "dotdot": ".claude/scripts/../rules/x.md",
    "dot segment": ".claude/scripts/./x.py",
    "empty segment": ".claude//scripts/x.py",
    "trailing space": ".claude/scripts/test_x.py ",
    "leading space": ".claude/scripts/ test_x.py",
    "tab": ".claude/scripts/test" + TAB + "x.py",
    "newline": ".claude/scripts/test_x.py" + NL,
    "zero width space": "Projects/no" + ZWSP + "te.md",
    "homoglyph under .claude": ".claude/scripts/trust_contract_verif" + CYR_U + ".py",
    "homoglyph outside .claude": "Projects/Vault-Maintenance/work/n" + CYR_A + "me.md",
    "nfkc unstable": "Projects/" + FULLWIDTH_A + "bc.md",
    "non ascii under .claude": ".claude/scripts/caf" + chr(0xE9) + ".py",
    "non ascii in a .claude sibling": ".claude-x/caf" + chr(0xE9) + ".py",
}

CLEAN = [
    ".claude/scripts/test_x.py",
    ".claude/hooks/_subagent_quality_logic.py",
    "Projects/Vault-Maintenance/work/2026-09-19-note.md",
    "Projects/Personal/za" + chr(0x17C) + chr(0xF3) + chr(0x142) + chr(0x107) + ".md",  # Polish, one script
    "Resources/KB/index.md",
    "a",
    "dir/",
]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(name, None)
    return mod


@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_module_refuses_every_hostile_path(label):
    assert hyg.hygiene_reasons(HOSTILE[label]), label
    if label not in REVIEW_TIER_ONLY:
        assert hyg.hard_reasons(HOSTILE[label]), label


@pytest.mark.parametrize("path", CLEAN)
def test_module_passes_clean_paths(path):
    assert hyg.hygiene_reasons(path) == []


def test_reasons_name_the_rule_that_fired():
    assert any("backslash" in r for r in hyg.hygiene_reasons("a" + BS + "b"))
    assert any("mixes character scripts" in r for r in hyg.hygiene_reasons(HOSTILE["homoglyph outside .claude"]))
    assert any("NFKC" in r for r in hyg.hygiene_reasons(HOSTILE["nfkc unstable"]))
    assert any("control character" in r for r in hyg.hygiene_reasons(HOSTILE["zero width space"]))
    assert any("printable ASCII" in r for r in hyg.hygiene_reasons(HOSTILE["non ascii in a .claude sibling"]))


def test_one_path_can_carry_several_reasons():
    reasons = hyg.hygiene_reasons(".claude/scripts/../ x" + TAB + ".py")
    assert len(reasons) >= 3


# --- parity: the three steps agree -----------------------------------------

def _apply_refuses(path: str) -> bool:
    return bool(_load("self_heal_apply")._hygiene_reasons(path))


def _stage_refuses(path: str) -> bool:
    return _load("self_heal_stage")._hygiene_violation(path)


def _accept_refuses(path: str) -> bool:
    return _load("self_heal_accept").check_path_hygiene_one(path) is not None


# Documented differences between the steps. Everything else must agree.
ACCEPT_DIFFERS = {
    # accept normalises first and judges the normal form, by design; a
    # fullwidth letter folds to plain ASCII and is then clean there.
    "nfkc unstable",
    # a FileChange side that does not exist is None or "", so accept skips
    # an empty path before the check. Pinned by its own test below.
    "empty",
}
REVIEW_TIER_ONLY = {
    # mixed scripts outside .claude: accept sends it to the owner, apply and
    # stage let it through so the round still produces a pull request.
    "homoglyph outside .claude",
}


@pytest.mark.parametrize("label", sorted(HOSTILE))
def test_the_three_steps_agree_on_every_hostile_path(label):
    path = HOSTILE[label]
    hard = {"apply": _apply_refuses(path), "stage": _stage_refuses(path)}
    if label in REVIEW_TIER_ONLY:
        assert not any(hard.values()), hard
        assert _accept_refuses(path)
        return
    assert all(hard.values()), hard
    if label not in ACCEPT_DIFFERS:
        assert _accept_refuses(path)


def test_accept_skips_an_empty_path_and_folds_an_nfkc_unstable_one():
    """The two documented differences, derived from accept's real function."""
    accept = _load("self_heal_accept")
    assert accept.check_path_hygiene_one("") is None
    assert accept.check_path_hygiene_one(HOSTILE["nfkc unstable"]) is None


def test_documented_differences_name_real_fixtures():
    assert ACCEPT_DIFFERS | REVIEW_TIER_ONLY <= set(HOSTILE)


def test_hard_tier_never_carries_the_mixed_script_heuristic():
    """A red run for an honest file name is the failure this split prevents.
    Greek mu inside a Latin name, outside .claude: a pull request for the
    owner, not a dead round."""
    honest = "Projects/Vault-Maintenance/work/latency_" + chr(0x3BC) + "s.md"
    assert hyg.hard_reasons(honest) == []
    assert any("mixes character scripts" in r for r in hyg.review_reasons(honest))
    assert hyg.hygiene_reasons(honest) == hyg.hard_reasons(honest) + hyg.review_reasons(honest)
    for label in HOSTILE:
        assert not any("mixes character scripts" in r for r in hyg.hard_reasons(HOSTILE[label])), label


def test_under_claude_a_homoglyph_is_refused_by_the_hard_tier_too():
    """The ASCII rule covers it there, so apply and stage still stop it."""
    assert hyg.hard_reasons(HOSTILE["homoglyph under .claude"])
    assert hyg.hard_reasons(".claude/scripts/latency_" + chr(0x3BC) + "s.py")


def test_segment_rules_report_the_one_that_fired():
    assert hyg.hard_reasons("a/../b") == ["contains a '..' segment"]
    assert hyg.hard_reasons("a/./b") == ["contains a '.' segment"]
    assert hyg.hard_reasons("a//b") == ["contains an empty segment"]


@pytest.mark.parametrize("path", CLEAN)
def test_all_three_steps_pass_the_same_clean_path(path):
    assert not _apply_refuses(path)
    assert not _stage_refuses(path)
    assert not _accept_refuses(path)


def test_no_step_keeps_a_private_copy_of_the_rules():
    """The drift this module ended must not come back: the three callers
    hold no unicodedata-based rule of their own for path hygiene."""
    for name in ("self_heal_apply", "self_heal_stage"):
        text = (HERE / f"{name}.py").read_text(encoding="utf-8")
        assert "self_heal_path_hygiene" in text, name
        assert ".hard_reasons(path)" in text, f"{name} must use the hard tier"
        assert "unicodedata" not in text, f"{name} still imports unicodedata"
    accept = (HERE / "self_heal_accept.py").read_text(encoding="utf-8")
    assert "self_heal_path_hygiene" in accept
    assert "def _segment_has_mixed_scripts" not in accept
    assert "def _char_script_bucket" not in accept


def test_accept_reports_against_the_raw_path():
    note = _load("self_heal_accept").check_path_hygiene_one(".claude/scripts/ x.py")
    assert note is not None and "[suspicious-path]" in note and "' x.py'" in note


def test_every_tracked_path_of_this_repo_is_clean():
    """The merged check is the strict union of the three old ones. It must
    not refuse any path the repo already tracks, or an ordinary round that
    touches such a file would go red."""
    import subprocess
    root = HERE.parents[2]
    proc = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        pytest.skip("not inside a git checkout with tracked files")
    paths = [p for p in proc.stdout.decode("utf-8", "surrogateescape").split(chr(0)) if p]
    bad = [p for p in paths if hyg.hygiene_reasons(p)]
    assert bad == []


def test_the_module_is_loaded_once_per_process_by_apply_and_stage():
    """Architect review LOW 1: the callers used to re-read and re-execute
    the module for every path they checked."""
    for name in ("self_heal_apply", "self_heal_stage"):
        mod = _load(name)
        assert mod._hygiene() is mod._hygiene(), name
