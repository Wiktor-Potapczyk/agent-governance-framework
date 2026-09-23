"""Tests for lint_pass_kb_index_budget.py (ROAD-8, Pass U).

Declarative-first: written before the implementation. Temp budget files and
a fixture index copy; no live _state/ file is written by any test.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_kb_index_budget.py"

INDEX_TEXT = (
    "# KB index\n\n"
    "| Path | Title |\n"
    "|---|---|\n"
    "| a.md | A |\n"
    "| b.md | B |\n"
    "| c.md | C |\n"
)  # 3 data rows


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def write_fixture(tmp_path, budget_bytes, budget_entries):
    idx = tmp_path / "index.md"
    idx.write_text(INDEX_TEXT, encoding="utf-8", newline="\n")
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({
        "generated_iso": "2026-09-08T00:00:00Z",
        "seed_bytes": len(INDEX_TEXT.encode()),
        "seed_entries": 3,
        "headroom_factor": 1.5,
        "budget_bytes": budget_bytes,
        "budget_entries": budget_entries,
    }), encoding="utf-8")
    return idx, budget


def test_under_budget_clean(tmp_path):
    idx, budget = write_fixture(tmp_path, 10000, 100)
    r = run("--index-file", str(idx), "--budget-file", str(budget))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "KB_INDEX_BUDGET" not in r.stdout
    assert "bytes=" in r.stdout and "entries=3" in r.stdout  # always-print


def test_over_byte_budget_one_finding(tmp_path):
    idx, budget = write_fixture(tmp_path, 10, 100)
    r = run("--index-file", str(idx), "--budget-file", str(budget))
    assert r.returncode == 1
    findings = [l for l in r.stdout.splitlines() if l.startswith("KB_INDEX_BUDGET")]
    assert len(findings) == 1
    assert "budget=10" in findings[0]


def test_over_entry_budget_one_finding(tmp_path):
    idx, budget = write_fixture(tmp_path, 10000, 2)
    r = run("--index-file", str(idx), "--budget-file", str(budget))
    assert r.returncode == 1
    findings = [l for l in r.stdout.splitlines() if l.startswith("KB_INDEX_BUDGET")]
    assert len(findings) == 1
    assert "entries=3" in findings[0] and "entry_budget=2" in findings[0]


def test_missing_budget_file_exits_2(tmp_path):
    idx = tmp_path / "index.md"
    idx.write_text(INDEX_TEXT, encoding="utf-8")
    r = run("--index-file", str(idx), "--budget-file", str(tmp_path / "absent.json"))
    assert r.returncode == 2
    assert "KB_INDEX_BUDGET" not in r.stdout


def test_seed_mode_writes_computed_budget(tmp_path):
    idx = tmp_path / "index.md"
    idx.write_text(INDEX_TEXT, encoding="utf-8", newline="\n")
    budget = tmp_path / "budget.json"
    r = run("--seed", "--index-file", str(idx), "--budget-file", str(budget))
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(budget.read_text(encoding="utf-8"))
    nbytes = len(INDEX_TEXT.encode())
    assert data["seed_bytes"] == nbytes
    assert data["seed_entries"] == 3
    assert data["headroom_factor"] == 1.5
    assert data["budget_bytes"] == int(round(nbytes * 1.5 / 100.0)) * 100
    assert data["budget_entries"] == int(round(3 * 1.5))
