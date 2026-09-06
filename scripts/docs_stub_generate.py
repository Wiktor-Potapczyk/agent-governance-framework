r"""O19 page-stub generator: one Markdown page per asset-inventory row.

Spec of record: Projects/Agent-Governance-Research/work/2026-09-03-docs-program-plan.md
(O19 objective, sections 5 and 6). Build plan: Projects/Agent-Governance-Research/work/
2026-09-04-o19-stub-generator-plan.md (design decisions D1-D10). Page contract:
.claude/docs/harness/template.md and README.md (O18 scaffold, read-only here).

WHAT IT DOES
  Reads .claude/hooks/aggregates/asset-inventory.json and rationale-index.json,
  validates them (D4, all failures exit 2 before any write), renders one page per
  row at <out>/<kind>/<slug>.md, and writes the tree deterministically (D9:
  UTF-8 without BOM, LF newlines, sorted traversal, no wall-clock, no randomness;
  two runs over unchanged inputs produce a byte-identical tree).

SEED-OR-PRESERVE CONTRACT (D8 refinement of the template's preservation line)
  The GENERATED block is machine-owned and rewritten wholesale on every run.
  The PROSE block is hand-owned with one refinement: a WHY or HOW section whose
  current content is byte-equal to the pristine UNFILLED marker text this
  generator itself would emit for that row is machine-owned and may be re-seeded
  when a machine source exists (this is what lets O23 wire plugin WHY paragraphs
  into existing stubs by re-run). Any other PROSE content is preserved
  byte-identical. template.md states the unrefined rule; the refinement is
  recorded here and flagged in the O19 build record for owner visibility because
  the O18 files are read-only contracts in this build.

PLUGIN-LEVEL WHY (O23)
  When <out>/_plugin-why.json exists it maps each plugin name to
  {"why": <paragraph>, "upstream": <cache path or source repo>}. For every
  plugin-provenance row whose WHY section still holds the pristine
  UNFILLED-WHY marker, the WHY is seeded with the plugin-level paragraph plus
  the upstream pointer, labeled "(plugin-level WHY; per-component WHY declined
  by ruling)" (D8 seed-or-preserve: hand-edited WHY stays byte-identical).
  The plugin name derives from the provenance string: the last "/" segment of
  the text after "plugin:". A missing file means markers stay (backward
  compatible). A present file missing an entry for any row-owning plugin is a
  loud exit 2 naming the plugin. Vault-owned rows are never touched by this
  path.

CLI (D2)
  python docs_stub_generate.py [--inventory PATH] [--rationale PATH]
      [--out DIR] [--kind KIND ...] [--dry-run]
  Exit 0 on success, exit 2 on any validation failure. --kind (repeatable)
  scopes writes to the listed kinds; --dry-run validates, reports, writes nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_INVENTORY = ".claude/hooks/aggregates/asset-inventory.json"
DEFAULT_RATIONALE = ".claude/hooks/aggregates/rationale-index.json"
DEFAULT_OUT = ".claude/docs/harness"

GEN_BEGIN = "<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->"
GEN_END = "<!-- GENERATED:END -->"
PROSE_BEGIN = "<!-- PROSE:BEGIN preserved byte-identical across regeneration -->"
PROSE_END = "<!-- PROSE:END -->"

UNFILLED_WHY = "UNFILLED-WHY (no machine source; tier policy in README.md)"

PLUGIN_WHY_FILENAME = "_plugin-why.json"
PLUGIN_WHY_LABEL = "(plugin-level WHY; per-component WHY declined by ruling)"

# D7 fixed sentinel vocabulary. Two cases, stated on every sentinel page:
# "no telemetry path exists" versus "instrumented, observed zero times".
SENTINEL_SENTENCES = {
    "NO_SOURCE_FOR_PLUGIN_SKILL": (
        "No telemetry path exists for this row: plugin skill invocations are not "
        "recorded in any harness sink (sentinel `NO_SOURCE_FOR_PLUGIN_SKILL`)."
    ),
    "NO_SOURCE_FOR_PLUGIN_HOOK": (
        "No telemetry path exists for this row: plugin hook fires are not "
        "recorded in any harness sink (sentinel `NO_SOURCE_FOR_PLUGIN_HOOK`)."
    ),
    "UNRESOLVED_REGISTRATION": (
        "No telemetry path exists for this row: the registration does not "
        "resolve to a trackable component (sentinel `UNRESOLVED_REGISTRATION`)."
    ),
    "NO_SOURCE_FOR_UNRESOLVED_PLUGIN_COMPONENT": (
        "No telemetry path exists for this row: the registry entry does not "
        "resolve to an installed plugin component "
        "(sentinel `NO_SOURCE_FOR_UNRESOLVED_PLUGIN_COMPONENT`)."
    ),
    "AWAITING_FIRST_OBSERVATION": (
        "Instrumented, observed zero times: a telemetry path exists and has "
        "recorded no use yet; runs from before the identity plumbing landed are "
        "excluded from this count (sentinel `AWAITING_FIRST_OBSERVATION`)."
    ),
}

_MCP_DETAIL = re.compile(r"^server='([^']*)'; command='(.*)'$")
_HOOK_DETAIL = re.compile(r"^event=(\S+) matcher=(\S+) command='(.*)'$")


class ValidationError(Exception):
    """Raised on any D4 validation failure; main() maps it to exit 2."""


# ------------------------------------------------------------------ helpers


def slugify(name):
    """D5 slug contract: lowercase, collapse non-[a-z0-9] runs to one hyphen,
    trim leading/trailing hyphens, empty result becomes 'unnamed'."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return slug or "unnamed"


def _is_owned(row):
    prov = row.get("provenance") or ""
    return prov == "authored-in-harness" or prov.startswith("junction:")


def _is_plugin(row):
    return (row.get("provenance") or "").startswith("plugin:")


def _plugin_name(row):
    """Derive the owning plugin's name from a 'plugin:' provenance string.
    'plugin:<marketplace>/<plugin>' yields the last '/' segment; a bare
    'plugin:<token>' (the BLK-004 registry-only rows) yields the token."""
    rest = (row.get("provenance") or "").split(":", 1)[1]
    return rest.split("/")[-1]


def _load_json(path, label):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise ValidationError(f"cannot read {label} at {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{label} at {path} is not valid JSON: {exc}") from exc


# --------------------------------------------------------------- validation


def load_and_validate(inventory_path, rationale_path):
    """Load both inputs and run D4 checks (a)-(d). Returns (inv, rat, recon)."""
    inv = _load_json(inventory_path, "inventory")
    rat = _load_json(rationale_path, "rationale index")
    rows = inv.get("rows")
    if not isinstance(rows, list):
        raise ValidationError("inventory has no 'rows' list")

    # (a) total vs twin_summary
    twin_total = sum((inv.get("twin_summary") or {}).values())
    if len(rows) != twin_total:
        raise ValidationError(
            f"row count {len(rows)} != twin_summary sum {twin_total}"
        )

    # (b) per-kind plugin counts vs plugin_cache_enumeration.row_counts
    row_counts = (inv.get("plugin_cache_enumeration") or {}).get("row_counts")
    if not isinstance(row_counts, dict):
        raise ValidationError("inventory has no plugin_cache_enumeration.row_counts")
    plugin_by_kind = Counter(r["kind"] for r in rows if _is_plugin(r))
    for kind in ("agent", "hook", "mcp-server"):
        expected = row_counts.get(kind)
        if plugin_by_kind.get(kind, 0) != expected:
            raise ValidationError(
                f"plugin {kind} rows {plugin_by_kind.get(kind, 0)} != "
                f"plugin_cache_enumeration.row_counts[{kind!r}] {expected}"
            )
    if "blk004_unresolved_registry_entries" not in row_counts:
        raise ValidationError(
            "plugin_cache_enumeration.row_counts lacks the "
            "'blk004_unresolved_registry_entries' term; the skill "
            "reconciliation cannot close"
        )
    cache_skill = row_counts.get("skill", 0)
    blk004 = row_counts["blk004_unresolved_registry_entries"]
    plugin_skill = plugin_by_kind.get("skill", 0)
    if plugin_skill != cache_skill + blk004:
        raise ValidationError(
            f"plugin skill rows {plugin_skill} != cache-enumerated {cache_skill} "
            f"+ BLK-004 registry-only {blk004}"
        )
    owned_skill = sum(1 for r in rows if r["kind"] == "skill" and _is_owned(r))
    total_skill = sum(1 for r in rows if r["kind"] == "skill")
    recon = (
        f"skill: {cache_skill} cache-enumerated + {blk004} BLK-004 registry-only "
        f"= {plugin_skill} plugin + {owned_skill} vault-owned = {total_skill} total"
    )
    if plugin_skill + owned_skill != total_skill:
        raise ValidationError(f"skill reconciliation does not close: {recon}")

    # (c) owned rows join 1:1 with rationale rows on (kind, name)
    owned_keys = {(r["kind"], r["name"]) for r in rows if _is_owned(r)}
    rat_keys = {(r["kind"], r["name"]) for r in rat.get("rows", [])}
    missing = owned_keys - rat_keys
    extra = rat_keys - owned_keys
    if missing or extra:
        raise ValidationError(
            f"rationale join gap: {len(missing)} owned rows unmatched "
            f"{sorted(missing)[:3]}, {len(extra)} rationale rows unmatched "
            f"{sorted(extra)[:3]}"
        )

    # (d) stamp alignment
    inv_stamp = inv.get("generated_at")
    rat_stamp = rat.get("source_asset_inventory_generated_at")
    if inv_stamp != rat_stamp:
        raise ValidationError(
            f"stamp drift: inventory generated_at {inv_stamp!r} != rationale "
            f"source_asset_inventory_generated_at {rat_stamp!r}"
        )

    return inv, rat, recon


def load_plugin_why(out_dir, rows):
    """Load <out>/_plugin-why.json when present (O23 plugin-level WHY).

    Returns None when the file is absent: markers stay, backward compatible.
    When present, validates the shape (a JSON object mapping plugin name to
    an object with non-empty string 'why' and 'upstream') and requires an
    entry for every plugin that owns at least one plugin-provenance row in
    the FULL population; any gap raises ValidationError (exit 2) naming the
    plugin, before a single byte is written."""
    path = Path(out_dir) / PLUGIN_WHY_FILENAME
    if not path.exists():
        return None
    mapping = _load_json(path, "plugin WHY map")
    if not isinstance(mapping, dict):
        raise ValidationError(f"plugin WHY map at {path} is not a JSON object")
    for key, entry in mapping.items():
        if not isinstance(entry, dict):
            raise ValidationError(
                f"plugin WHY entry for {key!r} is not an object"
            )
        for field in ("why", "upstream"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    f"plugin WHY entry for {key!r} lacks a non-empty "
                    f"{field!r} string"
                )
    needed = Counter(_plugin_name(r) for r in rows if _is_plugin(r))
    missing = sorted(set(needed) - set(mapping))
    if missing:
        listed = ", ".join(f"'{n}' ({needed[n]} rows)" for n in missing)
        raise ValidationError(
            f"plugin WHY map at {path} has no entry for plugin {listed}"
        )
    return mapping


# ---------------------------------------------------------------- rendering


def _render_path(row):
    if row.get("path") is not None:
        return f"- **Path:** `{row['path']}`"
    codes = ", ".join(f"`{c}`" for c in row.get("blocked_reason") or [])
    if codes:
        return f"- **Path:** (none recorded; unresolved registry entry, blocked: {codes})"
    return "- **Path:** (none recorded)"


def _render_reachability(row):
    entries = row.get("reachability") or []
    if not entries:
        codes = ", ".join(f"`{c}`" for c in row.get("blocked_reason") or [])
        if codes:
            return f"- **Reachability:** none recorded; blocked: {codes}"
        return "- **Reachability:** none recorded"
    seen = []
    for e in entries:
        pair = (e.get("type"), e.get("source_file"))
        if pair not in seen:
            seen.append(pair)
    joined = ", ".join(f"`{t}` ({s})" for t, s in seen)
    return f"- **Reachability:** {joined}"


def _render_usage(row):
    usage = row.get("usage") or {}
    source = usage.get("source") or ""
    parts = []
    if source in SENTINEL_SENTENCES:
        parts.append(SENTINEL_SENTENCES[source])
    else:
        parts.append(
            f"Recorded use count {usage.get('total_count')} (source: `{source}`)."
        )
        if usage.get("first_seen") or usage.get("last_seen"):
            parts.append(
                f"First seen {usage.get('first_seen')}; "
                f"last seen {usage.get('last_seen')}."
            )
        if "days_since_last_use" in usage or "dormant" in usage:
            parts.append(
                f"Days since last use: {usage.get('days_since_last_use')}; "
                f"dormant: {json.dumps(usage.get('dormant'))}."
            )
        if "writer_fire_count_sum" in usage:
            parts.append(
                f"Writer fire count sum: {usage['writer_fire_count_sum']} "
                f"(source: `{usage.get('writer_fire_count_source')}`)."
            )
    if usage.get("note"):
        parts.append(f"Note: {usage['note']}")
    return "- **Usage:** " + " ".join(parts)


def _render_edges(row):
    edges = row.get("edges") or []
    if not edges:
        return "- **Edges:** (no edges recorded)"
    lines = ["- **Edges:**"]
    for e in edges:
        line = f"  - {e.get('direction')} {e.get('relation')} {e.get('counterpart')}"
        if e.get("status") == "unresolved_prose_only":
            line += " [unresolved: prose mention only]"
        lines.append(line)
    return "\n".join(lines)


def _render_twin_state(row):
    state = row.get("twin_state")
    return f"- **Twin state:** {state if state is not None else '(none)'}"


def _pristine_why(row):
    """The UNFILLED-WHY marker this generator emits when no machine source exists."""
    return UNFILLED_WHY


def _pristine_how(row):
    """The UNFILLED-HOW marker variant this generator emits for the row (D6/D8)."""
    if row.get("path") is None:
        codes = ", ".join(f"`{c}`" for c in row.get("blocked_reason") or [])
        suffix = (
            "; no upstream source recorded; unresolved registry entry, "
            f"blocked: {codes}" if codes else "; no upstream source recorded"
        )
        return f"UNFILLED-HOW (see tier policy in README.md{suffix})"
    if _is_plugin(row):
        return (
            "UNFILLED-HOW (see tier policy in README.md; plugin-internal "
            f"mechanism, upstream source at `{row['path']}`)"
        )
    return "UNFILLED-HOW (see tier policy in README.md)"


def _seed_why(row, rationale_row, plugin_why=None):
    """WHY content: the plugin-level paragraph for plugin rows when
    _plugin-why.json is loaded, the rationale excerpt for EXTRACTED owned
    rows, the pristine marker otherwise. Vault-owned rows never take the
    plugin path (_is_plugin gates it)."""
    if plugin_why is not None and _is_plugin(row):
        entry = plugin_why.get(_plugin_name(row))
        if entry is not None:
            return (
                f"{entry['why']}\n\n"
                f"Upstream: `{entry['upstream']}`\n\n"
                f"{PLUGIN_WHY_LABEL}"
            )
    if (
        rationale_row
        and rationale_row.get("extraction_status") == "EXTRACTED"
        and rationale_row.get("rationale")
    ):
        locus = rationale_row.get("extraction_locus")
        return (
            f"{rationale_row['rationale']}\n\n"
            f"(machine-filled from rationale-index.json; extraction locus: {locus})"
        )
    return _pristine_why(row)


def _seed_how(row):
    """HOW content: template-derived sentence for settings-registrations, marker otherwise."""
    if row.get("kind") == "settings-registration":
        evd = next(
            (e for e in row.get("reachability") or [] if e.get("type") == "EVD-009"),
            None,
        )
        if evd is not None:
            detail = evd.get("detail") or ""
            lead = (
                f"This registration is declared in `{row.get('path')}` "
                f"({evd.get('source_file')})."
            )
            m = _MCP_DETAIL.match(detail)
            if m:
                body = (
                    f"It declares MCP server `{m.group(1)}` with launch "
                    f"command `{m.group(2)}`."
                )
            else:
                m = _HOOK_DETAIL.match(detail)
                if m:
                    body = (
                        f"It registers hook event `{m.group(1)}` "
                        f"(matcher: {m.group(2)}) with command `{m.group(3)}`."
                    )
                else:
                    body = f"Registration detail: `{detail}`."
            return (
                f"{lead} {body}\n\n"
                "(template-derived from the registration's reachability "
                "detail; not hand prose)"
            )
    return _pristine_how(row)


def render_page(row, rationale_row, stamp, plugin_why=None):
    """Render a fresh page for the row per the template.md byte layout."""
    generated = "\n".join(
        [
            _render_path(row),
            f"- **Provenance:** {row.get('provenance')}",
            _render_reachability(row),
            _render_usage(row),
            _render_edges(row),
            _render_twin_state(row),
        ]
    )
    return (
        "---\n"
        f"component: {json.dumps(row['name'])}\n"
        f"kind: {json.dumps(row['kind'])}\n"
        f"source_inventory_generated_at: {json.dumps(stamp)}\n"
        "---\n"
        "\n"
        f"# {row['kind']}: {row['name']}\n"
        "\n"
        f"{GEN_BEGIN}\n"
        f"{generated}\n"
        f"{GEN_END}\n"
        "\n"
        f"{PROSE_BEGIN}\n"
        "## Why\n"
        "\n"
        f"{_seed_why(row, rationale_row, plugin_why)}\n"
        "\n"
        "## How\n"
        "\n"
        f"{_seed_how(row)}\n"
        f"{PROSE_END}\n"
    )


# ------------------------------------------------------------- merge logic


def split_blocks(text):
    """Split a page into its marker-delimited parts. Raises ValidationError on
    missing, duplicated, or out-of-order markers (D4 f)."""
    positions = []
    for marker in (GEN_BEGIN, GEN_END, PROSE_BEGIN, PROSE_END):
        first = text.find(marker)
        if first == -1:
            raise ValidationError(f"marker missing: {marker}")
        if text.find(marker, first + 1) != -1:
            raise ValidationError(f"marker duplicated: {marker}")
        positions.append(first)
    if positions != sorted(positions):
        raise ValidationError("markers out of order")
    gb, ge, pb, pe = positions
    return {
        "head": text[:gb],
        "generated": text[gb + len(GEN_BEGIN): ge],
        "between": text[ge + len(GEN_END): pb],
        "prose": text[pb + len(PROSE_BEGIN): pe],
        "tail": text[pe + len(PROSE_END):],
    }


_PROSE_SECTIONS = re.compile(
    r"^\n## Why\n\n(?P<why>.*?)\n\n## How\n\n(?P<how>.*)\n$", re.DOTALL
)


def merge_existing(fresh_text, existing_text, row, rationale_row, stamp, plugin_why=None):
    """Merge a fresh render with an existing page: GENERATED block, frontmatter,
    and H1 come from the fresh render; the PROSE block is preserved byte-identical
    except that a section byte-equal to its pristine UNFILLED marker is re-seeded
    (D8 seed-or-preserve)."""
    fresh = split_blocks(fresh_text)
    existing = split_blocks(existing_text)
    m = _PROSE_SECTIONS.match(existing["prose"])
    if m is None:
        prose = existing["prose"]  # unparseable sections: preserve wholesale
    else:
        why = m.group("why")
        how = m.group("how")
        if why == _pristine_why(row):
            why = _seed_why(row, rationale_row, plugin_why)
        if how == _pristine_how(row):
            how = _seed_how(row)
        prose = f"\n## Why\n\n{why}\n\n## How\n\n{how}\n"
    return (
        fresh["head"]
        + GEN_BEGIN
        + fresh["generated"]
        + GEN_END
        + fresh["between"]
        + PROSE_BEGIN
        + prose
        + PROSE_END
        + fresh["tail"]
    )


# ---------------------------------------------------------------- generate


def generate(inventory_path, rationale_path, out_dir, kinds=None, dry_run=False):
    """Two-phase all-or-nothing run (D3): phase 1 validates and renders every
    page in memory; phase 2 writes. Any failure raises ValidationError before
    a single byte lands on disk. Returns a report dict."""
    inv, rat, recon = load_and_validate(inventory_path, rationale_path)
    rows = inv["rows"]
    stamp = inv.get("generated_at")
    rat_by_key = {(r["kind"], r["name"]): r for r in rat.get("rows", [])}
    out = Path(out_dir)
    plugin_why = load_plugin_why(out, rows)

    # (e) slug pass over the full population, before any scoping
    by_slug = {}
    for row in rows:
        by_slug.setdefault((row["kind"], slugify(row["name"])), []).append(row["name"])
    collisions = {k: v for k, v in by_slug.items() if len(v) > 1}
    if collisions:
        raise ValidationError(f"slug collisions: {collisions}")

    # unknown --kind values fail loud (exit 2) instead of planning zero pages
    if kinds is not None:
        present = sorted({r["kind"] for r in rows})
        unknown = sorted(set(kinds) - set(present))
        if unknown:
            raise ValidationError(
                f"unknown --kind {', '.join(unknown)}: "
                f"valid kinds are {', '.join(present)}"
            )

    scoped = [r for r in rows if kinds is None or r["kind"] in kinds]
    scoped.sort(key=lambda r: (r["kind"], slugify(r["name"])))

    # phase 1: render everything in memory, including merges with existing pages
    planned = []
    for row in scoped:
        slug = slugify(row["name"])
        target = out / row["kind"] / f"{slug}.md"
        fresh = render_page(
            row, rat_by_key.get((row["kind"], row["name"])), stamp, plugin_why
        )
        if target.exists():
            try:
                existing = target.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ValidationError(f"cannot read existing page {target}: {exc}") from exc
            try:
                content = merge_existing(
                    fresh, existing, row,
                    rat_by_key.get((row["kind"], row["name"])), stamp, plugin_why,
                )
            except ValidationError as exc:
                raise ValidationError(f"{target}: {exc}") from exc
        else:
            content = fresh
        planned.append((target, content.encode("utf-8")))

    per_kind = Counter(r["kind"] for r in scoped)
    report = {
        "pages_planned": len(planned),
        "per_kind": dict(sorted(per_kind.items())),
        "reconciliation": recon,
        "dry_run": bool(dry_run),
        "written": 0,
        "unchanged": 0,
        "plugin_why_entries": None if plugin_why is None else len(plugin_why),
        "plugin_rows_joined": (
            None if plugin_why is None
            else sum(1 for r in rows if _is_plugin(r))
        ),
    }
    if dry_run:
        return report

    # phase 2: write (only files whose bytes differ; D9/D10)
    for target, data in planned:
        if target.exists() and target.read_bytes() == data:
            report["unchanged"] += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        report["written"] += 1
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="O19 page-stub generator (deterministic, stdlib-only)."
    )
    parser.add_argument("--inventory", default=DEFAULT_INVENTORY)
    parser.add_argument("--rationale", default=DEFAULT_RATIONALE)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--kind", action="append", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = generate(
            args.inventory, args.rationale, args.out,
            kinds=args.kind, dry_run=args.dry_run,
        )
    except ValidationError as exc:
        print(f"VALIDATION FAILURE: {exc}", file=sys.stderr)
        return 2
    print(report["reconciliation"])
    if report["plugin_why_entries"] is not None:
        print(
            f"plugin-why: {report['plugin_why_entries']} entries loaded; "
            f"{report['plugin_rows_joined']} plugin rows joined"
        )
    for kind, count in report["per_kind"].items():
        print(f"{kind}: {count} pages planned")
    if report["dry_run"]:
        print(f"DRY RUN: {report['pages_planned']} pages planned, zero writes")
    else:
        print(
            f"{report['pages_planned']} pages planned; "
            f"{report['written']} written, {report['unchanged']} unchanged"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
