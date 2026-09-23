"""Tests for portability_buckets.py (A3, fixtures only, never live git ls-files).

Covers: bucket precedence (self-locating beats a comment elsewhere in the
file), hard-coded-literal detection, the depth() formula's two known
precedents, the fixture-bucket carve-out for install_prereqs.py-shaped
declared reference data, interpreter-path vs fixture distinguished, and
write_report()'s count/row-count consistency.
"""
from pathlib import Path

import portability_buckets as pb

FIXDIR = Path(__file__).resolve().parent / "_test_fixtures" / "blueprint" / "buckets"


def test_self_locating_precedence_over_literal_in_comment():
    fixture = FIXDIR / "self_locating_with_comment.py"
    rows = pb.scan([fixture], vault_root=FIXDIR)
    assert len(rows) == 1
    assert rows[0]["bucket"] == "self-locating"


def test_hard_coded_literal_detected():
    fixture = FIXDIR / "hard_coded_literal.py"
    rows = pb.scan([fixture], vault_root=FIXDIR)
    assert len(rows) == 1
    assert rows[0]["bucket"] == "hard-coded-vault-literal"


def test_depth_formula_matches_known_precedent():
    vault_root = Path("C:/fake-vault")
    scripts_path = vault_root / ".claude" / "scripts" / "x.py"
    self_heal_path = vault_root / ".claude" / "self-heal" / "scripts" / "x.py"
    assert pb.depth(scripts_path, vault_root) == 2
    assert pb.depth(self_heal_path, vault_root) == 3


def test_fixture_bucket_excludes_declared_reference_values():
    fixture = FIXDIR / "static_entries_declared_data.py"
    rows = pb.scan([fixture], vault_root=FIXDIR)
    assert len(rows) == 1
    assert rows[0]["bucket"] == "fixture"
    assert rows[0]["bucket"] != "hard-coded-vault-literal"


def test_interpreter_path_vs_fixture_distinguished():
    interp_fixture = FIXDIR / "interpreter_subprocess_call.py"
    static_fixture = FIXDIR / "static_entries_declared_data.py"
    interp_rows = pb.scan([interp_fixture], vault_root=FIXDIR)
    static_rows = pb.scan([static_fixture], vault_root=FIXDIR)
    assert interp_rows[0]["bucket"] == "interpreter-path"
    assert static_rows[0]["bucket"] == "fixture"
    assert interp_rows[0]["bucket"] != static_rows[0]["bucket"]


def test_report_counts_sum_to_scanned_files(tmp_path):
    rows = [
        {"file": "a.py", "bucket": "self-locating", "lines": [1]},
        {"file": "b.py", "bucket": "hard-coded-vault-literal", "lines": [1, 2]},
        {"file": "c.py", "bucket": "fixture", "lines": [3]},
        {"file": "d.py", "bucket": "prose-or-comment", "lines": [4]},
    ]
    out_path = tmp_path / "report.md"
    counts = pb.write_report(rows, out_path, generated="2026-09-22")
    assert out_path.is_file()
    assert sum(counts.values()) == len(rows)
