#!/usr/bin/env python3
"""staleness_manifest_generate.py - deterministic generator for the GENERATED
block of staleness-manifest.json.

Origin: O10 of Projects/Agent-Governance-Research/work/
2026-08-31-harness-takeover-objectives.md (spec lines 63-81), built per
2026-09-02-o10-staleness-generation-plan.md. R5-style extension of the O4
manifest+checker mechanism (staleness_check.py reads the block via its merged
loader); the checker keeps zero write paths, this script owns the only one.

What it emits: a top-level `generated_block` object holding the 10
auto-derivable entries the research classified:
  - the 7 dispatches-* entries (enumerated via the SAME glob
    dispatches_freshness_check.py uses, `.claude/skills/*/DISPATCHES.json`,
    then cross-checked against EXPECTED_DISPATCH_SKILLS; deriving them from
    the inventory's EVD-002 source_file values yields only 5, because
    process-qa and process-pentest declare zero dispatches - the fabrication
    hazard the plan neutralized). Their rederive_command names
    dispatches_freshness_check.py, which IS O11's content-based re-derive
    semantics.
  - harness-self-model, with its live_count_probe against registry.json
    `counts` (the inventory's documentation_drift generator_fresh_count is
    scoped local-only and would false-fail; verified decision, plan D6).
  - cmdb-vault-setup, keeping cmdb_refresh.py as rederive_command (this
    generated entry SUPERSEDES the standalone hand spot-refresh registration
    per the PM dedup ruling; the duplicate guard below and the checker's
    MANIFEST_DUPLICATE_ID error together keep both from ever co-existing).
  - rationale-index, keeping max_age_days 7 as backstop AND gaining a
    provenance_count_probe mirroring the index's own population_definition.

Determinism contract (cmdb_refresh.py precedent): the block stamp is the
INVENTORY's own generated_at, never now(), so re-running against unchanged
inputs is byte-identical and --check is a real drift probe (exit 2 naming
each drifting entry id, 0 when current). Missing or rowless inputs fail loud
at exit 2 with no write. Internal cross-check: per-kind row counts recomputed
from the inventory's rows must agree with the inventory's own per-kind
row_count headers (*_kind keys), else emission is refused.

Every count assertion here derives from len() over the classification
constants, never a literal 10/14/17 (spec risk flag 2). An eighth
DISPATCHES.json on disk fails loud demanding a classification update; it is
never silently emitted.

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/staleness_manifest_generate.py
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/staleness_manifest_generate.py --check
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

# Layout adaptation (published copy): harness root from VAULT_DIR (repo keeps
# scripts/ at top level, not under .claude/).
VAULT = Path(os.environ.get("VAULT_DIR", "C:/Users/exampleuser/Workspace"))

PY_EXE = '"C:\\Program Files\\Python314\\python.exe"'

# Classification constants (plan D7): the single count source. The board's
# expected totals are len() over these, never hardcoded.
EXPECTED_DISPATCH_SKILLS = ("pm", "process-analysis", "process-build",
                            "process-pentest", "process-planning",
                            "process-qa", "process-research")
GENERATED_STATIC_IDS = ("harness-self-model", "cmdb-vault-setup",
                        "rationale-index")
BESPOKE_IDS = ("cc-config-reference", "install-prereqs-manifest",
               "coverage-ledger-consistency", "harness-process-path-map")
GOVERNING_IDS = ("governing-claude-md-size", "governing-settings-split",
                 "governing-rules-directory")

DISPATCHES_REDERIVE = (
    PY_EXE + " .claude/scripts/dispatches_freshness_check.py ; if STALE, hand "
    "content-review the named file against SKILL.md and the workflow script, "
    "bump last_reviewed with a note, then re-run with --bootstrap (O11, "
    "2026-08-31-harness-takeover-objectives.md)"
)
DISPATCHES_AGE_REGEX = r'"last_reviewed"\s*:\s*"([0-9\-]+)"'

DO_NOT_EDIT = (
    "GENERATED BLOCK - DO NOT HAND-EDIT. Emitted by "
    ".claude/scripts/staleness_manifest_generate.py from asset-inventory.json; "
    "a hand edit is flagged as drift by 'staleness_manifest_generate.py "
    "--check' (exit 2) and overwritten by the next generate run. Change the "
    "generator, not this block."
)


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 2


def enumerate_dispatch_skills(vault_root: Path) -> list[str]:
    """Same enumeration dispatches_freshness_check.py uses (its _enumerate):
    sorted glob of .claude/skills/*/DISPATCHES.json."""
    skills_dir = vault_root / ".claude" / "skills"
    return [p.parent.name for p in sorted(skills_dir.glob("*/DISPATCHES.json"))]


def cross_check_inventory(inventory: dict) -> None:
    """Recompute per-kind row counts from rows and compare against the
    inventory's own per-kind row_count headers (every top-level *_kind key
    carrying an int row_count). Raises ValueError on any disagreement:
    emission from an internally inconsistent inventory is refused (D6/D7)."""
    rows = inventory.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("inventory has no rows; refusing to emit from nothing")
    per_kind = Counter(str(r.get("kind")) for r in rows if isinstance(r, dict))
    for key, value in inventory.items():
        if not key.endswith("_kind") or not isinstance(value, dict):
            continue
        expected = value.get("row_count")
        if not isinstance(expected, int):
            continue
        kind_name = key[: -len("_kind")].replace("_", "-")
        actual = per_kind.get(kind_name, 0)
        if actual != expected:
            raise ValueError(
                f"per-kind cross-check failed for kind {kind_name!r}: "
                f"inventory header row_count={expected} but rows hold {actual}; "
                "refusing to emit from an internally inconsistent inventory"
            )


def dispatches_entry(skill: str) -> dict:
    """Byte-equal to the proven-green 2026-08-31 shape, path parameterized."""
    return {
        "id": f"dispatches-{skill}",
        "artifact_path": f".claude/skills/{skill}/DISPATCHES.json",
        "max_age_days": 90,
        "rederive_command": DISPATCHES_REDERIVE,
        "age_source": "embedded_comment",
        "age_regex": DISPATCHES_AGE_REGEX,
    }


def harness_self_model_entry() -> dict:
    return {
        "id": "harness-self-model",
        "artifact_path": ".claude/harness-self-model.md",
        "max_age_days": 7,
        "rederive_command": PY_EXE + " .claude/scripts/generate_harness_self_model.py",
        "age_source": "embedded_comment",
        "age_regex": r"generated-at:\s*([0-9T:\-]+)",
        "live_count_probe": {
            "source_file": ".claude/registry.json",
            "source_key_path": ["counts"],
            "table_metric_map": {
                "Agents": "agents",
                "Skills": "skills",
                "Plugins (total)": "plugins_total",
                "Plugins (enabled)": "plugins_enabled",
            },
        },
    }


def cmdb_vault_setup_entry() -> dict:
    return {
        "id": "cmdb-vault-setup",
        "artifact_path": "Resources/KB/cmdb-vault-setup.md",
        "max_age_days": 90,
        "rederive_command": ("python .claude/scripts/cmdb_refresh.py "
                             "(regenerates the marked block from "
                             "asset-inventory.json; --check probes drift)"),
        "age_source": "embedded_comment",
        "age_regex": r"asset-inventory\.json generated_at ([0-9T:\-]+)Z",
        "note": ("Generator added 2026-08-31 (owner-ruled generator-first "
                 "refresh); age now reads the generated block stamp, which "
                 "tracks the inventory generation, not the page creation "
                 "date."),
    }


def rationale_index_entry() -> dict:
    return {
        "id": "rationale-index",
        "artifact_path": ".claude/hooks/aggregates/rationale-index.json",
        "max_age_days": 7,
        "rederive_command": PY_EXE + " .claude/scripts/rationale_extract.py",
        "age_source": "embedded_comment",
        "age_regex": r'"generated_at"\s*:\s*"([0-9T:\-]+)',
        "provenance_count_probe": {
            "source_file": ".claude/hooks/aggregates/asset-inventory.json",
            "exact": ["authored-in-harness"],
            "prefixes": ["junction:"],
            "expected_key_path": ["row_count"],
        },
        "note": ("O10 D6: the provenance_count_probe mirrors the index's own "
                 "population_definition (exact 'authored-in-harness', prefix "
                 "'junction:'); max_age_days stays as the age backstop per "
                 "the spec's 'instead of age alone'."),
    }


def build_block(inventory: dict, skills: list[str]) -> dict:
    """The generated block, in fixed classification order: the dispatches
    entries (sorted by skill dir name) then the three static ids."""
    stamp = inventory.get("generated_at")
    if not stamp:
        raise ValueError("inventory carries no generated_at stamp")
    entries = [dispatches_entry(s) for s in sorted(skills)]
    entries.append(harness_self_model_entry())
    entries.append(cmdb_vault_setup_entry())
    entries.append(rationale_index_entry())
    return {
        "do_not_edit": DO_NOT_EDIT,
        "source_inventory_generated_at": stamp,
        "entries": entries,
    }


def _entry_dump(entry: dict) -> str:
    return json.dumps(entry, ensure_ascii=False, indent=2)


def diff_blocks(on_disk: dict | None, fresh: dict) -> list[str]:
    """Name every difference between the on-disk generated block and a fresh
    emission, per entry id where possible."""
    if on_disk is None:
        return ["generated_block missing from the manifest; run generate"]
    diffs: list[str] = []
    for header in ("do_not_edit", "source_inventory_generated_at"):
        if on_disk.get(header) != fresh.get(header):
            diffs.append(f"generated_block header field {header!r} differs")
    disk_entries = {e.get("id"): e for e in on_disk.get("entries", [])
                    if isinstance(e, dict)}
    fresh_entries = {e["id"]: e for e in fresh["entries"]}
    for eid in fresh_entries:
        if eid not in disk_entries:
            diffs.append(f"entry {eid} missing from the on-disk block")
        elif _entry_dump(disk_entries[eid]) != _entry_dump(fresh_entries[eid]):
            diffs.append(f"entry {eid} differs from a fresh emission")
    for eid in disk_entries:
        if eid not in fresh_entries:
            diffs.append(f"entry {eid} present on disk but not in a fresh emission")
    return diffs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Generate (default) or drift-check the GENERATED block of "
                    "staleness-manifest.json from asset-inventory.json.")
    ap.add_argument("--vault-root", type=Path, default=VAULT)
    ap.add_argument("--manifest", type=Path, default=None,
                    help="default: <vault-root>/.claude/scripts/staleness-manifest.json")
    ap.add_argument("--inventory", type=Path, default=None,
                    help="default: <vault-root>/.claude/hooks/aggregates/asset-inventory.json")
    ap.add_argument("--check", action="store_true",
                    help="exit 2 naming each entry whose on-disk form differs "
                         "from a fresh emission; write nothing")
    args = ap.parse_args(argv)

    vault_root = args.vault_root
    manifest_path = args.manifest or (vault_root / ".claude" / "scripts"
                                      / "staleness-manifest.json")
    inventory_path = args.inventory or (vault_root / ".claude" / "hooks"
                                        / "aggregates" / "asset-inventory.json")

    for path, name in ((manifest_path, "manifest"), (inventory_path, "inventory")):
        if not path.exists():
            return _fail(f"{name} not found at {path}")

    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        manifest_text = manifest_path.read_text(encoding="utf-8")
        data = json.loads(manifest_text)
    except (OSError, json.JSONDecodeError) as exc:
        return _fail(f"unreadable input: {exc}")

    try:
        cross_check_inventory(inventory)
    except ValueError as exc:
        return _fail(str(exc))

    skills = enumerate_dispatch_skills(vault_root)
    expected = set(EXPECTED_DISPATCH_SKILLS)
    found = set(skills)
    if found != expected:
        extra = sorted(found - expected)
        missing = sorted(expected - found)
        parts = []
        if extra:
            parts.append(f"unclassified DISPATCHES.json skill dir(s): {extra}")
        if missing:
            parts.append(f"classified skill(s) with no DISPATCHES.json on disk: {missing}")
        return _fail(
            "dispatches enumeration does not map 1:1 onto "
            "EXPECTED_DISPATCH_SKILLS; update the classification constant "
            "rather than letting the block drift silently. " + "; ".join(parts))

    try:
        block = build_block(inventory, skills)
    except ValueError as exc:
        return _fail(str(exc))

    generated_ids = {e["id"] for e in block["entries"]}
    hand_entries = data.get("entries", [])
    collisions = sorted(
        e.get("id") for e in hand_entries
        if isinstance(e, dict) and e.get("id") in generated_ids)
    if collisions:
        return _fail(
            f"hand entries collide with generated ids: {collisions}; the "
            "generated entry supersedes the hand registration (O10 D9), so "
            "remove the hand entry first")

    if args.check:
        diffs = diff_blocks(data.get("generated_block"), block)
        if diffs:
            print("DRIFT in the generated block "
                  f"({len(diffs)} finding(s)):")
            for d in diffs:
                print(f"- {d}")
            return 2
        print("generated block is current")
        return 0

    data["generated_block"] = block
    new_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if new_text != manifest_text:
        with io.open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(new_text)
        print(f"generated block written ({len(block['entries'])} entries, "
              f"inventory {block['source_inventory_generated_at']})")
    else:
        print("generated block already current; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
