#!/usr/bin/env python3
"""Generate agent+skill registry from local .claude/ and plugin cache.

Scans all agent .md files and skill SKILL.md files, extracts metadata,
and produces .claude/registry.json — the single source of truth for
what agents and skills are available.

Usage:
    python .claude/scripts/generate_registry.py
"""
import json
import os
import re
import sys
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
PLUGIN_CACHE = Path.home() / ".claude" / "plugins" / "cache"
INSTALLED_PLUGINS_JSON = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
OUTPUT = VAULT / ".claude" / "registry.json"

# Stop words for keyword extraction
STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "must", "ought",
    "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "me", "him", "her", "us", "them", "my", "your", "his",
    "its", "our", "their", "what", "which", "who", "whom", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same",
    "so", "than", "too", "very", "just", "because", "as", "until", "while",
    "of", "at", "by", "for", "with", "about", "against", "between", "through",
    "during", "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further", "then",
    "once", "and", "but", "or", "if", "use", "used", "using", "agent",
    "when", "also", "e.g", "etc", "like", "including", "include", "includes",
    "specifically", "example", "examples", "invoke", "invoked", "ensure",
    "new", "existing", "based", "well", "work", "working", "first",
}


def extract_keywords(text: str, max_kw: int = 15) -> list[str]:
    """Extract domain keywords from description text."""
    words = re.findall(r"[a-z][a-z0-9\-]+", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in STOP_WORDS or len(w) < 3:
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq, key=lambda k: (-freq[k], k))
    return ranked[:max_kw]


def parse_agent_md(path: Path) -> dict | None:
    """Parse an agent .md file and extract metadata."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    name = path.stem
    lines = text.split("\n")

    # Extract frontmatter fields
    description = ""
    tools = []
    in_frontmatter = False
    fm_end = 0
    for i, line in enumerate(lines):
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                fm_end = i
                break
        if in_frontmatter:
            if line.startswith("description:"):
                description = line.split(":", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("tools:"):
                tools_str = line.split(":", 1)[1].strip()
                if tools_str.startswith("["):
                    tools = [t.strip().strip('"').strip("'")
                             for t in tools_str.strip("[]").split(",")]

    # If description not in frontmatter, use first non-empty line after frontmatter
    if not description:
        for line in lines[fm_end + 1:]:
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped[:200]
                break

    keywords = extract_keywords(description)

    return {
        "name": name,
        "description": description[:300],
        "keywords": keywords,
        "tools": tools,
    }


def parse_skill_md(path: Path) -> dict | None:
    """Parse a SKILL.md and extract metadata."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    skill_dir = path.parent.name
    lines = text.split("\n")

    # Try to get description from frontmatter
    description = ""
    in_frontmatter = False
    for line in lines[:30]:
        if line.strip() == "---":
            if not in_frontmatter:
                in_frontmatter = True
                continue
            else:
                break
        if in_frontmatter and line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip('"').strip("'")

    # Fallback: first heading or first substantial line
    if not description:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("# "):
                description = stripped[2:]
                break
            elif len(stripped) > 20 and not stripped.startswith("---"):
                description = stripped[:200]
                break

    keywords = extract_keywords(description)

    return {
        "name": skill_dir,
        "description": description[:300],
        "keywords": keywords,
    }


def scan_local_agents() -> list[dict]:
    agents_dir = VAULT / ".claude" / "agents"
    results = []
    if not agents_dir.exists():
        return results
    for f in sorted(agents_dir.glob("*.md")):
        if "backup" in str(f):
            continue
        parsed = parse_agent_md(f)
        if parsed:
            parsed["source"] = "local"
            results.append(parsed)
    return results


def scan_local_skills() -> list[dict]:
    skills_dir = VAULT / ".claude" / "skills"
    results = []
    if not skills_dir.exists():
        return results
    for skill_md in sorted(skills_dir.glob("*/[Ss][Kk][Ii][Ll][Ll].md")):
        parsed = parse_skill_md(skill_md)
        if parsed:
            parsed["source"] = "local"
            results.append(parsed)
    return results


def scan_plugin_agents() -> list[dict]:
    results = []
    if not PLUGIN_CACHE.exists():
        return results
    for agent_md in sorted(PLUGIN_CACHE.rglob("agents/*.md")):
        if "backup" in str(agent_md):
            continue
        parsed = parse_agent_md(agent_md)
        if parsed:
            # Derive plugin name from path
            rel = agent_md.relative_to(PLUGIN_CACHE)
            parsed["source"] = f"plugin:{rel.parts[0]}"
            results.append(parsed)
    return results


def scan_plugin_skills() -> list[dict]:
    results = []
    if not PLUGIN_CACHE.exists():
        return results
    for skill_md in sorted(PLUGIN_CACHE.rglob("*/[Ss][Kk][Ii][Ll][Ll].md")):
        parsed = parse_skill_md(skill_md)
        if parsed:
            rel = skill_md.relative_to(PLUGIN_CACHE)
            parsed["source"] = f"plugin:{rel.parts[0]}"
            results.append(parsed)
    return results


def load_installed_plugins() -> list[dict]:
    """Read installed_plugins.json and return a normalised list of plugin objects.

    installed_plugins.json schema (version 2 observed in the wild):
      {
        "version": 2,
        "plugins": {
          "<name>@<source>": [ { "scope", "installPath", "version", "installedAt",
                                  "lastUpdated", "gitCommitSha" (optional) }, ... ],
          ...
        }
      }

    Each key may have multiple installs (e.g. per-scope); we take the last element
    of the array (most-recently installed) as the canonical entry.

    Returns [] and prints a warning on any read/parse failure — never raises.
    """
    if not INSTALLED_PLUGINS_JSON.exists():
        print(f"  [WARN] installed_plugins.json not found at {INSTALLED_PLUGINS_JSON} — plugins list will be empty")
        return []

    try:
        with open(INSTALLED_PLUGINS_JSON, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as exc:
        print(f"  [WARN] Could not parse installed_plugins.json: {exc} — plugins list will be empty")
        return []

    plugins_map = raw.get("plugins")
    if not isinstance(plugins_map, dict):
        print(f"  [WARN] installed_plugins.json has unexpected structure (no 'plugins' dict) — plugins list will be empty")
        return []

    # Enabled/disabled state is NOT in installed_plugins.json (that is an install
    # manifest — disabled plugins remain listed). The authoritative source is the
    # `enabledPlugins` map in ~/.claude/settings.json, keyed by the same
    # "<name>@<source>" string. Default to True when a key is absent (present but
    # not explicitly disabled). Falls back to all-True if settings.json is unreadable.
    enabled_map: dict = {}
    try:
        settings_path = Path.home() / ".claude" / "settings.json"
        with open(settings_path, "r", encoding="utf-8") as sf:
            enabled_map = json.load(sf).get("enabledPlugins", {}) or {}
    except Exception as exc:
        print(f"  [WARN] Could not read enabledPlugins from settings.json: {exc} — assuming all enabled")

    results = []
    for key, installs in plugins_map.items():
        if not isinstance(installs, list) or not installs:
            continue
        # Take the last install entry as canonical (most-recently installed scope wins)
        install = installs[-1]
        if not isinstance(install, dict):
            continue

        # Parse name and marketplace/source from the "<name>@<source>" key format
        if "@" in key:
            name, _, marketplace = key.partition("@")
        else:
            name = key
            marketplace = ""

        version = install.get("version", "unknown")
        # Treat "unknown" versions as non-semver strings — still valid, just emit as-is
        enabled = bool(enabled_map.get(key, True))  # authoritative: settings.json enabledPlugins; default True if unlisted

        entry: dict = {
            "name": name,
            "enabled": enabled,
            "version": version,
            "installed_at": install.get("installedAt", ""),
            "last_updated": install.get("lastUpdated", ""),
        }
        if marketplace:
            entry["marketplace"] = marketplace
        if install.get("gitCommitSha"):
            entry["git_commit_sha"] = install["gitCommitSha"]

        results.append(entry)

    return results


def main():
    agents = scan_local_agents() + scan_plugin_agents()
    skills = scan_local_skills() + scan_plugin_skills()

    # Deduplicate by name (local takes precedence over plugin)
    seen_agents: dict[str, dict] = {}
    for a in agents:
        name = a["name"]
        if name not in seen_agents or a["source"] == "local":
            seen_agents[name] = a

    seen_skills: dict[str, dict] = {}
    for s in skills:
        name = s["name"]
        if name not in seen_skills or s["source"] == "local":
            seen_skills[name] = s

    plugins = load_installed_plugins()
    plugins_enabled = sum(1 for p in plugins if p.get("enabled", True))

    _now = __import__("datetime").datetime.now().isoformat()[:19]
    registry = {
        "generated_at": _now,
        # Keep "generated" key for any consumer that may reference the old name
        "generated": _now,
        "counts": {
            "agents": len(seen_agents),
            "skills": len(seen_skills),
            "plugins_total": len(plugins),
            "plugins_enabled": plugins_enabled,
        },
        "agents": {k: v for k, v in sorted(seen_agents.items())},
        "skills": {k: v for k, v in sorted(seen_skills.items())},
        "plugins": plugins,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)

    print(
        f"Registry generated: {len(seen_agents)} agents, {len(seen_skills)} skills, "
        f"{len(plugins)} plugins ({plugins_enabled} enabled) -> {OUTPUT}"
    )

    # Hook-liveness summary (GOV-2). Informational only — read the silent-zero
    # instrument (hook-activity.jsonl) at the natural "framework state changed"
    # moment and surface the registered-but-unmeasured count. Print-only; never
    # affects exit code. This is the cadence the reader's docstring intended
    # ("called at CMDB refresh time") — previously it was manual-only.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from hook_activity_report import report_dict
        hr = report_dict()
        print(
            f"  Hook liveness: {hr['distinct_hooks']} logging fires, "
            f"{len(hr['truly_silent'])} truly-silent, "
            f"{len(hr['logs_elsewhere_no_liveness'])} log-elsewhere "
            f"(of {hr['registered_count']} registered). "
            f"Full: python .claude/scripts/hook_activity_report.py"
        )
    except Exception as e:
        print(f"  [WARN] hook-liveness summary did not run: {e}")

    # Structural enforcement gates (Phase D dim4 C1/C2/C3). Run at every regen —
    # the moment framework state changes — and propagate a nonzero exit on hard
    # findings (dispatch-name drift, missing registered hook file). Pass
    # --no-validate to regenerate the registry without gating.
    if "--no-validate" not in sys.argv:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from structural_gates import run_gates
            return run_gates()
        except Exception as e:
            print(f"  [WARN] structural gates did not run: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
