"""TASK-033 (migration plan Phase 1, 2026-09-15-scheduled-jobs-off-laptop-plan.md):
plugin-cache snapshot fallback in asset_inventory.py's
load_installed_plugins_manifest() / load_plugin_enabled_map().

Loads the generator as a module (same pattern as
test_asset_inventory_taxonomy.py) and exercises the two loaders directly
against monkeypatched path constants, never the live plugin cache.
"""
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "asset_inventory.py"
_spec = importlib.util.spec_from_file_location(
    "asset_inventory_task033_under_test", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


SNAPSHOT = {
    "generated_at": "2026-09-15T12:00:00",
    "plugin_source": "snapshot",
    "plugins": {
        "code-reviewer@claude-plugins-official": {
            "name": "code-reviewer", "marketplace": "claude-plugins-official",
            "version": "1.2.0", "enabled": True,
        },
        "ralph-loop@claude-plugins-official": {
            "name": "ralph-loop", "marketplace": "claude-plugins-official",
            "version": "0.3.0", "enabled": False,
        },
    },
}


def test_manifest_falls_back_to_snapshot_when_cache_root_absent(tmp_path, monkeypatch):
    absent_cache = tmp_path / "no-such-cache"
    snapshot_path = tmp_path / "plugins-snapshot.json"
    snapshot_path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")

    monkeypatch.setattr(mod, "PLUGIN_CACHE_ROOT", absent_cache)
    monkeypatch.setattr(mod, "PLUGIN_SNAPSHOT_JSON", snapshot_path)

    canonical, notes, source = mod.load_installed_plugins_manifest()
    assert source == "snapshot"
    assert len(canonical) == 2
    assert "PLUGIN_CACHE_ABSENT" in notes[0]
    assert "TASK-033" in notes[0]
    # install_path is a guaranteed-nonexistent placeholder, never a real dir
    for info in canonical.values():
        assert not info["install_path"].exists()


def test_manifest_reports_absent_with_no_cache_and_no_snapshot(tmp_path, monkeypatch):
    absent_cache = tmp_path / "no-such-cache"
    absent_snapshot = tmp_path / "no-such-snapshot.json"

    monkeypatch.setattr(mod, "PLUGIN_CACHE_ROOT", absent_cache)
    monkeypatch.setattr(mod, "PLUGIN_SNAPSHOT_JSON", absent_snapshot)

    canonical, notes, source = mod.load_installed_plugins_manifest()
    assert source == "absent"
    assert canonical == {}


def test_manifest_prefers_live_cache_over_snapshot_when_both_present(tmp_path, monkeypatch):
    """Snapshot is only consulted when the live cache root itself is absent --
    a present (even empty-of-plugins) live cache must not be shadowed."""
    live_cache = tmp_path / "cache"
    live_cache.mkdir()
    installed_json = tmp_path / "installed_plugins.json"
    installed_json.write_text(json.dumps({"plugins": {}}), encoding="utf-8")
    snapshot_path = tmp_path / "plugins-snapshot.json"
    snapshot_path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")

    monkeypatch.setattr(mod, "PLUGIN_CACHE_ROOT", live_cache)
    monkeypatch.setattr(mod, "PLUGIN_INSTALLED_JSON", installed_json)
    monkeypatch.setattr(mod, "PLUGIN_SNAPSHOT_JSON", snapshot_path)

    canonical, notes, source = mod.load_installed_plugins_manifest()
    assert source == "live"
    assert canonical == {}  # the live (empty) manifest wins, not the snapshot's 2 entries


def test_enabled_map_falls_back_to_snapshot_when_user_settings_absent(tmp_path, monkeypatch):
    absent_settings = tmp_path / "no-such-settings.json"
    snapshot_path = tmp_path / "plugins-snapshot.json"
    snapshot_path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")

    monkeypatch.setattr(mod, "PLUGIN_USER_SETTINGS_JSON", absent_settings)
    monkeypatch.setattr(mod, "PLUGIN_SNAPSHOT_JSON", snapshot_path)

    enabled_map, notes = mod.load_plugin_enabled_map()
    assert enabled_map == {
        "code-reviewer@claude-plugins-official": True,
        "ralph-loop@claude-plugins-official": False,
    }
    assert any("TASK-033" in n for n in notes)


# ---------------------------------------------------------------------------
# BLK-004 on a run that cannot see the plugin cache (2026-09-20).
# generate_registry.py now keeps plugin entries on such a run and marks the
# registry plugin_entries = "carried-over". BLK-004 means "the registry names
# a plugin component and this machine's walk of the cache did not find it".
# With no cache to walk, that says nothing about the component. Without this
# rule the cloud docs job reported all 206 plugin components as unresolved and
# docs_stub_generate.py stopped the chain with
# "plugin agent rows 59 != plugin_cache_enumeration.row_counts['agent'] 0".
# ---------------------------------------------------------------------------

_REGISTRY = {
    "agents": {"code-reviewer": {"name": "code-reviewer", "source": "plugin:claude-plugins-official"},
               "local-one": {"name": "local-one", "source": "local"}},
    "skills": {"ars-full": {"name": "ars-full", "source": "plugin:academic-research-skills"}},
}
_NOTHING_FOUND = {"skill": set(), "agent": set()}


def test_blk004_still_reports_a_registry_entry_the_live_walk_missed():
    for flag in ({"plugin_entries": "live"}, {}):
        rows = mod.compute_blk004_rows(dict(_REGISTRY, **flag), _NOTHING_FOUND)
        assert {(r["kind"], r["name"]) for r in rows} == {("agent", "code-reviewer"), ("skill", "ars-full")}


def test_blk004_is_silent_when_the_registry_entries_were_carried_over():
    rows = mod.compute_blk004_rows(dict(_REGISTRY, plugin_entries="carried-over"), _NOTHING_FOUND)
    assert rows == []
