#!/usr/bin/env python3
"""Lint Pass O: ROOT_STRAY (ROAD-3, 2026-09-08).

Advisory weekly diff of the vault root (depth 1) against an allowlist
state file. Each unlisted entry, file or directory, emits one ROOT_STRAY
finding. Structure mirrors Pass M: single-purpose scan module called from
the process-lint skill.

The allowlist (`_state/root-allowlist.json`) is seeded by `--seed` from
the live root itself (union of the directory listing and the first path
segment of root-level `git ls-files` entries), one entry per element,
sorted, then owner-reviewed. It is never hand-typed (generator-derivation
rule); the evaluation's hand-listed candidate list is a review aid only.

Enumeration note: when `git ls-files` is unavailable (tmp fixture roots
are not repos) the union degrades to the directory listing alone; this is
printed, not silent.

CLI contract (shared by all lint_pass_* scripts):
  - always prints its measurement line
  - finding: `ROOT_STRAY  name=<entry>`
  - exit 0 clean, 1 findings, 2 derivation failure (missing allowlist)
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_STATE = VAULT / ".claude" / "hooks" / "_state" / "root-allowlist.json"


def enumerate_root(root):
    """Depth-1 root entries: listdir UNION first segments of git ls-files."""
    entries = set(os.listdir(root))
    git_note = ""
    try:
        # -z: NUL-separated output, no C-style quoting of special-char paths
        # (plain ls-files quotes them, which turned 'Clippings/<unicode>...'
        # into a bogus '"Clippings' allowlist entry on the first seed run).
        r = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        if r.returncode == 0:
            for line in r.stdout.split("\0"):
                seg = line.split("/", 1)[0]
                if seg:
                    entries.add(seg)
        else:
            git_note = " (git ls-files unavailable; listdir only)"
    except (OSError, subprocess.SubprocessError):
        git_note = " (git ls-files unavailable; listdir only)"
    return entries, git_note


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(VAULT))
    ap.add_argument("--state-file", default=str(DEFAULT_STATE))
    ap.add_argument("--seed", action="store_true",
                    help="write the allowlist from the live root enumeration")
    args = ap.parse_args(argv)

    if not os.path.isdir(args.root):
        print(f"DERIVATION FAILURE: root not a directory: {args.root}")
        return 2

    live, git_note = enumerate_root(args.root)

    if args.seed:
        state_path = Path(args.state_file)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entries": sorted(live),
        }
        with open(state_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"SEEDED {state_path}: {len(payload['entries'])} entries{git_note}")
        return 0

    try:
        allow = set(json.loads(Path(args.state_file).read_text(encoding="utf-8"))["entries"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"DERIVATION FAILURE: allowlist unusable ({args.state_file}): {e}")
        return 2

    strays = sorted(live - allow)
    print(f"ROOT entries={len(live)} allowlisted={len(allow)} strays={len(strays)}{git_note}")
    for name in strays:
        print(f"ROOT_STRAY  name={name}")
    return 1 if strays else 0


if __name__ == "__main__":
    sys.exit(main())
