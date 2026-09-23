"""Tests for status_normalize_sweep.py (TC-6 sweep, 2026-09-08).

Declarative-first: written before the implementation. Static fixture vault at
_test_fixtures/status_sweep/vault/ (byte-exact via .gitattributes `* -text`:
CRLF, BOM, and non-UTF8 fixtures must survive git). Every test copies the
fixture vault into tmp_path and runs the script there; the pristine fixtures
are never mutated. Uses the REAL spec and REAL hook source for derivations
(read-only), same convention as test_lint_pass_status_noncanon.py.

Fixture-vault expected census (kept in EXPECTED below):
  22 findings = 17 MAPPED + 4 UNMAPPED + 1 SKIP_DECODE.
  Not findings: canonical, quoted-canonical (F3), missing-status,
  bom-complete (frontmatter regex blind spot, symmetric with the lint),
  Archives/ (excluded scope).
"""
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "status_normalize_sweep.py"
LINT = SCRIPTS / "lint_pass_status_noncanon.py"
FIXTURE_VAULT = SCRIPTS / "_test_fixtures" / "status_sweep" / "vault"
VAULT = SCRIPTS.parent.parent
REAL_SPEC = VAULT / "Projects" / "Vault-Maintenance" / "work" / "2026-05-11-target-structure-spec.md"
REAL_HOOK = VAULT / ".claude" / "hooks" / "vault-structure-check.py"

EXPECTED_MAPPED = {
    "Notes/lf-hash-active.md": "active",
    "Notes/hash-done.md": "done",
    "Notes/quoted-hash-active.md": "active",
    "Notes/crlf-complete.md": "done",
    "Notes/alias-completed.md": "done",
    "Notes/alias-in-progress.md": "active",
    "Notes/alias-in-process.md": "active",
    "Notes/alias-wip.md": "active",
    "Notes/alias-ongoing.md": "active",
    "Notes/alias-on-hold.md": "waiting",
    "Notes/alias-on-hold-underscore.md": "waiting",
    "Notes/alias-paused.md": "waiting",
    "Notes/alias-blocked.md": "waiting",
    "Notes/alias-archive.md": "archived",
    "Notes/hash-complete.md": "done",       # F1: # strip composes with aliases
    "Notes/in-progress-space.md": "active",  # F2: separator unification
    "Notes/case-upper.md": "done",
}
EXPECTED_UNMAPPED = {
    "Notes/compound-a.md",
    "Notes/compound-b.md",
    "Notes/compound-c.md",
    "Notes/null-status.md",
}
EXPECTED_SKIP_DECODE = {"Notes/nonutf8.md"}
NEVER_IN_REPORT = {
    "Notes/good-canonical.md",
    "Notes/quoted-canonical.md",
    "Notes/missing-status.md",
    "Notes/bom-complete.md",
    "Archives/Old/legacy-wip.md",
}


def run_sweep(vault, report, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT),
         "--vault", str(vault), "--spec", str(REAL_SPEC),
         "--hook-source", str(REAL_HOOK), "--report", str(report), *extra],
        capture_output=True, text=True, encoding="utf-8",
    )


def run_lint(vault):
    return subprocess.run(
        [sys.executable, str(LINT),
         "--vault", str(vault), "--spec", str(REAL_SPEC),
         "--hook-source", str(REAL_HOOK)],
        capture_output=True, text=True, encoding="utf-8",
    )


def copy_vault(tmp_path):
    dst = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, dst)
    return dst


def tree_hashes(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*.md"))
    }


def parse_report(report):
    lines = report.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "path\traw_value\tdisposition"
    rows = {}
    for line in lines[1:]:
        path, raw, disp = line.split("\t")
        rows[path] = (raw, disp)
    return rows


def summary_of(stdout):
    for line in stdout.splitlines():
        if line.startswith("SWEEP "):
            return dict(kv.split("=", 1) for kv in line.split()[1:])
    raise AssertionError(f"no SWEEP summary line in: {stdout!r}")


def test_dry_run_dispositions_cover_the_ruled_table(tmp_path):
    root = copy_vault(tmp_path)
    report = tmp_path / "report.tsv"
    r = run_sweep(root, report)
    assert r.returncode == 0, r.stdout + r.stderr
    rows = parse_report(report)
    assert len(rows) == 22
    for path, target in EXPECTED_MAPPED.items():
        assert rows[path][1] == f"MAPPED->{target}", (path, rows[path])
    for path in EXPECTED_UNMAPPED:
        assert rows[path][1] == "UNMAPPED", (path, rows[path])
    for path in EXPECTED_SKIP_DECODE:
        assert rows[path][1] == "SKIP_DECODE", (path, rows[path])
    for path in NEVER_IN_REPORT:
        assert path not in rows, path
    s = summary_of(r.stdout)
    assert (s["mode"], s["total"], s["mapped"], s["unmapped"],
            s["skip_decode"], s["applied"]) == ("dry-run", "22", "17", "4", "1", "0")


def test_dry_run_report_raw_values_are_verbatim(tmp_path):
    root = copy_vault(tmp_path)
    report = tmp_path / "report.tsv"
    run_sweep(root, report)
    rows = parse_report(report)
    # raw value column carries the lint's parsed value (quote-stripped, verbatim)
    assert rows["Notes/hash-complete.md"][0] == "#complete"
    assert rows["Notes/in-progress-space.md"][0] == "In progress"
    assert rows["Notes/quoted-hash-active.md"][0] == "#active"
    assert rows["Notes/compound-a.md"][0] == "applied + verified"
    assert rows["Notes/null-status.md"][0] == "null"


def test_dry_run_writes_nothing(tmp_path):
    root = copy_vault(tmp_path)
    before = tree_hashes(root)
    r = run_sweep(root, tmp_path / "report.tsv")
    assert r.returncode == 0, r.stdout + r.stderr
    assert tree_hashes(root) == before


def test_apply_edits_exactly_the_status_line(tmp_path):
    root = copy_vault(tmp_path)
    target = root / "Notes" / "hash-complete.md"
    before_lines = target.read_bytes().split(b"\n")
    r = run_sweep(root, tmp_path / "report.tsv", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    after_lines = target.read_bytes().split(b"\n")
    assert len(before_lines) == len(after_lines)
    diff = [(a, b) for a, b in zip(before_lines, after_lines) if a != b]
    assert diff == [(b"status: #complete", b"status: done")]


def test_apply_quoted_value_becomes_bare_canonical(tmp_path):
    root = copy_vault(tmp_path)
    run_sweep(root, tmp_path / "report.tsv", "--apply")
    text = (root / "Notes" / "quoted-hash-active.md").read_text(encoding="utf-8")
    assert "status: active\n" in text
    assert '"' not in text.split("---")[1]


def test_apply_summary_and_untouched_files(tmp_path):
    root = copy_vault(tmp_path)
    before = tree_hashes(root)
    r = run_sweep(root, tmp_path / "report.tsv", "--apply")
    s = summary_of(r.stdout)
    assert (s["total"], s["mapped"], s["applied"]) == ("22", "17", "17")
    after = tree_hashes(root)
    changed = {p for p in before if before[p] != after[p]}
    assert changed == set(EXPECTED_MAPPED)
    # UNMAPPED, SKIP_DECODE, out-of-scope, blind-spot files: byte-identical
    for path in EXPECTED_UNMAPPED | EXPECTED_SKIP_DECODE | NEVER_IN_REPORT:
        assert before[path] == after[path], path


def test_crlf_lf_bom_round_trip(tmp_path):
    root = copy_vault(tmp_path)
    crlf = root / "Notes" / "crlf-complete.md"
    lf = root / "Notes" / "lf-hash-active.md"
    bom = root / "Notes" / "bom-complete.md"
    crlf_nl_before = crlf.read_bytes().count(b"\r\n")
    bom_before = bom.read_bytes()
    r = run_sweep(root, tmp_path / "report.tsv", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    crlf_bytes = crlf.read_bytes()
    # every newline still CRLF, none dropped, none added
    assert crlf_bytes.count(b"\r\n") == crlf_nl_before
    assert crlf_bytes.count(b"\n") == crlf_bytes.count(b"\r\n")
    assert b"status: done\r\n" in crlf_bytes
    lf_bytes = lf.read_bytes()
    assert b"\r" not in lf_bytes
    assert b"status: active\n" in lf_bytes
    # BOM file: invisible to the shared frontmatter regex, untouched entirely
    assert bom.read_bytes() == bom_before
    assert bom.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_apply_is_idempotent(tmp_path):
    root = copy_vault(tmp_path)
    run_sweep(root, tmp_path / "r1.tsv", "--apply")
    after_first = tree_hashes(root)
    r = run_sweep(root, tmp_path / "r2.tsv", "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    s = summary_of(r.stdout)
    assert (s["mapped"], s["applied"]) == ("0", "0")
    # residual findings remain enumerated, nothing more changes
    assert (s["total"], s["unmapped"], s["skip_decode"]) == ("5", "4", "1")
    assert tree_hashes(root) == after_first


def test_enumeration_consistent_with_lint_pass(tmp_path):
    root = copy_vault(tmp_path)
    lint_before = run_lint(root)
    findings_before = [l for l in lint_before.stdout.splitlines()
                       if l.startswith("STATUS_NONCANON")]
    report = tmp_path / "report.tsv"
    run_sweep(root, report)
    assert len(parse_report(report)) == len(findings_before) == 22
    run_sweep(root, report, "--apply")
    lint_after = run_lint(root)
    findings_after = [l for l in lint_after.stdout.splitlines()
                      if l.startswith("STATUS_NONCANON")]
    # residual = unmapped + skip_decode; every mapped file is now canonical
    assert len(findings_after) == 5
    residual_paths = {l.split("path=")[1].split(" value=")[0] for l in findings_after}
    assert residual_paths == EXPECTED_UNMAPPED | EXPECTED_SKIP_DECODE


def test_non_utf8_skip_decode_never_written(tmp_path):
    root = copy_vault(tmp_path)
    bad = root / "Notes" / "nonutf8.md"
    before = bad.read_bytes()
    report = tmp_path / "report.tsv"
    r = run_sweep(root, report, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    assert bad.read_bytes() == before
    assert parse_report(report)["Notes/nonutf8.md"][1] == "SKIP_DECODE"


def test_doctored_spec_exits_2_zero_writes(tmp_path):
    root = copy_vault(tmp_path)
    doctored = tmp_path / "spec.md"
    doctored.write_text(
        REAL_SPEC.read_text(encoding="utf-8").replace(
            "MUST be one of exactly 4 canonical values:", "values are listed elsewhere:"),
        encoding="utf-8",
    )
    before = tree_hashes(root)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(root),
         "--spec", str(doctored), "--hook-source", str(REAL_HOOK),
         "--report", str(tmp_path / "report.tsv"), "--apply"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert r.returncode == 2
    assert tree_hashes(root) == before


def test_apply_never_touches_a_blueprint_build_gate(tmp_path):
    """Regression, 2026-09-18: the sweep enumerated on its own and rewrote a
    live n8n blueprint's `#pending-flag-resolution` to `waiting`, the value the
    builder agent refuses on. The sweep must share the lint pass's exemption,
    in dry-run and in apply, and the two enumerations must stay equal."""
    root = tmp_path / "vault"
    work = root / "Projects" / "P" / "work"
    work.mkdir(parents=True)
    gate = work / "2026-01-01-blueprint-foo.md"
    ready = work / "2026-01-02-blueprint-bar.md"
    plain = work / "2026-01-03-plain.md"
    fm = "---" + chr(10) + "date: 2026-01-01" + chr(10) + "tags: [task]" + chr(10)
    tail = chr(10) + "---" + chr(10) + chr(10) + "# N" + chr(10)
    tw = chr(10) + "target_workflow: new"
    gate.write_bytes((fm + "status: #pending-flag-resolution" + tw + tail).encode("utf-8"))
    ready.write_bytes((fm + 'status: "#ready"' + tw + tail).encode("utf-8"))
    plain.write_bytes((fm + "status: draft" + tail).encode("utf-8"))
    before_gate, before_ready = gate.read_bytes(), ready.read_bytes()
    report = tmp_path / "r.tsv"
    dry = run_sweep(root, report)
    assert "total=1 " in dry.stdout, dry.stdout
    assert "blueprint" not in report.read_text(encoding="utf-8")
    ap = run_sweep(root, report, "--apply")
    assert "applied=1" in ap.stdout, ap.stdout
    assert gate.read_bytes() == before_gate and ready.read_bytes() == before_ready
    assert b"status: active" in plain.read_bytes()
    assert run_lint(root).returncode == 0
