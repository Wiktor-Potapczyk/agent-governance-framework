"""Enumerate every hook registered in settings, with its event and interpreter.

This is the denominator for the control-fires suite. Two properties matter more
than the enumeration itself, and both were added after an architect review found
each one missing:

1. IT MUST NOT SILENTLY UNDERCOUNT. The first version matched only `\\.py` and
   silently dropped three registered hooks whose commands are shell or
   PowerShell scripts, one of them a Stop hook. A hook invisible to the
   denominator can never fail the coverage gate, which is precisely the
   "registered and unverified" shape the whole suite exists to catch.

2. IT MUST FAIL LOUDLY RATHER THAN RETURN ZERO. If a settings file loses its
   hooks key, an enumerator that returns an empty list makes the coverage gate
   pass trivially: no controls, therefore no uncovered controls. That is the
   same bug one level up. This script exits non-zero on an empty result, and
   the suite checks the exit code.

Run: "C:\\Program Files\\Python314\\python.exe" .claude/scripts/enumerate_controls.py
"""

import collections
import io
import json
import os
import re
import sys

VAULT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SETTINGS = [os.path.join(VAULT, ".claude", "settings.json"),
            os.path.join(VAULT, ".claude", "settings.local.json")]
OUT = os.path.join(VAULT, ".claude", "hooks", "aggregates", "registered-controls.json")

# Every script extension a hook command can name. Adding one here is the only
# supported way to widen the denominator; the regex is deliberately not "any
# token with a dot" so a stray path in a command does not become a phantom hook.
SCRIPT_RE = re.compile(r"[\w./\\:-]+\.(?:py|sh|ps1|cmd|bat)", re.I)
INTERPRETER = {".py": "python", ".sh": "bash", ".ps1": "powershell",
               ".cmd": "cmd", ".bat": "cmd"}


def enumerate_controls():
    found, unparsed = {}, []
    for sp in SETTINGS:
        if not os.path.exists(sp):
            continue
        cfg = json.loads(io.open(sp, encoding="utf-8").read())
        for event, entries in (cfg.get("hooks") or {}).items():
            for entry in entries or []:
                matcher = entry.get("matcher", "")
                for h in entry.get("hooks") or []:
                    cmd = h.get("command") or ""
                    m = SCRIPT_RE.findall(cmd)
                    if not m:
                        # Recorded, not dropped. A command we cannot parse is a
                        # coverage hole and must be visible as one.
                        unparsed.append({"event": event, "command": cmd,
                                         "source": os.path.basename(sp)})
                        continue
                    script = m[-1].replace("\\", "/")
                    name = os.path.basename(script)
                    ext = os.path.splitext(name)[1].lower()
                    found.setdefault((name, event), {
                        "hook": name, "event": event, "matcher": matcher,
                        "command": cmd, "source": os.path.basename(sp),
                        "interpreter": INTERPRETER.get(ext, "unknown"),
                        "path": None,
                    })
    return found, unparsed


def resolve_on_disk(found):
    index = {}
    for d in (os.path.join(VAULT, ".claude", "hooks"),
              os.path.join(VAULT, ".claude", "scripts")):
        for root, dirs, files in os.walk(d):
            dirs[:] = [x for x in dirs if x not in ("__pycache__", ".pytest_cache")]
            for f in files:
                index.setdefault(f, os.path.join(root, f))
    missing = []
    for rec in found.values():
        p = index.get(rec["hook"])
        rec["path"] = os.path.relpath(p, VAULT).replace("\\", "/") if p else None
        if not p:
            missing.append(rec["hook"])
    return sorted(set(missing))


def main():
    found, unparsed = enumerate_controls()
    missing = resolve_on_disk(found)
    controls = sorted(found.values(), key=lambda r: (r["event"], r["hook"]))

    payload = {
        "generated_by": ".claude/scripts/enumerate_controls.py",
        "purpose": "denominator for the control-fires suite coverage gate",
        "pairs": len(controls),
        "distinct_files": len({c["hook"] for c in controls}),
        "by_event": dict(collections.Counter(c["event"] for c in controls)),
        "by_interpreter": dict(collections.Counter(c["interpreter"] for c in controls)),
        "registered_but_absent": missing,
        "unparsed_commands": unparsed,
        "controls": controls,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Atomic: write a sibling temp file then replace. The control-fires suite
    # probes hook-write-regression-gate.py, which runs the whole pytest suite,
    # which re-enters that suite and re-runs this script. A plain open(..., "w")
    # truncates the file at the exact moment a concurrent reader may be parsing
    # it, producing a JSONDecodeError unrelated to anything under test.
    tmp = OUT + f".tmp.{os.getpid()}"
    io.open(tmp, "w", encoding="utf-8", newline="\n").write(json.dumps(payload, indent=1) + "\n")
    os.replace(tmp, OUT)

    print(f"registered (hook, event) pairs: {len(controls)}")
    print(f"distinct hook files          : {payload['distinct_files']}")
    print(f"by event      : {payload['by_event']}")
    print(f"by interpreter: {payload['by_interpreter']}")
    if unparsed:
        print(f"UNPARSED COMMANDS ({len(unparsed)}) -- these name no recognisable script:")
        for u in unparsed:
            print(f"   {u['event']}: {u['command'][:100]}")
    if missing:
        print("REGISTERED BUT NOT ON DISK:", missing)
    print("wrote", OUT)

    if not controls:
        # An empty denominator makes the coverage gate vacuously true. Never
        # return success on it.
        print("FATAL: enumerated ZERO controls. Settings are missing, empty, or "
              "unparseable. A zero denominator would make the coverage gate pass "
              "while verifying nothing.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
