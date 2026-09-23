"""
test_staleness_manifest_generate.py - pytest suite for the O10 manifest
generator (staleness_manifest_generate.py), written RED-first per Step 4 of
Projects/Agent-Governance-Research/work/2026-09-02-o10-staleness-generation-plan.md.

Covers, per the plan's Step-4 list:
  (1) the generated block contains exactly the classification list's generated
      ids in fixed order, count derived from the list constants (D7)
  (2) idempotence: two consecutive generate runs are byte-identical (D11)
  (3) determinism: the block stamp equals the fixture inventory's generated_at,
      never now() (D2)
  (4) dispatches enumeration maps 1:1 onto the classified skills; an eighth
      DISPATCHES.json, or a missing one, fails loud with no write (D7)
  (5) bespoke preservation: generate never touches the hand entries array (D6)
  (6) --check: clean on a fresh fixture, exit 2 after a hand edit to one
      generated entry, with the diffing entry id named in output (D1)
  (7) the internal per-kind cross-check refuses emission when inventory rows
      disagree with the inventory's own per-kind row_count headers (D6/D7)
  (8) duplicate-guard: a hand section still carrying cmdb-vault-setup makes
      generate fail loud naming the collision (D9)

All fixtures are tmp_path-synthetic; none touch live files.

Run from inside .claude/scripts:
    "C:\\Program Files\\Python314\\python.exe" -m pytest test_staleness_manifest_generate.py -v
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import staleness_manifest_generate as smg  # noqa: E402

REAL_SKILLS = ("pm", "process-analysis", "process-build", "process-pentest",
               "process-planning", "process-qa", "process-research")


def _expected_generated_ids():
    return ([f"dispatches-{s}" for s in sorted(smg.EXPECTED_DISPATCH_SKILLS)]
            + list(smg.GENERATED_STATIC_IDS))


def _fixture_vault(tmp_path, skills=REAL_SKILLS, hand_ids=None,
                   break_kind_header=False):
    """Build a minimal synthetic vault the generator can run against."""
    skills_dir = tmp_path / ".claude" / "skills"
    for skill in skills:
        d = skills_dir / skill
        d.mkdir(parents=True)
        (d / "DISPATCHES.json").write_text(
            json.dumps({"last_reviewed": "2026-09-01"}), encoding="utf-8")

    agg = tmp_path / ".claude" / "hooks" / "aggregates"
    agg.mkdir(parents=True)
    inventory = {
        "generated_at": "2026-09-01T15:01:31Z",
        "mcp_server_kind": {"row_count": 1},
        "command_kind": {"row_count": 0},
        "telemetry_sink_kind": {"row_count": 1},
        "settings_registration_kind": {"row_count": 1},
        "rows": [
            {"name": "a", "kind": "skill", "provenance": "authored-in-harness"},
            {"name": "b", "kind": "hook", "provenance": "authored-in-harness"},
            {"name": "c", "kind": "mcp-server", "provenance": "plugin:x/y"},
            {"name": "d", "kind": "telemetry-sink", "provenance": "authored-in-harness"},
            {"name": "e", "kind": "settings-registration", "provenance": "authored-in-harness"},
            {"name": "f", "kind": "skill", "provenance": "junction:C:/somewhere"},
        ],
    }
    if break_kind_header:
        inventory["telemetry_sink_kind"]["row_count"] = 9
    (agg / "asset-inventory.json").write_text(
        json.dumps(inventory, indent=2), encoding="utf-8")

    scripts = tmp_path / ".claude" / "scripts"
    scripts.mkdir(parents=True)
    if hand_ids is None:
        hand_ids = ["cc-config-reference", "install-prereqs-manifest",
                    "coverage-ledger-consistency", "harness-process-path-map"]
    hand_entries = [
        {"id": hid, "artifact_path": f"{hid}.md", "max_age_days": 30,
         "rederive_command": f"echo {hid}"}
        for hid in hand_ids
    ]
    manifest = scripts / "staleness-manifest.json"
    manifest.write_text(json.dumps({
        "generated_at": "2026-08-30T00:00:00",
        "notes": "fixture manifest",
        "entries": hand_entries,
    }, indent=2), encoding="utf-8")
    return manifest


def _run(args):
    return smg.main([str(a) for a in args])


def _generate_args(tmp_path, manifest):
    return ["--vault-root", tmp_path, "--manifest", manifest]


def _load(manifest):
    return json.loads(Path(manifest).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# (1) generated block: exactly the classified ids, fixed order, derived count
# ---------------------------------------------------------------------------

def test_generate_emits_exactly_the_classified_generated_ids_in_order(tmp_path):
    manifest = _fixture_vault(tmp_path)
    assert _run(_generate_args(tmp_path, manifest)) == 0
    data = _load(manifest)
    block = data["generated_block"]
    ids = [e["id"] for e in block["entries"]]
    expected = _expected_generated_ids()
    assert ids == expected
    assert len(ids) == len(smg.EXPECTED_DISPATCH_SKILLS) + len(smg.GENERATED_STATIC_IDS)
    assert all(e.get("rederive_command") for e in block["entries"])
    assert "do_not_edit" in block and block["do_not_edit"]


# ---------------------------------------------------------------------------
# (2) idempotence: two consecutive generate runs are byte-identical
# ---------------------------------------------------------------------------

def test_generate_twice_is_byte_identical(tmp_path):
    manifest = _fixture_vault(tmp_path)
    assert _run(_generate_args(tmp_path, manifest)) == 0
    first = Path(manifest).read_bytes()
    assert _run(_generate_args(tmp_path, manifest)) == 0
    second = Path(manifest).read_bytes()
    assert first == second


# ---------------------------------------------------------------------------
# (3) determinism: block stamp is the inventory's generated_at, never now()
# ---------------------------------------------------------------------------

def test_block_stamp_equals_fixture_inventory_generated_at(tmp_path):
    manifest = _fixture_vault(tmp_path)
    assert _run(_generate_args(tmp_path, manifest)) == 0
    block = _load(manifest)["generated_block"]
    assert block["source_inventory_generated_at"] == "2026-09-01T15:01:31Z"


# ---------------------------------------------------------------------------
# (4) dispatches enumeration: 1:1 mapping; extra or missing file fails loud
# ---------------------------------------------------------------------------

def test_eighth_dispatches_file_fails_loud_with_no_write(tmp_path, capsys):
    manifest = _fixture_vault(tmp_path, skills=REAL_SKILLS + ("process-extra",))
    before = Path(manifest).read_bytes()
    rc = _run(_generate_args(tmp_path, manifest))
    out = capsys.readouterr().out
    assert rc != 0
    assert "process-extra" in out
    assert Path(manifest).read_bytes() == before


def test_missing_dispatches_file_fails_loud_with_no_write(tmp_path, capsys):
    manifest = _fixture_vault(tmp_path, skills=REAL_SKILLS[:-1])
    before = Path(manifest).read_bytes()
    rc = _run(_generate_args(tmp_path, manifest))
    out = capsys.readouterr().out
    assert rc != 0
    assert REAL_SKILLS[-1] in out
    assert Path(manifest).read_bytes() == before


# ---------------------------------------------------------------------------
# (5) bespoke preservation: hand entries never touched, byte-per-entry
# ---------------------------------------------------------------------------

def test_generate_never_touches_the_hand_entries_array(tmp_path):
    manifest = _fixture_vault(tmp_path)
    before = _load(manifest)["entries"]
    assert _run(_generate_args(tmp_path, manifest)) == 0
    after = _load(manifest)["entries"]
    assert len(before) == len(after)
    for b, a in zip(before, after):
        assert (json.dumps(b, ensure_ascii=False, indent=2)
                == json.dumps(a, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------------------
# (6) --check: clean when fresh, exit 2 naming the hand-edited entry
# ---------------------------------------------------------------------------

def test_check_clean_on_freshly_generated_fixture(tmp_path):
    manifest = _fixture_vault(tmp_path)
    assert _run(_generate_args(tmp_path, manifest)) == 0
    assert _run(_generate_args(tmp_path, manifest) + ["--check"]) == 0


def test_check_flags_hand_edited_generated_entry_and_names_it(tmp_path, capsys):
    manifest = _fixture_vault(tmp_path)
    assert _run(_generate_args(tmp_path, manifest)) == 0
    data = _load(manifest)
    target = data["generated_block"]["entries"][0]
    edited_id = target["id"]
    target["rederive_command"] = "hand-edited command"
    Path(manifest).write_text(json.dumps(data, indent=2), encoding="utf-8")
    rc = _run(_generate_args(tmp_path, manifest) + ["--check"])
    out = capsys.readouterr().out
    assert rc == 2
    assert edited_id in out


# ---------------------------------------------------------------------------
# (7) per-kind cross-check: header/rows disagreement refuses emission
# ---------------------------------------------------------------------------

def test_per_kind_cross_check_refuses_emission_on_header_mismatch(tmp_path, capsys):
    manifest = _fixture_vault(tmp_path, break_kind_header=True)
    before = Path(manifest).read_bytes()
    rc = _run(_generate_args(tmp_path, manifest))
    out = capsys.readouterr().out
    assert rc != 0
    assert "telemetry-sink" in out
    assert Path(manifest).read_bytes() == before


# ---------------------------------------------------------------------------
# (8) duplicate-guard: hand cmdb-vault-setup entry fails loud (supersession)
# ---------------------------------------------------------------------------

def test_hand_cmdb_entry_fails_loud_naming_the_collision(tmp_path, capsys):
    manifest = _fixture_vault(
        tmp_path,
        hand_ids=["cc-config-reference", "cmdb-vault-setup"])
    before = Path(manifest).read_bytes()
    rc = _run(_generate_args(tmp_path, manifest))
    out = capsys.readouterr().out
    assert rc != 0
    assert "cmdb-vault-setup" in out
    assert Path(manifest).read_bytes() == before


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
