---
name: verify
description: CoVe-based step-level verification of reasoning. Invoke when asked to verify reasoning, when the user says "/verify" or "verify this", when task-classifier routes with MECHANISM: CoVe, or when Claude identifies medium/low confidence in its own reasoning steps.
---

# Verify — Step-Level Reasoning Verification

## When to Use

- User says `/verify` or "verify this"
- Task-classifier outputs MECHANISM: CoVe
- You identify medium or low confidence in any reasoning step
- Scope: reasoning, logic, factual claims, math

## NOT for

- Knowledge-dependent tasks (MMLU, GPQA-type) — use external sources instead
- Framing or design decisions — use ensemble for those
- Chaining: apply ONCE per response, never stack multiple rounds

## The Prompt

Apply this to your preceding reasoning now:

```
For each major reasoning step above:
1. Rate your confidence (high / medium / low).
2. For each step rated medium or low:
   a. State the step's core claim in one sentence.
   b. Without referencing your original reasoning, independently derive
      whether that claim holds. Show your work from first principles.
   c. If your independent derivation contradicts the original step,
      flag the contradiction explicitly and revise.
3. After all verifications, check whether any revision requires
   changes to downstream steps. Propagate if needed.
```

## ONE-ROUND LIMIT

Apply once. Do not re-run this skill on its own output. If still uncertain after one round: escalate to ensemble (parallel independent agents) or external verification.

## OUTPUT RULES

- If no issues found: state "No issues found." in one line. Do not elaborate on why the reasoning is sound. Do not praise the reasoning. Empty findings stay empty.
- If issues found: state each contradiction or unsupported assumption in one line with why it matters. No padding.
- If a step depends on data you don't have: flag it as `[NEEDS RESEARCH]` with what data is missing. Do not guess — say you don't know. The research team exists for this.

## Evidence Basis (non-normative)

<!--
- Step-level targeting: Lightman et al. (OpenAI 2023) — step-level > answer-level verification
- Confidence gating: SSR (Shi et al., Salesforce 2025) — selective refinement of low-confidence steps only
- Condition masking: ProCo (Wu et al., EMNLP 2024) — "without referencing original reasoning" forces genuine re-derivation, +6.8 to +14.1 accuracy gains across tasks
- One-round limit: Lu et al. (2025) — same-model verification degrades with repetition
- Propagation: SSR — downstream steps must be updated after any revision
-->
