"""DEL-004: generate the classifier-to-agent process-path map from source.

Traces every branch the task-classifier's routing table names through to the
skill, workflow and agent dispatches that branch can reach, then cross-checks
every named component against the asset inventory (DEL-003).

Generated, not hand-typed, per the FLAG-004 ruling in the audit charter. A
hand-written map of this is a snapshot that starts rotting the moment a
DISPATCHES.json changes, and the whole point of the audit is to find components
nothing can reach: a stale map would hide exactly the class of defect being
looked for.

Sources, all read from disk, none from recollection:
  CLAUDE.md                                 the "Skill routing" branch line
  .claude/skills/task-classifier/SKILL.md   the domain-specialist table
  .claude/skills/<skill>/DISPATCHES.json    mandatory + conditional dispatches
  .claude/skills/<skill>/SKILL.md           the workflow scriptPath, if routed
  .claude/workflows/<name>.js               agentType / label strings
  .claude/hooks/aggregates/asset-inventory.json   the DEL-003 cross-reference

Usage:
    python .claude/scripts/process_path_map.py [--vault PATH] [--out-dir PATH]

Writes a JSON data file and a markdown view rendered from that JSON.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

DEFAULT_VAULT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = os.path.join("Projects", "Agent-Governance-Research", "work")

INVENTORY_REL = os.path.join(".claude", "hooks", "aggregates", "asset-inventory.json")
CLASSIFIER_REL = os.path.join(".claude", "skills", "task-classifier", "SKILL.md")


def read(path):
    with io.open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


# --------------------------------------------------------------- branch table

def parse_routing_line(claude_md):
    """Parse CLAUDE.md's one-line 'Skill routing:' branch table.

    Shape: `Research -> \\`process-research\\` | Analysis -> \\`process-analysis\\` | ...`
    The arrow is a literal Unicode arrow in the source, matched by codepoint so
    a prose scrub cannot silently break this parser (see the dash-scrub finding).
    """
    arrow = chr(0x2192)
    for line in claude_md.splitlines():
        if line.strip().startswith("Skill routing:"):
            body = line.split(":", 1)[1]
            branches = []
            for seg in body.split("|"):
                if arrow not in seg:
                    continue
                left, right = seg.split(arrow, 1)
                target = re.search(r"`([^`]+)`", right)
                branches.append({
                    "branch": left.strip(),
                    "target": target.group(1).strip() if target else right.strip(),
                    "target_kind": "skill" if target else "inline",
                    "note": right.strip(),
                    "source": "CLAUDE.md Skill routing line",
                })
            return branches
    return []


def parse_domain_table(classifier_md):
    """Parse the classifier's Step 1.5 domain-to-specialist table."""
    rows = []
    in_table = False
    for line in classifier_md.splitlines():
        if line.startswith("| Domain "):
            in_table = True
            continue
        if in_table:
            if not line.startswith("|"):
                if rows:
                    break
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or set(cells[0]) <= set("- "):
                continue
            # Strip parenthesised text BEFORE splitting. One row's specialist
            # cell is prose naming a plugin with example skills listed inside
            # parentheses; splitting on commas first turned that single cell
            # into six invented "missing agents". Parenthesised content is
            # always a role hint or an example list, never a separate target.
            cell = re.sub(r"\([^)]*\)", "", cells[1])
            tokens = [t.strip(" `*") for t in cell.split("/") if t.strip(" `*")]
            agents, prose = [], []
            for tok in tokens:
                # A dispatchable component is a bare identifier. Anything with
                # a space is a prose reference and is recorded as such rather
                # than looked up, because a failed lookup of prose is a parser
                # artifact, not a harness finding.
                (agents if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", tok) else prose).append(tok)
            rows.append({
                "domain": cells[0],
                "agents": agents,
                "prose_references": prose,
                "trigger": cells[2] if len(cells) > 2 else "",
                "source": ".claude/skills/task-classifier/SKILL.md Step 1.5",
            })
    return rows


def parse_mandatory_compounds(classifier_md):
    """Rows of the classifier's always-yes compound table that name a skill.

    These are not branch targets, they are obligations attached to every
    non-Quick branch, which is precisely why they belong on the map: they are
    the most-dispatched components in the harness and the routing line does not
    mention either of them.
    """
    out = []
    for line in classifier_md.splitlines():
        if not line.startswith("|") or "non-Quick" not in line:
            continue
        cells = [c.strip().strip("*` ") for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        name = cells[2]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            out.append((name, f"mandatory {cells[1].strip('*` ')} compound"))
    return out


# ------------------------------------------------------------------ dispatches

def parse_dispatches(vault, skill):
    path = os.path.join(vault, ".claude", "skills", skill, "DISPATCHES.json")
    if not os.path.isfile(path):
        return None
    try:
        data = json.loads(read(path))
    except Exception as exc:
        return {"error": f"unparseable: {exc}"}
    out = {"mandatory": [], "conditional": [], "allowed": []}
    for key, bucket in (("mandatory_dispatches", "mandatory"),
                        ("conditional_dispatches", "conditional"),
                        ("allowed_specialists", "allowed")):
        for entry in data.get(key, []) or []:
            if isinstance(entry, dict):
                out[bucket].append({
                    "name": entry.get("name"),
                    "role": entry.get("role"),
                    "condition": entry.get("condition"),
                })
            else:
                out[bucket].append({"name": str(entry), "role": None, "condition": None})
    return out


def parse_workflow_route(vault, skill):
    """Find the workflow scriptPath a SKILL.md routes non-Quick execution to."""
    path = os.path.join(vault, ".claude", "skills", skill, "SKILL.md")
    if not os.path.isfile(path):
        return None
    m = re.search(r'scriptPath:\s*"([^"]+)"', read(path))
    if not m:
        return None
    raw = m.group(1).replace("\\\\", "\\")
    return os.path.basename(raw)


def parse_workflow_agents(vault, script_name):
    """Extract agentType values and phase/label hints from a workflow script."""
    if not script_name:
        return None
    path = os.path.join(vault, ".claude", "workflows", script_name)
    if not os.path.isfile(path):
        return {"error": f"scriptPath names {script_name}, which is not on disk"}
    src = read(path)
    return {
        "file": script_name,
        "agent_types": sorted(set(re.findall(r"agentType:\s*['\"]([^'\"]+)['\"]", src))),
        "phases": sorted(set(re.findall(r"phase\(\s*['\"]([^'\"]+)['\"]", src))),
    }


# ------------------------------------------------------------- cross-reference

def load_inventory(vault):
    path = os.path.join(vault, INVENTORY_REL)
    if not os.path.isfile(path):
        return {}, None
    data = json.loads(read(path))
    rows = data.get("rows", data if isinstance(data, list) else [])
    index = {}
    for row in rows:
        index.setdefault(row.get("name"), []).append(row)
    return index, data.get("generated_at")


def crossref(name, index):
    hits = index.get(name)
    if not hits:
        return {"in_index": False, "kind": None, "blocked_reason": None,
                "usage_count": None, "note": "named by a dispatch contract, absent from the index"}
    row = hits[0]
    usage = row.get("usage") or {}
    return {
        "in_index": True,
        "kind": row.get("kind"),
        "path": row.get("path"),
        "blocked_reason": row.get("blocked_reason") or [],
        "usage_count": usage.get("total_count"),
        "reachability_types": sorted({e.get("type") for e in (row.get("reachability") or []) if isinstance(e, dict)}),
    }


# ------------------------------------------------------------------- rendering

def render_markdown(doc):
    L = []
    a = L.append
    a("---")
    a(f"date: {doc['generated_from']['as_of_date']}")
    a("tags: [project/agent-governance-research, audit, agents]")
    a("status: active")
    a("---")
    a("")
    a("# Harness process-path map (DEL-004)")
    a("")
    a("Generated by `.claude/scripts/process_path_map.py`. Do not hand-edit: rerun the")
    a("script. Every row below is derived from a file on disk, named in Sources.")
    a("")
    a("## Sources")
    a("")
    for k, v in doc["generated_from"].items():
        a(f"- `{k}`: {v}")
    a("")
    a("## 1. Classifier branches")
    a("")
    a("| Branch | Routes to | Kind |")
    a("|---|---|---|")
    for b in doc["branches"]:
        a(f"| {b['branch']} | `{b['target']}` | {b['target_kind']} |")
    a("")
    a("## 2. Each routed skill, through to its dispatches")
    a("")
    for skill, info in doc["skills"].items():
        a(f"### `{skill}`")
        a("")
        wf = info.get("workflow")
        if wf and not wf.get("error"):
            a(f"Workflow: `{wf['file']}`, phases: {', '.join(wf['phases']) or 'none declared'}")
        elif wf and wf.get("error"):
            a(f"Workflow: **{wf['error']}**")
        else:
            a("Workflow: none (prose path only)")
        a("")
        if not info.get("dispatches"):
            a("No `DISPATCHES.json`, so nothing machine-readable pins this skill's contract.")
            a("")
            continue
        a("| Dispatch | Tier | Role or condition | In index | Kind | Uses | Blocked |")
        a("|---|---|---|---|---|---|---|")
        for tier in ("mandatory", "conditional", "allowed"):
            for d in info["dispatches"].get(tier, []):
                x = d["crossref"]
                blocked = ", ".join(x.get("blocked_reason") or []) or "-"
                a(f"| `{d['name']}` | {tier} | {d.get('role') or d.get('condition') or '-'} "
                  f"| {'yes' if x['in_index'] else '**NO**'} | {x.get('kind') or '-'} "
                  f"| {x.get('usage_count') if x.get('usage_count') is not None else '-'} | {blocked} |")
        a("")
    a("## 3. Domain specialists (classifier Step 1.5)")
    a("")
    a("| Domain | Specialist | Edge status | In index | Uses | Blocked |")
    a("|---|---|---|---|---|---|")
    for row in doc["domains"]:
        for agent in row["agents"]:
            x = row["crossref"][agent]
            blocked = ", ".join(x.get("blocked_reason") or []) or "-"
            a(f"| {row['domain']} | `{agent}` | resolved | {'yes' if x['in_index'] else '**NO**'} "
              f"| {x.get('usage_count') if x.get('usage_count') is not None else '-'} | {blocked} |")
        for prose in row.get("prose_references", []):
            a(f"| {row['domain']} | {prose} | **UNRESOLVED (prose)** | n/a | n/a | n/a |")
    a("")
    a("## 3b. Parse confidence")
    a("")
    p = doc["parse_confidence"]
    a(f"- Edges resolved to a named component: **{p['resolved']}**")
    a(f"- Edges left UNRESOLVED because the source names them in prose: **{p['unresolved']}**")
    a("")
    a("An unresolved edge is a first-class status here, not a silent drop. This")
    a("project killed a structurally similar artifact on 2026-08-02 on precisely")
    a("that ground: edges in this harness live in prose (markdown tables, a")
    a("sentence in CLAUDE.md) and are heuristically parsed rather than compiled,")
    a("so a generated map can read as more trustworthy than a hand-maintained one")
    a("while being wrong. That objection is not answered by claiming a better")
    a("parser. It is answered by the parser reporting what it could not resolve.")
    a("")
    a("Concrete evidence that the risk is live rather than theoretical: the first")
    a("run of this generator reported six missing specialists that do not exist as")
    a("findings at all. One table cell names a plugin and lists example skills")
    a("inside parentheses, and splitting it on commas manufactured six phantom")
    a("components. The parser now strips parenthesised text before splitting and")
    a("looks up only bare identifiers, and anything else is reported above as")
    a("unresolved rather than guessed at.")
    a("")
    a("## 4. Findings this map produces on its own")
    a("")
    for f in doc["findings"]:
        a(f"- **{f['code']}** {f['detail']}")
    if not doc["findings"]:
        a("- None: every component named by a routing table or dispatch contract "
          "resolves to an index entry.")
    a("")
    a("## Related")
    a("")
    a("- [[2026-08-19-harness-audit-charter]] the charter this deliverable belongs to")
    a("- [[2026-08-19-asset-inventory-build-plan]] the DEL-003 index cross-referenced here")
    a("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=DEFAULT_VAULT)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--as-of", default=None, help="date stamp for the rendered view")
    args = ap.parse_args(argv)

    vault = args.vault
    out_dir = args.out_dir or os.path.join(vault, DEFAULT_OUT)
    os.makedirs(out_dir, exist_ok=True)

    claude_md = read(os.path.join(vault, "CLAUDE.md"))
    classifier = read(os.path.join(vault, CLASSIFIER_REL))
    index, inv_stamp = load_inventory(vault)

    branches = parse_routing_line(claude_md)
    domains = parse_domain_table(classifier)

    # The routing line names only the primary branch targets. The classifier's
    # mandatory-compound table adds two more that sit on EVERY non-Quick path,
    # so a map built from the routing line alone would omit the skills most
    # often dispatched in the whole harness.
    for name, why in parse_mandatory_compounds(classifier):
        branches.append({
            "branch": "ALL non-Quick",
            "target": name,
            "target_kind": "skill",
            "note": why,
            "source": ".claude/skills/task-classifier/SKILL.md mandatory-compound table",
        })

    skills = {}
    for b in branches:
        if b["target_kind"] != "skill":
            continue
        name = b["target"]
        if name in skills:
            continue
        disp = parse_dispatches(vault, name)
        if disp and "error" not in disp:
            for tier in ("mandatory", "conditional", "allowed"):
                for d in disp[tier]:
                    d["crossref"] = crossref(d["name"], index)
        skills[name] = {
            "workflow": parse_workflow_agents(vault, parse_workflow_route(vault, name)),
            "dispatches": disp,
        }

    for row in domains:
        row["crossref"] = {a: crossref(a, index) for a in row["agents"]}

    findings = []
    for skill, info in skills.items():
        disp = info.get("dispatches")
        if disp is None:
            findings.append({"code": "PPM-001",
                             "detail": f"`{skill}` is a routing target with no `DISPATCHES.json`, "
                                       "so no machine-readable contract pins what it must dispatch."})
            continue
        if "error" in disp:
            findings.append({"code": "PPM-004", "detail": f"`{skill}` DISPATCHES.json {disp['error']}."})
            continue
        for tier in ("mandatory", "conditional", "allowed"):
            for d in disp[tier]:
                if not d["crossref"]["in_index"]:
                    findings.append({"code": "PPM-002",
                                     "detail": f"`{skill}` names `{d['name']}` as a {tier} dispatch, "
                                               "but no asset of that name exists in the index."})
        wf = info.get("workflow")
        if wf and wf.get("error"):
            findings.append({"code": "PPM-003", "detail": f"`{skill}`: {wf['error']}."})
    for row in domains:
        for agent, x in row["crossref"].items():
            if not x["in_index"]:
                findings.append({"code": "PPM-005",
                                 "detail": f"domain `{row['domain']}` names specialist `{agent}`, "
                                           "absent from the index."})

    resolved = sum(len(r["agents"]) for r in domains)
    unresolved = sum(len(r.get("prose_references", [])) for r in domains)
    for info in skills.values():
        disp = info.get("dispatches")
        if disp and "error" not in disp:
            resolved += sum(len(disp[t]) for t in ("mandatory", "conditional", "allowed"))

    doc = {
        "deliverable": "DEL-004",
        "parse_confidence": {"resolved": resolved, "unresolved": unresolved},
        "generated_by": ".claude/scripts/process_path_map.py",
        "generated_from": {
            "CLAUDE.md": "Skill routing line",
            CLASSIFIER_REL.replace("\\", "/"): "Step 1.5 domain table",
            ".claude/skills/*/DISPATCHES.json": "dispatch contracts",
            ".claude/workflows/*.js": "workflow agent types and phases",
            INVENTORY_REL.replace("\\", "/"): f"DEL-003 index, generated_at={inv_stamp}",
            "as_of_date": args.as_of or "unstamped",
        },
        "branches": branches,
        "skills": skills,
        "domains": domains,
        "findings": findings,
    }

    json_path = os.path.join(out_dir, "2026-08-19-harness-process-path-map.json")
    md_path = os.path.join(out_dir, "2026-08-19-harness-process-path-map.md")
    io.open(json_path, "w", encoding="utf-8", newline="\n").write(json.dumps(doc, indent=2) + "\n")
    io.open(md_path, "w", encoding="utf-8", newline="\n").write(render_markdown(doc))

    print(f"branches: {len(branches)}  routed skills: {len(skills)}  "
          f"domains: {len(domains)}  findings: {len(findings)}")
    for f in findings:
        print(f"  {f['code']} {f['detail']}")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
