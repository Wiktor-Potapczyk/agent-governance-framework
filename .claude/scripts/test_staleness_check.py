"""
test_staleness_check.py - pytest suite for staleness_check.py.

Run from inside .claude/scripts:
    "C:\\Program Files\\Python314\\python.exe" -m pytest test_staleness_check.py -v

Covers, per the O4 CHECK contract:
  - manifest parse (well-formed manifest loads its entries)
  - one fresh entry verdicts PASS
  - one stale entry verdicts STALE (age past max_age_days)
  - empty-manifest exits non-zero via CLI, and raises ManifestError at the
    library level, so a manifest resolving to nothing is never a clean bill
  - a few adjacent branches (ERROR on missing artifact, live-count mismatch,
    manifest validation) exercised for the same reason the ceremony_cost_report
    suite exercises its own fail-loud paths: a checker's safety property is
    only real once its failure branch is proven to fire.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import staleness_check as sc  # noqa: E402


def _write_manifest(path, entries, generated_at="2026-08-30T00:00:00"):
    path.write_text(
        json.dumps({"generated_at": generated_at, "entries": entries}),
        encoding="utf-8",
    )


def _fresh_artifact(tmp_path, name="fresh.md", days_old=0):
    path = tmp_path / name
    path.write_text("fresh artifact\n", encoding="utf-8")
    if days_old:
        stamp = (datetime.now() - timedelta(days=days_old)).timestamp()
        import os
        os.utime(path, (stamp, stamp))
    return path


# ---------------------------------------------------------------------------
# Manifest parse
# ---------------------------------------------------------------------------

def test_load_manifest_parses_well_formed_entries(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "a", "artifact_path": "a.md", "max_age_days": 7, "rederive_command": "echo a"},
    ])
    entries = sc.load_manifest(manifest)
    assert len(entries) == 1
    assert entries[0]["id"] == "a"


def test_load_manifest_raises_on_missing_required_field(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "a", "artifact_path": "a.md", "max_age_days": 7},  # rederive_command missing
    ])
    with pytest.raises(sc.ManifestError, match="MANIFEST_MALFORMED"):
        sc.load_manifest(manifest)


def test_load_manifest_raises_on_invalid_json(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(sc.ManifestError, match="MANIFEST_INVALID_JSON"):
        sc.load_manifest(manifest)


def test_load_manifest_raises_on_missing_file(tmp_path):
    manifest = tmp_path / "does-not-exist.json"
    with pytest.raises(sc.ManifestError, match="MANIFEST_NOT_FOUND"):
        sc.load_manifest(manifest)


# ---------------------------------------------------------------------------
# One fresh entry -> PASS
# ---------------------------------------------------------------------------

def test_fresh_entry_verdicts_pass(tmp_path):
    artifact = _fresh_artifact(tmp_path, days_old=0)
    entry = {
        "id": "fresh", "artifact_path": artifact.name,
        "max_age_days": 7, "rederive_command": "echo fresh",
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS
    assert result.age_days is not None and result.age_days < 1


# ---------------------------------------------------------------------------
# One stale entry -> STALE
# ---------------------------------------------------------------------------

def test_stale_entry_verdicts_stale_on_age(tmp_path):
    artifact = _fresh_artifact(tmp_path, name="stale.md", days_old=30)
    entry = {
        "id": "stale", "artifact_path": artifact.name,
        "max_age_days": 7, "rederive_command": "echo stale",
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_STALE
    assert "exceeds max" in result.detail


def test_stale_entry_verdicts_stale_on_live_count_mismatch(tmp_path):
    artifact = _fresh_artifact(tmp_path, name="counted.md", days_old=0)
    artifact.write_text("| Agents | 5 | registry.json counts |\n", encoding="utf-8")
    source = tmp_path / "registry.json"
    source.write_text(json.dumps({"counts": {"agents": 9}}), encoding="utf-8")
    entry = {
        "id": "counted", "artifact_path": artifact.name,
        "max_age_days": 7, "rederive_command": "echo counted",
        "live_count_probe": {
            "source_file": "registry.json",
            "source_key_path": ["counts"],
            "table_metric_map": {"Agents": "agents"},
        },
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_STALE
    assert "live-count mismatch" in result.detail
    assert "embedded=5 live=9" in result.detail


def test_run_check_stays_silent_free_of_stale_after_regeneration(tmp_path):
    manifest = tmp_path / "manifest.json"
    artifact = _fresh_artifact(tmp_path, name="doc.md", days_old=30)
    _write_manifest(manifest, [
        {"id": "doc", "artifact_path": "doc.md", "max_age_days": 7, "rederive_command": "echo doc"},
    ])
    stale_results = sc.run_check(manifest, tmp_path)
    assert stale_results[0].verdict == sc.VERDICT_STALE

    import os
    now = datetime.now().timestamp()
    os.utime(artifact, (now, now))
    fresh_results = sc.run_check(manifest, tmp_path)
    assert fresh_results[0].verdict == sc.VERDICT_PASS


# ---------------------------------------------------------------------------
# ERROR verdict: artifact missing entirely
# ---------------------------------------------------------------------------

def test_missing_artifact_verdicts_error(tmp_path):
    entry = {
        "id": "gone", "artifact_path": "does-not-exist.md",
        "max_age_days": 7, "rederive_command": "echo gone",
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_ERROR
    assert "artifact not found" in result.detail


# ---------------------------------------------------------------------------
# Empty manifest: non-zero exit, never a clean bill
# ---------------------------------------------------------------------------

def test_empty_entries_list_raises_manifest_error(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    with pytest.raises(sc.ManifestError, match="MANIFEST_NO_ENTRIES"):
        sc.load_manifest(manifest)


def test_cli_main_exits_nonzero_on_empty_manifest(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    exit_code = sc.main(["--manifest", str(manifest)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "MANIFEST_NO_ENTRIES" in captured.err


def test_cli_main_exits_nonzero_on_missing_manifest_file(tmp_path, capsys):
    manifest = tmp_path / "does-not-exist.json"
    exit_code = sc.main(["--manifest", str(manifest)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "MANIFEST_NOT_FOUND" in captured.err


def test_cli_main_exits_zero_only_when_every_entry_passes(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _fresh_artifact(tmp_path, name="fresh.md", days_old=0)
    _write_manifest(manifest, [
        {"id": "fresh", "artifact_path": "fresh.md", "max_age_days": 7, "rederive_command": "echo fresh"},
    ])
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path)])
    assert exit_code == 0


def test_cli_main_exits_two_when_an_entry_is_stale(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _fresh_artifact(tmp_path, name="stale.md", days_old=30)
    _write_manifest(manifest, [
        {"id": "stale", "artifact_path": "stale.md", "max_age_days": 7, "rederive_command": "echo stale"},
    ])
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path)])
    assert exit_code == 2


# ---------------------------------------------------------------------------
# Hook mode: never raises, silent on all-PASS, advisory JSON otherwise
# ---------------------------------------------------------------------------

def test_hook_mode_silent_on_all_pass(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _fresh_artifact(tmp_path, name="fresh.md", days_old=0)
    _write_manifest(manifest, [
        {"id": "fresh", "artifact_path": "fresh.md", "max_age_days": 7, "rederive_command": "echo fresh"},
    ])
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path), "--hook"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


def test_hook_mode_emits_advisory_on_stale_and_never_raises(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _fresh_artifact(tmp_path, name="stale.md", days_old=30)
    _write_manifest(manifest, [
        {"id": "stale", "artifact_path": "stale.md", "max_age_days": 7, "rederive_command": "echo stale"},
    ])
    exit_code = sc.main(["--manifest", str(manifest), "--vault-root", str(tmp_path), "--hook"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "stale" in payload["hookSpecificOutput"]["additionalContext"]


def test_hook_mode_swallows_manifest_error_silently(tmp_path, capsys):
    manifest = tmp_path / "does-not-exist.json"
    exit_code = sc.main(["--manifest", str(manifest), "--hook"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------------
# consistency_probe (O7 Finding 3): two-file agreement check, no age required
# ---------------------------------------------------------------------------

def _consistency_entry(tmp_path, md_line):
    file_a = tmp_path / "ledger.md"
    file_a.write_text(f"# Ledger\n\n{md_line}\n", encoding="utf-8")
    file_b = tmp_path / "ledger.json"
    file_b.write_text(json.dumps({"scope_total": 685}), encoding="utf-8")
    return {
        "id": "coverage-ledger-consistency",
        "artifact_path": "ledger.md",
        "rederive_command": "hand-reconcile",
        "consistency_probe": {
            "file_a": "ledger.md",
            "regex_a": r"scope_total is (\d+)",
            "file_b": "ledger.json",
            "key_path_b": ["scope_total"],
        },
    }


def test_consistency_probe_match_verdicts_pass(tmp_path):
    entry = _consistency_entry(tmp_path, "scope_total is 685, AUDITED 436")
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS
    assert result.age_days is None  # no max_age_days on this entry


def test_consistency_probe_mismatch_verdicts_divergent(tmp_path):
    entry = _consistency_entry(tmp_path, "scope_total is 614, AUDITED 405")
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_DIVERGENT
    assert "consistency mismatch" in result.detail
    assert "614" in result.detail and "685" in result.detail


def test_consistency_probe_extraction_failure_verdicts_error(tmp_path):
    entry = _consistency_entry(tmp_path, "no matching phrase here")
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_ERROR
    assert "regex_a found no match" in result.detail


def test_load_manifest_allows_missing_max_age_days_with_consistency_probe(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [{
        "id": "a", "artifact_path": "a.md", "rederive_command": "echo a",
        "consistency_probe": {
            "file_a": "a.md", "regex_a": r"x(\d+)",
            "file_b": "b.json", "key_path_b": ["x"],
        },
    }])
    entries = sc.load_manifest(manifest)
    assert "max_age_days" not in entries[0]


def test_load_manifest_still_requires_max_age_days_without_consistency_probe(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "a", "artifact_path": "a.md", "rederive_command": "echo a"},
    ])
    with pytest.raises(sc.ManifestError, match="MANIFEST_MALFORMED"):
        sc.load_manifest(manifest)


# ---------------------------------------------------------------------------
# citations_probe (O7 Finding 4): every cited path must resolve on disk
# ---------------------------------------------------------------------------

def _citations_entry(tmp_path, artifact_text, targets_exist=True):
    (tmp_path / "real.md").write_text("real target\n", encoding="utf-8")
    if targets_exist:
        (tmp_path / "sub").mkdir(exist_ok=True)
        (tmp_path / "sub" / "other.md").write_text("also real\n", encoding="utf-8")
    artifact = tmp_path / "doc.md"
    artifact.write_text(artifact_text, encoding="utf-8")
    return {
        "id": "cc-config-reference",
        "artifact_path": "doc.md",
        "max_age_days": 90,
        "rederive_command": "rerun the investigation",
        "citations_probe": {"path_regex": r"`([\w./-]+\.md)`"},
    }


def test_citations_probe_all_resolve_verdicts_pass(tmp_path):
    entry = _citations_entry(tmp_path, "See `real.md` and `sub/other.md`.\n")
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS
    assert "all citations resolve" in result.detail


def test_citations_probe_missing_path_verdicts_broken_citation(tmp_path):
    entry = _citations_entry(tmp_path, "See `real.md` and `does-not-exist.md`.\n")
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_BROKEN_CITATION
    assert "does-not-exist.md" in result.detail


def test_citations_probe_extraction_failure_verdicts_error(tmp_path):
    entry = _citations_entry(tmp_path, "No backticked paths in this prose at all.\n")
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_ERROR
    assert "found no matches" in result.detail


# ---------------------------------------------------------------------------
# docs-harness-components (Phase C): embedded_comment stamp shape
# ---------------------------------------------------------------------------

def test_generator_stamp_shape_verdicts_pass_docs_harness_components(tmp_path):
    stamp = tmp_path / "_generated.json"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp.write_text(
        json.dumps({"generated_at": now, "source_inventory_generated_at": "2026-09-04T00:00:00Z"}),
        encoding="utf-8",
    )
    entry = {
        "id": "docs-harness-components",
        "artifact_path": "_generated.json",
        "max_age_days": 30,
        "rederive_command": "n/a",
        "age_source": "embedded_comment",
        "age_regex": r"\"generated_at\"\s*:\s*\"([0-9T:\-]+)Z?\"",
        "advisory": True,
    }
    result = sc.check_entry(entry, tmp_path)
    assert result.verdict == sc.VERDICT_PASS
    assert result.age_days is not None and result.age_days < 0.01


def test_unparseable_embedded_timestamp_is_error_verdict_not_a_crash(tmp_path):
    """RED-proven against the pre-fix checker: an artifact stamped 'date: unstamped'
    (what process_path_map.py writes when run without --as-of) made _parse_timestamp
    raise an uncaught ValueError, crashing the whole run instead of yielding one
    ERROR row. Found by the O7 registration pass, 2026-08-30."""
    art = tmp_path / "unstamped.md"
    art.write_text("---\ndate: unstamped\n---\nbody\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [{
        "id": "unstamped-artifact",
        "artifact_path": art.name,
        "max_age_days": 7,
        "rederive_command": "n/a",
        "age_source": "embedded_comment",
        "age_regex": "date:\s*(\S+)",
    }])
    results = sc.run_check(manifest, tmp_path)
    assert len(results) == 1
    assert results[0].verdict == "ERROR"
    assert "unparseable timestamp" in results[0].detail
