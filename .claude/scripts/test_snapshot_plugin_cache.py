"""Tests for snapshot_plugin_cache.py (TASK-033, migration plan Phase 1,
2026-09-15-scheduled-jobs-off-laptop-plan.md).

Declarative-first: written before the implementation. Fixtures live in tmp;
the real ~/.claude/plugins is never touched.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "snapshot_plugin_cache.py"
PY = sys.executable

INSTALLED = {
    "version": 2,
    "plugins": {
        "code-reviewer@claude-plugins-official": [
            {"version": "1.2.0", "installedAt": "2026-01-01", "installPath": "/x"},
        ],
        "ralph-loop@claude-plugins-official": [
            {"version": "0.3.0", "installedAt": "2026-02-01", "installPath": "/y"},
        ],
    },
}
SETTINGS = {"enabledPlugins": {"ralph-loop@claude-plugins-official": False}}


def _run(installed, settings, out):
    cmd = [PY, str(SCRIPT), "--installed", str(installed),
           "--settings", str(settings), "--out", str(out)]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def test_writes_names_versions_marketplace_only(tmp_path):
    installed = tmp_path / "installed_plugins.json"
    installed.write_text(json.dumps(INSTALLED), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    out = tmp_path / "plugins-snapshot.json"

    r = _run(installed, settings, out)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["plugin_source"] == "snapshot"
    assert data["plugins"]["code-reviewer@claude-plugins-official"] == {
        "name": "code-reviewer", "marketplace": "claude-plugins-official",
        "version": "1.2.0", "enabled": True,
    }
    assert data["plugins"]["ralph-loop@claude-plugins-official"]["enabled"] is False
    # never an install path or any other filesystem/credential detail
    dumped = json.dumps(data)
    assert "/x" not in dumped and "/y" not in dumped
    assert "installPath" not in dumped


def test_missing_installed_manifest_degrades_to_empty_snapshot(tmp_path):
    installed = tmp_path / "does-not-exist.json"
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    out = tmp_path / "plugins-snapshot.json"

    r = _run(installed, settings, out)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "INSTALLED_MANIFEST_ABSENT" in r.stdout
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["plugins"] == {}
    assert data["plugin_source"] == "snapshot"


def test_missing_user_settings_defaults_all_enabled(tmp_path):
    installed = tmp_path / "installed_plugins.json"
    installed.write_text(json.dumps(INSTALLED), encoding="utf-8")
    settings = tmp_path / "does-not-exist-settings.json"
    out = tmp_path / "plugins-snapshot.json"

    r = _run(installed, settings, out)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["plugins"]["ralph-loop@claude-plugins-official"]["enabled"] is True


def test_unchanged_second_run_does_not_rewrite_timestamp(tmp_path):
    installed = tmp_path / "installed_plugins.json"
    installed.write_text(json.dumps(INSTALLED), encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(SETTINGS), encoding="utf-8")
    out = tmp_path / "plugins-snapshot.json"

    first = _run(installed, settings, out)
    assert first.returncode == 0
    first_stamp = json.loads(out.read_text(encoding="utf-8"))["generated_at"]

    second = _run(installed, settings, out)
    assert second.returncode == 0
    assert "unchanged" in second.stdout
    second_stamp = json.loads(out.read_text(encoding="utf-8"))["generated_at"]
    assert second_stamp == first_stamp
