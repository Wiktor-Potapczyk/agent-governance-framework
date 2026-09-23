---
name: Ralph Loop Brainstorm Pattern
description: How to use Ralph Loop for multi-agent brainstorm sessions — state file design, agent routing, and n8n skill integration
type: project
---

## Ralph Loop for Multi-Agent Brainstorm

Successfully ran a 5-phase brainstorm loop (12 min, single iteration) that delegated to reviewer, prompt-engineer, and n8n skills.

### Pattern
1. **Loop prompt** reads a state file (BRAINSTORM-STATE.md) to find current step
2. **Agent routing table** maps each step to a specialist agent/skill
3. **Accumulated outputs** section in state file carries forward between steps
4. **Hard guardrail** prevents workflow modifications — read-only n8n access, documents only
5. State file uses frontmatter (`current_step`, `status`) + checkbox progress tracking

### What Worked
- Single iteration completed all 5 phases (Phase 0 steps ran in parallel)
- Reviewer caught 3 blocking issues in Phase 4 integration review — prompt-engineer fixed all 3
- n8n skills (node-configuration, code-javascript, validation-expert) caught Bridge Code compatibility and toolDescription issues

### What to Watch
- Ralph Loop plugin bash script still fails on Windows (`mkdir: command not found`) — use manual prompt paste instead
- PreToolUse/PostToolUse hook errors on OneDrive paths are non-blocking — files still write via Desktop Commander
