"""
QA harness for token-breakdown.py — runs all 7 synthetic tests.
Each test writes a synthetic JSONL fixture, invokes the hook via subprocess
with a crafted stdin payload, then inspects the tail of governance-log.jsonl
for the expected outcome (event present or absent).

Sets OBSERVABILITY_ENV=test so emits don't pollute prod counters.
"""
import json, os, subprocess, sys, shutil
from pathlib import Path

PYTHON = r"C:\Program Files\Python314\python.exe"
HOOK   = r"C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\hooks\token-breakdown.py"
GLOG   = r"C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\hooks\governance-log.jsonl"
QADIR  = r"C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\hooks\tests\qa-obs-v2-a"
os.makedirs(QADIR, exist_ok=True)

env = os.environ.copy()
env["OBSERVABILITY_ENV"] = "test"
env["PYTHONIOENCODING"] = "utf-8"

def write_fixture(name, entries):
    p = os.path.join(QADIR, name)
    with open(p, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p

def count_log_lines():
    try:
        with open(GLOG, "rb") as f:
            return sum(1 for _ in f)
    except FileNotFoundError:
        return 0

def latest_token_breakdown_event(since_sessionid):
    """Return last 'token_breakdown' event for given session_id, or None."""
    try:
        with open(GLOG, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return None
    # scan from the bottom for efficiency
    for ln in reversed(lines):
        try:
            ev = json.loads(ln)
        except Exception:
            continue
        if ev.get("event") == "token_breakdown" and ev.get("session") == since_sessionid:
            return ev
    return None

def run_hook(transcript_path, stop_hook_active=False, label="t"):
    payload = {"transcript_path": transcript_path, "stop_hook_active": stop_hook_active}
    proc = subprocess.run(
        [PYTHON, HOOK],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    return {"rc": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

results = {}

# ---------- T6: stop_hook_active=true ----------
# Use a bogus path; shouldn't matter because hook returns early.
before = count_log_lines()
r = run_hook(os.path.join(QADIR, "nonexistent.jsonl"), stop_hook_active=True, label="t6")
after = count_log_lines()
results["T6_stop_hook_active"] = {
    "rc": r["rc"],
    "lines_added": after - before,
    "pass": r["rc"] == 0 and (after - before) == 0,
}

# ---------- T7: nonexistent transcript_path ----------
before = count_log_lines()
r = run_hook(r"C:\Users\WiktorPotapczyk\Desktop\Vault\.claude\hooks\tests\qa-obs-v2-a\definitely-missing.jsonl", label="t7")
after = count_log_lines()
results["T7_missing_transcript"] = {
    "rc": r["rc"],
    "lines_added": after - before,
    "pass": r["rc"] == 0 and (after - before) == 0,
}

# ---------- T1: empty turn (non-zero usage but no boundary found) ----------
# Build a single assistant entry with all-zero usage, no tool_uses.
t1_sid = "qa-t1-empty"
t1_entries = [
    # Fresh user prompt (boundary)
    {"type": "user", "message": {"content": "hello"}, "sessionId": t1_sid},
    # Assistant with all-zero usage, no tool_uses
    {"type": "assistant", "message": {
        "content": [{"type": "text", "text": "hi"}],
        "usage": {"input_tokens": 0, "output_tokens": 0,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    }, "sessionId": t1_sid},
]
t1_path = write_fixture(f"{t1_sid}.jsonl", t1_entries)
before = count_log_lines()
r = run_hook(t1_path, label="t1")
after = count_log_lines()
ev = latest_token_breakdown_event(t1_sid)
results["T1_empty_turn"] = {
    "rc": r["rc"],
    "lines_added": after - before,
    "event_present": ev is not None,
    "pass": r["rc"] == 0 and ev is None,  # skip guard should fire
}

# ---------- T2: single main-session turn, 3 non-Agent tool_uses ----------
t2_sid = "qa-t2-main-session"
t2_entries = [
    {"type": "user", "message": {"content": "do stuff"}, "sessionId": t2_sid},
    {"type": "assistant", "message": {
        "content": [
            {"type": "text", "text": "let me help"},
            {"type": "tool_use", "id": "tu1", "name": "Read", "input": {"file_path": "/x"}},
            {"type": "tool_use", "id": "tu2", "name": "Edit", "input": {}},
            {"type": "tool_use", "id": "tu3", "name": "Bash", "input": {"command": "ls"}},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 50,
                  "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 200}
    }, "sessionId": t2_sid},
]
t2_path = write_fixture(f"{t2_sid}.jsonl", t2_entries)
run_hook(t2_path, label="t2")
ev = latest_token_breakdown_event(t2_sid)
t2_pass = False
t2_detail = {}
if ev:
    ms = ev.get("main_session", {})
    tc = ev.get("tool_calls", {})
    bs = ev.get("by_subagent", [])
    tt = ev.get("turn_total_tokens")
    t2_detail = {"main_session": ms, "tool_calls": tc, "by_subagent_len": len(bs), "turn_total": tt}
    t2_pass = (
        ms.get("input_tokens") == 100
        and ms.get("output_tokens") == 50
        and ms.get("cache_read_input_tokens") == 5000
        and ms.get("cache_creation_input_tokens") == 200
        and tc.get("Read") == 1 and tc.get("Edit") == 1 and tc.get("Bash") == 1
        and bs == []
        and tt == 5350
    )
results["T2_main_session"] = {"pass": t2_pass, "event": ev is not None, **t2_detail}

# ---------- T3: 1 Agent dispatch ----------
t3_sid = "qa-t3-one-agent"
t3_entries = [
    {"type": "user", "message": {"content": "check it"}, "sessionId": t3_sid},
    {"type": "assistant", "message": {
        "content": [
            {"type": "tool_use", "id": "agent-1", "name": "Agent",
             "input": {"subagent_type": "pm-orchestrator", "prompt": "…"}},
        ],
        "usage": {"input_tokens": 10, "output_tokens": 20,
                  "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}
    }, "sessionId": t3_sid},
    # user entry carrying toolUseResult (top-level) with usage
    {"type": "user",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "agent-1", "content": "ok"}]},
     "toolUseResult": {
         "usage": {"input_tokens": 1069, "output_tokens": 1460,
                   "cache_read_input_tokens": 26253, "cache_creation_input_tokens": 5830},
         "totalTokens": 34612
     },
     "sessionId": t3_sid},
]
t3_path = write_fixture(f"{t3_sid}.jsonl", t3_entries)
run_hook(t3_path, label="t3")
ev = latest_token_breakdown_event(t3_sid)
t3_detail = {}
t3_pass = False
if ev:
    bs = ev.get("by_subagent", [])
    t3_detail = {"by_subagent_len": len(bs), "first": bs[0] if bs else None}
    t3_pass = (
        len(bs) == 1
        and bs[0]["subagent_type"] == "pm-orchestrator"
        and bs[0]["totalTokens"] == 34612
        and bs[0]["input_tokens"] == 1069
        and bs[0]["output_tokens"] == 1460
        and bs[0]["cache_read_input_tokens"] == 26253
        and bs[0]["cache_creation_input_tokens"] == 5830
    )
results["T3_one_agent"] = {"pass": t3_pass, "event": ev is not None, **t3_detail}

# ---------- T4: 3 distinct Agent dispatches ----------
t4_sid = "qa-t4-three-agents"
t4_entries = [
    {"type": "user", "message": {"content": "run trio"}, "sessionId": t4_sid},
    {"type": "assistant", "message": {
        "content": [
            {"type": "tool_use", "id": "a1", "name": "Agent",
             "input": {"subagent_type": "pm-orchestrator"}},
            {"type": "tool_use", "id": "a2", "name": "Agent",
             "input": {"subagent_type": "architect-reviewer"}},
            {"type": "tool_use", "id": "a3", "name": "Agent",
             "input": {"subagent_type": "research-analyst"}},
        ],
        "usage": {"input_tokens": 1, "output_tokens": 2,
                  "cache_read_input_tokens": 3, "cache_creation_input_tokens": 4}
    }, "sessionId": t4_sid},
    {"type": "user",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "a1"}]},
     "toolUseResult": {"usage": {"input_tokens": 100, "output_tokens": 200,
                                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                       "totalTokens": 300},
     "sessionId": t4_sid},
    {"type": "user",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "a2"}]},
     "toolUseResult": {"usage": {"input_tokens": 400, "output_tokens": 500,
                                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                       "totalTokens": 900},
     "sessionId": t4_sid},
    {"type": "user",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "a3"}]},
     "toolUseResult": {"usage": {"input_tokens": 700, "output_tokens": 800,
                                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                       "totalTokens": 1500},
     "sessionId": t4_sid},
]
t4_path = write_fixture(f"{t4_sid}.jsonl", t4_entries)
run_hook(t4_path, label="t4")
ev = latest_token_breakdown_event(t4_sid)
t4_pass = False
t4_detail = {}
if ev:
    bs = ev.get("by_subagent", [])
    types = sorted(r["subagent_type"] for r in bs)
    t4_detail = {"by_subagent_len": len(bs), "types": types}
    t4_pass = (
        len(bs) == 3
        and types == ["architect-reviewer", "pm-orchestrator", "research-analyst"]
    )
results["T4_three_agents"] = {"pass": t4_pass, "event": ev is not None, **t4_detail}

# ---------- T5: orphan toolUseResult (no matching Agent in agent_map) ----------
t5_sid = "qa-t5-orphan"
t5_entries = [
    {"type": "user", "message": {"content": "orphan test"}, "sessionId": t5_sid},
    {"type": "assistant", "message": {
        "content": [{"type": "text", "text": "working"}],
        "usage": {"input_tokens": 5, "output_tokens": 5,
                  "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    }, "sessionId": t5_sid},
    # orphan user entry — toolUseResult with usage, but tool_use_id "ghost-id" never appeared in agent_map
    {"type": "user",
     "message": {"content": [{"type": "tool_result", "tool_use_id": "ghost-id"}]},
     "toolUseResult": {"usage": {"input_tokens": 999, "output_tokens": 999,
                                 "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
                       "totalTokens": 1998},
     "sessionId": t5_sid},
]
t5_path = write_fixture(f"{t5_sid}.jsonl", t5_entries)
run_hook(t5_path, label="t5")
ev = latest_token_breakdown_event(t5_sid)
t5_pass = False
t5_detail = {}
if ev:
    bs = ev.get("by_subagent", [])
    # must be empty — orphan should be skipped
    has_unknown = any(r["subagent_type"] == "unknown" for r in bs)
    t5_detail = {"by_subagent_len": len(bs), "has_unknown": has_unknown}
    t5_pass = len(bs) == 0 and not has_unknown
results["T5_orphan"] = {"pass": t5_pass, "event": ev is not None, **t5_detail}

# ---------- Print summary ----------
print("=" * 60)
print("QA HARNESS RESULTS")
print("=" * 60)
for name, r in results.items():
    mark = "PASS" if r.get("pass") else "FAIL"
    print(f"{mark}  {name}")
    for k, v in r.items():
        if k == "pass": continue
        print(f"       {k}: {v}")
print()
n_pass = sum(1 for r in results.values() if r.get("pass"))
print(f"TOTAL: {n_pass} / {len(results)} PASS")
# Cleanup fixtures (but keep harness for re-run)
for f in os.listdir(QADIR):
    if f.endswith(".jsonl"):
        try: os.remove(os.path.join(QADIR, f))
        except: pass
