#!/usr/bin/env python3
"""o16_manifest_check.py: removed-hunk-to-manifest-row accounting checker for the O16 trim.

Spec of record: Section 5 of
Projects/Agent-Governance-Research/work/2026-09-01-o16-trim-proposal.md.

Proves that every removed hunk of >= THRESHOLD consecutive lines in a CLAUDE.md
diff maps to a ruled manifest row (non-empty ruling_ref), and that MOVE/ARCHIVE/
MERGE destinations exist (MOVE-* destinations must contain the moved section's
heading text; MOVE-RULES destinations must carry paths: frontmatter).

It does NOT judge dispositions, diff destination content semantically, or
replace the safeguard-(e) grep. Exit 0 on PASS, 2 on FAIL, 1 on usage/parse error.

Usage:
  python o16_manifest_check.py --diff <file-or-git-range> --manifest <record.md> [--threshold 3]

--diff: a saved unified-diff file, or a git range (e.g. "abc123..HEAD") from which
        `git diff <range> -- CLAUDE.md` is taken.
--manifest: a markdown file containing one fenced ```json block with {"rows": [...]},
        each row: id, section_name, before_lines [start, end], disposition,
        destination_path (required for MOVE-*|ARCHIVE|MERGE), pointer_left, ruling_ref.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys

ENUM = {"STAY", "CONDENSE", "MOVE-RULES", "MOVE-SKILL", "ARCHIVE", "DELETE", "MERGE"}
NEEDS_DEST = {"MOVE-RULES", "MOVE-SKILL", "ARCHIVE", "MERGE"}


def load_manifest(path):
    text = io.open(path, encoding="utf-8").read()
    m = re.search(r"```json\s*\n(.*?)\n```", text, re.S)
    if not m:
        print(f"ERROR: no fenced json block found in {path}")
        sys.exit(1)
    data = json.loads(m.group(1))
    rows = data["rows"]
    problems = []
    for r in rows:
        rid = r.get("id", "<missing id>")
        if r.get("disposition") not in ENUM:
            problems.append(f"row {rid}: disposition {r.get('disposition')!r} not in enum")
        if not r.get("ruling_ref"):
            problems.append(f"row {rid}: empty ruling_ref")
        bl = r.get("before_lines")
        if (not isinstance(bl, list)) or len(bl) != 2 or bl[0] > bl[1]:
            problems.append(f"row {rid}: bad before_lines {bl!r}")
        if r.get("disposition") in NEEDS_DEST:
            dest = r.get("destination_path")
            if not dest:
                problems.append(f"row {rid}: {r['disposition']} row missing destination_path")
            elif not os.path.exists(dest):
                problems.append(f"row {rid}: destination_path does not exist: {dest}")
            else:
                if r["disposition"].startswith("MOVE-"):
                    head = io.open(dest, encoding="utf-8").read()
                    if r.get("section_name") and r["section_name"] not in head:
                        problems.append(
                            f"row {rid}: destination {dest} lacks heading text {r['section_name']!r}")
                if r["disposition"] == "MOVE-RULES":
                    top = "\n".join(io.open(dest, encoding="utf-8").read().split("\n")[:20])
                    if "paths:" not in top:
                        problems.append(f"row {rid}: MOVE-RULES destination {dest} lacks paths: frontmatter")
    return rows, problems


def read_diff(spec):
    if os.path.exists(spec):
        return io.open(spec, encoding="utf-8").read()
    r = subprocess.run(["git", "diff", spec, "--", "CLAUDE.md"],
                       capture_output=True, text=True)
    if r.returncode not in (0, 1):
        print(f"ERROR: git diff failed: {r.stderr.strip()[:300]}")
        sys.exit(1)
    return r.stdout


def removed_runs(diff_text):
    """Yield (start, end) original-file line ranges of consecutive removed lines."""
    runs = []
    orig = None
    run_start = None
    run_len = 0
    for line in diff_text.split("\n"):
        h = re.match(r"@@ -(\d+)(?:,(\d+))? \+", line)
        if h:
            if run_len:
                runs.append((run_start, run_start + run_len - 1))
            orig = int(h.group(1))
            run_start, run_len = None, 0
            continue
        if orig is None:
            continue
        if line.startswith("-") and not line.startswith("---"):
            if run_len == 0:
                run_start = orig
            run_len += 1
            orig += 1
        elif line.startswith("+") and not line.startswith("+++"):
            if run_len:
                runs.append((run_start, run_start + run_len - 1))
                run_start, run_len = None, 0
        else:
            if run_len:
                runs.append((run_start, run_start + run_len - 1))
                run_start, run_len = None, 0
            orig += 1
    if run_len:
        runs.append((run_start, run_start + run_len - 1))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diff", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--threshold", type=int, default=3)
    args = ap.parse_args()

    rows, problems = load_manifest(args.manifest)
    diff_text = read_diff(args.diff)
    if not diff_text.strip():
        print("NOTE: empty diff (no CLAUDE.md changes in range); manifest-only validation.")
    runs = removed_runs(diff_text)

    over = [r for r in runs if r[1] - r[0] + 1 >= args.threshold]
    under = [r for r in runs if r[1] - r[0] + 1 < args.threshold]

    print(f"removed runs: {len(runs)} total, {len(over)} at/over threshold {args.threshold}, "
          f"{len(under)} below")
    print("hunk range -> row id -> ruling_ref")
    unmapped = []
    for a, b in over:
        hits = [r for r in rows
                if not (b < r["before_lines"][0] or a > r["before_lines"][1])]
        if not hits:
            unmapped.append((a, b))
            print(f"  {a}-{b} -> UNMAPPED -> (none)")
        else:
            for r in hits:
                print(f"  {a}-{b} -> {r['id']} -> {r['ruling_ref']}")
    for a, b in under:
        print(f"  below-threshold removal {a}-{b} (eyeball review, no row required)")

    for a, b in unmapped:
        problems.append(f"unmapped over-threshold removed hunk at original lines {a}-{b}")

    if problems:
        print("FAIL")
        for p in problems:
            print(f"  - {p}")
        sys.exit(2)
    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
