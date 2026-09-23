"""Every registered control must actually fire.

WHY THIS EXISTS
---------------
The 2026-08-23 harness audit read all 614 files and confirmed 296 findings. The
nine high-severity ones were not logic errors. Every one was a control that
reported success it had not earned:

  - bash-safety-guard.py denied `rm -rf /` and allowed `bash -c "rm -rf /"`
  - reviewer-scope-violation-check.py was registered and enforced nothing
  - work-verification-check.py silently stopped firing on any turn using a tool
  - wiki-citation-check.py was documented as blocking and had blocked 0 of 186
  - mcp-circuit-breaker.py was disabled machine-wide by an environment variable

Each was invisible for months for the same reason: nothing ever asked a control
to prove it still fires. The hook suite tested the FUNCTIONS inside these files
and was green throughout.

So this suite asks one question of every registered hook: given an input that
MUST trip you, do you trip? And given one that must not, do you stay quiet?

THE COVERAGE GATE IS THE POINT
------------------------------
The denominator is not a list in this file. It is recomputed from the live
settings files on every run by `.claude/scripts/enumerate_controls.py`, and a
registered control with no probe FAILS. It can only be waived in writing, with
a reason.

WHAT AN ARCHITECT REVIEW FOUND IN THE FIRST VERSION OF THIS FILE
----------------------------------------------------------------
The first draft reproduced, in the meta-suite, three instances of the very
failure class it was built to catch. All three are fixed here and each fix has
its own test, because a guarantee with no test is the thing this file exists to
argue against:

  1. ZERO-DENOMINATOR COLLAPSE. `uncovered = registered - probed - waived` is
     trivially empty when `registered` is empty, so an enumerator returning
     nothing made the gate pass while verifying nothing. Now: the enumerator
     exits non-zero on an empty result, this suite checks that exit code, and a
     high-water mark file catches a denominator that silently SHRINKS.

  2. STRUCTURALLY INVISIBLE HOOKS. The enumerator matched only `.py`, so
     `session-start.sh`, `restore-compact.sh` and `ralph-stop-hook.ps1` were
     dropped from the denominator entirely. One is a Stop hook. A hook that
     cannot appear in the denominator can never fail the gate.

  3. CRASH READ AS A DECISION. Exit code 2 was classified `block` and any
     non-empty stderr was classified `warn`, both of which counted as "the
     control fired". A hook that threw on every input therefore passed both
     gates. Now there is an explicit `errored` bucket, a traceback in stderr is
     never a trip signal, and probes must state an expected signal rather than
     accepting any.

ISOLATION, AND WHAT IT DOES NOT COVER
-------------------------------------
Exercising a control must not write to live telemetry. This suite redirects
every sink that supports an env override. Several registered hooks hardcode
their aggregate paths with no override at all (`wiki-citation-check.py`,
`inbox-auto-ingest.py`, `unicode-hygiene-check.py`, `plain-language-guard.py`,
and the `agent-dispatch-check.py` gate log). Probing those WILL append to live
aggregates. They are listed in UNISOLATED_SINKS below and a probe for one of
them must carry `"accepts_live_write": true`, so the exposure is declared in
the manifest rather than discovered afterwards.
"""

import copy
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_DIR = Path(__file__).resolve().parent
VAULT = HOOK_DIR.parent.parent
ENUMERATOR = VAULT / ".claude" / "scripts" / "enumerate_controls.py"
REGISTERED = HOOK_DIR / "aggregates" / "registered-controls.json"
PROBES = HOOK_DIR / "control-probes.json"
HIGH_WATER = HOOK_DIR / "aggregates" / "controls-high-water.json"
WAIVER_REPORT = HOOK_DIR / "aggregates" / "control-waivers.txt"
PYTHON = sys.executable or r"C:\Program Files\Python314\python.exe"

# A crash is never one of these. That is the whole point of the errored bucket.
TRIP_SIGNALS = ("deny", "block", "warn")

TRACEBACK_MARKER = "Traceback (most recent call last)"

# Hooks that hardcode an aggregate path with no env override. Probing one of
# these appends to a live file. Documented rather than silently tolerated.
UNISOLATED_SINKS = {
    "wiki-citation-check.py": "aggregates/wiki-citation-violations.jsonl",
    "inbox-auto-ingest.py": "aggregates/inbox-ingest-triggers.jsonl",
    "unicode-hygiene-check.py": "aggregates/ (AGG_LOG_PATH constant)",
    "plain-language-guard.py": "aggregates/ (AGG_LOG_PATH constant)",
    "agent-dispatch-check.py": "governance-log.jsonl (GATE_LOG_PATH constant)",
}


_ENUM_CACHE = {}


def _run_enumerator():
    """Recompute the denominator, and refuse to proceed if that failed.

    The first version discarded this return code, so a crashed enumerator left
    the previous run's file in place and the gate ran on stale data with no
    indication anything had gone wrong."""
    if "reg" in _ENUM_CACHE:
        return _ENUM_CACHE["reg"]
    p = subprocess.run([PYTHON, str(ENUMERATOR)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(VAULT), timeout=120)
    assert p.returncode == 0, (
        "the control enumerator failed, so the denominator cannot be trusted and "
        "every coverage result below would be meaningless:\n"
        f"  exit={p.returncode}\n  stdout={p.stdout[-800:]}\n  stderr={p.stderr[-800:]}")
    _ENUM_CACHE["reg"] = json.loads(REGISTERED.read_text(encoding="utf-8"))
    return _ENUM_CACHE["reg"]


# --------------------------------------------------------------------------
# REHOMING: the manifest was authored on one laptop and records its absolute
# paths (83 occurrences of that username, including the memory folder path
# carrying that machine's project key). That was harmless while every guard
# also hard-coded the same literals. It stopped being harmless when the guards
# started deriving their own paths from the running vault root and home:
# memory-context-guard.py's trip probe then pointed at a folder that is not
# the guard's memory folder on any other checkout, so the control read
# 'silent' where the probe expected 'warn'. Measured on a bootstrapped target.
#
# The fix belongs here, in the loader, not in the manifest and not in the
# guards. The manifest is a record of inputs that were observed to trip real
# controls on a real machine; rewriting it would throw that provenance away,
# and every new probe would reintroduce the problem. Rehoming at load time
# makes the probe mean the same thing on every checkout.
# --------------------------------------------------------------------------

AUTHORED_VAULT = r"C:\Users\WiktorPotapczyk\Desktop\Vault"
AUTHORED_HOME = r"C:\Users\WiktorPotapczyk"
AUTHORED_PROJECT_KEY = "C--Users-WiktorPotapczyk-Desktop-Vault"
# Windows keeps an 8.3 alias for a long profile name, and it appears in real
# settings text. It resolves to the same directory, so it maps to the same
# replacement rather than to a short form of the target.
_AUTHORED_USER = "WiktorPotapczyk"
_AUTHORED_SHORT_USER = "WIKTOR~1"


def _spellings(win_path):
    """Every spelling of one Windows path that shows up in hook payloads.

    Backslash, forward slash, and the two MSYS forms Git Bash produces
    (/c/... from a command line, //c/... from a doubled-slash rewrite). A path
    with no drive letter yields the first two only.
    """
    win = str(win_path).replace("/", chr(92)).rstrip(chr(92))
    fwd = win.replace(chr(92), "/")
    out = [win, fwd]
    m = re.match(r"^([A-Za-z]):(/.*)$", fwd)
    if m:
        tail = m.group(1).lower() + m.group(2)
        out.append("//" + tail)
        out.append("/" + tail)
    return out


def _import_compute_project_key():
    """blueprint_render.compute_project_key, or None when .claude/scripts is
    not on this checkout.

    Imported rather than retyped: that module owns the rule, and a second copy
    of a shared rule is exactly the drift two reviews have already caught in
    this repository. The import is guarded because a hooks suite that cannot
    collect is worse than a fallback, and
    test_project_key_rule_matches_blueprint_render pins the fallback to the
    real implementation whenever the module is importable.
    """
    scripts = str(VAULT / ".claude" / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import blueprint_render
    except Exception:
        return None
    return getattr(blueprint_render, "compute_project_key", None)


def _project_key(vault_path):
    fn = _import_compute_project_key()
    if fn is not None:
        return fn(vault_path)
    win = str(vault_path).replace("/", chr(92))
    return win.replace(":", "-").replace(chr(92), "-").replace(" ", "-")


def _running_home():
    """What the guards mean by home.

    memory-context-guard.py builds its default memory folder from
    os.path.expanduser("~"), which on Windows is USERPROFILE. Mirroring the
    same source is what makes the rehomed probe path land on the folder the
    guard actually checks.
    """
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


def _rehome_pairs(vault=None, home=None):
    """[(authored text, replacement)] with every identity pair dropped.

    An empty list means the running checkout IS the authoring one, which is
    why this is a no-op on the machine the manifest came from.
    """
    vault = str(vault if vault is not None else VAULT)
    home = str(home if home is not None else _running_home())
    pairs = {}
    for authored, actual in ((AUTHORED_VAULT, vault), (AUTHORED_HOME, home)):
        short = authored.replace(_AUTHORED_USER, _AUTHORED_SHORT_USER)
        for authored_form, actual_form in zip(_spellings(authored), _spellings(actual)):
            pairs[authored_form] = actual_form
        for authored_form, actual_form in zip(_spellings(short), _spellings(actual)):
            pairs.setdefault(authored_form, actual_form)
    pairs[AUTHORED_PROJECT_KEY] = _project_key(vault)
    return [(a, b) for a, b in pairs.items() if a != b]


def _rehome_text(text, pairs):
    """One ordered alternation, one pass, longest authored form first.

    Single pass is load-bearing rather than an optimisation. The authoring
    home is a PREFIX of the authoring vault root, and a scratch target can sit
    underneath the authoring home, so a sequential replace-then-replace would
    rewrite the home inside the root it had just written.
    """
    if not pairs:
        return text
    ordered = sorted(pairs, key=lambda p: -len(p[0]))
    pattern = re.compile("|".join(re.escape(a) for a, _ in ordered))
    lookup = dict(ordered)
    return pattern.sub(lambda m: lookup[m.group(0)], text)


def _rehome(node, pairs):
    """Rehome every string in the document, dict KEYS included.

    Keys matter: a probe's `fixtures` block declares the absolute path it
    wants materialised as the key, and the runner substitutes that exact
    string into the payload.
    """
    if not pairs:
        return node
    if isinstance(node, dict):
        return {_rehome(k, pairs): _rehome(v, pairs) for k, v in node.items()}
    if isinstance(node, list):
        return [_rehome(v, pairs) for v in node]
    if isinstance(node, str):
        return _rehome_text(node, pairs)
    return node


_PROBE_CACHE = {}


def _load_probes(path=None, vault=None, home=None):
    """The manifest, with every input rehomed onto the running checkout."""
    src = Path(path) if path is not None else PROBES
    explicit = path is not None or vault is not None or home is not None
    if not explicit and "doc" in _PROBE_CACHE:
        return copy.deepcopy(_PROBE_CACHE["doc"])
    if not src.exists():
        return {"probes": [], "waivers": []}
    doc = _rehome(json.loads(src.read_text(encoding="utf-8")),
                  _rehome_pairs(vault, home))
    if not explicit:
        _PROBE_CACHE["doc"] = doc
        return copy.deepcopy(doc)
    return doc


def _key(hook, event):
    return f"{event}:{hook}"


def _invoke(hook_path, stdin_obj, scratch, timeout=90, extra_env=None):
    """Run a hook the way Claude Code runs it, with every overridable sink
    pointed at scratch."""
    env = dict(os.environ)
    env.update(extra_env or {})
    env["PYTHONIOENCODING"] = "utf-8"
    for var in ("GOVERNANCE_LOG_PATH", "GATE1_ALARM_LOG_PATH"):
        env[var] = str(scratch / "governance-log.jsonl")
    env["HOOK_ACTIVITY_LOG_PATH"] = str(scratch / "hook-activity.jsonl")
    env["MEMORY_CONTEXT_GUARD_LOG_PATH"] = str(scratch / "memory-context-warnings.jsonl")
    # Audit finding HA-A-159: set machine-wide at Windows User scope, which
    # makes the MCP breaker's deny branch unreachable. Stripped so the probe
    # measures the hook rather than the machine.
    env.pop("MCP_HEALTH_FAIL_OPEN", None)
    p = subprocess.run([PYTHON, str(VAULT / hook_path)],
                       input=json.dumps(stdin_obj), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env,
                       cwd=str(VAULT), timeout=timeout)
    return p


def _write_fixture(scratch, declared_path, content):
    """Materialise a fixture the probe author declared, inside scratch.

    The runner used to ignore these declarations completely. Those probes passed
    only for as long as the files the author happened to create at authoring time
    survived on disk: two of them sit in %TEMP%, which Windows reclaims. The
    author of the read-before-edit-check probe wrote the consequence into the
    manifest himself, that a missing transcript_path makes that hook return
    silently at line 57 and read as a false PASS. So the ignored declaration was
    not cosmetic; it was the difference between a probe and a coin flip.
    """
    dest = Path(scratch) / "fixtures" / Path(str(declared_path).replace("\\", "/")).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        dest.write_text(content, encoding="utf-8")
    else:
        dest.write_text("\n".join(json.dumps(x) for x in content) + "\n", encoding="utf-8")
    return str(declared_path), str(dest)


def _substitute(stdin_obj, mapping):
    """Point the payload at the fixtures actually written, not at the absolute
    paths recorded when the probe was authored."""
    if not mapping:
        return stdin_obj
    text = json.dumps(stdin_obj)
    for declared, actual in mapping.items():
        for variant in {declared, declared.replace("/", "\\"), declared.replace("\\", "/")}:
            text = text.replace(json.dumps(variant)[1:-1], json.dumps(actual)[1:-1])
    return json.loads(text)


def _scratch_repo(scratch, spec):
    """Provision the git working tree that a repo-state-dependent hook reads.

    subagent-scope-check computes its verdict from `git status --porcelain`, not
    from its payload: with no stored baseline every dirty line counts as a new
    change. Its probe was therefore a function of whatever the vault happened to
    be doing, and went silent the moment the tree was committed clean. Giving the
    probe its own repository makes the trip condition its own input again."""
    repo = Path(scratch) / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True, timeout=60)
    if spec == "dirty" or spec.startswith("dirty-with-baseline:"):
        (repo / "probe-dirty.txt").write_text("uncommitted\n", encoding="utf-8")
    if spec.startswith("dirty-with-baseline:"):
        # Seed an EMPTY baseline for this agent_id, so the dirty file above is a
        # genuine delta rather than an artefact of there being no baseline at all.
        #
        # Needed from 2026-08-24: the hook used to treat a missing baseline as the
        # empty set, which made `current - baseline` the whole dirty tree, and this
        # probe was written to trip on exactly that. That behaviour was a bug (it
        # put 161 MB of working-tree state into the log and produced 18,967 false
        # ownership hits) and is now fixed, so the probe has to trip on the real
        # condition instead: a baseline EXISTS and the agent added files under it.
        agent_id = spec.split(":", 1)[1]
        state_dir = repo / ".claude" / "hooks" / "_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "subagent-scope-baselines.json").write_text(
            json.dumps({agent_id: {"started_at": "2026-08-24T00:00:00",
                                   "agent_type": "probe-agent",
                                   "baseline": []}}),
            encoding="utf-8")
    return repo


def _run_case(probe, case, scratch):
    """Prepare everything the probe DECLARED it needs, then invoke it."""
    extra_env = {}
    mapping = {}
    for declared, content in (probe.get("fixtures") or {}).items():
        if declared == "note":
            continue
        declared_path, actual = _write_fixture(scratch, declared, content)
        mapping[declared_path] = actual
    transcript = case.get("transcript_fixture")
    if transcript:
        declared_path, actual = _write_fixture(scratch, transcript["path"],
                                               transcript["lines"])
        mapping[declared_path] = actual
    if probe.get("scratch_repo"):
        extra_env["SUBAGENT_SCOPE_ROOT"] = str(_scratch_repo(scratch,
                                                             probe["scratch_repo"]))
    if probe.get("scratch_state"):
        # A throttled hook reads its own past decisions and then rewrites them.
        # Seeding the state in scratch makes the trip deterministic AND stops the
        # probe from stamping the live throttle, which was suppressing the next
        # real injection for 30 minutes after every suite run.
        state_dir = Path(scratch) / "hook-state"
        state_dir.mkdir(parents=True, exist_ok=True)
        for name, content in probe["scratch_state"]["files"].items():
            (state_dir / name).write_text(json.dumps(content), encoding="utf-8")
        extra_env[probe["scratch_state"]["env"]] = str(state_dir)
    timeout = probe.get("timeout", 90)
    seed = case.get("seed_stdin")
    if seed:
        # A paired probe: the first payload writes the state the second is judged
        # against. Ignoring it silently inverted one pass case into a warn.
        _invoke(probe["path"], _substitute(seed, mapping), scratch, timeout, extra_env)
    return _invoke(probe["path"], _substitute(case["stdin"], mapping), scratch,
                   timeout, extra_env)


def _classify(proc):
    """What did the control actually do?

    `errored` exists because the first version could not tell an enforcement
    decision from an unhandled exception, and therefore scored a hook that
    crashed on every input as a hook that fires."""
    out = proc.stdout or ""
    err = proc.stderr or ""
    if TRACEBACK_MARKER in err:
        return "errored"

    # Parse the structured verdict rather than substring-matching, so the word
    # "deny" inside a human-readable reason cannot be mistaken for a decision.
    verdict = None
    try:
        parsed = json.loads(out.strip()) if out.strip().startswith("{") else None
        if isinstance(parsed, dict):
            verdict = (parsed.get("permissionDecision")
                       or parsed.get("decision")
                       or (parsed.get("hookSpecificOutput") or {}).get("permissionDecision"))
    except (ValueError, AttributeError):
        verdict = None

    if verdict == "deny":
        return "deny"
    if verdict == "block":
        # This is how a Stop hook blocks: structured JSON on stdout, exit code 0.
        # Reading only the exit code recorded eight correctly-blocking hooks as
        # mere warnings, which is the measuring instrument being wrong rather
        # than the controls.
        return "block"
    if '"deny"' in out or "'deny'" in out:
        return "deny"
    if proc.returncode == 2:
        return "block"
    if proc.returncode not in (0, 2):
        return "errored"
    if (out + err).strip():
        return "warn"
    return "silent"


# --------------------------------------------------------------------------
# GATE 1: the denominator itself must be trustworthy.
# --------------------------------------------------------------------------

def test_denominator_is_not_empty():
    """A zero denominator makes every coverage assertion below vacuously true."""
    reg = _run_enumerator()
    assert reg["pairs"] > 0, (
        "enumerated zero registered controls. The coverage gate would pass while "
        "verifying nothing, which is the exact failure this suite exists to catch.")


def test_denominator_has_not_silently_shrunk():
    """Catch a control quietly disappearing from settings.

    A hook removed by accident makes the coverage gate EASIER to pass, so no
    other test in this file would notice. The high-water file is committed and
    must be lowered deliberately, in a diff someone reviews."""
    reg = _run_enumerator()
    if not HIGH_WATER.exists():
        HIGH_WATER.write_text(json.dumps({"pairs": reg["pairs"],
                                          "note": "lower this only deliberately; a drop means a "
                                                  "control left settings"}, indent=1) + "\n",
                              encoding="utf-8")
        pytest.skip(f"high-water mark initialised at {reg['pairs']}")
    hw = json.loads(HIGH_WATER.read_text(encoding="utf-8"))["pairs"]
    assert reg["pairs"] >= hw, (
        f"registered controls dropped from {hw} to {reg['pairs']}. A control left the "
        f"settings files. If that was intentional, lower the count in {HIGH_WATER.name} "
        f"in the same commit so the removal is reviewed rather than absorbed.")


def test_no_registered_command_is_unparseable():
    """A command naming no recognisable script cannot enter the denominator, so
    it would be invisible to the coverage gate exactly like the three shell and
    PowerShell hooks the first version dropped."""
    reg = _run_enumerator()
    bad = reg.get("unparsed_commands") or []
    assert not bad, (
        "registered hook command(s) name no recognisable script, so they cannot be "
        "covered:\n  " + "\n  ".join(f"{u['event']}: {u['command'][:120]}" for u in bad))


def test_every_registered_control_resolves_on_disk():
    reg = _run_enumerator()
    assert not reg["registered_but_absent"], (
        "registered in settings but missing from disk: " + ", ".join(reg["registered_but_absent"]))


# --------------------------------------------------------------------------
# GATE 2: coverage.
# --------------------------------------------------------------------------

def test_every_registered_control_has_a_probe():
    reg = _run_enumerator()
    manifest = _load_probes()
    probed = {_key(p["hook"], p["event"]) for p in manifest.get("probes", [])}
    waived = {_key(w["hook"], w["event"]): w.get("reason", "") for w in manifest.get("waivers", [])}

    # Written to a file rather than printed: pytest captures stdout on a passing
    # test, so a bare print made the waiver list invisible in exactly the case
    # where it matters, a green run.
    WAIVER_REPORT.parent.mkdir(parents=True, exist_ok=True)
    WAIVER_REPORT.write_text(
        "\n".join(f"{k}: {r or 'NO REASON GIVEN'}" for k, r in sorted(waived.items()))
        or "(no waivers)", encoding="utf-8")

    registered = {_key(c["hook"], c["event"]) for c in reg["controls"]}
    uncovered = sorted(registered - probed - set(waived))
    unreasoned = sorted(k for k, r in waived.items() if not r.strip())

    assert not unreasoned, (
        "a waiver without a written reason is indistinguishable from an oversight:\n  "
        + "\n  ".join(unreasoned))
    assert not uncovered, (
        f"{len(uncovered)} registered control(s) have no probe and no waiver. Each is a hook "
        f"that runs on every session and that nothing verifies still fires:\n  "
        + "\n  ".join(uncovered))


def test_no_probe_targets_an_unregistered_control():
    """A probe for a hook nobody registered makes the suite look more thorough
    than it is."""
    reg = _run_enumerator()
    manifest = _load_probes()
    registered = {_key(c["hook"], c["event"]) for c in reg["controls"]}
    stray = sorted({_key(p["hook"], p["event"]) for p in manifest.get("probes", [])} - registered)
    assert not stray, "probe(s) target controls that are not registered:\n  " + "\n  ".join(stray)


def test_probes_declare_their_expected_signal():
    """No probe may accept "any" signal.

    With an any-signal default, a hook that crashes on every input satisfies its
    own trip case, and the suite reports a control working when it has never once
    reached its enforcement logic."""
    vague = [_key(p["hook"], p["event"]) for p in _load_probes().get("probes", [])
             if (p.get("trip") or {}).get("expect", "any") not in TRIP_SIGNALS]
    assert not vague, (
        "probe(s) do not name the signal they expect, so a crash would satisfy them:\n  "
        + "\n  ".join(vague))


def test_no_manifest_key_is_silently_ignored():
    """The manifest is a contract, and the runner must implement all of it.

    Five keys shipped in this manifest that the runner never read: seed_stdin,
    fixtures, transcript_fixture, scratch_repo and runner_discriminator. Probe
    authors had written down exactly what their probe needed in order to mean
    anything, and the runner threw it away, so four probes were measuring
    leftover files and the state of the vault instead of their own inputs. The
    failure was invisible because ignoring setup makes a probe pass more often,
    not less.

    A key is HANDLED if some code path reads it, INFORMATIONAL if it is prose for
    a human. Anything else is a declaration nobody honours, and it fails here at
    authoring time rather than silently months later."""
    handled_probe = {"hook", "event", "path", "trip", "pass", "timeout",
                     "known_defect", "defect_note", "accepts_live_write",
                     "fixtures", "scratch_repo", "scratch_state"}
    informational_probe = {"timeout_why", "defect_fixed", "limitation"}
    handled_case = {"stdin", "expect", "must_not", "seed_stdin", "transcript_fixture"}
    informational_case = {"why", "observed", "runner_discriminator", "trip_token_note"}

    unknown = set()
    for p in _load_probes().get("probes", []):
        unknown |= set(p) - handled_probe - informational_probe
        for name in ("trip", "pass"):
            case = p.get(name)
            if isinstance(case, dict):
                unknown |= set(case) - handled_case - informational_case
    assert not unknown, (
        "manifest key(s) that no runner code path reads and that are not declared "
        "informational: " + ", ".join(sorted(unknown)) + ". Either implement the key "
        "in _run_case or add it to the informational set with a reason.")


def test_probes_touching_unisolated_sinks_declare_it():
    """Some hooks hardcode their aggregate path. Probing them appends to a live
    file. That is acceptable only if the manifest says so out loud."""
    undeclared = [_key(p["hook"], p["event"]) for p in _load_probes().get("probes", [])
                  if p["hook"] in UNISOLATED_SINKS and not p.get("accepts_live_write")]
    assert not undeclared, (
        "probe(s) target hooks that write to a live aggregate with no env override, without "
        'declaring "accepts_live_write": true:\n  '
        + "\n  ".join(f'{k} -> {UNISOLATED_SINKS[k.split(":", 1)[1]]}' for k in undeclared))


# --------------------------------------------------------------------------
# GATE 3: behaviour.
# --------------------------------------------------------------------------

def _probe_params():
    """Build the parametrised probe list, marking known-broken controls xfail(strict).

    A probe carrying `known_defect` names a control this suite has already proven
    does not fire, with the audit finding id as evidence. Strict xfail is the
    point: if the control is fixed, the test PASSES, which under strict xfail
    fails the suite until the marker is removed. A defect therefore cannot be
    silently forgotten, and neither can its fix."""
    params = []
    for p in _load_probes().get("probes", []):
        marks = []
        if p.get("known_defect"):
            marks.append(pytest.mark.xfail(
                strict=True,
                reason=f"KNOWN BROKEN CONTROL {p['known_defect']}: {p.get('defect_note', '')}"))
        params.append(pytest.param(p, id=_key(p["hook"], p["event"]), marks=marks))
    return params


def _pass_params():
    """The pass case gets NO known-defect mark.

    A control that enforces nothing also, trivially, does not false-positive, so
    its pass case correctly passes. Under strict xfail a correct pass is reported
    as a failure, which would be the suite lying in the opposite direction."""
    return [pytest.param(p, id=_key(p["hook"], p["event"]))
            for p in _load_probes().get("probes", [])]


@pytest.mark.parametrize("probe", _probe_params())
def test_control_trips_on_input_that_must_trip(probe, tmp_path):
    trip = probe["trip"]
    proc = _run_case(probe, trip, tmp_path)
    got = _classify(proc)
    expected = trip["expect"]
    assert got != "errored", (
        f"{probe['hook']} CRASHED on its trip input, so this probe proves nothing about "
        f"whether the control fires:\n  exit={proc.returncode}\n"
        f"  stderr={(proc.stderr or '')[:600]}")
    assert got == expected, (
        f"{probe['hook']} did not trip on an input designed to trip it.\n"
        f"  expected: {expected}\n  observed: {got}\n  exit={proc.returncode}\n"
        f"  stdout={(proc.stdout or '')[:400]}\n  stderr={(proc.stderr or '')[:400]}\n"
        f"  probe rationale: {trip.get('why', '(none given)')}")


# --------------------------------------------------------------------------
# GATE 4: the probe inputs must point at THIS checkout, not the authoring one.
# --------------------------------------------------------------------------

_PLANTED = {
    "hook": "memory-context-guard.py",
    "event": "PreToolUse",
    "path": ".claude/hooks/memory-context-guard.py",
    "trip": {
        "stdin": {
            "bs": r"C:\Users\WiktorPotapczyk\Desktop\Vault\CLAUDE.md",
            "fwd": "C:/Users/WiktorPotapczyk/Desktop/Vault/CLAUDE.md",
            "msys": "/c/Users/WiktorPotapczyk/Desktop/Vault/CLAUDE.md",
            "msys2": "//c/Users/WiktorPotapczyk/Desktop/Vault/CLAUDE.md",
            "short": r"C:\Users\WIKTOR~1\Desktop\Vault\CLAUDE.md",
            "home": "C:/Users/WiktorPotapczyk/AppData/Local/Temp/probe8/tr.jsonl",
            "memory": ("C:/Users/WiktorPotapczyk/.claude/projects/"
                       "C--Users-WiktorPotapczyk-Desktop-Vault/memory/x.md"),
            "untouched": "Projects/Demo/STATE.md",
        },
        "expect": "warn",
    },
    "fixtures": {"C:/Users/WiktorPotapczyk/Desktop/Vault/f.jsonl": []},
}


def test_rehoming_maps_every_spelling_of_a_planted_foreign_path():
    """The measured defect: control-probes.json carries the authoring laptop's
    literal paths, and memory-context-guard.py now derives its memory folder
    from the running vault root and home, so on any other checkout the probe
    input no longer points at the guard's own folder and the trip case reads
    'silent' instead of 'warn'."""
    target = r"D:\work\OtherVault"
    home = r"D:\users\someone"
    out = _rehome(_PLANTED, _rehome_pairs(target, home))
    stdin = out["trip"]["stdin"]

    assert stdin["bs"] == r"D:\work\OtherVault\CLAUDE.md"
    assert stdin["fwd"] == "D:/work/OtherVault/CLAUDE.md"
    assert stdin["msys"] == "/d/work/OtherVault/CLAUDE.md"
    assert stdin["msys2"] == "//d/work/OtherVault/CLAUDE.md"
    assert stdin["short"] == r"D:\work\OtherVault\CLAUDE.md"
    assert stdin["home"] == "D:/users/someone/AppData/Local/Temp/probe8/tr.jsonl"
    assert stdin["memory"] == (
        "D:/users/someone/.claude/projects/D--work-OtherVault/memory/x.md")
    assert stdin["untouched"] == "Projects/Demo/STATE.md"
    # fixtures declare absolute paths as KEYS, so keys are rehomed too.
    assert list(out["fixtures"]) == ["D:/work/OtherVault/f.jsonl"]
    # The input document is never mutated in place.
    assert _PLANTED["trip"]["stdin"]["fwd"].startswith("C:/Users/WiktorPotapczyk")


def test_rehoming_leaves_the_manifest_untouched_on_the_authoring_machine():
    """Why the live suite stays green.

    Not because the pair list is empty: the 8.3 alias still normalises to the
    long form here, which is a real improvement rather than a no-op. It is
    green because the shipped manifest contains no 8.3 form, so loading it on
    this laptop reproduces the file exactly.
    """
    pairs = _rehome_pairs(AUTHORED_VAULT, AUTHORED_HOME)
    assert all(a.replace(_AUTHORED_SHORT_USER, _AUTHORED_USER) == b for a, b in pairs), (
        "a non-identity pair on the authoring machine that is not the 8.3 alias: "
        + str([(a, b) for a, b in pairs
               if a.replace(_AUTHORED_SHORT_USER, _AUTHORED_USER) != b]))

    raw = json.loads(PROBES.read_text(encoding="utf-8"))
    assert _rehome(raw, pairs) == raw

    planted = _rehome(_PLANTED, pairs)
    assert planted["trip"]["stdin"]["fwd"] == _PLANTED["trip"]["stdin"]["fwd"]
    assert planted["trip"]["stdin"]["short"] == r"C:\Users\WiktorPotapczyk\Desktop\Vault\CLAUDE.md"


def test_rehoming_never_reprocesses_its_own_output():
    """The scratch target sits UNDER the authoring home
    (C:\\Users\\WiktorPotapczyk\\.claude\\jobs\\...), so a naive
    replace-vault-then-replace-home pass would rewrite the home inside the
    root it had just written. One ordered alternation, one pass."""
    target = r"C:\Users\WiktorPotapczyk\.claude\jobs\x\t1"
    home = r"C:\Users\WiktorPotapczyk\.claude\jobs\x\h1"
    out = _rehome(_PLANTED, _rehome_pairs(target, home))

    assert out["trip"]["stdin"]["fwd"] == (
        "C:/Users/WiktorPotapczyk/.claude/jobs/x/t1/CLAUDE.md")
    assert out["trip"]["stdin"]["home"] == (
        "C:/Users/WiktorPotapczyk/.claude/jobs/x/h1/AppData/Local/Temp/probe8/tr.jsonl")


def test_project_key_rule_matches_blueprint_render():
    """The key rule lives in blueprint_render; this file imports it and falls
    back to a re-derivation only when .claude/scripts is absent. The fallback
    cannot drift unnoticed, because this test pins the two together whenever
    the module is importable."""
    fn = _import_compute_project_key()
    if fn is None:
        pytest.skip("blueprint_render not importable on this checkout")
    for path in (AUTHORED_VAULT, r"D:\work\OtherVault",
                 r"C:\Users\Foo Bar\Desktop\Vault", "C:/Users/Foo Bar/Desktop/Vault"):
        assert _project_key(path) == fn(path), path
    assert _project_key(AUTHORED_VAULT) == "C--Users-WiktorPotapczyk-Desktop-Vault"


def test_loaded_probes_carry_no_authoring_machine_path():
    """The gate that would have caught this, and it runs on every machine.

    Checking the live load would be vacuous on the laptop that authored the
    manifest, since there the authoring paths ARE the right ones. So the real
    manifest is loaded rehomed onto a synthetic foreign checkout, and no
    authoring spelling may survive. A probe added later with a fresh hard-coded
    path fails here rather than silently going silent on a target.
    """
    offenders = []

    def walk(node, trail):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(k, trail)
                walk(v, f"{trail}.{k}")
        elif isinstance(node, list):
            for v in node:
                walk(v, trail)
        elif isinstance(node, str):
            for spelling in _spellings(AUTHORED_VAULT) + _spellings(AUTHORED_HOME):
                if spelling in node:
                    offenders.append(f"{trail}: {node[:120]}")
                    return

    walk(_load_probes(vault=r"D:\work\OtherVault", home=r"D:\users\someone"), "probes")
    assert not offenders, (
        f"{len(offenders)} probe input(s) still name the authoring machine after "
        "rehoming; add the spelling to _spellings() or stop hard-coding it:\n  "
        + "\n  ".join(sorted(set(offenders))[:20]))


@pytest.mark.parametrize("probe", _pass_params())
def test_control_stays_quiet_on_input_that_must_pass(probe, tmp_path):
    """A control that fires on everything is as useless as one that never fires,
    and is the likelier outcome of a careless fix to one that never fires."""
    ok_case = probe.get("pass")
    if not ok_case:
        pytest.skip("no pass-case defined")
    proc = _run_case(probe, ok_case, tmp_path)
    got = _classify(proc)
    forbidden = set(ok_case.get("must_not", ["deny", "block"])) | {"errored"}
    assert got not in forbidden, (
        f"{probe['hook']} fired or crashed on benign input:\n"
        f"  observed: {got}\n  exit={proc.returncode}\n"
        f"  stdout={(proc.stdout or '')[:400]}\n  stderr={(proc.stderr or '')[:400]}\n"
        f"  probe rationale: {ok_case.get('why', '(none given)')}")
