#!/usr/bin/env python3
"""Lint Pass U: KB_INDEX_BUDGET (ROAD-8, 2026-09-08).

Advisory weekly growth tripwire for Resources/KB/index.md: reports the live
byte and entry count against a declared budget every run (always-print, so
growth is visible before the wall), and emits one KB_INDEX_BUDGET finding
when either budget is exceeded.

The budget file (`_state/kb-index-budget.json`) is seeded by `--seed` from
the live file (current size times a 1.5 headroom factor, bytes rounded to
the nearest 100), never hand-typed: it is a computed proposal pending the
owner budget ruling (trust-roadmap section 6 ruling 6).

Entries = pipe-prefixed lines minus header and separator rows.

CLI contract (shared by all lint_pass_* scripts):
  - always prints its measurement line
  - finding: `KB_INDEX_BUDGET  bytes=<n> budget=<b> entries=<e> entry_budget=<eb>`
  - exit 0 clean, 1 findings, 2 derivation failure (missing/unreadable
    budget file or index; never a silent clean report)
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_INDEX = VAULT / "Resources" / "KB" / "index.md"
DEFAULT_BUDGET = VAULT / ".claude" / "hooks" / "_state" / "kb-index-budget.json"
HEADROOM_FACTOR = 1.5


def measure(index_path):
    data = Path(index_path).read_bytes()
    text = data.decode("utf-8")
    pipe_rows = sum(1 for line in text.splitlines() if line.startswith("|"))
    entries = max(pipe_rows - 2, 0)  # minus header and separator
    return len(data), entries


def seed(index_path, budget_path):
    nbytes, entries = measure(index_path)
    budget = {
        "generated_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed_bytes": nbytes,
        "seed_entries": entries,
        "headroom_factor": HEADROOM_FACTOR,
        "budget_bytes": int(round(nbytes * HEADROOM_FACTOR / 100.0)) * 100,
        "budget_entries": int(round(entries * HEADROOM_FACTOR)),
    }
    budget_path = Path(budget_path)
    budget_path.parent.mkdir(parents=True, exist_ok=True)
    with open(budget_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(budget, f, indent=2)
        f.write("\n")
    print(f"SEEDED {budget_path}: budget_bytes={budget['budget_bytes']} "
          f"budget_entries={budget['budget_entries']} "
          f"(from bytes={nbytes} entries={entries} x{HEADROOM_FACTOR})")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--index-file", default=str(DEFAULT_INDEX))
    ap.add_argument("--budget-file", default=str(DEFAULT_BUDGET))
    ap.add_argument("--seed", action="store_true",
                    help="compute and write the budget proposal from the live file")
    args = ap.parse_args(argv)

    if not os.path.isfile(args.index_file):
        print(f"DERIVATION FAILURE: index file absent: {args.index_file}")
        return 2

    if args.seed:
        return seed(args.index_file, args.budget_file)

    try:
        budget = json.loads(Path(args.budget_file).read_text(encoding="utf-8"))
        budget_bytes = int(budget["budget_bytes"])
        budget_entries = int(budget["budget_entries"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"DERIVATION FAILURE: budget file unusable ({args.budget_file}): {e}")
        return 2

    nbytes, entries = measure(args.index_file)
    print(f"KB_INDEX bytes={nbytes} budget={budget_bytes} "
          f"entries={entries} entry_budget={budget_entries}")
    if nbytes > budget_bytes or entries > budget_entries:
        print(f"KB_INDEX_BUDGET  bytes={nbytes} budget={budget_bytes} "
              f"entries={entries} entry_budget={budget_entries}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
