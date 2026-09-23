#!/usr/bin/env python3
"""Generate the harness self-model: a deterministic, machine-regenerable inventory.

Emits `.claude/harness-self-model.md` describing the harness's own hook / skill /
agent inventory. Completes the DOCS-BUILD option (a) of the self-improvement-loop
spec (2026-07-13) Section 6 (Location doctrine + doc-as-loop-component): the
"machine-regenerable inventory in `.claude/`" leg, beyond the loop N5 doc checklist.

Usage:
    python .claude/scripts/generate_harness_self_model.py

Data contract (pinned; a reader can predict the output from this docstring):

1. Registry read. Load `.claude/registry.json`; consume `counts`
   (agents, skills, plugins_total, plugins_enabled) and `generated_at`. A missing
   key FAILS LOUD (raises KeyError with the missing key name) rather than emitting
   a partial doc with silent zeros.

2. Hook file glob. `sorted(Path('.claude/hooks').glob('*.py'))`, split into
   "implementation" vs `test_*.py`, so the totals block reports both "hook .py
   files on disk" and "of which test files" (the 103-vs-registered figures are
   intentionally different and each is labeled).

3. Settings merge. Read BOTH `.claude/settings.json` AND `.claude/settings.local.json`.
   For each, walk `hooks[<Event>]` -> matcher-groups -> `group['hooks'][*]['command']`.
   The `command` is a full shell invocation string (not a bare path), e.g.
   `"...python.exe" "...\\.claude\\scripts\\check_forbidden_tokens.py"`; the registered
   script is extracted by regex on the LAST `.claude/<dir>/<name>.(py|sh|ps1)`
   token in the command. Registered scripts are NOT confined to `.claude/hooks/`:
   settings.local.json registers `.claude/scripts/check_forbidden_tokens.py` as a
   PreToolUse hook, so the regex must accept any `.claude/<dir>/` prefix (a
   `hooks`-only pattern silently drops that runtime hook). Non-.py registered
   hooks (session-start.sh, ralph-stop-hook.ps1) are kept: the table's purpose is
   the runtime hook chain. A matcher-group may register multiple commands (iterate
   `group['hooks']`). Build `event -> set(scripts)`, UNION across both files per
   event, dedup, then `sorted(...)` the per-event script list. Event ordering is a
   fixed canonical order (CANONICAL_EVENTS); any unknown event is appended
   alphabetically at the end so a future new event never silently disappears.

4. Workflow-enforced skills. Glob `.claude/skills/*/SKILL.md`; for each, read text
   and test for the literal case-insensitive marker `workflow-enforced`; collect
   the skill directory name (parent folder) for every match; `sorted(...)`.

5. Output sections, in fixed order: (a) AUTO-GENERATED banner + one isolated
   generated-at line, (b) totals block, (c) hooks-by-event table, (d)
   Workflow-enforced-skills list.

Determinism: every list and dict-key iteration is `sorted(...)`; the ONLY line that
may vary between two consecutive runs is the generated-at line, and it is PINNED to
registry.json's `generated_at` (stable until the registry is regenerated), so back-to-
back runs are byte-identical. Output is written with `encoding="utf-8"`, `newline="\n"`,
no trailing whitespace, single trailing newline. Does NOT write on import (write
happens only in `main()` under `if __name__ == "__main__"`).
"""
import json
import re
from pathlib import Path

# Script lives at .claude/scripts/, so parents[2] is the vault root (CWD-independent).
VAULT = Path(__file__).resolve().parents[2]
CLAUDE = VAULT / ".claude"
REGISTRY = CLAUDE / "registry.json"
HOOKS_DIR = CLAUDE / "hooks"
SKILLS_DIR = CLAUDE / "skills"
SETTINGS_FILES = [CLAUDE / "settings.json", CLAUDE / "settings.local.json"]
OUTPUT = CLAUDE / "harness-self-model.md"

# Fixed canonical event ordering. Any event found in either settings file but not
# listed here is appended alphabetically (see order_events) so nothing is dropped.
CANONICAL_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolBatch",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "PreCompact",
    "PostCompact",
    "SessionEnd",
]

# Matches the LAST .claude/<dir>/<name>.(py|sh|ps1) token in a command string.
# Registered hooks are NOT confined to .claude/hooks/: settings.local.json registers
# .claude/scripts/check_forbidden_tokens.py as a PreToolUse hook, so anchoring on
# `.claude` (not on the literal `hooks` dir) is required or that runtime hook is
# silently dropped. Handles both / and \ separators (Windows commands embed \).
_HOOK_PATH_RE = re.compile(
    r"[\\/]\.claude[\\/][\w.-]+[\\/]([\w.-]+\.(?:py|sh|ps1))", re.IGNORECASE
)


def load_registry(path: Path) -> dict:
    """Load registry.json and return {counts, generated_at}. Fails loud on a missing key."""
    data = json.loads(path.read_text(encoding="utf-8"))
    counts = data["counts"]  # KeyError names the missing key if absent
    for key in ("agents", "skills", "plugins_total", "plugins_enabled"):
        if key not in counts:
            raise KeyError(f"registry.json counts missing required key: {key!r}")
    if "generated_at" not in data:
        raise KeyError("registry.json missing required key: 'generated_at'")
    return {"counts": counts, "generated_at": data["generated_at"]}


def glob_hook_py(hooks_dir: Path) -> tuple[list[str], list[str]]:
    """Return (impl_hooks, test_hooks) as sorted basename lists of .claude/hooks/*.py."""
    all_py = sorted(p.name for p in hooks_dir.glob("*.py"))
    test_py = [n for n in all_py if n.startswith("test_")]
    impl_py = [n for n in all_py if not n.startswith("test_")]
    return impl_py, test_py


def _extract_script(command: str) -> str | None:
    """Extract the registered hook script basename from a full command string."""
    matches = _HOOK_PATH_RE.findall(command)
    return matches[-1] if matches else None


def merge_hook_registrations(settings_files: list[Path]) -> dict[str, list[str]]:
    """Merge hook registrations across settings files into event -> sorted[script]."""
    event_scripts: dict[str, set[str]] = {}
    for path in settings_files:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for event, groups in data.get("hooks", {}).items():
            bucket = event_scripts.setdefault(event, set())
            for group in groups:
                for hook in group.get("hooks", []):
                    command = hook.get("command", "")
                    script = _extract_script(command)
                    if script:
                        bucket.add(script)
    return {event: sorted(scripts) for event, scripts in event_scripts.items()}


def order_events(events: list[str]) -> list[str]:
    """Canonical-order the events; unknown events appended alphabetically at the end."""
    present = set(events)
    ordered = [e for e in CANONICAL_EVENTS if e in present]
    extras = sorted(e for e in present if e not in CANONICAL_EVENTS)
    return ordered + extras


def find_workflow_enforced_skills(skills_dir: Path) -> list[str]:
    """Return sorted skill directory names whose SKILL.md carries the Workflow-enforced marker."""
    matched: list[str] = []
    for skill_md in skills_dir.glob("*/SKILL.md"):
        text = skill_md.read_text(encoding="utf-8", errors="replace")
        if "workflow-enforced" in text.lower():
            matched.append(skill_md.parent.name)
    return sorted(matched)


def render(registry: dict, impl_hooks: list[str], test_hooks: list[str],
           event_scripts: dict[str, list[str]], wf_skills: list[str]) -> str:
    """Render the harness self-model Markdown from the collected inventory."""
    counts = registry["counts"]
    ordered_events = order_events(list(event_scripts.keys()))
    total_hook_py = len(impl_hooks) + len(test_hooks)
    distinct_scripts = sorted({s for scripts in event_scripts.values() for s in scripts})

    lines: list[str] = []
    lines.append("<!-- AUTO-GENERATED by .claude/scripts/generate_harness_self_model.py -->")
    lines.append("<!-- DO NOT hand-edit. Regenerate: python .claude/scripts/generate_harness_self_model.py -->")
    lines.append(f"<!-- generated-at: {registry['generated_at']} (pinned to registry.json) -->")
    lines.append("")
    lines.append("# Harness Self-Model")
    lines.append("")
    lines.append(
        "Machine-regenerable inventory of the harness's own hooks, skills, and agents. "
        "Every figure is derived from live disk state (registry.json, .claude/hooks/, "
        ".claude/skills/, both settings files) at generation time."
    )
    lines.append("")

    # (b) Totals block
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value | Source |")
    lines.append("|---|---|---|")
    lines.append(f"| Agents | {counts['agents']} | registry.json counts |")
    lines.append(f"| Skills | {counts['skills']} | registry.json counts |")
    lines.append(f"| Plugins (total) | {counts['plugins_total']} | registry.json counts |")
    lines.append(f"| Plugins (enabled) | {counts['plugins_enabled']} | registry.json counts |")
    lines.append(f"| Hook .py files on disk | {total_hook_py} | glob .claude/hooks/*.py |")
    lines.append(f"| of which test files (test_*.py) | {len(test_hooks)} | glob .claude/hooks/test_*.py |")
    lines.append(f"| of which implementation files | {len(impl_hooks)} | glob .claude/hooks/*.py minus tests |")
    lines.append(f"| Workflow-enforced skills | {len(wf_skills)} | grep Workflow-enforced in SKILL.md |")
    lines.append(f"| Distinct events with registered hooks | {len(ordered_events)} | merged settings files |")
    lines.append(f"| Distinct registered hook scripts (all events) | {len(distinct_scripts)} | merged settings files |")
    lines.append("")
    lines.append(
        "Note: \"Hook .py files on disk\" (glob-derived) and \"distinct registered hook "
        "scripts\" (settings-derived) are intentionally different figures. The disk glob "
        "counts every .py file including tests and unregistered helpers; the registered "
        "count reflects the runtime hook chain and includes non-.py scripts (.sh/.ps1)."
    )
    lines.append("")

    # (c) Hooks-by-event table (merged view across both settings files)
    lines.append("## Hooks by Event")
    lines.append("")
    lines.append("Merged registrations across .claude/settings.json and .claude/settings.local.json.")
    lines.append("")
    lines.append("| Event | Registered scripts | Scripts |")
    lines.append("|---|---|---|")
    for event in ordered_events:
        scripts = event_scripts[event]
        script_cell = ", ".join(scripts) if scripts else "(none)"
        lines.append(f"| {event} | {len(scripts)} | {script_cell} |")
    lines.append("")

    # (d) Workflow-enforced skills list
    lines.append("## Workflow-Enforced Skills")
    lines.append("")
    lines.append("Skills whose SKILL.md carries the literal `Workflow-enforced` marker.")
    lines.append("")
    if wf_skills:
        for name in wf_skills:
            lines.append(f"- {name}")
    else:
        lines.append("- (none)")
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    registry = load_registry(REGISTRY)
    impl_hooks, test_hooks = glob_hook_py(HOOKS_DIR)
    event_scripts = merge_hook_registrations(SETTINGS_FILES)
    wf_skills = find_workflow_enforced_skills(SKILLS_DIR)
    content = render(registry, impl_hooks, test_hooks, event_scripts, wf_skills)
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT} ({len(content)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
