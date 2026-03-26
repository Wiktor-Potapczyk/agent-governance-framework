---
name: ensemble
description: Run 4 parallel agents with different thinking lenses on a framing/design question. Produces a divergence map showing where lenses agree and disagree. Use when task-classifier outputs MECHANISM: Ensemble, user says "/ensemble", or a design/architecture decision needs multiple perspectives. NOT for reasoning tasks (use /verify), NOT for Quick tasks.
---

# Ensemble — Parallel Thinking Lenses

## When to Use

- User says `/ensemble` or "run ensemble on this"
- Task-classifier outputs MECHANISM: Ensemble or CoVe + Ensemble
- The question involves framing, design, architecture, or option comparison
- There is no single correct answer — value is in surfacing different perspectives

## NOT for

- Quick tasks — refuse and explain why
- Reasoning/logic/math — use `/verify` instead
- Factual lookups — use external sources

## Procedure

**You MUST use the Agent tool to spawn all 4 agents in a single message (one response with 4 Agent tool calls).** This is how Claude Code runs them in parallel. If you output text between agent calls or dispatch them one at a time, they run sequentially — defeating the purpose. Do not answer the lenses yourself inline.

### Step 1 — Frame the question

**Before writing the question, answer this first:**
> "What does the user want to explore?" (one sentence — no options, no proposed answers, no conclusions)

Then de-bias the question using these 5 steps:

1. **Problem** — State the problem in one sentence
2. **De-self** — Remove every reference to YOUR situation (project names, tool names, infrastructure, what you built)
3. **De-direction** — Remove words that imply an answer ("should we adopt X" → "what approaches exist for X")
4. **De-progress** — Remove progress framing ("what are we missing" → "what does X require")
5. **Stranger test** — Would someone with zero context about this conversation answer differently? If yes, strip more.

The question should name WHAT to think about but not WHAT to think. Do not include proposed options, orderings, or your own hypothesis. Do not add context paragraphs or examples to the agents — the question alone must be sufficient.

**Test before sending:** Does your question contain proposed answers, self-references, progress assumptions, or conclusions? If yes, rewrite it. A good ensemble question is under 20 words and states a problem, not a choice.

### Step 1.5 — Get user approval (MANDATORY)

Use the AskUserQuestion tool to present your derived question to the user before launching agents. Show:
- The EXPLORE sentence (what the user wants to explore)
- The derived ensemble question
- Options: "Launch with this question" / "I'll reframe it"

Do NOT dispatch agents until the user approves the question. If the user reframes, use their version.

### Step 2 — Dispatch 4 agents in parallel

Each agent gets: the question + its lens instructions + "Under 300 words. Be direct."

**Lens A — Reframing:**
> Apply Recursive Architectural Reframing. 4 checks: (1) Trap — are we solving the right problem? What assumption feels obvious but might be wrong? (2) Boundary — where does this system's responsibility start and end? (3) Reality — what's actually possible given the constraints? (4) Collapse — does this simplify to something we already have? Then propose your answer.

**Lens B — Decomposition:**
> Apply Mechanical Decomposition. Break this into sub-components, map dependencies, identify the critical path, and list risks per component. What are the real tradeoffs? Then propose your answer.

**Lens C — Stakeholder:**
> Apply Stakeholder Reality Tracing. Start from the end-user's experience and work backwards. What does the user actually need? What makes this feel like overhead vs value? What failure mode would make them stop using it? Then propose your answer.

**Lens D — Adversarial:**
> Challenge the premise of this question. What's wrong with asking it this way? What would a skeptic say? What's the strongest argument against the most obvious answer? What failure mode is everyone ignoring? Then state what you would do instead.

### Step 3 — Produce divergence map

After all 4 agents return, produce this format:

```
## Ensemble: [question]

**LENS A (reframe):** [one-line position]
**LENS B (decompose):** [one-line position]
**LENS C (stakeholder):** [one-line position]
**LENS D (adversarial):** [one-line position]

**DIVERGENCE:** [name the specific tension between lenses — what they disagree on and why]
**CONVERGENCE:** [what all lenses agree on, if anything]
**SHARPEST INSIGHT:** [the single most non-obvious finding from any lens]
```

If all 4 lenses reach the same conclusion, say so explicitly — the value was in confirming consensus.

### Step 4 — Verify key claims

Ensemble lenses reason but do not research. Their outputs are ungrounded hypotheses. Immediately after producing the divergence map, verify the key claims:

1. Extract the 2-3 most consequential claims from the divergence map (positions that would change the decision if wrong).
2. For each claim, check: is there evidence in the conversation, in vault files, or in prior research that supports or contradicts it?
3. If a claim is ungrounded (no evidence found), flag it: `[UNGROUNDED]`
4. If a claim contradicts known evidence, flag it: `[CONTRADICTED BY: source]`
5. If a claim is supported, flag it: `[SUPPORTED BY: source]`
6. If a claim depends on data nobody has, flag it: `[NEEDS RESEARCH: what data is missing]`. Do not guess — the research team exists for this.

Add a `**GROUNDING CHECK:**` section to the divergence map output showing the verification results.

### Step 5 — Full outputs available on demand

Do not show full agent outputs by default. If the user asks for detail ("show me lens B", "expand on the adversarial"), then show that agent's full output.

For important questions, offer to save the divergence map to a work file.

<!--
Evidence basis:
- Ensemble experiment (2026-03-20): 5 tasks × 3 lenses, 35% avg overlap. Genuine divergence confirmed.
- Debate debunked: <20% win rate over CoT (2025). Blind parallel > debate.
- SelfOrg 2026: strong models gain nothing from debate. Blind independence is key.
- Lu et al. 2025: cross-family > intra-family, but prompt diversity works for framing tasks.
- Adversarial lens catches unique risks other lenses miss consistently.
-->
