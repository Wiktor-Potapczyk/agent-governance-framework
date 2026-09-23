"""
test_dispatches_freshness_check.py - pytest suite for dispatches_freshness_check.py (O11).

Run from inside .claude/scripts:
    "C:\\Program Files\\Python314\\python.exe" -m pytest test_dispatches_freshness_check.py -v

Covers, per the O11 CHECK contract (2026-08-31-harness-takeover-objectives.md) and
the 2026-09-01 implementation plan S1:
  - all-FRESH fixture run exits 0
  - corroboration flip (dispatch named in DISPATCHES.json, absent from sibling
    SKILL.md) is STALE naming that dispatch, exit 2
  - SKILL.md / workflow-.js content-hash drift past the recorded baseline is
    STALE naming the drifted sibling, exit 2
  - missing review_baseline is ERROR (NO_BASELINE), exit 1 - the checker must
    never bless an unbaselined file
  - a baseline listing a sibling absent on disk is ERROR (SIBLING_MISSING)
  - --bootstrap then check yields FRESH; a second bootstrap is byte-idempotent
  - empty enumeration exits 1, never 0 (same rule staleness_check.py applies to
    an empty manifest: nothing-to-check is never a clean bill)
  - two runs over one fixture produce byte-identical stdout (determinism)
  - enumeration covers both a pm/-shaped and a process-x/-shaped skill dir
    (regression pin for the widened */DISPATCHES.json glob)
  - review_baseline.review_date != last_reviewed is ERROR (BASELINE_REVIEW_MISMATCH)
"""
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import dispatches_freshness_check as dfc  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders: a mirrored vault tree under tmp_path
#   <root>/.claude/skills/<skill>/{DISPATCHES.json,SKILL.md}
#   <root>/.claude/workflows/<skill>.js
# ---------------------------------------------------------------------------

def _make_skill(root: Path, skill: str, dispatches: list[str],
                with_workflow: bool = True,
                last_reviewed: str = "2026-08-30") -> Path:
    skill_dir = root / ".claude" / "skills" / skill
    skill_dir.mkdir(parents=True, exist_ok=True)
    md_lines = [f"# {skill}", ""]
    for name in dispatches:
        md_lines.append(f"Dispatch `{name}` per contract.")
    (skill_dir / "SKILL.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
    payload = {
        "schema_version": 1,
        "skill": skill,
        "mandatory_dispatches": [
            {"name": name, "role": "step", "required": True} for name in dispatches
        ],
        "conditional_dispatches": [],
        "allowed_specialists_via_process_exemption": [],
        "notes": "fixture",
        "last_reviewed": last_reviewed,
        "linked_skill_md": f".claude/skills/{skill}/SKILL.md",
    }
    (skill_dir / "DISPATCHES.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if with_workflow:
        wf_dir = root / ".claude" / "workflows"
        wf_dir.mkdir(parents=True, exist_ok=True)
        body = "// fixture workflow\n" + "".join(
            "dispatch('" + name + "');\n" for name in dispatches)
        (wf_dir / f"{skill}.js").write_text(body, encoding="utf-8")
    return skill_dir / "DISPATCHES.json"


def _two_skill_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _make_skill(root, "process-x", ["agent-alpha", "agent-beta"])
    _make_skill(root, "pm", ["pm-orchestrator"], with_workflow=False)
    return root


def _run(capsys, argv: list[str]) -> tuple[int, str, str]:
    code = dfc.run(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ---------------------------------------------------------------------------
# (1) all-FRESH fixture, exit 0  +  (10) pm-shaped and process-x-shaped dirs
# ---------------------------------------------------------------------------

def test_all_fresh_after_bootstrap_exits_zero(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    code, out, err = _run(capsys, ["--root", str(root), "--bootstrap"])
    assert code == 0
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 0
    assert out.count("FRESH") == 2
    assert "STALE" not in out and "ERROR" not in out


def test_enumeration_covers_pm_and_process_shaped_dirs(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    code, out, err = _run(capsys, ["--root", str(root), "--bootstrap"])
    assert code == 0
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 0
    assert "pm: FRESH" in out
    assert "process-x: FRESH" in out
    assert "checked=2" in out


# ---------------------------------------------------------------------------
# (2) corroboration flip -> STALE naming the dispatch, exit 2
# ---------------------------------------------------------------------------

def test_corroboration_flip_is_stale_naming_the_dispatch(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    # Rewrite SKILL.md dropping agent-beta, then re-record its hash so ONLY the
    # corroboration branch fires (not drift).
    md = root / ".claude" / "skills" / "process-x" / "SKILL.md"
    md.write_text("# process-x\n\nDispatch `agent-alpha` per contract.\n",
                  encoding="utf-8")
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 2
    verdict_line = [l for l in out.splitlines() if l.startswith("process-x:")][0]
    assert "STALE" in verdict_line
    assert "corroboration" in verdict_line
    assert "agent-beta" in verdict_line
    assert "agent-alpha" not in verdict_line


# ---------------------------------------------------------------------------
# (3) SKILL.md hash drift -> STALE naming the sibling path
# ---------------------------------------------------------------------------

def test_skill_md_drift_is_stale_naming_the_sibling(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    md = root / ".claude" / "skills" / "process-x" / "SKILL.md"
    # Append content that still mentions every dispatch, so corroboration stays
    # satisfied and ONLY the drift branch fires.
    md.write_text(md.read_text(encoding="utf-8") + "\nEdited after review.\n",
                  encoding="utf-8")
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 2
    verdict_line = [l for l in out.splitlines() if l.startswith("process-x:")][0]
    assert "STALE" in verdict_line
    assert "drift" in verdict_line
    assert ".claude/skills/process-x/SKILL.md" in verdict_line


# ---------------------------------------------------------------------------
# (4) workflow .js hash drift -> STALE
# ---------------------------------------------------------------------------

def test_workflow_js_drift_is_stale(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    wf = root / ".claude" / "workflows" / "process-x.js"
    wf.write_text(wf.read_text(encoding="utf-8") + "// edited\n", encoding="utf-8")
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 2
    verdict_line = [l for l in out.splitlines() if l.startswith("process-x:")][0]
    assert "STALE" in verdict_line
    assert "drift" in verdict_line
    assert ".claude/workflows/process-x.js" in verdict_line


# ---------------------------------------------------------------------------
# (5) missing review_baseline -> ERROR (NO_BASELINE), exit 1
# ---------------------------------------------------------------------------

def test_missing_baseline_is_error_no_baseline(tmp_path, capsys):
    root = _two_skill_root(tmp_path)  # no bootstrap
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 1
    assert "pm: ERROR (NO_BASELINE)" in out
    assert "process-x: ERROR (NO_BASELINE)" in out


# ---------------------------------------------------------------------------
# (6) listed sibling missing on disk -> ERROR (SIBLING_MISSING)
# ---------------------------------------------------------------------------

def test_listed_sibling_missing_on_disk_is_error(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    (root / ".claude" / "workflows" / "process-x.js").unlink()
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 1
    verdict_line = [l for l in out.splitlines() if l.startswith("process-x:")][0]
    assert "ERROR" in verdict_line
    assert "SIBLING_MISSING" in verdict_line
    assert ".claude/workflows/process-x.js" in verdict_line


# ---------------------------------------------------------------------------
# (7) bootstrap -> FRESH; second bootstrap is byte-idempotent
# ---------------------------------------------------------------------------

def test_bootstrap_then_check_fresh_and_second_bootstrap_idempotent(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 0
    assert out.count("FRESH") == 2
    dispatch_files = sorted((root / ".claude" / "skills").glob("*/DISPATCHES.json"))
    before = {p: p.read_bytes() for p in dispatch_files}
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    after = {p: p.read_bytes() for p in dispatch_files}
    assert before == after


def test_bootstrap_records_expected_shape(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    data = json.loads((root / ".claude" / "skills" / "pm" / "DISPATCHES.json")
                      .read_text(encoding="utf-8"))
    rb = data["review_baseline"]
    assert rb["review_date"] == data["last_reviewed"]
    assert set(rb["siblings"]) == {".claude/skills/pm/SKILL.md"}  # pm has no workflow
    for v in rb["siblings"].values():
        assert v.startswith("sha256:") and len(v) == len("sha256:") + 64
    data_x = json.loads((root / ".claude" / "skills" / "process-x" / "DISPATCHES.json")
                        .read_text(encoding="utf-8"))
    assert set(data_x["review_baseline"]["siblings"]) == {
        ".claude/skills/process-x/SKILL.md",
        ".claude/workflows/process-x.js",
    }
    # Hand-typed content untouched (O5/R13)
    assert data_x["mandatory_dispatches"][0]["name"] == "agent-alpha"
    assert data_x["notes"] == "fixture"


# ---------------------------------------------------------------------------
# (8) empty enumeration exits 1, never 0
# ---------------------------------------------------------------------------

def test_empty_enumeration_exits_one(tmp_path, capsys):
    root = tmp_path / "empty-vault"
    (root / ".claude" / "skills").mkdir(parents=True)
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 1
    assert "NO_DISPATCH_FILES" in err


# ---------------------------------------------------------------------------
# (9) determinism: two runs, byte-identical stdout
# ---------------------------------------------------------------------------

def test_two_runs_byte_identical_stdout(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    code1, out1, _ = _run(capsys, ["--root", str(root)])
    code2, out2, _ = _run(capsys, ["--root", str(root)])
    assert (code1, out1) == (code2, out2)


# ---------------------------------------------------------------------------
# (11) review_baseline.review_date != last_reviewed -> ERROR
# ---------------------------------------------------------------------------

def test_baseline_review_date_mismatch_is_error(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    dp = root / ".claude" / "skills" / "process-x" / "DISPATCHES.json"
    data = json.loads(dp.read_text(encoding="utf-8"))
    data["last_reviewed"] = "2026-09-15"  # newer review, baseline not refreshed
    dp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 1
    verdict_line = [l for l in out.splitlines() if l.startswith("process-x:")][0]
    assert "ERROR" in verdict_line
    assert "BASELINE_REVIEW_MISMATCH" in verdict_line


# ---------------------------------------------------------------------------
# Scope ruling pin: an uncorroborated allowed-specialist does NOT trip STALE
# (trigger (a) covers "any named dispatch" - mandatory and conditional; the
# exemption list is by design the set of names SKILL.md does not enumerate)
# ---------------------------------------------------------------------------

def test_uncorroborated_allowed_specialist_is_not_stale(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    dp = root / ".claude" / "skills" / "process-x" / "DISPATCHES.json"
    data = json.loads(dp.read_text(encoding="utf-8"))
    # Name a specialist that appears nowhere in the fixture SKILL.md
    data["allowed_specialists_via_process_exemption"] = ["ghost-specialist"]
    dp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    assert dfc.run(["--root", str(root), "--bootstrap"]) == 0
    capsys.readouterr()
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 0
    assert "process-x: FRESH" in out
    assert "ghost-specialist" not in out


# ---------------------------------------------------------------------------
# --skill restriction works in both modes
# ---------------------------------------------------------------------------

def test_skill_filter_restricts_both_modes(tmp_path, capsys):
    root = _two_skill_root(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap", "--skill", "pm"]) == 0
    capsys.readouterr()
    code, out, err = _run(capsys, ["--root", str(root), "--skill", "pm"])
    assert code == 0
    assert "pm: FRESH" in out
    assert "process-x" not in out
    # process-x never bootstrapped, so an unfiltered run still refuses to bless it
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 1
    assert "process-x: ERROR (NO_BASELINE)" in out


# ---------------------------------------------------------------------------
# Malformed DISPATCHES.json: the corroboration pre-pass must not crash the
# run, and --skill must isolate a filtered run from an unrelated bad file.
# Reproduces the adversarial-reviewer's two confirmed defects (build record
# 2026-09-01-o11-build-record.md, orchestrator addendum): asset_inventory's
# load_dispatch_roles() is fail-fast (unhandled JSONDecodeError before this
# fix), and it was called unfiltered regardless of --skill.
# ---------------------------------------------------------------------------

def _skill_a_and_broken_skill_b(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _make_skill(root, "skill-a", ["agent-alpha"])
    skill_b_dir = root / ".claude" / "skills" / "skill-b"
    skill_b_dir.mkdir(parents=True, exist_ok=True)
    (skill_b_dir / "SKILL.md").write_text("# skill-b\n", encoding="utf-8")
    (skill_b_dir / "DISPATCHES.json").write_text("{broken json", encoding="utf-8")
    return root


def test_malformed_file_gets_per_file_error_and_good_file_still_verdicts(
        tmp_path, capsys):
    root = _skill_a_and_broken_skill_b(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap", "--skill", "skill-a"]) == 0
    capsys.readouterr()
    code, out, err = _run(capsys, ["--root", str(root)])
    assert code == 1
    assert "traceback" not in out.lower() and "traceback" not in err.lower()
    lines = out.splitlines()
    a_line = [l for l in lines if l.startswith("skill-a:")][0]
    b_line = [l for l in lines if l.startswith("skill-b:")][0]
    assert a_line == "skill-a: FRESH"
    assert "ERROR" in b_line and "INVALID_JSON" in b_line
    assert "RESULT: checked=2 fresh=1 stale=0 error=1" in out


def test_skill_filtered_run_unaffected_by_unrelated_malformed_file(
        tmp_path, capsys):
    root = _skill_a_and_broken_skill_b(tmp_path)
    assert dfc.run(["--root", str(root), "--bootstrap", "--skill", "skill-a"]) == 0
    capsys.readouterr()
    code, out, err = _run(capsys, ["--root", str(root), "--skill", "skill-a"])
    assert code == 0
    assert "traceback" not in out.lower() and "traceback" not in err.lower()
    assert "skill-a: FRESH" in out
    assert "skill-b" not in out
    assert "RESULT: checked=1 fresh=1 stale=0 error=0" in out
