#!/usr/bin/env python3
"""scheduler_watchdog.py - fleet health check for every Vault* scheduled task.

Enumerates every scheduled task whose name starts with "Vault" (one
PowerShell call, JSON output) and applies two independent verdicts per
task: the scheduler's own exit code, and an artifact-freshness check
re-derived from what the task is supposed to produce (never from the exit
code). Also evaluates one fleet-artifact-only check, the trust-contract
ledger, which is not tied to any single task.

Writes Resources/Observability/harness-alerts.md (byte-identical between
two runs of identical state except the last_run line and the History
section) and appends one JSON row per run to
.claude/hooks/_state/scheduler-watchdog.jsonl, bounded to 30 History
entries in the markdown (every run still appends to the jsonl; only the
markdown's History section truncates).

Exit codes:
  0  the watchdog ran (alerts are findings, not watchdog failure)
  2  the watchdog itself could not do its job (PowerShell launch failure,
     unparseable task JSON, or git unavailable); a "watchdog: <reason>"
     alert line is written before exiting

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/scheduler_watchdog.py
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/scheduler_watchdog.py --dry-run
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/scheduler_watchdog.py --retry-backup

Runner-safe mode (TASK-014, Projects/Vault-Maintenance/work/
2026-09-15-scheduled-jobs-off-laptop-plan.md, Phase 3): --repo-outcomes-only
skips PowerShell task enumeration and the backup retry entirely and runs only
the repo-visible checks. REPO_OUTCOME_CHECKS is the list of record; this
prose went stale twice when it restated it. It never touches harness-alerts.md or the scheduler-watchdog
jsonl state; it prints a Markdown report to stdout and, when --report-out is
given, also writes it to that path. It always exits 0: alerts are findings
for the caller (a GitHub Actions workflow that files them as an issue), not a
watchdog failure. A genuine WatchdogFatalError (e.g. git unavailable) still
exits 2. Intended entry point for .github/workflows/vault-outcome-watchdog.yml.

    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/scheduler_watchdog.py --repo-outcomes-only --report-out watchdog-report.md

Origin: Projects/Vault-Maintenance/work/backups/2026-09-15-watchdog-docs-stamp-plan.md,
Phase A (TASK-001 through TASK-008).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

SCRIPT_DIR = Path(__file__).resolve().parent
VAULT = SCRIPT_DIR.parents[1]  # .claude/scripts -> .claude -> vault root

ALERTS_MD_REL = "Resources/Observability/harness-alerts.md"
JSONL_STATE_REL = ".claude/hooks/_state/scheduler-watchdog.jsonl"
BACKUP_STATE_REL = ".claude/hooks/_state/vault-backup.json"
TRUST_LEDGER_REL = ".claude/hooks/_state/trust-contract-ledger.jsonl"
VAULT_METRICS_VERIFY_REL = "Resources/KB/vault-metrics-verify.jsonl"
DAILY_DIGEST_REL = "Resources/Observability/daily-digest.md"
LINT_SWEEPS_DIR_REL = "Resources/Observability/lint-sweeps"

HISTORY_MAX = 30
BACKUP_TASK_NAME = "Vault-BACKUP-daily"
TRUST_LEDGER_ID = "trust-contract-ledger"
ACTIONS_MINUTES_ID = "actions-minutes-remaining"
# GitHub Free plan, private repo, published allotment (platform-facts B5):
# https://docs.github.com/en/billing/managing-billing-for-your-products/about-billing-for-github-actions
# The GET /users/{login}/settings/billing/usage response carries no field for
# this figure (confirmed live 2026-09-16, Projects/Vault-Maintenance/work/
# 2026-09-16-actions-minutes-measurement.md), so this is GitHub's own
# published number, never a value read from the API.
GITHUB_FREE_TIER_INCLUDED_MINUTES = 2000
ACTIONS_MINUTES_ALERT_THRESHOLD = 200  # alert once remaining minutes drop below this

# 0x41301 TASK_STATE_QUEUED, 0x41303 TASK_STATE_DISABLED (informational,
# not a failure), 0x41325 TASK_STATE_READY_ALREADY_RUNNING,
# 0x41300 SCHED_S_TASK_HAS_NOT_RUN -- none of these mean the task failed.
INFORMATIONAL_RESULT_CODES = {0x41301, 0x41303, 0x41325, 0x41300}

RESULT_CODE_NAMES = {
    0xC000013A: "terminated",
    0x800710E0: "Win32 4320, operator or administrator refused the request",
    0x1: "generic failure",
    0x2: "file not found",
}

BACKUP_OK_RESULTS = {"success", "no-changes"}
BACKUP_MAX_AGE_HOURS = 26
AUTO_COMMIT_MAX_AGE_MINUTES = 90
OBSERVABILITY_MAX_AGE_HOURS = 26
LINT_SWEEP_MAX_AGE_DAYS = 8
TRUST_LEDGER_MAX_AGE_DAYS = 8

TASK_ARTIFACT_RULES = {
    BACKUP_TASK_NAME: "backup",
    "Vault Auto-Commit 30min": "auto_commit",
    "Vault-MON-V2-1-observability-collector": "observability",
    "Vault-MON-V2-1-observability-digest": "observability",
    "Vault-MON-V2-1-observability-verifier": "observability",
    "Vault-MON-V2-2-lint-sweep": "lint_sweep",
    "Vault-MON-V2-2-lint-verifier": "lint_verifier",
}

# --- Repo-outcomes-only constants (TASK-014) --------------------------------
# The runner checkout has no separate "origin" to lag behind (origin/main IS
# the checked-out HEAD), and no Task Scheduler to poll. These name the
# additional repo-visible artifacts that mode reads. Age thresholds are
# reused from the constants above, never redefined.
BOT_AUTHOR_NAME = "github-actions[bot]"
# Second, independent signal (architect review 2026-09-16, Phase 3 HIGH): a
# commit counts as bot-authored when EITHER the author name equals
# BOT_AUTHOR_NAME OR the author email ends with this suffix, so a cosmetic
# display-name change in a sibling workflow cannot silently reopen the
# filter. Matches .github/actions/vault-commit/commit_and_push.sh's
# `git config user.email "41898282+github-actions[bot]@users.noreply.github.com"`.
BOT_AUTHOR_EMAIL_SUFFIX = "[bot]@users.noreply.github.com"
DOCS_GENERATED_JSON_REL = ".claude/docs/harness/_generated.json"
DOCS_HARNESS_DIR_REL = ".claude/docs/harness"
OWNER_DIGEST_LAST_SEND_REL = "Resources/Observability/owner-digest-last-send.json"

# --- Self-heal phase (c) constants (TASK-032a-e) ---------------------------
RETENTION_JSON_REL = ".claude/self-heal/retention.json"
WORK_BACKUPS_GLOB_REL = "Projects/*/work/backups/*"
EXPERIENCE_DAILY_GLOB_REL = "Resources/Observability/experience/*.json"
TOKEN_MINTED_AT_REL = ".claude/self-heal/token-minted-at.txt"
PUSH_TOKEN_MINTED_AT_REL = ".claude/self-heal/push-token-minted-at.txt"
NEEDS_OWNER_PR_MAX_AGE_DAYS = 10
# Autonomy plan step 1.7 (2026-09-19): the loop runs daily at 04:00 UTC and
# GitHub delays scheduled runs by hours, so 30h is one missed day plus slack.
SELF_HEAL_ROUND_MAX_AGE_HOURS = 30
SELF_HEAL_WORKFLOW_FILE = "vault-self-heal.yml"
# 30 days of runway before a 1-year token/PAT expiry (mirrors
# ACTIONS_MINUTES_ALERT_THRESHOLD's own "alert with runway left" shape).
SELF_HEAL_TOKEN_AGE_ALERT_THRESHOLD_DAYS = 335
SELF_HEAL_MECHANICALLY_CAPPED_RETENTION_CLASSES = {
    "trust-ledger", "work-backups", "experience-daily", "lint-reports",
}

_DOTNET_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


class WatchdogFatalError(Exception):
    """The watchdog itself could not do its job: PowerShell launch failure,
    unparseable task JSON, or git unavailable. Distinct from a per-task
    alert, which is a finding, not a watchdog malfunction."""


@dataclass
class ArtifactVerdict:
    verdict: str          # PASS | STALE | ERROR | N/A
    detail: str
    age_display: str = "n/a"
    since: Optional[str] = None
    alert: Optional[str] = None


@dataclass
class TaskRow:
    name: str
    state: str
    last_run_display: str
    result_display: str
    next_run_display: str
    artifact: ArtifactVerdict
    alert_text: Optional[str] = None


@dataclass
class FleetResult:
    rows: list = field(default_factory=list)
    trust_ledger: Optional[ArtifactVerdict] = None
    actions_minutes: Optional[ArtifactVerdict] = None
    alerts: list = field(default_factory=list)  # list of "name: detail, since time" strings


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_dotnet_date(value) -> Optional[datetime]:
    """Parse a .NET '/Date(1234567890000)/' millisecond-epoch string to a
    UTC datetime. Returns None for None/empty input, and for an epoch the
    platform cannot represent as a datetime (e.g. Windows Task Scheduler's
    pre-1970 sentinel for a task's LastRunTime/NextRunTime before it has
    ever run; Windows CRT gmtime rejects pre-1970 timestamps): treated as
    'never run', not raised."""
    if not value:
        return None
    match = _DOTNET_DATE_RE.search(str(value))
    if not match:
        return None
    millis = int(match.group(1))
    try:
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def load_tasks_json(text: str) -> list:
    """Parse PowerShell's ConvertTo-Json output. A single result drops the
    array wrapper (returns an object, not a list); wrap it before use.
    None or empty text (PowerShell's swallowed-decode-error failure mode
    returns stdout=None with returncode=0) is a watchdog-fatal condition,
    not a per-task alert."""
    if not text:
        raise WatchdogFatalError("empty task JSON output (no data to parse)")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WatchdogFatalError(f"unparseable task JSON: {exc}") from exc
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed
    raise WatchdogFatalError(f"task JSON is not an object or array: {type(parsed).__name__}")


def result_code_display(code) -> str:
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        return str(code)
    if code_int == 0:
        return "0x0"
    hex_str = f"0x{code_int:X}"
    name = RESULT_CODE_NAMES.get(code_int)
    return f"{hex_str} ({name})" if name else hex_str


def _format_age(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours < 0:
        hours = 0
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f}d"


def _parse_iso(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# git helper (real git, never mocked; callers control cwd via vault_root)
# ---------------------------------------------------------------------------


def _git(args: list, cwd: Path):
    try:
        return subprocess.run(
            ["git"] + args, cwd=str(cwd), capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WatchdogFatalError(f"git unavailable: {exc}") from exc


# ---------------------------------------------------------------------------
# Per-kind artifact checks
# ---------------------------------------------------------------------------


def _backup_state_reasons(data: dict, now: datetime) -> tuple:
    """last_run/result staleness reasons shared by check_backup_artifact and
    check_backup_artifact_repo_outcomes (architect review 2026-09-16, Phase 3
    MEDIUM: the two callers previously carried byte-identical inline copies
    of this block; this is now the single source both call). Returns
    (reasons, since, age_display). Reuses BACKUP_MAX_AGE_HOURS and
    BACKUP_OK_RESULTS; never redefines them."""
    reasons = []
    since = data.get("last_run")
    last_run_str = data.get("last_run")
    age_display = "n/a"
    if last_run_str:
        try:
            last_run_dt = _parse_iso(last_run_str)
            age = now - last_run_dt
            age_display = _format_age(age)
            if age > timedelta(hours=BACKUP_MAX_AGE_HOURS):
                reasons.append(
                    f"last_run age {age_display} exceeds {BACKUP_MAX_AGE_HOURS}h"
                )
        except ValueError:
            reasons.append(f"unparseable last_run {last_run_str!r}")
    else:
        reasons.append("last_run missing")

    result = data.get("result")
    if result not in BACKUP_OK_RESULTS:
        reasons.append(f"result={result!r} not in {sorted(BACKUP_OK_RESULTS)}")
    return reasons, since, age_display


def check_backup_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    path = vault_root / BACKUP_STATE_REL
    if not path.exists():
        return ArtifactVerdict("ERROR", "state file not found", alert="state file not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ArtifactVerdict("ERROR", f"state file unreadable: {exc}",
                                alert=f"state file unreadable: {exc}")

    reasons, since, age_display = _backup_state_reasons(data, now)

    lag_reason = _check_origin_lag(vault_root)
    if lag_reason:
        reasons.append(lag_reason)

    if reasons:
        return ArtifactVerdict("STALE", "; ".join(reasons), age_display,
                                since=since, alert="; ".join(reasons))
    return ArtifactVerdict("PASS", f"age {age_display} within {BACKUP_MAX_AGE_HOURS}h max; "
                            "result ok; origin in sync", age_display, since=since)


def _check_origin_lag(vault_root: Path) -> Optional[str]:
    """Read-only git fetch plus a rev-list ahead-count. A fetch/rev-list
    command failure (network down, no remote) is reported as 'fetch failed',
    never treated as zero lag. Only a genuine git-launch failure (binary
    missing) is fatal; that bubbles as WatchdogFatalError from _git()."""
    fetch = _git(["fetch", "origin"], vault_root)
    if fetch.returncode != 0:
        return "fetch failed"
    rev_list = _git(
        ["rev-list", "--left-right", "--count", "main...origin/main"], vault_root
    )
    if rev_list.returncode != 0:
        return "rev-list failed"
    parts = rev_list.stdout.split()
    if len(parts) != 2:
        return "rev-list output unparseable"
    ahead = int(parts[0])
    if ahead > 0:
        return f"{ahead} commit(s) ahead of origin/main (unpushed)"
    return None


def check_auto_commit_artifact(
    vault_root: Path, now: datetime, max_age_minutes: int = AUTO_COMMIT_MAX_AGE_MINUTES
) -> ArtifactVerdict:
    status = _git(["status", "--porcelain"], vault_root)
    if status.returncode != 0:
        return ArtifactVerdict("ERROR", "git status failed", alert="git status failed")
    dirty = bool(status.stdout.strip())
    if not dirty:
        return ArtifactVerdict("PASS", "working tree clean, no new commits required")

    log = _git(["log", "-1", "--format=%cI"], vault_root)
    if log.returncode != 0 or not log.stdout.strip():
        return ArtifactVerdict("ERROR", "git log failed", alert="git log failed")
    commit_iso = log.stdout.strip()
    commit_dt = _parse_iso(commit_iso)
    age = now - commit_dt
    age_display = _format_age(age)
    if age > timedelta(minutes=max_age_minutes):
        detail = f"dirty tree, newest commit age {age_display} exceeds {max_age_minutes}m"
        return ArtifactVerdict("STALE", detail, age_display, since=commit_iso, alert=detail)
    return ArtifactVerdict(
        "PASS", f"dirty tree, newest commit age {age_display} within {max_age_minutes}m",
        age_display, since=commit_iso,
    )


def check_observability_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    verify_path = vault_root / VAULT_METRICS_VERIFY_REL
    reasons = []
    since = None
    age_display = "n/a"
    if not verify_path.exists():
        reasons.append(f"{VAULT_METRICS_VERIFY_REL} not found")
    else:
        try:
            lines = [ln for ln in verify_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not lines:
                reasons.append(f"{VAULT_METRICS_VERIFY_REL} has no rows")
            else:
                last_row = json.loads(lines[-1])
                verified_at = last_row.get("verified_at")
                if not verified_at:
                    reasons.append(f"{VAULT_METRICS_VERIFY_REL} newest row has no verified_at")
                else:
                    since = verified_at
                    age = now - _parse_iso(verified_at)
                    age_display = _format_age(age)
                    if age > timedelta(hours=OBSERVABILITY_MAX_AGE_HOURS):
                        reasons.append(
                            f"vault-metrics-verify.jsonl newest row age {age_display} "
                            f"exceeds {OBSERVABILITY_MAX_AGE_HOURS}h"
                        )
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            reasons.append(f"{VAULT_METRICS_VERIFY_REL} unreadable: {exc}")

    digest_path = vault_root / DAILY_DIGEST_REL
    if not digest_path.exists():
        reasons.append(f"{DAILY_DIGEST_REL} not found")
    else:
        mtime = datetime.fromtimestamp(digest_path.stat().st_mtime, tz=timezone.utc)
        age = now - mtime
        if age > timedelta(hours=OBSERVABILITY_MAX_AGE_HOURS):
            reasons.append(
                f"daily-digest.md mtime age {_format_age(age)} exceeds {OBSERVABILITY_MAX_AGE_HOURS}h"
            )

    if reasons:
        return ArtifactVerdict("STALE", "; ".join(reasons), age_display, since=since,
                                alert="; ".join(reasons))
    return ArtifactVerdict("PASS", f"verify row age {age_display} within "
                            f"{OBSERVABILITY_MAX_AGE_HOURS}h; digest fresh", age_display, since=since)


def _newest_lint_report(vault_root: Path):
    """Return (date_str, path) for the newest *-lint-report.md by filename
    date, or (None, None) if none exist. Filename date, not mtime: the
    lint-verifier rule matches a verify file by the same date string."""
    sweeps_dir = vault_root / LINT_SWEEPS_DIR_REL
    if not sweeps_dir.is_dir():
        return None, None
    pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})-lint-report\.md$")
    best_date, best_path = None, None
    for p in sweeps_dir.glob("*-lint-report.md"):
        m = pattern.match(p.name)
        if not m:
            continue
        if best_date is None or m.group(1) > best_date:
            best_date, best_path = m.group(1), p
    return best_date, best_path


def check_lint_sweep_artifact(
    vault_root: Path, now: datetime, max_age_days: int = LINT_SWEEP_MAX_AGE_DAYS
) -> ArtifactVerdict:
    date_str, path = _newest_lint_report(vault_root)
    if date_str is None:
        return ArtifactVerdict("ERROR", "no lint report found", alert="no lint report found")
    report_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    age = now - report_date
    age_display = _format_age(age)
    if age > timedelta(days=max_age_days):
        detail = f"newest lint report ({date_str}) age {age_display} exceeds {max_age_days}d"
        return ArtifactVerdict("STALE", detail, age_display, since=date_str, alert=detail)
    return ArtifactVerdict(
        "PASS", f"newest lint report ({date_str}) age {age_display} within {max_age_days}d",
        age_display, since=date_str,
    )


def check_lint_verifier_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    date_str, _ = _newest_lint_report(vault_root)
    if date_str is None:
        return ArtifactVerdict("ERROR", "no lint report found to match", alert="no lint report found to match")
    verify_path = vault_root / LINT_SWEEPS_DIR_REL / f"{date_str}-lint-verify.json"
    if not verify_path.exists():
        detail = f"missing {date_str}-lint-verify.json for newest report"
        return ArtifactVerdict("STALE", detail, since=date_str, alert=detail)
    return ArtifactVerdict(
        "PASS", f"{date_str}-lint-verify.json present for newest report", since=date_str
    )


def check_trust_ledger_artifact(
    vault_root: Path, now: datetime, max_age_days: int = TRUST_LEDGER_MAX_AGE_DAYS
) -> ArtifactVerdict:
    path = vault_root / TRUST_LEDGER_REL
    if not path.exists():
        return ArtifactVerdict("ERROR", "ledger not found", alert="ledger not found")
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return ArtifactVerdict("ERROR", "ledger has no rows", alert="ledger has no rows")
    try:
        row = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return ArtifactVerdict("ERROR", f"ledger newest row unparseable: {exc}",
                                alert=f"ledger newest row unparseable: {exc}")
    cycle_iso = row.get("cycle_iso")
    reasons = []
    age_display = "n/a"
    if not cycle_iso:
        reasons.append("newest row has no cycle_iso")
    else:
        age = now - _parse_iso(cycle_iso)
        age_display = _format_age(age)
        if age > timedelta(days=max_age_days):
            reasons.append(f"newest row age {age_display} exceeds {max_age_days}d")
    contract_result = (row.get("contract") or {}).get("result")
    if contract_result == "FAIL":
        reasons.append("contract.result=FAIL")
    if reasons:
        return ArtifactVerdict("STALE", "; ".join(reasons), age_display, since=cycle_iso,
                                alert="; ".join(reasons))
    return ArtifactVerdict("PASS", f"age {age_display} within {max_age_days}d; contract PASS",
                            age_display, since=cycle_iso)


def check_actions_minutes_artifact(
    vault_root: Path, now: datetime, client=None, token_loader=None
) -> ArtifactVerdict:
    """LOCAL-mode-only fallback (self-heal phase (a) TASK-006) for the exact
    scenario PLATFORM C3 names: once GitHub Actions itself runs out of
    minutes, its own Actions-hosted watchdog goes silent and cannot report
    the outage. Reuses actions_dispatch_test.py's own client/token loading
    and get_minutes_summary rather than re-deriving the billing-usage call.
    Never raises: an absent token, an import failure, a failed API call, or
    a malformed/reshaped API response all degrade to N/A/ERROR, never a
    crash and never a confident PASS on unconfirmed data (fix pass item
    10). Must be wired into evaluate_fleet only, never into
    REPO_OUTCOME_CHECKS/evaluate_repo_outcomes, since that path runs INSIDE
    a GitHub Actions runner and exists precisely to keep working when
    Actions itself has gone silent.

    token_loader (fix pass item 6, optional): when given, replaces
    actions_dispatch_test.load_token entirely, so a caller can prove the
    no-token path without depending on sys.modules identity at all.
    Defaults to the dynamically imported load_token."""
    try:
        from actions_dispatch_test import (
            DEFAULT_REPO, GitHubClient, get_minutes_summary, load_token,
        )
    except ImportError as exc:
        detail = f"actions minutes check failed to import: {exc}"
        return ArtifactVerdict("ERROR", detail, alert=detail)

    if token_loader is None:
        token_loader = load_token

    if client is None:
        try:
            token = token_loader()
        except RuntimeError:
            return ArtifactVerdict(
                "N/A", "actions minutes check unavailable: no GitHub token configured")
        client = GitHubClient(token=token, repo=DEFAULT_REPO)

    try:
        summary = get_minutes_summary(client, now_fn=lambda: now)
    except Exception as exc:  # noqa: BLE001 - any API failure degrades, never crashes
        detail = f"actions minutes check failed: {exc}"
        return ArtifactVerdict("ERROR", detail, alert=detail)

    # A reshaped/broken billing response degrades to ERROR, never a
    # confident PASS (fix pass item 10, adversarial review probe 7: a 200
    # response missing every expected key previously read as "0 usage" and
    # reported full health -- exactly backwards for a check whose entire
    # purpose is being the last line of defense when Actions itself has
    # gone silent). A well-formed /user response always carries a real
    # login; "unknown" is get_minutes_summary's own fallback for a missing
    # or empty response body.
    if not summary.get("login") or summary.get("login") == "unknown":
        detail = "unexpected billing response shape (no login in /user response)"
        return ArtifactVerdict("ERROR", detail, alert=detail)

    repo = getattr(client, "repo", DEFAULT_REPO)
    consumed = summary.get("current_month", {}).get("per_repo", {}).get(repo, 0.0)
    remaining = GITHUB_FREE_TIER_INCLUDED_MINUTES - consumed
    if remaining < ACTIONS_MINUTES_ALERT_THRESHOLD:
        detail = (
            f"{remaining:.0f} Actions minutes remaining this month "
            f"(threshold {ACTIONS_MINUTES_ALERT_THRESHOLD} of "
            f"{GITHUB_FREE_TIER_INCLUDED_MINUTES})"
        )
        return ArtifactVerdict("ERROR", detail, alert=detail)
    return ArtifactVerdict("PASS", f"{remaining:.0f} Actions minutes remaining this month")


_ARTIFACT_CHECKS = {
    "backup": check_backup_artifact,
    "auto_commit": check_auto_commit_artifact,
    "observability": check_observability_artifact,
    "lint_sweep": check_lint_sweep_artifact,
    "lint_verifier": check_lint_verifier_artifact,
}


# ---------------------------------------------------------------------------
# Repo-outcomes-only checks (TASK-014)
# ---------------------------------------------------------------------------


def _is_bot_commit(author_name: str, author_email: str) -> bool:
    """A commit counts as bot-authored on EITHER signal (architect review
    2026-09-16, Phase 3 HIGH): the author name matches BOT_AUTHOR_NAME
    byte-for-byte, or the author email ends with BOT_AUTHOR_EMAIL_SUFFIX.
    The OR (not AND) means a cosmetic display-name change in a sibling
    workflow's git identity still gets caught by the email suffix alone."""
    return author_name == BOT_AUTHOR_NAME or author_email.endswith(BOT_AUTHOR_EMAIL_SUFFIX)


def _check_last_non_bot_commit_age(
    vault_root: Path, now: datetime, max_age_hours: int = BACKUP_MAX_AGE_HOURS
) -> Optional[str]:
    """Age of the newest commit on HEAD not authored by the bot identity
    (see _is_bot_commit). Stands in for check_backup_artifact's fetch/rev-list
    origin-lag check on a runner where origin/main IS the checked-out HEAD:
    the last laptop-originated push is the newest non-bot commit. A git
    failure is reported as a reason string, never treated as zero age."""
    log = _git(["log", "--format=%H%x1f%aI%x1f%an%x1f%ae"], vault_root)
    if log.returncode != 0:
        return "git log failed"
    for line in log.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        _commit_hash, author_iso, author_name, author_email = parts
        if _is_bot_commit(author_name, author_email):
            continue
        try:
            commit_dt = _parse_iso(author_iso)
        except ValueError:
            continue
        age = now - commit_dt
        age_display = _format_age(age)
        if age > timedelta(hours=max_age_hours):
            return f"newest non-bot commit age {age_display} exceeds {max_age_hours}h"
        return None
    return "no non-bot commit found in history"


def _check_backup_sha_is_ancestor(vault_root: Path, commit_sha) -> Optional[str]:
    """Whether vault-backup.json's own commit_sha is an ancestor of HEAD. If
    not, the laptop's last backup never reached origin (a lost/orphaned local
    commit), the repo-outcomes-only equivalent of an unpushed local commit."""
    if not commit_sha:
        return "vault-backup.json has no commit_sha"
    exists = _git(["cat-file", "-e", f"{commit_sha}^{{commit}}"], vault_root)
    if exists.returncode != 0:
        return f"commit_sha {commit_sha!r} not found in repo history"
    is_ancestor = _git(["merge-base", "--is-ancestor", str(commit_sha), "HEAD"], vault_root)
    if is_ancestor.returncode != 0:
        return f"commit_sha {commit_sha!r} is not an ancestor of HEAD (laptop backup never reached origin)"
    return None


def check_backup_artifact_repo_outcomes(vault_root: Path, now: datetime) -> ArtifactVerdict:
    """Repo-outcomes-only translation of check_backup_artifact (TASK-014,
    TASK-015). On a GitHub Actions runner origin/main IS the checked-out
    HEAD, so check_backup_artifact's fetch+rev-list origin-lag check cannot
    detect anything. Substitutes two repo-visible signals instead: the age
    of the newest non-bot commit on HEAD (the last laptop-originated push),
    and whether vault-backup.json's commit_sha is an ancestor of HEAD.
    Reuses BACKUP_MAX_AGE_HOURS and BACKUP_OK_RESULTS, the same thresholds
    check_backup_artifact uses."""
    path = vault_root / BACKUP_STATE_REL
    if not path.exists():
        return ArtifactVerdict("ERROR", "state file not found", alert="state file not found")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ArtifactVerdict("ERROR", f"state file unreadable: {exc}",
                                alert=f"state file unreadable: {exc}")

    reasons, since, age_display = _backup_state_reasons(data, now)

    commit_age_reason = _check_last_non_bot_commit_age(vault_root, now)
    if commit_age_reason:
        reasons.append(commit_age_reason)

    sha_reason = _check_backup_sha_is_ancestor(vault_root, data.get("commit_sha"))
    if sha_reason:
        reasons.append(sha_reason)

    if reasons:
        return ArtifactVerdict("STALE", "; ".join(reasons), age_display, since=since,
                                alert="; ".join(reasons))
    return ArtifactVerdict(
        "PASS",
        f"age {age_display} within {BACKUP_MAX_AGE_HOURS}h max; result ok; "
        "last laptop-authored commit within window; commit_sha reached origin",
        age_display, since=since,
    )


def check_docs_stamp_artifact(
    vault_root: Path, now: datetime, max_age_hours: int = OBSERVABILITY_MAX_AGE_HOURS
) -> ArtifactVerdict:
    """Docs-regen freshness (TASK-015). Prefers the generator-written
    generated_at field in _generated.json; falls back to the harness docs
    directory's own mtime only when that file is absent, and names the
    RISK-004 limitation in the detail when it does: directory mtime only
    reflects writes to the directory's own immediate entries, not files the
    generator writes into subfolders, and can read stale even right after a
    run (2026-09-15-telemetry-loop-synthesis.md, Increment 3). Reuses
    OBSERVABILITY_MAX_AGE_HOURS: docs regen runs daily, the same cadence
    assumption that threshold already encodes."""
    generated_path = vault_root / DOCS_GENERATED_JSON_REL
    if generated_path.exists():
        try:
            data = json.loads(generated_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ArtifactVerdict("ERROR", f"{DOCS_GENERATED_JSON_REL} unreadable: {exc}",
                                    alert=f"{DOCS_GENERATED_JSON_REL} unreadable: {exc}")
        generated_at = data.get("generated_at")
        if not generated_at:
            return ArtifactVerdict("ERROR", f"{DOCS_GENERATED_JSON_REL} has no generated_at",
                                    alert=f"{DOCS_GENERATED_JSON_REL} has no generated_at")
        age = now - _parse_iso(generated_at)
        age_display = _format_age(age)
        if age > timedelta(hours=max_age_hours):
            detail = f"docs stamp (generated_at) age {age_display} exceeds {max_age_hours}h"
            return ArtifactVerdict("STALE", detail, age_display, since=generated_at, alert=detail)
        return ArtifactVerdict(
            "PASS", f"docs stamp (generated_at) age {age_display} within {max_age_hours}h",
            age_display, since=generated_at,
        )

    docs_dir = vault_root / DOCS_HARNESS_DIR_REL
    if not docs_dir.is_dir():
        return ArtifactVerdict("ERROR", f"{DOCS_HARNESS_DIR_REL} not found",
                                alert=f"{DOCS_HARNESS_DIR_REL} not found")
    mtime = datetime.fromtimestamp(docs_dir.stat().st_mtime, tz=timezone.utc)
    age = now - mtime
    age_display = _format_age(age)
    since = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
    risk_note = (
        "RISK-004: mtime fallback, directory mtime does not reflect writes into "
        "subfolders and can read stale even right after a run"
    )
    if age > timedelta(hours=max_age_hours):
        detail = f"docs dir mtime age {age_display} exceeds {max_age_hours}h ({risk_note})"
        return ArtifactVerdict("STALE", detail, age_display, since=since, alert=detail)
    return ArtifactVerdict(
        "PASS", f"docs dir mtime age {age_display} within {max_age_hours}h ({risk_note})",
        age_display, since=since,
    )


def check_owner_digest_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    """Owner-digest last-send proof-of-life (TASK-041, TASK-015). The routine
    that writes this file is Phase 5, not yet built: absence is informational
    (verdict N/A, never an alert) until it ships. Once present, alerts when
    sent_at ages past the file's own cadence_hours plus one grace cycle
    (2x cadence_hours total), per TASK-041's contract."""
    path = vault_root / OWNER_DIGEST_LAST_SEND_REL
    if not path.exists():
        return ArtifactVerdict("N/A", "not configured yet")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ArtifactVerdict("ERROR", f"{OWNER_DIGEST_LAST_SEND_REL} unreadable: {exc}",
                                alert=f"{OWNER_DIGEST_LAST_SEND_REL} unreadable: {exc}")
    sent_at = data.get("sent_at")
    if not sent_at:
        return ArtifactVerdict("ERROR", f"{OWNER_DIGEST_LAST_SEND_REL} has no sent_at",
                                alert=f"{OWNER_DIGEST_LAST_SEND_REL} has no sent_at")
    try:
        cadence_hours = float(data.get("cadence_hours"))
    except (TypeError, ValueError):
        return ArtifactVerdict("ERROR", f"{OWNER_DIGEST_LAST_SEND_REL} has no usable cadence_hours",
                                alert=f"{OWNER_DIGEST_LAST_SEND_REL} has no usable cadence_hours")
    age = now - _parse_iso(sent_at)
    age_display = _format_age(age)
    max_age = timedelta(hours=cadence_hours * 2)
    if age > max_age:
        detail = f"sent_at age {age_display} exceeds cadence {cadence_hours}h plus one grace cycle"
        return ArtifactVerdict("STALE", detail, age_display, since=sent_at, alert=detail)
    return ArtifactVerdict(
        "PASS",
        f"sent_at age {age_display} within cadence {cadence_hours}h plus one grace cycle",
        age_display, since=sent_at,
    )


# ---------------------------------------------------------------------------
# Self-heal phase (c) checks (TASK-032a through TASK-032d, spec section 5)
# ---------------------------------------------------------------------------

_RETENTION_LAST_ROWS_RE = re.compile(r"^last (\d+) rows$")
_RETENTION_DAYS_RE = re.compile(r"^(\d+) days$")
_RETENTION_DAYS_ACTIVE_RE = re.compile(r"^(\d+) days active")
_RETENTION_LAST_PLUS_PER_MONTH_RE = re.compile(r"^last (\d+) plus (\d+) per month$")


def _retention_class_entry(data: dict, class_name: str) -> Optional[dict]:
    for entry in data.get("artifacts", []) or []:
        if isinstance(entry, dict) and entry.get("class") == class_name:
            return entry
    return None


def _retention_parse_error(class_name: str, entry: dict) -> ArtifactVerdict:
    """Fail closed (phase (c) adversarial review, NEEDS CHANGE): a retention
    string the parser does not understand is an ERROR row, never a silent
    fall-back to a hardcoded cap."""
    detail = (f"{RETENTION_JSON_REL}: retention string for {class_name!r} not "
              f"parseable: {str(entry.get('retention', ''))!r}")
    return ArtifactVerdict("ERROR", detail, alert=detail)


def check_retention_caps_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    """TASK-032a. Reads retention.json and mechanically evaluates the four
    classes whose own retention string names a single, checkable cap:

    - trust-ledger: "last N rows" -> line count of the trust ledger jsonl.
    - work-backups: "N days" -> mtime age of every Projects/*/work/backups/*
      file.
    - experience-daily: "N days active, ..." -> the leading number is read as
      a FILE-COUNT cap over Resources/Observability/experience/*.json, a
      documented simplification of the archive-rollover rule (a true
      day-window check needs the archive-move logic this watchdog does not
      own); a live count over the cap is the cheap, mechanical proxy for "the
      exporter has stopped rolling files into experience/archive/<YYYY-MM>/".
    - lint-reports: "last N plus M per month" -> the newest N reports are
      always exempt; among the rest, any single calendar month carrying more
      than M reports is a breach.

    The remaining retention.json classes (review-build-records,
    watchdog-issue, self-heal-promotion-state, self-heal-open-prs) have no
    single mechanically parseable cap (a free-text policy, a GitHub-native
    object, or a cap already enforced elsewhere at construction time); each
    renders as "<class>: not mechanically capped" in the detail rather than
    being silently skipped. A missing or unreadable retention.json is ERROR,
    never a crash; a breach on any parseable class returns STALE (this
    file's existing convention for a threshold violation) naming the class
    and its excess over cap."""
    path = vault_root / RETENTION_JSON_REL
    if not path.exists():
        detail = f"{RETENTION_JSON_REL} not found"
        return ArtifactVerdict("ERROR", detail, alert=detail)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        detail = f"{RETENTION_JSON_REL} unreadable: {exc}"
        return ArtifactVerdict("ERROR", detail, alert=detail)

    breach_lines: list = []
    ok_lines: list = []

    entry = _retention_class_entry(data, "trust-ledger")
    if entry is not None:
        match = _RETENTION_LAST_ROWS_RE.match(str(entry.get("retention", "")))
        if not match:
            return _retention_parse_error("trust-ledger", entry)
        cap = int(match.group(1))
        ledger_path = vault_root / TRUST_LEDGER_REL
        count = 0
        if ledger_path.exists():
            count = sum(
                1 for ln in ledger_path.read_text(encoding="utf-8").splitlines() if ln.strip()
            )
        if count > cap:
            breach_lines.append(
                f"trust-ledger: {count} rows exceeds cap {cap} (excess {count - cap})"
            )
        else:
            ok_lines.append(f"trust-ledger: {count}/{cap} rows")

    entry = _retention_class_entry(data, "work-backups")
    if entry is not None:
        match = _RETENTION_DAYS_RE.match(str(entry.get("retention", "")))
        if not match:
            return _retention_parse_error("work-backups", entry)
        cap_days = int(match.group(1))
        offenders = []
        for p in vault_root.glob(WORK_BACKUPS_GLOB_REL):
            if not p.is_file():
                continue
            age = now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if age > timedelta(days=cap_days):
                offenders.append(age)
        if offenders:
            oldest = max(offenders)
            breach_lines.append(
                f"work-backups: {len(offenders)} file(s) exceed {cap_days}d "
                f"(oldest age {_format_age(oldest)})"
            )
        else:
            ok_lines.append(f"work-backups: within {cap_days}d")

    entry = _retention_class_entry(data, "experience-daily")
    if entry is not None:
        match = _RETENTION_DAYS_ACTIVE_RE.match(str(entry.get("retention", "")))
        if not match:
            return _retention_parse_error("experience-daily", entry)
        cap_files = int(match.group(1))
        files = [p for p in vault_root.glob(EXPERIENCE_DAILY_GLOB_REL) if p.is_file()]
        count = len(files)
        if count > cap_files:
            breach_lines.append(
                f"experience-daily: {count} files exceeds cap {cap_files} "
                f"(excess {count - cap_files})"
            )
        else:
            ok_lines.append(f"experience-daily: {count}/{cap_files} files")

    entry = _retention_class_entry(data, "lint-reports")
    if entry is not None:
        match = _RETENTION_LAST_PLUS_PER_MONTH_RE.match(str(entry.get("retention", "")))
        if not match:
            return _retention_parse_error("lint-reports", entry)
        keep_newest = int(match.group(1))
        per_month_cap = int(match.group(2))
        dated: list = []
        sweeps_dir = vault_root / LINT_SWEEPS_DIR_REL
        if sweeps_dir.is_dir():
            pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})-lint-report\.md$")
            for p in sweeps_dir.glob("*-lint-report.md"):
                m = pattern.match(p.name)
                if m:
                    dated.append(m.group(1))
        dated.sort(reverse=True)
        older = dated[keep_newest:]
        month_counts: dict = {}
        for date_str in older:
            month = date_str[:7]
            month_counts[month] = month_counts.get(month, 0) + 1
        offending = {mo: c for mo, c in month_counts.items() if c > per_month_cap}
        if offending:
            names = ", ".join(f"{mo} has {c}" for mo, c in sorted(offending.items()))
            excess = sum(c - per_month_cap for c in offending.values())
            breach_lines.append(
                f"lint-reports: {names} report(s) (cap {per_month_cap}/month among "
                f"non-newest-{keep_newest}, excess {excess})"
            )
        else:
            ok_lines.append(
                f"lint-reports: {len(dated)} report(s), newest {keep_newest} exempt, "
                f"remainder within {per_month_cap}/month"
            )

    na_lines = [
        f"{a.get('class')}: not mechanically capped"
        for a in data.get("artifacts", []) or []
        if isinstance(a, dict)
        and a.get("class") not in SELF_HEAL_MECHANICALLY_CAPPED_RETENTION_CLASSES
    ]

    if breach_lines:
        detail = "; ".join(breach_lines)
        return ArtifactVerdict("STALE", detail, alert=detail)

    detail = "; ".join(ok_lines + na_lines) if (ok_lines or na_lines) else "no retention classes evaluated"
    return ArtifactVerdict("PASS", detail)


def check_needs_owner_prs_artifact(
    vault_root: Path, now: datetime, run_fn=subprocess.run
) -> ArtifactVerdict:
    """TASK-032b. Shells to `gh pr list --label needs-owner --state open
    --json number,createdAt,title` (no --repo flag: gh infers the repo from
    the checked-out cwd, matching this workflow's own runner checkout) via
    run_fn, matching this file's existing run_fn=subprocess.run convention
    (check_actions_minutes_artifact's client= param plays the same role for
    its own injectable dependency). GH_TOKEN is read by gh from the ambient
    environment the caller already set (the workflow passes
    secrets.GITHUB_TOKEN); this function never reads or sets it directly. No
    token, gh not installed, a non-zero gh exit, or an unparseable/reshaped
    response all degrade to N/A "unavailable", never a crash: this check's
    own failure must never read as a healthy PASS. Alerts (STALE) when any
    returned PR's createdAt age exceeds NEEDS_OWNER_PR_MAX_AGE_DAYS; always
    renders the open count and the oldest PR's age."""
    try:
        proc = run_fn(
            ["gh", "pr", "list", "--label", "needs-owner", "--state", "open",
             "--json", "number,createdAt,title"],
            cwd=str(vault_root), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ArtifactVerdict("N/A", f"needs-owner PR check unavailable: {exc}")

    if proc.returncode != 0:
        detail = (getattr(proc, "stderr", "") or "gh pr list failed").strip()[:300]
        return ArtifactVerdict("N/A", f"needs-owner PR check unavailable: {detail}")

    try:
        prs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return ArtifactVerdict(
            "N/A", f"needs-owner PR check unavailable: unparseable gh output ({exc})"
        )
    if not isinstance(prs, list):
        return ArtifactVerdict("N/A", "needs-owner PR check unavailable: unexpected gh output shape")

    count = len(prs)
    if count == 0:
        return ArtifactVerdict("PASS", "0 open needs-owner PR(s)")

    oldest_pr = None
    oldest_age = None
    for pr in prs:
        created_at = pr.get("createdAt") if isinstance(pr, dict) else None
        if not created_at:
            continue
        try:
            age = now - _parse_iso(created_at)
        except ValueError:
            continue
        if oldest_age is None or age > oldest_age:
            oldest_age = age
            oldest_pr = pr

    if oldest_age is None:
        return ArtifactVerdict("N/A", f"{count} open needs-owner PR(s), no usable createdAt field")

    age_display = _format_age(oldest_age)
    if oldest_age > timedelta(days=NEEDS_OWNER_PR_MAX_AGE_DAYS):
        detail = (
            f"{count} open needs-owner PR(s); oldest (#{oldest_pr.get('number')}) "
            f"age {age_display} exceeds {NEEDS_OWNER_PR_MAX_AGE_DAYS}d"
        )
        return ArtifactVerdict("STALE", detail, age_display, alert=detail)

    return ArtifactVerdict(
        "PASS",
        f"{count} open needs-owner PR(s), oldest age {age_display} within "
        f"{NEEDS_OWNER_PR_MAX_AGE_DAYS}d",
        age_display,
    )


def _check_self_heal_token_age(
    vault_root: Path, now: datetime, rel_path: str, label: str
) -> ArtifactVerdict:
    """Shared body for check_oauth_token_age_artifact and
    check_push_token_age_artifact (TASK-032c, TASK-032d): both read a single
    date-only line, both alert at the same runway threshold. Mirrors
    _backup_state_reasons's own single-source-for-two-callers shape."""
    path = vault_root / rel_path
    if not path.exists():
        return ArtifactVerdict("N/A", "not minted yet")
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        detail = f"{rel_path} unreadable: {exc}"
        return ArtifactVerdict("ERROR", detail, alert=detail)
    if not text:
        detail = f"{rel_path} is empty"
        return ArtifactVerdict("ERROR", detail, alert=detail)
    try:
        minted_dt = datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        detail = f"{rel_path} unparseable date {text!r}: {exc}"
        return ArtifactVerdict("ERROR", detail, alert=detail)

    age = now - minted_dt
    age_display = _format_age(age)
    if age > timedelta(days=SELF_HEAL_TOKEN_AGE_ALERT_THRESHOLD_DAYS):
        detail = (
            f"{label} age {age_display} exceeds "
            f"{SELF_HEAL_TOKEN_AGE_ALERT_THRESHOLD_DAYS}d (30 days of runway before "
            "1-year expiry)"
        )
        return ArtifactVerdict("STALE", detail, age_display, since=text, alert=detail)
    return ArtifactVerdict(
        "PASS",
        f"{label} age {age_display} within {SELF_HEAL_TOKEN_AGE_ALERT_THRESHOLD_DAYS}d",
        age_display, since=text,
    )


def check_oauth_token_age_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    """TASK-032c. Reads .claude/self-heal/token-minted-at.txt (a date-only
    line, never the token value). Missing file (not minted yet, TASK-014 not
    run) is N/A, never an alert."""
    return _check_self_heal_token_age(
        vault_root, now, TOKEN_MINTED_AT_REL, "self-heal OAuth token"
    )


def check_push_token_age_artifact(vault_root: Path, now: datetime) -> ArtifactVerdict:
    """TASK-032d. Reads .claude/self-heal/push-token-minted-at.txt, same
    shape and threshold as check_oauth_token_age_artifact (spec section 5
    item 4: "mirroring check 3's own 30-days-of-runway alert threshold
    exactly")."""
    return _check_self_heal_token_age(
        vault_root, now, PUSH_TOKEN_MINTED_AT_REL, "self-heal PAT"
    )


def check_self_heal_round_artifact(
    vault_root: Path, now: datetime, run_fn=subprocess.run
) -> ArtifactVerdict:
    """Autonomy plan step 1.7. A self-heal round that never ran sends no
    failure mail: GitHub may delay or drop the schedule, and a disabled
    workflow is silent. Shells to `gh run list` for SCHEDULED runs of the loop
    workflow only (a manual test dispatch must never mask a missed scheduled
    round), same run_fn and GH_TOKEN convention as
    check_needs_owner_prs_artifact; needs `actions: read` on the workflow.
    STALE when the newest COMPLETED scheduled round finished more than
    SELF_HEAL_ROUND_MAX_AGE_HOURS ago, or none is listed. ERROR when that
    round finished in time but did not conclude `success`. A gh failure or a
    reshaped response degrades to N/A, never to PASS."""
    try:
        proc = run_fn(
            ["gh", "run", "list", "--workflow", SELF_HEAL_WORKFLOW_FILE,
             "--event", "schedule", "--limit", "20",
             "--json", "databaseId,status,conclusion,updatedAt"],
            cwd=str(vault_root), capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ArtifactVerdict("N/A", f"self-heal round check unavailable: {exc}")

    if proc.returncode != 0:
        detail = (getattr(proc, "stderr", "") or "gh run list failed").strip()[:300]
        return ArtifactVerdict("N/A", f"self-heal round check unavailable: {detail}")

    try:
        runs = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        return ArtifactVerdict(
            "N/A", f"self-heal round check unavailable: unparseable gh output ({exc})"
        )
    if not isinstance(runs, list):
        return ArtifactVerdict("N/A", "self-heal round check unavailable: unexpected gh output shape")

    newest = None
    newest_finished = None
    for run in runs:
        if not isinstance(run, dict) or run.get("status") != "completed":
            continue
        # `gh run list --json` exposes no completed-at field. updatedAt is the
        # run-level timestamp of the last state change, which for a completed
        # run is its completion. Anything that later mutates a finished run
        # (a re-run, a log deletion) would move it; nothing in this repo does.
        try:
            finished = _parse_iso(run.get("updatedAt") or "")
        except ValueError:
            continue
        if newest_finished is None or finished > newest_finished:
            newest, newest_finished = run, finished

    if newest is None:
        detail = (
            f"no completed scheduled self-heal round among the last {len(runs)} listed; "
            f"expected one inside {SELF_HEAL_ROUND_MAX_AGE_HOURS}h"
        )
        return ArtifactVerdict("STALE", detail, alert=detail)

    age = now - newest_finished
    age_display = _format_age(age)
    since = newest.get("updatedAt")
    run_id = newest.get("databaseId")
    conclusion = newest.get("conclusion") or "unknown"
    if age > timedelta(hours=SELF_HEAL_ROUND_MAX_AGE_HOURS):
        detail = (
            f"last scheduled self-heal round ({run_id}) finished {age_display} ago, "
            f"exceeds {SELF_HEAL_ROUND_MAX_AGE_HOURS}h"
        )
        return ArtifactVerdict("STALE", detail, age_display, since, alert=detail)
    if conclusion != "success":
        detail = (
            f"last scheduled self-heal round ({run_id}) concluded {conclusion} "
            f"{age_display} ago"
        )
        return ArtifactVerdict("ERROR", detail, age_display, since, alert=detail)
    return ArtifactVerdict(
        "PASS",
        f"last scheduled self-heal round ({run_id}) concluded success {age_display} ago, "
        f"within {SELF_HEAL_ROUND_MAX_AGE_HOURS}h",
        age_display, since,
    )


REPO_OUTCOME_CHECKS = [
    ("backup (origin outcome)", check_backup_artifact_repo_outcomes),
    ("lint sweep", check_lint_sweep_artifact),
    ("lint verifier", check_lint_verifier_artifact),
    (TRUST_LEDGER_ID, check_trust_ledger_artifact),
    ("observability digest", check_observability_artifact),
    ("docs stamp", check_docs_stamp_artifact),
    ("owner digest last-send", check_owner_digest_artifact),
    ("retention cap breach", check_retention_caps_artifact),
    ("needs-owner PR age", check_needs_owner_prs_artifact),
    ("self-heal OAuth token age", check_oauth_token_age_artifact),
    ("self-heal PAT age", check_push_token_age_artifact),
    ("self-heal round", check_self_heal_round_artifact),
]


# ---------------------------------------------------------------------------
# Fleet evaluation
# ---------------------------------------------------------------------------


def evaluate_fleet(tasks: list, vault_root: Path, now: datetime) -> FleetResult:
    result = FleetResult()
    for task in tasks:
        name = task.get("TaskName", "unknown")
        state = task.get("State", "unknown")
        last_run_dt = parse_dotnet_date(task.get("LastRunTime"))
        next_run_dt = parse_dotnet_date(task.get("NextRunTime"))
        raw_code = task.get("LastTaskResult")

        reasons = []
        try:
            code_int = int(raw_code)
        except (TypeError, ValueError):
            code_int = None
        if code_int is not None and code_int != 0 and code_int not in INFORMATIONAL_RESULT_CODES:
            since = last_run_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if last_run_dt else "unknown"
            reasons.append((f"scheduler result {result_code_display(code_int)}", since))

        kind = TASK_ARTIFACT_RULES.get(name)
        artifact = ArtifactVerdict("N/A", "no artifact rule for this task")
        if kind:
            checker = _ARTIFACT_CHECKS[kind]
            artifact = checker(vault_root, now)
            if artifact.alert:
                reasons.append((artifact.alert, artifact.since or "unknown"))

        alert_text = None
        if reasons:
            detail = "; ".join(r for r, _ in reasons)
            since = reasons[0][1]
            alert_text = f"{name}: {detail}, since {since}"
            result.alerts.append(alert_text)

        result.rows.append(
            TaskRow(
                name=name,
                state=state,
                last_run_display=last_run_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if last_run_dt else "n/a",
                result_display=result_code_display(code_int) if code_int is not None else "n/a",
                next_run_display=next_run_dt.strftime("%Y-%m-%dT%H:%M:%SZ") if next_run_dt else "n/a",
                artifact=artifact,
                alert_text=alert_text,
            )
        )

    trust_verdict = check_trust_ledger_artifact(vault_root, now)
    result.trust_ledger = trust_verdict
    if trust_verdict.alert:
        since = trust_verdict.since or "unknown"
        result.alerts.append(f"{TRUST_LEDGER_ID}: {trust_verdict.alert}, since {since}")

    # Fleet-artifact-only, LOCAL mode only (PAT-003, TASK-006): never wired
    # into REPO_OUTCOME_CHECKS/evaluate_repo_outcomes.
    actions_minutes_verdict = check_actions_minutes_artifact(vault_root, now)
    result.actions_minutes = actions_minutes_verdict
    if actions_minutes_verdict.alert:
        since = actions_minutes_verdict.since or "unknown"
        result.alerts.append(
            f"{ACTIONS_MINUTES_ID}: {actions_minutes_verdict.alert}, since {since}")

    return result


def evaluate_repo_outcomes(vault_root: Path, now: datetime) -> FleetResult:
    """TASK-014 runner-safe entry point body. Repo-visible checks only: no
    PowerShell task enumeration, no backup retry. Reuses the same per-check
    functions (and their thresholds) the local fleet path uses wherever a
    check has no PowerShell/Task-Scheduler dependency; the backup check is
    the one exception, translated for a runner where origin/main IS the
    checked-out HEAD (see check_backup_artifact_repo_outcomes). A
    WatchdogFatalError from a check (e.g. git unavailable) propagates to the
    caller uncaught; that is the one path that still exits nonzero."""
    result = FleetResult()
    for name, checker in REPO_OUTCOME_CHECKS:
        verdict = checker(vault_root, now)
        alert_text = None
        if verdict.alert:
            since = verdict.since or "unknown"
            alert_text = f"{name}: {verdict.alert}, since {since}"
            result.alerts.append(alert_text)
        result.rows.append(
            TaskRow(
                name=name, state="n/a", last_run_display="n/a", result_display="n/a",
                next_run_display="n/a", artifact=verdict, alert_text=alert_text,
            )
        )
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_markdown(fleet: FleetResult, now: datetime, history_rows: list) -> str:
    lines = []
    lines.append("---")
    lines.append(f"date: {now.date().isoformat()}")
    lines.append("tags: [monitoring, vault]")
    lines.append("status: active")
    lines.append("---")
    lines.append("")
    lines.append("# Harness Alerts")
    lines.append("")
    lines.append(f"last_run: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")
    lines.append("## Current alerts")
    lines.append("")
    if fleet.alerts:
        for a in fleet.alerts:
            lines.append(f"- {a}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Fleet")
    lines.append("")
    lines.append("| task | state | last run | result | next run | artifact verdict | age |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for row in fleet.rows:
        lines.append(
            f"| {row.name} | {row.state} | {row.last_run_display} | {row.result_display} | "
            f"{row.next_run_display} | {row.artifact.verdict} | {row.artifact.age_display} |"
        )
    if fleet.trust_ledger is not None:
        lines.append(
            f"| {TRUST_LEDGER_ID} | n/a | n/a | n/a | n/a | "
            f"{fleet.trust_ledger.verdict} | {fleet.trust_ledger.age_display} |"
        )
    if fleet.actions_minutes is not None:
        lines.append(
            f"| {ACTIONS_MINUTES_ID} | n/a | n/a | n/a | n/a | "
            f"{fleet.actions_minutes.verdict} | {fleet.actions_minutes.age_display} |"
        )
    lines.append("")
    lines.append("## History")
    lines.append("")
    bounded = history_rows[-HISTORY_MAX:]
    for row in bounded:
        alert_count = row.get("alert_count", 0)
        names = ", ".join(row.get("alerts_short", []))
        suffix = f" ({names})" if names else ""
        lines.append(f"- {row.get('run_time', 'unknown')}: {alert_count} alert(s){suffix}")
    lines.append("")
    return "\n".join(lines)


def _alert_short_names(alerts: list) -> list:
    names = []
    for a in alerts:
        names.append(a.split(":", 1)[0])
    return names


def render_repo_outcomes_markdown(fleet: FleetResult, now: datetime) -> str:
    """TASK-014/TASK-015 report body for the outcome-watchdog GitHub issue.
    No History section (a run's continuity lives in the issue's edit
    history, not in vault-local state this mode never writes)."""
    lines = []
    lines.append("# Vault outcome watchdog")
    lines.append("")
    lines.append(f"last_run: {now.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    lines.append("")
    lines.append("## Current alerts")
    lines.append("")
    if fleet.alerts:
        for a in fleet.alerts:
            lines.append(f"- {a}")
    else:
        lines.append("None.")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    lines.append("| check | verdict | age | detail | since |")
    lines.append("| --- | --- | --- | --- | --- |")
    for row in fleet.rows:
        lines.append(
            f"| {row.name} | {row.artifact.verdict} | {row.artifact.age_display} | "
            f"{row.artifact.detail} | {row.artifact.since or 'n/a'} |"
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# JSONL state
# ---------------------------------------------------------------------------


def _fleet_summary(fleet: FleetResult) -> dict:
    summary = {row.name: row.artifact.verdict for row in fleet.rows}
    if fleet.trust_ledger is not None:
        summary[TRUST_LEDGER_ID] = fleet.trust_ledger.verdict
    if fleet.actions_minutes is not None:
        summary[ACTIONS_MINUTES_ID] = fleet.actions_minutes.verdict
    return summary


def append_jsonl_row(jsonl_path: Path, row: dict) -> None:
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row) + "\n")


def read_history_rows(jsonl_path: Path) -> list:
    if not jsonl_path.exists():
        return []
    rows = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Backup retry (injectable runner; never fires under test unless injected)
# ---------------------------------------------------------------------------


def _in_test_context() -> bool:
    """Best-effort: True if a test_*.py frame with a unittest.TestCase or a
    pytest fixture is on the call stack. Mirrors the pattern in
    lint-cadence-trigger.py; belt-and-suspenders so the real
    Start-ScheduledTask call cannot fire from an unmocked test run even if a
    caller forgets to pass a runner."""
    try:
        import inspect
        for frame_info in inspect.stack(0):
            basename = os.path.basename(frame_info.filename)
            if basename.startswith("test_") or basename == "pytest" or "pytest" in basename:
                return True
    except Exception:
        pass
    return False


def _real_start_scheduled_task(task_name: str) -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-Command", f"Start-ScheduledTask -TaskName '{task_name}'"],
        capture_output=True, text=True, timeout=30,
    )


def issue_backup_retry(task_name: str = BACKUP_TASK_NAME, runner=None) -> None:
    if runner is not None:
        runner(task_name)
        return
    if _in_test_context():
        return
    _real_start_scheduled_task(task_name)


# ---------------------------------------------------------------------------
# PowerShell task enumeration
# ---------------------------------------------------------------------------

_PS_COMMAND = (
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -like 'Vault*' }; "
    "$result = foreach ($t in $tasks) { "
    "$info = Get-ScheduledTaskInfo -TaskName $t.TaskName; "
    "$action = $t.Actions | Select-Object -First 1; "
    "[PSCustomObject]@{ TaskName = $t.TaskName; State = $t.State.ToString(); "
    "LastRunTime = $info.LastRunTime; LastTaskResult = $info.LastTaskResult; "
    "NextRunTime = $info.NextRunTime; Execute = $action.Execute; "
    "Arguments = $action.Arguments } }; "
    "$result | ConvertTo-Json -Depth 4"
)


def run_powershell_tasks() -> str:
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _PS_COMMAND],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
    except OSError as exc:
        raise WatchdogFatalError(f"powershell launch failed: {exc}") from exc
    if proc.returncode != 0:
        raise WatchdogFatalError(
            f"powershell exited {proc.returncode}: {(proc.stderr or '').strip()[:300]}"
        )
    return proc.stdout


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fleet health check for every Vault* scheduled task."
    )
    parser.add_argument("--dry-run", action="store_true",
                         help="Print the report to stdout; write nothing.")
    parser.add_argument("--tasks-json", type=Path, default=None,
                         help="Read task fleet JSON from this file instead of calling PowerShell.")
    parser.add_argument("--vault-root", type=Path, default=VAULT,
                         help="Vault root that all artifact paths resolve under.")
    parser.add_argument("--retry-backup", action="store_true", default=False,
                         help="When the backup task alerts, issue one Start-ScheduledTask retry.")
    parser.add_argument("--repo-outcomes-only", action="store_true", default=False,
                         help="Runner-safe mode (TASK-014): skip PowerShell task enumeration "
                              "and the backup retry; run only repo-visible checks and print "
                              "a Markdown report (see --report-out).")
    parser.add_argument("--report-out", type=Path, default=None,
                         help="With --repo-outcomes-only, also write the report to this path "
                              "(default: print to stdout only).")
    return parser


def _read_existing_foreign_alert_rows(alerts_path: Path, generated_alerts: list) -> list:
    """Reads harness-alerts.md's existing '## Current alerts' section (if
    any) and returns any 'FAIL-LOUD:' bullet rows not already present in
    generated_alerts, de-duplicated, in their original order.

    These are rows a DIFFERENT writer (auto-commit.ps1) added; this run's
    own render_markdown rebuild, which is a full overwrite built solely
    from THIS run's own checks, must not silently drop them (self-heal
    phase (a) fix pass item 5b, adversarial review 'harness-alerts.md
    two-writer race': a rebase-conflict or origin-unreachable row is not
    one of scheduler_watchdog.py's own ArtifactVerdict checks, so without
    this read-before-rewrite step the next local run erases it
    unconditionally). scheduler_watchdog.py's own alerts never start with
    the literal "FAIL-LOUD:" string, so this filter cannot collide with
    anything this run generated itself."""
    if not alerts_path.exists():
        return []
    try:
        text = alerts_path.read_text(encoding="utf-8")
    except OSError:
        return []
    lines = text.splitlines()
    try:
        start = lines.index("## Current alerts") + 1
    except ValueError:
        return []
    section = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        section.append(line)
    seen = set(generated_alerts)
    foreign = []
    for line in section:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        content = stripped[2:]
        if not content.startswith("FAIL-LOUD:"):
            continue
        if content in seen:
            continue
        seen.add(content)
        foreign.append(content)
    return foreign


def _write_fatal(vault_root: Path, now: datetime, reason: str, dry_run: bool) -> None:
    alert_line = f"watchdog: {reason}, since {now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    fleet = FleetResult(alerts=[alert_line])
    alerts_path = vault_root / ALERTS_MD_REL
    foreign_alerts = _read_existing_foreign_alert_rows(alerts_path, fleet.alerts)
    if foreign_alerts:
        fleet.alerts = list(fleet.alerts) + foreign_alerts
    jsonl_path = vault_root / JSONL_STATE_REL
    history_rows = read_history_rows(jsonl_path)
    row = {
        "run_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alert_count": len(fleet.alerts),
        "alerts": list(fleet.alerts),
        "alerts_short": _alert_short_names(fleet.alerts),
        "fleet_summary": {},
    }
    markdown = render_markdown(fleet, now, history_rows + [row])
    if dry_run:
        print(markdown)
        return
    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    alerts_path.write_text(markdown, encoding="utf-8", newline="\n")
    append_jsonl_row(jsonl_path, row)


def _run_repo_outcomes_only(vault_root: Path, now: datetime, report_out) -> int:
    """TASK-014 entry point body. Never touches harness-alerts.md or the
    scheduler-watchdog jsonl state (those belong to the local fleet path).
    Always exits 0: alerts are findings for the caller, not a watchdog
    failure. A genuine WatchdogFatalError still exits 2."""
    try:
        fleet = evaluate_repo_outcomes(vault_root, now)
        exit_code = 0
    except WatchdogFatalError as exc:
        alert_line = f"watchdog: {exc}, since {now.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        fleet = FleetResult(alerts=[alert_line])
        exit_code = 2

    markdown = render_repo_outcomes_markdown(fleet, now)
    print(markdown)
    if report_out is not None:
        report_path = Path(report_out)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown, encoding="utf-8", newline="\n")
    return exit_code


def main(argv: list = None, *, retry_runner=None) -> int:
    args = build_parser().parse_args(argv)
    vault_root = Path(args.vault_root)
    now = datetime.now(timezone.utc)

    if args.repo_outcomes_only:
        return _run_repo_outcomes_only(vault_root, now, args.report_out)

    try:
        if args.tasks_json:
            raw = Path(args.tasks_json).read_text(encoding="utf-8")
        else:
            raw = run_powershell_tasks()
        tasks = load_tasks_json(raw)
    except WatchdogFatalError as exc:
        _write_fatal(vault_root, now, str(exc), args.dry_run)
        return 2

    try:
        fleet = evaluate_fleet(tasks, vault_root, now)
    except WatchdogFatalError as exc:
        _write_fatal(vault_root, now, str(exc), args.dry_run)
        return 2

    # Preserve any foreign "- FAIL-LOUD:" row a different writer
    # (auto-commit.ps1) added that this run's own checks did not generate
    # (fix pass item 5b): otherwise render_markdown's full-rebuild below
    # would silently drop it.
    alerts_path = vault_root / ALERTS_MD_REL
    foreign_alerts = _read_existing_foreign_alert_rows(alerts_path, fleet.alerts)
    if foreign_alerts:
        fleet.alerts = list(fleet.alerts) + foreign_alerts

    retried = False
    if args.retry_backup:
        backup_row = next((r for r in fleet.rows if r.name == BACKUP_TASK_NAME), None)
        if backup_row is not None and backup_row.alert_text:
            issue_backup_retry(BACKUP_TASK_NAME, runner=retry_runner)
            retried = True

    jsonl_path = vault_root / JSONL_STATE_REL
    history_rows = read_history_rows(jsonl_path)
    row = {
        "run_time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alert_count": len(fleet.alerts),
        "alerts": list(fleet.alerts),
        "alerts_short": _alert_short_names(fleet.alerts),
        "fleet_summary": _fleet_summary(fleet),
    }
    if retried:
        row["retry"] = "retry issued"

    markdown = render_markdown(fleet, now, history_rows + [row])

    if args.dry_run:
        print(markdown)
        return 0

    alerts_path.parent.mkdir(parents=True, exist_ok=True)
    alerts_path.write_text(markdown, encoding="utf-8", newline="\n")
    append_jsonl_row(jsonl_path, row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
