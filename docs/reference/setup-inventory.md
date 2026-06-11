# Setup Inventory

A reference catalogue of every artifact class in this framework — what is installed and how it is organized. This is a **Reference**-mode document (per the [Documentation Standard](../documentation-standard.md)). It is the zoomed-out map; the per-artifact attributes tables live in [hooks.md](hooks.md), [agents.md](agents.md), and [skills.md](skills.md).

> Counts here mirror the values pinned in `.doc-consistency.json` and asserted in `docs/architecture.md` / `README.md` / `INSTALL.md` — that manifest is the single source of truth; this page cites it, it does not re-derive it.

## At a glance

| Asset class | Count | Location |
|---|---|---|
| Governance agents | 28 | `agents/governance/` |
| Domain-example agents | 2 | `agents/domain-examples/` |
| Top-level agents | 1 | `agents/` (`code-simplifier`) |
| Core skills | 17 | `skills/core/` |
| Vault-management skills | 7 | `skills/vault/` |
| Domain-example skills | 19 | `skills/domain-examples/` (apify, n8n) |
| Production hook files | 40 | `hooks/` |
| — of which active enforcement (registered) | 28 | `settings/` |
| Shared hook libraries | 4 | `hooks/` |
| Opt-in (disabled) hooks | 5 | `hooks/disabled/` |

## Agents (`agents/`)

The 28 governance agents span five working categories:

- **Core build/review:** blueprint-mode, debugger, architect-reviewer, adversarial-reviewer, implementation-plan, api-designer, data-engineer, code-simplifier, git-flow-manager.
- **AI / prompts:** llm-architect, prompt-engineer.
- **Research pipeline:** research-orchestrator, research-coordinator, research-analyst, technical-researcher, research-synthesizer, report-generator, query-clarifier.
- **Specialized:** api-security-audit, postgres-pro, nosql-specialist, powershell-7-expert, mcp-developer, mcp-server-architect, mcp-registry-navigator.
- **Productivity / PM:** vault-keeper, content-marketer, competitive-analyst, pm-orchestrator.

`agents/domain-examples/` carries worked domain agents (n8n) as adoption examples — they illustrate the pattern, they are not part of the governance core.

Each agent is a markdown definition with `name` / `description` / `tools` frontmatter and a body describing its dispatch contract and output format. See the [Documentation Standard §3c](../documentation-standard.md) for the reference template every agent entry should follow.

## Skills (`skills/`)

- **`core/` (17)** — the governance spine: `task-classifier` (routes every task), the `process-*` family (`process-research`, `process-analysis`, `process-build`, `process-planning`, `process-qa`, `process-pentest`, `process-postmortem`, `process-governance-mine`), plus `pm`, `verify`, `ensemble`, `verification-gated-research`, `architect-loop`, `doc-consistency`, `db-migration-plan`, `index`.
- **`vault/` (7)** — knowledge-management skills for an Obsidian-style vault: `daily`, `inbox`, `maintain`, `process-ingest`, `process-lint`, `save`, `standup`.
- **`domain-examples/` (19)** — apify and n8n skill packs, shipped as adoption examples of the skill format applied to a real domain.

Each skill is a `SKILL.md` with `name` + `description` frontmatter and a body of Use-when / Do-NOT-use-when / Steps. See [Documentation Standard §3b](../documentation-standard.md).

## Hooks (`hooks/`)

The repository ships 40 production hook files; **28** of them are *active enforcement* hooks registered in `settings/` (the figure pinned in the manifest), and the remainder are logging/lifecycle handlers and shared libraries. Hooks bind to Claude Code lifecycle events (PreToolUse, PostToolUse, Stop, SubagentStart/Stop, SessionStart/End, UserPromptSubmit, Pre/PostCompact). They divide into:

- **Classification & routing gates** — verify the task-classifier ran and that dispatch references resolve.
- **Dispatch-compliance gates** — verify that mandated agents/skills were actually invoked.
- **Quality & anti-fabrication gates** — work-verification, subagent-quality, bias-guard, prose linters.
- **Safety gates** — bash-safety-guard, config-protection, read-before-edit.
- **Logging & lifecycle** — governance-log, checkpoint, session-start orientation, compaction handlers.

`hooks/disabled/` holds 5 opt-in hooks that ship unregistered (copy to the active dir + register in settings to arm). Most production hooks have a paired `test_<hook>.py` — that test file is the authoritative enumeration of the hook's branches (per [Documentation Standard §3a](../documentation-standard.md)).

## How this inventory stays current

This page is regenerated as part of the documentation Definition-of-Done whenever artifacts are added or removed. The counts are validated by the `doc-consistency` checker against the manifest; the per-class organization is stable doctrine. The standard's §8 checklist is the maintenance contract.
