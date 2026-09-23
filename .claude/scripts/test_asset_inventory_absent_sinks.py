"""Fix pass 2026-09-16 (Phase 2 migration build record headline finding):
asset_inventory.py's generate() raised an uncaught FileNotFoundError when
either usage sink (.claude/hooks/hook-activity.jsonl,
.claude/hooks/governance-log.jsonl) is absent -- the normal state on a
fresh checkout or a GitHub Actions runner, since both are gitignored
(.gitignore:66). This suite pins the fix: an absent sink is treated
exactly like an empty one (zero lines, field-contract check not
applicable), with a SINK_ABSENT note recorded in the output; a genuinely
present-but-empty sink behaves identically apart from the note; a present,
non-empty sink whose records never carry the checked field still aborts
(the pre-existing regression guard, unchanged).

Loads the generator as a module (same pattern as
test_asset_inventory_taxonomy.py). The generate()-level tests run against
this vault's REAL enumeration roots (HOOKS_DIR, SKILLS_DIR, AGENTS_DIR,
WORKFLOWS_DIR, REGISTRY_JSON) with skip_freshness_check=True -- the same
pattern asset_inventory_selftest.py's run_negative_fixture_test() uses --
overriding only the two sink paths and aggregates_dir to tmp_path
locations, so no live aggregate or sink file is ever touched.

Build record: Projects/Vault-Maintenance/work/2026-09-15-migration-build-record-phase2.md
(appendix "Fix pass 2026-09-16: absent usage sinks").
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent / "asset_inventory.py"
_spec = importlib.util.spec_from_file_location("asset_inventory_absent_sinks_under_test", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


# ---------------------------------------------------------------------------
# Unit level: the low-level helper and the two per-sink processors, direct
# calls, no generate() overhead.
# ---------------------------------------------------------------------------

def test_stream_jsonl_absent_path_yields_nothing(tmp_path):
    absent = tmp_path / "does-not-exist.jsonl"
    assert list(mod.stream_jsonl(absent)) == []


def test_process_hook_activity_absent_path_treated_as_empty(tmp_path):
    absent = tmp_path / "hook-activity.jsonl"
    out = mod.process_hook_activity(absent, {"some-hook"})
    assert out["total_lines"] == 0
    assert out["usage"] == {}
    assert out["skipped"] == 0
    assert out["contract_ok"] is True


def test_process_governance_log_absent_path_treated_as_empty(tmp_path):
    absent = tmp_path / "governance-log.jsonl"
    out = mod.process_governance_log(absent, {"some-agent"}, {"some-skill"})
    assert out["total_lines"] == 0
    assert out["total_agent_dispatched"] == 0
    assert out["agent_usage"] == {}
    assert out["skill_usage"] == {}
    assert out["contract_ok"] is True


def test_process_hook_activity_present_empty_file_identical_to_absent(tmp_path):
    present_empty = tmp_path / "hook-activity.jsonl"
    present_empty.write_bytes(b"")
    absent = tmp_path / "does-not-exist.jsonl"
    out_present = mod.process_hook_activity(present_empty, {"some-hook"})
    out_absent = mod.process_hook_activity(absent, {"some-hook"})
    assert out_present == out_absent


def test_process_governance_log_present_empty_file_identical_to_absent(tmp_path):
    present_empty = tmp_path / "governance-log.jsonl"
    present_empty.write_bytes(b"")
    absent = tmp_path / "does-not-exist.jsonl"
    out_present = mod.process_governance_log(present_empty, {"some-agent"}, {"some-skill"})
    out_absent = mod.process_governance_log(absent, {"some-agent"}, {"some-skill"})
    assert out_present == out_absent


# ---------------------------------------------------------------------------
# Regression guard: a PRESENT, non-empty sink whose records never carry a
# non-null value for the checked field must still fail the field-contract
# check. This is the exact defect class asset_inventory_selftest.py's
# run_negative_fixture_test() pins at the subprocess level; reproduced here
# at the unit level so it runs in the fast suite too. total_lines == 0 is
# the ONLY new escape hatch -- a non-empty file with an all-null field is
# untouched by this fix.
# ---------------------------------------------------------------------------

def test_hook_activity_present_nonempty_all_null_field_still_fails_contract(tmp_path):
    log = tmp_path / "hook-activity.jsonl"
    lines = [
        json.dumps({"ts": "2026-01-01 00:00:00", "hook": None}),
        json.dumps({"ts": "2026-01-01 00:00:01", "hook": None}),
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = mod.process_hook_activity(log, {"some-hook"})
    assert out["total_lines"] == 2
    assert out["contract_ok"] is False


def test_governance_log_present_nonempty_all_null_field_still_fails_contract(tmp_path):
    log = tmp_path / "governance-log.jsonl"
    lines = [
        json.dumps({"ts": "2026-01-01 00:00:00", "event": "agent_dispatched",
                    "agent_type": None, "skill_context": []}),
        json.dumps({"ts": "2026-01-01 00:00:01", "event": "agent_dispatched",
                    "agent_type": None, "skill_context": []}),
    ]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = mod.process_governance_log(log, {"some-agent"}, {"some-skill"})
    assert out["total_agent_dispatched"] == 2
    assert out["contract_ok"] is False


# ---------------------------------------------------------------------------
# generate()-level: both sinks absent must not raise, must emit the note,
# must still write output. A present-but-empty sink must behave
# identically apart from the note.
# ---------------------------------------------------------------------------

@pytest.fixture
def _aggregates_out(tmp_path):
    d = tmp_path / "aggregates_out"
    d.mkdir()
    return d


def test_generate_succeeds_when_both_sinks_absent(tmp_path, _aggregates_out):
    hook_path = tmp_path / "hook-activity.jsonl"
    gov_path = tmp_path / "governance-log.jsonl"
    assert not hook_path.exists() and not gov_path.exists()

    data = mod.generate(
        governance_log_path=gov_path,
        hook_activity_path=hook_path,
        aggregates_dir=_aggregates_out,
        write_output=True,
        run_id="test-absent-sinks",
        skip_freshness_check=True,
    )

    assert data["field_contract_check"] == "PASSED"
    ha = data["skipped_records"]["hook_activity_jsonl"]
    gov = data["skipped_records"]["governance_log_jsonl"]
    assert ha["total_lines"] == 0
    assert gov["total_lines"] == 0
    assert len(ha["notes"]) == 1 and "SINK_ABSENT" in ha["notes"][0] and str(hook_path) in ha["notes"][0]
    assert len(gov["notes"]) == 1 and "SINK_ABSENT" in gov["notes"][0] and str(gov_path) in gov["notes"][0]
    assert (_aggregates_out / "asset-inventory.json").exists()
    assert (_aggregates_out / "asset-inventory.md").exists()


def test_generate_present_but_empty_sinks_identical_apart_from_note(tmp_path, _aggregates_out):
    hook_path = tmp_path / "hook-activity.jsonl"
    gov_path = tmp_path / "governance-log.jsonl"
    hook_path.write_bytes(b"")
    gov_path.write_bytes(b"")

    data_present = mod.generate(
        governance_log_path=gov_path,
        hook_activity_path=hook_path,
        aggregates_dir=_aggregates_out,
        write_output=False,
        run_id="test-present-empty-sinks",
        skip_freshness_check=True,
    )

    absent_hook_path = tmp_path / "does-not-exist-hook.jsonl"
    absent_gov_path = tmp_path / "does-not-exist-gov.jsonl"
    data_absent = mod.generate(
        governance_log_path=absent_gov_path,
        hook_activity_path=absent_hook_path,
        aggregates_dir=_aggregates_out,
        write_output=False,
        run_id="test-present-empty-sinks",
        skip_freshness_check=True,
    )

    ha_present = data_present["skipped_records"]["hook_activity_jsonl"]
    gov_present = data_present["skipped_records"]["governance_log_jsonl"]
    assert ha_present["notes"] == []
    assert gov_present["notes"] == []

    # Strip the notes key (the only field the task allows to differ) and
    # the two path-bearing note-source fields don't otherwise leak into
    # this block, then diff the rest byte-for-byte via JSON serialization.
    def _without_notes(block):
        d = dict(block)
        d.pop("notes", None)
        return d

    ha_absent = data_absent["skipped_records"]["hook_activity_jsonl"]
    gov_absent = data_absent["skipped_records"]["governance_log_jsonl"]

    assert json.dumps(_without_notes(ha_present), sort_keys=True) == \
        json.dumps(_without_notes(ha_absent), sort_keys=True)
    assert json.dumps(_without_notes(gov_present), sort_keys=True) == \
        json.dumps(_without_notes(gov_absent), sort_keys=True)
