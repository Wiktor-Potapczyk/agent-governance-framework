#!/usr/bin/env python
"""twin_snapshot.py -- O14 (2026-09-01): forward-persistence of the twin
list (metric 3 of the first-checkpoint scorecard).

Two subcommands:

  write [--inventory PATH] [--out-dir PATH]
      Copy the `twins` block (counts + sorted divergent (kind, name, path)
      rows + kind_set) out of asset-inventory.json into a dated,
      run_id-named snapshot at a GIT-TRACKED path. Refuses loudly (exit 2)
      if the inventory has no `twins` block or if the snapshot already
      exists (re-runs stay idempotent). Run this ONCE per scorecard
      assembly -- never per generator run (spec risk flag 1: one file per
      scorecard assembly keeps volume bounded). The generator never
      invokes this script.

  diff OLD NEW
      Name the DISTINCT PATHS entering or leaving divergent state between
      two snapshots. Paths, not rows: many rows share one path
      (settings.local.json alone backs 72 rows), so row counts move in
      multiples. Reports a kind-set delta whenever the two snapshots'
      kind_sets differ (population change named, never silent). Exit 0 on
      any successful diff regardless of drift; exit 2 on an invalid
      snapshot; argparse exits 2 on wrong arity (one snapshot is not a
      diffable series).

Default snapshot home: Projects/Agent-Governance-Research/work/twin-snapshots/
(chosen because .gitignore:149 ignores .claude/hooks/aggregates/ wholesale,
which is what destroyed the 2026-08-24 baseline). Stdlib only.

Build record: Projects/Agent-Governance-Research/work/2026-09-01-o14-build-record.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_INVENTORY = REPO_ROOT / ".claude" / "hooks" / "aggregates" / "asset-inventory.json"
DEFAULT_OUT_DIR = (REPO_ROOT / "Projects" / "Agent-Governance-Research"
                   / "work" / "twin-snapshots")
SCHEMA_VERSION = 1


def fail(msg: str) -> int:
    print(f"[twin_snapshot] ERROR: {msg}", file=sys.stderr)
    return 2


def cmd_write(args: argparse.Namespace) -> int:
    inv_path = Path(args.inventory)
    if not inv_path.is_file():
        return fail(f"inventory not found: {inv_path}")
    try:
        inv = json.loads(inv_path.read_bytes().decode("utf-8"))
    except (OSError, ValueError) as exc:
        return fail(f"cannot parse inventory {inv_path}: {exc}")
    twins = inv.get("twins")
    if not isinstance(twins, dict):
        return fail(
            f"inventory {inv_path} has no `twins` block -- pre-O14 generator "
            "output; rerun asset_inventory.py first")
    run_id = inv.get("run_id") or "unknown-run"
    generated_at = inv.get("generated_at") or ""
    date_prefix = generated_at[:10] or "undated"
    out_dir = Path(args.out_dir)
    out_path = out_dir / f"{date_prefix}-{run_id}.json"
    if out_path.exists():
        return fail(
            f"snapshot already exists, refusing to overwrite: {out_path} "
            "(one snapshot per scorecard assembly; delete manually only if "
            "the source run was wrong)")
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "source_run_id": run_id,
        "source_generated_at": generated_at,
        "snapshot_written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_file": str(inv_path),
        "kind_set": twins.get("kind_set"),
        "counts": twins.get("counts"),
        "divergent": twins.get("divergent"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(json.dumps(snapshot, indent=2, ensure_ascii=False).encode("utf-8"))
        fh.write(b"\n")
    print(f"[twin_snapshot] wrote {out_path} (source_run_id={run_id}, "
          f"divergent rows={len(snapshot['divergent'] or [])})")
    return 0


def load_snapshot(path_str: str) -> dict | None:
    p = Path(path_str)
    if not p.is_file():
        return None
    try:
        snap = json.loads(p.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        return None
    if snap.get("schema_version") != SCHEMA_VERSION:
        return None
    if not isinstance(snap.get("counts"), dict):
        return None
    if not isinstance(snap.get("divergent"), list):
        return None
    if not isinstance(snap.get("kind_set"), list):
        return None
    return snap


def cmd_diff(args: argparse.Namespace) -> int:
    old = load_snapshot(args.old)
    if old is None:
        return fail(f"not a valid schema-v{SCHEMA_VERSION} snapshot: {args.old}")
    new = load_snapshot(args.new)
    if new is None:
        return fail(f"not a valid schema-v{SCHEMA_VERSION} snapshot: {args.new}")
    old_paths = {d.get("path") for d in old["divergent"]}
    new_paths = {d.get("path") for d in new["divergent"]}
    entering = sorted(new_paths - old_paths)
    leaving = sorted(old_paths - new_paths)
    still = len(old_paths & new_paths)
    print(f"[twin_snapshot] diff {old.get('source_run_id')} -> "
          f"{new.get('source_run_id')}")
    print(f"paths entering divergent ({len(entering)}):")
    for p in entering:
        print(f"  + {p}")
    print(f"paths leaving divergent ({len(leaving)}):")
    for p in leaving:
        print(f"  - {p}")
    print(f"still-divergent distinct paths: {still}")
    old_kinds = old.get("kind_set")
    new_kinds = new.get("kind_set")
    if old_kinds != new_kinds:
        added = sorted(set(new_kinds) - set(old_kinds))
        removed = sorted(set(old_kinds) - set(new_kinds))
        print(f"kind-set delta: added={added} removed={removed} -- the "
              "twin-eligible population changed between these runs; state "
              "counts are not apples-to-apples")
    else:
        print(f"kind-set unchanged ({len(new_kinds)} kinds)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_write = sub.add_parser("write", help="snapshot the current twins block")
    p_write.add_argument("--inventory", default=str(DEFAULT_INVENTORY))
    p_write.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p_diff = sub.add_parser("diff", help="diff two snapshots by distinct path")
    p_diff.add_argument("old")
    p_diff.add_argument("new")
    args = parser.parse_args()
    if args.command == "write":
        return cmd_write(args)
    return cmd_diff(args)


if __name__ == "__main__":
    raise SystemExit(main())
