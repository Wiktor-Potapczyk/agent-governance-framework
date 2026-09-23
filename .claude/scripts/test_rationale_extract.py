"""Selftest for rationale_extract.py (O6 why-layer generator).

Run: "C:\\Program Files\\Python314\\python.exe" -m pytest test_rationale_extract.py
     (from inside .claude/scripts; PYTHONIOENCODING=utf-8 set in the environment)
"""
from __future__ import annotations

import copy
import json
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rationale_extract as rex  # noqa: E402


def _load_inventory_rows() -> list[dict]:
    data = json.loads(rex.DEFAULT_ASSET_INVENTORY.read_text(encoding="utf-8"))
    return data["rows"]


def _independent_population_count(rows: list[dict]) -> int:
    """Re-derives the vault-owned population directly from asset-inventory.json,
    duplicating the filter logic rather than calling into rationale_extract, so
    this is a real re-derivation and not a tautology against the module under test."""
    count = 0
    for row in rows:
        prov = row.get("provenance", "") or ""
        if prov == "authored-in-harness" or prov.startswith("junction:"):
            count += 1
    return count


def test_row_count_equals_vault_owned_population():
    rows = _load_inventory_rows()
    expected = _independent_population_count(rows)
    index = rex.build_index(rex.DEFAULT_ASSET_INVENTORY, rex.DEFAULT_CLAUDE_MD)
    assert index["row_count"] == expected
    assert len(index["rows"]) == expected


def test_zero_extracted_rows_have_empty_rationale():
    index = rex.build_index(rex.DEFAULT_ASSET_INVENTORY, rex.DEFAULT_CLAUDE_MD)
    offenders = [
        r for r in index["rows"]
        if r["extraction_status"] == rex.STATUS_EXTRACTED and not r["rationale"].strip()
    ]
    assert offenders == []


def test_no_stated_why_rows_have_empty_rationale_and_null_locus():
    index = rex.build_index(rex.DEFAULT_ASSET_INVENTORY, rex.DEFAULT_CLAUDE_MD)
    for r in index["rows"]:
        if r["extraction_status"] == rex.STATUS_NONE:
            assert r["rationale"] == ""
            assert r["extraction_locus"] is None


def test_determinism_two_runs_identical_excluding_generated_at():
    index1 = rex.build_index(rex.DEFAULT_ASSET_INVENTORY, rex.DEFAULT_CLAUDE_MD)
    index2 = rex.build_index(rex.DEFAULT_ASSET_INVENTORY, rex.DEFAULT_CLAUDE_MD)

    def strip_header(idx: dict) -> dict:
        idx = copy.deepcopy(idx)
        idx.pop("generated_at", None)
        return idx

    assert json.dumps(strip_header(index1), sort_keys=True) == json.dumps(strip_header(index2), sort_keys=True)


def test_write_outputs_roundtrip(tmp_path):
    index = rex.build_index(rex.DEFAULT_ASSET_INVENTORY, rex.DEFAULT_CLAUDE_MD)
    out_json = tmp_path / "rationale-index.json"
    out_md = tmp_path / "rationale-index.md"
    rex.write_outputs(index, out_json, out_md)
    assert out_json.exists()
    assert out_md.exists()
    reloaded = json.loads(out_json.read_text(encoding="utf-8"))
    assert reloaded["row_count"] == index["row_count"]
    md_text = out_md.read_text(encoding="utf-8")
    assert "NO_STATED_WHY components" in md_text


def test_no_stated_why_fixture_no_docstring(tmp_path):
    """Fixture-based NO_STATED_WHY case: a hook script with no module docstring
    at all must extract to NO_STATED_WHY, not fabricate a rationale."""
    fixture = tmp_path / "fixture_no_docstring_hook.py"
    fixture.write_text(textwrap.dedent("""
        import sys

        def main():
            return 0

        if __name__ == "__main__":
            raise SystemExit(main())
    """), encoding="utf-8")

    row = {
        "name": "fixture_no_docstring_hook",
        "kind": "hook",
        "path": str(fixture),
        "provenance": "authored-in-harness",
        "reachability": [],
    }
    result = rex.extract_row(row, rex.DEFAULT_CLAUDE_MD)
    assert result["extraction_status"] == rex.STATUS_NONE
    assert result["rationale"] == ""
    assert result["extraction_locus"] is None


def test_why_marker_paragraph_preferred_over_first_paragraph(tmp_path):
    """A docstring whose second paragraph carries a why-marker must win over the
    first paragraph, per the extraction preference rule."""
    fixture = tmp_path / "fixture_why_marker_hook.py"
    fixture.write_text(textwrap.dedent('''
        """First paragraph, purely descriptive, no marker here at all.

        Origin: this is the paragraph that should be selected because it
        carries a recognized why-marker term.
        """

        def main():
            return 0
    '''), encoding="utf-8")

    row = {
        "name": "fixture_why_marker_hook",
        "kind": "hook",
        "path": str(fixture),
        "provenance": "authored-in-harness",
        "reachability": [],
    }
    result = rex.extract_row(row, rex.DEFAULT_CLAUDE_MD)
    assert result["extraction_status"] == rex.STATUS_EXTRACTED
    assert "Origin:" in result["rationale"]
    assert "First paragraph" not in result["rationale"]


if __name__ == "__main__":
    raise SystemExit(__import__("pytest").main([__file__, "-v"]))
