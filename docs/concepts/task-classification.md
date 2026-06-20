# Why Classify Tasks Before Acting?

**Audience:** new adopters and contributors who want to understand why the classifier is mandatory, not optional.

**Mode:** Explanation (Diátaxis). This page explains *why* the framework shapes task entry the way it does. For *what* the classifier produces, see [`docs/reference/skills.md`](../reference/skills.md). For *how* the enforcement works at the hook layer, see [`enforcement-layers.md`](enforcement-layers.md).

---

## The core problem: confident answers before the problem is understood

A language model's default behavior is to extract a confident answer from a prompt as quickly as possible. For most prompts this is correct. For non-trivial tasks: ones that require investigation, involve multiple sub-components, or carry hidden depth beneath simple surface wording: this default produces wrong-direction work.

The empirical failure mode: the model starts building or analyzing based on what the prompt *seems* to say, rather than what it *implies*. By the time the actual depth is discovered, significant work has been done in the wrong direction.

Classification is the forcing function that breaks this pattern. Before any work begins, the classifier surfaces:

- **IMPLIES**: what the prompt means beneath the words (the depth analysis)
- **TASK TYPE**: which primitive(s) apply: Research, Analysis, Planning, Build, QA, or Quick
- **APPROACH**: compound mixture (percentage ratios across primitives)
- **MISSED**: blind spot check (what a pessimistic reader would say was overlooked)
- **MUST DISPATCH**: the enforcement contract (which agents and skills are required)

## Burden of proof on Quick

The classifier's default is to assume depth. The burden of proof is on **Quick**: a task must affirmatively demonstrate that it is a single-field edit, a one-sentence answer, or a zero-judgment operation before receiving the Quick fast path.

Ambiguity resolves to depth. "Rename X to Y" is Quick: the action names target and operation precisely. "How should I approach X?" is not Quick: the IMPLIES step routinely reveals compound structure beneath that surface.

**The Explicit Imperative fast path (Step 3a):** small explicit imperatives (`rename X to Y`, `move X to Y`, `fix typo in X`, `delete the unused X`, `add line W to file V`) flip the burden of proof and default to Quick. This is not a weakening of the burden-of-proof rule: it recognizes a class where ambiguity genuinely does not exist. The classifier auto-escalates back to depth only if a depth signal is also present (compound analysis ask, prior hypothesis, ambiguous target needing investigation). See [docs/architecture.md](../architecture.md) Layer 0 for the full condition set.

## Compound detection

Most non-trivial tasks are mixtures of primitives. A Build task that requires investigating the codebase first carries a Research compound. An Analysis task that will produce a plan carries a Planning compound. QA is mandatory for all non-Quick tasks: it is always a compound.

The compound ratios in the TASK TYPE output determine MUST DISPATCH: the list of agents and skills that must actually be invoked. This list is enforced at the Stop hook by `dispatch-compliance-check.py`: a task classified as "Build primary, QA compound" that does not invoke `process-qa` is blocked.

## Why enforcement, not judgment

The classifier's output is enforced, not advisory. `classifier-field-check.py` blocks the response if classification fields are missing, or if PM is absent from a non-Quick task's MUST DISPATCH list. Without the hook, the classifier runs but is easily bypassed: the compliance gap from ~90% back to ~25% empirically. See [enforcement-layers.md](enforcement-layers.md) for the full hook chain and [ADR-0002](../adr/0002-hooks-enforce-process-not-prompts.md) for the decision rationale.

---

*Cross-references: [enforcement-layers.md](enforcement-layers.md) · [falsification-qa.md](falsification-qa.md) · [docs/architecture.md](../architecture.md) · [ADR-0002](../adr/0002-hooks-enforce-process-not-prompts.md)*
