#!/usr/bin/env python3
"""Creation audit (ROAD-12, 2026-09-08).

Derives the file-creation set for an arbitrary trailing window from git
history (git log --diff-filter=A --name-only --no-renames), classifies
each added path stray vs expected via the ROAD-3 root allowlist plus the
R2 scoped-directory contract (annotation layer), and writes a dated
report artifact. Closes the provenance gap on the evaluation's
8/3458/0.23-percent commissioning figure by making the number re-runnable.

Advisory measurement only: no hooks, no gates, nothing registered.
Standalone by design (D7): imports nothing from lint_pass_root_stray.py
(the allowlist JSON is read directly) and has no analog of --seed; this
script can never write the allowlist.

CLI contract (deliberately NOT the shared lint_pass_* contract):
  - exit 0: report written
  - exit 2: derivation failure (missing or unparseable allowlist,
    zero-row R2 parse, git failure, unwritable out path), printed as
    `DERIVATION FAILURE: <reason>` before exiting
  There is deliberately no exit-1 findings tier: this is an audit report
  writer, not a lint pass; a nonzero stray count is data inside the
  report, not a process failure.
"""
import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date as date_cls
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_ALLOWLIST = VAULT / ".claude" / "hooks" / "_state" / "root-allowlist.json"
DEFAULT_SPEC = (VAULT / "Projects" / "Vault-Maintenance" / "work"
                / "2026-05-11-target-structure-spec.md")

OUTSIDE_R2 = "allowlisted, outside R2 contract"
CAVEAT = ("git history cannot see files created and deleted between "
          "autosave sweeps, so counts are lower bounds, never exact.")

# Commissioning comparator (2026-09-08 vault architecture evaluation).
COMP_STRAY = 8
COMP_TOTAL = 3458
COMP_PCT = "0.23"

BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The live heading contains an em dash after "R2"; match only the stable part
# so this file stays dash-clean (constraint 6).
R2_HEADING = re.compile(r"^##\s+R2\b")
TRAILING_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


class DerivationFailure(Exception):
    """Unreadable or unparseable input, or a failed git derivation."""


def normalize_window(value):
    """Bare YYYY-MM-DD gets T00:00:00; git approxidate would otherwise fill
    the current clock time and break two-run determinism (D1)."""
    if BARE_DATE.match(value):
        return value + "T00:00:00"
    return value


def parse_git_log(text):
    """Parse `--pretty=format:@@%H%x09%cI --name-only` output into
    (path, sha, committer_date_iso) tuples, one per add event."""
    records = []
    sha = None
    cdate = None
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("@@"):
            sha, _, cdate = line[2:].partition("\t")
            continue
        if sha is None:
            continue
        records.append((line, sha, cdate))
    return records


def parse_r2_prefixes(spec_text):
    """Parse the R2 directory table's Directory column live from the spec
    (generator-derivation rule; the prefix list is never re-typed).

    Returns (row_count, sorted_unique_prefixes). Normalization per D3:
    trailing parentheticals dropped (`Projects/X/ (root)` to `Projects/X/`),
    then the first path segment is the top-level scope.
    """
    rows = []
    in_section = False
    in_table = False
    for line in spec_text.splitlines():
        if R2_HEADING.match(line):
            in_section = True
            continue
        if not in_section:
            continue
        if line.startswith("## "):
            break
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        in_table = True
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells or not cells[0]:
            continue
        first = cells[0]
        if first == "Directory" or set(first) <= set("-: "):
            continue
        rows.append(first)
    prefixes = set()
    for cell in rows:
        cell = TRAILING_PAREN.sub("", cell).strip().rstrip("/")
        seg = cell.split("/", 1)[0]
        if seg:
            prefixes.add(seg)
    return len(rows), sorted(prefixes)


def classify(path, allow_entries, r2_prefixes):
    """expected iff the first path segment is an allowlist member (D3);
    R2 annotates expected paths with a scope, it is never a second gate."""
    first = path.split("/", 1)[0]
    if first in allow_entries:
        scope = first if first in r2_prefixes else OUTSIDE_R2
        return "expected", scope
    return "stray", None


def summarize(records, allow_entries, r2_prefixes):
    """Counts on both bases (D4): add events and unique paths. First-seen
    commit per path is the chronologically earliest add event."""
    events = len(records)
    first_seen = {}
    stray_events = 0
    for path, sha, cdate in records:
        try:
            dt = datetime.fromisoformat(cdate)
        except (ValueError, TypeError):
            raise DerivationFailure(
                f"unparseable committer date {cdate!r} for {path!r}")
        prev = first_seen.get(path)
        if prev is None or dt < prev[2]:
            first_seen[path] = (sha, cdate, dt)
        if classify(path, allow_entries, r2_prefixes)[0] == "stray":
            stray_events += 1
    stray = {}
    expected_scopes = Counter()
    for path, (sha, cdate, _) in first_seen.items():
        kind, scope = classify(path, allow_entries, r2_prefixes)
        if kind == "stray":
            stray[path] = (sha, cdate)
        else:
            expected_scopes[scope] += 1
    return {
        "events": events,
        "unique": len(first_seen),
        "stray": dict(sorted(stray.items())),
        "stray_unique": len(stray),
        "stray_events": stray_events,
        "expected_unique": len(first_seen) - len(stray),
        "expected_scopes": dict(expected_scopes),
    }


def _pct(numerator, denominator):
    if denominator == 0:
        return "0.00"
    return f"{100.0 * numerator / denominator:.2f}"


def _verdict(total, stray):
    ok = (total == COMP_TOTAL and stray == COMP_STRAY)
    return "agreement" if ok else "divergence"


def build_report(*, since, until, cmdline, allowlist_path, generated_iso,
                 entry_count, spec_path, r2_rows, r2_prefixes, stats,
                 run_date):
    s = stats
    pct_u = _pct(s["stray_unique"], s["unique"])
    pct_e = _pct(s["stray_events"], s["events"])
    lines = [
        "---",
        f"date: {run_date}",
        "tags: [project/vault-maintenance, analysis, audit]",
        "status: active",
        "---",
        "",
        f"# Creation Audit: {since} to {until}",
        "",
        "Re-runnable creation audit (ROAD-12). Derives the set of files "
        "added to the vault repo in the window from git history and "
        "classifies each added path stray vs expected against the ROAD-3 "
        "root allowlist, with the R2 scoped-directory contract as an "
        "annotation layer.",
        "",
        "## Method",
        "",
        f"- Derivation command (verbatim): `{cmdline}`",
        f"- Window: commit dates from {since} (inclusive) to {until}, "
        "filtered by git's own --since/--until on commit date.",
        f"- Allowlist: `{allowlist_path}`, generated_iso {generated_iso}, "
        f"{entry_count} entries, consumed read-only.",
        f"- R2 contract: `{spec_path}`, {r2_rows} directory rows parsed, "
        f"{len(r2_prefixes)} unique top-level prefixes: "
        + ", ".join(r2_prefixes) + ".",
        "- Counting definitions: an add event is one added-path line in one "
        "commit (a path added, deleted, and re-added counts each time); "
        "unique paths collapse those duplicates. The headline totals and "
        "the two-run identity check are defined over unique paths.",
        "- Renames: --no-renames makes the add set independent of the "
        "machine's diff.renames config; a moved file counts as an add at "
        "its new path.",
        "- Merge commits: git log without -m lists no files for merges; the "
        "repo is main-only by doctrine, so this is a stated assumption, "
        "not a silent one.",
        "",
        "## Results",
        "",
        f"- Total added: {s['unique']} unique paths ({s['events']} add "
        "events)",
        f"- Expected: {s['expected_unique']} unique paths",
        f"- Stray: {s['stray_unique']} unique paths ({s['stray_events']} "
        "add events)",
        f"- Stray share: {pct_u} percent of unique paths, {pct_e} percent "
        "of add events",
        "",
        "### Stray paths (first-seen commit)",
        "",
    ]
    if s["stray"]:
        lines += ["| Path | First seen (commit) | Commit date |",
                  "|---|---|---|"]
        for path, (sha, cdate) in s["stray"].items():
            lines.append(f"| {path} | {sha[:12]} | {cdate} |")
    else:
        lines.append("None.")
    lines += ["", "### Stray aggregation by first segment", ""]
    seg_counts = Counter(p.split("/", 1)[0] for p in s["stray"])
    if seg_counts:
        lines += ["| First segment | Unique paths |", "|---|---|"]
        for seg, n in sorted(seg_counts.items()):
            lines.append(f"| {seg} | {n} |")
    else:
        lines.append("None.")
    lines += [
        "",
        "## R2 annotation summary",
        "",
        f"Expected unique paths per R2 scope; the bucket \"{OUTSIDE_R2}\" "
        "collects allowlisted entries the R2 table does not cover (tool "
        "caches and root-level files).",
        "",
    ]
    if s["expected_scopes"]:
        lines += ["| Scope | Unique paths |", "|---|---|"]
        for scope, n in sorted(s["expected_scopes"].items()):
            lines.append(f"| {scope} | {n} |")
    else:
        lines.append("None.")
    lines += [
        "",
        "## Comparison to the commissioning figure",
        "",
        f"The 2026-09-08 vault architecture evaluation reported "
        f"{COMP_STRAY} strays out of {COMP_TOTAL} added files "
        f"({COMP_PCT} percent) for a 60-day window, with no locatable "
        "source artifact and no recorded counting definitions. Measured "
        "values for this audit's window:",
        "",
        "| Basis | Total added | Stray | Stray share |",
        "|---|---|---|---|",
        f"| Evaluation (basis unrecorded) | {COMP_TOTAL} | {COMP_STRAY} | "
        f"{COMP_PCT} percent |",
        f"| This audit, unique paths | {s['unique']} | {s['stray_unique']} "
        f"| {pct_u} percent |",
        f"| This audit, add events | {s['events']} | {s['stray_events']} | "
        f"{pct_e} percent |",
        "",
        f"Unique-path basis: {_verdict(s['unique'], s['stray_unique'])} "
        "with the commissioned figure. Add-event basis: "
        f"{_verdict(s['events'], s['stray_events'])} with the commissioned "
        "figure. Open unknowns on the comparator side, listed and not "
        "resolved here: its counting basis, its exact window bounds, and "
        "its rename handling.",
        "",
        "## Population caveat",
        "",
        CAVEAT,
        "",
        f"The allowlist snapshots the root as of its generated_iso "
        f"({generated_iso}); entries legitimate earlier in the window but "
        "since removed would classify as stray. This audit reports against "
        "today's contract, not a historical one.",
        "",
        "## Re-run",
        "",
        "One command regenerates this report for any window (defaults: "
        "--root the vault root, --allowlist the live ROAD-3 allowlist, "
        "--spec the live target-structure spec):",
        "",
        "```",
        "PYTHONIOENCODING=utf-8 'C:/Program Files/Python314/python.exe' "
        f".claude/scripts/creation_audit.py --since {since} "
        f"--until {until} --out <path>",
        "```",
        "",
    ]
    return "\n".join(lines)


def run_git_log(root, since, until):
    cmd = ["git", "-C", str(root), "-c", "core.quotepath=off", "log",
           "--diff-filter=A", "--name-only", "--no-renames",
           "--pretty=format:@@%H%x09%cI",
           f"--since={since}", f"--until={until}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DerivationFailure(f"git log failed to run: {exc}")
    if r.returncode != 0:
        raise DerivationFailure(
            f"git log exited {r.returncode}: {r.stderr.strip()[:300]}")
    return r.stdout, " ".join(cmd)


def load_allowlist(path):
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DerivationFailure(f"allowlist unreadable at {path}: {exc}")
    entries = payload.get("entries")
    if (not isinstance(entries, list)
            or not all(isinstance(e, str) for e in entries)):
        raise DerivationFailure(
            f"allowlist at {path} has no string-list 'entries' field")
    return set(entries), payload.get("generated_iso", "unrecorded")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", required=True,
                    help="window start (YYYY-MM-DD or full timestamp)")
    ap.add_argument("--until", required=True,
                    help="window end (YYYY-MM-DD or full timestamp)")
    ap.add_argument("--root", default=str(VAULT))
    ap.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST))
    ap.add_argument("--spec", default=str(DEFAULT_SPEC))
    ap.add_argument("--out", required=True,
                    help="report path (the only file this script writes)")
    args = ap.parse_args(argv)

    try:
        since = normalize_window(args.since)
        until = normalize_window(args.until)
        print(f"resolved window: {since} .. {until}")

        allow_entries, generated_iso = load_allowlist(args.allowlist)
        print(f"allowlist entries={len(allow_entries)} "
              f"generated_iso={generated_iso}")

        try:
            spec_text = Path(args.spec).read_text(encoding="utf-8")
        except OSError as exc:
            raise DerivationFailure(f"spec unreadable at {args.spec}: {exc}")
        r2_rows, r2_prefixes = parse_r2_prefixes(spec_text)
        if r2_rows == 0:
            raise DerivationFailure(
                f"zero R2 directory rows parsed from spec at {args.spec}")
        print(f"r2 rows={r2_rows} prefixes={len(r2_prefixes)}")

        stdout, cmdline = run_git_log(args.root, since, until)
        records = parse_git_log(stdout)
        stats = summarize(records, allow_entries, r2_prefixes)
        print(f"added unique={stats['unique']} events={stats['events']}")
        print(f"stray unique={stats['stray_unique']} "
              f"events={stats['stray_events']} "
              f"expected unique={stats['expected_unique']}")

        report = build_report(
            since=since, until=until, cmdline=cmdline,
            allowlist_path=args.allowlist, generated_iso=generated_iso,
            entry_count=len(allow_entries), spec_path=args.spec,
            r2_rows=r2_rows, r2_prefixes=r2_prefixes, stats=stats,
            run_date=date_cls.today().isoformat())
        try:
            Path(args.out).write_text(report, encoding="utf-8")
        except OSError as exc:
            raise DerivationFailure(f"out path unwritable at {args.out}: {exc}")
        print(f"report written: {args.out}")
        return 0
    except DerivationFailure as exc:
        print(f"DERIVATION FAILURE: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
