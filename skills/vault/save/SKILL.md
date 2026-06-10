---
name: save
description: "Save current session state to vault. Use when the user says /save, asks to checkpoint, or wants to persist progress before ending a session."
---

Checkpoint the current session. Save progress to vault files so future sessions can resume seamlessly.

## Steps

### 1. Identify the active project

Glob for `Projects/*/STATE.md`. Determine which project this session relates to from conversation context. If ambiguous, ask the user.

### 2. Update STATE.md

Read the current STATE.md. Rewrite it with updated content, preserving the existing structure.

**Frontmatter fields to write:**

```yaml
date: YYYY-MM-DD       # original creation date — preserve from existing
updated: YYYY-MM-DD    # today's date
last_action: "..."     # one-line summary of what was accomplished, ≤120 chars
tags: #state           # preserve existing tags
status: "#active"      # or #blocked, #waiting, #done
milestone: "..."       # current milestone name (if applicable)
```

**Body sections** (write only sections that have content):

| Section | What goes here |
|---|---|
| `## Status` | One-paragraph current state (2-3 lines max) |
| `## Active Milestone` | Current milestone name + what done looks like (optional) |
| `## Built` / `## Built This Epoch` | Cumulative completed items. **Never delete existing items** — append new ones. |
| `## Next` | Strategic next steps (1-5 items). WHAT, not HOW. |
| `## Blocked` | Active blockers with dates. "None" if clear. |
| `## Recent Decisions` | Decisions made this epoch. Format: `YYYY-MM-DD — decision — rationale`. Prune entries >14 days old. |
| `## Work Files` | One-line index of active work files. Maintained by /maintain — preserve if present. |

**Rules:**
- Be concise. Target ≤60 lines but don't truncate important content to hit a number.
- Merge new info into existing content. Do not lose previously recorded items.
- If STATE.md has non-standard sections (On Watch, Background Tasks, Key Findings), preserve them unless the user says to restructure.

### 3. Update PROJECT.md (if it exists)

Check if `Projects/[Name]/PROJECT.md` exists.

**If it exists:**
- Promote completed milestones from STATE.md `## Built This Epoch` to PROJECT.md `## Built`
- Promote constitutional decisions (>14 days old or explicitly architectural) from STATE.md `## Recent Decisions` to PROJECT.md `## Decisions`
- Update `last_updated` frontmatter field

**If it does not exist:** Skip. PROJECT.md is optional until created during migration.

### 4. Update task_plan.md (if it exists)

Check if `Projects/[Name]/task_plan.md` exists.

**If it exists:**
- Mark completed steps as `[x]`
- If all steps are done, update `status` frontmatter to `#done`
- Do NOT delete task_plan.md — the user or next session handles cleanup

**If it does not exist:** Skip.

### 5. Save reusable knowledge to memory

Review the conversation for reusable knowledge: API quirks, tool gotchas, architectural decisions, user preferences, project context that future sessions need.

**Memory path:** The memory directory path from MEMORY.md (typically `.claude/projects/<vault-project-id>/memory/`)

For each piece of knowledge worth persisting:

1. Check existing memory files at the memory path — update if topic overlaps, otherwise create new.
2. **Always read a file before overwriting it.**
3. Write the memory file with frontmatter:

```markdown
---
name: <memory name>
description: <one-line description — be specific, this is used for relevance matching>
type: <user|feedback|project|reference|finding|hypothesis|decision>
confidence: <high|medium|low>
last_verified: <YYYY-MM-DD>
expires: <YYYY-MM-DD or null>
---

<memory content>
```

**Type selection:**
- `user` — role, goals, preferences, knowledge
- `feedback` — user corrections or confirmed approaches (never expires)
- `project` — ongoing work context (expires when project archives)
- `reference` — API quirks, tool behaviors, external facts (expires: 90 days for bugs/behaviors, 60 days for IDs/URLs)
- `finding` — empirically confirmed result (upgraded from hypothesis or observed directly)
- `hypothesis` — proposed but unverified claim (always `confidence: low` until tested)
- `decision` — architectural or process choice with rationale

**Confidence rubric:**
- `high` — confirmed across 2+ sessions, or empirically tested (hook ran, code executed, API returned expected result)
- `medium` — observed once with reasonable certainty, or from a single authoritative source. **Default for new memories.**
- `low` — inferred, hypothesized, or from indirect evidence. Single data point.

**Expiry rules:**
- `feedback`, `user`: `null` (never expires)
- `reference` (bugs/behaviors): 90 days from `last_verified`
- `reference` (IDs/URLs): 60 days from `last_verified`
- `project` (active): `null`; (archived project): archive immediately
- `finding`: `null` (empirically confirmed)
- `hypothesis`: 30 days (must be tested or archived)
- `decision`: `null` (decisions are permanent until explicitly reversed)

4. **Append to `memory-log.jsonl`** at the same memory path. One JSON line per action:

```json
{"ts": "2026-04-12T14:30:00", "action": "created", "file": "reference_foo.md", "reason": "Discovered during Awards build", "confidence": "medium"}
```

Valid actions: `created`, `updated`, `archived`, `verified`, `confidence_changed`, `rejected`, `corrected`.

- `rejected` — a memory proved wrong. Record what was wrong and why.
- `corrected` — a memory was updated to fix an error. Record what changed.
- `verified` — content was confirmed still accurate (resets `last_verified` date).

5. Update `MEMORY.md` at the same memory path. Keep it concise — one line per memory file with description.

Skip this step if nothing reusable was learned this session.

## Rules

- **Use built-in Read/Write/Edit tools** for all file operations. They work on the OneDrive path.
- **One topic per memory file** — keep memories focused and independently useful.
- **Never overwrite memory without reading first** — always read existing content and merge.
- **Don't duplicate** — check existing memories before creating new ones.
- **Report what you saved** — end with a short summary: which files written/updated, what was promoted, what knowledge was persisted.
