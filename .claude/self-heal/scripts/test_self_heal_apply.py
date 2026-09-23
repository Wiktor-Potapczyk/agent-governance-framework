"""Tests for self_heal_apply.py: the improver workflow's deterministic
apply step (write-path decision of 2026-09-18, Route B).

Written before the implementation (declarative-first). The improver never
touches the real checkout: it works in a throwaway shadow copy where the
vault's `.claude` directory is mounted as `_claude`. This script, run from
the real checkout afterwards, derives the change set, maps `_claude/` back
to `.claude/`, validates every changed path against targets.json (assigned
class paths, that class's excludes, forbidden_paths), rejects symlinks,
binaries, oversize and over-count rounds, refuses a dirty checkout, and only
then copies the validated files in and stages exactly those paths.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
VAULT = HERE.parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("self_heal_apply", HERE / "self_heal_apply.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


TARGETS = {
    "allowed_classes": [
        {"class": "tests", "paths": [".claude/scripts/test_*.py", ".claude/hooks/test_*.py"]},
        {"class": "scripts", "paths": [".claude/scripts/*.py"], "excludes": ["*_logic.py"]},
        {"class": "work-curation", "paths": ["Projects/*/work/**"],
         "excludes": ["Projects/*/work/backups/**"]},
    ],
    "forbidden_paths": [
        ".claude/hooks/bash-safety-guard.py", "CLAUDE.md", ".claude/rules/**",
        ".github/**", ".claude/self-heal/**",
    ],
}


@pytest.fixture
def targets_file(tmp_path):
    p = tmp_path / "targets.json"
    p.write_text(json.dumps(TARGETS), encoding="utf-8")
    return p


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _make_repo(tmp_path, files: dict[str, str]) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "core.autocrlf", "false")
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    _git(repo, "add", "--", *files.keys())
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def _rename_retrying(src: Path, dst: Path, attempts: int = 30, delay: float = 0.1) -> None:
    """Windows only. A virus scanner or the search indexer can hold a handle
    on a freshly extracted directory for a moment, and the rename then fails
    with access denied. About one full run in six failed on this machine
    until the cause was caught on 2026-09-20. The workflow itself runs on
    Linux, where this cannot happen, so the retry lives in the test only."""
    import time
    for attempt in range(attempts):
        try:
            src.rename(dst)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _make_shadow(tmp_path, repo: Path) -> Path:
    """Mirrors what the workflow does: git archive HEAD into a fresh
    directory, then rename .claude to _claude."""
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "HEAD"],
                             capture_output=True, check=True).stdout
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(shadow, filter="data")
    if (shadow / ".claude").exists():
        _rename_retrying(shadow / ".claude", shadow / "_claude")
    return shadow


BASE = {
    ".claude/scripts/existing.py": "x = 1\n",
    ".claude/scripts/test_existing.py": "def test_a():\n    assert True\n",
    ".claude/hooks/bash-safety-guard.py": "guard\n",
    "CLAUDE.md": "doctrine\n",
    "Projects/X/work/2026-01-01-note.md": "note\n",
    "README.md": "readme\n",
}


# 1. clean-checkout guard
def test_dirty_checkout_is_refused_and_names_the_paths(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    (repo / "README.md").write_text("touched through some other route\n", encoding="utf-8")
    (shadow / "_claude" / "scripts" / "test_new.py").write_text("def test_n():\n    assert 1\n", encoding="utf-8")
    dirty = app.verify_clean_checkout(repo)
    assert dirty == ["README.md"]
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(tmp_path / "absent.jsonl")])
    assert rc == 1
    assert _git(repo, "diff", "--cached", "--name-only") == ""


# 2. mapping
def test_map_shadow_path():
    app = _load()
    assert app.map_shadow_path("_claude/scripts/x.py") == ".claude/scripts/x.py"
    assert app.map_shadow_path("_claude") == ".claude"
    assert app.map_shadow_path("Projects/X/work/n.md") == "Projects/X/work/n.md"
    assert app.map_shadow_path("_claudeX/y") == "_claudeX/y"
    assert app.map_shadow_path("a/_claude/b") == "a/_claude/b"
    assert app.map_real_path(".claude/scripts/x.py") == "_claude/scripts/x.py"
    assert app.map_real_path(app.map_shadow_path("_claude/a/b")) == "_claude/a/b"


# 3. allowlist and excludes
def test_class_paths_and_excludes(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "scripts")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    ok = app.Change(".claude/scripts/helper.py", "added", tmp_path / "helper.py")
    (tmp_path / "helper.py").write_text("ok\n", encoding="utf-8")
    excluded = app.Change(".claude/scripts/generic_logic.py", "added", tmp_path / "generic_logic.py")
    (tmp_path / "generic_logic.py").write_text("no\n", encoding="utf-8")
    outside = app.Change("Projects/X/work/n.md", "added", tmp_path / "n.md")
    (tmp_path / "n.md").write_text("no\n", encoding="utf-8")
    assert app.validate_changes([ok], cls, targets, tmp_path) == []
    v = app.validate_changes([excluded, outside], cls, targets, tmp_path)
    assert len(v) == 2
    assert any("generic_logic.py" in x and "exclude" in x for x in v)
    assert any("Projects/X/work/n.md" in x and "class" in x for x in v)
    # work-curation: its own excludes convention (a pattern with a slash matches the whole path)
    wc = app.load_class(targets_file, "work-curation")
    backup = app.Change("Projects/X/work/backups/scratch.md", "added", tmp_path / "n.md")
    assert any("exclude" in x for x in app.validate_changes([backup], wc, targets, tmp_path))


# 4. forbidden
def test_forbidden_paths_rejected_regardless_of_class(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    (tmp_path / "f.md").write_text("probe\n", encoding="utf-8")
    probe = app.Change(".claude/rules/self-heal-probe.md", "added", tmp_path / "f.md")
    guard = app.Change(".claude/hooks/bash-safety-guard.py", "modified", tmp_path / "f.md")
    ctl = app.Change(".claude/self-heal/targets.json", "modified", tmp_path / "f.md")
    v = app.validate_changes([probe, guard, ctl], cls, targets, tmp_path)
    assert len(v) >= 3
    assert all("forbidden" in x for x in v[:3])


# 5. symlink
def test_symlink_in_shadow_voids_the_round(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    link = shadow / "_claude" / "scripts" / "test_link.py"
    try:
        os.symlink(str(shadow / "README.md"), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this machine")
    tracked = app.list_checkout_tracked(repo)
    changes = app.diff_paths(app.list_shadow_paths(shadow), tracked, shadow, repo)
    assert [c.path for c in changes] == [".claude/scripts/test_link.py"]
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    v = app.validate_changes(changes, cls, targets, repo)
    assert v and "symlink" in v[0]


# 6. binary
def test_binary_content_voids_the_round(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    nul = tmp_path / "nul.py"
    nul.write_bytes(b"def test_x():\x00pass\n")
    bad_utf8 = tmp_path / "bad.py"
    bad_utf8.write_bytes(b"def test_y():\n    return '\xff\xfe'\n")
    fine = tmp_path / "fine.py"
    fine.write_bytes("def test_z():\n    return 'zażółć'\n".encode("utf-8"))
    assert app.is_binary(nul) and app.is_binary(bad_utf8) and not app.is_binary(fine)
    v = app.validate_changes([app.Change(".claude/scripts/test_nul.py", "added", nul)], cls, targets, tmp_path)
    assert v and "binary" in v[0]


# 7. size and count caps
def test_size_and_count_caps(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    big = tmp_path / "big.py"
    big.write_text("# " + "a" * (app.MAX_FILE_BYTES + 10) + "\n", encoding="utf-8")
    v = app.validate_changes([app.Change(".claude/scripts/test_big.py", "added", big)], cls, targets, tmp_path)
    assert v and "size" in v[0]
    small = tmp_path / "small.py"
    small.write_text("ok\n", encoding="utf-8")
    many = [app.Change(f".claude/scripts/test_{i}.py", "added", small) for i in range(app.MAX_CHANGED_FILES + 1)]
    v = app.validate_changes(many, cls, targets, tmp_path)
    assert v and any("count" in x for x in v)


# 8. deletion
def test_tracked_file_absent_from_shadow_is_staged_as_deletion(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    (shadow / "_claude" / "scripts" / "test_existing.py").unlink()
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(tmp_path / "absent.jsonl")])
    assert rc == 0
    assert _git(repo, "diff", "--cached", "--name-only").split() == [".claude/scripts/test_existing.py"]
    assert not (repo / ".claude" / "scripts" / "test_existing.py").exists()


# 9. empty set
def test_empty_change_set_fails_with_run_log_diagnosis(tmp_path, targets_file, capsys):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    log = tmp_path / "run.jsonl"
    log.write_text("\n".join([
        json.dumps({"type": "system", "subtype": "permission_denied", "tool_name": "Write",
                    "message": "Claude requested permissions to edit x which is a sensitive file."}),
        json.dumps({"type": "result", "result": "I could not write the file."}),
    ]) + "\n", encoding="utf-8")
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(log)])
    assert rc == 1
    out = capsys.readouterr()
    text = out.out + out.err
    assert "improver result text: I could not write the file." in text
    assert "permission denials: 1" in text
    assert "sensitive file" in text
    assert _git(repo, "diff", "--cached", "--name-only") == ""


# 10. live targets.json versus ci-settings.json agree on the sample paths
def test_live_targets_and_ci_settings_agree_on_sample_paths():
    app = _load()
    live = VAULT / ".claude" / "self-heal" / "targets.json"
    cs = json.loads((VAULT / ".claude" / "self-heal" / "ci-settings.json").read_text(encoding="utf-8"))
    targets = json.loads(live.read_text(encoding="utf-8"))
    glob = app._glob()

    def settings_allow_write(path: str) -> bool:
        pats = lambda rules: [r[len("Write("):-1] for r in rules if r.startswith("Write(")]
        if glob.path_matches_any(path, pats(cs["permissions"]["deny"])):
            return False
        return glob.path_matches_any(path, pats(cs["permissions"]["allow"]))

    samples = {
        ("scripts", ".claude/scripts/new_helper.py"): True,
        ("scripts", ".claude/scripts/generic_logic.py"): False,
        ("tests", ".claude/rules/self-heal-probe.md"): False,
        ("tests", ".claude/self-heal/targets.json"): False,
        ("work-curation", "Projects/X/work/backups/scratch.md"): False,
    }
    for (cls_name, path), expected in samples.items():
        cls = app.load_class(live, cls_name)
        src = VAULT / "README.md"
        verdict = app.validate_changes([app.Change(path, "added", src)], cls, targets, VAULT) == []
        assert verdict == expected, (cls_name, path, verdict)
        assert settings_allow_write(path) == expected, ("ci-settings", path)


# 11. end to end on a scratch repo
def test_end_to_end_added_modified_deleted(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    (shadow / "_claude" / "scripts" / "test_new.py").write_bytes(b"def test_n():\n    assert 1\n")
    (shadow / "_claude" / "scripts" / "test_existing.py").write_bytes(b"def test_a():\n    assert 2\n")
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(tmp_path / "absent.jsonl")])
    assert rc == 0
    staged = sorted(_git(repo, "diff", "--cached", "--name-only").split())
    assert staged == [".claude/scripts/test_existing.py", ".claude/scripts/test_new.py"]
    assert (repo / ".claude" / "scripts" / "test_new.py").read_bytes() == b"def test_n():\n    assert 1\n"
    assert (repo / ".claude" / "scripts" / "test_existing.py").read_bytes() == b"def test_a():\n    assert 2\n"
    # CRLF bytes survive the copy untouched
    (shadow / "_claude" / "scripts" / "test_new.py").write_bytes(b"def test_n():\r\n    assert 1\r\n")
    _git(repo, "commit", "-q", "-m", "round 1")
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(tmp_path / "absent.jsonl")])
    assert rc == 0
    assert (repo / ".claude" / "scripts" / "test_new.py").read_bytes() == b"def test_n():\r\n    assert 1\r\n"


def test_violation_copies_nothing_and_lists_every_offender(tmp_path, targets_file, capsys):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    (shadow / "_claude" / "scripts" / "test_new.py").write_text("ok\n", encoding="utf-8")
    (shadow / "_claude" / "rules").mkdir()
    (shadow / "_claude" / "rules" / "self-heal-probe.md").write_text("probe\n", encoding="utf-8")
    (shadow / "CLAUDE.md").write_text("changed doctrine\n", encoding="utf-8")
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(tmp_path / "absent.jsonl")])
    assert rc == 1
    err = capsys.readouterr().err
    assert ".claude/rules/self-heal-probe.md" in err and "CLAUDE.md" in err
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    assert not (repo / ".claude" / "scripts" / "test_new.py").exists()
    assert (repo / "CLAUDE.md").read_text(encoding="utf-8") == "doctrine\n"


# 12. build-cache noise ignored
def test_pycache_and_pyc_in_shadow_never_register(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    (shadow / "_claude" / "scripts" / "__pycache__").mkdir()
    (shadow / "_claude" / "scripts" / "__pycache__" / "x.cpython-314.pyc").write_bytes(b"\x00\x01")
    (shadow / "_claude" / "scripts" / "stray.pyc").write_bytes(b"\x00\x01")
    (shadow / ".pytest_cache").mkdir()
    (shadow / ".pytest_cache" / "v").write_text("x", encoding="utf-8")
    changes = app.diff_paths(app.list_shadow_paths(shadow), app.list_checkout_tracked(repo), shadow, repo)
    assert changes == []


# 13. checkout-side diff uses tracked files only
def test_untracked_checkout_files_are_not_deletions(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    (repo / "self-heal-run.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / ".claude" / "scripts" / "__pycache__").mkdir()
    (repo / ".claude" / "scripts" / "__pycache__" / "e.pyc").write_bytes(b"\x00")
    # the clean guard must also ignore those untracked files
    assert app.verify_clean_checkout(repo) == []
    changes = app.diff_paths(app.list_shadow_paths(shadow), app.list_checkout_tracked(repo), shadow, repo)
    assert changes == []


def test_nothing_to_do_is_a_green_noop_only_without_denials_and_never_when_a_change_is_expected(tmp_path, targets_file, capsys):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    log = tmp_path / "run.jsonl"
    log.write_text(json.dumps({"type": "result", "result": "Reviewed the target.\nnothing to do"}) + "\n", encoding="utf-8")
    common = ["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file), "--class", "tests", "--run-log", str(log)]
    assert app.main(common) == 0
    assert "::notice::" in capsys.readouterr().out
    assert app.main(common + ["--expect-change"]) == 1
    capsys.readouterr()
    log.write_text("\n".join([
        json.dumps({"type": "system", "subtype": "permission_denied", "tool_name": "Write", "message": "denied"}),
        json.dumps({"type": "result", "result": "nothing to do"}),
    ]) + "\n", encoding="utf-8")
    assert app.main(common) == 1
    assert "permission denials: 1" in capsys.readouterr().out


def test_added_path_differing_only_by_case_from_a_tracked_path_is_rejected(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    src = tmp_path / "s.py"
    src.write_text("ok\n", encoding="utf-8")
    tracked = {".claude/scripts/test_existing.py"}
    v = app.validate_changes([app.Change(".claude/scripts/Test_Existing.py", "added", src)], cls, targets, tmp_path, tracked)
    assert v and "case" in v[0]
    assert app.validate_changes([app.Change(".claude/scripts/test_existing.py", "modified", src)], cls, targets, tmp_path, tracked) == []


@pytest.mark.skipif(os.name == "nt", reason="mode bits are not meaningful on Windows")
def test_applied_files_never_inherit_the_shadow_mode(tmp_path, targets_file):
    app = _load()
    repo = _make_repo(tmp_path, BASE)
    shadow = _make_shadow(tmp_path, repo)
    new = shadow / "_claude" / "scripts" / "test_new.py"
    new.write_bytes(b"def test_n():\n    assert 1\n")
    os.chmod(new, 0o777)
    rc = app.main(["--checkout", str(repo), "--shadow", str(shadow), "--targets", str(targets_file),
                   "--class", "tests", "--run-log", str(tmp_path / "absent.jsonl")])
    assert rc == 0
    assert (repo / ".claude" / "scripts" / "test_new.py").stat().st_mode & 0o777 == 0o644


def test_unknown_class_is_an_error(targets_file):
    app = _load()
    with pytest.raises(SystemExit):
        app.load_class(targets_file, "no-such-class")


def test_path_hygiene_rejections(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    src = tmp_path / "s.py"
    src.write_text("ok\n", encoding="utf-8")
    bad = [
        app.Change(".claude/scripts/../rules/x.py", "added", src),
        app.Change(".claude/scripts/tеst_x.py", "added", src),  # Cyrillic e
        app.Change(".claude/scripts/test_x.py ", "added", src),
        app.Change(".claude/scripts/test\tx.py", "added", src),
    ]
    v = app.validate_changes(bad, cls, targets, tmp_path)
    assert len(v) >= 4


def test_diagnose_only_prints_the_result_text_and_touches_nothing(tmp_path, capsys):
    app = _load()
    log = tmp_path / "run.jsonl"
    log.write_text(json.dumps({"type": "result", "result": "You've hit your session limit"}) + "\n", encoding="utf-8")
    rc = app.main(["--diagnose-only", "--run-log", str(log), "--shadow", str(tmp_path / "none"), "--class", "tests"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "improver result text: You've hit your session limit" in out
    assert "permission denials: 0" in out


def test_two_added_paths_differing_only_by_case_in_one_round_are_rejected(tmp_path, targets_file):
    app = _load()
    cls = app.load_class(targets_file, "tests")
    targets = json.loads(targets_file.read_text(encoding="utf-8"))
    src = tmp_path / "s.py"
    src.write_text("ok", encoding="utf-8")
    pair = [app.Change(".claude/scripts/test_Foo.py", "added", src), app.Change(".claude/scripts/test_foo.py", "added", src)]
    v = app.validate_changes(pair, cls, targets, tmp_path, set())
    assert len(v) == 1 and "same round" in v[0]


# --- live allowlist: a logic change and its sibling test (round 35707695830) ---
LIVE_TARGETS = VAULT / ".claude" / "self-heal" / "targets.json"


def test_a_logic_change_with_its_sibling_test_passes_the_live_allowlist(tmp_path):
    """The 2026-09-22 scheduled round produced exactly this change set and the
    apply step rejected it: the class named the logic file and not the test the
    class itself requires. Validated against the live targets.json, not a copy."""
    app = _load()
    cls = app.load_class(LIVE_TARGETS, "hook-logic-with-tests")
    targets = json.loads(LIVE_TARGETS.read_text(encoding="utf-8"))
    logic = app.Change(".claude/hooks/_subagent_quality_logic.py", "modified", tmp_path / "l.py")
    test = app.Change(".claude/hooks/test_subagent_quality_check.py", "modified", tmp_path / "t.py")
    hook = app.Change(".claude/hooks/subagent-quality-check.py", "modified", tmp_path / "h.py")
    for ch in (logic, test, hook):
        Path(ch.source).write_text("ok\n", encoding="utf-8")
    assert app.validate_changes([logic, test], cls, targets, tmp_path) == []
    v = app.validate_changes([hook], cls, targets, tmp_path)
    assert len(v) == 1 and "class" in v[0]
