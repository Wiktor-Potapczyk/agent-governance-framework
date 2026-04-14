# Agent Governance Framework for Claude Code

A deterministic, hook-driven governance framework for Claude Code (Anthropic's official CLI). It wraps the AI agent in four enforcement layers via Python hooks, raising complex task compliance from approximately 25% on prompt-only baselines to approximately 90%.

The framework operationalizes three research-backed principles: classify before acting, delegate specialist work to agents, and falsify rather than confirm. These principles are not left to the model's judgment -- they are enforced at runtime through hooks that can block, redirect, or inject context on every tool call and session boundary.

## Core Innovations

- **Exploration vs. Extraction routing** -- Tasks are classified not by surface keywords but by what they *imply*. The classifier distinguishes open-ended investigation (exploration) from directed retrieval (extraction) and routes each to a different process skill, preventing the model from converging prematurely on a confident answer before the problem space is understood.

- **Compound Task model** -- Every task is decomposed into a mixture of five primitives: Research, Analysis, Planning, Build, and QA. The classifier declares primary type and compound ratios. QA is mandatory for all non-Quick tasks and is enforced at the session Stop hook, not left as an optional step.

- **Popperian QA** -- Quality assurance is framed as falsification, not confirmation. A PASS means "could not break it." Every QA artifact must declare what was *not* tested (Untested Surface). Three tiers: per-task verification, per-increment adversarial pentest, and human-triggered eval suites.

## Architecture

The framework operates across five layers, with 18 active Python hooks:

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
│   └── domain-examples/     # Example domain-specific agents
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
│   └── disabled/                    # Optional/experimental hooks
├── skills/
│   ├── core/                # 12 governance skills (task-classifier, process-*, verify, ensemble, pm, etc.)
│   ├── vault/               # 5 knowledge-management skills (save, inbox, standup, etc.)
│   └── domain-examples/     # 19 domain skills across Apify and n8n
├── settings/
│   ├── settings.json.example        # Global hook registration template
│   └── settings.local.json.example  # Project-level override (includes all 12 hooks)
├── docs/                    # Architecture reference and customization guides
├── LICENSE.txt
└── INSTALL.md
```

## Quick Start

See [INSTALL.md](INSTALL.md) for step-by-step setup instructions.

## Customization

See [docs/customization.md](docs/customization.md) for guidance on adapting the framework to your domain: adding agents, writing process skills, adjusting hook enforcement thresholds, and disabling components you do not need.

## Research

The theory behind this framework -- including the Exploration vs. Extraction prompting model, the Compound Task decomposition, the Popperian QA approach, and empirical compliance data -- is documented in the companion research repository:

[https://github.com/Wiktor-Potapczyk/agent-governance-research](https://github.com/Wiktor-Potapczyk/agent-governance-research)

## License

Apache 2.0. Authored by Wiktor Potapczyk.
