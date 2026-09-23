"""Tests for trust_contract_verify.py (ROAD-13).

Declarative-first: written before the implementation. Every invocation
passes --ledger, --registry, and --baseline overrides (plus --report with
fixture frontmatter or --live with --scripts-dir stubs), so no test ever
touches the live ledger, registry, baseline, or any vault file.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "trust_contract_verify.py"

PASS_SCRIPT_NAMES = [
    "lint_pass_root_stray.py",
    "lint_pass_memory_overfill.py",
    "lint_pass_kb_index_budget.py",
    "lint_pass_work_index_stale.py",
    "lint_pass_orphan_drift.py",
    "lint_pass_tag_canon_divergence.py",
    "lint_pass_status_noncanon.py",
    "lint_pass_enforcement_claims.py",
]

# All-green pass output blocks, keyed by finding code, in the real grammars
# (catalogued from the eight lint_pass_* module sources; see the ROAD-13
# build record grammar table).
GREEN_BLOCKS = {
    "ROOT_STRAY": "ROOT entries=20 allowlisted=20 strays=0",
    "MEMORY_OVERFILL": "MEMORY bytes=15000 target=17100 long_lines=0  (fixture)",
    "KB_INDEX_BUDGET": (
        "KB_INDEX bytes=5000 budget=7500 entries=40 entry_budget=60"
    ),
    "WORK_INDEX_STALE": "WORK_INDEX project=Vault-Maintenance stamped=3 live=3",
    "ORPHAN_DRIFT": (
        "ORPHAN_LINKS total=100 dropped=0 unresolved=0 notes=50\n"
        "ORPHAN_DRIFT  layer=raw count=167 prev=167 delta=0\n"
        "ORPHAN_DRIFT  layer=wiki count=27 prev=27 delta=0"
    ),
    "TAG_CANON_DIVERGENCE": (
        "TAG_CANON sizes tag-variant-check=30 vault-structure-check=30 "
        "claude-md=30 divergent=0"
    ),
    "STATUS_NONCANON": "STATUS scanned=650 noncanonical=0",
    "ENFORCEMENT_CLAIM_STALE": "ENFORCEMENT_CLAIMS claims=4 ok=4 stale=0",
}

MEMORY_RED_BLOCK = (
    "MEMORY bytes=24000 target=17100 long_lines=2  (fixture)\n"
    "MEMORY_OVERFILL  bytes=24000 target=17100 long_lines=2"
)


def make_report(path, date, blocks=None, omit=(), replace=None):
    """Write a fixture lint report with pass outputs in fenced blocks."""
    blocks = dict(blocks or GREEN_BLOCKS)
    for code in omit:
        blocks.pop(code, None)
    for code, text in (replace or {}).items():
        blocks[code] = text
    body = "\n".join(
        "```\n" + text + "\n```\n" for text in blocks.values()
    )
    path.write_text(
        "---\n"
        f"date: {date}\n"
        "tags: [lint-report]\n"
        "status: active\n"
        "---\n\n"
        "# Fixture lint report\n\n"
        "## Pass outputs (trust-contract input)\n\n" + body,
        encoding="utf-8",
    )
    return path


def make_registry(path, n_claims=4):
    payload = {
        "schema": 1,
        "generated_iso": "2026-09-08T00:00:00Z",
        "claims": [{"id": f"c{i}"} for i in range(n_claims)],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def make_baseline(path, last_iso):
    payload = {"last_iso": last_iso, "raw_count": 1, "wiki_count": 1}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def paths(tmp_path):
    return {
        "ledger": tmp_path / "ledger.jsonl",
        "registry": make_registry(tmp_path / "registry.json"),
        "baseline": make_baseline(tmp_path / "baseline.json",
                                  "2026-09-08T00:00:00Z"),
    }


def run(p, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--ledger", str(p["ledger"]),
         "--registry", str(p["registry"]),
         "--baseline", str(p["baseline"]),
         *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def ledger_rows(p):
    if not p["ledger"].exists():
        return []
    lines = p["ledger"].read_text(encoding="utf-8").splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def tc_line(stdout, tc):
    hits = [l for l in stdout.splitlines() if l.startswith(tc + " ")]
    assert len(hits) == 1, f"expected one {tc} line in:\n{stdout}"
    return hits[0]


# 1. All-green fixture report: seven PASS lines, exit 0, one row, streaks 1.
def test_all_green_report(tmp_path):
    p = paths(tmp_path)
    rep = make_report(tmp_path / "rep.md", "2026-09-08")
    r = run(p, "--report", str(rep))
    assert r.returncode == 0, r.stdout + r.stderr
    for i in range(1, 8):
        assert tc_line(r.stdout, f"TC-{i}") == f"TC-{i} PASS streak=1"
    assert "CONTRACT PASS streak=1" in r.stdout
    rows = ledger_rows(p)
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == f"report:{rep}"
    for i in range(1, 8):
        assert row["objectives"][f"TC-{i}"] == {"result": "PASS", "streak": 1}
    assert row["contract"] == {"result": "PASS", "streak": 1}


# 2. TC-2 red: FAIL printed, exit 1, row appended, TC-2 streak 0, others 1.
def test_tc2_red_memory_overfill(tmp_path):
    p = paths(tmp_path)
    rep = make_report(tmp_path / "rep.md", "2026-09-08",
                      replace={"MEMORY_OVERFILL": MEMORY_RED_BLOCK})
    r = run(p, "--report", str(rep))
    assert r.returncode == 1
    assert tc_line(r.stdout, "TC-2").startswith("TC-2 FAIL streak=0")
    for i in (1, 3, 4, 5, 6, 7):
        assert tc_line(r.stdout, f"TC-{i}").startswith(f"TC-{i} PASS streak=1")
    rows = ledger_rows(p)
    assert len(rows) == 1
    assert rows[0]["objectives"]["TC-2"]["streak"] == 0
    assert rows[0]["contract"]["result"] == "FAIL"
    assert rows[0]["codes"]["MEMORY_OVERFILL"] == 1


# 3. TC-7 partial-run fail: one section missing entirely.
def test_tc7_missing_section(tmp_path):
    p = paths(tmp_path)
    rep = make_report(tmp_path / "rep.md", "2026-09-08",
                      omit=("STATUS_NONCANON",))
    r = run(p, "--report", str(rep))
    assert r.returncode == 1
    line7 = tc_line(r.stdout, "TC-7")
    assert line7.startswith("TC-7 FAIL streak=0")
    assert "STATUS_NONCANON" in line7  # missing section named
    assert tc_line(r.stdout, "TC-6").startswith("TC-6 FAIL streak=0")
    rows = ledger_rows(p)
    assert len(rows) == 1
    assert rows[0]["codes"]["STATUS_NONCANON"] is None


# 4. DERIVATION FAILURE in one section: section invalid, same outcome class.
def test_derivation_failure_section_invalid(tmp_path):
    p = paths(tmp_path)
    bad = ("DERIVATION FAILURE: cannot read spec fixture\n"
           + GREEN_BLOCKS["STATUS_NONCANON"])
    rep = make_report(tmp_path / "rep.md", "2026-09-08",
                      replace={"STATUS_NONCANON": bad})
    r = run(p, "--report", str(rep))
    assert r.returncode == 1
    assert tc_line(r.stdout, "TC-7").startswith("TC-7 FAIL streak=0")
    assert tc_line(r.stdout, "TC-6").startswith("TC-6 FAIL streak=0")
    assert len(ledger_rows(p)) == 1  # row IS appended (measured red)


# 5. Streak accumulation: four cycles 7 days apart reach streak 4 and GREEN.
def test_streak_reaches_green_at_4(tmp_path):
    p = paths(tmp_path)
    dates = ["2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"]
    for i, d in enumerate(dates):
        make_baseline(p["baseline"], f"{d}T00:00:00Z")
        rep = make_report(tmp_path / f"rep{i}.md", d)
        r = run(p, "--report", str(rep))
        assert r.returncode == 0, r.stdout + r.stderr
    assert tc_line(r.stdout, "TC-1") == "TC-1 PASS streak=4 GREEN"
    assert "CONTRACT PASS streak=4 GREEN" in r.stdout
    rows = ledger_rows(p)
    assert len(rows) == 4
    assert rows[-1]["contract"] == {"result": "PASS", "streak": 4}


# 6. Reset-on-missed-cycle: 9-day gap resets, green cycle restarts at 1.
def test_reset_on_missed_cycle(tmp_path):
    p = paths(tmp_path)
    dates = ["2026-09-08", "2026-09-15", "2026-09-24"]  # 9-day third gap
    for i, d in enumerate(dates):
        make_baseline(p["baseline"], f"{d}T00:00:00Z")
        rep = make_report(tmp_path / f"rep{i}.md", d)
        r = run(p, "--report", str(rep))
        assert r.returncode == 0, r.stdout + r.stderr
    assert tc_line(r.stdout, "TC-1") == "TC-1 PASS streak=1"
    assert "CONTRACT PASS streak=1" in r.stdout
    rows = ledger_rows(p)
    assert rows[1]["contract"]["streak"] == 2
    assert rows[2]["contract"]["streak"] == 1


# 7. Exactly-one-row dedupe: same report twice, second run appends nothing.
def test_dedupe_same_cycle(tmp_path):
    """One row per cycle, and the LAST run of the cycle is the one kept
    (ruled 2026-09-09; was: the first run won permanently)."""
    p = paths(tmp_path)
    rep = make_report(tmp_path / "rep.md", "2026-09-08")
    r1 = run(p, "--report", str(rep))
    assert r1.returncode == 0
    r2 = run(p, "--report", str(rep))
    assert r2.returncode == 0
    assert "superseded" in r2.stdout, r2.stdout
    assert len(ledger_rows(p)) == 1


def test_same_cycle_rerun_does_not_inflate_streak(tmp_path):
    """Re-running inside one cycle must not walk the streak up. Streaks are
    computed against the last row of a DIFFERENT cycle."""
    p = paths(tmp_path)
    rep = make_report(tmp_path / "rep.md", "2026-09-08")
    for _ in range(3):
        assert run(p, "--report", str(rep)).returncode == 0
    rows = ledger_rows(p)
    assert len(rows) == 1, rows
    assert rows[0]["contract"]["streak"] == 1, rows[0]["contract"]


def test_later_run_supersedes_an_earlier_failure(tmp_path):
    """The point of the ruling: a cycle that starts red and is then fixed must
    record the fix, not the failure it opened with."""
    p = paths(tmp_path)
    # Same report path re-measured, which is what a remediation day looks like:
    # the cycle opens red, the problem is fixed, the pass is re-run.
    rep = tmp_path / "rep.md"
    make_report(rep, "2026-09-08",
                replace={"ROOT_STRAY":
                         "ROOT entries=21 allowlisted=20 strays=1\n"
                         "ROOT_STRAY  path=stray.md"})
    assert run(p, "--report", str(rep)).returncode == 1
    assert ledger_rows(p)[-1]["contract"]["result"] == "FAIL"
    make_report(rep, "2026-09-08")
    assert run(p, "--report", str(rep)).returncode == 0
    rows = ledger_rows(p)
    assert len(rows) == 1, rows
    assert rows[-1]["contract"]["result"] == "PASS", rows[-1]["contract"]


# 8. Missing registry: exit 2, ledger untouched.
def test_missing_registry_exit_2_no_write(tmp_path):
    p = paths(tmp_path)
    p["registry"] = tmp_path / "absent-registry.json"
    rep = make_report(tmp_path / "rep.md", "2026-09-08")
    r = run(p, "--report", str(rep))
    assert r.returncode == 2
    assert not p["ledger"].exists()


# 9. Empty registry: TC-3 FAIL even with zero stale claims (vacuous-green).
def test_empty_registry_fails_tc3(tmp_path):
    p = paths(tmp_path)
    make_registry(p["registry"], n_claims=0)
    rep = make_report(
        tmp_path / "rep.md", "2026-09-08",
        replace={"ENFORCEMENT_CLAIM_STALE":
                 "ENFORCEMENT_CLAIMS claims=0 ok=0 stale=0"})
    r = run(p, "--report", str(rep))
    assert r.returncode == 1
    assert tc_line(r.stdout, "TC-3").startswith("TC-3 FAIL streak=0")
    assert len(ledger_rows(p)) == 1


# 10. Stale orphan baseline (8 days older than cycle): TC-4 FAIL.
def test_stale_baseline_fails_tc4(tmp_path):
    p = paths(tmp_path)
    make_baseline(p["baseline"], "2026-08-31T00:00:00Z")  # 8 days before
    rep = make_report(tmp_path / "rep.md", "2026-09-08")
    r = run(p, "--report", str(rep))
    assert r.returncode == 1
    assert tc_line(r.stdout, "TC-4").startswith("TC-4 FAIL streak=0")


# 11. Unreadable report path: exit 2, no ledger write.
def test_unreadable_report_exit_2(tmp_path):
    p = paths(tmp_path)
    r = run(p, "--report", str(tmp_path / "absent-report.md"))
    assert r.returncode == 2
    assert not p["ledger"].exists()


# 12. Corrupt ledger line: exit 2, no append.
def test_corrupt_ledger_exit_2(tmp_path):
    p = paths(tmp_path)
    rep = make_report(tmp_path / "rep.md", "2026-09-08")
    r1 = run(p, "--report", str(rep))
    assert r1.returncode == 0
    before = p["ledger"].read_text(encoding="utf-8")
    p["ledger"].write_text(before + "not json\n", encoding="utf-8")
    corrupted = p["ledger"].read_text(encoding="utf-8")
    rep2 = make_report(tmp_path / "rep2.md", "2026-09-15")
    r2 = run(p, "--report", str(rep2))
    assert r2.returncode == 2
    assert p["ledger"].read_text(encoding="utf-8") == corrupted


# 13. Live mode smoke via stub pass scripts: source recorded as "live".
def test_live_mode_stub_scripts(tmp_path):
    p = paths(tmp_path)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    code_by_script = dict(zip(PASS_SCRIPT_NAMES, [
        "ROOT_STRAY", "MEMORY_OVERFILL", "KB_INDEX_BUDGET",
        "WORK_INDEX_STALE", "ORPHAN_DRIFT", "TAG_CANON_DIVERGENCE",
        "STATUS_NONCANON", "ENFORCEMENT_CLAIM_STALE"]))
    for name, code in code_by_script.items():
        block = GREEN_BLOCKS[code]
        (stubs / name).write_text(
            "print(" + json.dumps(block) + ")\n", encoding="utf-8")
    r = run(p, "--live", "--scripts-dir", str(stubs),
            "--now", "2026-09-08T12:00:00Z")
    assert r.returncode == 0, r.stdout + r.stderr
    for i in range(1, 8):
        assert tc_line(r.stdout, f"TC-{i}").startswith(f"TC-{i} PASS")
    rows = ledger_rows(p)
    assert len(rows) == 1
    assert rows[0]["source"] == "live"
    assert rows[0]["cycle_iso"] == "2026-09-08T12:00:00Z"
