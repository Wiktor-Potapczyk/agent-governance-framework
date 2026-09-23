---
name: Gemini Prompt Engineering Patterns
description: Patterns for writing prompts targeting Gemini 2.5 Flash Preview in n8n agent nodes
type: feedback
---

## Gemini-Specific Prompt Patterns (for n8n agents)

S1 agents run on Gemini 2.5 Flash Preview, not Claude. Key differences:

1. **Sandwich pattern**: Place critical rules at TOP and BOTTOM of prompt — Gemini weights later instructions higher and can "forget" middle sections
2. **Positive framing**: "Always set tier to null when..." not "Never guess tier" — Gemini handles positive instructions more reliably
3. **JSON enforcement**: "First character must be {, last character must be }" — Gemini sometimes adds markdown fences
4. **Tool budget as priority allocation**: Don't rely on self-counting — use priority tiers (P1: initial, P2: retry, P3: remaining) instead of exact counts
5. **maxIterations is the real cap**: n8n enforces this at node level — prompt budgets are advisory only
