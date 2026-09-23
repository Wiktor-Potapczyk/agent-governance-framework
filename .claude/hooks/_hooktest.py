"""Run a hook in isolation so its suite never writes to a live sink.

Why this exists (2026-09-10). Working the untested-guard backlog surfaced a
systemic reason those guards had no suites: most hooks write to sinks derived
from their OWN location (a sibling .log, _state/<name>.json) or to a hardcoded
absolute path. A subprocess test of such a hook appends to real vault state,
so nobody wrote one. The hooks that DO have suites are, with few exceptions,
the ones whose sinks already honoured an env override.

The trick here is cheap and needs no change to the hook: copy it, plus the
shared `_`-prefixed modules it imports, into a temp directory and run it there.
Everything the hook derives from `__file__` then lands in the temp tree.

This preserves mutation-testability, which matters more than convenience. The
disarm probe replaces a guard with a no-op stub inside its own temp copy of the
hooks directory; a suite using this helper resolves the hook relative to its own
`__file__`, so under the probe it copies the STUB and the tests still fail. A
helper that reached back to the real hooks directory instead would quietly make
every suite built on it blind.

Named with a leading underscore so the disarm probe skips it: it is a support
module, not a guard.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent


def isolate(hook_name, tmp_path):
    """Copy `hook_name` plus the shared _ modules into tmp_path. Returns the
    path of the copied hook.

    The copy lands at tmp/vault/.claude/hooks/ rather than tmp/hooks/ so that
    the PRODUCTION directory depth is preserved. Several hooks derive the vault
    root as hook_dir/../.. and read registry.json or similar from it; a flatter
    layout sends them somewhere arbitrary above the temp tree, which is worse
    than a wrong answer because it can reach real files.
    """
    dest = tmp_path / "vault" / ".claude" / "hooks"
    dest.mkdir(parents=True, exist_ok=True)
    src = HOOKS_DIR / hook_name
    shutil.copy2(src, dest / hook_name)
    for helper in HOOKS_DIR.glob("_*.py"):
        if helper.name == "_hooktest.py":
            continue
        shutil.copy2(helper, dest / helper.name)
    return dest / hook_name


def run_isolated(hook_name, payload, tmp_path, extra_env=None):
    """Run a hook from an isolated copy. `payload` may be a dict or raw text.

    Returns (CompletedProcess, hooks_dir) so a caller can assert on sinks the
    hook wrote beside itself.
    """
    hook = isolate(hook_name, tmp_path)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["HOOK_ACTIVITY_LOG_PATH"] = str(hook.parent / "hook-activity.jsonl")
    env["GOVERNANCE_LOG_PATH"] = str(hook.parent / "governance-log.jsonl")
    env.update(extra_env or {})
    proc = subprocess.run([sys.executable, str(hook)], input=raw,
                          capture_output=True, text=True, timeout=60, env=env)
    return proc, hook.parent


def read_jsonl(path):
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()]


class _MissingAttr:
    """Stand-in for a hook attribute that is not there.

    Binding hook attributes into test-module globals at import time means a
    disarmed or renamed hook kills COLLECTION: pytest reports an error, zero
    assertions run, and the disarm probe cannot tell a protected guard from an
    unprotected one. Binding through `bind()` defers the failure to the point
    of USE, where it surfaces as a failing test instead.

    Every access raises. A plain default like {} or None would be worse than
    the crash it replaces: an assertion such as `x not in ALIASES` would PASS
    against an empty dict and quietly certify a guard that is not there.
    """
    __test__ = False

    def __init__(self, name):
        self._name = name

    def _boom(self, *_a, **_k):
        raise AssertionError(
            self._name + " is missing from the hook under test: this suite "
            "binds an attribute the module does not define")

    __getattr__ = __getitem__ = __call__ = __iter__ = _boom
    __len__ = __contains__ = __eq__ = __bool__ = _boom

    def __repr__(self):
        return "<missing " + self._name + ">"


def bind(module, name):
    """Return module.name, or a sentinel that fails loudly the moment it is used."""
    return getattr(module, name, _MissingAttr(getattr(module, "__name__", "?") + "." + name))
