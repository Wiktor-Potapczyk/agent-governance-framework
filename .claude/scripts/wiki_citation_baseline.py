#!/usr/bin/env python3
r"""Recompute the wiki-citation block-rate baseline that decision 3 rests on.

The question this answers: if `wiki-citation-check.py`'s hard block were switched
on, as CLAUDE.md's Wiki Layer Invariants already claim it is, what fraction of real
wiki writes would have been blocked?

It reads the hook's OWN emitted findings from its aggregate rather than
re-implementing the citation logic, so the number reflects what the shipped hook
actually decided, not a second opinion about what it should have decided.

CONTAMINATION WINDOW. On 2026-08-23 and 2026-08-24 a probe for
`hook-write-regression-gate.py` sent it a hook .py write with no isolated target
directory, so the gate ran the live hook suite, which contains the control-fires
suite, which ran the probe again. Every recursion level reached the wiki-citation
probe and appended one synthetic record naming
`Resources/KB/ralph-loop-research-2026-03.md`. That added roughly 20,700 records in
two days, against 185 real ones in the preceding three months, so a naive count of
this file overstates the population by more than a hundredfold. Those two days are
excluded by default. Pass --include-contaminated to see the raw figure.

Usage:
    python .claude/scripts/wiki_citation_baseline.py [--include-contaminated]
"""

import collections
import json
import os
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AGGREGATE = os.path.join(VAULT, ".claude", "hooks", "aggregates",
                         "wiki-citation-violations.jsonl")
CONTAMINATED_FROM = "2026-08-23"


def main():
    include = "--include-contaminated" in sys.argv
    if not os.path.exists(AGGREGATE):
        print(f"aggregate not found: {AGGREGATE}")
        return 1

    total = considered = with_findings = blocked = 0
    codes = collections.Counter()
    files = collections.Counter()

    with open(AGGREGATE, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            total += 1
            if not include and rec.get("ts", "")[:10] >= CONTAMINATED_FROM:
                continue
            considered += 1
            if rec.get("blocked"):
                blocked += 1
            findings = rec.get("findings") or []
            if findings:
                with_findings += 1
                files[rec.get("file")] += 1
                for f in findings:
                    codes[f.get("code")] += 1

    if considered == 0:
        print("zero records in the window, so any rate below would be meaningless")
        return 1

    rate = 100.0 * with_findings / considered
    print(f"aggregate            : {AGGREGATE}")
    print(f"records in file      : {total}")
    print(f"window               : {'ALL (contaminated)' if include else 'before ' + CONTAMINATED_FROM}")
    print(f"records considered   : {considered}")
    print(f"actually blocked     : {blocked}")
    print(f"carrying findings    : {with_findings}")
    print(f"clean                : {considered - with_findings}")
    print(f"WOULD-BLOCK RATE     : {rate:.1f}%")
    print()
    print("finding codes:")
    for code, n in codes.most_common():
        print(f"  {n:6d}  {code}")
    print()
    print("files carrying findings:")
    for name, n in files.most_common(10):
        print(f"  {n:6d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
