"""self_heal_apply.py: the improver workflow's deterministic apply step.

Write-path decision of 2026-09-18 (Route B, the GitHub agentic-workflows
shape): the improver never writes into the real checkout. It works in a
throwaway shadow copy of the checkout (no .git, no credentials) in which the
vault's `.claude` directory is mounted under the neutral name `_claude`, so
Claude Code's protected-path safety check (which denies every write under
`.claude/` in every permission mode except bypassPermissions) never fires
and no permission mode is widened. This script then runs from the REAL
checkout, in a process the improver never touched:

  1. refuses to proceed if the real checkout is dirty (the improver reached
     it by some other route, or the runner is not in the expected state);
  2. derives the change set by comparing the shadow tree with the tracked
     files of the checkout (raw bytes, never text mode), mapping `_claude/`
     back to `.claude/`; renames appear as one delete plus one add;
  3. treats an empty change set as a FAILURE (exit 1) and prints the
     improver's final result text and every permission_denied event from
     the run log, so a round that could not act is never a quiet green;
  4. validates every changed path, collecting every violation before
     returning: symlink, path hygiene (backslash, `..`, NFKC change,
     control characters, whitespace, non-ASCII under .claude/), containment
     inside the checkout, forbidden_paths (always), binary content, per-file
     size cap, the assigned class's `paths` and `excludes`, and the round's
     file-count cap;
  5. on any violation exits 1 having copied nothing;
  6. otherwise copies the validated files into the checkout (deletions
     included) and stages exactly those paths with explicit `git add` /
     `git rm`, never `git add --all`, then prints the staged list.

Pure functions over injectable inputs; the git calls take a `run_fn`. Python
3.14, standard library plus self_heal_glob.py, self_heal_stage.py and
self_heal_pr_body.py beside this file.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from typing import NamedTuple
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TARGETS = HERE.parent / "targets.json"

SHADOW_DIRNAME = "_claude"
REAL_DIRNAME = ".claude"
MAX_FILE_BYTES = 200_000
MAX_CHANGED_FILES = 25
IGNORED_DIR_SEGMENTS = {"__pycache__", ".pytest_cache", ".git"}
IGNORED_SUFFIXES = (".pyc", ".pyo")
BINARY_PROBE_BYTES = 8192


def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _glob():
    return _load_sibling("self_heal_glob")


class Change(NamedTuple):
    path: str            # real (.claude/...) form, forward slashes
    kind: str            # added | modified | deleted
    source: Path | None  # absolute path inside the shadow; None for deleted


# ---------------------------------------------------------------------------
# path mapping
# ---------------------------------------------------------------------------

def map_shadow_path(rel: str) -> str:
    """`_claude/x` -> `.claude/x`, bare `_claude` -> `.claude`; anything
    else unchanged. Only a leading top-level segment is mapped."""
    if rel == SHADOW_DIRNAME:
        return REAL_DIRNAME
    if rel.startswith(SHADOW_DIRNAME + "/"):
        return REAL_DIRNAME + rel[len(SHADOW_DIRNAME):]
    return rel


def map_real_path(rel: str) -> str:
    """Inverse of map_shadow_path."""
    if rel == REAL_DIRNAME:
        return SHADOW_DIRNAME
    if rel.startswith(REAL_DIRNAME + "/"):
        return SHADOW_DIRNAME + rel[len(REAL_DIRNAME):]
    return rel


# ---------------------------------------------------------------------------
# git-side inputs
# ---------------------------------------------------------------------------

def verify_clean_checkout(checkout: Path, run_fn=subprocess.run) -> list[str]:
    """Returns the list of paths `git status --porcelain` reports for
    TRACKED changes (modified, deleted, renamed, staged). Untracked files
    are ignored: the runner legitimately has the run log and bytecode
    caches lying around."""
    proc = run_fn(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=no", "-z"],
                  capture_output=True, check=True)
    out = proc.stdout.decode("utf-8", "surrogateescape")
    dirty = []
    for entry in out.split("\0"):
        if not entry:
            continue
        dirty.append(entry[3:])
    return dirty


def list_checkout_tracked(checkout: Path, run_fn=subprocess.run) -> set[str]:
    proc = run_fn(["git", "-C", str(checkout), "ls-files", "-z"], capture_output=True, check=True)
    return {p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p}


# ---------------------------------------------------------------------------
# shadow-side inputs
# ---------------------------------------------------------------------------

def _ignored(rel_parts: tuple[str, ...], name: str) -> bool:
    if any(seg in IGNORED_DIR_SEGMENTS for seg in rel_parts):
        return True
    return name.endswith(IGNORED_SUFFIXES)


def list_shadow_paths(shadow: Path) -> dict[str, Path]:
    """Every file (and every symlink, whether to a file or a directory) in
    the shadow tree, keyed by its forward-slash relative path in SHADOW
    form. Bytecode caches and pytest caches are skipped. Symlinks are
    listed, never followed, so validation can reject them."""
    shadow = Path(shadow)
    found: dict[str, Path] = {}
    for root, dirs, files in os.walk(shadow, followlinks=False):
        rel_root = Path(root).relative_to(shadow)
        parts = rel_root.parts
        if any(seg in IGNORED_DIR_SEGMENTS for seg in parts):
            dirs[:] = []
            continue
        keep_dirs = []
        for d in dirs:
            if d in IGNORED_DIR_SEGMENTS:
                continue
            abs_d = Path(root) / d
            if abs_d.is_symlink():
                found[(rel_root / d).as_posix()] = abs_d
                continue
            keep_dirs.append(d)
        dirs[:] = keep_dirs
        for f in files:
            if _ignored(parts, f):
                continue
            found[(rel_root / f).as_posix()] = Path(root) / f
    return found


def _same_bytes(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            ca, cb = fa.read(65536), fb.read(65536)
            if ca != cb:
                return False
            if not ca:
                return True


def diff_paths(shadow_paths: dict[str, Path], checkout_tracked: set[str],
               shadow: Path, checkout: Path) -> list[Change]:
    """Change set between the shadow tree and the checkout's tracked files.
    Raw byte comparison; a symlink in the shadow is always reported as a
    change unless the tracked path is a symlink with the same target."""
    checkout = Path(checkout)
    changes: list[Change] = []
    seen_real: set[str] = set()
    for shadow_rel in sorted(shadow_paths):
        src = shadow_paths[shadow_rel]
        real = map_shadow_path(shadow_rel)
        seen_real.add(real)
        dst = checkout / real
        if real in checkout_tracked:
            if src.is_symlink() or dst.is_symlink():
                if src.is_symlink() and dst.is_symlink() and os.readlink(src) == os.readlink(dst):
                    continue
                changes.append(Change(real, "modified", src))
            elif dst.is_file() and _same_bytes(src, dst):
                continue
            else:
                changes.append(Change(real, "modified", src))
        else:
            changes.append(Change(real, "added", src))
    for tracked in sorted(checkout_tracked):
        if tracked in seen_real:
            continue
        parts = tuple(tracked.split("/"))
        if _ignored(parts[:-1], parts[-1]):
            continue
        changes.append(Change(tracked, "deleted", None))
    return changes


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

def is_binary(path: Path) -> bool:
    with open(path, "rb") as fh:
        head = fh.read(BINARY_PROBE_BYTES)
    if b"\x00" in head:
        return True
    try:
        head.decode("utf-8", "strict")
        return False
    except UnicodeDecodeError as exc:
        # a multibyte sequence cut by the probe window is not binary
        return not (len(head) == BINARY_PROBE_BYTES and exc.end == len(head) and exc.start >= len(head) - 3)


@functools.cache
def _hygiene():
    return _load_sibling("self_heal_path_hygiene")


def _hygiene_reasons(path: str) -> list[str]:
    """The hard tier of the loop's one path hygiene check
    (self_heal_path_hygiene.py). A violation here ends the round, so the
    mixed character script heuristic is left to the accept step, where a
    person decides."""
    return _hygiene().hard_reasons(path)


def load_class(targets_path: Path, name: str) -> dict:
    data = json.loads(Path(targets_path).read_text(encoding="utf-8"))
    for cls in data.get("allowed_classes", []):
        if cls.get("class") == name:
            return cls
    raise SystemExit(f"self_heal_apply: class {name!r} is not in targets.json allowed_classes")


def validate_changes(changes: list[Change], cls: dict, targets: dict, checkout: Path,
                     tracked: set[str] | None = None) -> list[str]:
    """Every violation for every change, in path order; empty means clean.
    `tracked` (the checkout's tracked paths) enables the case-collision
    check: an added path that differs from a tracked path only by case
    would silently overwrite it on a case-insensitive filesystem."""
    glob = _glob()
    forbidden = [str(p) for p in targets.get("forbidden_paths", [])]
    paths = [str(p) for p in cls.get("paths", [])]
    excludes = [str(p) for p in cls.get("excludes", [])]
    checkout_res = Path(checkout).resolve()
    lowered = {t.lower(): t for t in (tracked or set())}
    batch_lower: dict[str, str] = {}
    violations: list[str] = []
    if len(changes) > MAX_CHANGED_FILES:
        violations.append(f"count: {len(changes)} changed paths exceeds the round cap of {MAX_CHANGED_FILES}")
    for ch in changes:
        p = ch.path
        if ch.source is not None and Path(ch.source).is_symlink():
            violations.append(f"{p}: symlink in the shadow tree")
            continue
        reasons = _hygiene_reasons(p)
        if reasons:
            violations.append(f"{p}: path hygiene: " + "; ".join(reasons))
            continue
        if ch.kind == "added" and p.lower() in lowered and lowered[p.lower()] != p:
            violations.append(f"{p}: differs only by case from tracked path {lowered[p.lower()]}")
            continue
        if ch.kind != "deleted":
            twin = batch_lower.setdefault(p.lower(), p)
            if twin != p:
                violations.append(f"{p}: differs only by case from {twin} in the same round")
                continue
        try:
            (checkout_res / p).resolve().relative_to(checkout_res)
        except ValueError:
            violations.append(f"{p}: resolves outside the checkout")
            continue
        if glob.path_matches_any(p, forbidden):
            violations.append(f"{p}: matches forbidden_paths")
            continue
        if ch.kind != "deleted" and ch.source is not None:
            if is_binary(ch.source):
                violations.append(f"{p}: binary content")
                continue
            size = Path(ch.source).stat().st_size
            if size > MAX_FILE_BYTES:
                violations.append(f"{p}: size {size} bytes exceeds the per-file cap of {MAX_FILE_BYTES}")
                continue
        if not glob.path_matches_any(p, paths):
            violations.append(f"{p}: outside the assigned class {cls.get('class')!r} paths")
            continue
        if glob.path_matches_exclude_any(p, excludes):
            violations.append(f"{p}: matches an exclude of class {cls.get('class')!r}")
            continue
    return violations


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------

def apply_changes(changes: list[Change], checkout: Path, run_fn=subprocess.run) -> list[str]:
    checkout = Path(checkout)
    staged: list[str] = []
    for ch in changes:
        if ch.kind == "deleted":
            run_fn(["git", "-C", str(checkout), "rm", "-q", "--", ch.path], check=True)
        else:
            assert ch.source is not None
            dst = checkout / ch.path
            dst.parent.mkdir(parents=True, exist_ok=True)
            # Bytes only; the mode is never inherited from the shadow. A
            # modified file keeps the mode it already had in the checkout,
            # an added file gets plain 0644 (no executable bit).
            keep_mode = dst.stat().st_mode & 0o777 if dst.exists() else None
            shutil.copyfile(ch.source, dst)
            os.chmod(dst, keep_mode if keep_mode is not None else 0o644)
            run_fn(["git", "-C", str(checkout), "add", "--", ch.path], check=True)
        staged.append(ch.path)
    return staged


NOTHING_TO_DO = "nothing to do"


def improver_declared_nothing_to_do(run_log: Path) -> bool:
    """True only when the improver's final result text contains the literal
    `nothing to do` AND the run log holds no permission_denied event: the
    explicit, sanctioned no-op of PROMPT.md, never a swallowed failure."""
    log = Path(run_log)
    if not log.exists():
        return False
    result, denied = None, False
    with open(log, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "system" and obj.get("subtype") == "permission_denied":
                denied = True
            if obj.get("type") == "result":
                result = obj.get("result")
    return (not denied) and isinstance(result, str) and NOTHING_TO_DO in result.lower()


# ---------------------------------------------------------------------------
# diagnosis for an empty round
# ---------------------------------------------------------------------------

def diagnose_empty_round(run_log: Path) -> str:
    denials: list[str] = []
    result = None
    log = Path(run_log)
    if log.exists():
        with open(log, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "system" and obj.get("subtype") == "permission_denied":
                    denials.append(f"{obj.get('tool_name')}: {obj.get('message')}")
                if obj.get("type") == "result":
                    result = obj.get("result")
    lines = [f"improver result text: {(result or '')[:2000]}", f"permission denials: {len(denials)}"]
    lines += [f"   {d[:300]}" for d in denials]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="self_heal_apply.py")
    p.add_argument("--checkout", default=".")
    p.add_argument("--shadow", required=True)
    p.add_argument("--targets", default=str(DEFAULT_TARGETS))
    p.add_argument("--class", dest="cls", required=True)
    p.add_argument("--run-log", default="self-heal-run.jsonl")
    p.add_argument("--diagnose-only", action="store_true",
                   help="print the improver's result text and permission denials from the run log, then exit 0")
    p.add_argument("--expect-change", action="store_true",
                   help="an empty change set is always a failure (test, spike and probe rounds)")
    return p


def main(argv: list[str] | None = None, run_fn=subprocess.run) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.diagnose_only:
        print(diagnose_empty_round(Path(args.run_log)))
        return 0
    checkout = Path(args.checkout).resolve()
    shadow = Path(args.shadow).resolve()
    if not shadow.is_dir():
        print(f"self_heal_apply: shadow directory missing: {shadow}", file=sys.stderr)
        return 1
    if not (shadow / SHADOW_DIRNAME).is_dir():
        print(f"self_heal_apply: shadow has no {SHADOW_DIRNAME}/ directory", file=sys.stderr)
        return 1
    dirty = verify_clean_checkout(checkout, run_fn)
    if dirty:
        print("self_heal_apply: the real checkout is not clean; the improver must never reach it. Dirty paths:",
              file=sys.stderr)
        for d in dirty:
            print(f"   {d}", file=sys.stderr)
        return 1
    cls = load_class(Path(args.targets), args.cls)
    targets = json.loads(Path(args.targets).read_text(encoding="utf-8"))
    tracked = list_checkout_tracked(checkout, run_fn)
    changes = diff_paths(list_shadow_paths(shadow), tracked, shadow, checkout)
    if not changes:
        # Three terminal states, never a quiet green: a real change (below),
        # the improver's explicit `nothing to do` with no denial in the log
        # (exit 0, printed as a notice), or a failure with the diagnosis.
        if not args.expect_change and improver_declared_nothing_to_do(Path(args.run_log)):
            print("::notice::improver declared nothing to do; no denial in the run log; no branch or PR")
            print(f"self_heal_apply: {NOTHING_TO_DO}")
            return 0
        print("::error::assigned round produced no change in the shadow workspace")
        print(diagnose_empty_round(Path(args.run_log)))
        return 1
    violations = validate_changes(changes, cls, targets, checkout, tracked)
    if violations:
        print("self_heal_apply: change set rejected, nothing copied:", file=sys.stderr)
        for v in violations:
            print(f"   {v}", file=sys.stderr)
        print("changed paths were:", file=sys.stderr)
        for ch in changes:
            print(f"   {ch.kind:8} {ch.path}", file=sys.stderr)
        return 1
    staged = apply_changes(changes, checkout, run_fn)
    print(f"self_heal_apply: {len(staged)} path(s) validated against class {args.cls!r} and staged:")
    for ch in changes:
        print(f"   {ch.kind:8} {ch.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
