#!/usr/bin/env python3
"""Recurrence-diff for the self-improvement loop MEASURE leg (N3).

Stdlib-only. Makes ledger-SUPPRESSED recurrences VISIBLE for measurement by
calling mine_governance.mine() twice:

  1. UNSUPPRESSED truth  — mine(..., resolved_ledger_path=None): every recurring
     sig, including sigs the operational ledger hides.
  2. Operational view    — mine(..., resolved_ledger_path=<real ledger>): the
     day-to-day view where ratified sigs are suppressed.

Each sig_id in the unsuppressed run is classified against (a) the real ledger's
ruled sig_ids and (b) the PRIOR run's stored unsuppressed sig set:

  RESOLVED  — ledgered AND absent from the current unsuppressed run.
  OPEN      — present in the current run, NOT ledgered.
  REGRESSED — ledgered BUT still present at >= its prior count in the current
              unsuppressed run. The ledger hid it; the diff surfaces it. This is
              the R2 anti-masking guarantee (spec Section 9): a ledger-suppressed
              recurrence must never be invisible.
  NEW       — present in the current run, absent from the prior run, not ledgered.

The script WRITES NOTHING under any live .claude/ path. It emits verdicts + a
summary table to stdout (and an optional --out path, which must live outside the
.claude/ live tree — /tmp or a caller-supplied scratch path).

The `session != 'session'` subprocess-test filter is inherited from mine();
this script does not re-implement admission or normalization.

Design refs:
  - Projects/Agent-Governance-Research/work/2026-07-13-self-improvement-loop-spec.md
    Section 4 (measurement leg), N3.
  - .claude/hooks/mine_governance.py  mine() signature (verified 2026-07-14):
    mine(log_path, now_date, window_days=WINDOW_DAYS, resolved_ledger_path=None).
"""

import argparse
import json
import os
import sys
from datetime import date

# --- import mine() from the hooks dir, mirroring test_mine_governance.py -----
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.normpath(os.path.join(_THIS_DIR, "..", "hooks"))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from mine_governance import mine, WINDOW_DAYS  # noqa: E402


# Verdict labels
RESOLVED = "RESOLVED"
OPEN = "OPEN"
REGRESSED = "REGRESSED"
NEW = "NEW"


def _ledger_sig_ids(ledger_path):
    """Return the set of sig_ids present in the resolved ledger.

    Boundary: tolerate a missing/unreadable ledger (returns empty set) and skip
    unparseable lines. Read-only.
    """
    sids = set()
    if not ledger_path or not os.path.isfile(ledger_path):
        return sids
    try:
        with open(ledger_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except Exception:
                    continue
                sid = entry.get("sig_id", "")
                if sid:
                    sids.add(sid)
    except OSError:
        pass
    return sids


def _load_prior_counts(prior_path):
    """Return {sig_id: count} from a prior run's stored unsuppressed sig set.

    Accepts either:
      - a JSON object {"sig_counts": {sig_id: count, ...}}  (this script's own
        --out format), or
      - a bare JSON object {sig_id: count, ...}.
    A missing/None prior path => {} (no prior run; nothing REGRESSED/RESOLVED can
    be computed relative to a prior, so every present sig is OPEN or NEW).
    Read-only; boundary-tolerant.
    """
    if not prior_path or not os.path.isfile(prior_path):
        return {}
    try:
        with open(prior_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("sig_counts"), dict):
        data = data["sig_counts"]
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def classify(unsuppressed, ledger_sids, prior_counts):
    """Classify each sig into RESOLVED / OPEN / REGRESSED / NEW.

    Parameters
    ----------
    unsuppressed : list of dict
        Records from mine(..., resolved_ledger_path=None) — the unsuppressed truth.
        Each has at least 'sig_id' and 'count'.
    ledger_sids : set of str
        sig_ids present in the real resolved ledger (ruled/suppressed sigs).
    prior_counts : dict {sig_id: count}
        The prior run's unsuppressed sig counts. May be empty (no prior run).

    Returns
    -------
    dict  {sig_id: {"verdict": <label>, "count": int, "prior_count": int|None,
                     "ledgered": bool}}

    Classification precedence, per sig present in the current unsuppressed run:
      - ledgered AND count >= prior_count(>0)  -> REGRESSED (anti-masking)
      - ledgered AND (no meaningful prior recurrence) -> still visible but treated
        OPEN-relative-to-ledger only if not below prior; a ledgered sig that is
        still present is at minimum surfaced. We classify a ledgered+present sig
        REGRESSED whenever it meets/exceeds its prior count (the guarantee), else
        (present but below its prior count) it is decaying -> reported OPEN with
        ledgered=True so it is not silently dropped.
      - not ledgered AND in prior           -> OPEN
      - not ledgered AND not in prior        -> NEW
    Plus, for ledgered sigs that are ABSENT from the current unsuppressed run:
      - RESOLVED (the ruling held).
    """
    result = {}
    present = {rec["sig_id"]: int(rec.get("count", 0)) for rec in unsuppressed}

    # Sigs present in the current unsuppressed run.
    for sid, cnt in present.items():
        prior = prior_counts.get(sid)
        ledgered = sid in ledger_sids
        if ledgered:
            # Anti-masking: a ledgered sig still recurring at/above its prior
            # count is REGRESSED. With no prior (prior is None), any continued
            # presence of a ledgered sig is a regression signal too.
            if prior is None or cnt >= prior:
                verdict = REGRESSED
            else:
                # Present but below prior — decaying, not yet resolved; keep it
                # visible rather than dropping it.
                verdict = OPEN
        else:
            verdict = OPEN if sid in prior_counts else NEW
        result[sid] = {
            "verdict": verdict,
            "count": cnt,
            "prior_count": prior,
            "ledgered": ledgered,
        }

    # Ledgered sigs that vanished from the current unsuppressed run => RESOLVED.
    for sid in ledger_sids:
        if sid not in present:
            result[sid] = {
                "verdict": RESOLVED,
                "count": 0,
                "prior_count": prior_counts.get(sid),
                "ledgered": True,
            }

    return result


def summary_table(classified):
    """Return a plain-text summary table (no fancy dashes)."""
    order = {REGRESSED: 0, NEW: 1, OPEN: 2, RESOLVED: 3}
    rows = sorted(
        classified.items(),
        key=lambda kv: (order.get(kv[1]["verdict"], 9), -kv[1]["count"]),
    )
    lines = []
    lines.append(f"{'sig_id':<14} {'verdict':<10} {'count':>5} {'prior':>6} {'ledgered':>8}")
    lines.append("-" * 48)
    for sid, info in rows:
        prior = info["prior_count"]
        prior_s = "None" if prior is None else str(prior)
        lines.append(
            f"{sid:<14} {info['verdict']:<10} {info['count']:>5} "
            f"{prior_s:>6} {str(info['ledgered']):>8}"
        )
    counts = {}
    for _sid, info in classified.items():
        counts[info["verdict"]] = counts.get(info["verdict"], 0) + 1
    lines.append("")
    lines.append(
        "totals: "
        + ", ".join(f"{k}={counts.get(k, 0)}" for k in (REGRESSED, NEW, OPEN, RESOLVED))
    )
    return "\n".join(lines)


def diff_runs(log_path, ledger_path, now_date, window_days=WINDOW_DAYS,
              prior_path=None):
    """Run the two mine() passes and classify. Returns (classified, unsuppressed, suppressed).

    - unsuppressed: mine(resolved_ledger_path=None)  -> the source of truth.
    - suppressed:   mine(resolved_ledger_path=ledger) -> operational cross-check.
    The suppressed pass is computed for the operational view only; classification
    uses the unsuppressed pass against the ledger sig set + prior counts, so
    ledgered-but-recurring sigs cannot be hidden.
    """
    unsuppressed = mine(log_path, now_date, window_days, resolved_ledger_path=None)
    suppressed = mine(log_path, now_date, window_days, resolved_ledger_path=ledger_path)
    ledger_sids = _ledger_sig_ids(ledger_path)
    prior_counts = _load_prior_counts(prior_path)
    classified = classify(unsuppressed, ledger_sids, prior_counts)
    return classified, unsuppressed, suppressed


def _sig_counts(unsuppressed):
    """{sig_id: count} snapshot of an unsuppressed run, for storing as the next
    run's prior."""
    return {rec["sig_id"]: int(rec.get("count", 0)) for rec in unsuppressed}


def main(argv=None):
    p = argparse.ArgumentParser(description="Recurrence-diff of two mine() runs (N3).")
    p.add_argument("--log", required=True, help="governance-log.jsonl path")
    p.add_argument("--ledger", required=True, help="miner-resolved.jsonl path")
    p.add_argument("--now", default=date.today().isoformat(),
                   help="reference date YYYY-MM-DD (default: today)")
    p.add_argument("--window", type=int, default=WINDOW_DAYS,
                   help=f"rolling window in days (default {WINDOW_DAYS})")
    p.add_argument("--prior", default=None,
                   help="prior run's stored sig-count JSON (optional)")
    p.add_argument("--out", default=None,
                   help="optional path to write this run's sig-count snapshot "
                        "(MUST be outside the live .claude/ tree, e.g. /tmp)")
    args = p.parse_args(argv)

    # Guard: refuse early if --log path does not exist as a file.
    resolved_log = os.path.abspath(args.log)
    if not os.path.isfile(resolved_log):
        print(f"REFUSED: --log path does not exist: {resolved_log}", file=sys.stderr)
        return 2

    classified, unsuppressed, _suppressed = diff_runs(
        args.log, args.ledger, args.now, args.window, args.prior
    )

    print(summary_table(classified))

    if args.out:
        # Guard: never write into the live .claude/ tree.
        norm = os.path.normpath(os.path.abspath(args.out))
        live = os.path.normpath(os.path.abspath(
            os.path.join(_THIS_DIR, "..")))  # the .claude/ dir
        if norm.startswith(live + os.sep):
            print(f"REFUSED: --out {args.out} is inside the live .claude/ tree",
                  file=sys.stderr)
            return 2
        with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"now": args.now, "sig_counts": _sig_counts(unsuppressed)},
                      fh, ensure_ascii=False, indent=2)
        print(f"\nsnapshot written: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
