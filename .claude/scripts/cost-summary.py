#!/usr/bin/env python3
"""Cost summary script (2026-05-10).

NOTE: Output is API-EQUIVALENT VALUE, not actual billing.
Wiktor is on Claude Max 5x subscription ($100/month flat) — see
memory/reference_wiktor_on_claude_max_5x_subscription.md. The dollar figures
are useful as a usage-volume proxy with intuitive units, but are NOT spend.
Actual constraint is the 5-hour rolling rate-limit window. Read accordingly.

Computes API-equivalent value from `event: "token_breakdown"` rows in
`.claude/hooks/governance-log.jsonl` using Anthropic published per-million rates.

Usage:
  python cost-summary.py                 # last 24h, default
  python cost-summary.py --hours 168     # last week
  python cost-summary.py --since 2026-05-01
  python cost-summary.py --by-session    # per-session breakdown
  python cost-summary.py --by-day        # per-day breakdown
  python cost-summary.py --json          # JSON output for programmatic use

Default model assumption:
  main_session  = Opus 4.7 (1M context) — Wiktor's primary
  by_subagent   = Sonnet 4.6 (per delegation directive)
Override per-row via environment if needed (out of scope for v1).

Pricing as of 2026-05 (verify before use):
  Opus 4.7 (1M):     $15/M input, $75/M output, $1.50/M cache_read, $18.75/M cache_creation
  Sonnet 4.6:        $3/M input,  $15/M output, $0.30/M cache_read, $3.75/M cache_creation
  Haiku 4.5:         $0.80/M input, $4/M output, $0.08/M cache_read, $1/M cache_creation
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = VAULT / ".claude" / "hooks" / "governance-log.jsonl"

PRICING = {
    "opus": {
        "input": 15.0,
        "output": 75.0,
        "cache_read": 1.50,
        "cache_creation": 18.75,
    },
    "sonnet": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,
        "cache_creation": 3.75,
    },
    "haiku": {
        "input": 0.80,
        "output": 4.0,
        "cache_read": 0.08,
        "cache_creation": 1.0,
    },
}


def cost_for(token_obj, model="opus"):
    """Compute USD cost from a token-object dict using PRICING[model] (per-million rates)."""
    if not token_obj:
        return 0.0
    rates = PRICING[model]
    inp = token_obj.get("input_tokens", 0)
    out = token_obj.get("output_tokens", 0)
    cr = token_obj.get("cache_read_input_tokens", 0)
    cc = token_obj.get("cache_creation_input_tokens", 0)
    return (
        inp * rates["input"]
        + out * rates["output"]
        + cr * rates["cache_read"]
        + cc * rates["cache_creation"]
    ) / 1_000_000.0


def load_token_rows(since_dt):
    """Yield token_breakdown rows from governance-log.jsonl with ts >= since_dt."""
    if not LOG_PATH.is_file():
        return
    with LOG_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if row.get("event") != "token_breakdown":
                continue
            ts_str = row.get("ts", "")
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                continue
            if ts < since_dt:
                continue
            yield ts, row


def aggregate(rows):
    """Aggregate cost across rows into totals + per-session + per-day buckets."""
    totals = {
        "main_cost": 0.0,
        "subagent_cost": 0.0,
        "main_tokens": 0,
        "subagent_tokens": 0,
        "row_count": 0,
    }
    per_session = defaultdict(lambda: {"cost": 0.0, "tokens": 0, "rows": 0})
    per_day = defaultdict(lambda: {"cost": 0.0, "tokens": 0, "rows": 0})
    per_task_type = defaultdict(lambda: {"cost": 0.0, "rows": 0})

    for ts, row in rows:
        main = row.get("main_session") or {}
        subs = row.get("by_subagent") or []

        main_cost = cost_for(main, model="opus")
        sub_cost = sum(cost_for(s, model="sonnet") for s in subs)
        row_total = row.get("turn_total_tokens", 0)
        sub_tokens = sum(
            (s.get("input_tokens", 0) + s.get("output_tokens", 0)
             + s.get("cache_read_input_tokens", 0) + s.get("cache_creation_input_tokens", 0))
            for s in subs
        )
        main_tokens = row_total - sub_tokens

        totals["main_cost"] += main_cost
        totals["subagent_cost"] += sub_cost
        totals["main_tokens"] += main_tokens
        totals["subagent_tokens"] += sub_tokens
        totals["row_count"] += 1

        sess = row.get("session", "(unknown)")
        per_session[sess]["cost"] += main_cost + sub_cost
        per_session[sess]["tokens"] += row_total
        per_session[sess]["rows"] += 1

        day = ts.strftime("%Y-%m-%d")
        per_day[day]["cost"] += main_cost + sub_cost
        per_day[day]["tokens"] += row_total
        per_day[day]["rows"] += 1

        ttype = row.get("task_type", "(unknown)")
        per_task_type[ttype]["cost"] += main_cost + sub_cost
        per_task_type[ttype]["rows"] += 1

    return totals, per_session, per_day, per_task_type


def fmt_usd(x):
    return f"${x:.4f}" if x < 1 else f"${x:.2f}"


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def main():
    ap = argparse.ArgumentParser(description="Anthropic API cost summary from governance-log.jsonl")
    ap.add_argument("--hours", type=int, default=None, help="Look-back window in hours (default 24)")
    ap.add_argument("--since", type=str, default=None, help="ISO date (YYYY-MM-DD) to start from")
    ap.add_argument("--by-session", action="store_true", help="Per-session breakdown")
    ap.add_argument("--by-day", action="store_true", help="Per-day breakdown")
    ap.add_argument("--by-task-type", action="store_true", help="Per-task-type breakdown")
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of human format")
    args = ap.parse_args()

    if args.since:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d")
        window_label = f"since {args.since}"
    elif args.hours is not None:
        since_dt = datetime.now() - timedelta(hours=args.hours)
        window_label = f"last {args.hours}h"
    else:
        since_dt = datetime.now() - timedelta(hours=24)
        window_label = "last 24h"

    rows = list(load_token_rows(since_dt))
    totals, per_session, per_day, per_task_type = aggregate(rows)

    if args.json:
        out = {
            "window": window_label,
            "since": since_dt.isoformat(),
            "totals": {
                "total_cost_usd": round(totals["main_cost"] + totals["subagent_cost"], 4),
                "main_cost_usd": round(totals["main_cost"], 4),
                "subagent_cost_usd": round(totals["subagent_cost"], 4),
                "main_tokens": totals["main_tokens"],
                "subagent_tokens": totals["subagent_tokens"],
                "turn_count": totals["row_count"],
            },
            "by_day": {d: {"cost_usd": round(v["cost"], 4), "tokens": v["tokens"], "turns": v["rows"]}
                       for d, v in sorted(per_day.items())},
            "by_session": {s: {"cost_usd": round(v["cost"], 4), "tokens": v["tokens"], "turns": v["rows"]}
                           for s, v in per_session.items()} if args.by_session else None,
            "by_task_type": {t: {"cost_usd": round(v["cost"], 4), "turns": v["rows"]}
                             for t, v in per_task_type.items()} if args.by_task_type else None,
            "pricing_model_assumption": {
                "main_session": "opus 4.7 (1M)",
                "by_subagent": "sonnet 4.6",
            },
        }
        print(json.dumps(out, indent=2))
        return

    # Human format
    total = totals["main_cost"] + totals["subagent_cost"]
    print(f"API-equivalent value — {window_label}")
    print(f"  (Wiktor is on Max 5x flat-rate; figures are usage proxy, NOT actual spend)")
    print(f"  Window since: {since_dt.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Turns: {totals['row_count']}")
    print(f"  TOTAL: {fmt_usd(total)} API-equivalent  ({fmt_tokens(totals['main_tokens'] + totals['subagent_tokens'])} tokens)")
    print(f"  Main session (Opus): {fmt_usd(totals['main_cost'])}  ({fmt_tokens(totals['main_tokens'])} tokens)")
    print(f"  Subagents  (Sonnet): {fmt_usd(totals['subagent_cost'])}  ({fmt_tokens(totals['subagent_tokens'])} tokens)")

    if args.by_day and per_day:
        print("\nPer-day:")
        for day in sorted(per_day.keys()):
            v = per_day[day]
            print(f"  {day}: {fmt_usd(v['cost'])}  ({fmt_tokens(v['tokens'])} / {v['rows']} turns)")

    if args.by_session and per_session:
        print("\nPer-session:")
        # Sort by cost desc, top 10
        sorted_s = sorted(per_session.items(), key=lambda x: -x[1]["cost"])[:10]
        for sess, v in sorted_s:
            sess_short = sess[:8] if sess != "(unknown)" else sess
            print(f"  {sess_short}...: {fmt_usd(v['cost'])}  ({fmt_tokens(v['tokens'])} / {v['rows']} turns)")

    if args.by_task_type and per_task_type:
        print("\nPer-task-type:")
        for ttype, v in sorted(per_task_type.items(), key=lambda x: -x[1]["cost"]):
            print(f"  {ttype}: {fmt_usd(v['cost'])}  ({v['rows']} turns)")


if __name__ == "__main__":
    main()
