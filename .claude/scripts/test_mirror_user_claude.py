"""Tests for mirror_user_claude.py.

Declarative-first. The load-bearing test is the secrets exclusion: a mirror
that quietly carried credentials into git would be worse than no mirror, so it
is asserted twice (source-side skip and destination-side sweep) and pinned here
against a fixture that deliberately plants a secret to be excluded.
"""
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    "mirror_user_claude", SCRIPTS / "mirror_user_claude.py")
mirror = importlib.util.module_from_spec(_spec)
sys.modules["mirror_user_claude"] = mirror
_spec.loader.exec_module(mirror)

VAULT_ID = "test-vault-id"


def make_user_claude(tmp_path, with_secret=True):
    uc = tmp_path / "dotclaude"
    mem = uc / "projects" / VAULT_ID / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("# index\n- a > b\n", encoding="utf-8")
    (mem / "finding_x.md").write_text("finding body\n", encoding="utf-8")
    (uc / "skills").mkdir()
    (uc / "skills" / "s.md").write_text("skill\n", encoding="utf-8")
    (uc / "settings.json").write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    (uc / "settings.local.json").write_text("{}", encoding="utf-8")
    if with_secret:
        sec = uc / "projects" / VAULT_ID / "secrets"
        sec.mkdir(parents=True)
        (sec / "github-pat.txt").write_text("ghp_TOTALLY_FAKE\n", encoding="utf-8")
    return uc


def run(uc, dest):
    return mirror.main(["--user-claude", str(uc), "--dest", str(dest),
                        "--vault-id", VAULT_ID])


def test_copies_the_irreplaceable_core(tmp_path):
    uc = make_user_claude(tmp_path)
    dest = tmp_path / "out"
    assert run(uc, dest) == 0
    assert (dest / "memory" / "MEMORY.md").exists()
    assert (dest / "memory" / "finding_x.md").exists()
    assert (dest / "skills" / "s.md").exists()
    assert (dest / "settings.json").exists()
    assert (dest / "settings.local.json").exists()


def test_secrets_are_never_mirrored(tmp_path):
    """The one that matters. A planted credential must not reach the mirror."""
    uc = make_user_claude(tmp_path, with_secret=True)
    dest = tmp_path / "out"
    assert run(uc, dest) == 0
    landed = [p for p in dest.rglob("*") if p.is_file()]
    # Compare paths RELATIVE to dest: the pytest tmp dir is itself named after
    # this test, so an absolute-path substring check matches "secret" in the
    # fixture directory name and fails on a correct mirror.
    rel = [p.relative_to(dest).as_posix().lower() for p in landed]
    assert not any("secret" in r for r in rel), rel
    assert not any("github-pat" in r for r in rel), rel
    for p in landed:
        assert "ghp_TOTALLY_FAKE" not in p.read_text(encoding="utf-8",
                                                     errors="replace")


def test_destination_sweep_catches_a_preplanted_secret(tmp_path):
    """Mutation guard on the second assertion: if a forbidden file is already
    sitting in the destination (say a past bug put it there), the run must
    fail loudly rather than report a clean mirror."""
    uc = make_user_claude(tmp_path, with_secret=False)
    dest = tmp_path / "out"
    (dest / "secrets").mkdir(parents=True)
    (dest / "secrets" / "leaked.txt").write_text("x", encoding="utf-8")
    assert run(uc, dest) == 2


def test_is_idempotent_and_reports_unchanged(tmp_path, capsys):
    uc = make_user_claude(tmp_path)
    dest = tmp_path / "out"
    assert run(uc, dest) == 0
    first = capsys.readouterr().out
    assert "copied=5" in first, first
    assert run(uc, dest) == 0
    second = capsys.readouterr().out
    assert "copied=0" in second, second
    assert "unchanged=5" in second, second


def test_changed_file_is_recopied(tmp_path, capsys):
    uc = make_user_claude(tmp_path)
    dest = tmp_path / "out"
    assert run(uc, dest) == 0
    capsys.readouterr()
    (uc / "projects" / VAULT_ID / "memory" / "MEMORY.md").write_text(
        "# index\n- a > b\n- c > d\n", encoding="utf-8")
    assert run(uc, dest) == 0
    out = capsys.readouterr().out
    assert "copied=1" in out, out
    assert "- c > d" in (dest / "memory" / "MEMORY.md").read_text(encoding="utf-8")


def test_missing_source_exits_2(tmp_path):
    """Never silently partial: a vanished memory folder is a loud failure, not
    a mirror that quietly backs up less than it claims."""
    uc = make_user_claude(tmp_path)
    import shutil
    shutil.rmtree(uc / "projects" / VAULT_ID / "memory")
    dest = tmp_path / "out"
    assert run(uc, dest) == 2


# --- credential content gate (added after the 2026-09-09 near-miss) -----------
# The first live run tried to mirror a real GitHub PAT sitting in plaintext
# inside settings.json. A path-based exclusion cannot catch that: the file was
# one we deliberately chose to back up.

def test_credential_in_a_wanted_file_is_refused(tmp_path, capsys):
    uc = make_user_claude(tmp_path, with_secret=False)
    (uc / "settings.json").write_text(
        '{"token": "ghp_' + "A" * 30 + '"}', encoding="utf-8")
    dest = tmp_path / "out"
    assert run(uc, dest) == 1                      # mirrored, with a refusal
    assert not (dest / "settings.json").exists()
    out = capsys.readouterr().out
    assert "REFUSED" in out and "refused=1" in out, out
    # the rest of the backup must still happen
    assert (dest / "memory" / "MEMORY.md").exists()


def test_previously_mirrored_credential_is_removed(tmp_path):
    """If an earlier run copied a file before the gate existed, the next run
    must delete that copy, not leave a stale credential sitting in the repo."""
    uc = make_user_claude(tmp_path, with_secret=False)
    dest = tmp_path / "out"
    assert run(uc, dest) == 0
    assert (dest / "settings.json").exists()
    (uc / "settings.json").write_text(
        '{"token": "ghp_' + "B" * 30 + '"}', encoding="utf-8")
    assert run(uc, dest) == 1
    assert not (dest / "settings.json").exists()


def test_ordinary_memory_note_mentioning_secrets_is_still_mirrored(tmp_path):
    """Guard against over-refusal: a note ABOUT credentials is not a credential.
    Six such files exist in the real memory folder."""
    uc = make_user_claude(tmp_path, with_secret=False)
    mem = uc / "projects" / VAULT_ID / "memory"
    (mem / "reference_secrets_live_outside_the_vault.md").write_text(
        "Secrets live at .claude/projects/<id>/secrets/. Never print values.\n",
        encoding="utf-8")
    dest = tmp_path / "out"
    assert run(uc, dest) == 0
    assert (dest / "memory" / "reference_secrets_live_outside_the_vault.md").exists()
