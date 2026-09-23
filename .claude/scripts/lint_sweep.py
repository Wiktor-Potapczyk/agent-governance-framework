"""
lint_sweep.py — Weekly Vault Lint Sweep (R-2 engine, CC-AUTOMATION-LEARN Step 3).

Role: R-2 writer. Deterministic vault-wide wiki-citation lint, mirroring the R-1
collector pattern (collect_vault_metrics.py): pure Python, vehicle-agnostic, runs
under a Windows scheduled task or direct invocation. NO LLM, NO cloud, NO branch/PR
(superseded by the 2026-05-23 local-vehicle pivot + the 2026-05-25 main-only doctrine).

What it checks (reuses the already-extracted, tested `_wiki_citation_logic`):
  - every wiki-layer page (Resources/KB/** unconditional; Notes/** and
    Projects/**/archive/** when #wiki-tagged) has a valid source: field
  - each source entry's path exists on disk (ORPHAN_CITATION)
  - committed sha256 matches the file's current bytes (SOURCE_DRIFT)
  - type: generated entries skip the SHA gate (path-existence still enforced)
  - missing source: (MISSING_SOURCE), missing sha (MISSING_SHA), malformed frontmatter

Output (operational artifact — Resources/Observability/, NOT Resources/KB which is
wiki-layer): a canonical JSON findings file the R-2V verifier re-derives against, plus
a human-glanceable Markdown report. Each finding carries the EVIDENCE the verifier
needs to re-derive independently (page path, source index, committed + observed sha).

0 findings -> NOOP (no files written), mirroring the plan's R-2 noop rule.

Usage:
    python lint_sweep.py [--root DIR] [--outdir DIR] [--date YYYY-MM-DD] [--dry-run]

Exit codes: 0 = success (including noop / dry-run). 2 = bad args. 3 = root unreadable.
4 = output dir uncreatable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse the tested citation logic from the hooks dir (single source of truth).
_HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(_HOOKS_DIR))
from _wiki_citation_logic import (  # noqa: E402
    has_wiki_tag,
    is_wiki_path_by_tag,
    is_wiki_path_unconditional,
    normalize_rel_path,
    parse_source_field,
    validate_source_entries,
)

ROUTINE_VERSION = "r2-v1"


def _default_root() -> Path:
    return Path(os.environ.get("VAULT_DIR", str(Path(__file__).resolve().parent.parent.parent)))


def iter_wiki_pages(root: Path):
    """Yield (rel_path, content) for every wiki-layer .md page under root.

    Unconditional: Resources/KB/**.md. By-tag: Notes/**.md and
    Projects/**/archive/**.md that carry the #wiki tag. Excludes index/STATE/etc.
    """
    candidates = []
    kb = root / "Resources" / "KB"
    if kb.is_dir():
        candidates += list(kb.rglob("*.md"))
    notes = root / "Notes"
    if notes.is_dir():
        candidates += list(notes.rglob("*.md"))
    projects = root / "Projects"
    if projects.is_dir():
        candidates += [p for p in projects.rglob("*.md") if "/archive/" in p.as_posix().lower()]

    seen = set()
    for p in sorted(candidates):
        try:
            rel = normalize_rel_path(str(p.relative_to(root)))
        except ValueError:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if is_wiki_path_unconditional(rel):
            yield rel, content
        elif is_wiki_path_by_tag(rel) and has_wiki_tag(content):
            yield rel, content


def sweep(root: Path) -> dict:
    """Run the lint sweep. Returns a findings record (machine-canonical)."""
    pages_scanned = 0
    page_findings = []  # list of {page, code, severity, message, evidence}

    for rel, content in iter_wiki_pages(root):
        pages_scanned += 1
        entries = parse_source_field(content)
        if entries is None:
            page_findings.append({
                "page": rel,
                "code": "MALFORMED_FRONTMATTER",
                "severity": "error",
                "message": "frontmatter missing or unterminated; cannot read source:",
                "evidence": {"page": rel},
            })
            continue
        findings, _has_blocking = validate_source_entries(entries, root)
        for f in findings:
            # Attach the full source: array as re-derivation evidence; R-2V re-reads
            # the page from disk anyway and does not trust these recorded values.
            ev = {"page": rel, "entries": entries}
            page_findings.append({
                "page": rel,
                "code": f["code"],
                "severity": f["severity"],
                "message": f["message"],
                "evidence": ev,
            })

    by_code = {}
    for f in page_findings:
        by_code[f["code"]] = by_code.get(f["code"], 0) + 1

    return {
        "routine_version": ROUTINE_VERSION,
        "swept_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pages_scanned": pages_scanned,
        "finding_count": len(page_findings),
        "findings_by_code": by_code,
        "findings": page_findings,
        "verifier_status": "PENDING",
    }


def render_markdown(record: dict, date_str: str) -> str:
    lines = [
        f"# Vault Lint Sweep — {date_str}",
        "",
        f"Routine {record['routine_version']} · swept {record['swept_at']} · "
        f"{record['pages_scanned']} wiki pages scanned · {record['finding_count']} findings · "
        f"verifier: {record['verifier_status']}",
        "",
    ]
    if not record["findings"]:
        lines.append("**0 findings — wiki citation layer clean.**")
        return "\n".join(lines)
    lines.append("## Findings by code")
    for code, n in sorted(record["findings_by_code"].items(), key=lambda kv: -kv[1]):
        lines.append(f"- `{code}`: {n}")
    lines.append("")
    lines.append("## Detail")
    for f in record["findings"]:
        lines.append(f"- **{f['code']}** ({f['severity']}) — `{f['page']}`: {f['message']}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="R-2 weekly vault lint sweep (wiki citations).")
    parser.add_argument("--root", default=None, help="Vault root. Default: VAULT_DIR or inferred.")
    parser.add_argument("--outdir", default="Resources/Observability/lint-sweeps",
                        help="Output dir (vault-relative). Default: Resources/Observability/lint-sweeps")
    parser.add_argument("--date", default=None, help="Report date stamp YYYY-MM-DD. Default: today UTC.")
    parser.add_argument("--dry-run", action="store_true", help="Print JSON record to stdout; write nothing.")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else _default_root()
    if not root.is_dir():
        print(f"ERROR: vault root not found: {root}", file=sys.stderr)
        return 3

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    record = sweep(root)
    record["date"] = date_str

    if args.dry_run:
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0

    if record["finding_count"] == 0:
        print(f"[NOOP] Lint sweep clean — {record['pages_scanned']} wiki pages, 0 findings. No report written.")
        return 0

    outdir = root / args.outdir
    try:
        outdir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"ERROR: cannot create output dir '{outdir}': {exc}", file=sys.stderr)
        return 4

    json_path = outdir / f"{date_str}-lint.json"
    md_path = outdir / f"{date_str}-lint-report.md"
    try:
        json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(render_markdown(record, date_str), encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot write report: {exc}", file=sys.stderr)
        return 3

    print(f"[OK] {record['finding_count']} findings across {record['pages_scanned']} pages "
          f"-> {json_path.relative_to(root)} (+ .md). Verifier status PENDING (run R-2V).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
