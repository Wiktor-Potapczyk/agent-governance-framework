"""Exact replica of test_controls_fire.py _invoke/_classify, run over probes-12.json only."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

VAULT = Path(r"C:\Users\WiktorPotapczyk\Desktop\Vault")
PYTHON = sys.executable
FRAG = VAULT / ".claude" / "hooks" / "_probe_fragments" / "probes-12.json"
TRIP_SIGNALS = ("deny", "block", "warn")


def _invoke(hook_path, stdin_obj, scratch):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["GOVERNANCE_LOG_PATH"] = str(scratch / "governance-log.jsonl")
    env["HOOK_ACTIVITY_LOG_PATH"] = str(scratch / "hook-activity.jsonl")
    env.pop("MCP_HEALTH_FAIL_OPEN", None)
    return subprocess.run([PYTHON, str(VAULT / hook_path)],
                          input=json.dumps(stdin_obj), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env,
                          cwd=str(VAULT), timeout=90)


def _classify(proc):
    out = proc.stdout or ""
    err = proc.stderr or ""
    blob = out + err
    if '"deny"' in out or "'deny'" in out:
        return "deny"
    if proc.returncode == 2:
        return "block"
    if blob.strip():
        return "warn"
    return "silent"


fail = 0
m = json.loads(FRAG.read_text(encoding="utf-8"))
for p in m["probes"]:
    key = f"{p['event']}:{p['hook']}"
    for phase in ("trip", "pass"):
        case = p[phase]
        scratch = Path(tempfile.mkdtemp(prefix="probe12-"))
        proc = _invoke(p["path"], case["stdin"], scratch)
        got = _classify(proc)
        if phase == "trip":
            expected = case.get("expect", "any")
            ok = got in TRIP_SIGNALS if expected == "any" else got == expected
            note = f"expect={expected}"
        else:
            forbidden = case.get("must_not", ["deny", "block"])
            ok = got not in forbidden
            note = f"must_not={forbidden}"
        fail += 0 if ok else 1
        print(f"[{'PASS' if ok else 'FAIL'}] {key} {phase}: got={got} exit={proc.returncode} {note}")
        print(f"        stdout[:160]={(proc.stdout or '')[:160]!r}")
        print(f"        stderr[:160]={(proc.stderr or '')[:160]!r}")

print("=" * 70)
print(f"replica result: {fail} failing case(s)")
sys.exit(1 if fail else 0)
