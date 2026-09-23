---
date: 2026-09-02
tags: [hooks, reference, vault]
status: active
paths:
  - "Inbox/**"
  - "Clippings/**"
---

# Inbox Processing Rules

Moved verbatim from vault-root CLAUDE.md (O16 trim, ruling row S4 of
[[2026-09-02-o16-row-rulings-merged]]). Enforcement is unchanged: the
`inbox-auto-ingest.py` PostToolUse hook fires on Inbox/ and Clippings/ writes
regardless of where this text lives; rules are context, hooks are enforcement.

## Inbox Processing Rules

1. **Task** — Extract actions, add to task_plan.md, move to Project
2. **Idea** — Tag #idea, move to Project or Areas/
3. **Meeting note** — Date, attendees, actions, move to Project
4. **Research** — Tag #research, move to Resources/ or Project
5. **Personal** — Move to Areas/Personal/
6. **Ingest (auto-fired by `inbox-auto-ingest.py` hook on Inbox/ writes; also manually invokable)** — After classify+route per Rules 1-5, invoke `process-ingest` skill to update wiki pages, `Resources/KB/index.md`, and `log.md` per Karpathy LLM-Wiki adoption (see section below). **Ingest cadence is input-driven, not calendar-driven** (Delta-4 of [[2026-05-25-agent-governance-architecture-v2]]): research-grade items in `Inbox/` or `Clippings/` (tagged `#research` or `#analysis`, OR any Clippings/ file) trigger ingest within 48 hours; operational vault-log items (TSB digests, daily notes) do NOT trigger ingest.

One line per inbox action: filename, classification, destination. (Folded in from the
retired CLAUDE.md Agent Rules heading, ruling row S23.)
