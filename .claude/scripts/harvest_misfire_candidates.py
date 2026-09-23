#!/usr/bin/env python3
"""Harvest false-positive (misfire) candidates from governance-log.jsonl.

Design: [[2026-06-02-enforcement-boundary-test-design]] §2a/§2c.

READ-ONLY. Surfaces block events for human review; it does NOT classify a block
as a misfire automatically. The high-signal heuristic (design Risk-3 mitigation):
a block event is more likely a misfire if a `feedback_*.md` memo was created in
the same window — strong signal that a human noticed something and corrected it.

Output: .claude/hooks/tests/misfire-candidates-<date>.jsonl + a printed summary.
Promotable candidates become `origin: regression` FP-guard cases in the hook's
test_*.py.

Usage:
    python .claude/scripts/harvest_misfire_candidates.py --days 90
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VAULT = Path(os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
))
GOV_LOG = VAULT / ".claude" / "hooks" / "governance-log.jsonl"
MEMORY_DIR = (Path.home() / ".claude" / "projects"
              / "C--Users-WiktorPotapczyk-Desktop-Vault" / "memory")
OUT_DIR = VAULT / ".claude" / "hooks" / "tests"


def parse_days() -> int:
    if "--days" in sys.argv:
        i = sys.argv.index("--days")
        if i + 1 < len(sys.argv):
            try:
                return int(sys.argv[i + 1])
            except ValueError:
                pass
    return 90


def parse_ts(s: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19], fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def main() -> int:
    days = parse_days()
    if not GOV_LOG.exists():
        print(f"[harvest] no governance-log at {GOV_LOG}")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    blocks_by_hook: dict[str, int] = {}
    recent_blocks: list[dict] = []
    with open(GOV_LOG, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("event") != "block":
                continue
            ts = parse_ts(e.get("ts", ""))
            if ts is None or ts < cutoff:
                continue
            hook = e.get("hook", "unknown")
            blocks_by_hook[hook] = blocks_by_hook.get(hook, 0) + 1
            recent_blocks.append({
                "ts": e.get("ts"),
                "hook": hook,
                "session": e.get("session"),
                "reason": e.get("reason") or e.get("missing") or e.get("declared"),
            })

    # Feedback memos created in-window (high-signal: a human noticed + corrected).
    recent_memos: list[str] = []
    if MEMORY_DIR.exists():
        for p in MEMORY_DIR.glob("feedback_*.md"):
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if mtime >= cutoff:
                    recent_memos.append(p.name)
            except OSError:
                continue

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = OUT_DIR / f"misfire-candidates-{stamp}.jsonl"
    with open(out_path, "w", encoding="utf-8") as f:
        for b in recent_blocks:
            # review_needed flag: any feedback memo exists in-window (weak global
            # signal — refined per-hook review is the human's job).
            b["review_needed"] = bool(recent_memos)
            f.write(json.dumps(b) + "\n")

    print(f"[harvest] window={days}d  block events={len(recent_blocks)}  -> {out_path}")
    print("Blocks by hook:")
    for hook, n in sorted(blocks_by_hook.items(), key=lambda kv: -kv[1]):
        print(f"  {hook:<32} {n}")
    print(f"feedback_*.md memos in window ({len(recent_memos)}): "
          f"{', '.join(sorted(recent_memos)[:8])}{' ...' if len(recent_memos) > 8 else ''}")
    print("NOTE: review the sessions around high-count hooks; promote confirmed "
          "misfires to origin:regression FP-guard cases in the hook's test_*.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
