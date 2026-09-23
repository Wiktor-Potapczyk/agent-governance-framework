"""Tests for self_heal_pr_body.py (the improver workflow's PR title and body
helper). Closes the phase (c) review gap that the helper had no test file."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("self_heal_pr_body", HERE / "self_heal_pr_body.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _write_log(path: Path, lines):
    path.write_text("\n".join(json.dumps(x) if not isinstance(x, str) else x for x in lines) + "\n", encoding="utf-8")


def test_result_text_comes_from_the_last_result_message(tmp_path):
    prb = _load()
    log = tmp_path / "run.jsonl"
    _write_log(log, [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": "working"}},
        "{not json",
        {"type": "result", "result": "Created the scratch test.\nTEST ROUND COMPLETE", "total_cost_usd": 0.01},
    ])
    assert prb.extract_claude_result_text(log) == "Created the scratch test.\nTEST ROUND COMPLETE"


def test_missing_or_resultless_log_yields_placeholder(tmp_path):
    prb = _load()
    assert prb.extract_claude_result_text(tmp_path / "absent.jsonl") == prb.NO_SUMMARY_TEXT
    log = tmp_path / "run.jsonl"
    _write_log(log, [{"type": "assistant", "message": {"content": "x"}}])
    assert prb.extract_claude_result_text(log) == prb.NO_SUMMARY_TEXT


def test_title_and_body_shape():
    prb = _load()
    assert prb.build_title(pr_class="tests", source="test-round", as_of="2026-09-18") == "self-heal: tests 2026-09-18 (test-round)"
    body = prb.build_body(deliverable_path=".claude/scripts/x.py", config_version="abc123",
                          summary=" done ", diff_stat=" 1 file changed ")
    lines = body.splitlines()
    assert lines[0] == "deliverable_path: .claude/scripts/x.py"
    assert lines[1] == "config_version: abc123"
    assert lines[2] == "rollback: "
    assert "done" in body and "1 file changed" in body
    assert body.rstrip().endswith("`PROMPT.md`.")
    assert "Comment `no: <reason>` to reject." in body
    assert "Click merge if you agree." in body


def test_deliverable_path_and_diff_stat_from_a_scratch_repo(tmp_path):
    prb = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    g = ["git", "-C", str(repo)]
    subprocess.run(g[:1] + ["init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(g + ["config", "user.email", "t@example.com"], check=True)
    subprocess.run(g + ["config", "user.name", "t"], check=True)
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(g + ["add", "base.txt"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "base"], check=True)
    base = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (repo / "b_second.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "a_first.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(g + ["add", "a_first.py", "b_second.py"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "round"], check=True)
    assert prb.git_diff_deliverable_path(repo, base) == "a_first.py"
    stat = prb.git_diff_stat(repo, base)
    assert "2 files changed" in stat
    assert prb.git_diff_deliverable_path(repo, "HEAD") == "(no changed files)"


def test_main_writes_both_files(tmp_path):
    prb = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    g = ["git", "-C", str(repo)]
    subprocess.run(g[:1] + ["init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(g + ["config", "user.email", "t@example.com"], check=True)
    subprocess.run(g + ["config", "user.name", "t"], check=True)
    (repo / "f.txt").write_text("1\n", encoding="utf-8")
    subprocess.run(g + ["add", "f.txt"], check=True)
    subprocess.run(g + ["commit", "-q", "-m", "one"], check=True)
    base = subprocess.run(g + ["rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    log = tmp_path / "run.jsonl"
    _write_log(log, [{"type": "result", "result": "summary here"}])
    title, body = tmp_path / "t.txt", tmp_path / "b.md"
    rc = prb.main(["--class", "tests", "--source", "test-round", "--config-version", base,
                   "--claude-log", str(log), "--main-checkout", str(repo),
                   "--title-out", str(title), "--body-out", str(body)])
    assert rc == 0
    assert title.read_text(encoding="utf-8").startswith("self-heal: tests ")
    text = body.read_text(encoding="utf-8")
    assert "deliverable_path: (no changed files)" in text
    assert "summary here" in text
