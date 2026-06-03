# Agent Governance Framework for Claude Code

A deterministic, hook-driven governance framework for Claude Code (Anthropic's official CLI). It wraps the AI agent in four enforcement layers via Python hooks, raising complex task compliance from approximately 25% on prompt-only baselines to approximately 90%.

The framework operationalizes three research-backed principles: classify before acting, delegate specialist work to agents, and falsify rather than confirm. These principles are not left to the model's judgment -- they are enforced at runtime through hooks that can block, redirect, or inject context on every tool call and session boundary.

## Core Innovations

- **Exploration vs. Extraction routing** -- Tasks are classified not by surface keywords but by what they *imply*. The classifier distinguishes open-ended investigation (exploration) from directed retrieval (extraction) and routes each to a different process skill, preventing the model from converging prematurely on a confident answer before the problem space is understood.

- **Compound Task model** -- Every task is decomposed into a mixture of five primitives: Research, Analysis, Planning, Build, and QA. The classifier declares primary type and compound ratios. QA is mandatory for all non-Quick tasks and is enforced at the session Stop hook, not left as an optional step.

- **Popperian QA** -- Quality assurance is framed as falsification, not confirmation. A PASS means "could not break it." Every QA artifact must declare what was *not* tested (Untested Surface). Three tiers: per-task verification, per-increment adversarial pentest, and human-triggered eval suites.

## Architecture

The framework operates across five layers, with 28 active enforcement hooks (plus four shared libraries):

| Layer | What it does | Hook events |
|---|---|---|
| **Classifier** | Forces task classification on every non-trivial prompt; enforces all required fields (IMPLIES, TASK TYPE, APPROACH, MISSED); enforces PM in MUST DISPATCH for every non-Quick task | `UserPromptSubmit`, `Stop` (classifier-field-check) |
| **Process Skills** | Routes tasks to typed process flows (research, analysis, build, QA, planning); validates skill selection matches classifier output | `PreToolUse` (skill-routing-check), `PostToolUse` (skill-step-reminder) |
| **Agent Delegation** | Enforces MUST DISPATCH items from the classifier; injects behavioral governance into every subagent at spawn; quality-checks subagent output on exit | `SubagentStart`, `SubagentStop`, `Stop` (dispatch-compliance-check) |
| **Quality Enforcement** | Blocks QA/pentest reports filed with zero execution tools; blocks premature escalation to user with fewer than 3 tool uses; monitors zero-work non-Quick tasks | `Stop` (work-verification-check) |
| **Tool Safety** | Blocks dangerous Bash commands (rm -rf, force-push, credential exposure); monitors for unsupported citation patterns and dark-zone reasoning failures | `PreToolUse` (bash-safety-guard), `Stop` (dark-zone-check, process-step-check, governance-log) |

All hooks are stateless Python scripts that read from stdin and write to stdout. They require no database, no server, and no persistent process.

For a detailed technical walkthrough of the architecture, see [docs/architecture.md](docs/architecture.md).

## Repository Structure

```
framework-repo/
├── agents/
│   ├── governance/          # 29 specialist agents (research team, architect, QA, planning, etc.)
│   └── domain-examples/     # Placeholder for project-specific agent examples
├── hooks/
│   ├── user-prompt-submit.py        # Context bar + classifier enforcement on every message
│   ├── skill-routing-check.py       # PreToolUse: validates skill matches classifier TYPE
│   ├── bash-safety-guard.py         # PreToolUse: blocks dangerous shell commands
│   ├── skill-step-reminder.py       # PostToolUse: injects step reminders after skill loads
│   ├── subagent-governance.py       # SubagentStart: injects behavioral rules into subagents
│   ├── subagent-quality-check.py    # SubagentStop: checks for empty, error, or wall-of-text output
│   ├── classifier-field-check.py    # Stop: enforces all classifier output fields present
│   ├── dispatch-compliance-check.py # Stop: verifies MUST DISPATCH items were executed
│   ├── governance-log.py            # Stop: JSONL audit log of session governance events
│   ├── process-step-check.py        # Stop: L1 exit gate -- blocks missing SCOPE or QA REPORT
│   ├── dark-zone-check.py           # Stop: monitors unsupported citations and reasoning gaps
│   ├── work-verification-check.py   # Stop: blocks lazy QA and premature user escalation
│   ├── epistemic-check.py           # Stop: Haiku-evaluated overconfidence/rationalization gate
│   ├── session-start-log.py         # SessionStart: governance-log session-boundary marker
│   ├── registry-staleness-check.py  # SessionStart: warns when the registry is stale (opt-in)
│   ├── prose-slop-check.py          # PostToolUse: flags LLM-slop vocabulary in generated prose (opt-in)
│   ├── sidecar_loader.py            # (library) post-compaction dispatch-contract loader
│   └── disabled/                    # Optional/experimental hooks
├── skills/
│   ├── core/                # 16 governance skills (task-classifier, process-*, db-migration-plan, process-postmortem, doc-consistency, verify, ensemble, pm, etc.)
│   ├── vault/               # 7 knowledge-management skills (save, inbox, standup, process-ingest, process-lint, etc.)
│   └── domain-examples/     # 19 domain skills across Apify and n8n
├── settings/
│   ├── settings.json.example        # Global hook registration template
│   └── settings.local.json.example  # Project-level override (registers 12 default hooks; remaining 5 active hooks are opt-in)
├── docs/                    # Architecture reference and customization guides
├── LICENSE.txt
└── INSTALL.md
```

## Quick Start

See [INSTALL.md](INSTALL.md) for step-by-step setup instructions.

## Customization

See [docs/customization.md](docs/customization.md) for guidance on adapting the framework to your domain: adding agents, writing process skills, adjusting hook enforcement thresholds, and disabling components you do not need.

## Skill Format

Core and vault skills follow a standardized 3-section format:

- **Use-when** — when to invoke this skill
- **Do-NOT-use-when** — boundaries (with skip-rules referencing equivalent skills)
- **Gotchas** — common failure modes specific to this skill

The format makes skill-routing decisions auditable from the SKILL.md alone — a model can read the three sections and decide whether to invoke without loading the full skill body. New skills should follow this format; see any of the `skills/core/process-*/SKILL.md` files for examples.

## Research

The theory behind this framework -- including the Exploration vs. Extraction prompting model, the Compound Task decomposition, the Popperian QA approach, and empirical compliance data -- is documented in the companion research repository:

[https://github.com/Wiktor-Potapczyk/agent-governance-research](https://github.com/Wiktor-Potapczyk/agent-governance-research)

## License

Apache 2.0. Authored by Wiktor Potapczyk.
