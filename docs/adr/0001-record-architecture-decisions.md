# ADR-0001: Record Architecture Decisions

**Status:** Accepted
**Date:** 2026-06-11

## Context and Problem Statement

Significant, costly, or hard-to-reverse choices made during the development of this framework were not being recorded in a queryable, append-only form. Without a decision log, future maintainers must reconstruct *why* the framework is shaped the way it is from changelog entries, comments, and memory: all of which degrade over time.

## Decision Drivers

- Single-authority rule: the "why" behind any decision must live in exactly one place (per [docs/documentation-standard.md](../documentation-standard.md) §4).
- Append-only: reversed decisions generate a new superseding record; the original is never deleted.
- Public repo: the log must be legible to outside readers without private context.

## Considered Options

1. **MADR files in `docs/adr/`**: lightweight, text-based, well-supported format (adr.github.io/madr).
2. **Inline rationale in skill/hook files**: co-located with the artifact, but scattered and harder to query.
3. **Changelog-only**: already exists, but structured for change history, not decision rationale.

## Decision Outcome

**Chosen option: MADR files in `docs/adr/`.**

Every significant, costly, or hard-to-reverse choice produces one MADR file, numbered sequentially. A reversed decision gets a new superseding ADR; the old one's `Status` line updates to `Superseded by ADR-NNNN`.

**Consequences:**

- *Positive:* decision rationale is queryable in one place; future maintainers can distinguish settled-and-deliberate from incidental choices.
- *Positive:* the single-authority rule is satisfied: ADRs are the canonical "why" store; CLAUDE.md and skill files state the rule in force and link here.
- *Negative:* adds a maintenance obligation: every significant choice requires a new file.
- *Negative:* the boundary between "significant enough for an ADR" and "changelog-only" requires judgment.

## Pros and Cons of the Options

**MADR files in `docs/adr/`**
- Pro: established format with tooling support.
- Pro: numbering makes sequencing and supersession explicit.
- Con: one more file class to maintain.

**Inline rationale**
- Con: scattered across the repo; no single queryable location.
- Con: mixes "what it does" with "why we chose it": violates Diátaxis mode separation.

**Changelog-only**
- Con: changelog entries are change-scoped; rationale for rejected options has no home.
