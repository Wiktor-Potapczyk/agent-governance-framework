#!/usr/bin/env python3
"""hook-activity.jsonl reader: GOV-2 (Phase D dim3).

The E1 silent-zero instrument (_governance_logger.log_fire) writes hook firings to
.claude/hooks/hook-activity.jsonl. Nothing read it until now: the data was
write-only. This reader aggregates it and: the actual audit payoff :
cross-references the registered hook set to surface which enforcement hooks are
STILL unmeasured (registered + firing in production but never self-logging).

Outputs:
  - per-hook fire counts + decision (block/allow/warn) breakdown
  - first/last timestamp per hook (liveness recency)
  - REGISTERED-BUT-UNMEASURED list: hooks in settings*.json with zero fire records
    (these are the remaining GOV-1 rollout candidates)

Usage:
    python .claude/scripts/hook_activity_report.py          # human report
    python .claude/scripts/hook_activity_report.py --json    # machine-readable

Designed to be called at CMDB refresh time (GOV-2). Importable: report_dict().
Never raises on missing/corrupt log: returns empty aggregates.
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_DIR", r"C:\Users\exampleuser\Workspace"))
LOG = VAULT / ".claude" / "hooks" / "hook-activity.jsonl"
SETTINGS_FILES = [
    VAULT / ".claude" / "settings.json",
    VAULT / ".claude" / "settings.local.json",
]
# synthetic / fixture hook names to exclude from real aggregates
_NOISE = {"SELF-TEST-hook", "x", "None", None, ""}
_PY_IN_CLAUDE = re.compile(r"\.claude[\\/](?:hooks|scripts)[\\/]([\w\-.]+)\.py", re.IGNORECASE)
# Signatures proving a hook records SOME log (used to avoid over-reporting silence:
# a hook that writes deny/event records to governance-log.jsonl is not truly silent,
# it just lacks a liveness record in hook-activity.jsonl).
_LOG_SIG = ("governance-log.jsonl", "emit_event", "_event_emit",
            "log_fire", "_governance_logger", ".log")


def _writes_any_log(hook_name: str) -> bool:
    for sub in ("hooks", "scripts"):
        p = VAULT / ".claude" / sub / (hook_name + ".py")
        if p.exists():
            t = p.read_text(encoding="utf-8", errors="replace")
            return any(s in t for s in _LOG_SIG)
    return False


def _registered_hook_names() -> set:
    names = set()
    for sf in SETTINGS_FILES:
        if not sf.exists():
            continue
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entries in data.get("hooks", {}).values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                for h in entry.get("hooks", []):
                    for m in _PY_IN_CLAUDE.findall(h.get("command", "")):
                        names.add(m)
    return names


def report_dict() -> dict:
    counts = Counter()
    decisions = defaultdict(Counter)
    first_seen, last_seen = {}, {}
    total = 0
    if LOG.exists():
        for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except Exception:
                continue
            hook = rec.get("hook")
            if hook in _NOISE:
                continue
            total += 1
            counts[hook] += 1
            decisions[hook][rec.get("decision") or "none"] += 1
            ts = rec.get("ts", "")
            if hook not in first_seen:
                first_seen[hook] = ts
            last_seen[hook] = ts

    registered = _registered_hook_names()
    measured = set(counts)
    no_liveness = sorted(registered - measured)
    # Split: truly silent (no log of any kind) vs logs-elsewhere (domain events in
    # governance-log.jsonl / own .log, but no liveness record in hook-activity.jsonl).
    truly_silent = [h for h in no_liveness if not _writes_any_log(h)]
    logs_elsewhere = [h for h in no_liveness if _writes_any_log(h)]
    return {
        "total_fires": total,
        "distinct_hooks": len(counts),
        "per_hook": {
            h: {
                "fires": counts[h],
                "decisions": dict(decisions[h]),
                "first": first_seen.get(h),
                "last": last_seen.get(h),
            }
            for h in sorted(counts, key=lambda k: -counts[k])
        },
        "registered_count": len(registered),
        "truly_silent": truly_silent,
        "logs_elsewhere_no_liveness": logs_elsewhere,
    }



# ---------------------------------------------------------------------------
# Observability-contract matrix generation (contract C6, 2026-08-01)
# The matrix must be GENERATED, not hand-maintained, or it rots like every other
# hand-kept count in this vault. Classes:
#   A = writes governance-log events itself (direct or via _event_emit)
#   B = logs fires through the shared _governance_logger helper
#   C = owns a dedicated aggregate/state sink (.log / aggregates jsonl / _state json)
#   D = dark: no sink of any kind found in source
# ---------------------------------------------------------------------------

_A_SIG = ("governance-log.jsonl", "emit_event", "_event_emit")
_B_SIG = ("log_fire", "_governance_logger")
_C_RE = re.compile(
    r"[\w\-]+\.log\b"
    r"|aggregates[\\/][\w\-]+\.jsonl"
    r"|_state[\\/][\w\-]+\.json"
    r"|[\w\-]+\.jsonl"
)
_C_IGNORE = {"governance-log.jsonl", "hook-activity.jsonl"}


def _hook_source(hook_name):
    for sub in ("hooks", "scripts"):
        p = VAULT / ".claude" / sub / (hook_name + ".py")
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
    return None


def _hook_events():
    """hook name -> sorted list of registered event names."""
    out = {}
    for sf in SETTINGS_FILES:
        if not sf.exists():
            continue
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for event, entries in data.get("hooks", {}).items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                for h in entry.get("hooks", []):
                    for m in _PY_IN_CLAUDE.findall(h.get("command", "")):
                        out.setdefault(m, set()).add(event)
    return dict((k, sorted(v)) for k, v in out.items())


def matrix_rows():
    events = _hook_events()
    rows = []
    for name in sorted(events):
        src = _hook_source(name)
        if src is None:
            rows.append({"hook": name, "events": events[name], "classes": ["D"],
                         "sinks": [], "source": "MISSING"})
            continue
        classes = []
        sinks = []
        if any(s in src for s in _A_SIG):
            classes.append("A")
            sinks.append("governance-log")
        if any(s in src for s in _B_SIG):
            classes.append("B")
            sinks.append("hook-activity")
        own = sorted(set(_C_RE.findall(src)) - _C_IGNORE)
        if own:
            classes.append("C")
            sinks.extend(own)
        if not classes:
            classes.append("D")
        rows.append({"hook": name, "events": events[name], "classes": classes,
                     "sinks": sinks, "source": "ok"})
    return rows


def dark_hooks():
    return sorted(r["hook"] for r in matrix_rows() if r["classes"] == ["D"])


def _hooks_matrix_markdown():
    rows = matrix_rows()
    lines = ["| Hook | Event(s) | Class | Sink(s) |", "|---|---|---|---|"]
    for r in rows:
        cls = "+".join(r["classes"])
        if cls == "D":
            cls = "**D**"
        lines.append("| %s | %s | %s | %s |" % (
            r["hook"], ",".join(r["events"]), cls, ", ".join(r["sinks"]) or "none"))
    dark = dark_hooks()
    lines.append("")
    lines.append("Generated: %d registered hooks, %d dark (%.0f%%)." % (
        len(rows), len(dark), 100.0 * len(dark) / max(len(rows), 1)))
    lines.append("Dark set: " + ", ".join(dark))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skills and agents matrix sections (Hermes P3 step 8, 2026-08-18)
#
# Coverage semantics differ from hooks and the output says so: skills and
# agents write no telemetry themselves; their footprint is records ABOUT
# them. A row is covered when at least one REAL-session record names it,
# otherwise it joins the dark-surface list, which is printed in full and
# never summarized: the honest listing is the deliverable, not a cleanup
# mandate, and it is wired to no gate.
#
# Enumeration sources, both named in the output because both are known drift
# risks: .claude/registry.json (a generated snapshot that goes stale between
# regenerations) cross-checked against the on-disk .claude/skills/ and
# .claude/agents/ trees. On-disk names missing from the registry are
# REGISTRY_DISK_DRIFT warn lines in the printed output. Registry names with
# no local file are NOT drift: plugin-sourced assets legitimately live in
# the plugin cache (Pass K doctrine).
# ---------------------------------------------------------------------------

REGISTRY_PATH = VAULT / ".claude" / "registry.json"


def _asset_inventory():
    reg_agents, reg_skills, generated_at = {}, {}, None
    try:
        reg = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        generated_at = reg.get("generated_at") or reg.get("generated")
        reg_agents = {_norm_hook_name(k): k for k in reg.get("agents", {})}
        reg_skills = {_norm_hook_name(k): k for k in reg.get("skills", {})}
    except Exception:
        pass
    disk_agents, disk_skills = {}, {}
    d = VAULT / ".claude" / "agents"
    if d.is_dir():
        for p in sorted(d.glob("*.md")):
            disk_agents[_norm_hook_name(p.stem)] = p.stem
    d = VAULT / ".claude" / "skills"
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if p.is_dir():
                disk_skills[_norm_hook_name(p.name)] = p.name
    return {"reg_agents": reg_agents, "reg_skills": reg_skills,
            "disk_agents": disk_agents, "disk_skills": disk_skills,
            "generated_at": generated_at}


def _asset_evidence():
    """One streaming pass over governance-log.jsonl, real sessions only.
    Returns (skill_counter, agent_counter) keyed by normalized name. A
    recorded name with a plugin prefix (plugin:skill) also credits its
    suffix, matching how registry keys are stored."""
    skills, agents = Counter(), Counter()

    def credit(counter, name):
        n = _norm_hook_name(str(name))
        if not n:
            return
        counter[n] += 1
        if ":" in n:
            counter[n.split(":", 1)[1]] += 1

    for rec in _stream_jsonl(_sink_paths()[SINK_GOV]):
        if rec.get("hook") in _NOISE:
            continue
        if str(rec.get("session")) in _SYN_SESSIONS:
            continue
        ev = rec.get("event")
        hook = rec.get("hook")
        if ev == "agent_dispatched":
            if rec.get("agent_type"):
                credit(agents, rec["agent_type"])
            for s in rec.get("skill_context") or []:
                credit(skills, s)
        elif hook == "subagent-quality-check" and rec.get("agent_type"):
            credit(agents, rec["agent_type"])
        elif ev == "turn_summary":
            for a in rec.get("agents") or []:
                credit(agents, a)
            for s in rec.get("skills") or []:
                credit(skills, s)
        elif hook == "skill-routing-check" and rec.get("attempted"):
            credit(skills, rec["attempted"])
    return skills, agents


def _asset_section(title, reg, disk, evidence, evidence_note):
    names = {}
    for n, orig in reg.items():
        names.setdefault(n, orig)
    for n, orig in disk.items():
        names.setdefault(n, orig)
    lines = ["", "## %s" % title,
             "Coverage semantics: %s A row is covered when at least one "
             "real-session record names it; otherwise it is DARK." % evidence_note,
             "| %s | Registry | Disk | Coverage |" % title[:-1],
             "|---|---|---|---|"]
    dark = []
    for n in sorted(names):
        cov = evidence.get(n, 0)
        if cov:
            covs = "covered (%d record(s))" % cov
        else:
            covs = "DARK"
            dark.append(names[n])
        lines.append("| %s | %s | %s | %s |" % (
            names[n], "yes" if n in reg else "no",
            "yes" if n in disk else "no", covs))
    drift = sorted(disk[n] for n in disk if n not in reg)
    for name in drift:
        lines.append("REGISTRY_DISK_DRIFT (warn): %r is on disk but not in "
                     "registry.json; regenerate the registry." % name)
    lines.append("")
    lines.append("Generated: %d %s (registry %d, disk %d), %d dark (%.0f%%)."
                 % (len(names), title.lower(), len(reg), len(disk), len(dark),
                    100.0 * len(dark) / max(len(names), 1)))
    lines.append("Dark surface (in full, measurement only, wired to no gate): "
                 + (", ".join(sorted(dark)) or "none"))
    return lines


def matrix_markdown():
    """Three sections: hooks (unchanged), skills, agents."""
    inv = _asset_inventory()
    skills_ev, agents_ev = _asset_evidence()
    out = ["## Hooks", _hooks_matrix_markdown()]
    out += _asset_section(
        "Skills", inv["reg_skills"], inv["disk_skills"], skills_ev,
        "skills write no telemetry; evidence is records about them "
        "(turn_summary `skills`, agent_dispatched `skill_context`, "
        "skill-routing-check `attempted`).")
    out += _asset_section(
        "Agents", inv["reg_agents"], inv["disk_agents"], agents_ev,
        "agents write no telemetry; evidence is records about them "
        "(agent_dispatched / subagent-quality-check `agent_type`, "
        "turn_summary `agents`).")
    out.append("")
    out.append("Enumeration sources: .claude/registry.json (generated_at %s; "
               "a snapshot that goes stale between regenerations, measured "
               "stale in the 2026-08-06 harness-utilization analysis) "
               "cross-checked against the on-disk .claude/skills/ and "
               ".claude/agents/ trees. Registry names with no local file are "
               "plugin-sourced, not drift." % inv["generated_at"])
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Matrix-as-gate findings (contract C5, 2026-08-01)
# C5 as written ("a registered asset without a matrix row is a finding") is
# close to vacuous now that the matrix is generated FROM the settings files:
# a registered hook always gets a row. These are the checks generation cannot
# paper over.
#
# HOOK_NAME_DRIFT is inherited from the C7 audit, which found that converging
# writers onto _event_emit does NOT fix naming drift: the helper takes `hook`
# as an unchecked caller string. A convention with no check drifts.
# ---------------------------------------------------------------------------

# Hooks whose emitted name already differs from their filename. Listed rather
# than accommodated: new drift still fails, and these two stay visible. Fixing
# them is a log-continuity decision (consumers filter on the old name and the
# historical records keep it), not a rename to make a check pass.
HOOK_NAME_GRANDFATHERED = {
    "dispatch-compliance-check": {"dispatch-compliance"},
    "verifier-gate-check": {"verifier-gate"},
}

_EMIT_HOOK_KW = re.compile(r'emit_event\(\s*[^)]*?hook\s*=\s*["\']([^"\']+)["\']', re.S)
_DICT_HOOK = re.compile(r'"hook"\s*:\s*["\']([^"\']+)["\']')
# Negative lookbehind so a local wrapper named _log_fire is not read as the
# shared log_fire, which would mistake its decision argument for a hook name.
_LOG_FIRE_NAME = re.compile(r'(?<![\w])log_fire\(\s*["\']([^"\']+)["\']')
_MODULE_DOCSTRING = re.compile(r'^\s*("""|\'\'\')(.*?)\1', re.S)


def _strip_module_docstring(src: str) -> str:
    """Drop the leading docstring so adoption examples in it are not scanned."""
    return _MODULE_DOCSTRING.sub("", src, count=1)


def _emitted_hook_names(src: str) -> set:
    body = _strip_module_docstring(src)
    return (set(_EMIT_HOOK_KW.findall(body))
            | set(_DICT_HOOK.findall(body))
            | set(_LOG_FIRE_NAME.findall(body)))


def _norm_hook_name(name: str) -> str:
    return name.replace("_", "-").lower()


def matrix_findings():
    """Return C5 findings over the generated matrix. Each is a dict with
    kind, hook and detail."""
    findings = []
    for row in matrix_rows():
        name = row["hook"]
        if row["source"] == "MISSING":
            findings.append({
                "kind": "MISSING_SOURCE", "hook": name,
                "detail": "registered in settings but no .py on disk",
            })
            continue
        if row["classes"] == ["D"]:
            findings.append({
                "kind": "DARK_HOOK", "hook": name,
                "detail": "no governance-log, hook-activity or own sink found in source",
            })
        src = _hook_source(name) or ""
        allowed = {_norm_hook_name(name)}
        allowed |= {_norm_hook_name(x) for x in HOOK_NAME_GRANDFATHERED.get(name, ())}
        for emitted in sorted(_emitted_hook_names(src)):
            if _norm_hook_name(emitted) not in allowed:
                findings.append({
                    "kind": "HOOK_NAME_DRIFT", "hook": name,
                    "detail": "emits hook=%r, which is not its filename" % emitted,
                })
    return findings


def findings_text() -> str:
    f = matrix_findings()
    if not f:
        return "MATRIX: 0 findings across %d registered hooks." % len(matrix_rows())
    lines = ["MATRIX: %d finding(s):" % len(f)]
    for item in f:
        lines.append("  %-16s %-34s %s" % (item["kind"], item["hook"], item["detail"]))
    return "\n".join(lines)


def main(as_json: bool = False) -> int:
    r = report_dict()
    if as_json:
        print(json.dumps(r, indent=2))
        return 0
    print("=== HOOK ACTIVITY REPORT (GOV-2) ===")
    print(f"  total fires: {r['total_fires']}  |  distinct hooks logging: {r['distinct_hooks']}"
          f"  |  registered hooks: {r['registered_count']}")
    print("  per-hook (fires | decisions | last-seen):")
    for h, d in r["per_hook"].items():
        dec = ", ".join(f"{k}={v}" for k, v in d["decisions"].items())
        print(f"    {h:34s} {d['fires']:5d}  [{dec}]  last={d['last']}")
    print(f"  TRULY SILENT ({len(r['truly_silent'])}): no log of any kind; "
          f"top GOV-1 liveness-rollout candidates:")
    for h in r["truly_silent"]:
        print(f"    - {h}")
    print(f"  LOGS ELSEWHERE, NO LIVENESS RECORD ({len(r['logs_elsewhere_no_liveness'])}) "
          f": measured on block/event but invisible on pass-through turns:")
    for h in r["logs_elsewhere_no_liveness"]:
        print(f"    > {h}")
    return 0


# --- Gate yield (2026-08-04) -------------------------------------------------
# Answers the deletion-criterion questions off governance-log.jsonl: which gates
# fired in REAL sessions, with what outcomes, in which class.
#
# Real-session filtering is mandatory: test traffic writes into the same file and
# is the majority for several hooks (bash-safety-guard is 137 real against 19,279
# synthetic), so an unfiltered count is not evidence.
#
# Class matters because the same number means opposite things. Fire rate is the
# right yield signal for a process gate and the wrong one for a safety floor: a
# floor exists to catch the irreversible action on the occasion it happens, and
# one that fired constantly would mean something upstream was broken.
GOVLOG = VAULT / ".claude" / "hooks" / "governance-log.jsonl"
_SYN_SESSIONS = {"session", "unknown", "None", ""}
_BLOCKING_EVENTS = {"block", "deny", "breaker_blocked", "transition_gate_block"}
_BLOCKING_RE = re.compile(r"block|deny|violation|missing|fabrication", re.IGNORECASE)
_FLOOR_SIG = ("_irreversible_surface",)


def _is_floor(hook_name: str) -> bool:
    """Derived, not stipulated: a gate is a safety floor when it imports the
    canonical irreversible surface rather than because a list says so.
    Reuses the module's existing _hook_source, which returns None when the file
    is absent; do not shadow it, matrix_rows() depends on that None contract."""
    src = _hook_source(str(hook_name)) or ""
    return any(s in src for s in _FLOOR_SIG)


def _writes_govlog(hook_name: str) -> bool:
    src = _hook_source(str(hook_name)) or ""
    return any(s in src for s in _A_SIG)


def _norm_hook(name: str) -> str:
    """Collapse the known drift between a hook's filename and the `hook` value it
    emits: separator style and a trailing -check/-guard suffix."""
    n = str(name).lower().replace("_", "-")
    for suffix in ("-check", "-guard"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n


def _alias_of(hook_name: str, seen: Counter):
    """Return the emitted name a zero-count registered hook is really logging
    under, or None. Only matches names that actually appear in the log."""
    target = _norm_hook(hook_name)
    for other, count in seen.items():
        if count and other != hook_name and _norm_hook(other) == target:
            return other
    return None


def gate_yield() -> dict:
    real, syn = Counter(), Counter()
    outcomes = defaultdict(Counter)
    if GOVLOG.exists():
        with GOVLOG.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                hook = rec.get("hook")
                if hook in _NOISE:
                    continue
                if str(rec.get("session")) in _SYN_SESSIONS:
                    syn[hook] += 1
                    continue
                real[hook] += 1
                outcomes[hook][rec.get("event") or "none"] += 1

    registered = _registered_hook_names()
    rows = []
    for hook in sorted(set(real) | set(syn) | registered,
                       key=lambda h: (-real[h], str(h))):
        # Blocking events are detected by name pattern as well as by the explicit
        # set, because event vocabularies differ per hook and a hardcoded list
        # silently under-counts. Non-blocking outcomes are derived as the
        # remainder rather than read from a "pass" key: several hooks record
        # their success path under a domain-specific name (classifier-field-check
        # uses classification_emitted), so keying on "pass" invents false zeros.
        blocks = sum(n for e, n in outcomes[hook].items()
                     if e in _BLOCKING_EVENTS or _BLOCKING_RE.search(str(e)))
        non_blocks = real[hook] - blocks
        if _is_floor(hook):
            cls, verdict = "floor", "keep - judged by coverage, not frequency"
        elif real[hook] == 0 and _alias_of(hook, real):
            # The registered filename and the emitted `hook` value have drifted
            # apart (dispatch-compliance-check emits as dispatch-compliance).
            # Reporting zero here would repeat the join-on-filename error that
            # once hid 726 verdicts; report the alias instead.
            cls, verdict = "alias", f"emits as '{_alias_of(hook, real)}' - counted there"
        elif real[hook] == 0 and not _writes_govlog(hook):
            cls, verdict = "unmeasured", "writes no governance-log verdict - cannot be judged"
        elif real[hook] == 0:
            cls, verdict = "process", "DEAD - zero real firings"
        elif blocks == 0:
            cls, verdict = "advisory", "name a consumer or silence"
        elif blocks == real[hook]:
            # Every record is a block, which is the signature of a deny-only
            # guard rather than of a gate with no passing path. Judge by
            # coverage like a floor; a ratio is meaningless here.
            cls, verdict = "deny-only", "keep - judged by coverage, no pass path by design"
        else:
            cls, verdict = "process", "keep"
        rows.append({
            "hook": hook, "class": cls, "real": real[hook], "synthetic": syn[hook],
            "blocks": blocks,
            "non_blocks": non_blocks,
            "block_ratio": round(blocks / non_blocks, 2) if non_blocks else None,
            "verdict": verdict,
            "registered": hook in registered,
        })
    return {"rows": rows,
            "real_total": sum(real.values()),
            "synthetic_total": sum(syn.values())}


def yield_text() -> str:
    r = gate_yield()
    out = ["=== GATE YIELD (real sessions only) ===",
           f"  real records: {r['real_total']}  |  synthetic (test traffic): {r['synthetic_total']}",
           f"  {'hook':34s} {'class':11s} {'real':>7s} {'synth':>7s} {'blk':>6s} {'nonblk':>6s}  verdict"]
    for row in r["rows"]:
        out.append(f"  {str(row['hook']):34s} {row['class']:11s} {row['real']:7d} "
                   f"{row['synthetic']:7d} {row['blocks']:6d} {row['non_blocks']:6d}  {row['verdict']}")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Telemetry vocabulary (Hermes P3, 2026-08-18)
# Each sink gets a DECLARED, GENERATED value set derived from writer source
# (the bounded-vocabulary idea adopted from Hermes mechanism 8). The anti-
# Hermes choice is explicit: nothing is ever coerced, dropped or rewritten;
# an undeclared value is an offline WARN finding (vocab_findings below), and
# the sinks stay append-only JSONL with no schema migration.
#
# Derivation is static regex scan of every production .py under .claude/hooks
# and .claude/scripts (docstring-stripped, sibling patterns of the proven
# _EMIT_HOOK_KW / _DICT_HOOK / _LOG_FIRE_NAME approach), plus a wrapper-aware
# pattern for the dominant live idiom: a local helper whose parameter is
# literally named `event` or `decision`, with string-literal call sites.
# Observed-but-underivable historical values are carried as DATA in
# VOCAB_GRANDFATHERED so the honesty class survives generation.
# ---------------------------------------------------------------------------

AGGREGATES = VAULT / ".claude" / "hooks" / "aggregates"
VOCAB_PATH = AGGREGATES / "telemetry-vocabulary.json"
PL_LOG = AGGREGATES / "plain-language-warnings.jsonl"

SINK_GOV = "governance-log.jsonl"
SINK_ACT = "hook-activity.jsonl"
SINK_PL = "plain-language-warnings.jsonl"

# Reviewed grandfather list (Hermes P3 step 3 reconciliation, 2026-08-18).
# Measured underivable share at review time: governance-log 3 of 33 observed
# event values (9.1%), hook-activity 0 of 29 decision values (0.0%); both
# under the ~25% HARD STOP threshold.
VOCAB_GRANDFATHERED = {
    SINK_GOV: {
        "event": [
            {"value": "override", "hook": "config-protection",
             "reason": "writer config-protection.py removed 2026-08-07 by owner "
                       "decision; 4 real historical records stay legal"},
            {"value": "reviewer_scope_violation_blocked",
             "hook": "reviewer-scope-violation-check",
             "reason": "retired 2026-08-07 (double-emission defect fix); "
                       "synthetic-only records remain"},
            {"value": "sdlc_evidence_verified", "hook": "sdlc-evidence-verifier",
             "reason": "emitted through 'log_event' dict values resolved at "
                       "runtime; statically invisible to the literal patterns"},
        ],
    },
    SINK_ACT: {
        "decision": [],
    },
}

_EVENT_KW_V = re.compile(r'\bevent\s*=\s*["\']([^"\']+)["\']')
_DICT_EVENT_V = re.compile(r'["\']event["\']\s*:\s*["\']([^"\']+)["\']')
_DECISION_KW_V = re.compile(r'\bdecision\s*=\s*["\']([^"\']+)["\']')
_EVENT_COND_V = re.compile(
    r'\bevent\s*=\s*\(?\s*["\']([^"\']+)["\']\s+if\b[^)]*?\belse\s+["\']([^"\']+)["\']')
_DECISION_COND_V = re.compile(
    r'\bdecision\s*=\s*\(?\s*["\']([^"\']+)["\']\s+if\b[^)]*?\belse\s+["\']([^"\']+)["\']')
_LOG_FIRE_POS2_V = re.compile(
    r'(?<![\w])log_fire\(\s*["\'][^"\']+["\']\s*,\s*["\']([^"\']+)["\']')
_DEF_PARAMS_V = re.compile(r'^\s*def\s+(\w+)\s*\(([^)]*)\)', re.M)


def _wrapper_literals(src, param_name):
    """String literals passed at call sites of local helpers whose parameter
    list contains a parameter literally named `param_name` (event/decision),
    at that parameter's positional index. Handles bare literals and the
    `var or "literal"` form (sdlc-evidence-verifier)."""
    out = set()
    for fn_name, params in _DEF_PARAMS_V.findall(src):
        names = [p.strip().split(":")[0].split("=")[0].strip()
                 for p in params.split(",") if p.strip()]
        if param_name not in names:
            continue
        idx = names.index(param_name)
        if idx > 2:
            continue
        prefix = r'(?:[\w.\[\]\'"]+\s*,\s*){%d}' % idx
        pat = re.compile(
            r'(?<![\w.])' + re.escape(fn_name) + r'\(\s*' + prefix +
            r'(?:\w+\s+or\s+)?["\']([^"\']+)["\']')
        out |= set(pat.findall(src))
    return out


def _writer_files():
    """Yield (relpath, docstring-stripped source) for every production .py
    under .claude/hooks and .claude/scripts. Test files and conftest are not
    production writers; a missing dir (fixture vaults) yields nothing."""
    for sub in ("hooks", "scripts"):
        d = VAULT / ".claude" / sub
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.py")):
            if p.name.startswith("test_") or p.name == "conftest.py":
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            yield "%s/%s" % (sub, p.name), _strip_module_docstring(src)


def vocab_sources():
    """Per-writer-file derived literals for the two JSONL event sinks.
    Returns {"gov_events": {file: set}, "act_decisions": {file: set},
    "gov_hooks": {file: set}, "act_hooks": {file: set}}."""
    gov_events, act_decisions = {}, {}
    gov_hooks, act_hooks = {}, {}
    for rel, src in _writer_files():
        # _governance_logger writes hook-activity.jsonl only; its _A_SIG hit
        # is a docstring mention of _event_emit. Its single event literal is
        # the sink-2 event axis, attached by construction in vocab_dict().
        if rel.endswith("_governance_logger.py"):
            continue
        if any(s in src for s in _A_SIG):
            evs = set(_EVENT_KW_V.findall(src)) | set(_DICT_EVENT_V.findall(src))
            evs |= _wrapper_literals(src, "event")
            for a, b in _EVENT_COND_V.findall(src):
                evs |= {a, b}
            if evs:
                gov_events[rel] = evs
            hooks = set(_EMIT_HOOK_KW.findall(src)) | set(_DICT_HOOK.findall(src))
            if hooks:
                gov_hooks[rel] = hooks
        if any(s in src for s in _B_SIG):
            decs = set(_DECISION_KW_V.findall(src)) | set(_LOG_FIRE_POS2_V.findall(src))
            decs |= _wrapper_literals(src, "decision")
            for a, b in _DECISION_COND_V.findall(src):
                decs |= {a, b}
            if decs:
                act_decisions[rel] = decs
            names = set(_LOG_FIRE_NAME.findall(src))
            if names:
                act_hooks[rel] = names
    return {"gov_events": gov_events, "act_decisions": act_decisions,
            "gov_hooks": gov_hooks, "act_hooks": act_hooks}


def _pl_vocab():
    """Plain-language sink axes, derived from its two writer files.
    Required record keys: the dict literal inside plain-language-guard.py's
    _append_record call. Rule keys: RULE_IDS from plain_language_check.py,
    loaded as a module (stdlib-only file). Fixture vaults without those files
    get empty axes."""
    required, rules = [], []
    guard = VAULT / ".claude" / "hooks" / "plain-language-guard.py"
    if guard.exists():
        try:
            src = _strip_module_docstring(
                guard.read_text(encoding="utf-8", errors="replace"))
            m = re.search(r'_append_record\(\s*\{(.*?)\}\s*\)', src, re.S)
            if m:
                required = sorted(set(
                    re.findall(r'["\'](\w[\w-]*)["\']\s*:', m.group(1))))
        except Exception:
            pass
    checker = VAULT / ".claude" / "hooks" / "plain_language_check.py"
    if checker.exists():
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location("_plc_vocab", checker)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            rules = sorted(mod.RULE_IDS)
        except Exception:
            rules = sorted(set(re.findall(
                r'["\'](PL-\d+)["\']',
                checker.read_text(encoding="utf-8", errors="replace"))))
    return required, rules


def _axis_values(per_file, grandfathered):
    """Merge derived per-file literals and grandfather data into a sorted
    declared-values list. A value that both derives and is grandfathered
    keeps its writers and loses the grandfather flag (source wins)."""
    writers = {}
    for rel in sorted(per_file):
        for v in per_file[rel]:
            writers.setdefault(v, []).append(rel)
    values = [{"value": v, "writers": writers[v], "grandfathered": False}
              for v in sorted(writers)]
    for g in grandfathered:
        if g["value"] not in writers:
            values.append({"value": g["value"], "writers": [],
                           "grandfathered": True, "hook": g.get("hook"),
                           "reason": g.get("reason")})
    return sorted(values, key=lambda e: e["value"])


def vocab_dict():
    """The declared telemetry vocabulary for all three sinks. Deterministic on
    an unchanged tree; the generation stamp is isolated in the single
    top-level `generated` field, which write_vocab only refreshes when the
    declared content actually changed."""
    s = vocab_sources()
    required, rules = _pl_vocab()
    gov_hook_names = sorted({h for hs in s["gov_hooks"].values() for h in hs})
    act_hook_names = sorted({h for hs in s["act_hooks"].values() for h in hs})
    sinks = {
        SINK_GOV: {
            "axes": {
                "event": {
                    "values": _axis_values(
                        s["gov_events"], VOCAB_GRANDFATHERED[SINK_GOV]["event"]),
                },
                "hook": {
                    "authority": "C5 HOOK_NAME_DRIFT gate (matrix_findings) "
                                 "stays authoritative for this axis",
                    "values": [{"value": v} for v in gov_hook_names],
                },
            },
            "writer_hooks": {rel: sorted(hs)
                             for rel, hs in sorted(s["gov_hooks"].items())},
        },
        SINK_ACT: {
            "axes": {
                "event": {
                    "note": "closed by construction in _governance_logger."
                            "log_fire; the only record shape this sink has",
                    "values": [{"value": "hook_fire",
                                "writers": ["hooks/_governance_logger.py"],
                                "grandfathered": False}],
                },
                "decision": {
                    "note": "null is legal by construction "
                            "(log_fire signature default)",
                    "values": _axis_values(
                        s["act_decisions"],
                        VOCAB_GRANDFATHERED[SINK_ACT]["decision"]),
                },
                "hook": {
                    "authority": "C5 HOOK_NAME_DRIFT gate (matrix_findings) "
                                 "stays authoritative for this axis",
                    "values": [{"value": v} for v in act_hook_names],
                },
            },
            "writer_hooks": {rel: sorted(hs)
                             for rel, hs in sorted(s["act_hooks"].items())},
        },
        SINK_PL: {
            "axes": {
                "required_keys": {
                    "values": [{"value": v} for v in required],
                },
                "per_rule_finding_counts_keys": {
                    "values": [{"value": v} for v in rules],
                },
            },
        },
    }
    return {
        "generated": {
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "generator": "hook_activity_report.py telemetry-vocab v1 "
                         "(Hermes P3, 2026-08-18)",
            "inputs": [".claude/hooks/*.py", ".claude/scripts/*.py",
                       ".claude/settings.json", ".claude/settings.local.json"],
        },
        "sinks": sinks,
    }


def _vocab_serialize(v):
    return json.dumps(v, indent=1, sort_keys=True) + "\n"


def write_vocab(path=None):
    """Write the vocabulary artifact. Stamp-only-on-content-change: when the
    declared content (everything outside `generated`) is unchanged against the
    existing file, the old stamp is kept, so regeneration on an unchanged tree
    is byte-identical."""
    p = Path(path) if path else VOCAB_PATH
    v = vocab_dict()
    if p.exists():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            if old.get("sinks") == v["sinks"]:
                v["generated"] = old["generated"]
        except Exception:
            pass
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(_vocab_serialize(v))
    return p


# ---------------------------------------------------------------------------
# Undeclared-value WARN check (Hermes P3 step 6, offline and advisory)
#
# Finding kinds:
#   UNDECLARED_VALUE   a real-session record carries a value outside the
#                      declared vocabulary for its sink and axis (for the
#                      plain-language sink this also covers a missing required
#                      key, stated in the detail field)
#   STALE_VOCABULARY   the artifact predates the newest production writer
#                      file's mtime, so regeneration is due (mtime heuristic,
#                      OneDrive-unreliable, advisory like everything here)
#
# Semantics: findings WARN. Nothing blocks, nothing is coerced, no sink is
# ever written by this check. Real-session filtering per _SYN_SESSIONS; hook
# names normalized per _norm_hook_name plus HOOK_NAME_GRANDFATHERED before
# any per-hook reasoning. The `since` cutoff defaults to the artifact's
# generation stamp so the WARN stream measures NEW drift, not archaeology;
# pass "1970-01-01 00:00:00" for the full-history count.
#
# Exit semantics at the CLI: vocabulary findings surface under the existing
# --findings flag ALONGSIDE the C5 kinds, keeping the exit-code contract
# (non-zero when any finding exists). They are deliberately NOT folded into
# findings_text(): hook-write-regression-gate.py imports that function on
# every hook-file write, and streaming the multi-MB sinks there would add
# per-edit latency this build is contractually barred from adding.
#
# Sink paths resolve at call time through the established env overrides
# (GOVERNANCE_LOG_PATH / HOOK_ACTIVITY_LOG_PATH / PLAIN_LANGUAGE_LOG_PATH),
# which is how the seeded demonstration points the check at an isolated
# temp-path copy instead of a live sink.
# ---------------------------------------------------------------------------


def _sink_paths():
    def ov(env, default):
        v = os.environ.get(env, "")
        return Path(v.strip()) if isinstance(v, str) and v.strip() else default
    return {
        SINK_GOV: ov("GOVERNANCE_LOG_PATH", GOVLOG),
        SINK_ACT: ov("HOOK_ACTIVITY_LOG_PATH", LOG),
        SINK_PL: ov("PLAIN_LANGUAGE_LOG_PATH", PL_LOG),
    }


def _stream_jsonl(path):
    if not path.exists():
        return
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict):
                yield rec


def vocab_findings(since=None):
    """Join observed real-session sink values against the declared vocabulary.
    Returns a list of finding dicts {kind, sink, axis, value, count, detail}.
    Uses the written artifact when present (its stamp is the default cutoff);
    falls back to a fresh in-memory generation with full history otherwise."""
    artifact = None
    if VOCAB_PATH.exists():
        try:
            artifact = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
        except Exception:
            artifact = None
    v = artifact if artifact else vocab_dict()
    if since is None:
        since = v["generated"]["at"] if artifact else "1970-01-01 00:00:00"

    axes = v["sinks"]
    gov_events = {e["value"] for e in axes[SINK_GOV]["axes"]["event"]["values"]}
    act_events = {e["value"] for e in axes[SINK_ACT]["axes"]["event"]["values"]}
    act_decisions = {e["value"] for e in axes[SINK_ACT]["axes"]["decision"]["values"]}
    pl_required = {e["value"] for e in axes[SINK_PL]["axes"]["required_keys"]["values"]}
    pl_rules = {e["value"] for e in
                axes[SINK_PL]["axes"]["per_rule_finding_counts_keys"]["values"]}

    paths = _sink_paths()
    hits = Counter()
    detail = {}

    def _tag(sink, axis, value, extra):
        key = (sink, axis, str(value))
        hits[key] += 1
        detail.setdefault(key, extra)

    for rec in _stream_jsonl(paths[SINK_GOV]):
        if rec.get("hook") in _NOISE:
            continue
        if str(rec.get("session")) in _SYN_SESSIONS:
            continue
        if str(rec.get("ts", "")) < since:
            continue
        ev = str(rec.get("event"))
        if ev not in gov_events:
            _tag(SINK_GOV, "event", ev, "sample hook=%s" % rec.get("hook"))

    for rec in _stream_jsonl(paths[SINK_ACT]):
        if rec.get("hook") in _NOISE:
            continue
        if str(rec.get("session")) in _SYN_SESSIONS:
            continue
        if str(rec.get("ts", "")) < since:
            continue
        ev = str(rec.get("event"))
        if ev not in act_events:
            _tag(SINK_ACT, "event", ev, "sample hook=%s" % rec.get("hook"))
        dec = rec.get("decision")
        if dec is not None and str(dec) not in act_decisions:
            _tag(SINK_ACT, "decision", dec, "sample hook=%s" % rec.get("hook"))

    for rec in _stream_jsonl(paths[SINK_PL]):
        if str(rec.get("session")) in _SYN_SESSIONS:
            continue
        if str(rec.get("ts", "")) < since:
            continue
        keys = set(rec)
        for k in sorted(keys - pl_required):
            _tag(SINK_PL, "required_keys", k, "extra top-level key")
        for k in sorted(pl_required - keys):
            _tag(SINK_PL, "required_keys", k, "missing required key")
        prf = rec.get("per_rule_finding_counts")
        if isinstance(prf, dict):
            for k in sorted(set(prf) - pl_rules):
                _tag(SINK_PL, "per_rule_finding_counts_keys", k,
                     "undeclared rule key")

    findings = [
        {"kind": "UNDECLARED_VALUE", "sink": sink, "axis": axis, "value": value,
         "count": hits[(sink, axis, value)], "detail": detail[(sink, axis, value)]}
        for (sink, axis, value) in sorted(hits)
    ]

    if artifact:
        try:
            art_mtime = VOCAB_PATH.stat().st_mtime
            newest, newest_m = None, art_mtime
            for sub in ("hooks", "scripts"):
                d = VAULT / ".claude" / sub
                if not d.is_dir():
                    continue
                for p in d.glob("*.py"):
                    if p.name.startswith("test_") or p.name == "conftest.py":
                        continue
                    m = p.stat().st_mtime
                    if m > newest_m:
                        newest, newest_m = "%s/%s" % (sub, p.name), m
            if newest:
                findings.append({
                    "kind": "STALE_VOCABULARY", "sink": "*", "axis": "*",
                    "value": newest, "count": 1,
                    "detail": "writer newer than artifact; rerun --vocab-write "
                              "(mtime heuristic, OneDrive-unreliable)"})
        except Exception:
            pass
    return findings


def vocab_findings_text(since=None, findings=None):
    f = vocab_findings(since=since) if findings is None else findings
    cutoff = since if since is not None else \
        (json.loads(VOCAB_PATH.read_text(encoding="utf-8"))["generated"]["at"]
         if VOCAB_PATH.exists() else "full history")
    if not f:
        return "VOCAB: 0 findings (since %s)." % cutoff
    lines = ["VOCAB: %d finding(s) (since %s):" % (len(f), cutoff)]
    for item in f:
        lines.append("  %-18s %-28s %-28s %-30s n=%-6d %s" % (
            item["kind"], item["sink"], item["axis"], str(item["value"]),
            item["count"], item["detail"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Emit-and-prove verification mode (Hermes P3 step 7, whole-chain check)
#
# Classifies every declared (hook, value) emitter pair by evidence:
#   PROVEN           at least one real-session record in the live sink
#   PROVEN_IN_TEST   a record produced by the emitter's own test file running
#                    against temp-path sinks (only under --prove-with-tests;
#                    the default mode never runs suites, so the lint-sweep
#                    invocation stays cheap and never re-adds test traffic to
#                    live sinks: the C7 lesson, commit ad8ee1e, 128 records
#                    per suite run eliminated)
#   NEVER_OBSERVED   no record anywhere; an honest state, not a failure. Each
#                    entry carries its gate class from gate_yield(): a
#                    deny-only floor at zero fires is healthy. Synthetic-only
#                    live evidence is annotated on the entry rather than
#                    upgrading it, because a historical synthetic record does
#                    not name the test file that produced it.
#
# The mode never drives events into live sinks; it reads them.
# ---------------------------------------------------------------------------


def _prove_pairs():
    """Declared emitter pairs from writer attribution. A file's values pair
    with each hook name it emits under (its literal `hook:` names, falling
    back to the filename stem), which over-approximates for shared helper
    modules; over-approximation can only add NEVER_OBSERVED rows, never hide
    an emitter."""
    s = vocab_sources()
    pairs = []
    for rel, evs in sorted(s["gov_events"].items()):
        hooks = sorted(s["gov_hooks"].get(rel, {Path(rel).stem}))
        for h in hooks:
            for e in sorted(evs):
                pairs.append({"sink": SINK_GOV, "hook": h, "value": e,
                              "writer": rel, "grandfathered": False})
    for g in VOCAB_GRANDFATHERED[SINK_GOV]["event"]:
        pairs.append({"sink": SINK_GOV, "hook": g["hook"], "value": g["value"],
                      "writer": None, "grandfathered": True})
    for rel, decs in sorted(s["act_decisions"].items()):
        hooks = sorted(s["act_hooks"].get(rel, {Path(rel).stem}))
        for h in hooks:
            for d in sorted(decs):
                pairs.append({"sink": SINK_ACT, "hook": h, "value": d,
                              "writer": rel, "grandfathered": False})
    for g in VOCAB_GRANDFATHERED[SINK_ACT]["decision"]:
        pairs.append({"sink": SINK_ACT, "hook": g["hook"], "value": g["value"],
                      "writer": None, "grandfathered": True})
    return pairs


def _pair_evidence(gov_path, act_path):
    """(real, synthetic) Counters keyed (sink, hook, value) from one streaming
    pass per sink."""
    real, syn = Counter(), Counter()
    for rec in _stream_jsonl(gov_path):
        if rec.get("hook") in _NOISE:
            continue
        key = (SINK_GOV, str(rec.get("hook")), str(rec.get("event")))
        (syn if str(rec.get("session")) in _SYN_SESSIONS else real)[key] += 1
    for rec in _stream_jsonl(act_path):
        if rec.get("hook") in _NOISE:
            continue
        dec = rec.get("decision")
        if dec is None:
            continue
        key = (SINK_ACT, str(rec.get("hook")), str(dec))
        (syn if str(rec.get("session")) in _SYN_SESSIONS else real)[key] += 1
    return real, syn


def _matching_test_file(writer_rel):
    if not writer_rel:
        return None
    sub, name = writer_rel.split("/", 1)
    stem = _norm_hook_name(Path(name).stem)
    d = VAULT / ".claude" / sub
    if not d.is_dir():
        return None
    for p in sorted(d.glob("test_*.py")):
        t = _norm_hook_name(p.stem[len("test_"):])
        if t == stem or t.startswith(stem) or stem.startswith(t):
            return "%s/%s" % (sub, p.name)
    return None


def _test_evidence(test_files):
    """Run each test file once with both JSONL sinks redirected to temp
    files; return the pair-set observed there, keyed by test file. Suites
    that error or time out contribute nothing (reported by caller absence)."""
    import subprocess
    import tempfile
    found = {}
    for tf in sorted(test_files):
        tmpdir = tempfile.mkdtemp(prefix="hermes-prove-")
        gov_t = os.path.join(tmpdir, "governance-log.jsonl")
        act_t = os.path.join(tmpdir, "hook-activity.jsonl")
        env = dict(os.environ)
        env["GOVERNANCE_LOG_PATH"] = gov_t
        env["HOOK_ACTIVITY_LOG_PATH"] = act_t
        try:
            subprocess.run(
                [sys.executable, str(VAULT / ".claude" / tf)],
                cwd=str((VAULT / ".claude" / tf).parent),
                env=env, capture_output=True, timeout=180)
        except Exception:
            continue
        r, s = _pair_evidence(Path(gov_t), Path(act_t))
        for key in set(r) | set(s):
            found.setdefault(key, tf)
    return found


def prove_report(with_tests=False):
    pairs = _prove_pairs()
    paths = _sink_paths()
    real, syn = _pair_evidence(paths[SINK_GOV], paths[SINK_ACT])
    gate_class = {}
    for row in gate_yield()["rows"]:
        gate_class[_norm_hook_name(str(row["hook"]))] = row["class"]

    test_hits = {}
    if with_tests:
        candidates = set()
        for p in pairs:
            key = (p["sink"], p["hook"], p["value"])
            if real[key] == 0:
                tf = _matching_test_file(p["writer"])
                if tf:
                    candidates.add(tf)
        test_hits = _test_evidence(candidates)

    out = []
    for p in pairs:
        key = (p["sink"], p["hook"], p["value"])
        row = dict(p)
        if real[key] > 0:
            row["class"] = "PROVEN"
            row["evidence"] = "%d real-session record(s)" % real[key]
        elif key in test_hits:
            row["class"] = "PROVEN_IN_TEST"
            row["evidence"] = "record produced by %s against temp-path sinks" \
                % test_hits[key]
            row["test_file"] = test_hits[key]
        else:
            row["class"] = "NEVER_OBSERVED"
            row["gate_class"] = gate_class.get(
                _norm_hook_name(p["hook"]), "unregistered")
            row["evidence"] = "no record" + (
                "; %d synthetic-only record(s) exist in the live sink"
                % syn[key] if syn[key] else "")
        out.append(row)
    return out


def prove_text(with_tests=False):
    rows = prove_report(with_tests=with_tests)
    counts = Counter(r["class"] for r in rows)
    head = ["=== EMIT-AND-PROVE (declared emitter pairs vs sink evidence) ===",
            "  pairs: %d  |  PROVEN: %d  |  PROVEN_IN_TEST: %d  |  "
            "NEVER_OBSERVED: %d  |  mode: %s" % (
                len(rows), counts["PROVEN"], counts["PROVEN_IN_TEST"],
                counts["NEVER_OBSERVED"],
                "with-tests" if with_tests else "join-only (live evidence)")]
    lines = []
    for r in sorted(rows, key=lambda x: (x["class"], x["sink"], str(x["hook"]),
                                         str(x["value"]))):
        extra = ""
        if r["class"] == "NEVER_OBSERVED":
            extra = "  [gate class: %s]" % r["gate_class"]
        if r.get("grandfathered"):
            extra += "  [grandfathered]"
        lines.append("  %-15s %-22s %-34s %-34s %s%s" % (
            r["class"], r["sink"].replace(".jsonl", ""), str(r["hook"]),
            str(r["value"]), r["evidence"], extra))
    return "\n".join(head + lines)


def vocab_text():
    v = vocab_dict()
    out = ["=== TELEMETRY VOCABULARY (declared, generated from writer source) ==="]
    for sink in sorted(v["sinks"]):
        out.append("sink: %s" % sink)
        for axis in sorted(v["sinks"][sink]["axes"]):
            spec = v["sinks"][sink]["axes"][axis]
            vals = spec["values"]
            out.append("  axis %s (%d declared):" % (axis, len(vals)))
            for e in vals:
                mark = "  [grandfathered: %s]" % e.get("reason") \
                    if e.get("grandfathered") else ""
                w = ", ".join(e.get("writers", [])) or "-"
                out.append("    %-40s %s%s" % (e["value"], w, mark))
            if spec.get("authority"):
                out.append("    (authority: %s)" % spec["authority"])
    return "\n".join(out)


if __name__ == "__main__":
    if "--yield" in sys.argv:
        print(yield_text())
        raise SystemExit(0)
    if "--matrix" in sys.argv:
        print(matrix_markdown())
        raise SystemExit(0)
    if "--findings" in sys.argv:
        since = None
        for arg in sys.argv:
            if arg.startswith("--since="):
                s = arg.split("=", 1)[1]
                since = "1970-01-01 00:00:00" if s == "all" else s
        mf = matrix_findings()
        vf = vocab_findings(since=since)
        print(findings_text())
        print(vocab_findings_text(since=since, findings=vf))
        raise SystemExit(1 if (mf or vf) else 0)
    if "--prove-with-tests" in sys.argv:
        print(prove_text(with_tests=True))
        raise SystemExit(0)
    if "--prove" in sys.argv:
        print(prove_text())
        raise SystemExit(0)
    if "--vocab-write" in sys.argv:
        p = write_vocab()
        print("telemetry vocabulary written: %s" % p)
        raise SystemExit(0)
    if "--vocab" in sys.argv:
        print(vocab_text())
        raise SystemExit(0)
    sys.exit(main(as_json="--json" in sys.argv))
