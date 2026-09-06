#!/usr/bin/env python
"""asset_inventory.py -- deterministic asset inventory generator for the .claude harness.

Emits one row per harness asset (hook, skill, agent, workflow, command,
mcp-server, settings-registration, telemetry-sink -- the latter two added
2026-08-30, O1) carrying identity, provenance, source-cited reachability
evidence, a closed-set blocked reason when applicable, sink-audited usage,
and compiled edges to other assets. Read-only against every input file it
consults; the only writes are its own output files under
.claude/hooks/aggregates/. SECURITY: settings-registration rows read
.mcp.json but only ever emit structural fields (server name, command,
transport type, env variable KEY NAMES) -- never an env value, header
value, url, or any other secret.

Build plan: Projects/Agent-Governance-Research/work/2026-08-19-asset-inventory-build-plan.md
Companion doc: .claude/scripts/asset-inventory-guide.md

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude\\scripts\\asset_inventory.py

Python 3.14, standard library only, no network access, Windows target.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Paths (all derived from this file's own location, so the script is
# relocatable together with the repo it inspects).
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve()
# Layout adaptation (published copy): the harness root comes from VAULT_DIR,
# because this repo keeps scripts/ at its top level rather than under .claude/.
REPO_ROOT = Path(os.environ.get("VAULT_DIR", "C:/Users/exampleuser/Workspace"))
CLAUDE_DIR = REPO_ROOT / ".claude"

HOOKS_DIR = CLAUDE_DIR / "hooks"
SKILLS_DIR = CLAUDE_DIR / "skills"
AGENTS_DIR = CLAUDE_DIR / "agents"
WORKFLOWS_DIR = CLAUDE_DIR / "workflows"
SETTINGS_JSON = CLAUDE_DIR / "settings.json"
SETTINGS_LOCAL_JSON = CLAUDE_DIR / "settings.local.json"
REGISTRY_JSON = CLAUDE_DIR / "registry.json"
MCP_JSON = REPO_ROOT / ".mcp.json"
COMMANDS_DIR = CLAUDE_DIR / "commands"
ROOT_CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

HOOK_ACTIVITY_JSONL_DEFAULT = HOOKS_DIR / "hook-activity.jsonl"
GOVERNANCE_LOG_JSONL_DEFAULT = HOOKS_DIR / "governance-log.jsonl"

# Fifth enumeration root (2026-08-20 extension), OUTSIDE the vault repo and
# outside its git repository, at the user profile's plugin cache. Unlike
# HOOKS_DIR/SKILLS_DIR/AGENTS_DIR/WORKFLOWS_DIR (which abort loudly via
# require_dir() if missing -- a moved local directory is always a defect),
# this root is legitimately absent on another machine (a fresh clone, a CI
# box, a teammate's own plugin set), so its absence degrades gracefully
# instead of aborting -- see load_installed_plugins_manifest(). Follows
# generate_registry.py's own precedent of anchoring plugin paths at
# Path.home() rather than at this script's own location, since the plugin
# cache is per-user-profile state, not part of the relocatable repo.
PLUGIN_HOME_ROOT = Path.home() / ".claude"
PLUGIN_CACHE_ROOT = PLUGIN_HOME_ROOT / "plugins" / "cache"
PLUGIN_INSTALLED_JSON = PLUGIN_HOME_ROOT / "plugins" / "installed_plugins.json"
PLUGIN_USER_SETTINGS_JSON = PLUGIN_HOME_ROOT / "settings.json"

AGGREGATES_DIR = HOOKS_DIR / "aggregates"
SNAPSHOTS_DIR = AGGREGATES_DIR / "asset-inventory-snapshots"
DATA_FILE = AGGREGATES_DIR / "asset-inventory.json"
MD_FILE = AGGREGATES_DIR / "asset-inventory.md"

# kind=telemetry-sink source (O1, 2026-08-30 harness-spec extension): the
# Hermes P3 telemetry-check's own generated vocabulary file, compiled by
# hook_activity_report.py --vocab-write. A regenerable aggregate, not one of
# the four core enumeration roots, so its absence degrades gracefully (see
# load_known_telemetry_sinks()) rather than aborting the run.
TELEMETRY_VOCAB_JSON = AGGREGATES_DIR / "telemetry-vocabulary.json"

GENERATOR_VERSION = "1.0"

IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# BLK-004 ("Plugin component with no routing path into any skill or hook")
# was removed from the closed set 2026-08-19 (build-review FIX 4) on the
# reasoning that the generator's kind=agent/kind=skill enumeration was
# fixed-scope, local-disk-only, so no row it could ever produce carried
# "plugin:" provenance with no local path -- the precondition was
# unreachable by construction, not merely untriggered by the data.
#
# RESTORED 2026-08-20, now that the plugin cache is a fifth enumeration
# root (see PLUGIN_CACHE_ROOT above and enumerate_plugin_skills_and_agents
# below). That removed the ORIGINAL reason BLK-004 was dead: plugin
# components now genuinely get real external paths. But that on its own
# still does not make BLK-004 fire -- every row this generator's own cache
# walk produces has has_path=True by definition (it only creates a row
# when it found a real file). BLK-004's precondition needs a SECOND,
# independent enumeration source: registry.json's own plugin-sourced
# agents/skills list. registry.json is built by generate_registry.py's
# scan_plugin_agents()/scan_plugin_skills(), an UNSCOPED rglob across the
# entire plugin cache (every stale version-folder included, deduplicated
# by bare name only) that does not consult installed_plugins.json at all.
# This generator's own plugin walk is deliberately narrower (see the
# multi-version rule below): only each plugin's CANONICAL installed
# version. A registry.json entry whose only backing file lived in a
# version-folder that is no longer the installed one (dropped between an
# update) would be claimed by registry.json but absent from this
# generator's fresh, installed-scoped walk -- exactly BLK-004's
# precondition. compute_blk004_rows() implements this diff and emits a
# synthetic, path=None row for any such gap.
#
# Measured on this machine, this run (2026-08-20): zero such gaps exist
# right now -- every registry.json plugin-sourced agent/skill name has a
# matching file in the currently-installed version of its plugin. That is
# a genuine, reportable fact (the installed marketplace snapshots have not
# drifted from registry.json's last regeneration), not a sign the check is
# unwired: BLK-004 is proven live via a synthetic registry.json fixture in
# the self-test (ASSERT-012), the same pattern already used for the
# field-contract abort (ASSERT-007/TASK-022) to prove a check fires when
# its precondition is met even though the live data happens not to trigger
# it today.
BLK_MEANINGS = {
    "BLK-001": "Present on disk but registered nowhere",
    "BLK-002": "Named in a dispatch contract but absent from the skill prose that drives it",
    "BLK-003": "Junction whose target is outside this repository",
    "BLK-004": ("Plugin component named in registry.json as plugin-sourced, with no matching "
                "file anywhere in the currently-installed (canonical-version) plugin cache"),
    "BLK-005": "No reachability evidence, general case",
    "BLK-006": ("Compiled settings-registration or telemetry-sink entry whose reference did not "
                "resolve to a matching on-disk asset: a settings.json/settings.local.json/"
                ".mcp.json registration entry whose command matches no currently-enumerated hook "
                "file (and, for an .mcp.json entry, carries neither a command nor an http type+url), "
                "or a declared telemetry sink whose backing file is absent from disk"),
}
# EVD-005 was added 2026-08-19 (build-review FIX 2), beyond the plan's
# original closed EVD-001..004 set. No existing code covers "reachable
# because a registered hook Python-imports this module as a shared
# library" (the confirmed live case: _irreversible_surface.py, imported
# by bash-safety-guard.py and mcp-irreversible-guard.py, both registered
# and security-critical) -- see the build report for the full reasoning.
EVD_MEANINGS = {
    "EVD-001": "Settings-file registration (hooks.<event>[].hooks[].command)",
    "EVD-002": "Dispatch-contract role (DISPATCHES.json, corroborated against sibling SKILL.md)",
    "EVD-003": "Workflow script reference (string literal in .claude/workflows/*.js)",
    "EVD-004": "Registry entry (registry.json agents/skills array membership)",
    "EVD-005": "Python import by another hook module that is itself EVD-001-registered",
    "EVD-006": ("Plugin skill/agent file present under an installed, enabled plugin's canonical "
                "install path (installed_plugins.json + user settings.json enabledPlugins)"),
    "EVD-007": ("Plugin hooks.json registration (an event/matcher/command entry in "
                "<plugin>/hooks/hooks.json), plugin installed and enabled"),
    "EVD-008": ("Plugin MCP server declared in the plugin's .mcp.json (default convention path "
                "or the path/object named by plugin.json's mcpServers field), plugin installed "
                "and enabled"),
    "EVD-009": ("Settings-registration entry (O1, 2026-08-30): a compiled structural description "
                "of one entry in .mcp.json, settings.json, or settings.local.json -- server name/"
                "command/transport type/env variable KEY NAMES for an .mcp.json entry, or event/"
                "matcher/command for a settings hook entry. Never carries an env value, header "
                "value, or any other secret. Attached unconditionally (whether or not the entry "
                "resolves), so an unresolved row still states what it is."),
    "EVD-010": ("Sink writer (O1, 2026-08-30): a currently-enumerated hook module named as a "
                "writer for a telemetry sink in telemetry-vocabulary.json (the Hermes P3 "
                "telemetry-check's own compiled vocabulary file)."),
}


class FieldContractError(RuntimeError):
    """Raised when a depended-on field is absent from every record of a
    sink/record-type this generator reads. This is the direct regression
    guard for the hook_activity_report.py line 301 defect class (a field
    silently absent from every record, producing a silent zero instead of
    a loud failure)."""


class EnumerationRootError(RuntimeError):
    """Raised when one of the four asset-enumeration root directories
    (hooks, skills, agents, workflows) does not exist (FIX 6, 2026-08-19).
    Path.glob() on a missing directory returns an empty iterator rather
    than raising, so without this check a moved or renamed directory would
    silently produce zero rows for an entire asset kind. This mirrors the
    discipline already applied to the two telemetry sinks: a missing sink
    file raises FileNotFoundError uncaught (open() is never guarded
    against a missing path), and a present-but-empty-of-signal sink raises
    FieldContractError; both abort loudly before any output is written
    rather than treating "nothing found" as a silent zero."""


def require_dir(path: Path, label: str) -> None:
    if not path.is_dir():
        raise EnumerationRootError(
            f"ENUMERATION_ROOT_MISSING: {label} directory not found at {path}. "
            f"Aborting before any output is written, rather than silently emitting "
            f"zero rows for this asset kind."
        )


# ---------------------------------------------------------------------------
# Row schema (TASK-002) -- the single definition site for row field names.
# ---------------------------------------------------------------------------

@dataclass
class Row:
    name: str
    kind: str
    path: Optional[str]
    provenance: str
    reachability: list = field(default_factory=list)
    blocked_reason: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    edges: list = field(default_factory=list)
    # DEL-003 GAP-1, ruled 2026-08-24 as a DIVERGENCE INDEX rather than a second
    # inventory. The index covered .claude/ and none of the published repo, while
    # framework-repo carries 131 entries under hooks/ alone. The obvious fix, adding
    # a row per repo file, was rejected: a published file is never executed here,
    # has no settings.json entry and emits no telemetry, so reachability, usage and
    # blocked_reason would all be vacuously negative on 131-plus rows and would
    # swamp the dark-surface signal this index exists to carry. Two columns on the
    # existing rows answer the question the gap was opened for, since all three real
    # defects found during the audit lived in the divergence between the two trees.
    twin: Optional[str] = None
    twin_state: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "path": self.path,
            "provenance": self.provenance,
            "reachability": self.reachability,
            "blocked_reason": self.blocked_reason,
            "usage": self.usage,
            "edges": self.edges,
            "twin": self.twin,
            "twin_state": self.twin_state,
        }



FRAMEWORK_REPO = REPO_ROOT / "Projects" / "Agent-Governance-Research" / "framework-repo"


def _repo_suffix_index(repo_root):
    """Map every path suffix of every repo file to the files carrying it.

    Suffix, not basename. Matching on basename alone is what produced two separate
    false-positive waves during this audit: ten distinct `run_actor.js` files under
    ten apify skill directories collapsed onto one, and four different `README.md`
    files were all matched to the same twin. A suffix keyed on at least two path
    segments cannot make that mistake, and where a suffix is still ambiguous the
    caller refuses to guess.
    """
    from collections import defaultdict
    index = defaultdict(list)
    if not repo_root.is_dir():
        return index
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            full = Path(dirpath) / fn
            parts = full.relative_to(repo_root).as_posix().split("/")
            for i in range(len(parts)):
                index["/".join(parts[i:])].append(full)
    return index


def _normalise(data: bytes) -> bytes:
    """Line endings only. The two trees are edited on the same machine but travel
    through git with different autocrlf histories, so a raw byte compare reports
    every file as divergent and tells you nothing."""
    return data.replace(b"\r\n", b"\n")


def stamp_twins(rows, repo_root=None):
    """Attach twin / twin_state to every row that has a path. Returns a summary.

    twin_state is one of:
      identical     the published copy matches after newline normalisation
      divergent     both exist and differ
      repo-absent   no published copy
      ambiguous       more than one repo file matches at the deepest suffix, so the
                      twin is NOT guessed. Recording ambiguity beats a coin flip.
      not-applicable  a plugin-sourced or absolute-path row. We do not publish those,
                      so they cannot have a twin in our repo.
    """
    repo_root = repo_root or FRAMEWORK_REPO
    index = _repo_suffix_index(repo_root)
    summary = {"identical": 0, "divergent": 0, "repo-absent": 0, "ambiguous": 0,
               "no-path": 0, "not-applicable": 0}
    for row in rows:
        if not row.path:
            summary["no-path"] += 1
            continue
        p = str(row.path).replace("\\", "/")
        # Only VAULT-OWNED files can have a published twin. Plugin-sourced rows carry
        # an absolute path into the plugin cache and are never published by us, so
        # matching them against the repo produces false twins: the plugin's own
        # `code-simplifier.md` matched the repo copy of the VAULT's agent of the same
        # name, which is a different file that happens to share a suffix. Same
        # cross-population error as the apify run_actor.js collisions, one level up.
        if os.path.isabs(p) or row.provenance.startswith("plugin:"):
            summary["not-applicable"] = summary.get("not-applicable", 0) + 1
            row.twin_state = "not-applicable"
            continue
        parts = p.split("/")
        match = None
        state = "repo-absent"
        # Longest suffix first, minimum two segments so a bare filename never matches.
        for i in range(len(parts) - 1):
            cands = index.get("/".join(parts[i:]))
            if not cands:
                continue
            if len(cands) > 1:
                state = "ambiguous"
                break
            match = cands[0]
            break
        if match is not None:
            try:
                same = _normalise(Path(row.path if os.path.isabs(str(row.path))
                                       else REPO_ROOT / row.path).read_bytes()) == \
                       _normalise(match.read_bytes())
                state = "identical" if same else "divergent"
                row.twin = match.relative_to(repo_root).as_posix()
            except OSError:
                state = "repo-absent"
        row.twin_state = state
        summary[state] += 1
    return summary


def evidence(evd_type: str, source_file: Any, detail: str) -> dict:
    return {"type": evd_type, "source_file": rel(source_file), "detail": detail}


def rel(path: Any) -> str:
    """Render a path relative to REPO_ROOT with forward slashes, for stable,
    portable, diffable output."""
    p = Path(path).resolve()
    try:
        r = p.relative_to(REPO_ROOT)
        return str(r).replace("\\", "/")
    except ValueError:
        return str(p).replace("\\", "/")


def empty_usage(source: str) -> dict:
    return {
        "total_count": 0,
        "first_seen": None,
        "last_seen": None,
        "source": source,
        "skipped_records_in_join": 0,
    }


# ---------------------------------------------------------------------------
# Generic file helpers -- all reads are explicit bytes-then-UTF-8-decode.
# ---------------------------------------------------------------------------

def read_bytes(path: Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def read_text(path: Path) -> str:
    return read_bytes(path).decode("utf-8", errors="replace")


def load_json_file(path: Path) -> Any:
    return json.loads(read_bytes(path).decode("utf-8"))


def stream_jsonl(path: Path):
    """Single streaming pass. Opens in binary mode, decodes each line as
    UTF-8, yields (ok: bool, record_or_None). Never holds the full file in
    memory; a truncated final line or an unparseable record yields
    (False, None) rather than raising."""
    with open(path, "rb") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                yield False, None
                continue
            try:
                text = line.decode("utf-8")
                rec = json.loads(text)
            except (UnicodeDecodeError, json.JSONDecodeError):
                yield False, None
                continue
            yield True, rec


def _update_span(usage_entry: dict, ts: Optional[str]) -> None:
    if not ts:
        return
    if usage_entry["first_seen"] is None or ts < usage_entry["first_seen"]:
        usage_entry["first_seen"] = ts
    if usage_entry["last_seen"] is None or ts > usage_entry["last_seen"]:
        usage_entry["last_seen"] = ts


def to_iso8601(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    # Sink timestamps are "YYYY-MM-DD HH:MM:SS"; normalize to ISO8601.
    if "T" not in ts and " " in ts:
        return ts.replace(" ", "T", 1)
    return ts


# ---------------------------------------------------------------------------
# Windows junction detection (RISK-002) -- reparse-point attribute + tag,
# not os.path.islink (which does not reliably report NTFS junctions).
# ---------------------------------------------------------------------------

def classify_skill_entry(path: Path) -> tuple[str, Optional[str]]:
    """Returns (kind, target) where kind is 'junction' or 'directory'."""
    st = os.lstat(path)
    attrs = getattr(st, "st_file_attributes", 0)
    is_reparse = bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
    reparse_tag = getattr(st, "st_reparse_tag", None)
    if is_reparse and reparse_tag == IO_REPARSE_TAG_MOUNT_POINT:
        target = os.path.realpath(str(path))
        return "junction", target
    return "directory", None


def is_under_repo_root(target: str) -> bool:
    try:
        t = Path(target).resolve()
        t.relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# EVD-001: settings-file hook registration
# ---------------------------------------------------------------------------

def load_settings_hook_commands() -> list[dict]:
    """Returns list of {source_file, event, matcher, command} for every
    individual hook command entry across both settings files."""
    out = []
    for settings_path in (SETTINGS_JSON, SETTINGS_LOCAL_JSON):
        if not settings_path.exists():
            continue
        data = load_json_file(settings_path)
        hooks_block = data.get("hooks", {})
        for evt, matcher_blocks in hooks_block.items():
            for block in matcher_blocks:
                matcher = block.get("matcher")
                for h in block.get("hooks", []):
                    out.append({
                        "source_file": settings_path,
                        "event": evt,
                        "matcher": matcher,
                        "command": h.get("command", ""),
                    })
    return out


def settings_entry_counts(commands: list[dict]) -> dict:
    counts: dict[str, dict[str, int]] = {}
    for c in commands:
        f = str(c["source_file"].name)
        counts.setdefault(f, {})
        counts[f][c["event"]] = counts[f].get(c["event"], 0) + 1
    summary = {}
    for f, per_event in counts.items():
        summary[f] = {
            "events": len(per_event),
            "entries": sum(per_event.values()),
        }
    return summary


def evd001_for_hook(hook_filename: str, commands: list[dict]) -> list[dict]:
    items = []
    for c in commands:
        if hook_filename in c["command"]:
            detail = f"event={c['event']} matcher={c['matcher']!r} command contains '{hook_filename}'"
            items.append(evidence("EVD-001", c["source_file"], detail))
    items.sort(key=lambda e: (e["source_file"], e["detail"]))
    return items


# ---------------------------------------------------------------------------
# EVD-002: dispatch-contract role, corroborated against sibling SKILL.md
# ---------------------------------------------------------------------------

def load_dispatch_roles(skills_dir: Path = SKILLS_DIR) -> list[dict]:
    """Returns list of role dicts: component, role_type, condition,
    dispatch_file, skill_md_file, skill_name, corroborated."""
    roles = []
    for dispatch_path in sorted(skills_dir.glob("*/DISPATCHES.json")):
        skill_dir = dispatch_path.parent
        skill_name = skill_dir.name
        skill_md_path = skill_dir / "SKILL.md"
        skill_md_text = read_text(skill_md_path) if skill_md_path.exists() else ""
        data = load_json_file(dispatch_path)

        def add(component: str, role_type: str, condition: Optional[str]) -> None:
            corroborated = bool(component) and component in skill_md_text
            roles.append({
                "component": component,
                "role_type": role_type,
                "condition": condition,
                "dispatch_file": dispatch_path,
                "skill_md_file": skill_md_path,
                "skill_name": skill_name,
                "corroborated": corroborated,
            })

        for item in data.get("mandatory_dispatches", []) or []:
            add(item.get("name", ""), "mandatory", None)
        for item in data.get("conditional_dispatches", []) or []:
            add(item.get("name", ""), "conditional", item.get("condition"))
        for name in data.get("allowed_specialists_via_process_exemption", []) or []:
            add(name, "allowed-specialist", None)
    return roles


def evd002_items_for(component_name: str, roles: list[dict]) -> tuple[list[dict], bool, bool]:
    """Returns (evidence_items, has_any_evd002, all_uncorroborated)."""
    matches = [r for r in roles if r["component"] == component_name]
    items = []
    for r in matches:
        cond = f" condition={r['condition']!r}" if r["condition"] else ""
        detail = (
            f"role={r['role_type']} in {rel(r['dispatch_file'])}{cond}; "
            f"corroborated_against_sibling_SKILL.md={r['corroborated']}"
        )
        items.append(evidence("EVD-002", r["dispatch_file"], detail))
    items.sort(key=lambda e: e["detail"])
    has_any = len(matches) > 0
    all_uncorroborated = has_any and all(not r["corroborated"] for r in matches)
    return items, has_any, all_uncorroborated


# ---------------------------------------------------------------------------
# EVD-003: workflow script string-literal reference
# ---------------------------------------------------------------------------

def load_workflow_texts(workflows_dir: Path = WORKFLOWS_DIR) -> dict[Path, str]:
    texts = {}
    for wf in sorted(workflows_dir.glob("*.js")):
        texts[wf] = read_text(wf)
    return texts


def evd003_items_for(component_name: str, workflow_texts: dict[Path, str]) -> list[dict]:
    """A component is cited by a workflow when its name appears as a quoted
    string literal in the workflow source (EVD-003's own definition: 'A
    string literal matching the component's name'), not as a bare
    substring, to avoid matching inside unrelated identifiers/comments."""
    items = []
    if not component_name:
        return items
    pattern = re.compile(r"""['"]""" + re.escape(component_name) + r"""['"]""")
    for wf_path, text in workflow_texts.items():
        if pattern.search(text):
            items.append(evidence("EVD-003", wf_path, f"string literal '{component_name}' found in {wf_path.name}"))
    items.sort(key=lambda e: e["source_file"])
    return items


# ---------------------------------------------------------------------------
# EVD-004: registry.json membership
# ---------------------------------------------------------------------------

def evd004_item_for(component_name: str, registry_bucket: dict, field_path: str) -> list[dict]:
    if component_name in registry_bucket:
        return [evidence("EVD-004", REGISTRY_JSON, f"present in registry.json {field_path}['{component_name}']")]
    return []


# ---------------------------------------------------------------------------
# Enumeration: hooks
# ---------------------------------------------------------------------------

def enumerate_hooks() -> tuple[list[str], list[str], list[str], list[str]]:
    """Returns (non_test_stems_sorted, test_filenames_sorted,
    retired_non_test_filenames_sorted, retired_test_filenames_sorted).

    Top-level: non-recursive glob over .claude/hooks/*.py, matching
    TASK-004's literal enumeration scope (__pycache__ and other
    subdirectories besides retired/ are excluded by construction, not by
    filtering).

    Retired (FIX 2026-08-19, build-review FIX 5): .claude/hooks/retired/
    is enumerated as a second, clearly separate population -- a hook file
    moved there is deregistered from settings.json/settings.local.json but
    can still carry real historical usage in hook-activity.jsonl (the
    confirmed case: retired/agent-registry-check.py, 4,287 recorded fires).
    Without this, that history sits in a raw skipped-records counter
    instead of a row. Retired rows are marked via their own `path` field
    (".../hooks/retired/<name>.py" instead of ".../hooks/<name>.py") --
    the row schema's existing vocabulary, no new field or provenance value
    added."""
    all_py = sorted(p.name for p in HOOKS_DIR.glob("*.py"))
    test_files = [f for f in all_py if f.startswith("test_")]
    non_test = [f for f in all_py if not f.startswith("test_")]

    retired_dir = HOOKS_DIR / "retired"
    retired_non_test: list[str] = []
    retired_test: list[str] = []
    if retired_dir.is_dir():
        retired_py = sorted(p.name for p in retired_dir.glob("*.py"))
        retired_test = [f for f in retired_py if f.startswith("test_")]
        retired_non_test = [f for f in retired_py if not f.startswith("test_")]

    return non_test, test_files, retired_non_test, retired_test


# ---------------------------------------------------------------------------
# kind=settings-registration + kind=telemetry-sink sources (O1, 2026-08-30
# harness-spec extension). Three compiled loaders, read-only, no hand-typed
# content. SECURITY: .mcp.json's env blocks and headers carry live API keys
# and bearer tokens; load_mcp_registration_entries() reads only structural
# fields (server name, command, transport type, env variable KEY NAMES) and
# never returns an env value, header value, url, or "args" entry.
# ---------------------------------------------------------------------------

def load_mcp_registration_entries(mcp_json_path: Path) -> list[dict]:
    """One dict per .mcp.json mcpServers entry: name, command, type,
    env_keys (sorted list of env variable KEY NAMES only), resolved (True if
    the entry carries either a command, i.e. a stdio launcher, or an http
    type plus a url -- the minimum structure needed to actually launch the
    server). Never reads 'args', 'url', or 'headers' VALUES."""
    if not mcp_json_path.exists():
        return []
    data = load_json_file(mcp_json_path)
    out = []
    for name, cfg in sorted(data.get("mcpServers", {}).items()):
        if not isinstance(cfg, dict):
            continue
        command = cfg.get("command")
        mtype = cfg.get("type")
        env_keys = sorted((cfg.get("env") or {}).keys())
        has_command = bool(command)
        is_http = mtype == "http" and bool(cfg.get("url"))
        out.append({
            "name": name, "command": command, "type": mtype,
            "env_keys": env_keys, "resolved": has_command or is_http,
        })
    return out


def load_settings_registration_entries() -> list[dict]:
    """One dict per individual hook-command entry across settings.json and
    settings.local.json, carrying the block/item indices needed for a
    unique row name. A fresh, small, independent read -- deliberately not
    reusing load_settings_hook_commands()'s flat (no-index) return shape,
    which existing EVD-001 evidence-attachment code depends on unchanged."""
    out = []
    for settings_path in (SETTINGS_JSON, SETTINGS_LOCAL_JSON):
        if not settings_path.exists():
            continue
        data = load_json_file(settings_path)
        hooks_block = data.get("hooks", {})
        for evt, matcher_blocks in hooks_block.items():
            for block_idx, block in enumerate(matcher_blocks):
                matcher = block.get("matcher")
                for item_idx, h in enumerate(block.get("hooks", [])):
                    out.append({
                        "source_file": settings_path, "event": evt,
                        "block_idx": block_idx, "item_idx": item_idx,
                        "matcher": matcher, "command": h.get("command", ""),
                    })
    return out


def load_known_telemetry_sinks() -> tuple[dict[str, set[str]], list[str]]:
    """Returns (sink_name -> set of writer .py stems declared for it in
    telemetry-vocabulary.json, notes). The sink-name population is the
    union of (a) the two sink basenames this generator already reads
    directly as its own hook/agent usage sinks (HOOK_ACTIVITY_JSONL_DEFAULT,
    GOVERNANCE_LOG_JSONL_DEFAULT -- the module-level defaults, not a
    fixture-overridden runtime path, so a self-test fixture sub-run cannot
    change which real sinks this kind describes), and (b) every sink name
    declared as a key in telemetry-vocabulary.json, the Hermes P3
    telemetry-check's own generated vocabulary file. A missing or
    unreadable vocabulary file degrades gracefully to (a) only -- it is a
    regenerable aggregate, not one of the four core enumeration roots --
    matching the plugin-cache-absent precedent (never fabricates a zero,
    reports the gap in `notes` instead)."""
    sinks: dict[str, set[str]] = {
        HOOK_ACTIVITY_JSONL_DEFAULT.name: set(),
        GOVERNANCE_LOG_JSONL_DEFAULT.name: set(),
    }
    notes: list[str] = []
    if not TELEMETRY_VOCAB_JSON.exists():
        notes.append(f"TELEMETRY_VOCAB_ABSENT: {TELEMETRY_VOCAB_JSON} not found. Falling back "
                      f"to the two hardcoded default sinks only; writer evidence is unavailable "
                      f"for either.")
        return sinks, notes
    try:
        vocab = load_json_file(TELEMETRY_VOCAB_JSON)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        notes.append(f"TELEMETRY_VOCAB_UNREADABLE: {TELEMETRY_VOCAB_JSON} failed to parse "
                      f"({exc}). Falling back to the two hardcoded default sinks only.")
        return sinks, notes
    for sink_name, sink_data in (vocab.get("sinks", {}) or {}).items():
        writer_stems = sinks.get(sink_name, set())
        for axis in (sink_data.get("axes", {}) or {}).values():
            for val in axis.get("values", []) or []:
                for w in val.get("writers", []) or []:
                    writer_stems.add(Path(w).stem)
        sinks[sink_name] = writer_stems
    return sinks, notes


def resolve_sink_path(sink_name: str) -> Optional[Path]:
    """A telemetry sink's backing file is not uniformly located: the two
    main sinks live directly under .claude/hooks/, but plain-language-
    warnings.jsonl lives under .claude/hooks/aggregates/ (confirmed live,
    2026-08-30 -- see reference_telemetry_sinks_are_not_under_aggregates.md
    for why the two main ones do NOT). Checking only HOOKS_DIR would
    misreport that sink as absent. Returns None if neither location has the
    file."""
    for candidate in (HOOKS_DIR / sink_name, AGGREGATES_DIR / sink_name):
        if candidate.is_file():
            return candidate
    return None


def count_sink_lines(path: Path) -> int:
    """Single stream-and-count over one sink file: the one genuinely new
    read O9 increment 1 adds, used only for sinks the generator does not
    already stream in full (today: plain-language-warnings.jsonl). Counts
    physical lines the same way stream_jsonl does (one per raw line),
    without JSON-parsing any of them and without holding the file in
    memory."""
    total = 0
    with open(path, "rb") as fh:
        for _raw_line in fh:
            total += 1
    return total


# ---------------------------------------------------------------------------
# Sink processing -- ONE streaming pass per sink per run (CON-004), combining
# the field-contract self-check (TASK-003) with usage-join counting so the
# worst case (zero qualifying records) never requires a second full read.
# ---------------------------------------------------------------------------

def process_hook_activity(path: Path, hook_stems: set[str],
                          window_start_cmp: Optional[str] = None,
                          window_end_cmp: Optional[str] = None) -> dict:
    total_lines = 0
    contract_seen_nonnull_hook = False
    usage: dict[str, dict] = {}
    unmatched_values: Counter = Counter()
    # O13 (D1): windowed counters accumulate in this same single pass.
    # A raw line that fails JSON parse has no timestamp, so it lands in
    # the windowed no-ts count by construction.
    w_matched = 0
    w_no_ts = 0
    w_unmatched: Counter = Counter()
    windowed_on = window_start_cmp is not None and window_end_cmp is not None
    for ok, rec in stream_jsonl(path):
        total_lines += 1
        if not ok:
            if windowed_on:
                w_no_ts += 1
            continue
        hook_val = rec.get("hook")
        if hook_val is not None:
            contract_seen_nonnull_hook = True
        ts = to_iso8601(rec.get("ts"))
        in_window = ts_in_window(ts, window_start_cmp, window_end_cmp) if windowed_on else False
        if windowed_on and in_window is None:
            w_no_ts += 1
        if isinstance(hook_val, str) and hook_val in hook_stems:
            u = usage.setdefault(hook_val, {"count": 0, "first_seen": None, "last_seen": None})
            u["count"] += 1
            _update_span(u, ts)
            if in_window:
                w_matched += 1
        else:
            unmatched_values[str(hook_val)] += 1
            if in_window:
                w_unmatched[str(hook_val)] += 1
    matched_total = sum(v["count"] for v in usage.values())
    skipped = total_lines - matched_total
    return {
        "total_lines": total_lines,
        "usage": usage,
        "skipped": skipped,
        "contract_ok": contract_seen_nonnull_hook,
        "unmatched_values": unmatched_values,
        "windowed": {"matched": w_matched, "no_ts": w_no_ts,
                     "unmatched_values": w_unmatched},
    }


def process_governance_log(path: Path, agent_names: set[str], skill_names: set[str],
                           workflow_names: set[str] | None = None,
                           window_start_cmp: Optional[str] = None,
                           window_end_cmp: Optional[str] = None) -> dict:
    workflow_names = workflow_names or set()
    total_lines = 0
    total_agent_dispatched = 0
    contract_seen_nonnull_agent_type = False
    agent_usage: dict[str, dict] = {}
    skill_usage: dict[str, dict] = {}
    unmatched_agent_values: Counter = Counter()
    unmatched_skill_values: Counter = Counter()
    skill_items_total = 0
    mcp_gate_usage: dict[str, dict] = {}
    mcp_gate_events_total = 0
    unmatched_mcp_gate_values: Counter = Counter()
    workflow_usage: dict[str, dict] = {}
    workflow_pass_total = 0
    workflow_pass_unattributed = 0
    unmatched_workflow_values: Counter = Counter()
    # O13 (D1): windowed counters for the two governance scopes,
    # accumulated in this same single pass.
    w_agent_matched = 0
    w_agent_no_ts = 0
    w_agent_unmatched: Counter = Counter()
    w_skill_matched = 0
    w_skill_no_ts = 0
    w_skill_unmatched: Counter = Counter()
    windowed_on = window_start_cmp is not None and window_end_cmp is not None

    for ok, rec in stream_jsonl(path):
        total_lines += 1
        if not ok:
            continue
        event = rec.get("event")
        # O9 increment 1 (2026-09-01): MCP gate events ride this same
        # single streaming pass (CON-004) rather than a second read. Two
        # writers, both confirmed in telemetry-vocabulary.json:
        # mcp-circuit-breaker.py emits breaker_blocked / breaker_override /
        # breaker_reset with the short server name in field 'server';
        # mcp-irreversible-guard.py emits 'deny' with the full
        # 'mcp__<segment>__<tool>' string in field 'tool'. The hook filter
        # on 'deny' is mandatory: other hooks (bash-safety-guard) also
        # write 'deny' events with different fields. These are GATING
        # decisions, not call volume; see MCP_GATE_USAGE_SOURCE.
        if event in ("breaker_blocked", "breaker_override", "breaker_reset"):
            mcp_gate_events_total += 1
            server = rec.get("server")
            if isinstance(server, str) and server:
                u = mcp_gate_usage.setdefault(
                    server, {"count": 0, "first_seen": None, "last_seen": None})
                u["count"] += 1
                _update_span(u, to_iso8601(rec.get("ts")))
            else:
                unmatched_mcp_gate_values[str(server)] += 1
        elif event == "deny" and rec.get("hook") == "mcp-irreversible-guard":
            mcp_gate_events_total += 1
            tool = rec.get("tool")
            segment = ""
            if isinstance(tool, str) and tool.startswith("mcp__"):
                # Mirrors mcp-circuit-breaker.py's _extract_server() rule
                # (lines 87-95): strip the leading 'mcp__', take the text
                # before the next '__' delimiter. Local stdlib copy of the
                # 4-line rule, never an import of the hook.
                segment = tool[len("mcp__"):].split("__", 1)[0]
            if segment:
                u = mcp_gate_usage.setdefault(
                    segment, {"count": 0, "first_seen": None, "last_seen": None})
                u["count"] += 1
                _update_span(u, to_iso8601(rec.get("ts")))
            else:
                unmatched_mcp_gate_values[str(tool)] += 1
        # O9 increment 2 (2026-09-01): workflow completion signals ride the
        # same single streaming pass. subagent-quality-check.py stamps a
        # 'workflow' field (the WORKFLOW-ID prompt marker, plumbed at the
        # dispatch site the same date) on every workflow-subagent pass
        # record; records written BEFORE the plumbing carry no such field
        # and are counted as unattributed legacy, never guessed at. These
        # are COMPLETIONS observed at SubagentStop, one per subagent, not
        # workflow invocations; see WORKFLOW_USAGE_SOURCE.
        elif (event == "pass" and rec.get("hook") == "subagent-quality-check"
              and rec.get("agent_type") == "workflow-subagent"):
            workflow_pass_total += 1
            wf = rec.get("workflow")
            if isinstance(wf, str) and wf in workflow_names:
                u = workflow_usage.setdefault(
                    wf, {"count": 0, "first_seen": None, "last_seen": None})
                u["count"] += 1
                _update_span(u, to_iso8601(rec.get("ts")))
            elif wf is None:
                workflow_pass_unattributed += 1
            else:
                unmatched_workflow_values[str(wf)] += 1
        if event != "agent_dispatched":
            continue
        total_agent_dispatched += 1
        ts = to_iso8601(rec.get("ts"))
        # O13 (D1): None from ts_in_window means a missing/unparseable
        # ts; it lands in the windowed unparseable_or_no_ts bucket,
        # matched or not, so windowed sums still reconcile.
        in_window = ts_in_window(ts, window_start_cmp, window_end_cmp) if windowed_on else False
        if windowed_on and in_window is None:
            w_agent_no_ts += 1
        at = rec.get("agent_type")
        if at is not None:
            contract_seen_nonnull_agent_type = True
        if isinstance(at, str) and at in agent_names:
            u = agent_usage.setdefault(at, {"count": 0, "first_seen": None, "last_seen": None})
            u["count"] += 1
            _update_span(u, ts)
            if in_window:
                w_agent_matched += 1
        else:
            unmatched_agent_values[str(at)] += 1
            if in_window:
                w_agent_unmatched[str(at)] += 1

        sc = rec.get("skill_context") or []
        for s in sc:
            skill_items_total += 1
            if windowed_on and in_window is None:
                w_skill_no_ts += 1
            if isinstance(s, str) and s in skill_names:
                u = skill_usage.setdefault(s, {"count": 0, "first_seen": None, "last_seen": None})
                u["count"] += 1
                _update_span(u, ts)
                if in_window:
                    w_skill_matched += 1
            else:
                unmatched_skill_values[str(s)] += 1
                if in_window:
                    w_skill_unmatched[str(s)] += 1

    matched_agent_total = sum(v["count"] for v in agent_usage.values())
    skipped_agent = total_agent_dispatched - matched_agent_total
    matched_skill_total = sum(v["count"] for v in skill_usage.values())
    skipped_skill = skill_items_total - matched_skill_total

    return {
        "total_lines": total_lines,
        "total_agent_dispatched": total_agent_dispatched,
        "agent_usage": agent_usage,
        "skill_usage": skill_usage,
        "skipped_agent": skipped_agent,
        "skipped_skill": skipped_skill,
        "contract_ok": contract_seen_nonnull_agent_type,
        "unmatched_agent_values": unmatched_agent_values,
        "unmatched_skill_values": unmatched_skill_values,
        "skill_items_total": skill_items_total,
        "mcp_gate_usage": mcp_gate_usage,
        "mcp_gate_events_total": mcp_gate_events_total,
        "unmatched_mcp_gate_values": unmatched_mcp_gate_values,
        "workflow_usage": workflow_usage,
        "workflow_pass_total": workflow_pass_total,
        "workflow_pass_unattributed": workflow_pass_unattributed,
        "unmatched_workflow_values": unmatched_workflow_values,
        "windowed_agent": {"matched": w_agent_matched, "no_ts": w_agent_no_ts,
                           "unmatched_values": w_agent_unmatched},
        "windowed_skill": {"matched": w_skill_matched, "no_ts": w_skill_no_ts,
                           "unmatched_values": w_skill_unmatched},
    }


# O9 increment 1 (2026-09-01): usage source for MCP gate-event joins.
# These events fire on GATING decisions (circuit-breaker trips, overrides
# and resets, and irreversible-guard denies), not on every MCP call, so a
# joined count is a sparse floor of activity, never invocation volume; the
# trailing qualifier says so on every row that carries it. A zero count
# under this source means "never tripped a gate", not "idle".
MCP_GATE_USAGE_SOURCE = ("governance-log.jsonl:mcp-gate-events("
                          "breaker_blocked/breaker_override/breaker_reset.server, "
                          "mcp-irreversible-guard.deny.tool); gated-events-only")


# O9 increment 2 (2026-09-01): usage source for the workflow-identity join.
# The signal is the subagent-quality-check PASS record's 'workflow' field
# (the WORKFLOW-ID prompt marker plumbed at the dispatch site 2026-09-01),
# so a joined count is COMPLETED workflow subagents, one per subagent, not
# workflow invocations, and only from records written after the plumbing:
# the 1,680+ earlier workflow-subagent pass records carry no identity and
# are permanently unattributable (counted in workflow_pass_unattributed,
# never estimated or backfilled). The exact text is pinned by the
# selftest's revised ASSERT-016.
WORKFLOW_USAGE_SOURCE = (
    "governance-log.jsonl:subagent-quality-check.pass(workflow); "
    "completions-only; identity plumbed 2026-09-01, earlier records carry no identity")

# The empty-usage source for a workflow row with no identified completion
# yet. Zero under this sentinel means "no identified completion observed
# since the plumbing", never "idle" -- also pinned by ASSERT-016.
WORKFLOW_AWAITING_SENTINEL = "AWAITING_FIRST_OBSERVATION"


def usage_from_join(usage_map: dict, name: str, source: str, skipped: int) -> dict:
    entry = usage_map.get(name)
    if entry is None:
        u = empty_usage(source)
        u["skipped_records_in_join"] = skipped
        return u
    return {
        "total_count": entry["count"],
        "first_seen": entry["first_seen"],
        "last_seen": entry["last_seen"],
        "source": source,
        "skipped_records_in_join": skipped,
    }


# ---------------------------------------------------------------------------
# O13 (2026-09-01): a stable definition for metric 1 (the usage join).
# Three additions, all computed from evidence the single streaming pass per
# sink already collects (CON-004: no second read of either sink):
#   D1  a 30-day trailing window beside the all-history figures,
#   D2  a labeled skip taxonomy beside the bare skip scalars,
#   D3  an enumeration-set fingerprint so match-set drift between runs is
#       visible in the header.
# Spec of record: '### O13' in Projects/Agent-Governance-Research/work/
# 2026-08-31-harness-takeover-objectives.md (ratified 2026-09-01).
# ---------------------------------------------------------------------------

WINDOW_DAYS = 30

# D2 built-in floor: dispatch labels that are real events but have no
# per-name inventory row by design. general-purpose/explore/plan/bash are
# the dispatch hook's own ALWAYS_ALLOWED infrastructure set
# (agent-dispatch-check.py); claude-code-guide and fork are runner-internal
# labels observed in the sink; '' is the hook's explicit no-type marker.
# PERMANENT BY DESIGN: this bucket never trends to zero, and no close-out
# may promise that it does.
BUILTIN_DISPATCH_FLOOR = frozenset({
    "general-purpose", "explore", "plan", "bash", "claude-code-guide",
    "fork", "",
})

BUILTIN_FLOOR_NOTE = (
    "builtin_floor is permanent by design: these dispatch labels are real "
    "events with no per-name inventory row (infrastructure dispatch types "
    "and runner-internal labels), so this bucket never trends to zero.")

# Normalized sink timestamp shape ("YYYY-MM-DDTHH:MM:SS" after to_iso8601).
# Anything else is treated as no-ts for windowed accounting (D1).
_TS_SHAPE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def window_bounds(generated_at: str, days: int = WINDOW_DAYS) -> tuple[str, str, str, str]:
    """D1: trailing window ending at this run's generated_at. Returns
    (start_iso, end_iso, start_cmp, end_cmp): the *_iso forms carry the
    trailing Z for the header; the *_cmp forms are the 19-char
    lexicographic comparators used against normalized sink timestamps
    (safe for this fixed format)."""
    end_dt = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    start_dt = end_dt - timedelta(days=days)
    start_iso = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return start_iso, generated_at, start_iso[:19], generated_at[:19]


def ts_in_window(ts: Optional[str], start_cmp: str, end_cmp: str) -> Optional[bool]:
    """True/False for a well-shaped normalized timestamp, None for a
    missing or unparseable one. The caller routes None into the windowed
    unparseable_or_no_ts bucket, matched or not (D1), so windowed sums
    still reconcile."""
    if not isinstance(ts, str) or not _TS_SHAPE.match(ts):
        return None
    return start_cmp <= ts[:19] <= end_cmp


def classify_skips(unmatched: Counter, scope: str, membership: dict,
                   unparseable_count: int = 0,
                   unparseable_bucket: Optional[str] = None) -> dict:
    """D2: pure, deterministic classification of the already-collected
    unmatched join values into the labeled skip taxonomy. No sink read.
    Precedence (fixed): unparseable, then builtin_floor, then
    cross_field_mislabel, then plugin_unqualified, then genuinely_unknown.

    scope: 'hook' | 'governance_agent' | 'governance_skill'.
    membership keys: builtin_floor, skill_names, agent_match_set,
    plugin_agent_bare_names.

    Bucket semantics per scope:
    - hook: unparseable (raw lines that failed JSON parse; passed in as
      unparseable_count) + genuinely_unknown (every parsed-but-unmatched
      hook value, including the stringified null).
    - governance_agent: builtin_floor / cross_field_mislabel (agent_type
      value that is a member of skill_names) / plugin_unqualified (bare
      name of a known plugin agent) / genuinely_unknown (everything else,
      including the literal 'None' and retired names).
    - governance_skill: builtin_floor / cross_field_mislabel (value in the
      agent match set or a plugin agent bare name) / plugin_unqualified
      (structurally empty here because cross_field_mislabel precedes it
      and already includes plugin bare names; kept for the fixed schema) /
      genuinely_unknown.
    """
    builtin_floor = membership["builtin_floor"]
    skill_names = membership["skill_names"]
    agent_match_set = membership["agent_match_set"]
    plugin_bare = membership["plugin_agent_bare_names"]

    if scope == "hook":
        bucket_order = ["genuinely_unknown"]
    else:
        bucket_order = ["builtin_floor", "cross_field_mislabel",
                        "plugin_unqualified", "genuinely_unknown"]

    per_bucket: dict[str, Counter] = {b: Counter() for b in bucket_order}
    for value, count in unmatched.items():
        if scope == "hook":
            bucket = "genuinely_unknown"
        elif value in builtin_floor:
            bucket = "builtin_floor"
        elif scope == "governance_agent" and value in skill_names:
            bucket = "cross_field_mislabel"
        elif scope == "governance_skill" and (value in agent_match_set
                                              or value in plugin_bare):
            bucket = "cross_field_mislabel"
        elif value in plugin_bare:
            bucket = "plugin_unqualified"
        else:
            bucket = "genuinely_unknown"
        per_bucket[bucket][value] += count

    buckets: dict[str, dict] = {}
    if unparseable_bucket is not None:
        buckets[unparseable_bucket] = {"count": unparseable_count,
                                       "top_values": []}
    for b in bucket_order:
        ctr = per_bucket[b]
        top = sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
        buckets[b] = {"count": sum(ctr.values()),
                      "top_values": [[v, c] for v, c in top]}

    block = {"buckets": buckets,
             "total_skips": sum(e["count"] for e in buckets.values())}
    if scope in ("governance_agent", "governance_skill"):
        block["builtin_floor_note"] = BUILTIN_FLOOR_NOTE
    return block


def windowed_scope_block(windowed: dict, scope: str, membership: dict) -> dict:
    """D1+D2: assemble one windowed_30d header block from the windowed
    counters the single streaming pass accumulated."""
    matched = windowed["matched"]
    tax = classify_skips(windowed["unmatched_values"], scope, membership,
                         unparseable_count=windowed["no_ts"],
                         unparseable_bucket="unparseable_or_no_ts")
    skipped = tax["total_skips"]
    return {"total_in_scope": matched + skipped, "matched": matched,
            "skipped": skipped, "skip_taxonomy": tax}


def enumeration_fingerprint(hook_match_set: set, agent_match_set: set,
                            skill_match_set: set) -> dict:
    """D3: sha256 over the canonical JSON of each sorted ACTUAL match set
    used by the join, plus a combined hash of the three per-set digests
    concatenated in fixed order (hooks, agents, skills). Using the match
    sets rather than the raw name lists is deliberate: the fingerprint
    changes exactly when the join's classification basis changes."""
    def _digest(s: set) -> str:
        canonical = json.dumps(sorted(list(s)), separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    hook_d = _digest(hook_match_set)
    agent_d = _digest(agent_match_set)
    skill_d = _digest(skill_match_set)
    combined = hashlib.sha256((hook_d + agent_d + skill_d).encode("ascii")).hexdigest()
    return {
        "hook_match_set_sha256": hook_d,
        "agent_match_set_sha256": agent_d,
        "skill_match_set_sha256": skill_d,
        "combined_sha256": combined,
        "hook_match_set_size": len(hook_match_set),
        "agent_match_set_size": len(agent_match_set),
        "skill_match_set_size": len(skill_match_set),
    }


# ---------------------------------------------------------------------------
# Blocked-reason evaluation (closed set BLK-001..BLK-005)
# ---------------------------------------------------------------------------

# Evidence types that prove a component is *known* (cataloged somewhere)
# but do not by themselves prove a dispatch/invocation path works. BLK-002
# already excluded EVD-004 from its own "other evidence" check on this
# reasoning (see the comment below); FIX 3 (2026-08-19) applies the same
# reasoning to the general BLK-001/BLK-005 gate, which previously let a
# reachability list containing only an EVD-004 item suppress BLK-001 --
# 43 of 166 rows rested on EVD-004 alone before this fix.
NON_MEANINGFUL_REACHABILITY_TYPES = {"EVD-004"}

# Dormancy threshold for the usage stamp below. 30 days is a starting number,
# not a derived one: it is long enough that a monthly-cadence tool is not
# flagged, short enough that a genuinely abandoned asset surfaces within a
# sprint. It gates a label, never a blocked_reason, so a wrong threshold
# mislabels rather than misleads.
DORMANT_AFTER_DAYS = 30



def suppress_blocked_by_usage(rows) -> int:
    """Clear BLK-001/BLK-005 from any row that has a recorded usage count.

    Owner-approved 2026-08-22. Both codes assert "no evidence this is
    reachable". A recorded use is direct evidence that it is, and it outranks
    every inference the reachability scan makes, so a row carrying both is
    self-contradictory. Measured before this change: 15 of 52 BLK-001 rows had
    a non-zero count, including pm-orchestrator (1,259 uses) and the pm skill
    (1,209), the two most-used assets in the harness, both mandatory by
    doctrine and both reported as things that could not be used.

    Runs as a post-pass because usage is joined onto rows after
    compute_blocked_reasons() has already run at ten separate call sites; a
    single pass here is one place to read and one place to test.

    Deliberately does NOT touch BLK-002 (a specific dispatch-contract
    corroboration failure), BLK-003 (junction outside the repo) or BLK-004
    (a claimed plugin file that is not on disk). Those assert something other
    than unreachability, and usage does not refute any of them.

    Returns the number of rows changed.
    """
    import datetime

    now = datetime.datetime.now()
    changed = 0
    for row in rows:
        # Retired assets are exempt (owner-approved 2026-08-23, D-5). A usage
        # count is evidence of reachability only while the asset is live; under
        # retired/ the count is history, and the directory is precisely how this
        # harness records that. Without this condition the rule cleared
        # agent-registry-check on 4,287 uses it accumulated BEFORE retirement,
        # leaving it with neither reachability evidence nor a blocked reason,
        # the single row failing the audit charter's DEL-003 criterion AC-2.
        # 2026-08-22-asset-inventory-decisions.md had already written down that
        # this exact asset should read blocked; the first version of this rule
        # tested the count and not the retirement, and so overrode it.
        path = (getattr(row, "path", None) or "").replace("\\", "/")
        if "/retired/" in path or path.startswith("retired/"):
            continue
        usage = getattr(row, "usage", None) or {}
        if not isinstance(usage, dict) or usage.get("total_count", 0) <= 0:
            continue
        codes = list(getattr(row, "blocked_reason", None) or [])
        kept = [c for c in codes if c not in ("BLK-001", "BLK-005")]
        if kept != codes:
            row.blocked_reason = kept
            changed += 1

        # Dormancy is stamped, never blocked (decision 2026-08-22, delegated).
        # "You cannot use this" and "you have not used this lately" are
        # different questions. Folding the second into blocked_reason would
        # repeat, in the other direction, the exact bug this suppression
        # fixed: a column meaning "unusable" naming things that work. An asset
        # last used in July is available, just rarely needed. So the row keeps
        # its cleared blocked_reason and carries the fact separately, where a
        # reader can sort on it without it being mistaken for a defect.
        last_seen = usage.get("last_seen")
        if not last_seen:
            continue
        try:
            when = datetime.datetime.fromisoformat(str(last_seen).rstrip("Z"))
        except (TypeError, ValueError):
            continue
        days = (now - when).days
        usage["days_since_last_use"] = days
        usage["dormant"] = days > DORMANT_AFTER_DAYS
    return changed


def compute_blocked_reasons(*, kind: str, has_path: bool, provenance: str,
                             reachability: list[dict], evd002_has_any: bool,
                             evd002_all_uncorroborated: bool) -> list[str]:
    codes = []
    meaningful_reachability = [e for e in reachability if e["type"] not in NON_MEANINGFUL_REACHABILITY_TYPES]
    reachability_empty = len(meaningful_reachability) == 0

    if reachability_empty and has_path:
        codes.append("BLK-001")

    # BLK-002: reachability's only evidence is EVD-002, and none corroborate.
    # "Other evidence" for this purpose means actual wiring evidence
    # (EVD-001/EVD-003), not mere registry existence (EVD-004), since
    # cataloging in registry.json proves the component is known, not that
    # a dispatch path into it works. See build report for the rationale.
    non_evd002_wiring = [e for e in reachability if e["type"] in ("EVD-001", "EVD-003")]
    if evd002_has_any and evd002_all_uncorroborated and not non_evd002_wiring:
        codes.append("BLK-002")

    if provenance.startswith("junction:"):
        target = provenance.split("junction:", 1)[1]
        if not is_under_repo_root(target):
            codes.append("BLK-003")

    # BLK-004 (restored 2026-08-20): a plugin-sourced component registry.json
    # claims exists, but this generator's own installed-scoped plugin-cache
    # walk found no matching file for it (see compute_blk004_rows()). Such a
    # row is constructed with has_path=False from the start -- has_path is
    # never guessed here, it reflects whether the cache walk actually found
    # the file.
    if provenance.startswith("plugin:") and not has_path and reachability_empty:
        codes.append("BLK-004")

    if reachability_empty and not any(c in codes for c in ("BLK-001", "BLK-003", "BLK-004")):
        codes.append("BLK-005")

    return codes


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------


class RegistryStalenessError(Exception):
    """registry.json is older than an asset file it is supposed to describe."""


def check_registry_freshness(registry_path, enumeration_roots) -> None:
    """Refuse to run against a registry older than the assets it describes.

    Owner decision 2026-08-22: a guard, not chaining. Auto-invoking
    generate_registry.py as a pre-step would make this generator write the
    very input it reads, which is the coupling the build plan deliberately
    avoided to keep the read/write boundary unambiguous.

    The staleness definition is checkable rather than time-based: if any file
    under the enumeration roots was modified after registry.json was
    generated, the registry cannot be describing current disk state. The
    build plan's FLAG-F asked whether a documented manual pre-step was
    sufficient; it was not, and the evidence was that it had already been
    skipped, leaving the inventory three days behind the registry.

    Silent when fresh. Raises RegistryStalenessError naming the exact command
    to run when stale, so the message is actionable rather than a complaint.
    """
    import datetime

    if not registry_path.exists():
        return
    try:
        stamp = load_json_file(registry_path).get("generated_at")
        if not stamp:
            return
        generated = datetime.datetime.fromisoformat(str(stamp).rstrip("Z")).timestamp()
    except Exception:
        # An unparseable stamp is not a staleness signal; the field-contract
        # check owns malformed-registry reporting.
        return

    # Only SOURCE files count. The first version of this guard walked every
    # file under the roots and immediately tripped on
    # .claude/hooks/hook-activity.jsonl, which every hook fire appends to, so
    # it would have refused every run forever. A guard that always fires is
    # not a guard. Assets are .md (agents, skills, commands), .py (hooks) and
    # .js (workflows); logs, aggregates and caches are state, not assets.
    ASSET_SUFFIXES = {".md", ".py", ".js"}
    EXCLUDED_PARTS = {"aggregates", "_state", "__pycache__", "snapshots", "_archive"}

    newest_path, newest_mtime = None, 0.0
    for root in enumeration_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in ASSET_SUFFIXES:
                continue
            if EXCLUDED_PARTS.intersection(path.parts):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime > newest_mtime:
                newest_path, newest_mtime = path, mtime

    if newest_path is not None and newest_mtime > generated:
        raise RegistryStalenessError(
            f"registry.json was generated {stamp} but {newest_path} was modified later "
            f"({datetime.datetime.fromtimestamp(newest_mtime).isoformat(timespec='seconds')}), "
            f"so it cannot describe current disk state. Run "
            f'"python .claude/scripts/generate_registry.py" first, then re-run this generator.'
        )


def load_registry(registry_path: Path = REGISTRY_JSON) -> dict:
    if not registry_path.exists():
        return {"agents": {}, "skills": {}, "plugins": [], "counts": {}}
    return load_json_file(registry_path)


def registry_provenance(name: str, bucket: dict, on_disk: bool, fallback_log: list[str]) -> str:
    entry = bucket.get(name)
    if entry is not None:
        source = entry.get("source", "local")
        if source == "local":
            return "authored-in-harness"
        if isinstance(source, str) and source.startswith("plugin:"):
            return source
        return "authored-in-harness"
    # ASSUMPTION-001 fallback: registry.json omits this component entirely.
    # A physical file under this repo's .claude/agents or .claude/skills
    # cannot be plugin-sourced (plugins live in the user-profile plugin
    # cache, not this repo), so on-disk presence settles the question.
    if on_disk:
        fallback_log.append(name)
        return "authored-in-harness"
    return "authored-in-harness"


# ---------------------------------------------------------------------------
# Plugin cache enumeration (2026-08-20 extension) -- a fifth asset root.
#
# Multi-version rule (states the decision REQ'd by the brief): one plugin
# key in installed_plugins.json ("<plugin-name>@<marketplace>") is exactly
# ONE enumeration root -- its own installPath, the LAST entry in that key's
# install array (mirrors generate_registry.py's load_installed_plugins()
# precedent: "most-recently installed scope wins"). Every OTHER
# version-folder physically present under the same plugin-name directory in
# the cache (a stale prior install, an inactive marketplace-resync
# snapshot, a manual .bak copy) is excluded from enumeration entirely --
# never walked, never counted. A plugin with two, or four, version-folders
# on disk still produces exactly the rows its ONE canonical version
# contains; duplicate versions cannot inflate the row count because they
# are never visited. Rows are additionally keyed by
# "<bare-name>@<plugin-name>@<marketplace>" (see qualified_plugin_name), so
# a genuine name collision across two DIFFERENT installed plugins --
# confirmed live on this machine: 'code-reviewer' is an agent in both
# feature-dev and pr-review-toolkit; 'atlassian' is an MCP server name in
# both the atlassian plugin and jira-toolkit; 'supabase' is an MCP server
# name in both the supabase plugin and this vault's own root .mcp.json --
# produces two distinct rows rather than one silently overwriting the
# other in rows_by_key.
# ---------------------------------------------------------------------------

CLAUDE_PLUGIN_ROOT_TOKEN_PATTERN = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}([^\s\"']+)")


STUB_SIZE_THRESHOLD_BYTES = 1000
STUB_CONTENT_PATTERN = re.compile(r"^[./][\w./\-]+\.(?:md|json)$")


def resolve_plugin_content_path(path: Path, max_hops: int = 4) -> Path:
    """Some plugins ship symlinks between skill/agent directories -- a
    shared definition referenced from more than one entry point. This
    machine's plugin-cache checkout runs with symlinks disabled at the git
    layer (the same, already-documented condition that leaves
    a vendored marketplace repo's validate_repo.py permanently red locally --
    core.symlinks=false): a symlink materializes as an ordinary small text
    file whose entire content is the target's relative path string, not a
    working filesystem symlink or NTFS reparse point (confirmed live:
    os.lstat() on the file shows is_symlink()==False, st_reparse_tag==0 --
    this is NOT the toolkit-code-review junction case classify_skill_entry()
    already handles). Confirmed live: academic-research-skills'
    agents/report_compiler_agent.md (48 bytes, content
    '../deep-research/agents/report_compiler_agent.md') and career-ops's
    .claude/skills/career-ops/SKILL.md (43 bytes, content
    '../../../.agents/skills/career-ops/SKILL.md') both redirect this way.

    Only files under STUB_SIZE_THRESHOLD_BYTES are opened and their
    content read -- every genuine SKILL.md/agent .md file found on this
    machine measures at least 2089 bytes, a clean, verified gap from the
    5 stub files found (42-51 bytes), so this never reads a real file's
    body just to confirm it is real (performance constraint: enumerate
    paths, read only what a row genuinely needs -- here, only the ~5
    suspiciously-tiny candidates out of ~200). Resolves relative to the
    STUB's OWN parent directory (standard symlink target-resolution
    semantics), follows up to max_hops redirects to guard against a
    cycle, and returns the original path unresolved the moment content
    does not look like a bare relative path or the next hop is not a real
    file -- i.e. it degrades to treating a merely-small-but-real file as
    real, never fabricates a resolution that is not there."""
    current = path
    for _ in range(max_hops):
        try:
            size = current.stat().st_size
        except OSError:
            return current
        if size == 0 or size >= STUB_SIZE_THRESHOLD_BYTES:
            return current
        try:
            content = current.read_bytes().decode("utf-8", errors="replace").strip()
        except OSError:
            return current
        if "\n" in content or not STUB_CONTENT_PATTERN.match(content):
            return current
        candidate = (current.parent / content).resolve()
        if not candidate.is_file():
            return current
        current = candidate
    return current


def qualified_plugin_name(bare_name: str, plugin_name: str, marketplace: str) -> str:
    """Row-unique name for a plugin-sourced component. Bare names alone are
    not safe as row keys -- see the multi-version-rule comment above this
    section for the confirmed live collisions this format avoids. The '@'
    separator cannot collide with any local asset name (no local hook,
    skill, or agent file name on this vault contains '@'), and reuses the
    '<name>@<source>' convention installed_plugins.json's own keys already
    use, one level deeper (component@plugin@marketplace)."""
    return f"{bare_name}@{plugin_name}@{marketplace}"


@dataclass
class PluginComponent:
    kind: str
    bare_name: str
    qualified_name: str
    plugin_name: str
    marketplace: str
    provenance: str
    path: Optional[Path]
    enabled: bool
    evidence: list = field(default_factory=list)
    usage_join_key: Optional[str] = None


def load_installed_plugins_manifest() -> tuple[dict, list]:
    """Reads installed_plugins.json; returns (canonical_by_key, notes).

    canonical_by_key maps '<plugin-name>@<marketplace>' -> {install_path,
    version, git_commit_sha}. This is the single source of truth for which
    version-folder is canonical per plugin (see the multi-version rule
    above). Absence of the cache directory or the manifest is reported via
    `notes` and returns ({}, notes) -- NEVER raised. This is the deliberate
    exception to this generator's usual loud-failure discipline: the four
    local roots (HOOKS_DIR etc.) abort via require_dir() because a missing
    one always means something broke in THIS repository; the plugin cache
    lives outside the repository entirely (Path.home()), so its absence on
    a different machine is normal, expected state, not a defect to abort
    over. Degrading to zero plugin rows plus an explicit note lets the four
    local-only asset kinds still produce a complete, correct report."""
    notes: list = []
    if not PLUGIN_CACHE_ROOT.is_dir():
        notes.append(
            f"PLUGIN_CACHE_ABSENT: {PLUGIN_CACHE_ROOT} does not exist on this machine. Zero "
            f"plugin-sourced rows enumerated this run. Expected on a machine without this user "
            f"profile's plugin cache (fresh clone, CI, a teammate's own plugin set); not an "
            f"error, and the four local-only enumeration roots are unaffected."
        )
        return {}, notes
    if not PLUGIN_INSTALLED_JSON.exists():
        notes.append(
            f"INSTALLED_MANIFEST_ABSENT: {PLUGIN_INSTALLED_JSON} not found, but "
            f"{PLUGIN_CACHE_ROOT} exists. Which version-folder is canonical per plugin cannot "
            f"be determined safely (picking newest-mtime or highest-semver would be a guess, "
            f"not evidence), so zero plugin-sourced rows enumerated this run rather than risk "
            f"misattributing a stale copy as live."
        )
        return {}, notes
    try:
        manifest = load_json_file(PLUGIN_INSTALLED_JSON)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        notes.append(f"INSTALLED_MANIFEST_UNREADABLE: {PLUGIN_INSTALLED_JSON} failed to parse "
                      f"({exc}). Zero plugin-sourced rows enumerated this run.")
        return {}, notes
    plugins_map = manifest.get("plugins")
    if not isinstance(plugins_map, dict):
        notes.append("INSTALLED_MANIFEST_MALFORMED: top-level 'plugins' key missing or not an "
                      "object. Zero plugin-sourced rows enumerated this run.")
        return {}, notes

    canonical: dict = {}
    for key, installs in plugins_map.items():
        if not isinstance(installs, list) or not installs:
            continue
        install = installs[-1]
        if not isinstance(install, dict):
            continue
        install_path_str = install.get("installPath")
        if not install_path_str:
            continue
        install_path = Path(install_path_str)
        if not install_path.is_dir():
            notes.append(f"INSTALL_PATH_MISSING: {key} names installPath={install_path} in "
                          f"installed_plugins.json, but that directory does not exist on disk. "
                          f"Skipped -- zero rows for this plugin this run.")
            continue
        canonical[key] = {
            "install_path": install_path,
            "version": install.get("version", "unknown"),
            "git_commit_sha": install.get("gitCommitSha"),
        }
    return canonical, notes


def load_plugin_enabled_map() -> tuple[dict, list]:
    """Reads the 'enabledPlugins' map from the USER-level settings.json
    (Path.home()/.claude/settings.json -- distinct from this repo's own
    .claude/settings.json / settings.local.json, which carry no such key).
    Mirrors generate_registry.py's load_installed_plugins() precedent
    exactly: same file, same key, default True when a plugin key is
    present in installed_plugins.json but absent from this map."""
    notes: list = []
    if not PLUGIN_USER_SETTINGS_JSON.exists():
        notes.append(f"USER_SETTINGS_ABSENT: {PLUGIN_USER_SETTINGS_JSON} not found; "
                      f"enabled/disabled state assumed True for every installed plugin.")
        return {}, notes
    try:
        data = load_json_file(PLUGIN_USER_SETTINGS_JSON)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        notes.append(f"USER_SETTINGS_UNREADABLE: {PLUGIN_USER_SETTINGS_JSON} failed to parse "
                      f"({exc}); enabled/disabled state assumed True for every installed plugin.")
        return {}, notes
    enabled_map = data.get("enabledPlugins")
    if not isinstance(enabled_map, dict):
        return {}, notes
    return enabled_map, notes


def enumerate_plugin_skills_and_agents(canonical: dict, enabled_map: dict) -> list:
    """kind=skill and kind=agent rows for every installed plugin's
    CANONICAL version only (see the multi-version rule above). Glob
    patterns ('*/[Ss][Kk][Ii][Ll][Ll].md', 'agents/*.md') deliberately
    mirror generate_registry.py's scan_plugin_skills()/scan_plugin_agents()
    exactly, so a plugin component this generator finds is guaranteed to be
    the same file registry.json's own EVD-004 evidence can corroborate
    against. Performance: enumerates PATHS only via rglob; the only file
    contents ever read are the small minority that fail the
    resolve_plugin_content_path() size check (~5 of ~200 on this machine),
    to disambiguate a real symlink-stub redirect -- see that function.

    Each raw glob hit is passed through resolve_plugin_content_path()
    before becoming a row, and rows are deduplicated per-plugin by
    (kind, bare_name, resolved real path): a symlink-stub and its target
    are the SAME logical asset reached two ways (confirmed live: the
    top-level agents/report_compiler_agent.md stub and the real
    deep-research/agents/report_compiler_agent.md file both resolve to one
    real path and now produce exactly one row, not two colliding ones).

    Reachability: a plugin skill/agent is invocable by name through the
    Skill/Agent tool once the plugin that ships it is both installed
    (present in installed_plugins.json) and enabled (per user
    settings.json's enabledPlugins). EVD-006 evidence is only attached when
    both hold; a disabled plugin's component still gets a real row (the
    file exists) but an empty reachability list, which correctly falls
    through to BLK-001 in compute_blocked_reasons -- no separate
    'disabled' blocked-code was needed."""
    components: list = []
    for key in sorted(canonical.keys()):
        info = canonical[key]
        plugin_name, _, marketplace = key.partition("@")
        install_path = info["install_path"]
        enabled = bool(enabled_map.get(key, True))
        provenance = f"plugin:{marketplace}/{plugin_name}"
        seen: set = set()

        for skill_md in sorted(install_path.rglob("*/[Ss][Kk][Ii][Ll][Ll].md")):
            real_path = resolve_plugin_content_path(skill_md)
            bare = real_path.parent.name
            dedupe_key = ("skill", bare, str(real_path))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            qname = qualified_plugin_name(bare, plugin_name, marketplace)
            ev = []
            if enabled:
                redirect_note = (f"; reached via symlink-stub redirect from {rel(skill_md)}"
                                  if real_path != skill_md else "")
                ev.append(evidence(
                    "EVD-006", real_path,
                    f"skill directory present under installed, enabled plugin '{plugin_name}' "
                    f"(marketplace '{marketplace}'){redirect_note}",
                ))
            components.append(PluginComponent(
                kind="skill", bare_name=bare, qualified_name=qname,
                plugin_name=plugin_name, marketplace=marketplace, provenance=provenance,
                path=real_path.parent, enabled=enabled, evidence=ev,
            ))

        agent_real_paths_by_bare: dict = {}
        for agent_md in sorted(install_path.rglob("agents/*.md")):
            real_path = resolve_plugin_content_path(agent_md)
            bare = real_path.stem
            dedupe_key = ("agent", bare, str(real_path))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            # Disambiguate a genuine same-plugin, same-bare-name collision:
            # two DIFFERENT real files sharing a stem (confirmed live:
            # academic-research-skills ships academic-paper/agents/
            # socratic_mentor_agent.md, 25KB, "Socratic Paper..." AND
            # deep-research/agents/socratic_mentor_agent.md, 37KB, "Socratic
            # Research..." -- both real content, not a stub/redirect pair).
            # `bare_name` (used for EVD-002/003/004 lookups against
            # DISPATCHES.json/workflows/registry.json, which only ever know
            # the plain stem) is left unchanged; only the ROW's qualified
            # name gains the containing-folder as context, matching the
            # distinction a human would reach for ("the academic-paper
            # one" vs "the deep-research one").
            prior_paths = agent_real_paths_by_bare.setdefault(bare, set())
            name_for_row = bare
            if prior_paths and str(real_path) not in prior_paths:
                context = real_path.parent.parent.name if real_path.parent.name == "agents" else real_path.parent.name
                name_for_row = f"{bare}[{context}]"
            prior_paths.add(str(real_path))

            qname = qualified_plugin_name(name_for_row, plugin_name, marketplace)
            ev = []
            if enabled:
                redirect_note = (f"; reached via symlink-stub redirect from {rel(agent_md)}"
                                  if real_path != agent_md else "")
                ev.append(evidence(
                    "EVD-006", real_path,
                    f"agent file present under installed, enabled plugin '{plugin_name}' "
                    f"(marketplace '{marketplace}'){redirect_note}",
                ))
            components.append(PluginComponent(
                kind="agent", bare_name=bare, qualified_name=qname,
                plugin_name=plugin_name, marketplace=marketplace, provenance=provenance,
                path=real_path, enabled=enabled, evidence=ev,
                usage_join_key=f"{plugin_name}:{bare}",
            ))
    return components


def enumerate_plugin_hooks(canonical: dict, enabled_map: dict) -> list:
    """kind=hook rows sourced from each installed plugin's own
    hooks/hooks.json. A plugin hook runs because the plugin registers it
    (its hooks.json is loaded by Claude Code's plugin system directly),
    NOT because it appears in this vault's settings.json/settings.local.json
    -- so its reachability evidence (EVD-007) is the hooks.json registration
    entry itself, scoped to an installed+enabled plugin, never an EVD-001
    settings-file check (hooks.json is a different registration mechanism
    entirely, not a vault settings entry).

    Row granularity: one row per {event, matcher-block, hook-item} entry in
    hooks.json, named positionally ('<Event>[<block>.<item>]') rather than
    by the invoked script. A single underlying script is often reused
    across several distinct registrations with different matchers/
    conditions (confirmed live: security-guidance's PostToolUse Bash block
    has 5 items all invoking security_reminder_hook.py, differentiated only
    by their 'if' condition) -- naming rows by script would collide or
    silently merge behaviorally distinct registrations. The `path` field is
    still populated with a best-effort resolution of the first
    '${CLAUDE_PLUGIN_ROOT}/...' script token found in the command string
    (the convention every observed plugin hooks.json uses); if no token
    resolves to a real file, `path` falls back to hooks.json itself, and
    the fallback is stated in the evidence detail, never left silent."""
    components: list = []
    for key in sorted(canonical.keys()):
        info = canonical[key]
        plugin_name, _, marketplace = key.partition("@")
        install_path = info["install_path"]
        enabled = bool(enabled_map.get(key, True))
        provenance = f"plugin:{marketplace}/{plugin_name}"

        hooks_json_path = install_path / "hooks" / "hooks.json"
        if not hooks_json_path.is_file():
            continue
        try:
            hdata = load_json_file(hooks_json_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        hooks_block = hdata.get("hooks", {})
        if not isinstance(hooks_block, dict):
            continue

        for event in sorted(hooks_block.keys()):
            matcher_blocks = hooks_block[event]
            if not isinstance(matcher_blocks, list):
                continue
            for block_idx, block in enumerate(matcher_blocks):
                if not isinstance(block, dict):
                    continue
                matcher = block.get("matcher")
                items = block.get("hooks", [])
                if not isinstance(items, list):
                    continue
                for item_idx, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    command = item.get("command", "")
                    bare = f"{event}[{block_idx}.{item_idx}]"
                    qname = qualified_plugin_name(bare, plugin_name, marketplace)

                    script_tokens = CLAUDE_PLUGIN_ROOT_TOKEN_PATTERN.findall(command)
                    resolved_path = hooks_json_path
                    path_note = ("no ${CLAUDE_PLUGIN_ROOT} script token found in command; "
                                  "row path points at hooks.json itself")
                    if script_tokens:
                        candidate = (install_path / script_tokens[0].lstrip("/\\")).resolve()
                        if candidate.is_file():
                            resolved_path = candidate
                            path_note = (f"path resolved from first of {len(script_tokens)} "
                                         f"${{CLAUDE_PLUGIN_ROOT}} token(s) in command: {script_tokens}")
                        else:
                            path_note = (f"${{CLAUDE_PLUGIN_ROOT}} token(s) in command "
                                         f"{script_tokens} did not resolve to a file on disk; "
                                         f"row path falls back to hooks.json itself")

                    ev = []
                    if enabled:
                        cond = f" if={item['if']!r}" if isinstance(item.get("if"), str) else ""
                        matcher_repr = f" matcher={matcher!r}" if matcher else ""
                        ev.append(evidence(
                            "EVD-007", hooks_json_path,
                            f"event={event}{matcher_repr}{cond} command={command!r}; {path_note}",
                        ))
                    components.append(PluginComponent(
                        kind="hook", bare_name=bare, qualified_name=qname,
                        plugin_name=plugin_name, marketplace=marketplace, provenance=provenance,
                        path=resolved_path, enabled=enabled, evidence=ev,
                    ))
    return components


def enumerate_plugin_mcp_servers(canonical: dict, enabled_map: dict) -> list:
    """kind=mcp-server rows sourced from each installed plugin's declared
    MCP configuration. A plugin MCP server is 'enabled by configuration':
    its .mcp.json (or the path/object plugin.json's own 'mcpServers' field
    names) is loaded by Claude Code's plugin system directly, scoped to an
    installed+enabled plugin (EVD-008), independent of this vault's own
    root .mcp.json.

    Resolution order, verified against every plugin.json on this machine
    that declares MCP: (1) plugin.json's 'mcpServers' field as a STRING
    path, resolved relative to the plugin root -- confirmed necessary
    (supabase declares "./agents/claude/.mcp.json", not the default
    convention path; three .mcp.json siblings exist under agents/ for
    other AI tools, and only this one is the Claude Code server list). (2)
    plugin.json's 'mcpServers' field as an inline object (no separate file
    to read). (3) the default convention path '<plugin-root>/.mcp.json' if
    plugin.json declares no 'mcpServers' field at all -- confirmed live
    (github/greptile/playwright/circleback all auto-discover this way, no
    explicit plugin.json field). The resolved file's schema also varies:
    some wrap servers in a top-level 'mcpServers' key (matching this vault's
    own root .mcp.json), others ARE the server map directly with no wrapper
    (confirmed live: github's .mcp.json). Both are handled."""
    components: list = []
    for key in sorted(canonical.keys()):
        info = canonical[key]
        plugin_name, _, marketplace = key.partition("@")
        install_path = info["install_path"]
        enabled = bool(enabled_map.get(key, True))
        provenance = f"plugin:{marketplace}/{plugin_name}"

        plugin_json_path = install_path / ".claude-plugin" / "plugin.json"
        mcp_field = None
        if plugin_json_path.is_file():
            try:
                pdata = load_json_file(plugin_json_path)
                mcp_field = pdata.get("mcpServers")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                mcp_field = None

        mcp_json_path: Optional[Path] = None
        inline_map: Optional[dict] = None
        source_note = ""
        if isinstance(mcp_field, str):
            rel_field = mcp_field[2:] if mcp_field.startswith("./") else mcp_field
            candidate = (install_path / rel_field).resolve()
            if candidate.is_file():
                mcp_json_path = candidate
                source_note = f"path declared in plugin.json mcpServers field ('{mcp_field}')"
        elif isinstance(mcp_field, dict):
            inline_map = mcp_field
            mcp_json_path = plugin_json_path
            source_note = "inline mcpServers object in plugin.json"
        else:
            default_path = install_path / ".mcp.json"
            if default_path.is_file():
                mcp_json_path = default_path
                source_note = "default convention path .mcp.json (no explicit plugin.json mcpServers field)"

        if mcp_json_path is None:
            continue

        server_map = inline_map
        if server_map is None:
            try:
                fdata = load_json_file(mcp_json_path)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            server_map = fdata.get("mcpServers") if isinstance(fdata.get("mcpServers"), dict) else fdata
        if not isinstance(server_map, dict):
            continue

        for server_name in sorted(server_map.keys()):
            qname = qualified_plugin_name(server_name, plugin_name, marketplace)
            ev = []
            if enabled:
                ev.append(evidence(
                    "EVD-008", mcp_json_path,
                    f"server '{server_name}' declared in plugin '{plugin_name}' ({source_note})",
                ))
            components.append(PluginComponent(
                kind="mcp-server", bare_name=server_name, qualified_name=qname,
                plugin_name=plugin_name, marketplace=marketplace, provenance=provenance,
                path=mcp_json_path, enabled=enabled, evidence=ev,
            ))
    return components


def compute_blk004_rows(registry: dict, found_bare_names: dict) -> list:
    """See the BLK-004 restoration comment above BLK_MEANINGS for the full
    reasoning. registry.json's plugin-sourced agents/skills (source field
    starting 'plugin:') are compared by bare name against
    found_bare_names = {'skill': {...}, 'agent': {...}}, the set this
    generator's OWN installed-scoped walk (enumerate_plugin_skills_and_agents)
    actually found. A registry name absent from that set becomes a
    synthetic, path=None candidate row. provenance uses registry.json's own
    (coarser, marketplace-only) source field, since that is the only
    plugin-identity information available for a component this generator's
    own walk never found -- there is no install_path to derive a specific
    plugin name from."""
    rows = []
    bucket_by_kind = {"agent": registry.get("agents", {}), "skill": registry.get("skills", {})}
    for kind, bucket in bucket_by_kind.items():
        for name in sorted(bucket.keys()):
            entry = bucket[name]
            source = entry.get("source", "")
            if not isinstance(source, str) or not source.startswith("plugin:"):
                continue
            if name in found_bare_names.get(kind, set()):
                continue
            marketplace = source.split("plugin:", 1)[1]
            rows.append({"kind": kind, "name": name, "provenance": f"plugin:{marketplace}"})
    return rows


# ---------------------------------------------------------------------------
# CLAUDE.md-vs-registry.json documentation-drift report (TASK-010)
# ---------------------------------------------------------------------------

DRIFT_PATTERN = re.compile(
    r"(\d+)\s+agents,\s*(\d+)\s+skills,.*?(\d+)\s+installed plugins\s*\((\d+)\s+enabled\)",
    re.DOTALL,
)


def build_documentation_drift_report(registry: dict, fresh_counts: dict) -> dict:
    claim = {"agents": None, "skills": None, "plugins_installed": None, "plugins_enabled": None,
             "found_in": None}
    if ROOT_CLAUDE_MD.exists():
        text = read_text(ROOT_CLAUDE_MD)
        m = DRIFT_PATTERN.search(text)
        if m:
            claim = {
                "agents": int(m.group(1)),
                "skills": int(m.group(2)),
                "plugins_installed": int(m.group(3)),
                "plugins_enabled": int(m.group(4)),
                "found_in": rel(ROOT_CLAUDE_MD),
            }

    reg_counts = registry.get("counts", {})
    registry_claim = {
        "agents": reg_counts.get("agents"),
        "skills": reg_counts.get("skills"),
        "plugins_installed": reg_counts.get("plugins_total"),
        "plugins_enabled": reg_counts.get("plugins_enabled"),
    }

    scope_notes = {
        "agents": ("generator_fresh_count is scoped to this build's local-only enumeration "
                   "(.claude/agents/*.md, per TASK-007); it excludes plugin-sourced agents that "
                   "CLAUDE.md's and registry.json's totals include. Not an apples-to-apples "
                   "third measurement of the same population."),
        "skills": ("generator_fresh_count is scoped to this build's local-only enumeration "
                   "(.claude/skills/*, per TASK-006); it excludes plugin-sourced skills that "
                   "CLAUDE.md's and registry.json's totals include. Not an apples-to-apples "
                   "third measurement of the same population."),
        "plugins_installed": ("generator_fresh_count is a live re-read of registry.json's own "
                              "plugins array, so agreement with registry_json_claim confirms "
                              "registry.json's internal counts field is self-consistent; it does "
                              "not independently re-derive plugin installation state."),
        "plugins_enabled": ("generator_fresh_count is a live re-read of registry.json's own "
                            "plugins array; see plugins_installed note."),
    }

    rows = []
    for field_name, label in (
        ("agents", "agents"),
        ("skills", "skills"),
        ("plugins_installed", "plugins installed"),
        ("plugins_enabled", "plugins enabled"),
    ):
        rows.append({
            "field": label,
            "claude_md_claim": claim.get(field_name),
            "registry_json_claim": registry_claim.get(field_name),
            "generator_fresh_count": fresh_counts.get(field_name),
            "scope_note": scope_notes[field_name],
        })

    return {
        "claude_md_source": claim.get("found_in"),
        "registry_generated_at": registry.get("generated_at"),
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Edges compiler (TASK-014) + unresolved prose scan (TASK-015)
# ---------------------------------------------------------------------------

def add_edge_pair(rows_by_key: dict, key_a: tuple, key_b: tuple, relation: str,
                   source: str, status: str, compiled_pairs: set) -> None:
    a = rows_by_key.get(key_a)
    b = rows_by_key.get(key_b)
    if a is not None and b is not None:
        a.edges.append({"direction": "outbound", "counterpart": b.name, "relation": relation,
                         "source": source, "status": status})
        b.edges.append({"direction": "inbound", "counterpart": a.name, "relation": relation,
                         "source": source, "status": status})
        if status == "resolved":
            compiled_pairs.add(frozenset((key_a, key_b)))
    elif a is not None and b is None:
        a.edges.append({"direction": "outbound", "counterpart": key_b[1], "relation": relation,
                         "source": source, "status": status})


def sort_edges(rows: list[Row]) -> None:
    for r in rows:
        r.edges.sort(key=lambda e: (e["direction"], e["counterpart"], e["relation"], e["source"]))
        # de-duplicate identical edge objects that can arise from multiple
        # evidence items pointing at the same underlying relationship.
        seen = set()
        deduped = []
        for e in r.edges:
            k = (e["direction"], e["counterpart"], e["relation"], e["source"], e["status"])
            if k not in seen:
                seen.add(k)
                deduped.append(e)
        r.edges = deduped


def scan_unresolved_prose(rows_by_key: dict, compiled_pairs: set,
                           skill_md_paths: dict[str, Path]) -> tuple[int, int]:
    """Scans every SKILL.md (the 42 enumerated skill entries' own file) and
    the root CLAUDE.md for plain-substring mentions of any known component
    name. A mention that has no corresponding compiled edge from the
    mentioning skill (or from CLAUDE.md, treated as a fixed doctrine node)
    is emitted as an unresolved_prose_only edge on the mentioned component's
    row. Returns (unresolved_count, compiled_count) as UNIQUE relationship
    counts (not doubled by the two reciprocal edge objects)."""
    unresolved_keys: set = set()

    all_component_names = sorted({k[1] for k in rows_by_key.keys() if k[1]})

    def scan_source(source_label: str, source_path: Path, text: str, owner_key: Optional[tuple]) -> None:
        for name in all_component_names:
            if not name or len(name) < 2:
                continue
            if owner_key is not None and name == owner_key[1]:
                continue  # skip self-mentions
            if name not in text:
                continue
            for target_key, target_row in rows_by_key.items():
                if target_key[1] != name:
                    continue
                if owner_key is not None:
                    pair = frozenset((owner_key, target_key))
                    if pair in compiled_pairs:
                        continue
                    rel_key = ("prose", owner_key, target_key)
                else:
                    rel_key = ("prose", source_label, target_key)
                if rel_key in unresolved_keys:
                    continue
                unresolved_keys.add(rel_key)
                target_row.edges.append({
                    "direction": "inbound",
                    "counterpart": source_label if owner_key is None else owner_key[1],
                    "relation": "mentioned_in_prose",
                    "source": "prose-scan",
                    "status": "unresolved_prose_only",
                })
                if owner_key is not None:
                    owner_row = rows_by_key.get(owner_key)
                    if owner_row is not None:
                        owner_row.edges.append({
                            "direction": "outbound",
                            "counterpart": name,
                            "relation": "mentions_in_prose",
                            "source": "prose-scan",
                            "status": "unresolved_prose_only",
                        })

    for skill_name, skill_md_path in skill_md_paths.items():
        if not skill_md_path.exists():
            continue
        text = read_text(skill_md_path)
        owner_key = ("skill", skill_name)
        scan_source(skill_name, skill_md_path, text, owner_key if owner_key in rows_by_key else None)

    if ROOT_CLAUDE_MD.exists():
        text = read_text(ROOT_CLAUDE_MD)
        scan_source("CLAUDE.md", ROOT_CLAUDE_MD, text, None)

    compiled_count = len(compiled_pairs)
    unresolved_count = len(unresolved_keys)
    return unresolved_count, compiled_count


UNRESOLVED_FRACTION_CAP = 0.40


# ---------------------------------------------------------------------------
# Rendered human view (TASK-018) -- a pure function over the just-written
# data file: re-reads it from disk, never trusts in-memory state.
# ---------------------------------------------------------------------------

def render_markdown_from_file(data_file_path: Path) -> str:
    data = load_json_file(data_file_path)
    lines = []
    lines.append(f"# Asset Inventory ({data['generated_at']})")
    lines.append("")
    lines.append(f"Run `{data['run_id']}`, generator v{data['generator_version']}. "
                  f"Field contract check: {data['field_contract_check']}. "
                  f"Excluded test scaffolding: {data['excluded_test_scaffolding_count']}.")
    lines.append("")
    lines.append("## Documentation drift (CLAUDE.md vs registry.json vs fresh count)")
    lines.append("")
    lines.append("| Field | CLAUDE.md claim | registry.json claim | Generator fresh count |")
    lines.append("| --- | --- | --- | --- |")
    for r in data["documentation_drift"]["rows"]:
        lines.append(f"| {r['field']} | {r['claude_md_claim']} | {r['registry_json_claim']} | {r['generator_fresh_count']} |")
    lines.append("")
    for r in data["documentation_drift"]["rows"]:
        lines.append(f"- **{r['field']}**: {r['scope_note']}")
    lines.append("")

    pce = data.get("plugin_cache_enumeration")
    if pce is not None:
        lines.append("## Plugin cache enumeration")
        lines.append("")
        lines.append(f"Cache root `{pce['cache_root']}`, exists this run: {pce['cache_root_exists']}.")
        lines.append("")
        lines.append(f"Marketplaces: {pce['marketplace_directory_count']}. "
                      f"Physical plugin directories: {pce['physical_plugin_directory_count']}. "
                      f"Installed (installed_plugins.json): {pce['installed_plugin_count']}. "
                      f"Plugin directories with more than one version-folder on disk: "
                      f"{pce['plugin_directories_with_multiple_version_folders']}.")
        lines.append("")
        lines.append(f"Multi-version rule: {pce['multi_version_rule']}")
        lines.append("")
        if pce["notes"]:
            lines.append("Degradation notes:")
            for n in pce["notes"]:
                lines.append(f"- {n}")
            lines.append("")
        lines.append("| Row kind | Count |")
        lines.append("| --- | --- |")
        for k, v in pce["row_counts"].items():
            lines.append(f"| {k} | {v} |")
        lines.append("")

    pr = data.get("plugin_reconciliation")
    if pr is not None:
        lines.append("## Plugin reconciliation (skills/agents available vs registry; loaded vs on disk; disabled)")
        lines.append("")
        lines.append(pr["note"])
        lines.append("")
        sar = pr["skills_available_vs_registry"]
        lines.append(f"- **Skills available vs registry**: fresh installed-scoped plugin skill rows = "
                      f"{sar['fresh_installed_scoped_plugin_skill_rows']}; registry.json plugin-sourced "
                      f"skill count = {sar['registry_json_plugin_sourced_skill_count']}; reload-reported "
                      f"skills available = {sar['reload_reported_skills_available']}. {sar['note']}")
        aar = pr["agents_available_vs_registry"]
        lines.append(f"- **Agents available vs registry**: fresh installed-scoped plugin agent rows = "
                      f"{aar['fresh_installed_scoped_plugin_agent_rows']}; registry.json plugin-sourced "
                      f"agent count = {aar['registry_json_plugin_sourced_agent_count']}. {aar['note']}")
        pl = pr["plugins_loaded_vs_on_disk"]
        lines.append(f"- **Plugins loaded vs on disk**: installed_plugins.json count = "
                      f"{pl['installed_plugins_json_count']}; physical directories on disk = "
                      f"{pl['physical_plugin_directories_on_disk']}; enabled per user settings.json = "
                      f"{pl['enabled_per_user_settings_json']}; reload-reported loaded = "
                      f"{pl['reload_reported_loaded']}. {pl['note']}")
        dp = pr["disabled_or_not_loadable_plugins"]
        lines.append(f"- **Disabled or not-loadable plugins**: explicitly disabled = "
                      f"{dp['explicitly_disabled_per_user_settings_json'] or '[]'}. {dp['note']}")
        lines.append("")

    lines.append(f"## Edges (unresolved_fraction={data['edges']['unresolved_fraction']:.4f}, "
                  f"status={data['edges']['status']})")
    lines.append("")

    rows = data["rows"]
    by_kind: dict[str, list[dict]] = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)

    for kind in ("hook", "skill", "agent", "workflow", "command", "mcp-server",
                 "settings-registration", "telemetry-sink"):
        krows = by_kind.get(kind, [])
        lines.append(f"## kind = {kind} ({len(krows)} rows)")
        lines.append("")
        blocked = [r for r in krows if r["blocked_reason"]]
        clear = [r for r in krows if not r["blocked_reason"]]
        for group_label, group_rows in (("Blocked", blocked), ("Reachable", clear)):
            if not group_rows:
                continue
            lines.append(f"### {group_label} ({len(group_rows)})")
            lines.append("")
            # "NO_SOURCE_FOR_*" is a family of sentinels, not one literal value
            # (2026-08-20: NO_SOURCE_FOR_KIND for workflow/command/mcp-server,
            # NO_SOURCE_FOR_PLUGIN_SKILL / NO_SOURCE_FOR_PLUGIN_HOOK /
            # NO_SOURCE_FOR_UNRESOLVED_PLUGIN_COMPONENT for the plugin-specific
            # no-channel cases) -- matched by prefix so every honest "no
            # evidence channel exists" row lands in the same bucket rather
            # than misreading as a silently-dormant, channel-having row.
            observed = [r for r in group_rows if r["usage"]["total_count"] > 0]
            dormant = [r for r in group_rows if r["usage"]["total_count"] == 0
                       and not r["usage"]["source"].startswith("NO_SOURCE_FOR")]
            no_source = [r for r in group_rows if r["usage"]["source"].startswith("NO_SOURCE_FOR")]
            for sub_label, sub_rows in (("Observed usage", observed), ("Dormant (reachable, zero usage)", dormant),
                                         ("No usage evidence channel", no_source)):
                if not sub_rows:
                    continue
                lines.append(f"**{sub_label}:**")
                lines.append("")
                lines.append("| Name | Provenance | Blocked | Usage total | First seen | Last seen | Reachability items | Edges |")
                lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
                for r in sorted(sub_rows, key=lambda x: x["name"]):
                    blk = ", ".join(r["blocked_reason"]) if r["blocked_reason"] else "-"
                    lines.append(
                        f"| {r['name']} | {r['provenance']} | {blk} | {r['usage']['total_count']} | "
                        f"{r['usage']['first_seen'] or '-'} | {r['usage']['last_seen'] or '-'} | "
                        f"{len(r['reachability'])} | {len(r['edges'])} |"
                    )
                lines.append("")
    lines.append("## Diff vs. previous snapshot")
    lines.append("")
    diff = data["diff"]
    if diff.get("baseline"):
        lines.append(f"Baseline run: no prior snapshot. {len(diff['installed'])} rows recorded as INSTALLED.")
    else:
        lines.append(f"Compared against `{diff['previous_run_id']}`.")
        lines.append(f"- INSTALLED: {len(diff['installed'])}")
        lines.append(f"- REMOVED: {len(diff['removed'])}")
        lines.append(f"- REACHABILITY_CHANGED: {len(diff['reachability_changed'])}")
        lines.append(f"- BLOCKED_STATUS_CHANGED: {len(diff['blocked_status_changed'])}")
    lines.append("")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Snapshot + diff (TASK-019)
# ---------------------------------------------------------------------------

def row_reachability_key(row: dict) -> str:
    return json.dumps(row["reachability"], sort_keys=True)


def row_blocked_key(row: dict) -> str:
    return json.dumps(sorted(row["blocked_reason"]))


def diff_against_previous(new_rows: list[dict], snapshots_dir: Path, current_run_id: str) -> dict:
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(p for p in snapshots_dir.glob("*.json") if p.stem != current_run_id)

    new_by_key = {(r["kind"], r["name"]): r for r in new_rows}

    if not existing:
        return {
            "baseline": True,
            "previous_run_id": None,
            "installed": [{"kind": k, "name": n} for (k, n) in sorted(new_by_key.keys())],
            "removed": [],
            "reachability_changed": [],
            "blocked_status_changed": [],
        }

    prev_path = existing[-1]
    prev_data = load_json_file(prev_path)
    prev_rows = {(r["kind"], r["name"]): r for r in prev_data.get("rows", [])}

    installed = sorted(set(new_by_key) - set(prev_rows))
    removed = sorted(set(prev_rows) - set(new_by_key))
    reachability_changed = []
    blocked_status_changed = []
    for key in sorted(set(new_by_key) & set(prev_rows)):
        new_r = new_by_key[key]
        old_r = prev_rows[key]
        if row_reachability_key(new_r) != row_reachability_key(old_r):
            reachability_changed.append({
                "kind": key[0], "name": key[1],
                "before": old_r["reachability"], "after": new_r["reachability"],
            })
        if row_blocked_key(new_r) != row_blocked_key(old_r):
            blocked_status_changed.append({
                "kind": key[0], "name": key[1],
                "before": old_r["blocked_reason"], "after": new_r["blocked_reason"],
            })

    return {
        "baseline": False,
        "previous_run_id": prev_data.get("run_id"),
        "installed": [{"kind": k, "name": n} for (k, n) in installed],
        "removed": [{"kind": k, "name": n} for (k, n) in removed],
        "reachability_changed": reachability_changed,
        "blocked_status_changed": blocked_status_changed,
    }


# ---------------------------------------------------------------------------
# Main generation pipeline
# ---------------------------------------------------------------------------

def generate(*, governance_log_path: Path = GOVERNANCE_LOG_JSONL_DEFAULT,
             hook_activity_path: Path = HOOK_ACTIVITY_JSONL_DEFAULT,
             aggregates_dir: Path = AGGREGATES_DIR,
             registry_path: Path = REGISTRY_JSON,
             write_output: bool = True,
             run_id: Optional[str] = None,
             skip_freshness_check: bool = False) -> dict:
    """Runs the full generation pipeline. Raises FieldContractError (writing
    no output files) if either sink fails its field-contract precondition.
    Returns the assembled data dict (also written to disk when
    write_output is True)."""

    # FIX 6 (2026-08-19): loud failure if an enumeration root is missing,
    # matching the discipline already applied to the two telemetry sinks.
    require_dir(HOOKS_DIR, "hooks (kind=hook)")
    require_dir(SKILLS_DIR, "skills (kind=skill)")
    require_dir(AGENTS_DIR, "agents (kind=agent)")
    require_dir(WORKFLOWS_DIR, "workflows (kind=workflow)")

    data_file = aggregates_dir / "asset-inventory.json"
    md_file = aggregates_dir / "asset-inventory.md"
    snapshots_dir = aggregates_dir / "asset-inventory-snapshots"

    if run_id is None:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- enumerate everything first, so join keys are known before the
    # single streaming pass over each sink. ----
    # Refuse before reading anything else if the registry cannot be describing
    # current disk state (owner decision 2026-08-22: guard, not chaining).
    # The self-test opts out: it runs against synthetic fixtures and is not
    # measuring registry freshness, and without the opt-out the suite fails
    # whenever anyone edits a hook without regenerating the registry, which is
    # the normal state mid-change. A guard that breaks the test suite is a
    # guard that gets routed around. The real path is unchanged.
    if not skip_freshness_check:
        check_registry_freshness(registry_path, [AGENTS_DIR, SKILLS_DIR, HOOKS_DIR,
                                                 WORKFLOWS_DIR, COMMANDS_DIR])
    registry = load_registry(registry_path)
    registry_agents = registry.get("agents", {})
    registry_skills = registry.get("skills", {})
    registry_plugins = registry.get("plugins", [])

    # ---- plugin cache enumeration (2026-08-20 extension) -- filesystem-only,
    # no sink reads, so it can run before the sink passes below and still
    # respect CON-004 (one streaming pass per SINK; this touches neither
    # sink file). Plugin agent usage-join keys are folded into the match
    # set passed to process_governance_log() below so the existing single
    # pass over governance-log.jsonl also captures plugin agent dispatches
    # without a second read of that file. ----
    plugin_canonical, plugin_manifest_notes = load_installed_plugins_manifest()
    plugin_enabled_map, plugin_settings_notes = load_plugin_enabled_map()
    plugin_skill_agent_components = enumerate_plugin_skills_and_agents(plugin_canonical, plugin_enabled_map)
    plugin_hook_components = enumerate_plugin_hooks(plugin_canonical, plugin_enabled_map)
    plugin_mcp_components = enumerate_plugin_mcp_servers(plugin_canonical, plugin_enabled_map)
    plugin_agent_usage_keys = {
        c.usage_join_key for c in plugin_skill_agent_components
        if c.kind == "agent" and c.usage_join_key
    }

    hook_files_non_test, hook_files_test, hook_files_retired_non_test, hook_files_retired_test = enumerate_hooks()
    hook_stems = sorted(f[:-3] for f in hook_files_non_test)
    hook_retired_stems = sorted(f[:-3] for f in hook_files_retired_non_test)

    # A retired stem colliding with an active top-level stem would break
    # the (kind, name) row-uniqueness invariant used throughout (rows_by_key,
    # the snapshot diff). Not observed in the live harness, but guarded
    # loudly rather than assumed away: the active row wins, the collision
    # is reported, and the retired duplicate is dropped from this run.
    _stem_collisions = sorted(set(hook_stems) & set(hook_retired_stems))
    if _stem_collisions:
        print(f"[asset_inventory] WARNING: retired hook stem(s) collide with an active "
              f"top-level hook stem; active row takes precedence: {_stem_collisions}")
        hook_retired_stems = [s for s in hook_retired_stems if s not in _stem_collisions]
        hook_files_retired_non_test = [f for f in hook_files_retired_non_test if f[:-3] not in _stem_collisions]

    skill_entries = sorted(p.name for p in SKILLS_DIR.iterdir())
    skill_names = skill_entries[:]

    agent_files = sorted(p.name for p in AGENTS_DIR.glob("*.md"))
    agent_names = [f[:-3] for f in agent_files]

    workflow_files = sorted(WORKFLOWS_DIR.glob("*.js"))
    workflow_names = [p.stem for p in workflow_files]

    commands_dir_confirmed = COMMANDS_DIR.is_dir()
    command_names: list[str] = []
    if commands_dir_confirmed:
        command_names = sorted(p.stem for p in COMMANDS_DIR.glob("*.md"))

    mcp_json_confirmed = MCP_JSON.exists()
    mcp_server_names: list[str] = []
    if mcp_json_confirmed:
        mcp_data = load_json_file(MCP_JSON)
        mcp_server_names = sorted(mcp_data.get("mcpServers", {}).keys())

    print(f"[asset_inventory] TASK-013 enumeration source check: "
          f"commands_dir={COMMANDS_DIR} exists={commands_dir_confirmed} "
          f"({len(command_names)} found); "
          f"mcp_json={MCP_JSON} exists={mcp_json_confirmed} "
          f"({len(mcp_server_names)} found)")

    all_agent_and_skill_names = set(agent_names) | set(skill_names)

    # ---- single streaming pass per sink (CON-004), combined with the
    # field-contract self-check (TASK-003 / REQ-008 ASSERT-007). ----
    # Match set includes retired stems (FIX 5) so a retired hook's
    # historical fires join to its own row instead of the skipped counter.
    # O13 (D1): trailing 30-day window bounds derive from this run's
    # generated_at; the cmp forms feed the same single streaming pass
    # per sink (no second read of either sink).
    _o13_ws_iso, _o13_we_iso, _o13_ws_cmp, _o13_we_cmp = window_bounds(generated_at)
    hook_result = process_hook_activity(hook_activity_path, set(hook_stems) | set(hook_retired_stems),
                                        window_start_cmp=_o13_ws_cmp, window_end_cmp=_o13_we_cmp)
    # Match set extended with plugin-qualified agent join keys ('<plugin>:<agent>',
    # e.g. 'pr-review-toolkit:silent-failure-hunter') -- confirmed live in
    # governance-log.jsonl's own agent_type field (see build report). Plugin
    # skill usage has no equivalent: skill_context never carries a
    # colon-qualified value on this machine (verified: 4,192 skill_context
    # items scanned, zero colon-qualified), so skill_names is NOT extended --
    # doing so would risk a false join against an unrelated same-bare-name
    # local skill rather than surface the genuine "no channel" gap.
    gov_result = process_governance_log(
        governance_log_path, set(agent_names) | plugin_agent_usage_keys, set(skill_names),
        set(workflow_names),
        window_start_cmp=_o13_ws_cmp, window_end_cmp=_o13_we_cmp
    )

    # O13 (D3): fingerprint the ACTUAL match sets used by the joins
    # above, so set drift between runs is visible in the header.
    _o13_fingerprint = enumeration_fingerprint(
        set(hook_stems) | set(hook_retired_stems),
        set(agent_names) | plugin_agent_usage_keys,
        set(skill_names),
    )

    if not hook_result["contract_ok"]:
        raise FieldContractError(
            f"FIELD_CONTRACT_ABORT: sink={hook_activity_path} field='hook': "
            f"zero of {hook_result['total_lines']} records carried a non-null 'hook' field. "
            f"Aborting before any output is written (regression guard for the "
            f"hook_activity_report.py line-301 defect class)."
        )
    if not gov_result["contract_ok"]:
        raise FieldContractError(
            f"FIELD_CONTRACT_ABORT: sink={governance_log_path} field='agent_type' "
            f"(on event='agent_dispatched'): zero of {gov_result['total_agent_dispatched']} "
            f"agent_dispatched records carried a non-null 'agent_type' field. "
            f"Aborting before any output is written (regression guard for the "
            f"hook_activity_report.py line-301 defect class)."
        )

    print(f"[asset_inventory] field-contract check PASSED for both sinks "
          f"(hook-activity: {hook_result['total_lines']} lines, "
          f"governance-log: {gov_result['total_agent_dispatched']} agent_dispatched records).")

    # ---- reachability evidence sources ----
    settings_commands = load_settings_hook_commands()
    dispatch_roles = load_dispatch_roles()
    workflow_texts = load_workflow_texts()

    rows: list[Row] = []
    rows_by_key: dict[tuple, Row] = {}
    agent_provenance_fallback: list[str] = []

    # ---- kind=hook ----
    for fname in hook_files_non_test:
        stem = fname[:-3]
        path = HOOKS_DIR / fname
        reach = evd001_for_hook(fname, settings_commands)
        blocked = compute_blocked_reasons(
            kind="hook", has_path=True, provenance="authored-in-harness",
            reachability=reach, evd002_has_any=False, evd002_all_uncorroborated=False,
        )
        usage = usage_from_join(
            hook_result["usage"], stem,
            "hook-activity.jsonl:hook_fire.hook",
            hook_result["skipped"],
        )
        row = Row(name=stem, kind="hook", path=rel(path), provenance="authored-in-harness",
                  reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[("hook", stem)] = row

    # ---- kind=hook, retired population (FIX 5, 2026-08-19) ----
    for fname in hook_files_retired_non_test:
        stem = fname[:-3]
        path = HOOKS_DIR / "retired" / fname
        reach = evd001_for_hook(fname, settings_commands)  # expected empty: retired == deregistered
        blocked = compute_blocked_reasons(
            kind="hook", has_path=True, provenance="authored-in-harness",
            reachability=reach, evd002_has_any=False, evd002_all_uncorroborated=False,
        )
        usage = usage_from_join(
            hook_result["usage"], stem,
            "hook-activity.jsonl:hook_fire.hook",
            hook_result["skipped"],
        )
        row = Row(name=stem, kind="hook", path=rel(path), provenance="authored-in-harness",
                  reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[("hook", stem)] = row

    # ---- kind=hook, import-based reachability pass (FIX 2, 2026-08-19) ----
    # A hook module present on disk but not itself settings-registered can
    # still have a genuine invocation path: another, registered hook
    # Python-imports it as a shared library module. BLK-001's literal
    # definition ("registered nowhere") does not distinguish this from a
    # genuinely orphaned file -- 16 of the 19 (measured: 18) single-code
    # BLK-001 hook rows before this fix were underscore-prefixed helpers
    # or conftest.py, most of them imported by live, registered hooks.
    # Runs over both populations (top-level + retired) after both row
    # loops above, so every hook row already exists to attach evidence to.
    _hook_import_candidates = list(hook_files_non_test) + list(hook_files_retired_non_test)
    _hook_texts: dict[str, tuple[Path, str]] = {}
    for fname in _hook_import_candidates:
        fpath = (HOOKS_DIR / fname) if fname in hook_files_non_test else (HOOKS_DIR / "retired" / fname)
        _hook_texts[fname] = (fpath, read_text(fpath))

    # A module is only a genuine reachability path for the *importED*
    # module if the *importING* module is itself settings-registered
    # (EVD-001) -- importing an equally-orphaned file proves nothing.
    _registered_hook_filenames = {
        fname for fname in _hook_import_candidates
        if evd001_for_hook(fname, settings_commands)
    }

    _import_pattern_cache: dict[str, re.Pattern] = {}

    def _import_pattern(py_stem: str) -> re.Pattern:
        if py_stem not in _import_pattern_cache:
            _import_pattern_cache[py_stem] = re.compile(
                r"(^|\n)\s*(from|import)\s+" + re.escape(py_stem) + r"(\s|\.|$)"
            )
        return _import_pattern_cache[py_stem]

    for fname, (fpath, _unused_text) in _hook_texts.items():
        stem = fname[:-3]
        row = rows_by_key.get(("hook", stem))
        if row is None:
            continue
        pattern = _import_pattern(stem.replace("-", "_"))
        registered_importers = []
        for other_fname, (other_path, other_text) in _hook_texts.items():
            if other_fname == fname or other_fname not in _registered_hook_filenames:
                continue
            if pattern.search(other_text):
                registered_importers.append((other_fname, other_path))
        if not registered_importers:
            continue
        for imp_name, imp_path in registered_importers:
            row.reachability.append(evidence(
                "EVD-005", imp_path,
                f"imported by {imp_name} (itself registered via EVD-001)",
            ))
        row.reachability.sort(key=lambda e: (e["type"], e["source_file"], e["detail"]))
        row.blocked_reason = compute_blocked_reasons(
            kind="hook", has_path=True, provenance=row.provenance,
            reachability=row.reachability, evd002_has_any=False, evd002_all_uncorroborated=False,
        )

    # ---- kind=skill ----
    junction_names: list[str] = []
    for entry_name in skill_entries:
        path = SKILLS_DIR / entry_name
        entry_kind, target = classify_skill_entry(path)
        if entry_kind == "junction":
            provenance = f"junction:{target}"
            junction_names.append(entry_name)
        else:
            provenance = registry_provenance(entry_name, registry_skills, True, agent_provenance_fallback)

        reach = []
        reach += evd002_items_for(entry_name, dispatch_roles)[0]
        reach += evd003_items_for(entry_name, workflow_texts)
        reach += evd004_item_for(entry_name, registry_skills, "skills")
        reach.sort(key=lambda e: (e["type"], e["source_file"], e["detail"]))

        _, evd002_has_any, evd002_all_uncorr = evd002_items_for(entry_name, dispatch_roles)
        blocked = compute_blocked_reasons(
            kind="skill", has_path=True, provenance=provenance,
            reachability=reach, evd002_has_any=evd002_has_any,
            evd002_all_uncorroborated=evd002_all_uncorr,
        )
        usage = usage_from_join(
            gov_result["skill_usage"], entry_name,
            "governance-log.jsonl:agent_dispatched.skill_context[]",
            gov_result["skipped_skill"],
        )
        row = Row(name=entry_name, kind="skill", path=rel(path), provenance=provenance,
                  reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[("skill", entry_name)] = row

    # ---- kind=agent ----
    for fname in agent_files:
        name = fname[:-3]
        path = AGENTS_DIR / fname
        provenance = registry_provenance(name, registry_agents, True, agent_provenance_fallback)

        evd002_items, evd002_has_any, evd002_all_uncorr = evd002_items_for(name, dispatch_roles)
        reach = []
        reach += evd002_items
        reach += evd003_items_for(name, workflow_texts)
        reach += evd004_item_for(name, registry_agents, "agents")
        reach.sort(key=lambda e: (e["type"], e["source_file"], e["detail"]))

        blocked = compute_blocked_reasons(
            kind="agent", has_path=True, provenance=provenance,
            reachability=reach, evd002_has_any=evd002_has_any,
            evd002_all_uncorroborated=evd002_all_uncorr,
        )
        usage = usage_from_join(
            gov_result["agent_usage"], name,
            "governance-log.jsonl:agent_dispatched.agent_type",
            gov_result["skipped_agent"],
        )
        row = Row(name=name, kind="agent", path=rel(path), provenance=provenance,
                  reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[("agent", name)] = row

    if agent_provenance_fallback:
        print(f"[asset_inventory] TASK-007 fallback rule applied for on-disk components absent "
              f"from registry.json (classified authored-in-harness by disk presence): "
              f"{sorted(set(agent_provenance_fallback))}")

    # ---- kind=skill / kind=agent, plugin-sourced (2026-08-20 extension) ----
    # Reuses the SAME evd002/evd003/evd004 evidence-gathering functions the
    # local skill/agent loops above use, by bare name -- a plugin skill/agent
    # can be named in a DISPATCHES.json role, cited in a workflow .js, or
    # listed in registry.json exactly like a local one, and those sources
    # only ever know bare names. Row identity (rows_by_key key) is the
    # provenance-qualified name; evidence lookups use the bare name.
    _skip_collisions: list = []
    for comp in plugin_skill_agent_components:
        reach = list(comp.evidence)  # EVD-006, or empty if the plugin is disabled
        evd002_items, evd002_has_any, evd002_all_uncorr = ([], False, False)
        if comp.kind == "agent":
            evd002_items, evd002_has_any, evd002_all_uncorr = evd002_items_for(comp.bare_name, dispatch_roles)
            reach += evd002_items
        reach += evd003_items_for(comp.bare_name, workflow_texts)
        bucket = registry_skills if comp.kind == "skill" else registry_agents
        field_path = "skills" if comp.kind == "skill" else "agents"
        reach += evd004_item_for(comp.bare_name, bucket, field_path)
        reach.sort(key=lambda e: (e["type"], e["source_file"], e["detail"]))

        blocked = compute_blocked_reasons(
            kind=comp.kind, has_path=True, provenance=comp.provenance,
            reachability=reach, evd002_has_any=evd002_has_any,
            evd002_all_uncorroborated=evd002_all_uncorr,
        )
        if comp.kind == "agent" and comp.usage_join_key:
            usage = usage_from_join(
                gov_result["agent_usage"], comp.usage_join_key,
                f"governance-log.jsonl:agent_dispatched.agent_type (plugin-qualified "
                f"'{comp.usage_join_key}')",
                gov_result["skipped_agent"],
            )
        else:
            # Plugin skill usage: no observable channel. skill_context never
            # carries a plugin-qualified value on this machine (verified
            # empirically -- see the gov_result match-set comment above),
            # and joining on bare name risks misattributing a same-named
            # local skill's fires. Honest sentinel, not a fabricated zero.
            usage = empty_usage("NO_SOURCE_FOR_PLUGIN_SKILL")

        key = (comp.kind, comp.qualified_name)
        if key in rows_by_key:
            _skip_collisions.append(key)
            continue
        row = Row(name=comp.qualified_name, kind=comp.kind,
                  path=rel(comp.path) if comp.path else None, provenance=comp.provenance,
                  reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[key] = row

    # ---- kind=hook, plugin-sourced (2026-08-20 extension) ----
    for comp in plugin_hook_components:
        reach = list(comp.evidence)  # EVD-007, or empty if the plugin is disabled
        blocked = compute_blocked_reasons(
            kind="hook", has_path=True, provenance=comp.provenance,
            reachability=reach, evd002_has_any=False, evd002_all_uncorroborated=False,
        )
        # Plugin hook usage: no observable channel. hook-activity.jsonl's
        # 'hook' field never carries a plugin hook script name on this
        # machine (verified empirically: the only unmatched values across
        # 96,254 lines are test/junk artifacts -- 'SELF-TEST-hook', 'None',
        # 'x' -- never a real plugin script stem), because plugin hook
        # scripts are external, third-party code not wired to this vault's
        # shared hook-activity logging helper.
        usage = empty_usage("NO_SOURCE_FOR_PLUGIN_HOOK")
        key = ("hook", comp.qualified_name)
        if key in rows_by_key:
            _skip_collisions.append(key)
            continue
        row = Row(name=comp.qualified_name, kind="hook", path=rel(comp.path),
                  provenance=comp.provenance, reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[key] = row

    # ---- kind=mcp-server, plugin-sourced (2026-08-20 extension) ----
    # O9 increment 1 (2026-09-01) gate-event join. Plugin-sourced tool
    # calls reach the gate events as 'mcp__plugin_<plugin>_<server>__<tool>'
    # (confirmed live: mcp__plugin_github_github__delete_file), so the join
    # key is REVERSE-CONSTRUCTED from each row's own (plugin_name,
    # bare_name) pair and compared by exact string equality against the
    # extracted pre-'__' segment: never by forward-splitting the segment on
    # underscores (a plugin or server name with an internal underscore
    # would mis-split) and never by substring containment. If two
    # components ever construct the same key, NONE of the claimants gets
    # the usage (the key is removed from the join view, so each claimant
    # takes the miss path: gated source, count 0); attaching on an
    # ambiguous match would double-count. Today's rows have unique
    # (server, plugin) pairs, so the guard is a tripwire, not a live
    # branch.
    _mcp_gate_skipped = sum(gov_result["unmatched_mcp_gate_values"].values())
    _plugin_gate_claims: dict[str, list] = {}
    for comp in plugin_mcp_components:
        _plugin_gate_claims.setdefault(
            f"plugin_{comp.plugin_name}_{comp.bare_name}", []).append(comp)
    _ambiguous_gate_keys = {k for k, v in _plugin_gate_claims.items() if len(v) > 1}
    if _ambiguous_gate_keys:
        print(f"[asset_inventory] WARNING: {len(_ambiguous_gate_keys)} reverse-constructed "
              f"plugin MCP gate join key(s) claimed by more than one component; attaching "
              f"gate usage to NONE of the claimants: {sorted(_ambiguous_gate_keys)}")
    _plugin_gate_join_view = {k: v for k, v in gov_result["mcp_gate_usage"].items()
                               if k not in _ambiguous_gate_keys}
    for comp in plugin_mcp_components:
        reach = list(comp.evidence)  # EVD-008, or empty if the plugin is disabled
        blocked = compute_blocked_reasons(
            kind="mcp-server", has_path=True, provenance=comp.provenance,
            reachability=reach, evd002_has_any=False, evd002_all_uncorroborated=False,
        )
        constructed = f"plugin_{comp.plugin_name}_{comp.bare_name}"
        usage = usage_from_join(_plugin_gate_join_view, constructed,
                                 MCP_GATE_USAGE_SOURCE, _mcp_gate_skipped)
        key = ("mcp-server", comp.qualified_name)
        if key in rows_by_key:
            _skip_collisions.append(key)
            continue
        row = Row(name=comp.qualified_name, kind="mcp-server", path=rel(comp.path),
                  provenance=comp.provenance, reachability=reach, blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[key] = row

    # ---- kind=skill / kind=agent, BLK-004 registry-vs-cache diff rows ----
    # See the BLK-004 restoration comment above BLK_MEANINGS. found_bare_names
    # is this run's own installed-scoped walk; compute_blk004_rows() diffs it
    # against registry.json's (unscoped, cross-version) plugin-sourced claims.
    found_bare_names = {
        "skill": {c.bare_name for c in plugin_skill_agent_components if c.kind == "skill"},
        "agent": {c.bare_name for c in plugin_skill_agent_components if c.kind == "agent"},
    }
    blk004_candidates = compute_blk004_rows(registry, found_bare_names)
    for cand in blk004_candidates:
        blocked = compute_blocked_reasons(
            kind=cand["kind"], has_path=False, provenance=cand["provenance"],
            reachability=[], evd002_has_any=False, evd002_all_uncorroborated=False,
        )
        usage = empty_usage("NO_SOURCE_FOR_UNRESOLVED_PLUGIN_COMPONENT")
        key = (cand["kind"], cand["name"])
        if key in rows_by_key:
            _skip_collisions.append(key)
            continue
        row = Row(name=cand["name"], kind=cand["kind"], path=None, provenance=cand["provenance"],
                  reachability=[], blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[key] = row

    if _skip_collisions:
        print(f"[asset_inventory] WARNING: {len(_skip_collisions)} plugin-sourced row(s) "
              f"collided with an existing (kind, name) key already in rows_by_key and were "
              f"skipped rather than silently overwriting: {_skip_collisions[:10]}")

    # ---- kind=workflow ----
    # O9 increment 2 (2026-09-01): join the subagent-quality-check pass
    # signal, identity-bearing since the same-date dispatch-site plumbing
    # (WORKFLOW-ID marker; see WORKFLOW_USAGE_SOURCE). A row with no
    # identified completion carries the explicit AWAITING_FIRST_OBSERVATION
    # sentinel plus a note -- never a silent NO_SOURCE_FOR_KIND, and never
    # a count fabricated from the kind-level legacy population.
    _wf_skipped = (gov_result["workflow_pass_unattributed"]
                   + sum(gov_result["unmatched_workflow_values"].values()))
    for wf_path in workflow_files:
        wf_name = wf_path.stem
        reach = evd004_item_for(wf_name, {}, "workflows")  # registry.json has no workflows array
        if wf_name in gov_result["workflow_usage"]:
            usage = usage_from_join(gov_result["workflow_usage"], wf_name,
                                    WORKFLOW_USAGE_SOURCE, _wf_skipped)
        else:
            usage = empty_usage(WORKFLOW_AWAITING_SENTINEL)
            usage["skipped_records_in_join"] = _wf_skipped
            usage["note"] = ("workflow-identity plumbing landed 2026-09-01: zero means "
                             "'no identified completion observed since the plumbing', "
                             "never 'idle'; pre-plumbing pass records carry no workflow "
                             "identity and are counted only in the header's "
                             "workflow_pass_unattributed")
        row = Row(name=wf_name, kind="workflow", path=rel(wf_path), provenance="authored-in-harness",
                  reachability=reach, blocked_reason=[], usage=usage)
        rows.append(row)
        rows_by_key[("workflow", wf_name)] = row

    # workflow reachability, part 2: a workflow is reachable if it is cited
    # as an EVD-003 source for some other component.
    for wf_path, text in workflow_texts.items():
        wf_name = wf_path.stem
        row = rows_by_key[("workflow", wf_name)]
        cited_for = [n for n in sorted(all_agent_and_skill_names)
                     if n and re.search(r"""['"]""" + re.escape(n) + r"""['"]""", text)]
        if cited_for:
            row.reachability.append(evidence(
                "EVD-003", wf_path,
                f"cites {len(cited_for)} known component name(s) as string literals: {cited_for}",
            ))
        row.blocked_reason = compute_blocked_reasons(
            kind="workflow", has_path=True, provenance=row.provenance,
            reachability=row.reachability, evd002_has_any=False, evd002_all_uncorroborated=False,
        )

    # ---- kind=command ----
    for cname in command_names:
        path = COMMANDS_DIR / f"{cname}.md"
        row = Row(name=cname, kind="command", path=rel(path), provenance="authored-in-harness",
                  reachability=[], blocked_reason=["BLK-005"], usage=empty_usage("NO_SOURCE_FOR_KIND"))
        rows.append(row)
        rows_by_key[("command", cname)] = row

    # ---- kind=mcp-server ----
    for mname in mcp_server_names:
        # No EVD-001..004 code covers .mcp.json / enabledMcpjsonServers
        # registration; this is a real gap in the closed evidence taxonomy,
        # not an omission in this generator (see build report). Usage (O9
        # increment 1): gate-event join by the short .mcp.json server name
        # (breaker events carry it in 'server'; guard denies reach it via
        # the extracted pre-'__' segment). A zero-event server keeps
        # total_count 0 but carries the caveat-labeled source: the
        # designed sparse-floor semantics, not evidence of idleness.
        row = Row(name=mname, kind="mcp-server", path=rel(MCP_JSON), provenance="authored-in-harness",
                  reachability=[], blocked_reason=["BLK-005"],
                  usage=usage_from_join(gov_result["mcp_gate_usage"], mname,
                                         MCP_GATE_USAGE_SOURCE, _mcp_gate_skipped))
        rows.append(row)
        rows_by_key[("mcp-server", mname)] = row

    # ---- kind=settings-registration (O1, 2026-08-30 harness-spec
    # extension). Two compiled sub-populations under one kind: MCP server
    # registrations (.mcp.json) and hook-command registrations
    # (settings.json + settings.local.json). SECURITY: only structural
    # facts ever reach a row -- server name, command, transport type, env
    # variable KEY NAMES for an MCP entry, event/matcher/command for a
    # settings hook entry -- .mcp.json's env values and header values (live
    # API keys, bearer tokens) are never copied anywhere in this
    # generator's output; see load_mcp_registration_entries(). An entry
    # that does not resolve to a known on-disk asset is still emitted, with
    # blocked_reason=['BLK-006'], rather than dropped. ----
    settings_registration_rows: list[Row] = []
    for entry in load_mcp_registration_entries(MCP_JSON):
        rname = f"mcp:{entry['name']}"
        detail_parts = [f"server={entry['name']!r}"]
        if entry["command"]:
            detail_parts.append(f"command={entry['command']!r}")
        if entry["type"]:
            detail_parts.append(f"type={entry['type']!r}")
        if entry["env_keys"]:
            detail_parts.append(f"env_keys={entry['env_keys']}")
        reach = [evidence("EVD-009", MCP_JSON, "; ".join(detail_parts))]
        blocked = [] if entry["resolved"] else ["BLK-006"]
        # O9 increment 1: same gate-event join as the kind=mcp-server rows,
        # by the entry's own short name, same caveat-labeled source.
        row = Row(name=rname, kind="settings-registration", path=rel(MCP_JSON),
                  provenance="authored-in-harness", reachability=reach,
                  blocked_reason=blocked,
                  usage=usage_from_join(gov_result["mcp_gate_usage"], entry["name"],
                                         MCP_GATE_USAGE_SOURCE, _mcp_gate_skipped))
        rows.append(row)
        rows_by_key[("settings-registration", rname)] = row
        settings_registration_rows.append(row)

    _settings_reg_resolution_candidates = list(hook_files_non_test) + list(hook_files_retired_non_test)
    for entry in load_settings_registration_entries():
        sfile = entry["source_file"]
        rname = f"{sfile.name}:{entry['event']}[{entry['block_idx']}.{entry['item_idx']}]"
        command = entry["command"]
        reach = [evidence("EVD-009", sfile,
                           f"event={entry['event']} matcher={entry['matcher']!r} command={command!r}")]
        matched_fname = next((f for f in _settings_reg_resolution_candidates if f in command), None)
        if matched_fname:
            reach.append(evidence("EVD-001", sfile, f"resolves to hook '{matched_fname[:-3]}'"))
        reach.sort(key=lambda e: (e["type"], e["source_file"], e["detail"]))
        blocked = [] if matched_fname else ["BLK-006"]
        if matched_fname:
            # O9 increment 1: propagation of an in-process value, not a new
            # join. hook_result["usage"] is computed once in this same
            # generate() call and already contains retired stems (FIX 5),
            # so a registration resolving to a retired hook propagates its
            # historical count correctly.
            usage = usage_from_join(
                hook_result["usage"], matched_fname[:-3],
                "hook-activity.jsonl:hook_fire.hook (via resolved hook registration)",
                hook_result["skipped"],
            )
        else:
            # BLK-006 carve-out (O9 increment 1): a registration that
            # resolves to no enumerated hook file has no hook to copy usage
            # from. Distinct code, never blended into NO_SOURCE_FOR_KIND
            # and never a fabricated source; the row's blocked_reason
            # ['BLK-006'] above stays on the row untouched.
            usage = empty_usage("UNRESOLVED_REGISTRATION")
        row = Row(name=rname, kind="settings-registration", path=rel(sfile),
                  provenance="authored-in-harness", reachability=reach,
                  blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[("settings-registration", rname)] = row
        settings_registration_rows.append(row)

    # ---- kind=telemetry-sink (O1, 2026-08-30 harness-spec extension).
    # Row population is the compiled union from load_known_telemetry_sinks()
    # (the two hardcoded default sinks plus telemetry-vocabulary.json's own
    # declared sinks). Reachability evidence cross-references "the existing
    # hook enumeration" (hook_files_non_test / hook_files_retired_non_test,
    # already computed above for kind=hook) against each sink's declared
    # writer stems, so a stale writer (named in the vocabulary but no
    # longer on disk) is silently excluded from evidence rather than
    # fabricated. A sink whose backing file cannot be found in either known
    # location is still emitted, with blocked_reason=['BLK-006'] and
    # path=None, rather than dropped. ----
    known_sinks, telemetry_vocab_notes = load_known_telemetry_sinks()
    telemetry_sink_rows: list[Row] = []
    for sink_name in sorted(known_sinks.keys()):
        sink_path = resolve_sink_path(sink_name)
        reach = []
        for stem in sorted(known_sinks[sink_name]):
            if ("hook", stem) not in rows_by_key:
                continue
            candidate = HOOKS_DIR / f"{stem}.py"
            if not candidate.is_file():
                candidate = HOOKS_DIR / "retired" / f"{stem}.py"
            if not candidate.is_file():
                continue
            reach.append(evidence("EVD-010", candidate,
                                   f"named as a writer for sink '{sink_name}' in "
                                   f"telemetry-vocabulary.json"))
        reach.sort(key=lambda e: (e["type"], e["source_file"], e["detail"]))
        blocked = [] if sink_path is not None else ["BLK-006"]
        # O9 increment 1: a sink's usage evidence is its own line count.
        # The two streamed sinks reuse totals already computed this run (no
        # new read); any other resolvable sink gets the one authorized
        # stream-and-count (today: plain-language-warnings.jsonl). A sink
        # whose file cannot be found keeps NO_SOURCE_FOR_KIND alongside its
        # BLK-006. Second evidence line: the sum of this run's observed
        # fire counts for the sink's own EVD-010 writer stems. No
        # first_seen/last_seen: a line count carries no span, and stamping
        # one would fabricate timestamps.
        if sink_name == HOOK_ACTIVITY_JSONL_DEFAULT.name:
            _sink_total = hook_result["total_lines"]
        elif sink_name == GOVERNANCE_LOG_JSONL_DEFAULT.name:
            _sink_total = gov_result["total_lines"]
        elif sink_path is not None:
            _sink_total = count_sink_lines(sink_path)
        else:
            _sink_total = None
        if _sink_total is None:
            usage = empty_usage("NO_SOURCE_FOR_KIND")
        else:
            _writer_sum = sum(
                hook_result["usage"][stem]["count"]
                for stem in known_sinks[sink_name]
                if stem in hook_result["usage"]
            )
            usage = {
                "total_count": _sink_total,
                "first_seen": None,
                "last_seen": None,
                "source": "self:total_lines (sink line count, this run's own stream)",
                "skipped_records_in_join": 0,
                "writer_fire_count_sum": _writer_sum,
                "writer_fire_count_source": (
                    "hook-activity.jsonl:hook_fire.hook summed over this sink's "
                    "EVD-010 writer stems (telemetry-vocabulary.json)"),
            }
        row = Row(name=sink_name, kind="telemetry-sink",
                  path=rel(sink_path) if sink_path is not None else None,
                  provenance="authored-in-harness", reachability=reach,
                  blocked_reason=blocked, usage=usage)
        rows.append(row)
        rows_by_key[("telemetry-sink", sink_name)] = row
        telemetry_sink_rows.append(row)

    # ---- edges compiler (TASK-014): EVD-001/002/003/004/005-sourced
    # compiled edges, derived directly from each row's already-computed
    # reachability evidence, so there is exactly one place edges are
    # decided. (FIX 1, 2026-08-19: the EVD-001 branch was missing
    # entirely -- see build report -- so all 76 hook rows' EVD-001
    # reachability compiled zero resolved edges before this fix.) ----
    compiled_pairs: set = set()
    for (kind, name), row in rows_by_key.items():
        for ev in row.reachability:
            source_path = Path(ev["source_file"])
            if ev["type"] == "EVD-001":
                # Settings-file registration: hook -> the settings file
                # that registers it. settings.json/settings.local.json are
                # not asset rows themselves, so this mirrors the EVD-004
                # fixed-node pattern below (a resolved edge recorded
                # directly on the hook's own row) rather than
                # add_edge_pair, which requires both endpoints to be real
                # rows. Multiple EVD-001 items for the same hook (one per
                # event/matcher) collapse to one edge per distinct
                # settings file via sort_edges' de-duplication.
                settings_file_name = source_path.name
                row.edges.append({
                    "direction": "inbound",
                    "counterpart": settings_file_name,
                    "relation": "registered_in",
                    "source": "EVD-001",
                    "status": "resolved",
                })
                compiled_pairs.add(frozenset(((kind, name), ("settings-file", settings_file_name))))
            elif ev["type"] == "EVD-005":
                # Python-import reachability (FIX 2, new evidence code --
                # see build report). source_file is the importing hook's
                # own path; the importer is itself a real row, so this
                # compiles as a normal two-endpoint edge via add_edge_pair,
                # unlike EVD-001/004's fixed-node pattern.
                importer_stem = source_path.stem
                if ("hook", importer_stem) in rows_by_key:
                    add_edge_pair(rows_by_key, ("hook", importer_stem), (kind, name),
                                  "imports", "EVD-005", "resolved", compiled_pairs)
            elif ev["type"] == "EVD-002":
                # dispatch-contract role: skill -> agent. source_file is the
                # DISPATCHES.json's repo-relative path, e.g.
                # ".claude/skills/process-research/DISPATCHES.json"; the
                # DISPATCHES.json's own parent directory is the skill dir,
                # regardless of how many leading path segments precede it.
                skill_dir_name = source_path.parent.name
                if ("skill", skill_dir_name) in rows_by_key:
                    add_edge_pair(rows_by_key, ("skill", skill_dir_name), (kind, name),
                                  "dispatches", "EVD-002", "resolved", compiled_pairs)
            elif ev["type"] == "EVD-003" and kind != "workflow":
                # A workflow row's own EVD-003 evidence is a self-descriptive
                # "cited by N components" summary (see the reciprocal
                # reachability step below), not a citation of the workflow
                # itself from within that same file -- excluding kind ==
                # "workflow" here prevents a spurious self-edge.
                if source_path.parent.name == "workflows":
                    wf_name = source_path.stem
                    if ("workflow", wf_name) in rows_by_key:
                        add_edge_pair(rows_by_key, ("workflow", wf_name), (kind, name),
                                      "invokes", "EVD-003", "resolved", compiled_pairs)
            elif ev["type"] == "EVD-004":
                # registry.json is a cataloging source, not a second asset
                # endpoint; record it as a resolved edge to a fixed
                # "registry.json" node directly on the component's own row.
                row.edges.append({
                    "direction": "inbound",
                    "counterpart": "registry.json",
                    "relation": "cataloged_in",
                    "source": "EVD-004",
                    "status": "resolved",
                })
                compiled_pairs.add(frozenset(((kind, name), ("registry.json", name))))
            elif ev["type"] == "EVD-009":
                # Settings-registration structural entry (O1, 2026-08-30):
                # the declaring file (.mcp.json, settings.json, or
                # settings.local.json) is a declaring source, not a second
                # asset row -- same fixed-node pattern as EVD-004 above.
                declaring_file_name = source_path.name
                row.edges.append({
                    "direction": "inbound",
                    "counterpart": declaring_file_name,
                    "relation": "declared_in",
                    "source": "EVD-009",
                    "status": "resolved",
                })
                compiled_pairs.add(frozenset(((kind, name), ("settings-file", declaring_file_name))))
            elif ev["type"] == "EVD-010":
                # Telemetry-sink writer evidence (O1, 2026-08-30): the
                # writer is a real hook row, so this is a genuine
                # two-endpoint edge via add_edge_pair, mirroring EVD-005.
                writer_stem = source_path.stem
                if ("hook", writer_stem) in rows_by_key:
                    add_edge_pair(rows_by_key, ("hook", writer_stem), (kind, name),
                                  "writes_to", "EVD-010", "resolved", compiled_pairs)
            elif ev["type"] in ("EVD-006", "EVD-007", "EVD-008"):
                # Plugin-native reachability (2026-08-20 extension): the
                # plugin itself, not another row, is the counterpart --
                # mirrors the EVD-004 fixed-node pattern above (registry.json
                # is a cataloging source, not a second asset; a plugin is a
                # declaring/registering source, not a second asset either).
                relation = {"EVD-006": "declared_by_plugin", "EVD-007": "registered_by_plugin",
                            "EVD-008": "declared_by_plugin"}[ev["type"]]
                row.edges.append({
                    "direction": "inbound",
                    "counterpart": row.provenance,
                    "relation": relation,
                    "source": ev["type"],
                    "status": "resolved",
                })
                compiled_pairs.add(frozenset(((kind, name), ("plugin", row.provenance))))

    sort_edges(rows)

    # ---- unresolved prose scan (TASK-015) ----
    skill_md_paths = {s: SKILLS_DIR / s / "SKILL.md" for s in skill_entries}
    unresolved_count, compiled_count = scan_unresolved_prose(rows_by_key, compiled_pairs, skill_md_paths)
    sort_edges(rows)
    denom = unresolved_count + compiled_count
    unresolved_fraction = (unresolved_count / denom) if denom > 0 else 0.0
    edges_status = "SCOPE_INSUFFICIENT" if unresolved_fraction > UNRESOLVED_FRACTION_CAP else "OK"

    # ---- documentation drift report (TASK-010) ----
    fresh_counts = {
        "agents": len(agent_files),
        "skills": len(skill_entries),
        "plugins_installed": len(registry_plugins),
        "plugins_enabled": sum(1 for p in registry_plugins if p.get("enabled")),
    }
    drift = build_documentation_drift_report(registry, fresh_counts)

    # ---- assemble rows, sorted deterministically ----
    # A recorded use outranks every reachability inference above it, so this
    # runs last, after the usage join has populated every row.
    usage_cleared = suppress_blocked_by_usage(rows)
    if usage_cleared:
        print(f"[asset_inventory] recorded usage cleared BLK-001/BLK-005 from "
              f"{usage_cleared} row(s); a use outranks a reachability inference.",
              file=sys.stderr)

    rows.sort(key=lambda r: (r.kind, r.name))

    # DEL-003 GAP-1 close (2026-08-24): stamp the divergence columns before the rows
    # are frozen into dicts, so every row carries whether a published twin exists and
    # whether it differs. Runs last so it sees the final row set.
    twin_summary = stamp_twins(rows)
    print("[asset_inventory] twins: " + ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(twin_summary.items())), file=sys.stderr)

    # O14 (2026-09-01): forward-persistence of the twin list (metric 3).
    # `counts` is the exact dict the stderr line above prints, so the two
    # match by construction; `divergent` is every divergent row projected
    # to (kind, name, path) and sorted by that triple; `kind_set` is the
    # distinct kinds over ALL rows this run, recorded so a population
    # change (the O1 kind extension is the documented confound) is visible
    # in any snapshot comparison. Snapshot persistence itself lives in a
    # separate standalone script this generator never imports or invokes:
    # one snapshot per scorecard assembly, never silently per generator run.
    twins_block = {
        "counts": twin_summary,
        "kind_set": sorted({r.kind for r in rows}),
        "divergent": sorted(
            ({"kind": r.kind, "name": r.name, "path": r.path}
             for r in rows if r.twin_state == "divergent"),
            key=lambda d: (d["kind"], d["name"], d["path"])),
    }

    row_dicts = [r.to_dict() for r in rows]

    diff = diff_against_previous(row_dicts, snapshots_dir, run_id)

    # ---- plugin cache enumeration + reconciliation facts (2026-08-20) ----
    # A fresh, independent directory count -- deliberately NOT reused from
    # plugin_canonical -- so this figure can be compared against
    # installed_plugins.json's own key count as a cross-check (both read 36
    # on this machine, i.e. every physical plugin-name directory has
    # exactly one install record and vice versa).
    _marketplace_count = 0
    _physical_plugin_dirs = 0
    _multi_version_plugin_count = 0
    _multi_version_examples: list = []
    if PLUGIN_CACHE_ROOT.is_dir():
        for _mkt_dir in sorted(PLUGIN_CACHE_ROOT.iterdir()):
            if not _mkt_dir.is_dir():
                continue
            _marketplace_count += 1
            for _plugin_dir in sorted(_mkt_dir.iterdir()):
                if not _plugin_dir.is_dir():
                    continue
                _physical_plugin_dirs += 1
                _version_dirs = [p for p in _plugin_dir.iterdir() if p.is_dir()]
                if len(_version_dirs) > 1:
                    _multi_version_plugin_count += 1
                    _multi_version_examples.append({
                        "plugin_dir": f"{_mkt_dir.name}/{_plugin_dir.name}",
                        "version_folder_count": len(_version_dirs),
                    })

    _plugin_row_counts = {"skill": 0, "agent": 0, "hook": 0, "mcp-server": 0}
    for _r in row_dicts:
        if _r["provenance"].startswith("plugin:") and _r["path"] is not None:
            _plugin_row_counts[_r["kind"]] = _plugin_row_counts.get(_r["kind"], 0) + 1

    plugin_cache_enumeration = {
        "cache_root": str(PLUGIN_CACHE_ROOT),
        "cache_root_exists": PLUGIN_CACHE_ROOT.is_dir(),
        "multi_version_rule": (
            "One plugin key in installed_plugins.json ('<plugin-name>@<marketplace>') is ONE "
            "enumeration root: its own installPath. Every other version-folder physically "
            "present under the same plugin-name directory in the cache (a stale prior "
            "install, an inactive marketplace-resync snapshot, a manual .bak copy) is "
            "excluded entirely from row generation -- never walked, never counted. Rows are "
            "keyed by '<bare-name>@<plugin-name>@<marketplace>', so a genuine name collision "
            "across two DIFFERENT installed plugins (confirmed live: 'code-reviewer' in both "
            "feature-dev and pr-review-toolkit; 'atlassian' as an MCP server name in both the "
            "atlassian plugin and jira-toolkit; 'supabase' as an MCP server name in both the "
            "supabase plugin and this vault's own root .mcp.json) produces two distinct rows "
            "rather than a silent overwrite."
        ),
        "notes": plugin_manifest_notes + plugin_settings_notes,
        "marketplace_directory_count": _marketplace_count,
        "physical_plugin_directory_count": _physical_plugin_dirs,
        "installed_plugin_count": len(plugin_canonical),
        "plugin_directories_with_multiple_version_folders": _multi_version_plugin_count,
        "multi_version_examples": _multi_version_examples,
        "row_counts": {**_plugin_row_counts, "blk004_unresolved_registry_entries": len(blk004_candidates)},
    }

    _reg_plugin_skill_names = {n for n, v in registry_skills.items()
                                if str(v.get("source", "")).startswith("plugin:")}
    _reg_plugin_agent_names = {n for n, v in registry_agents.items()
                                if str(v.get("source", "")).startswith("plugin:")}
    _enabled_plugin_keys = [k for k in plugin_canonical if bool(plugin_enabled_map.get(k, True))]
    _disabled_plugin_keys = sorted(k for k in plugin_canonical if not bool(plugin_enabled_map.get(k, True)))

    plugin_reconciliation = {
        "note": (
            "Three reconciliation facts a 2026-08-19 plugin-reload surfaced, computed fresh "
            "from files on this run wherever a file-based signal exists. The reload's own "
            "runtime-reported numbers are quoted for reference only where this generator has "
            "no file to independently re-derive them from -- each field's own note says which."
        ),
        "skills_available_vs_registry": {
            "fresh_installed_scoped_plugin_skill_rows": _plugin_row_counts["skill"],
            "registry_json_plugin_sourced_skill_count": len(_reg_plugin_skill_names),
            "reload_reported_skills_available": 281,
            "note": (
                "fresh_installed_scoped_plugin_skill_rows is this run's own walk of each "
                "plugin's CANONICAL installed version only. registry_json_plugin_sourced_"
                "skill_count is registry.json's own count, built by generate_registry.py's "
                "scan_plugin_skills() -- an UNSCOPED recursive scan of the entire cache "
                "(every stale version-folder included), deduplicated by bare name only. The "
                "two are expected to diverge; the divergence IS the reconciliation. "
                "reload_reported_skills_available (281) is the plugin-reload's own runtime "
                "count of every skill actually registered in that live session -- a third, "
                "independent measurement this generator has no file to re-derive; quoted, "
                "not computed."
            ),
        },
        "agents_available_vs_registry": {
            "fresh_installed_scoped_plugin_agent_rows": _plugin_row_counts["agent"],
            "registry_json_plugin_sourced_agent_count": len(_reg_plugin_agent_names),
            "note": (
                "Same scope divergence as the skills row above, applied to agents "
                "(generate_registry.py's scan_plugin_agents(), same unscoped-cache/"
                "dedup-by-name construction)."
            ),
        },
        "plugins_loaded_vs_on_disk": {
            "installed_plugins_json_count": len(plugin_canonical),
            "physical_plugin_directories_on_disk": _physical_plugin_dirs,
            "enabled_per_user_settings_json": len(_enabled_plugin_keys),
            "reload_reported_loaded": 35,
            "note": (
                "installed_plugins_json_count and enabled_per_user_settings_json are both "
                "real, file-based counts computed this run. physical_plugin_directories_on_"
                "disk is a fresh, independent directory count included to show it agrees "
                "with installed_plugins_json_count (both equal on this machine -- every "
                "physical plugin-name directory has exactly one install record and vice "
                "versa). reload_reported_loaded (35) is the plugin-reload's own runtime "
                "count of plugins that actually initialized in that session; no file this "
                "generator reads records per-plugin load success or failure, so it cannot "
                "independently re-derive 35, nor identify which plugin failed. That is a "
                "genuine gap in file-based evidence, not an oversight: 'loaded' is runtime "
                "state, not disk state."
            ),
        },
        "disabled_or_not_loadable_plugins": {
            "explicitly_disabled_per_user_settings_json": _disabled_plugin_keys,
            "note": (
                "This is the owner's literal 'what can I NOT use and why' case for plugins. "
                "explicitly_disabled_per_user_settings_json is real and complete: every "
                "installed_plugins.json key whose enabledPlugins value in the user-level "
                "settings.json is explicitly False. The plugin-reload's separately reported "
                "'one plugin failed to load' is NOT the same fact as 'disabled' -- a plugin "
                "can be enabled in settings.json and still fail to load at runtime (a "
                "manifest error, a missing dependency, a crash during plugin "
                "initialization), and no file this generator can read distinguishes that "
                "case from a healthy one. This generator can name every DISABLED plugin; it "
                "cannot name which enabled plugin, if any, is currently failing to load."
            ),
        },
    }

    # ---- O13: metric-1 stable-definition header blocks (window, skip
    # taxonomy, fingerprint). Pure assembly over counters the streaming
    # passes above already collected; neither sink is re-read here. ----
    _o13_membership = {
        "builtin_floor": BUILTIN_DISPATCH_FLOOR,
        "skill_names": set(skill_names),
        "agent_match_set": set(agent_names) | plugin_agent_usage_keys,
        "plugin_agent_bare_names": {k.rsplit(":", 1)[-1] for k in plugin_agent_usage_keys},
    }
    _o13_hook_unparseable = hook_result["skipped"] - sum(hook_result["unmatched_values"].values())
    _o13_hook_tax_all = classify_skips(
        hook_result["unmatched_values"], "hook", _o13_membership,
        unparseable_count=_o13_hook_unparseable, unparseable_bucket="unparseable")
    _o13_agent_tax_all = classify_skips(
        gov_result["unmatched_agent_values"], "governance_agent", _o13_membership)
    _o13_skill_tax_all = classify_skips(
        gov_result["unmatched_skill_values"], "governance_skill", _o13_membership)
    _o13_hook_windowed = windowed_scope_block(hook_result["windowed"], "hook", _o13_membership)
    _o13_agent_windowed = windowed_scope_block(gov_result["windowed_agent"], "governance_agent", _o13_membership)
    _o13_skill_windowed = windowed_scope_block(gov_result["windowed_skill"], "governance_skill", _o13_membership)

    data = {
        "run_id": run_id,
        "generated_at": generated_at,
        "generator_version": GENERATOR_VERSION,
        "field_contract_check": "PASSED",
        "excluded_test_scaffolding_count": len(hook_files_test) + len(hook_files_retired_test),
        "hook_py_file_count_top_level": len(hook_files_non_test) + len(hook_files_test),
        "hook_py_file_count_retired": len(hook_files_retired_non_test) + len(hook_files_retired_test),
        "skipped_records": {
            "window": {
                "window_days": WINDOW_DAYS,
                "window_start": _o13_ws_iso,
                "window_end": _o13_we_iso,
            },
            "enumeration_fingerprint": _o13_fingerprint,
            "hook_activity_jsonl": {
                "total_lines": hook_result["total_lines"],
                "unparseable_or_unmatched": hook_result["skipped"],
                "top_unmatched_hook_values": hook_result["unmatched_values"].most_common(10),
                "skip_taxonomy_all_history": _o13_hook_tax_all,
                "windowed_30d": _o13_hook_windowed,
            },
            "governance_log_jsonl": {
                "total_lines": gov_result["total_lines"],
                "total_agent_dispatched_records": gov_result["total_agent_dispatched"],
                "unmatched_or_null_agent_type": gov_result["skipped_agent"],
                "top_unmatched_agent_type_values": gov_result["unmatched_agent_values"].most_common(10),
                "skill_context_items_total": gov_result["skill_items_total"],
                "unmatched_skill_context_items": gov_result["skipped_skill"],
                "top_unmatched_skill_context_values": gov_result["unmatched_skill_values"].most_common(10),
                "mcp_gate_events_total": gov_result["mcp_gate_events_total"],
                "top_unmatched_mcp_gate_values": gov_result["unmatched_mcp_gate_values"].most_common(10),
                "workflow_pass_total": gov_result["workflow_pass_total"],
                "workflow_pass_attributed": sum(
                    v["count"] for v in gov_result["workflow_usage"].values()),
                "workflow_pass_unattributed": gov_result["workflow_pass_unattributed"],
                "top_unmatched_workflow_values": gov_result["unmatched_workflow_values"].most_common(10),
                "agent_skip_taxonomy_all_history": _o13_agent_tax_all,
                "agent_windowed_30d": _o13_agent_windowed,
                "skill_skip_taxonomy_all_history": _o13_skill_tax_all,
                "skill_windowed_30d": _o13_skill_windowed,
            },
        },
        "junctions_detected": junction_names,
        "settings_hook_entry_counts": settings_entry_counts(settings_commands),
        "documentation_drift": drift,
        "edges": {
            "unresolved_count": unresolved_count,
            "compiled_count": compiled_count,
            "unresolved_fraction": round(unresolved_fraction, 6),
            "cap": UNRESOLVED_FRACTION_CAP,
            "status": edges_status,
        },
        "command_kind": {
            "enumeration_source_confirmed": str(COMMANDS_DIR) if commands_dir_confirmed else None,
            "row_count": len(command_names),
            "note": ("No .claude/commands/ directory exists in this repository (ASSUMPTION-002 "
                     "disconfirmed); zero command-kind rows enumerated this run. Slash commands in "
                     "this harness are entirely plugin-delivered, living under the user-profile "
                     "plugin cache, which is outside this build's declared read scope (DEP-002)."
                     if not commands_dir_confirmed else "confirmed"),
        },
        "mcp_server_kind": {
            # O9 increment 1: row_count is the live count of kind=mcp-server
            # rows (it read len(mcp_server_names) == .mcp.json keys only
            # while plugin rows were added separately, shipping a stale 8
            # against 15 live rows). The two breakdown fields keep the old
            # meaning legible.
            "enumeration_source_confirmed": str(MCP_JSON) if mcp_json_confirmed else None,
            "row_count": sum(1 for (k, _n) in rows_by_key if k == "mcp-server"),
            "mcpjson_row_count": len(mcp_server_names),
            "plugin_row_count": sum(
                1 for (k, _n), r in rows_by_key.items()
                if k == "mcp-server" and r.provenance.startswith("plugin:")),
        },
        "settings_registration_kind": {
            "enumeration_sources": [str(MCP_JSON), str(SETTINGS_JSON), str(SETTINGS_LOCAL_JSON)],
            "row_count": len(settings_registration_rows),
            "unresolved_count": sum(1 for r in settings_registration_rows if r.blocked_reason),
            "note": ("O1, 2026-08-30. Unions two compiled sub-populations: .mcp.json server "
                     "entries and settings.json/settings.local.json hook-command entries. An "
                     "unresolved entry (command matches no currently-enumerated hook file, or an "
                     ".mcp.json entry with neither a command nor an http type+url) still gets a "
                     "row, blocked_reason=['BLK-006'], rather than being dropped."),
        },
        "telemetry_sink_kind": {
            "enumeration_sources": [str(HOOK_ACTIVITY_JSONL_DEFAULT), str(GOVERNANCE_LOG_JSONL_DEFAULT),
                                     str(TELEMETRY_VOCAB_JSON)],
            "row_count": len(telemetry_sink_rows),
            "unresolved_count": sum(1 for r in telemetry_sink_rows if r.blocked_reason),
            "notes": telemetry_vocab_notes,
        },
        "plugin_cache_enumeration": plugin_cache_enumeration,
        "plugin_reconciliation": plugin_reconciliation,
        "diff": diff,
        "twin_summary": twin_summary,
        "twins": twins_block,
        "rows": row_dicts,
    }

    if write_output:
        aggregates_dir.mkdir(parents=True, exist_ok=True)
        snapshots_dir.mkdir(parents=True, exist_ok=True)
        with open(data_file, "wb") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            fh.write(b"\n")
        with open(snapshots_dir / f"{run_id}.json", "wb") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8"))
            fh.write(b"\n")

        md_text = render_markdown_from_file(data_file)
        with open(md_file, "wb") as fh:
            fh.write(md_text.encode("utf-8"))

        print(f"[asset_inventory] wrote {data_file} ({len(row_dicts)} rows, of which "
              f"{sum(plugin_cache_enumeration['row_counts'][k] for k in ('skill', 'agent', 'hook', 'mcp-server'))} "
              f"plugin-sourced + {plugin_cache_enumeration['row_counts']['blk004_unresolved_registry_entries']} "
              f"BLK-004), {md_file}, and snapshot {snapshots_dir / (run_id + '.json')}")

    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--governance-log-path", type=Path, default=GOVERNANCE_LOG_JSONL_DEFAULT)
    parser.add_argument("--hook-activity-path", type=Path, default=HOOK_ACTIVITY_JSONL_DEFAULT)
    parser.add_argument("--aggregates-dir", type=Path, default=AGGREGATES_DIR)
    parser.add_argument("--registry-path", type=Path, default=REGISTRY_JSON,
                         help="Override registry.json path (2026-08-20; mainly for the self-test's "
                              "BLK-004 fixture, which needs a synthetic registry without touching "
                              "the live .claude/registry.json).")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--skip-freshness-check", action="store_true",
                        help="Skip the registry-freshness guard (2026-08-22). For the "
                             "self-test, which uses synthetic fixtures and is not "
                             "measuring registry freshness. Do not use for a real run: "
                             "the guard is what stops the inventory describing stale state.")
    args = parser.parse_args()

    try:
        generate(
            governance_log_path=args.governance_log_path,
            hook_activity_path=args.hook_activity_path,
            aggregates_dir=args.aggregates_dir,
            registry_path=args.registry_path,
            run_id=args.run_id,
            skip_freshness_check=args.skip_freshness_check,
        )
    except (FieldContractError, EnumerationRootError, RegistryStalenessError) as exc:
        print(f"[asset_inventory] ABORTED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
