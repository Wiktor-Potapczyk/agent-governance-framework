#!/usr/bin/env python3
"""Lint Pass S: WORK_INDEX_STALE (ROAD-7, 2026-09-08).

Advisory weekly comparison of each pilot's work-index stamp
(`_state/work-index-<slug>.json`, written by generate_work_index.py on
every regeneration) against a live recount using the generator's own
`collect_rows` (same exclusions: flat glob, INDEX.md and wiki-tagged
files skipped). Both counts are computed, never typed
(generator-derivation rule).

CLI contract (shared by all lint_pass_* scripts):
  - always prints one measurement line per pilot
  - finding: `WORK_INDEX_STALE  project=<p> stamped=<a> live=<b>`
    (stamped=none when the stamp file is missing)
  - exit 0 clean, 1 findings, 2 derivation failure
"""
import argparse
import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import generate_work_index as gwi  # noqa: E402

VAULT = SCRIPTS.parent.parent


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=str(VAULT))
    ap.add_argument("--state-dir", default=None,
                    help="override for tests; default <vault>/.claude/hooks/_state")
    args = ap.parse_args(argv)

    vault = Path(args.vault)
    state_dir = Path(args.state_dir) if args.state_dir else vault / ".claude" / "hooks" / "_state"

    findings = 0
    for project in gwi.PILOTS:
        work_dir = vault / Path(*project.split("/")) / "work"
        if not work_dir.is_dir():
            print(f"DERIVATION FAILURE: missing work dir: {work_dir}")
            return 2
        live = len(gwi.collect_rows(str(work_dir)))
        slug = os.path.basename(project.rstrip("/")).lower()
        stamp_path = state_dir / f"work-index-{slug}.json"
        stamped = None
        if stamp_path.is_file():
            try:
                stamped = json.loads(stamp_path.read_text(encoding="utf-8")).get("file_count")
            except (json.JSONDecodeError, OSError) as e:
                print(f"DERIVATION FAILURE: unreadable stamp {stamp_path}: {e}")
                return 2
        shown = "none" if stamped is None else stamped
        print(f"WORK_INDEX project={project} stamped={shown} live={live}")
        if stamped != live:
            print(f"WORK_INDEX_STALE  project={project} stamped={shown} live={live}")
            findings += 1
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
