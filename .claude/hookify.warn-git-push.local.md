---
name: warn-git-push
enabled: true
event: bash
pattern: git\s+push
action: warn
---

**git push detected**

STOP and ask Wiktor "Want me to push?" before proceeding. Each push is a separate authorization — "yes" to a prior push does not authorize this one. Don't chain `git commit && git push`.

Source: `memory/feedback_no_push_without_asking.md`. Backfilled by L34 (2026-05-24).
