"""
test_install_prereqs.py - pytest suite for install_prereqs.py.

Run from inside .claude/scripts:
    "C:\\Program Files\\Python314\\python.exe" -m pytest test_install_prereqs.py -v

Covers, per O2 increment 1's CHECK contract
(2026-08-30-harness-spec-objectives.md):
  - manifest parse (well-formed manifest loads its entries)
  - one entry PASSes on this machine (executable, file_exists, json_key_exists,
    env_var_set probe types each exercised)
  - a deliberately wrong entry (bad python version bound) FAILs
  - empty-manifest exits non-zero via CLI, and raises ManifestError at the
    library level, so a manifest resolving to nothing is never a clean bill
"""
import json
import os
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import install_prereqs as ip  # noqa: E402


def _write_manifest(path, entries, generated_at="2026-08-30T00:00:00Z"):
    path.write_text(
        json.dumps({
            "generated_at": generated_at,
            "generator_version": "1.0",
            "notes": "test fixture",
            "entries": entries,
        }),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Manifest parse
# ---------------------------------------------------------------------------

def test_load_manifest_parses_well_formed_entries(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "a", "kind": "file", "probe": {"type": "file_exists", "path": "a.txt"}, "source": "test"},
    ])
    entries = ip.load_manifest(manifest)
    assert len(entries) == 1
    assert entries[0]["id"] == "a"


def test_load_manifest_raises_on_missing_required_field(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "a", "kind": "file", "probe": {"type": "file_exists", "path": "a.txt"}},  # source missing
    ])
    with pytest.raises(ip.ManifestError, match="MANIFEST_MALFORMED"):
        ip.load_manifest(manifest)


def test_load_manifest_raises_on_unknown_kind(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "a", "kind": "spaceship", "probe": {"type": "file_exists", "path": "a.txt"}, "source": "test"},
    ])
    with pytest.raises(ip.ManifestError, match="unknown kind"):
        ip.load_manifest(manifest)


def test_load_manifest_raises_on_invalid_json(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ip.ManifestError, match="MANIFEST_INVALID_JSON"):
        ip.load_manifest(manifest)


def test_load_manifest_raises_on_missing_file(tmp_path):
    manifest = tmp_path / "does-not-exist.json"
    with pytest.raises(ip.ManifestError, match="MANIFEST_NOT_FOUND"):
        ip.load_manifest(manifest)


# ---------------------------------------------------------------------------
# Pass-entry: one of each probe type, verified against known-good fixtures
# ---------------------------------------------------------------------------

def test_file_exists_probe_passes_on_present_file(tmp_path):
    target = tmp_path / "present.txt"
    target.write_text("x", encoding="utf-8")
    entry = {"id": "f", "kind": "file", "probe": {"type": "file_exists", "path": str(target)}, "source": "test"}
    passed, detail = ip.check_entry(entry, tmp_path)
    assert passed is True
    assert "exists" in detail


def test_json_key_exists_probe_passes_when_key_present(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"mcpServers": {"qmd": {"command": "node"}}}), encoding="utf-8")
    entry = {
        "id": "m", "kind": "mcp-server",
        "probe": {"type": "json_key_exists", "json_path": "config.json", "key_path": ["mcpServers", "qmd"]},
        "source": "test",
    }
    passed, detail = ip.check_entry(entry, tmp_path)
    assert passed is True
    assert "present" in detail


def test_env_var_set_probe_passes_when_set(monkeypatch):
    monkeypatch.setenv("INSTALL_PREREQS_TEST_VAR", "some-value")
    entry = {"id": "e", "kind": "env", "probe": {"type": "env_var_set", "var_name": "INSTALL_PREREQS_TEST_VAR"}, "source": "test"}
    passed, detail = ip.check_entry(entry, Path("."))
    assert passed is True
    assert "is set" in detail
    assert "some-value" not in detail  # NAME only, never the value


def test_env_var_set_probe_fails_when_unset(monkeypatch):
    monkeypatch.delenv("INSTALL_PREREQS_TEST_VAR_ABSENT", raising=False)
    entry = {"id": "e", "kind": "env", "probe": {"type": "env_var_set", "var_name": "INSTALL_PREREQS_TEST_VAR_ABSENT"}, "source": "test"}
    passed, detail = ip.check_entry(entry, Path("."))
    assert passed is False
    assert "is not set" in detail


def test_executable_probe_passes_on_real_python_on_this_machine():
    entry = {
        "id": "py", "kind": "interpreter",
        "probe": {
            "type": "executable", "path": "C:\\Program Files\\Python314\\python.exe",
            "command": "python", "version_flag": ["--version"],
            "version_regex": r"Python\s+(\d+\.\d+\.\d+)", "min_version": "3.0.0",
        },
        "source": "test",
    }
    passed, detail = ip.check_entry(entry, Path("."))
    assert passed is True
    assert "version" in detail


# ---------------------------------------------------------------------------
# Fail-entry: a deliberately wrong python version bound
# ---------------------------------------------------------------------------

def test_executable_probe_fails_on_impossible_version_bound():
    entry = {
        "id": "py-wrong", "kind": "interpreter",
        "probe": {
            "type": "executable", "path": "C:\\Program Files\\Python314\\python.exe",
            "command": "python", "version_flag": ["--version"],
            "version_regex": r"Python\s+(\d+\.\d+\.\d+)", "min_version": "99.0.0",
        },
        "source": "test",
    }
    passed, detail = ip.check_entry(entry, Path("."))
    assert passed is False
    assert "< required 99.0.0" in detail


def test_executable_probe_fails_when_command_absent():
    entry = {
        "id": "ghost", "kind": "binary",
        "probe": {"type": "executable", "path": None, "command": "this-binary-does-not-exist-anywhere"},
        "source": "test",
    }
    passed, detail = ip.check_entry(entry, Path("."))
    assert passed is False
    assert "not found" in detail


def test_run_check_reports_mixed_pass_and_fail(tmp_path):
    good = tmp_path / "present.txt"
    good.write_text("x", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "good", "kind": "file", "probe": {"type": "file_exists", "path": "present.txt"}, "source": "test"},
        {"id": "bad", "kind": "file", "probe": {"type": "file_exists", "path": "absent.txt"}, "source": "test"},
    ])
    results = ip.run_check(manifest, tmp_path)
    by_id = {r["id"]: r["passed"] for r in results}
    assert by_id["good"] is True
    assert by_id["bad"] is False


# ---------------------------------------------------------------------------
# Empty manifest: non-zero exit, never a clean bill
# ---------------------------------------------------------------------------

def test_empty_entries_list_raises_manifest_error(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    with pytest.raises(ip.ManifestError, match="MANIFEST_NO_ENTRIES"):
        ip.load_manifest(manifest)


def test_cli_main_exits_nonzero_on_empty_manifest(tmp_path, capsys):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    exit_code = ip.main(["--check", "--manifest", str(manifest)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "MANIFEST_NO_ENTRIES" in captured.err


def test_cli_main_exits_nonzero_on_missing_manifest_file(tmp_path, capsys):
    manifest = tmp_path / "does-not-exist.json"
    exit_code = ip.main(["--check", "--manifest", str(manifest)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "MANIFEST_NOT_FOUND" in captured.err


def test_cli_main_exits_zero_only_when_every_entry_passes(tmp_path):
    target = tmp_path / "present.txt"
    target.write_text("x", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "good", "kind": "file", "probe": {"type": "file_exists", "path": "present.txt"}, "source": "test"},
    ])
    exit_code = ip.main(["--check", "--manifest", str(manifest), "--vault-root", str(tmp_path)])
    assert exit_code == 0


def test_cli_main_exits_two_when_an_entry_fails(tmp_path):
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [
        {"id": "bad", "kind": "file", "probe": {"type": "file_exists", "path": "absent.txt"}, "source": "test"},
    ])
    exit_code = ip.main(["--check", "--manifest", str(manifest), "--vault-root", str(tmp_path)])
    assert exit_code == 2


# ---------------------------------------------------------------------------
# Generator: determinism
# ---------------------------------------------------------------------------

def test_build_entries_is_sorted_and_deterministic_across_two_calls():
    entries_a = ip.build_entries(ip.VAULT)
    entries_b = ip.build_entries(ip.VAULT)
    ids_a = [e["id"] for e in entries_a]
    ids_b = [e["id"] for e in entries_b]
    assert ids_a == ids_b
    assert ids_a == sorted(ids_a)
    assert entries_a == entries_b


def test_generate_manifest_only_generated_at_varies_between_runs():
    manifest_a = ip.generate_manifest(ip.VAULT)
    manifest_b = ip.generate_manifest(ip.VAULT)
    a_no_ts = {k: v for k, v in manifest_a.items() if k != "generated_at"}
    b_no_ts = {k: v for k, v in manifest_b.items() if k != "generated_at"}
    assert a_no_ts == b_no_ts


def test_generated_manifest_has_no_secret_values():
    """SECURITY: no server env-block secret value (API key, bearer token)
    ever reaches the manifest, only names and structural facts. Scoped to
    values shaped like a credential (long opaque strings), not every env
    value verbatim -- a short operational flag like MCP_MODE="stdio" is
    not a secret, and it can legitimately recur independently in the
    manifest's own generated prose (e.g. "type=stdio")."""
    manifest = ip.generate_manifest(ip.VAULT)
    serialized = json.dumps(manifest)
    mcp_config = json.loads((ip.VAULT / ".mcp.json").read_text(encoding="utf-8"))

    def _looks_like_a_secret(value: str) -> bool:
        return isinstance(value, str) and len(value) >= 20

    for server in mcp_config.get("mcpServers", {}).values():
        for value in server.get("env", {}).values():
            if _looks_like_a_secret(value):
                assert value not in serialized
        for value in server.get("headers", {}).values():
            if _looks_like_a_secret(value):
                assert value not in serialized


# --- home resolution (architect 4, adversarial 4) ---

def test_rehome_reroots_a_user_profile_path_onto_this_machine(monkeypatch, tmp_path):
    """A run with USERPROFILE and APPDATA pointed at another home measures
    that home. The constants are read at import time, so the module is
    reloaded after the environment is patched."""
    import importlib

    other_home = tmp_path / "OtherUser"
    other_roaming = other_home / "AppData" / "Roaming"
    monkeypatch.setenv("USERPROFILE", str(other_home))
    monkeypatch.setenv("APPDATA", str(other_roaming))
    reloaded = importlib.reload(ip)
    try:
        assert reloaded.USER_HOME == other_home
        assert reloaded.NPM_PREFIX == other_roaming / "npm"

        plugin_row = reloaded.rehome(
            r"C:\Users\SomeoneElse\.claude\plugins\cache\market\pkg\0.1.0\.mcp.json"
        )
        assert Path(plugin_row) == other_home / ".claude/plugins/cache/market/pkg/0.1.0/.mcp.json"

        npm_row = reloaded.rehome(
            r"C:\Users\SomeoneElse\AppData\Roaming\npm\node_modules\@tobilu\qmd\dist\cli\qmd.js"
        )
        assert Path(npm_row) == other_roaming / "npm/node_modules/@tobilu/qmd/dist/cli/qmd.js"

        qmd_entry = next(
            e for e in reloaded._static_entries() if e["id"] == "file-qmd-cli"
        )
        assert str(other_roaming) in qmd_entry["probe"]["path"]
    finally:
        monkeypatch.undo()
        importlib.reload(ip)


def test_rehome_leaves_non_profile_paths_alone():
    assert ip.rehome(r"C:\Program Files\Python314\python.exe") == (
        r"C:\Program Files\Python314\python.exe"
    )
    assert ip.rehome(".claude/hooks/x.py") == ".claude/hooks/x.py"
    assert ip.rehome(None) is None


def test_no_user_name_literal_remains_in_the_generator():
    """The 13 rows that named this laptop's profile are derived now, not
    typed. The source file must carry no user-profile literal at all."""
    import re as _re

    source = Path(ip.__file__).read_text(encoding="utf-8")
    profile_literal = _re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+\w+")
    assert profile_literal.search(source) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
