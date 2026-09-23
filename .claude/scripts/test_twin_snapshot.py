"""O14 unit tests: twin_snapshot.py (write + diff subcommands).

Runs the script as a subprocess (the CLI exit codes ARE the contract:
CHECK (c) is a nonzero exit on wrong arity, CHECK (d) is a known-answer
diff naming exactly one flipped path). tmp_path fixtures only; never
reads or writes the live aggregates dir or any telemetry sink.

Build record: Projects/Agent-Governance-Research/work/2026-09-01-o14-build-record.md
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "twin_snapshot.py"
PYTHON = sys.executable


def run_cli(*args):
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8")


def make_inventory(tmp_path, *, with_twins=True, run_id="20260901T120000000000Z",
                   generated_at="2026-09-01T12:00:00Z"):
    inv = {
        "run_id": run_id,
        "generated_at": generated_at,
        "twin_summary": {"identical": 1, "divergent": 2, "repo-absent": 0,
                         "ambiguous": 0, "no-path": 0, "not-applicable": 0},
    }
    if with_twins:
        inv["twins"] = {
            "counts": dict(inv["twin_summary"]),
            "kind_set": ["agent", "hook"],
            "divergent": [
                {"kind": "agent", "name": "a1", "path": ".claude/agents/a1.md"},
                {"kind": "hook", "name": "h1", "path": ".claude/hooks/h1.py"},
            ],
        }
    p = tmp_path / "asset-inventory.json"
    p.write_text(json.dumps(inv), encoding="utf-8")
    return p, inv


def make_snapshot(path, *, run_id, divergent, kind_set=("agent", "hook"),
                  schema_version=1):
    paths = {d["path"] for d in divergent}
    snap = {
        "schema_version": schema_version,
        "source_run_id": run_id,
        "source_generated_at": "2026-09-01T12:00:00Z",
        "snapshot_written_at": "2026-09-01T12:01:00Z",
        "source_file": "fixture",
        "kind_set": list(kind_set),
        "counts": {"identical": 0, "divergent": len(divergent), "repo-absent": 0,
                   "ambiguous": 0, "no-path": 0, "not-applicable": 0},
        "divergent": sorted(divergent,
                            key=lambda d: (d["kind"], d["name"], d["path"])),
    }
    path.write_text(json.dumps(snap), encoding="utf-8")
    return snap, paths


class TestWrite:
    def test_write_copies_twins_block(self, tmp_path):
        inv_path, inv = make_inventory(tmp_path)
        out_dir = tmp_path / "snaps"
        proc = run_cli("write", "--inventory", str(inv_path),
                       "--out-dir", str(out_dir))
        assert proc.returncode == 0, proc.stderr
        expected = out_dir / "2026-09-01-20260901T120000000000Z.json"
        assert expected.exists(), list(out_dir.glob("*"))
        snap = json.loads(expected.read_text(encoding="utf-8"))
        assert snap["schema_version"] == 1
        assert snap["source_run_id"] == inv["run_id"]
        assert snap["source_generated_at"] == inv["generated_at"]
        assert snap["counts"] == inv["twins"]["counts"]
        assert snap["divergent"] == inv["twins"]["divergent"]
        assert snap["kind_set"] == inv["twins"]["kind_set"]
        assert snap["snapshot_written_at"]

    def test_write_refuses_missing_twins_block(self, tmp_path):
        inv_path, _ = make_inventory(tmp_path, with_twins=False)
        out_dir = tmp_path / "snaps"
        proc = run_cli("write", "--inventory", str(inv_path),
                       "--out-dir", str(out_dir))
        assert proc.returncode == 2
        assert "twins" in proc.stderr
        assert not list(out_dir.glob("*.json")) if out_dir.exists() else True

    def test_write_refuses_overwrite(self, tmp_path):
        inv_path, _ = make_inventory(tmp_path)
        out_dir = tmp_path / "snaps"
        first = run_cli("write", "--inventory", str(inv_path),
                        "--out-dir", str(out_dir))
        assert first.returncode == 0, first.stderr
        second = run_cli("write", "--inventory", str(inv_path),
                         "--out-dir", str(out_dir))
        assert second.returncode == 2
        assert len(list(out_dir.glob("*.json"))) == 1


class TestDiff:
    def test_known_answer_single_flip_names_exactly_that_path(self, tmp_path):
        # CHECK (d): fixture pair identical except ONE synthetic twin_state
        # flip -- path P divergent in NEW only. Shared-path rows prove the
        # report dedupes to distinct paths (settings.local.json alone backs
        # 72 rows in the live inventory).
        shared = [
            {"kind": "hook", "name": "h1", "path": ".claude/settings.local.json"},
            {"kind": "hook", "name": "h2", "path": ".claude/settings.local.json"},
        ]
        flipped = {"kind": "skill", "name": "s1",
                   "path": ".claude/skills/s1/SKILL.md"}
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        make_snapshot(old_p, run_id="run-old", divergent=shared)
        make_snapshot(new_p, run_id="run-new", divergent=shared + [flipped])
        proc = run_cli("diff", str(old_p), str(new_p))
        assert proc.returncode == 0, proc.stderr
        out = proc.stdout
        assert "entering divergent (1)" in out
        assert flipped["path"] in out
        assert "leaving divergent (0)" in out
        # Exactly the flipped path and nothing else in the entering section:
        entering_lines = [ln.strip().lstrip("+ ").strip() for ln in out.splitlines()
                         if ln.startswith("  + ")]
        assert entering_lines == [flipped["path"]]
        # Distinct-path dedupe: two shared rows collapse to one still path.
        assert "still-divergent distinct paths: 1" in out

    def test_single_argument_exits_nonzero(self, tmp_path):
        # CHECK (c): diff over one snapshot only must fail loudly.
        old_p = tmp_path / "only.json"
        make_snapshot(old_p, run_id="run-only", divergent=[])
        proc = run_cli("diff", str(old_p))
        assert proc.returncode != 0
        assert proc.returncode == 2  # argparse arity error

    def test_kind_set_delta_line_when_sets_differ(self, tmp_path):
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        make_snapshot(old_p, run_id="r1", divergent=[], kind_set=("agent", "hook"))
        make_snapshot(new_p, run_id="r2", divergent=[],
                      kind_set=("agent", "hook", "workflow"))
        proc = run_cli("diff", str(old_p), str(new_p))
        assert proc.returncode == 0, proc.stderr
        assert "kind-set delta" in proc.stdout
        assert "workflow" in proc.stdout

    def test_no_kind_set_delta_line_when_sets_equal(self, tmp_path):
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        make_snapshot(old_p, run_id="r1", divergent=[])
        make_snapshot(new_p, run_id="r2", divergent=[])
        proc = run_cli("diff", str(old_p), str(new_p))
        assert proc.returncode == 0, proc.stderr
        assert "kind-set delta" not in proc.stdout

    def test_invalid_snapshot_exits_2(self, tmp_path):
        old_p = tmp_path / "old.json"
        new_p = tmp_path / "new.json"
        make_snapshot(old_p, run_id="r1", divergent=[])
        make_snapshot(new_p, run_id="r2", divergent=[], schema_version=99)
        proc = run_cli("diff", str(old_p), str(new_p))
        assert proc.returncode == 2
