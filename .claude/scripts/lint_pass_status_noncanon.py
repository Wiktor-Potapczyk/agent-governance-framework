#!/usr/bin/env python3
"""Lint Pass Q: STATUS_NONCANON (ROAD-5, 2026-09-08).

Advisory weekly scan of every in-scope note's frontmatter `status:` value
against the canonical value set. Closes the evaluation's R5 DARK row.
Complements, never replaces, Pass H's separate mtime-decay purpose.

Generator derivations, both fail-loud (exit 2, never a silent clean report):
  - the canonical values are parsed from spec R5's own enumeration line
    ("MUST be one of exactly N canonical values:", backticked tokens) in
    2026-05-11-target-structure-spec.md; exactly N values must parse
  - the scan scope is AST-extracted from vault-structure-check.py
    (INCLUDE_PREFIXES, EXCLUDE_PREFIXES, EXCLUDE_FILENAMES: the R2
    scoped-directory encoding already on disk), never retyped; Archives/
    stays excluded via the extracted prefixes (roadmap scope-narrow-first)

A missing `status:` field is NOT a finding (that is R3's concern).

CLI contract (shared by all lint_pass_* scripts):
  - always prints its measurement line
  - finding: `STATUS_NONCANON  path=<p> value=<v>`
  - exit 0 clean, 1 findings, 2 derivation failure
"""
import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_SPEC = VAULT / "Projects" / "Vault-Maintenance" / "work" / "2026-05-11-target-structure-spec.md"
DEFAULT_HOOK = VAULT / ".claude" / "hooks" / "vault-structure-check.py"

SPEC_ANCHOR = re.compile(
    r"MUST be one of exactly (\d+) canonical values:\s*((?:`[^`]+`(?:,\s*)?)+)")
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
STATUS_LINE = re.compile(r"^status:\s*(.+?)\s*$", re.MULTILINE)


def extract_assign(source_path, name):
    """AST-extract the literal assigned to `name` in a Python source file."""
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise LookupError(f"no assignment to {name} in {source_path}")


def canonical_values(spec_path):
    text = Path(spec_path).read_text(encoding="utf-8")
    m = SPEC_ANCHOR.search(text)
    if not m:
        return None
    expected = int(m.group(1))
    values = re.findall(r"`([^`]+)`", m.group(2))
    if len(values) != expected:
        return None
    return set(values)


def gitignored_paths(root):
    """The set of vault-relative paths git is told to ignore.

    Scope correction 2026-09-09. TC-6 was red at 279 findings, of which 202
    were files git does not track: gitignored scratch under `work/backups/`
    (.gitignore line 124) and similar. A contract that asserts the CURRENT
    vault is trustworthy must not score content that was deliberately excluded
    from the vault's tracked state, and going red on frozen scratch made the
    contract unreachable for a reason unrelated to vault health.

    Deliberately keyed on IGNORED, not merely untracked: a brand-new note that
    has not been committed yet is untracked but is genuinely live vault state,
    and must still be scored.

    Two failure cases that look alike and are not:
      - `root` is NOT a git repository at all (every test fixture, any scratch
        copy). No ignore rules exist, so the correct answer is the empty set.
        Treating this as an error would make the pass unrunnable off a repo.
      - `root` IS a repository but git failed. That is a real derivation
        failure: return None so the caller exits 2 loudly. Neither silent
        fallback is acceptable, since scanning everything restores the bug and
        scanning nothing hides real findings.
    """
    def _git(*args):
        try:
            return subprocess.run(["git", "-C", str(root), *args],
                                  capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.SubprocessError):
            return None

    probe = _git("rev-parse", "--is-inside-work-tree")
    if probe is None or probe.returncode != 0:
        return set()  # not a repo: no ignore rules to apply

    r = _git("ls-files", "--others", "--ignored", "--exclude-standard")
    if r is None or r.returncode != 0:
        return None  # a repo, but git broke: fail loud
    return {ln.strip().replace("\\", "/").lower()
            for ln in r.stdout.splitlines() if ln.strip()}


# An n8n blueprint's status is a BUILD GATE, not a lifecycle status:
# n8n-workflow-architect writes `#ready` or `#pending-flag-resolution`, and
# n8n-workflow-builder refuses to build on the pending value. Normalising it
# to the R5 canon would silently open that gate, so exactly these values on
# blueprint files are exempt, and the exemption is counted in the measurement
# line, never silent (2026-09-18).
BLUEPRINT_GATE_VALUES = frozenset({"ready", "pending-flag-resolution"})


# The exemption is anchored on what n8n-workflow-architect actually writes
# (its output format carries a `target_workflow:` frontmatter key), not on the
# filename alone: eleven other notes in the vault are named "*blueprint*" and
# are not build gates (architect review C-1, 2026-09-18).
TARGET_WORKFLOW_LINE = re.compile(r"^target_workflow\s*:", re.MULTILINE)


def is_blueprint_gate(filename, value, text):
    if "blueprint" not in filename.lower():
        return False
    if value.strip().lstrip("#").lower() not in BLUEPRINT_GATE_VALUES:
        return False
    fm = FRONTMATTER.match(text)
    return bool(fm and TARGET_WORKFLOW_LINE.search(fm.group(1)))


def status_of(text):
    m = FRONTMATTER.match(text)
    if not m:
        return None
    s = STATUS_LINE.search(m.group(1))
    if not s:
        return None
    return s.group(1).strip().strip("'\"")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault", default=str(VAULT))
    ap.add_argument("--spec", default=str(DEFAULT_SPEC))
    ap.add_argument("--hook-source", default=str(DEFAULT_HOOK))
    args = ap.parse_args(argv)

    try:
        canon = canonical_values(args.spec)
    except OSError as e:
        print(f"DERIVATION FAILURE: cannot read spec {args.spec}: {e}")
        return 2
    if canon is None:
        print(f"DERIVATION FAILURE: R5 enumeration line did not parse in {args.spec}")
        return 2

    try:
        include = tuple(extract_assign(args.hook_source, "INCLUDE_PREFIXES"))
        exclude = tuple(extract_assign(args.hook_source, "EXCLUDE_PREFIXES"))
        exclude_names = set(extract_assign(args.hook_source, "EXCLUDE_FILENAMES"))
    except (OSError, LookupError, ValueError, SyntaxError) as e:
        print(f"DERIVATION FAILURE: scope extraction from {args.hook_source}: {e}")
        return 2

    root = Path(args.vault)
    ignored = gitignored_paths(root)
    if ignored is None:
        print(f"DERIVATION FAILURE: cannot determine gitignored paths under {root}")
        return 2

    scanned = 0
    skipped_ignored = 0
    exempt_gate = 0
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", ".obsidian")]
        for fname in filenames:
            if not fname.lower().endswith(".md"):
                continue
            full = Path(dirpath) / fname
            rel = full.relative_to(root).as_posix().lower()
            if not rel.startswith(include):
                continue
            if rel.startswith(exclude):
                continue
            if fname.lower() in exclude_names:
                continue
            if rel in ignored:
                skipped_ignored += 1
                continue
            scanned += 1
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            value = status_of(text)
            if value is not None and is_blueprint_gate(fname, value, text):
                exempt_gate += 1
                continue
            if value is not None and value not in canon:
                findings.append((full.relative_to(root).as_posix(), value))

    # skipped_gitignored is printed, never silent: a scope narrowing that
    # shrinks a finding count must be visible in the same line as the count,
    # or the drop reads as an improvement in vault health that never happened.
    print(f"STATUS scanned={scanned} noncanonical={len(findings)} "
          f"skipped_gitignored={skipped_ignored} "
          f"exempt_blueprint_gate={exempt_gate} "
          f"canon={','.join(sorted(canon))}")
    for path, value in findings:
        print(f"STATUS_NONCANON  path={path} value={value}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
