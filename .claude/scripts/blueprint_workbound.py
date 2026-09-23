"""Work-bound classification for the blueprint's bare profile (B1, B5).

Owner ask, verbatim: "FRESH DEVICE NEEDS JUST THE HARNESS AND BARE VAULT,
NOTHING [EMPLOYER] SPECIFIC." The full profile reproduces this workstation. The
bare profile reproduces the MECHANISM plus an empty vault skeleton, and this
module is the single place that decides which side of that line a thing sits
on.

Four classifiers, two scanners, one term list:

  classify_mcp_server(name, spec) -> "generic" | "work-bound"
  classify_permission_row(text)   -> "generic" | "work-bound"
  classify_path(path)             -> "generic" | "work-bound"
  work_dir_prefix(path)           -> the shortest work-bound ancestor, or None
  scan_text(text)                 -> [(line number, label), ...]
  scan_tree(root, relpaths)       -> [{path, line, term}, ...] over CONTENT

THE NAMES ARE DATA, THE MECHANISM IS CODE. The term list lives in
`.claude/blueprint/workbound-terms.json`, a file the bare profile deliberately
does not check out, because the list is itself the disclosure: an enumeration
of every employer, client, teammate, tracker and instance the owner wants kept
off a fresh device is exactly the document a stranger would want. The module
ships everywhere; the names ship only where they already are. On a device with
no term data, TERMS is empty, TERMS_SOURCE is None and terms_available() is
False, and every gate that depends on this module reports that rather than a
0-hit pass it did not earn.

Three match kinds, and the reason each exists is measured rather than
guessed. `.claude/skills/repo-sync/nda_gate.py` is a DIFFERENT gate (it blocks
a push to a public repository, this one shapes a local profile) but it learned
the same lesson first: employer and infrastructure tokens are matched as
case-insensitive SUBSTRINGS, because a company token must also catch its
domain and compound spellings; personal names are matched WORD-bounded,
because a short surname inside an ordinary English word was a real false
positive in manual review; and a tracker or namespace token is matched as a
left-bounded PREFIX so one entry covers its numeric and word suffixes. The two
lists overlap and are not the same scope, so this module keeps its own data
file: it must not change behaviour when the push gate is widened for a reason
that has nothing to do with a bare device.

B5 adds the two halves both 2026-09-22 reviews proved missing.

NORMALISATION. A literal substring matcher sees none of: a name split by
markdown emphasis or a backtick pair, an HTML entity, a percent escape, a
zero-width character, a fullwidth or compatibility form, or a name typed with
a space between every letter. All six were measured evading the gate end to
end, and the first is not an exotic attack: emphasis inside a word is how a
name gets written when somebody is being emphatic. Every line is therefore
matched in several NORMALISED variants as well as raw. The variants are
additive (a hit in any of them is a hit), so the cost of the design is false
positives, and the suite pins the shapes most likely to collide.

SHAPE RULES. A token list cannot see disclosure by shape. An IP address, a
`root@` login, an SSH key path and a deployment path are all zero-token
strings, and the same gate named above records why that matters: a production
VPS address with a root login sat in a public repository for seven days across
a passing run of a token-only gate. The generic shapes below carry no proper
noun and ship with the module; the two that name an organisation or a tracker
prefix live in the data file with the terms.

Deliberate non-terms, each a decision rather than an omission, all recorded
with their reason in the data file's `why` fields:
  - the product name of the owner's own stack. His stack travels: its skills,
    agents, hooks and doctrine are harness. The INSTANCES are not, so the
    server names and instance hosts are terms and the product name is not.
  - the owner's own name. The claim under test is "nothing employer specific",
    not "nothing identifying". A device meant to be handed over is a separate
    question, and it is the owner's to answer.

No credential value is ever read by any classifier here. classify_mcp_server
reads key NAMES, the SHAPE of a value (is it a remote host) and nothing else.
"""
import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import o17_portability_manifest as o17  # noqa: E402  (path insert must run first)

# Imported by identity, never re-derived (GUD-001): the same key-name rule
# that decides "this env key holds a secret" everywhere else in the blueprint.
SECRET_KEY = o17.SECRET_KEY

VAULT_ROOT = Path(__file__).resolve().parents[2]

GENERIC = "generic"
WORK_BOUND = "work-bound"

SUBSTRING = "substring"
WORD = "word"
PREFIX = "prefix"
# A data-file-only kind, expanded at load time into three SUBSTRING terms
# (hyphen, underscore, space). A two-word product name is written all three
# ways in the wild and one entry should cover all three.
COMPOUND = "compound"

# Where the names live. The environment variable exists for one measured
# case: the runner applies a profile from THIS machine to a target, and the
# target's own copy of this module has no data file. Pointing the target's
# process at the source's file keeps that one check full strength without
# copying any name onto the device.
TERMS_FILE_ENV = "BLUEPRINT_WORKBOUND_TERMS"
DEFAULT_TERMS_FILE = VAULT_ROOT / ".claude" / "blueprint" / "workbound-terms.json"


class Term(NamedTuple):
    text: str
    kind: str
    label: str = ""


def _term(text, kind, label=None):
    return Term(text, kind, label or text)


# ---------------------------------------------------------------------------
# scan-time terms: a client arrives as a directory, not as an edit to a list
# ---------------------------------------------------------------------------

DYNAMIC_TERM_ROOTS = ("Projects", "Archives")

# Directory names under those roots that are NOT company or client material.
# Each one is a judgement with its reason, because the alternative (a rule
# that infers it) would silently exclude a future client whose folder happens
# to read like harness vocabulary. Anything not listed here becomes a
# word-bounded term at scan time.
DYNAMIC_TERM_EXCLUSION_REASONS = {
    "Agent-Governance-Research": "the vault's own governance research; its scripts and three "
                                 "work files are named in the manifest's extra core paths and "
                                 "ship in bare on purpose",
    "Vault-Maintenance": "the vault's own maintenance project, the one this blueprint is built in",
    "Claude-Code-Workshop": "names the product the harness runs on, not a client",
    "Claude-Code-Workshop-V2": "same",
    "Observability": "an ordinary harness word; the vault has an observability dashboard and an "
                     "observability tag, so a word term here fires constantly and reads as noise",
    "Personal": "ordinary English, and personal material is out of the employer-specific claim",
    "Consultations": "ordinary English",
    "loose": "ordinary English; an archive holding bucket",
    "vault-setup": "ordinary harness words",
    "ralph-legacy": "the Ralph Loop is harness doctrine",
    "n8n-Error-Handling": "the owner's own stack doctrine, which travels by the module's own "
                          "stated rule: the product is harness, the instances are not",
    "n8n-guidelines": "same",
    "Repo-Intelligence-2026-05": "vault-internal repository investigation, date-stamped housekeeping",
    "Repo-Investigation-2026-05-13": "same",
    "Repo-Investigation-2026-05-15": "same",
    "Daily-Notes-2026-06-18": "the retired vault daily-notes folder",
    "leftovers-2026-06-18": "vault housekeeping",
    "agent-backups-2026-03-19": "vault housekeeping",
    "h11-test-qa": "a vault-internal test bucket",
}
DYNAMIC_TERM_EXCLUSIONS = frozenset(DYNAMIC_TERM_EXCLUSION_REASONS)


def dynamic_dir_terms(vault_root=None):
    """Every directory name under Projects/ and Archives/ as a WORD term,
    minus the documented harness-word exclusions.

    Read at scan time from the tree being scanned, never persisted: writing
    the resolved list into a shipped file would recreate the very disclosure
    the data file split exists to prevent. On a bare device those two
    directories are empty, which is the correct answer there.
    """
    root = Path(vault_root or VAULT_ROOT)
    out = []
    for parent in DYNAMIC_TERM_ROOTS:
        base = root / parent
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            name = child.name
            if name in DYNAMIC_TERM_EXCLUSIONS or name.startswith("."):
                continue
            out.append(_term(name, WORD))
    return out


# ---------------------------------------------------------------------------
# generic shapes: disclosure a name list cannot see
# ---------------------------------------------------------------------------

_IPV4_RE = re.compile(r"(?<![\d.\w])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])")
_VERSION_CONTEXT_RE = re.compile(
    r"(?:\bversion|\bver|\brelease|\brev|\bv|>=|<=|==|~=|\^)\s*$",
    re.IGNORECASE,
)
_PRIVILEGED_LOGIN_RE = re.compile(
    r"\broot@(?=[A-Za-z0-9])[A-Za-z0-9._-]+", re.IGNORECASE
)
_SSH_INVOCATION_RE = re.compile(
    r"\bssh\b[^\n]{0,60}?(?<![\w@.])[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\b",
    re.IGNORECASE,
)
_DEPLOY_PATH_RE = re.compile(r"(?<![A-Za-z0-9_.])/opt/[A-Za-z0-9._-]+")
_SSH_KEY_PATH_RE = re.compile(r"\.ssh[\\/][A-Za-z0-9_.-]+", re.IGNORECASE)


def _ipv4_is_disclosive(match, text):
    """True only for an address that could name a real remote host.

    Documentation ranges (RFC 5737), RFC 1918 private space, loopback, the
    unspecified and broadcast addresses and multicast disclose nothing, and a
    rule that fires on them is the list nobody reads. A dotted quad in a
    version context (npm, node, a pinned release) is not an address at all.
    """
    octets = match.group(1).split(".")
    try:
        values = [int(o) for o in octets]
    except ValueError:
        return False
    if any(v > 255 for v in values):
        return False
    if any(len(o) > 1 and o.startswith("0") for o in octets):
        return False  # zero-padded: a version or an identifier, not an address
    a, b = values[0], values[1]
    if a in (0, 10, 127) or a >= 224:
        return False
    if a == 172 and 16 <= b <= 31:
        return False
    if a == 192 and b == 168:
        return False
    if (a, b) == (192, 0) and values[2] == 2:
        return False
    if (a, b) == (198, 51) and values[2] == 100:
        return False
    if (a, b) == (203, 0) and values[2] == 113:
        return False
    if values == [255, 255, 255, 255]:
        return False
    before = text[max(0, match.start() - 24):match.start()]
    if _VERSION_CONTEXT_RE.search(before):
        return False
    return True


# (label, compiled pattern, guard(match, text) -> bool or None)
GENERIC_SHAPES = (
    ("ipv4", _IPV4_RE, _ipv4_is_disclosive),
    ("privileged-login", _PRIVILEGED_LOGIN_RE, None),
    ("ssh-invocation", _SSH_INVOCATION_RE, None),
    ("deploy-path", _DEPLOY_PATH_RE, None),
    ("ssh-key-path", _SSH_KEY_PATH_RE, None),
)


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------

_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿­᠎]")
_ENTITY_RE = re.compile(r"&(?:#\d{1,6}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});")
_PERCENT_RE = re.compile(r"%[0-9A-Fa-f]{2}")
_EMPHASIS_RE = re.compile(r"[*`~_]")
_SPACED_RUN_RE = re.compile(r"(?<![^\s])((?:\S ){3,}\S)(?![^\s])")
_EMPHASIS_TRIGGER_RE = re.compile(r"[*`~_]")


def _collapse_spaced_runs(text):
    return _SPACED_RUN_RE.sub(lambda m: m.group(1).replace(" ", ""), text)


def normalise_variants(text):
    """Every spelling of `text` the matcher should see, raw first.

    Each step is applied only when its trigger character is present, so an
    ordinary line costs one regex search rather than five rewrites. The result
    is deduplicated and always contains the input.
    """
    text = str(text)
    out = [text]
    current = text

    if _ZERO_WIDTH_RE.search(current):
        current = _ZERO_WIDTH_RE.sub("", current)
        out.append(current)
    if "&" in current and _ENTITY_RE.search(current):
        current = html.unescape(current)
        out.append(current)
    if "%" in current and _PERCENT_RE.search(current):
        current = unquote(current, errors="replace")
        out.append(current)
    if not current.isascii():
        folded = unicodedata.normalize("NFKC", current)
        if folded != current:
            current = folded
            out.append(current)
    folded = current.casefold()
    if folded != current:
        out.append(folded)
        current = folded
    if _EMPHASIS_TRIGGER_RE.search(current):
        stripped = _EMPHASIS_RE.sub("", current)
        if stripped != current:
            out.append(stripped)
            current = stripped
    if " " in current:
        collapsed = _collapse_spaced_runs(current)
        if collapsed != current:
            out.append(collapsed)
    return tuple(dict.fromkeys(v for v in out if v))


# ---------------------------------------------------------------------------
# the active term set
# ---------------------------------------------------------------------------

TERMS = ()
SHAPES = GENERIC_SHAPES
TERMS_SOURCE = None
_TERM_RE = None
_GROUP_NAMES = {}


def _pattern_for(term):
    body = re.escape(term.text)
    if term.kind == WORD:
        return r"\b" + body + r"\b"
    if term.kind == PREFIX:
        return r"\b" + body
    return body


def set_terms(terms, shapes=(), source=None):
    """Rebind the active term set and recompile. `shapes` are the data-file
    shapes, appended to the generic ones that ship with the module."""
    global TERMS, SHAPES, TERMS_SOURCE, _TERM_RE, _GROUP_NAMES
    # Deduplicated by (text, kind): a directory name present under both
    # Projects/ and Archives/ is one term, not two, and a duplicate entry
    # would put two named groups on the same pattern for no gain.
    seen, unique = set(), []
    for t in terms:
        key = (t.text.casefold(), t.kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    terms = unique
    TERMS = tuple(terms)
    SHAPES = tuple(GENERIC_SHAPES) + tuple(shapes)
    TERMS_SOURCE = source
    _GROUP_NAMES = {f"t{i}": t.label or t.text for i, t in enumerate(TERMS)}
    if not TERMS:
        _TERM_RE = None
        return
    _TERM_RE = re.compile(
        "|".join(f"(?P<t{i}>{_pattern_for(t)})" for i, t in enumerate(TERMS)),
        re.IGNORECASE,
    )


def _expand(entry):
    """One data-file entry to one or more Terms."""
    text, kind = entry["text"], entry["kind"]
    if kind == COMPOUND:
        base = text.replace("_", "-").replace(" ", "-")
        return [
            _term(base, SUBSTRING, base),
            _term(base.replace("-", "_"), SUBSTRING, base),
            _term(base.replace("-", " "), SUBSTRING, base),
        ]
    return [_term(text, kind)]


def term_data_path():
    """The data file this process would load, or None."""
    override = os.environ.get(TERMS_FILE_ENV)
    if override and Path(override).is_file():
        return Path(override)
    if DEFAULT_TERMS_FILE.is_file():
        return DEFAULT_TERMS_FILE
    return None


def load_term_data(path):
    """(terms, shapes) from one data file. Never raises on a malformed entry
    it can skip; a file it cannot parse at all returns empty, which every
    caller treats as "no term data on this device"."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    terms = []
    for entry in data.get("terms") or []:
        if not isinstance(entry, dict) or not entry.get("text"):
            continue
        if entry.get("kind") not in (SUBSTRING, WORD, PREFIX, COMPOUND):
            continue
        terms.extend(_expand(entry))
    shapes = []
    for entry in data.get("shapes") or []:
        if not isinstance(entry, dict) or not entry.get("pattern"):
            continue
        try:
            shapes.append((entry["name"], re.compile(entry["pattern"], re.IGNORECASE), None))
        except re.error:
            continue
    return terms, shapes


def activate(vault_root=None, terms_file=None):
    """Load the data file and the scan-time directory terms, and compile.

    Called once at import with this module's own vault. A caller scanning a
    DIFFERENT tree (the runner, scanning a target) calls it again with that
    tree's root so the directory terms come from the tree being scanned.
    """
    path = Path(terms_file) if terms_file else term_data_path()
    terms, shapes = load_term_data(path) if path else ([], [])
    source = str(path) if (path and terms) else None
    terms = list(terms) + list(dynamic_dir_terms(vault_root))
    set_terms(terms, shapes, source)
    return source


def terms_available():
    """False on a device with no term data. Every gate that scans for terms
    reports this rather than a 0-hit pass: an empty list matches nothing, and
    "0 hits" from an empty list is not evidence of anything."""
    return bool(TERMS) and TERMS_SOURCE is not None


activate()


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------

def _labels(text):
    """Every term and shape label present in `text`, across every normalised
    variant. Labels only: the matched text is never returned, because a line
    carrying a term can also carry a credential."""
    if not text:
        return set()
    found = set()
    for variant in normalise_variants(text):
        if _TERM_RE is not None:
            for match in _TERM_RE.finditer(variant):
                name = match.lastgroup
                if name in _GROUP_NAMES:
                    found.add(_GROUP_NAMES[name])
        for label, pattern, guard in SHAPES:
            key = "shape:" + label
            if key in found:
                continue
            for match in pattern.finditer(variant):
                if guard is not None and not guard(match, variant):
                    continue
                found.add(key)
                break
    return found


def term_matches(text):
    """Every term and shape label present in `text`, sorted, deduplicated."""
    return sorted(_labels(text))


def has_term(text):
    """True when any term or shape is present. The cheap form of term_matches."""
    return bool(text) and bool(_labels(text))


def scan_text(text):
    """[(line number, label)] for every hit, 1-based line numbers,
    deduplicated per (line, label) and ordered by line then label.

    Reports the LABEL, never the surrounding line: a line carrying a term can
    also carry a credential. The whole-text prefilter is an optimisation, not
    a second rule: every variant transformation is line-local, so a hit in a
    line is a hit in the document.
    """
    text = str(text or "")
    if not _labels(text):
        return []
    hits = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        for label in sorted(_labels(line)):
            hits.append((lineno, label))
    return hits


# Binary-ish suffixes skipped before the NUL sniff, so a large asset is never
# read into memory just to be discarded.
BINARY_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip", ".gz",
    ".7z", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".exe", ".dll", ".pyc",
    ".pyo", ".so", ".dylib", ".class", ".jar", ".mp4", ".mp3", ".wav", ".db",
    ".sqlite", ".bin", ".base",
})


def scan_tree(root, relpaths, max_bytes=4_000_000):
    """[{path, line, term}] for every hit in the CONTENT of every file.

    This is the half a path rule cannot do. classify_path answers "is this
    file's NAME work-bound"; a file with a generic name whose content names a
    client is exactly what a path rule is blind to by construction, and 154 of
    them were measured in the bare checkout. Binary files, unreadable files
    and files above max_bytes are skipped and counted by the caller through
    the returned paths, never silently reported as clean.
    """
    root = Path(root)
    hits = []
    for rel in sorted(str(r).replace(chr(92), "/") for r in relpaths):
        path = root / rel
        if path.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            if not path.is_file() or path.stat().st_size > max_bytes:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - a file we cannot read is skipped
                continue
        for lineno, label in scan_text(text):
            hits.append({"path": rel, "line": lineno, "term": label})
    return hits


def classify_path(path):
    """WORK_BOUND when any term appears in the path itself.

    Path-level only, never content: a generic hook mentioning a client project
    in a test fixture string is still pure mechanism, and the CONTENT question
    is scan_tree's, not this one's. The three cases the owner named (the
    tracker guard, its test, and the tracker skill directory) all carry the
    term in their own path, which is why a path rule is enough for them.
    """
    normalised = str(path).replace(chr(92), "/")
    return WORK_BOUND if has_term(normalised) else GENERIC


def work_dir_prefix(path):
    """The shortest ancestor DIRECTORY of `path` whose own name carries a
    term, or None.

    Lets a whole work-bound directory collapse to one negative sparse
    pattern instead of one per file. Returns None for a work-bound FILE
    inside a generic directory, which then needs its own pattern.
    """
    parts = str(path).replace(chr(92), "/").split("/")
    for i, segment in enumerate(parts[:-1]):
        if has_term(segment):
            return "/".join(parts[: i + 1])
    return None


def classify_permission_row(text):
    """WORK_BOUND when a permission grant names an instance, a tenant, a
    tracker, or a plugin bound to one of them.

    This is a NECESSARY condition, not a sufficient one. A permission row can
    be simultaneously term-free and a client roster (a research allowlist of
    competitor domains names nobody on any list), so blueprint_render applies
    a default-deny host rule on top of this for the WebFetch family.
    """
    return WORK_BOUND if has_term(text) else GENERIC


def _server_blob(spec):
    """The server's own declaration as one searchable string. Values are
    included because a term can hide in a host name; the string is only ever
    searched for a term and never returned or printed."""
    try:
        return json.dumps(spec, sort_keys=True)
    except (TypeError, ValueError):
        return str(spec)


_URL_SCHEME_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s\"']+")
# A bare hostname needs a plausible public or corporate suffix; a filename
# with a dot ("index.js", "mcp-memory-graph.json") and a dotted module path
# ("pkg.sub.module") must not read as a host.
_HOST_SUFFIXES = (
    "com", "net", "org", "io", "dev", "cloud", "internal", "local", "ai", "co",
    "app", "sh", "tech", "info", "biz", "us", "uk", "eu", "de", "pl", "test",
)
_BARE_HOST_RE = re.compile(
    r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+(?:"
    + "|".join(_HOST_SUFFIXES)
    + r")\b",
    re.IGNORECASE,
)
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def names_remote_host(value):
    """True when a string names a remote host: a URL with a scheme, or a bare
    dotted hostname with a plausible suffix. Local addresses are not remote
    accounts and do not count."""
    if not isinstance(value, str) or not value:
        return False
    text = value.strip()
    if any(h in text.lower() for h in _LOCAL_HOSTS):
        return False
    if _URL_SCHEME_RE.search(text):
        return True
    return bool(_BARE_HOST_RE.search(text))


def _spec_strings(spec):
    """Every string a server declaration carries in its command, args, env
    values and header values. Values are read for SHAPE only."""
    out = []
    if not isinstance(spec, dict):
        return out
    command = spec.get("command")
    if isinstance(command, str):
        out.append(command)
    args = spec.get("args")
    if isinstance(args, list):
        out.extend(a for a in args if isinstance(a, str))
    for container in (spec.get("env") or {}, spec.get("headers") or {}):
        if isinstance(container, dict):
            out.extend(str(v) for v in container.values() if isinstance(v, (str, int, float)))
    return out


def classify_mcp_server(name, spec):
    """GENERIC only for a server that carries no term, needs no secret, and
    reaches no remote account.

    Five rules, in order. A server is work-bound when:
      1. its name or its declaration carries a term or a shape (the employer's
         own servers, and the instance hosts);
      2. it declares `headers` (an MCP http server's headers block is an
         authorization header in every case seen here);
      3. it declares a top-level `url` (an http server is an account or a
         tenant on somebody's machine, and its url is per-machine);
      4. any env or header KEY matches the shared SECRET_KEY rule, which is
         the same rule the renderer uses to decide a value is secret-class;
      5. any string in its command, ARGS, env values or header values names a
         REMOTE HOST. Rule 3 tested a top-level url key only, so a stdio
         server reaching the same host through its argument vector came back
         generic (measured, adversarial F11). The hole was exactly the set of
         hosts the term list does not know, which is the set that matters when
         the owner adds a server and forgets to widen the list.

    No credential value is read: rule 4 tests the key name, rules 2 and 3 test
    presence, rule 5 tests a value's shape and never its content.
    """
    if has_term(name) or has_term(_server_blob(spec)):
        return WORK_BOUND
    if not isinstance(spec, dict):
        return WORK_BOUND
    if spec.get("headers"):
        return WORK_BOUND
    if spec.get("url"):
        return WORK_BOUND
    for container in (spec.get("env") or {}, spec.get("headers") or {}):
        for key in container:
            if SECRET_KEY.search(str(key)):
                return WORK_BOUND
    for value in _spec_strings(spec):
        if names_remote_host(value):
            return WORK_BOUND
    return GENERIC


def generic_mcp_servers(mcp_cfg):
    """The sorted names of every GENERIC server in an .mcp.json config."""
    servers = (mcp_cfg or {}).get("mcpServers") or {}
    return sorted(n for n, spec in servers.items() if classify_mcp_server(n, spec) == GENERIC)


def main(argv=None):
    """Report mode: classify the paths given on stdin or as arguments.

    Prints one line per work-bound path. Exists so the owner can see what a
    term edit would move before regenerating anything.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    paths = argv or [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    work = [p for p in paths if classify_path(p) == WORK_BOUND]
    for p in work:
        print(f"work-bound: {p} ({', '.join(term_matches(p.replace(chr(92), '/')))})")
    print(f"TERM_DATA: {TERMS_SOURCE or 'ABSENT (no term list on this device)'}")
    print(f"WORK_BOUND: {len(work)} of {len(paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
