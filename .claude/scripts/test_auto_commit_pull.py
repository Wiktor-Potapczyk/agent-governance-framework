"""Tests for auto-commit.ps1's commit-then-pull step (self-heal phase (a),
spec TASK-004).

Declarative-first, git-backed scratch-repo fixtures (same convention as
test_scheduler_watchdog.py's _init_git_repo): a real bare origin plus real
clones under tmp_path, never the live vault. Invokes the real script via
powershell -NonInteractive -ExecutionPolicy Bypass -File ... -VaultPath
<tmp-dir>, so these tests exercise the actual PowerShell logic, not a Python
re-implementation of it.

vault-repo-lock.ps1 is copied into the fixture's .claude/scripts/ directory:
without it, auto-commit.ps1 silently no-ops (its own line "Helper missing:
quiet skip"), which would make a passing test meaningless. Each test proves
the script actually ran by asserting a new commit exists on the fixture
"local" repo.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
AUTO_COMMIT_PS1 = SCRIPTS / "auto-commit.ps1"
LOCK_HELPER = SCRIPTS / "vault-repo-lock.ps1"

ALERT_PHRASE_PREFIX = "FAIL-LOUD: rebase conflict against origin/main; aborted, no force-push, no retry. Conflicting path(s):"


def _run_git(cmd, cwd, env=None):
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True, env=env)


def _git_output(cmd, cwd):
    return subprocess.run(
        cmd, cwd=str(cwd), check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo_with_origin(tmp_path, name="local"):
    """A bare origin plus one clone (the owner's vault stand-in), one commit
    on conflict.md already pushed to origin/main."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _run_git(["git", "init", "--bare"], origin)

    local = tmp_path / name
    local.mkdir()
    _run_git(["git", "init", "-b", "main"], local)
    _run_git(["git", "config", "user.email", "owner@example.com"], local)
    _run_git(["git", "config", "user.name", "Owner"], local)
    (local / "conflict.md").write_text("line1\n", encoding="utf-8")
    _run_git(["git", "add", "conflict.md"], local)
    _run_git(["git", "commit", "-m", "seed"], local)
    _run_git(["git", "remote", "add", "origin", str(origin)], local)
    _run_git(["git", "push", "-u", "origin", "main"], local)
    # `git init --bare` defaults HEAD to a "master" symref regardless of the
    # branch later pushed into it; without this, a plain `git clone` checks
    # out an empty, unborn "master" instead of the pushed "main" content.
    _run_git(["git", "symbolic-ref", "HEAD", "refs/heads/main"], origin)
    return origin, local


def _clone(origin, dest):
    _run_git(["git", "clone", "-b", "main", str(origin), dest.name], dest.parent)
    _run_git(["git", "config", "user.email", "other@example.com"], dest)
    _run_git(["git", "config", "user.name", "Other"], dest)
    return dest


def _install_lock_helper(local_root):
    dest = local_root / ".claude" / "scripts"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LOCK_HELPER, dest / "vault-repo-lock.ps1")
    (local_root / "Resources" / "Observability").mkdir(parents=True, exist_ok=True)


def _run_auto_commit(vault_path, log_path=None, tmp_path=None):
    """Invokes the real script. -LogPath always points at a scratch file
    under tmp_path (self-heal phase (a) fix pass item 11): the script's log
    is otherwise the single, real, machine-wide
    %LOCALAPPDATA%\\vault-auto-commit.log with no per-invocation override,
    so an un-parameterized test run pollutes production telemetry
    (adversarial review probe 4, reproduced incidentally)."""
    if log_path is None:
        assert tmp_path is not None, "pass tmp_path or an explicit log_path"
        log_path = tmp_path / "auto-commit-test.log"
    return subprocess.run(
        ["powershell", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(AUTO_COMMIT_PS1), "-VaultPath", str(vault_path),
         "-LogPath", str(log_path)],
        capture_output=True, text=True,
    )


def _rebase_in_progress(local_root):
    git_dir = local_root / ".git"
    return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _origin_head(origin):
    return _git_output(["git", "rev-parse", "refs/heads/main"], origin)


@pytest.fixture(autouse=True)
def _require_lock_helper():
    if not LOCK_HELPER.exists():
        pytest.skip("vault-repo-lock.ps1 not present in .claude/scripts/")


def test_rebase_conflict_aborts_and_alerts(tmp_path):
    origin, local = _init_repo_with_origin(tmp_path, name="local")
    _install_lock_helper(local)
    origin_sha_before = _origin_head(origin)
    seed_sha = _git_output(["git", "rev-parse", "HEAD"], local)

    other = _clone(origin, tmp_path / "other")
    (other / "conflict.md").write_text("other-value\n", encoding="utf-8")
    _run_git(["git", "commit", "-am", "other edit"], other)
    _run_git(["git", "push", "origin", "main"], other)
    origin_sha_after_other_push = _origin_head(origin)
    assert origin_sha_after_other_push != origin_sha_before

    (local / "conflict.md").write_text("owner-value\n", encoding="utf-8")
    pre_run_content = (local / "conflict.md").read_text(encoding="utf-8")

    result = _run_auto_commit(local, tmp_path=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    new_head = _git_output(["git", "rev-parse", "HEAD"], local)
    assert new_head != seed_sha, "script must have committed the owner's local change"

    assert not _rebase_in_progress(local)
    status = _git_output(["git", "status", "--porcelain"], local)
    status_lines = [
        ln for ln in status.splitlines()
        if ln[3:].strip() != "Resources/"
    ]
    assert status_lines == [], status

    alerts_path = local / "Resources" / "Observability" / "harness-alerts.md"
    assert alerts_path.exists()
    alerts_text = alerts_path.read_text(encoding="utf-8")
    assert f"- {ALERT_PHRASE_PREFIX} conflict.md" in alerts_text, alerts_text

    assert (local / "conflict.md").read_text(encoding="utf-8") == pre_run_content

    assert _origin_head(origin) == origin_sha_after_other_push, "no push must ever happen"


def test_happy_path_fast_forwards_no_alert(tmp_path):
    origin, local = _init_repo_with_origin(tmp_path, name="local")
    _install_lock_helper(local)
    seed_sha = _git_output(["git", "rev-parse", "HEAD"], local)

    other = _clone(origin, tmp_path / "other")
    (other / "other-file.md").write_text("from someone else\n", encoding="utf-8")
    _run_git(["git", "add", "other-file.md"], other)
    _run_git(["git", "commit", "-m", "unrelated addition"], other)
    _run_git(["git", "push", "origin", "main"], other)
    origin_sha_after_other_push = _origin_head(origin)

    (local / "owner-file.md").write_text("owner addition\n", encoding="utf-8")

    result = _run_auto_commit(local, tmp_path=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    new_head = _git_output(["git", "rev-parse", "HEAD"], local)
    assert new_head != seed_sha

    assert not _rebase_in_progress(local)
    assert (local / "other-file.md").exists(), "the incoming commit must be pulled in"
    assert (local / "owner-file.md").exists()

    alerts_path = local / "Resources" / "Observability" / "harness-alerts.md"
    if alerts_path.exists():
        assert "FAIL-LOUD" not in alerts_path.read_text(encoding="utf-8")

    assert _origin_head(origin) == origin_sha_after_other_push, "no push must ever happen"


def test_unreachable_origin_writes_distinct_alert_no_conflict_claim(tmp_path):
    """Adversarial review probe 4 ('BREAKS on the unreachable-origin
    misdiagnosis') reproduction, self-heal phase (a) fix pass item 4: a
    fetch failure must never be reported as a rebase conflict, and no
    rebase must ever be attempted once fetch itself has failed."""
    origin, local = _init_repo_with_origin(tmp_path, name="local")
    _install_lock_helper(local)
    seed_sha = _git_output(["git", "rev-parse", "HEAD"], local)

    _run_git(
        ["git", "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git")],
        local,
    )

    (local / "conflict.md").write_text("owner-value\n", encoding="utf-8")

    result = _run_auto_commit(local, tmp_path=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    new_head = _git_output(["git", "rev-parse", "HEAD"], local)
    assert new_head != seed_sha, "script must have committed the owner's local change"
    assert not _rebase_in_progress(local)

    alerts_path = local / "Resources" / "Observability" / "harness-alerts.md"
    assert alerts_path.exists()
    alerts_text = alerts_path.read_text(encoding="utf-8")
    assert (
        "- FAIL-LOUD: origin unreachable during autosave pull" in alerts_text
    ), alerts_text
    assert "rebase conflict" not in alerts_text

    assert _origin_head(origin) == seed_sha, "no push must ever happen; origin untouched"


def test_repeated_identical_alert_is_not_duplicated(tmp_path):
    """Self-heal phase (a) fix pass item 5a: auto-commit.ps1 never appends a
    row that already exists verbatim under '## Current alerts'. Two
    consecutive cycles hitting the same unreachable-origin failure must
    produce exactly one row, not two."""
    origin, local = _init_repo_with_origin(tmp_path, name="local")
    _install_lock_helper(local)
    _run_git(
        ["git", "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git")],
        local,
    )

    (local / "conflict.md").write_text("owner-value-1\n", encoding="utf-8")
    result1 = _run_auto_commit(local, tmp_path=tmp_path)
    assert result1.returncode == 0, result1.stdout + result1.stderr

    (local / "conflict.md").write_text("owner-value-2\n", encoding="utf-8")
    result2 = _run_auto_commit(local, tmp_path=tmp_path)
    assert result2.returncode == 0, result2.stdout + result2.stderr

    alerts_path = local / "Resources" / "Observability" / "harness-alerts.md"
    alerts_text = alerts_path.read_text(encoding="utf-8")
    assert (
        alerts_text.count("FAIL-LOUD: origin unreachable during autosave pull") == 1
    ), alerts_text


def test_successful_pull_clears_previously_written_fail_loud_rows(tmp_path):
    """Self-heal phase (a) fix pass item 5a: auto-commit.ps1 removes its own
    earlier FAIL-LOUD rows once a pull succeeds, so a stale alert does not
    outlive the condition that caused it."""
    origin, local = _init_repo_with_origin(tmp_path, name="local")
    _install_lock_helper(local)

    alerts_path = local / "Resources" / "Observability" / "harness-alerts.md"
    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    alerts_path.write_text(
        "# Harness Alerts\n\n## Current alerts\n\n"
        "- FAIL-LOUD: origin unreachable during autosave pull "
        "(git fetch exit 128); no rebase attempted\n\n",
        encoding="utf-8",
    )

    other = _clone(origin, tmp_path / "other")
    (other / "other-file.md").write_text("from someone else\n", encoding="utf-8")
    _run_git(["git", "add", "other-file.md"], other)
    _run_git(["git", "commit", "-m", "unrelated addition"], other)
    _run_git(["git", "push", "origin", "main"], other)

    (local / "owner-file.md").write_text("owner addition\n", encoding="utf-8")

    result = _run_auto_commit(local, tmp_path=tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not _rebase_in_progress(local)

    alerts_text = alerts_path.read_text(encoding="utf-8")
    assert "FAIL-LOUD" not in alerts_text, alerts_text


def test_log_path_param_writes_to_the_given_file_not_the_shared_log(tmp_path):
    """Self-heal phase (a) fix pass item 11: -LogPath defaults to the real
    %LOCALAPPDATA%\\vault-auto-commit.log, but a caller-supplied path must
    receive this run's log lines instead (adversarial review probe 4,
    shared-log test-isolation gap, reproduced incidentally)."""
    origin, local = _init_repo_with_origin(tmp_path, name="local")
    _install_lock_helper(local)
    (local / "owner-file.md").write_text("owner addition\n", encoding="utf-8")

    log_path = tmp_path / "scratch-auto-commit.log"
    assert not log_path.exists()

    result = _run_auto_commit(local, log_path=log_path)
    assert result.returncode == 0, result.stdout + result.stderr

    assert log_path.exists()
    log_text = log_path.read_text(encoding="utf-8")
    assert "COMMIT" in log_text
