"""self_heal_shadow_settings.py: derive the improver's runtime settings file
for the shadow workspace (write-path decision of 2026-09-18, Route B).

The improver runs with cwd = a throwaway shadow copy of the checkout in
which `.claude` is mounted as `_claude`. Two things in the committed
`ci-settings.json` must change for that run, and only at runtime:

  1. Hook commands reference `$CLAUDE_PROJECT_DIR/.claude/...`. In the
     shadow that directory does not exist, so the commands are rewritten to
     the ABSOLUTE path of the real checkout (`<workspace>/.claude/...`).
     The Gate-1 guards therefore run from bytes the improver process never
     touched this run, not from a same-run copy.
  2. Edit and Write permission patterns reference `.claude/...`. Those are
     matched against the paths the agent edits, which live under
     `_claude/...` in the shadow, so the prefix inside the parentheses is
     rewritten. Everything else (Read, Glob, Grep, Bash, Projects/** rules)
     is left untouched.

Pure function plus a small CLI. Python 3.14, standard library only.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path

HOOK_PREFIX = "$CLAUDE_PROJECT_DIR/.claude/"
RULE_RE = re.compile(r"^(Edit|Write)\(\.claude/")


def rewrite_hook_command(command: str, workspace_abs: str) -> str:
    ws = workspace_abs.rstrip("/")
    return command.replace(HOOK_PREFIX, f"{ws}/.claude/")


def rewrite_rule(rule: str) -> str:
    return RULE_RE.sub(lambda m: f"{m.group(1)}(_claude/", rule, count=1)


def build_shadow_settings(ci_settings: dict, workspace_abs: str) -> dict:
    out = copy.deepcopy(ci_settings)
    for event, groups in (out.get("hooks") or {}).items():
        for group in groups:
            for hook in group.get("hooks", []):
                if "command" in hook:
                    hook["command"] = rewrite_hook_command(hook["command"], workspace_abs)
    perms = out.get("permissions") or {}
    for key in ("allow", "deny"):
        if key in perms:
            perms[key] = [rewrite_rule(r) for r in perms[key]]
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="self_heal_shadow_settings.py")
    p.add_argument("--ci-settings", required=True)
    p.add_argument("--workspace", required=True, help="absolute path of the real checkout")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    ci = json.loads(Path(args.ci_settings).read_text(encoding="utf-8"))
    shadow = build_shadow_settings(ci, args.workspace)
    Path(args.out).write_text(json.dumps(shadow, indent=2) + "\n", encoding="utf-8")
    hooks = sum(len(g.get("hooks", [])) for gs in (shadow.get("hooks") or {}).values() for g in gs)
    perms = shadow.get("permissions") or {}
    print(f"shadow settings written to {args.out}: {hooks} hook(s) re-pointed at {args.workspace}, "
          f"{len(perms.get('allow', []))} allow and {len(perms.get('deny', []))} deny rule(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
