"""Blueprint A4: the first-slice runner (Implementation Phase A4).

Spec of record: Projects/Vault-Maintenance/work/2026-09-22-blueprint-implementation-plan.md
section "Implementation Phase A4: Runner, first slice". Plan of record:
Projects/Vault-Maintenance/work/2026-09-22-harness-migration-blueprint-plan.md
(A4 row, architect review finding 5: the first slice that counts as A4 done
is clone, scaffold, wiring, templates and --check; plugins, tasks and the
mirror restore are later slices, printed as NOT-IN-SLICE-1).

Ported flow (not payload) from cc-config's setup.sh / setup_helpers.py:
compute the Claude Code project key from the vault path, render templates,
place files, verify. The project key itself comes from
blueprint_render.compute_values, the single implementation of that rule
(architect review 8: the runner's own copy disagreed with it on posix input,
so the copy is deleted rather than repaired).

Two profiles, bare by default (B3, B4). Owner ask, verbatim: "FRESH DEVICE
NEEDS JUST THE HARNESS AND BARE VAULT, NOTHING [EMPLOYER] SPECIFIC."
  --profile bare  the harness mechanism plus an empty vault skeleton. Clones
                  the manifest's bare pattern set (no work bucket, no
                  Resources/KB), places a scrubbed CLAUDE.md at the target
                  root, renders templates that name no employer, no client,
                  no instance. Needs no --secrets-dir and no --values-extra:
                  its templates carry no {{secret:...}} and no {{value:...}}.
  --profile full  this workstation reproduced, the previous behaviour,
                  including the five owed secret files and the five owed
                  values.

Four modes, mutually exclusive:
  --dry-run    read --manifest, report its pattern and bucket counts, run the
               read-only preflight against --target/--home/--secrets-dir and
               print the step plan as a table. Writes nothing, anywhere.
  --apply      run every slice-1 step in order against --target/--home.
               Idempotent: rerunning an already-completed step reports
               SKIP rather than redoing or failing.
  --check      run the check-family substeps against --target and --home.
               Exit 0 clean, exit 2 on any failing substep.
  --acceptance --check plus a live probe of the placed wiring. Exit 0 only
               when every substep AND the probe passed. A missing claude CLI
               is a FAIL, never a pass; --no-probe records SKIPPED-BY-FLAG
               and still exits 1, because a probe that did not run cannot
               establish acceptance.

Safety (CON-006, plan risk flag): every filesystem target is injectable
through --target and --home; this module never calls Path.home() or reads
a real secrets/ directory. --secrets-dir must be given and non-empty for
--apply; a non-empty --home/.claude is refused unless --home-may-exist.
--home is required for --apply, --check and --acceptance alike, because
three of the five placed files live under it (adversarial review 5).

Credential handling (architect review 1): --apply renders into a
tempfile.mkdtemp outside the checkout and deletes it in a finally, and
writes bootstrap-values.json under --home/.claude/blueprint/. Nothing the
runner produces lands in the target's tracked tree, so the target's own
30-minute autosave has nothing of ours to commit. .gitignore carries
.claude/blueprint/rendered/ and .claude/blueprint/bootstrap-values.json as
a second, weaker layer: an ignore rule protects one repository, a temp
directory protects every clone.

Values for the {{value:<key>}} placeholders A2's templates carry (mcp.json
env values that are neither a machine path nor a secret) come from three
sources, in order: compute_bootstrap_values (project_key/vault/home/npm/
python), _computed_value_defaults (the memory server file under --target's
own .claude, qmd's config and cache dirs under --home), then --values-extra
(a per-machine JSON of {key: value} the owner or the session writes),
which wins on conflict. Any templates_dir/_values-needed.json key still
absent after that merge is reported unresolved in the [values] apply line,
before render_templates would otherwise raise UnresolvedPlaceholderError.

Slice-1 steps and NOT-IN-SLICE-1 items are named constants below
(SLICE_1_STEPS, NOT_IN_SLICE_1) so --dry-run's table and this docstring
cannot drift apart silently.

No em dash or en dash appears in this file's output (CON-007).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import blueprint_render  # noqa: E402  (path insert must run first)
import blueprint_workbound as wb  # noqa: E402  (path insert must run first)

# B4: two profiles, bare by default. The owner's ask, verbatim: "FRESH DEVICE
# NEEDS JUST THE HARNESS AND BARE VAULT, NOTHING [EMPLOYER] SPECIFIC." bare clones
# the mechanism and a bare vault skeleton, places a scrubbed CLAUDE.md, owes
# no secret file and no --values-extra value. full reproduces this
# workstation and is opt-in.
PROFILES = blueprint_render.PROFILES
DEFAULT_PROFILE = blueprint_render.DEFAULT_PROFILE

# .claude/scripts/bootstrap_machine.py -> vault root, same idiom as
# o17_portability_figures.py and blueprint_manifest.py (CON-004: no new
# path-resolver module).
VAULT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = VAULT_ROOT / ".claude" / "blueprint" / "manifest.json"

# Where each rendered file lands, keyed on blueprint_render's SOURCE keys so
# the deploy names themselves are never retyped here (architect review 11:
# PLACEMENT hard-coded the five strings under a comment claiming reuse, so a
# rename in DEPLOY_NAMES would orphan a key silently).
_PLACEMENT_SPEC = {
    "settings_local": ("target", (".claude", "settings.local.json")),
    "mcp": ("target", (".mcp.json",)),
    "user_settings": ("home", (".claude", "settings.json")),
    "user_claude_md": ("home", (".claude", "CLAUDE.md")),
    "qmd_index": ("home", (".config", "qmd", "index.yml")),
    # Bare only: the four scrubbed twins. Each is staged under a distinct name
    # (the user-level CLAUDE.md already owns "CLAUDE.md" in the same staging
    # directory) and lands where the bare sparse pattern set deliberately left
    # no tracked file for it to collide with. Derived from the renderer's own
    # twin table so a twin cannot be added on one side alone.
    "vault_claude_md": ("target", ("CLAUDE.md",)),
    "vault_gitignore": ("target", (".gitignore",)),
    "control_probes": ("target", (".claude", "hooks", "control-probes.json")),
    "install_prereqs_manifest": (
        "target", (".claude", "scripts", "install-prereqs-manifest.json")
    ),
    "project_settings": ("target", (".claude", "settings.json")),
}
assert set(_PLACEMENT_SPEC) == set(blueprint_render.DEPLOY_NAMES), (
    "PLACEMENT and blueprint_render.DEPLOY_NAMES disagree on the source set: "
    f"{sorted(set(_PLACEMENT_SPEC) ^ set(blueprint_render.DEPLOY_NAMES))}"
)
PLACEMENT = {
    blueprint_render.DEPLOY_NAMES[key]: spec for key, spec in _PLACEMENT_SPEC.items()
}
assert set(PLACEMENT) == set(blueprint_render.DEPLOY_NAMES.values())

# The three files that land under --home, the ones no check substep used to
# read (adversarial review 5). Same three in both profiles.
HOME_PLACED_NAMES = tuple(
    name for name, (root, _parts) in PLACEMENT.items() if root == "home"
)


def placement_for(profile=DEFAULT_PROFILE):
    """The deploy-name to destination mapping for one profile, derived from
    blueprint_render's own source order so a profile cannot place a file its
    renderer never wrote."""
    names = {
        blueprint_render.DEPLOY_NAMES[key]
        for key in blueprint_render.source_order(profile)
    }
    return {name: spec for name, spec in PLACEMENT.items() if name in names}


def placement_dest(name, target, home, profile=DEFAULT_PROFILE):
    """Absolute destination of one rendered file on the target machine."""
    root, parts = placement_for(profile)[name]
    base = Path(target) if root == "target" else Path(home)
    return base.joinpath(*parts)


def default_templates_dir(target, profile=DEFAULT_PROFILE):
    """The profile's template directory inside the TARGET checkout."""
    return Path(target) / ".claude" / "blueprint" / "templates" / profile


def manifest_patterns(manifest, profile=DEFAULT_PROFILE):
    """The sparse patterns for one profile, read off the manifest's own
    profiles block. Falls back to the full list for a manifest written before
    profiles existed, which is honest: that manifest has no bare set."""
    block = (manifest.get("profiles") or {}).get(profile) or {}
    key = block.get("patterns_key") or (
        "sparse_patterns" if profile == "full" else "sparse_patterns_bare"
    )
    return list(manifest.get(key) or manifest.get("sparse_patterns") or [])


# The runbook's empty-skeleton dirs plus stub files, only where absent
# (plan of record, Phase A4 row). Kept as an explicit list rather than
# derived solely from the manifest so the scaffold set is legible on its
# own; _scaffold_targets below unions this with every manifest instance
# and schema unit, so a manifest change still drives the population.
SKELETON_DIRS = (
    "Inbox", "Projects", "Resources/KB", "Templates", "Archives",
    "Areas", "Clippings", "Notes",
)
STUB_FILES = ("log.md", "Home.md", "Resources/KB/index.md")

# Known file-shaped schema/instance units (never created as a directory).
KNOWN_SCAFFOLD_FILES = {
    "log.md", "CLAUDE.md", "README.md", "ARCHITECTURE.md", "CHANGELOG.md",
    "Home.md", "Rules.md", "ruff.toml", ".gitattributes", ".gitignore",
    ".mcp.json.example", ".maintain-cache.json",
}

VALUES_FILE_NAME = "bootstrap-values.json"

# Generated inventories the bare profile does not ship and this runner rebuilds
# on the target instead. Each shipped copy describes THIS machine's agents,
# skills, hooks and projects, so each names every work-bound one of them;
# regenerating on the target produces the same artifact describing the device
# it is actually on, which is the only version that is true there. The
# generator paths are read from the manifest module so the two lists cannot
# drift apart.
BARE_REGENERATED_ON_TARGET = {
    ".claude/registry.json": ".claude/scripts/generate_registry.py",
    ".claude/hooks/_known_dispatch_names.json":
        ".claude/scripts/generate_known_dispatch_names.py",
    "Home.md": ".claude/scripts/generate-home.py",
}

# The inventories whose CONTENT depends on which plugins the user has: they
# read the plugin cache under the home directory, so a run without the home
# overlay describes the source machine's plugins even when VAULT_DIR is
# right. Measured: 131 of the first bare run's work-bound hits were this.
HOME_AWARE_INVENTORIES = (
    ".claude/registry.json",
    ".claude/hooks/_known_dispatch_names.json",
)

SLICE_1_STEPS = [
    ("preflight", "verify git/python/node present, refuse on a non-empty "
                  "--home/.claude, and (full profile only) on a missing or "
                  "empty --secrets-dir"),
    ("clone", "git clone --no-checkout plus the manifest's sparse patterns into "
              "--target, repoint origin at the source's own remote, or --in-place "
              "to reuse an existing clone"),
    ("longpaths", "git config core.longpaths true on the target checkout"),
    ("scaffold", "create the empty skeleton dirs and stub files named in the "
                 "manifest's instance/schema buckets, only where absent AND only "
                 "where git does not already track the path"),
    ("values", "compute vault, home, npm prefix, python and the derived project "
               "key, merge computed defaults and --values-extra, report any "
               "_values-needed.json key still unresolved, into a values JSON "
               "under --home/.claude/blueprint/ (outside the checkout)"),
    ("render_templates", "blueprint_render.py render the profile's templates "
                         "from --target's own "
                         ".claude/blueprint/templates/<profile>/ into a "
                         "temporary directory outside the checkout"),
    ("place_hook_wiring", "place settings.local.json and .mcp.json into --target, "
                          "settings.json, CLAUDE.md and the qmd index under --home, "
                          "creating only, never overwriting a differing file"),
    ("home_wiring", "the three --home files exist, settings.json parses and carries "
                    "no unrendered placeholder"),
    ("install_prereqs_check", "install_prereqs.py --check on the target checkout, "
                              "with the home variables pointed at --home"),
    ("o17_check", "o17_portability_manifest.py check --local <placed settings.local.json>"),
    ("blueprint_manifest_check", "blueprint_manifest.py check on the target checkout"),
    ("hooks_suite", "pytest .claude/hooks -q -p no:cacheprovider on the target checkout"),
    ("hook_activity_findings", "hook_activity_report.py --findings on the target checkout"),
]

# Bare-only plan rows, appended after the shared ones.
BARE_ONLY_STEPS = [
    ("regenerate_inventories", "rebuild the generated inventories the bare profile "
                               "does not ship (the registry, the known dispatch names, "
                               "the home dashboard) from the target's own contents"),
    ("seed_coverage_ratchet", "write the shipped bare control high-water baseline onto "
                              "the target so the first check compares against it "
                              "instead of initialising it from whatever the scrub left"),
    ("workbound_scan", "scan the WHOLE target tree plus every file this run wrote for a "
                       "work-bound term or shape; any hit fails the check"),
    ("bare_idempotence", "run the target's own blueprint_render.py check --profile bare, "
                         "which is the twin drift detector nothing used to run"),
]

# name, one-line description, the command a later slice will run.
NOT_IN_SLICE_1 = [
    ("plugins", "plugin marketplace install",
     "claude plugin install <name> for each plugin the profile's "
     "user-settings template enables (Phase B step 4)"),
    ("scheduled_tasks", "Windows scheduled task replay",
     "Register-ScheduledTask -TaskName <name> -Xml (Get-Content "
     ".claude/scripts/scheduled-tasks-archive/<name>.xml -Raw) (Phase B step 5)"),
    ("mirror_restore", "user-claude-mirror skills/memory restore to the target home",
     "copy .claude/user-claude-mirror/skills/* and memory/* (flag-gated) into "
     "--home/.claude (A4 plan row, later slice)"),
    ("codegraph_index", "codegraph index build",
     "codegraph index build (named step, Phase B step 4)"),
    ("qmd_index_build", "qmd index build",
     "qmd index build (named step, Phase B step 4)"),
]

CHECK_SUBSTEPS = [
    ("home_wiring", "step_home_wiring"),
    ("install_prereqs_check", "step_install_prereqs_check"),
    ("o17_check", "step_o17_check"),
    ("blueprint_manifest_check", "step_blueprint_manifest_check"),
    ("hooks_suite", "step_hooks_suite"),
    ("hook_activity_findings", "step_hook_activity_findings"),
    ("workbound_scan", "step_workbound_scan"),
    ("bare_idempotence", "step_bare_idempotence"),
]


def check_substeps(profile=DEFAULT_PROFILE):
    """The check family for one profile. The list is the same for both:
    workbound_scan runs in either, and reports NOT-IN-PROFILE rather than a
    pass in full, where the placed files are meant to name this workstation.
    """
    return list(CHECK_SUBSTEPS)


def _profile_plugins(templates_dir):
    """The plugin names the profile's own user-settings template enables, or
    None when that template is not readable from here."""
    if templates_dir is None:
        return None
    path = Path(templates_dir) / blueprint_render.TEMPLATE_NAMES["user_settings"]
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    plugins = data.get("enabledPlugins")
    if isinstance(plugins, dict):
        return sorted(plugins)
    if isinstance(plugins, list):
        return sorted(str(p) for p in plugins)
    return None


def not_in_slice_1(profile=DEFAULT_PROFILE, templates_dir=None):
    """NOT_IN_SLICE_1 with the plugins row resolved for this profile.

    In bare the row names the generic plugins only: every plugin whose name
    carries a work-bound term (the tracker plugins, the employer's own
    marketplace, the instance skills packs) was scrubbed out of the profile's
    user-settings template, so naming it here would send the owner to install
    something the profile does not wire up.
    """
    rows = []
    for name, label, why in NOT_IN_SLICE_1:
        if name == "plugins":
            plugins = _profile_plugins(templates_dir)
            if plugins is not None:
                plugins = [p for p in plugins if wb.classify_path(p) == wb.GENERIC]
                label = f"{len(plugins)}-plugin marketplace install"
                why = (
                    "claude plugin install for each of: " + ", ".join(plugins)
                    + " (Phase B step 4)"
                )
            elif profile == "bare":
                why = (
                    "claude plugin install for each plugin the bare "
                    "user-settings template enables; every plugin naming a "
                    "work-bound term was scrubbed out of it (Phase B step 4)"
                )
        rows.append((name, label, why))
    return rows

# Data file naming the hooks-suite pytest NODE IDS whose failure on a
# mechanism-only clone is a content gap, not a defect; read from the
# TARGET's own checked-out copy (.claude/blueprint/ is a core-bucket path),
# never from this script's source vault, so a target always judges itself
# against the list it shipped with. Node ids, not filenames: keying on the
# file let any failure in a listed file pass, and that mask was measured
# hiding a real regression (adversarial review 3).
KNOWN_FAILURES_FILE = "mechanism-only-known-failures.json"
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_PYTEST_SUMMARY_LINE_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+)")

# The O17 checker reads its manifest of record out of an instance-bucket
# work/ directory. When the clone does not carry these, the checker emits a
# raw PARSE_FAILURE that reads like a defect; it is a clone-contents gap
# (adversarial review 6).
O17_ARTIFACTS = (
    "Projects/Agent-Governance-Research/work/2026-09-02-o17-portability-manifest.md",
    "Projects/Agent-Governance-Research/work/2026-09-02-o17-substitution-table.md",
    "Projects/Agent-Governance-Research/work/2026-09-02-o17-portability-build.md",
)

# install_prereqs.py rows that cannot pass before the NOT-IN-SLICE-1 plugin
# install: an mcp-server row whose probe path sits in the plugin cache
# (architect review 4, adversarial review 4).
_INSTALL_ROW_RE = re.compile(r"^(\S+)\s{2,}(PASS|FAIL)\s{2,}(.*)$")
_PLUGIN_CACHE_RE = re.compile(r"plugins[\\/]cache[\\/]")

# install_prereqs rows that a later-slice provisioning step satisfies, mapped
# to the command that satisfies them so the detail names the fix rather than
# leaving an owner to guess. file-qmd-cli was measured failing on a real apply
# because qmd.js is absent under a fresh home; that is the Phase B npm install,
# not a defect of the clone.
SLICE_2_INSTALL_ROWS = {
    "file-qmd-cli": "npm install -g @tobilu/qmd",
}
_PLUGIN_INSTALL_COMMAND = "claude plugin install (Phase B step 4)"

CLONE_TIMEOUT_S = 600

# Interpreter resolution: the same four candidates, in the same order, as
# .claude/bin/py (CON-004, architect review 7).
HARD_CODED_PYTHON = "C:/Program Files/Python314/python.exe"
MIN_PYTHON = (3, 14)


# ---------------------------------------------------------------------------
# interpreter resolution (one order, shared with .claude/bin/py and the .ps1)
# ---------------------------------------------------------------------------

def resolve_python():
    """The interpreter .claude/bin/py would exec, or None.

    Same order, same guards, as .claude/bin/py lines 25 to 39:
      1. $VAULT_PYTHON, if set, a regular file, AND executable
      2. C:/Program Files/Python314/python.exe, if it exists
      3. python3 on PATH
      4. python on PATH

    The candidate-1 pair of guards is load-bearing and was a named
    adversarial-review fix in bin/py: `[ -x PATH ]` alone is true for a
    directory, and exec-ing a directory hard-crashes the resolver instead of
    falling through, which would take every hook routed through it down with
    a single stale VAULT_PYTHON value. os.access(X_OK) is the weaker of the
    two on Windows (it is true for any existing file), so the is_file check
    is what actually carries the guard there; both are kept so the two
    implementations read the same on every platform.

    bootstrap_machine.ps1 documents and implements this same order for the
    PowerShell entry point.
    """
    vault_python = os.environ.get("VAULT_PYTHON")
    if vault_python:
        candidate = Path(vault_python)
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    if Path(HARD_CODED_PYTHON).is_file():
        return HARD_CODED_PYTHON
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    return None


def python_version_tuple(exe):
    """(major, minor) of the interpreter at `exe`, or None if it cannot be
    read. Measured, not assumed: preflight used to accept any python on PATH
    while its own refusal text promised a 3.14+ gate (adversarial 22)."""
    try:
        proc = subprocess.run(
            [str(exe), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)\.(\d+)", (proc.stdout or "") + (proc.stderr or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


@contextmanager
def _env_overlay(overrides):
    """Set env vars for the duration of a block, restoring them after.

    Mutating os.environ rather than passing an env= dict to subprocess.run is
    deliberate and measured: an explicitly rebuilt dict(os.environ), even a
    content-identical copy, changed how Windows resolved "bash" on this
    machine (it picked the WSL launcher stub over Git Bash).
    """
    saved = {}
    for key, value in (overrides or {}).items():
        saved[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


# ---------------------------------------------------------------------------
# values
# ---------------------------------------------------------------------------

def compute_bootstrap_values(target, home, python=None):
    """{project_key, vault, home, npm, python}, straight from
    blueprint_render.compute_values.

    The project key is NOT recomputed here. blueprint_render.compute_project_key
    normalises forward slashes to the Windows separator before substituting,
    so it is correct for a posix-form --target; the runner's own former copy
    omitted that step and produced "C-/Users/Foo-Bar/..." for the same input
    (architect review 8).
    """
    return blueprint_render.compute_values(vault=target, home=home, python=python)


def write_values(values, values_dir):
    """Write bootstrap-values.json into `values_dir`, which the caller keeps
    OUTSIDE the target checkout (architect review 1 and finding 18: the file
    is paths-only, no secrets, but it belongs with the rendered output, not
    in a tracked directory of the clone)."""
    out = Path(values_dir) / "bootstrap-values.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(values, indent=2, sort_keys=True) + "\n"
    if out.is_file() and out.read_text(encoding="utf-8") == text:
        return out, True
    out.write_text(text, encoding="utf-8", newline="\n")
    return out, False


# ---------------------------------------------------------------------------
# {{value:<key>}} placeholders: A2's blueprint_render.py leaves every
# non-secret .mcp.json/user-settings env value it cannot classify as a
# machine path (project_key/vault/home/npm/python) as a {{value:<key>}}
# token, and records the (key, key_path) pairs it found in
# .claude/blueprint/templates/_values-needed.json. Three keys are derivable
# from the runner's own --target/--home inputs; the rest (measured: the
# three n8n instance URLs) are owner-supplied via --values-extra.
# ---------------------------------------------------------------------------

VALUES_NEEDED_FILE = "_values-needed.json"


def _load_values_needed(templates_dir):
    """[{key, key_path}, ...] from templates_dir/_values-needed.json.
    Missing or malformed file: empty list (nothing declared needed, so
    nothing is reported unresolved; render's own UnresolvedPlaceholderError
    is still the final net)."""
    p = Path(templates_dir) / VALUES_NEEDED_FILE
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []
    entries = data.get("values_needed") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    return [e for e in entries if isinstance(e, dict) and e.get("key")]


def _computed_value_defaults(target, home):
    """Values the runner can derive from its own --target/--home inputs,
    verified 2026-09-22 against the live-generated mcp.json.tmpl: the memory
    server's file lives under the VAULT's own .claude (a core-bucket
    tracked path, target-relative, not home-relative, contra the first
    draft of this feature), qmd's config dir and cache dir live under the
    user's home."""
    defaults = {}
    if target is not None:
        defaults["mcp-memory-memory-file-path"] = (
            Path(target) / ".claude" / "mcp-memory-graph.json"
        ).as_posix()
    if home is not None:
        defaults["mcp-qmd-qmd-config-dir"] = (Path(home) / ".config" / "qmd").as_posix()
        defaults["mcp-qmd-xdg-cache-home"] = (Path(home) / ".cache").as_posix()
    return defaults


def _load_values_extra(path):
    """{key: value} from a --values-extra JSON file. None input: empty dict
    (the flag is optional). A given-but-missing or malformed file raises
    ValueError naming the problem, rather than silently contributing
    nothing: an owner who passed the flag expects it to take effect."""
    if path is None:
        return {}
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"--values-extra file not found: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValueError(f"--values-extra file is not valid JSON: {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"--values-extra file must be a JSON object of key: value: {p}")
    return data


def apply_values_extra(values, templates_dir, values_extra_path, target, home):
    """Merge computed defaults, then --values-extra, on top of the base
    values dict (vault/home/npm/python/project_key). Returns (merged,
    unresolved_keys, values_needed_entries); unresolved_keys is every
    _values-needed.json key still absent from the merged values, sorted.
    May raise ValueError (from _load_values_extra) naming a given-but-bad
    --values-extra file; the caller reports that as a refusal.
    """
    merged = dict(values)
    merged.update(_computed_value_defaults(target, home))
    merged.update(_load_values_extra(values_extra_path))
    entries = _load_values_needed(templates_dir)
    unresolved = sorted({e["key"] for e in entries if e["key"] not in merged})
    return merged, unresolved, entries


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def load_manifest(path=None):
    """The manifest MERGED with its bare data sidecar when that file is
    present.

    The pattern lists and the work-bucket unit map live in the sidecar,
    because each of them names the material the bare profile removes and an
    inventory of what was removed is as disclosive as the thing itself. The
    sidecar sits beside the manifest on a source checkout and is deliberately
    absent on a bare device, so this returns what it can and the callers that
    need a pattern list say so when it is missing.
    """
    p = Path(path) if path else DEFAULT_MANIFEST
    data = json.loads(p.read_text(encoding="utf-8"))
    sidecar = p.parent / "work-paths.json"
    if sidecar.is_file():
        try:
            extra = json.loads(sidecar.read_text(encoding="utf-8"))
        except ValueError:
            extra = {}
        for key, value in extra.items():
            if key.startswith("_"):
                continue
            data.setdefault(key, value)
        buckets = dict(data.get("buckets") or {})
        buckets.update(extra.get("work_buckets") or {})
        data["buckets"] = buckets
    return data


def _scaffold_targets(manifest):
    """{relpath: 'dir'|'file'} for every instance/schema manifest unit, plus
    the runbook's explicit skeleton dirs and stub files (SKELETON_DIRS,
    STUB_FILES), which is a superset when the manifest already agrees and a
    safety net when a fixture manifest omits one."""
    buckets = manifest.get("buckets", {})
    targets = {}
    for unit, bucket in buckets.items():
        if bucket not in ("instance", "schema"):
            continue
        targets[unit] = "file" if unit in KNOWN_SCAFFOLD_FILES else "dir"
    for d in SKELETON_DIRS:
        targets.setdefault(d, "dir")
    for f in STUB_FILES:
        targets[f] = "file"
    return targets


# ---------------------------------------------------------------------------
# step functions
# ---------------------------------------------------------------------------

def step_preflight(args):
    """Every refusal reason at once, not the first one found.

    Ordering is deliberate: the missing-tool list comes before the secrets
    and home checks, because the secrets check used to return early and an
    owner missing both git and the secrets directory was told about one of
    them (adversarial review 22).
    """
    problems = []
    if not shutil.which("git"):
        problems.append("git not found on PATH")

    python = resolve_python()
    if not python:
        problems.append(
            "no Python interpreter found (checked VAULT_PYTHON, "
            f"{HARD_CODED_PYTHON}, python3, python); this harness needs "
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+"
        )
    else:
        version = python_version_tuple(python)
        if version is None:
            problems.append(
                f"could not read a version from the resolved Python at {python} "
                f"(needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+)"
            )
        elif version < MIN_PYTHON:
            problems.append(
                f"Python at {python} is {version[0]}.{version[1]}, below the "
                f"required {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+"
            )

    if not shutil.which("node"):
        problems.append("node not found on PATH")

    # The bare profile owes no secret file (its templates carry no
    # {{secret:...}} placeholder at all), so demanding the directory there
    # would be an invented prerequisite that stops a correct run.
    profile = getattr(args, "profile", DEFAULT_PROFILE)
    secrets_dir = Path(args.secrets_dir) if getattr(args, "secrets_dir", None) else None
    if profile != "bare" and (
        secrets_dir is None or not secrets_dir.is_dir() or not any(secrets_dir.iterdir())
    ):
        problems.append(f"--secrets-dir missing or empty: {secrets_dir}")

    home = getattr(args, "home", None)
    if home is not None:
        home_claude = Path(home) / ".claude"
        if (home_claude.exists() and any(home_claude.iterdir())
                and not getattr(args, "home_may_exist", False)):
            listing = ", ".join(sorted(p.name for p in home_claude.iterdir()))
            problems.append(
                f"--home/.claude already exists and is non-empty ({home_claude}): {listing}"
            )

    if problems:
        return False, "REFUSED: " + "; ".join(problems)
    return True, "preflight OK"


def _repo_is_url(repo):
    """True for a clone URL, False for a local path.

    A local --repo is the default, and a clone from one leaves origin
    pointing at a folder on the source machine (adversarial review 7). A URL
    already carries the right remote and is left alone.
    """
    s = str(repo)
    if re.match(r"^[A-Za-z]:[/\\]", s):  # C:/... is a Windows path, not a scheme
        return False
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", s):
        return True
    # scp-like form: user@host:path
    return bool(re.match(r"^[^/\\:]+@[^/\\:]+:", s))


def _source_origin_url(repo):
    """The `origin` URL the local --repo itself uses, or None."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def _worktree_file_count(target):
    """Files in the working tree, excluding .git. The old count reported
    10,174 against 1,815 real files, which is not a number an owner can
    compare to anything (adversarial review 20)."""
    total = 0
    for _root, dirs, files in os.walk(target):
        if ".git" in dirs:
            dirs.remove(".git")
        total += len(files)
    return total


def step_sparse_clone(manifest, target, repo, in_place=False, origin_url=None,
                      profile=DEFAULT_PROFILE):
    target = Path(target)
    if in_place:
        if not (target / ".git").exists():
            return False, f"REFUSED: --in-place given but {target} is not a git checkout"
        return True, f"in-place: using existing checkout at {target}"

    if (target / ".git").is_dir():
        return True, f"SKIP already cloned: {target}"
    if target.exists() and any(target.iterdir()):
        return False, f"REFUSED: clone target {target} exists, is non-empty, and has no .git"

    # GIT_TERMINAL_PROMPT=0 plus a bounded wait: on a fresh Windows machine
    # cloning a private HTTPS repository, a credential prompt otherwise leaves
    # the runner hanging with its output captured and nothing on screen
    # (adversarial review 23). This is the first real step of the first run.
    with _env_overlay({"GIT_TERMINAL_PROMPT": "0"}):
        try:
            proc = subprocess.run(
                ["git", "clone", "--no-checkout", str(repo), str(target)],
                capture_output=True, text=True, timeout=CLONE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return False, (
                f"FAILED: git clone timed out after {CLONE_TIMEOUT_S}s "
                "(credential prompts are disabled, so this is a slow or "
                "unreachable remote, not a hidden password box)"
            )
    if proc.returncode != 0:
        return False, f"FAILED: git clone --no-checkout: {proc.stderr.strip()}"

    sparse_file = target / ".git" / "info" / "sparse-checkout"
    sparse_file.parent.mkdir(parents=True, exist_ok=True)
    patterns = manifest_patterns(manifest, profile)
    # Written to the file, never the command line: MSYS rewrites leading
    # slashes passed as arguments (measured 2026-09-22).
    sparse_file.write_text("\n".join(patterns) + "\n", encoding="utf-8", newline="\n")

    for cmd in (
        ["git", "-C", str(target), "sparse-checkout", "init", "--no-cone"],
        ["git", "-C", str(target), "sparse-checkout", "reapply"],
        ["git", "-C", str(target), "config", "core.longpaths", "true"],
        ["git", "-C", str(target), "checkout", "-f", "main"],
    ):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, f"FAILED: {' '.join(cmd)}: {proc.stderr.strip()}"

    desired = origin_url
    origin_note = ""
    if desired is None and not _repo_is_url(repo):
        desired = _source_origin_url(repo)
        if desired is None:
            origin_note = (
                f"; WARNING: origin still points at the local path {repo} because "
                "that repository has no origin of its own, pass --origin-url"
            )
    if desired:
        proc = subprocess.run(
            ["git", "-C", str(target), "remote", "set-url", "origin", str(desired)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return False, f"FAILED: git remote set-url origin: {proc.stderr.strip()}"
        origin_note = f"; origin set to {desired}"

    n_files = _worktree_file_count(target)
    return True, (
        f"sparse clone complete: {n_files} file(s) checked out, "
        f"{len(patterns)} pattern(s){origin_note}"
    )


def step_longpaths(target):
    proc = subprocess.run(
        ["git", "-C", str(target), "config", "core.longpaths", "true"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return False, f"FAILED: git config core.longpaths true: {proc.stderr.strip()}"
    return True, "core.longpaths=true set on the target checkout"


def _is_tracked(target, rel):
    """True when git tracks `rel` in `target`, by `git ls-files --error-unmatch`.

    This is the discriminator that stops the scaffold blanking real content.
    A sparse checkout leaves tracked-but-absent paths (log.md,
    .maintain-cache.json); writing an empty stub over one of those stages a
    content deletion, measured at 819 lines on a real target, which the
    target's autosave would then push (adversarial review 2). A path git does
    not know about at all is a genuine scaffold candidate.
    """
    target = Path(target)
    if not (target / ".git").exists():
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(target), "ls-files", "--error-unmatch", "--", str(rel)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _placement_relpaths(profile):
    """Target-relative paths the profile is going to PLACE.

    The scaffold must not stub one of these: place_hook_wiring refuses to
    overwrite a file that differs from the rendered one, so an empty stub at
    <target>/CLAUDE.md would make the bare profile's own scrubbed twin
    unplaceable. Measured on the first bare apply.
    """
    return {
        "/".join(parts)
        for root, parts in placement_for(profile).values()
        if root == "target"
    }


def step_scaffold(manifest, target, profile=DEFAULT_PROFILE):
    target = Path(target)
    created, present, skipped = [], [], []
    reserved = _placement_relpaths(profile)
    placed_later = []
    for rel, kind in sorted(_scaffold_targets(manifest).items()):
        if rel in reserved:
            placed_later.append(rel)
            continue
        p = target / rel
        if kind == "dir":
            if p.is_dir():
                present.append(rel)
            else:
                p.mkdir(parents=True, exist_ok=True)
                created.append(rel)
            continue
        if p.exists():
            present.append(rel)
        elif _is_tracked(target, rel):
            skipped.append(rel)
        else:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("", encoding="utf-8", newline="\n")
            created.append(rel)
    msg = f"scaffold: created {len(created)}, already present {len(present)}"
    if placed_later:
        msg += (
            f", reserved {len(placed_later)} for the render step: "
            + ", ".join(sorted(placed_later))
        )
    if skipped:
        msg += (
            f", skipped {len(skipped)} (tracked, sparse-excluded): "
            + ", ".join(sorted(skipped))
        )
    return True, msg


def step_render_templates(values, secrets_dir, templates_dir, out_dir,
                          profile=DEFAULT_PROFILE):
    templates_dir = Path(templates_dir)
    expected = [
        blueprint_render.TEMPLATE_NAMES[k]
        for k in blueprint_render.source_order(profile)
    ]
    existing = [n for n in expected if (templates_dir / n).is_file()]
    if not existing:
        return False, (
            f"FAILED: no .tmpl file found in {templates_dir} (expected one of "
            f"{expected}); A2 template generation has not produced them on this "
            "checkout yet (blueprint_render.py generate needs real secrets and "
            "runs main-session-only)"
        )
    try:
        written = blueprint_render.render(
            templates_dir, out_dir, values, secrets_dir, profile=profile,
        )
    except Exception as exc:  # noqa: BLE001 - reported honestly, never swallowed
        return False, f"FAILED: blueprint_render.render raised: {exc}"
    return True, (
        f"rendered {len(written)} of {len(existing)} available template(s) into {out_dir}"
    )


def step_regenerate_inventories(target, home=None, profile=DEFAULT_PROFILE):
    """Rebuild, on the target, the generated inventories the bare profile does
    not ship. Returns (ok, message).

    Each of these is a description of the machine it was generated on. The
    shipped copies named this workstation's work-bound agents, skills, hooks
    and projects (the registry alone was 148 term hits, the home dashboard
    128), and a copy describing a machine the reader is not on is wrong twice
    over. Running the generator on the target produces the version that is
    true there, which on a fresh device is mostly empty.
    """
    if profile != "bare":
        return True, "NOT-IN-PROFILE: the full profile ships these inventories"
    done, failed = [], []
    for rel, generator in sorted(BARE_REGENERATED_ON_TARGET.items()):
        if not (Path(target) / generator).is_file():
            failed.append(f"{rel}: generator {generator} not in the checkout")
            continue
        # VAULT_DIR is how both inventory generators resolve which vault
        # they describe; their default is a hard-coded source path, so
        # without it they would rewrite the SOURCE machine's copy from a
        # process running on the target.
        # VAULT_DIR decides which vault the inventory describes; the three
        # home variables decide whose PLUGINS it enumerates. Without the
        # second half, a registry regenerated on the target still listed the
        # source machine's installed plugins, which is where 131 of the first
        # run's work-bound hits came from.
        env = {"VAULT_DIR": str(Path(target).resolve())}
        if rel in HOME_AWARE_INVENTORIES:
            # Only the two inventories that enumerate PLUGINS get the home
            # overlay. Pointing HOME at the target also moves Python's user
            # site-packages, and the home dashboard's generator needs a
            # package that lives there: measured as "ERROR: pyyaml not
            # installed" on a target where pyyaml is installed.
            env.update(_home_env(home))
        ok, raw = _run_via_bin_py(target, [generator], timeout=300, extra_env=env)
        # The artifact, not the exit code, is the contract: the registry
        # generator runs its own self-checks and exits non-zero on a WARN (a
        # hook with no test, which a bare device legitimately has after the
        # content exclusions), while still writing the file it was asked for.
        if (Path(target) / rel).exists():
            done.append(rel if ok else f"{rel} (generator exit non-zero, artifact written)")
        else:
            failed.append(
                f"{rel}: {generator} wrote nothing: "
                + (raw.splitlines()[0] if raw else "no output")
            )
    msg = f"regenerated {len(done)} inventory file(s): {', '.join(done) or 'none'}"
    if failed:
        return False, "FAILED: " + "; ".join(failed) + "\n" + msg
    return True, msg


def step_seed_coverage_ratchet(target, profile=DEFAULT_PROFILE):
    """Write the SHIPPED bare control high-water baseline onto the target.

    The ratchet file is gitignored, so it never travels, and the test that
    reads it writes it and skips when it is absent. On a fresh device that
    means the first run anchors the baseline to whatever the scrub left, and
    any over-drop introduced before that moment is baked in and can never be
    detected there (adversarial F12). Seeding it from a value that shipped
    with the profile makes the FIRST run a comparison.
    """
    if profile != "bare":
        return True, "NOT-IN-PROFILE: the baseline is a bare-profile figure"
    known = Path(target) / ".claude" / "blueprint" / KNOWN_FAILURES_FILE
    baseline = None
    if known.is_file():
        try:
            baseline = json.loads(known.read_text(encoding="utf-8")).get(
                "controls_high_water_bare"
            )
        except ValueError:
            baseline = None
    if not isinstance(baseline, int):
        return False, (
            "FAILED: no controls_high_water_bare baseline shipped in "
            f"{KNOWN_FAILURES_FILE}, so the coverage ratchet would self-initialise "
            "on this device and the first run would be unguarded"
        )
    out = Path(target) / ".claude" / "hooks" / "aggregates" / "controls-high-water.json"
    if out.is_file():
        return True, f"already present: {out}"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({
            "pairs": baseline,
            "note": (
                "shipped bare baseline, written by bootstrap_machine so the first "
                "check on this device compares rather than initialises. Lower it only "
                "deliberately: a drop means a control left the settings files."
            ),
        }, indent=1) + "\n",
        encoding="utf-8", newline="\n",
    )
    return True, f"seeded the coverage ratchet at {baseline} registered control pair(s)"


def step_place_hook_wiring(rendered_dir, target, home, profile=DEFAULT_PROFILE):
    """Place every rendered file, refusing rather than skipping on a gap.

    A missing rendered source used to `continue`, so a rename in DEPLOY_NAMES
    would have produced "placed 0 file(s)" with ok=True (architect review 11).
    """
    rendered_dir = Path(rendered_dir)
    to_place, conflicts, skipped, absent = [], [], [], []
    for name in placement_for(profile):
        src = rendered_dir / name
        if not src.is_file():
            absent.append(name)
            continue
        dest = placement_dest(name, target, home, profile=profile)
        if dest.exists():
            if dest.read_bytes() == src.read_bytes():
                skipped.append(str(dest))
            else:
                conflicts.append(str(dest))
        else:
            to_place.append((src, dest))
    if absent:
        return False, (
            "FAILED: no rendered source for " + ", ".join(sorted(absent))
            + f" in {rendered_dir}; render produced a different set of names than "
            "PLACEMENT expects"
        )
    if conflicts:
        return False, (
            "REFUSED: existing file(s) differ and would be overwritten: "
            + ", ".join(conflicts)
        )
    for src, dest in to_place:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())
    return True, f"placed {len(to_place)} file(s), {len(skipped)} already present and identical"


# ---------------------------------------------------------------------------
# check-family substeps. Every one takes (target, home) so the dispatch in
# run_check stays uniform and no substep can quietly ignore --home again.
# They reuse .claude/bin/py (DEP-002), the only sanctioned interpreter
# resolution order (CON-004), so no new path resolver is added.
# ---------------------------------------------------------------------------

def _resolve_bash():
    """A bare "bash" executable name handed to subprocess.run (no shell=True)
    goes through Windows CreateProcess's own search order, which checks
    System32 before PATH: C:\\Windows\\System32\\bash.exe is the WSL launcher
    stub there and wins over Git Bash's usr\\bin\\bash.exe regardless of PATH
    content or order (measured on this machine). shutil.which honours PATH
    order correctly, so resolve the full path once per call and fall back to
    the bare name only if that lookup itself comes back empty."""
    return shutil.which("bash") or "bash"


def _run_via_bin_py(target, script_args, timeout=180, extra_env=None, full_output=False):
    bin_py = Path(target) / ".claude" / "bin" / "py"
    if not bin_py.is_file():
        return False, f"FAILED: {bin_py} not found on the target checkout"
    cmd = [_resolve_bash(), str(bin_py)] + [str(a) for a in script_args]
    # subprocess.run's env=None (the default) inherits the real parent
    # environment untouched; passing an explicitly rebuilt dict(os.environ),
    # even as a content-identical copy, was observed to change how Windows
    # resolves "bash" on this machine (it picked the WSL launcher stub
    # instead of Git Bash's bash.exe). extra_env is therefore applied by
    # mutating the live os.environ for the duration of the call and
    # restoring it after, so subprocess.run always keeps env=None.
    with _env_overlay(extra_env):
        try:
            proc = subprocess.run(
                cmd, cwd=str(target), capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, f"FAILED: timed out after {timeout}s: {' '.join(cmd)}"
        except OSError as exc:
            return False, f"FAILED to run {' '.join(cmd)}: {exc}"
    output = (proc.stdout or "") + (proc.stderr or "")
    body = output if full_output else "\n".join(output.splitlines()[-20:])
    return proc.returncode == 0, f"exit {proc.returncode}\n{body}"


def step_home_wiring(target, home, profile=DEFAULT_PROFILE):
    """The three files PLACEMENT puts under --home are there and usable.

    --check and --acceptance never read --home, so a target whose user-level
    placement went to the wrong home, or silently did not happen, passed the
    whole check family unchanged (adversarial review 5).
    """
    if home is None:
        return False, "REFUSED: --home is required for the home_wiring check"
    missing = []
    for name in HOME_PLACED_NAMES:
        dest = placement_dest(name, target, home)
        if not dest.is_file():
            missing.append(str(dest))
    if missing:
        return False, "FAILED: not placed under --home: " + ", ".join(missing)

    settings = placement_dest(blueprint_render.DEPLOY_NAMES["user_settings"], target, home)
    text = settings.read_text(encoding="utf-8")
    try:
        json.loads(text)
    except ValueError as exc:
        return False, f"FAILED: {settings} does not parse as JSON: {exc}"
    if "{{" in text:
        leftovers = sorted(set(blueprint_render.LEFTOVER_PLACEHOLDER_RE.findall(text)))
        return False, (
            f"FAILED: {settings} still carries unrendered placeholder(s): "
            + ", ".join(leftovers)
        )
    placed = ", ".join(str(placement_dest(n, target, home)) for n in HOME_PLACED_NAMES)
    return True, f"3 file(s) placed under --home and parseable: {placed}"


def _home_env(home):
    """The three variables that decide where a Windows process thinks "home"
    is. install_prereqs.py resolves its home-relative rows from these, so
    pointing them at --home is what makes its check a statement about the
    TARGET rather than about this laptop (architect review 4)."""
    if home is None:
        return {}
    resolved = Path(home).resolve()
    return {
        "USERPROFILE": str(resolved),
        "HOME": str(resolved),
        "APPDATA": str((resolved / "AppData" / "Roaming").resolve()),
    }


def _parse_install_prereqs_rows(raw):
    """[(id, verdict, detail)] from install_prereqs.py --check's table."""
    rows = []
    for line in _ANSI_RE.sub("", raw).splitlines():
        match = _INSTALL_ROW_RE.match(line.rstrip())
        if match:
            rows.append((match.group(1), match.group(2), match.group(3).strip()))
    return rows


def _placed_mcp_servers(target):
    """The server names in the TARGET's own placed .mcp.json, or None when it
    is absent or unparseable."""
    path = Path(target) / ".mcp.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    servers = data.get("mcpServers")
    return sorted(servers) if isinstance(servers, dict) else None


def _slug_for_row(name):
    """install_prereqs.py's own row-id slug rule for an MCP server name."""
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def _not_in_profile_rows(rows, target):
    """Rows the bare profile deliberately does not provision.

    An `mcp-server-<slug>` row probes a key in the target's own .mcp.json, or
    a plugin's cache path. The bare profile ships neither for a work-bound
    server, so such a row can never pass and is not a prerequisite gap: it is
    the profile working. Rows are matched against the PLACED .mcp.json, not
    against a list in this file, so adding a generic server to the profile
    needs no edit here.
    """
    placed = _placed_mcp_servers(target)
    if placed is None:
        return []
    in_profile = {"mcp-server-" + _slug_for_row(n) for n in placed}
    out = []
    for row in rows:
        row_id, _verdict, detail = row
        if not row_id.startswith("mcp-server-"):
            continue
        if row_id in in_profile:
            continue
        # A plugin-cache row for a plugin the bare profile still installs is
        # PENDING-SLICE-2, not out of profile: a generic plugin's row passes
        # once the plugin install runs. Only a row naming a work-bound term
        # is out of profile.
        if _PLUGIN_CACHE_RE.search(detail) and not wb.has_term(row_id + " " + detail):
            continue
        # The same requirement on the server branch (architect F6). Without
        # it, ANY absent server was excused as "not in this profile", so a
        # term false positive that dropped a GENERIC server from the scrub
        # would read NOT-IN-PROFILE in the runner's own table rather than
        # FAIL. The renderer has a finding for exactly that case, but it is a
        # different program run at a different time.
        if not wb.has_term(row_id + " " + detail):
            continue
        out.append(row)
    return out


def _pending_slice_2_rows(rows):
    """[(row, satisfying command)] for every row a later-slice provisioning
    step owns: the plugin-cache mcp-server rows, and the named npm install
    rows. Verdict-independent on purpose, so the expectation is on the record
    before the rows go red rather than after."""
    out = []
    for row in rows:
        row_id, _verdict, detail = row
        if row_id in SLICE_2_INSTALL_ROWS:
            out.append((row, SLICE_2_INSTALL_ROWS[row_id]))
        elif row_id.startswith("mcp-server-") and _PLUGIN_CACHE_RE.search(detail):
            out.append((row, _PLUGIN_INSTALL_COMMAND))
    return out


def step_install_prereqs_check(target, home, profile=DEFAULT_PROFILE):
    """install_prereqs.py --check, measured against --home, with the
    later-slice rows named rather than folded into a flat FAIL.

    Returns (passed, detail, verdict). The third verdict, PENDING-SLICE-2,
    exists because those rows cannot pass before their NOT-IN-SLICE-1
    provisioning step: recording them PASS would be the false green the
    review measured, and recording them FAIL without naming them hides which
    rows are a real defect. PENDING-SLICE-2 is not a pass: the row keeps
    passed=False, so --check still exits 2 and --acceptance still exits 1.
    """
    ok, raw = _run_via_bin_py(
        target, [".claude/scripts/install_prereqs.py", "--check"],
        extra_env=_home_env(home), full_output=True,
    )
    rows = _parse_install_prereqs_rows(raw)
    not_in_profile = _not_in_profile_rows(rows, target) if profile == "bare" else []
    not_in_profile_ids = {r[0] for r in not_in_profile}
    pending_all = [
        (row, cmd) for row, cmd in _pending_slice_2_rows(rows)
        if row[0] not in not_in_profile_ids
    ]
    note = ""
    if not_in_profile:
        note += (
            "\nrows outside this profile, reported NOT-IN-PROFILE: the bare "
            "profile places no .mcp.json entry and installs no plugin for "
            "them, so the probe cannot pass and nothing is missing: "
            + ", ".join(r[0] for r in not_in_profile)
        )
    if pending_all:
        note = (
            "\nlater-slice rows, expected to fail on any target until the "
            "NOT-IN-SLICE-1 provisioning step runs, and reported PENDING-SLICE-2 "
            "when they do (neither PASS nor a silent FAIL): "
            + ", ".join(f"{row[0]} -> {cmd}" for row, cmd in pending_all)
        )
    if ok:
        return True, raw + note, "PASS"

    pending_by_id = {row[0]: cmd for row, cmd in pending_all}
    failing = [r for r in rows if r[1] == "FAIL" and r[0] not in not_in_profile_ids]
    if not failing:
        # Every failing row was outside this profile: the check passes, and
        # the rows are named rather than hidden.
        if not_in_profile:
            summary = (
                f"NOT-IN-PROFILE: {len(not_in_profile)} row(s) belong to a server "
                "or plugin the bare profile does not place: "
                + ", ".join(r[0] for r in not_in_profile)
            )
            return True, summary + "\n" + raw + note, "NOT-IN-PROFILE"
        return False, raw + note, "FAIL"
    pending = [r for r in failing if r[0] in pending_by_id]
    other = [r for r in failing if r[0] not in pending_by_id]
    pending_text = ", ".join(f"{r[0]} -> {pending_by_id[r[0]]}" for r in pending)
    if not other:
        summary = (
            f"PENDING-SLICE-2: {len(pending)} row(s) wait on a NOT-IN-SLICE-1 "
            "provisioning step and cannot pass before it: " + pending_text
        )
        return False, summary + "\n" + raw + note, "PENDING-SLICE-2"
    summary = (
        f"FAIL: {len(other)} row(s) failed for reasons other than a pending "
        "provisioning step: " + ", ".join(r[0] for r in other)
    )
    if pending:
        summary += f" (plus {len(pending)} PENDING-SLICE-2: {pending_text})"
    return False, summary + "\n" + raw + note, "FAIL"


def _o17_supports_home(target):
    """True when the target's own o17 checker accepts --home.

    The flag normalises home paths and is arriving in a parallel change, so
    the capability is read off the checker's own --help rather than assumed.
    Passing an unknown flag to argparse is exit 2 plus a usage dump, which
    the step would then report as an o17 failure: a runner defect dressed as
    a portability finding.
    """
    ok, raw = _run_via_bin_py(
        target,
        [".claude/scripts/o17_portability_manifest.py", "check", "--help"],
        timeout=60, full_output=True,
    )
    return ok and "--home" in raw


def step_o17_check(target, home, profile=DEFAULT_PROFILE):
    local = Path(target) / ".claude" / "settings.local.json"
    if not local.is_file():
        return False, (
            f"FAILED: {local} not present (place_hook_wiring did not run or failed)"
        )
    absent = [rel for rel in O17_ARTIFACTS if not (Path(target) / rel).is_file()]
    if absent and profile == "bare":
        # The O17 manifest of record is a DESCRIPTION OF THE SOURCE MACHINE:
        # every server, every host, every substitution it uses. The bare
        # profile stopped shipping it for that reason, so its absence here is
        # the profile working rather than a clone gap. A bare device has no
        # machine description to check the wiring against, and saying so is
        # more honest than checking the wiring against somebody else's.
        return True, (
            "NOT-IN-PROFILE: the O17 manifest of record describes the source "
            "workstation (every MCP server, host and substitution by name), so the "
            "bare profile does not ship it and this comparison has no baseline "
            "here: " + ", ".join(absent)
        ), "NOT-IN-PROFILE"
    if absent:
        return False, (
            "FAILED: artifacts absent: re-clone with the current manifest; the O17 "
            "checker reads its manifest of record from these tracked paths and the "
            "clone does not carry them: " + ", ".join(absent)
        )
    argv = [".claude/scripts/o17_portability_manifest.py", "check", "--local", str(local)]
    home_note = ""
    if home is not None:
        if _o17_supports_home(target):
            argv += ["--home", str(home)]
        else:
            home_note = (
                "\nNOTE: the target's o17 checker has no --home flag yet, so home "
                "paths are not normalised in this run; any finding naming a home "
                "path may be that gap rather than a real divergence"
            )
    # full_output, not the last 20 lines: the bare classifier below reads
    # EVERY finding line, and a truncated tail would let an unexplained
    # finding at the head of the output pass as explained. Only the first
    # line of the detail ever reaches the table, so this costs nothing.
    ok, raw = _run_via_bin_py(target, argv, full_output=True)
    if not ok and "artifact missing" in raw:
        return False, (
            "FAILED: artifacts absent: re-clone with the current manifest\n" + raw
            + home_note
        )
    if not ok and profile == "bare":
        return _o17_bare_verdict(raw + home_note)
    return ok, raw + home_note


# O17's CHECK-A compares the placed wiring against a manifest of record that
# describes THIS workstation: every server, every permission row, every hook
# tuple it had on the day the manifest was written. A bare target removed
# some of those on purpose, so CHECK-A reports one MISSING_* finding per
# removal. Each of those is the profile working, and calling it a failure
# would put a permanent red row on a correct device.
#
# Two rules decide, and both are narrow. A MISSING_* finding is expected only
# when its detail carries a work-bound term. The one exception that cannot
# carry a term is named here rather than pattern-matched: the mcp-enablement
# section's row set IS the enabledMcpjsonServers list the bare scrub filters,
# so a differing row set there is the same removal seen from the section
# level. Anything else, including any non-MISSING code, is a real failure and
# is reported by name.
_O17_FINDING_RE = re.compile(r"^(CHECK-[A-Z])\s+([A-Z_]+):\s*(.*)$")
_O17_BARE_NAMED_EXCEPTIONS = (
    ("MISSING_SECTION", "mcp-enablement"),
)


def _o17_finding_row(detail):
    """The ROW a MISSING_* finding is about, not the sentence around it.

    O17 writes `manifest missing live <label> row (<n>x): <row>` and
    `manifest carries <label> row absent from live parse (<n>x): <row>`, so
    the row is the text after the last `): `. Matching the term against the
    whole detail auto-blessed any finding whose prose mentioned a term
    anywhere, which is how a generic hook lost as collateral to a
    term-carrying group matcher read as expected (adversarial F13). When the
    shape does not match, the whole detail is returned: a rule that cannot
    find the row must not silently widen to "no term, therefore unexpected"
    either way, so it falls back to the previous behaviour and the finding is
    judged on everything it says.
    """
    match = re.search(r"\)\s*:\s*(.+)$", str(detail))
    if match:
        return match.group(1).strip()
    match = re.match(r"^[a-z-]+:\s*(.+)$", str(detail))
    return match.group(1).strip() if match else str(detail)


def _o17_bare_verdict(raw):
    """Classify a failing o17 run on a bare target.

    Returns (passed, detail, verdict), so the check table shows
    NOT-IN-PROFILE rather than an unqualified PASS.
    """
    expected, unexpected = [], []
    for line in _ANSI_RE.sub("", raw).splitlines():
        match = _O17_FINDING_RE.match(line.strip())
        if not match:
            continue
        _check, code, detail = match.groups()
        if code.startswith("MISSING_") and wb.has_term(_o17_finding_row(detail)):
            expected.append(line.strip())
            continue
        if any(code == c and name in detail for c, name in _O17_BARE_NAMED_EXCEPTIONS):
            expected.append(line.strip())
            continue
        unexpected.append(line.strip())

    if unexpected:
        return False, (
            f"FAIL: {len(unexpected)} o17 finding(s) the bare scrub does not "
            "explain: " + "; ".join(unexpected[:10]) + "\n" + raw
        ), "FAIL"
    if not expected:
        return False, raw, "FAIL"
    return True, (
        f"NOT-IN-PROFILE: {len(expected)} o17 finding(s), every one a row the "
        "bare scrub removed on purpose (the manifest of record describes this "
        "workstation, not a bare device)\n" + raw
    ), "NOT-IN-PROFILE"


def step_blueprint_manifest_check(target, home, profile=DEFAULT_PROFILE):  # uniform signature
    return _run_via_bin_py(target, [".claude/scripts/blueprint_manifest.py", "check"])


def _load_known_failures(target, profile=DEFAULT_PROFILE):
    """(node id set, raw document) from the target's own
    mechanism-only-known-failures.json.

    The document shape is {measured_on, count, node_ids, reasons}, plus
    node_ids_bare and reasons_bare. The bare list is UNIONED only for a bare
    target: five ids fail there and nowhere else, each traceable to a
    deliberate profile decision (the tracker guard is a work-bound path the
    bare sparse set excludes; Resources/KB is knowledge-bucket and does not
    travel). A full target still reports those five by name.

    The older list-of-{file} shape returns an empty set on purpose: a target
    still shipping the filename mask gets no free pass, it gets every failure
    reported by node id.
    """
    p = Path(target) / ".claude" / "blueprint" / KNOWN_FAILURES_FILE
    if not p.is_file():
        return set(), {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return set(), {}
    if not isinstance(doc, dict):
        return set(), {}
    node_ids = doc.get("node_ids")
    if not isinstance(node_ids, list):
        return set(), doc
    if profile == "bare" and isinstance(doc.get("node_ids_bare"), list):
        node_ids = list(node_ids) + list(doc["node_ids_bare"])
    return {n for n in node_ids if isinstance(n, str) and "::" in n}, doc


def _parse_pytest_summary(raw_output):
    """[(status, node_id, line)] for every FAILED/ERROR line in a pytest -rfE
    short summary. The node id is file-relative (basename plus ::test), so a
    target's path spelling does not enter the comparison. ANSI colour codes
    are stripped first (pytest on this machine colours output even under
    capture_output=True)."""
    clean = _ANSI_RE.sub("", raw_output)
    rows = []
    for line in clean.splitlines():
        line = line.rstrip()
        m = _PYTEST_SUMMARY_LINE_RE.match(line)
        if not m:
            continue
        status, ref = m.group(1), m.group(2)
        file_part, sep, rest = ref.partition("::")
        basename = Path(file_part.replace(chr(92), "/")).name
        node_id = basename + sep + rest if sep else basename
        rows.append((status, node_id, line))
    return rows


def _hooks_suite_verdict(raw_output, known_node_ids):
    """Classify a failed hooks-suite run's raw combined stdout+stderr.

    PASS only when the set of failing NODE IDS is a subset of the known set.
    The previous rule keyed on the failing file's basename, so any failure in
    any of the five listed files passed whatever its cause; that mask was
    measured hiding a real regression (a second, different failure inside
    test_hooks_survive_malformed_payload.py) and could not see a failure
    count change either. Any node id not in the list is reported by name.
    Unparseable output (no FAILED/ERROR line at all, for example a crash
    before the summary prints) is never a silent pass.
    """
    rows = _parse_pytest_summary(raw_output)
    if not rows:
        return False, "FAIL (no FAILED/ERROR summary line parsed)\n" + raw_output
    failing = {node_id for _status, node_id, _line in rows}
    unknown = sorted(failing - set(known_node_ids))
    if not unknown:
        summary = (
            f"KNOWN-NEEDS-CONTENT: {len(failing)} failing node id(s), every one "
            f"listed in {KNOWN_FAILURES_FILE}"
        )
        return True, summary + "\n" + raw_output
    summary = (
        f"FAIL: {len(unknown)} failing node id(s) not in {KNOWN_FAILURES_FILE}: "
        + ", ".join(unknown)
    )
    return False, summary + "\n" + raw_output


def step_hooks_suite(target, home, profile=DEFAULT_PROFILE):  # uniform signature
    ok, raw = _run_via_bin_py(
        target,
        ["-m", "pytest", ".claude/hooks", "-q", "-p", "no:cacheprovider", "-rfE"],
        timeout=900, full_output=True,
    )
    if ok:
        return True, raw
    known_ids, _doc = _load_known_failures(target, profile=profile)
    return _hooks_suite_verdict(raw, known_ids)


def step_hook_activity_findings(target, home, profile=DEFAULT_PROFILE):  # uniform signature
    # hook_activity_report.py's VAULT default is a hard-coded live-machine
    # literal (os.environ.get("VAULT_DIR", r"C:\...\Vault")), not
    # self-locating; its own documented VAULT_DIR override points it at the
    # target instead of silently reading the source machine's sinks.
    return _run_via_bin_py(
        target, [".claude/scripts/hook_activity_report.py", "--findings"],
        extra_env={"VAULT_DIR": str(Path(target).resolve())},
    )


def run_written_files(target, home, profile=DEFAULT_PROFILE):
    """Every file THIS RUN wrote, however far from the placement map.

    Enumerated rather than hard-coded: the runner writes a file the old scan
    list did not carry (`<home>/.claude/blueprint/bootstrap-values.json`, which
    holds the vault path, the home path and the derived project key, so a vault
    installed under a company-named directory put that name in a file nothing
    read). Adversarial F9.
    """
    out = [
        placement_dest(name, target, home, profile=profile)
        for name in placement_for(profile)
    ]
    if home is not None:
        out.append(Path(home) / ".claude" / "blueprint" / VALUES_FILE_NAME)
    out.append(Path(target) / ".claude" / "hooks" / "aggregates" / "controls-high-water.json")
    for rel in BARE_REGENERATED_ON_TARGET:
        out.append(Path(target) / rel)
    return out


def _tree_relpaths(root, skip_dirs=(".git",)):
    """Every file under `root`, as root-relative posix paths."""
    root = Path(root)
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            out.append(str(Path(dirpath, name).relative_to(root)).replace(chr(92), "/"))
    return out


def step_workbound_scan(target, home, profile=DEFAULT_PROFILE):
    """THE WHOLE TARGET TREE, plus every file this run wrote outside it,
    carries no work-bound term and no work-bound shape. Any hit fails.

    This is the runner's half of the bare profile's claim, and its scope is
    the finding both 2026-09-22 reviews led with: the old version read six
    placed files while the profile delivered 1,724, and printed "0 hit(s)
    across 6 placed file(s)" as though that covered the delivery. 154 of the
    unscanned files named the employer in their content.

    It reports the term and the line number, never the line: a line carrying a
    term can also carry a credential. In the full profile the check does not
    apply, and says so rather than reporting a pass it did not earn.
    """
    if profile != "bare":
        return True, (
            "NOT-IN-PROFILE: the full profile reproduces this workstation, "
            "so its placed files name it by design; nothing was scanned"
        ), "NOT-IN-PROFILE"

    if not wb.terms_available():
        return False, (
            "FAILED: no work-bound term data on this device "
            f"({wb.TERMS_FILE_ENV} unset and no data file next to the blueprint "
            "manifest), so this scan cannot mean anything. 0 hits from an empty "
            "term list is not evidence."
        ), "FAIL"

    target = Path(target)
    findings = []
    tree = _tree_relpaths(target)
    for hit in wb.scan_tree(target, tree):
        findings.append(f"{hit['path']}:{hit['line']}: {hit['term']}")

    placed_names = set(placement_for(profile))
    extra = []
    for path in run_written_files(target, home, profile=profile):
        path = Path(path)
        try:
            if path.resolve().is_relative_to(target.resolve()):
                continue  # already covered by the tree walk above
        except (OSError, ValueError):
            pass
        extra.append(path)
        if not path.is_file():
            # A file the profile PLACES must be there; a file the run merely
            # writes alongside (the values file, the seeded ratchet) may not
            # have been written in this mode, and its absence is not a leak.
            if path.name in placed_names:
                findings.append(f"{path}: not placed")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(f"{path}: unreadable: {exc}")
            continue
        for lineno, term in wb.scan_text(text):
            findings.append(f"{path}:{lineno}: {term}")
    scanned = len(tree) + len(extra)

    if findings:
        return False, (
            f"FAILED: {len(findings)} work-bound hit(s) across {scanned} file(s) "
            f"({len(tree)} in the target tree, {len(extra)} written outside it): "
            + "; ".join(findings[:20])
        ), "FAIL"
    return True, (
        f"0 hit(s) of {len(wb.TERMS)} term(s) and {len(wb.SHAPES)} shape(s) across "
        f"{scanned} file(s): the whole target tree ({len(tree)}) plus {len(extra)} "
        "file(s) this run wrote outside it"
    ), "PASS"


def step_bare_idempotence(target, home, profile=DEFAULT_PROFILE):
    """The target's own `blueprint_render.py check --profile bare`.

    The twin's drift detector worked and nothing ran it (architect F8). It
    runs here. On a device whose term data is not reachable the term-dependent
    findings cannot fire, so the row says which half it established:
    regeneration stability always, term absence only with term data.
    """
    if profile != "bare":
        return True, (
            "NOT-IN-PROFILE: the bare idempotence check belongs to the bare profile"
        ), "NOT-IN-PROFILE"
    argv = [
        ".claude/scripts/blueprint_render.py", "check", "--profile", "bare",
        "--templates-dir", ".claude/blueprint/templates/bare",
    ]
    # The renderer resolves three of its sources under the user home. On a
    # real fresh device that IS the process home; in a sandbox run it is
    # --home, and without this the check compares the target's templates
    # against the SOURCE machine's live files and reports drift that is
    # entirely an artifact of where the run happens.
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    source_terms = wb.term_data_path()
    if source_terms is not None:
        env[wb.TERMS_FILE_ENV] = str(source_terms)
    ok, raw = _run_via_bin_py(target, argv, timeout=300, extra_env=env, full_output=True)
    note = (
        "\nNOTE: the target carries no term data by design, so this run read the "
        f"source's term file through {wb.TERMS_FILE_ENV}"
        if source_terms is not None else
        "\nNOTE: no term data reachable, so this run established regeneration "
        "stability only, not term absence"
    )
    return ok, raw + note


def run_check(target, home, profile=DEFAULT_PROFILE):
    """Run every check-family substep. Returns ([{step, passed, verdict, detail}], ok).

    Looked up via globals() rather than a fixed tuple of function objects so
    a test can monkeypatch step_* names on the module and have run_check
    observe the patched version. A substep returns (passed, detail) or
    (passed, detail, verdict); the third element carries the PENDING-SLICE-2
    state, which is neither a pass nor an undifferentiated fail.
    """
    rows = []
    ok = True
    for label, fn_name in check_substeps(profile):
        fn = globals()[fn_name]
        result = fn(target, home, profile=profile)
        passed, detail = result[0], result[1]
        verdict = result[2] if len(result) > 2 else ("PASS" if passed else "FAIL")
        rows.append({"step": label, "passed": passed, "verdict": verdict, "detail": detail})
        ok = ok and passed
    return rows, ok


def probe_claude_cli(target, timeout=120, cli=None):
    """Run the CLI against the target checkout. Returns (passed, detail, skipped).

    Two changes the reviews forced. A missing CLI is a FAIL: the old code
    returned a pass for it, so --acceptance could exit 0 on a machine where
    Claude Code was never installed, and that exit code is what Phase B's
    definition of done rests on. And cwd is the target, so the target's own
    hooks fire on the probe rather than the source machine's.
    """
    exe = shutil.which(cli) if cli else shutil.which("claude")
    if not exe:
        return False, (
            f"FAILED: claude CLI not found ({cli or 'claude'}); a missing CLI is "
            "not an accepted acceptance outcome"
        ), False
    cmd = [str(exe), "-p", "reply with the single word ok", "--model", "haiku"]
    try:
        proc = subprocess.run(
            cmd, cwd=str(target), capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"FAILED: claude CLI probe timed out after {timeout}s", False
    except OSError as exc:
        return False, f"FAILED: claude CLI probe could not run: {exc}", False
    out = proc.stdout or ""
    ok = proc.returncode == 0 and bool(re.search(r"\bok\b", out, re.IGNORECASE))
    detail = f"exit {proc.returncode}: {out.strip()[:120]}"
    if not ok:
        detail = "FAILED: " + detail
    return ok, detail, False


def _acceptance_rows(target, home, probe=True, cli=None, profile=DEFAULT_PROFILE):
    rows, _ = run_check(target, home, profile=profile)
    if probe:
        p_ok, p_detail, _p_skipped = probe_claude_cli(target, cli=cli)
        rows.append({
            "step": "claude_cli_probe", "passed": p_ok,
            "verdict": "PASS" if p_ok else "FAIL", "detail": p_detail,
        })
    else:
        rows.append({
            "step": "claude_cli_probe", "passed": False, "verdict": "SKIPPED-BY-FLAG",
            "detail": "SKIPPED-BY-FLAG: --no-probe given, so nothing probed the "
                      "placed wiring",
        })
    return rows


def acceptance(target, home, probe=True, cli=None, profile=DEFAULT_PROFILE):
    """0 only if every check substep AND the probe passed. A skipped probe is
    not an accepted outcome: it exits 1."""
    rows = _acceptance_rows(target, home, probe=probe, cli=cli, profile=profile)
    return 0 if all(r["passed"] for r in rows) else 1


# ---------------------------------------------------------------------------
# planning and reporting tables
# ---------------------------------------------------------------------------

def plan_steps(profile=DEFAULT_PROFILE, templates_dir=None):
    """The step plan. One status set only: DO for every slice-1 step,
    NOT-IN-SLICE-1 for the rest. The SKIP status and the check-only plan mode
    were unreachable from any CLI path while two documents advertised them
    (architect review 16, adversarial review 14), so they are gone.

    The bare profile adds the workbound_scan row; the full profile does not,
    because in full the placed files are meant to name this workstation."""
    steps = list(SLICE_1_STEPS)
    if profile == "bare":
        steps += BARE_ONLY_STEPS
    rows = [{"step": name, "status": "DO", "why": why} for name, why in steps]
    for name, label, why in not_in_slice_1(profile, templates_dir=templates_dir):
        rows.append({"step": name, "status": "NOT-IN-SLICE-1", "why": f"{label}: {why}"})
    return rows


def render_plan_table(rows):
    lines = ["Bootstrap plan", ""]
    w_step = max([len("step")] + [len(r["step"]) for r in rows])
    w_status = max([len("status")] + [len(r["status"]) for r in rows])
    header = f"{'step'.ljust(w_step)}  {'status'.ljust(w_status)}  why"
    lines.append(header)
    lines.append("-" * len(header))
    for r in rows:
        lines.append(f"{r['step'].ljust(w_step)}  {r['status'].ljust(w_status)}  {r['why']}")
    return "\n".join(lines)


def render_manifest_summary(manifest, path, profile=DEFAULT_PROFILE):
    counts = manifest.get("counts") or {}
    patterns = manifest_patterns(manifest, profile)
    buckets = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    block = (manifest.get("profiles") or {}).get(profile) or {}
    lines = [
        f"Manifest: {path}",
        "",
        f"{len(patterns)} sparse pattern(s) for profile {profile}",
        f"buckets: {buckets}" if buckets else "buckets: (none recorded)",
    ]
    if block:
        lines.append(
            f"profile {profile}: {block.get('file_count', '?')} tracked file(s), "
            f"buckets {', '.join(block.get('buckets') or [])}"
            + (
                f", replaces {', '.join(block['replaced_paths'])}"
                if block.get("replaced_paths") else ""
            )
        )
    return "\n".join(lines)


def preflight_report(args):
    """Read-only preflight rows for --dry-run. Opens nothing for writing and
    creates nothing; every row is a stat or a PATH lookup."""
    rows = []
    git = shutil.which("git")
    rows.append(("git", bool(git), git or "not found on PATH"))

    python = resolve_python()
    if python:
        version = python_version_tuple(python)
        if version is None:
            rows.append(("python", False, f"{python} (version unreadable)"))
        else:
            rows.append((
                "python", version >= MIN_PYTHON,
                f"{python} is {version[0]}.{version[1]}, "
                f"need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+",
            ))
    else:
        rows.append(("python", False,
                     "no interpreter found (VAULT_PYTHON, "
                     f"{HARD_CODED_PYTHON}, python3, python)"))

    node = shutil.which("node")
    rows.append(("node", bool(node), node or "not found on PATH"))

    target = Path(args.target)
    if not target.exists():
        rows.append(("target", True, f"{target} does not exist yet, clone will create it"))
    elif (target / ".git").exists():
        rows.append(("target", True, f"{target} is an existing git checkout"))
    elif any(target.iterdir()):
        rows.append(("target", False, f"{target} exists, is non-empty and has no .git"))
    else:
        rows.append(("target", True, f"{target} exists and is empty"))

    home = getattr(args, "home", None)
    if home is None:
        rows.append(("home", True, "--home not given, required for --apply/--check"))
    else:
        home_claude = Path(home) / ".claude"
        if not home_claude.exists():
            rows.append(("home", True, f"{home_claude} does not exist yet"))
        elif any(home_claude.iterdir()):
            rows.append((
                "home", bool(getattr(args, "home_may_exist", False)),
                f"{home_claude} exists and is non-empty "
                "(needs --home-may-exist)",
            ))
        else:
            rows.append(("home", True, f"{home_claude} exists and is empty"))

    profile = getattr(args, "profile", DEFAULT_PROFILE)
    secrets_dir = getattr(args, "secrets_dir", None)
    if profile == "bare":
        rows.append((
            "secrets-dir", True,
            "not needed in the bare profile: its templates carry no "
            "{{secret:...}} placeholder",
        ))
    elif secrets_dir is not None:
        p = Path(secrets_dir)
        if p.is_dir() and any(p.iterdir()):
            rows.append(("secrets-dir", True, f"{p} present and non-empty"))
        else:
            rows.append(("secrets-dir", False, f"{p} missing or empty"))
    return rows


def render_preflight_table(rows):
    lines = ["Preflight (read-only)", ""]
    w_item = max([len("item")] + [len(r[0]) for r in rows])
    header = f"{'item'.ljust(w_item)}  verdict  detail"
    lines.append(header)
    lines.append("-" * len(header))
    for name, ok, detail in rows:
        lines.append(f"{name.ljust(w_item)}  {('OK' if ok else 'PROBLEM').ljust(7)}  {detail}")
    return "\n".join(lines)


def render_check_table(rows):
    lines = ["Bootstrap check", ""]
    w_step = max([len("step")] + [len(r["step"]) for r in rows])
    verdicts = [r.get("verdict") or ("PASS" if r["passed"] else "FAIL") for r in rows]
    w_verdict = max([len("verdict")] + [len(v) for v in verdicts])
    header = f"{'step'.ljust(w_step)}  {'verdict'.ljust(w_verdict)}  detail"
    lines.append(header)
    lines.append("-" * len(header))
    for r, verdict in zip(rows, verdicts):
        detail = str(r["detail"]).splitlines()[0] if r["detail"] else ""
        lines.append(f"{r['step'].ljust(w_step)}  {verdict.ljust(w_verdict)}  {detail}")
    n_pass = sum(1 for r in rows if r["passed"])
    lines.append("")
    lines.append(f"PASS: {n_pass} / {len(rows)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--acceptance", action="store_true")

    ap.add_argument(
        "--profile", choices=PROFILES, default=DEFAULT_PROFILE,
        help="bare (default): the harness mechanism plus a bare vault "
             "skeleton, nothing company-specific, no secret file and no "
             "--values-extra needed. full: this workstation reproduced.",
    )
    ap.add_argument("--target", required=True, type=Path)
    ap.add_argument("--home", type=Path, default=None,
                    help="target user home; required for --apply, --check and "
                         "--acceptance (three placed files live under it)")
    ap.add_argument("--secrets-dir", type=Path, default=None)
    ap.add_argument("--repo", default=str(VAULT_ROOT),
                    help="source repo URL or local path for the sparse clone")
    ap.add_argument("--origin-url", default=None,
                    help="remote URL to set on the clone's origin; defaults to "
                         "the --repo source's own origin when --repo is a local path")
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--home-may-exist", action="store_true")
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument("--templates-dir", type=Path, default=None)
    ap.add_argument("--python", default=None)
    ap.add_argument("--values-extra", type=Path, default=None,
                    help="per-machine JSON of {key: value} merged into the "
                         "values file before render (owner or session supplied)")
    ap.add_argument("--claude-cli", default=None,
                    help="path to the claude CLI for the acceptance probe "
                         "(default: 'claude' on PATH)")
    ap.add_argument("--no-probe", action="store_true",
                    help="acceptance mode: skip the claude CLI probe. Acceptance "
                         "still exits 1, because a probe that did not run "
                         "establishes nothing")
    return ap


def _run_dry_run(args):
    """Read the manifest, report it, preflight read-only, print the plan.

    Writes nothing. The previous --dry-run read only the module constants:
    it never opened --manifest and never touched --target, while the A4 CHECK
    and the definition of done both claimed it reproduced this machine's
    layout (architect review 6, adversarial review 14).
    """
    manifest_path = Path(args.manifest) if args.manifest else DEFAULT_MANIFEST
    try:
        manifest = load_manifest(manifest_path)
    except OSError as exc:
        print(f"REFUSED: manifest not readable: {manifest_path}: {exc}")
        return 2
    except ValueError as exc:
        print(f"REFUSED: manifest is not valid JSON: {manifest_path}: {exc}")
        return 2

    print(f"profile: {args.profile}")
    print(render_manifest_summary(manifest, manifest_path, profile=args.profile))
    print()
    print(render_preflight_table(preflight_report(args)))
    print()
    templates_dir = args.templates_dir or default_templates_dir(args.target, args.profile)
    print(render_plan_table(plan_steps(args.profile, templates_dir=templates_dir)))
    return 0


def _run_apply(args):
    ok, msg = step_preflight(args)
    print(f"[preflight] {'DO' if ok else 'REFUSED'}: {msg}")
    if not ok:
        return 2

    manifest = load_manifest(args.manifest)

    ok, msg = step_sparse_clone(manifest, args.target, args.repo,
                                in_place=args.in_place, origin_url=args.origin_url,
                                profile=args.profile)
    print(f"[clone] {'DO' if ok else 'FAIL'}: {msg}")
    if not ok:
        return 1

    ok, msg = step_longpaths(args.target)
    print(f"[longpaths] {'DO' if ok else 'FAIL'}: {msg}")
    if not ok:
        return 1

    ok, msg = step_scaffold(manifest, args.target, profile=args.profile)
    print(f"[scaffold] {'DO' if ok else 'FAIL'}: {msg}")
    if not ok:
        return 1

    if args.home is None:
        print("[values] REFUSED: --home is required for --apply")
        return 2
    values = compute_bootstrap_values(args.target, args.home, args.python)
    templates_dir = args.templates_dir or default_templates_dir(args.target, args.profile)
    try:
        values, unresolved, _entries = apply_values_extra(
            values, templates_dir, args.values_extra, args.target, args.home,
        )
    except ValueError as exc:
        print(f"[values] REFUSED: {exc}")
        return 2
    # Outside the checkout: the values file is paths-only, but it belongs
    # with the rendered output rather than in a tracked directory.
    values_path, unchanged = write_values(values, Path(args.home) / ".claude" / "blueprint")
    note = f"; {len(unresolved)} unresolved: {', '.join(unresolved)}" if unresolved else ""
    print(f"[values] {'SKIP already current' if unchanged else 'DO'}: wrote {values_path}{note}")

    # The five rendered files carry fully resolved credentials. They are
    # staged outside the checkout and deleted in the finally below, so no
    # autosave on the target has anything of ours to commit.
    staging = Path(tempfile.mkdtemp(prefix="blueprint-render-"))
    try:
        ok, msg = step_render_templates(values, args.secrets_dir, templates_dir, staging,
                                        profile=args.profile)
        print(f"[render_templates] {'DO' if ok else 'FAIL'}: {msg}")
        if not ok:
            return 1

        ok, msg = step_place_hook_wiring(staging, args.target, args.home,
                                         profile=args.profile)
        print(f"[place_hook_wiring] {'DO' if ok else 'FAIL'}: {msg}")
        if not ok:
            return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    ok, msg = step_regenerate_inventories(args.target, args.home, profile=args.profile)
    print(f"[regenerate_inventories] {'DO' if ok else 'FAIL'}: {msg}")
    if not ok:
        return 1

    # A missing baseline is an input gap, not a reason to abandon a completed
    # placement: it leaves the ratchet self-initialising exactly as it did
    # before this step existed, and the row says so by name. Every other
    # failure here is a real one and still reads FAIL.
    ok, msg = step_seed_coverage_ratchet(args.target, profile=args.profile)
    print(f"[seed_coverage_ratchet] {'DO' if ok else 'WARN'}: {msg}")

    print()
    print(render_plan_table([
        r for r in plan_steps(args.profile, templates_dir=templates_dir)
        if r["status"] == "NOT-IN-SLICE-1"
    ]))
    print()
    rows, checks_ok = run_check(args.target, args.home, profile=args.profile)
    print(render_check_table(rows))
    return 0 if checks_ok else 2


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.dry_run:
        return _run_dry_run(args)

    if (args.check or args.acceptance) and args.home is None:
        print("REFUSED: --home is required for --check and --acceptance; three of "
              "the five placed files (settings.json, CLAUDE.md, the qmd index.yml) "
              "live under it and nothing else reads them")
        return 2

    if args.check:
        rows, ok = run_check(args.target, args.home, profile=args.profile)
        print(f"profile: {args.profile}")
        print(render_check_table(rows))
        return 0 if ok else 2

    if args.acceptance:
        rows = _acceptance_rows(args.target, args.home, probe=not args.no_probe,
                                cli=args.claude_cli, profile=args.profile)
        print(f"profile: {args.profile}")
        print(render_check_table(rows))
        if args.no_probe:
            print("acceptance not established: probe skipped")
        return 0 if all(r["passed"] for r in rows) else 1

    return _run_apply(args)


if __name__ == "__main__":
    sys.exit(main())
