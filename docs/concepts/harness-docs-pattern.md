# The bike-spec docs pattern: one page per harness component

Status: adopted 2026-09-04. Published 2026-09-06.

## The idea

When you buy a bike, the seller hands you its full specification: every component, its role, its geometry. A governance harness deserves the same. This pattern gives every component in the harness its own documentation page, generated from the asset inventory, so the count can never drift from reality.

The source installation ran this pattern over 498 components in two days. Every page now answers four questions: what the component is, why it exists, how it works, and what it connects to.

## The three generators

The pattern ships as three scripts in `scripts/`. Run them in this order.

1. `asset_inventory.py` writes one inventory row per component. It walks `hooks/`, `skills/`, `agents/`, `workflows/`, and the settings registrations. Each row carries name, kind, path, provenance, reachability, usage evidence, and edges.
2. `rationale_extract.py` builds the rationale index. It pulls each owned component's purpose text from commit history and doctrine files.
3. `docs_stub_generate.py` writes one page per inventory row, sharded by kind. The script fails loud on count or slug mismatch.

Each generated page holds two blocks. The GENERATED block carries the machine fields and is rewritten on every run. The protected PROSE block carries the hand-written purpose and mechanics, preserved byte-identical across regenerations. A pristine UNFILLED marker stays machine-owned: the generator may seed it, and a later run preserves any hand edit.

The generator is idempotent. A second run on an unchanged harness must report zero pages written. That property is the drift alarm: a nonzero second run means the harness changed under the docs.

## Staleness tooling

Two more scripts keep the tree honest over time.

- `staleness_manifest_generate.py` derives a manifest of freshness conditions (which generated artifact depends on which sources).
- `staleness_check.py` evaluates the manifest and reports each entry as fresh or stale. Entries can run advisory first and flip to enforcing later.

Point both at your harness root with the `VAULT_DIR` environment variable. All five scripts use the same variable.

## What this repo ships and what it does not

This repo ships the five scripts and this pattern page. It does not ship a generated tree: the 498 pages of the source installation describe that installation, not yours. Run the generators against your own harness to get your own tree.

## Known limits

- Usage counts come from the harness telemetry sinks. With no telemetry, pages still generate; the usage field reads zero.
- Plugin-provided components get a plugin-level WHY from a shared source file, not a per-component one.
- The prose layer is only as good as the hands that fill it. The generator guarantees coverage and freshness of the machine fields, never the quality of the WHY.
