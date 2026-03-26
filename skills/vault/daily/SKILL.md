---
name: daily
description: Create today's daily note in Daily Notes/ with tasks pulled from task_plan.md. Use when the user says "daily note", "create daily", or "/daily".
disable-model-invocation: true
---

Create today's daily note.

1. Check `Daily Notes/` — if today's note already exists, open it and report that
2. Read `task_plan.md` and pull all incomplete "In Progress" tasks
3. Create `Daily Notes/YYYY-MM-DD.md` using today's date with this structure:

```
---
date: YYYY-MM-DD
tags: #daily
status: active
---

# YYYY-MM-DD

## Tasks
(paste incomplete In Progress tasks from task_plan.md here)

## Log
- 

## Notes
- 

## End of Day
- [ ] Inbox processed
- [ ] task_plan.md updated
```

Report the filename created.
