"""
test_staleness_check_generated.py - pytest suite for the O10 extensions to
staleness_check.py (Projects/Agent-Governance-Research/work/
2026-09-02-o10-staleness-generation-plan.md, Step 2; spec O10 of
2026-08-31-harness-takeover-objectives.md).

Covers the checker-side contract the O10 generator relies on:
  - loader merges generated_block.entries with the hand entries array (D3)
  - a duplicate id across the two sections is a MANIFEST error (D3)
  - an old-shape manifest (no generated_block) loads unchanged (D3;
    backward-compat regression guard, green by construction pre-change)
  - advisory entries downgrade any non-PASS verdict to WARN, excluded from
    the CLI exit-2 set (D4)
  - line_count_probe, dir_count_probe, provenance_count_probe (D5)
  - max_age_days optional on line_count_probe / dir_count_probe entries,
    still required otherwise (D5)
  - hook mode with a WARN entry emits at most an advisory line, exit 0 (D4)

All fixtures are tmp_path-synthetic; none touch live files.

Run from inside .claude/scripts:
    "C:\\Program Files\\Python314\\python.exe" -m pytest test_staleness_check_generated.py -v
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import staleness_check as sc  # noqa: E402


def _write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _base_entry(name, **extra):
    entry = {
        "id": name,
        "artifact_path": f"{name}.md",
        "max_age_days": 7,
        "rederive_command": f"echo {name}",
    }
    entry.update(extra)
    return entry


# ---------------------------------------------------------------------------
# D3: loader merges generated_block.entries with entries
# ---------------------------------------------------------------------------

def test_loader_merges_generated_block_entries_with_hand_entries(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {
        "generated_at": "2026-09-02T00:00:00",
        "entries": [_base_entry("hand-a"), _base_entry("hand-b")],
        "generated_block": {
            "do_not_edit": "GENERATED - do not hand-edit",
            "source_inventory_generated_at": "2026-09-01T15:01:31Z",
            "entries": [_base_entry("gen-a"), _base_entry("gen-b"), _base_entry("gen-c")],
        },
    })
    entries = sc.load_manifest(manifest)
    assert [e["id"] for e in entries] == ["hand-a", "hand-b", "gen-a", "gen-b", "gen-c"]


def test_loader_validates_generated_entries_with_same_required_fields(tmp_path):
    manifest = tmp_path / "manifest.json"
    broken = _base_entry("gen-a")
    del broken["rederive_command"]
    _write_json(manifest, {
        "entries": [_base_entry("hand-a")],
        "generated_block": {"entries": [broken]},
    })
    with pytest.raises(sc.ManifestError, match="MANIFEST_MALFORMED"):
        sc.load_manifest(manifest)


# ---------------------------------------------------------------------------
# D3: duplicate id across sections is a MANIFEST error
# ---------------------------------------------------------------------------

def test_duplicate_id_across_sections_raises_manifest_error(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {
        "entries": [_base_entry("cmdb-vault-setup")],
        "generated_block": {"entries": [_base_entry("cmdb-vault-setup")]},
    })
    with pytest.raises(sc.ManifestError, match="MANIFEST_DUPLICATE_ID"):
        sc.load_manifest(manifest)


def test_duplicate_id_error_names_the_colliding_id(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {
        "entries": [_base_entry("cmdb-vault-setup")],
        "generated_block": {"entries": [_base_entry("cmdb-vault-setup")]},
    })
    with pytest.raises(sc.ManifestError, match="cmdb-vault-setup"):
        sc.load_manifest(manifest)


# ---------------------------------------------------------------------------
# D3: old-shape manifest (no generated_block) loads unchanged
# NOTE: green by construction against the pre-change checker; kept as the
# backward-compatibility regression guard the plan's Step 2 item (3) names.
# ---------------------------------------------------------------------------

def test_old_shape_manifest_loads_unchanged(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {
        "generated_at": "2026-08-30T00:00:00",
        "entries": [_base_entry("a"), _base_entry("b")],
    })
    entries = sc.load_manifest(manifest)
    assert [e["id"] for e in entries] == ["a", "b"]


# ---------------------------------------------------------------------------
# D4: advisory entries downgrade non-PASS verdicts to WARN
# ---------------------------------------------------------------------------

def test_advisory_failing_probe_yields_warn_and_cli_exit_zero(tmp_path, capsys):
    (tmp_path / "big.md").write_text("line\n" * 50, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {
        "entries": [{
            "id": "big",
            "artifact_path": "big.md",
            "rederive_command": "trim it",
            "advisory": True,
            "line_count_probe": {"max_lines": 10},
        }],
    })
    results = sc.run_check(manifest, tmp_path)
    assert results[0].verdict == sc.VERDICT_WARN
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path)])
    assert exit_code == 0


def test_advisory_error_verdict_also_downgrades_to_warn(tmp_path):
    entry = {
        "id": "gone",
        "artifact_path": "does-not-exist.md",
        "max_age_days": 7,
        "rederive_command": "echo gone",
        "advisory": True,
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_WARN
    assert "ERROR" in result.detail  # the original verdict stays visible


def test_non_advisory_failing_entry_still_exits_two(tmp_path, capsys):
    (tmp_path / "big.md").write_text("line\n" * 50, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {
        "entries": [{
            "id": "big",
            "artifact_path": "big.md",
            "rederive_command": "trim it",
            "line_count_probe": {"max_lines": 10},
        }],
    })
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path)])
    assert exit_code == 2


def test_advisory_passing_entry_stays_pass(tmp_path):
    (tmp_path / "small.md").write_text("line\n" * 5, encoding="utf-8")
    entry = {
        "id": "small",
        "artifact_path": "small.md",
        "rederive_command": "n/a",
        "advisory": True,
        "line_count_probe": {"max_lines": 10},
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS


# ---------------------------------------------------------------------------
# D5(i): line_count_probe
# ---------------------------------------------------------------------------

def test_line_count_probe_over_max_lines_is_stale(tmp_path):
    (tmp_path / "doc.md").write_text("line\n" * 12, encoding="utf-8")
    entry = {
        "id": "doc", "artifact_path": "doc.md",
        "rederive_command": "trim", "line_count_probe": {"max_lines": 10},
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_STALE
    assert "12" in result.detail and "10" in result.detail


def test_line_count_probe_under_max_lines_is_pass(tmp_path):
    (tmp_path / "doc.md").write_text("line\n" * 8, encoding="utf-8")
    entry = {
        "id": "doc", "artifact_path": "doc.md",
        "rederive_command": "trim", "line_count_probe": {"max_lines": 10},
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS


# ---------------------------------------------------------------------------
# D5(ii): dir_count_probe
# ---------------------------------------------------------------------------

def test_dir_count_probe_under_min_count_is_stale(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "one.md").write_text("rule\n", encoding="utf-8")
    entry = {
        "id": "rules-dir", "artifact_path": "rules",
        "rederive_command": "populate rules",
        "dir_count_probe": {"dir": "rules", "glob": "*.md", "min_count": 2},
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_STALE
    assert "below min" in result.detail


def test_dir_count_probe_at_min_count_is_pass(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "one.md").write_text("rule\n", encoding="utf-8")
    (rules / "two.md").write_text("rule\n", encoding="utf-8")
    entry = {
        "id": "rules-dir", "artifact_path": "rules",
        "rederive_command": "populate rules",
        "dir_count_probe": {"dir": "rules", "glob": "*.md", "min_count": 2},
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS


def test_dir_count_probe_missing_dir_is_error(tmp_path):
    (tmp_path / "placeholder.md").write_text("x\n", encoding="utf-8")
    entry = {
        "id": "rules-dir", "artifact_path": "placeholder.md",
        "rederive_command": "populate rules",
        "dir_count_probe": {"dir": "no-such-dir", "glob": "*.md", "min_count": 2},
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_ERROR


# ---------------------------------------------------------------------------
# D5(iii): provenance_count_probe
# ---------------------------------------------------------------------------

def _provenance_fixture(tmp_path, index_row_count):
    inventory = {
        "generated_at": "2026-09-01T15:01:31Z",
        "rows": [
            {"name": "a", "kind": "hook", "provenance": "authored-in-harness"},
            {"name": "b", "kind": "skill", "provenance": "authored-in-harness"},
            {"name": "c", "kind": "skill", "provenance": "junction:C:/somewhere"},
            {"name": "d", "kind": "skill", "provenance": "plugin:x/y"},
        ],
    }
    _write_json(tmp_path / "inventory.json", inventory)
    _write_json(tmp_path / "index.json", {
        "generated_at": "2026-09-01T16:00:00Z",
        "row_count": index_row_count,
    })
    return {
        "id": "rationale-index",
        "artifact_path": "index.json",
        "max_age_days": 3650,
        "rederive_command": "regenerate the index",
        "provenance_count_probe": {
            "source_file": "inventory.json",
            "exact": ["authored-in-harness"],
            "prefixes": ["junction:"],
            "expected_key_path": ["row_count"],
        },
    }


def test_provenance_count_probe_match_is_pass(tmp_path):
    entry = _provenance_fixture(tmp_path, index_row_count=3)
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS


def test_provenance_count_probe_mismatch_is_stale(tmp_path):
    entry = _provenance_fixture(tmp_path, index_row_count=2)
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_STALE
    assert "provenance count mismatch" in result.detail
    assert "2" in result.detail and "3" in result.detail


def test_provenance_count_probe_missing_source_is_error(tmp_path):
    entry = _provenance_fixture(tmp_path, index_row_count=3)
    (tmp_path / "inventory.json").unlink()
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_ERROR


# ---------------------------------------------------------------------------
# D5: max_age_days optional on line_count/dir_count entries, required otherwise
# ---------------------------------------------------------------------------

def test_max_age_days_optional_with_line_count_probe(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"entries": [{
        "id": "a", "artifact_path": "a.md", "rederive_command": "echo a",
        "line_count_probe": {"max_lines": 10},
    }]})
    entries = sc.load_manifest(manifest)
    assert "max_age_days" not in entries[0]


def test_max_age_days_optional_with_dir_count_probe(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"entries": [{
        "id": "a", "artifact_path": "rules", "rederive_command": "echo a",
        "dir_count_probe": {"dir": "rules", "glob": "*.md", "min_count": 2},
    }]})
    entries = sc.load_manifest(manifest)
    assert "max_age_days" not in entries[0]


def test_max_age_days_still_required_without_exempting_probe(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"entries": [{
        "id": "a", "artifact_path": "a.md", "rederive_command": "echo a",
        "provenance_count_probe": {
            "source_file": "inv.json", "exact": ["x"], "prefixes": [],
            "expected_key_path": ["row_count"],
        },
    }]})
    with pytest.raises(sc.ManifestError, match="MANIFEST_MALFORMED"):
        sc.load_manifest(manifest)


# ---------------------------------------------------------------------------
# D4: hook mode with a WARN entry - at most an advisory line, never a block
# ---------------------------------------------------------------------------

def test_hook_mode_warn_entry_emits_one_advisory_line_and_exit_zero(tmp_path, capsys):
    (tmp_path / "big.md").write_text("line\n" * 50, encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_json(manifest, {"entries": [{
        "id": "governing-size", "artifact_path": "big.md",
        "rederive_command": "trim it", "advisory": True,
        "line_count_probe": {"max_lines": 10},
    }]})
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path), "--hook"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert context.count("governing-size") == 1
    assert "WARN" in context


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
