"""ledger_check.py: computational join between findings-resolved-ledger.jsonl
and the two audit registers, plus the re-runnable metric-2 counts.

Architect finding 2026-08-31: the ledger key (tier:path:batch:slug) is
hand-assigned because register rows carry no ids, so nothing verified that a
key resolves to exactly one register row. This script is that verification,
run before trusting any resolved count:

- every ledger entry must resolve to EXACTLY ONE register row (same tier,
  path, batch, severity, and the entry's summary_prefix tokens appearing in
  order inside the row's summary); zero or multiple matches exit 2
- two ledger entries resolving to the same register row exit 2 (a duplicate
  would silently inflate "resolved")
- the metric-2 numbers (raw HIGH, resolved HIGH, open-or-unassessed) are
  printed from the join, replacing prose arithmetic with a re-runnable
  artifact

Determinism: output is a pure function of the three input files; no
timestamps, no wall clock. Missing or empty inputs fail loud at exit 2.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
WORK = VAULT / "Projects" / "Agent-Governance-Research" / "work"
DEFAULT_LEDGER = WORK / "findings-resolved-ledger.jsonl"
DEFAULT_TIER_A = WORK / "2026-08-23-audit-tierA-merged.json"
DEFAULT_TIER_B = WORK / "2026-08-23-audit-tierB-merged.json"

KEY_RE = re.compile(r"^tier([AB]):(.+):batch(\d+):([A-Za-z0-9][A-Za-z0-9-]*)$")


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 2


def _tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def tokens_in_order(prefix_tokens: list[str], summary_tokens: list[str]) -> bool:
    """True if every prefix token appears in the summary, in order (gaps
    allowed). Handles prefixes that paraphrase punctuation/backtick elisions."""
    it = iter(summary_tokens)
    return all(tok in it for tok in prefix_tokens)


def resolve_entry(entry: dict, registers: dict) -> tuple[str, int] | str:
    """Return (tier, row_index) for a unique match, or an error string."""
    key = entry.get("key", "")
    m = KEY_RE.match(key)
    if not m:
        return f"unparseable key {key!r}"
    tier, path, batch, _slug = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    if entry.get("tier") and entry["tier"] != tier:
        return f"key names tier{tier} but entry field says tier {entry['tier']!r}"
    if entry.get("path") and entry["path"] != path:
        return f"key path {path!r} disagrees with entry path {entry['path']!r}"
    rows = registers.get(tier, [])
    prefix = _tokens(entry.get("summary_prefix", ""))
    if not prefix:
        return "entry has no summary_prefix to join on"
    candidates = [
        (i, r) for i, r in enumerate(rows)
        if r.get("path") == path and int(r.get("batch", -1)) == batch
    ]
    matches = [
        (i, r) for i, r in candidates
        if tokens_in_order(prefix, _tokens(str(r.get("summary", ""))))
    ]
    if len(matches) != 1:
        return (f"key {key!r} matched {len(matches)} register rows "
                f"(candidates sharing tier/path/batch: {len(candidates)})")
    i, row = matches[0]
    if entry.get("severity") and str(row.get("severity", "")).lower() != entry["severity"].lower():
        return (f"key {key!r} resolved to a row of severity "
                f"{row.get('severity')!r}, entry claims {entry['severity']!r}")
    return (tier, i)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--tier-a", type=Path, default=DEFAULT_TIER_A)
    ap.add_argument("--tier-b", type=Path, default=DEFAULT_TIER_B)
    args = ap.parse_args(argv)

    for path, name in ((args.ledger, "ledger"), (args.tier_a, "tier A register"),
                       (args.tier_b, "tier B register")):
        if not path.exists():
            return _fail(f"{name} not found at {path}")

    registers = {}
    for tier, path in (("A", args.tier_a), ("B", args.tier_b)):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return _fail(f"tier {tier} register unparseable: {exc}")
        rows = doc.get("findings")
        if not isinstance(rows, list) or not rows:
            return _fail(f"tier {tier} register has no findings array; "
                         "refusing a vacuous pass")
        registers[tier] = rows

    entries = []
    for n, line in enumerate(args.ledger.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            return _fail(f"ledger line {n} unparseable: {exc}")

    resolved_rows: dict[tuple[str, int], str] = {}
    for entry in entries:
        outcome = resolve_entry(entry, registers)
        if isinstance(outcome, str):
            return _fail(outcome)
        if outcome in resolved_rows:
            return _fail(f"keys {resolved_rows[outcome]!r} and {entry['key']!r} "
                         "resolve to the SAME register row; duplicate would "
                         "inflate the resolved count")
        resolved_rows[outcome] = entry["key"]
        print(f"OK {entry['key']} -> tier{outcome[0]} row {outcome[1]}")

    raw_high = resolved_high = 0
    for tier in ("A", "B"):
        rows = registers[tier]
        high = [i for i, r in enumerate(rows)
                if str(r.get("severity", "")).lower() == "high"]
        tier_resolved = [i for i in high if (tier, i) in resolved_rows]
        raw_high += len(high)
        resolved_high += len(tier_resolved)
        print(f"tier{tier}: {len(rows)} findings, {len(high)} HIGH, "
              f"{len(tier_resolved)} HIGH resolved")
    print(f"metric-2: {raw_high} raw HIGH, {resolved_high} resolved, "
          f"{raw_high - resolved_high} open-or-unassessed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
