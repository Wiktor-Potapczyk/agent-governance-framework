"""Tests for vault_backup.py (Increment 8 Python port, ROAD-11 fold-ins).

Declarative-first: written before the implementation (plan Step 2,
2026-09-09-vault-backup-port-plan.md). Every path is injected through the
Config object; no live vault path literal appears anywhere in this file.
Lock tests use tmp lock dirs; end-to-end tests use throwaway git repos with
a local bare remote under tmp_path. Apply mode is exercised ONLY against
the throwaway remote, never the vault.

Fold-in coverage:
  fix A (TOCTOU bounded retry around git add / git commit): triage items 3, 6.
  fix B (owner.json pid anomaly: payload-rich refusal message, post-acquire
  verification read): triage item 5 and candidate 2.
"""
import ast
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import vault_backup  # noqa: E402


# ---- helpers -------------------------------------------------------


def make_config(tmp_path, **overrides):
    """Config with every path pointed at throwaway locations."""
    defaults = dict(
        repo_root=str(tmp_path / "repo"),
        lock_path=str(tmp_path / "lock" / "vault-repo-lock"),
        log_path=str(tmp_path / "sinks" / "backup.log"),
        status_path=str(tmp_path / "sinks" / "status.json"),
        lock_retries=1,
        lock_retry_delay=0.0,
        add_commit_retry_delay=0.0,
        sleep=lambda seconds: None,
    )
    defaults.update(overrides)
    cfg = vault_backup.Config(**defaults)
    Path(cfg.lock_path).parent.mkdir(parents=True, exist_ok=True)
    return cfg


def git(repo, *args):
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return proc


def git_ok(repo, *args):
    """git() for fixture setup: a non-zero exit is a broken fixture.

    The unchecked git() stays for probes whose return code the test
    inspects or tolerates. Setup commands go through here: a silently
    swallowed setup failure produced two of the three original reds.
    """
    proc = git(repo, *args)
    assert proc.returncode == 0, (
        f"fixture setup failed: git {' '.join(args)}\n"
        f"{proc.stdout}{proc.stderr}")
    return proc


def make_repo_with_remote(tmp_path):
    """Throwaway repo on branch main with a local bare remote, synced."""
    remote = tmp_path / "remote.git"
    # -b main is load-bearing: a bare remote initialised without it
    # keeps HEAD pointing at refs/heads/master while only
    # refs/heads/main exists, so rev-parse HEAD echoes "HEAD" and exits
    # 0, and clones of it check out nothing.
    subprocess.run(["git", "init", "--bare", "-b", "main", str(remote)],
                   capture_output=True, check=True)
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)],
                   capture_output=True, check=True)
    git_ok(repo, "config", "user.email", "test@example.invalid")
    git_ok(repo, "config", "user.name", "vault-backup-test")
    git_ok(repo, "config", "commit.gpgsign", "false")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git_ok(repo, "add", "-A")
    git_ok(repo, "commit", "-m", "seed")
    git_ok(repo, "remote", "add", "origin", str(remote))
    git_ok(repo, "push", "-u", "origin", "main")
    return repo, remote


def write_owner(lock_path, pid, task, started):
    lock = Path(lock_path)
    lock.mkdir(parents=True, exist_ok=True)
    payload = {"pid": pid, "task": task, "started": started}
    (lock / "owner.json").write_text(json.dumps(payload), encoding="utf-8")
    return lock


def run_main(cfg, *cli_args):
    """Run main in-process; return the SystemExit code."""
    with pytest.raises(SystemExit) as excinfo:
        vault_backup.main(list(cli_args), config=cfg)
    return excinfo.value.code or 0


def read_status(cfg):
    raw = Path(cfg.status_path).read_bytes()
    assert raw[:1] == b"{", "status file must not start with a BOM"
    return json.loads(raw.decode("utf-8"))


def iso_now_minus(minutes):
    moment = datetime.datetime.now().astimezone()
    moment -= datetime.timedelta(minutes=minutes)
    return moment.isoformat()


# ---- lock protocol -------------------------------------------------


def test_lock_fresh_acquire_writes_owner_payload(tmp_path):
    cfg = make_config(tmp_path)
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is True
    assert result.holder_pid == os.getpid()
    assert result.holder_task == "vault-backup"
    payload = json.loads(
        (Path(cfg.lock_path) / "owner.json").read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert payload["task"] == "vault-backup"
    assert vault_backup._parse_iso(payload["started"]) is not None
    assert vault_backup.unlock_vault_repo(cfg).released is True


def test_lock_contention_reports_holder(tmp_path):
    cfg = make_config(tmp_path)
    # This process's own pid is guaranteed alive, inside the ceiling.
    write_owner(cfg.lock_path, os.getpid(), "other-task", iso_now_minus(1))
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is False
    assert result.holder_pid == os.getpid()
    assert result.holder_task == "other-task"


def test_lock_dead_pid_takeover(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)
    write_owner(cfg.lock_path, 99999, "auto-commit", iso_now_minus(1))
    monkeypatch.setattr(vault_backup, "_pid_alive", lambda pid: False)
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is True
    assert any("Stale lock cleared" in m for m in result.messages)
    assert any("99999" in m for m in result.messages)


def test_lock_ceiling_takeover(tmp_path):
    cfg = make_config(tmp_path)
    # Live pid (our own) but started 2 hours ago: ceiling rule takes over.
    write_owner(cfg.lock_path, os.getpid(), "auto-commit", iso_now_minus(120))
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is True
    assert any("CEILING TAKEOVER" in m for m in result.messages)


def test_lock_unreadable_owner_falls_back_to_creation_time(tmp_path):
    cfg = make_config(tmp_path)
    lock = Path(cfg.lock_path)
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text("not json at all", encoding="utf-8")
    # Directory just created: inside the ceiling, so held, holder unknown.
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is False
    assert result.holder_pid is None
    assert result.holder_task == "unknown"


def test_lock_payload_write_failure_backs_out(tmp_path, monkeypatch):
    cfg = make_config(tmp_path)

    def failing_write(lock_path, payload):
        raise OSError("simulated owner.json write failure")

    monkeypatch.setattr(vault_backup, "_write_owner_payload", failing_write)
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is False
    assert result.holder_task == "payload-write-failed"
    assert any("backed out" in m for m in result.messages)
    assert not Path(cfg.lock_path).exists(), "backout must remove the dir"


def test_unlock_release_succeeds_for_owner_pid(tmp_path):
    cfg = make_config(tmp_path)
    assert vault_backup.lock_vault_repo(cfg, "vault-backup").acquired
    release = vault_backup.unlock_vault_repo(cfg)
    assert release.released is True
    assert not Path(cfg.lock_path).exists()


def test_unlock_refuses_foreign_pid_and_names_full_payload(tmp_path):
    """Fix B part a: the refusal message carries task, pid, and started."""
    cfg = make_config(tmp_path)
    started = iso_now_minus(5)
    write_owner(cfg.lock_path, os.getpid() + 7, "auto-commit", started)
    release = vault_backup.unlock_vault_repo(cfg)
    assert release.released is False
    assert str(os.getpid() + 7) in release.reason
    assert "auto-commit" in release.reason
    assert started in release.reason
    assert Path(cfg.lock_path).exists(), "refusal must not remove the lock"


def test_unlock_refuses_when_owner_json_unreadable(tmp_path):
    cfg = make_config(tmp_path)
    lock = Path(cfg.lock_path)
    lock.mkdir(parents=True)
    (lock / "owner.json").write_text("garbage", encoding="utf-8")
    release = vault_backup.unlock_vault_repo(cfg)
    assert release.released is False
    assert "cannot prove" in release.reason


def test_lock_post_acquire_verification_rejects_foreign_pid(tmp_path,
                                                            monkeypatch):
    """Fix B part b: a foreign pid observed right after our write means the
    lock is NOT ours (the pid-48824 anomaly, triage item 5)."""
    cfg = make_config(tmp_path)

    def hijacking_write(lock_path, payload):
        foreign = dict(payload)
        foreign["pid"] = payload["pid"] + 13
        foreign["task"] = "unexplained-third-actor"
        (Path(lock_path) / "owner.json").write_text(
            json.dumps(foreign), encoding="utf-8")

    monkeypatch.setattr(vault_backup, "_write_owner_payload", hijacking_write)
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is False
    assert any("Post-acquire verification" in m for m in result.messages)
    assert any("unexplained-third-actor" in m for m in result.messages)
    # The observed holder's payload must survive for attribution.
    assert Path(cfg.lock_path).exists()


def test_lock_interop_parses_ps1_shaped_owner_json(tmp_path, monkeypatch):
    """owner.json as ConvertTo-Json writes it: 4-space indent, two spaces
    after the colon, CRLF line ends, 7-digit ISO fraction."""
    cfg = make_config(tmp_path)
    lock = Path(cfg.lock_path)
    lock.mkdir(parents=True)
    started = iso_now_minus(1)
    # Rebuild the stamp with a 7-digit fraction the way PS1 emits it.
    base, offset = started[:-6], started[-6:]
    if "." in base:
        base = base.split(".")[0]
    ps1_started = base + ".1234567" + offset
    ps1_json = (
        '{\r\n'
        '    "pid":  424242,\r\n'
        '    "task":  "auto-commit",\r\n'
        f'    "started":  "{ps1_started}"\r\n'
        '}'
    )
    (lock / "owner.json").write_bytes(ps1_json.encode("utf-8"))
    monkeypatch.setattr(vault_backup, "_pid_alive", lambda pid: True)
    result = vault_backup.lock_vault_repo(cfg, "vault-backup")
    assert result.acquired is False
    assert result.holder_pid == 424242
    assert result.holder_task == "auto-commit"


def test_parse_iso_accepts_seven_digit_fraction():
    parsed = vault_backup._parse_iso("2026-09-08T18:01:46.4060500+02:00")
    assert parsed is not None
    assert parsed.year == 2026 and parsed.second == 46


def test_pid_liveness_helper_is_ctypes_not_os_kill():
    # AST, not a substring scan: the module deliberately NAMES os.kill
    # in a docstring to preserve the Windows trap knowledge (plan design
    # decision 5). A grep cannot tell a call from a prose warning; an
    # ast.Attribute walk catches every real reference, aliases included.
    source = (SCRIPTS / "vault_backup.py").read_text(encoding="utf-8")
    kill_refs = [
        node.lineno for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Attribute) and node.attr == "kill"
        and isinstance(node.value, ast.Name) and node.value.id == "os"
    ]
    assert kill_refs == [], (
        "os.kill(pid, 0) on Windows terminates the probed process; "
        f"os.kill referenced at lines {kill_refs}")
    assert "OpenProcess" in source
    assert vault_backup._pid_alive(os.getpid()) is True
    assert vault_backup._pid_alive(999999) is False


# ---- index.lock self-heal ------------------------------------------


def test_selfheal_absent_lock_proceeds(tmp_path):
    repo, _ = make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 0
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "index.lock" not in log


def test_selfheal_recent_lock_fails_loud(tmp_path, monkeypatch):
    repo, _ = make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    (repo / ".git" / "index.lock").write_text("", encoding="utf-8")
    # Deterministic: an unrelated git.exe elsewhere on the machine must not
    # flip this case onto the running-git branch.
    monkeypatch.setattr(vault_backup, "_git_process_running", lambda: False)
    code = run_main(cfg)
    assert code == 1
    status = read_status(cfg)
    assert status["result"] == "failed"
    assert "Too recent" in status["detail"]
    assert (repo / ".git" / "index.lock").exists()


def test_selfheal_aged_lock_no_git_process_removed(tmp_path, monkeypatch):
    repo, _ = make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    stale = repo / ".git" / "index.lock"
    stale.write_text("", encoding="utf-8")
    old = (datetime.datetime.now()
           - datetime.timedelta(hours=2)).timestamp()
    os.utime(stale, (old, old))
    monkeypatch.setattr(vault_backup, "_git_process_running", lambda: False)
    code = run_main(cfg)
    assert code == 0
    assert not stale.exists()
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "Removing stale index.lock" in log


def test_selfheal_aged_lock_with_running_git_fails_loud(tmp_path,
                                                        monkeypatch):
    repo, _ = make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    stale = repo / ".git" / "index.lock"
    stale.write_text("", encoding="utf-8")
    old = (datetime.datetime.now()
           - datetime.timedelta(hours=2)).timestamp()
    os.utime(stale, (old, old))
    monkeypatch.setattr(vault_backup, "_git_process_running", lambda: True)
    code = run_main(cfg)
    assert code == 1
    assert "git process is running" in read_status(cfg)["detail"]
    assert stale.exists(), "must not disturb a live operation"


# ---- TOCTOU bounded retry (fix A) ----------------------------------

INDEX_LOCK_ERROR = ("fatal: Unable to create '.git/index.lock': "
                    "File exists.")


class FlakyGit:
    """Delegates to the real run_git except for scripted failures."""

    def __init__(self, fail_subcommand, fail_times,
                 output=INDEX_LOCK_ERROR):
        self.fail_subcommand = fail_subcommand
        self.remaining = fail_times
        self.output = output
        self.calls = []
        self.real = vault_backup.run_git

    def __call__(self, args, cwd):
        if args and args[0] == self.fail_subcommand:
            self.calls.append(list(args))
            if self.remaining > 0:
                self.remaining -= 1
                return vault_backup.GitResult(self.output, 128)
        return self.real(args, cwd)


def test_fix_a_add_retries_once_then_succeeds(tmp_path, monkeypatch):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    flaky = FlakyGit("add", fail_times=1)
    monkeypatch.setattr(vault_backup, "run_git", flaky)
    code = run_main(cfg)
    assert code == 0
    assert len(flaky.calls) == 2
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "index.lock collision" in log
    assert "[WARN]" in log


def test_fix_a_add_failing_all_attempts_exits_1(tmp_path, monkeypatch):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    flaky = FlakyGit("add", fail_times=99)
    monkeypatch.setattr(vault_backup, "run_git", flaky)
    code = run_main(cfg)
    assert code == 1
    assert len(flaky.calls) == cfg.add_commit_retries
    status = read_status(cfg)
    assert status["result"] == "failed"
    assert "git add failed" in status["detail"]


def test_fix_a_non_index_lock_add_failure_never_retries(tmp_path,
                                                        monkeypatch):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    flaky = FlakyGit("add", fail_times=99,
                     output="fatal: unrelated failure")
    monkeypatch.setattr(vault_backup, "run_git", flaky)
    code = run_main(cfg)
    assert code == 1
    assert len(flaky.calls) == 1, "non-matching failures fail loud at once"
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "index.lock collision" not in log


def test_fix_a_commit_retries_after_index_lock_collision(tmp_path,
                                                         monkeypatch):
    repo, remote = make_repo_with_remote(tmp_path)
    (repo / "new.txt").write_text("payload\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    flaky = FlakyGit("commit", fail_times=1)
    monkeypatch.setattr(vault_backup, "run_git", flaky)
    code = run_main(cfg)
    assert code == 0
    assert len(flaky.calls) == 2
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "git commit hit an index.lock collision" in log


# ---- status contract -----------------------------------------------


def test_status_contract_keys_and_order(tmp_path):
    cfg = make_config(tmp_path)
    runner = vault_backup.BackupRunner(cfg, dry_run=False)
    runner.save_status("success", "detail text",
                       commit_sha="abc1234", files_changed=3)
    status = read_status(cfg)
    assert list(status.keys()) == [
        "last_run", "result", "detail", "commit_sha",
        "files_changed", "dry_run",
    ]
    assert status["result"] == "success"
    assert status["commit_sha"] == "abc1234"
    assert status["files_changed"] == 3
    assert status["dry_run"] is False
    assert vault_backup._parse_iso(status["last_run"]) is not None


def test_status_file_has_no_bom(tmp_path):
    cfg = make_config(tmp_path)
    runner = vault_backup.BackupRunner(cfg, dry_run=True)
    runner.save_status("no-changes", "x")
    raw = Path(cfg.status_path).read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw[:1] == b"{"


def test_status_failure_path_carries_tracked_progress(tmp_path):
    """The 4d70df65 contract: a run that committed and then failed reports
    what it did accomplish, not zeros."""
    cfg = make_config(tmp_path)
    runner = vault_backup.BackupRunner(cfg, dry_run=False)
    runner.commit_sha = "abc1234"
    runner.files_changed = 1464
    with pytest.raises(SystemExit) as excinfo:
        runner.stop_with_failure("simulated push failure")
    assert excinfo.value.code == 1
    status = read_status(cfg)
    assert status["result"] == "failed"
    assert status["detail"] == "simulated push failure"
    assert status["commit_sha"] == "abc1234"
    assert status["files_changed"] == 1464


def test_status_result_values_are_validated(tmp_path):
    cfg = make_config(tmp_path)
    runner = vault_backup.BackupRunner(cfg, dry_run=False)
    with pytest.raises(ValueError):
        runner.save_status("exploded", "not a valid result value")


# ---- log contract --------------------------------------------------

LINE_GRAMMAR = re.compile(
    r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[(INFO|WARN|ERROR)\] .+$")


def test_log_line_grammar(tmp_path, capsys):
    cfg = make_config(tmp_path)
    runner = vault_backup.BackupRunner(cfg, dry_run=False)
    runner.write_log("hello backup")
    runner.write_log("watch out", "WARN")
    for line in runner.log_buffer:
        assert LINE_GRAMMAR.match(line), line
    printed = capsys.readouterr().out.splitlines()
    assert printed == runner.log_buffer


def test_log_trim_to_max_lines(tmp_path):
    cfg = make_config(tmp_path, max_log_lines=10)
    log_file = Path(cfg.log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text(
        "".join(f"old line {i}\n" for i in range(15)), encoding="utf-8")
    runner = vault_backup.BackupRunner(cfg, dry_run=False)
    runner.write_log("fresh line")
    runner.save_log()
    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    assert "fresh line" in lines[-1]
    assert lines[0] == "old line 6"


# ---- oversize guard ------------------------------------------------


def test_oversize_staged_file_unstages_everything_and_fails(tmp_path):
    repo, _ = make_repo_with_remote(tmp_path)
    (repo / "big.bin").write_bytes(b"x" * 2048)
    (repo / "small.txt").write_text("ok\n", encoding="utf-8")
    cfg = make_config(tmp_path, max_file_bytes=1024)
    code = run_main(cfg)
    assert code == 1
    status = read_status(cfg)
    assert status["result"] == "failed"
    assert "big.bin" in status["detail"]
    assert "exceed" in status["detail"]
    staged = git(repo, "diff", "--cached", "--name-only").stdout.strip()
    assert staged == "", "oversize guard must unstage everything"


def test_oversize_unscannable_path_warns_without_failing(tmp_path,
                                                         monkeypatch):
    repo, _ = make_repo_with_remote(tmp_path)
    (repo / "fine.txt").write_text("ok\n", encoding="utf-8")
    cfg = make_config(tmp_path)

    real = vault_backup._scan_file_size

    def flaky_scan(repo_root, rel_path):
        if rel_path == "fine.txt":
            raise OSError("simulated unresolvable git-quoted name")
        return real(repo_root, rel_path)

    monkeypatch.setattr(vault_backup, "_scan_file_size", flaky_scan)
    code = run_main(cfg, "--dry-run")
    assert code == 0
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "could not resolve 1 staged path(s)" in log
    assert "[WARN]" in log


# ---- pipeline end-to-end (throwaway repo + local bare remote) ------


def test_e2e_no_changes_exits_0(tmp_path):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 0
    status = read_status(cfg)
    assert status["result"] == "no-changes"
    assert status["detail"] == "Working tree clean, remote in sync."
    assert status["dry_run"] is False
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "No changes and nothing unpushed. Backup already current." in log
    assert "Repo lock released." in log


def test_e2e_dry_run_stages_resets_commits_nothing(tmp_path):
    repo, _ = make_repo_with_remote(tmp_path)
    (repo / "pending.txt").write_text("pending\n", encoding="utf-8")
    head_before = git(repo, "rev-parse", "HEAD").stdout.strip()
    cfg = make_config(tmp_path)
    code = run_main(cfg, "--dry-run")
    assert code == 0
    assert git(repo, "rev-parse", "HEAD").stdout.strip() == head_before
    assert git(repo, "diff", "--cached",
               "--name-only").stdout.strip() == ""
    status = read_status(cfg)
    assert status["result"] == "no-changes"
    assert status["detail"] == "Dry run; no commit or push performed."
    assert status["files_changed"] == 1
    assert status["dry_run"] is True
    assert status["commit_sha"] == ""
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "DRY RUN: would commit 1 path(s)" in log


def test_e2e_apply_commits_pushes_and_verifies_remote(tmp_path):
    repo, remote = make_repo_with_remote(tmp_path)
    (repo / "payload.txt").write_text("payload\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 0
    local_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    probe = subprocess.run(["git", "rev-parse", "refs/heads/main"],
                           cwd=str(remote), capture_output=True,
                           text=True)
    assert probe.returncode == 0, probe.stderr
    remote_head = probe.stdout.strip()
    assert remote_head == local_head
    subject = git(repo, "log", "-1", "--format=%s").stdout.strip()
    assert re.fullmatch(
        r"chore\(backup\): automated vault snapshot "
        r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} \(1 paths\)", subject), subject
    status = read_status(cfg)
    assert status["result"] == "success"
    assert status["detail"] == "Pushed to origin/main."
    assert status["files_changed"] == 1
    assert status["commit_sha"] == git(
        repo, "rev-parse", "--short", "HEAD").stdout.strip()
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "Backup complete." in log


def test_e2e_behind_remote_rebases_then_pushes(tmp_path):
    repo, remote = make_repo_with_remote(tmp_path)
    # Advance the remote from a second clone so repo is behind.
    other = tmp_path / "other"
    subprocess.run(["git", "clone", str(remote), str(other)],
                   capture_output=True, check=True)
    git_ok(other, "config", "user.email", "test@example.invalid")
    git_ok(other, "config", "user.name", "vault-backup-test")
    git_ok(other, "config", "commit.gpgsign", "false")
    (other / "remote-side.txt").write_text("upstream\n", encoding="utf-8")
    git_ok(other, "add", "-A")
    git_ok(other, "commit", "-m", "upstream change")
    git_ok(other, "push", "origin", "main")
    (repo / "local-side.txt").write_text("local\n", encoding="utf-8")
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 0
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    # Assert the whole WARN line, not just the verb: the rebase branch
    # must be proven to have executed, not merely not-failed.
    assert "Local is 1 commit(s) behind origin/main. Rebasing." in log
    local_head = git(repo, "rev-parse", "HEAD").stdout.strip()
    probe = subprocess.run(["git", "rev-parse", "refs/heads/main"],
                           cwd=str(remote), capture_output=True,
                           text=True)
    assert probe.returncode == 0, probe.stderr
    remote_head = probe.stdout.strip()
    assert remote_head == local_head
    tree = git(repo, "ls-tree", "--name-only", "HEAD").stdout
    assert "remote-side.txt" in tree and "local-side.txt" in tree


def test_e2e_branch_mismatch_fails_loud(tmp_path):
    repo, _ = make_repo_with_remote(tmp_path)
    git(repo, "checkout", "-b", "feature")
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 1
    detail = read_status(cfg)["detail"]
    assert "On branch 'feature', expected 'main'" in detail


def test_e2e_mid_operation_marker_fails_loud(tmp_path):
    repo, _ = make_repo_with_remote(tmp_path)
    (repo / ".git" / "MERGE_HEAD").write_text("deadbeef", encoding="utf-8")
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 1
    detail = read_status(cfg)["detail"]
    assert "mid-operation" in detail and "MERGE_HEAD" in detail


def test_e2e_missing_repo_root_fails_loud(tmp_path):
    cfg = make_config(tmp_path, repo_root=str(tmp_path / "nowhere"))
    code = run_main(cfg)
    assert code == 1
    assert "Repo root not found" in read_status(cfg)["detail"]


def test_e2e_not_a_git_repository_fails_loud(tmp_path):
    bare_dir = tmp_path / "repo"
    bare_dir.mkdir()
    cfg = make_config(tmp_path)
    code = run_main(cfg)
    assert code == 1
    assert "is not a git repository" in read_status(cfg)["detail"]


def test_e2e_lock_held_by_live_holder_fails_after_retries(tmp_path):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path, lock_retries=2)
    write_owner(cfg.lock_path, os.getpid(), "auto-commit", iso_now_minus(1))
    code = run_main(cfg)
    assert code == 1
    detail = read_status(cfg)["detail"]
    assert "Could not acquire the repo lock after 2 retries" in detail
    assert "auto-commit" in detail
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "retry 1 of 2" in log and "retry 2 of 2" in log
    # The foreign holder's lock must survive the failed run untouched.
    assert Path(cfg.lock_path).exists()
    # PS1 parity: the lock-failure abort happens before the try block, so
    # no unlock is attempted and no release line is appended.
    assert "Repo lock release" not in log


def test_cli_help_names_the_three_flags(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "vault_backup.py"), "--help"],
        capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--log-path" in proc.stdout
    assert "--status-path" in proc.stdout


# --- core.longpaths preflight (regression coverage, added 2026-09-09) --------
# Untested Surface item 13 of the port build record named this gap: the
# preflight sets repo-local core.longpaths on every run and nothing asserted
# it, so a regression would have kept the suite green. The defect class is real
# history: a 258 character Clippings/ path broke vault-backup.ps1 in production
# on 2026-07-29.

def test_longpaths_is_enabled_when_unset(tmp_path):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    git(cfg.repo_root, "config", "--unset", "core.longpaths")
    code = run_main(cfg)
    assert code == 0
    got = git(cfg.repo_root, "config", "--get", "core.longpaths")
    assert got.stdout.strip() == "true"
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "core.longpaths" in log


def test_longpaths_already_true_is_left_alone_and_not_relogged(tmp_path):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    git(cfg.repo_root, "config", "core.longpaths", "true")
    code = run_main(cfg)
    assert code == 0
    got = git(cfg.repo_root, "config", "--get", "core.longpaths")
    assert got.stdout.strip() == "true"
    log = Path(cfg.log_path).read_text(encoding="utf-8")
    assert "Enabling core.longpaths" not in log


def test_longpaths_set_failure_stops_the_run(tmp_path, monkeypatch):
    make_repo_with_remote(tmp_path)
    cfg = make_config(tmp_path)
    git(cfg.repo_root, "config", "--unset", "core.longpaths")
    real_run_git = vault_backup.run_git

    def refuse_longpaths_write(args, cwd):
        if list(args[:2]) == ["config", "core.longpaths"]:
            return vault_backup.GitResult("permission denied", 1)
        return real_run_git(args, cwd)

    monkeypatch.setattr(vault_backup, "run_git", refuse_longpaths_write)
    code = run_main(cfg)
    assert code == 1
    status = read_status(cfg)
    assert status["result"] == "failed"
    assert "core.longpaths" in status["detail"]
