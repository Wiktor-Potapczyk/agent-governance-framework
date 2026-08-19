#!/usr/bin/env python3
"""Fixture test suite for transcript_search.py (Hermes P6, declarative-first).

Spec: Projects/your-project/work/2026-08-18-hermes-p6-transcript-search-plan.md
Step 2 fixture list (a)-(n) maps to tests as follows:
  (a) sess-aaaa-0001.jsonl        -> test_search_hit_and_miss, test_read_shape
  (b) sess-torn-0003.jsonl        -> test_torn_tail_skip_and_catchup
  (c) special chars in (a)        -> test_sanitize_special_char_queries
  (d) excluded record types in (a)-> test_excluded_types_not_indexed
  (e) grow pair (sess-grow-0004 + GROW_LINES appended in-test)
                                  -> test_incremental_appends_only
  (f) shrunk file (in-test)       -> test_shrunk_file_reindexed
  (g) sess-bbbb-0002.jsonl        -> test_search_bookends_and_window, browse tests
  (h) subagents/agent-test1.jsonl -> test_subagent_attribution_direct
  (i) subagents/workflows/wf-test1/agent-test2.jsonl
                                  -> test_nested_workflow_fixture_found (depth-open red guard)
  (j) journal.jsonl decoy         -> test_decoys_excluded
  (k) memory/memory-log.jsonl     -> test_decoys_excluded
  (l) temp git repo harness       -> test_ignore_guard_*
  (m) deleted-fixture case        -> test_stale_file_report_and_missing_notice
  (n) mid-file invalid UTF-8      -> test_corruption_replacement_lines
Plan-added constraint tests: test_cp1250_console_safe (cp1250 safety) and the
read-only byte assertion inside run_index (every indexer invocation).
Fixtures live ONLY under _test_fixtures/transcripts/; tests copy them to
tmp_path and never touch .claude/projects/ or the real .claude/transcript-index/.
"""
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

PY = sys.executable
SCRIPTS_DIR = Path(__file__).resolve().parent
SCRIPT = SCRIPTS_DIR / "transcript_search.py"
FIXTURES = SCRIPTS_DIR / "_test_fixtures" / "transcripts"

LONG_MSG = ("The pangolin ledger in the beta project needs a very long first user message "
            "so the browse label truncation to one hundred twenty characters can be proven "
            "by the fixture suite beyond doubt")

GROW_LINES = [
    {"type": "user", "uuid": "g-u3", "timestamp": "2026-08-04T09:01:00Z",
     "sessionId": "sess-grow-0004",
     "message": {"role": "user", "content": "newgrowthterm message three"}},
    {"type": "assistant", "uuid": "g-a3", "timestamp": "2026-08-04T09:01:05Z",
     "sessionId": "sess-grow-0004",
     "message": {"role": "assistant", "content": [{"type": "text", "text": "growth reply three"}]}},
    {"type": "user", "uuid": "g-u4", "timestamp": "2026-08-04T09:01:10Z",
     "sessionId": "sess-grow-0004",
     "message": {"role": "user", "content": "growth message four"}},
    {"type": "assistant", "uuid": "g-a4", "timestamp": "2026-08-04T09:01:15Z",
     "sessionId": "sess-grow-0004",
     "message": {"role": "assistant", "content": [{"type": "text", "text": "growth reply four"}]}},
]

TORN_COMPLETION = b' message arrives"}}\n'

EXCLUDED_MARKERS = [
    "toolresultsecret", "secretthink", "attachsecret", "systemsecret",
    "snapsecret", "titlesecret", "namesecret", "startedsecret", "permsecret",
    "journalsecret", "memorysecret",
]


# ---------- helpers ----------

def make_corpus(tmp_path):
    root = tmp_path / "projects"
    shutil.copytree(FIXTURES, root)
    return root


def snapshot(root):
    return {str(p): p.read_bytes() for p in sorted(Path(root).rglob("*.jsonl"))}


def run_cli(args, env_extra=None):
    if not SCRIPT.exists():
        pytest.fail("transcript_search.py does not exist yet (module absence)")
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([PY, str(SCRIPT)] + [str(a) for a in args],
                       capture_output=True, env=env)
    out = r.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    err = r.stderr.decode("utf-8", errors="replace").replace("\r\n", "\n")
    return r.returncode, out, err


def run_index(root, db, extra=(), expect_rc=0):
    """Every indexer invocation in this suite runs inside a read-only byte assertion."""
    before = snapshot(root)
    rc, out, err = run_cli(["index", "--root", root, "--db", db] + list(extra))
    after = snapshot(root)
    assert before == after, "indexer modified transcript fixture bytes (read-only violation)"
    assert rc == expect_rc, f"index rc={rc}\nstdout:\n{out}\nstderr:\n{err}"
    return out, err


def report_value(out, key):
    m = re.search(r"^" + re.escape(key) + r": (.+)$", out, re.M)
    assert m, f"missing report line {key!r} in output:\n{out}"
    return m.group(1).strip()


def indexed(tmp_path):
    root = make_corpus(tmp_path)
    db = tmp_path / "idx" / "transcripts.db"
    out, err = run_index(root, db)
    return root, db, out


def search(db, query, extra=()):
    return run_cli(["search", query, "--db", db] + list(extra))


def result_count(out):
    m = re.search(r"^results: (\d+)", out, re.M)
    assert m, f"missing results line in output:\n{out}"
    return int(m.group(1))


# ---------- discovery walk / kinds / decoys ----------

def test_discovery_kinds_and_counts(tmp_path):
    root, db, out = indexed(tmp_path)
    assert report_value(out, "files (session)") == "6"
    assert report_value(out, "files (subagent)") == "1"
    assert report_value(out, "files (workflow-subagent)") == "1"
    con = sqlite3.connect(db)
    rows = dict(con.execute("SELECT kind, COUNT(*) FROM files GROUP BY kind").fetchall())
    con.close()
    assert rows == {"session": 6, "subagent": 1, "workflow-subagent": 1}


def test_nested_workflow_fixture_found(tmp_path):
    """Red guard against a depth-literal discovery rule: the nested workflow
    worker at subagents/workflows/wf-test1/agent-test2.jsonl MUST be discovered."""
    root, db, out = indexed(tmp_path)
    con = sqlite3.connect(db)
    rows = con.execute("SELECT path, kind FROM files WHERE path LIKE '%agent-test2.jsonl'").fetchall()
    con.close()
    assert len(rows) == 1
    assert rows[0][1] == "workflow-subagent"
    assert "workflows" in rows[0][0]


def test_decoys_excluded(tmp_path):
    root, db, out = indexed(tmp_path)
    con = sqlite3.connect(db)
    bad = con.execute("SELECT path FROM files WHERE path LIKE '%journal.jsonl' "
                      "OR path LIKE '%memory-log.jsonl'").fetchall()
    con.close()
    assert bad == []
    for term in ("journalsecret", "memorysecret"):
        rc, out2, err = search(db, term)
        assert rc == 0
        assert result_count(out2) == 0


# ---------- hit / miss / exclusions ----------

def test_search_hit_and_miss(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = search(db, "quokka")
    assert rc == 0
    assert result_count(out2) >= 1
    rc, out3, err = search(db, "zzzunfindable")
    assert rc == 0
    assert result_count(out3) == 0


def test_excluded_types_not_indexed(tmp_path):
    root, db, out = indexed(tmp_path)
    for term in EXCLUDED_MARKERS:
        rc, out2, err = search(db, term)
        assert rc == 0, f"search {term} rc={rc}\n{err}"
        assert result_count(out2) == 0, f"excluded marker {term} was indexed"


# ---------- subagent attribution ----------

def test_subagent_attribution_direct(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = search(db, "marmoset")
    assert rc == 0
    assert result_count(out2) >= 1
    assert "agent agent-test1" in out2
    assert "kind subagent" in out2
    assert "session sess-aaaa-0001" in out2


def test_subagent_attribution_workflow(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = search(db, "axolotl")
    assert rc == 0
    assert result_count(out2) >= 1
    assert "agent agent-test2" in out2
    assert "kind workflow-subagent" in out2


def test_search_main_only_filter(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = search(db, "marmoset", ["--main-only"])
    assert rc == 0
    assert result_count(out2) == 0


# ---------- bookends and windows ----------

def test_search_bookends_and_window(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = search(db, "heron")
    assert rc == 0
    assert result_count(out2) == 1
    assert "alpha-start" in out2, "first-3 bookend missing"
    assert "omega-end" in out2, "last-3 bookend missing"
    m = re.search(r"^\s*match\| .*heron", out2, re.M)
    assert m, f"match line missing:\n{out2}"


# ---------- sanitization ----------

def test_sanitize_special_char_queries(tmp_path):
    root, db, out = indexed(tmp_path)
    queries = ['"quoted"', 'star*', 'colon:value', '(paren)', 'NEAR quokka',
               'quokka AND wombat', 'x" OR "quokka']
    for q in queries:
        rc, out2, err = search(db, q)
        assert rc == 0, f"query {q!r} rc={rc}\nstderr:\n{err}"
        assert "fts5" not in err.lower(), f"raw FTS5 error leaked for {q!r}: {err}"
        assert "Traceback" not in err
    rc, out2, err = search(db, "quokka AND wombat")
    assert result_count(out2) >= 1


def test_sanitize_empty_query_usage(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = search(db, "AND OR NOT NEAR")
    assert rc == 2
    assert "empty query" in (out2 + err).lower()
    assert "Traceback" not in err


# ---------- incremental / shrink / torn tail / corruption ----------

def test_incremental_appends_only(tmp_path):
    root, db, out = indexed(tmp_path)
    grow = root / "proj-alpha" / "sess-grow-0004.jsonl"
    con = sqlite3.connect(db)
    before = con.execute(
        "SELECT m.id, m.uuid FROM messages m JOIN files f ON f.id=m.file_id "
        "WHERE f.path LIKE '%sess-grow-0004.jsonl' ORDER BY m.id").fetchall()
    con.close()
    assert len(before) == 4
    with open(grow, "ab") as f:
        for rec in GROW_LINES:
            f.write(json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n")
    out2, err = run_index(root, db)
    assert report_value(out2, "messages new") == "4"
    assert report_value(out2, "files updated") == "1"
    con = sqlite3.connect(db)
    after = con.execute(
        "SELECT m.id, m.uuid FROM messages m JOIN files f ON f.id=m.file_id "
        "WHERE f.path LIKE '%sess-grow-0004.jsonl' ORDER BY m.id").fetchall()
    con.close()
    assert after[:4] == before, "prior row ids changed on incremental append"
    assert len(after) == 8
    rc, out3, err = search(db, "newgrowthterm")
    assert result_count(out3) == 1


def test_shrunk_file_reindexed(tmp_path):
    root, db, out = indexed(tmp_path)
    grow = root / "proj-alpha" / "sess-grow-0004.jsonl"
    lines = grow.read_bytes().splitlines(keepends=True)
    grow.write_bytes(b"".join(lines[:2]))
    out2, err = run_index(root, db)
    assert report_value(out2, "files reindexed") == "1"
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM messages m JOIN files f ON f.id=m.file_id "
                    "WHERE f.path LIKE '%sess-grow-0004.jsonl'").fetchone()[0]
    con.close()
    assert n == 2


def test_torn_tail_skip_and_catchup(tmp_path):
    root, db, out = indexed(tmp_path)
    assert report_value(out, "skipped tails") == "1"
    rc, out2, err = search(db, "tornfinal")
    assert result_count(out2) == 0, "torn tail must not be indexed"
    rc, out3, err = search(db, "ibex")
    assert result_count(out3) >= 1, "complete lines before the torn tail must index"
    torn = root / "proj-alpha" / "sess-torn-0003.jsonl"
    with open(torn, "ab") as f:
        f.write(TORN_COMPLETION)
    out4, err = run_index(root, db)
    assert report_value(out4, "skipped tails") == "0"
    assert report_value(out4, "messages new") == "1"
    rc, out5, err = search(db, "tornfinal")
    assert result_count(out5) == 1, "completed tail line must index on the next run"


def test_corruption_replacement_lines(tmp_path):
    root, db, out = indexed(tmp_path)
    # two corruption classes in the fixture: one raw invalid UTF-8 byte line,
    # one JSON \\ud83c escape producing a lone surrogate (live-corpus defect)
    assert report_value(out, "replacement_lines") == "2"
    rc, out2, err = search(db, "tailmarker")
    assert result_count(out2) == 1, "intact tail after the corrupt line must index"
    rc, out3, err = search(db, "osprey")
    assert result_count(out3) >= 3, "corrupt lines still index (mangled, not dropped)"
    rc, out4, err = search(db, "surrogate")
    assert result_count(out4) == 1, "lone-surrogate line must index with U+FFFD"


# ---------- stale files / missing-file notice ----------

def test_stale_file_report_and_missing_notice(tmp_path):
    root, db, out = indexed(tmp_path)
    assert report_value(out, "stale_files") == "0"
    victim = root / "proj-alpha" / "sess-bbbb-0002.jsonl"
    os.remove(victim)  # deliberate out-of-band fixture deletion (case m)
    out2, err = run_index(root, db)
    assert report_value(out2, "stale_files") == "1"
    rc, out3, err = run_cli(["read", "sess-bbbb-0002", "--db", db])
    assert rc == 0
    assert "missing transcript:" in out3
    assert "last indexed" in out3
    assert "Traceback" not in err
    rc, out4, err = run_cli(["scroll", "sess-bbbb-0002", "--db", db])
    assert rc == 0
    assert "missing transcript:" in out4
    assert "Traceback" not in err
    rc, out5, err = search(db, "capybara")
    assert rc == 0
    assert "missing transcript:" in out5
    assert "Traceback" not in err


# ---------- read / scroll shapes ----------

def test_read_shape(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["read", "sess-aaaa-0001", "--db", db])
    assert rc == 0
    assert "quokka indexing pipeline" in out2
    assert "wombat cache" in out2
    assert "secretthink" not in out2
    assert "toolresultsecret" not in out2


def test_scroll_shape(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["scroll", "sess-bbbb-0002", "--before", "2", "--after", "0", "--db", db])
    assert rc == 0
    assert "omega-end" in out2
    assert "alpha-start" not in out2, "scroll window must not span the whole session"


def test_scroll_read_by_agent_id(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["read", "agent-test1", "--db", db])
    assert rc == 0
    assert "marmoset delegation" in out2
    rc, out3, err = run_cli(["scroll", "agent-test2", "--before", "5", "--db", db])
    assert rc == 0
    assert "axolotl" in out3


# ---------- browse shapes ----------

def test_browse_lists_sessions_recent_first(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["browse", "--db", db])
    assert rc == 0
    data = [l for l in out2.splitlines() if l.startswith("sess-")]
    assert len(data) == 6
    assert data[0].startswith("sess-cccc-0006"), f"most recent session first, got:\n{out2}"


def test_browse_limit(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["browse", "--limit", "1", "--db", db])
    assert rc == 0
    data = [l for l in out2.splitlines() if l.startswith("sess-")]
    assert len(data) == 1


def test_browse_project_filter(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["browse", "--project", "proj-beta", "--db", db])
    assert rc == 0
    data = [l for l in out2.splitlines() if l.startswith("sess-")]
    assert len(data) == 1
    assert data[0].startswith("sess-cccc-0006")


def test_browse_label_truncated_120(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["browse", "--db", db])
    assert rc == 0
    assert LONG_MSG not in out2, "label must be truncated to 120 chars"
    assert LONG_MSG[:120] in out2


def test_browse_agents_grouping(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, out2, err = run_cli(["browse", "--agents", "sess-aaaa-0001", "--db", db])
    assert rc == 0
    assert "[subagent] agent-test1" in out2
    assert "workflow wf-test1:" in out2
    m = re.search(r"workflow wf-test1:\n\s+\[workflow-subagent\] agent-test2", out2)
    assert m, f"workflow worker not grouped under its run id:\n{out2}"


# ---------- ignore guard (temp git repo harness, case l) ----------

def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    r = subprocess.run(["git", "init", "-q", str(repo)], capture_output=True)
    assert r.returncode == 0, r.stderr
    return repo


def test_ignore_guard_aborts_in_non_ignored_git_repo(tmp_path):
    root = make_corpus(tmp_path)
    repo = _git_repo(tmp_path)
    db = repo / "idx" / "transcripts.db"
    rc, out, err = run_cli(["index", "--root", root, "--db", db])
    assert rc != 0
    assert "not git-ignored" in (out + err)
    assert not db.parent.exists(), "guard must abort before creating the index directory"
    assert not db.exists()


def test_ignore_guard_proceeds_when_ignored(tmp_path):
    root = make_corpus(tmp_path)
    repo = _git_repo(tmp_path)
    (repo / ".gitignore").write_text("idx/\n", encoding="utf-8")
    db = repo / "idx" / "transcripts.db"
    out, err = run_index(root, db)
    assert db.exists()


# ---------- concurrency: busy_timeout serialization ----------

def test_locked_db_exits_loudly(tmp_path):
    root, db, out = indexed(tmp_path)
    con = sqlite3.connect(db)
    con.execute("BEGIN IMMEDIATE")
    try:
        rc, out2, err = run_cli(["index", "--root", root, "--db", db])
    finally:
        con.rollback()
        con.close()
    assert rc == 1
    assert "locked" in (out2 + err).lower()
    assert "Traceback" not in err


# ---------- cp1250 console safety (plan constraint 6) ----------

def test_cp1250_console_safe(tmp_path):
    root, db, out = indexed(tmp_path)
    rc, raw_out, err = run_cli(["read", "sess-aaaa-0001", "--db", db],
                               env_extra={"PYTHONIOENCODING": "cp1250"})
    assert rc == 0, f"CLI crashed under cp1250 console encoding:\n{err}"
    assert "★" in raw_out, "non-cp1250 character must survive via UTF-8 reconfigure"


# ---------- rebuild / read-only ----------

def test_rebuild(tmp_path):
    root, db, out = indexed(tmp_path)
    total1 = report_value(out, "messages total")
    out2, err = run_index(root, db, extra=["--rebuild"])
    assert report_value(out2, "messages total") == total1
    assert report_value(out2, "files (session)") == "6"


def test_readonly_bytes_across_runs(tmp_path):
    """Explicit read-only check; run_index also asserts this on every invocation."""
    root = make_corpus(tmp_path)
    db = tmp_path / "idx" / "transcripts.db"
    before = snapshot(root)
    run_index(root, db)
    run_index(root, db)
    assert snapshot(root) == before


# ---------- help epilog ----------

def test_help_contains_source_priority(tmp_path):
    rc, out, err = run_cli(["--help"])
    assert rc == 0
    assert "not evidence" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
