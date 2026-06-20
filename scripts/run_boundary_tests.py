#!/usr/bin/env python3
"""Boundary-test coverage runner (enforcement boundary-test harness).

Design: [[2026-06-02-enforcement-boundary-test-design]] §3a/§4.

Discovers every `test_*.py` in .claude/hooks/, introspects each for FP-guard
coverage (methods named test_fp_*), runs the suite, and prints a coverage
report. BLOCK-class hooks with zero FP-guard methods are flagged GAP.

Usage:
    python .claude/scripts/run_boundary_tests.py                 # full report
    python .claude/scripts/run_boundary_tests.py --coverage-only # no test run, just counts
    python .claude/scripts/run_boundary_tests.py --hook dispatch_compliance_check

Exit code: 0 always (advisory reporter). The C4 gate in structural_gates.py is
the enforcement surface; this script is the human-facing report.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

HOOK_DIR = Path(os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "hooks")
))

# BLOCK-class hooks (decision:block / exit 2). These are the ones that MUST carry
# FP-guard coverage: a false positive here interrupts real work. Kept in sync
# with the design Appendix B fire-rate table. WARN/LOGGING hooks are advisory.
BLOCK_CLASS_HOOKS = {
    "dispatch_compliance_check", "dispatch-compliance-check",
    "subagent_quality_check", "subagent-quality-check",
    "process_step_check", "process-step-check",
    "work_verification_check", "work-verification-check",
    "proactivity_check", "proactivity-check",
    "wiki_citation_check", "wiki-citation-check",
    "classifier_field_check", "classifier-field-check",
    "verifier_gate", "verifier-gate",
}

FP_DEF = re.compile(r"def\s+(test_fp_\w+)", re.IGNORECASE)
TP_DEF = re.compile(r"def\s+(test_(?:tp_|tp|)\w+)")
ANY_TEST_DEF = re.compile(r"def\s+(test_\w+)")
REGRESSION_MARK = re.compile(r"origin['\"]?\s*[:=]\s*['\"]?regression|regression_memo", re.IGNORECASE)


def hook_name_from_test(p: Path) -> str:
    """test_dispatch_compliance_check.py -> dispatch_compliance_check"""
    return p.stem[len("test_"):]


def scan_file(p: Path) -> dict:
    text = p.read_text(encoding="utf-8", errors="replace")
    all_tests = ANY_TEST_DEF.findall(text)
    fp = FP_DEF.findall(text)
    fp_set = set(fp)
    tp = [t for t in all_tests if t not in fp_set]
    return {
        "hook": hook_name_from_test(p),
        "test_file": p.name,
        "tp_count": len(tp),
        "fp_count": len(fp_set),
        "regression": len(REGRESSION_MARK.findall(text)),
        "is_block_class": hook_name_from_test(p) in BLOCK_CLASS_HOOKS,
    }


def run_suite(p: Path) -> str:
    """Run one test file standalone; return PASS / FAIL(n) / ERROR."""
    try:
        r = subprocess.run(
            [sys.executable, str(p)],
            capture_output=True, text=True, timeout=120, cwd=str(HOOK_DIR.parent.parent),
        )
        out = (r.stderr or "") + (r.stdout or "")
        if r.returncode == 0 and ("OK" in out or "ok" in out):
            return "PASS"
        m = re.search(r"FAILED \(.*?failures=(\d+)", out)
        if m:
            return f"FAIL({m.group(1)})"
        return "FAIL" if r.returncode != 0 else "PASS"
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:  # noqa: BLE001
        return f"ERROR:{type(e).__name__}"


def main() -> int:
    coverage_only = "--coverage-only" in sys.argv
    hook_filter = None
    if "--hook" in sys.argv:
        i = sys.argv.index("--hook")
        if i + 1 < len(sys.argv):
            hook_filter = sys.argv[i + 1]

    test_files = sorted(HOOK_DIR.glob("test_*.py"))
    rows = []
    for p in test_files:
        info = scan_file(p)
        if hook_filter and hook_filter not in info["hook"]:
            continue
        if not coverage_only:
            info["outcome"] = run_suite(p)
        rows.append(info)

    print("BOUNDARY COVERAGE REPORT")
    print(f"{'Hook':<34} {'TP':>3} {'FP':>3} {'Reg':>4} {'Block?':>6}  {'Outcome' if not coverage_only else ''}")
    print("-" * 72)
    block_gaps = []
    for r in rows:
        block = "BLOCK" if r["is_block_class"] else "warn"
        outcome = r.get("outcome", "")
        flag = ""
        if r["is_block_class"] and r["fp_count"] == 0:
            flag = "  <-- GAP: no FP-guard"
            block_gaps.append(r["hook"])
        print(f"{r['hook']:<34} {r['tp_count']:>3} {r['fp_count']:>3} {r['regression']:>4} {block:>6}  {outcome}{flag}")

    total = len(rows)
    zero_fp = sum(1 for r in rows if r["fp_count"] == 0)
    print("-" * 72)
    print(f"Test files: {total} | zero FP-guard: {zero_fp} ({(100*zero_fp//total) if total else 0}%)")
    if block_gaps:
        print(f"BLOCK-class hooks still lacking FP-guards ({len(block_gaps)}): {', '.join(sorted(block_gaps))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
