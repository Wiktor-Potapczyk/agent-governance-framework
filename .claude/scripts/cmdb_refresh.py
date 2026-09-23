"""cmdb_refresh.py: deterministic generator for cmdb-vault-setup's enumerable block.

Owner-ruled 2026-08-31 ("shouldn't we do it with a script? i thought we dont
want to write any docs manually"): the wiki page's headline counts and hook
event coverage are enumerable content, so they are generated from the live
sources, never hand-typed. Everything outside the marked block is the dated
human synthesis and is never touched.

Determinism contract: the stamp inside the block is the INVENTORY's own
generated_at, never now(), so re-running against the same inputs is
byte-identical and --check is a real drift probe (exit 2 on drift, 0 when
current). Missing inputs fail loud at exit 2.

Sources read: asset-inventory.json (counts by kind and provenance),
settings.local.json (hooks wired per event). The page's frontmatter gains a
`type: generated` source entry for the inventory (no sha256, per the
volatile-files exemption ruled 2026-05-30).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_DIR", r"C:\Users\WiktorPotapczyk\Desktop\Vault"))
DEFAULT_PAGE = VAULT / "Resources" / "KB" / "cmdb-vault-setup.md"
DEFAULT_INVENTORY = VAULT / ".claude" / "hooks" / "aggregates" / "asset-inventory.json"
DEFAULT_SETTINGS = VAULT / ".claude" / "settings.local.json"

BLOCK_START = "<!-- GENERATED:cmdb-counts"
BLOCK_END = "<!-- /GENERATED:cmdb-counts -->"

KIND_ORDER = ("skill", "agent", "hook", "mcp-server", "workflow",
              "settings-registration", "telemetry-sink", "junction")


def _fail(msg: str) -> int:
    print(f"ERROR: {msg}")
    return 2


def render_block(inventory: dict, settings: dict, settings_absent: bool = False) -> str:
    stamp = inventory.get("generated_at")
    if not stamp:
        raise ValueError("inventory carries no generated_at stamp")
    rows = inventory.get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("inventory has no rows; refusing to render a zero table")

    per_kind: dict[str, Counter] = {}
    for r in rows:
        kind = str(r.get("kind"))
        prov = str(r.get("provenance", ""))
        if prov.startswith(("authored-in-harness", "junction")):
            bucket = "vault"
        elif prov.startswith("plugin"):
            bucket = "plugin"
        else:
            # Fail loud on schema drift (architect finding 2026-08-31): a new
            # provenance family must extend this classifier, never be silently
            # counted as plugin-sourced.
            raise ValueError(f"unrecognized provenance {prov!r} on kind "
                             f"{kind!r}; refusing to guess a bucket")
        per_kind.setdefault(kind, Counter())[bucket] += 1

    lines = [
        f"{BLOCK_START} by .claude/scripts/cmdb_refresh.py from "
        f"asset-inventory.json generated_at {stamp} -->",
        "## Headline numbers (generated)",
        "",
        f"Counts regenerated from the live asset inventory "
        f"(`asset-inventory.json`, generated_at {stamp}); rerun "
        f"`python .claude/scripts/cmdb_refresh.py` after an inventory "
        f"regeneration. Sections below the marker are the dated human "
        f"synthesis and are historical, not regenerated.",
        "",
        "| Kind | Total | Vault-owned | Plugin-sourced |",
        "|---|---|---|---|",
    ]
    seen = set()
    for kind in KIND_ORDER:
        if kind in per_kind:
            c = per_kind[kind]
            lines.append(f"| {kind} | {c['vault'] + c['plugin']} | "
                         f"{c['vault']} | {c['plugin']} |")
            seen.add(kind)
    for kind in sorted(set(per_kind) - seen):
        c = per_kind[kind]
        lines.append(f"| {kind} | {c['vault'] + c['plugin']} | "
                     f"{c['vault']} | {c['plugin']} |")
    total = sum(sum(c.values()) for c in per_kind.values())
    lines.append(f"| **total** | {total} | "
                 f"{sum(c['vault'] for c in per_kind.values())} | "
                 f"{sum(c['plugin'] for c in per_kind.values())} |")

    lines += ["", "## Hook event coverage (generated)", ""]
    if settings_absent:
        # TASK-004 (migration plan Phase 1): settings.local.json is gitignored
        # and legitimately absent on a fresh clone / CI runner. Degrade to a
        # zero-row table rather than aborting -- the plugin-cache precedent
        # in asset_inventory.py's load_installed_plugins_manifest().
        lines.append(
            "_settings.local.json absent on this runner; hook event coverage "
            "not available (0 settings.local-sourced hook rows)._"
        )
        lines.append("")
    lines += ["| Event | Wired hooks |", "|---|---|"]
    events = settings.get("hooks", {})
    if not events and not settings_absent:
        raise ValueError("settings file declares no hooks; refusing to render")
    for event in sorted(events):
        n = sum(len(m.get("hooks", [])) for m in events[event])
        lines.append(f"| {event} | {n} |")
    lines.append(BLOCK_END)
    return "\n".join(lines)


def splice(page_text: str, block: str) -> str:
    if BLOCK_START in page_text:
        start = page_text.index(BLOCK_START)
        end = page_text.index(BLOCK_END) + len(BLOCK_END)
        return page_text[:start] + block + page_text[end:]
    # First run: replace from "## Headline numbers" up to (excluding) the next
    # section after "## Hook event coverage".
    m = re.search(r"^## Headline numbers$", page_text, re.M)
    if not m:
        raise ValueError("page has neither a generated block nor a "
                         "'## Headline numbers' section to replace")
    cov = re.search(r"^## Hook event coverage$", page_text, re.M)
    if not cov:
        raise ValueError("page lacks the '## Hook event coverage' section")
    after = re.search(r"^## ", page_text[cov.end():], re.M)
    end = cov.end() + (after.start() if after else len(page_text) - cov.end())
    return page_text[:m.start()] + block + "\n\n" + page_text[end:]


def ensure_generated_source(page_text: str, inventory_rel: str) -> str:
    # Scoped to THIS citation (architect finding 2026-08-31): gating on the
    # bare substring "type: generated" would silently skip the insert once any
    # OTHER generated source is cited on the page.
    entry = (f'  - path: "{inventory_rel}"\n'
             f"    type: generated\n")
    if entry in page_text:
        return page_text
    if f'"{inventory_rel}"' in page_text:
        raise ValueError(
            f"page already cites {inventory_rel} with a different source type; "
            "refusing to add a second citation for the same path")
    m = re.search(r"^source:\n((?:  .*\n)+)", page_text, re.M)
    if not m:
        raise ValueError("page frontmatter has no source: block to extend")
    return page_text[:m.end(1)] + entry + page_text[m.end(1):]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", type=Path, default=DEFAULT_PAGE)
    ap.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    ap.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    ap.add_argument("--check", action="store_true",
                    help="exit 2 if the page's block differs from a fresh render")
    args = ap.parse_args(argv)

    for path, name in ((args.page, "page"), (args.inventory, "inventory")):
        if not path.exists():
            return _fail(f"{name} not found at {path}")
    # TASK-004 (migration plan Phase 1): settings.local.json is gitignored, so
    # its absence on a fresh clone / CI runner is expected state, not a defect
    # -- degrade to a zero-hooks-row render instead of failing loud, matching
    # the precedent asset_inventory.py already uses for the plugin cache.
    settings_absent = not args.settings.exists()
    try:
        inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
        settings = ({"hooks": {}} if settings_absent
                    else json.loads(args.settings.read_text(encoding="utf-8")))
        page_text = args.page.read_text(encoding="utf-8")
        block = render_block(inventory, settings, settings_absent=settings_absent)
        new_text = splice(page_text, block)
        new_text = ensure_generated_source(
            new_text, ".claude/hooks/aggregates/asset-inventory.json")
    except (ValueError, json.JSONDecodeError) as exc:
        return _fail(str(exc))

    if args.check:
        if new_text != page_text:
            return _fail("cmdb page block is stale against the live inventory; "
                         "run cmdb_refresh.py to regenerate")
        print("cmdb page block is current")
        return 0

    if new_text != page_text:
        with io.open(args.page, "w", encoding="utf-8", newline="") as f:
            f.write(new_text)
        print(f"cmdb block regenerated (inventory {inventory.get('generated_at')})")
    else:
        print("cmdb block already current; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
