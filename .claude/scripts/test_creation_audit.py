"""Tests for creation_audit.py (ROAD-12, 2026-09-08).

Declarative-first: written before the implementation. Every stateful path
is overridden per run (tmp scratch repo, tmp allowlist, tmp spec, tmp out
path); no test reads or writes live vault state. Subprocess runs go through
sys.executable with PYTHONIOENCODING=utf-8 per the house idiom; the
scripts-suite conftest already isolates the two live observability sinks.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "creation_audit.py"
sys.path.insert(0, str(SCRIPTS))

# The live spec heading uses an em dash; the glyph is built via chr() so it
# never appears in this file's bytes (dash-hygiene constraint 6).
EM = chr(0x2014)

R2_SPEC = (
    "# Fixture spec\n"
    "\n"
    "| Layer | Locations | Owner |\n"
    "|---|---|---|\n"
    "| raw | Inbox/ | W |\n"
    "\n"
    "## R2 " + EM + " Directory Rules\n"
    "\n"
    "| Directory | Layer | Phase-5 action |\n"
    "|---|---|---|\n"
    "| Inbox/ | raw | Keep. |\n"
    "| Projects/X/ (root) | raw + wiki | Stuff. |\n"
    "| Projects/X/source-data/ | raw | Valid orphans. |\n"
    "| Resources/ (non-KB) | raw | Reference. |\n"
    "| Resources/KB/ | wiki | Wiki home. |\n"
    "| Archives/loose/ | raw | Catch-all. |\n"
    "| .claude/ | schema | Excluded. |\n"
    "\n"
    "## R3\n"
)

CAVEAT = ("git history cannot see files created and deleted between "
          "autosave sweeps, so counts are lower bounds, never exact.")


def run(*args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env,
    )


def make_allowlist(tmp_path, entries):
    p = tmp_path / "allowlist.json"
    p.write_text(json.dumps({
        "generated_iso": "2026-09-08T00:00:00Z", "entries": entries,
    }), encoding="utf-8")
    return p


def make_spec(tmp_path, text=R2_SPEC):
    p = tmp_path / "spec.md"
    p.write_text(text, encoding="utf-8")
    return p


def make_repo(tmp_path, commits):
    """commits: ordered list of (iso_date, added_relpaths, removed_relpaths)."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*a, date=None):
        env = {**os.environ}
        if date:
            env["GIT_AUTHOR_DATE"] = date
            env["GIT_COMMITTER_DATE"] = date
        r = subprocess.run(
            ["git", "-C", str(repo), *a],
            capture_output=True, text=True, encoding="utf-8", env=env,
        )
        assert r.returncode == 0, r.stdout + r.stderr
        return r

    git("init", "-q")
    git("config", "user.email", "fixture@example.com")
    git("config", "user.name", "fixture")
    for date, adds, removes in commits:
        for rel in adds:
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        for rel in removes:
            (repo / rel).unlink()
        git("add", "-A")
        git("commit", "-q", "-m", "fixture", date=date)
    return repo


def common_args(repo, allow, spec, out):
    return ("--since", "2026-07-10", "--until", "2026-09-08",
            "--root", str(repo), "--allowlist", str(allow),
            "--spec", str(spec), "--out", str(out))


# Test 1: bare-date normalization (D1)

def test_bare_date_normalization_printed(tmp_path):
    repo = make_repo(tmp_path, [("2026-07-15T10:00:00", ["Projects/a.md"], [])])
    allow = make_allowlist(tmp_path, ["Projects"])
    spec = make_spec(tmp_path)
    r = run(*common_args(repo, allow, spec, tmp_path / "report.md"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "resolved window: 2026-07-10T00:00:00 .. 2026-09-08T00:00:00" in r.stdout


def test_normalize_window_pure():
    import creation_audit as ca
    assert ca.normalize_window("2026-07-10") == "2026-07-10T00:00:00"
    assert ca.normalize_window("2026-07-10T05:06:07") == "2026-07-10T05:06:07"


# Test 2: git-log fixture parsing (D2), unicode path included

def test_git_log_fixture_parsing():
    import creation_audit as ca
    fixture = (
        "@@aaa1111\t2026-07-11T10:00:00+02:00\n"
        "\n"
        "Projects/one.md\n"
        "Notes/zażółć file.md\n"
        "\n"
        "@@bbb2222\t2026-07-12T09:30:00+02:00\n"
        "\n"
        "stray.txt\n"
    )
    records = ca.parse_git_log(fixture)
    assert records == [
        ("Projects/one.md", "aaa1111", "2026-07-11T10:00:00+02:00"),
        ("Notes/zażółć file.md", "aaa1111",
         "2026-07-11T10:00:00+02:00"),
        ("stray.txt", "bbb2222", "2026-07-12T09:30:00+02:00"),
    ]


# Test 3: classification rules (D3)

def test_classification_rules():
    import creation_audit as ca
    allow = {"CLAUDE.md", "Projects", "Notes"}
    r2 = {"Projects", "Notes"}
    assert ca.classify("CLAUDE.md", allow, r2) == ("expected", ca.OUTSIDE_R2)
    assert ca.classify("Projects/X/work/a.md", allow, r2) == ("expected", "Projects")
    assert ca.classify("stray.txt", allow, r2) == ("stray", None)
    assert ca.classify("NewTopDir/deep/file.md", allow, r2) == ("stray", None)


# Test 4: R2 parse and normalization (D3); zero rows is a derivation failure

def test_r2_parse_normalization():
    import creation_audit as ca
    rows, prefixes = ca.parse_r2_prefixes(R2_SPEC)
    assert rows == 7
    assert prefixes == [".claude", "Archives", "Inbox", "Projects", "Resources"]


def test_r2_zero_rows_exits_2(tmp_path):
    allow = make_allowlist(tmp_path, ["Projects"])
    spec = make_spec(tmp_path, "# No R2 table anywhere in this file\n")
    r = run(*common_args(tmp_path, allow, spec, tmp_path / "r.md"))
    assert r.returncode == 2
    assert "DERIVATION FAILURE" in r.stdout


# Test 5: unique-vs-event counting (D4)

def test_unique_vs_event_counting(tmp_path):
    repo = make_repo(tmp_path, [
        ("2026-07-15T10:00:00", ["Projects/twice.md"], []),
        ("2026-07-16T10:00:00", [], ["Projects/twice.md"]),
        ("2026-07-17T10:00:00", ["Projects/twice.md"], []),
    ])
    allow = make_allowlist(tmp_path, ["Projects"])
    spec = make_spec(tmp_path)
    r = run(*common_args(repo, allow, spec, tmp_path / "r.md"))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "added unique=1 events=2" in r.stdout


# Test 6: missing inputs exit 2 with a DERIVATION FAILURE line (D6)

def test_missing_allowlist_exits_2(tmp_path):
    spec = make_spec(tmp_path)
    r = run(*common_args(tmp_path, tmp_path / "absent.json", spec,
                         tmp_path / "r.md"))
    assert r.returncode == 2
    assert "DERIVATION FAILURE" in r.stdout


def test_missing_spec_exits_2(tmp_path):
    allow = make_allowlist(tmp_path, ["Projects"])
    r = run(*common_args(tmp_path, allow, tmp_path / "absent.md",
                         tmp_path / "r.md"))
    assert r.returncode == 2
    assert "DERIVATION FAILURE" in r.stdout


# Test 7: report writing (D5)

def test_report_contents(tmp_path):
    repo = make_repo(tmp_path, [
        ("2026-07-15T10:00:00", ["Projects/in.md"], []),
        ("2026-07-16T10:00:00", ["Weird/stray.md"], []),
    ])
    allow = make_allowlist(tmp_path, ["Projects", "Notes", "CLAUDE.md"])
    spec = make_spec(tmp_path)
    out = tmp_path / "report.md"
    r = run(*common_args(repo, allow, spec, out))
    assert r.returncode == 0, r.stdout + r.stderr
    text = out.read_text(encoding="utf-8")
    assert text.startswith("---\ndate: ")
    assert "tags: [project/vault-maintenance, analysis, audit]" in text
    assert CAVEAT in text
    assert "unique paths" in text
    assert "add events" in text
    assert "Weird/stray.md" in text


# Test 8: end-to-end determinism on a real scratch repo (top-level CHECK shape)

def test_two_run_determinism(tmp_path):
    repo = make_repo(tmp_path, [
        ("2026-07-15T10:00:00", ["Projects/in-window.md"], []),
        ("2026-07-16T10:00:00", ["Weird/stray.md"], []),
        ("2026-10-01T10:00:00", ["Projects/outside.md"], []),
    ])
    allow = make_allowlist(tmp_path, ["Projects", "Notes", "CLAUDE.md"])
    spec = make_spec(tmp_path)
    out1 = tmp_path / "run1.md"
    out2 = tmp_path / "run2.md"
    r1 = run(*common_args(repo, allow, spec, out1))
    r2 = run(*common_args(repo, allow, spec, out2))
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert r2.returncode == 0, r2.stdout + r2.stderr

    def measurement_lines(res):
        return [line for line in res.stdout.splitlines()
                if not line.startswith("report written:")]

    assert measurement_lines(r1) == measurement_lines(r2)
    assert "added unique=2 events=2" in r1.stdout
    assert "stray unique=1" in r1.stdout
    assert out1.read_bytes() == out2.read_bytes()
    text = out1.read_text(encoding="utf-8")
    assert "Weird/stray.md" in text
    assert "Projects/outside.md" not in text
