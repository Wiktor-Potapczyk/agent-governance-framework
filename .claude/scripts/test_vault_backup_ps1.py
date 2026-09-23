"""Live-path tests for vault-backup.ps1 (autonomy plan step 2.1, 2026-09-19).

The script is run for real, by Windows PowerShell, against a scratch clone
with a local bare remote. Nothing here touches the vault or its remote:
-RepoRoot points the script at the scratch clone and LOCALAPPDATA is
redirected so the cross-task lock is a scratch directory too.

Why these exist: the status record used to be written AFTER the push, so the
record of run N reached origin with run N+1, a day late. The outcome watchdog
reads the record from origin with a 26 hour limit, so its backup row was STALE
for most of every day while the backup itself was healthy.

Run: PYTHONIOENCODING=utf-8 "C:/Program Files/Python314/python.exe" -m pytest \
    .claude/scripts/test_vault_backup_ps1.py -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
POWERSHELL = shutil.which("powershell")
STATUS_REL = ".claude/hooks/_state/vault-backup.json"

pytestmark = pytest.mark.skipif(
    os.name != "nt" or not POWERSHELL, reason="needs Windows PowerShell")


def _git(cwd, *args, check=True):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stderr}")
    return proc.stdout.strip()


@pytest.fixture()
def scratch(tmp_path):
    remote = tmp_path / "remote.git"
    clone = tmp_path / "clone"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(tmp_path, "clone", str(remote), str(clone))
    _git(clone, "config", "user.name", "backup-test")
    _git(clone, "config", "user.email", "backup-test@example.invalid")
    _git(clone, "config", "core.autocrlf", "false")
    _git(clone, "checkout", "-b", "main", check=False)
    (clone / ".claude" / "scripts").mkdir(parents=True)
    (clone / ".claude" / "hooks" / "_state").mkdir(parents=True)
    for name in ("vault-backup.ps1", "vault-repo-lock.ps1"):
        shutil.copy(SCRIPTS / name, clone / ".claude" / "scripts" / name)
    (clone / ".gitignore").write_text(".claude/logs/\n", encoding="utf-8")
    (clone / "note.md").write_text("first\n", encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "seed")
    _git(clone, "push", "-u", "origin", "main")
    return {"remote": remote, "clone": clone, "appdata": tmp_path / "appdata"}


def _run_backup(scratch, *extra):
    scratch["appdata"].mkdir(exist_ok=True)
    env = dict(os.environ, LOCALAPPDATA=str(scratch["appdata"]))
    script = scratch["clone"] / ".claude" / "scripts" / "vault-backup.ps1"
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(script), "-RepoRoot", str(scratch["clone"]), *extra],
        capture_output=True, text=True, env=env, timeout=300)


def _remote_status(scratch):
    raw = _git(scratch["remote"], "show", f"main:{STATUS_REL}")
    return json.loads(raw)


def _log_text(scratch):
    return (scratch["clone"] / ".claude" / "logs" / "vault-backup.log").read_text(encoding="utf-8")


def test_a_run_with_changes_publishes_its_own_record_in_the_same_run(scratch):
    clone = scratch["clone"]
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    status = _remote_status(scratch)
    assert status["result"] == "success"
    assert status["files_changed"] == 1
    assert status["commit_sha"]
    # the recorded id is the snapshot commit, and origin holds it
    assert _git(scratch["remote"], "show", "main:note.md") == "second"
    _git(scratch["remote"], "merge-base", "--is-ancestor", status["commit_sha"], "main")
    # local and origin agree and nothing is left dirty or unpushed
    assert _git(clone, "rev-parse", "HEAD") == _git(scratch["remote"], "rev-parse", "main")
    assert _git(clone, "status", "--porcelain") == ""


def test_a_clean_in_sync_run_still_publishes_a_fresh_record(scratch):
    clone = scratch["clone"]
    (clone / "note.md").write_text("second\n", encoding="utf-8")
    assert _run_backup(scratch).returncode == 0
    first = _remote_status(scratch)

    proc = _run_backup(scratch)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    second = _remote_status(scratch)
    assert second["result"] == "no-changes"
    assert second["last_run"] != first["last_run"]
    assert second["commit_sha"]
    _git(scratch["remote"], "merge-base", "--is-ancestor", second["commit_sha"], "main")
    assert _git(clone, "status", "--porcelain") == ""
    assert _git(clone, "rev-parse", "HEAD") == _git(scratch["remote"], "rev-parse", "main")


def test_a_dry_run_commits_nothing_and_pushes_nothing(scratch):
    clone = scratch["clone"]
    before_remote = _git(scratch["remote"], "rev-parse", "main")
    before_local = _git(clone, "rev-parse", "HEAD")
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch, "-DryRun")

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _git(scratch["remote"], "rev-parse", "main") == before_remote
    assert _git(clone, "rev-parse", "HEAD") == before_local


def test_a_rejected_record_push_never_fails_the_backup(scratch):
    """The record is secondary. If origin refuses the record commit, the
    snapshot is still safe at origin, the run still exits 0, and the log says
    what happened."""
    clone = scratch["clone"]
    hook = scratch["remote"] / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "while read old new ref; do\n"
        "  if git log -1 --format=%s \"$new\" | grep -q 'status record'; then\n"
        "    echo 'record refused by test hook' >&2; exit 1\n"
        "  fi\n"
        "done\n"
        "exit 0\n", encoding="utf-8", newline="\n")
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _git(scratch["remote"], "show", "main:note.md") == "second"
    log = _log_text(scratch)
    assert "[WARN]" in log and "status record" in log
    assert "BACKUP FAILED" not in log


def test_the_default_repo_root_is_still_the_vault():
    """The scheduled task passes no arguments. The new parameter must default
    to the vault, or the nightly backup silently backs up nothing."""
    text = (SCRIPTS / "vault-backup.ps1").read_text(encoding="utf-8")
    bs = chr(92)
    expected = "[string]$RepoRoot = 'C:" + bs + "Users" + bs + "WiktorPotapczyk" + bs + "Desktop" + bs + "Vault'"
    assert expected in text


# ---------------------------------------------------------------------------
# PowerShell review findings, 2026-09-19
# ---------------------------------------------------------------------------

def test_the_snapshot_commit_never_carries_skip_ci(scratch):
    """Review MEDIUM: [skip ci] belongs to the record commit only. If it ever
    reached the snapshot commit, GitHub would stop running workflows for real
    content pushes."""
    clone = scratch["clone"]
    (clone / "note.md").write_text("second\n", encoding="utf-8")
    assert _run_backup(scratch).returncode == 0
    subjects = _git(scratch["remote"], "log", "--format=%s", "main").splitlines()
    snapshot = [s for s in subjects if "automated vault snapshot" in s]
    record = [s for s in subjects if "status record" in s]
    assert len(snapshot) == 1 and len(record) == 1
    assert "[skip ci]" not in snapshot[0]
    assert "[skip ci]" in record[0]
    # and the record commit holds the record file alone
    files = _git(scratch["remote"], "show", "--name-only", "--format=", "main").splitlines()
    assert files == [STATUS_REL]


def test_a_record_missing_from_disk_is_never_published_as_a_deletion(scratch):
    """Review HIGH: `git add` on a tracked path that is missing from disk
    stages a deletion and exits 0. Publish-Status must refuse to publish then,
    with a WARN, and must never log the ordinary success line."""
    clone = scratch["clone"]
    state_dir = clone / ".claude" / "hooks" / "_state"
    # A file where the state DIRECTORY should be: Save-Status cannot write.
    shutil.rmtree(state_dir)
    state_dir.write_text("not a directory\n", encoding="utf-8")
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _git(scratch["remote"], "show", "main:note.md") == "second"
    log = _log_text(scratch)
    assert "status record missing from disk" in log
    assert "status record published" not in log


def test_a_record_rebase_conflict_is_disowned_not_left_for_tomorrow(scratch):
    """Review MEDIUM: a record commit stranded by a failed rebase used to stay
    on local main. The next night the ordinary rebase would hit the same
    conflict and fail the REAL backup. The record is a timestamp; drop the
    commit, keep the file, and let the next snapshot carry it."""
    clone = scratch["clone"]
    hook = scratch["remote"] / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "# When the RECORD push arrives, move origin first with a conflicting\n"
        "# record file, the way a cloud job pushing in the same minute would,\n"
        "# then refuse the push. The snapshot push is left alone, so the\n"
        "# script's own read-back of the remote ref still matches.\n"
        "while read old new ref; do\n"
        "  if git log -1 --format=%s \"$new\" | grep -q 'status record'; then\n"
        "    if [ ! -f hook-fired ]; then\n"
        "      touch hook-fired\n"
        "      unset GIT_QUARANTINE_PATH GIT_OBJECT_DIRECTORY GIT_ALTERNATE_OBJECT_DIRECTORIES\n"
        "      export GIT_INDEX_FILE=\"$PWD/hook-index\"\n"
        "      git read-tree main\n"
        "      blob=$(echo '{\"conflict\": true}' | git hash-object -w --stdin)\n"
        "      git update-index --add --cacheinfo 100644,$blob,.claude/hooks/_state/vault-backup.json\n"
        "      tree=$(git write-tree)\n"
        "      commit=$(git -c user.name=cloud -c user.email=cloud@example.invalid commit-tree $tree -p main -m 'cloud push')\n"
        "      git update-ref refs/heads/main $commit\n"
        "    fi\n"
        "    echo 'origin moved under the record push' >&2; exit 1\n"
        "  fi\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8", newline="\n")
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (scratch["remote"] / "hook-fired").exists(), "the hook never ran; the test proves nothing"
    assert "cloud push" in _git(scratch["remote"], "log", "-1", "--format=%s", "main"), \
        "origin never moved; the rebase conflict was not exercised"
    assert "rebase failed" in _log_text(scratch)
    assert _git(scratch["remote"], "show", "main:note.md") == "second"
    log = _log_text(scratch)
    assert "[WARN]" in log and "status record" in log
    assert "BACKUP FAILED" not in log
    # no rebase left in progress, and local main ends on the snapshot commit
    assert not (clone / ".git" / "rebase-merge").exists()
    assert not (clone / ".git" / "rebase-apply").exists()
    assert "automated vault snapshot" in _git(clone, "log", "-1", "--format=%s")
    # the record itself survives on disk for the next run
    assert (clone / ".claude" / "hooks" / "_state" / "vault-backup.json").exists()


# ---------------------------------------------------------------------------
# Architect review findings, 2026-09-19
# ---------------------------------------------------------------------------

def test_a_failed_run_publishes_its_failed_record_the_same_day(scratch):
    """Architect review H1. Before this, a failed run's record stayed on disk,
    and the NEXT healthy run overwrote it seconds after committing it, so a
    failure that healed itself overnight was never visible at origin."""
    clone = scratch["clone"]
    big = clone / "too-big.bin"
    with open(big, "wb") as fh:
        fh.seek(96 * 1024 * 1024)
        fh.write(b"0")

    proc = _run_backup(scratch)

    assert proc.returncode == 1, proc.stdout + proc.stderr
    status = _remote_status(scratch)
    assert status["result"] == "failed"
    assert "exceed" in status["detail"]
    # only the record went out; the oversize file did not
    names = _git(scratch["remote"], "ls-tree", "-r", "--name-only", "main").splitlines()
    assert "too-big.bin" not in names


def test_a_rejected_record_push_leaves_no_stranded_commit(scratch):
    """Architect review M2 and PowerShell review MEDIUM: no record commit may
    stay on local main. A stranded one reads as a failed backup to the local
    watchdog and rides into tomorrow's rebase."""
    clone = scratch["clone"]
    hook = scratch["remote"] / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\n"
        "while read old new ref; do\n"
        "  if git log -1 --format=%s \"$new\" | grep -q 'status record'; then\n"
        "    echo 'record refused by test hook' >&2; exit 1\n"
        "  fi\n"
        "done\n"
        "exit 0\n", encoding="utf-8", newline="\n")
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    assert _run_backup(scratch).returncode == 0

    assert "automated vault snapshot" in _git(clone, "log", "-1", "--format=%s")
    assert _git(clone, "rev-parse", "HEAD") == _git(scratch["remote"], "rev-parse", "main")
    assert (clone / ".claude" / "hooks" / "_state" / "vault-backup.json").exists()


# ---------------------------------------------------------------------------
# Read-back check (2026-09-20). The script used to demand that the remote ref
# EQUALS local HEAD right after the push. A cloud job that pushes in the same
# second moves origin past our commit, and a healthy backup then reported
# failure. Found on 2026-09-19 by an earlier version of the conflict test
# above. What the check has to prove is that origin HOLDS our commit.
# ---------------------------------------------------------------------------

def _install_post_receive(scratch, body: str) -> None:
    hook = scratch["remote"] / "hooks" / "post-receive"
    hook.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")


def test_origin_moving_past_our_commit_in_the_same_second_is_still_a_good_backup(scratch):
    clone = scratch["clone"]
    _install_post_receive(scratch, (
        "# When the SNAPSHOT push has landed, add one unrelated commit on top,\n"
        "# the way a cloud job pushing in the same second would.\n"
        "while read old new ref; do\n"
        "  if [ ! -f hook-fired ] && ! git log -1 --format=%s \"$new\" | grep -q 'status record'; then\n"
        "    touch hook-fired\n"
        "    export GIT_INDEX_FILE=\"$PWD/hook-index\"\n"
        "    git read-tree \"$new\"\n"
        "    blob=$(echo cloud | git hash-object -w --stdin)\n"
        "    git update-index --add --cacheinfo 100644,$blob,cloud.txt\n"
        "    tree=$(git write-tree)\n"
        "    commit=$(git -c user.name=cloud -c user.email=cloud@example.invalid commit-tree $tree -p \"$new\" -m 'cloud push')\n"
        "    git update-ref refs/heads/main $commit\n"
        "  fi\n"
        "done\n"
        "exit 0\n"))
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert (scratch["remote"] / "hook-fired").exists(), "the hook never ran; the test proves nothing"
    assert proc.returncode == 0, proc.stdout + proc.stderr + _log_text(scratch)
    log = _log_text(scratch)
    assert "Backup complete." in log
    assert "BACKUP FAILED" not in log
    assert "origin has moved past it" in log
    # origin holds the snapshot, the cloud commit, and this run's success record
    assert _git(scratch["remote"], "show", "main:note.md") == "second"
    assert _git(scratch["remote"], "show", "main:cloud.txt") == "cloud"
    status = _remote_status(scratch)
    assert status["result"] == "success"
    _git(scratch["remote"], "merge-base", "--is-ancestor", status["commit_sha"], "main")
    # nothing stranded locally
    assert _git(clone, "status", "--porcelain") == ""
    assert _git(clone, "rev-parse", "HEAD") == _git(scratch["remote"], "rev-parse", "main")


def test_a_remote_that_does_not_hold_our_commit_is_still_a_failure(scratch):
    """The loosened check must not pass a remote that lost the push: the ref
    is put back to where it was, so our commit is not an ancestor of it."""
    clone = scratch["clone"]
    _install_post_receive(scratch, (
        "while read old new ref; do\n"
        "  if [ ! -f hook-fired ]; then\n"
        "    touch hook-fired\n"
        "    git update-ref refs/heads/main \"$old\"\n"
        "  fi\n"
        "done\n"
        "exit 0\n"))
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert (scratch["remote"] / "hook-fired").exists(), "the hook never ran; the test proves nothing"
    assert proc.returncode != 0
    log = _log_text(scratch)
    assert "does not hold local HEAD" in log
    assert "Backup complete." not in log
    # What happens to the failed record afterwards is the business of the
    # publish tests above; this test pins only the verdict of the check.


def test_a_moved_origin_that_cannot_be_fetched_is_a_failure_with_its_own_reason(scratch):
    """Origin has moved, and the fetch that would prove ancestry fails. The
    run must fail closed, and the log must say that the FETCH failed, with
    git's own words, not that origin lacks our commit."""
    clone = scratch["clone"]
    _install_post_receive(scratch, (
        "# Move origin with a commit whose object is then removed, so the ref\n"
        "# can still be listed but can no longer be fetched.\n"
        "while read old new ref; do\n"
        "  if [ ! -f hook-fired ]; then\n"
        "    touch hook-fired\n"
        "    tree=$(git rev-parse \"$new^{tree}\")\n"
        "    commit=$(git -c user.name=cloud -c user.email=cloud@example.invalid commit-tree $tree -p \"$new\" -m 'cloud push')\n"
        "    git update-ref refs/heads/main $commit\n"
        "    rm -f \"objects/$(echo $commit | cut -c1-2)/$(echo $commit | cut -c3-)\"\n"
        "  fi\n"
        "done\n"
        "exit 0\n"))
    (clone / "note.md").write_text("second\n", encoding="utf-8")

    proc = _run_backup(scratch)

    assert (scratch["remote"] / "hook-fired").exists(), "the hook never ran; the test proves nothing"
    assert proc.returncode != 0
    log = _log_text(scratch)
    assert "could not be fetched to check that it holds local HEAD" in log
    assert "does not hold local HEAD" not in log
    assert "Backup complete." not in log
