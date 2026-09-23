"""Tests for lint_pass_status_noncanon.py (ROAD-5, Pass Q).

Declarative-first: written before the implementation. Fixture tree in tmp;
doctored spec copy for the fail-loud case. Uses the REAL spec and REAL
hook source for derivations (read-only) unless doctored.
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_status_noncanon.py"
VAULT = SCRIPTS.parent.parent
REAL_SPEC = VAULT / "Projects" / "Vault-Maintenance" / "work" / "2026-05-11-target-structure-spec.md"
REAL_HOOK = VAULT / ".claude" / "hooks" / "vault-structure-check.py"


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def note(status_line):
    fm = "---\ndate: 2026-01-01\ntags: [task]\n"
    if status_line is not None:
        fm += status_line + "\n"
    return fm + "---\n\n# Note\n"


def make_tree(tmp_path):
    root = tmp_path / "vault"
    (root / "Notes").mkdir(parents=True)
    (root / "Projects" / "P" / "work").mkdir(parents=True)
    (root / "Archives" / "Old").mkdir(parents=True)
    (root / "Notes" / "good.md").write_text(note("status: active"), encoding="utf-8")
    (root / "Notes" / "bad.md").write_text(note("status: wip"), encoding="utf-8")
    (root / "Notes" / "quoted-bad.md").write_text(note('status: "#active"'), encoding="utf-8")
    (root / "Notes" / "missing.md").write_text(note(None), encoding="utf-8")
    # excluded dir: non-canonical value here must NOT be a finding
    (root / "Archives" / "Old" / "legacy.md").write_text(note("status: frozen"), encoding="utf-8")
    (root / "Projects" / "P" / "work" / "ok.md").write_text(note("status: done"), encoding="utf-8")
    return root


def test_findings_and_scope(tmp_path):
    root = make_tree(tmp_path)
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(REAL_HOOK))
    assert r.returncode == 1, r.stdout + r.stderr
    findings = [l for l in r.stdout.splitlines() if l.startswith("STATUS_NONCANON")]
    assert len(findings) == 2
    assert any("bad.md" in f and "value=wip" in f for f in findings)
    assert any("quoted-bad.md" in f and "value=#active" in f for f in findings)
    assert not any("legacy.md" in f for f in findings)  # Archives excluded
    assert not any("missing.md" in f for f in findings)  # missing status: not a finding
    assert "scanned=" in r.stdout  # always-print


def test_all_canonical_clean(tmp_path):
    root = tmp_path / "vault"
    (root / "Notes").mkdir(parents=True)
    (root / "Notes" / "a.md").write_text(note("status: waiting"), encoding="utf-8")
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(REAL_HOOK))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STATUS_NONCANON" not in r.stdout


def test_doctored_spec_exits_2(tmp_path):
    root = tmp_path / "vault"
    (root / "Notes").mkdir(parents=True)
    doctored = tmp_path / "spec.md"
    doctored.write_text(
        REAL_SPEC.read_text(encoding="utf-8").replace(
            "MUST be one of exactly 4 canonical values:", "values are listed elsewhere:"),
        encoding="utf-8",
    )
    r = run("--vault", str(root), "--spec", str(doctored), "--hook-source", str(REAL_HOOK))
    assert r.returncode == 2
    assert "STATUS_NONCANON" not in r.stdout


def test_doctored_hook_source_exits_2(tmp_path):
    root = tmp_path / "vault"
    (root / "Notes").mkdir(parents=True)
    doctored = tmp_path / "hook.py"
    doctored.write_text(
        REAL_HOOK.read_text(encoding="utf-8").replace("INCLUDE_PREFIXES", "INCL_PREFIXES"),
        encoding="utf-8",
    )
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(doctored))
    assert r.returncode == 2


# --- gitignored-scope correction (2026-09-09) ---------------------------------
# TC-6 was red at 279 findings, 202 of which were files git does not track
# (gitignored scratch under work/backups/). A contract asserting the CURRENT
# vault is trustworthy must not score deliberately-excluded content. These
# tests pin the rule and, critically, pin that it can still FAIL.

def git_init(root):
    for args in (("init", "-q"), ("config", "user.email", "t@example.invalid"),
                 ("config", "user.name", "T")):
        subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)


def test_gitignored_note_is_not_a_finding(tmp_path):
    """The rule itself: an ignored file with a bad status is out of scope."""
    root = make_tree(tmp_path)
    git_init(root)
    (root / ".gitignore").write_text("Notes/ignored.md\n", encoding="utf-8")
    (root / "Notes" / "ignored.md").write_text(note("status: junk"), encoding="utf-8")
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(REAL_HOOK))
    findings = [l for l in r.stdout.splitlines() if l.startswith("STATUS_NONCANON")]
    assert not any("ignored.md" in f for f in findings), r.stdout
    assert "skipped_gitignored=1" in r.stdout, r.stdout


def test_tracked_note_with_bad_status_still_fails(tmp_path):
    """Mutation guard: the exclusion must not disarm the pass. The same file,
    NOT ignored, must still be found. Without this, a bug that excluded
    everything would look identical to a clean vault."""
    root = make_tree(tmp_path)
    git_init(root)
    (root / ".gitignore").write_text("nothing-matches-this\n", encoding="utf-8")
    (root / "Notes" / "ignored.md").write_text(note("status: junk"), encoding="utf-8")
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(REAL_HOOK))
    findings = [l for l in r.stdout.splitlines() if l.startswith("STATUS_NONCANON")]
    assert any("ignored.md" in f and "value=junk" in f for f in findings), r.stdout
    assert "skipped_gitignored=0" in r.stdout, r.stdout


def test_non_git_directory_scans_normally(tmp_path):
    """A tree that is not a repository has no ignore rules, so the pass must
    run normally rather than treating it as a derivation failure. Every test
    fixture and any scratch copy hits this path."""
    root = make_tree(tmp_path)  # deliberately NOT git_init'ed
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(REAL_HOOK))
    assert r.returncode == 1, r.stdout + r.stderr
    assert "skipped_gitignored=0" in r.stdout, r.stdout


def test_blueprint_gate_status_is_exempt_and_counted(tmp_path):
    """An n8n blueprint's `#ready` / `#pending-flag-resolution` status is a
    build gate two agent definitions branch on (n8n-workflow-builder refuses
    on the pending value). Normalising it would open that gate, so the pass
    exempts exactly those values on blueprint files, and says so in the
    measurement line. Anything else stays a finding."""
    root = make_tree(tmp_path)
    work = root / "Projects" / "P" / "work"
    tw = chr(10) + "target_workflow: new"
    (work / "2026-01-01-blueprint-foo.md").write_text(note("status: #pending-flag-resolution" + tw), encoding="utf-8")
    (work / "2026-01-02-blueprint-bar.md").write_text(note('status: "#ready"' + tw), encoding="utf-8")
    # Named like a blueprint but not an n8n-workflow-architect blueprint: no
    # target_workflow key, so its gate-shaped status stays a finding.
    (work / "2026-01-05-blueprint-remediation-notes.md").write_text(note("status: #ready"), encoding="utf-8")
    (work / "2026-01-03-blueprint-baz.md").write_text(note("status: wip"), encoding="utf-8")
    (work / "2026-01-04-plain-note.md").write_text(note("status: #pending-flag-resolution"), encoding="utf-8")
    r = run("--vault", str(root), "--spec", str(REAL_SPEC), "--hook-source", str(REAL_HOOK))
    findings = [l for l in r.stdout.splitlines() if l.startswith("STATUS_NONCANON")]
    assert not any("blueprint-foo" in f or "blueprint-bar" in f for f in findings), r.stdout
    assert any("blueprint-baz" in f and "value=wip" in f for f in findings), r.stdout
    assert any("plain-note" in f for f in findings), r.stdout
    assert any("blueprint-remediation-notes" in f for f in findings), r.stdout
    assert "exempt_blueprint_gate=2" in r.stdout, r.stdout
