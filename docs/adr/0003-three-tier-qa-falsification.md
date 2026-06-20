# ADR-0003: Three-Tier QA as Falsification, Not Confirmation

**Status:** Accepted
**Date:** 2026-06-11

## Context and Problem Statement

Quality assurance in AI-agent workflows is structurally different from software testing: the agent can produce a confident, fluent "PASS" verdict without executing any test. A hook that checks for the presence of a "QA REPORT" text block does not verify that real tests were run. The framework needed a QA model that (a) distinguishes real execution from prose-only verdicts and (b) makes the boundary of what was tested explicit.

The `work-verification-check.py` hook closes the "filed QA report without running any tools" bypass at the enforcement layer. This is documented in [docs/architecture.md](../architecture.md) Three-Tier QA Model.

## Decision Drivers

- Popperian falsification: QA proves absence of *found* bugs, not absence of all bugs. A PASS means "could not break it."
- Three separate failure surfaces need different tools: per-task correctness, per-increment integration, per-milestone prompt behavior.
- The enforcement hook must verify real tool execution, not just report-text presence.

## Considered Options

1. **Three-tier model with mandatory Untested Surface**: per-task (`process-qa`), per-increment adversarial (`process-pentest`), per-milestone eval suite.
2. **Single-tier: QA report per task**: one process skill, one report format.
3. **Continuous testing only**: assertion suites run on every commit; no per-task QA gate.

## Decision Outcome

**Chosen option: three-tier model with mandatory Untested Surface.**

- **Tier 1 (`process-qa`):** every non-Quick task. Uses the 3a/3b/3c pattern: 3a: run the test (tool call), 3b: show raw output (quote before interpreting), 3c: judge PASS/FAIL based on specific output lines. "Looks correct" without quoting actual output is explicitly invalid evidence.
- **Tier 2 (`process-pentest`):** per-increment, adversarial. Boundary inputs, malformed data, regression checks, integration failures. Tier 1 is prerequisite.
- **Tier 3 (promptfoo or equivalent):** human-triggered, per-milestone. Tests prompts/components directly via assertion suites. Tier 2 is prerequisite.

Every report at every tier must declare **Untested Surface**: what was not tested and why.

**Consequences:**

- *Positive:* `work-verification-check.py` blocks QA reports filed with zero execution tools: bypass closed at the enforcement layer.
- *Positive:* Untested Surface makes the gap visible for human judgment (the irreducible Layer 4).
- *Positive:* tier separation matches the tools and cadence appropriate to each failure surface.
- *Negative:* three tiers add overhead; per-task QA on every small task risks ceremony outweighing value (mitigated by the Quick fast path).
- *Negative:* "could not break it" is not an absolute guarantee: the model's adversarial creativity is the ceiling.

## Pros and Cons of the Options

**Three-tier with Untested Surface**
- Pro: each tier catches what the others miss.
- Pro: Untested Surface forces explicit acknowledgment of gaps.
- Con: highest per-task overhead.

**Single-tier**
- Pro: simpler to explain and enforce.
- Con: no adversarial tier; integration failures go undetected until later.

**Continuous testing only**
- Pro: automated, no per-task overhead.
- Con: assertion suites test fixed cases; they do not test reasoning quality on novel tasks.
