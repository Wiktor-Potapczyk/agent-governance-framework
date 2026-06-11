# ADR-0004: Routing-as-Code for the Procedure Layer (Pilot Direction)

**Status:** Pilot — not yet adopted
**Date:** 2026-06-09

## Context and Problem Statement

The framework's Layer 1 (Process Skills) is currently implemented as prose that the model is asked to follow. Prose instructions, like prompt-based enforcement, inherit below-100% step-compliance. The dispatch sequence — which agents run, in which order, with which typed handoffs — depends on the model executing the prose correctly.

Additionally, the current architecture triples the source of truth for each process skill: a prose SKILL.md, a machine-readable DISPATCHES.json sidecar, and enforcement hooks. These three can and do drift.

This direction is documented in [docs/architecture.md](../architecture.md) Layer 1 and the CHANGELOG entry for 2026-06-09.

## Decision Drivers

- Empirical verification: Claude Code workflow sub-agents have the full tool surface (shell, file-read, dynamic tool-loading, MCP) — the enabling capability exists and has been confirmed.
- Two worked conversion drafts exist (one routing-class, one execution-class) — the pattern is concrete, not aspirational.
- Adoption is gated on a human output-quality calibration baseline because dispatch-by-construction makes "did we dispatch?" tautological and useless as a success metric.

## Considered Options

1. **Convert process skills to deterministic routing workflow scripts** — each process skill becomes a script encoding which agents run, in what order, with typed handoffs and gates. Agents reason freely inside each step; routing is deterministic.
2. **Keep prose SKILL.md with hook enforcement** — current state; hooks enforce the dispatch contract after-the-fact.
3. **Full workflow-as-code (execution-class)** — agents also follow a scripted execution path, not just routing.

## Decision Outcome

**Chosen option: routing-class workflow scripts (pilot direction, not yet adopted).**

The active architectural direction is to convert each process skill into a deterministic workflow script that makes the dispatch sequence happen by construction — routing-as-code, not execution-as-code. The script encodes which agents run, in what order, with what typed handoffs and gates. Agents still reason freely inside each step.

The prose SKILL.md becomes the spec and human-readable fallback. The script is the authoritative runtime.

**Adoption gate:** a human output-quality calibration baseline must be established first. Until then, the current prose + hook architecture remains operative.

**Consequences:**

- *Positive:* collapses the prose/DISPATCHES.json/hook triplication into one executable source.
- *Positive:* dispatch correctness becomes a construction-time property, not a runtime measurement.
- *Negative:* the existing compliance-rate metric ("did we dispatch?") becomes tautological once routing is by-construction — a new quality metric is required.
- *Negative:* workflow scripts add a new artifact class to maintain.
- *Negative:* not yet adopted — pilot direction may be revised or abandoned based on calibration results.

## Pros and Cons of the Options

**Routing-class workflow scripts**
- Pro: dispatch is deterministic, not model-dependent.
- Pro: single source of truth replaces the current triplication.
- Con: requires calibration before adoption; adds maintenance surface.

**Prose + hook enforcement (current)**
- Pro: no new artifact class; already operational.
- Con: prose compliance below 100%; triplication of the dispatch contract creates drift risk.

**Full execution-class workflow**
- Pro: end-to-end determinism.
- Con: over-constrains agent reasoning inside steps; defeats the purpose of using a reasoning model for the substantive work.
