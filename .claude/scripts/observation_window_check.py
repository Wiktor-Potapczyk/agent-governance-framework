"""
observation_window_check.py - O12 observation-window checker.

Evaluates the staleness-board SessionStart run record over a bounded
observation window and renders a PASS/FAIL verdict per the ratified O12 spec
(Projects/Agent-Governance-Research/work/2026-08-31-harness-takeover-objectives.md
lines 103-121) and the 2026-09-02 PM ruling (window bounds are arguments).

Three branches, all of which must hold for PASS:
  (a) VACUITY                  at least --min-evaluations (default 10) board
                               evaluations logged in-window. An evaluation is a
                               hook-activity.jsonl record with event=hook_fire,
                               hook=staleness_check, decision in {pass, warn}.
                               decision=error runs evaluated nothing: reported,
                               never counted.
  (b) INCIDENT_LEDGER_NONEMPTY the incident ledger has zero INCIDENT lines.
  (c) UNRESOLVED_FAIL_OVER_48H every in-window FAIL episode was cleared by a
                               later clean evaluation within 48 hours of its
                               first in-window failing record, or classified by
                               an INCIDENT ledger line naming its entry id and
                               dated within 48 hours of episode start.

The FAIL set is every per-entry verdict except PASS and WARN (WARN is advisory
per O10 D4 and O12 risk flag 3): {STALE, ERROR, DIVERGENT, BROKEN_CITATION}.

Verdicts and exit codes:
  0  PASS                   all branches hold, nothing pending
  2  FAIL                   at least one branch failed (a legitimate recordable
                            outcome, never an error)
  3  INCONCLUSIVE_PENDING   no branch failed, but an unresolved episode is
                            younger than 48h at --now; the report names the
                            earliest re-run time
  1  record/usage error     missing run-log or ledger, malformed INCIDENT
                            line, unparseable staleness record

Determinism: window bounds, --now (defaulting to local datetime.now()) and the
record are the only time sources; identical inputs plus identical --now give
byte-identical --json output. All timestamps are naive local, matching
_governance_logger.py (datetime.now(), line 163). Details are truncated to 200
chars at the sink (line 167): a warn detail of exactly 200 chars has its
trailing partial pair dropped with a loud notice.

Read-only over every sink; never calls log_fire (anti-coercion: no sink
record is ever changed).

Usage:
  "C:/Program Files/Python314/python.exe" .claude/scripts/observation_window_check.py
      --window-start "2026-09-03 00:00:00" --window-end "2026-09-17 00:00:00"
      [--run-log PATH] [--ledger PATH] [--now "YYYY-MM-DD HH:MM:SS"]
      [--min-evaluations 10] [--json]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from staleness_check import (  # noqa: E402
    VERDICT_PASS,
    VERDICT_WARN,
    VERDICT_STALE,
    VERDICT_ERROR,
    VERDICT_DIVERGENT,
    VERDICT_BROKEN_CITATION,
)

VAULT_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_RUN_LOG = VAULT_ROOT / ".claude" / "hooks" / "hook-activity.jsonl"
DEFAULT_LEDGER = (VAULT_ROOT / "Projects" / "Agent-Governance-Research"
                  / "work" / "2026-09-02-o12-incident-ledger.md")

KNOWN_VERDICTS = {VERDICT_PASS, VERDICT_WARN, VERDICT_STALE, VERDICT_ERROR,
                  VERDICT_DIVERGENT, VERDICT_BROKEN_CITATION}
FAIL_VERDICTS = KNOWN_VERDICTS - {VERDICT_PASS, VERDICT_WARN}

BRANCH_VACUITY = "VACUITY"
BRANCH_LEDGER = "INCIDENT_LEDGER_NONEMPTY"
BRANCH_UNRESOLVED = "UNRESOLVED_FAIL_OVER_48H"

RESOLUTION_WINDOW = timedelta(hours=48)
DETAIL_TRUNCATION_LEN = 200  # _governance_logger.py line 167
TS_FMT = "%Y-%m-%d %H:%M:%S"


class RecordError(Exception):
    """A record or usage problem that makes the verdict unproducible.
    Distinct from FAIL, which is a legitimate produced verdict."""


def parse_ts(value, what="timestamp"):
    """Naive local timestamp. Accepts YYYY-MM-DD HH:MM[:SS], T separator too."""
    try:
        ts = datetime.fromisoformat(str(value).strip())
    except (ValueError, TypeError) as exc:
        raise RecordError("unparseable %s: %r (%s)" % (what, value, exc))
    if ts.tzinfo is not None:
        raise RecordError("%s %r carries a timezone; the record is naive local"
                          % (what, value))
    return ts


def fmt_ts(ts):
    return ts.strftime(TS_FMT)


def parse_warn_detail(detail, ts_label):
    """Parse a warn record's detail into [(id, verdict)] plus notices.

    The sink joins failing entries with "; " (staleness_check._run_hook_mode)
    and truncates the string to 200 chars (_governance_logger.py). A detail of
    exactly 200 chars may end in a partial pair: complete pairs are kept, the
    trailing partial is dropped, and a loud notice is emitted. A malformed
    token anywhere else is a RecordError, never silently skipped.
    """
    notices = []
    text = "" if detail is None else str(detail)
    truncated = len(text) == DETAIL_TRUNCATION_LEN
    tokens = [t.strip() for t in text.split(";")]
    tokens = [t for t in tokens if t]
    pairs = []
    for i, token in enumerate(tokens):
        entry_id, sep, verdict = token.rpartition(":")
        ok = bool(sep) and bool(entry_id) and verdict in KNOWN_VERDICTS
        if ok:
            pairs.append((entry_id, verdict))
            continue
        if truncated and i == len(tokens) - 1:
            notices.append(
                "warn record at %s: detail is exactly %d chars (sink "
                "truncation); dropped trailing partial pair %r. Failing ids "
                "beyond the cut are invisible to this check." %
                (ts_label, DETAIL_TRUNCATION_LEN, token))
            continue
        raise RecordError(
            "warn record at %s: unparseable id:VERDICT token %r in detail %r"
            % (ts_label, token, text))
    return pairs, notices


def load_run_records(run_log, window_start, window_end):
    """Stream the run-log; return (evaluations, error_runs, notices).

    An evaluation dict: {ts: datetime, failing: set of entry ids}. Records of
    other hooks are ignored. A staleness_check record that parses as JSON but
    has bad fields is a RecordError (fail loud, never guess). A line that is
    not JSON at all is skipped WITH a loud notice: the live multi-writer sink
    holds torn lines (67 counted 2026-09-02, e.g. a bare brace from an
    interleaved concurrent append) that carry no timestamp or hook name, so
    they cannot be attributed; aborting on them would make the real-record
    run permanently impossible."""
    if not run_log.exists():
        raise RecordError("run-log not found: %s" % run_log)
    evaluations = []
    error_runs = []
    notices = []
    unparseable = []
    with run_log.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                unparseable.append(lineno)
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("hook") != "staleness_check":
                continue
            if rec.get("event") != "hook_fire":
                continue
            ts = parse_ts(rec.get("ts"), "record ts (line %d)" % lineno)
            if not (window_start <= ts < window_end):
                continue
            decision = rec.get("decision")
            if decision == "error":
                error_runs.append({"ts": fmt_ts(ts),
                                   "detail": rec.get("detail")})
                continue
            if decision == "pass":
                evaluations.append({"ts": ts, "failing": set()})
                continue
            if decision == "warn":
                pairs, pair_notices = parse_warn_detail(
                    rec.get("detail"), fmt_ts(ts))
                notices.extend(pair_notices)
                failing = {eid for eid, verdict in pairs
                           if verdict in FAIL_VERDICTS}
                evaluations.append({"ts": ts, "failing": failing})
                continue
            raise RecordError(
                "%s line %d: unknown staleness_check decision %r"
                % (run_log, lineno, decision))
    if unparseable:
        shown = ", ".join(str(n) for n in unparseable[:5])
        more = "" if len(unparseable) <= 5 else " (first 5 shown)"
        notices.append(
            "run-log has %d unparseable (torn) line(s) at line(s) %s%s; "
            "they carry no timestamp or hook name and were skipped. If any "
            "was a staleness_check record it is invisible to this check."
            % (len(unparseable), shown, more))
    evaluations.sort(key=lambda e: e["ts"])
    error_runs.sort(key=lambda e: e["ts"])
    return evaluations, error_runs, notices


def load_ledger(ledger_path):
    """Return (incident_dicts, verbatim_lines). An incident line starts at
    column 0 with "INCIDENT" and has exactly 5 pipe-separated fields:
    INCIDENT | YYYY-MM-DD HH:MM | <board-entry-id> | <claim> | <why>.
    A malformed INCIDENT-prefixed line is a RecordError, never skipped."""
    if not ledger_path.exists():
        raise RecordError("incident ledger not found: %s" % ledger_path)
    incidents = []
    verbatim = []
    for lineno, line in enumerate(
            ledger_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.startswith("INCIDENT"):
            continue
        fields = [f.strip() for f in line.split("|")]
        if len(fields) != 5 or fields[0] != "INCIDENT":
            raise RecordError(
                "%s line %d: malformed INCIDENT line (need exactly 5 "
                "pipe-separated fields starting INCIDENT): %r"
                % (ledger_path, lineno, line))
        ts = parse_ts(fields[1], "incident date (ledger line %d)" % lineno)
        if not all(fields[2:]):
            raise RecordError(
                "%s line %d: empty field in INCIDENT line: %r"
                % (ledger_path, lineno, line))
        incidents.append({"ts": ts, "entry_id": fields[2],
                          "claim": fields[3], "why": fields[4]})
        verbatim.append(line)
    return incidents, verbatim


def build_episodes(evaluations, incidents, now):
    """Episode model (plan DD-6): an episode for id X opens at its first
    in-window failing evaluation and closes at the first later in-window
    evaluation where X is not failing. Statuses:
      cleared              closed, clear within 48h of start
      incident_classified  an INCIDENT line names the id, dated within
                           [start, start + 48h]  (satisfies branch (c))
      cleared_late         closed, clear later than 48h  (violates (c))
      unresolved_over_48h  open, now >= start + 48h      (violates (c))
      pending              open, now < start + 48h       (INCONCLUSIVE)
    """
    open_eps = {}
    episodes = []
    for ev in evaluations:
        for eid in sorted(open_eps):
            if eid not in ev["failing"]:
                episodes.append({"id": eid, "start": open_eps.pop(eid),
                                 "clear": ev["ts"]})
        for eid in sorted(ev["failing"]):
            if eid not in open_eps:
                open_eps[eid] = ev["ts"]
    for eid, start in sorted(open_eps.items()):
        episodes.append({"id": eid, "start": start, "clear": None})

    def incident_within(eid, start):
        return any(inc["entry_id"] == eid
                   and start <= inc["ts"] <= start + RESOLUTION_WINDOW
                   for inc in incidents)

    rows = []
    for ep in sorted(episodes, key=lambda e: (e["start"], e["id"])):
        start, clear = ep["start"], ep["clear"]
        deadline = start + RESOLUTION_WINDOW
        if clear is not None and clear <= deadline:
            status = "cleared"
        elif incident_within(ep["id"], start):
            status = "incident_classified"
        elif clear is not None:
            status = "cleared_late"
        elif now >= deadline:
            status = "unresolved_over_48h"
        else:
            status = "pending"
        rows.append({
            "id": ep["id"],
            "start": fmt_ts(start),
            "clear": fmt_ts(clear) if clear is not None else None,
            "deadline": fmt_ts(deadline),
            "status": status,
        })
    return rows


def run_window_check(window_start, window_end, run_log, ledger_path, now,
                     min_evaluations):
    evaluations, error_runs, notices = load_run_records(
        run_log, window_start, window_end)
    incidents, incident_lines = load_ledger(ledger_path)
    episodes = build_episodes(evaluations, incidents, now)

    failed = []
    if len(evaluations) < min_evaluations:
        failed.append(BRANCH_VACUITY)
    if incident_lines:
        failed.append(BRANCH_LEDGER)
    violations = [e for e in episodes
                  if e["status"] in ("cleared_late", "unresolved_over_48h")]
    if violations:
        failed.append(BRANCH_UNRESOLVED)

    pending = [e for e in episodes if e["status"] == "pending"]
    rerun_after = None
    if failed:
        verdict, exit_code = "FAIL", 2
    elif pending:
        verdict, exit_code = "INCONCLUSIVE_PENDING", 3
        rerun_after = max(e["deadline"] for e in pending)
    else:
        verdict, exit_code = "PASS", 0

    branches = {
        BRANCH_VACUITY: "FAIL" if BRANCH_VACUITY in failed else "PASS",
        BRANCH_LEDGER: "FAIL" if BRANCH_LEDGER in failed else "PASS",
        BRANCH_UNRESOLVED: "FAIL" if BRANCH_UNRESOLVED in failed else "PASS",
    }
    return {
        "window_start": fmt_ts(window_start),
        "window_end": fmt_ts(window_end),
        "now": fmt_ts(now),
        "run_log": str(run_log),
        "ledger": str(ledger_path),
        "min_evaluations": min_evaluations,
        "evaluation_count": len(evaluations),
        "error_run_count": len(error_runs),
        "error_runs": error_runs,
        "incident_count": len(incident_lines),
        "incident_lines": incident_lines,
        "episodes": episodes,
        "branches": branches,
        "failed_branches": failed,
        "notices": notices,
        "rerun_after": rerun_after,
        "verdict": verdict,
        "exit_code": exit_code,
    }


def render_report(rep):
    lines = ["O12 observation-window check"]
    lines.append("window: %s -> %s   now: %s"
                 % (rep["window_start"], rep["window_end"], rep["now"]))
    lines.append("run-log: %s" % rep["run_log"])
    lines.append("ledger:  %s" % rep["ledger"])
    lines.append("evaluations in window: %d (floor %d)   error runs: %d"
                 % (rep["evaluation_count"], rep["min_evaluations"],
                    rep["error_run_count"]))
    lines.append("incident lines: %d" % rep["incident_count"])
    for ln in rep["incident_lines"]:
        lines.append("  %s" % ln)
    if rep["episodes"]:
        lines.append("episodes:")
        for e in rep["episodes"]:
            lines.append("  %-28s start %s  clear %s  [%s]"
                         % (e["id"], e["start"], e["clear"] or "-",
                            e["status"]))
    else:
        lines.append("episodes: none")
    lines.append("branches: " + "  ".join(
        "%s=%s" % (k, v) for k, v in sorted(rep["branches"].items())))
    if rep["notices"]:
        lines.append("notices:")
        for n in rep["notices"]:
            lines.append("  %s" % n)
    if rep["rerun_after"]:
        lines.append("pending episode(s): re-run on or after %s"
                     % rep["rerun_after"])
    lines.append("VERDICT: %s" % rep["verdict"])
    return "\n".join(lines)


def build_parser():
    p = argparse.ArgumentParser(
        description="O12 observation-window checker (read-only; verdict "
                    "PASS=0, FAIL=2, INCONCLUSIVE_PENDING=3, record error=1).")
    p.add_argument("--window-start", required=True,
                   help="Window start, naive local, inclusive "
                        "(YYYY-MM-DD HH:MM:SS; T separator accepted).")
    p.add_argument("--window-end", required=True,
                   help="Window end, naive local, exclusive.")
    p.add_argument("--run-log", default=str(DEFAULT_RUN_LOG),
                   help="hook-activity.jsonl path (default: live sink).")
    p.add_argument("--ledger", default=str(DEFAULT_LEDGER),
                   help="Incident ledger markdown path.")
    p.add_argument("--now", default=None,
                   help="Evaluation time (default: current local time). "
                        "Fixture runs pass it explicitly for determinism.")
    p.add_argument("--min-evaluations", type=int, default=10,
                   help="Vacuity floor (ratified default 10).")
    p.add_argument("--json", action="store_true",
                   help="Emit the deterministic JSON report.")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        window_start = parse_ts(args.window_start, "--window-start")
        window_end = parse_ts(args.window_end, "--window-end")
        if window_end <= window_start:
            raise RecordError("--window-end must be after --window-start")
        now = (parse_ts(args.now, "--now") if args.now is not None
               else datetime.now())
        rep = run_window_check(window_start, window_end,
                               Path(args.run_log), Path(args.ledger),
                               now, args.min_evaluations)
    except RecordError as exc:
        print("RECORD ERROR: %s" % exc, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
    else:
        print(render_report(rep))
    return rep["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
