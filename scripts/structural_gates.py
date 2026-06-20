#!/usr/bin/env python3
"""Structural enforcement gates: Phase D dim4 (C1 / C2 / C3).

Three checks that formalize latent CMDB wiring, run at registry-generation time
(the moment framework state changes). Theme B of
Projects/Agent-Governance-Research/work/2026-05-31-phase-d-growth-candidates.md.

  C1: KNOWN_DISPATCH_NAMES drift across the 4 copies      → HARD (exit nonzero)
  C3: every settings*.json hook registration points to a
       .py that exists on disk                             → HARD (exit nonzero)
  C2: hook -> `_helper` import-coupling map; unguarded
       (module-level) imports are BLOCK-class, guarded
       (try/except) imports are WARN-class                 → INFORMATIONAL

Usage (standalone):
    python .claude/scripts/structural_gates.py            # run all, print, exit code
    python .claude/scripts/structural_gates.py --json     # machine-readable

Wired into generate_registry.py: it calls run_gates() after writing the registry
and propagates the exit code. Pass --no-validate to generate_registry.py to skip.
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
HOOKS_DIR = VAULT / ".claude" / "hooks"
SCRIPTS_DIR = VAULT / ".claude" / "scripts"
SETTINGS_FILES = [
    VAULT / ".claude" / "settings.json",
    VAULT / ".claude" / "settings.local.json",
]
DRIFT_TEST = HOOKS_DIR / "test_known_dispatch_names_drift.py"

# A .py path referenced from a hook command string, anywhere under .claude/.
_PY_IN_CLAUDE = re.compile(r"\.claude[\\/](?:hooks|scripts)[\\/][\w\-.]+\.py", re.IGNORECASE)

# C4 (2026-06-02): BLOCK-class hooks that must carry boundary (FP-guard) coverage.
# A false positive in any of these interrupts real work. Source: enforcement
# boundary-test harness design Appendix B. WARN-class until the first-5 are
# covered, then promote check_c4 severity to HARD.
_C4_BLOCK_CLASS_HOOKS = [
    "dispatch-compliance-check", "subagent-quality-check", "process-step-check",
    "work-verification-check", "proactivity-check", "wiki-citation-check",
    "classifier-field-check", "verifier-gate-check",
]
_FP_DEF = re.compile(r"def\s+test_fp_\w+", re.IGNORECASE)

REGISTRY = VAULT / ".claude" / "registry.json"
DISPATCH_LOGIC = HOOKS_DIR / "_dispatch_compliance_logic.py"

# C5 (2026-06-02): dispatch names that intentionally do NOT resolve to a live
# registry agent/skill. These are the FP-guards for the resolution gate: without
# them C5 would false-positive on deliberate entries (the over-application trap the
# boundary-test harness exists to prevent). Each needs a documented reason.
#   workflow-orchestrator: deprecated alias kept as a safety net for skills still
#     referencing it (CLAUDE.md §"n8n Two-Phase Orchestration"); not a live agent.
# (Alias-keys from SKILL_AGENT_ALIASES: e.g. "architect-review" -> architect-reviewer
# : are exempted separately/automatically, not listed here.)
_DEPRECATED_DISPATCH_ALIASES = {"workflow-orchestrator"}


def check_c1_dispatch_drift() -> dict:
    """C1: the 4 KNOWN_DISPATCH_NAMES copies must be identical.

    Reuses the proven drift-guard unittest rather than reimplementing the
    set comparison. Nonzero test exit => drift.
    """
    if not DRIFT_TEST.exists():
        return {"check": "C1", "severity": "HARD", "ok": False,
                "findings": [f"drift test missing: {DRIFT_TEST}"]}
    proc = subprocess.run(
        [sys.executable, str(DRIFT_TEST)],
        capture_output=True, text=True, cwd=str(VAULT),
    )
    if proc.returncode == 0:
        return {"check": "C1", "severity": "HARD", "ok": True, "findings": []}
    tail = (proc.stderr or proc.stdout).strip().splitlines()[-8:]
    return {"check": "C1", "severity": "HARD", "ok": False,
            "findings": ["KNOWN_DISPATCH_NAMES drift across copies:"] + tail}


def check_c3_hook_files_exist() -> dict:
    """C3: every .py referenced in a settings*.json hook command exists on disk."""
    findings = []
    checked = 0
    for sf in SETTINGS_FILES:
        if not sf.exists():
            continue
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception as e:
            findings.append(f"{sf.name}: unparseable ({e})")
            continue
        hooks = data.get("hooks", {})
        for event, entries in hooks.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                for h in entry.get("hooks", []):
                    cmd = h.get("command", "")
                    for m in _PY_IN_CLAUDE.findall(cmd):
                        checked += 1
                        # Normalize the matched .claude/... suffix under VAULT.
                        rel = m.replace("\\", "/")
                        target = VAULT / rel
                        if not target.exists():
                            findings.append(
                                f"{sf.name} [{event}]: registered hook file missing -> {rel}"
                            )
    return {"check": "C3", "severity": "HARD", "ok": not findings,
            "findings": findings, "checked": checked}


def _guarded_import_lines(tree: ast.AST) -> set:
    """Line numbers that fall inside a try-block body (=> guarded import)."""
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for stmt in node.body:
                for sub in ast.walk(stmt):
                    if hasattr(sub, "lineno"):
                        guarded.add(sub.lineno)
    return guarded


def check_c2_helper_coupling() -> dict:
    """C2: map hook -> `_helper` imports. Module-level = BLOCK-class (deleting the
    helper hard-breaks the hook); inside try/except = WARN-class (degrades gracefully).
    Informational: emits edges, never fails the build.
    """
    edges = []
    if not HOOKS_DIR.exists():
        return {"check": "C2", "severity": "INFO", "ok": True, "findings": [], "edges": []}
    for py in sorted(HOOKS_DIR.glob("*.py")):
        if py.name.startswith("test_"):
            continue
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(src)
        except Exception:
            continue
        guarded = _guarded_import_lines(tree)
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for mod in mods:
                top = mod.split(".")[0]
                if top.startswith("_") and not top.startswith("__"):
                    klass = "WARN" if node.lineno in guarded else "BLOCK"
                    edges.append({
                        "hook": py.name, "helper": top,
                        "line": node.lineno, "class": klass,
                    })
    block = [e for e in edges if e["class"] == "BLOCK"]
    findings = [
        f"{e['hook']} --[{e['class']}]--> {e['helper']} (line {e['line']})"
        for e in edges
    ]
    return {"check": "C2", "severity": "INFO", "ok": True,
            "findings": findings, "edges": edges,
            "summary": f"{len(edges)} helper edges ({len(block)} BLOCK-class)"}


def check_c4_boundary_coverage() -> dict:
    """C4: every BLOCK-class hook should have >=1 FP-guard test (test_fp_*).

    WARN-class: a false positive in a BLOCK hook interrupts real work, but missing
    coverage should not hard-fail registry regen while the harness is still rolling
    out (design §3b WARN->HARD path). Promote severity to HARD after the first-5
    hooks are covered + the pattern is proven.
    """
    findings = []
    covered = 0
    for hook in _C4_BLOCK_CLASS_HOOKS:
        test_file = HOOKS_DIR / f"test_{hook.replace('-', '_')}.py"
        if not test_file.exists():
            findings.append(f"{hook}: no test_*.py (0 FP-guards)")
            continue
        try:
            n_fp = len(_FP_DEF.findall(test_file.read_text(encoding="utf-8", errors="replace")))
        except Exception:
            n_fp = 0
        if n_fp == 0:
            findings.append(f"{hook}: test file present but 0 FP-guard methods")
        else:
            covered += 1
    total = len(_C4_BLOCK_CLASS_HOOKS)
    return {"check": "C4", "severity": "WARN", "ok": not findings,
            "findings": findings,
            "summary": f"{covered}/{total} BLOCK-class hooks have FP-guard coverage"}


def _load_dispatch_logic():
    """Import _dispatch_compliance_logic.py (lives in hooks/, not on sys.path).
    Returns the module or None."""
    if not DISPATCH_LOGIC.exists():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_dcl_for_c5", str(DISPATCH_LOGIC))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def check_c5_dispatch_name_resolution() -> dict:
    """C5: every KNOWN_DISPATCH_NAMES entry must resolve to a live target 
    a registered agent, a registered skill, a SKILL_AGENT_ALIASES key, or a
    documented deprecation alias. Anything else is a TRUE phantom: a dispatch
    name pointing at nothing (the finding_n8n_agents_missing_from_known_dispatch_names
    regression class: a renamed/removed agent left in the list).

    C1 only proves the 4 copies match EACH OTHER; they can be identically wrong.
    C5 is the orthogonal check against live registry reality.

    WARN-class: resolution is deterministic, but keep it advisory until proven 
    mirrors C4's WARN->HARD rollout. The exemptions (alias keys + deprecations) are
    the FP-guards.
    """
    dcl = _load_dispatch_logic()
    if dcl is None:
        return {"check": "C5", "severity": "WARN", "ok": True, "findings": [],
                "summary": "skipped (dispatch logic module unavailable)"}
    names = set(getattr(dcl, "KNOWN_DISPATCH_NAMES", set()) or set())
    alias_keys = set((getattr(dcl, "SKILL_AGENT_ALIASES", {}) or {}).keys())
    if not REGISTRY.exists():
        return {"check": "C5", "severity": "WARN", "ok": True, "findings": [],
                "summary": "skipped (registry.json absent)"}
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as e:
        return {"check": "C5", "severity": "WARN", "ok": False,
                "findings": [f"registry.json unparseable ({e})"]}
    resolvable = (set(reg.get("agents", {}).keys())
                  | set(reg.get("skills", {}).keys())
                  | alias_keys
                  | _DEPRECATED_DISPATCH_ALIASES)
    phantoms = sorted(n for n in names if n not in resolvable)
    findings = [f"phantom dispatch name (resolves to nothing): {p}" for p in phantoms]
    return {"check": "C5", "severity": "WARN", "ok": not findings,
            "findings": findings,
            "summary": f"{len(names) - len(phantoms)}/{len(names)} dispatch names resolve"}


def run_gates(as_json: bool = False) -> int:
    """Run all gates, print a report, return process exit code (0 ok / 1 hard finding)."""
    results = [
        check_c1_dispatch_drift(),
        check_c3_hook_files_exist(),
        check_c2_helper_coupling(),
        check_c4_boundary_coverage(),
        check_c5_dispatch_name_resolution(),
    ]
    if as_json:
        print(json.dumps({"gates": results}, indent=2))
    else:
        print("=== STRUCTURAL VALIDATION (Phase D dim4 C1/C2/C3 + C4) ===")
        for r in results:
            if r["ok"]:
                status = "OK"
            else:
                status = "WARN" if r["severity"] == "WARN" else "FAIL"
            label = {"C1": "KNOWN_DISPATCH_NAMES drift",
                     "C3": "settings -> hook-file existence",
                     "C2": "hook -> _helper coupling",
                     "C4": "BLOCK-hook boundary (FP-guard) coverage",
                     "C5": "dispatch-name -> registry resolution"}.get(r["check"], r["check"])
            extra = r.get("summary", "")
            print(f"  [{status}] {r['check']} {label}  {extra}")
            for f in r["findings"]:
                prefix = "        - " if r["ok"] else "    !!  "
                print(f"{prefix}{f}")
    hard_fail = any((not r["ok"]) and r["severity"] == "HARD" for r in results)
    return 1 if hard_fail else 0


if __name__ == "__main__":
    sys.exit(run_gates(as_json="--json" in sys.argv))
