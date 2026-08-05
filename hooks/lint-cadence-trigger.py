#!/usr/bin/env python3
"""SessionStart cadence trigger for /process-lint, /process-governance-mine, and the rolling setup-audit (2026-06-08).

Reads three sibling state files and surfaces a "consider running" suggestion
for each when last run is older than its cadence (or the state file does not exist).

State files:
  .claude/hooks/_state/lint-cadence.json: /process-lint (7d)
  .claude/hooks/_state/governance-mine-cadence.json: /process-governance-mine (7d)
  .claude/hooks/_state/setup-audit-cadence.json: rolling CMDB / full-setup-analysis refresh (30d)

The setup-audit cadence makes the situational-awareness audit (CMDB-v3 + asset-awareness
Phases 0:C) a ROLLING effort rather than incidental, per
[[feedback_rolling_setup_analysis_single_source_of_truth]]: so registry.json stays the
single source of truth and redundancy/dead-dependency drift surfaces on a schedule.

Output contract: stdout JSON per SessionStart hook spec. Never blocks.
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

VAULT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
STATE_FILE = os.path.join(VAULT, ".claude", "hooks", "_state", "lint-cadence.json")
GOVERNANCE_MINE_STATE_FILE = os.path.join(
    VAULT, ".claude", "hooks", "_state", "governance-mine-cadence.json"
)
SETUP_AUDIT_STATE_FILE = os.path.join(
    VAULT, ".claude", "hooks", "_state", "setup-audit-cadence.json"
)
WORK_TRIAGE_STATE_FILE = os.path.join(
    VAULT, ".claude", "hooks", "_state", "work-triage-cadence.json"
)

MINER_RESOLVED_LEDGER = os.path.join(
    VAULT, ".claude", "hooks", "aggregates", "miner-resolved.jsonl"
)
GOVERNANCE_MINE_TRIAGE_SHEET = os.path.join(
    "Projects", "your-project", "work",
    "2026-07-10-governance-mine-proposal-triage.md",
)

CADENCE_DAYS = 7
SETUP_AUDIT_CADENCE_DAYS = 30
INGEST_BACKLOG_HOURS = 48
ESCALATION_FACTOR = 2  # overdue > factor*cadence -> escalated directive (Increment 2, 2026-06-12)


def parse_iso(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def bootstrap_state_file(path: str, op_name: str):
    """Lesson 4 (audit 2026-06-10): cadence state files must be bootstrapped, not assumed.

    Creates the file with an epoch-old last_iso so the normal age path fires the
    reminder from now on, and the missing-file special case can never silently
    diverge again. Best-effort; never raises.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_iso": "1970-01-01T00:00:00Z",
                    "report_path": "",
                    "bootstrapped_by": "lint-cadence-trigger",
                    "note": f"auto-bootstrapped; no prior {op_name} run on record",
                },
                f,
                indent=2,
            )
    except Exception:
        pass


def build_ingest_backlog_suggestion():
    """[INGEST CADENCE]: flag Inbox/Clippings items older than 48h with no log.md mention.

    Advisory heuristic: mtime is OneDrive-unreliable (STATE On-Watch), so this is a
    best-effort surface, not a gate. Items already decided (any basename mention in
    log.md: ingest, skip, or routing entry) are excluded; lesson 5: a recorded skip
    counts as processed.
    """
    now = datetime.now(timezone.utc)
    try:
        with open(os.path.join(VAULT, "log.md"), "r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    except Exception:
        log_text = ""
    overdue = []
    for dirname in ("Inbox", "Clippings"):
        d = os.path.join(VAULT, dirname)
        if not os.path.isdir(d):
            continue
        for name in os.listdir(d):
            if name.startswith(".") or name == "desktop.ini":
                continue
            # operational vault-log items do not trigger ingest (CLAUDE.md Rule 6)
            if name.startswith(("team-signal-", "claude-signal-")):
                continue
            p = os.path.join(d, name)
            if not os.path.isfile(p):
                continue
            try:
                age_h = (now.timestamp() - os.path.getmtime(p)) / 3600.0
            except Exception:
                continue
            if age_h < INGEST_BACKLOG_HOURS:
                continue
            stem = os.path.splitext(name)[0]
            # log entries may truncate long titles: probe on the first token
            # (repo/article slug), min 8 chars to avoid false matches, else full stem
            first_token = stem.split()[0] if stem.split() else stem
            probe = first_token if len(first_token) >= 8 else stem[:60]
            if probe and probe in log_text:
                continue
            overdue.append(f"{dirname}/{name}"[:100])
    if not overdue:
        return ""
    shown = ", ".join(overdue[:5]) + (f" (+{len(overdue)-5} more)" if len(overdue) > 5 else "")
    return (
        f"[INGEST CADENCE] {len(overdue)} item(s) past the {INGEST_BACKLOG_HOURS}h ingest rule with no "
        f"log.md decision: {shown}. Run process-ingest or record a CLIP-SKIPPED decision: "
        "silence is worse than a recorded skip (audit 2026-06-10, lesson 5)."
    )


def build_lint_suggestion():
    """Return additionalContext string for /process-lint, or empty if cadence not due."""
    now = datetime.now(timezone.utc)
    if not os.path.isfile(STATE_FILE):
        bootstrap_state_file(STATE_FILE, "/process-lint")
        return (
            "[LINT CADENCE] No prior /process-lint run on record (state file bootstrapped). "
            "Lint is read-only: RUN /process-lint this session to establish baseline "
            "(standing authorization, Increment 2 2026-06-12)."
        )
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    last_iso = data.get("last_iso")
    last_dt = parse_iso(last_iso) if last_iso else None
    if last_dt is None:
        return ""
    age = now - last_dt
    if age < timedelta(days=CADENCE_DAYS):
        return ""
    errors = data.get("errors", 0)
    warnings = data.get("warnings", 0)
    last_report = data.get("report_path", "")
    age_days = age.days
    if age >= timedelta(days=CADENCE_DAYS * ESCALATION_FACTOR):
        msg = (
            f"[LINT CADENCE: OVERDUE] Last /process-lint ran {age_days} days ago "
            f"(cadence 7d; {errors} errors, {warnings} warnings unresolved). "
            "Lint is read-only: RUN /process-lint this session, do not defer "
            "(standing authorization, Increment 2 2026-06-12)."
        )
    else:
        msg = (
            f"[LINT CADENCE] Last /process-lint ran {age_days} days ago "
            f"({errors} errors, {warnings} warnings). "
            "Consider re-running to catch wiki drift."
        )
    if last_report:
        msg += f" Last report: {last_report}"
    return msg


def build_governance_mine_suggestion():
    """Return additionalContext string for /process-governance-mine, or empty if not due."""
    now = datetime.now(timezone.utc)
    if not os.path.isfile(GOVERNANCE_MINE_STATE_FILE):
        bootstrap_state_file(GOVERNANCE_MINE_STATE_FILE, "/process-governance-mine")
        return (
            "[GOVERNANCE-MINE CADENCE] No prior /process-governance-mine run (state file "
            "bootstrapped). Mining is proposal-only: RUN /process-governance-mine this "
            "session to establish baseline (standing authorization, Increment 2 2026-06-12)."
        )
    try:
        with open(GOVERNANCE_MINE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    last_iso = data.get("last_iso")
    last_dt = parse_iso(last_iso) if last_iso else None
    if last_dt is None:
        return ""
    age = now - last_dt
    if age < timedelta(days=CADENCE_DAYS):
        return ""
    age_days = age.days
    last_report = data.get("report_path", "")
    proposal_count = data.get("proposal_count", "?")
    if age >= timedelta(days=CADENCE_DAYS * ESCALATION_FACTOR):
        msg = (
            f"[GOVERNANCE-MINE CADENCE: OVERDUE] Last /process-governance-mine ran {age_days} "
            f"days ago (cadence 7d; {proposal_count} proposals last run). Mining is "
            "proposal-only: RUN /process-governance-mine this session, do not defer "
            "(standing authorization, Increment 2 2026-06-12)."
        )
    else:
        msg = (
            f"[GOVERNANCE-MINE CADENCE] Last /process-governance-mine ran {age_days} days ago "
            f"({proposal_count} proposals). "
            "Consider re-running to catch new recurring failure patterns."
        )
    if last_report:
        msg += f" Last report: {last_report}"
    return msg


def build_governance_mine_proposal_closure_suggestion():
    """GAP-3b (TA-3 Phase 2, 2026-07-10): loop-closure reminder for UNRESOLVED
    governance-mine proposals.

    The cadence reminder above only asks "is a new mine run due?": proposals
    from the LAST run can sit unruled forever without tripping anything. This
    builder fires when: the last report still exists on disk AND unresolved
    proposals remain (proposal_count minus distinct sig_ids in the resolved
    ledger; a MISSING ledger counts as 0 resolved, never as an error and never
    as fully-resolved: plan discovery D3) AND the run is older than 7 days.
    Advisory only; the ruling on each proposal is the owner's (flag F6).
    """
    now = datetime.now(timezone.utc)
    if not os.path.isfile(GOVERNANCE_MINE_STATE_FILE):
        return ""  # cadence builder above handles bootstrap; nothing to close
    try:
        with open(GOVERNANCE_MINE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    last_iso = data.get("last_iso")
    last_dt = parse_iso(last_iso) if last_iso else None
    if last_dt is None:
        return ""
    if now - last_dt <= timedelta(days=CADENCE_DAYS):
        return ""
    report_path = data.get("report_path", "")
    if not report_path or not os.path.isfile(os.path.join(VAULT, report_path)):
        return ""
    try:
        proposal_count = int(data.get("proposal_count", 0))
    except (TypeError, ValueError):
        return ""
    if proposal_count <= 0:
        return ""
    resolved_ids = set()
    try:
        with open(MINER_RESOLVED_LEDGER, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                sig = entry.get("sig_id")
                if sig:
                    resolved_ids.add(sig)
    except FileNotFoundError:
        pass  # D3: missing ledger = 0 resolved (reminder fires)
    except Exception:
        pass
    unresolved = proposal_count - len(resolved_ids)
    if unresolved <= 0:
        return ""
    return (
        f"[GOVERNANCE-MINE LOOP-CLOSURE] {unresolved} of {proposal_count} proposals "
        f"from the last mine run remain unruled (report: {report_path}). "
        f"Triage sheet: {GOVERNANCE_MINE_TRIAGE_SHEET}: one owner ruling per row "
        "(accept / tune / reject); append accepted rulings to "
        ".claude/hooks/aggregates/miner-resolved.jsonl to close the loop."
    )


def build_work_triage_suggestion():
    """Return additionalContext string for the work-layer triage sweep, or empty if not due.

    FILE-ORG-3 increment 1 (M-B cadence, spec 2026-06-23 section 3.2): own state file,
    own emit block per the E4 one-reminder-per-concern sibling pattern. Never folded
    into the wiki-lint block.
    """
    now = datetime.now(timezone.utc)
    if not os.path.isfile(WORK_TRIAGE_STATE_FILE):
        bootstrap_state_file(WORK_TRIAGE_STATE_FILE, "/maintain work-triage")
        return (
            "[WORK-TRIAGE CADENCE] No prior work-layer triage on record (state file "
            "bootstrapped). The sweep is proposal-only: run /maintain work-triage "
            "(python .claude/scripts/work_triage_sweep.py) to establish baseline."
        )
    try:
        with open(WORK_TRIAGE_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    last_iso = data.get("last_iso")
    last_dt = parse_iso(last_iso) if last_iso else None
    if last_dt is None:
        return ""
    age = now - last_dt
    if age < timedelta(days=CADENCE_DAYS):
        return ""
    age_days = age.days
    last_report = data.get("report_path", "")
    if age >= timedelta(days=CADENCE_DAYS * ESCALATION_FACTOR):
        msg = (
            f"[WORK-TRIAGE CADENCE: OVERDUE] Last work-layer triage was {age_days} days ago "
            "(cadence 7d). The sweep is proposal-only: run /maintain work-triage this "
            "session, do not defer."
        )
    else:
        msg = (
            f"[WORK-TRIAGE CADENCE] Last work-layer triage was {age_days} days ago. "
            "Run /maintain work-triage."
        )
    if last_report:
        msg += f" Last report: {last_report}"
    return msg


def build_setup_audit_suggestion():
    """Return additionalContext string for the rolling setup-audit, or empty if not due."""
    now = datetime.now(timezone.utc)
    if not os.path.isfile(SETUP_AUDIT_STATE_FILE):
        return (
            "[SETUP-AUDIT CADENCE] No rolling setup-audit on record. "
            "The CMDB / full-setup-analysis is meant to be ROLLING, not incidental. "
            "Consider refreshing: `python .claude/scripts/generate_registry.py`, reconcile the "
            "CLAUDE.md Agent Registry counts, and re-run the asset-awareness pass to catch "
            "redundancy / dead-dependency drift. Then stamp _state/setup-audit-cadence.json."
        )
    try:
        with open(SETUP_AUDIT_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return ""
    last_iso = data.get("last_iso")
    last_dt = parse_iso(last_iso) if last_iso else None
    if last_dt is None:
        return ""
    age = now - last_dt
    if age < timedelta(days=SETUP_AUDIT_CADENCE_DAYS):
        return ""
    age_days = age.days
    last_report = data.get("report_path", "")
    counts = data.get("counts", "")
    msg = (
        f"[SETUP-AUDIT CADENCE] Last rolling setup-audit ran {age_days} days ago"
        f"{(' (' + str(counts) + ')') if counts else ''}. "
        "Consider re-running: regenerate registry.json, reconcile CLAUDE.md counts, "
        "refresh the CMDB so registry stays the single source of truth."
    )
    if last_report:
        msg += f" Last report: {last_report}"
    return msg


def main():
    try:
        sys.stdin.read()
    except Exception:
        pass

    lint_suggestion = ""
    gov_suggestion = ""
    gov_closure_suggestion = ""
    setup_suggestion = ""
    ingest_suggestion = ""
    work_triage_suggestion = ""
    try:
        lint_suggestion = build_lint_suggestion()
    except Exception:
        pass
    try:
        gov_suggestion = build_governance_mine_suggestion()
    except Exception:
        pass
    try:
        gov_closure_suggestion = build_governance_mine_proposal_closure_suggestion()
    except Exception:
        pass
    try:
        setup_suggestion = build_setup_audit_suggestion()
    except Exception:
        pass
    try:
        ingest_suggestion = build_ingest_backlog_suggestion()
    except Exception:
        pass
    try:
        work_triage_suggestion = build_work_triage_suggestion()
    except Exception:
        pass

    # Concatenate all non-empty suggestions (newline-separated)
    parts = [s for s in (lint_suggestion, gov_suggestion, gov_closure_suggestion,
                         setup_suggestion, ingest_suggestion, work_triage_suggestion) if s]
    combined = "\n".join(parts)

    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire(
            "lint-cadence-trigger",
            decision=("suggested" if combined else "quiet"),
            detail=(
                f"lint={'yes' if lint_suggestion else 'no'} "
                f"gov-mine={'yes' if gov_suggestion else 'no'} "
                f"gov-mine-closure={'yes' if gov_closure_suggestion else 'no'} "
                f"setup-audit={'yes' if setup_suggestion else 'no'} "
                f"ingest-backlog={'yes' if ingest_suggestion else 'no'} "
                f"work-triage={'yes' if work_triage_suggestion else 'no'}"
            ),
        )
    except Exception:
        pass

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": combined,
        }
    }
    try:
        print(json.dumps(output))
    except Exception:
        pass


if __name__ == "__main__":
    main()
