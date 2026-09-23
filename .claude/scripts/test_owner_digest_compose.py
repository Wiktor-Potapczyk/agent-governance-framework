"""Tests for owner_digest_compose.py (autonomy plan step 4.1, 2026-09-19).

The daily owner message, composed with no model call from the same checks the
outcome watchdog runs. Format contract: .claude/routines/owner-digest.md,
Prompt step 2 (health word and date, at most 5 bullets that each name their
source, a closing line, the fixed kill-switch footer, under 150 words).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import owner_digest_compose as odc  # noqa: E402

TODAY = date(2026, 9, 19)
FOOTER = "Pause: .claude/self-heal/PAUSED. Rules: targets.json, acceptance.json, retention.json, PROMPT.md."


def _row(name, verdict, detail="", alert=None):
    return {"name": name, "verdict": verdict, "detail": detail, "alert": alert}


def test_all_healthy_is_green_with_no_bullets_and_the_fixed_footer():
    rows = [_row("backup (origin outcome)", "PASS"), _row("docs stamp", "PASS")]
    msg = odc.compose(rows, [], TODAY, mention="@owner")
    lines = msg.splitlines()
    assert lines[0] == "Vault digest 2026-09-19"
    assert lines[1] == "GREEN 2026-09-19"
    assert not [ln for ln in lines if ln.startswith("- ")]
    assert "Nothing needs you" in lines
    assert lines[-1] == FOOTER
    assert "@owner" in msg


def test_a_stale_row_is_amber_and_its_bullet_names_the_watchdog_as_source():
    rows = [_row("backup (origin outcome)", "STALE", alert="last_run age 27.6h exceeds 26h")]
    msg = odc.compose(rows, [], TODAY, mention="@owner")
    assert msg.splitlines()[1] == "AMBER 2026-09-19"
    bullets = [ln for ln in msg.splitlines() if ln.startswith("- ")]
    assert bullets == ["- backup (origin outcome): last_run age 27.6h exceeds 26h (watchdog checks)"]
    assert "Nothing needs you" in msg


def test_an_error_row_is_red():
    rows = [_row("self-heal round", "ERROR", alert="last scheduled self-heal round (7) concluded failure 3h ago")]
    assert odc.compose(rows, [], TODAY, mention="@owner").splitlines()[1] == "RED 2026-09-19"


def test_every_check_unavailable_is_red():
    rows = [_row("needs-owner PR age", "N/A"), _row("docs stamp", "N/A")]
    msg = odc.compose(rows, None, TODAY, mention="@owner")
    assert msg.splitlines()[1] == "RED 2026-09-19"


def test_an_open_needs_owner_pr_counts_as_needing_him():
    prs = [{"number": 12, "title": "self-heal: tighten subagent quality check"},
           {"number": 13, "title": "self-heal: docs"}]
    msg = odc.compose([_row("docs stamp", "PASS")], prs, TODAY, mention="@owner")
    assert "- PR #12 waits for you: self-heal: tighten subagent quality check (open pull requests)" in msg
    assert "Needs you: 2" in msg
    assert msg.splitlines()[1] == "AMBER 2026-09-19"


def test_a_token_age_alert_counts_as_needing_him():
    rows = [_row("self-heal PAT age", "STALE", alert="self-heal PAT age 340d exceeds 335d")]
    assert "Needs you: 1" in odc.compose(rows, [], TODAY, mention="@owner")


def test_the_digests_own_proof_of_life_row_is_never_a_bullet():
    rows = [_row("owner digest last-send", "STALE", alert="sent_at age 3d exceeds cadence")]
    msg = odc.compose(rows, [], TODAY, mention="@owner")
    assert "owner digest" not in msg
    assert msg.splitlines()[1] == "GREEN 2026-09-19"


def test_more_than_five_findings_keep_five_bullets_and_say_how_many_were_cut():
    rows = [_row(f"check {i}", "STALE", alert=f"problem {i}") for i in range(8)]
    msg = odc.compose(rows, [], TODAY, mention="@owner")
    bullets = [ln for ln in msg.splitlines() if ln.startswith("- ")]
    assert len(bullets) == 5
    assert bullets[-1].startswith("- 4 more:")


def test_needs_owner_bullets_come_before_watchdog_bullets():
    rows = [_row(f"check {i}", "STALE", alert=f"problem {i}") for i in range(6)]
    prs = [{"number": 9, "title": "self-heal: x"}]
    bullets = [ln for ln in odc.compose(rows, prs, TODAY, mention="@owner").splitlines()
               if ln.startswith("- ")]
    assert bullets[0].startswith("- PR #9")


def test_the_message_stays_under_150_words_even_with_long_details():
    long_alert = "word " * 120
    rows = [_row(f"check {i}", "STALE", alert=long_alert) for i in range(8)]
    prs = [{"number": i, "title": "title " * 40} for i in range(4)]
    msg = odc.compose(rows, prs, TODAY, mention="@owner")
    assert len(msg.split()) < 150
    assert msg.splitlines()[-1] == FOOTER


def test_untrusted_text_cannot_inject_a_mention_or_a_new_line():
    prs = [{"number": 5, "title": "hello @someone-else\n- fake bullet"}]
    msg = odc.compose([], prs, TODAY, mention="@owner")
    assert "@someone-else" not in msg
    assert "- fake bullet" not in msg.splitlines()


# ---------------------------------------------------------------------------
# The workflow that posts it
# ---------------------------------------------------------------------------

def _workflow():
    import pytest
    yaml = pytest.importorskip("yaml")
    path = SCRIPTS.parents[1] / ".github" / "workflows" / "vault-owner-digest.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps():
    return {st["name"]: st for st in _workflow()["jobs"]["owner-digest"]["steps"]}


def test_the_comment_is_written_by_the_actions_bot_never_by_the_push_credential():
    wf_text = (SCRIPTS.parents[1] / ".github" / "workflows" / "vault-owner-digest.yml").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in wf_text.splitlines() if not ln.lstrip().startswith("#"))
    assert "secrets.GITHUB_TOKEN" in code
    assert code.count("secrets.") == code.count("secrets.GITHUB_TOKEN")


def test_a_dry_run_posts_nothing_and_commits_nothing():
    steps = _steps()
    assert steps["Post the comment"]["if"] == "${{ inputs.dry_run != true }}"
    for name in ("Write the proof-of-send file", "Commit and push the proof-of-send file"):
        assert steps[name]["if"] == "${{ steps.post.outputs.posted == 'true' }}", name


def test_the_proof_of_send_is_written_only_after_the_comment_call():
    names = list(_steps())
    assert names.index("Post the comment") < names.index("Write the proof-of-send file")
    post = _steps()["Post the comment"]["run"]
    assert post.index("gh issue comment") < post.index("posted=true")
    assert "set -e" in post


def test_the_workflow_shares_the_git_writer_group_and_has_the_four_scopes_it_uses():
    wf = _workflow()
    assert wf["concurrency"]["group"] == "vault-git-writer"
    assert wf["permissions"] == {"contents": "write", "issues": "write",
                                 "pull-requests": "read", "actions": "read"}
