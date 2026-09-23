"""Tests for lint_pass_tag_canon_divergence.py (ROAD-4, Pass P).

Declarative-first: written before the implementation. Fixture source files
with known divergences; fail-loud cases for a renamed set variable and a
missing CLAUDE.md anchor line.
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_tag_canon_divergence.py"

HOOK1 = '''CANONICAL_TAGS = {
    "idea", "research", "extra-in-hook1",
    "active",
}
'''
HOOK2 = '''FALLBACK_CANONICAL_TAGS = {
    "idea", "research",
    "active",
    "project/x", "project/y",
}
'''
CLAUDE_MD = (
    "## Conventions\n\n"
    "- Tags (canonical, spec R4 v2): `project/<name>`, `idea`, `research`\n"
    "- Status: `active`, `waiting`, `done`, `archived` "
    "(bare strings in frontmatter `status:` field; spec R5)\n"
)


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def write_sources(tmp_path, hook1=HOOK1, hook2=HOOK2, claude=CLAUDE_MD):
    p1 = tmp_path / "tag-variant-check.py"
    p2 = tmp_path / "vault-structure-check.py"
    p3 = tmp_path / "CLAUDE.md"
    p1.write_text(hook1, encoding="utf-8")
    p2.write_text(hook2, encoding="utf-8")
    p3.write_text(claude, encoding="utf-8")
    return p1, p2, p3


def test_known_divergences(tmp_path):
    p1, p2, p3 = write_sources(tmp_path)
    r = run("--tag-variant-source", str(p1), "--vault-structure-source", str(p2),
            "--claude-md", str(p3))
    # divergent: extra-in-hook1 (only hook1); waiting/done/archived (only claude-md)
    # project/* members are exempt everywhere
    assert r.returncode == 1, r.stdout + r.stderr
    findings = [l for l in r.stdout.splitlines() if l.startswith("TAG_CANON_DIVERGENCE")]
    tags = sorted(f.split("tag=")[1].split()[0] for f in findings)
    assert tags == ["archived", "done", "extra-in-hook1", "waiting"]
    assert not any("project/" in t for t in tags)
    # non-tag backticked mentions on the anchor lines never become findings
    assert "status:" not in tags
    one = [f for f in findings if "tag=extra-in-hook1" in f][0]
    assert "present=" in one and "absent=" in one
    assert "sizes" in r.stdout or "divergent=" in r.stdout  # always-print


def test_full_agreement_clean(tmp_path):
    hook1 = 'CANONICAL_TAGS = {"idea", "active", "waiting", "done", "archived", "research"}\n'
    hook2 = 'FALLBACK_CANONICAL_TAGS = {"idea", "active", "waiting", "done", "archived", "research", "project/z"}\n'
    p1, p2, p3 = write_sources(tmp_path, hook1=hook1, hook2=hook2)
    r = run("--tag-variant-source", str(p1), "--vault-structure-source", str(p2),
            "--claude-md", str(p3))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TAG_CANON_DIVERGENCE" not in r.stdout


def test_renamed_set_variable_exits_2(tmp_path):
    p1, p2, p3 = write_sources(tmp_path, hook1='RENAMED_TAGS = {"idea"}\n')
    r = run("--tag-variant-source", str(p1), "--vault-structure-source", str(p2),
            "--claude-md", str(p3))
    assert r.returncode == 2
    assert "TAG_CANON_DIVERGENCE" not in r.stdout


def test_missing_claude_anchor_exits_2(tmp_path):
    p1, p2, p3 = write_sources(tmp_path, claude="# no tags line here\n")
    r = run("--tag-variant-source", str(p1), "--vault-structure-source", str(p2),
            "--claude-md", str(p3))
    assert r.returncode == 2
