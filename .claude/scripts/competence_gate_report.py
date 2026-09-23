"""
competence_gate_report.py — Step-11 competence-gate measurement analytics (spec Step 5)

Spec: Projects/Agent-Governance-Research/work/2026-07-10-step11-competence-gate-spec.md §5 Step 5
Role: offline gate-evaluation table for the advisory window. Reads
      competence_gate_decision events from governance-log.jsonl (FULL read —
      this script is never on the dispatch path) and prints, per agent_type:
      total decisions, scored decisions (verdict OK|BELOW), score distribution
      (min / p50 / max), warn count + rate, NO_SIGNAL count + rate, and verdict
      counts. Every high-tier agent from the risk-tier sidecar is listed even
      at zero decisions (sparsity must stay visible for the Step-6 window and
      kill criterion 1). Agent types seen in gate events but ABSENT from the
      sidecar are listed separately so the analytics view is not blind to them.

Mandatory analytic pre-filters (spec DQ-1):
  - entries with session == 'session' (synthetic subprocess-test pollution)
    are dropped before any counting;
  - command_prefix is never used anywhere in this script.

Usage:
    python competence_gate_report.py [--log PATH] [--tiers PATH]

    --log    Path to governance-log.jsonl.
             Default: .claude/hooks/governance-log.jsonl (relative to CWD, vault root).
    --tiers  Path to the risk-tier sidecar.
             Default: .claude/hooks/_agent_risk_tiers.json

Exit codes: 0 = success (including an empty table). Non-zero only if the log
or sidecar file is unreadable. Malformed JSONL lines are skipped silently.
Stdlib only; encoding='utf-8' on every read.
"""

import argparse
import json
import sys

DEFAULT_LOG = ".claude/hooks/governance-log.jsonl"
DEFAULT_TIERS = ".claude/hooks/_agent_risk_tiers.json"

_SYNTHETIC_SESSION = "session"
_GATE_EVENT = "competence_gate_decision"
_SCORED_VERDICTS = ("OK", "BELOW")


def read_decisions(log_path):
    """Read competence_gate_decision events from the log, pre-filters applied.

    Full read (offline analytics). Malformed lines skipped; synthetic-session
    entries (session == 'session') dropped before any counting.
    """
    decisions = []
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("event") != _GATE_EVENT:
                continue
            if entry.get("session") == _SYNTHETIC_SESSION:
                continue
            decisions.append(entry)
    return decisions


def load_high_tier_agents(tiers_path):
    """Return (sorted high-tier agent list, set of all sidecar agent names)."""
    with open(tiers_path, "r", encoding="utf-8") as f:
        tiers = json.load(f)
    agents = {
        name: spec for name, spec in tiers.items()
        if not name.startswith("_") and isinstance(spec, dict)
    }
    high = sorted(n for n, s in agents.items() if s.get("tier") == "high")
    return high, set(agents)


def _p50(values):
    """Median of a non-empty list (mean of the two middles for even n)."""
    srt = sorted(values)
    n = len(srt)
    mid = n // 2
    if n % 2 == 1:
        return srt[mid]
    return (srt[mid - 1] + srt[mid]) / 2


def summarize(decisions, high_tier_agents, sidecar_agents):
    """Per-agent summary rows. Pure function (no I/O).

    Returns {"rows": {agent_type: row}, "unknown_agents": [names]} where every
    high-tier agent has a row even at zero decisions, and unknown_agents are
    agent types seen in gate events but absent from the sidecar entirely.
    """
    by_agent = {}
    for d in decisions:
        by_agent.setdefault(d.get("agent_type", "unknown"), []).append(d)

    rows = {}
    listed = set(high_tier_agents) | set(by_agent)
    for agent in sorted(listed):
        evs = by_agent.get(agent, [])
        total = len(evs)
        scores = [
            e["score"] for e in evs
            if e.get("verdict") in _SCORED_VERDICTS
            and isinstance(e.get("score"), (int, float))
        ]
        n_scored = len(scores)
        warns = sum(1 for e in evs if e.get("action_taken") == "warn")
        no_signal = sum(1 for e in evs if e.get("verdict") == "NO_SIGNAL")
        verdicts = {}
        for e in evs:
            v = e.get("verdict", "unknown")
            verdicts[v] = verdicts.get(v, 0) + 1
        rows[agent] = {
            "total": total,
            "n_scored": n_scored,
            "score_min": min(scores) if scores else None,
            "score_p50": _p50(scores) if scores else None,
            "score_max": max(scores) if scores else None,
            "warn_count": warns,
            "warn_rate": (warns / total) if total else None,
            "no_signal_count": no_signal,
            "no_signal_rate": (no_signal / total) if total else None,
            "verdict_counts": verdicts,
        }

    unknown_agents = sorted(set(by_agent) - sidecar_agents)
    return {"rows": rows, "unknown_agents": unknown_agents}


def _fmt(value, pattern="{:.2f}"):
    return pattern.format(value) if value is not None else "-"


def format_table(summary, high_tier_agents):
    """Render the gate-evaluation table as text."""
    lines = []
    header = (
        f"{'agent_type':<28} {'total':>5} {'scored':>6} "
        f"{'min':>5} {'p50':>5} {'max':>5} "
        f"{'warn':>4} {'w_rate':>6} {'nosig':>5} {'ns_rate':>7}  verdicts"
    )
    lines.append("COMPETENCE GATE REPORT (structural reliability signal, advisory window)")
    lines.append("pre-filters: session != 'session'; command_prefix never used")
    lines.append("")
    lines.append(header)
    lines.append("-" * len(header))
    high_set = set(high_tier_agents)
    for agent, r in summary["rows"].items():
        tag = "" if agent in high_set else " (non-sidecar-high)"
        verdicts = ",".join(
            f"{k}={v}" for k, v in sorted(r["verdict_counts"].items())
        ) or "-"
        lines.append(
            f"{agent + tag:<28} {r['total']:>5} {r['n_scored']:>6} "
            f"{_fmt(r['score_min']):>5} {_fmt(r['score_p50']):>5} "
            f"{_fmt(r['score_max']):>5} "
            f"{r['warn_count']:>4} {_fmt(r['warn_rate']):>6} "
            f"{r['no_signal_count']:>5} {_fmt(r['no_signal_rate']):>7}  {verdicts}"
        )
    if summary["unknown_agents"]:
        lines.append("")
        lines.append(
            "agent types seen in gate events but ABSENT from the sidecar: "
            + ", ".join(summary["unknown_agents"])
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--log", default=DEFAULT_LOG)
    parser.add_argument("--tiers", default=DEFAULT_TIERS)
    args = parser.parse_args(argv)

    try:
        high, sidecar_agents = load_high_tier_agents(args.tiers)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FATAL: cannot read tier sidecar {args.tiers}: {exc}", file=sys.stderr)
        return 1
    try:
        decisions = read_decisions(args.log)
    except OSError as exc:
        print(f"FATAL: cannot read log {args.log}: {exc}", file=sys.stderr)
        return 1

    summary = summarize(decisions, high, sidecar_agents)
    print(format_table(summary, high))
    return 0


if __name__ == "__main__":
    sys.exit(main())
