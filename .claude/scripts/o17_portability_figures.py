"""O17 portability figures: the single re-runnable source for every live-derived
number quoted in the O17 objective section of
Projects/Agent-Governance-Research/work/2026-08-31-harness-takeover-objectives.md.

Derives, from the live settings files on disk:
  - hook registration (event, matcher, command) tuple counts per file and total
  - unique command strings per file, combined, and the cross-file overlap
  - scripts registered under more than one tuple (repeat rows)
  - permissions.allow row counts per file and total
  - the machine-path subset of permissions.allow rows, criterion pinned in
    MACHINE_TOKEN below (a drive-letter path with either separator, or the
    machine username in its
    long form WiktorPotapczyk or short form WIKTOR~1)
  - the checked-in settings.json hook-row decomposition (interpreter-path
    rows vs vault-internal wrapper rows) backing the RESIDENT-WITH-TOKENS state
  - .mcp.json server count, secret-bearing count (key NAMES only, never
    values), machine-path count, and gitignore status

Secrets discipline: this script never prints, returns, or embeds any value
from .mcp.json env or headers. It reports key names and booleans only.

Fails loudly (exit 1) on a missing input file or an empty population; a
selector that breaks must never pass vacuously. Deterministic: same input,
same output, byte for byte; no timestamps.

Usage: python .claude/scripts/o17_portability_figures.py [--json]
"""
import json
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
SETTINGS = VAULT / ".claude" / "settings.json"
SETTINGS_LOCAL = VAULT / ".claude" / "settings.local.json"
MCP = VAULT / ".mcp.json"
GITIGNORE = VAULT / ".gitignore"

# Pattern built via chr(92): a literal double backslash in this source gets
# collapsed by heredoc/escape layers and silently narrows it to slash-only.
# The lookbehind and the /(?!/) guard exclude URL schemes: in https:// the
# colon is letter-preceded and slash-doubled, so neither branch can match;
# a real drive path (C: then backslash, or C: then a single slash) still does.
MACHINE_TOKEN = re.compile(
    "(?<![A-Za-z])[A-Za-z]:(?:" + chr(92) + chr(92) + "|/(?!/))|WiktorPotapczyk|WIKTOR~1"
)
SECRET_KEY = re.compile(r"(?i)key|token|secret|authorization|password|credential")


def die(msg):
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def load(path):
    if not path.is_file():
        die(f"input file missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def hook_tuples(cfg):
    out = []
    for event, matchers in (cfg.get("hooks") or {}).items():
        for m in matchers:
            matcher = m.get("matcher", "")
            for h in m.get("hooks", []):
                out.append((event, matcher, h.get("command", "")))
    return out


def perm_allow(cfg):
    return list((cfg.get("permissions") or {}).get("allow") or [])


def walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk_strings(v)


def main():
    s = load(SETTINGS)
    sl = load(SETTINGS_LOCAL)
    mcp = load(MCP)

    t_s, t_sl = hook_tuples(s), hook_tuples(sl)
    if not t_s or not t_sl:
        die("empty hook-tuple population in a settings file")
    cmds_s = {c for _, _, c in t_s}
    cmds_sl = {c for _, _, c in t_sl}
    repeats = {}
    for _, _, c in t_sl:
        repeats[c] = repeats.get(c, 0) + 1
    multi = {c: n for c, n in repeats.items() if n > 1}

    p_s, p_sl = perm_allow(s), perm_allow(sl)
    if not p_s or not p_sl:
        die("empty permissions.allow population in a settings file")
    mp_s = [r for r in p_s if MACHINE_TOKEN.search(r)]
    mp_sl = [r for r in p_sl if MACHINE_TOKEN.search(r)]

    interp = [c for _, _, c in t_s if "Python314" in c]
    wrappers = [c for _, _, c in t_s if "Python314" not in c]

    servers = mcp.get("mcpServers") or {}
    if not servers:
        die("empty mcpServers population in .mcp.json")
    srv = {}
    for name, cfg in sorted(servers.items()):
        keys = list((cfg.get("env") or {}).keys()) + list((cfg.get("headers") or {}).keys())
        secret_keys = [k for k in keys if SECRET_KEY.search(k)]
        machine = any(MACHINE_TOKEN.search(v) for v in walk_strings(cfg))
        srv[name] = {"secret_keys": secret_keys, "machine_path": machine}
    secret_bearing = [n for n, d in srv.items() if d["secret_keys"]]
    machine_servers = [n for n, d in srv.items() if d["machine_path"]]

    gitignored = any(
        ln.strip() == ".mcp.json" for ln in GITIGNORE.read_text(encoding="utf-8").splitlines()
    ) if GITIGNORE.is_file() else False

    fig = {
        "hook_tuples": {"settings.json": len(t_s), "settings.local.json": len(t_sl),
                        "total": len(t_s) + len(t_sl)},
        "unique_commands": {"settings.json": len(cmds_s), "settings.local.json": len(cmds_sl),
                            "combined": len(cmds_s | cmds_sl), "shared": len(cmds_s & cmds_sl)},
        "local_repeat_commands": {"commands_under_multiple_tuples": len(multi),
                                  "repeat_rows": sum(n - 1 for n in multi.values())},
        "permissions_allow": {"settings.json": len(p_s), "settings.local.json": len(p_sl),
                              "total": len(p_s) + len(p_sl)},
        "machine_path_allow_rows": {"settings.json": len(mp_s), "settings.local.json": len(mp_sl),
                                    "total": len(mp_s) + len(mp_sl),
                                    "remainder_without_machine_token":
                                        len(p_s) + len(p_sl) - len(mp_s) - len(mp_sl)},
        "settings_json_hook_rows": {"interpreter_path": len(interp), "wrapper": len(wrappers)},
        "mcp_json": {"servers": len(srv), "secret_bearing": len(secret_bearing),
                     "secret_bearing_names": secret_bearing,
                     "machine_path_names": machine_servers, "gitignored": gitignored},
    }
    if "--json" in sys.argv:
        print(json.dumps(fig, indent=2, sort_keys=True))
    else:
        for k, v in fig.items():
            print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
