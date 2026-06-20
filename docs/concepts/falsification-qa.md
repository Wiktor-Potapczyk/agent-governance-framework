# Falsification QA: What a PASS Actually Means

**Audience:** contributors and operators who want to understand the framework's approach to quality assurance and why it is structured the way it is.

**Mode:** Explanation (Diátaxis). This page explains *why* QA is framed as falsification. For *how* to run QA, see `process-qa` and `process-pentest` in [`docs/reference/skills.md`](../reference/skills.md). For the three-tier structure decision, see [ADR-0003](../adr/0003-three-tier-qa-falsification.md).

---

## The core claim: PASS means "could not break it"

Standard QA asks: "does it work?" Falsification QA asks: "can I find a way to break it?"

A PASS verdict in this framework means: **"using the available tools and test cases, I could not break it."** It does not mean "there are no bugs." This distinction matters for two reasons:

1. The model's adversarial creativity is the ceiling on what gets tested. Untested paths remain untested after any PASS.
2. A confident "PASS" verdict without real test execution is textually indistinguishable from a correct "PASS": which is why `work-verification-check.py` blocks QA reports filed with zero execution tools.

## The 3a/3b/3c execution pattern

Every Tier 1 QA report follows this pattern:

- **3a: Run the test:** an actual tool call (Bash, file read, API invocation). Not a description of what the test would do.
- **3b: Show raw output:** quote the actual output text before interpreting it. "Looks correct" without quoting specific output lines is explicitly invalid evidence.
- **3c: Judge PASS/FAIL:** based on specific output lines, not on reasoning from first principles about what the output should be.

This sequence prevents the failure mode where the model reasons about what the output *should* be rather than reporting what it *actually* is.

## Untested Surface is mandatory

Every QA and pentest report must explicitly name what was **not** tested and why. This is the **Untested Surface**.

Untested Surface is not an admission of failure: it is the correct epistemological position. It makes the gap visible for human judgment, which is the irreducible Layer 4 that no hook can replace. A report without Untested Surface implicitly claims complete coverage, which is never true.

## The three tiers

Three tiers address three different failure surfaces:

| Tier | When | What it tests | Skill |
|---|---|---|---|
| 1 | Per-task | Correctness of the specific task output | `process-qa` |
| 2 | Per-increment | Integration and adversarial resilience of the combined output | `process-pentest` |
| 3 | Per-milestone | Prompt and component behavior on assertion suites | promptfoo or equivalent |

Tier N is prerequisite for Tier N+1. A missing Tier 1 on any task makes the increment's pentest incomplete, because the pentest builds on what Tier 1 verified.

Tier 2 (pentest) extends the 3a/3b/3c pattern with a **3d: State the test** step before 3a: articulate what adversarial condition is being tested before executing it. This makes adversarial intent explicit upfront rather than reverse-engineered from results.

## Why enforcement is necessary

The `work-verification-check.py` Stop hook closes the "QA report without execution" bypass. Without this hook, a model could write a QA REPORT text block without invoking any execution tool: and a downstream check that only verified the block's presence would accept it.

The hook requires at least one execution tool use in the turn's tool-call history before accepting a QA REPORT. This is the runtime expression of the falsification principle: a PASS requires evidence of an attempt to break, not just a claim.

---

*Cross-references: [task-classification.md](task-classification.md) · [enforcement-layers.md](enforcement-layers.md) · [docs/architecture.md](../architecture.md) · [ADR-0003](../adr/0003-three-tier-qa-falsification.md)*
