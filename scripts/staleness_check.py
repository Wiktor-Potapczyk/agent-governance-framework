#!/usr/bin/env python3
"""staleness_check.py - one generalized staleness mechanism for registered spec artifacts.

Origin: O4 of Projects/Agent-Governance-Research/work/2026-08-30-harness-spec-objectives.md.
Generalizes .claude/hooks/registry-staleness-check.py's age-threshold pattern (one
artifact, one max age) into a declarative manifest of many artifacts, rather than
cloning a new one-off script per artifact (per R5, extend-not-clone).

Data contract
-------------
Reads a manifest JSON file (default: staleness-manifest.json next to this script)
shaped as:

    {
      "generated_at": "<iso timestamp, informational only>",
      "entries": [
        {
          "id": "<unique string>",
          "artifact_path": "<path relative to vault root>",
          "max_age_days": <int>,
          "rederive_command": "<shell command that regenerates the artifact>",
          "age_source": "mtime" | "embedded_comment",   # optional, default "mtime"
          "age_regex": "<regex with one capture group>", # required if age_source is embedded_comment
          "advisory": true,                               # optional (O10 D4): any non-PASS
                                                          # verdict downgrades to WARN
          "live_count_probe": {                           # optional
            "source_file": "<path relative to vault root, a JSON file>",
            "source_key_path": ["<key>", ...],             # walked into source_file's JSON
            "table_metric_map": {"<markdown table label>": "<source JSON field>", ...}
          },
          "consistency_probe": {                          # optional
            "file_a": "<path relative to vault root>",
            "regex_a": "<regex with exactly one capture group>",
            "file_b": "<path relative to vault root, a JSON file>",
            "key_path_b": ["<key>", ...]                   # walked into file_b's JSON
          },
          "citations_probe": {                            # optional
            "path_regex": "<regex; every match is a path to resolve>"
          },
          "line_count_probe": {                           # optional (O10 D5)
            "max_lines": <int>                             # artifact line count must not exceed
          },
          "dir_count_probe": {                            # optional (O10 D5)
            "dir": "<path relative to vault root>",
            "glob": "<glob pattern>",
            "min_count": <int>                             # matching files must be >= this
          },
          "provenance_count_probe": {                     # optional (O10 D5)
            "source_file": "<path relative to vault root, JSON with a rows list>",
            "exact": ["<provenance value>", ...],          # rows counted on equality
            "prefixes": ["<provenance prefix>", ...],      # rows counted on startswith
            "expected_key_path": ["<key>", ...]            # walked into the ARTIFACT's JSON
          }
        }, ...
      ],
      "generated_block": {                                # optional (O10 D2/D3)
        "do_not_edit": "<header naming the generator and the --check consequence>",
        "source_inventory_generated_at": "<the inventory's own stamp, never now()>",
        "entries": [ ...same entry shape as above... ]
      }
    }

When `generated_block` is present, its `entries` are appended to the hand `entries`
array at load time and validated identically; the generator that owns the block is
.claude/scripts/staleness_manifest_generate.py (O10). An entry id duplicated across
(or within) the two sections is a MANIFEST_DUPLICATE_ID error: this is the machine
guarantee that a superseded hand entry and its generated replacement never both sit
on the board. A manifest without the block loads exactly as before.

`id`, `artifact_path`, `rederive_command` are required on every entry. `max_age_days`
is also required, EXCEPT on an entry carrying a `consistency_probe`, a
`line_count_probe`, or a `dir_count_probe`: those checks compare live structure, not
an artifact age of their own, so age checking is optional there (O7 Finding 3,
extended by O10 D5). An entry missing a field it's required to carry, or a manifest
with zero entries, is a MANIFEST error, not a per-entry one: a manifest that
resolves to nothing to check must never report a clean bill.

Per-entry verdicts
------------------
PASS             the artifact exists, is within max_age_days (when configured), and
                  every configured probe (live_count_probe, consistency_probe,
                  citations_probe) agrees with its live source.
STALE             the artifact exists and is checkable, but is past max_age_days
                  and/or its embedded counts disagree with the live source
                  (live_count_probe, provenance_count_probe), and/or a structural
                  bound is violated (line_count_probe, dir_count_probe).
WARN              an entry flagged "advisory": true evaluated to any non-PASS
                  verdict (O10 D4). The original verdict stays visible in the
                  detail. WARN is excluded from the CLI exit-2 set and appears in
                  hook mode as at most one advisory line per entry. Only the O10
                  governing-artifact entries carry the flag until O16's rulings
                  land.
DIVERGENT         a consistency_probe's two extracted values disagree. Exit-code
                  class matches STALE.
BROKEN_CITATION   a citations_probe found a path that does not resolve on disk.
                  Exit-code class matches STALE.
ERROR             the artifact cannot be checked at all: missing file, unreadable
                  manifest field, age marker not found, probe source missing or
                  malformed, or a probe's regex extracted nothing. ERROR is distinct
                  from STALE/DIVERGENT/BROKEN_CITATION: those mean "known to need
                  re-derivation", ERROR means "the checker could not determine an
                  answer".

Two run modes
-------------
CLI mode (default): fails loud. An empty, missing, or malformed manifest exits 1
with a distinct MANIFEST_* message on stderr. Any entry not PASS and not WARN
exits 2. Clean exit 0 when every entry is PASS or WARN (WARN is advisory by
definition and must not fail the board; O10 D4).

Hook mode (--hook): the SessionStart advisory contract used across this vault's
hooks (see registry-staleness-check.py) -- never raises, never blocks a session.
A manifest problem or a per-entry ERROR is swallowed to silence (exit 0); when one
or more entries are STALE or ERROR, emits one hookSpecificOutput additionalContext
line per entry naming its re-derive command. Silent (no stdout) when everything
passes.

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/staleness_check.py
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/staleness_check.py --json
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/staleness_check.py --hook
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Layout adaptation (published copy): harness root from VAULT_DIR (repo keeps
# scripts/ at top level, not under .claude/).
VAULT = Path(os.environ.get("VAULT_DIR", "C:/Users/exampleuser/Workspace"))
DEFAULT_MANIFEST = Path(__file__).resolve().parent / "staleness-manifest.json"

VERDICT_PASS = "PASS"
VERDICT_STALE = "STALE"
VERDICT_ERROR = "ERROR"
VERDICT_DIVERGENT = "DIVERGENT"
VERDICT_BROKEN_CITATION = "BROKEN_CITATION"
VERDICT_WARN = "WARN"

# Required on every entry. max_age_days is checked separately in load_manifest:
# it is required too, except on an entry carrying one of the age-exempt probes.
BASE_REQUIRED_ENTRY_FIELDS = ("id", "artifact_path", "rederive_command")
REQUIRED_ENTRY_FIELDS = BASE_REQUIRED_ENTRY_FIELDS + ("max_age_days",)

# Probes whose presence lifts the max_age_days requirement: they compare live
# structure and have no artifact age of their own (O7 Finding 3, O10 D5).
AGE_EXEMPT_PROBES = ("consistency_probe", "line_count_probe", "dir_count_probe")


class ManifestError(Exception):
    """The manifest itself cannot be trusted: missing, unreadable, empty, malformed,
    or resolving to zero entries. Distinct from a per-entry ERROR verdict."""


class EntryError(Exception):
    """Raised while checking one entry; caught by check_entry and turned into an
    ERROR verdict rather than propagating."""


@dataclass
class EntryResult:
    id: str
    artifact_path: str
    verdict: str
    detail: str
    rederive_command: str
    age_days: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "artifact_path": self.artifact_path,
            "verdict": self.verdict,
            "detail": self.detail,
            "rederive_command": self.rederive_command,
            "age_days": round(self.age_days, 2) if self.age_days is not None else None,
        }


def load_manifest(manifest_path: Path) -> list[dict]:
    """Load and validate the manifest. Raises ManifestError on anything that means
    the manifest cannot be trusted to check against."""
    if not manifest_path.exists():
        raise ManifestError(f"MANIFEST_NOT_FOUND: {manifest_path} does not exist")
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"MANIFEST_UNREADABLE: {manifest_path}: {exc}") from exc
    if not raw.strip():
        raise ManifestError(f"MANIFEST_EMPTY: {manifest_path} is an empty file")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ManifestError(f"MANIFEST_INVALID_JSON: {manifest_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"MANIFEST_MALFORMED: {manifest_path} top level must be an object")
    hand = data.get("entries", [])
    if not isinstance(hand, list):
        raise ManifestError(f"MANIFEST_MALFORMED: {manifest_path} 'entries' must be a list")
    generated: list = []
    block = data.get("generated_block")
    if block is not None:
        if not isinstance(block, dict) or not isinstance(block.get("entries"), list):
            raise ManifestError(
                f"MANIFEST_MALFORMED: {manifest_path} 'generated_block' must be an "
                "object with an 'entries' list"
            )
        generated = block["entries"]
    entries = hand + generated
    if len(entries) == 0:
        raise ManifestError(
            f"MANIFEST_NO_ENTRIES: {manifest_path} 'entries' is missing or empty; "
            "a manifest resolving to nothing is refused, not reported as a clean bill"
        )
    seen_ids: set = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ManifestError(f"MANIFEST_MALFORMED: entries[{i}] is not an object")
        required = list(BASE_REQUIRED_ENTRY_FIELDS)
        if not any(p in entry for p in AGE_EXEMPT_PROBES):
            required.append("max_age_days")
        missing = [f for f in required if f not in entry]
        if missing:
            raise ManifestError(
                f"MANIFEST_MALFORMED: entries[{i}] (id={entry.get('id')!r}) "
                f"missing required field(s): {missing}"
            )
        entry_id = entry["id"]
        if entry_id in seen_ids:
            raise ManifestError(
                f"MANIFEST_DUPLICATE_ID: id {entry_id!r} appears more than once "
                "across the hand and generated sections; a superseded entry and "
                "its replacement must never both sit on the board (O10 D3)"
            )
        seen_ids.add(entry_id)
    return entries


def _parse_timestamp(ts: str) -> datetime:
    ts = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        try:
            dt = datetime.fromisoformat(ts[:19]).replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise EntryError(f"unparseable timestamp {ts!r} in age source") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _entry_age_days(entry: dict, artifact_path: Path) -> float:
    age_source = entry.get("age_source", "mtime")
    if age_source == "mtime":
        mtime = artifact_path.stat().st_mtime
        generated_at = datetime.fromtimestamp(mtime, tz=timezone.utc)
    elif age_source == "embedded_comment":
        regex = entry.get("age_regex")
        if not regex:
            raise EntryError("age_source=embedded_comment requires 'age_regex'")
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
        match = re.search(regex, text)
        if not match:
            raise EntryError(f"age_regex found no match in {artifact_path}")
        generated_at = _parse_timestamp(match.group(1))
    else:
        raise EntryError(f"unknown age_source: {age_source!r}")
    age = datetime.now(timezone.utc) - generated_at
    return age.total_seconds() / 86400


def _check_live_count_probe(entry: dict, vault_root: Path, artifact_path: Path) -> list[str]:
    """Return mismatch descriptions. Empty list means no mismatch (or no probe configured)."""
    probe = entry.get("live_count_probe")
    if not probe:
        return []
    source_file = vault_root / probe["source_file"]
    if not source_file.exists():
        raise EntryError(f"live_count_probe source_file not found: {source_file}")
    try:
        source_data = json.loads(source_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EntryError(f"live_count_probe source_file invalid JSON: {source_file}: {exc}") from exc
    node: Any = source_data
    for key in probe.get("source_key_path", []):
        if not isinstance(node, dict) or key not in node:
            raise EntryError(f"live_count_probe source_key_path {key!r} not found in {source_file}")
        node = node[key]
    text = artifact_path.read_text(encoding="utf-8", errors="replace")
    mismatches: list[str] = []
    for label, source_field in probe.get("table_metric_map", {}).items():
        pattern = rf"\|\s*{re.escape(label)}\s*\|\s*(\d+)\s*\|"
        match = re.search(pattern, text)
        if not match:
            raise EntryError(f"live_count_probe metric row {label!r} not found in {artifact_path}")
        embedded_value = int(match.group(1))
        if not isinstance(node, dict) or source_field not in node:
            raise EntryError(
                f"live_count_probe source field {source_field!r} not found under source_key_path"
            )
        live_value = node[source_field]
        if embedded_value != live_value:
            mismatches.append(f"{label}: embedded={embedded_value} live={live_value}")
    return mismatches


def _normalize_for_compare(value: Any) -> str:
    """String-compare after int-normalize: 685 and '685' must compare equal."""
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return str(int(stripped))
        except ValueError:
            return stripped
    return str(value)


def _check_consistency_probe(entry: dict, vault_root: Path) -> Optional[str]:
    """Return a mismatch description, or None if the two extracted values agree
    (or no probe is configured). Raises EntryError on any extraction failure."""
    probe = entry.get("consistency_probe")
    if not probe:
        return None
    file_a = vault_root / probe["file_a"]
    file_b = vault_root / probe["file_b"]
    regex_a = probe["regex_a"]

    if not file_a.exists():
        raise EntryError(f"consistency_probe file_a not found: {file_a}")
    text_a = file_a.read_text(encoding="utf-8", errors="replace")
    match = re.search(regex_a, text_a)
    if not match:
        raise EntryError(f"consistency_probe regex_a found no match in {file_a}")
    value_a = match.group(1)

    if not file_b.exists():
        raise EntryError(f"consistency_probe file_b not found: {file_b}")
    try:
        data_b = json.loads(file_b.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EntryError(f"consistency_probe file_b invalid JSON: {file_b}: {exc}") from exc
    node: Any = data_b
    for key in probe.get("key_path_b", []):
        if not isinstance(node, dict) or key not in node:
            raise EntryError(f"consistency_probe key_path_b {key!r} not found in {file_b}")
        node = node[key]

    if _normalize_for_compare(value_a) != _normalize_for_compare(node):
        return f"file_a={value_a!r} file_b={node!r}"
    return None


def _check_citations_probe(entry: dict, vault_root: Path, artifact_path: Path) -> list[str]:
    """Return the list of cited paths that do not resolve on disk. Empty means every
    cited path resolves (or no probe is configured). Raises EntryError if the artifact
    is unreadable or the regex extracts nothing."""
    probe = entry.get("citations_probe")
    if not probe:
        return []
    path_regex = probe["path_regex"]
    try:
        text = artifact_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EntryError(f"citations_probe artifact unreadable: {artifact_path}: {exc}") from exc
    matches = re.findall(path_regex, text)
    if not matches:
        raise EntryError(f"citations_probe path_regex found no matches in {artifact_path}")
    missing: list[str] = []
    seen: set[str] = set()
    for raw in matches:
        candidate = raw.strip()
        if candidate in seen:
            continue
        seen.add(candidate)
        candidate_path = Path(candidate)
        resolved = candidate_path if candidate_path.is_absolute() else vault_root / candidate
        if not resolved.exists():
            missing.append(candidate)
    return missing


def _check_line_count_probe(entry: dict, artifact_path: Path) -> Optional[str]:
    """Return a violation description, or None when within bounds (or no probe).
    O10 D5(i): counts the artifact's lines against max_lines."""
    probe = entry.get("line_count_probe")
    if not probe:
        return None
    max_lines = probe["max_lines"]
    try:
        text = artifact_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise EntryError(f"line_count_probe artifact unreadable: {artifact_path}: {exc}") from exc
    count = len(text.splitlines())
    if count > max_lines:
        return f"line count {count} exceeds max {max_lines}"
    return None


def _check_dir_count_probe(entry: dict, vault_root: Path) -> Optional[str]:
    """Return a violation description, or None when the directory holds at least
    min_count files matching glob (or no probe). O10 D5(ii)."""
    probe = entry.get("dir_count_probe")
    if not probe:
        return None
    target = vault_root / probe["dir"]
    if not target.is_dir():
        raise EntryError(f"dir_count_probe dir not found: {target}")
    count = len([p for p in target.glob(probe["glob"]) if p.is_file()])
    min_count = probe["min_count"]
    if count < min_count:
        return (f"directory {probe['dir']} has {count} file(s) matching "
                f"{probe['glob']!r}, below min {min_count}")
    return None


def _check_provenance_count_probe(entry: dict, vault_root: Path,
                                   artifact_path: Path) -> Optional[str]:
    """Return a mismatch description, or None when the filtered row count in the
    source inventory equals the value at expected_key_path inside the ARTIFACT's
    own JSON (or no probe). O10 D5(iii): rationale-index's population check."""
    probe = entry.get("provenance_count_probe")
    if not probe:
        return None
    source_file = vault_root / probe["source_file"]
    if not source_file.exists():
        raise EntryError(f"provenance_count_probe source_file not found: {source_file}")
    try:
        source_data = json.loads(source_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EntryError(
            f"provenance_count_probe source_file invalid JSON: {source_file}: {exc}") from exc
    rows = source_data.get("rows")
    if not isinstance(rows, list):
        raise EntryError(f"provenance_count_probe source_file has no rows list: {source_file}")
    exact = set(probe.get("exact", []))
    prefixes = tuple(probe.get("prefixes", []))
    live_count = sum(
        1 for r in rows
        if isinstance(r, dict)
        and (str(r.get("provenance", "")) in exact
             or (prefixes and str(r.get("provenance", "")).startswith(prefixes)))
    )
    try:
        artifact_data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EntryError(
            f"provenance_count_probe artifact not readable JSON: {artifact_path}: {exc}") from exc
    node: Any = artifact_data
    for key in probe.get("expected_key_path", []):
        if not isinstance(node, dict) or key not in node:
            raise EntryError(
                f"provenance_count_probe expected_key_path {key!r} not found in {artifact_path}")
        node = node[key]
    if _normalize_for_compare(node) != _normalize_for_compare(live_count):
        return (f"provenance count mismatch: artifact expects {node!r}, "
                f"live filtered count is {live_count}")
    return None


def check_entry(entry: dict, vault_root: Path) -> EntryResult:
    """Evaluate one entry. Advisory downgrade (O10 D4): an entry flagged
    "advisory": true never fails the board; any non-PASS verdict it earns is
    rewritten to WARN with the original verdict preserved in the detail."""
    result = _check_entry_inner(entry, vault_root)
    if entry.get("advisory") and result.verdict != VERDICT_PASS:
        return EntryResult(
            result.id, result.artifact_path, VERDICT_WARN,
            f"advisory (downgraded from {result.verdict}): {result.detail}",
            result.rederive_command, age_days=result.age_days,
        )
    return result


def _check_entry_inner(entry: dict, vault_root: Path) -> EntryResult:
    entry_id = entry["id"]
    artifact_rel = entry["artifact_path"]
    artifact_path = vault_root / artifact_rel
    max_age_days = entry.get("max_age_days")
    rederive_command = entry["rederive_command"]

    if not artifact_path.exists():
        return EntryResult(entry_id, artifact_rel, VERDICT_ERROR,
                            f"artifact not found: {artifact_path}", rederive_command)

    age_days: Optional[float] = None
    if max_age_days is not None:
        try:
            age_days = _entry_age_days(entry, artifact_path)
        except EntryError as exc:
            return EntryResult(entry_id, artifact_rel, VERDICT_ERROR, str(exc), rederive_command)
        except OSError as exc:
            return EntryResult(entry_id, artifact_rel, VERDICT_ERROR,
                                f"age check failed: {exc}", rederive_command)

    try:
        mismatches = _check_live_count_probe(entry, vault_root, artifact_path)
    except EntryError as exc:
        return EntryResult(entry_id, artifact_rel, VERDICT_ERROR, str(exc),
                            rederive_command, age_days=age_days)

    try:
        consistency_mismatch = _check_consistency_probe(entry, vault_root)
    except EntryError as exc:
        return EntryResult(entry_id, artifact_rel, VERDICT_ERROR, str(exc),
                            rederive_command, age_days=age_days)

    try:
        missing_citations = _check_citations_probe(entry, vault_root, artifact_path)
    except EntryError as exc:
        return EntryResult(entry_id, artifact_rel, VERDICT_ERROR, str(exc),
                            rederive_command, age_days=age_days)

    try:
        line_count_violation = _check_line_count_probe(entry, artifact_path)
        dir_count_violation = _check_dir_count_probe(entry, vault_root)
        provenance_mismatch = _check_provenance_count_probe(entry, vault_root, artifact_path)
    except EntryError as exc:
        return EntryResult(entry_id, artifact_rel, VERDICT_ERROR, str(exc),
                            rederive_command, age_days=age_days)

    # Probe-specific verdicts take precedence over the generic age/live-count STALE
    # verdict: they name a more precise failure than "past max age".
    if consistency_mismatch:
        return EntryResult(entry_id, artifact_rel, VERDICT_DIVERGENT,
                            f"consistency mismatch: {consistency_mismatch}",
                            rederive_command, age_days=age_days)
    if missing_citations:
        return EntryResult(entry_id, artifact_rel, VERDICT_BROKEN_CITATION,
                            "citation(s) do not resolve: " + "; ".join(missing_citations),
                            rederive_command, age_days=age_days)

    reasons = []
    if age_days is not None and age_days > max_age_days:
        reasons.append(f"age {age_days:.1f}d exceeds max {max_age_days}d")
    if mismatches:
        reasons.append("live-count mismatch: " + "; ".join(mismatches))
    if line_count_violation:
        reasons.append(line_count_violation)
    if dir_count_violation:
        reasons.append(dir_count_violation)
    if provenance_mismatch:
        reasons.append(provenance_mismatch)

    if reasons:
        return EntryResult(entry_id, artifact_rel, VERDICT_STALE, "; ".join(reasons),
                            rederive_command, age_days=age_days)

    detail_parts = (
        [f"age {age_days:.1f}d within {max_age_days}d max"]
        if age_days is not None else ["no age check configured"]
    )
    if entry.get("live_count_probe"):
        detail_parts.append("live counts match")
    if entry.get("consistency_probe"):
        detail_parts.append("consistency probe match")
    if entry.get("citations_probe"):
        detail_parts.append("all citations resolve")
    if entry.get("line_count_probe"):
        detail_parts.append("line count within max")
    if entry.get("dir_count_probe"):
        detail_parts.append("directory count at or above min")
    if entry.get("provenance_count_probe"):
        detail_parts.append("provenance count matches")
    return EntryResult(entry_id, artifact_rel, VERDICT_PASS, "; ".join(detail_parts),
                        rederive_command, age_days=age_days)


def run_check(manifest_path: Path, vault_root: Path) -> list[EntryResult]:
    """Core entry point shared by both run modes. Raises ManifestError if the
    manifest itself cannot be trusted; never raises for a per-entry problem."""
    entries = load_manifest(manifest_path)
    return [check_entry(entry, vault_root) for entry in entries]


def render_table(results: list[EntryResult]) -> str:
    lines = ["Staleness Check Report", ""]
    width_id = max([len("id")] + [len(r.id) for r in results])
    width_verdict = max([len("verdict")] + [len(r.verdict) for r in results])
    header = f"{'id'.ljust(width_id)}  {'verdict'.ljust(width_verdict)}  detail"
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        lines.append(f"{r.id.ljust(width_id)}  {r.verdict.ljust(width_verdict)}  {r.detail}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the generalized staleness check against the manifest."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST,
                         help="Path to the manifest JSON (default: staleness-manifest.json next to this script).")
    parser.add_argument("--vault-root", type=Path, default=VAULT,
                         help="Vault root that artifact_path/source_file entries are relative to.")
    parser.add_argument("--json", action="store_true",
                         help="Emit JSON instead of a table (CLI mode only).")
    parser.add_argument("--hook", action="store_true",
                         help="SessionStart hook mode: swallow all errors, silent when everything "
                              "passes, exit 0 always.")
    return parser


def _run_cli_mode(args: argparse.Namespace) -> int:
    try:
        results = run_check(args.manifest, args.vault_root)
    except ManifestError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(render_table(results))

    # WARN is advisory by definition (O10 D4): it never enters the exit-2 set.
    if any(r.verdict not in (VERDICT_PASS, VERDICT_WARN) for r in results):
        return 2
    return 0


def _log_fire(decision, detail=None):
    """Telemetry record to hook-activity.jsonl via the shared helper. Never
    raises; added 2026-08-31 so the SessionStart control is measurable."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
        from _governance_logger import log_fire
        log_fire("staleness_check", decision=decision, detail=detail)
    except Exception:
        pass


def _run_hook_mode(args: argparse.Namespace) -> int:
    # Hook payload (session identity, event name) is not consumed by this checker,
    # so stdin is never read: reading it would risk blocking on an unclosed pipe
    # in contexts where nothing writes to or closes stdin (e.g. a bare manual
    # invocation, or an in-process test harness).
    try:
        results = run_check(args.manifest, args.vault_root)
    except Exception as exc:
        _log_fire("error", type(exc).__name__)
        return 0  # hook contract: never block, never crash a session

    not_passing = [r for r in results if r.verdict != VERDICT_PASS]
    if not not_passing:
        _log_fire("pass", f"{len(results)} entries all PASS")
        return 0
    _log_fire("warn", "; ".join(f"{r.id}:{r.verdict}" for r in not_passing))

    lines = ["[STALENESS] The following registered artifacts need attention:"]
    for r in not_passing:
        lines.append(f"- {r.id} ({r.verdict}): {r.detail} -> {r.rederive_command}")
    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "\n".join(lines),
        }
    }
    try:
        print(json.dumps(output))
    except Exception:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.hook:
        return _run_hook_mode(args)
    return _run_cli_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
