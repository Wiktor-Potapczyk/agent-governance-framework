"""
Session Summary — Three-layer analytics for CC Agent Governance Framework.

Computes 9 KPIs across 3 layers (governance, work patterns, cost) for a given
session. Produces: one-liner → session-log.txt, JSON → work/, SQLite → observability.db.

Usage:
    python session_summary.py <session_id>
    python session_summary.py --latest
    python session_summary.py --all

Iteration 2, per work/2026-04-12-iteration2-plan.md v2.
"""

import argparse
import glob
import json
import os
import sys
from collections import Counter
from datetime import datetime

# Add scripts/ to path for shared imports
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

from observability_db import get_connection, upsert_session, upsert_kpi, upsert_tool_calls, upsert_agent_dispatches

# --- Configuration ---

# Session JSONL directory — set CC_SESSIONS_DIR env var, or auto-detect from
# ~/.claude/projects/ (picks the directory with most .jsonl files)
def _detect_sessions_dir():
    env = os.environ.get("CC_SESSIONS_DIR")
    if env:
        return os.path.normpath(env)
    projects_dir = os.path.normpath(os.path.expanduser("~/.claude/projects"))
    if not os.path.isdir(projects_dir):
        return projects_dir
    candidates = [d for d in os.listdir(projects_dir)
                  if os.path.isdir(os.path.join(projects_dir, d)) and not d.startswith(".")]
    if not candidates:
        return projects_dir
    # Pick the one with the most .jsonl files
    best = max(candidates, key=lambda d: len(glob.glob(os.path.join(projects_dir, d, "*.jsonl"))))
    return os.path.join(projects_dir, best)

SESSIONS_DIR = _detect_sessions_dir()

# Vault root (3 levels up from scripts/: scripts → Agent-Governance-Research → Projects → Vault)
VAULT_ROOT = os.path.normpath(os.path.join(SCRIPTS_DIR, "..", "..", ".."))

# Governance log path
GOVERNANCE_LOG = os.path.join(VAULT_ROOT, ".claude", "hooks", "governance-log.jsonl")

# Output paths
SESSION_LOG = os.path.join(SCRIPTS_DIR, "..", "session-log.txt")
WORK_DIR = os.path.join(SCRIPTS_DIR, "..", "work")

# Per-million-token pricing (USD) — update when models change
PRICING = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_create": 3.75},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00, "cache_read": 1.50, "cache_create": 18.75},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00, "cache_read": 0.08, "cache_create": 1.00},
    # Older model names (in case transcripts reference them)
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_create": 3.75},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_create": 3.75},
}

# GHS weights
GHS_WEIGHTS = {"dar": 0.30, "hsr": 0.25, "dzur": 0.20, "hor": 0.15, "sc_eff": 0.10}
GHS_RALPH_WEIGHTS = {"dzur": 0.44, "hor": 0.33, "sc_eff": 0.23}  # renormalized without DAR/HSR (sums to 1.0)
BUDGET_CAP = 5.00  # provisional — calibrate in Iteration 3

# GHS tiers
def ghs_tier(score):
    if score > 70: return "Healthy"
    if score > 40: return "Needs Attention"
    return "Critical"


# --- Path Resolution (sub-task B) ---

def resolve_session_path(session_id):
    """Find the main JSONL file for a session."""
    path = os.path.join(SESSIONS_DIR, f"{session_id}.jsonl")
    if os.path.exists(path):
        return path
    # Try partial match
    matches = glob.glob(os.path.join(SESSIONS_DIR, f"{session_id}*.jsonl"))
    if matches:
        return matches[0]
    return None


def find_subagent_paths(session_id):
    """Find all subagent JSONL files for a session."""
    subdir = os.path.join(SESSIONS_DIR, session_id, "subagents")
    if not os.path.isdir(subdir):
        return []
    return glob.glob(os.path.join(subdir, "agent-*.jsonl"))


def find_latest_session():
    """Find the most recently modified session JSONL."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    files = glob.glob(pattern)
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    return os.path.splitext(os.path.basename(newest))[0]


def list_all_sessions():
    """List all session IDs with JSONL files."""
    pattern = os.path.join(SESSIONS_DIR, "*.jsonl")
    return [os.path.splitext(os.path.basename(f))[0] for f in glob.glob(pattern)]


# --- JSONL Parsing Helpers ---

def parse_jsonl(path):
    """Parse a JSONL file, yielding entries. Skips malformed lines."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


# --- Layer 1: Governance Parser (sub-task C) ---

def parse_governance(session_id):
    """Parse governance-log.jsonl for a session. Returns governance KPIs."""
    entries = [e for e in parse_jsonl(GOVERNANCE_LOG) if e.get("session", "").startswith(session_id)]

    if not entries:
        return {
            "dar": None, "hsr": None, "dzur": None,
            "total_entries": 0, "blocks_by_hook": {},
            "event_counts": {}, "schema_version": None,
        }

    # Event counts
    event_counts = Counter(e.get("event", "unknown") for e in entries)

    # DAR: pass / (pass + block) from dispatch-compliance entries only
    dc_entries = [e for e in entries if e.get("hook") == "dispatch-compliance"]
    dc_pass = sum(1 for e in dc_entries if e.get("event") == "pass")
    dc_block = sum(1 for e in dc_entries if e.get("event") == "block")
    dc_total = dc_pass + dc_block
    dar = (dc_pass / dc_total * 100) if dc_total > 0 else None

    # HSR: compliance events only (block, deny, pass, warn) — W1 fix
    compliance_events = [e for e in entries if e.get("event") in ("block", "deny", "pass", "warn")]
    enforcement_count = sum(1 for e in compliance_events if e.get("event") in ("block", "deny"))
    hsr = (enforcement_count / len(compliance_events)) if compliance_events else None

    # DZUR: dark-zone entries only — W2 fix
    dz_entries = [e for e in entries if e.get("event") == "dark-zone"]
    if dz_entries:
        non_high = sum(1 for e in dz_entries if e.get("severity", "low") != "high")
        dzur = (non_high / len(dz_entries) * 100)
    else:
        dzur = None

    # Blocks by hook
    blocks_by_hook = Counter(
        e.get("hook", "unknown") for e in entries if e.get("event") in ("block", "deny")
    )

    # Schema check
    has_v2 = any(e.get("schema") == 2 for e in entries)

    return {
        "dar": dar,
        "hsr": hsr,
        "dzur": dzur,
        "total_entries": len(entries),
        "blocks_by_hook": dict(blocks_by_hook),
        "event_counts": dict(event_counts),
        "schema_version": 2 if has_v2 else 1,
    }


# --- Layer 2: Work Patterns Parser (sub-task E) ---

def parse_work_patterns(session_id):
    """Parse CC session JSONL for work pattern KPIs. Main session only for WP-2."""
    main_path = resolve_session_path(session_id)
    subagent_paths = find_subagent_paths(session_id)

    tool_counts = Counter()  # WP-1
    mcp_count = 0  # WP-3
    total_tools = 0
    write_edit_count = 0  # WP-4
    human_turns = 0  # WP-2
    subagent_count = len(subagent_paths)  # number of subagent files

    all_paths = ([main_path] if main_path else []) + subagent_paths

    for path in all_paths:
        is_main = (path == main_path)
        for entry in parse_jsonl(path):
            entry_type = entry.get("type", "")

            # WP-2: human turns — main session only
            if is_main and entry_type == "user":
                content = entry.get("message", {}).get("content", "")
                # Filter: keep only real human text messages
                # Drop tool_result blocks and hook injections
                if isinstance(content, str):
                    # Plain string content = real human message
                    human_turns += 1
                elif isinstance(content, list):
                    # Check if content has only text blocks (not tool_result)
                    has_text = any(b.get("type") == "text" for b in content if isinstance(b, dict))
                    has_tool_result = any(b.get("type") == "tool_result" for b in content if isinstance(b, dict))
                    if has_text and not has_tool_result:
                        human_turns += 1

            # Tool calls from assistant messages
            if entry_type == "assistant":
                message = entry.get("message", {})
                for block in message.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "unknown")
                        tool_counts[name] += 1
                        total_tools += 1
                        if name.startswith("mcp__"):
                            mcp_count += 1
                        if name in ("Write", "Edit"):
                            write_edit_count += 1

    mcp_ratio = (mcp_count / total_tools * 100) if total_tools > 0 else 0

    return {
        "wp1_tool_profile": dict(tool_counts.most_common(10)),  # top 10
        "wp1_total_tools": total_tools,
        "wp2_human_turns": human_turns,
        "wp3_mcp_ratio": mcp_ratio,
        "wp3_mcp_count": mcp_count,
        "wp4_artifacts": write_edit_count,
        "subagent_count": subagent_count,
    }


# --- Layer 3: Cost Parser (sub-task D) ---

def parse_cost(session_id):
    """Parse CC session JSONL for cost KPIs. Primary: JSONL token fields + pricing constants."""
    main_path = resolve_session_path(session_id)
    subagent_paths = find_subagent_paths(session_id)

    all_paths = ([main_path] if main_path else []) + subagent_paths
    total_cost = 0.0
    subagent_cost = 0.0
    model_counts = Counter()
    hook_durations = []  # for HOR
    first_ts = None
    last_ts = None

    for path in all_paths:
        is_subagent = (path != main_path)
        for entry in parse_jsonl(path):
            entry_type = entry.get("type", "")

            # Timestamps for duration
            ts_str = entry.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                    if last_ts is None or ts > last_ts:
                        last_ts = ts
                except (ValueError, TypeError):
                    pass

            # Cost from assistant entries
            if entry_type == "assistant":
                message = entry.get("message", {})
                usage = message.get("usage", {})
                model = message.get("model", "")

                if usage and model:
                    # Find pricing
                    pricing = None
                    for model_key, p in PRICING.items():
                        if model_key in model or model in model_key:
                            pricing = p
                            break
                    if pricing is None:
                        # Default to sonnet pricing for unknown models
                        pricing = PRICING["claude-sonnet-4-6"]

                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    cache_read = usage.get("cache_read_input_tokens", 0)
                    cache_create = usage.get("cache_creation_input_tokens", 0)

                    entry_cost = (
                        (input_tokens / 1_000_000) * pricing["input"]
                        + (output_tokens / 1_000_000) * pricing["output"]
                        + (cache_read / 1_000_000) * pricing["cache_read"]
                        + (cache_create / 1_000_000) * pricing["cache_create"]
                    )

                    total_cost += entry_cost
                    if is_subagent:
                        subagent_cost += entry_cost

                    # Track model usage (W6 fix: extract readable model name)
                    model_short = model
                    for key in ("opus", "sonnet", "haiku"):
                        if key in model.lower():
                            model_short = key
                            break
                    model_counts[model_short] += 1

            # HOR: hook durations from system entries
            if entry_type == "system":
                hook_infos = entry.get("hookInfos", [])
                if hook_infos:
                    for hi in hook_infos:
                        dur = hi.get("durationMs", 0)
                        if dur > 0:
                            hook_durations.append(dur)

    # Duration
    duration_min = None
    if first_ts and last_ts:
        duration_min = (last_ts - first_ts).total_seconds() / 60.0

    # HOR: median hook duration / median turn time (simplified: just report median hook ms)
    hor_median_ms = None
    if hook_durations:
        sorted_durs = sorted(hook_durations)
        mid = len(sorted_durs) // 2
        hor_median_ms = sorted_durs[mid]

    # Subagent ratio
    sub_ratio = (subagent_cost / total_cost * 100) if total_cost > 0 else 0

    # Model mix string
    model_mix = ", ".join(f"{m}:{c}" for m, c in model_counts.most_common(3))

    return {
        "sc_total": round(total_cost, 2),
        "sc_subagent": round(subagent_cost, 2),
        "sc_sub_ratio": round(sub_ratio, 1),
        "hor_median_ms": hor_median_ms,
        "duration_min": round(duration_min, 1) if duration_min else None,
        "model_mix": model_mix,
    }


# --- Ralph Loop Detection (sub-task G) ---

def detect_ralph_loop(session_id):
    """Detect if session is a Ralph Loop.
    Threshold-based: architect-loop must be >50% of all Skill invocations,
    not just present once (C1 fix — prevents false positives on long sessions)."""
    main_path = resolve_session_path(session_id)
    if not main_path:
        return False

    architect_loop_count = 0
    total_skill_count = 0

    for entry in parse_jsonl(main_path):
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message", {})
        for block in message.get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                if block.get("name") == "Skill":
                    total_skill_count += 1
                    inp = block.get("input", {})
                    if isinstance(inp, dict) and inp.get("skill") == "architect-loop":
                        architect_loop_count += 1

    if total_skill_count == 0:
        return False
    # Ralph Loop if architect-loop is >50% of all skill invocations
    return (architect_loop_count / total_skill_count) > 0.5


# --- GHS Computation (sub-task F) ---

def compute_ghs(governance, cost, is_ralph_loop):
    """Compute Governance Health Score (0-100)."""
    dar = governance.get("dar")  # 0-100 or None
    hsr = governance.get("hsr")  # 0-1 or None
    dzur = governance.get("dzur")  # 0-100 or None
    hor_ms = cost.get("hor_median_ms")  # ms or None
    sc_total = cost.get("sc_total", 0)  # USD

    # Normalize components to 0-100 scale
    dar_norm = dar if dar is not None else 50  # default to neutral
    hsr_norm = min(hsr, 1.0) * 100 if hsr is not None else 50
    dzur_norm = dzur if dzur is not None else 50
    # HOR: lower is better, normalize 0-5000ms to 0-100 (5s = worst)
    # W2 fix: None → neutral (50), not max credit (0)
    hor_norm = min(hor_ms / 5000, 1.0) * 100 if hor_ms is not None else 50
    # SC efficiency: 1 - (cost/cap), capped at 0
    sc_eff = max(0, (1 - sc_total / BUDGET_CAP)) * 100

    if is_ralph_loop:
        # 3-component formula (W3: fallback dropped, use renormalized weights)
        w = GHS_RALPH_WEIGHTS
        score = (dzur_norm * w["dzur"] / 100
                 + (100 - hor_norm) * w["hor"] / 100
                 + sc_eff * w["sc_eff"] / 100) * 100
    else:
        w = GHS_WEIGHTS
        score = (dar_norm * w["dar"] / 100
                 + (100 - hsr_norm) * w["hsr"] / 100
                 + dzur_norm * w["dzur"] / 100
                 + (100 - hor_norm) * w["hor"] / 100
                 + sc_eff * w["sc_eff"] / 100) * 100

    return round(min(100, max(0, score)), 1)


# --- Output Formatters (sub-task H) ---

def format_oneliner(session_id, governance, work, cost, ghs, is_ralph):
    """Format one-liner for session-log.txt."""
    date = datetime.now().strftime("%Y-%m-%d")

    # Governance part
    if is_ralph:
        gov_str = "[RALPH_LOOP]"
    else:
        dar_str = f"{governance['dar']:.0f}%" if governance.get("dar") is not None else "N/A"
        hsr_str = f"{governance['hsr']:.2f}" if governance.get("hsr") is not None else "N/A"
        dzur_str = f"{governance['dzur']:.0f}%" if governance.get("dzur") is not None else "N/A"
        gov_str = f"DAR:{dar_str} HSR:{hsr_str} DZUR:{dzur_str}"

    # Top 3 tools
    top_tools = list(work.get("wp1_tool_profile", {}).keys())[:3]
    tools_str = ",".join(top_tools) if top_tools else "none"

    return (
        f"{date} | {session_id[:8]} | GHS:{ghs} ({ghs_tier(ghs)}) | "
        f"{gov_str} | SC:${cost['sc_total']} HOR:{cost.get('hor_median_ms', 'N/A')}ms | "
        f"WP: {tools_str} MCP:{work['wp3_mcp_ratio']:.0f}%"
    )


def build_json_summary(session_id, governance, work, cost, ghs, is_ralph):
    """Build full JSON summary dict."""
    return {
        "session_id": session_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "is_ralph_loop": is_ralph,
        "ghs_score": ghs,
        "ghs_tier": ghs_tier(ghs),
        "governance": governance,
        "work_patterns": work,
        "cost": cost,
    }


def save_to_db(conn, session_id, governance, work, cost, ghs, is_ralph):
    """Write all data to observability.db."""
    upsert_session(conn, {
        "session_id": session_id,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "duration_min": cost.get("duration_min"),
        "cost_total": cost.get("sc_total"),
        "cost_subagent": cost.get("sc_subagent"),
        "model_mix": cost.get("model_mix"),
        "is_ralph_loop": 1 if is_ralph else 0,
        "ghs_score": ghs,
    })

    # KPI values
    kpi_map = {
        "DAR": ("governance", governance.get("dar")),
        "HSR": ("governance", governance.get("hsr")),
        "DZUR": ("governance", governance.get("dzur")),
        "SC": ("cost", cost.get("sc_total")),
        "SC_SubRatio": ("cost", cost.get("sc_sub_ratio")),
        "HOR": ("cost", cost.get("hor_median_ms")),
        "WP1_TotalTools": ("work_patterns", work.get("wp1_total_tools")),
        "WP2_HumanTurns": ("work_patterns", work.get("wp2_human_turns")),
        "WP3_MCPRatio": ("work_patterns", work.get("wp3_mcp_ratio")),
        "WP4_Artifacts": ("work_patterns", work.get("wp4_artifacts")),
    }
    for kpi_name, (layer, value) in kpi_map.items():
        status = None
        if kpi_name == "DAR" and value is not None:
            status = "OK" if value >= 85 else ("WARN" if value >= 70 else "ALERT")
        elif kpi_name == "HSR" and value is not None:
            status = "OK" if value <= 0.10 else ("WARN" if value <= 0.25 else "ALERT")
        upsert_kpi(conn, session_id, kpi_name, layer, value, status)

    # Tool calls
    upsert_tool_calls(conn, session_id, work.get("wp1_tool_profile", {}))

    conn.commit()


def append_oneliner(oneliner, session_id):
    """Append one-liner to session-log.txt with dedup. Atomic write via tmp+replace (C2 fix)."""
    log_path = os.path.normpath(SESSION_LOG)
    tmp_path = log_path + ".tmp"
    prefix = session_id[:8]

    # Read existing lines, remove any with same session prefix
    existing_lines = []
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            existing_lines = [l for l in f.readlines() if prefix not in l]

    # Write to temp file, then atomic replace
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)
        f.write(oneliner + "\n")
    os.replace(tmp_path, log_path)


# --- Main ---

def summarize_session(session_id, db_path=None):
    """Run full three-layer analysis for a session. Returns summary dict."""
    # Verify session exists
    main_path = resolve_session_path(session_id)
    if not main_path:
        print(f"ERROR: No JSONL found for session {session_id}", file=sys.stderr)
        return None

    print(f"Analyzing session {session_id[:12]}...")

    # Layer 1: Governance
    governance = parse_governance(session_id)
    print(f"  L1 Governance: {governance['total_entries']} entries, DAR={governance['dar']}")

    # Layer 2: Work Patterns
    work = parse_work_patterns(session_id)
    print(f"  L2 Work: {work['wp1_total_tools']} tools, {work['wp2_human_turns']} human turns, {work['wp3_mcp_ratio']:.0f}% MCP")

    # Layer 3: Cost
    cost = parse_cost(session_id)
    print(f"  L3 Cost: ${cost['sc_total']}, {cost.get('duration_min', 'N/A')} min")

    # Ralph Loop detection
    is_ralph = detect_ralph_loop(session_id)
    if is_ralph:
        print(f"  [RALPH_LOOP detected]")

    # GHS
    ghs = compute_ghs(governance, cost, is_ralph)
    print(f"  GHS: {ghs} ({ghs_tier(ghs)})")

    # Outputs
    oneliner = format_oneliner(session_id, governance, work, cost, ghs, is_ralph)
    print(f"\n  {oneliner}\n")

    # Save JSON summary
    summary = build_json_summary(session_id, governance, work, cost, ghs, is_ralph)
    json_path = os.path.join(WORK_DIR, f"{datetime.now().strftime('%Y-%m-%d')}-session-{session_id[:8]}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  JSON saved: {json_path}")

    # Save to DB
    conn = get_connection(db_path)
    save_to_db(conn, session_id, governance, work, cost, ghs, is_ralph)
    conn.close()
    print(f"  DB updated: observability.db")

    # Append one-liner
    append_oneliner(oneliner, session_id)
    print(f"  One-liner appended: session-log.txt")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Session summary — three-layer governance analytics")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("session_id", nargs="?", help="Session UUID (full or partial)")
    group.add_argument("--latest", action="store_true", help="Analyze the most recent session")
    group.add_argument("--all", action="store_true", help="Analyze all sessions")
    parser.add_argument("--db", help="Override observability.db path")
    args = parser.parse_args()

    if args.latest:
        sid = find_latest_session()
        if not sid:
            print("ERROR: No sessions found", file=sys.stderr)
            sys.exit(1)
        summarize_session(sid, args.db)
    elif args.all:
        sessions = list_all_sessions()
        print(f"Found {len(sessions)} sessions")
        for sid in sessions:
            summarize_session(sid, args.db)
    else:
        # Support partial session ID
        if len(args.session_id) < 36:
            all_sessions = list_all_sessions()
            matches = [s for s in all_sessions if s.startswith(args.session_id)]
            if len(matches) == 1:
                summarize_session(matches[0], args.db)
            elif len(matches) > 1:
                print(f"ERROR: Ambiguous session ID prefix '{args.session_id}', matches: {matches[:5]}", file=sys.stderr)
                sys.exit(1)
            else:
                print(f"ERROR: No session found matching '{args.session_id}'", file=sys.stderr)
                sys.exit(1)
        else:
            summarize_session(args.session_id, args.db)


if __name__ == "__main__":
    main()
