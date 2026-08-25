"""Shared loader for the generated KNOWN_DISPATCH_NAMES data file.

Single source of truth: .claude/hooks/_known_dispatch_names.json, produced by
.claude/scripts/generate_known_dispatch_names.py (union of registry.json's
agents+skills, a direct scan of .claude/agents/*.md and
.claude/skills/*/SKILL.md, and a small legacy-compat allowlist, minus the
false-positive guard: see that script's docstring for full provenance).

Imported by the three name-consuming hooks:
  - agent-dispatch-check.py
  - _dispatch_compliance_logic.py (used by the dispatch-compliance-check.py
    Stop hook)
  - governance-log.py

so there is exactly one file-read implementation, rather than three copies of
both the DATA and the loading code (the pre-2026-08-19 state: three hand-typed
KNOWN_DISPATCH_NAMES set literals, held in sync only by a drift test).

Each caller supplies its own `fallback` set for when the data file is
missing, unreadable, or malformed. The three hooks have different failure
costs (never-deny vs. can-block vs. log-only), so the safe fallback direction
is decided per caller, not uniformly here: see the inline comment at each
call site for the reasoning.
"""
import json
import os
import sys


_DATA_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "_known_dispatch_names.json"
)


def load_known_dispatch_names(fallback, warn_label=None):
    """Return a set of dispatch names read from the generated data file.

    On any read/parse/schema failure, returns `fallback` unchanged and (if
    `warn_label` is given) prints one stderr line naming the failure, so a
    broken generated file is loud rather than silently degrading
    enforcement. Never raises.
    """
    reason = None
    try:
        with open(_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        names = data.get("known_dispatch_names")
        if isinstance(names, list) and names:
            return set(names)
        reason = "empty or malformed 'known_dispatch_names' field"
    except FileNotFoundError:
        reason = "file not found"
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"

    if warn_label:
        try:
            print(
                f"KNOWN_DISPATCH_NAMES ({warn_label}): could not read "
                f"{_DATA_PATH} ({reason}). Falling back to {len(fallback)} "
                "bundled name(s). Run "
                "'python .claude/scripts/generate_known_dispatch_names.py' "
                "to regenerate.",
                file=sys.stderr,
            )
        except Exception:
            pass
    return fallback
