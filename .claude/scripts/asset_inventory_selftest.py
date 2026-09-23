#!/usr/bin/env python
"""asset_inventory_selftest.py -- independent self-test for asset_inventory.py.

Every assertion re-derives its comparison value directly from the raw
sources at self-test run time (a fresh directory listing, a fresh stream of
the sink files) -- never by reading the generator's own cached totals and
comparing them to themselves. Runs the real generator script as a
subprocess (not an in-process function call) so every assertion observes
the same CLI behavior a human invoking the script would see.

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude\\scripts\\asset_inventory_selftest.py

O9 increment 1 (2026-09-01): pass --check-live-only to run ONLY
ASSERT-016..019 against the on-disk asset-inventory.json without invoking
the generator (fail-branch demonstration mode; a full run would
regenerate and overwrite the pre-change JSON under test).

Exit code 0 if every assertion PASSes, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
CLAUDE_DIR = SCRIPT_DIR.parent
REPO_ROOT = CLAUDE_DIR.parent

GENERATOR = SCRIPT_DIR / "asset_inventory.py"
HOOKS_DIR = CLAUDE_DIR / "hooks"
HOOK_ACTIVITY_JSONL = HOOKS_DIR / "hook-activity.jsonl"
GOVERNANCE_LOG_JSONL = HOOKS_DIR / "governance-log.jsonl"
AGGREGATES_DIR = HOOKS_DIR / "aggregates"
DATA_FILE = AGGREGATES_DIR / "asset-inventory.json"

PYTHON = sys.executable

RESULTS: list[tuple[str, bool, str]] = []

# O9 increment 2 (2026-09-01): the two legal usage.source values for a
# workflow row. Deliberately duplicated string literals (this suite never
# imports the generator -- same independence rule as every other assertion;
# ASSERT-016 pins the exact text the same way it pinned NO_SOURCE_FOR_KIND).
WORKFLOW_USAGE_SOURCE = (
    "governance-log.jsonl:subagent-quality-check.pass(workflow); "
    "completions-only; identity plumbed 2026-09-01, earlier records carry no identity")
WORKFLOW_SENTINEL = "AWAITING_FIRST_OBSERVATION"


def record(assert_id: str, ok: bool, detail: str) -> None:
    RESULTS.append((assert_id, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {assert_id}: {detail}")


def run_generator(*, aggregates_dir: Path = AGGREGATES_DIR,
                   governance_log_path: Path = GOVERNANCE_LOG_JSONL,
                   hook_activity_path: Path = HOOK_ACTIVITY_JSONL,
                   registry_path: Path | None = None,
                   run_id: str | None = None) -> subprocess.CompletedProcess:
    args = [
        PYTHON, str(GENERATOR),
        "--aggregates-dir", str(aggregates_dir),
        "--governance-log-path", str(governance_log_path),
        "--hook-activity-path", str(hook_activity_path),
    ]
    if registry_path:
        args += ["--registry-path", str(registry_path)]
    if run_id:
        args += ["--run-id", run_id]
    # The registry-freshness guard (2026-08-22) is for real runs. This suite
    # uses synthetic fixtures and would otherwise fail whenever anyone edits a
    # hook without regenerating registry.json, which is the normal state
    # mid-change.
    args += ["--skip-freshness-check"]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", env=env)


PLUGIN_CACHE_ROOT = Path.home() / ".claude" / "plugins" / "cache"
PLUGIN_INSTALLED_JSON = Path.home() / ".claude" / "plugins" / "installed_plugins.json"


def fresh_plugin_row_expectations() -> dict | None:
    """Independent re-derivation of the plugin-cache row population, for
    ASSERT-010/ASSERT-011. Does NOT import or call anything from
    asset_inventory.py -- a fresh installed_plugins.json read and fresh
    Path.rglob calls, written separately so a generator defect that
    miscounts cannot also miscount identically here. Implements the SAME
    documented rule the generator states (canonical installPath only, one
    row per hooks.json {event,matcher,item} entry, one row per declared MCP
    server name) but via its own independent code path, including its own
    symlink-stub detection (small text file whose content is a bare
    relative path -- see asset_inventory.py's resolve_plugin_content_path
    docstring for why this exists on this machine) and its own dedupe.
    Returns None if the plugin cache is absent on this machine (the
    generator's own graceful-degradation case -- not a test failure)."""
    if not PLUGIN_CACHE_ROOT.is_dir() or not PLUGIN_INSTALLED_JSON.exists():
        return None
    manifest = json.loads(PLUGIN_INSTALLED_JSON.read_bytes().decode("utf-8"))
    plugins_map = manifest.get("plugins", {})

    def resolve_stub(p: Path, max_hops: int = 4) -> Path:
        cur = p
        for _ in range(max_hops):
            try:
                size = cur.stat().st_size
            except OSError:
                return cur
            if size == 0 or size >= 1000:
                return cur
            try:
                content = cur.read_bytes().decode("utf-8", errors="replace").strip()
            except OSError:
                return cur
            if "\n" in content or not re.match(r"^[./][\w./\-]+\.(?:md|json)$", content):
                return cur
            cand = (cur.parent / content).resolve()
            if not cand.is_file():
                return cur
            cur = cand
        return cur

    skill_real_paths: set = set()
    agent_real_paths: set = set()
    hook_entry_count = 0
    mcp_server_names: set = set()

    for key, installs in plugins_map.items():
        if not isinstance(installs, list) or not installs:
            continue
        install_path = Path(installs[-1].get("installPath", ""))
        if not install_path.is_dir():
            continue

        for skill_md in install_path.rglob("*/[Ss][Kk][Ii][Ll][Ll].md"):
            real = resolve_stub(skill_md)
            skill_real_paths.add((key, str(real)))
        for agent_md in install_path.rglob("agents/*.md"):
            real = resolve_stub(agent_md)
            agent_real_paths.add((key, str(real)))

        hooks_json = install_path / "hooks" / "hooks.json"
        if hooks_json.is_file():
            try:
                hdata = json.loads(hooks_json.read_bytes().decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                hdata = {}
            for event, blocks in (hdata.get("hooks") or {}).items():
                if not isinstance(blocks, list):
                    continue
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    items = block.get("hooks", [])
                    if isinstance(items, list):
                        hook_entry_count += sum(1 for it in items if isinstance(it, dict))

        plugin_json = install_path / ".claude-plugin" / "plugin.json"
        mcp_field = None
        if plugin_json.is_file():
            try:
                mcp_field = json.loads(plugin_json.read_bytes().decode("utf-8")).get("mcpServers")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                mcp_field = None
        mcp_json_path = None
        inline_map = None
        if isinstance(mcp_field, str):
            rel_field = mcp_field[2:] if mcp_field.startswith("./") else mcp_field
            cand = (install_path / rel_field).resolve()
            if cand.is_file():
                mcp_json_path = cand
        elif isinstance(mcp_field, dict):
            inline_map = mcp_field
        else:
            default_path = install_path / ".mcp.json"
            if default_path.is_file():
                mcp_json_path = default_path
        server_map = inline_map
        if server_map is None and mcp_json_path is not None:
            try:
                fdata = json.loads(mcp_json_path.read_bytes().decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                fdata = {}
            server_map = fdata.get("mcpServers") if isinstance(fdata.get("mcpServers"), dict) else fdata
        if isinstance(server_map, dict):
            for server_name in server_map.keys():
                mcp_server_names.add((key, server_name))

    return {
        "skill_count": len(skill_real_paths),
        "agent_count": len(agent_real_paths),
        "hook_entry_count": hook_entry_count,
        "mcp_server_count": len(mcp_server_names),
    }


def fresh_hook_py_stems() -> tuple[set[str], set[str]]:
    """Fresh count of every .py file the generator's hook enumeration can
    produce a row or an excluded-count entry for: top-level plus retired/
    (FIX 5, 2026-08-19) -- kept in sync with enumerate_hooks() in
    asset_inventory.py so ASSERT-001 stays a meaningful independent check
    rather than silently going stale against the generator's own scope."""
    top_py = sorted(p.name for p in HOOKS_DIR.glob("*.py"))
    retired_dir = HOOKS_DIR / "retired"
    retired_py = sorted(p.name for p in retired_dir.glob("*.py")) if retired_dir.is_dir() else []
    all_py = top_py + retired_py
    non_test = {f[:-3] for f in all_py if not f.startswith("test_")}
    test_files = {f for f in all_py if f.startswith("test_")}
    return non_test, test_files


def fresh_hook_activity_line_count() -> int:
    n = 0
    with open(HOOK_ACTIVITY_JSONL, "rb") as fh:
        for _ in fh:
            n += 1
    return n


def fresh_agent_dispatched_count() -> int:
    n = 0
    with open(GOVERNANCE_LOG_JSONL, "rb") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                rec = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if rec.get("event") == "agent_dispatched":
                n += 1
    return n


def fresh_all_hook_files() -> list[Path]:
    """Independent re-derivation of the full hook-file population (FIX 5:
    top-level + retired), for ASSERT-009. Fresh os.walk-equivalent glob at
    self-test time, not a read of the generator's own enumeration."""
    top = sorted(HOOKS_DIR.glob("*.py"))
    retired_dir = HOOKS_DIR / "retired"
    retired = sorted(retired_dir.glob("*.py")) if retired_dir.is_dir() else []
    return [p for p in (top + retired) if not p.name.startswith("test_")]


def fresh_settings_registers(hook_filename: str) -> bool:
    """Independent re-derivation of EVD-001 (settings-file registration)
    for one hook filename: fresh read of both settings files, no reuse of
    the generator's own load_settings_hook_commands()."""
    for settings_name in ("settings.json", "settings.local.json"):
        settings_path = CLAUDE_DIR / settings_name
        if not settings_path.exists():
            continue
        data = json.loads(settings_path.read_bytes().decode("utf-8"))
        for matcher_blocks in (data.get("hooks", {}) or {}).values():
            for block in matcher_blocks:
                for h in block.get("hooks", []):
                    if hook_filename in h.get("command", ""):
                        return True
    return False


def fresh_imports(importer_text: str, target_py_stem: str) -> bool:
    pattern = re.compile(r"(^|\n)\s*(from|import)\s+" + re.escape(target_py_stem) + r"(\s|\.|$)")
    return bool(pattern.search(importer_text))


AGGREGATES_DIR_FRESH = CLAUDE_DIR / "hooks" / "aggregates"
MCP_JSON_FRESH = REPO_ROOT / ".mcp.json"
TELEMETRY_VOCAB_JSON_FRESH = AGGREGATES_DIR_FRESH / "telemetry-vocabulary.json"
SENSITIVE_ENV_KEY_PATTERN = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|AUTH|CREDENTIAL)", re.IGNORECASE)


def fresh_settings_registration_count() -> int:
    """Independent re-derivation of the O1 (2026-08-30) settings-registration
    row count: a fresh read of settings.json's and settings.local.json's own
    hook-command entries, plus a fresh read of .mcp.json's own mcpServers
    entries. Shares no code with asset_inventory.py's own
    load_settings_registration_entries()/load_mcp_registration_entries()."""
    n = 0
    for settings_name in ("settings.json", "settings.local.json"):
        settings_path = CLAUDE_DIR / settings_name
        if not settings_path.exists():
            continue
        data = json.loads(settings_path.read_bytes().decode("utf-8"))
        for matcher_blocks in (data.get("hooks", {}) or {}).values():
            for block in matcher_blocks:
                n += len(block.get("hooks", []))
    if MCP_JSON_FRESH.exists():
        mcp_data = json.loads(MCP_JSON_FRESH.read_bytes().decode("utf-8"))
        n += len(mcp_data.get("mcpServers", {}))
    return n


def fresh_telemetry_sink_count() -> int:
    """Independent re-derivation of the O1 (2026-08-30) telemetry-sink row
    count: the union of the two sink basenames this generator reads
    directly (hook-activity.jsonl, governance-log.jsonl) plus every sink
    name declared as a key in telemetry-vocabulary.json, if present. Shares
    no code with asset_inventory.py's own load_known_telemetry_sinks()."""
    names = {"hook-activity.jsonl", "governance-log.jsonl"}
    if TELEMETRY_VOCAB_JSON_FRESH.exists():
        try:
            vocab = json.loads(TELEMETRY_VOCAB_JSON_FRESH.read_bytes().decode("utf-8"))
            names |= set(vocab.get("sinks", {}).keys())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    return len(names)


def fresh_mcp_secret_values() -> list[str]:
    """Every literal secret-bearing string value in .mcp.json: every 'env'
    dict value whose KEY name matches a KEY/TOKEN/SECRET/PASSWORD/AUTH/
    CREDENTIAL pattern, and every 'headers' dict value unconditionally (a
    header value is always treated as sensitive, per the O1 constraint's
    explicit wording). Used by ASSERT-015 to prove none of them land
    anywhere in the generated asset-inventory.json output. Scoped by key
    name rather than by every env value, so a plain structural value like
    'stdio' or 'error' is never flagged -- that would risk a false FAIL on
    an unrelated coincidental substring match elsewhere in a large JSON
    file, not a real leak."""
    if not MCP_JSON_FRESH.exists():
        return []
    data = json.loads(MCP_JSON_FRESH.read_bytes().decode("utf-8"))
    secrets: list[str] = []
    for cfg in data.get("mcpServers", {}).values():
        if not isinstance(cfg, dict):
            continue
        for k, v in (cfg.get("env") or {}).items():
            if isinstance(v, str) and v and SENSITIVE_ENV_KEY_PATTERN.search(k):
                secrets.append(v)
        for v in (cfg.get("headers") or {}).values():
            if isinstance(v, str) and v:
                secrets.append(v)
    return secrets


def stat_sink(path: Path) -> tuple[int, float]:
    st = path.stat()
    return st.st_size, st.st_mtime


def hash_prefix(path: Path, length: int, chunk_size: int = 1024 * 1024) -> str:
    """SHA-256 over the first `length` bytes of path, read in bounded
    chunk_size (default 1 MiB) increments. Used by ASSERT-006 to prove
    non-authorship (the generator never truncated or rewrote pre-existing
    sink bytes) without ever holding the full multi-megabyte sink file in
    memory at once."""
    h = hashlib.sha256()
    remaining = length
    with open(path, "rb") as fh:
        while remaining > 0:
            chunk = fh.read(min(chunk_size, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest()


def strip_volatile(data: dict) -> dict:
    d = dict(data)
    d.pop("run_id", None)
    d.pop("generated_at", None)
    d.pop("diff", None)
    # O13 (2026-09-01): the 30-day window bounds derive from generated_at,
    # so they are volatile by construction and must not fail the
    # determinism comparison. window_days stays (a spec constant), and the
    # windowed counts stay: with static sinks they are expected identical
    # (a boundary record crossing the 30-day edge between two runs seconds
    # apart is the accepted residual race, called out in the O13 build
    # record's untested surface).
    sk = d.get("skipped_records")
    if isinstance(sk, dict) and isinstance(sk.get("window"), dict):
        sk = dict(sk)
        win = dict(sk["window"])
        win.pop("window_start", None)
        win.pop("window_end", None)
        sk["window"] = win
        d["skipped_records"] = sk
    return d


def strip_usage(data: dict) -> dict:
    """Removes every field that a genuine concurrent sink write can
    legitimately change (usage counts/timestamps and the metadata derived
    from them), leaving only the structural fields a real generator defect
    could plausibly disturb."""
    d = dict(data)
    d.pop("skipped_records", None)
    rows = []
    for r in d.get("rows", []):
        r2 = dict(r)
        r2.pop("usage", None)
        rows.append(r2)
    d["rows"] = rows
    return d


def run_o9_assertions(data: dict) -> None:
    """O9 increment 1 (2026-09-01): four assertions over one generated
    asset-inventory.json dict. Shared between the normal full run (against
    the fresh regeneration) and --check-live-only (against the on-disk
    file, no generator invocation). Set equality and within-JSON equalities
    only: no absolute event counts are hardcoded, because the live sinks
    grow between a fail-branch and a pass-branch run. The one fixed
    cardinality is the 7 workflow rows, a file-count fact of
    .claude/workflows/."""
    rows = data["rows"]

    # ---- ASSERT-016 (revised 2026-09-01, O9 increment 2): NO_SOURCE_FOR_KIND
    # is EMPTY, and the 7 workflow rows partition between the attributed
    # workflow source (count >= 1) and the explicit awaiting-first-observation
    # sentinel (count == 0). The increment-1 form (set == the 7 workflow rows)
    # would false-fail against a correct post-increment-2 inventory (Gate's
    # ASSERTION HANDOVER clause, amendment review 2026-09-01). ----
    no_source = sorted((r["kind"], r["name"]) for r in rows
                       if r["usage"]["source"] == "NO_SOURCE_FOR_KIND")
    wf_rows = [r for r in rows if r["kind"] == "workflow"]
    attributed = sorted(r["name"] for r in wf_rows
                        if r["usage"]["source"] == WORKFLOW_USAGE_SOURCE)
    sentinel = sorted(r["name"] for r in wf_rows
                      if r["usage"]["source"] == WORKFLOW_SENTINEL)
    bad_counts = sorted(
        r["name"] for r in wf_rows
        if (r["usage"]["source"] == WORKFLOW_USAGE_SOURCE and r["usage"]["total_count"] < 1)
        or (r["usage"]["source"] == WORKFLOW_SENTINEL and r["usage"]["total_count"] != 0))
    unpartitioned = sorted(set(r["name"] for r in wf_rows)
                           - set(attributed) - set(sentinel))
    ok16 = (len(no_source) == 0 and len(wf_rows) == 7 and not bad_counts
            and not unpartitioned)
    record(
        "ASSERT-016",
        ok16,
        f"rows with usage.source == 'NO_SOURCE_FOR_KIND' = {len(no_source)} (expected 0) "
        f"{no_source[:12]}; workflow rows = {len(wf_rows)} (expected exactly 7); attributed "
        f"(WORKFLOW_USAGE_SOURCE, count >= 1) = {len(attributed)} {attributed}; sentinel "
        f"('{WORKFLOW_SENTINEL}', count == 0) = {len(sentinel)} {sentinel}; count-rule "
        f"violations = {bad_counts}; rows outside the partition = {unpartitioned}",
    )

    # ---- ASSERT-017: UNRESOLVED_REGISTRATION is exactly the BLK-006
    # settings-registration rows, blocked_reason carried, header agrees ----
    unresolved = {(r["kind"], r["name"]) for r in rows
                  if r["usage"]["source"] == "UNRESOLVED_REGISTRATION"}
    blk006 = {(r["kind"], r["name"]) for r in rows
              if r["kind"] == "settings-registration" and r["blocked_reason"]}
    carried = all("BLK-006" in r["blocked_reason"] for r in rows
                  if (r["kind"], r["name"]) in unresolved)
    header_unresolved = data["settings_registration_kind"]["unresolved_count"]
    ok17 = (unresolved == blk006 and carried and len(unresolved) == header_unresolved)
    record(
        "ASSERT-017",
        ok17,
        f"rows with usage.source == 'UNRESOLVED_REGISTRATION' = {len(unresolved)}; "
        f"settings-registration rows with non-empty blocked_reason = {len(blk006)}; sets equal "
        f"= {unresolved == blk006}; every UNRESOLVED_REGISTRATION row still carries 'BLK-006' "
        f"= {carried}; header settings_registration_kind.unresolved_count = {header_unresolved}",
    )

    # ---- ASSERT-018: the two streamed sinks' rows carry their own
    # header total_lines as usage (all four values from the same JSON) ----
    sink_rows = {r["name"]: r for r in rows if r["kind"] == "telemetry-sink"}
    ha_row = sink_rows.get("hook-activity.jsonl")
    gov_row = sink_rows.get("governance-log.jsonl")
    ha_header = data["skipped_records"]["hook_activity_jsonl"]["total_lines"]
    gov_header = data["skipped_records"]["governance_log_jsonl"]["total_lines"]
    ha_count = ha_row["usage"]["total_count"] if ha_row else None
    gov_count = gov_row["usage"]["total_count"] if gov_row else None
    ok18 = ha_count == ha_header and gov_count == gov_header
    record(
        "ASSERT-018",
        ok18,
        f"hook-activity.jsonl sink row usage.total_count = {ha_count} vs header total_lines = "
        f"{ha_header}; governance-log.jsonl sink row usage.total_count = {gov_count} vs header "
        f"total_lines = {gov_header} (both equalities required)",
    )

    # ---- ASSERT-019: mcp_server_kind.row_count matches the live rows
    # (stale-header regression guard: 8 vs 15 shipped before O9) ----
    mcp_row_count = sum(1 for r in rows if r["kind"] == "mcp-server")
    header_count = data["mcp_server_kind"]["row_count"]
    ok19 = header_count == mcp_row_count
    record(
        "ASSERT-019",
        ok19,
        f"mcp_server_kind.row_count header = {header_count}; live rows with kind == "
        f"'mcp-server' = {mcp_row_count} (stale-header regression guard)",
    )


def run_o13_assertions(data: dict) -> None:
    """O13 (2026-09-01): three assertions over the metric-1 stable
    definition header blocks (30-day trailing window, enumeration-set
    fingerprint, per-scope skip taxonomy). Shared between the full run and
    --check-live-only, same as run_o9_assertions. Sum reconciliations and
    format checks only: no absolute counts are hardcoded, because the live
    sinks grow between a fail-branch and a pass-branch run."""
    from datetime import datetime, timedelta

    sk = data.get("skipped_records") or {}

    # ---- ASSERT-021: window bounds present, window_days == 30,
    # window_end == generated_at, bounds parseable and exactly 30 days
    # apart ----
    win = sk.get("window") or {}
    parse_ok = False
    delta_ok = False
    try:
        ws = datetime.strptime(win.get("window_start") or "", "%Y-%m-%dT%H:%M:%SZ")
        we = datetime.strptime(win.get("window_end") or "", "%Y-%m-%dT%H:%M:%SZ")
        parse_ok = True
        delta_ok = (we - ws) == timedelta(days=30)
    except (ValueError, TypeError):
        pass
    end_matches = win.get("window_end") == data.get("generated_at")
    ok21 = (win.get("window_days") == 30 and parse_ok and delta_ok and end_matches)
    record(
        "ASSERT-021",
        ok21,
        f"skipped_records.window = {win if win else 'MISSING'}; window_days == 30: "
        f"{win.get('window_days') == 30}; bounds parseable: {parse_ok}; exactly 30 "
        f"days apart: {delta_ok}; window_end == generated_at "
        f"({data.get('generated_at')}): {end_matches}",
    )

    # ---- ASSERT-022: enumeration fingerprint block: four sha256 hex
    # digests plus three positive set sizes ----
    fp = sk.get("enumeration_fingerprint") or {}
    hex_keys = ["hook_match_set_sha256", "agent_match_set_sha256",
                "skill_match_set_sha256", "combined_sha256"]
    size_keys = ["hook_match_set_size", "agent_match_set_size",
                 "skill_match_set_size"]
    bad_hex = [k for k in hex_keys
               if not (isinstance(fp.get(k), str)
                       and re.fullmatch(r"[0-9a-f]{64}", fp.get(k) or ""))]
    bad_size = [(k, fp.get(k)) for k in size_keys
                if not (isinstance(fp.get(k), int) and fp.get(k) > 0)]
    ok22 = not bad_hex and not bad_size
    record(
        "ASSERT-022",
        ok22,
        f"enumeration_fingerprint present: {bool(fp)}; non-hex64 digest keys: "
        f"{bad_hex or 'none'}; non-positive-int size keys: {bad_size or 'none'}; "
        f"sizes = {[(k, fp.get(k)) for k in size_keys]}",
    )

    # ---- ASSERT-023: per-scope taxonomy blocks, all-history AND windowed,
    # bucket sums equal to that scope's total skips; windowed
    # matched + skipped == total_in_scope ----
    problems: list[str] = []

    def _tax_sum(tax) -> int | None:
        if not isinstance(tax, dict):
            return None
        buckets = tax.get("buckets")
        if not isinstance(buckets, dict) or not buckets:
            return None
        try:
            return sum(int(b.get("count")) for b in buckets.values())
        except (TypeError, ValueError, AttributeError):
            return None

    ha = sk.get("hook_activity_jsonl") or {}
    gov = sk.get("governance_log_jsonl") or {}

    for label, tax, expected in [
        ("hook all-history", ha.get("skip_taxonomy_all_history"),
         ha.get("unparseable_or_unmatched")),
        ("gov-agent all-history", gov.get("agent_skip_taxonomy_all_history"),
         gov.get("unmatched_or_null_agent_type")),
        ("gov-skill all-history", gov.get("skill_skip_taxonomy_all_history"),
         gov.get("unmatched_skill_context_items")),
    ]:
        s = _tax_sum(tax)
        if s is None:
            problems.append(f"{label}: taxonomy block missing or malformed")
        elif s != expected or tax.get("total_skips") != expected:
            problems.append(
                f"{label}: bucket sum {s} / total_skips {tax.get('total_skips')} "
                f"!= scope skips {expected}")

    for label, wblock in [
        ("hook windowed", ha.get("windowed_30d")),
        ("gov-agent windowed", gov.get("agent_windowed_30d")),
        ("gov-skill windowed", gov.get("skill_windowed_30d")),
    ]:
        if not isinstance(wblock, dict):
            problems.append(f"{label}: windowed_30d block missing")
            continue
        s = _tax_sum(wblock.get("skip_taxonomy"))
        if s is None:
            problems.append(f"{label}: windowed taxonomy missing or malformed")
            continue
        if s != wblock.get("skipped"):
            problems.append(
                f"{label}: windowed bucket sum {s} != skipped {wblock.get('skipped')}")
        if ((wblock.get("matched") or 0) + (wblock.get("skipped") or 0)
                != wblock.get("total_in_scope")):
            problems.append(
                f"{label}: matched {wblock.get('matched')} + skipped "
                f"{wblock.get('skipped')} != total_in_scope "
                f"{wblock.get('total_in_scope')}")

    ok23 = not problems
    record(
        "ASSERT-023",
        ok23,
        "all six taxonomy blocks (3 scopes x all-history/windowed) reconcile: "
        "bucket sums equal scope skips and windowed matched+skipped equals "
        "total_in_scope" if ok23 else "; ".join(problems),
    )


# O14 (2026-09-01): tracked home of the per-scorecard-assembly twin
# snapshots. Duplicated as a literal (this suite never imports the
# generator or twin_snapshot.py -- same independence rule as every other
# assertion).
TWIN_SNAPSHOT_DIR = REPO_ROOT / "Projects" / "Agent-Governance-Research" / "work" / "twin-snapshots"
TWIN_SNAPSHOT_REL = "Projects/Agent-Governance-Research/work/twin-snapshots"


def run_o14_assertions(data: dict) -> None:
    """O14 (2026-09-01): ASSERT-024 -- the `twins` block (counts + sorted
    divergent (kind, name, path) rows + kind_set) is present and internally
    consistent with both `twin_summary` and a fresh per-row tally recomputed
    from data["rows"]. Shared between the full run and --check-live-only,
    same as run_o9_assertions."""
    twins = data.get("twins")
    if not isinstance(twins, dict):
        record("ASSERT-024", False,
               "`twins` block missing from asset-inventory.json (pre-O14 "
               "generator output, or the key was dropped)")
        return
    problems: list[str] = []
    counts = twins.get("counts")
    if counts != data.get("twin_summary"):
        problems.append(
            f"twins.counts {counts} != twin_summary {data.get('twin_summary')}")
    # Fresh per-row tally: stamp_twins() leaves twin_state None on rows
    # with no path (the summary's "no-path" bucket), so None maps there.
    tally: dict = {"identical": 0, "divergent": 0, "repo-absent": 0,
                   "ambiguous": 0, "no-path": 0, "not-applicable": 0}
    for r in data.get("rows", []):
        key = r.get("twin_state") or "no-path"
        tally[key] = tally.get(key, 0) + 1
    if counts != tally:
        problems.append(f"twins.counts {counts} != fresh per-row tally {tally}")
    div = twins.get("divergent")
    if not isinstance(div, list):
        problems.append(f"twins.divergent is {type(div).__name__}, not a list")
        div = []
    if isinstance(counts, dict) and len(div) != counts.get("divergent"):
        problems.append(
            f"len(divergent) {len(div)} != counts['divergent'] "
            f"{counts.get('divergent')}")
    triples = [(d.get("kind"), d.get("name"), d.get("path")) for d in div]
    if triples != sorted(triples):
        problems.append("divergent list is not sorted by (kind, name, path)")
    fresh_kinds = sorted({r.get("kind") for r in data.get("rows", [])})
    if twins.get("kind_set") != fresh_kinds:
        problems.append(
            f"kind_set {twins.get('kind_set')} != fresh per-row kind set "
            f"{fresh_kinds}")
    ok24 = not problems
    record(
        "ASSERT-024",
        ok24,
        "twins block internally consistent: counts == twin_summary == fresh "
        f"per-row tally; {len(div)} divergent row(s) sorted by "
        "(kind, name, path); kind_set matches rows"
        if ok24 else "; ".join(problems),
    )


def run_o14_git_assertions() -> None:
    """O14 (2026-09-01): ASSERT-025 -- permanent git-integrity guard on the
    twin-snapshot directory (spec risk flag 2: if the tracked path is ever
    gitignored later, the whole objective silently dies, so the `git
    ls-files` assertion stays in the selftest permanently). Reads git
    state, not the data dict, so it runs unchanged in both full mode and
    --check-live-only."""
    if not TWIN_SNAPSHOT_DIR.is_dir():
        record("ASSERT-025", False,
               f"snapshot dir {TWIN_SNAPSHOT_REL} does not exist")
        return
    problems: list[str] = []
    ign = subprocess.run(["git", "check-ignore", "-q", TWIN_SNAPSHOT_REL],
                         cwd=REPO_ROOT, capture_output=True, text=True)
    if ign.returncode == 0:
        problems.append(
            f"{TWIN_SNAPSHOT_REL} is gitignored (git check-ignore matched)")
    ls = subprocess.run(["git", "ls-files", "--", TWIN_SNAPSHOT_REL],
                        cwd=REPO_ROOT, capture_output=True, text=True)
    listed = {p.strip().replace("\\", "/") for p in ls.stdout.splitlines()
              if p.strip()}
    snapshots = sorted(TWIN_SNAPSHOT_DIR.glob("*.json"))
    if not snapshots:
        problems.append(f"{TWIN_SNAPSHOT_REL} exists but holds no *.json snapshot")

    def written_at(p) -> str:
        try:
            return (json.loads(p.read_bytes().decode("utf-8"))
                    .get("snapshot_written_at") or "")
        except (OSError, ValueError):
            return ""

    newest_listed = max((written_at(p) for p in snapshots
                         if f"{TWIN_SNAPSHOT_REL}/{p.name}" in listed),
                        default="")
    for p in snapshots:
        rel = f"{TWIN_SNAPSHOT_REL}/{p.name}"
        if rel in listed:
            continue  # git ls-files lists staged and committed alike
        f_ign = subprocess.run(["git", "check-ignore", "-q", rel],
                               cwd=REPO_ROOT, capture_output=True, text=True)
        if f_ign.returncode == 0:
            problems.append(f"snapshot {rel} is gitignored")
        elif written_at(p) > newest_listed:
            # Pre-first-commit grace window: untracked-but-not-ignored is
            # tolerated only for a snapshot newer than the newest listed one.
            continue
        else:
            problems.append(
                f"snapshot {rel} is untracked and not newer than the newest "
                f"git-listed snapshot ({newest_listed or 'none listed'})")
    ok25 = not problems
    record(
        "ASSERT-025",
        ok25,
        f"snapshot dir {TWIN_SNAPSHOT_REL} exists, not gitignored; "
        f"{len(snapshots)} snapshot(s), each git-listed (staged or "
        "committed) or within the pre-first-commit grace window"
        if ok25 else "; ".join(problems),
    )


def check_live_only() -> int:
    """--check-live-only: parse the on-disk asset-inventory.json and run
    ASSERT-016..019 plus the O13 ASSERT-021..023 against it, without invoking the generator. This
    is the fail-branch demonstration mode: a full selftest run regenerates
    and would overwrite the very JSON whose pre-change state the fail
    branch must be shown against."""
    print("=== asset_inventory self-test: O9 --check-live-only mode ===")
    print(f"data file: {DATA_FILE}")
    if not DATA_FILE.exists():
        record("SETUP", False, f"{DATA_FILE} does not exist; nothing to check")
        print_summary()
        return 1
    data = json.loads(DATA_FILE.read_bytes().decode("utf-8"))
    print(f"run_id: {data.get('run_id')}")
    print()
    run_o9_assertions(data)
    run_o13_assertions(data)
    run_o14_assertions(data)
    run_o14_git_assertions()
    print()
    print_summary()
    return 0 if all(ok for _, ok, _ in RESULTS) else 1


def main() -> int:
    print("=== asset_inventory self-test ===")
    print(f"generator: {GENERATOR}")
    print(f"sinks: {HOOK_ACTIVITY_JSONL} , {GOVERNANCE_LOG_JSONL}")
    print()

    # ---- ASSERT-006 setup: stat + hash the pre-run prefix of both sinks.
    # hook-activity.jsonl / governance-log.jsonl are append-only shared logs
    # that every hook in every concurrently running session appends to, so
    # asserting the files are byte-for-byte unchanged across the run tests
    # immutability -- the wrong property. It fails at random on a busy
    # machine whenever another session appends mid-run, and even a clean
    # pass on a quiet machine would not prove what the assertion claims
    # (that the generator itself never writes to either sink). What the
    # generator can actually promise, and what this checks, is
    # non-authorship: it never truncates or rewrites bytes that already
    # existed. Growth past the pre-run size is expected from concurrent
    # sessions and is tolerated, not treated as a failure.
    pre_hook_stat = stat_sink(HOOK_ACTIVITY_JSONL)
    pre_gov_stat = stat_sink(GOVERNANCE_LOG_JSONL)
    pre_hook_size = pre_hook_stat[0]
    pre_gov_size = pre_gov_stat[0]
    pre_hook_prefix_hash = hash_prefix(HOOK_ACTIVITY_JSONL, pre_hook_size)
    pre_gov_prefix_hash = hash_prefix(GOVERNANCE_LOG_JSONL, pre_gov_size)

    proc1 = run_generator(run_id="selftest-run-1")
    if proc1.returncode != 0:
        record("SETUP", False, f"generator run 1 failed rc={proc1.returncode}: {proc1.stderr[-800:]}")
        print_summary()
        return 1

    post_hook_stat = stat_sink(HOOK_ACTIVITY_JSONL)
    post_gov_stat = stat_sink(GOVERNANCE_LOG_JSONL)
    post_hook_size = post_hook_stat[0]
    post_gov_size = post_gov_stat[0]
    # Re-hash only the first pre_hook_size / pre_gov_size bytes of the
    # post-run file -- the region that existed before the run and is the
    # only region the generator had any business touching.
    post_hook_prefix_hash = hash_prefix(HOOK_ACTIVITY_JSONL, pre_hook_size)
    post_gov_prefix_hash = hash_prefix(GOVERNANCE_LOG_JSONL, pre_gov_size)

    hook_not_shrunk = post_hook_size >= pre_hook_size
    gov_not_shrunk = post_gov_size >= pre_gov_size
    hook_prefix_stable = post_hook_prefix_hash == pre_hook_prefix_hash
    gov_prefix_stable = post_gov_prefix_hash == pre_gov_prefix_hash
    ok6 = hook_not_shrunk and gov_not_shrunk and hook_prefix_stable and gov_prefix_stable
    record(
        "ASSERT-006",
        ok6,
        f"non-authorship, not immutability -- growth past the pre-run size is expected from "
        f"concurrent sessions and is not a failure: hook-activity.jsonl size before={pre_hook_size} "
        f"after={post_hook_size} (not_shrunk={hook_not_shrunk}), prefix sha256 unchanged="
        f"{hook_prefix_stable}; governance-log.jsonl size before={pre_gov_size} after={post_gov_size} "
        f"(not_shrunk={gov_not_shrunk}), prefix sha256 unchanged={gov_prefix_stable}",
    )

    data1 = json.loads((AGGREGATES_DIR / "asset-inventory.json").read_bytes().decode("utf-8"))
    rows1 = data1["rows"]

    # ---- ASSERT-001 ----
    # Scoped to LOCAL hook rows only (provenance == 'authored-in-harness')
    # since 2026-08-20: kind=hook now also carries plugin-sourced rows
    # (provenance starts 'plugin:'), and fresh_hook_py_stems() -- by
    # design, unchanged -- only ever counted THIS repo's own
    # .claude/hooks/*.py files. Comparing the full (local + plugin) row
    # count against a local-only fresh count would be an apples-to-oranges
    # break of this assertion's own intent; ASSERT-010/011 are the
    # plugin-scoped equivalent checks.
    fresh_non_test, fresh_test = fresh_hook_py_stems()
    hook_rows = [r for r in rows1 if r["kind"] == "hook"]
    local_hook_rows = [r for r in hook_rows if r["provenance"] == "authored-in-harness"]
    generator_hook_row_count = len(local_hook_rows)
    generator_excluded = data1["excluded_test_scaffolding_count"]
    fresh_total = len(fresh_non_test) + len(fresh_test)
    ok1 = (generator_hook_row_count + generator_excluded) == fresh_total
    record(
        "ASSERT-001",
        ok1,
        f"generator hook_rows={generator_hook_row_count} + excluded={generator_excluded} "
        f"= {generator_hook_row_count + generator_excluded}; fresh os.listdir .py count = {fresh_total}",
    )

    # ---- ASSERT-002 ----
    fresh_hook_lines = fresh_hook_activity_line_count()
    hook_usage_sum = sum(r["usage"]["total_count"] for r in hook_rows)
    hook_skipped = data1["skipped_records"]["hook_activity_jsonl"]["unparseable_or_unmatched"]
    ok2 = (hook_usage_sum + hook_skipped) == fresh_hook_lines
    record(
        "ASSERT-002",
        ok2,
        f"sum(hook usage.total_count)={hook_usage_sum} + skipped_records={hook_skipped} "
        f"= {hook_usage_sum + hook_skipped}; fresh hook-activity.jsonl line count = {fresh_hook_lines}",
    )

    # ---- ASSERT-003 ----
    fresh_agent_dispatched = fresh_agent_dispatched_count()
    agent_rows = [r for r in rows1 if r["kind"] == "agent"]
    agent_usage_sum = sum(r["usage"]["total_count"] for r in agent_rows)
    agent_skipped = data1["skipped_records"]["governance_log_jsonl"]["unmatched_or_null_agent_type"]
    ok3 = (agent_usage_sum + agent_skipped) == fresh_agent_dispatched
    record(
        "ASSERT-003",
        ok3,
        f"sum(agent usage.total_count)={agent_usage_sum} + skipped_records={agent_skipped} "
        f"= {agent_usage_sum + agent_skipped}; fresh agent_dispatched record count = {fresh_agent_dispatched}",
    )

    # ---- ASSERT-004 ----
    missing = []
    checked = 0
    for r in rows1:
        for ev in r["reachability"]:
            checked += 1
            p = REPO_ROOT / ev["source_file"]
            if not p.exists():
                missing.append((r["kind"], r["name"], ev["source_file"]))
    ok4 = len(missing) == 0
    record(
        "ASSERT-004",
        ok4,
        f"checked {checked} reachability evidence source_file paths; missing={missing[:10]}"
        if missing else f"checked {checked} reachability evidence source_file paths; all exist on disk",
    )

    # ---- ASSERT-005 ----
    # CON-003's promise ("two runs over an UNCHANGED harness") has a
    # precondition this self-test cannot force in a live, multi-session
    # vault: hook-activity.jsonl / governance-log.jsonl can grow from
    # concurrent session activity between the two sub-runs below. Retry a
    # bounded number of times to catch a quiet window; if every attempt
    # sees the sinks change, fall back to a structural-only comparison
    # (every field except usage counts/timestamps, which are the only
    # fields a genuine concurrent write can legitimately move) so a live
    # sink write is reported as environmental, not misreported as a defect.
    ok5 = False
    detail5 = ""
    baseline_stat = (post_hook_stat, post_gov_stat)  # sink state as of run 1 (ASSERT-006 already
    # confirmed run 1 itself does not move it); this is the correct comparison anchor for "did
    # anything change between run 1 and run 2", not just "did run 2's own narrow window move it".
    for attempt in range(1, 4):
        pre = (stat_sink(HOOK_ACTIVITY_JSONL), stat_sink(GOVERNANCE_LOG_JSONL))
        proc2 = run_generator(run_id=f"selftest-run-2-attempt{attempt}")
        post = (stat_sink(HOOK_ACTIVITY_JSONL), stat_sink(GOVERNANCE_LOG_JSONL))
        if proc2.returncode != 0:
            ok5, detail5 = False, f"generator run 2 failed rc={proc2.returncode}: {proc2.stderr[-800:]}"
            break
        data2 = json.loads((AGGREGATES_DIR / "asset-inventory.json").read_bytes().decode("utf-8"))
        s1 = json.dumps(strip_volatile(data1), sort_keys=True)
        s2 = json.dumps(strip_volatile(data2), sort_keys=True)
        if s1 == s2:
            ok5 = True
            detail5 = (f"two consecutive generator runs produced byte-identical data apart from "
                       f"run_id/generated_at/diff (attempt {attempt}/3, sinks static since run 1)")
            break
        sinks_changed = (pre != baseline_stat) or (pre != post)
        if sinks_changed and attempt < 3:
            baseline_stat = post  # re-anchor for the next attempt
            continue  # retry: concurrent write landed between run 1 and this attempt, not a generator defect
        struct1 = strip_usage(strip_volatile(data1))
        struct2 = strip_usage(strip_volatile(data2))
        structurally_identical = json.dumps(struct1, sort_keys=True) == json.dumps(struct2, sort_keys=True)
        ok5 = sinks_changed and structurally_identical
        detail5 = (
            f"sinks changed between run 1 and this sub-run on all {attempt} attempt(s) (concurrent "
            f"session activity; run1_baseline={baseline_stat} pre={pre} post={post}); structural "
            f"fields (name/kind/path/provenance/reachability/blocked_reason/edges) "
            f"identical={structurally_identical}, so divergence is confined to usage counts/timestamps, "
            f"the expected effect of a live-growing sink, not a defect"
            if sinks_changed else
            "stripped outputs diverged between run 1 and run 2 with sinks reporting static throughout "
            "(size/mtime unchanged since run 1) -- this would be a genuine non-determinism defect"
        )

    record("ASSERT-005", ok5, detail5)

    # ---- ASSERT-007: negative-fixture regression test (TASK-022) ----
    fixture_dir = SCRIPT_DIR / "_selftest_fixtures"
    try:
        ok7, detail7 = run_negative_fixture_test(fixture_dir)
        record("ASSERT-007", ok7, detail7)
    finally:
        # This build adds new files only; the fixture scaffolding is
        # self-test-owned scratch state, so it is removed at the end of
        # every run rather than left as an untracked artifact.
        if fixture_dir.exists():
            shutil.rmtree(fixture_dir, ignore_errors=True)

    # ---- ASSERT-008 (added 2026-08-19, build-review class guard for
    # FIX 1): every reachability evidence type actually wired into at
    # least one row's `reachability` list must produce at least one
    # resolved (compiled) edge somewhere in the output. Re-derived
    # directly from data1's own rows -- reachability items and edges are
    # two separate parts of the row model, so an evidence type present in
    # reachability with zero matching `edges[].source` values means the
    # edges compiler has no branch for it (exactly the class of defect
    # that shipped for EVD-001 before FIX 1: 76 hook rows carried EVD-001
    # reachability and zero of them produced a resolved edge). ----
    wired_evd_types = set()
    for r in rows1:
        for ev in r["reachability"]:
            wired_evd_types.add(ev["type"])
    resolved_edge_sources = set()
    for r in rows1:
        for e in r["edges"]:
            if e["status"] == "resolved":
                resolved_edge_sources.add(e["source"])
    dead_evidence_sources = sorted(wired_evd_types - resolved_edge_sources)
    ok8 = len(dead_evidence_sources) == 0
    record(
        "ASSERT-008",
        ok8,
        f"wired reachability evidence types={sorted(wired_evd_types)}; "
        f"resolved edge sources={sorted(resolved_edge_sources)}; "
        f"evidence types with zero resolved edges={dead_evidence_sources}",
    )

    # ---- ASSERT-009 (added 2026-08-19, build-review class guard for
    # FIX 2): every hook row assigned BLK-001 genuinely has no invocation
    # path, including an import-based one. Re-derived fully independently
    # of the generator's own reachability/edges output: a fresh glob of
    # every hook file (top-level + retired), a fresh read of both
    # settings files, and a fresh regex scan for "from/import <stem>" in
    # every OTHER hook file's source, so this would have failed on the
    # pre-fix generator (which never checked imports and mislabeled
    # _irreversible_surface.py and 11 other genuinely-imported modules as
    # BLK-001). ----
    fresh_hook_files = fresh_all_hook_files()
    fresh_hook_texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in fresh_hook_files}
    fresh_registered = {p.name for p in fresh_hook_files if fresh_settings_registers(p.name)}

    blk001_hook_rows = [r for r in rows1 if r["kind"] == "hook" and "BLK-001" in r["blocked_reason"]]
    false_positives = []
    for r in blk001_hook_rows:
        target_stem = r["name"]
        target_py_stem = target_stem.replace("-", "_")
        for other_path, other_text in fresh_hook_texts.items():
            if other_path.stem == target_stem:
                continue
            if other_path.name not in fresh_registered:
                continue
            if fresh_imports(other_text, target_py_stem):
                false_positives.append((target_stem, other_path.name))
                break
    ok9 = len(false_positives) == 0
    record(
        "ASSERT-009",
        ok9,
        f"checked {len(blk001_hook_rows)} BLK-001 hook rows against a fresh import scan of "
        f"{len(fresh_hook_files)} hook files (top-level + retired) and fresh settings-file "
        f"registration; rows with a genuine but unrecognized import-based invocation path="
        f"{false_positives}" if false_positives else
        f"checked {len(blk001_hook_rows)} BLK-001 hook rows against a fresh import scan of "
        f"{len(fresh_hook_files)} hook files (top-level + retired) and fresh settings-file "
        f"registration; none have a genuine invocation path (import-based or settings-registered)",
    )

    # ---- ASSERT-010 (added 2026-08-20, plugin-cache extension): the
    # generator's plugin-sourced, cache-walk-backed row count (provenance
    # starts 'plugin:' AND path is not null -- excluding the separate
    # BLK-004 population, which is sourced from registry.json, not the
    # cache walk) reconciles against a FRESH, independently-written walk of
    # the same plugin cache (fresh_plugin_row_expectations(), which shares
    # no code with asset_inventory.py). Absent cache degrades to N/A, not a
    # failure -- matches the generator's own graceful-degradation rule. ----
    plugin_fresh = fresh_plugin_row_expectations()
    if plugin_fresh is None:
        record("ASSERT-010", True,
               "plugin cache absent on this machine; skipped as N/A (not a failure) -- matches "
               "the generator's own PLUGIN_CACHE_ABSENT graceful-degradation note")
    else:
        plugin_rows = [r for r in rows1 if r["provenance"].startswith("plugin:") and r["path"] is not None]
        generator_plugin_row_count = len(plugin_rows)
        fresh_total = (plugin_fresh["skill_count"] + plugin_fresh["agent_count"]
                       + plugin_fresh["hook_entry_count"] + plugin_fresh["mcp_server_count"])
        ok10 = generator_plugin_row_count == fresh_total
        record(
            "ASSERT-010",
            ok10,
            f"generator plugin-sourced, cache-walk-backed rows = {generator_plugin_row_count} "
            f"(skill={sum(1 for r in plugin_rows if r['kind'] == 'skill')}, "
            f"agent={sum(1 for r in plugin_rows if r['kind'] == 'agent')}, "
            f"hook={sum(1 for r in plugin_rows if r['kind'] == 'hook')}, "
            f"mcp-server={sum(1 for r in plugin_rows if r['kind'] == 'mcp-server')}); "
            f"fresh independent walk = {fresh_total} (skill={plugin_fresh['skill_count']}, "
            f"agent={plugin_fresh['agent_count']}, hook_entries={plugin_fresh['hook_entry_count']}, "
            f"mcp_server={plugin_fresh['mcp_server_count']})",
        )

    # ---- ASSERT-011 (added 2026-08-20): at least one plugin-supplied hook
    # appears as a row -- the gap the brief measured directly (zero rows
    # ever pointed into the plugin cache before this build). ----
    plugin_hook_rows = [r for r in rows1 if r["kind"] == "hook" and r["provenance"].startswith("plugin:")]
    ok11 = len(plugin_hook_rows) >= 1
    record(
        "ASSERT-011",
        ok11,
        f"plugin-supplied hook rows present = {len(plugin_hook_rows)} (e.g. "
        f"{plugin_hook_rows[0]['name']!r})" if plugin_hook_rows else
        "zero plugin-supplied hook rows found -- expected at least one (this machine has 6 "
        "plugins shipping hooks/hooks.json)",
    )

    # ---- ASSERT-012 (added 2026-08-20): BLK-004 fires when its precondition
    # is genuinely met, proven the same way ASSERT-007/TASK-022 proves the
    # field-contract abort -- a synthetic fixture, not a claim. Builds a
    # temporary registry.json copy with one extra plugin-sourced agent name
    # guaranteed to match no real file in the live plugin cache, points a
    # fresh generator run at it via --registry-path, and confirms that row
    # comes back with blocked_reason == ['BLK-004'] and path == null. ----
    try:
        ok12, detail12 = run_blk004_fixture_test(SCRIPT_DIR / "_selftest_fixtures_blk004")
        record("ASSERT-012", ok12, detail12)
    finally:
        fixture_dir = SCRIPT_DIR / "_selftest_fixtures_blk004"
        if fixture_dir.exists():
            shutil.rmtree(fixture_dir, ignore_errors=True)

    # ---- ASSERT-013 (added 2026-08-30, O1): the generator's own
    # settings-registration row count reconciles against a FRESH,
    # independently-written read of settings.json + settings.local.json +
    # .mcp.json (fresh_settings_registration_count(), sharing no code with
    # asset_inventory.py). ----
    sr_rows = [r for r in rows1 if r["kind"] == "settings-registration"]
    fresh_sr_count = fresh_settings_registration_count()
    ok13 = len(sr_rows) == fresh_sr_count
    record(
        "ASSERT-013",
        ok13,
        f"generator settings-registration rows = {len(sr_rows)}; fresh independent count "
        f"(settings.json + settings.local.json hook entries + .mcp.json server entries) = "
        f"{fresh_sr_count}",
    )

    # ---- ASSERT-014 (added 2026-08-30, O1): the generator's own
    # telemetry-sink row count reconciles against a FRESH, independently-
    # written union of the two hardcoded default sinks plus every sink name
    # declared in telemetry-vocabulary.json (fresh_telemetry_sink_count(),
    # sharing no code with asset_inventory.py). ----
    ts_rows = [r for r in rows1 if r["kind"] == "telemetry-sink"]
    fresh_ts_count = fresh_telemetry_sink_count()
    ok14 = len(ts_rows) == fresh_ts_count
    record(
        "ASSERT-014",
        ok14,
        f"generator telemetry-sink rows = {len(ts_rows)}; fresh independent count (2 hardcoded "
        f"default sinks union telemetry-vocabulary.json's declared sinks) = {fresh_ts_count}",
    )

    # ---- ASSERT-015 (added 2026-08-30, O1 security constraint): none of
    # .mcp.json's secret-bearing env/header values land anywhere in the
    # generated asset-inventory.json output. Checks the WHOLE output file
    # text, not just settings-registration rows, as defense in depth.
    # Never prints a secret value itself, only counts. ----
    mcp_secret_values = fresh_mcp_secret_values()
    output_text = (AGGREGATES_DIR / "asset-inventory.json").read_text(encoding="utf-8")
    leaked = [s for s in mcp_secret_values if s in output_text]
    ok15 = len(leaked) == 0
    record(
        "ASSERT-015",
        ok15,
        f"checked {len(mcp_secret_values)} .mcp.json env/header secret-bearing value(s) against "
        f"the full generated asset-inventory.json text; leaked = {len(leaked)}"
        if not leaked else
        f"SECRET LEAK: {len(leaked)} of {len(mcp_secret_values)} .mcp.json secret-bearing "
        f"env/header value(s) found verbatim in asset-inventory.json output",
    )

    # ---- ASSERT-016..019 (added 2026-09-01, O9 increment 1): run against
    # data1, the fresh regeneration from run 1 above. The same four
    # assertions run standalone against the on-disk JSON via
    # --check-live-only (fail-branch demonstration without regenerating).
    run_o9_assertions(data1)
    run_o13_assertions(data1)
    # ---- ASSERT-024/025 (added 2026-09-01, O14): twins-block consistency
    # plus the permanent snapshot-dir git-integrity guard. ----
    run_o14_assertions(data1)
    run_o14_git_assertions()

    # ---- ASSERT-020 (added 2026-09-01, O9 increment 2): fixture proof of
    # BOTH workflow-attribution branches without waiting on live timing.
    # The synthetic governance log lives in a tempfile.mkdtemp() directory
    # ONLY (hard requirement: no test or fixture ever writes the live log),
    # unlike ASSERT-012's SCRIPT_DIR fixture. ----
    wf_fixture_dir = Path(tempfile.mkdtemp(prefix="selftest_o9_workflow_"))
    try:
        ok20, detail20 = run_workflow_fixture_test(wf_fixture_dir)
        record("ASSERT-020", ok20, detail20)
    finally:
        shutil.rmtree(wf_fixture_dir, ignore_errors=True)

    print()
    print_summary()
    return 0 if all(ok for _, ok, _ in RESULTS) else 1


def run_workflow_fixture_test(fixture_dir: Path) -> tuple[bool, str]:
    """ASSERT-020 (O9 increment 2): a 3-line synthetic governance log --
    one agent_dispatched record (satisfies the generator's field-contract
    gate), one identified workflow pass ("workflow": "process-qa"), one
    legacy pass with no workflow field -- fed to a fresh generator run
    whose --governance-log-path and --aggregates-dir both point INSIDE
    fixture_dir (a tempfile.mkdtemp() dir; the live log and live
    aggregates are never touched). Proves the attributed branch (process-qa
    row: WORKFLOW_USAGE_SOURCE, count 1), the sentinel branch (the other 6
    rows: AWAITING_FIRST_OBSERVATION, count 0), and the legacy counter
    (header workflow_pass_unattributed == 1) in one run."""
    fixture_dir.mkdir(parents=True, exist_ok=True)
    gov_fixture = fixture_dir / "governance-log-workflow-fixture.jsonl"
    recs = [
        {"ts": "2026-09-01 10:00:00", "schema": 2, "event": "agent_dispatched",
         "hook": "governance-log", "session": "selftest-o9-fixture",
         "agent_type": "general-purpose"},
        {"ts": "2026-09-01 10:01:00", "schema": 2, "event": "pass",
         "hook": "subagent-quality-check", "session": "selftest-o9-fixture",
         "agent_type": "workflow-subagent", "agent_id": "fixture-id-1",
         "message_len": 42, "workflow": "process-qa",
         "workflow_run": "wf_fixture-001"},
        {"ts": "2026-09-01 10:02:00", "schema": 2, "event": "pass",
         "hook": "subagent-quality-check", "session": "selftest-o9-fixture",
         "agent_type": "workflow-subagent", "agent_id": "fixture-id-2",
         "message_len": 42},
    ]
    with open(gov_fixture, "wb") as fh:
        for r in recs:
            fh.write((json.dumps(r, ensure_ascii=False) + "\n").encode("utf-8"))

    fixture_aggregates = fixture_dir / "aggregates"
    fixture_aggregates.mkdir(parents=True, exist_ok=True)
    proc = run_generator(aggregates_dir=fixture_aggregates,
                         governance_log_path=gov_fixture)
    out_file = fixture_aggregates / "asset-inventory.json"
    if proc.returncode != 0 or not out_file.exists():
        return False, (f"generator failed on the workflow fixture: rc={proc.returncode} "
                        f"stderr={proc.stderr[-400:]}")
    data = json.loads(out_file.read_bytes().decode("utf-8"))
    wf_rows = {r["name"]: r for r in data["rows"] if r["kind"] == "workflow"}
    qa = wf_rows.get("process-qa")
    qa_ok = (qa is not None
             and qa["usage"]["source"] == WORKFLOW_USAGE_SOURCE
             and qa["usage"]["total_count"] == 1)
    others = {n: r for n, r in wf_rows.items() if n != "process-qa"}
    sentinel_ok = (len(others) == 6 and all(
        r["usage"]["source"] == WORKFLOW_SENTINEL and r["usage"]["total_count"] == 0
        for r in others.values()))
    gov_header = data["skipped_records"]["governance_log_jsonl"]
    unattributed = gov_header.get("workflow_pass_unattributed")
    header_ok = unattributed == 1
    ok = qa_ok and sentinel_ok and header_ok
    qa_usage = qa["usage"] if qa else None
    return ok, (f"fixture log at {gov_fixture} (3 records: 1 identified pass, 1 legacy "
                 f"pass, 1 agent_dispatched contract-keeper); process-qa row attributed "
                 f"with count 1 = {qa_ok} (usage={qa_usage}); other 6 rows on "
                 f"'{WORKFLOW_SENTINEL}' with count 0 = {sentinel_ok}; header "
                 f"workflow_pass_unattributed = {unattributed} (expected 1)")


def run_blk004_fixture_test(fixture_dir: Path) -> tuple[bool, str]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    real_registry_path = CLAUDE_DIR / "registry.json"
    registry = json.loads(real_registry_path.read_bytes().decode("utf-8"))

    sentinel_name = "selftest-blk004-sentinel-agent-does-not-exist-on-disk"
    registry.setdefault("agents", {})[sentinel_name] = {
        "name": sentinel_name,
        "description": "ASSERT-012 fixture only -- not a real agent.",
        "keywords": [],
        "tools": [],
        "source": "plugin:selftest-fixture-marketplace",
    }
    fixture_registry_path = fixture_dir / "registry-with-blk004-sentinel.json"
    with open(fixture_registry_path, "wb") as fh:
        fh.write(json.dumps(registry, ensure_ascii=False).encode("utf-8"))

    fixture_aggregates_dir = fixture_dir / "aggregates_out"
    fixture_aggregates_dir.mkdir(parents=True, exist_ok=True)

    proc = run_generator(
        aggregates_dir=fixture_aggregates_dir,
        governance_log_path=GOVERNANCE_LOG_JSONL,
        hook_activity_path=HOOK_ACTIVITY_JSONL,
        registry_path=fixture_registry_path,
        run_id="selftest-blk004-fixture",
    )
    if proc.returncode != 0:
        return False, f"generator run against the BLK-004 fixture registry failed rc={proc.returncode}: {proc.stderr[-500:]}"

    fixture_data_file = fixture_aggregates_dir / "asset-inventory.json"
    if not fixture_data_file.exists():
        return False, "generator did not write output against the BLK-004 fixture registry"

    fdata = json.loads(fixture_data_file.read_bytes().decode("utf-8"))
    matches = [r for r in fdata["rows"] if r["kind"] == "agent" and r["name"] == sentinel_name]
    if not matches:
        return False, (f"sentinel agent '{sentinel_name}' (source=plugin:..., no matching file "
                        f"anywhere in the live plugin cache) produced NO row at all -- BLK-004's "
                        f"registry-vs-cache diff did not run")
    row = matches[0]
    ok = (row["blocked_reason"] == ["BLK-004"] and row["path"] is None
          and row["provenance"] == "plugin:selftest-fixture-marketplace")
    return ok, (f"sentinel agent row: path={row['path']!r}, provenance={row['provenance']!r}, "
                f"blocked_reason={row['blocked_reason']!r} (expected path=None, "
                f"provenance='plugin:selftest-fixture-marketplace', blocked_reason=['BLK-004'])")


def run_negative_fixture_test(fixture_dir: Path) -> tuple[bool, str]:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixture_gov_log = fixture_dir / "governance-log-zero-agent-type.jsonl"

    # Deliberately field-stripped fixture: agent_dispatched records present,
    # but every agent_type value is null -- the exact defect class from
    # hook_activity_report.py line 301 (a depended-on field silently absent
    # from every record of a type the code reads).
    fixture_lines = [
        {"ts": "2026-01-01 00:00:00", "event": "agent_dispatched", "agent_type": None, "skill_context": []},
        {"ts": "2026-01-01 00:00:01", "event": "agent_dispatched", "agent_type": None, "skill_context": ["pm"]},
        {"ts": "2026-01-01 00:00:02", "event": "session_start"},
    ]
    with open(fixture_gov_log, "wb") as fh:
        for rec in fixture_lines:
            fh.write(json.dumps(rec).encode("utf-8"))
            fh.write(b"\n")

    fixture_aggregates_dir = fixture_dir / "aggregates_out"
    if fixture_aggregates_dir.exists():
        for p in fixture_aggregates_dir.rglob("*"):
            if p.is_file():
                p.unlink()
    fixture_aggregates_dir.mkdir(parents=True, exist_ok=True)

    proc = run_generator(
        aggregates_dir=fixture_aggregates_dir,
        governance_log_path=fixture_gov_log,
        hook_activity_path=HOOK_ACTIVITY_JSONL,
        run_id="selftest-negative-fixture",
    )

    aborted_correctly = (proc.returncode != 0) and ("FIELD_CONTRACT_ABORT" in proc.stderr) and \
        ("agent_type" in proc.stderr)
    no_output_written = not (fixture_aggregates_dir / "asset-inventory.json").exists()

    if not aborted_correctly:
        return False, (f"expected non-zero exit with FIELD_CONTRACT_ABORT naming 'agent_type'; "
                        f"got rc={proc.returncode} stderr={proc.stderr[-500:]}")
    if not no_output_written:
        return False, "generator wrote output files despite the field-contract abort"

    # Second half of TASK-022: confirm the real sinks still pass normally.
    proc_real = run_generator(
        aggregates_dir=fixture_aggregates_dir,
        governance_log_path=GOVERNANCE_LOG_JSONL,
        hook_activity_path=HOOK_ACTIVITY_JSONL,
        run_id="selftest-negative-fixture-control",
    )
    real_ok = proc_real.returncode == 0 and (fixture_aggregates_dir / "asset-inventory.json").exists()
    if not real_ok:
        return False, (f"fixture aborted correctly, but the control run against the real sinks "
                        f"did not complete normally: rc={proc_real.returncode} stderr={proc_real.stderr[-500:]}")

    return True, ("fixture (zero non-null agent_type across all agent_dispatched records) aborted with "
                   "FIELD_CONTRACT_ABORT, wrote no output; control run against real sinks completed normally")


def print_summary() -> None:
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== {passed}/{total} assertions passed ===")


if __name__ == "__main__":
    if "--check-live-only" in sys.argv[1:]:
        raise SystemExit(check_live_only())
    raise SystemExit(main())
