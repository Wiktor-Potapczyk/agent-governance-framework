"""Blueprint manifest generator and checker (Implementation Phase A1).

Plan of record: Projects/Vault-Maintenance/work/2026-09-22-harness-migration-blueprint-plan.md
(A1 row). File-level plan: Projects/Vault-Maintenance/work/2026-09-22-blueprint-implementation-plan.md
section "Implementation Phase A1: Blueprint manifest".

generate: reads the live `git ls-files -z` population (or an injected list,
for fixtures and tests), classifies every tracked top-level path and every
`.claude/` second-segment path into one of six buckets (core, overlay,
knowledge, schema, instance, archive), derives the sparse-checkout pattern
list, and writes `.claude/blueprint/manifest.json`.

check: validates a manifest on disk for internal consistency (no path left
unclassified, no instance-bucket path leaking into the sparse pattern list),
re-derives it against the live `git ls-files` population when run inside a
git checkout (UNCLASSIFIED_TOP_LEVEL_PATH for a tracked unit the manifest
never classified, STALE_UNIT for the reverse, MISSING_PATTERN for a pattern
deleted from the manifest, STALE_PATTERN for the reverse), SCANS THE CONTENT
of every file the bare patterns select (WORKBOUND_TERM_IN_BARE_TREE), and,
when a `.mcp.json` is available, reuses O17's `check_d` by identity to confirm
no live secret value from it appears in the manifest or any other named
artifact. Exit contract for the CLI: 0 clean, 2 findings, 1 missing or
malformed manifest.

The tree scan (B5) is the half a path rule cannot do, and two reviews on
2026-09-22 measured the gap: the profile's own gate read six placed files
while the profile delivered 1,724, and 154 of those named the employer in
their CONTENT under a perfectly generic file name. Content classification is
therefore derived at generate time (`content_paths`) and every flagged path
becomes a negative sparse pattern, so the exclusion list maintains itself: a
file scrubbed upstream returns to the bare profile on the next regenerate with
no code change, and a new file that names a client leaves it the same way.

A per-bucket count drift is reported as an INFO line carrying both numbers
and does NOT gate: it means the manifest is older than the checkout, which
is the normal state of every clone (the target is cloned at HEAD, the
manifest was written at an earlier commit) and of this vault after any
autosave. The four codes above are classification gaps, which do not heal on
their own; a count drift clears with one regenerate.

The live half answers the A1 CHECK that self-consistency cannot: a newly
tracked top-level path is not `unclassified` in the manifest, it is simply
absent, so both `check` and a fixture-only suite stay green while the
snapshot rots. Outside a git checkout the live half is skipped, which is
reported as skipped, never as passed.

Buckets:
  - core: mechanism code and config that should ship on every clone
    (hooks, scripts, skills, agents, workflows, .github, .obsidian, and
    other .claude/ subsystems not carved out below).
  - overlay: private-only, never-publish machine or scratch state that
    still belongs in a mechanism-only clone (self-heal, the mirrored
    ~/.claude skills and settings snapshot, hookify local drafts, one-off
    scratch files, tmp).
  - knowledge: the wiki-first corpus (Resources/KB), in by default so the
    wiki-first gate is not hollow on a fresh clone.
  - schema: skeleton and doctrine files that define structure without
    carrying vault content (Templates, root doctrine files).
  - instance: vault content that travels only when content follows
    (Projects, Inbox, Clippings, Notes, Areas, Archives, log.md, the rest
    of Resources outside KB, the mirrored ~/.claude memory).
  - archive: retired material kept for history, never shipped to a fresh
    clone (paths naming "archive", "_archived", or a ".bak-" snapshot).

Path granularity: every tracked top-level path is one classification unit,
except `.claude/` and `Resources/`, whose second segment (and, for
`.claude/user-claude-mirror/`, third segment) is its own unit, per
REQ-001 and the A1 override table.

No em dash or en dash appears in this file's output (CON-007).
"""
import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
MANIFEST = VAULT / ".claude" / "blueprint" / "manifest.json"

# The bare profile's own data sidecar, written next to the manifest and
# deliberately NOT checked out by the bare profile. It holds the three lists
# that are, by construction, an inventory of work-bound material: the
# name-derived work paths, the content-derived ones, the bare pattern list
# that embeds both, and the secret FILE NAMES the full templates reference.
# manifest.json keeps counts and a pointer. Moving them is not cosmetic: the
# inventory was measured as the single densest disclosure in the bare
# checkout (184 term hits in one file), and an inventory of what was removed
# is as good as the thing removed.
WORK_PATHS_NAME = "work-paths.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import o17_portability_manifest as o17  # noqa: E402  (path insert must run first)
import blueprint_workbound as wb  # noqa: E402  (path insert must run first)

check_d = o17.check_d  # identity, never a copy (GUD-001)

GENERATOR_VERSION = "1.1.0"

BUCKETS = (
    "core", "overlay", "knowledge", "schema", "instance", "archive", "work",
)
UNCLASSIFIED = "unclassified"

# Reported with both numbers, never counted as a finding and never part of
# the exit code. See _live_findings for why a per-bucket count drift is
# information rather than a defect.
INFORMATIONAL_STALE_COUNT = "STALE_COUNT"

# Deep harness dependencies that live under an instance-bucket directory.
# Found by A4's first mechanism-only run (2026-09-22): the hooks suite imports
# shared.known_names from the AGR project scripts. Found by the adversarial
# review the same day (finding 6): O17's own checker reads its manifest of
# record, its substitution table and its build record out of the same
# instance-bucket work/ directory, so check_b, check_c and check_d all return
# PARSE_FAILURE on a mechanism-only clone and --acceptance can never exit 0.
#
# Each entry is a path relative to the vault root, added to the sparse
# patterns as a positive pattern and recorded in the manifest as
# extra_core_paths. A directory entry ends in "/"; a file entry does not, so
# the three O17 artifacts travel without dragging the whole work/ directory
# (which is instance-bucket content by design) along with them.
EXTRA_CORE_PATHS = (
    "Projects/Agent-Governance-Research/scripts/shared/",
    "Projects/Agent-Governance-Research/work/2026-09-02-o17-portability-manifest.md",
    "Projects/Agent-Governance-Research/work/2026-09-02-o17-substitution-table.md",
    "Projects/Agent-Governance-Research/work/2026-09-02-o17-portability-build.md",
)

# The three O17 artifacts above are a DESCRIPTION OF THIS WORKSTATION: the
# manifest of record enumerates every MCP server, every host and every
# substitution this machine uses, which is 106 term hits and the second
# densest disclosure measured in the bare checkout. A bare device has no such
# description and needs none, so they travel in the full profile only;
# bootstrap_machine's o17 step reports NOT-IN-PROFILE rather than a failure
# when they are absent under bare. The shared/ scripts package stays in both:
# the hooks suite imports it.
EXTRA_CORE_PATHS_BY_PROFILE = {
    "full": EXTRA_CORE_PATHS,
    "bare": ("Projects/Agent-Governance-Research/scripts/shared/",),
}


def extra_core_paths(profile="full"):
    return EXTRA_CORE_PATHS_BY_PROFILE.get(profile, EXTRA_CORE_PATHS)

# Exact-match overrides, checked before the default heuristic. Recorded in
# the manifest under "overrides" so the classification is reviewable.
OVERRIDES = {
    ".gitattributes": "schema",
    ".gitignore": "schema",
    ".github": "core",
    ".obsidian": "core",
    ".maintain-cache.json": "instance",
    ".mcp.json.example": "schema",
    "ARCHITECTURE.md": "schema",
    "CHANGELOG.md": "schema",
    "CLAUDE.md": "schema",
    "ruff.toml": "schema",
    "Resources/KB": "knowledge",
    "Resources": "instance",
    ".claude/self-heal": "overlay",
    ".claude/user-claude-mirror/skills": "overlay",
    ".claude/user-claude-mirror/memory": "instance",
    ".claude/user-claude-mirror/settings.local.json": "overlay",
    ".claude/plugins-snapshot.json": "overlay",
    ".claude/forbidden-tokens.json": "overlay",
    ".claude/tmp": "overlay",
    ".claude/jobs": "overlay",
    ".claude/projects": "overlay",
    ".claude/logs": "overlay",
    ".claude/_archived": "archive",
    ".claude/skills-archived": "archive",
}

# Default heuristic, applied only when no override matches (GOAL-001).
_ARCHIVE_SUBSTRINGS = ("archive", "_archived", ".bak-")
# The tracker-prefixed scratch glob that used to sit here is gone:
# classify_path consults the work-bound classifier BEFORE this heuristic, and
# the tracker prefix term catches every one of those basenames, so the glob
# was unreachable and encoded the same fact twice (architect F10).
_OVERLAY_GLOBS = ("hookify.*.local.md", "m8b-*")
_INSTANCE_NAMED = {
    "Projects", "Inbox", "Clippings", "Notes", "Areas", "Archives", "log.md",
    ".claude/user-claude-mirror",
}
_SCHEMA_NAMED = {"Templates", "Rules.md", "README.md", "ARCHITECTURE.md", "Home.md"}

# Sparse-checkout patterns are derived only from these buckets; instance and
# archive never appear as a positive pattern (REQ-001, A1 GOAL-001).
#
# Two profiles (B2). The full profile reproduces this workstation and is
# unchanged from the single set that shipped on 2026-09-22: the `work` bucket
# is included there, so nothing moved out of a clone that already had it. The
# bare profile answers the owner's ask, verbatim except for the employer's own
# name, which this file does not carry: "FRESH DEVICE NEEDS JUST THE HARNESS
# AND BARE VAULT, NOTHING [EMPLOYER] SPECIFIC." It drops the work bucket
# (company and client material), the knowledge bucket (Resources/KB is the
# vault's own wiki corpus, which is content), and, as always, instance and
# archive.
PROFILES = ("full", "bare")
PROFILE_BUCKETS = {
    "full": ("core", "overlay", "knowledge", "schema", "work"),
    "bare": ("core", "overlay", "schema"),
}
_SPARSE_INCLUDE_BUCKETS = PROFILE_BUCKETS["full"]

# Paths the bare profile deliberately does NOT check out, because the runner
# places a scrubbed twin of each one in its place (bootstrap_machine.py's
# place_hook_wiring, which refuses to overwrite a differing file). Leaving the
# tracked original in the sparse set would make that placement a refusal.
#
# This list and blueprint_render's own twin table are two halves of one fact
# (what bare removes, what bare puts back). They are not imported from each
# other, because the import would run one module's whole dependency chain to
# read one tuple; they are bound by a test that fails if either side is edited
# alone (architect F14).
BARE_REPLACED_PATHS = (
    "CLAUDE.md",
    ".gitignore",
    ".claude/hooks/control-probes.json",
    ".claude/scripts/install-prereqs-manifest.json",
    ".claude/settings.json",
)

# Generated artifacts the bare profile does not ship and the runner rebuilds
# ON THE TARGET instead. Both are inventories of this machine's agents,
# skills, hooks and commands, so the shipped copy names every work-bound one
# of them; regenerating on the target produces the same artifact describing
# the device it is actually on, which is the only version that is true there.
BARE_REGENERATED_PATHS = {
    ".claude/registry.json": ".claude/scripts/generate_registry.py",
    ".claude/hooks/_known_dispatch_names.json":
        ".claude/scripts/generate_known_dispatch_names.py",
    # A Dataview dashboard over vault content, generated from the STATE.md
    # files it summarises. The shipped copy is a project-by-project briefing
    # (ticket keys, commit ids, PR numbers, colleague names, the production
    # host: 128 term hits, the third densest file in the bare checkout). On a
    # target with an empty Projects/ the same generator writes an empty
    # dashboard, which is the only version that is true there.
    "Home.md": ".claude/scripts/generate-home.py",
}

# Paths the bare profile excludes by explicit ruling rather than by a content
# hit, each with the reason. A content hit would catch most of them anyway;
# naming them here means the ruling survives a scrub of the file that happens
# to remove the term while leaving the reason intact.
BARE_EXPLICIT_EXCLUDE = {
    ".claude/blueprint/templates/full/":
        "the full profile's payload: a complete description of this workstation's "
        "wiring, secret file names and permission grants, riding inside the "
        "directory that implements the scrub (architect F2, adversarial F3)",
    ".claude/blueprint/settings.local.portable.json":
        "the full profile's source of record for the wiring, same content as the "
        "template above",
    ".claude/blueprint/workbound-terms.json":
        "the term list itself: an enumeration of every name the owner wants kept "
        "off a fresh device is the document a stranger would want",
    ".claude/blueprint/" + WORK_PATHS_NAME:
        "the inventory of what the bare profile removes, which is as disclosive "
        "as the thing removed",
    ".claude/skills/repo-sync/":
        "the public-push NDA gate. A bare device has no private repository to "
        "push to and does not need it, and the gate is by construction an "
        "enumeration of every sensitive name, spelling and ticket prefix "
        "(adversarial F16)",
    ".claude/hooks/sdlc-evidence-verifier.py":
        "a client production VPS with its root login, SSH key path, container "
        "name, public host and deploy directory, in a hook that probes that one "
        "deployment (adversarial F2)",
    ".claude/hooks/test_sdlc_evidence_verifier.py":
        "the same host and paths, in the test",
    ".claude/docs/harness/hook/sdlc-evidence-verifier.md":
        "the generated doc page for the same hook",
    ".claude/hooks/_irreversible_surface_local.json":
        "the instance-specific half of the Gate-1 surface: the MCP tool names of "
        "the employer's accounts and the two internal hosts. The MECHANISM ships; "
        "the names do not, and on a device without them those tools do not exist",
}

# Belt-and-suspenders exclusion: even though the memory unit is bucketed
# instance and so never becomes a positive pattern, the plan of record's
# probe recorded this negative pattern explicitly, so it is written every
# time, not only when the unit happens to be present in the input.
INSTANCE_EXCLUDE_PATTERN = "!/.claude/user-claude-mirror/memory/"

# Machine-local items named in the plan of record's A1 row, each with the
# plan step that provisions it on a target machine. Filled in full here
# (A1 reserves the field); no value, only names and provisioning pointers.
MACHINE_LOCAL = [
    {
        "name": "hook wiring",
        "provisioning_step": (
            "A3 converts .claude/settings.local.json to the $CLAUDE_PROJECT_DIR form on a "
            "scratch .claude/blueprint/settings.local.portable.json; A4's "
            "step_place_hook_wiring places it on the target machine"
        ),
    },
    {
        "name": "MCP file",
        "provisioning_step": (
            "A2 renders mcp.json.tmpl from the live .mcp.json with secret values replaced by "
            "{{secret:<file>}} placeholders; A4's step_render_templates writes .mcp.json from "
            "the template plus secrets/ on the target machine"
        ),
    },
    {
        "name": "user settings and CLAUDE.md",
        "provisioning_step": (
            "A2 renders user-settings.json.tmpl and user-claude-md.tmpl from "
            "~/.claude/settings.json and ~/.claude/CLAUDE.md; A4's step_render_templates writes "
            "them under the target ~/.claude"
        ),
    },
    {
        "name": "trust",
        "provisioning_step": (
            "Phase B step 4: opening the vault in Claude Code once on the target machine writes "
            "the ~/.claude.json trust record; not scripted by the runner"
        ),
    },
    {
        "name": "plugins",
        "provisioning_step": (
            "A4 names the 31-plugin install as a later slice (NOT-IN-SLICE-1); Phase B step 4 "
            "installs marketplaces and plugins on the target machine"
        ),
    },
    {
        "name": "qmd index",
        "provisioning_step": (
            "A2 renders qmd-index.yml.tmpl with {{vault}}/{{home}} placeholders; A4's "
            "step_render_templates writes ~/.config/qmd/index.yml, then Phase B step 4 runs the "
            "qmd index build"
        ),
    },
    {
        "name": "tasks",
        "provisioning_step": (
            "A4 names the scheduled-tasks-archive XML replay as a later slice "
            "(NOT-IN-SLICE-1); Phase B step 5 opts in per task with the vault path rewritten"
        ),
    },
    {
        "name": "interpreters",
        "provisioning_step": (
            "Phase B step 1: install Python 3.14 at C:\\Program Files\\Python314 and Node "
            "(current LTS or 25) on the target machine before running the runner"
        ),
    },
    {
        "name": "npm globals",
        "provisioning_step": (
            "A4 names the npm global installs (the four packages named in "
            ".claude/scripts/install-prereqs-manifest.json) as a later slice "
            "(NOT-IN-SLICE-1); Phase B step 3 installs them via the runner"
        ),
    },
    {
        "name": "core.longpaths",
        "provisioning_step": (
            "A4's step_longpaths sets git config core.longpaths true on the target clone; "
            "Phase B step 1 sets the Windows-wide LongPathsEnabled policy, which needs admin "
            "rights"
        ),
    },
]


class ManifestError(Exception):
    """Raised by check() when the manifest is missing or malformed."""


def _unit_hash(unit):
    """A short, name-free fingerprint of a classification unit. Lets a device
    that does not carry the work-bucket names still recognise one when it
    re-derives it."""
    return hashlib.sha256(str(unit).encode("utf-8")).hexdigest()[:16]


def unit_for(path):
    """Map a tracked file path to its classification unit.

    `.claude/` and `Resources/` expand one segment (REQ-001 plus the KB
    split); `.claude/user-claude-mirror/` expands one further segment so
    its skills, memory and settings.local.json sub-paths classify
    independently. Every other top-level path is its own unit.
    """
    parts = path.split("/")
    if parts[0] == ".claude" and len(parts) > 1:
        if parts[1] == "user-claude-mirror" and len(parts) > 2:
            return ".claude/user-claude-mirror/" + parts[2]
        return ".claude/" + parts[1]
    if parts[0] == "Resources":
        if len(parts) > 1 and parts[1] == "KB":
            return "Resources/KB"
        return "Resources"
    return parts[0]


def classify_path(path):
    """Return the bucket for one classification unit, or UNCLASSIFIED.

    Exact-match override dict first (OVERRIDES), then the default
    heuristic in the precedence order documented in the A1 plan: archive
    naming, private-only overlay naming, the knowledge and named-instance
    lists, the named-schema list, then a `.claude/`-rooted default of
    core. Anything matching none of these is UNCLASSIFIED, which is the
    signal REQ-001's completeness check acts on.
    """
    if path in OVERRIDES:
        return OVERRIDES[path]

    # B2: a unit whose own path carries a work-bound term is company or
    # client material, whatever the default heuristic would have said. Placed
    # after OVERRIDES so an explicit owner ruling still wins, and before the
    # heuristic so a tracker-prefixed scratch file stops reading as overlay.
    if wb.classify_path(path) == wb.WORK_BOUND:
        return "work"

    basename = path.rsplit("/", 1)[-1].lower()
    if any(s in basename for s in _ARCHIVE_SUBSTRINGS):
        return "archive"
    if any(fnmatch.fnmatch(basename, g) for g in _OVERLAY_GLOBS):
        return "overlay"
    if path == "Resources/KB":
        return "knowledge"
    if path in _INSTANCE_NAMED:
        return "instance"
    if path in _SCHEMA_NAMED:
        return "schema"
    if path.startswith(".claude/"):
        return "core"
    if path.startswith("Resources"):
        return "instance"
    return UNCLASSIFIED


def _pattern_for(unit, is_dir):
    return "/" + unit + "/" if is_dir else "/" + unit


def content_paths(units, buckets, vault_root, profile="bare"):
    """Sorted list of paths the profile would ship whose CONTENT carries a
    work-bound term or shape.

    This is the measurement architect F2 and adversarial F1 both asked for,
    turned into an exclusion. A path rule cannot see it: the files are named
    `settings.json`, `Home.md`, `registry.json` and `control-probes.json`, and
    the employer is in the fifth line rather than in the name.

    Two collapses keep the pattern list readable. A flagged `SKILL.md` takes
    its whole skill directory with it, because a skill without its SKILL.md is
    not a skill. A flagged file under an already-flagged directory is dropped
    from the list, because the directory pattern covers it.

    Returns [] when no term data is available (a device with no term list
    cannot make this judgement and must not pretend the answer is "none"):
    the caller reports that state rather than writing an empty list as fact.
    """
    if vault_root is None or not wb.terms_available():
        return []
    # The manifest is excluded from its OWN derivation: generate() rewrites it
    # in this same run, so scanning the version on disk would classify the
    # PREVIOUS content and could exclude the manifest from the profile that
    # needs it. The newly written one is not unchecked: check()'s tree scan
    # reads it like every other file, so a manifest that does carry a term is
    # a finding rather than a silent exclusion.
    self_written = (".claude/blueprint/manifest.json",)
    population = [
        p for p in sorted(_all_files(units))
        if ships_in_profile(p, buckets, profile)
        and p not in BARE_REGENERATED_PATHS
        and p not in BARE_REPLACED_PATHS
        and p not in self_written
        and not _explicitly_excluded(p)
    ]
    flagged = {h["path"] for h in wb.scan_tree(vault_root, population)}
    out = set()
    for path in flagged:
        if path.rsplit("/", 1)[-1] == "SKILL.md" and "/" in path:
            out.add(path.rsplit("/", 1)[0] + "/")
        else:
            out.add(path)
    # Companions are owed to every excluded hook, whichever list excluded it:
    # a hook dropped by RULING leaves its tests behind exactly as one dropped
    # by content does, and the target's hook suite fails the same way.
    ruled = {p for p in BARE_EXPLICIT_EXCLUDE if not p.endswith("/")}
    out |= _companions(out | ruled, units, vault_root)
    dirs = [p for p in out if p.endswith("/")]
    return sorted(p for p in out if not any(p != d and p.startswith(d) for d in dirs))


def _companions(flagged, units, vault_root=None):
    """The files that must leave with an excluded HOOK: its tests and its
    generated doc page.

    Measured on the first end-to-end bare apply: excluding two hook scripts
    whose content named a client left three test files behind that import
    them, and the hooks suite reported three failures nobody had a reason
    for. A hook and its tests are one unit even when only one of them
    happens to carry the term.
    """
    tracked = set(_all_files(units))
    out = set()
    for path in flagged:
        if not (path.startswith(".claude/hooks/") and path.endswith(".py")):
            continue
        stem = path.rsplit("/", 1)[-1][:-3]
        snake = stem.replace("-", "_")
        for candidate in tracked:
            name = candidate.rsplit("/", 1)[-1]
            if candidate.startswith(".claude/hooks/") and name.startswith("test_") \
                    and snake in name.replace("-", "_"):
                out.add(candidate)
        doc = f".claude/docs/harness/hook/{stem}.md"
        if doc in tracked:
            out.add(doc)
        # A test does not have to be NAMED after its subject to import it:
        # two of this hook suite's files are named for the behaviour they
        # pin, not for the script, and stayed behind as unexplained failures
        # on the target. The reference in the file body is the reliable link.
        if vault_root is None:
            continue
        needle = path.rsplit("/", 1)[-1]
        for candidate in tracked:
            name = candidate.rsplit("/", 1)[-1]
            if not (candidate.startswith(".claude/hooks/")
                    and name.startswith("test_") and name.endswith(".py")):
                continue
            if candidate in out:
                continue
            try:
                body = (Path(vault_root) / candidate).read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
            if needle in body:
                out.add(candidate)
    return out


def _explicitly_excluded(path):
    """True when `path` is under one of the explicitly excluded bare paths."""
    for prefix in BARE_EXPLICIT_EXCLUDE:
        if path == prefix or (prefix.endswith("/") and path.startswith(prefix)):
            return True
    return False


def work_paths(units, buckets, profile="bare"):
    """Sorted, collapsed list of work-bound paths that the profile's positive
    patterns would otherwise pull in.

    Only files inside a unit the profile SHIPS are listed: a work-bound file
    under Projects/ needs no negative pattern, because no positive pattern
    ever reaches it. Each entry is either a directory (when a whole
    work-bound directory sits under a generic unit, so one pattern covers it)
    or a single file (the tracker guard hook, whose parent directory is pure
    mechanism).
    """
    include = PROFILE_BUCKETS[profile]
    out = set()
    for unit, files in units.items():
        if buckets.get(unit) not in include:
            continue
        for path in files:
            if wb.classify_path(path) != wb.WORK_BOUND:
                continue
            out.add(wb.work_dir_prefix(path) or path)
    return sorted(out)


def _sparse_patterns(units, buckets, profile="full", content=()):
    """The sparse-checkout pattern list for one profile.

    full: every core, overlay, knowledge, schema and work unit, plus the
    extra core paths, plus the one standing negative pattern. Byte-identical
    to the single list that shipped before profiles existed.

    bare: core, overlay and schema only, minus BARE_REPLACED_PATHS, plus its
    own (shorter) extra core paths, plus one negative pattern per work-bound
    path the positive patterns would otherwise pull in, by NAME (work_paths),
    by CONTENT (`content`), and by explicit ruling (BARE_EXPLICIT_EXCLUDE,
    BARE_REGENERATED_PATHS).
    """
    positive = []
    for unit in sorted(units):
        if buckets.get(unit) not in PROFILE_BUCKETS[profile]:
            continue
        if profile == "bare" and unit in BARE_REPLACED_PATHS:
            continue
        files = units[unit]
        is_dir = any(f != unit for f in files)
        positive.append(_pattern_for(unit, is_dir))
    positive.extend("/" + extra for extra in extra_core_paths(profile))

    negative = [INSTANCE_EXCLUDE_PATTERN]
    if profile == "bare":
        # A work path is a directory unless it is itself a tracked file:
        # work_dir_prefix returns an ancestor directory, and everything else
        # it returns is the file path it was given.
        tracked = set(_all_files(units))
        excluded = set(work_paths(units, buckets, profile="bare"))
        excluded |= {p for p in content}
        excluded |= set(BARE_EXPLICIT_EXCLUDE)
        excluded |= set(BARE_REGENERATED_PATHS)
        # A replaced path inside a shipped unit needs a negative pattern of
        # its own; one that IS a unit was already skipped above.
        excluded |= {p for p in BARE_REPLACED_PATHS if unit_for(p) != p}
        for path in sorted(excluded):
            is_dir = path.endswith("/") or path not in tracked
            negative.append("!" + _pattern_for(path.rstrip("/"), is_dir))
    return positive + negative


def _all_files(units):
    for files in units.values():
        yield from files


def ships_in_profile(path, buckets, profile, content_excluded=()):
    """True when `path` survives `profile`'s pattern set. The file-count
    numbers in the manifest's profiles block are derived from this, rather
    than from a per-bucket sum that cannot see a negative pattern.

    `content_excluded` is the content-derived exclusion list; it is a
    parameter rather than a module read because content_paths() calls this
    function to build the population it scans, and a self-referential default
    would make the first derivation depend on its own output.
    """
    for extra in extra_core_paths(profile):
        if path == extra or path.startswith(extra):
            return True
    unit = unit_for(path)
    if buckets.get(unit) not in PROFILE_BUCKETS[profile]:
        return False
    if profile == "bare":
        if unit in BARE_REPLACED_PATHS or path in BARE_REPLACED_PATHS:
            return False
        if path in BARE_REGENERATED_PATHS:
            return False
        if _explicitly_excluded(path):
            return False
        if wb.classify_path(path) == wb.WORK_BOUND:
            return False
        for entry in content_excluded:
            if path == entry or (entry.endswith("/") and path.startswith(entry)):
                return False
    return True


def _profiles_block(units, buckets, patterns_by_profile, content=()):
    ls_files = list(_all_files(units))
    return {
        profile: {
            "buckets": list(PROFILE_BUCKETS[profile]),
            "patterns_key": (
                "sparse_patterns" if profile == "full" else "sparse_patterns_bare"
            ),
            "patterns_file": None if profile == "full" else WORK_PATHS_NAME,
            "pattern_count": len(patterns_by_profile[profile]),
            "file_count": sum(
                1 for p in ls_files
                if ships_in_profile(
                    p, buckets, profile,
                    content_excluded=(content if profile == "bare" else ()),
                )
            ),
            "replaced_paths": (
                [] if profile == "full" else list(BARE_REPLACED_PATHS)
            ),
            "regenerated_paths": (
                [] if profile == "full" else sorted(BARE_REGENERATED_PATHS)
            ),
            "templates_subdir": profile,
        }
        for profile in PROFILES
    }


def work_paths_sidecar(manifest_path=MANIFEST):
    """The bare data sidecar's path for a given manifest path."""
    return Path(manifest_path).parent / WORK_PATHS_NAME


def read_sidecar(manifest_path=MANIFEST):
    """The sidecar's contents, or None when it is absent (the normal state of
    a bare device, which deliberately does not check it out) or unreadable."""
    p = work_paths_sidecar(manifest_path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None


def patterns_for(manifest, profile, manifest_path=MANIFEST):
    """The pattern list a runner should use for `profile`.

    full reads the manifest's own key. bare reads the sidecar named in the
    manifest's profiles block, because the bare list embeds the name of every
    path it excludes and that inventory does not travel. A bare device
    therefore cannot re-derive its own pattern list, which is correct: it has
    no reason to, and the checker reports the comparison as skipped rather
    than passed.
    """
    if profile not in PROFILES:
        raise ManifestError(f"unknown profile: {profile!r} (known: {', '.join(PROFILES)})")
    block = (manifest.get("profiles") or {}).get(profile) or {}
    key = block.get("patterns_key") or (
        "sparse_patterns" if profile == "full" else "sparse_patterns_bare"
    )
    if key in manifest:
        return list(manifest.get(key) or [])
    sidecar = read_sidecar(manifest_path)
    if sidecar is None:
        raise ManifestError(
            f"profile {profile!r} keeps its pattern list in {WORK_PATHS_NAME}, which is "
            f"not present next to {manifest_path}. That file is excluded from the bare "
            "profile on purpose; run the manifest generator on a source checkout."
        )
    return list(sidecar.get(key) or [])


def build(ls_files, vault_root=None):
    """Classify a tracked-file population and derive the manifest body.

    `vault_root`, when given, enables the CONTENT derivation: every file the
    bare patterns would select is read and scanned, and every flagged path
    becomes an exclusion. Without it (fixtures, and any caller with no tree to
    read) the content list is empty and `content_scanned` is False, which the
    checker reports rather than treating as a clean result.
    """
    units = {}
    for p in ls_files:
        u = unit_for(p)
        units.setdefault(u, []).append(p)

    buckets = {u: classify_path(u) for u in units}

    counts = {b: 0 for b in BUCKETS}
    counts[UNCLASSIFIED] = 0
    for u, files in units.items():
        counts[buckets[u]] += len(files)

    content = content_paths(units, buckets, vault_root, profile="bare")
    scanned = bool(vault_root) and wb.terms_available()

    patterns = {
        p: _sparse_patterns(units, buckets, profile=p, content=content)
        for p in PROFILES
    }

    return {
        "buckets": buckets,
        "counts": counts,
        "sparse_patterns": patterns["full"],
        "sparse_patterns_bare": patterns["bare"],
        "work_paths": work_paths(units, buckets, profile="bare"),
        "content_paths": content,
        "content_scanned": scanned,
        "profiles": _profiles_block(units, buckets, patterns, content=content),
        "overrides": dict(OVERRIDES),
        "extra_core_paths": list(EXTRA_CORE_PATHS),
    }


def _run_git_ls_files(vault_root):
    """Live `git ls-files -z`. -z avoids the quoting bug found in planning:

    plain `git ls-files` quotes paths needing escaping, which mis-splits
    under naive parsing (for example under `awk -F/`) into spurious rows.
    """
    proc = subprocess.run(
        ["git", "-C", str(vault_root), "ls-files", "-z"],
        capture_output=True, check=True,
    )
    raw = proc.stdout.decode("utf-8")
    return [p for p in raw.split("\x00") if p]


def generate(date, out_path=MANIFEST, ls_files=None, vault_root=VAULT):
    """Build and write the manifest AND its bare data sidecar. Deterministic
    given the same date, ls_files and tree: no wall-clock read, sorted lists,
    sort_keys JSON.
    """
    if ls_files is None:
        ls_files = _run_git_ls_files(vault_root or VAULT)
    if not ls_files:
        raise ManifestError("empty ls-files population")

    body = build(ls_files, vault_root=vault_root)
    # The secret FILE NAMES are blueprint_render's field ("filled_by"). They
    # live in the sidecar, not the manifest: every one of them is derived from
    # a server name, so the list names the instances. Regeneration preserves
    # whatever is already there rather than blanking a list this module does
    # not own.
    out_path = Path(out_path)
    prior_sidecar = read_sidecar(out_path) or {}
    secrets_items = list(prior_sidecar.get("secrets_items") or [])

    # The work-bucket unit map and BOTH pattern lists name work-bound paths by
    # construction (a tracker-prefixed scratch file is a unit, and the full
    # profile ships it, so it is a positive pattern). They go to the sidecar
    # with everything else that is an inventory of the removed material.
    work_buckets = {u: b for u, b in body["buckets"].items() if b == "work"}
    public_buckets = {u: b for u, b in body["buckets"].items() if b != "work"}

    manifest = {
        "generated_at": date,
        "generator_version": GENERATOR_VERSION,
        "buckets": public_buckets,
        "profiles": body["profiles"],
        "extra_core_paths": body["extra_core_paths"],
        "extra_core_paths_bare": list(extra_core_paths("bare")),
        "machine_local": MACHINE_LOCAL,
        "secrets": {
            "count": len(secrets_items),
            "filled_by": "blueprint_render",
            "items_file": WORK_PATHS_NAME,
        },
        "bare_data_file": WORK_PATHS_NAME,
        # A NAME-FREE record of the units the manifest deliberately does not
        # list. A bare device re-derives its own unit map and would otherwise
        # report every one of them as "tracked live, never classified"; the
        # hash says "this one is accounted for" without carrying the name.
        "work_unit_hashes": sorted(_unit_hash(u) for u in work_buckets),
        "bare_excluded_counts": {
            "by_name": len(body["work_paths"]),
            "by_content": len(body["content_paths"]),
            "by_ruling": len(BARE_EXPLICIT_EXCLUDE),
            "regenerated_on_target": len(BARE_REGENERATED_PATHS),
            "replaced_by_a_twin": len(BARE_REPLACED_PATHS),
            "content_scanned": body["content_scanned"],
        },
        "counts": body["counts"],
        "overrides": body["overrides"],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    out_path.write_text(text, encoding="utf-8", newline="\n")

    sidecar = {
        "_comment": (
            "The bare profile's own data, kept out of manifest.json because every "
            "list here names the material the bare profile removes, and an "
            "inventory of what was removed is as disclosive as the thing itself. "
            "The bare sparse patterns exclude this file. A device without it "
            "cannot re-derive the bare pattern list, and the checker reports that "
            "comparison as skipped rather than passed."
        ),
        "generated_at": date,
        "sparse_patterns": body["sparse_patterns"],
        "sparse_patterns_bare": body["sparse_patterns_bare"],
        "work_buckets": work_buckets,
        "work_paths": body["work_paths"],
        "content_paths": body["content_paths"],
        "content_scanned": body["content_scanned"],
        "explicit_exclusions": dict(BARE_EXPLICIT_EXCLUDE),
        "regenerated_paths": dict(BARE_REGENERATED_PATHS),
        "secrets_items": secrets_items,
    }
    work_paths_sidecar(out_path).write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return manifest


def _bucket_findings(data, bare_patterns=()):
    """Self-consistency findings over an in-memory manifest dict."""
    findings = []
    buckets = data.get("buckets") or {}
    for unit in sorted(buckets):
        bucket = buckets[unit]
        if bucket == UNCLASSIFIED or bucket not in BUCKETS:
            findings.append(("UNCLASSIFIED_TOP_LEVEL_PATH", unit))

    for pat in data.get("sparse_patterns") or []:
        if pat.startswith("!"):
            continue
        key = pat.lstrip("/").rstrip("/")
        if buckets.get(key) == "instance":
            findings.append(("INSTANCE_IN_PATTERN", pat))

    # B2 CHECK: no core unit carries a term in its own path. A unit that does
    # is company or client material sitting in the bucket that ships on every
    # clone, which is the exact failure the bare profile exists to prevent.
    for unit in sorted(buckets):
        if buckets[unit] != "core":
            continue
        if wb.classify_path(unit) == wb.WORK_BOUND:
            findings.append((
                "WORKBOUND_TERM_IN_CORE_UNIT",
                f"{unit}: core bucket, path carries "
                f"{', '.join(wb.term_matches(unit))}",
            ))

    for pat in bare_patterns or []:
        if pat.startswith("!"):
            continue
        key = pat.lstrip("/").rstrip("/")
        if buckets.get(key) in ("instance", "archive", "work", "knowledge"):
            findings.append((
                "NON_BARE_BUCKET_IN_BARE_PATTERN",
                f"{pat}: bucket {buckets.get(key)}",
            ))
        if wb.classify_path(key) == wb.WORK_BOUND:
            findings.append((
                "WORKBOUND_TERM_IN_BARE_PATTERN",
                f"{pat}: carries {', '.join(wb.term_matches(key))}",
            ))
    return findings


def _stub_block_for_check_d():
    """Throwaway artifact satisfying o17 check_d's `_read_block` contract.

    blueprint_manifest.json carries no mcp_servers section (an O17-specific
    concept); this stub supplies an empty one so check_d's first sub-check
    is a harmless no-op while its secret-value scan runs for real.
    """
    fd, raw_path = tempfile.mkstemp(suffix=".md", prefix="blueprint-check-d-stub-")
    path = Path(raw_path)
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write("```json\n" + json.dumps({"sections": {"mcp_servers": []}}) + "\n```\n")
    return path


def _live_findings(data, ls_files, informational_out=None, vault_root=None,
                   bare_patterns=None):
    """Re-derive the manifest from a tracked-file population and report the
    drift. This is the half of the A1 CHECK ("every git ls-files top-level
    entry is classified") that a self-consistency pass cannot see: a newly
    tracked top-level path is absent from the manifest rather than
    UNCLASSIFIED, and a pattern deleted from the manifest leaves no trace at
    all.

    Four of the five codes are real findings: a unit, or a pattern, that
    exists on one side and not the other is a classification gap, and a
    classification gap does not heal by itself.

    STALE_COUNT is the fifth, and it is INFORMATIONAL, never a finding. A
    per-bucket count differs whenever the tracked population has moved since
    the manifest was generated, which on this vault is every autosave commit,
    and on a target machine is guaranteed: the clone is at HEAD while
    manifest.json was written at an earlier commit. Counting that as a
    failure would make bootstrap_machine.py's own
    step_blueprint_manifest_check red on every fresh clone, teaching the
    owner to stop reading the exit code, which is the exact habit the
    architect review named as the worst outcome available. The numbers are
    still printed, both of them, so a large drift is visible; they simply do
    not gate. Append targets: `informational_out` when given, dropped
    otherwise.
    """
    findings = []
    live = build(ls_files, vault_root=vault_root)

    man_buckets = data.get("buckets") or {}
    # A work-bucket unit's NAME is work-bound material, so the manifest does
    # not carry it when the sidecar is absent. Reporting it as unclassified
    # there would be reporting the profile working as a defect; the count is
    # still visible through the bucket counts.
    skip_work = bare_patterns is None
    known_hashes = set(data.get("work_unit_hashes") or [])
    work_skipped = 0
    for unit in sorted(live["buckets"]):
        if unit not in man_buckets:
            if skip_work and (live["buckets"][unit] == "work"
                              or _unit_hash(unit) in known_hashes):
                work_skipped += 1
                continue
            findings.append((
                "UNCLASSIFIED_TOP_LEVEL_PATH",
                f"{unit}: tracked live, absent from the manifest (never classified)",
            ))
    if work_skipped and informational_out is not None:
        informational_out.append((
            "WORK_UNITS_NOT_IN_MANIFEST",
            f"{work_skipped} work-bucket unit(s) are classified live and named only in "
            f"{WORK_PATHS_NAME}, which this device does not carry",
        ))
    for unit in sorted(man_buckets):
        if unit not in live["buckets"]:
            findings.append((
                "STALE_UNIT",
                f"{unit}: in the manifest, no longer tracked live",
            ))

    man_counts = data.get("counts") or {}
    for bucket in sorted(live["counts"]):
        live_n = live["counts"][bucket]
        man_n = man_counts.get(bucket)
        if man_n != live_n and informational_out is not None:
            informational_out.append((
                INFORMATIONAL_STALE_COUNT,
                f"{bucket}: manifest {man_n}, live {live_n}",
            ))

    # Both profiles are re-derived, with their own codes: a bare-only gap
    # (a work path that stopped being excluded) is invisible in the full
    # list, and the bare list is the one a fresh device clones by default.
    # The bare list is compared only when it is actually available: it lives
    # in the sidecar, which a bare device does not carry, and comparing an
    # absent list against a derived one would report every pattern as missing.
    comparisons = []
    if data.get("sparse_patterns"):
        comparisons.append(("sparse_patterns", "MISSING_PATTERN", "STALE_PATTERN", None))
    elif informational_out is not None:
        informational_out.append((
            "PATTERNS_UNAVAILABLE",
            f"the pattern lists live in {WORK_PATHS_NAME}, which is not present next "
            "to the manifest, so neither profile's list was compared (expected on a "
            "bare device, which excludes that file on purpose)",
        ))
    if bare_patterns is not None:
        comparisons.append((
            "sparse_patterns_bare", "MISSING_PATTERN_BARE", "STALE_PATTERN_BARE",
            list(bare_patterns),
        ))
    for key, missing_code, stale_code, override in comparisons:
        man_patterns = override if override is not None else list(data.get(key) or [])
        live_patterns = live[key]
        for pat in live_patterns:
            if pat not in man_patterns:
                findings.append((
                    missing_code,
                    f"{pat}: derived from the live population, absent from the manifest",
                ))
        live_set = set(live_patterns)
        for pat in man_patterns:
            if pat not in live_set:
                findings.append((
                    stale_code,
                    f"{pat}: in the manifest, not derivable from the live population",
                ))
    return findings


def _bare_tree_findings(ls_files, vault_root, sidecar, informational_out=None):
    """WORKBOUND_TERM_IN_BARE_TREE over every file the bare patterns select.

    The gate the two 2026-09-22 reviews proved missing: the profile's own
    scan read six placed files while the profile delivered 1,724. This reads
    the CONTENT of all of them. It is skipped, and says so, in the two states
    where it cannot mean anything: no tree to read, and no term data on this
    device (an empty term list matches nothing, and reporting that as zero
    hits would be the vacuous pass the reviews called the worst outcome).
    """
    if vault_root is None:
        return []
    if not wb.terms_available():
        if informational_out is not None:
            informational_out.append((
                "BARE_TREE_SCAN_SKIPPED",
                "no work-bound term data on this device, so the bare tree scan "
                "cannot run; 0 hits from an empty term list is not a result",
            ))
        return []
    units = {}
    for path in ls_files:
        units.setdefault(unit_for(path), []).append(path)
    buckets = {u: classify_path(u) for u in units}
    content = list((sidecar or {}).get("content_paths") or [])
    population = [
        path for path in sorted(ls_files)
        if ships_in_profile(path, buckets, "bare", content_excluded=content)
    ]
    findings = []
    for hit in wb.scan_tree(vault_root, population):
        findings.append((
            "WORKBOUND_TERM_IN_BARE_TREE",
            f"{hit['path']}:{hit['line']}: carries {hit['term']!r} "
            "(content, not path: exclude it from bare, scrub it, or twin it)",
        ))
    return findings


def live_ls_files(vault_root=VAULT):
    """The live tracked-file population, or None when this is not a usable
    git checkout (a mechanism-only tarball, or git absent). None means the
    live half of check() is skipped, never that it passed."""
    try:
        return _run_git_ls_files(vault_root)
    except (OSError, subprocess.SubprocessError):
        return None


def check(manifest_path=MANIFEST, mcp_path=None, extra_artifact_paths=None,
          ls_files=None, vault_root=VAULT, verify_live=True,
          informational_out=None, content_root=None):
    """Validate a manifest on disk. Raises ManifestError on missing or
    malformed input; otherwise returns a findings list (empty means clean).

    When `ls_files` is given, or `verify_live` is true and this is a git
    checkout, the manifest is also re-derived against that population
    (_live_findings). Passing ls_files is how the suite exercises the live
    half against a fixture without shelling out to git.

    `informational_out`, when given, collects the (code, detail) rows that
    are reported but never gate: STALE_COUNT, and the two "this could not be
    checked here" rows (BARE_PATTERNS_UNAVAILABLE, BARE_TREE_SCAN_SKIPPED).
    Nothing in the returned findings list is informational, so `if check(...)`
    stays a correct pass/fail test for every caller.

    WORKBOUND_TERM_IN_BARE_TREE is the new gating finding: every file the bare
    patterns select is read and scanned, and a hit is a defect rather than a
    statistic. It can only fire when the manifest is stale against the tree,
    because generate() turns every hit into an exclusion; that is the point,
    and it is why the code names the path and the line rather than a count.
    """
    p = Path(manifest_path)
    if not p.is_file():
        raise ManifestError(f"manifest missing: {p}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ManifestError(f"manifest malformed: {p}: {exc}") from exc

    sidecar = read_sidecar(p)
    if sidecar is not None:
        # One merged view for every check below: the sidecar is the same
        # manifest, split so the half that names work-bound material does not
        # travel. A device without it is checked on what it has.
        data = dict(data)
        data["buckets"] = {**(data.get("buckets") or {}),
                           **(sidecar.get("work_buckets") or {})}
        data["sparse_patterns"] = list(sidecar.get("sparse_patterns") or [])
    bare_patterns = None if sidecar is None else list(sidecar.get("sparse_patterns_bare") or [])
    findings = _bucket_findings(data, bare_patterns=bare_patterns or [])

    if ls_files is None and verify_live:
        ls_files = live_ls_files(vault_root)
    if ls_files:
        findings += _live_findings(
            data, ls_files, informational_out=informational_out,
            vault_root=content_root, bare_patterns=bare_patterns,
        )
        findings += _bare_tree_findings(
            ls_files, content_root, sidecar, informational_out=informational_out,
        )

    mcp = Path(mcp_path) if mcp_path is not None else o17.MCP
    if mcp.is_file():
        artifact_paths = [str(p)] + list(extra_artifact_paths or [])
        stub = _stub_block_for_check_d()
        try:
            findings += list(check_d(str(stub), str(mcp), artifact_paths))
        finally:
            stub.unlink(missing_ok=True)
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--date", required=True)
    g.add_argument("--out", default=str(MANIFEST))

    c = sub.add_parser("check")
    c.add_argument("--manifest", default=str(MANIFEST))
    c.add_argument(
        "--no-verify-live", action="store_true",
        help="skip the live git ls-files re-derivation (self-consistency only)",
    )

    args = ap.parse_args()

    if args.cmd == "generate":
        manifest = generate(args.date, out_path=args.out)
        print(f"manifest: {args.out}")
        print(f"bare data sidecar: {work_paths_sidecar(args.out)}")
        print(json.dumps(manifest["counts"], indent=2, sort_keys=True))
        print("bare exclusions: " + json.dumps(
            manifest["bare_excluded_counts"], sort_keys=True,
        ))
        if not manifest["bare_excluded_counts"]["content_scanned"]:
            print(
                "WARNING: the content scan did not run (no term data on this "
                "device), so the bare exclusion list is name-derived only"
            )
        return 0

    # Resolve the live population once here rather than letting check() call
    # git a second time just to report whether it was skipped.
    ls_files = None if args.no_verify_live else live_ls_files()
    if not args.no_verify_live and ls_files is None:
        print("LIVE_VERIFY: skipped (not a usable git checkout)")
    informational = []
    try:
        # The content scan reads the tree the population came from. It runs
        # for the vault's OWN manifest, where those two are the same thing;
        # pointed at a manifest somewhere else (a fixture, a copy under
        # review) there is no matching tree to read and the scan is skipped
        # rather than run against the wrong one.
        own_manifest = Path(args.manifest).resolve() == Path(MANIFEST).resolve()
        findings = check(
            manifest_path=args.manifest, ls_files=ls_files, verify_live=False,
            informational_out=informational,
            content_root=(VAULT if own_manifest else None),
        )
        if not own_manifest:
            print(
                "CONTENT_SCAN: skipped (this is not the vault's own manifest, so "
                "there is no matching tree to scan)"
            )
    except ManifestError as exc:
        print(f"MANIFEST_ERROR: {exc}")
        return 1
    # Printed with both numbers, excluded from the count and the exit code:
    # a count drift means the manifest is older than the checkout, which is
    # the normal state of every clone, not a defect.
    for code, detail in informational:
        print(f"INFO {code}: {detail}")
    if informational:
        print(
            f"INFO: {len(informational)} count drift(s), not counted as findings; "
            "regenerate the manifest to clear them"
        )
    if findings:
        for code, detail in findings:
            print(f"{code}: {detail}")
        print(f"FINDINGS: {len(findings)}")
        return 2
    print("FINDINGS: 0 (all checks pass)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
