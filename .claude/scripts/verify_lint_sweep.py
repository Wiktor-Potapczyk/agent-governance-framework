"""
verify_lint_sweep.py — Lint Verifier (R-2V engine, CC-AUTOMATION-LEARN Step 3).

Role: R-2V verifier. The INDEPENDENT gate on R-2's lint findings, mirroring R-1V's
relationship to R-1. Runs as a separate scheduled invocation (fresh context) and
does NOT trust R-2's output: for each finding R-2 reported, it re-reads the cited
page from disk and re-derives that specific finding with its OWN implementation —
deliberately NOT importing `_wiki_citation_logic` (the module R-2 used), so the two
do not share blind spots. This is generator != verifier enforced at the engine level
(the `verification-gated-research` separate-verifier rule).

Verdict:
  - every R-2 finding reproduced by the independent re-derivation -> PASS
  - any R-2 finding NOT reproducible (spurious / drifted-away) -> VERIFY-FAIL,
    naming the specific non-reproducible findings.

Output: writes verifier_status + a `<date>-lint-verify.json` sibling next to R-2's
report; updates the report JSON's verifier_status in place. Prints a summary.

Usage:
    python verify_lint_sweep.py [--root DIR] [--findings PATH] [--dry-run]
    (--findings defaults to the most recent *-lint.json under the sweep dir.)

Exit codes: 0 = PASS or nothing-to-verify. 1 = VERIFY-FAIL. 2 = bad args.
3 = findings file unreadable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROUTINE_VERSION = "r2v-v1"
SWEEP_DIR = "Resources/Observability/lint-sweeps"


def _default_root() -> Path:
    return Path(os.environ.get("VAULT_DIR", str(Path(__file__).resolve().parent.parent.parent)))


def _latest_findings(root: Path) -> Path | None:
    d = root / SWEEP_DIR
    if not d.is_dir():
        return None
    cands = sorted(d.glob("*-lint.json"))
    return cands[-1] if cands else None


# --- Independent frontmatter source: extractor (deliberately NOT parse_source_field) ---
# R-2 used _wiki_citation_logic.parse_source_field (line-walking). This is a separate
# regex-block implementation so a bug in one is not mirrored in the other.

def _independent_frontmatter(content: str) -> str | None:
    """Return frontmatter body, or None if missing/unterminated."""
    if not content.startswith("---"):
        return None
    m = re.search(r"\n---", content[3:])
    if not m:
        return None
    return content[3:3 + m.start()]


def _independent_source_entries(content: str) -> list[dict] | None:
    """Independently parse the source: block into a list of {path,sha256,type}.

    Returns None if frontmatter malformed, [] if no source: field.
    """
    fm = _independent_frontmatter(content)
    if fm is None:
        return None
    lines = fm.split("\n")
    # find the source: key and capture indented lines under it
    out: list[dict] = []
    in_src = False
    cur: dict = {}
    for line in lines:
        if re.match(r"^source\s*:", line):
            in_src = True
            continue
        if not in_src:
            continue
        if line.strip() == "":
            continue
        if not line.startswith((" ", "\t")):  # dedent to col 0 => end of block
            break
        stripped = line.strip()
        if stripped.startswith("-"):
            if cur:
                out.append(cur)
            cur = {}
            stripped = stripped[1:].strip()
        mm = re.match(r'^(\w+)\s*:\s*"?([^"\n]*)"?\s*$', stripped)
        if mm:
            cur[mm.group(1)] = mm.group(2).strip().strip('"').strip("'")
    if cur:
        out.append(cur)
    return out


def reproduce(finding: dict, root: Path) -> tuple[bool, str]:
    """Independently re-derive a single R-2 finding. Returns (reproduced, note)."""
    code = finding.get("code")
    page = finding.get("page", "")
    page_path = root / page
    if not page_path.exists():
        # If the cited page itself is gone, a page-level finding can't be reproduced.
        return False, f"page '{page}' no longer exists"
    content = page_path.read_text(encoding="utf-8", errors="replace")
    entries = _independent_source_entries(content)

    if code == "MALFORMED_FRONTMATTER":
        return (entries is None), ("frontmatter still malformed" if entries is None
                                   else "frontmatter now parses — NOT reproduced")
    if code == "MISSING_SOURCE":
        return (entries == []), ("source: still absent/empty" if entries == []
                                 else f"source: now present ({len(entries or [])} entries) — NOT reproduced")
    if entries is None:
        return False, "frontmatter malformed but finding was citation-level — NOT reproduced"

    # The remaining codes are per-entry; reproduce if ANY entry independently shows the issue.
    if code == "ORPHAN_CITATION":
        for e in entries:
            p = e.get("path", "")
            if p and not (root / p).exists():
                return True, f"path '{p}' independently confirmed missing"
        return False, "all source paths now exist — NOT reproduced"
    if code == "SOURCE_DRIFT":
        for e in entries:
            p, committed = e.get("path", ""), e.get("sha256", "")
            if not p or not committed or e.get("type") == "generated":
                continue
            fp = root / p
            if fp.exists():
                actual = hashlib.sha256(fp.read_bytes()).hexdigest()
                if actual != committed:
                    return True, f"'{p}' sha independently confirmed drifted ({committed[:8]}!={actual[:8]})"
        return False, "all shas now match — NOT reproduced"
    if code == "MISSING_SHA":
        for e in entries:
            if e.get("path") and not e.get("sha256") and e.get("type") != "generated":
                return True, "source entry independently confirmed missing sha256"
        return False, "all entries now have sha / are generated — NOT reproduced"
    if code in ("EMPTY_SOURCE_PATH", "HASH_COMPUTE_FAIL"):
        # Re-derive conservatively: confirm an entry with empty/unreadable path.
        for e in entries:
            if not e.get("path"):
                return True, "empty source path independently confirmed"
        return False, "no empty path found — NOT reproduced"
    return False, f"unknown finding code '{code}' — cannot independently re-derive"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="R-2V independent verifier of R-2 lint findings.")
    parser.add_argument("--root", default=None)
    parser.add_argument("--findings", default=None, help="Path to R-2 *-lint.json. Default: latest.")
    parser.add_argument("--dry-run", action="store_true", help="Print verdict; write nothing.")
    args = parser.parse_args(argv)

    root = Path(args.root) if args.root else _default_root()
    fpath = Path(args.findings) if args.findings else _latest_findings(root)
    if fpath is None or not fpath.exists():
        print("[NOOP] No lint findings file to verify (R-2 may have found 0 findings).")
        return 0
    try:
        record = json.loads(fpath.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read findings '{fpath}': {exc}", file=sys.stderr)
        return 3

    results = []
    spurious = []
    for f in record.get("findings", []):
        ok, note = reproduce(f, root)
        results.append({"page": f.get("page"), "code": f.get("code"), "reproduced": ok, "note": note})
        if not ok:
            spurious.append(results[-1])

    status = "PASS" if not spurious else "VERIFY-FAIL"
    verify_record = {
        "routine_version": ROUTINE_VERSION,
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "findings_checked": len(results),
        "reproduced": sum(1 for r in results if r["reproduced"]),
        "spurious": spurious,
        "verifier_status": status,
        "source_report": fpath.name,
    }

    if args.dry_run:
        print(json.dumps(verify_record, ensure_ascii=False, indent=2))
        return 0 if status == "PASS" else 1

    # Update R-2's report in place + write the verify sidecar.
    try:
        record["verifier_status"] = status
        fpath.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (fpath.parent / fpath.name.replace("-lint.json", "-lint-verify.json")).write_text(
            json.dumps(verify_record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: cannot write verification result: {exc}", file=sys.stderr)
        return 3

    print(f"[{status}] {verify_record['reproduced']}/{verify_record['findings_checked']} "
          f"R-2 findings independently reproduced."
          + ("" if status == "PASS" else f" {len(spurious)} spurious: "
             + ", ".join(f"{s['code']}@{s['page']}" for s in spurious[:5])))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
