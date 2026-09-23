# Harness Component Docs

## What this tree is

One prose page per harness component. The population is every row of `.claude/hooks/aggregates/asset-inventory.json`. The layout is one subdirectory per kind. Filenames come from the `(kind, name)` slug contract: lowercase the name, collapse each non-alphanumeric run to one hyphen, trim leading and trailing hyphens. The generator fails loud on any slug collision. Contract source: [[2026-09-03-docs-program-plan]], O19 design constraints.

At O18 this tree holds only `template.md` (the O19 page contract) and this README. The O19 generator writes the per-component pages.

## Tier policy

From [[2026-09-03-docs-program-plan]] section 6. Uniform depth across all rows is declined on the record.

- **Tier A, full depth: the 266 vault-owned rows.** WHY is machine-filled from `rationale-index.json`. HOW is hand prose for 177 rows (agents, hooks, mcp-servers, skills, telemetry-sinks, workflows). The 89 settings-registration rows get template-rendered HOW instead: their mechanism is the registration line itself (file, event, matcher, command), rendered as a sentence and labeled template-derived.
- **Tier B, stub depth: the 232 plugin rows.** Machine fields only, plus one plugin-level WHY paragraph per installed plugin, written once at O23 and wired into each of the plugin's component stubs. Per-component hand prose for plugin rows is declined.
- **The 175 sentinel-usage rows** are documented through rendered sentinel meaning, using the five-code vocabulary, never through prose invention. Each page states the difference between "no telemetry path exists" and "instrumented, observed zero times."

## GENERATED and PROSE block contract

Every page carries two marked blocks, as spelled in `template.md`:

- **GENERATED block**: regeneration rewrites it wholesale. Machine facts only.
- **PROSE block**: regeneration preserves it byte-identical. Hand prose lives here. `UNFILLED-WHY` and `UNFILLED-HOW` markers stand where no source exists yet; the O20-O23 batches replace them.

## Staleness registration

This tree is registered on the staleness board as hand entry `docs-harness-components`, advisory until O24, then enforcing. The refresh path is the O19 generator named in the entry's `rederive_command`.

> RULING LINE (O18, per O12 risk flag 3): the `docs-harness-components` manifest entry is a ruled governing change. Any WARN it produces on the live board during the O12 observation window (live through 2026-09-16) is a real ruled change, not an incident, and must not be ledger-classified as the board asserting something false.

## Provenance

- Plan of record: [[2026-09-03-docs-program-plan]] sections 5 (placement), 6 (tiers), 7 (objectives O18-O24).
- Evidence base: [[2026-09-03-docs-program-research]].
