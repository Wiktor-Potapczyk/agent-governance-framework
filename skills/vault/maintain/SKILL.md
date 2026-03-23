---
name: maintain
description: Clean up and organize a project's work files. Inventories work/ directory, reads each file to classify it (keep/archive/merge), executes moves, and updates STATE.md. Use when the user says "maintain", "clean up files", "organize work directory", "archive stale files", "file maintenance", or after a major project milestone when files have accumulated. Also trigger when the user says "/maintain" or "run maintenance".
---

# Project File Maintenance

**CRITICAL: Delegate the entire maintenance task to an agent.** File maintenance requires reading every file in the work directory, which trashes the main session context. Always spawn an agent to do the work — never read work files inline.

## How to invoke

1. Identify the active project (from conversation context, or ask the user)
2. Read the project's `STATE.md` (this one read is acceptable — it's small and needed for the delegation prompt)
3. Spawn an agent with the full instructions below

## Agent delegation prompt

Use the Agent tool with `subagent_type: "general-purpose"`. Include in the prompt:

- The project path (e.g., `Projects/[Name]/`)
- The current STATE.md content (paste it — the agent can't see our context)
- All classification rules and decision rules from below
- Instruction to present the classification table, execute moves, and update STATE.md
- Instruction to report back with a summary: files kept, archived, merged, deleted

## Instructions to include in the agent prompt

```
You are performing file maintenance on a project's work directory.

PROJECT PATH: [path]
STATE.md CONTENT: [paste current STATE.md]

TASK:
1. List all files in [project]/work/ with sizes and modification dates
2. Check if [project]/archive/ exists (create if not)
3. Read EVERY file — at minimum frontmatter + first 30 lines; read small files (<100 lines) entirely
4. Classify each file using these categories:

| Category | Criteria | Action |
|----------|----------|--------|
| KEEP | Actively referenced in STATE.md, contains findings still used, is a reusable tool/script, or is an entry point | Leave in work/ |
| ARCHIVE | Completed loop prompts, one-time scripts already applied, superseded plans/specs, intermediate artifacts captured elsewhere | Move to archive/ |
| MERGE | Two files cover same topic, one is primary, other adds detail | Merge into primary, archive secondary |
| DELETE | Empty files, duplicate copies, temporary debug output | Delete after confirming |

Decision rules:
- Referenced in STATE.md work files -> default KEEP unless clearly stale
- Loop prompt that already produced output -> ARCHIVE
- One-time script already run -> ARCHIVE
- Plan already executed -> ARCHIVE (decisions in STATE.md)
- Research findings -> KEEP (long shelf life reference)
- Test harnesses and reusable scripts -> KEEP
- When in doubt -> KEEP. Over-archiving is worse than messy.

5. Present classification table grouped by category:
   | File | Size | Category | Reason |

6. Execute: move ARCHIVE files, merge MERGE files, do NOT delete without confirmation

7. Update the Work Files section in STATE.md -- organize into logical groups (entry points, research, tools), include counts

8. Report summary: X kept, Y archived, Z merged. New file count in work/.
```

## After the agent returns

Review the agent's summary. If it looks correct, you're done. If the agent made questionable classifications, discuss with the user before accepting.

Do NOT re-read the files yourself to verify — trust the agent's classification unless the user flags something.
