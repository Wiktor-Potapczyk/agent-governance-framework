#!/usr/bin/env python3
"""Phase 2 MOC freshness: extract Dataview queries from each MOC, resolve current
counts, compare against baseline in .maintain-cache.json, flag drift.

We approximate Dataview query semantics:
  - FROM "#tag"          → notes with that tag (frontmatter)
  - FROM "folder/path"   → notes under that folder
  - WHERE contains(...)  → string match approximation (best-effort)
  - SORT/LIMIT           → ignored (only counts matter)
This is sufficient for freshness drift; not a Dataview engine clone.
"""
import os
import re
import sys
import json
import datetime
from pathlib import Path
from collections import defaultdict

VAULT = Path(__file__).resolve().parents[2]
CACHE = VAULT / ".maintain-cache.json"
SCAN_DIRS = ["Inbox", "Notes", "Projects", "Resources", "Areas", "Archives", "Daily Notes", "Templates", "Clippings"]

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
TAGS_LIST = re.compile(r"^tags:\s*\[([^\]]*)\]", re.MULTILINE)
TAGS_BLOCK = re.compile(r"^tags:\s*\n((?:\s*-\s*[^\n]+\n)+)", re.MULTILINE)
TAGS_NONSTD = re.compile(r"^tags:[ \t]+(#[^\n\[]+)$", re.MULTILINE)
DATE_RE = re.compile(r"^date:\s*(\S+)", re.MULTILINE)
TYPE_RE = re.compile(r"^type:\s*(.+)$", re.MULTILINE)
STATUS_RE = re.compile(r"^status:\s*(.+)$", re.MULTILINE)
DV_BLOCK = re.compile(r"```(dataview|dataviewjs)\s*\n(.*?)\n```", re.DOTALL)


def file_tags(text: str):
    fm_m = FM_RE.match(text)
    if not fm_m:
        return set(), {}
    fm = fm_m.group(1)
    tags = set()
    m = TAGS_LIST.search(fm)
    if m:
        for t in m.group(1).split(","):
            t = t.strip().strip("'\"").lstrip("#").lower()
            if t:
                tags.add(t)
    m = TAGS_BLOCK.search(fm)
    if m:
        for line in m.group(1).split("\n"):
            t = line.strip().lstrip("-").strip().strip("'\"").lstrip("#").lower()
            if t:
                tags.add(t)
    m = TAGS_NONSTD.search(fm)
    if m and not tags:
        for t in re.split(r"[,\s]+", m.group(1)):
            t = t.strip().lstrip("#").lower()
            if t:
                tags.add(t)
    fields = {}
    for rgx, key in [(DATE_RE, "date"), (TYPE_RE, "type"), (STATUS_RE, "status")]:
        mm = rgx.search(fm)
        if mm:
            fields[key] = mm.group(1).strip()
    return tags, fields


def build_index():
    """Index every md file: path → (tags, frontmatter fields)."""
    idx = {}
    for d in SCAN_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            tags, fields = file_tags(text)
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            idx[rel] = {"tags": tags, "fields": fields}
    return idx


def parse_dv_query(q: str):
    """Extract: FROM clause tags/folders, WHERE contains predicates, FROM negations."""
    out = {"from_tags": [], "from_folders": [], "from_neg_tags": [], "from_neg_folders": [],
           "where_status_eq": [], "where_status_neq": [], "where_type_eq": [],
           "raw": q.strip()}
    # FROM line(s)
    from_m = re.search(r"\bFROM\b(.+?)(?:\bWHERE\b|\bSORT\b|\bLIMIT\b|\bGROUP\b|\bFLATTEN\b|$)",
                       q, re.IGNORECASE | re.DOTALL)
    if from_m:
        from_clause = from_m.group(1).strip()
        # Split on AND/OR while preserving negation
        # Token: either "#tag" or "folder/path" with optional - prefix
        tokens = re.findall(r"(-)?\s*(#[A-Za-z][A-Za-z0-9/_-]*|\"[^\"]+\")", from_clause)
        for neg, tok in tokens:
            if tok.startswith("#"):
                tag = tok[1:].lower().rstrip("/")
                (out["from_neg_tags"] if neg else out["from_tags"]).append(tag)
            elif tok.startswith('"'):
                folder = tok.strip('"').strip("/").lower()
                (out["from_neg_folders"] if neg else out["from_folders"]).append(folder)
    # WHERE status = "active" / status != "archived" / type = "..."
    for m in re.finditer(r"status\s*=\s*\"([^\"]+)\"", q, re.IGNORECASE):
        out["where_status_eq"].append(m.group(1).lower())
    for m in re.finditer(r"status\s*!=\s*\"([^\"]+)\"", q, re.IGNORECASE):
        out["where_status_neq"].append(m.group(1).lower())
    for m in re.finditer(r"type\s*=\s*\"([^\"]+)\"", q, re.IGNORECASE):
        out["where_type_eq"].append(m.group(1).lower())
    return out


def resolve(query, idx):
    """Return set of paths matching the parsed query."""
    p = parse_dv_query(query)
    matches = []
    for path, meta in idx.items():
        tags = meta["tags"]
        fields = meta["fields"]
        # FROM filter
        if p["from_tags"]:
            if not any(t in tags for t in p["from_tags"]):
                continue
        if p["from_neg_tags"]:
            if any(t in tags for t in p["from_neg_tags"]):
                continue
        if p["from_folders"]:
            if not any(path.lower().startswith(f + "/") or path.lower() == f
                       for f in p["from_folders"]):
                continue
        if p["from_neg_folders"]:
            if any(path.lower().startswith(f + "/") for f in p["from_neg_folders"]):
                continue
        # WHERE status / type
        if p["where_status_eq"]:
            if fields.get("status", "").lstrip("#").lower() not in p["where_status_eq"]:
                continue
        if p["where_status_neq"]:
            if fields.get("status", "").lstrip("#").lower() in p["where_status_neq"]:
                continue
        if p["where_type_eq"]:
            if fields.get("type", "").lstrip("#").lower() not in p["where_type_eq"]:
                continue
        matches.append(path)
    return matches


def main():
    idx = build_index()
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    today = datetime.date.today().isoformat()
    moc_dir = VAULT / "Resources" / "KB"
    results = {}
    flags_zero = []
    flags_stale_30 = []
    flags_drift = []
    for moc_path in sorted(moc_dir.glob("moc-*.md")):
        text = moc_path.read_text(encoding="utf-8", errors="replace")
        rel = str(moc_path.relative_to(VAULT)).replace("\\", "/")
        # Extract date from frontmatter
        moc_date = None
        fm_m = FM_RE.match(text)
        if fm_m:
            d_m = DATE_RE.search(fm_m.group(1))
            if d_m:
                moc_date = d_m.group(1).strip()
        # Extract Dataview queries
        queries = DV_BLOCK.findall(text)
        if not queries:
            continue
        moc_results = []
        for kind, q in queries:
            matches = resolve(q, idx)
            moc_results.append({"kind": kind, "count": len(matches), "query_preview": q.strip()[:120]})
        total = sum(r["count"] for r in moc_results)
        # Use rel path (no anchor) as cache key — matches existing cache keys
        baseline = cache.get("moc_baselines", {}).get(rel)
        prior = baseline["result_count"] if baseline else None
        prior_date = baseline["date"] if baseline else None
        # Flags
        if prior is not None and prior >= 1 and total == 0:
            flags_zero.append({"moc": rel, "prior": prior, "current": 0, "prior_date": prior_date})
        if prior is not None and prior == total and moc_date:
            try:
                md = datetime.date.fromisoformat(moc_date)
                age_days = (datetime.date.today() - md).days
                if age_days > 30:
                    flags_stale_30.append({"moc": rel, "count": total, "moc_date": moc_date, "age_days": age_days})
            except Exception:
                pass
        if prior is not None and prior != total:
            flags_drift.append({"moc": rel, "prior": prior, "current": total, "diff": total - prior})
        results[rel] = {
            "queries": moc_results,
            "total_count": total,
            "moc_date": moc_date,
            "prior": prior,
            "prior_date": prior_date,
        }
    # Update cache (atomic via .tmp + rename)
    new_cache = dict(cache)
    new_cache["last_run"] = today
    new_baselines = {}
    for rel, r in results.items():
        new_baselines[rel] = {"result_count": r["total_count"], "date": today}
    # Preserve any pre-existing baseline keys we didn't overwrite (e.g. anchored variants)
    for k, v in cache.get("moc_baselines", {}).items():
        if k not in new_baselines:
            new_baselines[k] = v
    new_cache["moc_baselines"] = new_baselines
    tmp = CACHE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new_cache, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CACHE)
    out = {
        "results": results,
        "flags_zero_with_prior": flags_zero,
        "flags_stale_30day": flags_stale_30,
        "flags_drift": flags_drift,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
