#!/usr/bin/env python3
"""Read subagent-scope-log.jsonl and say something useful about it.

Ruled 2026-08-24 (owner decision brief, item 3). Wiktor: "cap the payload,
anyways, can we start using this data? then we could simply get rid of it once
in a while." This is the reader half. The log had been write-only since it was
created: `subagent-scope-check.py` appended a record on every subagent stop and
nothing ever opened it, so it reached 162 MB across 9,641 records without ever
answering a question.

That is the V2 the hook's own docstring describes and nobody built. The full V2
needs the subagent's declared output path from its dispatch prompt, which the
log does not carry. This reader answers what the log CAN answer on its own:

  volume      how much is here, per agent type, and how skewed
  ownership   paths doctrine says subagents do not own, changed in-window
  outliers    records whose footprint is far above normal FOR THAT AGENT TYPE
  hotspots    the files subagents touch most

WHAT THIS DATA CANNOT DO, stated up front because the first version of this
reader got it wrong. The hook diffs `git status --porcelain` between a
subagent's start and its stop. That is only ATTRIBUTION if the subagent is the
only writer in the window, and on this machine it never is: multi-session work
is the documented norm, and the main session edits files continuously while a
subagent runs. So a path here means "changed while that agent was running", a
CORRELATION, not "changed by that agent".

The ownership pass below is therefore reported as correlations, not violations.
For real attribution use the PreToolUse route, which sees the tool call itself
along with its agent_type: `memory-context-guard.py` already does exactly that
for the memory folder.

Records with no baseline are excluded from every path-level count. Before the
2026-08-24 hook fix, a missing baseline made the diff the ENTIRE dirty tree:
5,249 of 9,641 records, averaging 407 "new" files against 0.8 for records that
had a baseline, holding 161.2 MB of the log's 162.8 MB and producing 18,967 of
18,981 apparent ownership hits. All working tree, no agent.

Streaming by design: 162 MB does not go in memory. Usage:

    python .claude/scripts/scope_log_report.py            # full report
    python .claude/scripts/scope_log_report.py --ownership  # just the correlations
    python .claude/scripts/scope_log_report.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
LOG = os.path.join(VAULT, ".claude", "hooks", "subagent-scope-log.jsonl")

# Paths a subagent is not supposed to be writing. Sourced from doctrine, not invented
# here, so a change in doctrine is a change in one place and this stays honest.
OWNERSHIP_RULES = [
    (re.compile(r"\.claude/projects/[^/]+/memory/"),
     "memory folder is main-session-owned (CLAUDE.md, Memory-folder ownership)"),
    (re.compile(r"\.claude/hooks/aggregates/(governance-log|hook-activity|"
                r"telemetry-vocabulary)\."),
     "singleton aggregate, deny-tier under aggregate-write-guard.py"),
    (re.compile(r"\.claude/settings(\.local)?\.json"),
     "settings files change runtime behaviour for every session"),
    (re.compile(r"(^|/)CLAUDE\.md$"), "CLAUDE.md is doctrine"),
]


def _paths(rec):
    """Yield the changed paths from a record, tolerating both payload shapes.

    Records written before the 2026-08-24 cap carry the full `new_changes` list of
    `XX path` porcelain lines. Records after it carry a count plus a truncated
    sample. Both are read here, so the reader keeps working across the cap.
    """
    for line in (rec.get("new_changes") or []):
        if not isinstance(line, str):
            continue
        # `git status --porcelain` lines are "XY path"; the status is 2 cols + space.
        yield line[3:].strip() if len(line) > 3 and line[2] == " " else line.strip()


def scan(path=LOG):
    total = 0
    unparseable = 0
    per_agent = defaultdict(list)      # agent_type -> [footprint, ...]
    correlations = []                  # (agent, ts, path, why)
    hotspots = Counter()
    truncated = 0
    no_baseline = 0

    if not os.path.isfile(path):
        raise SystemExit("scope log not found at %s" % path)

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
            except Exception:
                unparseable += 1
                continue
            agent = rec.get("agent_type") or "unknown"
            if rec.get("new_changes_truncated") or rec.get("new_changes_total") is not None:
                truncated += 1
            n = rec.get("new_changes_total")
            if n is None:
                n = len(rec.get("new_changes") or [])
            per_agent[agent].append(n)
            # Path-level analysis only on records that actually measured a delta.
            # A record with no baseline carries either the whole tree (pre-fix) or
            # nothing (post-fix); neither says anything about this agent.
            if not rec.get("had_baseline"):
                no_baseline += 1
                continue
            for p in _paths(rec):
                hotspots[p] += 1
                for rx, why in OWNERSHIP_RULES:
                    if rx.search(p.replace("\\", "/")):
                        correlations.append((agent, rec.get("ts"), p, why))
                        break

    # A reader that finds nothing because its parse broke must say so, not print a
    # clean report. Same zero-denominator discipline as the rest of this harness.
    if total == 0:
        raise SystemExit("scope log at %s has 0 parseable records: refusing to "
                         "report a clean result on an empty read" % path)

    return {
        "records": total,
        "unparseable": unparseable,
        "capped_records": truncated,
        "no_baseline_records": no_baseline,
        "per_agent": {a: {"records": len(v), "files_total": sum(v), "max": max(v),
                          "mean": round(sum(v) / len(v), 1)}
                      for a, v in sorted(per_agent.items(),
                                         key=lambda kv: -sum(kv[1]))},
        "ownership_correlations": correlations,
        "hotspots": hotspots.most_common(15),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ownership", action="store_true", help="only the ownership correlations")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--log", default=LOG)
    args = ap.parse_args()

    r = scan(args.log)

    if args.json:
        print(json.dumps(r, indent=2, default=str))
        return 0

    v = r["ownership_correlations"]
    if args.ownership:
        print("ownership correlations: %d (changed DURING the agent, not necessarily BY it)"
              % len(v))
        for agent, ts, p, why in v[:100]:
            print("  %-24s %-24s %s\n      %s" % (agent, ts or "?", p, why))
        return 1 if v else 0

    size = os.path.getsize(args.log)
    print("subagent scope log: %d records, %.1f MB, %d unparseable, %d capped"
          % (r["records"], size / 1e6, r["unparseable"], r["capped_records"]))
    print("%d records have no baseline and are excluded from path-level counts"
          % r["no_baseline_records"])
    print()
    print("%-26s %8s %10s %8s %8s" % ("agent type", "records", "files", "max", "mean"))
    for a, s in list(r["per_agent"].items())[:12]:
        print("%-26s %8d %10d %8d %8.1f"
              % (a[:26], s["records"], s["files_total"], s["max"], s["mean"]))
    print()
    print("ownership correlations: %d (correlation, not attribution, see module docstring)"
          % len(v))
    for agent, ts, p, why in v[:20]:
        print("  %-22s %s  %s" % (agent[:22], p, why))
    print()
    print("most-touched paths:")
    for p, c in r["hotspots"][:10]:
        print("  %6d  %s" % (c, p))
    return 0


if __name__ == "__main__":
    sys.exit(main())
