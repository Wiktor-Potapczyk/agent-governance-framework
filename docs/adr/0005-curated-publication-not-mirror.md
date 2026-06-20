# ADR-0005: Curated Publication, Not a Direct Mirror

**Status:** Accepted
**Date:** 2026-06-11

## Context and Problem Statement

This framework is derived from a personal governance setup that includes domain-specific agents, private hook configurations, and personal CLAUDE.md content that cannot be published verbatim. Publishing the full private setup would not be useful to external adopters who have different domains, tools, and constraints.

The question is: what is the right publication model for a personal framework intended to be adopted and adapted by others?

## Decision Drivers

- Privacy constraint: personal configuration details, employer-specific content, and private API endpoints cannot ship in a public repository.
- Adoption intent: the framework's value is its patterns (hook architecture, skill format, three-tier QA), not the author's specific configurations.
- Count drift risk: artifact counts appear in multiple docs; without a single source of truth they diverge. The `.doc-consistency.json` manifest + CI gate is the mechanism that prevents this.

## Considered Options

1. **Curated subset with pinned counts in a manifest**: publish the domain-neutral core; pin all artifact counts in `.doc-consistency.json`; CI verifies manifest vs on-disk reality on every push.
2. **Full mirror with redaction**: publish everything, redact sensitive fields.
3. **Pattern documentation only**: publish docs and templates, no runnable artifacts.

## Decision Outcome

**Chosen option: curated subset with pinned counts in `.doc-consistency.json`.**

The repository ships:
- The domain-neutral governance core (hooks, core skills, governance agents).
- Domain-example artifacts (apify, n8n) as illustrative, not prescriptive.
- A CLAUDE.md template that adopters fill in for their own context.

All artifact counts are pinned in `.doc-consistency.json`. The CI workflow (`docs.yml`) verifies pinned numbers match on-disk reality on every push. Docs cite the manifest as the single source of truth and do not restate counts inline: per the single-source-of-truth rule in [docs/documentation-standard.md](../documentation-standard.md) §6.1.

**Consequences:**

- *Positive:* no private information in the public repository.
- *Positive:* the manifest + CI gate prevents count drift between docs and filesystem.
- *Positive:* the curated subset is more useful to adopters than a full mirror: they receive patterns, not configurations.
- *Negative:* the curated repo diverges from the private setup over time; the maintainer must decide what to publish per change.
- *Negative:* the "what to include" decision requires judgment per artifact class.

## Pros and Cons of the Options

**Curated subset with manifest**
- Pro: clean separation between private and public.
- Pro: machine-verifiable count consistency via CI.
- Con: sync overhead between private setup and public repo.

**Full mirror with redaction**
- Pro: minimal selection work upfront.
- Con: high risk of accidental leakage; redaction is error-prone and hard to audit.

**Pattern documentation only**
- Pro: zero leakage risk.
- Con: no runnable artifacts: adopters cannot install and use the framework; the value proposition is halved.
