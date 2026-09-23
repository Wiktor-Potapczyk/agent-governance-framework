#!/usr/bin/env python3
"""Ask of every guard: would its own tests notice if it stopped working?

Motivation (2026-09-09). Three checks were found in one session that were
silently verifying nothing: a QA harness whose exact-match rule matched no real
input, a test mirroring its subject's logic instead of importing it, and a
memory-index checker whose regex stopped matching after a convention change.
All three were GREEN the whole time. A green check nobody can distinguish from
a disarmed one is the thing that breaks a reliability claim, because it removes
the signal you would have used to notice.

Static scanning cannot answer this. Guards signal in incompatible ways (exit
code, a printed JSON line, additionalContext, a written sink), so any single
pattern produces false positives in both directions. Mutation is the only
verdict that holds.

THE MUTATION, and why this one: each guard is replaced by a NO-OP that reads
stdin, prints nothing and exits 0, which is the shape of a completely disarmed
hook. Then its suite runs against that stub. This is deliberately crude rather
than clever: a subtle mutation tests whether the suite catches THAT change,
while the no-op tests the property actually worth knowing, namely whether the
suite can detect the guard not working at all. If a suite passes against a
guard that does nothing, it cannot protect that guard, whatever else it checks.

Verdicts:
  BLIND     suite passed against a no-op. The finding. Its guard could be
            disarmed and every signal would stay green.
  DETECTED  suite failed on an assertion: it noticed the behaviour vanish.
  ERRORED   the suite never got as far as running its assertions (collection
            error, interrupt, usage error, timeout). Weaker than DETECTED: it
            noticed something, but by breaking rather than by asserting, so it
            is reported separately instead of counted as protection. Decided
            from pytest's exit code, NOT from keywords in its output; see
            _classify_failure for the false positive that taught us why.
  NO_TESTS  no suite exists for this guard at all.

Nothing live is touched: guard and suite are copied to a temp tree and the copy
is mutated. Read-only with respect to the vault.

Exit: 0 no BLIND guards, 1 at least one BLIND, 2 harness failure.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
HOOKS = VAULT / ".claude" / "hooks"
STAMP = VAULT / ".claude" / "hooks" / "_state" / "disarm-cadence.json"
PYTHON = sys.executable

# The stub must be IMPORTABLE, not just runnable. The first version called
# sys.exit(0) at module level, which is fine for a suite that runs the hook as
# a subprocess but fatal for one that imports it: the import raises SystemExit
# during pytest collection and pytest aborts with INTERNALERROR, exit code 3.
#
# That mattered far more than it sounds. The original classifier decided
# ERRORED by grepping output for crash keywords, and an INTERNALERROR traceback
# contains none of them, so every import-binding suite was scored DETECTED
# while never running a single test. The 2026-09-10 morning baseline of
# "48 detected, 1 blind" was inflated by exactly that. Guarding the exit under
# __main__ makes the stub disarmed when RUN and harmless when IMPORTED, so an
# import-binding suite now reports honestly (as ERRORED: it notices the guard
# is gone, but by failing to find its functions rather than by asserting).
NOOP_STUB = '''"""Disarmed stub planted by disarm_probe.py. Reads stdin, does nothing."""
import sys

if __name__ == "__main__":
    try:
        sys.stdin.read()
    except Exception:
        pass
    sys.exit(0)
'''


def guard_pairs(hooks_dir):
    """(guard, test) pairs. A guard is a hook .py with a sibling test_*.py."""
    pairs = []
    for guard in sorted(hooks_dir.glob("*.py")):
        if guard.name.startswith(("test_", "_")):
            continue
        stem = guard.stem.replace("-", "_")
        test = hooks_dir / f"test_{stem}.py"
        pairs.append((guard, test if test.exists() else None))
    return pairs


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def _classify_failure(returncode, out):
    """Split "noticed by asserting" from "fell over", using pytest's own exit
    codes rather than keywords in its output.

    The first version grepped the combined output for ImportError,
    AttributeError and friends. That was wrong in a way worth recording,
    because it is the same mistake this whole tool exists to find: it matched
    on text rather than on behaviour. On 2026-09-10 a suite that legitimately
    ASSERTS a hook raises AttributeError was reported ERRORED, because the
    failing assertion printed the word AttributeError. A checker that cannot
    tell a test's subject from a test's outcome is not measuring what it says.

    pytest exit codes: 1 tests failed, 2 interrupted, 3 internal error,
    4 usage error, 5 nothing collected. Only code 1 means the suite ran and
    its assertions caught the change; anything higher means it never got that
    far, which is a weaker signal and is reported separately.
    """
    if returncode != 1:
        return "ERRORED"
    # Within code 1, pytest still distinguishes failures from collection-time
    # errors in its summary line ("2 failed" vs "1 error").
    #
    # Third correction, 2026-09-11, same family as the first two. A run
    # summarised "25 failed, 8 errors" was scored ERRORED, meaning "we could
    # not tell whether the suite noticed". It plainly did notice: 25
    # assertions fired. The errors were teardown noise from fixtures touching
    # an attribute the disarmed stub no longer has. Any failure at all means
    # assertions ran and caught the change, so failures outrank errors.
    # ERRORED is now reserved for a run with NO failures, the only case where
    # the suite genuinely never got far enough to judge.
    tail = [ln for ln in _ANSI.sub('', out).strip().splitlines() if ln.strip()]
    summary = tail[-1] if tail else ""
    failed = re.search(r'(\d+)\s+failed\b', summary)
    if failed and int(failed.group(1)) > 0:
        return "DETECTED"
    errors = re.search(r'(\d+)\s+errors?\b', summary)
    if errors and int(errors.group(1)) > 0:
        return "ERRORED"
    return "DETECTED"


def probe(guard, test, keep=False):
    """Copy hooks dir, replace `guard` with a no-op, run `test`."""
    tmp = Path(tempfile.mkdtemp(prefix="disarm_"))
    try:
        shutil.copytree(guard.parent, tmp / "hooks",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (tmp / "hooks" / guard.name).write_text(NOOP_STUB, encoding="utf-8")
        r = subprocess.run(
            [PYTHON, "-m", "pytest", str(tmp / "hooks" / test.name), "-q",
             "--no-header", "-p", "no:cacheprovider"],
            capture_output=True, text=True, timeout=300, cwd=str(tmp / "hooks"))
        out = (r.stdout or "") + (r.stderr or "")
        if r.returncode == 0:
            return "BLIND", out
        return _classify_failure(r.returncode, out), out
    except subprocess.TimeoutExpired:
        return "ERRORED", "timeout"
    finally:
        if not keep:
            shutil.rmtree(tmp, ignore_errors=True)


def write_stamp(path, blind, detected, errored, untested, partial):
    """Record the run so the SessionStart cadence builder can nag with NAMES.

    A reminder that only says "a check is due" gets ignored; one that says
    which guards are currently unprotected is actionable. That is the whole
    reason this stamp carries name lists and not just counts.

    A PARTIAL run (--only / --limit) is stamped as partial and never resets
    the cadence clock. Otherwise probing one guard would mark the whole
    sweep as done, which is the disarmed-check failure mode again, one layer up.
    """
    payload = {
        "last_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "partial": bool(partial),
        "counts": {"blind": len(blind), "detected": len(detected),
                   "errored": len(errored), "no_tests": len(untested)},
        "blind": blind,
        "errored": errored,
        "no_tests": untested,
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2)
    except OSError as exc:
        # Loud, not silent: a stamp that failed to write means the cadence
        # believes the sweep never ran, and the operator should know why.
        print(f"STAMP FAILED: {exc}")
        return False
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--hooks", default=str(HOOKS))
    ap.add_argument("--only", default="", help="substring filter on guard name")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stamp", action="store_true",
                    help="write _state/disarm-cadence.json for the SessionStart nag")
    ap.add_argument("--stamp-path", default=str(STAMP))
    args = ap.parse_args(argv)

    pairs = guard_pairs(Path(args.hooks))
    if args.only:
        pairs = [(g, t) for g, t in pairs if args.only in g.name]
    if args.limit:
        pairs = pairs[:args.limit]
    if not pairs:
        print("HARNESS FAILURE: no guards found")
        return 2

    blind, detected, errored, untested = [], [], [], []
    for guard, test in pairs:
        if test is None:
            untested.append(guard.name)
            print(f"NO_TESTS   {guard.name}")
            continue
        verdict, _ = probe(guard, test)
        print(f"{verdict:<10} {guard.name}")
        {"BLIND": blind, "DETECTED": detected,
         "ERRORED": errored}[verdict].append(guard.name)

    print()
    print(f"DISARM_PROBE guards={len(pairs)} blind={len(blind)} "
          f"detected={len(detected)} errored={len(errored)} "
          f"no_tests={len(untested)}")
    for name in blind:
        print(f"BLIND_GUARD  {name}  (its suite passes against a no-op)")

    if args.stamp:
        partial = bool(args.only or args.limit)
        if not write_stamp(args.stamp_path, blind, detected, errored,
                           untested, partial):
            return 2
        print(f"STAMPED {args.stamp_path}" + (" (partial)" if partial else ""))
    return 1 if blind else 0


if __name__ == "__main__":
    sys.exit(main())
