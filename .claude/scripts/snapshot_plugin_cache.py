#!/usr/bin/env python3
"""Snapshot the user-level plugin install manifest into the repo.

TASK-033 (migration plan Phase 1, 2026-09-15-scheduled-jobs-off-laptop-plan.md,
architect review H1 fidelity gap + M1): ~/.claude/plugins/ is gitignored
(.gitignore:45, a directory-only rule) and absent on every GitHub Actions
runner and every fresh clone. Without a fallback, generate_registry.py and
asset_inventory.py's plugin-scanning functions silently degrade to zero
plugin rows on that substrate.

This script reads the same two sources generate_registry.py's own
load_installed_plugins() already reads:
  ~/.claude/plugins/installed_plugins.json   name/version/marketplace/install info
  ~/.claude/settings.json                    enabledPlugins map (enabled/disabled)

and writes ONLY plugin names, versions, and marketplace/source strings --
never cache file bodies, never install paths, never a credential -- to a new
committed, non-gitignored path: .claude/plugins-snapshot.json (confirmed
unmatched by the .claude/plugins/ directory-only .gitignore rule, a sibling
filename, not a path under it).

Run from auto-commit.ps1's existing pre-stage step, the same pattern already
proven for mirror_user_claude.py. FAIL-OPEN by design, mirroring that
script: a snapshot problem must never stop the vault's own autosave, so
every failure mode here degrades to an empty-but-valid snapshot plus a
printed note rather than a nonzero exit.

Usage:
    python .claude/scripts/snapshot_plugin_cache.py
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
USER_CLAUDE = Path.home() / ".claude"
DEFAULT_INSTALLED = USER_CLAUDE / "plugins" / "installed_plugins.json"
DEFAULT_SETTINGS = USER_CLAUDE / "settings.json"
DEFAULT_OUT = VAULT / ".claude" / "plugins-snapshot.json"


def load_plugins_and_enabled(installed_path: Path, settings_path: Path):
    """Returns (plugins: dict, notes: list). Never raises."""
    notes = []
    if not installed_path.exists():
        notes.append(f"INSTALLED_MANIFEST_ABSENT: {installed_path} not found; "
                      f"snapshot written with zero plugins.")
        return {}, notes
    try:
        manifest = json.loads(installed_path.read_text(encoding="utf-8"))
    except Exception as exc:
        notes.append(f"INSTALLED_MANIFEST_UNREADABLE: {exc}; snapshot written "
                      f"with zero plugins.")
        return {}, notes

    plugins_map = manifest.get("plugins")
    if not isinstance(plugins_map, dict):
        notes.append("INSTALLED_MANIFEST_MALFORMED: no 'plugins' dict; "
                      "snapshot written with zero plugins.")
        return {}, notes

    enabled_map = {}
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        enabled_map = settings.get("enabledPlugins", {}) or {}
    except Exception as exc:
        notes.append(f"USER_SETTINGS_UNREADABLE: {exc}; assuming all enabled.")

    out = {}
    for key, installs in plugins_map.items():
        if not isinstance(installs, list) or not installs:
            continue
        install = installs[-1]
        if not isinstance(install, dict):
            continue
        if "@" in key:
            name, _, marketplace = key.partition("@")
        else:
            name, marketplace = key, ""
        out[key] = {
            "name": name,
            "marketplace": marketplace,
            "version": install.get("version", "unknown"),
            "enabled": bool(enabled_map.get(key, True)),
        }
    return out, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--installed", type=Path, default=DEFAULT_INSTALLED)
    ap.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    plugins, notes = load_plugins_and_enabled(args.installed, args.settings)
    for n in notes:
        print(n)

    payload = {
        "generated_at": datetime.now().isoformat()[:19],
        "plugin_source": "snapshot",
        "plugins": plugins,
    }

    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        if args.out.exists():
            try:
                prior = json.loads(args.out.read_text(encoding="utf-8"))
            except Exception:
                prior = None
            if prior is not None and prior.get("plugins") == plugins:
                print(f"SNAPSHOT unchanged={len(plugins)} plugins -> {args.out}")
                return 0
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2, sort_keys=True, ensure_ascii=False)
            f.write("\n")
    except OSError as exc:
        print(f"SNAPSHOT WRITE FAILED: {exc}")
        return 2

    print(f"SNAPSHOT written={len(plugins)} plugins -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
