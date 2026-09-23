"""Tests for lint_pass_memory_overfill.py (ROAD-2, Pass N).

Declarative-first: written before the implementation. Fixtures live in tmp;
no live state or live memory file is touched.
"""
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_memory_overfill.py"
REAL_SOURCE = SCRIPTS / "check_memory_index.py"

sys.path.insert(0, str(SCRIPTS))
import lint_pass_memory_overfill as _module  # noqa: E402


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def test_under_target_clean(tmp_path):
    mem = tmp_path / "MEMORY.md"
    mem.write_text("short\n" * 10, encoding="utf-8")
    r = run("--memory-file", str(mem), "--source", str(REAL_SOURCE))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MEMORY_OVERFILL" not in r.stdout
    # always-print measurement line present even when clean
    assert "bytes=" in r.stdout and "target=" in r.stdout


def test_over_target_one_finding(tmp_path):
    mem = tmp_path / "MEMORY.md"
    long_line = "x" * 250
    mem.write_text((long_line + "\n") * 100, encoding="utf-8", newline="\n")  # 25100 bytes > 17100
    r = run("--memory-file", str(mem), "--source", str(REAL_SOURCE))
    assert r.returncode == 1, r.stdout + r.stderr
    findings = [l for l in r.stdout.splitlines() if l.startswith("MEMORY_OVERFILL")]
    assert len(findings) == 1
    assert "bytes=25100" in findings[0]
    assert "long_lines=100" in findings[0]


def test_doctored_source_exits_2(tmp_path):
    mem = tmp_path / "MEMORY.md"
    mem.write_text("short\n", encoding="utf-8")
    doctored = tmp_path / "check_memory_index.py"
    doctored.write_text(
        REAL_SOURCE.read_text(encoding="utf-8").replace("target < ", "goal < "),
        encoding="utf-8",
    )
    r = run("--memory-file", str(mem), "--source", str(doctored))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "MEMORY_OVERFILL" not in r.stdout


def test_missing_memory_file_exits_2(tmp_path):
    r = run("--memory-file", str(tmp_path / "absent.md"), "--source", str(REAL_SOURCE))
    assert r.returncode == 2


# --- TASK-034 (migration plan Phase 1, 2026-09-15): VAULT_MEMORY_ROOT override
# and mirror fallback -----------------------------------------------------------

def test_vault_memory_root_env_overrides_derivation(tmp_path):
    """VAULT_MEMORY_ROOT wins outright over the Path.home()-derived path when
    set, exercising derive_memory_file() itself (no --memory-file passed)."""
    mem_root = tmp_path / "memroot"
    mem_root.mkdir()
    (mem_root / "MEMORY.md").write_text("short\n", encoding="utf-8")
    env = dict(os.environ, VAULT_MEMORY_ROOT=str(mem_root), PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", str(REAL_SOURCE)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "DERIVATION FAILURE" not in r.stdout
    assert "bytes=" in r.stdout and "target=" in r.stdout


def test_vault_memory_root_falls_back_to_mirror_when_live_path_absent(tmp_path, monkeypatch):
    """VAULT_MEMORY_ROOT unset AND the live Path.home()-derived path absent:
    derive_memory_file() falls back to the committed mirror
    .claude/user-claude-mirror/memory/MEMORY.md (mirror_user_claude.py's own
    DEST_REL, refreshed every 30 minutes by auto-commit.ps1)."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("VAULT_MEMORY_ROOT", raising=False)
    mirror_file = _module.VAULT / ".claude" / "user-claude-mirror" / "memory" / "MEMORY.md"
    assert mirror_file.is_file(), (
        "live mirror must exist on this machine for the fallback path to be exercised"
    )
    assert _module.derive_memory_file() == mirror_file


def test_cli_falls_back_to_mirror_end_to_end(tmp_path):
    """Same fallback, exercised through the real subprocess CLI (TASK-034's
    own CHECK): with VAULT_MEMORY_ROOT unset and USERPROFILE pointed at a
    fake, empty home, the script must still find the mirror and print a
    normal measurement line, never DERIVATION FAILURE."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    env = dict(os.environ, PYTHONIOENCODING="utf-8", USERPROFILE=str(fake_home),
              HOME=str(fake_home))
    env.pop("VAULT_MEMORY_ROOT", None)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--source", str(REAL_SOURCE)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "DERIVATION FAILURE" not in r.stdout
    assert "bytes=" in r.stdout and "target=" in r.stdout
