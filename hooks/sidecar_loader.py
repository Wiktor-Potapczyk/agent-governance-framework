"""
Sidecar loader — H11 proof-of-concept (2026-04-18).

Provides `load_dispatches(skill_name)` for hooks that need to consult a process
skill's DISPATCHES.json as fallback ground truth when transcript classification
is missing or truncated (e.g., post-compaction enforcement blind spot, audit
finding H11).

Any hook can import this module and call load_dispatches() to get:
- list of mandatory dispatch names
- list of conditionally-mandatory dispatch names
- list of process-exemption-allowed specialists

Design notes:
- Skill dirs live at .claude/skills/<skill>/DISPATCHES.json (sibling to SKILL.md).
- If the sidecar is missing, return a sentinel (empty dict) — caller decides
  whether absence is valid (most process skills will eventually have a sidecar;
  skills without one fall back to prose-only contract).
- Silent-on-malformed: log warn to governance-log but don't crash the hook.
  Caller treats missing/malformed as "no sidecar available".
"""
import json
import os
from datetime import datetime


SKILLS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills"
)
GOVERNANCE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "governance-log.jsonl")


def _log_warn(skill_name, reason, detail=""):
    try:
        entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "event": "warn",
            "hook": "sidecar-loader",
            "skill": skill_name,
            "reason": reason,
            "detail": str(detail)[:200],
            "schema": 2,
        })
        with open(GOVERNANCE_LOG, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def load_dispatches(skill_name):
    """Return parsed DISPATCHES.json for `skill_name`, or {} if missing/malformed.

    Returns a dict with keys: schema_version, skill, mandatory_dispatches (list),
    conditional_dispatches (list), allowed_specialists_via_process_exemption (list).
    Missing keys default to empty list.
    """
    if not skill_name:
        return {}
    path = os.path.join(SKILLS_ROOT, skill_name, "DISPATCHES.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        _log_warn(skill_name, "sidecar_parse_error", str(e))
        return {}
    if not isinstance(data, dict):
        _log_warn(skill_name, "sidecar_not_object", type(data).__name__)
        return {}
    # Normalize defaults
    data.setdefault("mandatory_dispatches", [])
    data.setdefault("conditional_dispatches", [])
    data.setdefault("allowed_specialists_via_process_exemption", [])
    return data


def mandatory_agent_names(skill_name):
    """Flat list of agent names marked required in the sidecar.
    Convenience helper for hooks that want a simple allowlist."""
    data = load_dispatches(skill_name)
    return [
        d["name"] for d in data.get("mandatory_dispatches", [])
        if isinstance(d, dict) and d.get("name") and d.get("required", True)
    ]


def all_allowed_agent_names(skill_name):
    """Flat list of every agent a hook should consider legitimate inside this skill.
    = mandatory + conditional + exemption specialists."""
    data = load_dispatches(skill_name)
    names = set()
    for d in data.get("mandatory_dispatches", []):
        if isinstance(d, dict) and d.get("name"):
            names.add(d["name"])
    for d in data.get("conditional_dispatches", []):
        if isinstance(d, dict) and d.get("name"):
            names.add(d["name"])
    for n in data.get("allowed_specialists_via_process_exemption", []):
        if isinstance(n, str):
            names.add(n)
    return sorted(names)


if __name__ == "__main__":
    # POC self-test — verify the sidecar file can be read
    import sys
    skill = sys.argv[1] if len(sys.argv) > 1 else "process-build"
    data = load_dispatches(skill)
    if not data:
        print(f"NO_SIDECAR for skill '{skill}'")
        sys.exit(1)
    print(f"Loaded sidecar for skill: {data.get('skill')}")
    print(f"  schema_version: {data.get('schema_version')}")
    print(f"  mandatory: {mandatory_agent_names(skill)}")
    print(f"  all allowed: {all_allowed_agent_names(skill)}")
    print(f"  notes: {data.get('notes', '')[:100]}")
