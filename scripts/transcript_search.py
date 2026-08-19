#!/usr/bin/env python3
"""Local FTS5 full-text search over this machine's Claude Code session transcripts.

Hermes P6 adaptation (vault pillar). Corpus: main-session transcripts
(<project>/<uuid>.jsonl), direct subagent transcripts
(<project>/<session>/subagents/agent-*.jsonl) and workflow-run subagent
transcripts (<project>/<session>/subagents/workflows/<run-id>/agent-*.jsonl).
journal.jsonl and memory-log.jsonl are excluded by name. The discovery rule is
depth-open under subagents/ on purpose.

Source priority doctrine: search results are this machine's own past agent
conversations. They are recall, not evidence about a live external system, and
they rank BELOW the existing priority chain: live system, then work files, then
memory, then transcripts. A transcript hit that contradicts the live system is
a prompt to re-check the live system, never a citation.

Read-only contract: this tool never opens a transcript for writing, never
locks, renames or deletes one. Its only write surface is its own index
directory (.claude/transcript-index/ by default), which must be git-ignored
before the first byte is written; the index subcommand refuses to run
otherwise. The index holds unscrubbed transcript text and never leaves the
vault (NDA gate sits at public push, vault-local storage is unrestricted).

Upstream citations (adapted, not vendored; repo github.com/NousResearch/hermes-agent):
- _sanitize_fts5_query adapted from hermes_state_search.py lines 1174-1232.
- The four calling shapes (search/discovery, scroll, read, browse) follow
  tools/session_search_tool.py lines 848-1159; bookended discovery context
  follows lines 993-1023.

Spec of record:
Projects/your-project/work/2026-08-18-hermes-p6-transcript-search-plan.md
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = os.path.join(
    os.environ.get("USERPROFILE", os.path.expanduser("~")), ".claude", "projects")
DEFAULT_DB = str(SCRIPT_DIR.parent / "transcript-index" / "transcripts.db")

EXCLUDED_NAMES = ("journal.jsonl", "memory-log.jsonl")
INDEXED_TYPES = ("user", "assistant")
FTS_OPERATOR_WORDS = {"AND", "OR", "NOT", "NEAR"}
DB_SIZE_GUARD_BYTES = 2 * 1024 ** 3  # 2 GiB runaway guard (spec Step 5)

SOURCE_PRIORITY_TEXT = (
    "Search results are this machine's own past agent conversations. They are "
    "recall, not evidence about a live external system, and they rank BELOW the "
    "existing priority chain: live system, then work files, then memory, then "
    "transcripts. A transcript hit that contradicts the live system is a prompt "
    "to re-check the live system, never a citation."
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  project_dir TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('session','subagent','workflow-subagent')),
  size_indexed INTEGER NOT NULL DEFAULT 0,
  mtime_indexed REAL,
  last_run_ts TEXT,
  lines_seen INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL,
  session_id TEXT,
  agent_id TEXT,
  uuid TEXT,
  ts TEXT,
  role TEXT,
  line_no INTEGER,
  byte_offset INTEGER
);
CREATE INDEX IF NOT EXISTS idx_messages_file ON messages(file_id);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_agent ON messages(agent_id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
  USING fts5(text, content='', contentless_delete=1);
"""


def reconfigure_streams():
    """cp1250-safe output: force UTF-8 with replacement on stdout/stderr.

    Display paths print arbitrary transcript text; the Windows console default
    (cp1250 here) would raise UnicodeEncodeError on characters outside it.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Discovery walk (spec section 1.1; same classification as the frozen Step 1
# command; the two excluded names are checked first, which is equivalent on
# any corpus that has no top-level file with an excluded name)
# ---------------------------------------------------------------------------

def discover(root):
    root = os.path.abspath(root)
    for proj in sorted(os.listdir(root)):
        pdir = os.path.join(root, proj)
        if not os.path.isdir(pdir):
            continue
        for dirpath, dirnames, filenames in os.walk(pdir):
            for fn in filenames:
                if not fn.endswith(".jsonl"):
                    continue
                if fn in EXCLUDED_NAMES:
                    continue
                full = os.path.join(dirpath, fn)
                parts = os.path.relpath(full, pdir).replace(os.sep, "/").split("/")
                if len(parts) == 1:
                    yield full, proj, "session"
                elif "subagents" in parts[:-1] and fn.startswith("agent-"):
                    si = parts.index("subagents")
                    kind = "subagent" if len(parts) == si + 2 else "workflow-subagent"
                    yield full, proj, kind


# ---------------------------------------------------------------------------
# Index-content policy (spec section 3.2)
# ---------------------------------------------------------------------------

def extract_text(rec):
    """Return (text, role) for an indexable record, (None, None) otherwise.

    Indexed: text blocks of user/assistant records. Excluded: every other
    record type, tool_result blocks, thinking blocks, attachments.
    """
    if not isinstance(rec, dict) or rec.get("type") not in INDEXED_TYPES:
        return None, None
    msg = rec.get("message")
    if not isinstance(msg, dict):
        return None, None
    role = msg.get("role") or rec.get("type")
    content = msg.get("content")
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
    text = "\n".join(p for p in parts if p.strip())
    if not text.strip():
        return None, None
    return text, role


# ---------------------------------------------------------------------------
# Ignore guard (spec section 3.1 defense in depth)
# ---------------------------------------------------------------------------

def _git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True, text=True)


def guard_index_ignored(db_path):
    """Refuse to write the index if its directory sits in a git work tree and
    is not git-ignored. Runs BEFORE the directory or any byte is created."""
    target_dir = os.path.abspath(os.path.dirname(db_path))
    probe_dir = target_dir
    while not os.path.isdir(probe_dir):
        parent = os.path.dirname(probe_dir)
        if parent == probe_dir:
            break
        probe_dir = parent
    try:
        r = _git("-C", probe_dir, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        print("transcript_search: git executable not found; cannot verify the "
              "index directory is git-ignored; refusing to write (fail-safe)",
              file=sys.stderr)
        raise SystemExit(2)
    if r.returncode != 0:
        return  # not inside a git work tree: nothing to guard
    top = os.path.normpath(r.stdout.strip())
    try:
        rel = os.path.relpath(target_dir, top)
    except ValueError:
        return  # different drive: not inside this work tree
    if rel.startswith(".."):
        return
    # Probe the db file path: a "dir/" .gitignore pattern matches it even
    # while the directory does not exist yet (bare-dir probes do not).
    probe = os.path.join(target_dir, os.path.basename(db_path) or "transcripts.db")
    r2 = _git("-C", top, "check-ignore", "-q", "--", probe)
    if r2.returncode == 0:
        return
    print(f"transcript_search: refusing to write index: {target_dir} is inside "
          f"git work tree {top} and is not git-ignored; add the directory to "
          f".gitignore first (auto-commit runs git add -A)", file=sys.stderr)
    raise SystemExit(2)


# ---------------------------------------------------------------------------
# Incremental indexer (spec sections 3.1, 3.3)
# ---------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.files_new = 0
        self.files_updated = 0
        self.files_reindexed = 0
        self.files_rescanned = 0
        self.files_skipped = 0
        self.messages_new = 0
        self.skipped_tails = 0
        self.unparsable_lines = 0
        self.replacement_lines = 0
        self.replacement_files = {}


def _strip_lone_surrogates(text):
    """JSON \\uXXXX escapes can yield unpaired surrogates that raw-byte
    decoding never sees; they cannot encode to UTF-8, so SQLite storage (and
    strict encoders) would raise. Replace each with U+FFFD, detection-only,
    same policy as the decode-stage replacement counter."""
    try:
        text.encode("utf-8")
        return text, False
    except UnicodeEncodeError:
        cleaned = "".join(
            "�" if 0xD800 <= ord(ch) <= 0xDFFF else ch for ch in text)
        return cleaned, True


def clean_line_start(path, mark):
    if mark == 0:
        return True
    with open(path, "rb") as f:
        f.seek(mark - 1)
        return f.read(1) == b"\n"


def parse_from(conn, path, fid, mark, lines_seen, stats):
    """Stream lines from byte offset `mark`; never load the file whole.

    Torn-tail rule: a final line that lacks a newline or fails json.loads is
    skipped and the high-water mark does not advance past it. A mid-file
    complete line that fails json.loads is counted and advanced past.
    Any decoded line containing U+FFFD increments replacement_lines.
    """
    state = {"new_mark": mark, "lines_seen": lines_seen}

    def consume(raw, start, is_last):
        end = start + len(raw)
        if is_last and not raw.endswith(b"\n"):
            stats.skipped_tails += 1
            return
        text = raw.decode("utf-8", errors="replace")
        if "�" in text:
            stats.replacement_lines += 1
            stats.replacement_files[path] = stats.replacement_files.get(path, 0) + 1
        try:
            rec = json.loads(text)
        except ValueError:
            if is_last:
                stats.skipped_tails += 1
                return
            state["lines_seen"] += 1
            state["new_mark"] = end
            stats.unparsable_lines += 1
            return
        state["lines_seen"] += 1
        mtext, role = extract_text(rec)
        if mtext is not None:
            mtext, had_surrogates = _strip_lone_surrogates(mtext)
            if had_surrogates and "�" not in text:
                stats.replacement_lines += 1
                stats.replacement_files[path] = stats.replacement_files.get(path, 0) + 1
            cur = conn.execute(
                "INSERT INTO messages(file_id, session_id, agent_id, uuid, ts, "
                "role, line_no, byte_offset) VALUES (?,?,?,?,?,?,?,?)",
                (fid, rec.get("sessionId"), rec.get("agentId"), rec.get("uuid"),
                 rec.get("timestamp"), role, state["lines_seen"], start))
            conn.execute("INSERT INTO messages_fts(rowid, text) VALUES (?,?)",
                         (cur.lastrowid, mtext))
            stats.messages_new += 1
        state["new_mark"] = end

    with open(path, "rb") as f:  # read-only, shared-read; transcripts are never written
        f.seek(mark)
        offset = mark
        prev = None
        for raw in f:
            start = offset
            offset += len(raw)
            if prev is not None:
                consume(prev[0], prev[1], False)
            prev = (raw, start)
        if prev is not None:
            consume(prev[0], prev[1], True)
    return state["new_mark"], state["lines_seen"]


def process_file(conn, path, proj, kind, run_ts, stats):
    st = os.stat(path)
    row = conn.execute(
        "SELECT id, size_indexed, mtime_indexed, lines_seen FROM files WHERE path=?",
        (path,)).fetchone()
    conn.execute("BEGIN")
    try:
        reindexed = False
        if row is None:
            cur = conn.execute(
                "INSERT INTO files(path, project_dir, kind, size_indexed, "
                "mtime_indexed, last_run_ts, lines_seen) VALUES (?,?,?,0,?,?,0)",
                (path, proj, kind, st.st_mtime, run_ts))
            fid, mark, lines_seen = cur.lastrowid, 0, 0
            stats.files_new += 1
        else:
            fid, mark, mtime_prev, lines_seen = row
            if st.st_size == mark and mtime_prev == st.st_mtime:
                conn.execute("UPDATE files SET last_run_ts=? WHERE id=?", (run_ts, fid))
                conn.execute("COMMIT")
                stats.files_skipped += 1
                return
            if st.st_size < mark or not clean_line_start(path, mark):
                # Shrunk or rewritten file: drop this file's rows, reindex from zero.
                conn.execute("DELETE FROM messages_fts WHERE rowid IN "
                             "(SELECT id FROM messages WHERE file_id=?)", (fid,))
                conn.execute("DELETE FROM messages WHERE file_id=?", (fid,))
                mark, lines_seen = 0, 0
                reindexed = True
                stats.files_reindexed += 1
        entry_mark = mark
        new_mark, lines_seen = parse_from(conn, path, fid, mark, lines_seen, stats)
        if row is not None and not reindexed:
            if new_mark > entry_mark:
                stats.files_updated += 1
            else:
                stats.files_rescanned += 1  # torn tail re-attempted, no progress
        conn.execute(
            "UPDATE files SET size_indexed=?, mtime_indexed=?, last_run_ts=?, "
            "lines_seen=? WHERE id=?",
            (new_mark, st.st_mtime, run_ts, lines_seen, fid))
        conn.execute("COMMIT")
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise


def db_total_bytes(db_path):
    total = 0
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            total += os.path.getsize(p)
    return total


def peak_memory_bytes():
    """PeakWorkingSetSize via psapi GetProcessMemoryInfo (stdlib ctypes)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = PROCESS_MEMORY_COUNTERS()
        pmc.cb = ctypes.sizeof(pmc)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(),
                                      ctypes.byref(pmc), pmc.cb):
            return int(pmc.PeakWorkingSetSize)
    except Exception:
        return None
    return None


def cmd_index(args):
    root = os.path.abspath(args.root)
    db_path = os.path.abspath(args.db)
    if not os.path.isdir(root):
        print(f"transcript_search: corpus root not found: {root}", file=sys.stderr)
        return 2
    guard_index_ignored(db_path)
    if args.rebuild:
        for suffix in ("", "-wal", "-shm"):
            p = db_path + suffix
            if os.path.exists(p):
                os.remove(p)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    t0 = time.monotonic()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path, autocommit=True)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.executescript(SCHEMA)
        stats = Stats()
        for full, proj, kind in discover(root):
            process_file(conn, full, proj, kind, run_ts, stats)
            if db_total_bytes(db_path) > DB_SIZE_GUARD_BYTES:
                print("transcript_search: ABORT: index database crossed the "
                      f"{DB_SIZE_GUARD_BYTES} byte runaway guard at {db_path}; "
                      "stopping before filling the disk", file=sys.stderr)
                return 3
        stale = []
        for pth, lrt in conn.execute("SELECT path, last_run_ts FROM files"):
            if not os.path.exists(pth):
                stale.append((pth, lrt))
        kind_counts = dict(conn.execute(
            "SELECT kind, COUNT(*) FROM files GROUP BY kind").fetchall())
        messages_total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        sessions_seen = conn.execute(
            "SELECT COUNT(DISTINCT session_id) FROM messages "
            "WHERE session_id IS NOT NULL").fetchone()[0]
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    elapsed = time.monotonic() - t0
    print(f"index root: {root}")
    print(f"index db: {db_path}")
    for kind in ("session", "subagent", "workflow-subagent"):
        print(f"files ({kind}): {kind_counts.get(kind, 0)}")
    print(f"files new: {stats.files_new}")
    print(f"files updated: {stats.files_updated}")
    print(f"files reindexed: {stats.files_reindexed}")
    print(f"files rescanned: {stats.files_rescanned}")
    print(f"files skipped: {stats.files_skipped}")
    print(f"messages new: {stats.messages_new}")
    print(f"messages total: {messages_total}")
    print(f"sessions seen: {sessions_seen}")
    print(f"skipped tails: {stats.skipped_tails}")
    print(f"unparsable lines: {stats.unparsable_lines}")
    print(f"stale_files: {len(stale)}")
    for pth, lrt in stale[:20]:
        print(f"stale: {pth} (last indexed {lrt})")
    print(f"replacement_lines: {stats.replacement_lines}")
    for pth, n in sorted(stats.replacement_files.items())[:20]:
        print(f"replacement file: {pth} ({n} lines)")
    if stats.replacement_lines:
        print("WARNING: replacement_lines is nonzero: some transcript lines "
              "contained undecodable bytes and were indexed with U+FFFD "
              "substitutions (detection only, no repair)")
    print(f"elapsed seconds: {elapsed:.2f}")
    print(f"db bytes: {db_total_bytes(db_path)}")
    peak = peak_memory_bytes()
    print(f"peak memory bytes: {peak if peak is not None else 'unknown'}")
    return 0


# ---------------------------------------------------------------------------
# Query sanitization (adapted from Hermes hermes_state_search.py:1174-1232)
# ---------------------------------------------------------------------------

def _sanitize_fts5_query(query):
    """Strip FTS5 grammar (AND/OR/NOT/NEAR, ^ * : quotes, parentheses) from
    user input, quote each surviving token, join with implicit AND.
    Returns None when nothing survives."""
    tokens = re.findall(r"\w+", query, flags=re.UNICODE)
    tokens = [t for t in tokens if t.upper() not in FTS_OPERATOR_WORDS]
    if not tokens:
        return None
    return " ".join('"' + t + '"' for t in tokens)


# ---------------------------------------------------------------------------
# Query surfaces (spec sections 3.2, 3.5), four Hermes calling shapes
# ---------------------------------------------------------------------------

def open_db_readonly(db_path):
    db_path = os.path.abspath(db_path)
    if not os.path.exists(db_path):
        print(f"transcript_search: index not found at {db_path}; run the "
              "index subcommand first", file=sys.stderr)
        raise SystemExit(2)
    uri = "file:///" + Path(db_path).as_posix() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def load_message_text(path, byte_offset):
    """Re-open the transcript at the stored offset (read-only) and re-extract
    the display text. Returns (text, error) with error in (None, 'missing',
    'truncated')."""
    try:
        with open(path, "rb") as f:
            f.seek(byte_offset)
            raw = f.readline()
    except OSError:
        return None, "missing"
    if not raw:
        return None, "truncated"
    text = raw.decode("utf-8", errors="replace")
    try:
        rec = json.loads(text)
    except ValueError:
        return None, "truncated"
    mtext, _role = extract_text(rec)
    return (mtext if mtext is not None else ""), None


class Display:
    """Missing-file and truncation notices on every display path; one notice
    per file, never a traceback (spec section 3.5)."""

    def __init__(self):
        self.notified = set()

    def text_for(self, file_row, msg_row):
        path = file_row["path"]
        text, err = load_message_text(path, msg_row["byte_offset"])
        if err == "missing":
            if path not in self.notified:
                print(f"missing transcript: {path} "
                      f"(last indexed {file_row['last_run_ts']})")
                self.notified.add(path)
            return None
        if err == "truncated":
            print(f"truncated read: {path} at offset {msg_row['byte_offset']} "
                  "(live append in progress)")
            return None
        return text


def resolve_ident(conn, ident):
    """Session id first (main-session rows), then agent id."""
    rows = conn.execute(
        "SELECT DISTINCT f.* FROM files f JOIN messages m ON m.file_id=f.id "
        "WHERE m.session_id=? AND m.agent_id IS NULL", (ident,)).fetchall()
    if rows:
        return rows
    return conn.execute(
        "SELECT DISTINCT f.* FROM files f JOIN messages m ON m.file_id=f.id "
        "WHERE m.agent_id=?", (ident,)).fetchall()


def _file_messages(conn, file_id):
    return conn.execute(
        "SELECT * FROM messages WHERE file_id=? ORDER BY byte_offset",
        (file_id,)).fetchall()


def _one_line(text):
    return " ".join(text.split())


def cmd_search(args):
    conn = open_db_readonly(args.db)
    q = _sanitize_fts5_query(args.query)
    if q is None:
        print("transcript_search: empty query after sanitization; give at "
              "least one word (FTS5 operators are stripped from input)",
              file=sys.stderr)
        return 2
    sql = ("SELECT m.id AS mid, m.file_id, m.session_id, m.agent_id, m.ts, "
           "m.role, m.byte_offset FROM messages_fts "
           "JOIN messages m ON m.id = messages_fts.rowid "
           "JOIN files f ON f.id = m.file_id WHERE messages_fts MATCH ?")
    if args.main_only:
        sql += " AND f.kind = 'session'"
    sql += " ORDER BY rank LIMIT ?"
    rows = conn.execute(sql, (q, args.limit)).fetchall()
    disp = Display()
    for i, m in enumerate(rows, 1):
        f = conn.execute("SELECT * FROM files WHERE id=?",
                         (m["file_id"],)).fetchone()
        head = f"result {i}: session {m['session_id']}"
        if m["agent_id"]:
            head += f" agent {m['agent_id']}"
        head += f" kind {f['kind']} ts {m['ts']} file {f['path']}"
        print(head)
        msgs = _file_messages(conn, m["file_id"])
        idx = next((j for j, r in enumerate(msgs) if r["id"] == m["mid"]), None)
        if idx is not None:
            # window around the match: 2 before, the match, 2 after
            for j in range(max(0, idx - 2), min(len(msgs), idx + 3)):
                r = msgs[j]
                t = disp.text_for(f, r)
                if t is None:
                    continue
                tag = "match| " if j == idx else "ctx| "
                print(f"  {tag}{r['role']}: {_one_line(t)}")
            # bookends: first 3 and last 3 messages of the hit transcript
            for r in msgs[:3]:
                t = disp.text_for(f, r)
                if t is not None:
                    print(f"  first| {r['role']}: {_one_line(t)}")
            for r in msgs[-3:]:
                t = disp.text_for(f, r)
                if t is not None:
                    print(f"  last| {r['role']}: {_one_line(t)}")
    print(f"results: {len(rows)}")
    return 0


def cmd_scroll(args):
    conn = open_db_readonly(args.db)
    files = resolve_ident(conn, args.ident)
    if not files:
        print(f"transcript_search: no indexed session or agent matches "
              f"{args.ident!r}", file=sys.stderr)
        return 2
    disp = Display()
    for f in files:
        msgs = _file_messages(conn, f["id"])
        if not msgs:
            continue
        anchor = len(msgs) - 1
        lo = max(0, anchor - args.before)
        hi = min(len(msgs), anchor + args.after + 1)
        print(f"scroll {args.ident} kind {f['kind']} file {f['path']} "
              f"(messages {lo + 1}..{hi} of {len(msgs)})")
        for r in msgs[lo:hi]:
            t = disp.text_for(f, r)
            if t is None:
                continue
            print(f"{r['line_no']} {r['ts']} {r['role']}| {t}")
    return 0


def cmd_read(args):
    conn = open_db_readonly(args.db)
    files = resolve_ident(conn, args.ident)
    if not files:
        print(f"transcript_search: no indexed session or agent matches "
              f"{args.ident!r}", file=sys.stderr)
        return 2
    disp = Display()
    for f in files:
        print(f"read {args.ident} kind {f['kind']} file {f['path']}")
        for r in _file_messages(conn, f["id"]):
            t = disp.text_for(f, r)
            if t is None:
                continue
            print(f"{r['line_no']} {r['ts']} {r['role']}| {t}")
    return 0


def _run_id_from_path(path):
    parts = str(path).replace(os.sep, "/").split("/")
    try:
        si = parts.index("subagents")
        if si + 2 < len(parts) and parts[si + 1] == "workflows":
            return parts[si + 2]
    except ValueError:
        pass
    return "(unknown-run)"


def _session_label(conn, disp, f):
    """First user text message of the transcript, truncated to 120 chars."""
    r = conn.execute(
        "SELECT * FROM messages WHERE file_id=? AND role='user' "
        "ORDER BY byte_offset LIMIT 1", (f["id"],)).fetchone()
    if r is None:
        return "(no user message indexed)"
    t = disp.text_for(f, r)
    if t is None:
        return "(transcript unavailable)"
    return _one_line(t)[:120]


def cmd_browse(args):
    conn = open_db_readonly(args.db)
    disp = Display()
    if args.agents:
        sid = args.agents
        rows = conn.execute(
            "SELECT f.id, f.path, f.kind, f.last_run_ts, COUNT(m.id) AS n, "
            "MIN(m.agent_id) AS agent_id FROM files f "
            "JOIN messages m ON m.file_id=f.id "
            "WHERE m.session_id=? AND m.agent_id IS NOT NULL "
            "GROUP BY f.id ORDER BY f.path", (sid,)).fetchall()
        print(f"agents for session {sid}:")
        wf = {}
        for r in rows:
            if r["kind"] == "subagent":
                print(f"[subagent] {r['agent_id']} ({r['n']} msgs)")
            elif r["kind"] == "workflow-subagent":
                wf.setdefault(_run_id_from_path(r["path"]), []).append(r)
        for run_id in sorted(wf):
            print(f"workflow {run_id}:")
            for r in wf[run_id]:
                print(f"  [workflow-subagent] {r['agent_id']} ({r['n']} msgs)")
        return 0
    sql = ("SELECT f.*, COUNT(m.id) AS n, MAX(m.ts) AS last_ts FROM files f "
           "LEFT JOIN messages m ON m.file_id=f.id WHERE f.kind='session'")
    params = []
    if args.project:
        sql += " AND f.project_dir=?"
        params.append(args.project)
    sql += " GROUP BY f.id ORDER BY (last_ts IS NULL), last_ts DESC LIMIT ?"
    params.append(args.limit)
    for f in conn.execute(sql, params):
        stem = os.path.splitext(os.path.basename(f["path"]))[0]
        label = _session_label(conn, disp, f)
        print(f"{stem}  {f['last_ts']}  {f['n']} msgs  {f['project_dir']}  {label}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="transcript_search.py",
        description="Local FTS5 search over Claude Code session transcripts "
                    "(read-only toward transcripts; index is vault-local and "
                    "git-ignored).",
        epilog="Source priority: " + SOURCE_PRIORITY_TEXT,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="build or refresh the index")
    p_index.add_argument("--root", default=DEFAULT_ROOT,
                         help="transcript corpus root (default: %(default)s)")
    p_index.add_argument("--db", default=DEFAULT_DB,
                         help="index database path (default: %(default)s)")
    p_index.add_argument("--rebuild", action="store_true",
                         help="drop and recreate the whole index (v1 stale-row remedy)")
    p_index.set_defaults(func=cmd_index)

    p_search = sub.add_parser("search", help="FTS5 discovery with bookended context")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.add_argument("--main-only", action="store_true",
                          help="restrict hits to main-session transcripts")
    p_search.add_argument("--db", default=DEFAULT_DB)
    p_search.set_defaults(func=cmd_search)

    p_scroll = sub.add_parser("scroll", help="window of messages at the end of a "
                                             "session or agent transcript")
    p_scroll.add_argument("ident", help="session id or agent id")
    p_scroll.add_argument("--before", type=int, default=5)
    p_scroll.add_argument("--after", type=int, default=0)
    p_scroll.add_argument("--db", default=DEFAULT_DB)
    p_scroll.set_defaults(func=cmd_scroll)

    p_read = sub.add_parser("read", help="print a whole session or agent transcript")
    p_read.add_argument("ident", help="session id or agent id")
    p_read.add_argument("--db", default=DEFAULT_DB)
    p_read.set_defaults(func=cmd_read)

    p_browse = sub.add_parser("browse", help="list sessions, or a session's agents")
    p_browse.add_argument("--limit", type=int, default=20)
    p_browse.add_argument("--project", help="filter by project directory name")
    p_browse.add_argument("--agents", metavar="SESSION",
                          help="list this session's subagent transcripts")
    p_browse.add_argument("--db", default=DEFAULT_DB)
    p_browse.set_defaults(func=cmd_browse)
    return parser


def main(argv=None):
    reconfigure_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "locked" in msg or "busy" in msg:
            print("transcript_search: database is locked by another process "
                  f"(busy_timeout expired): {e}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
