"""Tests for cmdb_refresh.py (generator for cmdb-vault-setup's enumerable block).

Written before the implementation (2026-08-31, owner-ruled generator-first
refresh). Fixtures supply a fake inventory, settings file, and page; the
generator must be deterministic (stamp from the inventory's generated_at,
never now()) and idempotent.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "cmdb_refresh.py"
PY = sys.executable

PAGE = """---
date: 2026-05-25
tags: [wiki, vault]
status: active
wiki_status: bootstrap
source:
  - path: "old/source.md"
    type: work-artifact
    sha256: "abc"
---

# Vault CMDB

Intro prose.

## Headline numbers

| Surface | Count |
|---|---|
| Skills (local) | 41 |

## Hook event coverage

Old prose about events.

## Skill dispatch concentration

Historical synthesis that must survive untouched.
"""

INVENTORY = {
    "generated_at": "2026-08-30T21:29:22Z",
    "rows": [
        {"kind": "skill", "provenance": "authored-in-harness"},
        {"kind": "skill", "provenance": "plugin:x"},
        {"kind": "agent", "provenance": "authored-in-harness"},
        {"kind": "hook", "provenance": "authored-in-harness"},
        {"kind": "hook", "provenance": "authored-in-harness"},
        {"kind": "mcp-server", "provenance": "authored-in-harness"},
        {"kind": "workflow", "provenance": "authored-in-harness"},
        {"kind": "settings-registration", "provenance": "authored-in-harness"},
        {"kind": "telemetry-sink", "provenance": "authored-in-harness"},
    ],
}

SETTINGS = {"hooks": {
    "Stop": [{"hooks": [{"command": "python a.py"}, {"command": "python b.py"}]}],
    "PreToolUse": [{"matcher": "Bash", "hooks": [{"command": "python c.py"}]}],
}}


def _setup(tmp_path):
    page = tmp_path / "cmdb-vault-setup.md"
    page.write_text(PAGE, encoding="utf-8")
    inv = tmp_path / "asset-inventory.json"
    inv.write_text(json.dumps(INVENTORY), encoding="utf-8")
    st = tmp_path / "settings.local.json"
    st.write_text(json.dumps(SETTINGS), encoding="utf-8")
    return page, inv, st


def _run(page, inv, st, extra=None):
    cmd = [PY, str(SCRIPT), "--page", str(page), "--inventory", str(inv),
           "--settings", str(st)] + (extra or [])
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run(cmd, capture_output=True, text=True, env=env,
                          timeout=60)


def test_refresh_writes_marked_block_with_inventory_stamp(tmp_path):
    page, inv, st = _setup(tmp_path)
    r = _run(page, inv, st)
    assert r.returncode == 0, r.stdout + r.stderr
    text = page.read_text(encoding="utf-8")
    assert "<!-- GENERATED:cmdb-counts" in text
    assert "2026-08-30T21:29:22Z" in text
    assert "| skill | 2 | 1 | 1 |" in text
    assert "Stop | 2" in text and "PreToolUse | 1" in text


def test_historical_prose_survives_untouched(tmp_path):
    page, inv, st = _setup(tmp_path)
    _run(page, inv, st)
    text = page.read_text(encoding="utf-8")
    assert "Historical synthesis that must survive untouched." in text
    assert "Intro prose." in text
    assert text.count("## Headline numbers") == 1


def test_generated_source_entry_added_without_sha(tmp_path):
    page, inv, st = _setup(tmp_path)
    _run(page, inv, st)
    text = page.read_text(encoding="utf-8")
    assert "type: generated" in text
    assert "old/source.md" in text  # existing citations preserved


def test_idempotent_second_run_is_byte_identical(tmp_path):
    page, inv, st = _setup(tmp_path)
    _run(page, inv, st)
    first = page.read_bytes()
    r = _run(page, inv, st)
    assert r.returncode == 0
    assert page.read_bytes() == first


def test_check_mode_green_after_refresh_red_on_drift(tmp_path):
    page, inv, st = _setup(tmp_path)
    _run(page, inv, st)
    assert _run(page, inv, st, ["--check"]).returncode == 0
    inv.write_text(json.dumps({**INVENTORY, "generated_at": "2026-09-09T00:00:00Z"}),
                   encoding="utf-8")
    assert _run(page, inv, st, ["--check"]).returncode == 2


def test_missing_inventory_fails_loud(tmp_path):
    page, inv, st = _setup(tmp_path)
    inv.unlink()
    r = _run(page, inv, st)
    assert r.returncode == 2
    assert "ERROR" in (r.stdout + r.stderr)


# --- architect-review fixes 2026-08-31 -----------------------------------------

def test_generated_citation_added_despite_other_generated_source(tmp_path):
    """A pre-existing OTHER generated citation must not suppress the insert
    (review finding: bare-substring gate false-skipped this case)."""
    page = tmp_path / "cmdb-vault-setup.md"
    other = '  - path: "other/generated.json"\n    type: generated\n  - path: "old/source.md"'
    page.write_text(PAGE.replace('  - path: "old/source.md"', other), encoding="utf-8")
    inv = tmp_path / "asset-inventory.json"
    inv.write_text(json.dumps(INVENTORY), encoding="utf-8")
    st = tmp_path / "settings.local.json"
    st.write_text(json.dumps(SETTINGS), encoding="utf-8")
    r = _run(page, inv, st)
    assert r.returncode == 0, r.stdout + r.stderr
    text = page.read_text(encoding="utf-8")
    assert text.count("type: generated") == 2
    assert "asset-inventory.json" in text


def test_unrecognized_provenance_fails_loud(tmp_path):
    """Schema drift in the inventory must abort, never silently count as plugin."""
    page, inv, st = _setup(tmp_path)
    bad = {**INVENTORY, "rows": INVENTORY["rows"] + [{"kind": "hook", "provenance": "mystery"}]}
    inv.write_text(json.dumps(bad), encoding="utf-8")
    before = page.read_text(encoding="utf-8")
    r = _run(page, inv, st)
    assert r.returncode == 2
    assert "unrecognized provenance" in (r.stdout + r.stderr)
    assert page.read_text(encoding="utf-8") == before


# --- TASK-004 (migration plan Phase 1, 2026-09-15): VAULT_DIR fallback and
# settings.local.json graceful degradation -------------------------------------

def test_vault_dir_env_overrides_hardcoded_default(monkeypatch, tmp_path):
    """cmdb_refresh.py's module-level VAULT constant must read VAULT_DIR the
    same way generate_registry.py:17 already does. VAULT is only consulted
    for its own DEFAULT_* constants, which every test above overrides via
    --page/--inventory/--settings, so this test asserts on the subprocess's
    own environment reflection instead of a default-path side effect."""
    cmd = [PY, "-c",
           "import cmdb_refresh as m; print(m.VAULT)"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", VAULT_DIR=str(tmp_path))
    r = subprocess.run(cmd, capture_output=True, text=True, env=env,
                       cwd=str(SCRIPT.parent), timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.strip() == str(tmp_path)


def test_missing_settings_degrades_to_zero_hook_rows(tmp_path):
    """settings.local.json absent (gitignored, expected on a fresh clone/CI
    runner): render succeeds with a zero-row hook table instead of failing."""
    page = tmp_path / "cmdb-vault-setup.md"
    page.write_text(PAGE, encoding="utf-8")
    inv = tmp_path / "asset-inventory.json"
    inv.write_text(json.dumps(INVENTORY), encoding="utf-8")
    missing_st = tmp_path / "does-not-exist-settings.local.json"
    r = _run(page, inv, missing_st)
    assert r.returncode == 0, r.stdout + r.stderr
    text = page.read_text(encoding="utf-8")
    assert "settings.local.json absent on this runner" in text
    assert "| Event | Wired hooks |" in text


def test_check_passes_when_settings_absent_and_block_already_reflects_it(tmp_path):
    """--check exits 0 on a runner with no settings.local.json present, once
    the page already reflects the degraded (zero-row) render -- TASK-004's
    own CHECK, verbatim."""
    page = tmp_path / "cmdb-vault-setup.md"
    page.write_text(PAGE, encoding="utf-8")
    inv = tmp_path / "asset-inventory.json"
    inv.write_text(json.dumps(INVENTORY), encoding="utf-8")
    missing_st = tmp_path / "does-not-exist-settings.local.json"
    first = _run(page, inv, missing_st)
    assert first.returncode == 0, first.stdout + first.stderr
    r = _run(page, inv, missing_st, ["--check"])
    assert r.returncode == 0, r.stdout + r.stderr
