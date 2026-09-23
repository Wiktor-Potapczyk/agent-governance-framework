r"""self_heal_pr_body.py - builds the phase (c) improver's structured PR
title/body (spec section 3.3 step 6) from the round's assignment, the
committed diff, and the improver's own captured claude log.

Spec of record: Projects/Vault-Maintenance/work/2026-09-16-self-healing-loop-spec.md
section 3.3. Plan: Projects/Vault-Maintenance/work/backups/
2026-09-16-self-heal-phase-c-plan.md TASK-017. Used only by
.github/workflows/vault-self-heal.yml's "Commit, push, and open or update
PR" step -- the loop's own improver session never calls this script itself,
since the claude step has no GitHub credential to open a PR with (spec
section 3.3 credential design); the workflow builds the PR title/body AFTER
the improver's turn ends, from what it actually committed.

DELIVERABLE_PATH (open item, see the phase (c) build record). PROMPT.md's
own template asks the improver to name its "one primary deliverable" file
itself, but the improver has no channel back to this script (it only edits
files; it never writes a machine-readable side artifact). This script
instead reads the committed diff and uses the FIRST changed path
(alphabetically, via `git diff --name-only`, sorted) as deliverable_path.
For a single-file round (the common case, since PROMPT.md's own assignment
contract scopes one class/one target per round) this is exact; for a
multi-file round it is a heuristic, not a claim of primacy, and is named
here as an open item rather than silently assumed correct.

CLI (thin; the only I/O this script does is `git diff` against
--main-checkout and reading --claude-log)
  python self_heal_pr_body.py --class scripts --source watchdog-issue \
      --config-version <sha> --claude-log self-heal-run.jsonl \
      --main-checkout . --title-out /tmp/pr-title.txt --body-out /tmp/pr-body.md

Python 3.14, standard library only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOW_TO_ANSWER = (
    "## How to answer\n\n"
    "Comment `no: <reason>` to reject. Comment `partial: <what>` to flag "
    "this for a live session instead of a merge or reject. Click merge if "
    "you agree. The kill switch is `.claude/self-heal/PAUSED`; create it "
    "with any commit to pause every future round. Rule files: "
    "`.claude/self-heal/targets.json`, `acceptance.json`, `retention.json`, "
    "`PROMPT.md`.\n"
)

NO_SUMMARY_TEXT = "(no summary text captured from the improver's result)"
NO_DIFF_TEXT = "(no diff)"


def extract_claude_result_text(log_path: Path) -> str:
    """Reads a `claude -p --output-format stream-json` log (one JSON object
    per line) and returns the final `type: result` message's own `result`
    text, scanning from the END of the file backwards so a truncated or
    malformed earlier line never blocks it. Returns a placeholder string if
    no such message is found (including when the log file itself is
    absent, e.g. a revert-priority round that never invoked claude)."""
    if not log_path.exists():
        return NO_SUMMARY_TEXT
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result" and obj.get("result"):
            return str(obj["result"])
    return NO_SUMMARY_TEXT


def git_diff_stat(main_checkout: Path, base_sha: str, run_fn=subprocess.run) -> str:
    """Three-dot diff (base_sha...HEAD): what HEAD introduced since it
    diverged from base_sha, never main's own later, unrelated changes."""
    proc = run_fn(
        ["git", "-C", str(main_checkout), "diff", "--stat", f"{base_sha}...HEAD"],
        capture_output=True, text=True, check=True,
    )
    return proc.stdout


def git_diff_deliverable_path(main_checkout: Path, base_sha: str, run_fn=subprocess.run) -> str:
    proc = run_fn(
        ["git", "-C", str(main_checkout), "diff", "--name-only", f"{base_sha}...HEAD"],
        capture_output=True, text=True, check=True,
    )
    paths = sorted(p for p in proc.stdout.splitlines() if p.strip())
    return paths[0] if paths else "(no changed files)"


def build_title(*, pr_class: str, source: str, as_of: str | None = None) -> str:
    day = as_of or datetime.now(timezone.utc).date().isoformat()
    return f"self-heal: {pr_class} {day} ({source})"


def build_body(*, deliverable_path: str, config_version: str, summary: str, diff_stat: str) -> str:
    return (
        f"deliverable_path: {deliverable_path}\n"
        f"config_version: {config_version}\n"
        "rollback: \n\n"
        f"{summary.strip()}\n\n"
        "```\n"
        f"{diff_stat.strip() or NO_DIFF_TEXT}\n"
        "```\n\n"
        f"{HOW_TO_ANSWER}"
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--class", dest="pr_class", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--config-version", required=True,
                         help="the main SHA the round's assignment and control "
                              "files were read from; also the diff-stat base")
    parser.add_argument("--claude-log", required=True,
                         help="path to the improver's captured "
                              "--output-format stream-json log")
    parser.add_argument("--main-checkout", default=".")
    parser.add_argument("--title-out", required=True)
    parser.add_argument("--body-out", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    main_checkout = Path(args.main_checkout)
    summary = extract_claude_result_text(Path(args.claude_log))
    diff_stat = git_diff_stat(main_checkout, args.config_version)
    deliverable_path = git_diff_deliverable_path(main_checkout, args.config_version)

    title = build_title(pr_class=args.pr_class, source=args.source)
    body = build_body(
        deliverable_path=deliverable_path,
        config_version=args.config_version,
        summary=summary,
        diff_stat=diff_stat,
    )

    Path(args.title_out).write_text(title, encoding="utf-8")
    Path(args.body_out).write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
