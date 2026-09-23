#!/usr/bin/env python3
"""experience_export.py - deterministic daily experience export for the
self-healing harness loop (self-healing-loop-spec.md section 3.1, TASK-003).

No LLM call. Reads two laptop-only, gitignored sinks
(.claude/hooks/governance-log.jsonl, .claude/hooks/hook-activity.jsonl) and
the day's Claude Code session transcripts, buckets what a future improver
round needs to diagnose (hook denies/blocks, dispatch-compliance misses, QA
fails, classifier corrections, owner-correction quotes), and writes one file
per day: Resources/Observability/experience/<date>.json.

Field shapes were confirmed live against the two sinks before this was
written, not assumed: governance-log.jsonl carries ts/event/hook (plus a
per-event payload); hook-activity.jsonl carries ts/decision/hook. A record
whose "session" field is literally the string "session" is a known-malformed
row and is dropped by the mandatory pre-filter before any bucketing.

Redaction, two independent passes over the WHOLE rendered export tree,
applied once, at the end, right before write:
  1. EXPORT_CREDENTIAL_PATTERNS, a strict superset of
     mirror_user_claude.CREDENTIAL_PATTERNS (dynamically imported, never
     re-derived) plus exporter-only shapes mirror_user_claude.py has no
     reason to cover (AWS AKIA keys, Authorization/bare Bearer headers, PEM
     private-key blocks, any sk- prefixed key of 10+ chars including
     Anthropic sk-ant-, gho_/ghs_ GitHub tokens, generic token=/api_key=/
     password= pairs), substituting "[REDACTED]" for any credential-shaped
     substring.
  2. sanitize_text from .claude/hooks/_unicode_hygiene.py, stripping
     bidi/zero-width/invisible characters from every string.
If loading either primitive or applying either pass raises for any reason,
the whole write is abandoned (FAIL-CLOSED): no partial or unredacted file
ever reaches disk.

Owner-correction quotes are kept only if they (a) match one of
CORRECTION_PREFIXES, (b) are at most MAX_QUOTE_LENGTH characters after
sentence-trimming, and (c) contain none of INSTRUCTION_DENY_MARKERS and no
control or zero-width character survives a check independent of the later
sanitize_text pass. A quote failing (b) or (c) is replaced with
{"dropped": "instruction-shaped", "session_date": ...} so the count is
preserved but the text is gone, never truncated-and-kept (self-heal phase
(a) fix pass item 2; the old single-phrase trailing cut was not a real
filter).

Never overwrites a prior day's file: the target date (--date, default the
current UTC date) must equal --now's own UTC date, or the run is refused
with no file written. This is a clock-skew / accidental-backfill guard, not
a same-day-rerun guard; auto-commit.ps1 calls this script roughly every 30
minutes, and re-running for the CURRENT day is expected to overwrite that
day's own file with freshly recomputed counts.

On the write that brings the daily-file count under
Resources/Observability/experience/ to 15 or more, the single oldest daily
file is rolled into <YYYY-MM>-rollup.json (one summary entry: date plus
per-bucket totals) and MOVED, never deleted, to
Resources/Observability/experience/archive/<YYYY-MM>/.

Exit codes:
  0  wrote the file (or, when 15+ daily files resulted, also rolled one up)
  2  refused: --date does not match --now's own UTC date
  3  FAIL-CLOSED: the redaction step itself raised; nothing was written

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude\\scripts\\experience_export.py
        [--vault-root PATH] [--transcripts-dir PATH] [--date YYYY-MM-DD] [--now ISO8601]

Python 3.14, standard library only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

VAULT = Path(__file__).resolve().parent.parent.parent
GOVERNANCE_LOG_REL = ".claude/hooks/governance-log.jsonl"
HOOK_ACTIVITY_REL = ".claude/hooks/hook-activity.jsonl"
EXPERIENCE_DIR_REL = "Resources/Observability/experience"
VAULT_ID = "C--Users-WiktorPotapczyk-Desktop-Vault"
DEFAULT_TRANSCRIPTS_DIR = Path.home() / ".claude" / "projects" / VAULT_ID

ROLLUP_TRIGGER_COUNT = 15

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_REDACTION_FAILED = 3

DENY_BLOCK_EVENTS = {"deny", "block"}
DENY_BLOCK_DECISIONS = {"deny", "block"}

# Vault-authored, concrete, small by design (PL-5 wordlist convention): a
# user turn qualifies as correction-shaped when its stripped, casefolded
# text starts with one of these.
CORRECTION_PREFIXES = (
    "no,", "no.", "never", "don't", "do not", "why did you",
    "stop", "wrong", "that's wrong", "that's not right",
)

# A correction quote is dropped (self-heal phase (a) fix pass item 2) when
# it contains any of these markers, case-insensitive, or a fenced code
# block. Replaces the old single-phrase trailing cut, which was a keyword
# list applied only at the END of a sentence and left an untouched
# instruction-shaped quote intact whenever it did not happen to use one of
# four exact trailing phrases (adversarial review probe 2, "BREAKS").
INSTRUCTION_DENY_MARKERS = (
    "ignore", "instruction", "system:", "you are now", "from now on",
    "always", "push", "force", "delete", "remove", "rm ", "run ",
    "execute", "curl", "wget", "token", "secret", "password", "sudo",
    "override", "bypass", "disable", "merge", "commit",
)

MAX_QUOTE_LENGTH = 240

# Zero-width/bidi-mark codepoints sanitize_text strips; checked here too
# (independent of the later sanitize_text pass) so an obfuscated marker
# that splices one of these mid-word still fails the quote filter even
# though the plain substring match on INSTRUCTION_DENY_MARKERS would miss
# it. unicodedata.category == "Cc" catches plain ASCII control bytes
# (\x00-\x1F, \x7F), which sanitize_text's own Cf-based class table does
# not cover at all.
_ZERO_WIDTH_CODEPOINTS = frozenset((0x200B, 0x200C, 0x200D, 0x2060, 0x200E, 0x200F))

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_DAILY_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


class RedactionError(RuntimeError):
    """Raised when loading or applying either redaction primitive fails.
    Callers must treat this as FAIL-CLOSED: no file is written."""


# ---------------------------------------------------------------------------
# Redaction primitives (dynamic import, GUD-002: reuse, never re-derive)
# ---------------------------------------------------------------------------

# Exporter-only additions (self-heal phase (a) fix pass item 1, adversarial
# review probe 1, "Exfiltration: BREAKS"), layered on top of
# mirror_user_claude.CREDENTIAL_PATTERNS via alternation, never replacing
# it. Each `(?i:...)` group scopes its own case-insensitivity locally
# (Python 3.11+ rejects an inline (?i) flag placed anywhere but the very
# start of the whole pattern when combined via `|`).
_EXPORT_ONLY_CREDENTIAL_PATTERNS = "|".join((
    r"AKIA[0-9A-Z]{16}",                                            # AWS access key
    r"(?i:Authorization:\s*Bearer\s+[A-Za-z0-9\-_.=]+)",            # Authorization: Bearer <token>
    r"(?i:\bBearer\s+[A-Za-z0-9\-_.=]{8,})",                        # bare Bearer <token-like>
    r"-----BEGIN(?: [A-Z]+)* PRIVATE KEY-----"
    r"(?:[\s\S]*?-----END(?: [A-Z]+)* PRIVATE KEY-----)?",         # PEM private-key blocks, header alone too (a truncated log line)
    r"sk-[A-Za-z0-9_\-]{10,}",                                      # any sk- key, incl. Anthropic sk-ant-
    r"gh[ops]_[A-Za-z0-9]{20,}",                                    # GitHub gho_/ghs_ (ghp_ covered by mirror)
    r"(?i:(?:token|api_key|password)=[^\s&\"']+)",                  # generic key=value pairs
))


def _load_credential_patterns():
    """Returns a compiled regex that is a strict superset of
    mirror_user_claude.CREDENTIAL_PATTERNS: its full pattern text is reused
    verbatim (GUD-002: reuse, never re-derive) and combined via alternation
    with the exporter-only shapes above. mirror_user_claude.py itself is
    never weakened or edited."""
    path = Path(__file__).resolve().parent / "mirror_user_claude.py"
    spec = importlib.util.spec_from_file_location("mirror_user_claude", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mirror_patterns = module.CREDENTIAL_PATTERNS
    combined = mirror_patterns.pattern + "|" + _EXPORT_ONLY_CREDENTIAL_PATTERNS
    return re.compile(combined)


def _load_sanitize_text():
    path = Path(__file__).resolve().parent.parent / "hooks" / "_unicode_hygiene.py"
    spec = importlib.util.spec_from_file_location("_unicode_hygiene", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.sanitize_text


def _redact_tree(obj, patterns, sanitize_fn):
    if isinstance(obj, str):
        redacted = patterns.sub("[REDACTED]", obj)
        clean, _manifest = sanitize_fn(redacted)
        return clean
    if isinstance(obj, list):
        return [_redact_tree(v, patterns, sanitize_fn) for v in obj]
    if isinstance(obj, dict):
        return {k: _redact_tree(v, patterns, sanitize_fn) for k, v in obj.items()}
    return obj


def redact_and_sanitize(export: dict) -> dict:
    """Loads both primitives and applies them to the whole export tree in
    one pass. Any failure anywhere in this function is re-raised as
    RedactionError; the caller must not write a file when this raises."""
    try:
        patterns = _load_credential_patterns()
        sanitize_fn = _load_sanitize_text()
        return _redact_tree(export, patterns, sanitize_fn)
    except RedactionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure here is fail-closed
        raise RedactionError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Sink reading
# ---------------------------------------------------------------------------

def read_jsonl_lines(path: Path):
    """Returns a list of parsed dict records, or None if the file is
    absent/unreadable (the sink-absent sentinel). Unparseable individual
    lines are skipped, never fatal."""
    if not path.exists():
        return None
    records = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    records.append(rec)
    except OSError:
        return None
    return records


def _parse_sink_ts_to_utc(ts: str):
    """Parses a governance-log.jsonl/hook-activity.jsonl 'ts' stamp
    ('YYYY-MM-DD HH:MM:SS', an explicit UTC offset only if present) and
    returns the equivalent UTC datetime, or None if unparseable.

    Confirmed live against both real sinks (self-heal phase (a) fix pass
    item 7, architect review Finding 2, HIGH): 'ts' carries naive LOCAL
    machine time with no offset, not UTC. datetime.astimezone(timezone.utc)
    on a naive datetime attaches the system's local zone before converting,
    per the stdlib's own documented contract, so a single call handles both
    the naive (local) and offset-aware cases correctly without treating the
    string's own date prefix as if it were already a UTC date."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def filter_day(records: list, target_date_str: str) -> list:
    """Mandatory pre-filter (session != 'session') plus the day window.
    Buckets by the record's TRUE UTC day (see _parse_sink_ts_to_utc), never
    by the local-time 'ts' string's own date prefix."""
    out = []
    for rec in records:
        if rec.get("session") == "session":
            continue
        ts = rec.get("ts") or ""
        utc_dt = _parse_sink_ts_to_utc(ts)
        if utc_dt is None or utc_dt.date().isoformat() != target_date_str:
            continue
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Bucketing
# ---------------------------------------------------------------------------

def _first_reason(rec: dict) -> str:
    for key in ("pattern", "reason", "detail", "message"):
        val = rec.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def bucket_hook_denies_blocks(gov_day: list, hook_day: list) -> list:
    counts: dict = {}

    def _add(hook_name, reason):
        entry = counts.setdefault(hook_name, {"count": 0, "sample_reason": ""})
        entry["count"] += 1
        if not entry["sample_reason"] and reason:
            entry["sample_reason"] = reason

    for rec in gov_day:
        if rec.get("event") in DENY_BLOCK_EVENTS:
            _add(rec.get("hook") or "unknown", _first_reason(rec))
    for rec in hook_day:
        if rec.get("decision") in DENY_BLOCK_DECISIONS:
            _add(rec.get("hook") or "unknown", _first_reason(rec))

    return [
        {"hook": hook, "count": v["count"], "sample_reason": v["sample_reason"]}
        for hook, v in sorted(counts.items())
    ]


def bucket_dispatch_compliance_misses(gov_day: list) -> list:
    counts: dict = {}
    for rec in gov_day:
        if rec.get("hook") != "dispatch-compliance" or rec.get("event") != "block":
            continue
        missing = rec.get("missing") or []
        if isinstance(missing, str):
            missing = [missing]
        for item in missing:
            if not isinstance(item, str):
                continue
            label = item.strip()
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
    return [{"skill": skill, "count": n} for skill, n in sorted(counts.items())]


def bucket_qa_fails(gov_day: list) -> list:
    counts: dict = {}
    for rec in gov_day:
        if rec.get("hook") != "work-verification-check" or rec.get("event") != "qa_fail_reported":
            continue
        # No "project" field exists in either sink; the session id is the
        # nearest deterministic grouping key available from these two logs
        # alone (documented deviation, see the phase-a build record).
        project = rec.get("session") or "unknown-session"
        fails = rec.get("fails") or []
        sample = fails[0] if fails and isinstance(fails[0], str) else ""
        try:
            n = int(rec.get("fail_count"))
        except (TypeError, ValueError):
            n = len(fails) if fails else 1
        entry = counts.setdefault(project, {"count": 0, "sample": ""})
        entry["count"] += n
        if not entry["sample"] and sample:
            entry["sample"] = sample
    return [
        {"project": project, "count": v["count"], "sample": v["sample"]}
        for project, v in sorted(counts.items())
    ]


def bucket_classifier_corrections(gov_day: list) -> list:
    total = 0
    for rec in gov_day:
        if rec.get("hook") == "classifier-field-check" and rec.get("event") == "classifier_field_missing":
            total += 1
    return [{"count": total}]


# ---------------------------------------------------------------------------
# Owner-correction quotes from session transcripts
# ---------------------------------------------------------------------------

def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            c.get("text", "") for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        return " ".join(p for p in parts if p)
    return ""


def _first_sentence(text: str) -> str:
    parts = _SENTENCE_SPLIT_RE.split(text.strip(), maxsplit=1)
    return parts[0].strip() if parts else text.strip()


def _has_surviving_control_or_zero_width(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if cp in _ZERO_WIDTH_CODEPOINTS:
            return True
        if unicodedata.category(ch) == "Cc":
            return True
    return False


def _is_instruction_shaped(quote: str) -> bool:
    if "```" in quote:
        return True
    lowered = quote.casefold()
    return any(marker in lowered for marker in INSTRUCTION_DENY_MARKERS)


def _build_correction_entry(quote: str, session_date: str) -> dict | None:
    """Real filter (self-heal phase (a) fix pass item 2), not a trailing-
    keyword cut: a quote is kept only if it is non-empty, at most
    MAX_QUOTE_LENGTH characters, contains none of INSTRUCTION_DENY_MARKERS
    or a fenced code block, and has no control/zero-width character
    surviving independent of the later sanitize_text pass (catches an
    obfuscated marker that splices one mid-word to dodge the substring
    check). A quote failing any check becomes {"dropped": ...,
    "session_date": ...}: the count is preserved, the text is gone."""
    if not quote:
        return None
    if (len(quote) > MAX_QUOTE_LENGTH
            or _is_instruction_shaped(quote)
            or _has_surviving_control_or_zero_width(quote)):
        return {"dropped": "instruction-shaped", "session_date": session_date}
    return {"quote": quote, "session_date": session_date}


def _is_real_user_text_turn(obj: dict) -> bool:
    if obj.get("type") != "user":
        return False
    if obj.get("isMeta"):
        return False
    if "toolUseResult" in obj or "sourceToolUseID" in obj or "sourceToolAssistantUUID" in obj:
        return False
    return isinstance(obj.get("message"), dict)


def scan_owner_corrections(transcripts_dir: Path, target_date_str: str):
    """Returns (list of {"quote", "session_date"}, sink_absent bool)."""
    if not transcripts_dir.exists():
        return [], True

    results = []
    for path in sorted(transcripts_dir.glob("*.jsonl")):
        try:
            mtime_date = datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        except OSError:
            continue
        # A file's last modification can never predate its own last line's
        # timestamp; skip files that could not possibly hold a line from
        # the target day.
        if mtime_date < target_date_str:
            continue
        try:
            handle = open(path, encoding="utf-8")
        except OSError:
            continue
        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(obj, dict) or not _is_real_user_text_turn(obj):
                    continue
                timestamp = obj.get("timestamp") or ""
                if timestamp[:10] != target_date_str:
                    continue
                text = _extract_text(obj["message"].get("content"))
                stripped = text.strip()
                if not stripped:
                    continue
                lowered = stripped.casefold()
                if not any(lowered.startswith(p) for p in CORRECTION_PREFIXES):
                    continue
                sentence = _first_sentence(stripped)
                entry = _build_correction_entry(sentence, timestamp[:10])
                if entry is None:
                    continue
                results.append(entry)
    return results, False


# ---------------------------------------------------------------------------
# Rollup / archive
# ---------------------------------------------------------------------------

def _bucket_total(entries) -> int:
    total = 0
    for e in entries or []:
        if isinstance(e, dict) and "count" in e:
            try:
                total += int(e["count"])
            except (TypeError, ValueError):
                total += 1
        else:
            total += 1
    return total


def maybe_rollup(experience_dir: Path):
    """Rolls exactly one file per call, only when >= ROLLUP_TRIGGER_COUNT
    daily files are present. Archives via shutil.move (byte-identical,
    never a read/rewrite), never deletes.

    The archive month comes from the daily file's own FILENAME, never its
    internal 'date' field (self-heal phase (a) fix pass item 8, adversarial
    review probe 3, "archive-month selection: NEEDS CHANGE"): the internal
    field is untrusted content that can disagree with the filename the glob
    and this trigger both actually key on. A mismatch is reported in the
    returned dict's "date_mismatch" key, never silently followed."""
    daily_files = sorted(
        p for p in experience_dir.glob("*.json") if _DAILY_FILE_RE.match(p.name)
    )
    if len(daily_files) < ROLLUP_TRIGGER_COUNT:
        return None

    oldest = daily_files[0]
    filename_date = oldest.stem
    try:
        data = json.loads(oldest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    internal_date = data.get("date")
    date_mismatch = bool(internal_date) and internal_date != filename_date
    month_key = filename_date[:7]

    counts = {
        key: _bucket_total(data.get(key, []))
        for key in (
            "hook_denies_blocks", "dispatch_compliance_misses",
            "qa_fails", "classifier_corrections", "owner_corrections",
        )
    }

    rollup_path = experience_dir / f"{month_key}-rollup.json"
    existing = []
    if rollup_path.exists():
        try:
            loaded = json.loads(rollup_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = []
    existing.append({"date": filename_date, "counts": counts})
    rollup_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )

    archive_dir = experience_dir / "archive" / month_key
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / oldest.name
    shutil.move(str(oldest), str(archive_path))

    result = {"archived": oldest.name, "rollup_file": rollup_path.name}
    if date_mismatch:
        result["date_mismatch"] = {
            "filename_date": filename_date, "internal_date": internal_date,
        }
    return result


# ---------------------------------------------------------------------------
# Build and write
# ---------------------------------------------------------------------------

def build_export(vault_root: Path, transcripts_dir: Path, target_date: date,
                  now_dt: datetime) -> dict:
    target_date_str = target_date.isoformat()

    gov_records = read_jsonl_lines(vault_root / GOVERNANCE_LOG_REL)
    gov_absent = gov_records is None
    gov_day = filter_day(gov_records or [], target_date_str)

    hook_records = read_jsonl_lines(vault_root / HOOK_ACTIVITY_REL)
    hook_absent = hook_records is None
    hook_day = filter_day(hook_records or [], target_date_str)

    owner_corrections, transcripts_absent = scan_owner_corrections(
        transcripts_dir, target_date_str)

    return {
        "date": target_date_str,
        "generated_at": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {
            "start": f"{target_date_str}T00:00:00Z",
            "end": f"{target_date_str}T23:59:59Z",
        },
        "hook_denies_blocks": bucket_hook_denies_blocks(gov_day, hook_day),
        "dispatch_compliance_misses": bucket_dispatch_compliance_misses(gov_day),
        "qa_fails": bucket_qa_fails(gov_day),
        "classifier_corrections": bucket_classifier_corrections(gov_day),
        "owner_corrections": owner_corrections,
        "redaction": {"credential_scrub_applied": True, "unicode_hygiene_applied": True},
        "sinks": {
            "governance_log": {"sink_absent": gov_absent},
            "hook_activity": {"sink_absent": hook_absent},
            "transcripts_dir": {"sink_absent": transcripts_absent},
        },
    }


def write_export(vault_root: Path, transcripts_dir: Path, target_date: date,
                  now_dt: datetime):
    """Returns (out_path, export_dict). Raises RedactionError, writing
    nothing, if the redaction step fails."""
    raw = build_export(vault_root, transcripts_dir, target_date, now_dt)
    export = redact_and_sanitize(raw)

    experience_dir = vault_root / EXPERIENCE_DIR_REL
    experience_dir.mkdir(parents=True, exist_ok=True)
    out_path = experience_dir / f"{target_date.isoformat()}.json"
    is_new_file = not out_path.exists()

    out_path.write_text(
        json.dumps(export, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )

    rollup_info = None
    if is_new_file:
        rollup_info = maybe_rollup(experience_dir)

    return out_path, export, rollup_info


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_now(value: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vault-root", default=str(VAULT))
    ap.add_argument("--transcripts-dir", default=str(DEFAULT_TRANSCRIPTS_DIR))
    ap.add_argument("--date", default=None,
                     help="target UTC date YYYY-MM-DD, default: --now's own date")
    ap.add_argument("--now", default=None,
                     help="ISO8601 UTC instant treated as 'now', default: real now")
    args = ap.parse_args(argv)

    now_dt = _parse_now(args.now) if args.now else datetime.now(timezone.utc)
    target_date = date.fromisoformat(args.date) if args.date else now_dt.date()

    if target_date != now_dt.date():
        print(
            f"REFUSED: target date {target_date.isoformat()} does not match "
            f"now's date {now_dt.date().isoformat()}; the exporter never "
            "backfills or overwrites a prior day",
            file=sys.stderr,
        )
        return EXIT_REFUSED

    vault_root = Path(args.vault_root)
    transcripts_dir = Path(args.transcripts_dir)

    try:
        out_path, export, rollup_info = write_export(
            vault_root, transcripts_dir, target_date, now_dt)
    except RedactionError as exc:
        print(f"FAIL-CLOSED: redaction step raised, no file written: {exc}",
              file=sys.stderr)
        return EXIT_REDACTION_FAILED

    hd = sum(e["count"] for e in export["hook_denies_blocks"])
    dc = sum(e["count"] for e in export["dispatch_compliance_misses"])
    qf = sum(e["count"] for e in export["qa_fails"])
    cc = export["classifier_corrections"][0]["count"] if export["classifier_corrections"] else 0
    oc = len(export["owner_corrections"])
    print(f"EXPERIENCE wrote {out_path} "
          f"hook_denies_blocks={hd} dispatch_compliance_misses={dc} "
          f"qa_fails={qf} classifier_corrections={cc} owner_corrections={oc}")
    if rollup_info:
        print(f"ROLLUP archived {rollup_info['archived']} into {rollup_info['rollup_file']}")
        mismatch = rollup_info.get("date_mismatch")
        if mismatch:
            print(
                f"ROLLUP-WARN filename date {mismatch['filename_date']} disagrees with "
                f"internal date {mismatch['internal_date']}; filename wins for archival",
                file=sys.stderr,
            )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
