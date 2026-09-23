#!/usr/bin/env python3
"""Settle the vault-ahead / repo-ahead direction call for every content-drifted twin.

Ruled 2026-08-24 (owner decision brief, item 8): "I settle them and report the
list, flagging only the genuinely undecidable."

This is what `repo-sync` needs to stop guessing. For each file that exists in
both the vault and the published framework repo and differs by CONTENT (not by
the publication scrub), which side is ahead?

Evidence, in the order it is trusted:

  1. LAST-COMMIT DATE on each side. The tree whose copy was committed more
     recently is ahead. This is the primary signal and it is a fact, not a
     judgment.
  2. MARGIN, kept deliberately SMALL. The first version of this script used a
     14-day window on the theory that a same-week edit on both sides is parallel
     divergence. That reasoning does not hold here, and it made 41 of 95 rows
     undecidable for no good reason. The repo copy is DERIVED: it is a scrubbed
     publication of the vault file, not an independent fork. So a vault commit
     dated after the repo's means the vault has edits that were never published,
     which is vault-ahead regardless of whether the gap is two days or two
     months. The only genuine ambiguity is ordering noise inside a single day.
  3. SIZE DELTA, used only to describe the call, never to make it. A file that
     grew on one side is usually the side with new material, but "usually" is
     not evidence and it does not decide anything here.

Deliberately NOT used: the content of the diff. Reading a diff and deciding
which version "looks better" is exactly the judgment this script must not make
on its own; that is what the UNDECIDABLE bucket is for.

Re-runnable by construction: takes its population from the recon artifact,
re-derives every date from git at run time, and writes nothing unless --write.

    python .claude/scripts/twin_direction_calls.py            # report
    python .claude/scripts/twin_direction_calls.py --write    # stamp the artifact
"""
from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from collections import Counter

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
RECON = os.path.join(VAULT, "Projects", "Agent-Governance-Research", "work",
                     "2026-08-23-audit-recon-classification.json")
REPO = os.path.join(VAULT, "Projects", "Agent-Governance-Research", "framework-repo")

AMBIGUOUS_DAYS = 1


def _last_commit(repo_root: str, rel: str):
    """(iso_date, subject) of the newest commit touching `rel`, or (None, None)."""
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--format=%cI%x00%s", "--", rel],
            cwd=repo_root, capture_output=True, text=True, timeout=30)
    except Exception:
        return None, None
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        return None, None
    iso, _, subject = out.partition("\x00")
    return iso.strip(), subject.strip()


def _days_between(a: str, b: str) -> float:
    from datetime import datetime
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 86400.0


def population(rows, include_called=False):
    """Rows that differ by CONTENT and do not already carry a direction."""
    out = []
    for r in rows:
        if r.get("twin_state") != "DIVERGENT":
            continue
        td = r.get("twin_diff") or {}
        if not (td.get("content_shaped", 0) > 0 or td.get("scrub_on_data", 0) > 0):
            continue
        conf = (r.get("drift_direction_confidence") or "").lower()
        # A row counts as needing a call if it has none, OR if the call it has was
        # self-flagged low-confidence by the pass that made it. All 87 content-drift
        # rows carry `confidence: "low, heuristic over-claims"`, so treating a
        # populated field as done would have closed this ticket on the prior pass's
        # own admission that it was guessing.
        # `include_called` exists because --write CLEARS this function's own selector:
        # once a row is stamped date-evidenced it no longer looks like it needs a call,
        # so a second run finds nothing and the script cannot re-derive its own output.
        # That is the same defect twin_drift_classify.py shipped with earlier the same
        # day. A number given to a decision-maker has to stay re-runnable.
        if include_called or not r.get("drift_direction") or conf.startswith("low"):
            out.append(r)
    return out


def call_direction(row):
    vault_rel = row["path"]
    repo_rel = row["twin"]
    v_date, v_sub = _last_commit(VAULT, vault_rel)
    r_date, r_sub = _last_commit(REPO, repo_rel)

    ev = {"vault_last_commit": v_date, "vault_subject": v_sub,
          "repo_last_commit": r_date, "repo_subject": r_sub}

    if not v_date and not r_date:
        return "UNDECIDABLE", "neither side has a commit touching this path", ev
    if not r_date:
        return "vault-ahead", "the repo has no commit touching its copy", ev
    if not v_date:
        return "repo-ahead", "the vault has no commit touching its copy", ev

    gap = _days_between(v_date, r_date)
    if gap < AMBIGUOUS_DAYS:
        return ("UNDECIDABLE",
                "both sides were last committed within %d day (%.2f), so intra-day "
                "ordering is not evidence of direction" % (AMBIGUOUS_DAYS, gap), ev)
    if v_date > r_date:
        return "vault-ahead", "vault copy committed %.0f days later" % gap, ev
    return "repo-ahead", "repo copy committed %.0f days later" % gap, ev


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true",
                    help="re-derive every content-drift row, including ones already called")
    ap.add_argument("--write", action="store_true",
                    help="stamp drift_direction onto the recon artifact")
    args = ap.parse_args()

    doc = json.load(io.open(RECON, encoding="utf-8"))
    rows = doc["rows"]
    pop = population(rows, include_called=args.all)

    if not pop:
        print("no rows need a call. If you meant to re-derive the ones already stamped, "
              "pass --all; if you expected work here, check twin_state/content_shaped "
              "before reading this as done.")
        return 0

    calls = Counter()
    results = []
    for row in pop:
        direction, why, ev = call_direction(row)
        calls[direction] += 1
        results.append((row["path"], direction, why))
        if args.write:
            row["drift_direction"] = direction
            row["drift_direction_confidence"] = "undecidable" if direction == "UNDECIDABLE" else "date-evidenced"
            row["drift_direction_why"] = why
            row["drift_evidence"] = ev
            row["drift_direction_called"] = "2026-08-24 twin_direction_calls.py"

    print("content-drift rows needing a call: %d" % len(pop))
    for k, v in calls.most_common():
        print("  %-14s %d" % (k, v))
    print()
    for path, direction, why in sorted(results, key=lambda x: (x[1], x[0])):
        print("  %-12s %-58s %s" % (direction, path[:58], why))

    if args.write:
        io.open(RECON, "w", encoding="utf-8").write(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print()
        print("stamped %d rows into %s" % (len(pop), os.path.basename(RECON)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
