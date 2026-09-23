#!/usr/bin/env python3
"""install_prereqs.py - fresh-machine prerequisite manifest generator + checker.

Origin: O2 increment 1 of
Projects/Agent-Governance-Research/work/2026-08-30-harness-spec-objectives.md.
Closes the "Install / fresh-machine story" Gap Map dimension for the vault's live
.claude/ harness: "No fresh-machine story exists for the artifact that actually
runs" (Absences paragraph).

Increment 2 (an exhaustive walk across every hook and script file confirming
runtime imports match the manifest) is named separately in O2 and is OUT OF
SCOPE here; it is gated on a fresh owner opt-in per R6 (fan-out-scale coverage).
This generator reads only the four already-compiled sources named in O2's
deliverable shape, not every hook/script body.

Compiled sources read (increment 1 scope, nothing wider)
----------------------------------------------------------
- .claude/hooks/aggregates/asset-inventory.json  (kind == "mcp-server" rows)
- .mcp.json                                       (server declarations; commands
  and structural facts only -- see SECURITY below)
- .claude/settings.local.json + .claude/settings.json (hook registrations:
  interpreter paths and commands actually invoked)
- probed interpreter facts on this machine: python (fixed path per
  reference_windows_python_path_order.md), node, git, powershell, bash

SECURITY
--------
Never copies secret VALUES (API keys, bearer tokens, env blocks inside
.mcp.json server entries) into the manifest or any output. Only server
NAMES, declared TYPES ("stdio" implied by command/args vs "http"), and
structural facts (a key path exists) are recorded. Where an "env" kind
probe is used, only the variable NAME is ever read or printed -- never
its value.

Data contract (install-prereqs-manifest.json)
----------------------------------------------
{
  "generated_at": "<iso timestamp, informational only -- excluded from any
                    determinism comparison>",
  "generator_version": "1.0",
  "notes": "...",
  "entries": [
    {
      "id": "<unique string>",
      "kind": "interpreter" | "binary" | "file" | "env" | "mcp-server",
      "probe": { "type": "executable" | "file_exists" | "json_key_exists"
                 | "env_var_set", ...type-specific fields },
      "source": "<which compiled file this entry derives from>",
      "note": "<optional human context>"
    }, ...
  ]
}

Probe types
-----------
executable        -- resolve either a literal absolute "path" or a PATH-searched
                      "command" name; optionally run "version_flag" and match
                      "version_regex" against combined stdout+stderr, comparing
                      against "min_version" (dotted, tuple-compared). No
                      min_version means presence-only.
file_exists        -- a literal "path" (absolute, or vault-relative if not
                      absolute) exists on disk.
json_key_exists     -- "json_path" (vault-relative if not absolute) parses as
                      JSON and "key_path" (list of keys) resolves inside it.
env_var_set         -- "var_name" is present (and non-empty) in os.environ.
                      NAME only is ever read; the value is never printed.

Determinism
-----------
Generation is deterministic: entries are sorted by "id", and no per-entry
timestamp is embedded. The single "generated_at" header field is the only
run-varying content and is excluded from determinism comparisons (matches
staleness-manifest.json's own convention).

Two run modes
-------------
Generate (default): reads the compiled sources + probes this machine's fixed
python path, writes install-prereqs-manifest.json.

Check (--check): loads a manifest (default: install-prereqs-manifest.json next
to this script) and verifies every entry against the machine it runs on. An
empty, missing, or malformed manifest is a MANIFEST error and exits 1 -- a
manifest resolving to nothing is never a clean bill, matching
staleness_check.py's ManifestError discipline. Any entry not PASS exits 2.
Clean exit 0 only when every entry passes.

Usage
-----
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/install_prereqs.py
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/install_prereqs.py --check
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/install_prereqs.py --check --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure UTF-8 stdout/stderr on Windows (Python 3.14 defaults stdout text mode
# to the OS ANSI codepage -- reference_python_windows_encoding.md). Stdlib only.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]  # .claude/scripts -> .claude -> vault root
DEFAULT_MANIFEST = SCRIPT_DIR / "install-prereqs-manifest.json"

# Home resolution, read once at import time (monkeypatch the environment and
# reload the module to point a run at a different home). Every user-profile
# path in this file, whether typed here or copied in from
# asset-inventory.json, is re-rooted through these three constants by
# rehome(), so a run on another machine measures THAT machine. Before this,
# 13 probe rows named the source laptop's profile: a false green here and a
# guaranteed red on any machine with a different Windows user name.
USER_HOME = Path(os.environ.get("USERPROFILE") or Path.home())
APPDATA_ROAMING = Path(os.environ.get("APPDATA") or (USER_HOME / "AppData" / "Roaming"))
NPM_PREFIX = APPDATA_ROAMING / "npm"

# A Windows user-profile prefix in any drive-letter spelling, user name not
# named: C:\Users\<anyone>\ or C:/Users/<anyone>/.
_PROFILE_PREFIX_RE = re.compile(r"^[A-Za-z]:[\\/]+Users[\\/]+[^\\/]+[\\/]+")
_ROAMING_PREFIX = "appdata/roaming/"


def rehome(path_str: str) -> str:
    """Re-root an absolute Windows user-profile path onto this machine's home.

    Leaves every other path untouched (vault-relative paths, Program Files,
    a bare command name). APPDATA is honoured separately because a roaming
    profile can put it outside USERPROFILE.
    """
    if not isinstance(path_str, str):
        return path_str
    m = _PROFILE_PREFIX_RE.match(path_str)
    if not m:
        return path_str
    rest = path_str[m.end():].replace("\\", "/")
    if rest.lower().startswith(_ROAMING_PREFIX):
        return str(APPDATA_ROAMING / rest[len(_ROAMING_PREFIX):])
    return str(USER_HOME / rest)
ASSET_INVENTORY = VAULT / ".claude" / "hooks" / "aggregates" / "asset-inventory.json"
MCP_CONFIG = VAULT / ".mcp.json"

GENERATOR_VERSION = "1.0"

REQUIRED_ENTRY_FIELDS = ("id", "kind", "probe", "source")
VALID_KINDS = {"interpreter", "binary", "file", "env", "mcp-server"}


class ManifestError(Exception):
    """The manifest itself cannot be trusted: missing, unreadable, empty,
    malformed, or resolving to zero entries. A manifest problem, not a
    per-entry one."""


class GeneratorError(Exception):
    """A compiled source needed to generate the manifest is missing or
    malformed."""


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Any:
    if not path.exists():
        raise GeneratorError(f"compiled source not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GeneratorError(f"compiled source invalid JSON: {path}: {exc}") from exc


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def get_mcp_server_rows(asset_inventory: dict) -> list[dict]:
    rows = asset_inventory.get("rows")
    if not isinstance(rows, list):
        raise GeneratorError(
            f"{ASSET_INVENTORY}: expected top-level 'rows' array, none found"
        )
    return [r for r in rows if r.get("kind") == "mcp-server"]


def _static_entries() -> list[dict]:
    """Interpreter/binary/file entries derived from settings.local.json,
    settings.json, and .mcp.json hook/server command strings, plus the
    python full-path convention documented in
    reference_windows_python_path_order.md."""
    return [
        {
            "id": "interpreter-python",
            "kind": "interpreter",
            "probe": {
                "type": "executable",
                "path": "C:\\Program Files\\Python314\\python.exe",
                "command": "python",
                "version_flag": ["--version"],
                "version_regex": r"Python\s+(\d+\.\d+\.\d+)",
                "min_version": "3.14.0",
            },
            "source": (
                ".claude/settings.local.json + .claude/settings.json "
                "(hook command interpreter path, invoked as the literal full "
                "path in every Python hook registration)"
            ),
            "note": (
                "Every Python-based hook in this vault invokes this literal "
                "path rather than bare 'python', per "
                "reference_windows_python_path_order.md: a Windows Store "
                "python.exe alias stub can shadow bare 'python' on PATH."
            ),
        },
        {
            "id": "interpreter-node",
            "kind": "interpreter",
            "probe": {
                "type": "executable",
                "path": None,
                "command": "node",
                "version_flag": ["--version"],
                "version_regex": r"v?(\d+\.\d+\.\d+)",
                "min_version": None,
            },
            "source": ".mcp.json (qmd MCP server command: \"node\" <qmd.js path>)",
            "note": (
                "Also the runtime the 'cmd /c npx -y <pkg>'-based MCP servers "
                "(the stdio servers named in install-prereqs-manifest.json) depend "
                "on at boot; see binary-npx."
            ),
        },
        {
            "id": "interpreter-powershell",
            "kind": "interpreter",
            "probe": {
                "type": "executable",
                "path": None,
                "command": "powershell",
                "version_flag": [
                    "-NoProfile", "-NonInteractive", "-Command",
                    "$PSVersionTable.PSVersion.ToString()",
                ],
                "version_regex": r"(\d+\.\d+(?:\.\d+)?)",
                "min_version": None,
            },
            "source": ".claude/settings.json (Stop hook: ralph-stop-hook.ps1)",
        },
        {
            "id": "interpreter-bash",
            "kind": "interpreter",
            "probe": {
                "type": "executable",
                "path": None,
                "command": "bash",
                "version_flag": ["--version"],
                "version_regex": r"version\s+(\d+\.\d+\.\d+)",
                "min_version": None,
            },
            "source": (
                ".claude/settings.json (SessionStart hooks: session-start.sh, "
                "restore-compact.sh)"
            ),
        },
        {
            "id": "binary-git",
            "kind": "binary",
            "probe": {
                "type": "executable",
                "path": None,
                "command": "git",
                "version_flag": ["--version"],
                "version_regex": r"git version (\d+\.\d+\.\d+)",
                "min_version": None,
            },
            "source": (
                "probed interpreter fact (task instruction); this vault is a "
                "git repository (CLAUDE.md Tool & Environment Quirks)"
            ),
        },
        {
            "id": "binary-npx",
            "kind": "binary",
            "probe": {
                "type": "executable",
                "path": None,
                "command": "npx",
                "version_flag": ["--version"],
                "version_regex": r"(\d+\.\d+\.\d+)",
                "min_version": None,
            },
            "source": (
                ".mcp.json (every stdio server command of the form "
                "\"cmd /c npx -y <pkg>\")"
            ),
        },
        {
            "id": "file-qmd-cli",
            "kind": "file",
            "probe": {
                "type": "file_exists",
                "path": str(
                    NPM_PREFIX / "node_modules" / "@tobilu" / "qmd" / "dist"
                    / "cli" / "qmd.js"
                ),
            },
            "source": ".mcp.json (qmd server args: absolute qmd.js path)",
            "note": (
                "Globally npm-installed package; a fresh machine needs "
                "'npm install -g @tobilu/qmd' (or equivalent) before this "
                "path exists."
            ),
        },
    ]


def _mcp_server_entries(vault_root: Path) -> list[dict]:
    asset_inventory = load_json(ASSET_INVENTORY)
    mcp_config = load_json(MCP_CONFIG)
    mcp_config_servers = mcp_config.get("mcpServers", {})
    rows = sorted(get_mcp_server_rows(asset_inventory), key=lambda r: r["name"])

    entries = []
    for row in rows:
        name = row["name"]
        path = row.get("path")
        provenance = row.get("provenance", "")
        entry_id = f"mcp-server-{_slug(name)}"

        if path == ".mcp.json":
            # Vault-authored server: declared directly in this vault's .mcp.json.
            server_cfg = mcp_config_servers.get(name, {})
            server_type = server_cfg.get("type", "stdio")
            if server_type == "http":
                runtime_note = "network service (http type); no local runtime prerequisite beyond reachability"
            elif name == "qmd":
                runtime_note = "runs via 'node' directly; see interpreter-node, file-qmd-cli"
            else:
                runtime_note = "runs via 'cmd /c npx'; see binary-npx, interpreter-node"
            entries.append({
                "id": entry_id,
                "kind": "mcp-server",
                "probe": {
                    "type": "json_key_exists",
                    "json_path": ".mcp.json",
                    "key_path": ["mcpServers", name],
                },
                "source": (
                    ".claude/hooks/aggregates/asset-inventory.json "
                    "(mcp-server row) + .mcp.json (server declaration)"
                ),
                "note": f"provenance={provenance}; type={server_type}; {runtime_note}",
            })
        else:
            # Plugin-declared server: reachable only once the declaring plugin
            # is installed. Path is asset-inventory.json's own resolved path.
            entries.append({
                "id": entry_id,
                "kind": "mcp-server",
                "probe": {
                    "type": "file_exists",
                    # asset-inventory.json records the path with the
                    # generating machine's profile baked in; re-root it so
                    # the row probes this machine's plugin cache.
                    "path": rehome(path),
                },
                "source": (
                    ".claude/hooks/aggregates/asset-inventory.json "
                    "(mcp-server row, plugin-declared)"
                ),
                "note": (
                    f"provenance={provenance}; materializes once the "
                    "declaring plugin is installed via /plugin marketplace "
                    "add + /plugin install. The content-hash path segment "
                    "can change on plugin update, so this entry is only as "
                    "fresh as the asset-inventory.json generation it was "
                    "derived from."
                ),
            })
    return entries


def build_entries(vault_root: Path) -> list[dict]:
    entries = _static_entries() + _mcp_server_entries(vault_root)
    entries.sort(key=lambda e: e["id"])
    return entries


def generate_manifest(vault_root: Path) -> dict:
    entries = build_entries(vault_root)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_version": GENERATOR_VERSION,
        "notes": (
            "O2 increment 1 fresh-machine prerequisite manifest "
            "(2026-08-30-harness-spec-objectives.md). Generated from "
            "compiled sources only: asset-inventory.json mcp-server rows, "
            ".mcp.json, settings.local.json/settings.json hook "
            "registrations, and probed interpreter facts. Increment 2 (the "
            "exhaustive runtime-import walk across every hook and script) is "
            "a named follow-up, out of this manifest's scope, per O2's "
            "close bar. No env-kind entries are populated this pass: "
            "determining real environment-variable prerequisites requires "
            "reading individual hook script bodies, which is increment-2 "
            "scope; the env_var_set probe type is implemented and tested "
            "for forward use."
        ),
        "entries": entries,
    }


def write_manifest(manifest: dict, path: Path) -> None:
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

def load_manifest(manifest_path: Path) -> list[dict]:
    if not manifest_path.exists():
        raise ManifestError(f"MANIFEST_NOT_FOUND: {manifest_path} does not exist")
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"MANIFEST_UNREADABLE: {manifest_path}: {exc}") from exc
    if not raw.strip():
        raise ManifestError(f"MANIFEST_EMPTY: {manifest_path} is an empty file")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"MANIFEST_INVALID_JSON: {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"MANIFEST_MALFORMED: {manifest_path} top level must be an object")
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) == 0:
        raise ManifestError(
            f"MANIFEST_NO_ENTRIES: {manifest_path} 'entries' is missing or empty; "
            "a manifest resolving to nothing is refused, not reported as a clean bill"
        )
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"MANIFEST_MALFORMED: entries[{i}] is not an object")
        missing = [f for f in REQUIRED_ENTRY_FIELDS if f not in entry]
        if missing:
            raise ManifestError(
                f"MANIFEST_MALFORMED: entries[{i}] (id={entry.get('id')!r}) "
                f"missing required field(s): {missing}"
            )
        if entry["kind"] not in VALID_KINDS:
            raise ManifestError(
                f"MANIFEST_MALFORMED: entries[{i}] (id={entry.get('id')!r}) "
                f"unknown kind {entry['kind']!r}"
            )
    return entries


def _version_tuple(v: str) -> tuple:
    parts = re.findall(r"\d+", v)
    return tuple(int(x) for x in parts) if parts else (0,)


def _resolve_executable(command: Optional[str], path: Optional[str]) -> Optional[Path]:
    if path:
        p = Path(path)
        return p if p.exists() else None
    if not command:
        return None
    found = shutil.which(command)
    return Path(found) if found else None


def check_executable(probe: dict) -> tuple[bool, str]:
    command = probe.get("command")
    path = probe.get("path")
    exe = _resolve_executable(command, path)
    if exe is None:
        loc = path or f"'{command}' on PATH"
        return False, f"not found: {loc}"

    min_version = probe.get("min_version")
    if not min_version:
        return True, f"found at {exe}"

    version_flag = probe.get("version_flag") or ["--version"]
    try:
        result = subprocess.run(
            [str(exe), *version_flag],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:
        return False, f"version check failed to run: {exc}"

    output = (result.stdout or "") + (result.stderr or "")
    regex = probe.get("version_regex")
    match = re.search(regex, output) if regex else None
    if not match:
        return False, f"could not parse version from output near {output[:120]!r}"

    found_version = match.group(1)
    if _version_tuple(found_version) >= _version_tuple(min_version):
        return True, f"found at {exe}, version {found_version} >= required {min_version}"
    return False, f"found at {exe}, version {found_version} < required {min_version}"


def check_file_exists(probe: dict, vault_root: Path) -> tuple[bool, str]:
    # rehome() at check time as well as at generate time: a checked-in
    # manifest carries whichever machine generated it, and the probe has to
    # measure the machine it is running on.
    p = Path(rehome(probe["path"]))
    if not p.is_absolute():
        p = vault_root / probe["path"]
    if p.exists():
        return True, f"exists: {p}"
    return False, f"not found: {p}"


def check_json_key_exists(probe: dict, vault_root: Path) -> tuple[bool, str]:
    p = Path(probe["json_path"])
    if not p.is_absolute():
        p = vault_root / probe["json_path"]
    if not p.exists():
        return False, f"json file not found: {p}"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON in {p}: {exc}"
    node: Any = data
    key_path = probe.get("key_path", [])
    for key in key_path:
        if not isinstance(node, dict) or key not in node:
            return False, f"key path {key_path} not found in {p} (missing at {key!r})"
        node = node[key]
    return True, f"key path {key_path} present in {p}"


def check_env_var_set(probe: dict) -> tuple[bool, str]:
    var_name = probe["var_name"]
    # NAME only -- the value is deliberately never read into the result string.
    if os.environ.get(var_name, "") != "":
        return True, f"env var {var_name} is set"
    return False, f"env var {var_name} is not set"


PROBE_CHECKERS = {
    "executable": lambda probe, vault_root: check_executable(probe),
    "file_exists": check_file_exists,
    "json_key_exists": check_json_key_exists,
    "env_var_set": lambda probe, vault_root: check_env_var_set(probe),
}


def check_entry(entry: dict, vault_root: Path) -> tuple[bool, str]:
    probe = entry.get("probe", {})
    ptype = probe.get("type")
    fn = PROBE_CHECKERS.get(ptype)
    if fn is None:
        return False, f"unknown probe type: {ptype!r}"
    try:
        return fn(probe, vault_root)
    except KeyError as exc:
        return False, f"probe missing required field: {exc}"
    except Exception as exc:
        return False, f"probe raised: {exc}"


def run_check(manifest_path: Path, vault_root: Path) -> list[dict]:
    """Raises ManifestError if the manifest itself cannot be trusted; never
    raises for a per-entry problem."""
    entries = load_manifest(manifest_path)
    results = []
    for entry in entries:
        passed, detail = check_entry(entry, vault_root)
        results.append({
            "id": entry["id"],
            "kind": entry["kind"],
            "passed": passed,
            "detail": detail,
        })
    return results


def render_table(results: list[dict]) -> str:
    lines = ["Install Prereqs Check", ""]
    width_id = max([len("id")] + [len(r["id"]) for r in results])
    header = f"{'id'.ljust(width_id)}  verdict  detail"
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        verdict = "PASS" if r["passed"] else "FAIL"
        lines.append(f"{r['id'].ljust(width_id)}  {verdict.ljust(7)}  {r['detail']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate (default) or check (--check) the fresh-machine "
            "prerequisite manifest for this vault's live .claude/ harness."
        )
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                         help="Manifest JSON path (default: install-prereqs-manifest.json next to this script).")
    parser.add_argument("--vault-root", type=Path, default=VAULT,
                         help="Vault root that vault-relative probe paths resolve against.")
    parser.add_argument("--check", action="store_true",
                         help="Check mode: verify every manifest entry against this machine.")
    parser.add_argument("--json", action="store_true",
                         help="Emit JSON instead of a table (check mode only).")
    return parser


def _run_generate(args: argparse.Namespace) -> int:
    try:
        manifest = generate_manifest(args.vault_root)
    except GeneratorError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    write_manifest(manifest, args.manifest)
    print(f"Wrote {len(manifest['entries'])} entries to {args.manifest}")
    return 0


def _run_check(args: argparse.Namespace) -> int:
    try:
        results = run_check(args.manifest, args.vault_root)
    except ManifestError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(render_table(results))

    if any(not r["passed"] for r in results):
        return 2
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        return _run_check(args)
    return _run_generate(args)


if __name__ == "__main__":
    raise SystemExit(main())
