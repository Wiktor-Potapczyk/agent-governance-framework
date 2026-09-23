#!/usr/bin/env python3
"""Lint Pass N: MEMORY_OVERFILL (ROAD-2, 2026-09-08).

Advisory weekly measure of MEMORY.md size against the byte target that
`check_memory_index.py` prints (the `(target < NNNNN)` f-string fragment).
The target is READ FROM THAT SOURCE at run time, never re-typed here
(generator-derivation rule; the script may later expose it as a named
constant, in which case the regex below must be updated deliberately).

CLI contract (shared by all lint_pass_* scripts):
  - always prints its measurement line(s), findings or not
  - one line per finding: `MEMORY_OVERFILL  bytes=<n> target=<t> long_lines=<k>`
  - exit 0 clean, 1 findings, 2 derivation failure (fail-loud, never a
    silent clean report)

Read-only; writes no state.
"""
import argparse
import os
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_SOURCE = SCRIPTS / "check_memory_index.py"

TARGET_RE = re.compile(r"\(target < (\d+)\)")
LONG_LINE_CHARS = 200


def derive_memory_file():
    r"""~/.claude/projects/<enc>/memory/MEMORY.md, <enc> from the vault path.

    Encoding rule (verified against the one live value): every colon,
    backslash, and slash in the absolute vault path becomes `-`
    (C:\...\Vault -> C--Users-WiktorPotapczyk-Desktop-Vault).

    TASK-034 (migration plan Phase 1, 2026-09-15-scheduled-jobs-off-laptop-
    plan.md): VAULT_MEMORY_ROOT, when set, names the memory ROOT directory
    directly (MEMORY.md is expected inside it) and wins outright -- this is
    the override a cloud runner sets. When unset, today's Path.home()-derived
    path is tried first; only when THAT path does not exist (true on every
    machine but this laptop) does this fall back to the committed mirror
    mirror_user_claude.py already writes at .claude/user-claude-mirror/memory/
    (DEST_REL, refreshed every 30 minutes via auto-commit.ps1). Laptop
    behavior is unchanged: the live path exists here, so it is still returned.
    """
    override = os.environ.get("VAULT_MEMORY_ROOT")
    if override:
        return Path(override) / "MEMORY.md"
    enc = re.sub(r"[:\\/]", "-", str(VAULT))
    live = Path.home() / ".claude" / "projects" / enc / "memory"
    if live.is_dir():
        return live / "MEMORY.md"
    return VAULT / ".claude" / "user-claude-mirror" / "memory" / "MEMORY.md"


def extract_target(source_path):
    text = Path(source_path).read_text(encoding="utf-8")
    m = TARGET_RE.search(text)
    if not m:
        return None
    return int(m.group(1))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", default=str(DEFAULT_SOURCE),
                    help="check_memory_index.py to read the byte target from")
    ap.add_argument("--memory-file", default=None,
                    help="MEMORY.md override (tests); default is derived")
    args = ap.parse_args(argv)

    try:
        target = extract_target(args.source)
    except OSError as e:
        print(f"DERIVATION FAILURE: cannot read {args.source}: {e}")
        return 2
    if target is None:
        print(f"DERIVATION FAILURE: no '(target < NNNNN)' literal in {args.source}")
        return 2

    mem = Path(args.memory_file) if args.memory_file else derive_memory_file()
    if not mem.is_file():
        print(f"DERIVATION FAILURE: memory file absent: {mem}")
        return 2

    size = os.path.getsize(mem)
    with open(mem, encoding="utf-8") as f:
        long_lines = sum(1 for line in f if len(line.rstrip("\n")) > LONG_LINE_CHARS)

    print(f"MEMORY bytes={size} target={target} long_lines={long_lines}  ({mem})")
    if size > target:
        print(f"MEMORY_OVERFILL  bytes={size} target={target} long_lines={long_lines}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
