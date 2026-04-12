"""
Unused Resource Detection — identifies agents/skills never dispatched.

Scans governance-log.jsonl for all dispatched agent/skill names, cross-references
against KNOWN_DISPATCH_NAMES, reports days-since-last-dispatch for each.

Usage:
    python unused_resources.py
    python unused_resources.py --days 14   # only show stale >14 days

Iteration 2, task I2-4.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from shared.known_names import KNOWN_DISPATCH_NAMES

VAULT_ROOT = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "..", ".."))
GOVERNANCE_LOG = os.path.join(VAULT_ROOT, ".claude", "hooks", "governance-log.jsonl")


def scan_dispatches():
    """Scan governance-log.jsonl for all dispatched agent/skill names and their last timestamp."""
    last_seen = defaultdict(lambda: None)

    if not os.path.exists(GOVERNANCE_LOG):
        print(f"WARNING: governance-log.jsonl not found at {GOVERNANCE_LOG}", file=sys.stderr)
        return last_seen

    with open(GOVERNANCE_LOG, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts_str = entry.get("ts", "")
            try:
                # W3 fix: handle both "%Y-%m-%d %H:%M:%S" and ISO format
                ts = datetime.fromisoformat(ts_str.replace(" ", "T") if "T" not in ts_str else ts_str)
            except (ValueError, TypeError):
                continue

            # Sources of dispatch evidence:

            # 1. dispatch-compliance pass events: "matched" list
            if entry.get("hook") == "dispatch-compliance" and entry.get("event") == "pass":
                for name in entry.get("matched", []):
                    if last_seen[name] is None or ts > last_seen[name]:
                        last_seen[name] = ts

            # 2. dispatch-compliance block events: "declared" list (they were at least declared)
            if entry.get("hook") == "dispatch-compliance" and entry.get("event") == "block":
                for name in entry.get("declared", []):
                    if last_seen[name] is None or ts > last_seen[name]:
                        last_seen[name] = ts

            # 3. agent-dispatch-check deny events: "agent_type" was attempted
            if entry.get("hook") == "agent-dispatch-check" and entry.get("event") == "deny":
                name = entry.get("agent_type", "")
                if name and (last_seen[name] is None or ts > last_seen[name]):
                    last_seen[name] = ts

            # 4. governance-log classification entries: "agents" and "skills" lists (v1)
            if entry.get("event") not in ("block", "deny", "pass", "warn", "dark-zone", "session_start"):
                # v1 classification entries
                for name in entry.get("agents", []):
                    if name in KNOWN_DISPATCH_NAMES:
                        if last_seen[name] is None or ts > last_seen[name]:
                            last_seen[name] = ts
                for name in entry.get("skills", []):
                    if name in KNOWN_DISPATCH_NAMES:
                        if last_seen[name] is None or ts > last_seen[name]:
                            last_seen[name] = ts

            # 5. dark-zone "agents" list
            if entry.get("event") == "dark-zone":
                for name in entry.get("agents", []):
                    if name in KNOWN_DISPATCH_NAMES:
                        if last_seen[name] is None or ts > last_seen[name]:
                            last_seen[name] = ts

    return last_seen


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Detect unused agents/skills")
    parser.add_argument("--days", type=int, default=0, help="Only show resources stale >N days (0=all)")
    args = parser.parse_args()

    last_seen = scan_dispatches()
    now = datetime.now()

    # Classify each known name
    results = []
    for name in sorted(KNOWN_DISPATCH_NAMES):
        ts = last_seen.get(name)
        if ts is None:
            status = "NEVER"
            days_ago = None
        else:
            days_ago = (now - ts).days
            if days_ago > 14:
                status = "STALE"
            else:
                status = "ACTIVE"
        results.append((name, status, days_ago, ts))

    # Filter
    if args.days > 0:
        results = [r for r in results if r[1] == "NEVER" or (r[2] is not None and r[2] > args.days)]

    # Counts
    never = sum(1 for r in results if r[1] == "NEVER")
    stale = sum(1 for r in results if r[1] == "STALE")
    active = sum(1 for r in results if r[1] == "ACTIVE")

    print(f"\nUnused Resource Report — {len(KNOWN_DISPATCH_NAMES)} known agents/skills")
    print(f"ACTIVE: {active} | STALE (>14d): {stale} | NEVER: {never}")
    print(f"{'='*70}\n")

    # Print by category
    for category in ["NEVER", "STALE", "ACTIVE"]:
        items = [r for r in results if r[1] == category]
        if not items:
            continue
        print(f"  {category}:")
        for name, status, days_ago, ts in items:
            if ts:
                print(f"    {name:<35} last: {ts.strftime('%Y-%m-%d')} ({days_ago}d ago)")
            else:
                print(f"    {name:<35} NEVER dispatched")
        print()


if __name__ == "__main__":
    main()
