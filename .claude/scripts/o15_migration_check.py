r"""
o15_migration_check.py - declarative verification for O15 (rules-directory adoption).

Spec of record: Projects/Agent-Governance-Research/work/2026-08-31-harness-takeover-objectives.md
section O15; plan: Projects/Agent-Governance-Research/work/2026-09-01-o15-migration-plan.md.

Asserts, mapping to O15 CHECK (a)-(d):
  (a) .claude/rules/plain-language.md exists; frontmatter parses (regex-based
      stdlib routine, the ONLY parser - no optional PyYAML fallback per plan
      decision 6); paths: key present with 4 non-empty globs; body carries
      exactly 10 "### PL-" blocks, each with a "**Provenance**:" line
      (mirrors the PL-10 doctrine-drift pytest in test_plain_language_check.py).
  (b) every plain-language rules-path string in plain-language-guard.py source
      names the NEW canonical path AND resolves on disk; then a guard-fire
      harness proves enforcement: three fixture payloads (governed-path Write
      with a PL-5 violation, governed-path clean Write, out-of-scope Write),
      asserting exit 0, a WARN naming PL-5 on the violation, exactly one temp
      JSONL record per in-scope payload carrying all ten PL keys, and total
      silence (no stderr, no record) on the out-of-scope payload.
  (c) .claude/plain-language-rules.md is absent OR is the intentional pointer:
      15 lines or fewer, names the new path, zero "### PL-" blocks.
  (d) .claude/registry.json contains an n8n-patterns skill entry.

Harness hygiene (plan decision 7): the guard is imported via
importlib.util.spec_from_file_location, its module-level AGG_LOG_PATH is
overridden to a temp file, and its _log_fire is no-opped so a probe run never
touches the live plain-language-warnings.jsonl calibration denominator or the
shared hook-activity sink. The script never writes outside a temp dir.

Overrides for fixture runs: --rules-path, --guard-path, --registry-path.
--only a,b limits which assertions run (used for Step-2 isolation runs).

Exit codes: 0 = every selected assertion passed; 1 = at least one failed
(each assertion prints PASS/FAIL; the first failure is named on a
FIRST-FAILED line).

Usage:
    "C:\Program Files\Python314\python.exe" .claude/scripts/o15_migration_check.py
"""

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]

NEW_RULES_REL = ".claude/rules/plain-language.md"
OLD_RULES_REL = ".claude/plain-language-rules.md"

# Any .claude/...plain-language....md path string, either slash direction.
RULES_PATH_STRING_RE = re.compile(
    r"\.claude[/\\][\w.\\/-]*plain-language[\w.\\/-]*\.md"
)

PL_KEYS = [f"PL-{i}" for i in range(1, 11)]


# ---------------------------------------------------------------- frontmatter

def parse_frontmatter(text):
    """Return (frontmatter_text, body_text) or (None, text) when no block.
    Regex-based stdlib routine; the only parser in this script."""
    m = re.match(r"\A---\r?\n(.*?)\r?\n---\r?\n", text, flags=re.S)
    if not m:
        return None, text
    return m.group(1), text[m.end():]


def extract_paths_globs(frontmatter_text):
    """Return the list of glob strings under the paths: key (dash-list form)."""
    lines = frontmatter_text.splitlines()
    globs = []
    in_paths = False
    for line in lines:
        if re.match(r"^paths:\s*$", line):
            in_paths = True
            continue
        if in_paths:
            m = re.match(r"^\s+-\s*[\"']?([^\"']+?)[\"']?\s*$", line)
            if m:
                globs.append(m.group(1).strip())
                continue
            if re.match(r"^\S", line):
                in_paths = False
    return globs


# ------------------------------------------------------------ guard harness

def _load_guard_module(guard_path, agg_log_path):
    """Import the guard from an explicit file path, redirect its JSONL sink to
    a temp file, and no-op its shared-activity logging (probe hygiene)."""
    hooks_dir = str(Path(guard_path).resolve().parent)
    live_hooks_dir = str(VAULT_ROOT / ".claude" / "hooks")
    for d in (hooks_dir, live_hooks_dir):
        if d not in sys.path:
            sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location("o15_guard_under_test", guard_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.AGG_LOG_PATH = str(agg_log_path)
    mod._log_fire = lambda *a, **k: None
    return mod


def run_guard_fixture(guard_path, payload, agg_log_path):
    """Feed one payload to the guard's main() via a patched stdin; return
    (exit_code, stderr_text, records_appended_this_run)."""
    before = 0
    if os.path.exists(agg_log_path):
        with open(agg_log_path, encoding="utf-8") as f:
            before = sum(1 for _ in f)
    mod = _load_guard_module(guard_path, agg_log_path)
    old_stdin = sys.stdin
    err = io.StringIO()
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        with contextlib.redirect_stderr(err):
            code = mod.main()
    finally:
        sys.stdin = old_stdin
    records = []
    if os.path.exists(agg_log_path):
        with open(agg_log_path, encoding="utf-8") as f:
            lines = f.read().splitlines()
        records = [json.loads(x) for x in lines[before:]]
    return code, err.getvalue(), records


def fixture_payloads():
    governed = str(VAULT_ROOT / "Projects" / "O15-Fixture" / "work" / "o15-fixture.md")
    out_of_scope = str(VAULT_ROOT / "Notes" / "o15-fixture-scratch.md")
    return [
        ("violation", {"tool_name": "Write", "tool_input": {
            "file_path": governed,
            "content": "Utilize the API prior to commencing the export.\n"}}),
        ("clean", {"tool_name": "Write", "tool_input": {
            "file_path": governed,
            "content": "The guard fails open on internal error.\n"}}),
        ("out_of_scope", {"tool_name": "Write", "tool_input": {
            "file_path": out_of_scope,
            "content": "Utilize the API prior to commencing the export.\n"}}),
    ]


# -------------------------------------------------------------- assertions

def check_a(rules_path):
    p = Path(rules_path)
    if not p.is_file():
        return f"rules file missing: {p}"
    text = p.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    if fm is None:
        return "frontmatter block does not parse (no leading --- fence pair)"
    globs = extract_paths_globs(fm)
    if len(globs) != 4 or any(not g for g in globs):
        return f"paths: key must carry 4 non-empty globs, found {len(globs)}: {globs}"
    blocks = [b for b in re.split(r"(?=^### PL-)", body, flags=re.M)
              if b.startswith("### PL-")]
    if len(blocks) != 10:
        return f"expected exactly 10 '### PL-' blocks in body, found {len(blocks)}"
    for block in blocks:
        head = re.split(r"\n#{2,3} ", block)[0]
        if "**Provenance**:" not in head:
            return f"PL block without **Provenance**: line: {block.splitlines()[0]}"
    return None


def check_b(guard_path):
    p = Path(guard_path)
    if not p.is_file():
        return f"guard missing: {p}"
    src = p.read_text(encoding="utf-8")
    found = RULES_PATH_STRING_RE.findall(src)
    if not found:
        return "no plain-language rules-path string found in guard source"
    for s in found:
        norm = s.replace("\\", "/")
        if norm != NEW_RULES_REL:
            return f"guard names '{s}', not the new path {NEW_RULES_REL}"
        if not (VAULT_ROOT / norm).is_file():
            return f"guard rules path does not resolve on disk: {VAULT_ROOT / norm}"
    with tempfile.TemporaryDirectory() as td:
        agg = Path(td) / "o15-guard-fire.jsonl"
        for name, payload in fixture_payloads():
            code, stderr, records = run_guard_fixture(str(p), payload, agg)
            if code != 0:
                return f"harness [{name}]: exit {code}, expected 0"
            if name == "violation":
                if "PL-5" not in stderr or "WARN" not in stderr:
                    return f"harness [violation]: stderr lacks PL-5 WARN: {stderr!r}"
                if len(records) != 1:
                    return f"harness [violation]: {len(records)} records, expected 1"
                counts = records[0].get("per_rule_finding_counts", {})
                if sorted(counts.keys()) != sorted(PL_KEYS):
                    return f"harness [violation]: record lacks all ten PL keys: {sorted(counts)}"
                if counts.get("PL-5", 0) < 1:
                    return "harness [violation]: PL-5 count is zero in the record"
            elif name == "clean":
                if stderr:
                    return f"harness [clean]: unexpected stderr: {stderr!r}"
                if len(records) != 1:
                    return f"harness [clean]: {len(records)} records, expected 1"
                counts = records[0].get("per_rule_finding_counts", {})
                if sorted(counts.keys()) != sorted(PL_KEYS):
                    return f"harness [clean]: record lacks all ten PL keys: {sorted(counts)}"
                if records[0].get("total_findings") != 0:
                    return f"harness [clean]: total_findings {records[0].get('total_findings')}, expected 0"
            else:  # out_of_scope
                if stderr:
                    return f"harness [out_of_scope]: unexpected stderr: {stderr!r}"
                if records:
                    return f"harness [out_of_scope]: {len(records)} records, expected 0"
    return None


def check_c(old_rules_path):
    p = Path(old_rules_path)
    if not p.exists():
        return None  # removed outright: acceptable retirement form
    text = p.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) > 15:
        return f"loose file still {len(lines)} lines (>15): not the pointer form"
    if NEW_RULES_REL not in text:
        return f"pointer does not name the new path {NEW_RULES_REL}"
    if re.search(r"^### PL-", text, flags=re.M):
        return "pointer still contains '### PL-' rule blocks"
    return None


def check_d(registry_path):
    p = Path(registry_path)
    if not p.is_file():
        return f"registry missing: {p}"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return f"registry.json does not parse: {e}"
    skills = data.get("skills")
    if not isinstance(skills, dict) or "n8n-patterns" not in skills:
        return "no 'n8n-patterns' entry under skills in registry.json"
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="O15 migration check (assertions a-d)")
    ap.add_argument("--rules-path", default=str(VAULT_ROOT / NEW_RULES_REL))
    ap.add_argument("--old-rules-path", default=str(VAULT_ROOT / OLD_RULES_REL))
    ap.add_argument("--guard-path",
                    default=str(VAULT_ROOT / ".claude" / "hooks" / "plain-language-guard.py"))
    ap.add_argument("--registry-path", default=str(VAULT_ROOT / ".claude" / "registry.json"))
    ap.add_argument("--only", default="a,b,c,d",
                    help="comma list of assertion letters to run (default all)")
    args = ap.parse_args(argv)

    selected = [s.strip().lower() for s in args.only.split(",") if s.strip()]
    runners = {
        "a": lambda: check_a(args.rules_path),
        "b": lambda: check_b(args.guard_path),
        "c": lambda: check_c(args.old_rules_path),
        "d": lambda: check_d(args.registry_path),
    }
    first_failed = None
    for letter in ["a", "b", "c", "d"]:
        if letter not in selected:
            continue
        try:
            failure = runners[letter]()
        except Exception as e:  # boundary: a broken fixture must name itself
            failure = f"internal error while checking: {e!r}"
        if failure is None:
            print(f"({letter}) PASS")
        else:
            print(f"({letter}) FAIL: {failure}")
            if first_failed is None:
                first_failed = (letter, failure)
    if first_failed:
        print(f"FIRST-FAILED: ({first_failed[0]}) {first_failed[1]}")
        return 1
    print("O15 CHECK: all selected assertions passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
