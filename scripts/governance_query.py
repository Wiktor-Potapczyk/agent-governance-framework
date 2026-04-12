"""
Governance Query — CLI tool to query observability.db with layer filtering.

Usage:
    python governance_query.py                    # all layers, all sessions
    python governance_query.py --layer governance  # governance KPIs only
    python governance_query.py --layer work        # work pattern KPIs only
    python governance_query.py --layer cost        # cost KPIs only
    python governance_query.py --last 5           # last 5 sessions
    python governance_query.py --session 59710481 # specific session

Iteration 2, task I2-3.
"""

import argparse
import os
import sqlite3
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "observability.db"))

LAYER_KPIS = {
    "governance": ["DAR", "HSR", "DZUR"],
    "work": ["WP1_TotalTools", "WP2_HumanTurns", "WP3_MCPRatio", "WP4_Artifacts"],
    "cost": ["SC", "SC_SubRatio", "HOR"],
}


def query_sessions(conn, last_n=None, session_prefix=None):
    """Fetch session records."""
    sql = "SELECT * FROM sessions ORDER BY date DESC"
    rows = conn.execute(sql).fetchall()
    cols = [d[0] for d in conn.execute("SELECT * FROM sessions LIMIT 0").description]

    if session_prefix:
        rows = [r for r in rows if r[0].startswith(session_prefix)]
    if last_n:
        rows = rows[:last_n]

    return cols, rows


def query_kpis(conn, session_ids, layer=None):
    """Fetch KPI values for given sessions, optionally filtered by layer."""
    if not session_ids:
        return []

    placeholders = ",".join("?" * len(session_ids))
    sql = f"SELECT session_id, kpi_name, layer, value, threshold_status FROM kpi_values WHERE session_id IN ({placeholders})"
    if layer and layer in LAYER_KPIS:
        kpi_names = LAYER_KPIS[layer]
        kpi_ph = ",".join("?" * len(kpi_names))
        sql += f" AND kpi_name IN ({kpi_ph})"
        rows = conn.execute(sql, session_ids + kpi_names).fetchall()
    else:
        rows = conn.execute(sql, session_ids).fetchall()

    return rows


def format_output(cols, sessions, kpi_rows, layer):
    """Format output for terminal display."""
    if not sessions:
        print("No sessions found.")
        return

    print(f"\n{'='*80}")
    title = f"Governance Query — {layer.upper() if layer else 'ALL LAYERS'}"
    print(f"  {title}")
    print(f"{'='*80}\n")

    # Group KPIs by session
    kpi_by_session = {}
    for sid, kpi_name, kpi_layer, value, status in kpi_rows:
        if sid not in kpi_by_session:
            kpi_by_session[sid] = {}
        kpi_by_session[sid][kpi_name] = (value, status, kpi_layer)

    for row in sessions:
        # W5 fix: use column names instead of hardcoded indices
        row_dict = dict(zip(cols, row))
        sid = row_dict["session_id"]
        date = row_dict["date"]
        duration = row_dict.get("duration_min")
        cost = row_dict.get("cost_total")
        is_ralph = row_dict.get("is_ralph_loop")
        ghs = row_dict.get("ghs_score")

        ralph_tag = " [RALPH]" if is_ralph else ""
        print(f"  Session: {sid[:12]}  Date: {date}  GHS: {ghs}{ralph_tag}")

        if duration:
            print(f"  Duration: {duration:.0f} min  Cost: ${cost:.2f}")
        print()

        kpis = kpi_by_session.get(sid, {})

        # Print by layer
        layers_to_show = [layer] if layer else ["governance", "work", "cost"]
        for l in layers_to_show:
            kpi_names = LAYER_KPIS.get(l, [])
            relevant = {k: v for k, v in kpis.items() if k in kpi_names}
            if relevant:
                print(f"    {l.upper()}:")
                for kpi_name in kpi_names:
                    if kpi_name in relevant:
                        val, status, _ = relevant[kpi_name]
                        status_str = f" [{status}]" if status else ""
                        if val is not None:
                            if kpi_name in ("DAR", "DZUR", "WP3_MCPRatio", "SC_SubRatio"):
                                print(f"      {kpi_name}: {val:.1f}%{status_str}")
                            elif kpi_name == "HSR":
                                print(f"      {kpi_name}: {val:.3f}{status_str}")
                            elif kpi_name in ("SC",):
                                print(f"      {kpi_name}: ${val:.2f}{status_str}")
                            elif kpi_name == "HOR":
                                print(f"      {kpi_name}: {val:.0f}ms{status_str}")
                            else:
                                print(f"      {kpi_name}: {val:.0f}{status_str}")
                        else:
                            print(f"      {kpi_name}: N/A{status_str}")
                print()

        print(f"  {'-'*60}")


def main():
    parser = argparse.ArgumentParser(description="Query governance observability database")
    parser.add_argument("--layer", choices=["governance", "work", "cost"], help="Filter by KPI layer")
    parser.add_argument("--last", type=int, help="Show last N sessions")
    parser.add_argument("--session", help="Filter by session ID prefix")
    parser.add_argument("--db", help="Override DB path")
    args = parser.parse_args()

    db_path = args.db or DEFAULT_DB
    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        print("Run session_summary.py first to populate the database.", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    cols, sessions = query_sessions(conn, args.last, args.session)
    session_ids = [r[0] for r in sessions]
    kpi_rows = query_kpis(conn, session_ids, args.layer)
    format_output(cols, sessions, kpi_rows, args.layer)
    conn.close()


if __name__ == "__main__":
    main()
