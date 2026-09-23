#!/usr/bin/env python3
"""owner_digest_compose.py - the daily owner message, composed with no model call.

Autonomy plan of record step 4.1 (Projects/Vault-Maintenance/work/
2026-09-18-autonomy-programme-plan.md, decision 1): the daily message moves to
GitHub. `.github/workflows/vault-owner-digest.yml` runs this script, posts the
result as ONE comment on the pinned digest issue with the workflow's own
GITHUB_TOKEN (the Actions bot, never the push credential: GitHub does not
notify a person about a comment authored as himself), and commits the
proof-of-send file the outcome watchdog already reads.

Format contract: `.claude/routines/owner-digest.md`, Prompt step 2. Health
word and date, at most five bullets that each name their source, a closing
line, the fixed kill-switch footer, under 150 words. Only alerts and things
waiting on the owner become bullets; healthy status never does.

Sources, both re-derived at run time, never copied from an older report:
  1. scheduler_watchdog.evaluate_repo_outcomes: the same checks the outcome
     watchdog runs.
  2. `gh pr list --label needs-owner`: open loop pull requests waiting on him.

Every piece of text that comes from a pull request title or a check detail is
flattened to one line, stripped of "@", and cut to a word limit, so it can
neither mention a third party nor forge a bullet.

Run (read-only, prints the message):
    PYTHONIOENCODING=utf-8 "C:/Program Files/Python314/python.exe" \
        .claude/scripts/owner_digest_compose.py --vault-root .
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FOOTER = ("Pause: .claude/self-heal/PAUSED. Rules: targets.json, acceptance.json, "
          "retention.json, PROMPT.md.")
MAX_BULLETS = 5
NAME_WORD_LIMIT = 6
DETAIL_WORD_LIMIT = 12
WORD_BUDGET = 150
# The digest cannot report its own silence; the watchdog issue does that.
OWN_PROOF_OF_LIFE_ROW = "owner digest last-send"
# Alerts that are the owner's to act on, beyond open needs-owner pull requests.
OWNER_ACTION_ROWS = ("self-heal OAuth token age", "self-heal PAT age")
ALERT_VERDICTS = ("STALE", "ERROR")


def _clean(text, word_limit: int) -> str:
    words = str(text or "").replace("@", "").split()
    if len(words) > word_limit:
        words = words[:word_limit] + ["..."]
    return " ".join(words)


def compose(rows: list, needs_owner_prs, today: date, mention: str) -> str:
    """Pure function. `rows` are dicts with name, verdict, detail, alert.
    `needs_owner_prs` is a list of dicts with number and title, or None when
    the pull request read was unavailable."""
    rows = [r for r in rows if r.get("name") != OWN_PROOF_OF_LIFE_ROW]
    alert_rows = [r for r in rows if r.get("verdict") in ALERT_VERDICTS]
    prs = list(needs_owner_prs or [])

    bullets = []
    for pr in prs:
        bullets.append(
            f"- PR #{int(pr.get('number', 0))} waits for you: "
            f"{_clean(pr.get('title'), DETAIL_WORD_LIMIT)} (open pull requests)")
    for row in alert_rows:
        bullets.append(
            f"- {_clean(row.get('name'), NAME_WORD_LIMIT)}: "
            f"{_clean(row.get('alert') or row.get('detail'), DETAIL_WORD_LIMIT)} (watchdog checks)")
    if len(bullets) > MAX_BULLETS:
        cut = len(bullets) - (MAX_BULLETS - 1)
        bullets = bullets[:MAX_BULLETS - 1] + [f"- {cut} more: see the watchdog issue (watchdog checks)"]

    nothing_readable = bool(rows) and all(r.get("verdict") == "N/A" for r in rows)
    if any(r.get("verdict") == "ERROR" for r in alert_rows) or nothing_readable or (
            not rows and needs_owner_prs is None):
        health = "RED"
    elif bullets:
        health = "AMBER"
    else:
        health = "GREEN"

    needs_you = len(prs) + sum(1 for r in alert_rows if r.get("name") in OWNER_ACTION_ROWS)
    closing = f"Needs you: {needs_you}" if needs_you else "Nothing needs you"

    stamp = today.isoformat()
    lines = [f"Vault digest {stamp}", f"{health} {stamp}", f"cc {mention}", *bullets, closing, FOOTER]
    message = "\n".join(lines)
    assert len(message.split()) < WORD_BUDGET, "digest exceeds its word budget"
    return message


def health_of(message: str) -> str:
    return message.splitlines()[1].split()[0]


def read_needs_owner_prs(vault_root: Path, run_fn=subprocess.run):
    """None when the read is unavailable, never an empty list by default."""
    try:
        proc = run_fn(
            ["gh", "pr", "list", "--label", "needs-owner", "--state", "open",
             "--json", "number,title"],
            cwd=str(vault_root), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        prs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return prs if isinstance(prs, list) else None


def gather_rows(vault_root: Path, now: datetime) -> list:
    import scheduler_watchdog as sw
    fleet = sw.evaluate_repo_outcomes(vault_root, now)
    return [{"name": row.name, "verdict": row.artifact.verdict,
             "detail": row.artifact.detail, "alert": row.artifact.alert}
            for row in fleet.rows]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault-root", default=".")
    parser.add_argument("--mention", default="@Wiktor-Potapczyk")
    parser.add_argument("--out", help="write the message to this file")
    parser.add_argument("--meta-out", help="write {health, sent_at, channel, cadence_hours} here")
    args = parser.parse_args(argv)

    vault_root = Path(args.vault_root).resolve()
    now = datetime.now(timezone.utc)
    message = compose(gather_rows(vault_root, now), read_needs_owner_prs(vault_root),
                      now.date(), args.mention)
    print(message)
    if args.out:
        Path(args.out).write_text(message + "\n", encoding="utf-8", newline="\n")
    if args.meta_out:
        meta = {"sent_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "channel": "github-issue-comment", "cadence_hours": 24,
                "health": health_of(message)}
        Path(args.meta_out).write_text(json.dumps(meta, indent=2) + "\n",
                                       encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
