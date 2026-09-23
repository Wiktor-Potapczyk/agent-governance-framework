"""Every hook must survive a payload whose JSON is valid but the wrong SHAPE.

Written 2026-09-11, check-before-fix per the declarative-first rule: this file was
authored while 36 of 67 hooks still failed it.

What this pins, and what it does not. The harness sends a JSON OBJECT. An array is
not a shape it produces today, so nothing here claims to fix a live incident. What
it pins is the boundary property: a hook decodes untrusted stdin and must not
assume the decoded value's type. 36 hooks called `.get` straight on the result, so
a valid-JSON wrong-shape payload produced an AttributeError traceback.

Severity, measured rather than assumed: all 36 exited 1, none exited 2. Under the
hook protocol exit 2 blocks and anything else does not, so none of them could
wedge a tool call. The real cost was a traceback printed into the transcript, on a
surface whose owner has twice asked for less noise in it.

Isolation: the hooks are copied to a temp tree and run with that tree as cwd,
because these hooks write telemetry, state and aggregates. Measuring 67 of them
against the live tree would pollute the logs the vault uses as evidence.
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PYTHON = sys.executable
HOOKS = Path(__file__).resolve().parent

# Valid JSON, wrong shape. A bare array and a bare scalar both decode cleanly and
# both lack `.get`, which is the assumption under test.
MALFORMED = ["[]", '["a", "b"]', "42", '"a string"', "null"]

# A well-formed payload describing something almost every hook ignores. Used as the
# per-hook baseline, so the assertion compares the hook against itself rather than
# against an absolute exit code the fixture can influence.
WELL_FORMED = json.dumps({"session_id": "shape-test", "tool_name": "Read",
                          "tool_input": {"file_path": "x.md"},
                          "hook_event_name": "PreToolUse"})


VAULT = HOOKS.parent.parent
SETTINGS = [VAULT / ".claude" / "settings.json",
            VAULT / ".claude" / "settings.local.json"]


SCRIPT_RE = re.compile(r'[^"\s]+\.py')

# The portable wiring spells every hook path `$CLAUDE_PROJECT_DIR/.claude/...`
# (blueprint A3). Claude Code expands that at runtime; this parser has to do the
# same or the row resolves nowhere.
PROJECT_DIR_RE = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?")


def expand_command_vars(token, vault=None):
    """Substitute `$CLAUDE_PROJECT_DIR` (both spellings) with the repo root.

    Third scoping mistake, measured on a bootstrapped target: `resolved: 63` of
    72 registered commands, and `scripts/ rows: []`. The absolute form resolves
    by luck and the portable form does not, because an unexpanded token is not
    an absolute path, so the `HOOKS / p.name` fallback catches the hooks rows
    and silently drops the two that live in `.claude/scripts`. That is the same
    silent population shrink the docstring below already describes, arriving by
    a different route: the wiring changed spelling and the parser did not.
    """
    return PROJECT_DIR_RE.sub((vault or VAULT).as_posix(), token)


def registered_hooks():
    """Every hook the settings files register, as a path relative to `.claude`.

    Three scoping mistakes are baked into this docstring because all three were
    made.

    First attempt: every `*.py` in the hooks directory. Wrong, because it swept in
    support modules that never receive a payload, and `sidecar_loader.py` duly
    "failed" a test it was never in scope for.

    Second attempt: registered names, but resolved only against `.claude/hooks`.
    Also wrong, and worse, because it failed SILENTLY. Two registered hooks live
    in `.claude/scripts`, so they were dropped from the parametrize list with no
    error, and a house-wide fix that skipped them still showed green. One of the
    two, `check_forbidden_tokens.py`, had the exact defect being fixed. A filter
    that quietly shrinks its own population is the same trap as a checker that
    matches text instead of behaviour.

    Third attempt: the actual path, but read literally, so the `$CLAUDE_PROJECT_DIR`
    form the portable wiring uses resolved nowhere. See expand_command_vars above.

    So: expand the variables the harness expands, then resolve the actual path
    out of the command string, wherever it points.
    """
    out = {}
    for path in SETTINGS:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entries in (data.get("hooks") or {}).values():
            for entry in entries or []:
                for h in entry.get("hooks") or []:
                    for token in SCRIPT_RE.findall(h.get("command") or ""):
                        p = Path(expand_command_vars(token).replace("\\", "/"))
                        if not p.is_absolute():
                            p = HOOKS / p.name
                        if not p.is_file():
                            continue
                        try:
                            rel = p.resolve().relative_to(VAULT / ".claude")
                        except ValueError:
                            continue
                        out[rel.as_posix()] = p
    return dict(sorted(out.items()))


def hook_files():
    return list(registered_hooks().values())


@pytest.fixture(scope="module")
def isolated():
    """A throwaway vault whose .claude holds copies of both hook-bearing dirs.

    `scripts/` is copied as well as `hooks/`, because registered hooks live in
    both and copying only one is how two of them went untested. Mirroring the
    layout matters too: these files derive the vault root from their own
    location, so a flattened copy would point them back at the real vault.
    """
    tmp = Path(tempfile.mkdtemp(prefix="payload_shape_"))
    claude = tmp / "vault" / ".claude"
    for sub in ("hooks", "scripts"):
        src = VAULT / ".claude" / sub
        if src.is_dir():
            shutil.copytree(src, claude / sub,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    yield claude
    shutil.rmtree(tmp, ignore_errors=True)


# Empty, and kept rather than deleted. It held bash-safety-guard.py for part of
# 2026-09-11: R13 makes edits to that file owner-gated, so it was the one
# registered hook held back from the house-wide pass. It was marked xfail(strict)
# rather than skipped or silently excluded, precisely so the gap stayed counted in
# every run and would turn into a failure the moment someone fixed it without
# removing the mark. The owner gave an explicit OK the same day and the guard went
# in, so the entry is gone. The mechanism stays for the next owner-gated file.
OWNER_GATED = {}


def hook_params():
    out = []
    for rel in registered_hooks():
        reason = OWNER_GATED.get(Path(rel).name)
        marks = [pytest.mark.xfail(reason=reason, strict=True)] if reason else []
        out.append(pytest.param(rel, marks=marks, id=rel))
    return out


def test_the_population_is_not_silently_empty():
    """A population filter that shrinks to nothing must fail, not pass quietly.

    Every parametrized test above disappears if `registered_hooks()` returns an
    empty dict, and a run of zero cases reports green. That is precisely how the
    scripts-directory hooks went unnoticed, only in miniature. This pins a floor.
    """
    hooks = registered_hooks()
    assert len(hooks) >= 50, f"only {len(hooks)} registered hooks resolved"
    assert any(r.startswith("scripts/") for r in hooks), \
        "no scripts/ hook resolved; the settings-derived population lost a directory"


@pytest.mark.parametrize("hook", hook_params())
def test_hook_survives_wrong_shape_payload(hook, isolated):
    """A wrong-shape payload must behave no differently from an uninteresting one.

    The first version of this asserted exit 0 outright. That was the wrong
    property and it produced a false alarm: `scripts/staleness_check.py` exits 2
    inside this temp tree because its manifest is not there, on a well-formed
    payload just as much as on a bad one. Asserting an absolute code measured the
    fixture, not the hook.

    So the baseline is taken from a well-formed payload the hook has no reason to
    act on, and each malformed payload must match it. That is immune to whatever
    the fixture does or does not provide, and it is the property actually wanted:
    valid JSON of the wrong shape should be as unremarkable as a Read of a file
    nobody cares about. The traceback assertion is separate and absolute, because
    a stack trace in the transcript is the cost this whole change exists to remove.
    """
    target = isolated / hook
    baseline = subprocess.run([PYTHON, str(target)], input=WELL_FORMED,
                              capture_output=True, text=True, timeout=30,
                              cwd=str(target.parent))
    for payload in MALFORMED:
        proc = subprocess.run([PYTHON, str(target)], input=payload,
                              capture_output=True, text=True, timeout=30,
                              cwd=str(target.parent))
        assert "Traceback (most recent call last)" not in (proc.stderr or ""), (
            f"{hook} printed a traceback on payload {payload!r}\n"
            + (proc.stderr or "")[-400:])
        assert proc.returncode == baseline.returncode, (
            f"{hook} exited {proc.returncode} on payload {payload!r} but "
            f"{baseline.returncode} on a well-formed one\n" + (proc.stderr or "")[-400:])


def test_the_harness_shape_still_works(isolated):
    """Guard against a fix that swallows the REAL payload along with the bad one.

    A hook could pass every case above by returning early on everything. This runs
    a well-formed object through the same path; it asserts only that nothing
    crashes, since each hook's actual decision is its own suite's business.
    """
    good = json.dumps({"session_id": "shape-test", "tool_name": "Read",
                       "tool_input": {"file_path": "x.md"}, "hook_event_name": "PreToolUse"})
    failures = []
    for rel in registered_hooks():
        target = isolated / rel
        proc = subprocess.run([PYTHON, str(target)], input=good,
                              capture_output=True, text=True, timeout=30,
                              cwd=str(target.parent))
        if proc.returncode not in (0, 2):
            failures.append(f"{rel} exited {proc.returncode}")
    assert not failures, "well-formed payload broke: " + "; ".join(failures)
