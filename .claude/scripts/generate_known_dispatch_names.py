#!/usr/bin/env python3
"""Generate the KNOWN_DISPATCH_NAMES data file consumed by the three
dispatch-name-matching hooks (agent-dispatch-check.py, dispatch-compliance-check.py
via _dispatch_compliance_logic.py, governance-log.py).

Replaces the three hand-maintained KNOWN_DISPATCH_NAMES set literals (which only
ever covered 47 of 54 plugin agents and zero of 138 plugin skills, per
Projects/Agent-Governance-Research/work/2026-08-19-plugin-wiring-investigation.md)
with one generated, mechanically-derived population.

Sources, unioned:
  1. .claude/registry.json's `agents` + `skills` dict keys (local + plugin,
     local wins on name collision inside the registry itself).
  2. A direct scan of .claude/agents/*.md and .claude/skills/*/SKILL.md on
     disk. This is deliberate belt-and-suspenders against registry.json
     staleness for LOCAL names specifically: a brand-new local agent/skill
     file is readable immediately, without needing the (comparatively
     expensive) plugin-cache walk that only regenerating registry.json
     performs. Plugin names still only ever arrive via registry.json.
  3. LEGACY_COMPAT_NAMES: a small, explicit set of declared tokens that are
     not backed by any file but must stay recognized for backward
     compatibility (see comment on the constant below).

Then subtracts FALSE_POSITIVE_GUARD: the exact 7 plugin agent names the three
hooks already excluded by hand (2026-08-07 prune) because they are bare or
near-bare common-English compounds that the comma-segment matching in
extract_dispatch_names() can pick up from ordinary trailing reasoning text in
a MUST DISPATCH line, producing a phantom DECLARED item unrelated to any real
dispatch. This mirrors an existing, already-ratified exclusion; it is not new
policy invented by this generator.

Writes: .claude/hooks/_known_dispatch_names.json

Usage:
    python .claude/scripts/generate_known_dispatch_names.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_DIR", r"C:\Users\WiktorPotapczyk\Desktop\Vault"))
REGISTRY_PATH = VAULT / ".claude" / "registry.json"
AGENTS_DIR = VAULT / ".claude" / "agents"
SKILLS_DIR = VAULT / ".claude" / "skills"
OUTPUT = VAULT / ".claude" / "hooks" / "_known_dispatch_names.json"

SCHEMA_VERSION = 1

# False-positive guard (defect 5 prune, 2026-08-07). Verbatim copy of the
# exclusion already documented in agent-dispatch-check.py,
# _dispatch_compliance_logic.py, governance-log.py, and
# Projects/Agent-Governance-Research/scripts/shared/known_names.py.
FALSE_POSITIVE_GUARD = {
    "analyzer", "comparator", "compliance_agent", "formatter_agent",
    "grader", "intake_agent", "monitoring_agent",
}

# Legacy/backward-compat declared tokens that are not backed by any agent or
# skill file on disk or in the registry, but must remain recognized because
# SKILL_AGENT_ALIASES (hand-maintained, out of scope for this generator —
# only the KNOWN_DISPATCH_NAMES triplicate was asked for) still maps
# "architect-review" onto the real agent "architect-reviewer". Dropping it
# here would silently stop recognizing the pre-2026-04-18 declared name.
LEGACY_COMPAT_NAMES = {"architect-review"}


def load_registry_names():
    """Return (agent_names, skill_names, registry_generated_at).

    All three come back empty/None on any read failure — callers still get a
    usable (if reduced) population from the local disk scan.
    """
    try:
        with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        agents = set(data.get("agents", {}).keys())
        skills = set(data.get("skills", {}).keys())
        gen_at = data.get("generated_at") or data.get("generated")
        return agents, skills, gen_at
    except Exception as exc:
        print(f"  [WARN] could not read registry.json: {exc}")
        return set(), set(), None


def scan_local_agent_names():
    """Local agent stems from .claude/agents/*.md (excludes backup files)."""
    names = set()
    if not AGENTS_DIR.exists():
        return names
    for f in AGENTS_DIR.glob("*.md"):
        if "backup" in f.name:
            continue
        names.add(f.stem)
    return names


def scan_local_skill_names():
    """Local skill directory names under .claude/skills/*/SKILL.md."""
    names = set()
    if not SKILLS_DIR.exists():
        return names
    for skill_md in SKILLS_DIR.glob("*/[Ss][Kk][Ii][Ll][Ll].md"):
        names.add(skill_md.parent.name)
    return names


def build_known_dispatch_names():
    """Return (names_set, provenance_dict, registry_generated_at)."""
    registry_agents, registry_skills, registry_generated_at = load_registry_names()
    local_agents = scan_local_agent_names()
    local_skills = scan_local_skill_names()

    raw_union = (
        registry_agents | registry_skills | local_agents | local_skills
        | LEGACY_COMPAT_NAMES
    )
    guarded_out = raw_union & FALSE_POSITIVE_GUARD
    names = raw_union - FALSE_POSITIVE_GUARD

    provenance = {
        "registry_agents": len(registry_agents),
        "registry_skills": len(registry_skills),
        "local_agent_files": len(local_agents),
        "local_skill_dirs": len(local_skills),
        "legacy_compat_names": len(LEGACY_COMPAT_NAMES),
        "false_positive_guard_excluded": len(guarded_out),
        "raw_union_before_guard": len(raw_union),
    }
    return names, provenance, registry_generated_at


def main():
    names, provenance, registry_generated_at = build_known_dispatch_names()

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "schema": SCHEMA_VERSION,
        "source_registry_generated_at": registry_generated_at,
        "counts": {**provenance, "total": len(names)},
        "false_positive_guard": sorted(FALSE_POSITIVE_GUARD),
        "legacy_compat_names": sorted(LEGACY_COMPAT_NAMES),
        "known_dispatch_names": sorted(names),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(
        f"KNOWN_DISPATCH_NAMES generated: {len(names)} names -> {OUTPUT}\n"
        f"  sources: {provenance}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
