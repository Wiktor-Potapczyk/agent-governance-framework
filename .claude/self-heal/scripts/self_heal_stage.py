"""self_heal_stage.py: the improver workflow's staging guard.

One mode, used by .github/workflows/vault-self-heal.yml's commit step
right after self_heal_apply.py has staged the validated change set:

  verify     read `git diff --cached --name-only` and exit 1 if any staged
             path matches a forbidden pattern or fails the loop's path
             hygiene (self_heal_path_hygiene.py). Defense in depth behind
             the apply step, with the loop's strict matcher from
             self_heal_glob.py. (The former `pathspec` mode fed the old
             `git add --all -- <exclusions>` staging, retired by the
             write-path build of 2026-09-18.)

The forbidden list is the same one self_heal_accept.py enforces at accept
time (phase (b)); this guard applies it at commit time inside the improver
round, so a forbidden edit never even reaches a PR. Origin: phase (c)
architect review, HIGH 1 (the hand-written exclusions covered two of the
thirteen forbidden paths).

Python 3.14, standard library plus self_heal_glob.py beside this file.
"""
from __future__ import annotations

import argparse
import functools
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_TARGETS = HERE.parent / "targets.json"
RUN_LOG = "self-heal-run.jsonl"


def _load_sibling(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _glob():
    return _load_sibling("self_heal_glob")


def forbidden_patterns(targets_path: Path) -> list[str]:
    data = json.loads(Path(targets_path).read_text(encoding="utf-8"))
    patterns = data.get("forbidden_paths")
    if not isinstance(patterns, list) or not patterns:
        raise SystemExit("self_heal_stage: targets.json has no forbidden_paths list")
    return [str(p) for p in patterns] + [RUN_LOG]


@functools.cache
def _hygiene():
    return _load_sibling("self_heal_path_hygiene")


def _hygiene_violation(path: str) -> bool:
    """True when the hard tier of the loop's one path hygiene check refuses
    `path` (self_heal_path_hygiene.py). Same tier as the apply step."""
    return bool(_hygiene().hard_reasons(path))


def forbidden_staged(staged: list[str], targets_path: Path = DEFAULT_TARGETS) -> list[str]:
    glob = _glob()
    patterns = forbidden_patterns(targets_path)
    bad = []
    for path in staged:
        if _hygiene_violation(path) or glob.path_matches_any(path, patterns):
            bad.append(path)
    return bad


def _staged_paths() -> list[str]:
    proc = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"],
                          capture_output=True, check=True)
    return [p for p in proc.stdout.decode("utf-8", "surrogateescape").split("\0") if p]


def main(argv: list[str] | None = None, staged_fn=_staged_paths) -> int:
    parser = argparse.ArgumentParser(prog="self_heal_stage.py")
    parser.add_argument("mode", choices=["verify"])
    parser.add_argument("--targets", default=str(DEFAULT_TARGETS))
    args = parser.parse_args(argv)
    targets = Path(args.targets)
    bad = forbidden_staged(staged_fn(), targets)
    if bad:
        print("self_heal_stage: forbidden path(s) staged, refusing to commit:", file=sys.stderr)
        for p in bad:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("self_heal_stage: staged paths verified against targets.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
