"""
Observability database — SQLite analytics cache for governance monitoring.

Architecture: hooks → JSONL (append-only, canonical) → session-summary.py → observability.db (derived)
If observability.db corrupts, regenerate from JSONL sources.

Schema: 4 tables — sessions, kpi_values, tool_calls, agent_dispatches
"""

import os
import sqlite3

# Default DB path — can be overridden
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "observability.db"
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    duration_min REAL,
    cost_total REAL,
    cost_subagent REAL,
    model_mix TEXT,
    is_ralph_loop INTEGER DEFAULT 0,
    ghs_score REAL
);

CREATE TABLE IF NOT EXISTS kpi_values (
    session_id TEXT NOT NULL,
    kpi_name TEXT NOT NULL,
    layer TEXT NOT NULL,
    value REAL,
    threshold_status TEXT,
    PRIMARY KEY (session_id, kpi_name)
);

CREATE TABLE IF NOT EXISTS tool_calls (
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    PRIMARY KEY (session_id, tool_name)
);

CREATE TABLE IF NOT EXISTS agent_dispatches (
    session_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    was_declared INTEGER DEFAULT 0,
    was_invoked INTEGER DEFAULT 0,
    cost_usd REAL,
    PRIMARY KEY (session_id, agent_name)
);
"""


def get_connection(db_path=None):
    """Get a connection to the observability database, creating tables if needed."""
    path = db_path or DEFAULT_DB_PATH
    path = os.path.normpath(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")  # safer for OneDrive
    conn.executescript(SCHEMA_SQL)
    return conn


def upsert_session(conn, session_data):
    """Insert or replace a session record."""
    conn.execute(
        "INSERT OR REPLACE INTO sessions "
        "(session_id, date, duration_min, cost_total, cost_subagent, model_mix, is_ralph_loop, ghs_score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_data["session_id"],
            session_data["date"],
            session_data.get("duration_min"),
            session_data.get("cost_total"),
            session_data.get("cost_subagent"),
            session_data.get("model_mix"),
            session_data.get("is_ralph_loop", 0),
            session_data.get("ghs_score"),
        ),
    )


def upsert_kpi(conn, session_id, kpi_name, layer, value, status=None):
    """Insert or replace a KPI value."""
    conn.execute(
        "INSERT OR REPLACE INTO kpi_values (session_id, kpi_name, layer, value, threshold_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (session_id, kpi_name, layer, value, status),
    )


def upsert_tool_calls(conn, session_id, tool_counts):
    """Insert or replace tool call counts. tool_counts is a dict {tool_name: count}."""
    for name, count in tool_counts.items():
        conn.execute(
            "INSERT OR REPLACE INTO tool_calls (session_id, tool_name, count) VALUES (?, ?, ?)",
            (session_id, name, count),
        )


def upsert_agent_dispatches(conn, session_id, dispatches):
    """Insert or replace agent dispatch records.
    dispatches is a list of dicts {agent_name, was_declared, was_invoked, cost_usd}."""
    for d in dispatches:
        conn.execute(
            "INSERT OR REPLACE INTO agent_dispatches "
            "(session_id, agent_name, was_declared, was_invoked, cost_usd) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, d["agent_name"], d.get("was_declared", 0),
             d.get("was_invoked", 0), d.get("cost_usd")),
        )
