#!/usr/bin/env python3
"""M-B work-layer lifecycle triage sweep — PROPOSAL-ONLY.

Mechanism M-B of the 2026-06-23 FILE-ORG increment-1 spec
(Projects/Agent-Governance-Research/work/2026-06-23-fileorg-increment1-spec.md,
sections 3.1-3.2).

Hard invariants:
  - PROPOSAL-ONLY: this script edits NO frontmatter, moves NO file, deletes
    NOTHING. Its only writes are the two proposal artifacts and the cadence
    state file. Wiktor rules on every proposed row; archive-moves follow his
    confirmation. Delete never appears as an action.
  - Same operative corpus as M-A: flat non-recursive Projects/<pilot>/work/*.md
    (glob excludes backups/, archive/, inventory/, __pycache__/ and non-md),
    minus INDEX.md, minus files tagged `wiki`.
  - Full (status, lifecycle, lifecycle_updated) state is evaluated; the sweep
    NEVER flags on `status` alone.
  - Age basis: `lifecycle_updated`, falling back to `date:` (creation date,
    over-ages recently re-affirmed files — caveat carried into the proposal).
    NEVER mtime (OneDrive-unreliable).

Arms (spec section 3.2, state-mapping section 3.1):
  - date arm: lifecycle in {active, reference} AND effective age > 30 days AND
    the file is not another live file's `superseded_by` target (being pointed
    at marks it as the live replacement — protected). `reference` files are
    proposed ONLY when they themselves carry a `superseded_by` pointer.
  - supersession arm (no date condition): a file CARRYING a `superseded_by`
    pointer has been superseded by the pointer's target -> propose `retired`.
    NOTE: the spec's literal sentence says the POINTED-AT file is retired;
    that inverts the schema comment (value names the replacement) and would
    retire the live replacement while the date arm protects it. This script
    implements the coherent semantics (carrier retired, target protected);
    the inversion is flagged in the build record for Wiktor's ruling.
  - explicit arm: lifecycle already `archive` or `retired` but the file still
    sits in the flat layer -> propose the work/archive/ move (state-mapping
    rows 3-4; no lifecycle transition, move only).

stdlib-only (+ optional PyYAML, regex fallback shared with M-A).
encoding='utf-8' on every open().
"""
import glob
import json
import os
import re
import sys
from datetime import date, datetime, timezone

try:
    import yaml
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
PILOTS = [
    ("Projects/Vault-Maintenance", "project/vault-maintenance"),
    ("Projects/Agent-Governance-Research", "project/agent-governance-research"),
]
THRESHOLD_DAYS = 30  # spec section 3.2 recommendation; untested-surface item 4
STATE_FILE = os.path.join(VAULT, ".claude", "hooks", "_state", "work-triage-cadence.json")


def parse_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    if HAVE_YAML:
        try:
            data = yaml.safe_load(block)
            return data if isinstance(data, dict) else {}
        except yaml.YAMLError:
            return _regex_frontmatter(block)
    return _regex_frontmatter(block)


def _regex_frontmatter(block):
    """Documented regex fallback; limits per spec section 2."""
    return dict(re.findall(r"^(\w[\w_-]*):\s*(.+)$", block, re.MULTILINE))


def tags_of(fm):
    raw = fm.get("tags")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw]
    s = str(raw).strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [t.strip().strip("'\"") for t in s.split(",") if t.strip()]


def scalar(fm, key, default=""):
    v = fm.get(key)
    if v is None:
        return default
    return str(v).strip()


def parse_date(s):
    """ISO date string -> date, else None. Never mtime."""
    if not s:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(s))
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def superseded_target(fm):
    """Basename (no .md) named by this file's superseded_by field, or ''."""
    raw = scalar(fm, "superseded_by")
    if not raw:
        return ""
    t = raw.strip().strip("'\"")
    t = re.sub(r"^\[\[|\]\]$", "", t.strip())
    t = t.split("|")[0].split("#")[0].strip()  # alias / heading suffixes
    if t.lower().endswith(".md"):
        t = t[:-3]
    return os.path.basename(t)


def collect(work_dir):
    entries = []
    for path in sorted(glob.glob(os.path.join(work_dir, "*.md"))):
        fname = os.path.basename(path)
        if fname == "INDEX.md":
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as e:
            print(f"WARN: cannot read {path}: {e}", file=sys.stderr)
            continue
        fm = parse_frontmatter(text)
        if "wiki" in tags_of(fm):
            continue
        entries.append({
            "file": fname,
            "stem": fname[:-3] if fname.lower().endswith(".md") else fname,
            "status": scalar(fm, "status") or "(none)",
            "lifecycle": scalar(fm, "lifecycle") or "active",  # default per spec 3.1
            "lifecycle_explicit": bool(scalar(fm, "lifecycle")),
            "lifecycle_updated": scalar(fm, "lifecycle_updated"),
            "date": scalar(fm, "date"),
            "superseded_by": superseded_target(fm),
        })
    return entries


def triage(entries, today):
    """Return (candidates, anomalies). Proposal computation only — no writes here."""
    stems = {e["stem"] for e in entries}
    # files pointed at by another live file's superseded_by = live replacements, protected
    protected = {e["superseded_by"] for e in entries if e["superseded_by"] in stems}
    candidates = []
    anomalies = []
    for e in entries:
        lc = e["lifecycle"]
        # supersession arm — carrier of a superseded_by pointer (no date condition)
        if e["superseded_by"]:
            candidates.append(dict(e, proposal="retired",
                                   action=f"move to work/archive/ (superseded by [[{e['superseded_by']}]])",
                                   arm="supersession"))
            continue
        # explicit arm — already archive/retired but still in the flat layer
        if lc in ("archive", "retired"):
            candidates.append(dict(e, proposal=lc,
                                   action="move to work/archive/ (lifecycle already " + lc + ")",
                                   arm="explicit"))
            continue
        # date arm
        if lc not in ("active", "reference"):
            anomalies.append(f"{e['file']}: non-enum lifecycle value '{lc}' — skipped, needs manual ruling")
            continue
        if lc == "reference":
            continue  # reference proposed only via a superseded_by pointer (handled above)
        if e["stem"] in protected:
            continue  # live replacement target — protected from date-based demotion
        basis = e["lifecycle_updated"] or e["date"]
        basis_src = "lifecycle_updated" if e["lifecycle_updated"] else "date (fallback, may over-age)"
        d = parse_date(basis)
        if d is None:
            anomalies.append(f"{e['file']}: no parseable lifecycle_updated or date — cannot age, skipped")
            continue
        age = (today - d).days
        if age > THRESHOLD_DAYS:
            candidates.append(dict(e, proposal="archive",
                                   action="move to work/archive/",
                                   arm=f"date ({age}d via {basis_src})"))
    return candidates, anomalies


def render_proposal(project, project_tag, entries, candidates, anomalies, today, run_iso):
    lines = [
        "---",
        f"date: {today.isoformat()}",
        f"tags: [{project_tag}, analysis, vault]",
        "status: waiting",
        "lifecycle: active",
        f"lifecycle_updated: {today.isoformat()}",
        "---",
        "",
        f"# Work-Layer Triage Proposal — {os.path.basename(project)} — {today.isoformat()}",
        "",
        f"PROPOSAL-ONLY output of `.claude/scripts/work_triage_sweep.py` (run {run_iso}). "
        "No frontmatter was edited, no file was moved. Every row awaits Wiktor's ruling; "
        "confirmed rows are moved to `work/archive/` (archive-move only — delete is never "
        "an action). Corpus: flat `work/*.md` minus INDEX.md and wiki-tagged files "
        f"({len(entries)} files evaluated). Threshold: {THRESHOLD_DAYS} days "
        "(untested-surface item 4 — tune after first runs).",
        "",
        f"**{len(candidates)} candidate(s).** Age basis is `lifecycle_updated` with `date:` "
        "creation-date fallback (over-ages files whose lifecycle was recently re-affirmed "
        "but never stamped — this first run predates the convention, so ALL files age via "
        "the fallback). Never mtime.",
        "",
    ]
    if candidates:
        lines += [
            "| file | status | lifecycle | lifecycle_updated | proposed lifecycle | implied action | arm |",
            "|---|---|---|---|---|---|---|",
        ]
        for c in candidates:
            lu = c["lifecycle_updated"] or f"(absent; date: {c['date'] or '(none)'})"
            lines.append(
                f"| {c['file']} | {c['status']} | {c['lifecycle']} | {lu} "
                f"| {c['proposal']} | {c['action']} | {c['arm']} |"
            )
    else:
        lines.append("No candidates this run.")
    if anomalies:
        lines += ["", "## Anomalies (not candidates — need manual attention)", ""]
        lines += [f"- {a}" for a in anomalies]
    lines += [
        "",
        "## Ruling protocol",
        "",
        "Per row: confirm (move file to `work/archive/`, stamp `lifecycle` + "
        "`lifecycle_updated` per ruling) / demote-to-reference (stamp `lifecycle: reference` "
        "+ `lifecycle_updated: <today>`) / keep-active (stamp `lifecycle_updated: <today>` "
        "to re-affirm). All stamps are the confirmer's edits, never this script's.",
        "",
    ]
    return "\n".join(lines)


def main():
    today = date.today()
    run_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    report_path = ""
    for project, project_tag in PILOTS:
        work_dir = os.path.join(VAULT, *project.split("/"), "work")
        if not os.path.isdir(work_dir):
            print(f"WARN: missing work dir, skipping: {work_dir}", file=sys.stderr)
            continue
        entries = collect(work_dir)
        candidates, anomalies = triage(entries, today)
        out_rel = f"{project}/work/{today.isoformat()}-triage-proposal.md"
        out_path = os.path.join(VAULT, *out_rel.split("/"))
        content = render_proposal(project, project_tag, entries, candidates,
                                  anomalies, today, run_iso)
        try:
            with open(out_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(content)
        except OSError as e:
            print(f"ERROR: cannot write {out_path}: {e}", file=sys.stderr)
            return 1
        print(f"{out_rel}: {len(entries)} evaluated, {len(candidates)} candidate(s), "
              f"{len(anomalies)} anomaly(ies)")
        report_path = out_rel  # last pilot = AGR per PILOTS order (plan step 10)
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "last_iso": run_iso,
                "report_path": report_path,
                "bootstrapped_by": "increment-1-build",
                "note": "work-layer triage cadence",
            }, f, indent=2)
    except OSError as e:
        print(f"ERROR: cannot stamp state file {STATE_FILE}: {e}", file=sys.stderr)
        return 1
    print(f"stamped {os.path.relpath(STATE_FILE, VAULT)} last_iso={run_iso}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
