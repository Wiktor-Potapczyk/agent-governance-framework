"""Tests for lint_pass_work_index_stale.py + generate_work_index.py stamp (ROAD-7, Pass S).

Declarative-first: written before the implementation. Uses a tmp fixture
vault plus monkeypatched module globals so no live INDEX.md or live
_state/ file is ever touched.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import generate_work_index as gwi  # noqa: E402


def make_fixture_vault(tmp_path, n_files=2):
    work = tmp_path / "Projects" / "Pilot" / "work"
    work.mkdir(parents=True)
    for i in range(n_files):
        (work / f"2026-01-0{i + 1}-note{i}.md").write_text(
            f"---\ndate: 2026-01-0{i + 1}\ntags: [task]\nstatus: active\n---\n\n# Note {i}\n\n## Purpose {i}\n",
            encoding="utf-8",
        )
    return work


@pytest.fixture
def fixture_vault(tmp_path, monkeypatch):
    work = make_fixture_vault(tmp_path)
    monkeypatch.setattr(gwi, "VAULT", str(tmp_path))
    monkeypatch.setattr(gwi, "PILOTS", ["Projects/Pilot"])
    return tmp_path, work


def test_generator_writes_stamp(fixture_vault):
    tmp, work = fixture_vault
    assert gwi.main() == 0
    assert (work / "INDEX.md").is_file()
    stamp_path = tmp / ".claude" / "hooks" / "_state" / "work-index-pilot.json"
    assert stamp_path.is_file(), "generator must write work-index-<slug>.json"
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert stamp["file_count"] == 2
    assert stamp["project"] == "Projects/Pilot"
    assert "last_iso" in stamp


def test_pass_clean_after_regeneration(fixture_vault, capsys):
    tmp, work = fixture_vault
    gwi.main()
    import lint_pass_work_index_stale as pass_s
    rc = pass_s.main(["--vault", str(tmp), "--state-dir",
                      str(tmp / ".claude" / "hooks" / "_state")])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "WORK_INDEX_STALE" not in out
    assert "WORK_INDEX " in out or "WORK_INDEX\t" in out or "project=" in out


def test_pass_detects_added_file(fixture_vault, capsys):
    tmp, work = fixture_vault
    gwi.main()
    (work / "2026-01-09-added.md").write_text(
        "---\ndate: 2026-01-09\ntags: [task]\nstatus: active\n---\n\n# Added\n",
        encoding="utf-8",
    )
    import lint_pass_work_index_stale as pass_s
    rc = pass_s.main(["--vault", str(tmp), "--state-dir",
                      str(tmp / ".claude" / "hooks" / "_state")])
    out = capsys.readouterr().out
    assert rc == 1
    findings = [l for l in out.splitlines() if l.startswith("WORK_INDEX_STALE")]
    assert len(findings) == 1
    assert "stamped=2" in findings[0] and "live=3" in findings[0]


def test_pass_missing_stamp_is_finding(fixture_vault, capsys):
    tmp, work = fixture_vault
    import lint_pass_work_index_stale as pass_s
    rc = pass_s.main(["--vault", str(tmp), "--state-dir",
                      str(tmp / ".claude" / "hooks" / "_state")])
    out = capsys.readouterr().out
    assert rc == 1
    findings = [l for l in out.splitlines() if l.startswith("WORK_INDEX_STALE")]
    assert len(findings) == 1
    assert "stamped=none" in findings[0]
