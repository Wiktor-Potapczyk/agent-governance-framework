#!/usr/bin/env python3
"""H-4: task_plan.md auto-sync hook (2026-05-10).

Fires on Stop events when the last assistant message contains a QA REPORT block
with OVERALL PASS verdict. Locates the matching open `- [ ] **TASK-ID**` line in
the active project's task_plan.md, marks it `[x]`, and appends a 1-line summary.

Non-blocking: always exits 0. Failures log to .claude/hooks/logs/h4-sync.log.

v1: pure-regex matching only (73% coverage). Haiku fallback gated behind
H4_ENABLE_HAIKU=1 env var (off by default until regex path is empirically validated).

v1.1 (2026-05-10): regex broadened to match multi-segment IDs like OBS-V2-A and
ECC-LEARN-A2 (alpha trailing + 5+ char prefixes). Old regex required <=4-char prefix
+ numeric-only trailing segment, missing ~27% of IDs. New regex allows up to
10-char prefix and arbitrary alphanumeric trailing segments. False-positive defense unchanged: still
gated by `**` boundary + lookahead, and SCOPE-first extraction (Issue 1) remains
the primary prose-mention guard.

Known limitations (v1.2):
- T-SM-RESIDUAL-date-handle: date injection in the [x] mark does not handle the edge case
  where the existing task line already has a date suffix (e.g., "| 2026-04-25 |"). In that
  case the rewrite appends a duplicate date. Low-priority; filed in backlog.
- Revert-fail logging clarity: if atomic rename fails, the log message says "write failed"
  not "rename failed". Minor.
- Excerpt-length inconsistency: the excerpt captured for logging is 120 chars from raw text,
  not the cleaned QA block. Low-priority cosmetic issue.
- Haiku subprocess fallback is opt-in via H4_ENABLE_HAIKU=1. When enabled, a single
  `claude -p --model haiku` subprocess is invoked if the static regex finds no TASK-ID.
  Latency budget: 6-sec timeout leaves ~2-4 sec for typical Haiku response plus overhead.
- Windows ~/.claude.json corruption risk: the `claude -p` inline-prompt mode is read-only
  on session state (does not write ~/.claude.json mid-execution). The corruption risk only
  applies to interactive sessions interrupted mid-write. Mitigation: subprocess uses -p with
  inline prompt (not interactive mode); KeyboardInterrupt is caught, logged, and re-raised
  to prevent zombie subprocess accumulation.
- Concurrent H4 invocations: no lock is taken. If two Stop events fire simultaneously
  (e.g., rapid session cycling), two Haiku subprocesses may run in parallel. This is safe
  (both are read-only on session state) but may produce duplicate JSONL entries.
- Letter-prefixed date-style handles like `**H-2026-05**` match the regex (all segments
  are alphanumeric). Mitigated at runtime by regex_match() requiring the ID to appear
  in an open `[ ]` line of a task_plan.md — false-positive impact is near-zero unless
  someone creates a task line with exactly that handle. Codified as
  T-SM-RESIDUAL-date-handle in selftest.
- Multi-candidate guard takes only the first match if more than one ID survives extraction;
  this can miss the intended ID if a QA REPORT mentions multiple task IDs in prose.
  SCOPE-first extraction is the primary mitigation.

Safety: every mutation is preceded by undo log write. Post-write verification reverts on mismatch.
DRY_RUN via H4_DRY_RUN=1.
Undo via: python task-plan-auto-sync.py --undo [N]
Selftest via: python task-plan-auto-sync.py --selftest
"""
import sys
import json
import re
import os
import hashlib
import time
import datetime as _dt
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = VAULT / ".claude" / "hooks" / "logs"
STATE_DIR = VAULT / ".claude" / "hooks" / "_state"
LOG_PATH = LOG_DIR / "h4-sync.log"
DEDUP_PATH = STATE_DIR / "h4-dedup.json"
UNDO_PATH = STATE_DIR / "h4-undo.json"
OVERRIDE_FILE = VAULT / ".claude" / "active-project.txt"
PROJECTS_DIR = VAULT / "Projects"

DEDUP_WINDOW_HOURS = 72
UNDO_MAX_ENTRIES = 50
DRY_RUN = os.environ.get("H4_DRY_RUN", "0") == "1"
HAIKU_ENABLED = os.environ.get("H4_ENABLE_HAIKU", "0") == "1"
SUMMARY_MAX = 200
EXCERPT_MAX = 1500  # Max chars sent to Haiku fallback prompt

VERSION = "1.2"

# Path for Haiku fallback JSONL sink (relative to this file's parent = .claude/hooks/)
HAIKU_SINK = Path(__file__).parent / "aggregates" / "h4-haiku-fallback.jsonl"

# Validates bare TASK-ID output from Haiku (no ** boundary required — Haiku outputs raw ID)
PATTERN_BARE_TASK_ID = re.compile(r'^([A-Z][A-Z0-9]{0,9}(?:-[A-Z0-9]+)+)$')

PATTERN_QA_REPORT = re.compile(r'QA REPORT', re.IGNORECASE)
PATTERN_QA_PASS_TABLE = re.compile(r'\|\s*OVERALL\s*\|[^\n]*PASS', re.IGNORECASE)
PATTERN_QA_PASS_SIMPLE = re.compile(r'^\s*PASS:\s*\d+\s*/\s*\d+', re.IGNORECASE | re.MULTILINE)
PATTERN_TASK_ID = re.compile(r'\*\*([A-Z][A-Z0-9]{0,9}(?:-[A-Z0-9]+)+)(?=\*\*|\s)')
PATTERN_OPEN_LINE = re.compile(r'^\s*-\s*\[\s\]\s')
PATTERN_SCOPE = re.compile(r'\|\s*SCOPE\s*\|([^\n|]+)\|', re.IGNORECASE)


def log(msg: str):
    """Append timestamped line to LOG_PATH (best-effort, never raises)."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} {msg}\n")
    except Exception:
        pass


def get_last_assistant_text(transcript_path: str) -> str:
    """Parse transcript JSONL; return concatenated text from the last assistant message."""
    try:
        if not transcript_path or not os.path.isfile(transcript_path):
            return ""
        size = os.path.getsize(transcript_path)
        # Read tail (last ~200KB is enough for any single assistant turn)
        tail_size = min(200_000, size)
        with open(transcript_path, "rb") as f:
            f.seek(max(0, size - tail_size))
            tail = f.read().decode("utf-8", errors="replace")

        last_text = ""
        for line in tail.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("type") == "assistant":
                msg = entry.get("message", {})
                blocks = msg.get("content", [])
                texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
                if texts:
                    last_text = "\n".join(texts)
        return last_text
    except Exception as e:
        log(f"get_last_assistant_text failed: {e}")
        return ""


def detect_active_project() -> str:
    """Same logic as H-1: override file → most-recently-modified STATE.md → no fallback."""
    try:
        if OVERRIDE_FILE.is_file():
            name = OVERRIDE_FILE.read_text(encoding="utf-8").strip()
            if name and (PROJECTS_DIR / name / "STATE.md").is_file():
                return name
    except Exception:
        pass
    try:
        if not PROJECTS_DIR.is_dir():
            return ""
        best = None
        best_mt = 0
        for proj in PROJECTS_DIR.iterdir():
            if not proj.is_dir():
                continue
            sp = proj / "STATE.md"
            if sp.is_file():
                try:
                    mt = sp.stat().st_mtime
                    if mt > best_mt:
                        best_mt = mt
                        best = proj.name
                except Exception:
                    continue
        return best or ""
    except Exception:
        return ""


def find_task_plans(active_project: str):
    """Return ordered list of task_plan.md Paths: active first, then others."""
    plans = []
    if active_project:
        ap = PROJECTS_DIR / active_project / "task_plan.md"
        if ap.is_file():
            plans.append(ap)
    if PROJECTS_DIR.is_dir():
        for proj in PROJECTS_DIR.iterdir():
            if not proj.is_dir() or proj.name == active_project:
                continue
            tp = proj / "task_plan.md"
            if tp.is_file() and tp not in plans:
                plans.append(tp)
    return plans


def regex_match(candidate_ids, task_plans):
    """Scan task_plans for first open `[ ]` line where ** starts with ID.
    Matches both `**H-4**` and `**H-4 phrase**` formats (real task_plan.md uses the latter).
    Returns dict {file, line_index, original_line} or None.
    """
    for tid in candidate_ids:
        # Match **<TID> followed by either end-bold (**) or whitespace
        line_pattern = re.compile(r'\*\*' + re.escape(tid) + r'(?:\*\*|\s)')
        for tp in task_plans:
            try:
                with tp.open("r", encoding="utf-8") as f:
                    lines = f.read().split("\n")
                for idx, line in enumerate(lines):
                    if not PATTERN_OPEN_LINE.match(line):
                        continue
                    if line_pattern.search(line):
                        return {
                            "file": tp,
                            "line_index": idx,
                            "original_line": line,
                            "task_id": tid,
                        }
            except Exception as e:
                log(f"regex_match read failed for {tp}: {e}")
                continue
    return None


def extract_qa_block(assistant_text: str) -> str:
    """Return the substring from 'QA REPORT' through ~30 lines (covers full block)."""
    m = PATTERN_QA_REPORT.search(assistant_text)
    if not m:
        return ""
    start = m.start()
    # Take next ~3000 chars or up to next major section
    block = assistant_text[start:start + 3000]
    return block


def compose_summary(assistant_text: str) -> str:
    """Extract SCOPE field from QA block as primary summary source.
    Fallback: first PASS-line counts (e.g., 'PASS: 9 / 9').
    """
    qa = extract_qa_block(assistant_text)
    if not qa:
        return ""
    # Try table-style SCOPE field first
    m = PATTERN_SCOPE.search(qa)
    if m:
        scope = m.group(1).strip()
        summary = f"QA PASS — {scope}"
        return summary[:SUMMARY_MAX]
    # Try simple-format counts (process-qa skill's actual output uses `PASS: N / total`)
    m = PATTERN_QA_PASS_SIMPLE.search(qa)
    if m:
        # Pull the line + next non-empty
        lines = qa.split("\n")
        pass_idx = None
        for i, l in enumerate(lines):
            if PATTERN_QA_PASS_SIMPLE.match(l):
                pass_idx = i
                break
        if pass_idx is not None:
            summary = lines[pass_idx].strip()
            return summary[:SUMMARY_MAX]
    return "QA PASS"


def detected_qa_pass(assistant_text: str) -> bool:
    """Both forms count: table (| OVERALL | ... | PASS) OR simple (PASS: N / N)."""
    if not PATTERN_QA_REPORT.search(assistant_text):
        return False
    if PATTERN_QA_PASS_TABLE.search(assistant_text):
        return True
    if PATTERN_QA_PASS_SIMPLE.search(assistant_text):
        return True
    return False


def load_dedup():
    if not DEDUP_PATH.is_file():
        return []
    try:
        with DEDUP_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def is_recent_duplicate(line_hash: str) -> bool:
    cutoff = time.time() - DEDUP_WINDOW_HOURS * 3600
    entries = load_dedup()
    for e in entries:
        if e.get("hash") == line_hash and e.get("ts", 0) >= cutoff:
            return True
    return False


def record_dedup(line_hash: str):
    cutoff = time.time() - DEDUP_WINDOW_HOURS * 3600
    entries = [e for e in load_dedup() if e.get("ts", 0) >= cutoff]
    entries.append({"hash": line_hash, "ts": time.time()})
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = str(DEDUP_PATH) + f".tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        os.replace(tmp, DEDUP_PATH)
    except Exception as e:
        log(f"record_dedup failed: {e}")


def write_undo_entry(match, replacement_line):
    """Append undo entry. Raises on failure (caller skips mutation)."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    if UNDO_PATH.is_file():
        try:
            with UNDO_PATH.open("r", encoding="utf-8") as f:
                entries = json.load(f)
        except Exception:
            entries = []
    entries.append({
        "ts": datetime.now().isoformat(),
        "file": str(match["file"]),
        "line_index": match["line_index"],
        "original_line": match["original_line"],
        "replacement_line": replacement_line,
        "task_id": match.get("task_id", ""),
    })
    # Cap
    entries = entries[-UNDO_MAX_ENTRIES:]
    tmp = str(UNDO_PATH) + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
    os.replace(tmp, UNDO_PATH)


def apply_replacement(match, replacement_line):
    """Atomic write: read → modify line → write to .tmp → os.replace."""
    fp = match["file"]
    with fp.open("r", encoding="utf-8") as f:
        lines = f.read().split("\n")
    idx = match["line_index"]
    if idx >= len(lines):
        raise IndexError(f"line_index {idx} out of range for {fp}")
    # Replace single line; replacement_line MUST NOT contain extra newlines that shift line indices
    # If summary is multi-line, embed it inline (no newline) to keep indices stable.
    lines[idx] = replacement_line
    new_text = "\n".join(lines)
    tmp = str(fp) + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, fp)


def verify_write(match, expected_replacement) -> bool:
    """Re-read and confirm the replacement is in place."""
    try:
        with match["file"].open("r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        actual = lines[match["line_index"]] if match["line_index"] < len(lines) else ""
        return actual == expected_replacement
    except Exception:
        return False


def revert_via_undo(match):
    """Best-effort revert if verification fails."""
    try:
        with match["file"].open("r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        idx = match["line_index"]
        if idx < len(lines):
            lines[idx] = match["original_line"]
            tmp = str(match["file"]) + f".rev.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            os.replace(tmp, match["file"])
            log(f"REVERTED line {idx+1} in {match['file'].name} after verification failure")
    except Exception as e:
        log(f"revert_via_undo failed: {e}")


def undo_last(n: int = 1):
    """CLI undo mode: revert the last N undo entries."""
    if not UNDO_PATH.is_file():
        print("No undo log present.")
        return
    try:
        with UNDO_PATH.open("r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        print(f"Failed to read undo log: {e}")
        return
    if not entries:
        print("Undo log is empty.")
        return
    to_revert = entries[-n:]
    remaining = entries[:-n] if n <= len(entries) else []
    for e in reversed(to_revert):
        fp = Path(e["file"])
        try:
            with fp.open("r", encoding="utf-8") as f:
                lines = f.read().split("\n")
            idx = e["line_index"]
            if idx < len(lines) and lines[idx] == e["replacement_line"]:
                lines[idx] = e["original_line"]
                tmp = str(fp) + f".undo.{os.getpid()}"
                with open(tmp, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines))
                os.replace(tmp, fp)
                print(f"REVERTED {fp.name} line {idx+1} (task_id={e.get('task_id','?')})")
            else:
                print(f"SKIPPED {fp.name} line {idx+1}: file changed since H-4 wrote (task_id={e.get('task_id','?')})")
        except Exception as ex:
            print(f"FAILED to revert {fp}: {ex}")
    # Persist remaining
    try:
        with UNDO_PATH.open("w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2)
    except Exception as ex:
        print(f"Failed to update undo log: {ex}")


# ---------------------------------------------------------------------------
# Haiku subprocess fallback (opt-in, H4_ENABLE_HAIKU=1)
# ---------------------------------------------------------------------------

def _invoke_haiku_fallback(prose: str) -> tuple:
    """
    Invoke `claude -p --model haiku` to extract a TASK-ID from *prose*.

    Returns (extracted_id_or_None, outcome_string) where outcome is one of:
      "hit"            — ID extracted, validated against PATTERN_TASK_ID
      "miss"           — Haiku returned NONE or empty
      "timeout"        — subprocess.TimeoutExpired (6-sec budget)
      "invalid_output" — Haiku output doesn't match PATTERN_TASK_ID or is unparseable
      "cli_absent"     — `claude` binary not on PATH

    Caller MUST call regex_match() against task_plan.md before using the result to
    distinguish "hit + in plan" from "hit + not in plan". This function validates
    the ID format only.
    """
    prompt = (
        "You are a TASK-ID extractor. "
        "Read the following QA REPORT excerpt and output ONLY the TASK-ID "
        "(format: UPPERCASE letters/digits, hyphen-separated segments, e.g. PROJ-TASK-001) "
        "found in it. If no TASK-ID is present, output the single word NONE. "
        "Do not output anything else — no explanation, no punctuation, no markdown.\n\n"
        f"QA REPORT EXCERPT:\n{prose}"
    )

    t_start = time.monotonic()
    sink_entry: dict = {
        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "exit_code": None,
        "latency_ms": None,
        "extracted_id": None,
        "outcome": "miss",
    }

    try:
        result = subprocess.run(
            ["claude", "-p", "--model", "haiku", prompt],
            capture_output=True,
            text=True,
            timeout=6,
            check=False,
        )
        latency_ms = int((time.monotonic() - t_start) * 1000)
        sink_entry["exit_code"] = result.returncode
        sink_entry["latency_ms"] = latency_ms

        if result.returncode != 0:
            log(f"haiku non-zero exit {result.returncode}: {result.stderr[:200]!r}")
            sink_entry["outcome"] = "miss"
            _write_haiku_sink(sink_entry)
            return None, "miss"

        raw_output = result.stdout.strip()

        if not raw_output or raw_output.upper() == "NONE":
            sink_entry["outcome"] = "miss"
            _write_haiku_sink(sink_entry)
            return None, "miss"

        # Validate the bare ID returned by Haiku (no ** delimiters in Haiku's output)
        m_bare = PATTERN_BARE_TASK_ID.match(raw_output)
        if not m_bare:
            log(f"haiku output {raw_output!r} failed regex validation")
            sink_entry["outcome"] = "invalid_output"
            _write_haiku_sink(sink_entry)
            return None, "invalid_output"

        validated_id = m_bare.group(1)
        sink_entry["extracted_id"] = validated_id
        sink_entry["outcome"] = "hit"
        _write_haiku_sink(sink_entry)
        return validated_id, "hit"

    except subprocess.TimeoutExpired:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        sink_entry["latency_ms"] = latency_ms
        sink_entry["outcome"] = "timeout"
        log("haiku fallback timed out (6 sec)")
        _write_haiku_sink(sink_entry)
        return None, "timeout"

    except FileNotFoundError:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        sink_entry["latency_ms"] = latency_ms
        sink_entry["outcome"] = "cli_absent"
        log("haiku fallback: `claude` CLI not found on PATH")
        _write_haiku_sink(sink_entry)
        return None, "cli_absent"

    except KeyboardInterrupt:
        latency_ms = int((time.monotonic() - t_start) * 1000)
        sink_entry["latency_ms"] = latency_ms
        sink_entry["outcome"] = "miss"
        _write_haiku_sink(sink_entry)
        raise  # Re-raise; do not suppress Ctrl-C


def _write_haiku_sink(entry: dict) -> None:
    """Append *entry* as a JSON line to the Haiku fallback sink. Never raises."""
    try:
        HAIKU_SINK.parent.mkdir(parents=True, exist_ok=True)
        with open(HAIKU_SINK, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        log(f"haiku sink write failed: {exc}")


def main():
    try:
        raw = sys.stdin.read()
    except Exception:
        return
    if not raw:
        return
    try:
        hook_input = json.loads(raw)
    except Exception:
        return

    transcript_path = hook_input.get("transcript_path", "")
    assistant_text = get_last_assistant_text(transcript_path)
    if not assistant_text:
        return

    if not detected_qa_pass(assistant_text):
        return  # Not a completed-task turn

    # Issue 1 fix: SCOPE-field-first to avoid prose-mention false positives
    qa_block = extract_qa_block(assistant_text)
    scope_match = PATTERN_SCOPE.search(qa_block)
    if scope_match:
        scope_text = scope_match.group(1)
        scope_ids = list(dict.fromkeys(PATTERN_TASK_ID.findall(scope_text)))
        if scope_ids:
            candidate_ids = scope_ids  # SCOPE field provided IDs — these are authoritative
        else:
            candidate_ids = list(dict.fromkeys(PATTERN_TASK_ID.findall(assistant_text)))  # fallback
    else:
        candidate_ids = list(dict.fromkeys(PATTERN_TASK_ID.findall(assistant_text)))

    # Multi-candidate guard: if more than one ID survives extraction, log + take only the first
    if len(candidate_ids) > 1:
        log(f"Multi-candidate TIDs {candidate_ids}; using first only ({candidate_ids[0]}) — rest may be prose mentions of completed work")
        candidate_ids = candidate_ids[:1]

    if not candidate_ids:
        if HAIKU_ENABLED:
            # --- Haiku fallback (v1.2, opt-in via H4_ENABLE_HAIKU=1) ---
            log("static regex found no TASK-ID; invoking Haiku fallback")
            excerpt = assistant_text[:EXCERPT_MAX]
            haiku_id, _outcome = _invoke_haiku_fallback(excerpt)
            if haiku_id is not None:
                # Check plan membership before accepting
                _h_active = detect_active_project()
                _h_plans = find_task_plans(_h_active)
                _h_match = regex_match([haiku_id], _h_plans) if _h_plans else None
                if _h_match is not None:
                    log(f"haiku fallback: accepted {haiku_id!r}")
                    # Fall through with the Haiku-derived match directly
                    match = _h_match
                    line_hash = hashlib.sha256(match["original_line"].encode()).hexdigest()[:16]
                    if is_recent_duplicate(line_hash):
                        log(f"Dedup: line for {match['task_id']} synced within {DEDUP_WINDOW_HOURS}h; skipping")
                        return
                    summary = compose_summary(assistant_text)
                    replacement_line = match["original_line"].replace("- [ ]", "- [x]", 1)
                    if summary:
                        replacement_line = replacement_line.rstrip() + f"  ← {summary}"
                    if DRY_RUN:
                        log(f"DRY_RUN: would mark {match['file'].name} line {match['line_index']+1} as [x] (task={match['task_id']})")
                        return
                    try:
                        write_undo_entry(match, replacement_line)
                    except Exception as e:
                        log(f"undo log write failed; mutation skipped for safety: {e}")
                        return
                    try:
                        apply_replacement(match, replacement_line)
                    except Exception as e:
                        log(f"apply_replacement failed: {e}")
                        return
                    if not verify_write(match, replacement_line):
                        log(f"WRITE VERIFY FAILED for {match['file'].name} line {match['line_index']+1}; reverting")
                        revert_via_undo(match)
                        return
                    record_dedup(line_hash)
                    log(f"SYNCED (haiku) {match['file'].name} line {match['line_index']+1} task={match['task_id']}")
                    return
                else:
                    # Second JSONL entry overrides the optimistic "hit" outcome from _invoke_haiku_fallback
                    _write_haiku_sink({
                        "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                        "exit_code": None,
                        "latency_ms": 0,
                        "extracted_id": haiku_id,
                        "outcome": "not_in_plan",
                    })
                    log(f"haiku ID {haiku_id!r} not in any open [ ] line — skipping")
        return  # no candidate IDs (regex miss, Haiku disabled or also missed)

    active = detect_active_project()
    plans = find_task_plans(active)
    if not plans:
        log(f"No task_plan.md found (active={active})")
        return

    match = regex_match(candidate_ids, plans)
    if match is None:
        log(f"TASK-ID(s) {candidate_ids} not in any open [ ] line; already marked or wrong project")
        return

    # Dedup
    line_hash = hashlib.sha256(match["original_line"].encode()).hexdigest()[:16]
    if is_recent_duplicate(line_hash):
        log(f"Dedup: line for {match['task_id']} synced within {DEDUP_WINDOW_HOURS}h; skipping")
        return

    summary = compose_summary(assistant_text)
    # Replacement is single-line — embed summary inline (no newline) to keep file line indices stable
    replacement_line = match["original_line"].replace("- [ ]", "- [x]", 1)
    if summary:
        replacement_line = replacement_line.rstrip() + f"  ← {summary}"

    if DRY_RUN:
        log(f"DRY_RUN: would mark {match['file'].name} line {match['line_index']+1} as [x] (task={match['task_id']})")
        log(f"  FROM: {match['original_line'][:120]}")
        log(f"  TO:   {replacement_line[:120]}")
        return

    try:
        write_undo_entry(match, replacement_line)
    except Exception as e:
        log(f"undo log write failed; mutation skipped for safety: {e}")
        return

    try:
        apply_replacement(match, replacement_line)
    except Exception as e:
        log(f"apply_replacement failed: {e}")
        return

    if not verify_write(match, replacement_line):
        log(f"WRITE VERIFY FAILED for {match['file'].name} line {match['line_index']+1}; reverting")
        revert_via_undo(match)
        return

    record_dedup(line_hash)
    log(f"SYNCED {match['file'].name} line {match['line_index']+1} task={match['task_id']}")


def selftest():
    """Smoke-test PATTERN_TASK_ID against fixture inputs.
    Cases:
      T-SM-1   (existing, single-segment numeric trailing) — H-4
      T-SM-2   (existing, multi-char prefix + digit) — EXAMPLE-CLEANUP-BUILD
      T-SM-3   (existing, with trailing space variant) — H-4 phrase
      T-SM-OBS (v1.1 NEW, alpha trailing) — OBS-V2-A
      T-SM-ECC (v1.1 NEW, 5+ char prefix + multi-segment) — ECC-LEARN-A2
      T-SM-FP-section  (regression: prose mention, no **) — "section 5-A"
      T-SM-FP-task     (regression: prose mention, no **) — "task 12-B"
      T-SM-no-id (existing, no ID present) — "QA REPORT PASS: 5/5"
      T-SM-FP-date     (regression: bare date string) — "**2026-05-10**"
    """
    cases = [
        ("T-SM-1",   "Built **H-4** under the audit-driven directive.",                          "H-4"),
        ("T-SM-2",   "Applied **EXAMPLE-CLEANUP-BUILD** to live workflow.",                      "EXAMPLE-CLEANUP-BUILD"),
        ("T-SM-3",   "Closed **H-4 phrase** with PASS verdict.",                                 "H-4"),
        ("T-SM-OBS", "Resolved **OBS-V2-A** in the observability backlog.",                      "OBS-V2-A"),
        ("T-SM-ECC", "Promoted **ECC-LEARN-A2** to ratified status.",                            "ECC-LEARN-A2"),
        ("T-SM-FP-section", "Per section 5-A, the audit shows...",                               None),
        ("T-SM-FP-task",    "Continue with task 12-B handling.",                                 None),
        ("T-SM-no-id",      "QA REPORT PASS: 5/5 with no task ID anywhere",                     None),
        ("T-SM-FP-date",    "On **2026-05-10** we shipped the feature.",                         None),
        ("T-SM-lowercase",  "Mentioned **h-4** in lowercase, should be rejected.",               None),
        # KNOWN RESIDUAL: letter-prefixed date-style handles like **H-2026-05** match the new
        # regex (all segments are alphanumeric). Mitigated at runtime by regex_match() requiring
        # the ID to appear in an open `[ ]` task line. Documented here so the residual is
        # explicit; ID extraction is intentionally permissive — open-line filter is the gate.
        ("T-SM-RESIDUAL-date-handle", "Sprint **H-2026-05** in scope.",                          "H-2026-05"),
    ]
    passed = 0
    failed = 0
    for name, text, expected in cases:
        matches = PATTERN_TASK_ID.findall(text)
        if expected is None:
            if matches:
                print(f"FAIL {name}: expected NO match, got {matches}")
                failed += 1
            else:
                print(f"PASS {name}: correctly rejected")
                passed += 1
        else:
            if matches and matches[0] == expected:
                print(f"PASS {name}: matched {expected}")
                passed += 1
            else:
                print(f"FAIL {name}: expected {expected}, got {matches}")
                failed += 1

    # ---- T-SM-HAIKU-MOCK: monkey-patch subprocess to test Haiku branch logic ----
    import unittest.mock as _mock

    # Sub-test A: valid ID returned by mock subprocess -> extracted and validated
    mock_result_hit = _mock.MagicMock()
    mock_result_hit.returncode = 0
    mock_result_hit.stdout = "PROJ-TASK-002\n"
    mock_result_hit.stderr = ""

    with _mock.patch("subprocess.run", return_value=mock_result_hit):
        haiku_id_a, outcome_a = _invoke_haiku_fallback("The report covers PROJ-TASK-002 completion.")
    if haiku_id_a == "PROJ-TASK-002" and outcome_a == "hit":
        print(f"PASS T-SM-HAIKU-MOCK-A: extracted PROJ-TASK-002, outcome=hit")
        passed += 1
    else:
        print(f"FAIL T-SM-HAIKU-MOCK-A: expected ('PROJ-TASK-002','hit'), got ({haiku_id_a!r},{outcome_a!r})")
        failed += 1

    # Sub-test B: mock returns invalid (non-regex) output -> rejected as invalid_output
    mock_result_invalid = _mock.MagicMock()
    mock_result_invalid.returncode = 0
    mock_result_invalid.stdout = "not-a-valid-id because lowercase\n"
    mock_result_invalid.stderr = ""

    with _mock.patch("subprocess.run", return_value=mock_result_invalid):
        haiku_id_b, outcome_b = _invoke_haiku_fallback("some prose without bold ID")
    if haiku_id_b is None and outcome_b == "invalid_output":
        print(f"PASS T-SM-HAIKU-MOCK-B: invalid output correctly rejected")
        passed += 1
    else:
        print(f"FAIL T-SM-HAIKU-MOCK-B: expected (None,'invalid_output'), got ({haiku_id_b!r},{outcome_b!r})")
        failed += 1

    # Sub-test C: mock returns NONE -> outcome=miss
    mock_result_none = _mock.MagicMock()
    mock_result_none.returncode = 0
    mock_result_none.stdout = "NONE\n"
    mock_result_none.stderr = ""

    with _mock.patch("subprocess.run", return_value=mock_result_none):
        haiku_id_c, outcome_c = _invoke_haiku_fallback("prose with no task id")
    if haiku_id_c is None and outcome_c == "miss":
        print(f"PASS T-SM-HAIKU-MOCK-C: NONE output correctly treated as miss")
        passed += 1
    else:
        print(f"FAIL T-SM-HAIKU-MOCK-C: expected (None,'miss'), got ({haiku_id_c!r},{outcome_c!r})")
        failed += 1

    # Sub-test D: mock raises FileNotFoundError -> outcome=cli_absent
    with _mock.patch("subprocess.run", side_effect=FileNotFoundError("claude not found")):
        haiku_id_d, outcome_d = _invoke_haiku_fallback("some prose")
    if haiku_id_d is None and outcome_d == "cli_absent":
        print(f"PASS T-SM-HAIKU-MOCK-D: FileNotFoundError correctly mapped to cli_absent")
        passed += 1
    else:
        print(f"FAIL T-SM-HAIKU-MOCK-D: expected (None,'cli_absent'), got ({haiku_id_d!r},{outcome_d!r})")
        failed += 1

    print(f"\nSELFTEST RESULT: {passed} PASS / {failed} FAIL out of {len(cases) + 4} cases")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--undo":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        undo_last(n)
    elif len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        selftest()
    else:
        try:
            main()
        except Exception as e:
            log(f"UNHANDLED EXCEPTION: {e}")
        sys.exit(0)  # Always non-blocking
