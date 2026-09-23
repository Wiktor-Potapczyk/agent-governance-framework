"""Daily observability digest — renders the latest row of
`Resources/KB/vault-metrics-timeseries.jsonl` + `vault-metrics-verify.jsonl`
into a Markdown section and upserts it into
`Resources/KB/observability-daily-digest.md`.

Idempotent: re-running on the same date overwrites that date's section.
Headless / no flags. Designed to run after the verifier (daily 10:35 local).

Exit codes:
  0 — wrote (or refreshed) today's section, or nothing to do (no data)
  1 — unexpected error
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
KB_DIR = VAULT / "Resources" / "KB"
OBS_DIR = VAULT / "Resources" / "Observability"
TIMESERIES_PATH = KB_DIR / "vault-metrics-timeseries.jsonl"
VERIFY_PATH = KB_DIR / "vault-metrics-verify.jsonl"
DIGEST_PATH = OBS_DIR / "daily-digest.md"

SECTION_MARK = "<!-- digest:section -->"
SECTION_END = "<!-- digest:end -->"


def _read_last_record_for_date(path: Path, date: str | None = None) -> dict | None:
    """Return the last record in the JSONL file. If `date` given, return the
    last record whose `date` matches; else return the chronologically latest."""
    if not path.is_file():
        return None
    latest = None
    latest_date = None
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            d = rec.get("date")
            if date is not None:
                if d == date:
                    latest = rec
            else:
                if d and (latest_date is None or d >= latest_date):
                    latest_date = d
                    latest = rec
    return latest


def _fmt_dict_top(d: dict | None, n: int = 5) -> str:
    if not d:
        return "—"
    items = sorted(d.items(), key=lambda kv: -kv[1])[:n]
    return ", ".join(f"{k}: {v}" for k, v in items)


def _fmt_dashboard_alerts(alerts: list[str] | None) -> str:
    if not alerts:
        return "— (none)"
    seen, dedup = set(), []
    for a in alerts:
        if a not in seen:
            seen.add(a)
            dedup.append(a)
    return "\n  - " + "\n  - ".join(dedup)


def render_section(ts: dict, ver: dict | None) -> str:
    date = ts.get("date", "?")
    m = ts.get("metrics", {}) or {}
    if ver is None:
        mismatch_line = "no verifier record"
    else:
        verdict = ver.get("overall_status") or "?"
        mismatches = ver.get("mismatches") or []
        if verdict == "PASS" and not mismatches:
            mismatch_line = "PASS - no drift"
        else:
            mismatch_line = f"{verdict}: {len(mismatches)} mismatch(es)"

    classified = m.get("classification_emitted_count")
    complete = m.get("classification_complete_count")
    classifier_blocks = m.get("classifier_block_count", 0)
    quick_ratio_30d = m.get("quick_ratio_30d")
    quick_str = f"{quick_ratio_30d:.0%}" if isinstance(quick_ratio_30d, (int, float)) else "—"

    agent_total = m.get("agent_dispatch_count", 0)
    agent_outcomes = m.get("agent_dispatch_outcomes", {}) or {}
    agent_types = m.get("agent_type_counts", {}) or {}

    hook_blocks = m.get("hook_block_count", 0)
    blocks_by_hook = m.get("blocks_by_hook", {}) or {}
    hook_blocks_7d = m.get("hook_block_count_7d", 0)

    dark_zone = m.get("dark_zone_count", 0)
    dark_zone_hm = m.get("dark_zone_high_med_count", 0)

    verifier_block = m.get("verifier_gate_block_count", 0)
    verifier_pass = m.get("verifier_gate_pass_count", 0)
    qa_fail = m.get("qa_fail_event_count", 0)
    qa_fail_total = m.get("qa_fail_total", 0)

    sessions = m.get("session_count", 0)
    session_starts = m.get("session_start_count", 0)
    session_ends = m.get("session_end_count", 0)

    parse_err = ts.get("parse_error_count", 0)
    scanned = ts.get("governance_log_records_scanned", 0)

    dashboard = m.get("dashboard_alerts") or []

    rendered_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return (
        f"{SECTION_MARK} date={date}\n"
        f"## {date}\n\n"
        f"_Rendered: {rendered_at} · Verifier: {mismatch_line}_\n\n"
        f"### Classification\n"
        f"- Emitted: **{classified}** · Complete: **{complete}** · Classifier blocks: **{classifier_blocks}**\n"
        f"- Quick-ratio 30d: **{quick_str}**\n\n"
        f"### Agent dispatch (total: {agent_total})\n"
        f"- Outcomes — {_fmt_dict_top(agent_outcomes, 6)}\n"
        f"- Top agents — {_fmt_dict_top(agent_types, 6)}\n\n"
        f"### Hooks\n"
        f"- Today blocks: **{hook_blocks}** · 7d rolling: **{hook_blocks_7d}**\n"
        f"- Blocks by hook — {_fmt_dict_top(blocks_by_hook, 6)}\n"
        f"- Verifier gate — block: {verifier_block} · pass: {verifier_pass}\n"
        f"- QA fails — events: {qa_fail} · total: {qa_fail_total}\n\n"
        f"### Sessions\n"
        f"- Count: **{sessions}** · starts: {session_starts} · ends: {session_ends}\n\n"
        f"### Dark zone\n"
        f"- Count: **{dark_zone}** (high+med: {dark_zone_hm})\n\n"
        f"### Collector health\n"
        f"- Scanned: {scanned} · parse errors: {parse_err}\n\n"
        f"### Dashboard alerts ({len(dashboard)})\n"
        f"{_fmt_dashboard_alerts(dashboard)}\n\n"
        f"{SECTION_END}\n\n"
    )


def upsert_section(digest_path: Path, date: str, new_section: str) -> str:
    """Insert or replace the section for `date`. Returns 'created'/'replaced'/'appended'."""
    digest_path.parent.mkdir(parents=True, exist_ok=True)
    if not digest_path.is_file():
        header = (
            "---\n"
            "date: 2026-05-24\n"
            "updated: 2026-05-24\n"
            "tags: [observability-v2, project/agent-governance-research, vault-log]\n"
            "status: active\n"
            "---\n\n"
            "# Vault Observability — Daily Digest\n\n"
            "Auto-rendered by `.claude/scripts/observability_daily_digest.py` from "
            "`Resources/KB/vault-metrics-timeseries.jsonl` + `vault-metrics-verify.jsonl`.\n\n"
            "Related: [[moc-agent-governance]] · [[moc-active]]\n\n"
            "---\n\n"
        )
        digest_path.write_text(header + new_section, encoding="utf-8")
        return "created"

    text = digest_path.read_text(encoding="utf-8")
    # Look for an existing section for this date
    pattern = re.compile(
        rf"{re.escape(SECTION_MARK)} date={re.escape(date)}\n.*?{re.escape(SECTION_END)}\n\n",
        re.DOTALL,
    )
    if pattern.search(text):
        new_text = pattern.sub(new_section, text)
        digest_path.write_text(new_text, encoding="utf-8")
        return "replaced"

    # Append at end
    digest_path.write_text(text.rstrip() + "\n\n" + new_section, encoding="utf-8")
    return "appended"


def main() -> int:
    ts = _read_last_record_for_date(TIMESERIES_PATH, date=None)
    if not ts:
        print(f"observability_daily_digest: no timeseries data at {TIMESERIES_PATH}")
        return 0
    date = ts.get("date")
    ver = _read_last_record_for_date(VERIFY_PATH, date=date) if date else None
    section = render_section(ts, ver)
    action = upsert_section(DIGEST_PATH, date, section)
    print(f"observability_daily_digest: {action} section for date={date} -> {DIGEST_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # pragma: no cover
        print(f"observability_daily_digest: ERROR — {e}", file=sys.stderr)
        sys.exit(1)
