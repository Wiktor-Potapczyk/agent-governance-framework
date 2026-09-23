"""Tests for ledger_check.py (resolved-ledger to register computational join,
architect finding 2026-08-31)."""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "ledger_check.py"
PY = sys.executable

REG_A = {"findings": [
    {"path": ".claude/hooks/guard.py", "batch": 3, "severity": "high",
     "summary": "Wrapping any command in `bash -c \"...\"` erases it from the scan entirely."},
    {"path": ".claude/hooks/guard.py", "batch": 3, "severity": "low",
     "summary": "The module docstring claims a deny the code does not perform."},
    {"path": ".claude/hooks/other.py", "batch": 1, "severity": "high",
     "summary": "Something else entirely."},
]}
REG_B = {"findings": [
    {"path": ".claude/scripts/x.py", "batch": 2, "severity": "high",
     "summary": "A tier B finding."},
]}
ENTRY = {"key": "tierA:.claude/hooks/guard.py:batch3:wrapper-erases",
         "tier": "A", "path": ".claude/hooks/guard.py", "severity": "high",
         "summary_prefix": "Wrapping any command in bash -c erases it from the scan"}


def _setup(tmp_path, entries=None, reg_a=None):
    a = tmp_path / "tierA.json"
    a.write_text(json.dumps(reg_a if reg_a is not None else REG_A), encoding="utf-8")
    b = tmp_path / "tierB.json"
    b.write_text(json.dumps(REG_B), encoding="utf-8")
    led = tmp_path / "ledger.jsonl"
    rows = entries if entries is not None else [ENTRY]
    led.write_text("".join(json.dumps(e) + "\n" for e in rows), encoding="utf-8")
    return led, a, b


def _run(led, a, b):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [PY, str(SCRIPT), "--ledger", str(led), "--tier-a", str(a), "--tier-b", str(b)],
        capture_output=True, text=True, env=env, timeout=60)


def test_unique_match_passes_with_counts(tmp_path):
    r = _run(*_setup(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK tierA:.claude/hooks/guard.py:batch3:wrapper-erases" in r.stdout
    assert "metric-2: 3 raw HIGH, 1 resolved, 2 open-or-unassessed" in r.stdout


def test_paraphrased_prefix_still_joins_in_order(tmp_path):
    """Backtick/punctuation elisions in the prefix must not break the join;
    the tokens appear in order with gaps."""
    e = dict(ENTRY, summary_prefix="Wrapping any command erases it from the scan")
    r = _run(*_setup(tmp_path, entries=[e]))
    assert r.returncode == 0, r.stdout + r.stderr


def test_zero_matches_fails_loud(tmp_path):
    e = dict(ENTRY, summary_prefix="totally unrelated words here")
    r = _run(*_setup(tmp_path, entries=[e]))
    assert r.returncode == 2
    assert "matched 0 register rows" in (r.stdout + r.stderr)


def test_ambiguous_match_fails_loud(tmp_path):
    reg = {"findings": REG_A["findings"] + [
        {"path": ".claude/hooks/guard.py", "batch": 3, "severity": "high",
         "summary": "Wrapping any command in a subshell erases it from the scan too."}]}
    e = dict(ENTRY, summary_prefix="Wrapping any command erases it from the scan")
    r = _run(*_setup(tmp_path, entries=[e], reg_a=reg))
    assert r.returncode == 2
    assert "matched 2 register rows" in (r.stdout + r.stderr)


def test_duplicate_resolution_of_same_row_fails_loud(tmp_path):
    e2 = dict(ENTRY, key="tierA:.claude/hooks/guard.py:batch3:other-slug")
    r = _run(*_setup(tmp_path, entries=[ENTRY, e2]))
    assert r.returncode == 2
    assert "SAME register row" in (r.stdout + r.stderr)


def test_severity_mismatch_fails_loud(tmp_path):
    e = dict(ENTRY, severity="low")
    r = _run(*_setup(tmp_path, entries=[e]))
    assert r.returncode == 2
    assert "severity" in (r.stdout + r.stderr)


def test_missing_ledger_fails_loud(tmp_path):
    led, a, b = _setup(tmp_path)
    led.unlink()
    r = _run(led, a, b)
    assert r.returncode == 2
    assert "ERROR" in (r.stdout + r.stderr)


def test_output_deterministic(tmp_path):
    led, a, b = _setup(tmp_path)
    r1, r2 = _run(led, a, b), _run(led, a, b)
    assert r1.stdout == r2.stdout and r1.returncode == r2.returncode == 0
