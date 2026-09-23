"""Tests for lint_pass_root_stray.py (ROAD-3, Pass O).

Declarative-first: written before the implementation. Tmp root dir plus
--state-file override; no live allowlist is written by any test.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_root_stray.py"


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def make_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "CLAUDE.md").write_text("x", encoding="utf-8")
    (root / "Projects").mkdir()
    (root / "Notes").mkdir()
    return root


def test_seed_then_clean(tmp_path):
    root = make_root(tmp_path)
    state = tmp_path / "root-allowlist.json"
    r = run("--seed", "--root", str(root), "--state-file", str(state))
    assert r.returncode == 0, r.stdout + r.stderr
    entries = json.loads(state.read_text(encoding="utf-8"))["entries"]
    assert sorted(entries) == ["CLAUDE.md", "Notes", "Projects"]
    r2 = run("--root", str(root), "--state-file", str(state))
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "ROOT_STRAY" not in r2.stdout
    assert "entries=" in r2.stdout  # always-print


def test_stray_file_and_dir_detected(tmp_path):
    root = make_root(tmp_path)
    state = tmp_path / "root-allowlist.json"
    run("--seed", "--root", str(root), "--state-file", str(state))
    (root / "stray.txt").write_text("x", encoding="utf-8")
    (root / "StrayDir").mkdir()
    r = run("--root", str(root), "--state-file", str(state))
    assert r.returncode == 1
    findings = [l for l in r.stdout.splitlines() if l.startswith("ROOT_STRAY")]
    assert len(findings) == 2
    assert any("name=stray.txt" in f for f in findings)
    assert any("name=StrayDir" in f for f in findings)


def test_missing_allowlist_exits_2(tmp_path):
    root = make_root(tmp_path)
    r = run("--root", str(root), "--state-file", str(tmp_path / "absent.json"))
    assert r.returncode == 2
    assert "ROOT_STRAY" not in r.stdout
