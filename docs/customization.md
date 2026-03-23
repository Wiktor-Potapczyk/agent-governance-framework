# Customization Guide

This framework is designed to be forked and adapted. Every component is replaceable.

## Agents

Agents in `agents/governance/` are generic and work for any project. Agents in `agents/domain-examples/` show how to build application-specific agents.

**To add your own agent:**

Create a `.md` file in your `.claude/agents/` directory:

```markdown
---
description: One-line description of what this agent does (MUST be single-line)
model: sonnet
---

Your system prompt here. This becomes the agent's system prompt when dispatched.
```

Key rules:
- Description MUST be a single line. Multi-line descriptions break agent discovery silently.
- The `model` field controls which Claude model the agent uses. Use `sonnet` for most agents to save tokens.
- Agent body content IS delivered as the system prompt.

## Skills

Skills in `skills/core/` implement the governance pipeline. Each skill is a directory containing a `SKILL.md` file.

**To customize the task classifier:**

Edit `skills/core/task-classifier/SKILL.md`. The key sections to customize:
- **Step 1.5 Domain Detection** table: add your own domains and specialist agents
- **Classification traps** table: add examples from your own workflow
- **Step 3 Quick Check**: adjust the criteria for what counts as Quick in your context

**To add domain-specific skills:**

Create a new directory under `skills/` with a `SKILL.md` file:

```markdown
---
description: When to trigger this skill
---

Skill content here. This is injected when the skill is invoked.
```

## Hooks

All hooks read JSON from stdin and write JSON to stdout. The framework uses three response patterns:

1. **Allow** (default): exit with no output or exit code 0
2. **Block**: output `{"decision": "block", "reason": "..."}`
3. **Inject context**: output `{"hookSpecificOutput": {"additionalContext": "..."}}`

**To add a new hook:**

1. Write a Python script that reads stdin JSON and outputs a response
2. Register it in `.claude/settings.local.json` under the appropriate event
3. Test with: `echo '{"prompt":"test"}' | python your-hook.py`

**Hook events available:**
- `PreToolUse` — before a tool is called (can block)
- `PostToolUse` — after a tool returns (can inject context)
- `Stop` — before the assistant's response is shown (can block)
- `SubagentStart` — when a subagent is spawned (can inject context)
- `SubagentStop` — when a subagent finishes (can block)
- `UserPromptSubmit` — when the user sends a message (can inject context)

## CLAUDE.md

The template `CLAUDE.md` in the repo root contains the governance philosophy and rules. Customize:

- **Owner line**: your name, role, tech stack
- **Directory Structure**: match your project layout
- **Agent Registry**: list your actual agents
- **Tool & Environment Quirks**: your specific environment

Keep the **CRITICAL RULE** sections intact — they encode the governance principles that make the hooks effective.

## Removing Components

The framework is modular. You can run subsets:

| Want | Keep |
|---|---|
| Just task classification | task-classifier skill + classifier-field-check hook |
| Classification + process routing | Above + process-* skills + skill-routing-check hook |
| Full governance | Everything |
| Monitoring only | governance-log hook (no blocking, just JSONL logging) |
