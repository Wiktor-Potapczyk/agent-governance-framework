"""Tests for repo_release.py, run against a throwaway git repo in tmp_path.

    "C:\\Program Files\\Python314\\python.exe" -m pytest test_repo_release.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "repo_release.py"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout


def run_script(repo: Path, *extra_args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *extra_args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV,
    )


def make_commit(
    repo: Path, filename: str, content: str, message: str, commit_date: str | None = None
) -> None:
    (repo / filename).write_text(content, encoding="utf-8", newline="\n")
    git(repo, "add", filename)
    env = dict(os.environ)
    if commit_date:
        stamp = f"{commit_date}T12:00:00"
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
    proc = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", message],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "test@example.com")
    git(r, "config", "user.name", "Test User")
    git(r, "config", "commit.gpgsign", "false")
    git(r, "config", "core.autocrlf", "false")
    # Seed commit is explicitly dated to match its own CHANGELOG heading
    # (2026-08-01) so the boundary-mapping test exercises the real "map a
    # changelog heading to a commit" path rather than the wall-clock date
    # pytest happens to run under.
    make_commit(
        r, "CHANGELOG.md",
        "# Changelog\n\n## 2026-08-01: seed entry\n\n- initial commit\n",
        "chore: seed changelog", commit_date="2026-08-01",
    )
    return r


def test_first_release_boundary_from_changelog(repo: Path):
    make_commit(repo, "a.txt", "a", "feat: add a")
    make_commit(repo, "b.txt", "b", "feat: add b")

    proc = run_script(repo, "--date", "2026-08-15")

    assert proc.returncode == 0, proc.stderr
    assert "2026-08-01" in proc.stdout  # boundary resolved from the changelog heading
    assert "no v* tags" in proc.stdout
    assert "feat: add a" in proc.stdout
    assert "feat: add b" in proc.stdout

    tags = git(repo, "tag", "-l").split()
    assert "v2026.08.15" in tags


def test_entry_generation_determinism(repo: Path):
    make_commit(repo, "a.txt", "a", "feat: add a")

    first = run_script(repo, "--date", "2026-08-15", "--dry-run")
    second = run_script(repo, "--date", "2026-08-15", "--dry-run")

    assert first.returncode == 0 and second.returncode == 0
    assert first.stdout == second.stdout


def test_tag_creation(repo: Path):
    make_commit(repo, "a.txt", "a", "feat: add a")

    proc = run_script(repo, "--date", "2026-08-15")
    assert proc.returncode == 0, proc.stderr

    tags = git(repo, "tag", "-l").split()
    assert "v2026.08.15" in tags

    tag_body = git(repo, "for-each-ref", "--format=%(contents)", "refs/tags/v2026.08.15")
    assert "## v2026.08.15 (2026-08-15)" in tag_body
    assert "- feat: add a" in tag_body


def test_same_day_suffix(repo: Path):
    make_commit(repo, "a.txt", "a", "feat: add a")
    first = run_script(repo, "--date", "2026-08-15")
    assert first.returncode == 0, first.stderr
    assert "v2026.08.15" in git(repo, "tag", "-l").split()

    make_commit(repo, "c.txt", "c", "feat: add c")
    second = run_script(repo, "--date", "2026-08-15")
    assert second.returncode == 0, second.stderr

    tags = git(repo, "tag", "-l").split()
    assert "v2026.08.15.1" in tags
    assert "newest v* tag: v2026.08.15" in second.stdout


def test_zero_commits_loud_failure(repo: Path):
    make_commit(repo, "a.txt", "a", "feat: add a")
    first = run_script(repo, "--date", "2026-08-15")
    assert first.returncode == 0, first.stderr

    changelog_before = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    tags_before = git(repo, "tag", "-l").split()

    second = run_script(repo, "--date", "2026-08-16")

    assert second.returncode == 2
    assert "NO_COMMITS_SINCE_BOUNDARY" in second.stderr
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == changelog_before
    assert git(repo, "tag", "-l").split() == tags_before


def test_dry_run_writes_nothing(repo: Path):
    make_commit(repo, "a.txt", "a", "feat: add a")

    changelog_before = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    tags_before = git(repo, "tag", "-l").split()

    proc = run_script(repo, "--date", "2026-08-15", "--dry-run")

    assert proc.returncode == 0, proc.stderr
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == changelog_before
    assert git(repo, "tag", "-l").split() == tags_before
