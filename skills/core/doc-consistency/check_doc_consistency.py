#!/usr/bin/env python3
"""doc-consistency deterministic pre-check.

Reads a doc-coupling manifest (JSON) and flags EXACT cross-referenced-value
contradictions between documentation files and their authoritative sources.

This is the cheap, deterministic Phase-3 gate of the `doc-consistency` skill.
It catches the failure class that bit us — a count/version/path asserted one
way in doc A and another way in doc B (or in the live system) — WITHOUT any
LLM call. Semantic / prose drift is out of scope here (that is the skill's
LLM reconciliation phase); this script only compares exact values.

Pure Python 3 stdlib (no pip, no yaml — manifest is JSON so we stay stdlib).
All file reads use encoding='utf-8' (Windows open() otherwise defaults to a
locale codec such as cp1252).

Manifest schema (JSON):
{
  "root": ".",                       # optional; base dir for all relative paths (default: manifest's dir)
  "checks": [
    {
      "id": "shared-libraries-count",         # human label
      "expect": {                              # the authoritative value, ONE of:
        "count_files": {"dir": ".claude/hooks", "glob": "_*.py"}   # live count of matching files
        # OR "literal": "4"                    # a hand-set source-of-truth value
        # OR "count_lines": {"file": "x", "pattern": "regex"}      # lines in file matching regex
      },
      "asserted_in": [                          # docs that state this value
        {"file": "README.md", "pattern": "(\\d+) shared librar"},
        {"file": "docs/architecture.md", "pattern": "Shared hook libraries \\| (\\d+)"}
      ]
    }
  ]
}

Each `asserted_in` entry's regex MUST have exactly one capture group = the value
the doc claims. The script compares every claimed value against the expected
(authoritative) value. Any difference is a MISMATCH.

Exit code: 0 = all checks consistent; 1 = at least one mismatch or error; 2 = usage/manifest error.
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import os
import re
import sys


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _resolve(root: str, rel: str) -> str:
    return os.path.normpath(os.path.join(root, rel))


def compute_expected(expect: dict, root: str) -> tuple[str | None, str | None]:
    """Return (value, error). value is a string for uniform comparison."""
    if "literal" in expect:
        return str(expect["literal"]), None
    if "count_files" in expect:
        spec = expect["count_files"]
        d = _resolve(root, spec["dir"])
        pattern = spec.get("glob", "*")
        if not os.path.isdir(d):
            return None, f"count_files dir not found: {d}"
        matches = globmod.glob(os.path.join(d, pattern))
        # files only (a glob may catch subdirs); count regular files
        n = sum(1 for m in matches if os.path.isfile(m))
        return str(n), None
    if "count_lines" in expect:
        spec = expect["count_lines"]
        f = _resolve(root, spec["file"])
        if not os.path.isfile(f):
            return None, f"count_lines file not found: {f}"
        rx = re.compile(spec["pattern"])
        n = sum(1 for line in _read(f).splitlines() if rx.search(line))
        return str(n), None
    return None, f"unknown expect type: {list(expect.keys())}"


def read_asserted(entry: dict, root: str) -> tuple[str | None, str | None]:
    """Return (claimed_value, error) for one asserted_in entry."""
    f = _resolve(root, entry["file"])
    if not os.path.isfile(f):
        return None, f"asserted_in file not found: {f}"
    rx = re.compile(entry["pattern"])
    if rx.groups < 1:
        return None, f"pattern has no capture group in {entry['file']}: {entry['pattern']!r}"
    m = rx.search(_read(f))
    if not m:
        return None, f"pattern did not match in {entry['file']}: {entry['pattern']!r}"
    return m.group(1).strip(), None


def run(manifest_path: str) -> int:
    if not os.path.isfile(manifest_path):
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(_read(manifest_path))
    except json.JSONDecodeError as e:
        print(f"ERROR: manifest is not valid JSON: {e}", file=sys.stderr)
        return 2

    # root defaults to the manifest's own directory
    root = manifest.get("root")
    base = os.path.dirname(os.path.abspath(manifest_path))
    root = _resolve(base, root) if root else base

    checks = manifest.get("checks", [])
    if not checks:
        print("ERROR: manifest has no 'checks'", file=sys.stderr)
        return 2

    mismatches = 0
    errors = 0
    for chk in checks:
        cid = chk.get("id", "<unnamed>")
        expected, err = compute_expected(chk.get("expect", {}), root)
        if err:
            print(f"[ERROR] {cid}: {err}")
            errors += 1
            continue
        for entry in chk.get("asserted_in", []):
            claimed, aerr = read_asserted(entry, root)
            if aerr:
                print(f"[ERROR] {cid}: {aerr}")
                errors += 1
                continue
            if claimed != expected:
                print(
                    f"[MISMATCH] {cid}: {entry['file']} claims {claimed!r} "
                    f"but authoritative value is {expected!r}"
                )
                mismatches += 1
            else:
                print(f"[OK] {cid}: {entry['file']} = {claimed!r}")

    print(
        f"\nsummary: {mismatches} mismatch(es), {errors} error(s) "
        f"across {len(checks)} check(s)"
    )
    return 1 if (mismatches or errors) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic doc-consistency pre-check: compare "
        "cross-referenced values across docs against their authoritative source.",
    )
    ap.add_argument(
        "manifest",
        nargs="?",
        default=".doc-consistency.json",
        help="path to the JSON doc-coupling manifest (default: .doc-consistency.json)",
    )
    args = ap.parse_args(argv)
    return run(args.manifest)


if __name__ == "__main__":
    sys.exit(main())
