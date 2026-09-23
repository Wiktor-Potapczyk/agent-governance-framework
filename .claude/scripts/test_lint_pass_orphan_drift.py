"""Tests for lint_pass_orphan_drift.py (ROAD-6, Pass R).

Declarative-first: written before the implementation, on a fixture
mini-vault encoding the historically bug-prone classes: archive-target
resolution (the 982-vs-99 class), memory-shape links, placeholder/relative
drops, valid-orphan class exclusion, and delta arithmetic across runs.
--root and --state-file overrides keep pytest away from live state.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_orphan_drift.py"
VAULT = SCRIPTS.parent.parent
REAL_SPEC = VAULT / "Projects" / "Vault-Maintenance" / "work" / "2026-05-11-target-structure-spec.md"

sys.path.insert(0, str(SCRIPTS))
import lint_pass_orphan_drift as _module  # noqa: E402


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def w(path, tags, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    tag_str = ", ".join(tags)
    path.write_text(
        f"---\ndate: 2026-01-01\ntags: [{tag_str}]\nstatus: active\n---\n\n{body}\n",
        encoding="utf-8",
    )


def make_vault(tmp_path):
    root = tmp_path / "vault"
    # raw layer: Projects/*/work/ + Notes/
    w(root / "Projects" / "P" / "STATE.md", ["task"], "See [[linked]].")
    w(root / "Projects" / "P" / "work" / "linked.md", ["task"], "Body.")           # inbound: STATE
    w(root / "Projects" / "P" / "work" / "orphan1.md", ["task"], "Body.")          # raw orphan
    # linker: no inbound -> raw orphan; its outbound links exercise resolution:
    # archive target, memory shape, placeholder, relative (last two dropped)
    w(root / "Projects" / "P" / "work" / "linker.md", ["task"],
      "See [[old-note]] and [[feedback_some_memory_note]] and [[<placeholder>]] and [[../rel/path]].")
    w(root / "Projects" / "P" / "work" / "backups" / "bk.md", ["task"], "Body.")   # excluded: backups
    w(root / "Notes" / "plain.md", ["task"], "See [[wiki-hub]].")                  # valid-orphan class: Notes w/o wiki
    w(root / "Notes" / "wiki-orphan.md", ["wiki"], "Body.")                        # raw orphan + wiki orphan
    w(root / "Notes" / "wiki-linked.md", ["wiki"], "Body.")                        # inbound from wiki-hub
    w(root / "Resources" / "KB" / "wiki-hub.md", ["wiki"], "See [[wiki-linked]].") # wiki orphan (inbound only non-wiki)
    # archived note: valid link TARGET; NOT a link source (its outbound must not count)
    w(root / "Archives" / "Old" / "old-note.md", ["task"], "See [[orphan1]].")
    return root


def test_counts_and_baseline_run(tmp_path):
    root = make_vault(tmp_path)
    state = tmp_path / "orphan-baseline.json"
    r = run("--root", str(root), "--state-file", str(state), "--spec", str(REAL_SPEC),
            "--memory-dir", str(tmp_path / "no-such-memory-dir"))
    assert r.returncode == 0, r.stdout + r.stderr
    lines = [l for l in r.stdout.splitlines() if l.startswith("ORPHAN_DRIFT")]
    assert len(lines) == 2
    raw = [l for l in lines if "layer=raw" in l][0]
    wiki = [l for l in lines if "layer=wiki" in l][0]
    # raw orphans: orphan1, linker, wiki-orphan (inbound from Archives does
    # NOT count: archived files are not link sources)
    assert "count=3" in raw and "prev=none" in raw and "delta=n/a" in raw
    assert "count=2" in wiki and "prev=none" in wiki
    # all resolvable shapes resolved: archive target + memory fallback shape;
    # placeholder and relative shapes dropped before counting
    assert "unresolved=0" in r.stdout
    stamp = json.loads(state.read_text(encoding="utf-8"))
    assert stamp["raw_count"] == 3 and stamp["wiki_count"] == 2


def test_delta_arithmetic_across_runs(tmp_path):
    root = make_vault(tmp_path)
    state = tmp_path / "orphan-baseline.json"
    run("--root", str(root), "--state-file", str(state), "--spec", str(REAL_SPEC),
        "--memory-dir", str(tmp_path / "none"))
    # unchanged vault: delta must be 0 for both layers, exit 0
    r2 = run("--root", str(root), "--state-file", str(state), "--spec", str(REAL_SPEC),
             "--memory-dir", str(tmp_path / "none"))
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "layer=raw count=3 prev=3 delta=0" in r2.stdout
    assert "layer=wiki count=2 prev=2 delta=0" in r2.stdout
    # add one new raw orphan: delta = count minus stamped prev = +1, exit 1
    w(root / "Projects" / "P" / "work" / "orphan2.md", ["task"], "Body.")
    r3 = run("--root", str(root), "--state-file", str(state), "--spec", str(REAL_SPEC),
             "--memory-dir", str(tmp_path / "none"))
    assert r3.returncode == 1
    assert "layer=raw count=4 prev=3 delta=+1" in r3.stdout
    stamp = json.loads(state.read_text(encoding="utf-8"))
    assert stamp["raw_count"] == 4


def test_memory_dir_resolution(tmp_path):
    # with a real memory dir present, only its actual filenames resolve
    root = make_vault(tmp_path)
    mem = tmp_path / "memory"
    mem.mkdir()
    (mem / "feedback_some_memory_note.md").write_text("x", encoding="utf-8")
    state = tmp_path / "orphan-baseline.json"
    r = run("--root", str(root), "--state-file", str(state), "--spec", str(REAL_SPEC),
            "--memory-dir", str(mem))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "unresolved=0" in r.stdout


def test_doctored_spec_exits_2(tmp_path):
    root = make_vault(tmp_path)
    doctored = tmp_path / "spec.md"
    doctored.write_text(
        REAL_SPEC.read_text(encoding="utf-8").replace("Valid-orphan classes", "Whitelist"),
        encoding="utf-8",
    )
    state = tmp_path / "orphan-baseline.json"
    r = run("--root", str(root), "--state-file", str(state), "--spec", str(doctored),
            "--memory-dir", str(tmp_path / "none"))
    assert r.returncode == 2
    assert not state.exists()


# --- TASK-034 (migration plan Phase 1, 2026-09-15): VAULT_MEMORY_ROOT override
# and mirror fallback -----------------------------------------------------------

def test_vault_memory_root_env_overrides_derivation(tmp_path):
    """VAULT_MEMORY_ROOT wins outright over the Path.home()-derived path when
    set, exercising derive_memory_dir() itself (no --memory-dir passed)."""
    root = make_vault(tmp_path)
    mem_root = tmp_path / "memroot"
    mem_root.mkdir()
    state = tmp_path / "orphan-baseline.json"
    env = dict(os.environ, VAULT_MEMORY_ROOT=str(mem_root), PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--state-file", str(state),
         "--spec", str(REAL_SPEC)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "DERIVATION FAILURE" not in r.stdout
    assert "ORPHAN_LINKS" in r.stdout


def test_vault_memory_root_falls_back_to_mirror_when_live_path_absent(tmp_path, monkeypatch):
    """VAULT_MEMORY_ROOT unset AND the live Path.home()-derived path absent:
    derive_memory_dir() falls back to the committed mirror directory
    .claude/user-claude-mirror/memory/ (mirror_user_claude.py's own DEST_REL,
    refreshed every 30 minutes by auto-commit.ps1)."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    monkeypatch.delenv("VAULT_MEMORY_ROOT", raising=False)
    mirror_dir = _module.VAULT / ".claude" / "user-claude-mirror" / "memory"
    assert mirror_dir.is_dir(), (
        "live mirror must exist on this machine for the fallback path to be exercised"
    )
    assert _module.derive_memory_dir() == mirror_dir


def test_cli_falls_back_to_mirror_end_to_end(tmp_path):
    """Same fallback, exercised through the real subprocess CLI (TASK-034's
    own CHECK): with VAULT_MEMORY_ROOT unset and USERPROFILE pointed at a
    fake, empty home, the script must still find the mirror and print a
    normal measurement line, never DERIVATION FAILURE."""
    root = make_vault(tmp_path)
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    state = tmp_path / "orphan-baseline.json"
    env = dict(os.environ, PYTHONIOENCODING="utf-8", USERPROFILE=str(fake_home),
              HOME=str(fake_home))
    env.pop("VAULT_MEMORY_ROOT", None)
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), "--state-file", str(state),
         "--spec", str(REAL_SPEC)],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert "DERIVATION FAILURE" not in r.stdout
    assert "ORPHAN_LINKS" in r.stdout
