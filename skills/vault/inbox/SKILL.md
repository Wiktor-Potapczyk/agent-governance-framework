---
name: inbox
description: Process all notes in the Inbox/ folder. Classify, tag, and move each note to the correct vault location according to CLAUDE.md rules. Use when the user says "process inbox", "sort inbox", or "/inbox".
disable-model-invocation: true
---

Process my inbox using the vault-keeper agent.

1. Read every file in `Inbox/`
2. For each note: classify it (Task, Idea, Meeting note, Research, Personal), add complete YAML frontmatter (date, tags, status), rename to kebab-case if needed, move it to the correct folder
3. Report what you moved and why — one line per note
4. If Inbox is empty, say so

Follow CLAUDE.md rules exactly. Never delete notes — move to Archives/ if unsure.
