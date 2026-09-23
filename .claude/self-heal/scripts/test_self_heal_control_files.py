"""Structural-validation tests for the self-healing loop's three control
files: targets.json, acceptance.json, retention.json.

Spec: Projects/Vault-Maintenance/work/2026-09-16-self-healing-loop-spec.md,
sections 3.2, 3.4, section 5. Plan: Projects/Vault-Maintenance/work/backups/
2026-09-16-self-heal-phase-b-plan.md, TASK-008/TASK-009/TASK-010.

Run: PYTHONIOENCODING=utf-8 "C:/Program Files/Python314/python.exe" -m pytest
     .claude/self-heal/scripts/test_self_heal_control_files.py -q -p no:cacheprovider

Read-only against every file it inspects; never writes anything.
"""
from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[3]
TARGETS_PATH = VAULT / ".claude" / "self-heal" / "targets.json"
ACCEPTANCE_PATH = VAULT / ".claude" / "self-heal" / "acceptance.json"
RETENTION_PATH = VAULT / ".claude" / "self-heal" / "retention.json"

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from self_heal_glob import path_matches  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _class_by_name(targets: dict, name: str) -> dict:
    for entry in targets["allowed_classes"]:
        if entry["class"] == name:
            return entry
    raise AssertionError(f"class {name!r} not found in allowed_classes")


# ---------------------------------------------------------------------------
# targets.json
# ---------------------------------------------------------------------------

def test_targets_json_parses_and_has_required_top_level_keys():
    data = _load(TARGETS_PATH)
    for key in ("version", "allowed_classes", "forbidden_paths", "ranking"):
        assert key in data, f"missing top-level key {key!r}"


def test_targets_json_every_forbidden_path_resolves_to_a_real_path_or_glob():
    data = _load(TARGETS_PATH)
    for entry in data["forbidden_paths"]:
        if "*" in entry:
            if entry.endswith("/**"):
                base = entry[: -len("/**")]
                assert (VAULT / base).is_dir(), (
                    f"forbidden_paths glob {entry!r}: base dir {base!r} does not exist"
                )
            else:
                matches = list(VAULT.glob(entry))
                # Path.glob() must not raise; zero-or-more matches is valid
                # for a genuine glob entry (plan TASK-008 test 2).
                assert isinstance(matches, list)
        else:
            assert (VAULT / entry).is_file(), (
                f"forbidden_paths literal entry {entry!r} does not exist on disk"
            )


def test_targets_json_self_heal_scripts_dir_covered_by_forbidden_glob():
    data = _load(TARGETS_PATH)
    assert ".claude/self-heal/**" in data["forbidden_paths"]
    for script in (
        ".claude/self-heal/scripts/self_heal_target_select.py",
        ".claude/self-heal/scripts/self_heal_accept.py",
    ):
        assert fnmatch.fnmatch(script, ".claude/self-heal/**"), (
            f"{script!r} not covered by the .claude/self-heal/** forbidden glob (fnmatch)"
        )
        # Cross-checked against this loop's own directory-respecting glob
        # convention too (self_heal_glob.py), so the two matchers agree.
        assert path_matches(script, ".claude/self-heal/**"), (
            f"{script!r} not covered by the .claude/self-heal/** forbidden glob (self_heal_glob)"
        )


def test_targets_json_class_flags_present_where_spec_requires():
    data = _load(TARGETS_PATH)
    assert _class_by_name(data, "hook-logic-with-tests")["requires_sibling_test"] is True
    assert _class_by_name(data, "work-curation")["wikilink_integrity_check"] is True
    assert _class_by_name(data, "generated-docs")["protected_prose_check"] is True


def test_targets_json_trust_contract_verify_explicitly_forbidden():
    data = _load(TARGETS_PATH)
    assert ".claude/scripts/trust_contract_verify.py" in data["forbidden_paths"]
    assert ".claude/scripts/test_trust_contract_verify.py" in data["forbidden_paths"]


def test_targets_json_promotion_state_file_explicitly_forbidden():
    """AMB-002 (main-session decision): the promotion-state seed file is not
    under any allowed_classes glob, but it also gets an explicit
    forbidden_paths row for defense in depth."""
    data = _load(TARGETS_PATH)
    assert ".claude/hooks/_state/self-heal-promotion-state.json" in data["forbidden_paths"]


def test_targets_json_work_curation_excludes_backups_subtree():
    """Fix pass item 9 (adversarial Finding 11): work-curation's own glob
    (Projects/*/work/**) otherwise reaches into the researcher-owned
    Projects/*/work/backups/** scratch tree, which retention.json separately
    governs on its own 30-day policy."""
    data = _load(TARGETS_PATH)
    entry = _class_by_name(data, "work-curation")
    assert "Projects/*/work/backups/**" in (entry.get("excludes") or [])


def test_targets_json_signal_map_present_with_seed_entries():
    """Fix pass item 11 (architect MEDIUM-4): an owner-editable
    signal-to-target map, ordered list of {match, class, path}. Three
    infrastructure signals stay explicitly unmapped (class: null) so the
    loop never touches them."""
    data = _load(TARGETS_PATH)
    signal_map = data["signal_map"]
    assert isinstance(signal_map, list) and signal_map
    by_match = {entry["match"]: entry for entry in signal_map}
    assert by_match["^trust-contract-ledger"]["class"] == "work-curation"
    assert by_match["^lint (sweep|verifier)"]["class"] == "work-curation"
    for unmapped in ("^backup", "^observability digest", "^docs stamp",
                     "^owner digest", "^actions-minutes"):
        assert by_match[unmapped]["class"] is None, unmapped
        assert by_match[unmapped]["path"] is None, unmapped


def test_targets_json_merge_subject_prefix_present():
    """AMB-005 (main-session decision): the squash-merge-subject convention
    is recorded as a stable key, not left implicit in prose alone."""
    data = _load(TARGETS_PATH)
    assert data.get("merge_subject_prefix") == "self-heal: "


# ---------------------------------------------------------------------------
# acceptance.json
# ---------------------------------------------------------------------------

def test_acceptance_json_parses_and_has_required_top_level_keys():
    data = _load(ACCEPTANCE_PATH)
    for key in (
        "version", "max_diff_lines", "max_files_changed", "required_checks",
        "conditional_checks", "review_verdicts_required",
        "forbidden_diff_signatures", "promotion", "slow_regression_demotion_days",
    ):
        assert key in data, f"missing top-level key {key!r}"


def test_acceptance_json_all_nine_forbidden_diff_signatures_present():
    """Fix pass item 12 (architect MEDIUM-5): forbidden_diff_signatures now
    carries the spec's literal eight entries (each an {"id": ...,
    "description": ...} object; spec item 3, "outside the assigned class
    globs", gets id out-of-class-path, spec item 4, "inside
    forbidden_paths", gets id forbidden-path-touch, no longer merged),
    plus a ninth, suspicious-path, for the path-hygiene check (item 2),
    which is a distinct mechanism from forbidden-path-touch and so gets its
    own id rather than being folded in. work_dir_file_count_rule stays its
    own top-level key, not a tenth signature entry."""
    data = _load(ACCEPTANCE_PATH)
    signatures = data["forbidden_diff_signatures"]
    assert len(signatures) == 9, len(signatures)
    expected_ids = {
        "test-weakening",
        "protected-prose-byte-change",
        "rename-into-forbidden",
        "symlink-escape",
        "new-dependency",
        "secret-shaped-string",
        "out-of-class-path",
        "forbidden-path-touch",
        "suspicious-path",
    }
    ids = [sig["id"] for sig in signatures]
    assert len(set(ids)) == 9, f"duplicate id among {ids}"
    assert set(ids) == expected_ids, set(ids) ^ expected_ids
    for sig in signatures:
        assert isinstance(sig.get("description"), str) and sig["description"], sig
    assert "work_dir_file_count_rule" in data
    assert "work-dir-growth-without-deliverable" not in ids


def test_acceptance_json_split_signature_descriptions_match_spec_wording():
    """The two split-apart entries carry the spec's own literal sentence
    for each half (2026-09-16-self-healing-loop-spec.md:314-315), not a
    concatenation of both."""
    data = _load(ACCEPTANCE_PATH)
    by_id = {sig["id"]: sig["description"] for sig in data["forbidden_diff_signatures"]}
    assert by_id["out-of-class-path"] == "any path outside targets.json's assigned class globs"
    assert by_id["forbidden-path-touch"] == "any path inside targets.json's forbidden_paths"


def test_acceptance_json_every_dev1_class_reads_promotable_false():
    data = _load(ACCEPTANCE_PATH)
    for cls in ("hook-logic-with-tests", "skill-prose"):
        assert data["promotion"][cls]["promotable"] is False, cls


def test_acceptance_json_five_promotable_classes_have_streak_10():
    data = _load(ACCEPTANCE_PATH)
    for cls in ("generated-docs", "tests", "scripts", "registry", "work-curation"):
        entry = data["promotion"][cls]
        assert entry["promotable"] is True, cls
        assert entry["consecutive_green_required"] == 10, cls


def test_acceptance_json_slow_regression_demotion_days_is_7():
    data = _load(ACCEPTANCE_PATH)
    assert data["slow_regression_demotion_days"] == 7


def test_acceptance_json_conditional_check_maps_work_curation_to_wikilink_integrity():
    data = _load(ACCEPTANCE_PATH)
    assert data["conditional_checks"]["work-curation"] == ["wikilink-integrity"]


# ---------------------------------------------------------------------------
# retention.json
# ---------------------------------------------------------------------------

# Two classes are GitHub-native records with no vault filesystem path.
_NON_FILESYSTEM_CLASSES = {"watchdog-issue", "self-heal-open-prs"}

# Classes the plan/user require to demonstrably match at least one live file
# today (so the cross-check cannot pass on a vacuous zero-match glob).
_MUST_MATCH_TODAY = {"lint-reports", "experience-daily"}


def _iter_globs(path_field: str):
    """retention.json's 'review-build-records' row packs two globs into one
    comma-separated string; every other row is a single glob or literal
    path. Yields each individual glob/literal, stripped."""
    for part in path_field.split(","):
        part = part.strip()
        if part:
            yield part


def test_retention_json_parses_and_has_version_and_artifacts_list():
    data = _load(RETENTION_PATH)
    assert data.get("version") == 2
    assert isinstance(data.get("artifacts"), list) and data["artifacts"]


def test_retention_json_eight_classes_present():
    data = _load(RETENTION_PATH)
    classes = {a["class"] for a in data["artifacts"]}
    expected = {
        "lint-reports", "work-backups", "review-build-records",
        "experience-daily", "trust-ledger", "watchdog-issue",
        "self-heal-promotion-state", "self-heal-open-prs",
    }
    assert classes == expected, classes ^ expected


def test_retention_json_paths_resolve_against_live_repo_glob():
    data = _load(RETENTION_PATH)
    for artifact in data["artifacts"]:
        cls = artifact["class"]
        if cls in _NON_FILESYSTEM_CLASSES:
            continue
        matched_any = False
        for glob_str in _iter_globs(artifact["path"]):
            if "*" in glob_str:
                matches = list(VAULT.glob(glob_str))
                assert isinstance(matches, list), f"{cls}: {glob_str!r} raised on glob"
                if matches:
                    matched_any = True
            else:
                assert (VAULT / glob_str).exists(), (
                    f"{cls}: literal path {glob_str!r} does not exist"
                )
                matched_any = True
        if cls in _MUST_MATCH_TODAY:
            assert matched_any, f"{cls}: expected at least one live match, found none"


def test_retention_json_self_heal_open_prs_cap_matches_class_count():
    """The self-heal-open-prs row's retention prose states a bound
    consistent with targets.json's own allowed_classes count (7 today).
    Plain string-content assertion (retention values are prose, not
    structured numbers)."""
    retention = _load(RETENTION_PATH)
    targets = _load(TARGETS_PATH)
    open_prs_row = next(
        a for a in retention["artifacts"] if a["class"] == "self-heal-open-prs"
    )
    assert "one open PR per target class maximum" in open_prs_row["retention"]
    assert len(targets["allowed_classes"]) == 7


def test_hook_logic_class_paths_cover_the_sibling_test_it_requires():
    """Scheduled round 35707695830 (2026-09-22 08:58 UTC): the improver widened
    a regex in _subagent_quality_logic.py and added three regression tests to
    test_subagent_quality_check.py; the apply step rejected the whole change
    set because the class paths named only the logic file. A class that
    requires a sibling test must let a round change that test. The entry hook
    itself and tests elsewhere stay outside the class."""
    data = _load(TARGETS_PATH)
    paths = _class_by_name(data, "hook-logic-with-tests")["paths"]
    assert any(path_matches(".claude/hooks/_subagent_quality_logic.py", p) for p in paths)
    assert any(path_matches(".claude/hooks/test_subagent_quality_check.py", p) for p in paths)
    for outside in (".claude/hooks/subagent-quality-check.py",
                    ".claude/scripts/test_self_heal_apply.py",
                    ".claude/hooks/_state/self-heal-promotion-state.json"):
        assert not any(path_matches(outside, p) for p in paths), outside
