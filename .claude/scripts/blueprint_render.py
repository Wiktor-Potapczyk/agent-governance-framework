"""Blueprint A2: secret-free templates, generated from the live settings and
MCP files.

Spec of record: Projects/Vault-Maintenance/work/2026-09-22-blueprint-implementation-plan.md
section "Implementation Phase A2: Secret-free templates". Plan of record:
Projects/Vault-Maintenance/work/2026-09-22-harness-migration-blueprint-plan.md
(A2 row and review responses 5, 6, architect 4).

generate(sources, secrets_dir, out_dir, values=None, placeholder_missing=False):
reads the five live files (settings.local.json, .mcp.json, the user-level
settings.json, ~/.claude/CLAUDE.md, the qmd index.yml), replaces every secret
value with a {{secret:<file-name>}} placeholder, every non-secret-keyed
.mcp.json env/header value with a {{value:<derived-key>}} placeholder, and
every machine path with one of the project_key/vault/home/npm/python
spelling placeholders (see below), and writes the five .tmpl files to
out_dir. Returns ({tmpl file name: placeholder count dict}, missing,
values_needed).

A secret value in settings_local.env is any value under a key the imported
SECRET_KEY regex matches (legacy, unchanged scope). Every other env value
(mcp.env, mcp.headers, user_settings.env) is default-deny: secret-class
unless it is an explicit non-secret shape (a URL, a filesystem path) or an
allow-listed key (ENV_VALUE_ALLOW_LIST) or shorter than SECRET_SCAN_MIN_LEN.
A secret-class value is matched against secrets_dir by full stripped-value
equality, never substring. A secret-class value with no file match raises
SecretNotFoundError naming the key, unless placeholder_missing=True, in
which case a placeholder is still emitted under a derived file name (never
written to secrets_dir), the (file, key_path) pairs are returned as
`missing` and recorded in out_dir/_missing-secrets.json (names and key
paths, never values). This default-deny closes the gap a key-name rule
alone misses (found live: `_GITHUB_PAT_PERSONAL` in the user settings.json,
whose key matched no SECRET_KEY substring and whose value matched no
secrets_dir file, so it was never classified as secret at all).

A non-secret-shaped (URL/path/allow-listed) env/header value in mcp.env,
mcp.headers or user_settings.env, at least SECRET_SCAN_MIN_LEN long, becomes
{{value:<derived-key>}}; the (key, key_path) pairs are returned as
`values_needed` and recorded in out_dir/_values-needed.json (names and key
paths, never values). This closes O17 check_d's own scan, which treats
every .mcp.json env/header value as sensitive by construction regardless of
whether it is secret-shaped.

An .mcp.json server's top-level `url` is classified too, not only its env
and headers: a url whose query string carries a tenant- or
credential-shaped parameter (TENANT_URL_PARAMS: project_ref, token, key,
api_key) becomes {{value:mcp-<server>-url}} and enters `values_needed`.
Found live: a tenant-hosted server's `project_ref`, which cc-config's own
templates already parameterised and which the env/header-only scope let
through as a literal.

Secret and value substitution is whole-JSON-string only: the generator
replaces `"<value>"` with `"{{secret:...}}"` / `"{{value:...}}"`, never a
bare substring. A substring replace let a short value reach inside a
longer, unrelated field (found live: one server's 26-character API URL is a
prefix of another server's `url`, so filling one server's env key rewrote
the other server's url). Only the path spellings below are still
substituted as substrings, where reaching inside a longer path is the
point.

generate() also asserts no template it writes contains any secrets_dir
file's content (SecretLeakError), then scans every rendered line against
the imported CREDENTIAL_PATTERNS (mirror_user_claude.py, by identity) as a
format-based final net independent of the classification above, refusing
(CredentialPatternError, line number only, never the match) if any line
matches a known credential shape.

Path placeholders: for each of project_key, vault, home, npm, python,
generate() searches every on-disk spelling actually seen in these files:
{{X}} (forward slash), {{X:bs}} (single backslash), {{X:bs2}} (JSON-doubled
backslash), {{X:bs4}} (JSON-doubled backslash inside a quoted Bash string),
{{X:msys}} (/c/Users/...) and {{X:msys2}} (//c/Users/...), plus the DOS 8.3
short form of the user-profile segment (WIKTOR~1 for WiktorPotapczyk),
derived generically by _short_name() rather than retyped. The 8.3 form
collapses to the long form on decode, so it does NOT round trip: every
template generate() writes is decoded back and compared to its source
before anything is written, and a line that does not reproduce refuses the
whole run with SPELLING_NOT_ROUND_TRIPPABLE (line numbers only, never
content) rather than shipping a lossy template.

project_key is substituted first (it does not
contain vault's own spelling, but the Claude Code project-directory name
embeds the username and would otherwise leak past the path substitutions
and the username check); vault and npm are substituted before home (both
contain home as a prefix); python is independent. project_key has no
backslash/MSYS spelling of its own (it is already a flat hyphenated
string), so only {{project_key}} is ever emitted.

check(templates_dir, sources, secrets_dir, values=None): renders the
templates with this machine's values (plus the live .mcp.json's own
non-secret values, resolved in memory, never from a file), diffs the result
against the live sources line by line after CRLF normalisation (a line
whose only mismatch source is an UNRESOLVED_SECRET_FILE placeholder is
skipped for ROUND_TRIP_MISMATCH, not silently: the UNRESOLVED_SECRET_FILE
finding already reports it), verifies every {{secret:<file>}} placeholder
names a file that exists (UNRESOLVED_SECRET_FILE otherwise), verifies no
live secret value nor machine-shaped path survives unreplaced in a
template, reports CREDENTIAL_PATTERN_IN_TEMPLATE (line number only) on any
line matching CREDENTIAL_PATTERNS, and runs the imported O17 check_d over
the rendered templates. Returns a list of (code, detail) findings, never a
value.

Sidecars: generate() always writes all three of out_dir/
_missing-secrets.json, _values-needed.json and _secrets-referenced.json,
with an empty list when nothing is owed. An empty list is a statement; an
absent file is ambiguous, and a stale one told the owner to recreate
secrets that already existed. _secrets-referenced.json is the full list of
every {{secret:<file>}} the templates carry, each with
`exists_on_source: true|false`, which is the superset the runbook needs
(_missing-secrets.json names only the ones with no file on this machine).
generate(manifest_path=...) writes that same list into the blueprint
manifest's `secrets.items`, keeping the manifest's own
`"filled_by": "blueprint_render"` promise.

user-claude-md.tmpl is a verbatim render of ~/.claude/CLAUDE.md, including
the team knowledge-base pointer. Rather than add a second templating mechanism
for one conditional section, generate() prepends GENERATOR_NOTE, one HTML
comment telling the owner to delete that section by hand on a device that
does no team work. The note is stripped on decode, so check() and render()
both reproduce the source exactly.

render(templates_dir, out_dir, values, secrets_dir): the target-machine
deploy path. Fills every path, secret and value placeholder from `values`
(a single JSON file carrying project_key/vault/home/npm/python plus every
derived {{value:<key>}} entry) and secrets_dir; raises
UnresolvedPlaceholderError naming the leftover placeholder tokens (never
values) and writes nothing if any placeholder cannot resolve.

Reuse discipline (GUD-001): classify, secret_kind, check_d, MACHINE_TOKEN,
SECRET_KEY, SECRET_SCAN_MIN_LEN, NAME_RE, VAULT_RE, INTERP_RE, PROFILE_RE are
imported from o17_portability_manifest by identity, never re-derived. The
long/short username spellings are read off NAME_RE's own pattern text
rather than retyped. compute_project_key() implements the same rule
cc-config's setup_helpers.compute_project_key does, verified against the
live directory name under ~/.claude/projects/.

Hard constraint (REQ-002): no secret value is ever printed, returned in a
finding detail, or embedded in a written artifact. No function in this
module writes into secrets_dir; --placeholder-missing only ever emits a
{{secret:<derived-name>}} placeholder and a name/key-path sidecar.
"""
import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import o17_portability_manifest as o17
import mirror_user_claude as _mirror
import blueprint_workbound as wb

classify = o17.classify
secret_kind = o17.secret_kind
check_d = o17.check_d
MACHINE_TOKEN = o17.MACHINE_TOKEN
SECRET_KEY = o17.SECRET_KEY
SECRET_SCAN_MIN_LEN = o17.SECRET_SCAN_MIN_LEN
NAME_RE = o17.NAME_RE
VAULT_RE = o17.VAULT_RE
INTERP_RE = o17.INTERP_RE
PROFILE_RE = o17.PROFILE_RE
# GitHub classic (ghp_) and fine-grained (github_pat_) shapes are already
# present in mirror_user_claude's pattern set; imported by identity, not
# copied, so a future addition there reaches this net too.
CREDENTIAL_PATTERNS = _mirror.CREDENTIAL_PATTERNS

# .claude/scripts/blueprint_render.py -> vault root, same idiom as
# o17_portability_figures.py (CON-004: no new path-resolver module).
VAULT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_ORDER = ["settings_local", "mcp", "user_settings", "user_claude_md", "qmd_index"]

# B3. Two profiles, and bare is the default because the bare profile is the
# product: the owner's ask, verbatim except for the employer's own name, which
# this file does not carry, is "FRESH DEVICE NEEDS JUST THE HARNESS AND BARE
# VAULT, NOTHING [EMPLOYER] SPECIFIC." The full profile reproduces this
# workstation and is opt-in.
PROFILES = ("full", "bare")
DEFAULT_PROFILE = "bare"

# B5. The bare profile renders four more files than the full one: a scrubbed
# TWIN of each tracked vault file that must exist on a bare device and whose
# content names the employer. The bare sparse patterns exclude the original,
# which sets git's skip-worktree bit on it, so the twin lands in its place
# with no staged modification; the full profile checks the real one out.
#
# One table, four facts each: the vault path replaced, the source key, the
# template name and the scrub kind. blueprint_manifest.BARE_REPLACED_PATHS is
# the same list seen from the clone side, and a test binds the two (architect
# F14) rather than one importing the other.
BARE_TWINS = (
    # (vault path, source key, template name, deploy name, scrub kind)
    ("CLAUDE.md", "vault_claude_md", "vault-claude-md.tmpl", "vault-CLAUDE.md", "markdown"),
    (".gitignore", "vault_gitignore", "vault-gitignore.tmpl", "vault-gitignore", "lines"),
    (".claude/hooks/control-probes.json", "control_probes", "control-probes.json.tmpl",
     "control-probes.json", "json_rows"),
    (".claude/scripts/install-prereqs-manifest.json", "install_prereqs_manifest",
     "install-prereqs-manifest.json.tmpl", "install-prereqs-manifest.json", "json_rows"),
    # The project settings file is TRACKED, so it used to ship verbatim and
    # carried registrations for hooks the bare profile excludes by content: a
    # fresh device fired them and got "no such file" on every matching event.
    # It goes through the same scrubber as the two settings files that were
    # already twins, which is why its kind is "settings" and not "json_rows".
    (".claude/settings.json", "project_settings",
     "project-settings.json.tmpl", "project-settings.json", "settings"),
)
BARE_TWIN_TARGETS = tuple(row[0] for row in BARE_TWINS)
BARE_TWIN_KINDS = {row[1]: row[4] for row in BARE_TWINS}
BARE_TWIN_SOURCE_PATHS = {row[1]: row[0] for row in BARE_TWINS}

SOURCE_ORDER_BY_PROFILE = {
    "full": list(SOURCE_ORDER),
    "bare": list(SOURCE_ORDER) + [row[1] for row in BARE_TWINS],
}
TEMPLATE_NAMES = {
    "settings_local": "settings.local.json.tmpl",
    "mcp": "mcp.json.tmpl",
    "user_settings": "user-settings.json.tmpl",
    "user_claude_md": "user-claude-md.tmpl",
    "qmd_index": "qmd-index.yml.tmpl",
}
TEMPLATE_NAMES.update({row[1]: row[2] for row in BARE_TWINS})
# The deploy name of the vault twin is NOT "CLAUDE.md": the user-level
# CLAUDE.md already owns that name, and both land in one staging directory
# before placement. The runner's PLACEMENT maps each name to its destination.
DEPLOY_NAMES = {
    "settings_local": "settings.local.json",
    "mcp": ".mcp.json",
    "user_settings": "settings.json",
    "user_claude_md": "CLAUDE.md",
    "qmd_index": "index.yml",
}
DEPLOY_NAMES.update({row[1]: row[3] for row in BARE_TWINS})


def source_order(profile=DEFAULT_PROFILE, sources=None):
    """The source keys one profile renders, in order.

    `sources`, when given, narrows the list to the keys that mapping actually
    carries. The five core sources are always required; a bare TWIN whose
    source file is not in the mapping is skipped rather than raising, which is
    what lets a fixture exercise the bare path with three files instead of
    nine. A twin that IS declared but whose file is missing still refuses,
    because check() reports TEMPLATE_MISSING for the template it never wrote.
    """
    if profile not in SOURCE_ORDER_BY_PROFILE:
        raise ValueError(f"unknown profile: {profile!r} (known: {', '.join(PROFILES)})")
    order = list(SOURCE_ORDER_BY_PROFILE[profile])
    if sources is None:
        return order
    twins = {row[1] for row in BARE_TWINS}
    return [k for k in order if k not in twins or sources.get(k) is not None]

SIDECAR_MISSING_SECRETS = "_missing-secrets.json"
SIDECAR_VALUES_NEEDED = "_values-needed.json"
SIDECAR_SECRETS_REFERENCED = "_secrets-referenced.json"
SIDECAR_NAMES = (
    SIDECAR_MISSING_SECRETS, SIDECAR_VALUES_NEEDED, SIDECAR_SECRETS_REFERENCED,
)

# One HTML comment, prepended to user-claude-md.tmpl only, stripped again on
# decode so the round trip stays exact. The alternative (a conditional
# section) would be a second templating mechanism for one paragraph.
GENERATOR_NOTE = (
    "<!-- blueprint-note: the team knowledge-base pointer section below is "
    "rendered verbatim from the source machine. On a device that does no team "
    "work, delete that section by hand after this file is placed. This comment "
    "line is added by blueprint_render.py generate and is not part of the "
    "source file. -->"
)
GENERATOR_NOTE_RE = re.compile(
    r"^<!-- blueprint-note:.*?-->(?:\r\n|\r|\n)", re.DOTALL
)

SECRET_PLACEHOLDER_RE = re.compile(r"\{\{secret:([^}]+)\}\}")
VALUE_PLACEHOLDER_RE = re.compile(r"\{\{value:([^}]+)\}\}")
PATH_PLACEHOLDER_RE = re.compile(
    r"\{\{(project_key|vault|home|npm|python)(?::(bs4|bs2|bs|msys2|msys))?\}\}"
)
LEFTOVER_PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")

# project_key never contains vault's own spelling, but the Claude Code
# project-directory name embeds the username inside other paths (memory,
# session transcripts) and must be substituted before those paths are
# scanned for a bare username. vault and npm both contain home as a prefix;
# substitute them first so the longer, more specific spelling always wins.
# python is unrelated to all of them.
VALUE_ORDER = ["project_key", "vault", "npm", "home", "python"]
# bs4 contains bs2 as a substring, bs2 contains bs (via the character class),
# and msys2 ("//c/...") contains msys ("/c/...") as a substring starting at
# index 1: longest/most-specific spelling first, always.
SPELLING_ORDER = ["bs4", "bs2", "bs", "msys2", "msys", ""]

# Read off NAME_RE's own pattern rather than retyping the username spellings.
# Index-based rather than a two-way unpack: a third alternative in NAME_RE
# must not raise ValueError at import time and take every caller down with it.
_NAME_ALTERNATIVES = NAME_RE.pattern.split("|")
USERNAME_LONG = _NAME_ALTERNATIVES[0]
USERNAME_SHORT = _NAME_ALTERNATIVES[1] if len(_NAME_ALTERNATIVES) > 1 else None

# The user-profile segment regex and the DOS 8.3 short-name derivation are
# bound from o17 by identity, not re-derived: O17's own CHECK (a) needs the
# same rule to compare two machines' rows, and two copies of it would drift
# exactly the way the round-4 defect did (GUD-001).
PROFILE_SEGMENT_RE = o17.PROFILE_SEGMENT_RE
_short_name = o17._short_name
_short_name_variant = o17._short_name_variant

# Default-deny scope: env values in the user settings.json and .mcp.json,
# and header values in .mcp.json, are secret-class unless they match one of
# these explicit non-secret shapes or a named allow-listed key. Values
# shorter than SECRET_SCAN_MIN_LEN are exempt everywhere (O17's own
# generic-flag floor), independent of this list.
ENV_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
ENV_FS_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|//?[A-Za-z]([\\/]|$)|\.{1,2}[\\/])")
ENV_VALUE_ALLOW_LIST = {
    "MCP_MODE", "LOG_LEVEL", "DISABLE_CONSOLE_OUTPUT", "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
}

# An .mcp.json server url carrying one of these query parameters names a
# tenant or a credential and is therefore per-machine, not a constant. Found
# live: a tenant-hosted database server's project_ref, which cc-config's own
# templates already parameterised.
TENANT_URL_PARAMS = ("project_ref", "token", "key", "api_key")


class SecretNotFoundError(Exception):
    """A SECRET_KEY-matched value has no file match in secrets_dir."""


class SecretLeakError(Exception):
    """A generated template still contains a secrets_dir file's content."""


class CredentialPatternError(Exception):
    """A rendered template line matches a known credential shape."""


class UnresolvedPlaceholderError(Exception):
    """render() found a placeholder token with no resolvable value."""


class WorkBoundTermError(Exception):
    """A bare-profile artifact still carries a work-bound term after the
    scrub. Raised by generate() before anything reaches the templates
    directory: shipping a bare profile that names the employer is the one
    failure this profile exists to prevent, so it refuses rather than
    reports."""


class SpellingNotRoundTrippableError(Exception):
    """A source line carries a spelling this generator cannot reproduce on
    decode (the DOS 8.3 short user name is the live case: it encodes to the
    same placeholder as the long form and decodes only to the long form).
    generate() refuses the whole run rather than write a lossy template.
    Carries the finding code SPELLING_NOT_ROUND_TRIPPABLE and line numbers
    only, never line content."""


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()


def _derive_secret_filename(name_parts):
    return "-".join(_slug(p) for p in name_parts if _slug(p)) + ".txt"


def _derive_value_key(name_parts):
    return "-".join(_slug(p) for p in name_parts if _slug(p))


def _classify_env_value(key, value, secrets_content):
    """Default-deny classification for one env/header (key, value) pair.

    Returns ('skip', None) for values shorter than SECRET_SCAN_MIN_LEN,
    ('secret', file_name) when the value matches a secrets_content file,
    ('value', None) for an explicit non-secret shape (URL, filesystem
    path) or an allow-listed key, and ('secret', None) otherwise (default
    deny: an unrecognised shape is secret-class with no file match yet).
    """
    stripped = value.strip()
    if len(stripped) < SECRET_SCAN_MIN_LEN:
        return "skip", None
    match = secrets_content.get(stripped)
    if match:
        return "secret", match
    if key in ENV_VALUE_ALLOW_LIST or ENV_URL_RE.match(stripped) or ENV_FS_PATH_RE.match(stripped):
        return "value", None
    return "secret", None


# Claude Code's own project-directory-name rule: the absolute Windows path
# with ':' and every path separator replaced by '-'. Matches cc-config's
# setup_helpers.compute_project_key; verified against the live directory name
# under ~/.claude/projects/. Bound from o17 by identity, which is also where
# O17's CHECK (a) reads it, so the rule has one implementation (GUD-001).
compute_project_key = o17.compute_project_key


def portable_settings_local():
    """A3's portable wiring file: the settings_local source the SHIPPED bare
    templates were generated from, and the only one they can reproduce
    byte-for-byte. The live `.claude/settings.local.json` is rewritten by
    Claude Code on every permission approval and has carried a spelling the
    encoder cannot round trip, so defaulting bare to the live file made its
    own idempotence check structurally unable to pass (architect F3b)."""
    return VAULT_ROOT / ".claude" / "blueprint" / "settings.local.portable.json"


def default_sources(profile=None):
    """The live sources. For the bare profile the settings_local default is
    the portable wiring file, which is stated in the CLI --help and is the
    only source the shipped bare templates reproduce."""
    home = Path.home()
    sources = {
        "settings_local": VAULT_ROOT / ".claude" / "settings.local.json",
        "mcp": VAULT_ROOT / ".mcp.json",
        "user_settings": home / ".claude" / "settings.json",
        "user_claude_md": home / ".claude" / "CLAUDE.md",
        "qmd_index": home / ".config" / "qmd" / "index.yml",
    }
    for vault_path, key, _tmpl, _deploy, _kind in BARE_TWINS:
        sources[key] = VAULT_ROOT / vault_path
    if profile == "bare" and portable_settings_local().is_file():
        sources["settings_local"] = portable_settings_local()
    return sources


def default_secrets_dir():
    return (
        Path.home() / ".claude" / "projects"
        / "C--Users-WiktorPotapczyk-Desktop-Vault" / "secrets"
    )


def default_templates_dir(profile=DEFAULT_PROFILE):
    """templates/<profile>/. Both profiles have their own directory, so a
    reader never has to know which machine a .tmpl came from."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (known: {', '.join(PROFILES)})")
    return VAULT_ROOT / ".claude" / "blueprint" / "templates" / profile


def default_manifest_path():
    return VAULT_ROOT / ".claude" / "blueprint" / "manifest.json"


def compute_values(vault=None, home=None, python=None):
    vault = Path(vault) if vault is not None else VAULT_ROOT
    home = Path(home) if home is not None else Path.home()
    python = Path(python) if python is not None else Path(sys.executable)
    return {
        "project_key": compute_project_key(vault.as_posix()),
        "vault": vault.as_posix(),
        "home": home.as_posix(),
        "npm": (home / "AppData" / "Roaming" / "npm").as_posix(),
        "python": python.as_posix(),
    }


def _crlf(text):
    return text.replace("\r\n", "\n")


# ---------------------------------------------------------------------------
# B3: the bare scrub.
#
# Every scrubber below is explicit about the key it handles, because the
# shapes are known, stable and reviewable, and a generic recursive filter
# cannot tell "drop this list element" from "drop the key that holds the
# hooks". The generic part is the GUARANTEE rather than the transformation:
# assert_no_work_bound_term runs over every scrubbed artifact before anything
# is written, so an unanticipated shape refuses the run instead of shipping.
#
# No scrubber reads a secret value. The env rule asks the renderer's own
# classifier whether a value is secret-class and drops the ENTRY on a yes;
# the value never leaves the dict it was read from.
# ---------------------------------------------------------------------------

# The only hosts a permission row may name in the bare profile. Everything
# else is dropped, because a research allowlist is per-machine state by
# nature: it accumulates a client's competitor set, the award directories
# entered and the vendor comparison sites, and no plausible term list catches
# them (a client arrives without announcing itself in a domain name). The
# measured cost of the old default-ALLOW posture was 21 rows that read as an
# index of one client engagement, inside the six files the gate called clean
# (architect F1, adversarial F4). Nothing on a fresh device needs a research
# allowlist pre-filled; it re-accumulates on first use.
BARE_HOST_ALLOWLIST = (
    "github.com", "raw.githubusercontent.com", "docs.anthropic.com",
    "code.claude.com", "pypi.org", "npmjs.com", "registry.npmjs.org",
    "nodejs.org", "python.org",
)
_DOMAIN_RE = re.compile(r"domain:\s*([A-Za-z0-9._*-]+)")
_URL_IN_ROW_RE = re.compile(r"https?://([A-Za-z0-9._-]+)")
# A vault-relative path inside a permission row: the part from `.claude/` (or
# a bare `Projects/`) to the file extension, however the row spells the prefix
# ($CLAUDE_PROJECT_DIR, {{vault}}, an absolute path, or nothing at all).
_ROW_PATH_RE = re.compile(
    r"((?:\.claude|Projects|Resources|Templates|Archives)[\\/][\w./\\-]+"
    r"\.(?:py|md|js|mjs|ps1|json|ya?ml|txt|sh|toml))"
)


def _row_hosts(text):
    """Every host a permission row names, from a domain: clause or a URL."""
    hosts = set(_DOMAIN_RE.findall(text)) | set(_URL_IN_ROW_RE.findall(text))
    return {h.strip().lower().lstrip("*.") for h in hosts if h.strip()}


def host_is_allowed(host):
    """True for a host on the short generic allowlist, matching the host
    itself or one of its subdomains."""
    host = host.lower().lstrip("*.")
    return any(host == a or host.endswith("." + a) for a in BARE_HOST_ALLOWLIST)


def _row_vault_paths(text):
    """Vault-relative paths a permission row references, wildcard-free ones
    only: a glob cannot be tested for existence and must not be dropped on a
    failed lookup."""
    out = []
    for raw in _ROW_PATH_RE.findall(text):
        path = raw.replace(chr(92), "/")
        if "*" in path or "?" in path:
            continue
        out.append(path)
    return out


def bare_tree_paths(manifest_path=None):
    """The set of vault-relative paths the bare profile checks out, or None
    when it cannot be derived here (no manifest, or no bare data sidecar).

    None means every rule that depends on it is SKIPPED and said to be
    skipped, never silently satisfied.
    """
    try:
        import blueprint_manifest as bm
    except ImportError:  # pragma: no cover - the module sits beside this one
        return None
    path = Path(manifest_path or default_manifest_path())
    sidecar = bm.read_sidecar(path)
    if sidecar is None:
        return None
    ls_files = bm.live_ls_files(VAULT_ROOT)
    if not ls_files:
        return None
    units = {}
    for p in ls_files:
        units.setdefault(bm.unit_for(p), []).append(p)
    buckets = {u: bm.classify_path(u) for u in units}
    content = list(sidecar.get("content_paths") or [])
    tree = {
        p for p in ls_files
        if bm.ships_in_profile(p, buckets, "bare", content_excluded=content)
    }
    # Two families of path are deliberately NOT checked out and are still
    # present on the target: the twins the renderer places over them, and the
    # inventories the runner regenerates there. A rule that asks "does this
    # path exist on a bare device" has to count them present, or it drops
    # every row that points at CLAUDE.md, .gitignore or the settings file.
    tree |= set(bm.BARE_REPLACED_PATHS) | set(bm.BARE_REGENERATED_PATHS)
    return tree


def assert_no_work_bound_term(payload, label):
    """Raise WorkBoundTermError if any work-bound term survives in `payload`
    (a str, or anything json.dumps can serialise). Names the term and the
    line number, never the line."""
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    hits = wb.scan_text(text)
    if hits:
        summary = ", ".join(f"line {lineno}: {term}" for lineno, term in hits[:10])
        raise WorkBoundTermError(
            f"WORKBOUND_TERM_IN_BARE_TEMPLATE: {label}: {len(hits)} hit(s): {summary}"
        )


def scrub_mcp_config(cfg):
    """Keep only the GENERIC servers (blueprint_workbound.classify_mcp_server).

    Returns (new config, dropped server names). Measured against the live
    .mcp.json: memory, qmd and codegraph survive, which is the set with no
    term, no secret-shaped env key and no remote url."""
    servers = (cfg or {}).get("mcpServers") or {}
    keep, dropped = {}, []
    for name in servers:
        if wb.classify_mcp_server(name, servers[name]) == wb.GENERIC:
            keep[name] = servers[name]
        else:
            dropped.append(name)
    out = dict(cfg or {})
    out["mcpServers"] = keep
    return out, sorted(dropped)


def _drop_secret_or_work_bound_env(env, secrets_content):
    """Drop every env entry that is secret-class or names a term. Returns
    (kept dict, dropped key names). Key names only are ever returned."""
    kept, dropped = {}, []
    for key, value in (env or {}).items():
        if wb.has_term(key) or (isinstance(value, str) and wb.has_term(value)):
            dropped.append(key)
            continue
        if SECRET_KEY.search(str(key)):
            dropped.append(key)
            continue
        if isinstance(value, str):
            kind, _match = _classify_env_value(key, value, secrets_content or {})
            if kind == "secret":
                dropped.append(key)
                continue
        kept[key] = value
    return kept, sorted(dropped)


def bare_permission_verdict(text, tree=None):
    """Why the bare profile drops one permission row, or None to keep it.

    Three rules, in order, and the first two are DEFAULT-DENY. The module's
    own risk posture was inconsistent before B5: `_classify_env_value` drops
    an unrecognised env value, while this surface kept an unrecognised row,
    and both guard the same promise (architect F1).

      1. term or shape: the row names an instance, a tenant, a tracker, a
         deploy host or an address (classify_permission_row).
      2. host: the row names ANY host outside the short generic allowlist.
         This is the rule that removes a client roster a term list cannot see.
      3. dangling reference: the row names a vault-relative file that the bare
         profile does not check out. 41 such rows were measured surviving on a
         bare device, pointing at agent definitions, scratch scripts and work
         files from March (adversarial F15). Skipped when `tree` is None.
    """
    text = str(text)
    if wb.classify_permission_row(text) == wb.WORK_BOUND:
        return "term"
    for host in _row_hosts(text):
        if not host_is_allowed(host):
            return "host"
    if tree is not None:
        for path in _row_vault_paths(text):
            if path not in tree:
                return "dangling"
    return None


def _scrub_permission_block(permissions, tree=None):
    """Filter every allow/deny/ask list by bare_permission_verdict. Returns
    (block, {reason: count})."""
    out, dropped = {}, {"term": 0, "host": 0, "dangling": 0}
    for key, value in (permissions or {}).items():
        if not isinstance(value, list):
            out[key] = value
            continue
        kept = []
        for row in value:
            reason = bare_permission_verdict(row, tree=tree)
            if reason is None:
                kept.append(row)
            else:
                dropped[reason] += 1
        out[key] = kept
    return out, dropped


def _scrub_hook_registrations(hooks, tree=None):
    """Drop the individual hook ENTRIES the bare profile cannot run, and any
    group left with nothing in it. Every other byte of the wiring is untouched.

    Two rules, both entry-level:
      1. the entry's command carries a term or a shape;
      2. the entry invokes a script that is not in the bare tree (generic, not
         keyed to any one hook's name).

    A group whose MATCHER itself carries a term (a matcher naming an instance
    server) still cannot ship, because the matcher string would carry the term
    into the file. It is dropped, but its entries are counted under their own
    reason rather than folded into the term count: the cost of the old
    behaviour was that a matcher-level drop took generic hooks with it and the
    runner's o17 verdict auto-excused every one of them, because the finding
    text carried the term (adversarial F13). Collateral loss is now a separate
    number in the report, and the o17 rule that blessed it is fixed in the
    runner.

    Returns (hooks, {reason: count}, dropped group count).
    """
    out, dropped = {}, {"term": 0, "missing_script": 0, "matcher_collateral": 0}
    dropped_groups = 0
    for event, groups in (hooks or {}).items():
        if not isinstance(groups, list):
            out[event] = groups
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            if wb.has_term(str(group.get("matcher") or "")):
                dropped_groups += 1
                dropped["matcher_collateral"] += len(group.get("hooks") or [])
                continue
            entries = group.get("hooks")
            if not isinstance(entries, list):
                kept_groups.append(group)
                continue
            kept = []
            for entry in entries:
                blob = json.dumps(entry)
                if wb.has_term(blob):
                    dropped["term"] += 1
                    continue
                if tree is not None and any(
                    p not in tree for p in _row_vault_paths(blob)
                ):
                    dropped["missing_script"] += 1
                    continue
                kept.append(entry)
            if not kept:
                dropped_groups += 1
                continue
            new_group = dict(group)
            new_group["hooks"] = kept
            kept_groups.append(new_group)
        out[event] = kept_groups
    return out, dropped, dropped_groups


def _scrub_mapping_by_term(mapping):
    """Drop every entry of a name-keyed mapping (enabledPlugins,
    extraKnownMarketplaces) whose key or value subtree carries a term.

    Both shapes Claude Code writes are handled: the dict form
    ({"plugin@market": true}) and the plain list of names.
    """
    if isinstance(mapping, list):
        kept = [v for v in mapping if not wb.has_term(json.dumps(v))]
        dropped = [str(v) for v in mapping if wb.has_term(json.dumps(v))]
        return kept, sorted(dropped)
    kept, dropped = {}, []
    for key, value in (mapping or {}).items():
        if wb.has_term(key) or wb.has_term(json.dumps(value)):
            dropped.append(key)
            continue
        kept[key] = value
    return kept, sorted(dropped)


def _scrub_scalar_lists(node):
    """Drop term-carrying scalars from every list under `node`, recursing
    into dicts. Used for autoMode, whose soft_deny and environment lists
    describe THIS workstation's repositories."""
    if isinstance(node, dict):
        return {k: _scrub_scalar_lists(v) for k, v in node.items() if not wb.has_term(k)}
    if isinstance(node, list):
        return [
            _scrub_scalar_lists(v) for v in node
            if not (isinstance(v, str) and wb.has_term(v))
        ]
    return node


# Top-level settings keys with their own scrubber. Anything not named here
# travels unchanged, and assert_no_work_bound_term is what catches a new key
# that should have been named.
_SETTINGS_PASSTHROUGH_SCRUB = ("autoMode",)


def scrub_settings(cfg, secrets_content, generic_servers=None, tree=None):
    """Scrub one settings file (project-level or user-level) for the bare
    profile. Returns (new config, stats dict).

    stats carries counts and names only: dropped permission rows, dropped
    env KEY names, dropped plugin names, dropped hook entries.
    """
    out = {}
    stats = {
        "permission_rows_dropped": 0,
        "permission_rows_by_reason": {},
        "env_keys_dropped": [],
        "plugins_dropped": [],
        "marketplaces_dropped": [],
        "mcp_servers_dropped": [],
        "hook_entries_dropped": 0,
        "hook_entries_by_reason": {},
        "hook_groups_dropped": 0,
    }
    for key, value in (cfg or {}).items():
        if key == "env":
            out[key], stats["env_keys_dropped"] = _drop_secret_or_work_bound_env(
                value, secrets_content
            )
        elif key == "permissions":
            out[key], by_reason = _scrub_permission_block(value, tree=tree)
            stats["permission_rows_by_reason"] = by_reason
            stats["permission_rows_dropped"] = sum(by_reason.values())
        elif key == "hooks":
            out[key], by_reason, groups = _scrub_hook_registrations(value, tree=tree)
            stats["hook_entries_by_reason"] = by_reason
            stats["hook_entries_dropped"] = sum(by_reason.values())
            stats["hook_groups_dropped"] = groups
        elif key == "enabledMcpjsonServers" and isinstance(value, list):
            allowed = set(generic_servers or [])
            kept = sorted(
                v for v in value
                if not wb.has_term(str(v)) and (not allowed or v in allowed)
            )
            stats["mcp_servers_dropped"] = sorted(set(map(str, value)) - set(kept))
            out[key] = kept
        elif key == "enabledPlugins":
            out[key], stats["plugins_dropped"] = _scrub_mapping_by_term(value)
        elif key == "extraKnownMarketplaces":
            out[key], stats["marketplaces_dropped"] = _scrub_mapping_by_term(value)
        elif key in _SETTINGS_PASSTHROUGH_SCRUB:
            out[key] = _scrub_scalar_lists(value)
        else:
            out[key] = value
    return out, stats


def scrub_json_rows(node, tree=None, stats=None):
    """Drop every list ELEMENT, at any depth, whose serialised form carries a
    term or a shape, or which names a vault file the bare profile does not
    ship. Returns the scrubbed node; `stats` collects counts by reason.

    One generic rule serves both JSON twins. The probe manifest keeps a row
    per registered control, and a bare device registers fewer controls: a
    probe pointing at a hook that is not there fails a global invariant test
    (architect F7), which the known-failures file used to excuse WHOLESALE,
    hiding every other stray probe with it. Dropping the row instead lets the
    invariant genuinely pass. The prerequisite manifest keeps a row per
    prerequisite, and a bare device has fewer of those too.
    """
    stats = stats if stats is not None else {}
    if isinstance(node, dict):
        return {k: scrub_json_rows(v, tree, stats) for k, v in node.items()}
    if isinstance(node, list):
        kept = []
        for element in node:
            blob = element if isinstance(element, str) else json.dumps(element)
            if wb.has_term(blob):
                stats["term"] = stats.get("term", 0) + 1
                continue
            if tree is not None and any(p not in tree for p in _row_vault_paths(blob)):
                stats["missing_path"] = stats.get("missing_path", 0) + 1
                continue
            kept.append(scrub_json_rows(element, tree, stats))
        return kept
    return node


_DRIVE_PATH_RE = re.compile(r"(?<![A-Za-z])([A-Za-z]:[\\/])([^\s\"']*)")


def redact_foreign_paths(node, values, stats=None):
    """Replace a drive-letter path that is NOT under this machine's vault,
    home, npm prefix or interpreter with `<drive>:/...`.

    A path under one of those four roots is modelled by a placeholder and the
    encoder rewrites it for the target. Everything else is a drive path in
    PROSE (a probe's written rationale saying "use the C:/ path form", a
    fixture naming a deliberately nonexistent file), and it would otherwise
    ship as MACHINE_PATH_IN_TEMPLATE forever: a real finding on a real string
    that no placeholder can resolve. Redacting the drive prefix keeps the
    sentence readable and the check honest.
    """
    stats = stats if stats is not None else {}
    roots = [str(v).replace(chr(92), "/").lower() for v in (values or {}).values() if v]

    def _redact(text):
        def sub(match):
            whole = match.group(0)
            normalised = whole.replace(chr(92), "/").lower()
            if any(normalised.startswith(r) for r in roots):
                return whole
            stats["paths"] = stats.get("paths", 0) + 1
            return "<drive>:/" + match.group(2).lstrip("/" + chr(92))
        return _DRIVE_PATH_RE.sub(sub, text)

    if isinstance(node, dict):
        return {k: redact_foreign_paths(v, values, stats) for k, v in node.items()}
    if isinstance(node, list):
        return [redact_foreign_paths(v, values, stats) for v in node]
    if isinstance(node, str):
        return _redact(node)
    return node


def scrub_lines(text):
    """Drop every LINE carrying a term or a shape. For a line-oriented file
    whose lines are independent of each other (the vault's .gitignore is the
    live case: an ignore rule naming a client project is one line, and
    removing it on a device that has no such directory changes nothing).
    Returns (text, removed line records)."""
    out, removed = [], []
    for lineno, line in enumerate(_crlf(text).split("\n"), start=1):
        terms = wb.term_matches(line)
        if terms:
            removed.append({"kind": "line", "line_number": lineno, "terms": terms})
            continue
        out.append(line)
    return "\n".join(out), removed


def scrub_qmd_index(text, tree=None, home_placeholder="{{home}}"):
    """Keep only the qmd collections whose `path` exists in the bare profile.

    The bare index was a byte copy of the full one and pointed at three
    directories a bare device does not have, plus one that exists and is empty
    (adversarial F14). A collection is kept when its path is under the home
    directory (the memory collection, which the runner creates) or when its
    vault-relative path is in the bare tree. Returns (text, dropped names).
    """
    lines = _crlf(text).split("\n")
    out, dropped = [], []
    block, block_path, block_name = [], None, None
    # Both shapes qmd writes: a mapping of collection name to body (the live
    # file), and a list of `- name:` entries.
    head_map = re.compile(r"^(\s{2,})([A-Za-z0-9_.-]+):\s*$")
    head_list = re.compile(r"^\s*-\s+name:\s*(.+?)\s*$")
    path_re = re.compile(r"^\s*path:\s*(.+?)\s*$")

    def flush():
        nonlocal block, block_path, block_name
        if not block:
            return
        keep = True
        if block_path is not None and tree is not None:
            rel = _vault_relative(block_path)
            if rel is not None:
                keep = any(p == rel or p.startswith(rel + "/") for p in tree)
        if keep:
            out.extend(block)
        else:
            dropped.append(block_name or "(unnamed)")
        block, block_path, block_name = [], None, None

    for line in lines:
        m_list = head_list.match(line)
        m_map = head_map.match(line)
        if m_list or m_map:
            flush()
            block = [line]
            block_name = (m_list.group(1) if m_list else m_map.group(2))
            continue
        if block:
            m = path_re.match(line)
            if m:
                block_path = m.group(1).strip().strip('"')
            block.append(line)
            continue
        out.append(line)
    flush()
    return "\n".join(out), dropped


def _vault_relative(path_text, vault_root=None):
    """The vault-relative form of a path, whether it is spelled as a machine
    path (the live qmd index) or with a {{vault}} placeholder (a template).
    None when the path is not under the vault, which is how a home-directory
    collection stays untouched."""
    text = str(path_text).replace(chr(92), "/").strip().strip('"')
    for marker in ("{{vault}}", "{{vault:bs}}", "{{vault:bs2}}", "{{vault:bs4}}",
                   "{{vault:msys}}", "{{vault:msys2}}"):
        if text.startswith(marker):
            return text[len(marker):].lstrip("/") or "."
    root = Path(vault_root or VAULT_ROOT).as_posix()
    for candidate in (root, "/" + root[0].lower() + root[2:] if root[1:2] == ":" else root):
        if text.lower().startswith(candidate.lower()):
            return text[len(candidate):].lstrip("/") or "."
    return None


_HEADING_RE = re.compile(r"^## ")

# Lines that describe THIS MACHINE rather than any employer. The scrub used to
# be a name filter only, so the doctrine twin still carried the session id of
# the run that generated it, an inventory of the home directory down to the
# size of its secrets folder, and the machine's corporate lockdown (adversarial
# F17). None of that is company-named and all of it describes one device.
_MACHINE_DESCRIPTION_RES = (
    re.compile(r"\bsession\s+(?:id\s+)?[0-9a-f]{8}\b", re.IGNORECASE),
    re.compile(r"`?[0-9a-f]{8}`?\s+(?:session|transcript)", re.IGNORECASE),
    re.compile(r"\b\d+(?:\.\d+)?\s*(?:GB|MB|KB)\b.*\b(?:home|~/\.claude|directory|folder|"
               r"secrets|memory|transcripts|caches?)\b", re.IGNORECASE),
    re.compile(r"(?:~/)?\.claude\b.*?\d+(?:\.\d+)?\s*(?:GB|MB|KB)\b", re.IGNORECASE),
    re.compile(r"\bwork machine\b|\bthis laptop\b|\bthis workstation's\b", re.IGNORECASE),
    re.compile(r"\bOneDrive\b", re.IGNORECASE),
    re.compile(r"\bcorp(?:orate)?\s+lockdown\b", re.IGNORECASE),
)


def machine_description_terms(line):
    """The machine-description rules a line trips, by name. Empty when none."""
    names = ("session-id", "session-id", "home-size", "home-size",
             "machine-name", "cloud-sync", "lockdown")
    return sorted({
        names[i] for i, rx in enumerate(_MACHINE_DESCRIPTION_RES) if rx.search(line)
    })


def scrub_markdown(text):
    """Drop every `##` section whose HEADING carries a work-bound term, and
    every remaining line that carries one. Returns (scrubbed text, removed).

    `removed` is a list of {"kind": "section"|"line", "heading"|"line_number",
    "terms"} records, so the caller can report what went without quoting the
    content. Sections are identified by their heading, never by a line
    number: a line number in this file would rot on the next edit of the
    source.
    """
    lines = _crlf(text).split("\n")
    removed = []
    out = []
    current_heading = None
    dropping = False
    for lineno, line in enumerate(lines, start=1):
        if _HEADING_RE.match(line):
            current_heading = line.rstrip()
            terms = wb.term_matches(line) + machine_description_terms(line)
            dropping = bool(terms)
            if dropping:
                removed.append({
                    "kind": "section", "heading": current_heading, "terms": terms,
                })
                continue
        if dropping:
            continue
        terms = wb.term_matches(line) + machine_description_terms(line)
        if terms:
            removed.append({
                "kind": "line", "line_number": lineno, "terms": sorted(set(terms)),
                "section": current_heading,
            })
            continue
        out.append(line)

    # A dropped section leaves its trailing blank line behind; collapse runs
    # of three or more blank lines to two so the scrub does not change the
    # document's shape beyond what it removed.
    collapsed = []
    for line in out:
        if line.strip() == "" and len(collapsed) >= 2 and collapsed[-1].strip() == "" \
                and collapsed[-2].strip() == "":
            continue
        collapsed.append(line)
    return "\n".join(collapsed), removed


def _load_secrets(secrets_dir):
    """Return {stripped file content: file name} for every file in secrets_dir.

    `None` is a legitimate input in the bare profile, which owes no secret
    file at all, and returns the same empty mapping a missing directory does.
    """
    if secrets_dir is None:
        return {}
    secrets_dir = Path(secrets_dir)
    out = {}
    if not secrets_dir.is_dir():
        return out
    for p in sorted(secrets_dir.iterdir()):
        if p.is_file():
            content = p.read_text(encoding="utf-8", newline="").strip()
            if content:
                out[content] = p.name
    return out


def _msys_form(fwd_value, doubled_slash):
    m = re.match(r"^([A-Za-z]):(/.*)$", fwd_value)
    if not m:
        return None
    prefix = "//" if doubled_slash else "/"
    return prefix + m.group(1).lower() + m.group(2)


def _spelling_for(value_name, suffix, values):
    """The one canonical spelling of values[value_name] for this suffix
    ('', 'bs', 'bs2', 'bs4', 'msys', 'msys2'). None if inapplicable (for
    example project_key, which has no '/' to convert)."""
    fwd = values.get(value_name)
    if not fwd:
        return None
    if not suffix:
        return fwd
    if suffix in ("msys", "msys2"):
        return _msys_form(fwd, doubled_slash=(suffix == "msys2"))
    if "/" not in fwd:
        return None
    bs = fwd.replace("/", chr(92))
    if suffix == "bs":
        return bs
    if suffix == "bs2":
        return bs.replace(chr(92), chr(92) * 2)
    if suffix == "bs4":
        return bs.replace(chr(92), chr(92) * 4)
    return None


def _encode_variants(value_name, suffix, values):
    """Search strings for one placeholder: the canonical spelling, plus the
    8.3 short-user-name spelling of the same path when one exists.

    The 8.3 variant is a search string only. It decodes back to the long
    form, so any source line that uses it fails the round-trip self-check in
    render_template and refuses the run (SPELLING_NOT_ROUND_TRIPPABLE)."""
    base = _spelling_for(value_name, suffix, values)
    if not base:
        return []
    variants = [base]
    short = _short_name_variant(base)
    if short and short != base:
        variants.append(short)
    return variants


def secret_map(mcp_cfg, settings_local, secrets_content, user_settings=None,
                placeholder_missing=False, missing_out=None):
    """Match every secret-class env/header value against secrets_content
    ({stripped content: file name}).

    settings_local.env uses the legacy SECRET_KEY-named rule (unchanged
    scope). mcp.env, mcp.headers and user_settings.env use the default-deny
    rule (_classify_env_value): secret-class unless the value is an
    explicit non-secret shape (URL, filesystem path) or the key is
    allow-listed (ENV_VALUE_ALLOW_LIST) or the value is shorter than
    SECRET_SCAN_MIN_LEN.

    Returns {live value: file name}. Without placeholder_missing, raises
    SecretNotFoundError naming the key when a secret-class value has no
    match. With placeholder_missing, a derived file name is used instead
    (never written to disk) and {"file": ..., "key_path": ...} is appended
    to missing_out.
    """
    mapping = {}

    def _refuse_or_placeholder(label, key, name_parts, value):
        if not placeholder_missing:
            raise SecretNotFoundError(
                f"no secrets/ file matches the value of key {label}{key!r}"
            )
        fname = _derive_secret_filename(name_parts + [key])
        mapping[value] = fname
        if missing_out is not None:
            missing_out.append({"file": fname, "key_path": label + key})

    def scan_key_based(container, label, name_parts):
        """settings_local.env only: legacy SECRET_KEY-named rule."""
        if not isinstance(container, dict):
            return
        for key, value in container.items():
            if not isinstance(value, str):
                continue
            stripped = value.strip()
            if len(stripped) < SECRET_SCAN_MIN_LEN:
                continue
            match = secrets_content.get(stripped)
            if match:
                mapping[value] = match
                continue
            if not SECRET_KEY.search(key):
                continue
            _refuse_or_placeholder(label, key, name_parts, value)

    def scan_default_deny(container, label, name_parts):
        """mcp.env/headers and user_settings.env: default-deny rule."""
        if not isinstance(container, dict):
            return
        for key, value in container.items():
            if not isinstance(value, str):
                continue
            kind, match = _classify_env_value(key, value, secrets_content)
            if kind in ("skip", "value"):
                continue
            if match:
                mapping[value] = match
                continue
            _refuse_or_placeholder(label, key, name_parts, value)

    for name, cfg in sorted((mcp_cfg.get("mcpServers") or {}).items()):
        scan_default_deny(cfg.get("env") or {}, f"mcpServers.{name}.env.", ["mcp", name])
        scan_default_deny(cfg.get("headers") or {}, f"mcpServers.{name}.headers.", ["mcp", name])

    scan_key_based(settings_local.get("env") or {}, "settings_local.env.", ["settings-local"])

    if user_settings is not None:
        scan_default_deny(user_settings.get("env") or {}, "user_settings.env.", ["user-settings"])

    return mapping


def url_is_tenant_bound(url):
    """True when an .mcp.json server url's query string carries a tenant- or
    credential-shaped parameter (TENANT_URL_PARAMS). Parameter NAMES only are
    ever read here; no value is returned, logged or compared."""
    if not isinstance(url, str) or "?" not in url:
        return False
    query = url.split("?", 1)[1]
    names = {
        part.split("=", 1)[0].strip().lower()
        for part in query.replace(";", "&").split("&")
        if part
    }
    return any(p in names for p in TENANT_URL_PARAMS)


def mcp_scan_values(mcp_cfg):
    """Every .mcp.json env/header value at or above O17's scan floor: the
    exact population check_d searches tracked artifacts for. Values are
    returned for containment tests only and are never printed or written."""
    out = []
    for _name, cfg in sorted((mcp_cfg.get("mcpServers") or {}).items()):
        for container in ((cfg.get("env") or {}), (cfg.get("headers") or {})):
            for value in container.values():
                v = str(value)
                if len(v) >= SECRET_SCAN_MIN_LEN:
                    out.append(v)
    return out


def url_needs_placeholder(url, scan_values=()):
    """True when an .mcp.json server url must not ship as a literal.

    Two rules, both per-machine by construction:
      1. the query string carries a tenant- or credential-shaped parameter
         (url_is_tenant_bound), for example a hosted database's project_ref;
      2. the url embeds another server's env or header value, which O17's
         check_d scans tracked artifacts for by substring (found live: one
         server's url starts with another server's API URL).
    """
    if not isinstance(url, str):
        return False
    if url_is_tenant_bound(url):
        return True
    return any(v and v != url and v in url for v in scan_values)


def value_map(mcp_cfg, secrets_content, needed_out=None, user_settings=None,
              skip_fs_paths=False):
    """Values classified 'value' (explicit non-secret shape or allow-listed
    key) by _classify_env_value, across mcp.env, mcp.headers and
    user_settings.env, plus every mcp server `url` that url_needs_placeholder
    classifies as per-machine:
    {live value: derived key}. Closes O17 check_d's own scan, which treats
    every .mcp.json env/header value as sensitive by construction, without
    smuggling a secret-class value into this, externally-resolved,
    non-secret bucket. {"key": ..., "key_path": ...} is appended to
    needed_out.

    skip_fs_paths (the bare profile) leaves filesystem-path values to the
    PATH encoder instead. A path under the vault, the home directory or the
    npm prefix is already modelled by {{vault}}/{{home}}/{{npm}}, which the
    runner fills from --target and --home alone; turning it into a
    {{value:<key>}} the owner has to supply is the difference between "bare
    needs no values file" and "bare needs three". A path-shaped value under
    none of those prefixes stays literal and is then reported by check()'s
    MACHINE_PATH_IN_TEMPLATE, which is the visible failure this trade wants.
    """
    mapping = {}
    scan_values = mcp_scan_values(mcp_cfg)

    def scan(container, name_parts, key_path_prefix):
        for key, value in container.items():
            if not isinstance(value, str):
                continue
            kind, _ = _classify_env_value(key, value, secrets_content)
            if kind != "value":
                continue
            if skip_fs_paths and ENV_FS_PATH_RE.match(value.strip()):
                continue
            derived = _derive_value_key(name_parts + [key])
            mapping[value] = derived
            if needed_out is not None:
                needed_out.append({"key": derived, "key_path": key_path_prefix + key})

    for name, cfg in sorted((mcp_cfg.get("mcpServers") or {}).items()):
        scan(cfg.get("env") or {}, ["mcp", name], f"mcpServers.{name}.env.")
        scan(cfg.get("headers") or {}, ["mcp", name], f"mcpServers.{name}.headers.")
        url = cfg.get("url")
        if url_needs_placeholder(url, scan_values):
            derived = _derive_value_key(["mcp", name, "url"])
            mapping[url] = derived
            if needed_out is not None:
                needed_out.append({"key": derived, "key_path": f"mcpServers.{name}.url"})

    if user_settings is not None:
        scan(user_settings.get("env") or {}, ["user-settings"], "user_settings.env.")

    return mapping


def assert_no_secret_leak(text, secrets_content, label):
    """Raise SecretLeakError if any secrets_content value is present in text."""
    for content, fname in secrets_content.items():
        if content and content in text:
            raise SecretLeakError(
                f"{label}: contains the content of secrets/{fname}"
            )


def assert_no_credential_pattern(text, label):
    """Raise CredentialPatternError (line number only, never the match) if
    any line matches the imported CREDENTIAL_PATTERNS: the final net,
    independent of how a value was classified upstream."""
    for lineno, line in enumerate(text.split("\n"), start=1):
        if CREDENTIAL_PATTERNS.search(line):
            raise CredentialPatternError(
                f"{label}:{lineno}: CREDENTIAL_PATTERN_IN_TEMPLATE"
            )


def _strip_generator_note(text):
    """Remove the one GENERATOR_NOTE line if the text starts with it."""
    return GENERATOR_NOTE_RE.sub("", text, count=1)


def _decode_for_selfcheck(text, values, smap, vmap):
    """Decode a just-generated template back to its source text, resolving
    secrets and values from the very maps that produced them (never from
    disk, so a missing secrets/ file cannot masquerade as a spelling
    defect). Used only by the round-trip self-check below."""
    secret_inv = {}
    for value, fname in smap.items():
        secret_inv.setdefault(fname, value)
    value_inv = {}
    for value, derived_key in vmap.items():
        value_inv.setdefault(derived_key, value)

    out = SECRET_PLACEHOLDER_RE.sub(
        lambda m: secret_inv.get(m.group(1), m.group(0)), text
    )
    out = VALUE_PLACEHOLDER_RE.sub(
        lambda m: value_inv.get(m.group(1), m.group(0)), out
    )
    out = PATH_PLACEHOLDER_RE.sub(
        lambda m: _spelling_for(m.group(1), m.group(2), values) or m.group(0), out
    )
    return _strip_generator_note(out)


def assert_round_trips(text, live_text, values, smap, vmap, label):
    """Refuse a template that does not decode back to its own source.

    The live case is the DOS 8.3 short user name: it encodes to the same
    placeholder as the long form and decodes only to the long form, so the
    template is lossy and `check` is permanently red. Raises
    SpellingNotRoundTrippableError naming the label and the line numbers,
    never the line content (a mismatching line can carry a secret).
    """
    decoded = _decode_for_selfcheck(text, values, smap, vmap)
    if decoded == live_text:
        return
    decoded_lines = _crlf(decoded).split("\n")
    live_lines = _crlf(live_text).split("\n")
    bad = [
        i + 1
        for i in range(max(len(decoded_lines), len(live_lines)))
        if (decoded_lines[i] if i < len(decoded_lines) else None)
        != (live_lines[i] if i < len(live_lines) else None)
    ]
    raise SpellingNotRoundTrippableError(
        f"SPELLING_NOT_ROUND_TRIPPABLE: {label}: line(s) {bad} carry a spelling this "
        "generator cannot reproduce on decode (content not shown). The DOS 8.3 short "
        "user name is the known case: respell the source line in the long form, or add "
        "a distinct placeholder suffix for that spelling."
    )


def render_template(live_path, out_path, smap, vmap, values, secrets_content, note=None,
                    strict=True):
    """Render one template from one live file. Returns a placeholder count dict.

    Secrets and values are substituted only where the value is the entire
    JSON string ("<value>" becomes "{{...}}"); the path spellings keep
    substring substitution, where reaching inside a longer path is the
    point. `note`, when given, is prepended as one line and stripped again
    on decode.

    strict=True (the default, and the only value generate() ever passes)
    runs the round-trip self-check before anything reaches disk, so a lossy
    template is never written. strict=False is for tests that need to
    inspect a deliberately lossy encoding.
    """
    live_text = Path(live_path).read_text(encoding="utf-8", newline="")
    text = live_text
    counts = {}

    for value, fname in sorted(smap.items(), key=lambda kv: -len(kv[0])):
        needle = '"' + value + '"'
        n = text.count(needle)
        if n:
            text = text.replace(needle, '"{{secret:' + fname + '}}"')
            key = "secret:" + fname
            counts[key] = counts.get(key, 0) + n

    for value, derived_key in sorted(vmap.items(), key=lambda kv: -len(kv[0])):
        needle = '"' + value + '"'
        n = text.count(needle)
        if n:
            text = text.replace(needle, '"{{value:' + derived_key + '}}"')
            key = "value:" + derived_key
            counts[key] = counts.get(key, 0) + n

    for value_name in VALUE_ORDER:
        for suffix in SPELLING_ORDER:
            for variant in _encode_variants(value_name, suffix, values):
                n = text.count(variant)
                if not n:
                    continue
                token = "{{" + value_name + (":" + suffix if suffix else "") + "}}"
                text = text.replace(variant, token)
                key = value_name + (":" + suffix if suffix else "")
                counts[key] = counts.get(key, 0) + n

    if note:
        newline = "\r\n" if "\r\n" in live_text else "\n"
        text = note + newline + text

    if strict:
        assert_round_trips(text, live_text, values, smap, vmap, str(out_path))
    assert_no_secret_leak(text, secrets_content, str(out_path))
    assert_no_credential_pattern(text, str(out_path))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8", newline="")
    return counts


def _decode_placeholders(text, values, secrets_dir):
    def _sub_secret(m):
        fname = m.group(1)
        if secrets_dir is None:
            return m.group(0)
        p = Path(secrets_dir) / fname
        if not p.is_file():
            return m.group(0)
        return p.read_text(encoding="utf-8", newline="").strip()

    text = SECRET_PLACEHOLDER_RE.sub(_sub_secret, text)

    def _sub_value(m):
        v = values.get(m.group(1))
        return v if v is not None else m.group(0)

    text = VALUE_PLACEHOLDER_RE.sub(_sub_value, text)

    def _sub_path(m):
        v = _spelling_for(m.group(1), m.group(2), values)
        return v if v is not None else m.group(0)

    # The generator note is stripped here, not in render(), so check()'s
    # round trip and render()'s deploy output both lose it by one rule.
    return _strip_generator_note(PATH_PLACEHOLDER_RE.sub(_sub_path, text))


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def secrets_referenced(templates_dir, secrets_dir):
    """Every {{secret:<file>}} the templates carry, with whether the file
    exists on this machine. Names only, never a value. The superset
    _missing-secrets.json is the false-only slice of: the runbook needs the
    whole list, because a file that exists here still has to be copied to
    the target."""
    templates_dir = Path(templates_dir)
    secrets_dir = Path(secrets_dir) if secrets_dir is not None else None
    names = set()
    for tmpl_name in TEMPLATE_NAMES.values():
        p = templates_dir / tmpl_name
        if not p.is_file():
            continue
        names.update(SECRET_PLACEHOLDER_RE.findall(p.read_text(encoding="utf-8", newline="")))
    return [
        {
            "file": n,
            "exists_on_source": bool(secrets_dir) and (secrets_dir / n).is_file(),
        }
        for n in sorted(names)
    ]


def update_manifest_secrets(manifest_path, items):
    """Write the referenced secret FILE NAMES into the manifest's bare data
    sidecar, and the count into the manifest itself.

    The names live in the sidecar because every one of them is derived from
    the server it belongs to, so the list names the instances: five of the
    seven on this machine did, and they were shipping inside the manifest on
    every bare device. The manifest keeps the count and the pointer, which is
    what a reader needs to know something is owed. No-op when the manifest is
    absent or unparseable: filling a reserved field must never take a generate
    run down.
    """
    p = Path(manifest_path)
    if not p.is_file():
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return False
    items = list(items)
    secrets_block = data.get("secrets")
    if not isinstance(secrets_block, dict):
        secrets_block = {"filled_by": "blueprint_render"}
        data["secrets"] = secrets_block
    secrets_block.pop("items", None)
    secrets_block["count"] = len(items)
    secrets_block["items_file"] = "work-paths.json"
    p.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n",
    )
    sidecar_path = p.parent / "work-paths.json"
    sidecar = {}
    if sidecar_path.is_file():
        try:
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except ValueError:
            sidecar = {}
    sidecar["secrets_items"] = items
    sidecar_path.write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    return True


def _write_sidecar(out_dir, name, payload):
    (Path(out_dir) / name).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="",
    )


def scrub_sources(sources, secrets_dir, scrub_dir, report=None, values=None):
    """Write a bare-profile copy of every source into `scrub_dir` and return
    the new sources mapping.

    The scrub happens on a real file rather than in memory because everything
    downstream (the path-spelling encoder, the round-trip self-check, the
    secret-leak assertion) reads a file and compares against it. The scrubbed
    copy is the source of record for the round trip, which is exactly right:
    a bare template must reproduce the SCRUBBED file, not the live one.

    `report`, when given, collects per-source stats (names and counts only).
    """
    scrub_dir = Path(scrub_dir)
    scrub_dir.mkdir(parents=True, exist_ok=True)
    secrets_content = _load_secrets(secrets_dir)
    out = dict(sources)
    tree = bare_tree_paths()
    if report is not None:
        report["tree"] = {
            "available": tree is not None,
            "files": len(tree or ()),
        }

    mcp_cfg = _read_json(sources["mcp"])
    bare_mcp, dropped_servers = scrub_mcp_config(mcp_cfg)
    generic = sorted(bare_mcp.get("mcpServers") or {})
    assert_no_work_bound_term(bare_mcp, "mcp")
    out["mcp"] = _write_json(scrub_dir / "mcp.json", bare_mcp)

    for key, filename in (
        ("settings_local", "settings.local.json"),
        ("user_settings", "settings.json"),
    ):
        cfg = _read_json(sources[key])
        scrubbed, stats = scrub_settings(
            cfg, secrets_content, generic_servers=generic, tree=tree,
        )
        assert_no_work_bound_term(scrubbed, key)
        out[key] = _write_json(scrub_dir / filename, scrubbed)
        if report is not None:
            report[key] = stats

    for key, filename in (
        ("user_claude_md", "user-CLAUDE.md"),
        ("vault_claude_md", "vault-CLAUDE.md"),
    ):
        source_path = sources.get(key)
        if source_path is None:
            continue
        text = Path(source_path).read_text(encoding="utf-8", newline="")
        scrubbed, removed = scrub_markdown(text)
        assert_no_work_bound_term(scrubbed, key)
        target = scrub_dir / filename
        target.write_text(scrubbed, encoding="utf-8", newline="")
        out[key] = target
        if report is not None:
            report[key] = {"removed": removed}

    # The remaining twins, by kind. Each is written into the scrub directory
    # under its own deploy name and becomes the source of record for the round
    # trip, exactly as the two markdown twins above do.
    for _vault_path, key, _tmpl, deploy_name, kind in BARE_TWINS:
        if kind == "markdown" or sources.get(key) is None:
            continue
        source_path = Path(sources[key])
        if not source_path.is_file():
            continue
        if kind == "lines":
            text = source_path.read_text(encoding="utf-8", newline="")
            scrubbed, removed = scrub_lines(text)
            assert_no_work_bound_term(scrubbed, key)
            target = scrub_dir / deploy_name
            # Exactly one trailing newline, not "one more than last time":
            # scrub_lines keeps the source's own final newline, so appending
            # another grew the file by a byte on every pass and made the twin
            # fail its own idempotence check on the target (architect F8).
            target.write_text(scrubbed.rstrip("\n") + "\n", encoding="utf-8", newline="")
            out[key] = target
            if report is not None:
                report[key] = {"removed": removed}
        elif kind == "settings":
            cfg = _read_json(source_path)
            scrubbed, stats = scrub_settings(
                cfg, secrets_content, generic_servers=generic, tree=tree,
            )
            assert_no_work_bound_term(scrubbed, key)
            out[key] = _write_json(scrub_dir / deploy_name, scrubbed)
            if report is not None:
                report[key] = stats
        elif kind == "json_rows":
            data = _read_json(source_path)
            stats = {}
            scrubbed = scrub_json_rows(data, tree=tree, stats=stats)
            scrubbed = redact_foreign_paths(scrubbed, values, stats)
            assert_no_work_bound_term(scrubbed, key)
            out[key] = _write_json(scrub_dir / deploy_name, scrubbed)
            if report is not None:
                report[key] = {"rows_dropped": stats}

    qmd_source = sources.get("qmd_index")
    if qmd_source is not None:
        text = Path(qmd_source).read_text(encoding="utf-8", newline="")
        # The qmd index is the one placed file the bare profile never scrubbed:
        # it passed the term gate by carrying no listed name while pointing at
        # three directories a bare device does not have (adversarial F14).
        scrubbed, dropped_collections = scrub_qmd_index(text, tree=tree)
        assert_no_work_bound_term(scrubbed, "qmd_index")
        target = scrub_dir / "qmd-index.yml"
        target.write_text(scrubbed, encoding="utf-8", newline="")
        out["qmd_index"] = target
        if report is not None:
            report["qmd_index"] = {"collections_dropped": dropped_collections}

    if report is not None:
        report["mcp"] = {"servers_dropped": dropped_servers, "servers_kept": generic}
    return out


def _write_json(path, payload):
    path = Path(path)
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="",
    )
    return path


def _placeholder_keys(written, prefix):
    """The {{<prefix>:<key>}} tokens that actually reached a template, read
    off render_template's own count dicts."""
    out = set()
    for counts in written.values():
        for key in counts:
            if key.startswith(prefix + ":"):
                out.add(key.split(":", 1)[1])
    return out


def generate(sources, secrets_dir, out_dir, values=None, placeholder_missing=False,
             manifest_path=None, profile=DEFAULT_PROFILE, report=None):
    """Render one profile's templates from the live sources. Returns
    ({tmpl file name: placeholder count dict}, missing, values_needed).

    full: the five templates, rendered verbatim from this workstation's
    files. Unchanged behaviour. Raises SecretNotFoundError unless
    placeholder_missing=True, and SpellingNotRoundTrippableError when a
    source line carries a spelling that cannot be reproduced on decode.

    bare: the same five plus a scrubbed twin of the vault's own CLAUDE.md,
    rendered from SCRUBBED copies of the sources (scrub_sources). The scrub
    removes every work-bound MCP server, permission row, plugin, hook
    registration and doctrine section, which is why the bare profile owes no
    secret file and no --values-extra value: both sidecars come back empty
    because no placeholder of either kind survives the scrub. Raises
    WorkBoundTermError, before writing anything, if a term does survive.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (known: {', '.join(PROFILES)})")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    values = values or compute_values()

    scrub_dir = None
    try:
        if profile == "bare":
            scrub_dir = Path(tempfile.mkdtemp(prefix="blueprint-bare-scrub-"))
            sources = scrub_sources(
                sources, secrets_dir, scrub_dir, report=report, values=values,
            )
            # A scrubbed source owes nothing, so the secret and value maps
            # are computed against it, not against the live files.
            secrets_dir = None

        secrets_content = _load_secrets(secrets_dir)
        mcp_cfg = _read_json(sources["mcp"])
        settings_local_cfg = _read_json(sources["settings_local"])
        user_settings_cfg = _read_json(sources["user_settings"])

        missing = []
        smap = secret_map(
            mcp_cfg, settings_local_cfg, secrets_content, user_settings_cfg,
            placeholder_missing=placeholder_missing, missing_out=missing,
        )
        values_needed = []
        vmap = value_map(
            mcp_cfg, secrets_content, needed_out=values_needed,
            user_settings=user_settings_cfg, skip_fs_paths=(profile == "bare"),
        )

        written = {}
        for name in source_order(profile, sources):
            live_path = Path(sources[name])
            tmpl_name = TEMPLATE_NAMES[name]
            out_path = out_dir / tmpl_name
            counts = render_template(
                live_path, out_path, smap, vmap, values, secrets_content,
                note=(
                    GENERATOR_NOTE
                    if (name == "user_claude_md" and profile == "full")
                    else None
                ),
            )
            written[tmpl_name] = counts
    finally:
        if scrub_dir is not None:
            shutil.rmtree(scrub_dir, ignore_errors=True)

    if profile == "bare":
        # The bare profile reports what the TEMPLATES actually carry. The
        # full profile keeps its historical superset (three of its eight
        # keys are runner-computed and never become a token, and both the
        # runbook and bootstrap_machine._computed_value_defaults name them),
        # so the narrowing is scoped to bare rather than applied to both.
        present_values = _placeholder_keys(written, "value")
        present_secrets = _placeholder_keys(written, "secret")
        values_needed = [e for e in values_needed if e["key"] in present_values]
        missing = [e for e in missing if e["file"] in present_secrets]
        for name in source_order(profile, sources):
            assert_no_work_bound_term(
                (out_dir / TEMPLATE_NAMES[name]).read_text(encoding="utf-8", newline=""),
                TEMPLATE_NAMES[name],
            )

    # All three sidecars are written every run, with an empty list when
    # nothing is owed. An absent file is ambiguous, and a stale one told the
    # owner to recreate secrets that already existed.
    _write_sidecar(
        out_dir, SIDECAR_MISSING_SECRETS,
        {"missing_secrets": sorted(missing, key=lambda d: d["file"])},
    )
    _write_sidecar(
        out_dir, SIDECAR_VALUES_NEEDED,
        {"values_needed": sorted(values_needed, key=lambda d: d["key"])},
    )
    referenced = secrets_referenced(out_dir, secrets_dir)
    _write_sidecar(out_dir, SIDECAR_SECRETS_REFERENCED, {"secrets_referenced": referenced})

    # Full profile only. The bare templates reference no secret at all, so a
    # bare run would otherwise blank the full profile's record of what the
    # owner has to copy, which is the one thing that list exists for.
    if manifest_path is not None and profile == "full":
        update_manifest_secrets(manifest_path, referenced)

    return written, missing, values_needed


def check_d_over_templates(templates_dir, sources, secrets_dir, profile=DEFAULT_PROFILE):
    """Run the imported O17 check_d over every rendered template, scanning
    for live .mcp.json env/header values. Returns [(code, detail)]."""
    templates_dir = Path(templates_dir)
    artifact_paths = [
        templates_dir / TEMPLATE_NAMES[n] for n in source_order(profile, sources)
        if (templates_dir / TEMPLATE_NAMES[n]).is_file()
    ]
    mcp_path = sources["mcp"]
    mcp_cfg = _read_json(mcp_path)
    rows = [
        {"name": n, "bucket": "MACHINE-BOUND"}
        for n in sorted((mcp_cfg.get("mcpServers") or {}).keys())
    ]
    manifest_block = {"sections": {"mcp_servers": rows}}
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8", newline=""
    )
    try:
        tmp.write("```json\n" + json.dumps(manifest_block) + "\n```\n")
        tmp.close()
        raw = check_d(tmp.name, mcp_path, artifact_paths)
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return [("CHECK-D " + code, detail) for code, detail in raw]


def check(templates_dir, sources, secrets_dir, values=None, profile=DEFAULT_PROFILE):
    """Verify one profile's templates. Returns [(code, detail)].

    Both profiles check placeholder resolution, residual secret values,
    residual machine paths and usernames, credential shapes, and the
    imported O17 check_d.

    full additionally round trips every template against its live source: a
    full template is a verbatim encoding, so a byte that does not come back
    is a defect.

    bare cannot round trip against the live source, because it is a SCRUB:
    the template is deliberately not the live file. Its three replacements
    are idempotence (generating twice gives identical bytes),
    GENERIC_SERVER_MISSING (every server the classifier calls generic
    survived), and WORKBOUND_TERM_IN_BARE_TEMPLATE (scan_text over every
    template, including the vault CLAUDE.md twin, returns nothing).
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile: {profile!r} (known: {', '.join(PROFILES)})")
    templates_dir = Path(templates_dir)
    secrets_dir = Path(secrets_dir) if secrets_dir is not None else None
    values = values or compute_values()
    secrets_content = _load_secrets(secrets_dir)
    findings = []

    mcp_cfg = _read_json(sources["mcp"])
    user_settings_cfg = _read_json(sources["user_settings"]) if sources.get("user_settings") else {}
    check_values = dict(values)
    for live_value, derived_key in value_map(
        mcp_cfg, secrets_content, user_settings=user_settings_cfg,
        skip_fs_paths=(profile == "bare"),
    ).items():
        check_values[derived_key] = live_value

    for name in source_order(profile, sources):
        tmpl_path = templates_dir / TEMPLATE_NAMES[name]
        live_path = Path(sources[name])
        if not tmpl_path.is_file():
            findings.append(("TEMPLATE_MISSING", str(tmpl_path)))
            continue
        tmpl_text = tmpl_path.read_text(encoding="utf-8", newline="")
        tmpl_lines = tmpl_text.split("\n")

        unresolved_lines = set()
        for lineno, line in enumerate(tmpl_lines):
            for m in SECRET_PLACEHOLDER_RE.finditer(line):
                fname = m.group(1)
                if secrets_dir is None or not (secrets_dir / fname).is_file():
                    findings.append((
                        "UNRESOLVED_SECRET_FILE",
                        f"{tmpl_path}:{lineno + 1}: {{{{secret:{fname}}}}} names a file "
                        f"absent from {secrets_dir}",
                    ))
                    unresolved_lines.add(lineno)

        for content, fname in secrets_content.items():
            if content and content in tmpl_text:
                findings.append((
                    "SECRET_VALUE_IN_TEMPLATE",
                    f"{tmpl_path}: contains the content of secrets/{fname} unreplaced",
                ))

        if NAME_RE.search(tmpl_text):
            findings.append((
                "USERNAME_IN_TEMPLATE",
                f"{tmpl_path}: an unsubstituted machine username remains",
            ))

        for lineno, line in enumerate(tmpl_lines, start=1):
            if MACHINE_TOKEN.search(line):
                findings.append((
                    "MACHINE_PATH_IN_TEMPLATE",
                    f"{tmpl_path}:{lineno}: an unsubstituted machine-shaped path remains",
                ))

        for lineno, line in enumerate(tmpl_lines, start=1):
            if CREDENTIAL_PATTERNS.search(line):
                findings.append((
                    "CREDENTIAL_PATTERN_IN_TEMPLATE",
                    f"{tmpl_path}:{lineno}: a credential-shaped string remains",
                ))

        if profile == "bare":
            for lineno, term in wb.scan_text(tmpl_text):
                findings.append((
                    "WORKBOUND_TERM_IN_BARE_TEMPLATE",
                    f"{tmpl_path}:{lineno}: carries the work-bound term {term!r}",
                ))
            continue

        if not live_path.is_file():
            findings.append(("SOURCE_MISSING", str(live_path)))
            continue

        rendered = _decode_placeholders(tmpl_text, check_values, secrets_dir)
        live_text = live_path.read_text(encoding="utf-8", newline="")
        rendered_lines = _crlf(rendered).split("\n")
        live_lines = _crlf(live_text).split("\n")
        mismatched = [
            i + 1
            for i in range(max(len(rendered_lines), len(live_lines)))
            if i not in unresolved_lines
            and (rendered_lines[i] if i < len(rendered_lines) else None)
            != (live_lines[i] if i < len(live_lines) else None)
        ]
        if mismatched:
            findings.append((
                "ROUND_TRIP_MISMATCH",
                f"{tmpl_path} vs {live_path}: line(s) {mismatched} differ after "
                "CRLF normalisation",
            ))

    if profile == "bare":
        findings += _bare_only_findings(templates_dir, sources, values)

    findings += check_d_over_templates(templates_dir, sources, secrets_dir, profile=profile)
    return findings


def _bare_only_findings(templates_dir, sources, values):
    """Idempotence and generic-server survival, the two checks that replace
    the full profile's round trip.

    Every exception generate() can raise is caught and REPORTED. It used to
    catch one class of five, so the documented `check --profile bare` command
    exited with a traceback and zero findings printed, converting a finding
    the full profile would have reported into a crash (architect F3a). A
    checker that raises is strictly worse than one that reports.
    """
    findings = []
    templates_dir = Path(templates_dir)

    tmp = Path(tempfile.mkdtemp(prefix="blueprint-bare-check-"))
    try:
        generate(sources, None, tmp, values=values, profile="bare", manifest_path=None)
        for name in source_order("bare", sources):
            a = templates_dir / TEMPLATE_NAMES[name]
            b = tmp / TEMPLATE_NAMES[name]
            if not a.is_file() or not b.is_file():
                continue
            if a.read_bytes() != b.read_bytes():
                findings.append((
                    "BARE_NOT_IDEMPOTENT",
                    f"{a}: regenerating from the same sources produced different bytes",
                ))
    except WorkBoundTermError as exc:
        findings.append(("WORKBOUND_TERM_IN_BARE_TEMPLATE", str(exc)))
    except SpellingNotRoundTrippableError as exc:
        findings.append(("SPELLING_NOT_ROUND_TRIPPABLE", str(exc)))
    except SecretNotFoundError as exc:
        findings.append(("UNRESOLVED_SECRET_FILE", str(exc)))
    except SecretLeakError as exc:
        findings.append(("SECRET_VALUE_IN_TEMPLATE", str(exc)))
    except CredentialPatternError as exc:
        findings.append(("CREDENTIAL_PATTERN_IN_TEMPLATE", str(exc)))
    except (OSError, ValueError) as exc:
        findings.append((
            "BARE_REGENERATION_FAILED",
            f"regenerating the bare templates raised {type(exc).__name__}: {exc}",
        ))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    mcp_tmpl = templates_dir / TEMPLATE_NAMES["mcp"]
    if mcp_tmpl.is_file():
        expected = wb.generic_mcp_servers(_read_json(sources["mcp"]))
        try:
            shipped = sorted(
                (json.loads(mcp_tmpl.read_text(encoding="utf-8", newline=""))
                 .get("mcpServers") or {})
            )
        except ValueError as exc:
            findings.append(("BARE_MCP_UNPARSEABLE", f"{mcp_tmpl}: {exc}"))
            shipped = []
        for name in expected:
            if name not in shipped:
                findings.append((
                    "GENERIC_SERVER_MISSING",
                    f"{mcp_tmpl}: the generic server {name!r} did not survive the scrub",
                ))
    return findings


def _apply_source_overrides(sources, settings_local=None):
    """Return a copy of sources with settings_local replaced when given.

    Lets generate/check be pointed at A3's portable wiring file
    (.claude/blueprint/settings.local.portable.json) instead of the live,
    absolute-path settings.local.json, without changing the default.
    """
    sources = dict(sources)
    if settings_local is not None:
        sources["settings_local"] = Path(settings_local)
    return sources


def render(templates_dir, out_dir, values, secrets_dir, profile=DEFAULT_PROFILE):
    """Deploy: fill every placeholder in the profile's templates, writing the
    live-shaped files to out_dir. Raises UnresolvedPlaceholderError naming
    every leftover placeholder token (never a value) and writes nothing if
    any placeholder in any template cannot resolve. Returns the list of
    written paths."""
    templates_dir = Path(templates_dir)
    out_dir = Path(out_dir)
    secrets_dir = Path(secrets_dir) if secrets_dir is not None else None

    rendered = {}
    unresolved = set()
    for name in source_order(profile):
        tmpl_path = templates_dir / TEMPLATE_NAMES[name]
        if not tmpl_path.is_file():
            continue
        text = tmpl_path.read_text(encoding="utf-8", newline="")
        text = _decode_placeholders(text, values, secrets_dir)
        rendered[name] = text
        unresolved.update(LEFTOVER_PLACEHOLDER_RE.findall(text))

    if unresolved:
        raise UnresolvedPlaceholderError(
            "render refuses: unresolved placeholder(s) " + ", ".join(sorted(unresolved))
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in source_order(profile):
        if name not in rendered:
            continue
        out_path = out_dir / DEPLOY_NAMES[name]
        out_path.write_text(rendered[name], encoding="utf-8", newline="")
        written.append(str(out_path))
    return written


def _print_bare_report(report):
    """What the bare scrub removed, by name and count. No value, no line."""
    tree = report.get("tree") or {}
    if tree:
        print(
            f"BARE_TREE: {tree.get('files', 0)} file(s) in the bare checkout"
            if tree.get("available")
            else "BARE_TREE: NOT AVAILABLE (no bare data sidecar here): the "
                 "dangling-reference and qmd-collection rules were SKIPPED"
        )
    for key in ("vault_gitignore", "control_probes", "install_prereqs_manifest"):
        stats = report.get(key)
        if not stats:
            continue
        if "rows_dropped" in stats:
            counts = stats["rows_dropped"] or {}
            print(
                f"BARE_TWIN {key}: dropped "
                + (", ".join(f"{n} row(s) ({why})" for why, n in sorted(counts.items()))
                   or "nothing")
            )
        else:
            print(f"BARE_TWIN {key}: dropped {len(stats.get('removed') or [])} line(s)")
    qmd = report.get("qmd_index") or {}
    if qmd:
        dropped = qmd.get("collections_dropped") or []
        print(
            f"BARE_QMD: dropped {len(dropped)} collection(s) pointing outside the "
            f"bare tree: {', '.join(dropped) or 'none'}"
        )
    mcp = report.get("mcp") or {}
    if mcp:
        print(
            f"BARE_MCP: kept {len(mcp.get('servers_kept') or [])} generic server(s) "
            f"({', '.join(mcp.get('servers_kept') or []) or 'none'}); dropped "
            f"{len(mcp.get('servers_dropped') or [])}"
        )
    for key, label in (
        ("settings_local", "settings.local.json"),
        ("user_settings", "settings.json"),
    ):
        stats = report.get(key)
        if not stats:
            continue
        rows = stats.get("permission_rows_by_reason") or {}
        entries = stats.get("hook_entries_by_reason") or {}
        print(
            f"BARE_SCRUB {label}: {stats['permission_rows_dropped']} permission row(s) "
            + "(" + ", ".join(f"{n} {why}" for why, n in sorted(rows.items())) + "), "
            f"{len(stats['env_keys_dropped'])} env key(s), "
            f"{len(stats['plugins_dropped'])} plugin(s), "
            f"{len(stats['marketplaces_dropped'])} marketplace(s), "
            f"{len(stats['mcp_servers_dropped'])} enabled server(s), "
            f"{stats['hook_entries_dropped']} hook entry/entries "
            + "(" + ", ".join(f"{n} {why}" for why, n in sorted(entries.items())) + ") in "
            f"{stats['hook_groups_dropped']} dropped group(s)"
        )
        if stats.get("plugins_dropped"):
            print(f"  plugins dropped: {', '.join(stats['plugins_dropped'])}")
        if stats.get("marketplaces_dropped"):
            print(f"  marketplaces dropped: {', '.join(stats['marketplaces_dropped'])}")
    for key, label in (
        ("user_claude_md", "~/.claude/CLAUDE.md"),
        ("vault_claude_md", "the vault CLAUDE.md"),
    ):
        stats = report.get(key)
        if not stats:
            continue
        removed = stats.get("removed") or []
        sections = [r["heading"] for r in removed if r["kind"] == "section"]
        lines = [r for r in removed if r["kind"] == "line"]
        print(
            f"BARE_SCRUB {label}: {len(sections)} section(s), {len(lines)} line(s)"
        )
        for heading in sections:
            print(f"  section dropped: {heading}")
        for row in lines:
            print(
                f"  line dropped: {row['line_number']} "
                f"({', '.join(row['terms'])})"
            )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _add_profile(parser):
        parser.add_argument(
            "--profile", choices=PROFILES, default=DEFAULT_PROFILE,
            help="bare (default): the harness mechanism and a bare vault, "
                 "nothing company-specific, no secret file and no owed value. "
                 "full: this workstation reproduced verbatim.",
        )

    g = sub.add_parser("generate")
    _add_profile(g)
    g.add_argument("--out", default=None)
    g.add_argument("--secrets", default=None)
    g.add_argument(
        "--settings-local", default=None,
        help="override the settings_local source. DEFAULT: the live "
             ".claude/settings.local.json in the full profile, and "
             ".claude/blueprint/settings.local.portable.json in bare, which is "
             "the only source the shipped bare templates reproduce byte for byte",
    )
    g.add_argument(
        "--placeholder-missing", action="store_true",
        help="emit a derived {{secret:<name>}} placeholder instead of refusing "
             "when a secret-keyed value has no secrets/ file match",
    )
    g.add_argument(
        "--manifest", default=str(default_manifest_path()),
        help="blueprint manifest whose secrets.items this run fills; "
             "pass an empty string to skip the manifest write",
    )

    c = sub.add_parser("check")
    _add_profile(c)
    c.add_argument("--templates-dir", default=None)
    c.add_argument("--secrets", default=None)
    c.add_argument(
        "--settings-local", default=None,
        help="override the settings_local source. DEFAULT: the live "
             ".claude/settings.local.json in the full profile, and "
             ".claude/blueprint/settings.local.portable.json in bare. The live "
             "file is rewritten on every permission approval and has carried a "
             "spelling this generator cannot round trip, so a bare check against "
             "it cannot be green for reasons that have nothing to do with bare",
    )

    r = sub.add_parser("render")
    _add_profile(r)
    r.add_argument("--values", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--templates-dir", default=None)
    r.add_argument("--secrets", default=None)

    args = ap.parse_args()
    profile = getattr(args, "profile", DEFAULT_PROFILE)
    sources = default_sources(profile)
    # The bare profile owes no secret file, so --secrets defaults to nothing
    # there rather than to this machine's secrets directory.
    secrets = getattr(args, "secrets", None)
    if secrets is None and profile == "full":
        secrets = str(default_secrets_dir())
    templates_dir = getattr(args, "templates_dir", None) or str(default_templates_dir(profile))

    if args.cmd == "generate":
        sources = _apply_source_overrides(sources, args.settings_local)
        out_dir = args.out or str(default_templates_dir(profile))
        report = {}
        try:
            written, missing, values_needed = generate(
                sources, secrets, out_dir, placeholder_missing=args.placeholder_missing,
                manifest_path=(args.manifest or None), profile=profile, report=report,
            )
        except (SecretNotFoundError, SpellingNotRoundTrippableError,
                WorkBoundTermError) as exc:
            print(f"REFUSED: {exc}")
            return 2
        args.out = out_dir
        print(f"profile: {profile}")
        for name in source_order(profile):
            tmpl_name = TEMPLATE_NAMES[name]
            counts = written.get(tmpl_name, {})
            print(f"{tmpl_name}: {json.dumps(counts, sort_keys=True)}")
        if profile == "bare":
            _print_bare_report(report)
        if missing:
            names = sorted(d["file"] for d in missing)
            print(
                f"WARNING: {len(missing)} secret-keyed value(s) had no secrets/ file; "
                "placeholder(s) emitted, see _missing-secrets.json"
            )
            print(f"MISSING_SECRET_FILES: {', '.join(names)}")
        if values_needed:
            keys = sorted(d["key"] for d in values_needed)
            print(f"VALUES_NEEDED: {', '.join(keys)}")
        referenced = secrets_referenced(out_dir, secrets)
        print(
            f"SECRETS_REFERENCED: {len(referenced)} file(s) named by the templates, "
            f"{sum(1 for d in referenced if not d['exists_on_source'])} absent here; "
            f"full list in {SIDECAR_SECRETS_REFERENCED} (every one of them has to be "
            "copied to the target, not only the absent ones)"
        )
        return 0

    if args.cmd == "check":
        sources = _apply_source_overrides(sources, args.settings_local)
        findings = check(templates_dir, sources, secrets, profile=profile)
        print(f"profile: {profile}")
        for code, detail in findings:
            print(f"{code}: {detail}")
        print(f"FINDINGS: {len(findings)}")
        return 1 if findings else 0

    if args.cmd == "render":
        values = json.loads(Path(args.values).read_text(encoding="utf-8"))
        try:
            written = render(templates_dir, args.out, values, secrets, profile=profile)
        except UnresolvedPlaceholderError as exc:
            print(f"REFUSED: {exc}")
            return 2
        for p in written:
            print(f"rendered: {p}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
