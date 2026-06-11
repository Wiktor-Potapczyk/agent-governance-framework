# ADR-0002: Hooks Enforce Process, Not Prompts

**Status:** Accepted
**Date:** 2026-06-11

## Context and Problem Statement

The framework's critical rules — classify before acting, QA every non-Quick task, dispatch declared agents — are stated as instructions in CLAUDE.md and process skill bodies. Empirical measurement shows that prompt-only enforcement achieves approximately 25% compliance on the target behaviors. The gap between stated intention and runtime behavior is large enough to undermine the framework's core purpose.

This finding is documented in [docs/architecture.md](../architecture.md) Design Principles and [README.md](../../README.md) under Architecture.

## Decision Drivers

- Compliance data: ~25% with prompts alone vs ~90% with hooks (empirically measured via the governance log).
- Hook infrastructure already exists (Claude Code's lifecycle event system); the incremental cost per rule is low once the harness is in place.
- Hooks are stateless Python scripts — no server, no database, no persistent process; low operational complexity.

## Considered Options

1. **Hooks for every critical rule** — each CRITICAL RULE has a corresponding enforcement hook that can block, warn, or inject context.
2. **Prompts only** — critical rules stated in CLAUDE.md; model follows or not.
3. **Hybrid: hooks for high-stakes rules, prompts for lower-stakes rules** — calibrate enforcement level per rule.

## Decision Outcome

**Chosen option: hooks for every critical rule.**

Every critical rule that is (a) rule-shaped, (b) regex-detectable, and (c) intended to fire at runtime gets a corresponding enforcement hook. The hook is the runtime enforcement; CLAUDE.md is the human-readable rationale and context. Both exist — they serve different functions.

**Consequences:**

- *Positive:* compliance rate rises from ~25% to ~90% on enforced behaviors.
- *Positive:* enforcement is visible, testable, and auditable via `hooks/test_*.py` test suites.
- *Negative:* hook proliferation risk — poorly scoped rules become false-positive sources; each block-class hook requires `test_fp_*` boundary guards.
- *Negative:* hooks can only enforce pattern-detectable properties; judgment calls (is this analysis thorough enough?) require a model-evaluated gate such as `epistemic-check.py`.

## Pros and Cons of the Options

**Hooks for every critical rule**
- Pro: measurable compliance improvement.
- Pro: enforcement is inspectable — read the hook source, run the tests.
- Con: requires ongoing maintenance as rules evolve.

**Prompts only**
- Pro: zero maintenance overhead beyond CLAUDE.md.
- Con: ~25% compliance empirically — insufficient for a governance framework.

**Hybrid**
- Pro: reduces hook surface for low-stakes rules.
- Con: the data shows prompts alone are unreliable even for salient, frequently-stated rules; the hybrid threshold is hard to calibrate without more data.
