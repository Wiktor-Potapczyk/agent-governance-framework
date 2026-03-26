---
name: index
description: Check if a new thought/finding connects to existing research threads. Reads INDEX.md, compares against the new content, and suggests whether to update an existing thread or create a new one. Use when the user says "/index", "index this", "where does this fit", "check the index", or when promoting work from work/ to research/. Also use proactively after any substantive finding emerges in conversation.
---

# Index Check — Connect New Thoughts to Existing Threads

## Purpose

Implements the "sharpen or replace" discipline: every new finding either updates an existing research thread or starts a justified new one. Prevents unchecked accumulation.

## Procedure

### Step 1 — Read the INDEX

Read `Projects/Agent-Governance-Research/INDEX.md`. This is the living synthesis of all research threads.

If INDEX.md doesn't exist or is empty, tell the user and offer to create it.

### Step 2 — Identify the new content

The new content comes from one of:
- **User's message** — a thought or finding stated in conversation
- **A file argument** — user provides a path (e.g., `/index work/2026-03-25-some-finding.md`)
- **Recent conversation context** — the last substantive finding discussed

If a file path is provided, read it. Otherwise, extract the core claim from the conversation.

State the new content as a single sentence: **"NEW: [claim]"**

### Step 3 — Compare against each thread

For each thread in INDEX.md, ask:
- Does this new content **extend** this thread? (adds evidence, data, or nuance)
- Does this new content **contradict** something in this thread?
- Does this new content **depend on** this thread? (builds on it as a prerequisite)
- Is this new content **unrelated** to this thread?

### Step 4 — Output

```
## Index Check: [one-line summary of new content]

**Connections found:**
- Thread [N]: [thread name] — [EXTENDS/CONTRADICTS/DEPENDS ON]: [one sentence explaining the connection]
- Thread [M]: [thread name] — [relationship]: [explanation]
(list all connections, or "None — this is genuinely new")

**Recommendation:** [one of:]
- UPDATE thread [N]: [draft the specific text change to INDEX.md]
- NEW THREAD: [draft the new INDEX.md entry — 2-5 lines of current understanding + file pointers]
- DUPLICATE: this is already captured in thread [N], no action needed

**Promotion path:** [if applicable]
- File to promote: [path]
- Destination: research/ or eval/
- INDEX.md update: [the exact edit]
```

### Step 5 — Execute if approved

If the user approves, make the INDEX.md edit and file move. If not, do nothing.

## Rules

- Never create a new thread without checking all existing threads first
- New threads need justification — "this doesn't fit anywhere" is valid only after checking
- The INDEX entry must contain understanding (2-5 lines), not just a file pointer
- If the new content is too vague to index, say so — "this needs more development before indexing"
