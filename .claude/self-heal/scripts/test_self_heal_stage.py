"""Tests for self_heal_stage.py: the improver workflow's staging guard.

Written before the helper (declarative-first). The helper's `verify` mode
reads the staged path list and fails on any forbidden path; pure over its
inputs except for the git call, which is injectable. (Its former `pathspec`
mode and tests were retired with the write-path build of 2026-09-18.)
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
VAULT = HERE.parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("self_heal_stage", HERE / "self_heal_stage.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def targets_file(tmp_path):
    p = tmp_path / "targets.json"
    p.write_text(json.dumps({
        "forbidden_paths": [
            ".claude/hooks/bash-safety-guard.py",
            "CLAUDE.md",
            ".claude/rules/**",
            ".github/**",
            ".claude/self-heal/**",
        ]
    }), encoding="utf-8")
    return p




def test_verify_passes_on_allowed_paths(targets_file):
    stage = _load()
    staged = [".claude/scripts/foo.py", "Projects/X/work/2026-09-16-y.md"]
    assert stage.forbidden_staged(staged, targets_file) == []


def test_verify_catches_nested_and_exact_forbidden_paths(targets_file):
    stage = _load()
    staged = [
        ".claude/scripts/foo.py",
        ".claude/rules/plain-language.md",
        ".github/workflows/vault-self-heal.yml",
        "CLAUDE.md",
        "self-heal-run.jsonl",
    ]
    bad = stage.forbidden_staged(staged, targets_file)
    assert set(bad) == {
        ".claude/rules/plain-language.md",
        ".github/workflows/vault-self-heal.yml",
        "CLAUDE.md",
        "self-heal-run.jsonl",
    }


def test_verify_is_case_and_homoglyph_hostile(targets_file):
    stage = _load()
    # a Cyrillic 'a' in CLAUDE.md-like names is not the forbidden path, but any
    # path outside ASCII under .claude/** is refused by the loop's path hygiene
    # (phase (b)); the staging guard refuses it too rather than letting it through.
    bad = stage.forbidden_staged([".claude/scripts/fаke.py"], targets_file)
    assert bad == [".claude/scripts/fаke.py"]


def test_main_verify_exit_codes(targets_file, tmp_path):
    stage = _load()
    good = stage.main(["verify", "--targets", str(targets_file)],
                      staged_fn=lambda: [".claude/scripts/ok.py"])
    assert good == 0
    bad = stage.main(["verify", "--targets", str(targets_file)],
                     staged_fn=lambda: ["CLAUDE.md"])
    assert bad == 1








def test_ci_settings_permissions_mirror_targets_json():
    """The runner's permission rules are derived from targets.json: every
    class path is allowed for Edit and Write, every forbidden path is
    denied for both, and nothing else is allowed for Edit or Write."""
    targets = json.loads((VAULT / ".claude" / "self-heal" / "targets.json").read_text(encoding="utf-8"))
    cs = json.loads((VAULT / ".claude" / "self-heal" / "ci-settings.json").read_text(encoding="utf-8"))
    allow = set(cs["permissions"]["allow"])
    deny = set(cs["permissions"]["deny"])
    for c in targets["allowed_classes"]:
        for p in c["paths"]:
            assert f"Edit({p})" in allow and f"Write({p})" in allow, p
    for p in targets["forbidden_paths"]:
        assert f"Edit({p})" in deny and f"Write({p})" in deny, p
    edit_write_allows = {a for a in allow if a.startswith(("Edit(", "Write("))}
    expected = {f"{t}({p})" for c in targets["allowed_classes"] for p in c["paths"] for t in ("Edit", "Write")}
    assert edit_write_allows == expected
    assert "Bash" in allow


def test_ci_settings_deny_covers_every_class_exclude():
    """Write-path build 2026-09-18 (R6): each class's excludes are denied for
    Edit and Write, a bare-filename exclude expanded against every path of
    its class, a slashed exclude used as is."""
    import posixpath
    targets = json.loads((VAULT / ".claude" / "self-heal" / "targets.json").read_text(encoding="utf-8"))
    cs = json.loads((VAULT / ".claude" / "self-heal" / "ci-settings.json").read_text(encoding="utf-8"))
    deny = set(cs["permissions"]["deny"])
    seen = 0
    for c in targets["allowed_classes"]:
        for ex in c.get("excludes", []):
            pats = [ex] if "/" in ex else sorted({posixpath.dirname(p) + "/" + ex for p in c["paths"]})
            for pat in pats:
                assert f"Edit({pat})" in deny and f"Write({pat})" in deny, (c["class"], pat)
                seen += 1
    assert seen >= 2
