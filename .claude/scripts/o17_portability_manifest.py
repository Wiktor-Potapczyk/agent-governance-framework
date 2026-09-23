"""O17 portability manifest generator + checker (round-5 spec, build 2026-09-02).

Spec of record: Projects/Agent-Governance-Research/work/2026-08-31-harness-takeover-objectives.md
section '### O17'. Plan: Projects/Agent-Governance-Research/work/2026-09-02-o17-portability-plan.md.

generate: parses .claude/settings.json, .claude/settings.local.json and .mcp.json
(paths injectable for fixtures), classifies every row into PORTABLE-AS-IS /
PORTABLE-AFTER-SUBSTITUTION / MACHINE-BOUND, and emits two deterministic
markdown artifacts, each carrying a machine layer (one fenced json block) plus
human tables rendered from the same in-memory structure:
  - the portability manifest (all hook tuples keyed on (event, matcher,
    command), all permissions.allow rows, env, MCP-enablement, and the
    .mcp.json server rows as names + key names + booleans only)
  - the substitution table (every machine token found, live value where the
    source is a settings file, secret KIND + provisioning step where the
    source is .mcp.json, never a value)

check: CHECKs (a)-(d) plus the (e) parse assertion, each an importable
function returning a findings list of (code, detail) pairs. CHECK (a)
compares hook commands and permission rules after normalise_row, which
collapses the vault root in every spelling the vault uses (C:\\Users\\...
\\Vault, C:/Users/.../Vault, /c/Users/.../Vault, //c/Users/.../Vault) to
$CLAUDE_PROJECT_DIR, collapses the 8.3 short user name to the long one, and
collapses a recognised leading Python interpreter to one token. Codes:
MISSING_HOOK_TUPLE, MISSING_PERMISSION_ROW, MISSING_SECTION,
MISSING_SERVER_ROW, UNLISTED_TOKEN, UNCLASSIFIED_SETTINGS_ROW,
MCP_ROW_NOT_MACHINE_BOUND, SECRET_VALUE_IN_TRACKED_ARTIFACT, PARSE_FAILURE.

Hard constraint (spec (e)): no value from .mcp.json env or headers is ever
written to any generated artifact. CHECK (d) loads those values into memory
and scans every git-tracked artifact this objective writes, reporting hit
counts and paths only, never a matched value. Scan floor: values shorter than
SECRET_SCAN_MIN_LEN characters are generic mode flags (the true/error/stdio
class) that would false-positive on ordinary source text; no credential, URL
or path among the live values is that short (live minimum above the floor: 26).

Determinism: no wall-clock reads; the generation date is a required --date
argument echoed into the output; same inputs and date produce byte-identical
files. Fails loudly (exit 1) on a missing input or an empty population.

The machine-token criterion is IMPORTED from o17_portability_figures, never
copied: the round-4 defect was exactly a criterion drifting between copies.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import o17_portability_figures as figures

# Reused criterion-of-record objects (identity, not copies).
MACHINE_TOKEN = figures.MACHINE_TOKEN
SECRET_KEY = figures.SECRET_KEY
hook_tuples = figures.hook_tuples
perm_allow = figures.perm_allow
walk_strings = figures.walk_strings
load = figures.load
die = figures.die

VAULT = figures.VAULT
SETTINGS = figures.SETTINGS
SETTINGS_LOCAL = figures.SETTINGS_LOCAL
MCP = figures.MCP

WORK = VAULT / "Projects" / "Agent-Governance-Research" / "work"
DEFAULT_MANIFEST = WORK / "2026-09-02-o17-portability-manifest.md"
DEFAULT_SUBTABLE = WORK / "2026-09-02-o17-substitution-table.md"
BUILD_RECORD = WORK / "2026-09-02-o17-portability-build.md"
FIXDIR = Path(__file__).resolve().parent / "_test_fixtures" / "o17"

P1 = "PORTABLE-AS-IS"
P2 = "PORTABLE-AFTER-SUBSTITUTION"
MB = "MACHINE-BOUND"

SECRET_SCAN_MIN_LEN = 8

# chr(92) construction per the figures script: a literal double backslash in
# source gets collapsed by heredoc/escape layers and silently narrows patterns.
BS = chr(92)
SEP = "[" + BS + BS + "/]+"  # regex class: backslash or slash, one or more
NAME_RE = re.compile("WiktorPotapczyk|WIKTOR~1")
VAULT_RE = re.compile(
    "(?<![A-Za-z])[A-Za-z]:" + SEP + "Users" + SEP
    + "(?:WiktorPotapczyk|WIKTOR~1)" + SEP + "Desktop" + SEP + "Vault"
)
INTERP_RE = re.compile("(?<![A-Za-z])[A-Za-z]:" + SEP + "Program Files" + SEP + "Python314")
PROFILE_RE = re.compile("(?<![A-Za-z])[A-Za-z]:" + SEP + "Users" + SEP + "(?:WiktorPotapczyk|WIKTOR~1)")
DRIVE_RE = re.compile("^[A-Za-z]:")
JSON_BLOCK = re.compile("```json\n(.*?)\n```", re.DOTALL)

# The user-profile segment of a Windows path, for the DOS 8.3 short-name
# derivation below. Case-insensitive: the live spellings mix "Users" and
# "users" across the MSYS and drive-letter forms.
PROFILE_SEGMENT_RE = re.compile(r"(?i)(?<=[/\\])Users([/\\]+)([^/\\]+)")


def _short_name(name):
    """The DOS 8.3 short form Windows generates for a long profile name: the
    first six characters, upper-cased, plus '~1'. None when the name is
    already 8.3-shaped.

    Derived, not retyped: on this machine it reproduces the WIKTOR~1
    spelling NAME_RE carries, and a test asserts that equivalence so the two
    cannot drift. blueprint_render binds this by identity rather than
    keeping a second copy.
    """
    if len(name) <= 8 or "~" in name:
        return None
    return name[:6].upper() + "~1"


def _short_name_variant(base):
    """`base` with its user-profile segment replaced by that segment's 8.3
    short form, or None when there is no such segment."""
    hit = [False]

    def _sub(m):
        short = _short_name(m.group(2))
        if short is None:
            return m.group(0)
        hit[0] = True
        return "Users" + m.group(1) + short

    out = PROFILE_SEGMENT_RE.sub(_sub, base)
    return out if hit[0] else None


def compute_project_key(vault_path):
    """Claude Code's own project-directory-name rule: the absolute path with
    the drive colon, every separator and every space replaced by '-'.

    The single implementation of that rule in this repository;
    blueprint_render binds it by identity (GUD-001).
    """
    win = str(vault_path).replace("/", BS)
    return win.replace(":", "-").replace(BS, "-").replace(" ", "-")


def path_spellings(path):
    """Every on-disk spelling of one absolute path that these settings files
    actually use, longest first so a shorter spelling can never consume the
    prefix of a longer one.

    Six forms plus their 8.3 short-user-name variants: forward slash
    (C:/Users/X), single backslash (C:\\Users\\X), doubled backslash
    (the JSON-escaped form that survives inside a quoted Bash string),
    doubled forward slash (C://Users//X, produced by the same quoting path),
    and the two MSYS forms (/c/Users/X and //c/Users/X).
    """
    fwd = str(path).replace(BS, "/").rstrip("/")
    if not fwd:
        return []
    out = {fwd, fwd.replace("/", BS), fwd.replace("/", BS * 2), fwd.replace("/", "//")}
    m = re.match("^([A-Za-z]):(/.*)$", fwd)
    if m:
        drive = m.group(1).lower()
        out.add("/" + drive + m.group(2))
        out.add("//" + drive + m.group(2))
    for spelling in list(out):
        short = _short_name_variant(spelling)
        if short:
            out.add(short)
    return sorted(out, key=len, reverse=True)


def default_home():
    """This machine's user profile. USERPROFILE first: it is what Claude Code
    itself resolves '~' to on Windows, and it is what a test or a runner
    points elsewhere to measure another home."""
    return os.environ.get("USERPROFILE") or str(Path.home())

TOKEN_INFO = {
    "interpreter-path": {
        "live_value": "C:" + BS + "Program Files" + BS + "Python314" + BS + "python.exe",
        "replacement_rule": (
            "Replace with the target machine's Python 3.14+ interpreter path, quoted where it "
            "contains spaces. Inside permission rules the backslashes appear doubled."
        ),
    },
    "vault-root-prefix": {
        "live_value": "C:" + BS + "Users" + BS + "WiktorPotapczyk" + BS + "Desktop" + BS + "Vault",
        "replacement_rule": (
            "Replace with the vault checkout root on the target machine. Both separators occur "
            "(backslash and forward slash); permission rules double the backslashes. Apply this "
            "substitution before the user-profile one: the vault root contains the profile prefix."
        ),
    },
    "user-profile-prefix": {
        "live_value": "C:" + BS + "Users" + BS + "WiktorPotapczyk",
        "replacement_rule": (
            "Replace with the target user profile. Spellings seen live: "
            "C:" + BS + "Users" + BS + "WiktorPotapczyk, C:/Users/WiktorPotapczyk, "
            "/c/Users/WiktorPotapczyk, //c/Users/WiktorPotapczyk, //c/Users/WIKTOR~1, and the "
            "munged project-directory form C--Users-WiktorPotapczyk-Desktop-Vault inside "
            ".claude/projects paths (Claude Code recomputes that form on the new machine, so "
            "rows carrying only it are safe to drop rather than translate)."
        ),
    },
    "unrecognized-machine-token": {
        "live_value": "(varies)",
        "replacement_rule": (
            "A machine token outside the three named substitution tokens. The row is "
            "MACHINE-BOUND and needs per-machine judgment."
        ),
    },
}


def classify(text):
    """Return (tokens, bucket, reason) for one settings-file string.

    Gated on the imported criterion-of-record first: a string MACHINE_TOKEN
    does not match is PORTABLE-AS-IS by definition, even where a looser
    feature (a bare Python314 substring in MSYS spelling) would have flagged
    it. The bucket population must equal the ratified figures exactly.
    """
    if not MACHINE_TOKEN.search(text):
        return [], P1, None
    tokens = set()
    vault_spans = [m.span() for m in VAULT_RE.finditer(text)]
    if "Python314" in text:
        tokens.add("interpreter-path")
    if vault_spans:
        tokens.add("vault-root-prefix")
    for m in NAME_RE.finditer(text):
        if not any(a <= m.start() < b for a, b in vault_spans):
            tokens.add("user-profile-prefix")
            break
    covered = (
        vault_spans
        + [m.span() for m in INTERP_RE.finditer(text)]
        + [m.span() for m in PROFILE_RE.finditer(text)]
    )
    for m in MACHINE_TOKEN.finditer(text):
        if DRIVE_RE.match(m.group()) and not any(a <= m.start() < b for a, b in covered):
            tokens.add("unrecognized-machine-token")
            break
    if "unrecognized-machine-token" in tokens:
        return sorted(tokens), MB, (
            "carries a machine token outside the three named substitution tokens; "
            "needs per-machine judgment"
        )
    if tokens:
        return sorted(tokens), P2, None
    return [], P1, None


def secret_kind(key_name):
    k = key_name.lower()
    if k == "authorization":
        return "bearer token"
    if "token" in k:
        return "API token"
    if "key" in k:
        return "API key"
    if "password" in k:
        return "password"
    if "secret" in k:
        return "secret"
    return "credential"


def build(settings_path, local_path, mcp_path, date, home=None, vault=None):
    """Parse the input trio and build the full classified row structure.

    `home` and `vault` name the machine this manifest describes; they are
    recorded in the block so the checker can map the manifest side's home
    and project key onto the same tokens as another machine's. Without
    them, every permission row carrying a bare home path (21 live, plus 5
    carrying the project key) is reported as missing on any machine whose
    user profile differs, which is every target machine by definition.
    """
    home = str(home) if home else default_home()
    vault = str(vault) if vault else str(VAULT)
    s = load(Path(settings_path))
    sl = load(Path(local_path))
    mcp = load(Path(mcp_path))

    t_s, t_sl = hook_tuples(s), hook_tuples(sl)
    if not t_s or not t_sl:
        die("empty hook-tuple population in a settings file")
    p_s, p_sl = perm_allow(s), perm_allow(sl)
    if not p_s or not p_sl:
        die("empty permissions.allow population in a settings file")
    servers = mcp.get("mcpServers") or {}
    if not servers:
        die("empty mcpServers population in .mcp.json")

    hooks = []
    for fname, tuples in (("settings.json", t_s), ("settings.local.json", t_sl)):
        for event, matcher, command in tuples:
            tokens, bucket, reason = classify(command)
            hooks.append({
                "file": fname, "event": event, "matcher": matcher, "command": command,
                "bucket": bucket, "tokens": tokens, "reason": reason,
            })

    permissions = []
    for fname, rules in (("settings.json", p_s), ("settings.local.json", p_sl)):
        for rule in rules:
            tokens, bucket, reason = classify(rule)
            permissions.append({
                "file": fname, "rule": rule,
                "bucket": bucket, "tokens": tokens, "reason": reason,
            })

    env_rows = []
    for key, value in (sl.get("env") or {}).items():
        tokens, bucket, reason = classify(f"{key}={value}")
        env_rows.append({
            "file": "settings.local.json", "key": key, "value": str(value),
            "bucket": bucket, "tokens": tokens, "reason": reason,
        })

    enablement = []
    for name in (sl.get("enabledMcpjsonServers") or []):
        tokens, bucket, reason = classify(name)
        enablement.append({
            "file": "settings.local.json", "server": name,
            "bucket": bucket, "tokens": tokens, "reason": reason,
        })

    mcp_rows = []
    for name, cfg in sorted(servers.items()):
        keys = list((cfg.get("env") or {}).keys()) + list((cfg.get("headers") or {}).keys())
        mcp_rows.append({
            "name": name,
            "secret_key_names": sorted(k for k in keys if SECRET_KEY.search(k)),
            "machine_path": any(MACHINE_TOKEN.search(v) for v in walk_strings(cfg)),
            "bucket": MB,
            "reason": "secrets: every .mcp.json row is MACHINE-BOUND by construction (spec (e))",
        })

    resident = [
        {
            "event": r["event"], "matcher": r["matcher"], "command": r["command"],
            "tokens": r["tokens"],
            "kind": "interpreter-path" if "Python314" in r["command"] else "wrapper",
        }
        for r in hooks if r["file"] == "settings.json" and r["bucket"] == P2
    ]
    move_count = sum(
        1 for r in hooks if r["file"] == "settings.local.json" and r["bucket"] == P1
    )

    settings_rows = [r for sec in (hooks, permissions) for r in sec]
    bucket_counts = {P1: 0, P2: 0, MB: 0}
    for r in hooks + permissions + env_rows + enablement + mcp_rows:
        bucket_counts[r["bucket"]] += 1

    tokens_found = sorted({t for r in settings_rows + env_rows + enablement for t in r["tokens"]})

    return {
        "generated": date,
        "machine": {
            "home": str(home).replace(BS, "/").rstrip("/"),
            "vault": str(vault).replace(BS, "/").rstrip("/"),
            "project_key": compute_project_key(vault),
            "note": (
                "The machine this manifest was generated on. CHECK (a) maps these "
                "three onto the same tokens as the checked machine's, so a row "
                "naming a home path or the Claude Code project-directory name "
                "compares equal across machines. Paths only, never a credential."
            ),
        },
        "criterion": (
            "MACHINE_TOKEN imported from .claude/scripts/o17_portability_figures.py "
            "(identity-asserted by the test suite, never copied)"
        ),
        "secret_scan_min_len": SECRET_SCAN_MIN_LEN,
        "sections": {
            "hooks": hooks,
            "permissions": permissions,
            "env": env_rows,
            "mcp_enablement": enablement,
            "mcp_servers": mcp_rows,
        },
        "counts": {
            "hooks": {
                "settings.json": len(t_s), "settings.local.json": len(t_sl),
                "total": len(t_s) + len(t_sl),
            },
            "permissions": {
                "settings.json": len(p_s), "settings.local.json": len(p_sl),
                "total": len(p_s) + len(p_sl),
            },
            "env": len(env_rows),
            "mcp_enablement": len(enablement),
            "mcp_servers": len(mcp_rows),
            "buckets": bucket_counts,
        },
        "portable_as_is_move_count": move_count,
        "portable_as_is_move_population": (
            "settings.local.json hook registrations classified PORTABLE-AS-IS"
        ),
        "resident_with_tokens": resident,
        "tokens_found": tokens_found,
    }


def _cell(text):
    """Render one markdown table cell: pipe-escaped, code-spanned."""
    text = str(text).replace("|", BS + "|")
    if "`" in text:
        return text
    return "`" + text + "`" if text else ""


def _frontmatter(date, extra_tag):
    return (
        "---\n"
        f"date: '{date}'\n"
        f"tags: [project/agent-governance-research, {extra_tag}, vault]\n"
        "status: active\n"
        "---\n"
    )


def render_manifest(data):
    sec = data["sections"]
    c = data["counts"]
    lines = [
        _frontmatter(data["generated"], "spec"),
        "",
        "# O17 Portability Manifest",
        "",
        f"Generated {data['generated']} by `.claude/scripts/o17_portability_manifest.py generate`. "
        "Deterministic: the same inputs and date produce this file byte for byte.",
        "",
        "Scope statement (spec risk flag 1): this manifest never promises a clone runs untouched. "
        "It promises the migration delta is enumerated and checked. Every row below carries a "
        "bucket. Every machine token has a substitution rule in "
        "[[2026-09-02-o17-substitution-table]]. The checker re-derives the row set from the live "
        "files on every run.",
        "",
        "Hard constraint (spec (e)): nothing from `.mcp.json` is ever moved or copied into a "
        "git-tracked file. The `.mcp.json` rows below carry server names, secret key NAMES and "
        "booleans only, never a value. CHECK (d) enforces this by scanning every artifact this "
        "objective writes for live `.mcp.json` env and header values.",
        "",
        "## Buckets",
        "",
        "- **PORTABLE-AS-IS**: no machine token; the row works unchanged on another machine.",
        "- **PORTABLE-AFTER-SUBSTITUTION** (bucket 2): correct once a named machine token is "
        "replaced (interpreter path, vault-root prefix, user-profile prefix).",
        "- **MACHINE-BOUND**: needs per-machine judgment (unrecognized machine tokens; and, by "
        "construction, every `.mcp.json` row, reason: secrets).",
        "- **RESIDENT-WITH-TOKENS** (state, not a fourth bucket): a bucket-2 row already checked "
        "into settings.json. It has nowhere else to move to and is not a failure. It stays "
        "pending the separate owner-gated interpreter-indirection follow-up.",
        "",
        "## Machine row set (checker input)",
        "",
        "The checker parses this block, never the generator's memory. A manifest that silently "
        "drops a section or a row fails the set comparison.",
        "",
        "```json",
        json.dumps(data, indent=2, sort_keys=True),
        "```",
        "",
        f"## Hook registrations ({c['hooks']['total']} rows: "
        f"{c['hooks']['settings.json']} settings.json + "
        f"{c['hooks']['settings.local.json']} settings.local.json)",
        "",
        "Keyed on the (event, matcher, command) tuple, never the command string: duplicate "
        "commands under different pairs are real, separately classified rows.",
        "",
        "| File | Event | Matcher | Command | Bucket | Tokens |",
        "|---|---|---|---|---|---|",
    ]
    for r in sec["hooks"]:
        lines.append(
            f"| {r['file']} | {r['event']} | {_cell(r['matcher'])} | {_cell(r['command'])} "
            f"| {r['bucket']} | {', '.join(r['tokens'])} |"
        )
    lines += [
        "",
        f"## permissions.allow ({c['permissions']['total']} rows: "
        f"{c['permissions']['settings.json']} settings.json + "
        f"{c['permissions']['settings.local.json']} settings.local.json)",
        "",
        "| File | Rule | Bucket | Tokens |",
        "|---|---|---|---|",
    ]
    for r in sec["permissions"]:
        lines.append(
            f"| {r['file']} | {_cell(r['rule'])} | {r['bucket']} | {', '.join(r['tokens'])} |"
        )
    lines += [
        "",
        f"## env section ({c['env']} row(s), settings.local.json)",
        "",
        "| Key | Value | Bucket | Tokens |",
        "|---|---|---|---|",
    ]
    for r in sec["env"]:
        lines.append(f"| {_cell(r['key'])} | {_cell(r['value'])} | {r['bucket']} | {', '.join(r['tokens'])} |")
    lines += [
        "",
        f"## MCP enablement section ({c['mcp_enablement']} entries, settings.local.json)",
        "",
        "Server names only; each entry is functional on a new machine only after its "
        "MACHINE-BOUND `.mcp.json` server entry is provisioned per the substitution table.",
        "",
        "| Server | Bucket |",
        "|---|---|",
    ]
    for r in sec["mcp_enablement"]:
        lines.append(f"| {_cell(r['server'])} | {r['bucket']} |")
    lines += [
        "",
        f"## .mcp.json server rows ({c['mcp_servers']} rows; names, key names and booleans only)",
        "",
        "| Server | Secret key names | Machine path | Bucket | Reason |",
        "|---|---|---|---|---|",
    ]
    for r in sec["mcp_servers"]:
        keys = ", ".join(r["secret_key_names"]) or "(none)"
        lines.append(
            f"| {_cell(r['name'])} | {keys} | {'yes' if r['machine_path'] else 'no'} "
            f"| {r['bucket']} | secrets by construction |"
        )
    resident = data["resident_with_tokens"]
    n_interp = sum(1 for r in resident if r["kind"] == "interpreter-path")
    n_wrap = len(resident) - n_interp
    lines += [
        "",
        f"## RESIDENT-WITH-TOKENS ({len(resident)} settings.json hook rows: "
        f"{n_interp} interpreter-path + {n_wrap} wrapper)",
        "",
        "Bucket-2 rows physically resident in the checked-in settings.json. Not moved, not a "
        "failure; pending the separate interpreter-indirection follow-up.",
        "",
        "| Event | Matcher | Command | Kind | Tokens |",
        "|---|---|---|---|---|",
    ]
    for r in resident:
        lines.append(
            f"| {r['event']} | {_cell(r['matcher'])} | {_cell(r['command'])} | {r['kind']} "
            f"| {', '.join(r['tokens'])} |"
        )
    perm_resident = [
        r for r in sec["permissions"] if r["file"] == "settings.json" and r["bucket"] == P2
    ]
    lines += [
        "",
        f"Note: {len(perm_resident)} settings.json permissions.allow row(s) also carry tokens "
        "and resolve to the same RESIDENT-WITH-TOKENS state under CHECK (c). The named list "
        "above covers the hook rows, per the spec's 9-row enumeration.",
        "",
        "## Portable-as-is move count (deliverable (c))",
        "",
        f"Recorded count: **{data['portable_as_is_move_count']}**.",
        "",
        f"Move population: {data['portable_as_is_move_population']}. The deliverable-(c) move "
        "mechanism was defined over hook registrations (the round-2 revision found its source "
        "set empty because all 72 local registrations embed the interpreter path). Permission "
        "rows, the env key and the MCP-enablement list are classified above but are not move "
        "candidates: a personal allowlist's home is the local file, and the spec's own "
        "near-zero expectation is only satisfiable on the hook-row population.",
        "",
        "## O10 freshness hookup (deliverable (d))",
        "",
        "O10's governing-artifact settings-split entry watches manifest freshness, not raw "
        "registration counts. Watch criterion: this file's generation date plus a clean "
        "checker run (`o17_portability_manifest.py check` exit 0). A settings change without "
        "regeneration, or any checker finding, marks the entry stale. No O10 board file exists "
        "at generation time; wiring waits for O10's own board landing (see the build record).",
        "",
        "## Substitution table",
        "",
        "Sibling artifact: [[2026-09-02-o17-substitution-table]].",
        "",
    ]
    return "\n".join(lines)


def render_subtable(data):
    sub = {
        "generated": data["generated"],
        "tokens": {t: TOKEN_INFO[t] for t in data["tokens_found"]},
        "machine_bound_provisioning": [],
    }
    for r in data["sections"]["mcp_servers"]:
        if r["secret_key_names"]:
            prov = (
                "Issue fresh credentials for this server on the target machine and write them "
                "into the local, gitignored .mcp.json entry. Values are never copied from this "
                "machine."
            )
        elif r["machine_path"]:
            prov = (
                "No secret. Recreate the server entry in the local, gitignored .mcp.json, "
                "adjusting its machine-specific paths (values not reproduced here per the O17 "
                "hard constraint)."
            )
        else:
            prov = "No secret. Recreate the server entry in the local, gitignored .mcp.json."
        sub["machine_bound_provisioning"].append({
            "name": r["name"],
            "secret_key_names": r["secret_key_names"],
            "secret_kinds": [secret_kind(k) for k in r["secret_key_names"]],
            "machine_path": r["machine_path"],
            "provisioning": prov,
        })

    lines = [
        _frontmatter(data["generated"], "spec"),
        "",
        "# O17 Substitution Table",
        "",
        f"Generated {data['generated']} by `.claude/scripts/o17_portability_manifest.py "
        "generate`, beside [[2026-09-02-o17-portability-manifest]]. Every machine token found "
        "in the settings files appears below with its live value and replacement rule. "
        "`.mcp.json` entries carry secret KIND and provisioning step only, never a value "
        "(spec hard constraint (e)).",
        "",
        "```json",
        json.dumps(sub, indent=2, sort_keys=True),
        "```",
        "",
        "## Machine tokens (settings files)",
        "",
        "Apply the vault-root substitution before the user-profile one: the vault root "
        "contains the profile prefix.",
        "",
        "| Token | Live value | Replacement rule |",
        "|---|---|---|",
    ]
    for t in data["tokens_found"]:
        info = TOKEN_INFO[t]
        lines.append(f"| {t} | {_cell(info['live_value'])} | {info['replacement_rule']} |")
    lines += [
        "",
        "## MACHINE-BOUND provisioning checklist (.mcp.json servers)",
        "",
        "| Server | Secret key names | Secret kind | Machine paths | Provisioning step |",
        "|---|---|---|---|---|",
    ]
    for r in sub["machine_bound_provisioning"]:
        keys = ", ".join(r["secret_key_names"]) or "(none)"
        kinds = ", ".join(r["secret_kinds"]) or "(none)"
        lines.append(
            f"| {_cell(r['name'])} | {keys} | {kinds} | {'yes' if r['machine_path'] else 'no'} "
            f"| {r['provisioning']} |"
        )
    lines.append("")
    return "\n".join(lines)


def generate(settings_path, local_path, mcp_path, date, out_manifest, out_subtable,
             home=None, vault=None):
    data = build(settings_path, local_path, mcp_path, date, home=home, vault=vault)
    Path(out_manifest).write_text(render_manifest(data), encoding="utf-8", newline="\n")
    Path(out_subtable).write_text(render_subtable(data), encoding="utf-8", newline="\n")
    return data


# --- checker ---

def _read_block(path):
    p = Path(path)
    if not p.is_file():
        return None, [("PARSE_FAILURE", f"artifact missing: {p}")]
    m = JSON_BLOCK.search(p.read_text(encoding="utf-8"))
    if not m:
        return None, [("PARSE_FAILURE", f"no json block in {p}")]
    try:
        return json.loads(m.group(1)), []
    except ValueError as exc:
        return None, [("PARSE_FAILURE", f"json block unparseable in {p}: {exc}")]


# --- spelling normalisation for CHECK (a) ---
#
# The same hook row is spelled two ways on this machine. The live
# .claude/settings.local.json carries
#   "C:\Program Files\Python314\python.exe" "C:\Users\...\Vault\.claude\hooks\x.py"
# and A3's portable wiring carries
#   bash "$CLAUDE_PROJECT_DIR/.claude/bin/py" "$CLAUDE_PROJECT_DIR/.claude/hooks/x.py"
# Both invoke the same hook. Comparing them as raw strings produced 144
# MISSING_HOOK_TUPLE findings, 72 each way, purely from spelling, which is
# the drift detector reporting its own conversion as drift.
#
# Normalisation is deliberately narrow, so that a real change still shows:
#   - the vault root, in every spelling the vault uses, collapses to
#     $CLAUDE_PROJECT_DIR;
#   - the 8.3 short user name collapses to the long one (NAME_RE already
#     treats them as one name);
#   - path separators inside the row become forward slashes;
#   - a LEADING interpreter invocation collapses to <PY>, but only when it
#     is recognisably a Python interpreter or the vault's own .claude/bin/py
#     resolver. Anything else is left verbatim, so swapping in a different
#     interpreter is still reported.
# What this loses: a change of interpreter spelling between two recognised
# forms no longer shows in CHECK (a). That token is classified in its own
# right by check_c and carried in the substitution table, which is where
# O17 records it.
MSYS_VAULT_RE = re.compile(
    "//?[A-Za-z]/Users/(?:WiktorPotapczyk|WIKTOR~1)/Desktop/Vault", re.IGNORECASE
)
PROJECT_DIR_TOKEN = "$CLAUDE_PROJECT_DIR"
_BRACED_PROJECT_DIR_RE = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}")
_PY_PREFIX_RES = (
    # bash "<root>/.claude/bin/py"  (the portable resolver, root already
    # normalised to the token by the time this runs)
    re.compile(r'^bash\s+"?\$CLAUDE_PROJECT_DIR/\.claude/bin/py"?\s+'),
    # "<any path>/python.exe" or python3/python, quoted or bare
    re.compile(r'^"[^"]*[/\\]python(?:3(?:\.\d+)?)?\.exe"\s+', re.IGNORECASE),
    re.compile(r"^python(?:3(?:\.\d+)?)?(?:\.exe)?\s+", re.IGNORECASE),
)
PY_TOKEN = "<PY>"
USERHOME_TOKEN = "<USERHOME>"
PROJECT_KEY_TOKEN = "<PROJECT_KEY>"


def normalise_row(text, home=None, project_key=None, vault=None):
    """Collapse the machine spellings of one hook command or permission rule
    so that the same row parses equal from the live wiring and from the
    $CLAUDE_PROJECT_DIR form, on any machine.

    Substitution order is longest-context first, because these paths nest:
    on the source machine the vault root sits inside the home, and the
    project key is a mangling of the vault path. Vault root, then project
    key, then home.

    Each of the three is replaced ONLY as a whole absolute path, in the six
    spellings path_spellings enumerates plus their 8.3 short-name variants.
    A row naming any other directory is untouched, so a rule that really
    does point somewhere else still differs. Returns the row unchanged when
    it carries none of the three and no recognised interpreter.
    """
    if not isinstance(text, str):
        return text
    out = _BRACED_PROJECT_DIR_RE.sub(PROJECT_DIR_TOKEN, text)

    if vault:
        for spelling in path_spellings(vault):
            out = out.replace(spelling, PROJECT_DIR_TOKEN)
    # This machine's own literal vault spellings, for a row recorded before
    # any checkout was named on the command line.
    out = VAULT_RE.sub(PROJECT_DIR_TOKEN, out)
    out = MSYS_VAULT_RE.sub(PROJECT_DIR_TOKEN, out)

    if project_key:
        out = out.replace(project_key, PROJECT_KEY_TOKEN)

    if home:
        for spelling in path_spellings(home):
            out = out.replace(spelling, USERHOME_TOKEN)

    out = NAME_RE.sub("WiktorPotapczyk", out)
    out = out.replace(BS, "/")
    for pattern in _PY_PREFIX_RES:
        new = pattern.sub(PY_TOKEN + " ", out, count=1)
        if new != out:
            return new
    return out


def _normalise_hook_tuple(row, ctx=None):
    src, event, matcher, command = row
    return (src, event, matcher, normalise_row(command, **(ctx or {})))


def _normalise_perm_row(row, ctx=None):
    src, rule = row
    return (src, normalise_row(rule, **(ctx or {})))


def _machine_ctx(block):
    """The normalisation context recorded in a manifest block, or an empty
    context for a manifest generated before the machine section existed."""
    machine = (block or {}).get("machine") or {}
    return {
        "home": machine.get("home"),
        "project_key": machine.get("project_key"),
        "vault": machine.get("vault"),
    }


def live_vault_for(local_path):
    """The checkout a live settings.local.json belongs to: its grandparent,
    but only when the file really sits in a `.claude/` directory.

    `check --local .claude/blueprint/settings.local.portable.json` must NOT
    resolve to `.claude`; that file describes this machine's own checkout,
    whose literal spellings VAULT_RE already handles.
    """
    p = Path(local_path).resolve()
    if p.parent.name == ".claude":
        return str(p.parent.parent)
    return str(VAULT)


def _multiset_diff(live, manifest, code, label):
    findings = []
    from collections import Counter
    lc, mc = Counter(live), Counter(manifest)
    for row, n in sorted((lc - mc).items()):
        findings.append((code, f"manifest missing live {label} row ({n}x): {row}"))
    for row, n in sorted((mc - lc).items()):
        findings.append((code, f"manifest carries {label} row absent from live parse ({n}x): {row}"))
    return findings


def check_a(manifest_path, settings_path, local_path, mcp_path,
            home=None, project_key=None, vault=None):
    """Manifest row set equals a live parse of the input trio, per section.

    Hook commands and permission rules are compared after normalise_row, so
    a row spelled with the absolute vault root and a row spelled with
    $CLAUDE_PROJECT_DIR are the same row. Without that, regenerating the
    manifest from either spelling makes the checker red against the other,
    and the manifest of record can only ever describe one of the two files
    the vault actually has.

    The two sides get DIFFERENT normalisation contexts. The manifest side
    uses the home, vault and project key recorded in its own block; the live
    side uses `home` (default: this machine's USERPROFILE), `vault` (default:
    the checkout the live settings file sits in) and `project_key` (default:
    derived from that vault). A permission rule naming the user profile, or
    the Claude Code project-directory name, therefore compares equal across
    two machines that spell them differently, while a rule naming any other
    directory still differs.
    """
    block, findings = _read_block(manifest_path)
    if block is None:
        return findings
    sections = block.get("sections") or {}
    s = load(Path(settings_path))
    sl = load(Path(local_path))
    mcp = load(Path(mcp_path))

    man_ctx = _machine_ctx(block)
    live_vault = str(vault) if vault else live_vault_for(local_path)
    local_ctx = {
        "home": str(home) if home else default_home(),
        "project_key": project_key or compute_project_key(live_vault),
        "vault": live_vault,
    }
    # .claude/settings.json is TRACKED: a clone carries the generating
    # machine's own file, so its rows name the generating machine's home no
    # matter where they are checked out, and they normalise against the
    # manifest's recorded machine on both sides. .claude/settings.local.json
    # is placed per machine, so its live rows name the checked machine.
    # Applying the checked machine's home to the tracked file reported 2
    # identical rows as different; applying the recorded home to the placed
    # file would hide a failed substitution, so the split is per file, not a
    # union of the two contexts.
    live_ctx = {"settings.json": man_ctx, "settings.local.json": local_ctx}

    live_hooks = [
        _normalise_hook_tuple(("settings.json", e, m, c), live_ctx["settings.json"])
        for e, m, c in hook_tuples(s)
    ] + [
        _normalise_hook_tuple(("settings.local.json", e, m, c), live_ctx["settings.local.json"])
        for e, m, c in hook_tuples(sl)
    ]
    man_hooks = [
        _normalise_hook_tuple((r["file"], r["event"], r["matcher"], r["command"]), man_ctx)
        for r in sections.get("hooks") or []
    ]
    findings += _multiset_diff(live_hooks, man_hooks, "MISSING_HOOK_TUPLE", "hook-tuple")

    live_perms = [
        _normalise_perm_row(("settings.json", r), live_ctx["settings.json"])
        for r in perm_allow(s)
    ] + [
        _normalise_perm_row(("settings.local.json", r), live_ctx["settings.local.json"])
        for r in perm_allow(sl)
    ]
    man_perms = [
        _normalise_perm_row((r["file"], r["rule"]), man_ctx)
        for r in sections.get("permissions") or []
    ]
    findings += _multiset_diff(live_perms, man_perms, "MISSING_PERMISSION_ROW", "permission")

    if "env" not in sections:
        findings.append(("MISSING_SECTION", "env: section absent from manifest"))
    else:
        live_env = sorted((k, str(v)) for k, v in (sl.get("env") or {}).items())
        man_env = sorted((r["key"], r["value"]) for r in sections["env"])
        if live_env != man_env:
            findings.append(("MISSING_SECTION", "env: row set differs from live parse"))

    if "mcp_enablement" not in sections:
        findings.append(("MISSING_SECTION", "mcp-enablement: section absent from manifest"))
    else:
        live_en = sorted(sl.get("enabledMcpjsonServers") or [])
        man_en = sorted(r["server"] for r in sections["mcp_enablement"])
        if live_en != man_en:
            findings.append(("MISSING_SECTION", "mcp-enablement: row set differs from live parse"))

    if "mcp_servers" not in sections:
        findings.append(("MISSING_SECTION", "mcp-servers: section absent from manifest"))
    else:
        live_srv = sorted((mcp.get("mcpServers") or {}).keys())
        man_srv = sorted(r["name"] for r in sections["mcp_servers"])
        for name in live_srv:
            if name not in man_srv:
                findings.append(("MISSING_SERVER_ROW", f"manifest missing server row: {name}"))
        for name in man_srv:
            if name not in live_srv:
                findings.append(("MISSING_SERVER_ROW", f"manifest carries unknown server row: {name}"))
    return findings


def check_b(manifest_path, subtable_path):
    """Every bucket-2 row's machine tokens all appear in the substitution table."""
    block, findings = _read_block(manifest_path)
    sub, f2 = _read_block(subtable_path)
    findings += f2
    if block is None or sub is None:
        return findings
    table_tokens = set((sub.get("tokens") or {}).keys())
    sections = block.get("sections") or {}
    for name in ("hooks", "permissions", "env", "mcp_enablement"):
        for r in sections.get(name) or []:
            if r.get("bucket") != P2:
                continue
            for t in r.get("tokens") or []:
                if t not in table_tokens:
                    ident = r.get("command") or r.get("rule") or r.get("key") or r.get("server")
                    findings.append((
                        "UNLISTED_TOKEN",
                        f"bucket-2 {name} row carries token '{t}' absent from the "
                        f"substitution table: {ident}",
                    ))
    return findings


def check_c(manifest_path, settings_path):
    """Every checked-in settings.json row resolves to exactly one named state.

    Returns (findings, state_counts).
    """
    states = {P1: 0, "RESIDENT-WITH-TOKENS": 0, MB: 0}
    block, findings = _read_block(manifest_path)
    if block is None:
        return findings, states
    sections = block.get("sections") or {}
    man = {}
    for r in sections.get("hooks") or []:
        if r["file"] == "settings.json":
            man[("hook", r["event"], r["matcher"], r["command"])] = r
    for r in sections.get("permissions") or []:
        if r["file"] == "settings.json":
            man[("permission", r["rule"])] = r

    s = load(Path(settings_path))
    live = [("hook", e, m, c) for e, m, c in hook_tuples(s)] + [
        ("permission", r) for r in perm_allow(s)
    ]
    for key in live:
        row = man.get(key)
        if row is None:
            findings.append((
                "UNCLASSIFIED_SETTINGS_ROW",
                f"live settings.json row has no manifest entry naming it: {key}",
            ))
            continue
        bucket, reason = row.get("bucket"), row.get("reason")
        if bucket == P1:
            states[P1] += 1
        elif bucket == P2:
            states["RESIDENT-WITH-TOKENS"] += 1
        elif bucket == MB and reason:
            states[MB] += 1
        else:
            findings.append((
                "UNCLASSIFIED_SETTINGS_ROW",
                f"settings.json row resolves to no named state (bucket={bucket!r}, "
                f"reason={reason!r}): {key}",
            ))
    return findings, states


def check_d(manifest_path, mcp_path, artifact_paths):
    """No .mcp.json row classified anything but MACHINE-BOUND; no .mcp.json
    env/header value in any tracked artifact this objective writes.

    Reports hit counts and paths only, never a matched value.
    """
    block, findings = _read_block(manifest_path)
    if block is not None:
        for r in (block.get("sections") or {}).get("mcp_servers") or []:
            if r.get("bucket") != MB:
                findings.append((
                    "MCP_ROW_NOT_MACHINE_BOUND",
                    f".mcp.json row '{r.get('name')}' classified {r.get('bucket')!r}",
                ))

    mcp = load(Path(mcp_path))
    values = []
    for name, cfg in sorted((mcp.get("mcpServers") or {}).items()):
        for key, value in {**(cfg.get("env") or {}), **(cfg.get("headers") or {})}.items():
            v = str(value)
            if len(v) >= SECRET_SCAN_MIN_LEN:
                values.append((name, key, v))
    for p in artifact_paths:
        p = Path(p)
        if not p.is_file():
            findings.append(("PARSE_FAILURE", f"artifact missing: {p}"))
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for name, key, v in values:
            n = text.count(v)
            if n:
                findings.append((
                    "SECRET_VALUE_IN_TRACKED_ARTIFACT",
                    f"{p}: {n} occurrence(s) of the .mcp.json value of {name}.{key} "
                    "(value not shown)",
                ))
    return findings


def check_e(settings_path, local_path):
    """Both settings files parse."""
    findings = []
    for p in (Path(settings_path), Path(local_path)):
        try:
            json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            findings.append(("PARSE_FAILURE", f"{p}: {exc}"))
    return findings


def default_artifacts():
    fixture_files = sorted(FIXDIR.glob("*")) if FIXDIR.is_dir() else []
    return [
        SETTINGS, DEFAULT_MANIFEST, DEFAULT_SUBTABLE, BUILD_RECORD,
        Path(__file__).resolve(),
        Path(__file__).resolve().parent / "test_o17_portability_manifest.py",
    ] + fixture_files


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate")
    g.add_argument("--date", required=True)
    g.add_argument("--settings", default=str(SETTINGS))
    g.add_argument("--local", default=str(SETTINGS_LOCAL))
    g.add_argument("--mcp", default=str(MCP))
    g.add_argument("--out-manifest", default=str(DEFAULT_MANIFEST))
    g.add_argument("--out-subtable", default=str(DEFAULT_SUBTABLE))

    c = sub.add_parser("check")
    c.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    c.add_argument("--subtable", default=str(DEFAULT_SUBTABLE))
    c.add_argument("--settings", default=str(SETTINGS))
    c.add_argument("--local", default=str(SETTINGS_LOCAL))
    c.add_argument("--mcp", default=str(MCP))
    c.add_argument("--artifacts", nargs="*", default=None,
                   help="tracked artifacts for the CHECK (d) secret scan; "
                        "defaults to every artifact this objective writes")
    c.add_argument("--home", default=None,
                   help="the user profile the CHECKED machine uses; defaults to "
                        "USERPROFILE. A permission rule naming this directory "
                        "compares equal to the manifest's own recorded home")
    c.add_argument("--vault", default=None,
                   help="the checkout the CHECKED settings file belongs to; "
                        "defaults to the parent of its .claude/ directory")
    c.add_argument("--project-key", default=None,
                   help="Claude Code's project-directory name on the CHECKED "
                        "machine; defaults to the one derived from --vault")

    args = ap.parse_args()
    if args.cmd == "generate":
        data = generate(args.settings, args.local, args.mcp, args.date,
                        args.out_manifest, args.out_subtable)
        print(f"manifest: {args.out_manifest}")
        print(f"subtable: {args.out_subtable}")
        print(json.dumps(data["counts"], indent=2, sort_keys=True))
        print(f"portable_as_is_move_count: {data['portable_as_is_move_count']}")
        print(f"resident_with_tokens: {len(data['resident_with_tokens'])}")
        return 0

    artifacts = args.artifacts if args.artifacts is not None else default_artifacts()
    findings = []
    findings += [("CHECK-A " + c_, d) for c_, d in
                 check_a(args.manifest, args.settings, args.local, args.mcp,
                         home=args.home, project_key=args.project_key, vault=args.vault)]
    findings += [("CHECK-B " + c_, d) for c_, d in check_b(args.manifest, args.subtable)]
    c_findings, states = check_c(args.manifest, args.settings)
    findings += [("CHECK-C " + c_, d) for c_, d in c_findings]
    findings += [("CHECK-D " + c_, d) for c_, d in
                 check_d(args.manifest, args.mcp, artifacts)]
    findings += [("CHECK-E " + c_, d) for c_, d in check_e(args.settings, args.local)]
    print(f"check_c settings.json state counts: {json.dumps(states, sort_keys=True)}")
    print(f"check_d artifacts scanned: {len(artifacts)}")
    if findings:
        for code, detail in findings:
            print(f"{code}: {detail}")
        print(f"FINDINGS: {len(findings)}")
        return 1
    print("FINDINGS: 0 (all checks pass)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
