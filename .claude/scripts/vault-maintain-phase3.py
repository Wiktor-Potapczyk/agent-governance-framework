#!/usr/bin/env python3
"""Phase 3 cross-project link integrity.

Scan every [[wiki-link]] in Projects/ + Notes/. Resolve against vault file index.
Classify: resolved / orphaned / one-way (resolved but target does not link back).
Write report; NO auto-fix.
"""
import re
import json
import datetime
from pathlib import Path
from collections import defaultdict

VAULT = Path(__file__).resolve().parents[2]
SCAN_DIRS_FOR_LINKS = ["Projects", "Notes"]
INDEX_DIRS = ["Inbox", "Notes", "Projects", "Resources", "Areas", "Archives", "Daily Notes", "Templates", "Clippings"]

WIKI_RE = re.compile(r"\[\[([^\]\|#]+?)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]+`")


def build_file_index():
    """basename → list of relative paths; relpath_lower → relpath."""
    by_basename = defaultdict(list)
    by_relpath = {}
    for d in INDEX_DIRS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            stem = p.stem
            by_basename[stem.lower()].append(rel)
            by_relpath[rel.lower()] = rel
            # also index without .md extension by relpath
            by_relpath[rel.lower().removesuffix(".md")] = rel
    return by_basename, by_relpath


def strip_code(text: str) -> str:
    text = CODE_FENCE_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    return text


def extract_links(text: str):
    text = strip_code(text)
    return [m.group(1).strip() for m in WIKI_RE.finditer(text)]


def resolve_link(target: str, by_basename, by_relpath):
    """Return list of resolved relative paths (could be 0, 1, or many for ambiguous basenames)."""
    t = target.strip()
    if not t:
        return []
    tl = t.lower().removesuffix(".md")
    # 1. Try exact relative-path match
    if tl in by_relpath:
        return [by_relpath[tl]]
    if (tl + ".md") in by_relpath:
        return [by_relpath[tl + ".md"]]
    # 2. Try basename match
    stem = tl.rsplit("/", 1)[-1]
    if stem in by_basename:
        return list(by_basename[stem])
    return []


def main():
    by_basename, by_relpath = build_file_index()

    # Forward link map: source_rel → set of resolved targets
    forward = defaultdict(set)
    # Track all (source, target_text, resolution_status, resolved_paths)
    link_records = []  # list of dicts

    for d in SCAN_DIRS_FOR_LINKS:
        root = VAULT / d
        if not root.exists():
            continue
        for p in root.rglob("*.md"):
            rel = str(p.relative_to(VAULT)).replace("\\", "/")
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for raw in extract_links(text):
                resolved = resolve_link(raw, by_basename, by_relpath)
                rec = {
                    "source": rel,
                    "target_text": raw,
                    "resolved": resolved,
                    "ambiguous": len(resolved) > 1,
                }
                link_records.append(rec)
                for r in resolved:
                    forward[rel].add(r)

    # Build backward map for one-way detection
    backward = defaultdict(set)
    for src, tgts in forward.items():
        for t in tgts:
            backward[t].add(src)

    # Classify
    resolved = []
    orphaned = []
    ambiguous = []
    one_way_pairs = []  # (src, tgt) where src→tgt but tgt has no edge back

    for rec in link_records:
        if not rec["resolved"]:
            orphaned.append(rec)
        elif rec["ambiguous"]:
            ambiguous.append(rec)
        else:
            resolved.append(rec)
            tgt = rec["resolved"][0]
            src = rec["source"]
            if src not in forward.get(tgt, set()):
                # tgt does NOT link back to src
                one_way_pairs.append((src, tgt))

    print(f"Total links scanned: {len(link_records)}")
    print(f"Resolved unique edges: {len(resolved)}")
    print(f"Ambiguous (basename collision): {len(ambiguous)}")
    print(f"Orphaned (no resolution): {len(orphaned)}")
    print(f"One-way edges (resolved but no back-link): {len(one_way_pairs)}")

    out = {
        "summary": {
            "total_links": len(link_records),
            "resolved": len(resolved),
            "ambiguous": len(ambiguous),
            "orphaned": len(orphaned),
            "one_way_edges": len(one_way_pairs),
        },
        "orphaned": orphaned,
        "ambiguous": ambiguous,
        # Don't dump all one-way pairs (huge). Aggregate by source.
        "one_way_by_source_top": [],
    }
    one_way_by_source = defaultdict(int)
    for src, _ in one_way_pairs:
        one_way_by_source[src] += 1
    top = sorted(one_way_by_source.items(), key=lambda x: -x[1])[:30]
    out["one_way_by_source_top"] = [{"source": s, "count": c} for s, c in top]

    out_path = VAULT / ".claude" / "scripts" / "phase3.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull report → {out_path.relative_to(VAULT)}")


if __name__ == "__main__":
    main()
