#!/usr/bin/env python3
"""Trust-contract verifier and sustained-green ledger (ROAD-13, 2026-09-08).

Evaluates TC-1 through TC-7 (trust roadmap section 4) over the output of
the eight contract lint passes (ROAD-2 through ROAD-9), prints one
PASS/FAIL line per objective plus a contract line, and appends exactly one
row per cycle to the ledger. Advisory only: it blocks nothing, is
registered in no hook chain, and its only write is appends to its own
ledger file. It never modifies the lint passes, the registry, the
baseline, or any doctrine file, and it reads finding counts from pass
OUTPUT text only (it imports nothing from the pass modules).

Input modes (mutually exclusive):
  --report PATH   parse a weekly lint report; pass outputs are read from
                  the report's fenced code blocks; the cycle timestamp is
                  the report's frontmatter `date:` field (midnight UTC).
  --live          run the eight pass scripts and evaluate their captured
                  stdout; the cycle timestamp is now (UTC), or --now.

Output contract:
  - seven lines `TC-<n> PASS|FAIL streak=<k>[ GREEN][ <reason key=values>]`
  - one line `CONTRACT PASS|FAIL streak=<k>[ GREEN]`
  - one LEDGER action line (`appended` or `duplicate ... appended=none`)

Exit codes:
  0  all seven objectives PASS (row appended, or duplicate dedupe)
  1  at least one objective FAIL (row appended, or duplicate dedupe)
  2  fail-loud BEFORE any ledger write: report missing/unreadable or
     frontmatter date missing, registry missing/unparseable, existing
     ledger line unparseable, live-mode subprocess launch failure,
     timeout, or undecodable stdout.

Boundary rule: a pass that RUNS and prints DERIVATION FAILURE produced
readable output stating failure. That is a measured-red fact: the section
is invalid, TC-7 and the owning objective FAIL, and the row IS appended.
Only output the verifier cannot read at all triggers the no-write exit 2.

Streaks: GREEN_WINDOW_N = 4 consecutive stamped weekly cycles; a gap
larger than WEEKLY_GAP_LIMIT_DAYS between adjacent ledger rows is a
missed cycle and resets every streak before the new cycle counts (an
unmeasured week is not a green week). Both constants are owner-tunable
at ratification (section 6 ruling 7); the 8-day gap limit is the 7-day
cadence plus 1 day grace, a build-time proposal.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_LEDGER = VAULT / ".claude" / "hooks" / "_state" / "trust-contract-ledger.jsonl"
DEFAULT_REGISTRY = VAULT / ".claude" / "hooks" / "_state" / "enforcement-claims.json"
DEFAULT_BASELINE = VAULT / ".claude" / "hooks" / "_state" / "orphan-baseline.json"

GREEN_WINDOW_N = 4          # sustained-green window (section 6 ruling 7)
WEEKLY_GAP_LIMIT_DAYS = 8   # 7-day cadence + 1 day grace (proposal)
BASELINE_MAX_AGE_DAYS = 7   # TC-4 stamp-age window (section 4)

SUBPROCESS_TIMEOUT_S = 300

# Grammar catalog, transcribed from the eight lint_pass_* module sources
# (measurement-line prefix, finding-line prefix, script filename). The
# verifier's only knowledge of the passes is these printed shapes.
PASSES = {
    "ROOT_STRAY": {
        "measure": re.compile(r"^ROOT entries=\d+ allowlisted=\d+ strays=\d+"),
        "finding": re.compile(r"^ROOT_STRAY  "),
        "script": "lint_pass_root_stray.py",
    },
    "MEMORY_OVERFILL": {
        "measure": re.compile(r"^MEMORY bytes=\d+ target=\d+ long_lines=\d+"),
        "finding": re.compile(r"^MEMORY_OVERFILL  "),
        "script": "lint_pass_memory_overfill.py",
    },
    "KB_INDEX_BUDGET": {
        "measure": re.compile(r"^KB_INDEX bytes=\d+ budget=\d+"),
        "finding": re.compile(r"^KB_INDEX_BUDGET  "),
        "script": "lint_pass_kb_index_budget.py",
    },
    "WORK_INDEX_STALE": {
        "measure": re.compile(r"^WORK_INDEX project="),
        "finding": re.compile(r"^WORK_INDEX_STALE  "),
        "script": "lint_pass_work_index_stale.py",
    },
    "ORPHAN_DRIFT": {
        "measure": re.compile(r"^ORPHAN_LINKS total=\d+ dropped=\d+"),
        "finding": re.compile(r"^ORPHAN_DRIFT  layer="),
        "script": "lint_pass_orphan_drift.py",
    },
    "TAG_CANON_DIVERGENCE": {
        "measure": re.compile(r"^TAG_CANON sizes "),
        "finding": re.compile(r"^TAG_CANON_DIVERGENCE  "),
        "script": "lint_pass_tag_canon_divergence.py",
    },
    "STATUS_NONCANON": {
        "measure": re.compile(r"^STATUS scanned=\d+ noncanonical=\d+"),
        "finding": re.compile(r"^STATUS_NONCANON  "),
        "script": "lint_pass_status_noncanon.py",
    },
    "ENFORCEMENT_CLAIM_STALE": {
        "measure": re.compile(r"^ENFORCEMENT_CLAIMS claims=\d+ ok=\d+ stale=\d+"),
        "finding": re.compile(r"^ENFORCEMENT_CLAIM_STALE  "),
        "script": "lint_pass_enforcement_claims.py",
    },
}

DERIVATION = re.compile(r"^DERIVATION FAILURE")
FENCE = re.compile(r"^```[^\n]*\n(.*?)^```[ \t]*$", re.M | re.S)
FRONT_DATE = re.compile(r"^date:\s*[\"']?(\d{4}-\d{2}-\d{2})", re.M)
ORPHAN_LAYER = re.compile(r"^ORPHAN_DRIFT  layer=(raw|wiki)\b", re.M)


def parse_iso(value):
    """Parse an ISO timestamp (Z-suffixed or offset) to aware UTC."""
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def report_segments(text):
    """Fenced code blocks of a report, or the whole text when none exist."""
    blocks = [m.group(1) for m in FENCE.finditer(text)]
    return blocks if blocks else [text]


def evaluate(segments):
    """Evaluate segments of pass output text.

    Returns {code: {"state": present|missing|invalid, "count": int|None}}
    plus the set of ORPHAN_DRIFT layers seen in valid segments. A segment
    containing a DERIVATION FAILURE line invalidates every pass whose
    measurement or finding line appears in that same segment.
    """
    state = {code: {"state": "missing", "count": None} for code in PASSES}
    layers = set()
    for seg in segments:
        lines = seg.splitlines()
        failed = any(DERIVATION.match(l) for l in lines)
        for code, g in PASSES.items():
            measured = any(g["measure"].match(l) for l in lines)
            found = [l for l in lines if g["finding"].match(l)]
            if not measured and not found:
                continue
            if failed:
                state[code] = {"state": "invalid", "count": None}
                continue
            if state[code]["state"] == "invalid":
                continue
            prev = state[code]["count"] or 0
            state[code] = {"state": "present" if measured or
                           state[code]["state"] == "present" else
                           state[code]["state"], "count": prev + len(found)}
            if state[code]["state"] != "present" and measured:
                state[code]["state"] = "present"
        if not failed:
            layers.update(ORPHAN_LAYER.findall(seg))
    # a pass with finding lines but no measurement line anywhere stays
    # missing: the always-print measurement line is the presence witness
    for code in PASSES:
        if state[code]["state"] != "present":
            state[code]["count"] = None
    return state, layers


def run_live(scripts_dir):
    """Run the eight pass scripts, return list of captured stdout bodies.

    Any launch failure, timeout, or undecodable stdout is fail-loud exit 2
    (raises SystemExit through the caller). A pass exiting 2 with readable
    DERIVATION FAILURE output is NOT a launch failure: its text is
    returned and evaluated as an invalid section (measured red).
    """
    segments = []
    for code, g in PASSES.items():
        script = Path(scripts_dir) / g["script"]
        try:
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, encoding="utf-8",
                errors="strict", timeout=SUBPROCESS_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            print(f"FAIL-LOUD: cannot run {script.name}: {e}")
            return None
        if proc.stdout is None:
            print(f"FAIL-LOUD: no stdout captured from {script.name}")
            return None
        segments.append(proc.stdout)
    return segments


def load_registry_count(path):
    """Claim count from the registry, or None on fail-loud."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"FAIL-LOUD: registry unusable ({path}): {e}")
        return None
    claims = data.get("claims") if isinstance(data, dict) else data
    if not isinstance(claims, list):
        print(f"FAIL-LOUD: registry has no claims list ({path})")
        return None
    return len(claims)


def baseline_age_ok(path, cycle_dt):
    """(ok, reason) for the TC-4 stamp-age assertion.

    An unreadable baseline is a measured TC-4 FAIL, not a fail-loud exit:
    the freshness the objective asserts cannot be shown. (D6's exit-2
    list is exhaustive and does not include the baseline.)
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        stamp = parse_iso(data["last_iso"])
    except (OSError, json.JSONDecodeError, UnicodeDecodeError,
            KeyError, ValueError) as e:
        return False, f"baseline-unreadable:{type(e).__name__}"
    age = cycle_dt - stamp
    if age > timedelta(days=BASELINE_MAX_AGE_DAYS):
        return False, f"baseline-stale:last_iso={data['last_iso']}"
    return True, ""


def load_ledger(path):
    """Existing ledger rows, [] when absent, None on a corrupt line."""
    p = Path(path)
    if not p.exists():
        return []
    rows = []
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        print(f"FAIL-LOUD: ledger unreadable ({path}): {e}")
        return None
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"FAIL-LOUD: ledger line {n} unparseable ({path}); "
                  "streaks cannot be computed from a corrupt ledger")
            return None
    return rows


def judge(sections, layers, registry_count, baseline_ok, baseline_reason):
    """Per-objective (ok, reason) map from the evaluated inputs."""
    def clean(code):
        s = sections[code]
        if s["state"] != "present":
            return False, f"section={code}:{s['state']}"
        if s["count"] != 0:
            return False, f"{code}={s['count']}"
        return True, ""

    results = {}
    results["TC-1"] = clean("ROOT_STRAY")

    reasons = [r for ok, r in (clean("MEMORY_OVERFILL"),
                               clean("KB_INDEX_BUDGET"),
                               clean("WORK_INDEX_STALE")) if not ok]
    results["TC-2"] = (not reasons, " ".join(reasons))

    ok3, r3 = clean("ENFORCEMENT_CLAIM_STALE")
    if ok3 and registry_count < 1:
        ok3, r3 = False, "registry-claims=0"
    results["TC-3"] = (ok3, r3)

    s4 = sections["ORPHAN_DRIFT"]
    if s4["state"] != "present":
        results["TC-4"] = (False, f"section=ORPHAN_DRIFT:{s4['state']}")
    elif layers != {"raw", "wiki"}:
        missing = sorted({"raw", "wiki"} - layers)
        results["TC-4"] = (False, f"layers-missing={','.join(missing)}")
    elif not baseline_ok:
        results["TC-4"] = (False, baseline_reason)
    else:
        results["TC-4"] = (True, "")

    results["TC-5"] = clean("TAG_CANON_DIVERGENCE")
    results["TC-6"] = clean("STATUS_NONCANON")

    missing = sorted(c for c in PASSES if sections[c]["state"] == "missing")
    invalid = sorted(c for c in PASSES if sections[c]["state"] == "invalid")
    if missing or invalid:
        parts = []
        if missing:
            parts.append("missing=" + ",".join(missing))
        if invalid:
            parts.append("invalid=" + ",".join(invalid))
        results["TC-7"] = (False, " ".join(parts))
    else:
        results["TC-7"] = (True, "")
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", help="lint report file to evaluate")
    mode.add_argument("--live", action="store_true",
                      help="run the eight pass scripts and evaluate stdout")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    ap.add_argument("--scripts-dir", default=str(SCRIPTS),
                    help="directory holding the pass scripts (live mode)")
    ap.add_argument("--now", default=None,
                    help="ISO override for the live-mode cycle timestamp")
    args = ap.parse_args(argv)

    # --- gather inputs (every fail-loud path exits 2 BEFORE any write) ---
    if args.report:
        try:
            text = Path(args.report).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"FAIL-LOUD: report unreadable ({args.report}): {e}")
            return 2
        m = FRONT_DATE.search(text.split("\n---", 2)[0] + "\n"
                              if text.startswith("---") else "")
        if not m:
            m = FRONT_DATE.search(text)
        if not m:
            print(f"FAIL-LOUD: no frontmatter date in {args.report}")
            return 2
        cycle_dt = parse_iso(m.group(1) + "T00:00:00Z")
        source = f"report:{args.report}"
        segments = report_segments(text)
    else:
        cycle_dt = parse_iso(args.now) if args.now else \
            datetime.now(timezone.utc).replace(microsecond=0)
        source = "live"
        # TC-4 reads the baseline stamp BEFORE the passes run: a live run
        # of lint_pass_orphan_drift restamps the baseline itself, which
        # would make the freshness assertion vacuously true afterwards.
        baseline_pre = baseline_age_ok(args.baseline, cycle_dt)
        segments = run_live(args.scripts_dir)
        if segments is None:
            return 2

    registry_count = load_registry_count(args.registry)
    if registry_count is None:
        return 2

    ledger_rows = load_ledger(args.ledger)
    if ledger_rows is None:
        return 2

    if args.report:
        baseline_ok, baseline_reason = baseline_age_ok(args.baseline, cycle_dt)
    else:
        baseline_ok, baseline_reason = baseline_pre

    # --- evaluate ---
    sections, layers = evaluate(segments)
    results = judge(sections, layers, registry_count,
                    baseline_ok, baseline_reason)

    # --- streaks ---
    # "Exactly one row per cycle" is the invariant, and the LAST run of a cycle
    # is the one that counts (ruled 2026-09-09; overturn by reverting this
    # block and the ledger action below). Previously the FIRST run won
    # permanently, so a cycle that started red and was then fixed still
    # recorded FAIL. Since remediation is exactly what happens on a red day,
    # that made GREEN_WINDOW_N effectively unreachable.
    #
    # Streaks are therefore computed against the last row of a DIFFERENT
    # cycle, never against an earlier run of this one. Without that, re-running
    # the verifier inside one cycle walks the streak up by one each time.
    cycle_key = iso(cycle_dt)[:10]
    same_cycle_prev = None
    if ledger_rows and ledger_rows[-1].get("source") == source and \
            str(ledger_rows[-1].get("cycle_iso", ""))[:10] == cycle_key:
        same_cycle_prev = ledger_rows[-1]
    prior_cycles = [r for r in ledger_rows
                    if str(r.get("cycle_iso", ""))[:10] != cycle_key]
    prev = prior_cycles[-1] if prior_cycles else None
    consecutive = False
    if prev is not None:
        try:
            gap = cycle_dt - parse_iso(prev["cycle_iso"])
        except (KeyError, ValueError):
            print(f"FAIL-LOUD: previous ledger row has no usable cycle_iso")
            return 2
        # out-of-order (negative) gaps also reset: not consecutive
        consecutive = timedelta(0) <= gap <= \
            timedelta(days=WEEKLY_GAP_LIMIT_DAYS)

    objectives = {}
    all_green = all(ok for ok, _ in results.values())
    for tc, (ok, _reason) in results.items():
        prev_streak = 0
        if consecutive and prev is not None:
            prev_streak = prev.get("objectives", {}).get(tc, {}) \
                              .get("streak", 0)
        streak = prev_streak + 1 if ok else 0
        objectives[tc] = {"result": "PASS" if ok else "FAIL",
                          "streak": streak}
    prev_contract = 0
    if consecutive and prev is not None:
        prev_contract = prev.get("contract", {}).get("streak", 0)
    contract_streak = prev_contract + 1 if all_green else 0
    contract = {"result": "PASS" if all_green else "FAIL",
                "streak": contract_streak}

    # --- print the seven lines + contract line ---
    for tc in sorted(results, key=lambda t: int(t.split("-")[1])):
        ok, reason = results[tc]
        o = objectives[tc]
        line = f"{tc} {o['result']} streak={o['streak']}"
        if ok and o["streak"] >= GREEN_WINDOW_N:
            line += " GREEN"
        if reason:
            line += f" {reason}"
        print(line)
    cline = f"CONTRACT {contract['result']} streak={contract['streak']}"
    if all_green and contract_streak >= GREEN_WINDOW_N:
        cline += " GREEN"
    print(cline)

    # --- ledger action: exactly one row per cycle ---
    row = {
        "cycle_iso": iso(cycle_dt),
        "source": source,
        "codes": {c: sections[c]["count"] for c in PASSES},
        "objectives": objectives,
        "contract": contract,
    }
    ledger_path = Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if same_cycle_prev is not None:
        # Supersede this cycle's existing row, preserving one-row-per-cycle.
        # Rewritten via a temp file and os.replace so an interrupted run cannot
        # leave a truncated ledger: the whole history is being rewritten here,
        # not appended to, and that is the one operation worth making atomic.
        rewritten = ledger_rows[:-1] + [row]
        tmp = ledger_path.with_suffix(ledger_path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            for r in rewritten:
                f.write(json.dumps(r) + "\n")
        os.replace(tmp, ledger_path)
        print(f"LEDGER superseded cycle={row['cycle_iso'][:10]} "
              f"source={source} row={len(rewritten)} path={ledger_path}")
    else:
        with open(ledger_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row) + "\n")
        print(f"LEDGER appended row={len(ledger_rows) + 1} "
              f"path={ledger_path}")

    return 0 if all_green else 1


if __name__ == "__main__":
    sys.exit(main())
