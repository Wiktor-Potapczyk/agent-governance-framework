# Agents Reference

**Audience:** operators and contributors who need to understand what each agent does, which skills route to it, and what it produces.

**Mode:** Reference (Diátaxis). This page describes *what each agent IS* — fields, contracts, known failures. For *why* agents are shaped this way, see `docs/concepts/` and `docs/adr/`. For *how to use* them end-to-end, see the skill reference pages.

**Coverage:** 32 agents total — 29 from `agents/governance/`, 2 from `agents/domain-examples/n8n/`, 1 top-level (`agents/code-simplifier.md`).

---

## Summary Table

| Agent | Category | Domain one-liner |
|---|---|---|
| adversarial-reviewer | Core build/review | Challenge decisions and plans; produce structured `CRITICAL/WARNING/GAP/NOTE` findings |
| architect-reviewer | Core build/review | Review code for architectural consistency, SOLID, layering |
| blueprint-mode | Core build/review | Implement tasks via structured Debug/Express/Main/Loop workflows |
| implementation-plan | Core build/review | Generate deterministic, AI-executable implementation plans |
| prompt-engineer | AI/prompts | Design, optimize, and manage LLM prompts for production |
| llm-architect | AI/prompts | Design LLM production systems: RAG, fine-tuning, serving, multi-model |
| research-orchestrator | Research pipeline | Coordinate multi-phase research across specialist agents |
| research-coordinator | Research pipeline | Strategic planning and task allocation for complex research |
| research-analyst | Research pipeline | Multi-source research synthesis and trend analysis |
| technical-researcher | Research pipeline | Analyze code repos, technical docs, and implementation details |
| research-synthesizer | Research pipeline | Consolidate multi-researcher findings into unified analysis |
| query-clarifier | Research pipeline | Analyze query clarity and decide whether clarification is needed |
| report-generator | Research pipeline | Transform synthesized findings into structured final reports |
| api-designer | Specialized | REST/GraphQL API design, OpenAPI spec, versioning strategy |
| api-security-audit | Specialized | API security audit: auth, OWASP top 10, compliance |
| data-engineer | Specialized | ETL/ELT pipelines, data platform architecture, data quality |
| debugger | Specialized | Systematic bug diagnosis and root cause analysis |
| git-flow-manager | Specialized | Git Flow branch management, merging, PR generation |
| mcp-developer | Specialized | Build and optimize MCP servers and clients |
| mcp-registry-navigator | Specialized | MCP registry discovery, evaluation, and integration configuration |
| mcp-server-architect | Specialized | MCP server architecture, transport layers, protocol compliance |
| nosql-specialist | Specialized | MongoDB, Redis, Cassandra, DynamoDB schema design and optimization |
| postgres-pro | Specialized | PostgreSQL performance, replication, backup, advanced features |
| powershell-7-expert | Specialized | Cross-platform cloud automation, Azure, M365, Graph API with PS7 |
| competitive-analyst | Specialized | Apply competitive frameworks (SWOT, feature matrix, Porter's) to research data |
| content-marketer | Specialized | Write external-audience marketing copy from provided source material |
| vault-keeper | Specialized | Obsidian vault organization: inbox triage, daily notes, health checks |
| workflow-orchestrator | Specialized | Design n8n automation orchestration blueprints (design only, no JSON) |
| pm-orchestrator | Productivity/PM | Project lifecycle management: phase detection, checkpoints with mandatory re-ranked next-3-tickets, viability gates |
| code-simplifier | Productivity/PM | Mechanical hygiene cleanup on recently modified n8n JSON, Python hooks, Markdown skills |
| n8n-workflow-architect | Domain examples | Phase 1 n8n design: blueprint + guidelines compliance matrix |
| n8n-workflow-builder | Domain examples | Phase 2 n8n implementation: execute blueprint via Spiral pattern + autonomous QA loop |

---

## Core Build / Review

### adversarial-reviewer

| Field | Value |
|---|---|
| Domain | Structured adversarial challenge: finds flaws in decisions, plans, designs, and recommendations |
| Tools | Read, Grep, Glob |
| Dispatched by | `process-planning` (mandatory — DISPATCHES.json required binding); `process-analysis` (allowed specialist, optional lens); `task-classifier` (every Planning task gets adversarial challenge) |
| Model | sonnet |
| Inputs | The artifact under challenge; evaluation criteria (optional — defaults to internal rubric) |
| Output contract | `## Adversarial Review` block with `### Findings` (each tagged CRITICAL/WARNING/GAP/NOTE with category and "why it matters") and `### Verdict` (one sentence + confidence 0.0–1.0) |
| Known failure modes | Agent body states: "If everything genuinely holds up, say 'no significant issues found'… but this should be rare" — over-permissive verdicts are a documented risk |

---

### architect-reviewer

| Field | Value |
|---|---|
| Domain | Architectural integrity review: SOLID compliance, pattern adherence, dependency direction, service boundaries |
| Tools | all tools (no restriction declared in frontmatter) |
| Dispatched by | `process-build` (mandatory post-build review, DISPATCHES.json mandatory binding); `process-planning` (mandatory plan review); `task-classifier` (Build+Analysis compound mandatory) |
| Model | sonnet |
| Inputs | Code or config changes to review; optional: existing architecture description |
| Output contract | Structured review with: Architectural Impact (High/Medium/Low), Pattern Compliance checklist, Violations list, Recommendations, Long-Term Implications |
| Known failure modes | None documented in agent body |

---

### blueprint-mode

| Field | Value |
|---|---|
| Domain | Precise software engineering execution via structured Debug/Express/Main/Loop workflows |
| Tools | Read, Bash, Grep, Glob, Edit, Write |
| Dispatched by | `process-build` (mandatory Build agent, DISPATCHES.json mandatory binding); `task-classifier` (Build → blueprint-mode) |
| Model | sonnet |
| Inputs | Task description; optionally: existing code context, requirements, design spec |
| Output contract | Completed implementation (code changes, files); Final Summary with Outstanding Issues, Next, and Status (COMPLETED / PARTIALLY COMPLETED / FAILED); internal Self-Reflection rubric scores (all 6 categories must exceed 8/10) |
| Known failure modes | On ambiguity, agent pauses at confidence < 90 to ask one question; retry cap is 3 internal attempts before marking FAILED |

---

### implementation-plan

| Field | Value |
|---|---|
| Domain | Generate structured, deterministic, AI-executable implementation plans — no code edits |
| Tools | search/codebase, search/usages, vscode/vscodeAPI, think, read/problems, search/changes, execute/testFailure, read/terminalSelection, read/terminalLastCommand, vscode/openSimpleBrowser, web/fetch, findTestFiles, search/searchResults, web/githubRepo, vscode/extensions, edit/editFiles, execute/runNotebookCell, read/getNotebookSummary, read/readNotebookCellOutput, search, vscode/getProjectSetupInfo, vscode/installExtension, vscode/newWorkspace, vscode/runCommand, execute/getTerminalOutput, execute/runInTerminal, execute/createAndRunTask, execute/getTaskOutput, execute/runTask |
| Dispatched by | `process-build` (mandatory planning step, DISPATCHES.json mandatory binding); `process-planning` (mandatory SKILL.md binding) |
| Model | sonnet |
| Inputs | Requirements, features to implement, or refactoring targets; optionally: existing codebase context |
| Output contract | Markdown plan file saved to `/plan/` directory with frontmatter (goal, version, date, status, tags); mandatory sections: Requirements & Constraints (REQ-/SEC-/CON-/GUD-/PAT- prefixes), Implementation Steps (phased task tables with TASK-NNN identifiers + completion status), Alternatives, Dependencies, Files, Testing, Risks & Assumptions, Related Specifications |
| Known failure modes | Agent body notes fabrication risk if context manager is unavailable; tool list references VSCode-specific tools that may not be available in all environments |

---

## AI / Prompts

### prompt-engineer

| Field | Value |
|---|---|
| Domain | Design, optimize, test, and manage LLM prompts for production systems |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (mandatory when artifact includes LLM prompts, DISPATCHES.json mandatory binding); `process-planning` (mandatory for plans involving LLM prompts); `process-analysis` (DISPATCHES.json advisory) |
| Model | sonnet |
| Inputs | Current prompts; performance targets (accuracy %, token budget, latency target); constraints and use-case description |
| Output contract | Optimized prompt templates/systems; AGENT OUTPUT METADATA YAML block (confidence, confidence_basis, data_quality, assumptions, sources, flags) |
| Known failure modes | None documented in agent body beyond the standard output-metadata quality flags |

---

### llm-architect

| Field | Value |
|---|---|
| Domain | Design and implement production LLM systems: fine-tuning, RAG, serving infrastructure, multi-model orchestration |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (DISPATCHES.json advisory); `process-planning` (advisory for LLM system design, SKILL.md reference); `task-classifier` (LLM architecture domain row) |
| Model | sonnet |
| Inputs | LLM system requirements: use case, performance targets (latency, throughput), scale, safety needs, budget |
| Output contract | Architecture design with system components, serving configuration, fine-tuning pipeline, RAG implementation, safety mechanisms, monitoring setup; Production readiness checklist |
| Known failure modes | None documented in agent body |

---

## Research Pipeline

### research-orchestrator

| Field | Value |
|---|---|
| Domain | Coordinate comprehensive multi-phase research projects by delegating to specialist agents in sequence |
| Tools | Read, Write, Edit, Task, TodoWrite |
| Dispatched by | `process-research` (mandatory for complex multi-phase research with 4+ sub-questions, DISPATCHES.json mandatory binding); `task-classifier` (Content path: research-orchestrator → content-marketer) |
| Model | sonnet |
| Inputs | Research query (clear or ambiguous); optionally: constraints, depth requirements |
| Output contract | Completed research pipeline result (query-clarifier → planning → parallel researchers → synthesis → report); AGENT OUTPUT METADATA YAML block; TodoWrite checklist tracking phase completion |
| Known failure modes | On agent failure, retries once with refined input; partial results preferred over none; errors logged in workflow state |

---

### research-coordinator

| Field | Value |
|---|---|
| Domain | Strategic planning and task allocation for complex research across specialist researchers |
| Tools | Read, Write, Edit, Task |
| Dispatched by | direct dispatch — no skill binding in this repo |
| Model | sonnet |
| Inputs | Research brief describing scope, domains, and objectives |
| Output contract | JSON plan with: strategy, iterations_planned, researcher_tasks (per academic/web/technical/data-analyst researcher with assigned bool, priority, tasks, focus_areas, constraints), integration_plan, success_criteria, contingency; followed by AGENT OUTPUT METADATA YAML block |
| Known failure modes | None documented in agent body |

---

### research-analyst

| Field | Value |
|---|---|
| Domain | Multi-source research synthesis, trend analysis, and insight generation across diverse domains |
| Tools | Read, Grep, Glob, WebFetch, WebSearch |
| Dispatched by | `process-research` (DISPATCHES.json mandatory binding for web sources, trends, multi-source synthesis) |
| Model | sonnet |
| Inputs | Research objectives; optionally: existing source material, scope constraints, date ranges |
| Output contract | Research findings with synthesized insights, trend analysis, source citations; AGENT OUTPUT METADATA YAML block (confidence, confidence_basis, data_quality, assumptions, sources, flags) |
| Known failure modes | None documented in agent body |

---

### technical-researcher

| Field | Value |
|---|---|
| Domain | Analyze code repositories, technical documentation, API specs, and implementation details |
| Tools | Read, Write, Edit, WebSearch, WebFetch, Bash |
| Dispatched by | `process-research` (DISPATCHES.json mandatory binding for code repos, technical docs, API behavior, implementation) |
| Model | sonnet |
| Inputs | Technical research question; optionally: target repositories, APIs, frameworks |
| Output contract | JSON output with: search_summary, repositories (citation, platform, stats, key_features, architecture, code_quality, usage_example, limitations, alternatives), technical_insights, implementation_recommendations, community_insights, output_metadata |
| Known failure modes | output_metadata field is MANDATORY; confidence 0.9+ requires cited sources for all claims |

---

### research-synthesizer

| Field | Value |
|---|---|
| Domain | Consolidate findings from multiple specialist researchers into a unified, comprehensive analysis |
| Tools | Read, Write, Edit |
| Dispatched by | `process-research` (mandatory when 2+ researchers dispatched, DISPATCHES.json mandatory binding); `process-analysis` (mandatory when 2+ agents dispatched, SKILL.md mandatory binding) |
| Model | **opus** |
| Inputs | All researcher outputs (from research-analyst, technical-researcher, and others); synthesis approach preference (optional) |
| Output contract | JSON output with: synthesis_metadata, major_themes (each with supporting_evidence and consensus_level), unique_insights, contradictions (viewpoint_1/2 with resolution), evidence_assessment (strongest/moderate/weak/speculative), knowledge_gaps, all_citations, synthesis_summary; followed by AGENT OUTPUT METADATA YAML block |
| Known failure modes | None documented in agent body |

---

### query-clarifier

| Field | Value |
|---|---|
| Domain | Analyze research query clarity and determine whether user clarification is needed before research begins |
| Tools | Read, Write, Edit |
| Dispatched by | `process-research` (DISPATCHES.json mandatory binding when query is ambiguous); invoked by research-orchestrator in Phase 1 |
| Model | sonnet |
| Inputs | Research query string |
| Output contract | JSON object with: needs_clarification (bool), confidence_score (0.0–1.0), analysis, questions (array with question/type/options), refined_query, focus_areas; followed by AGENT OUTPUT METADATA YAML block |
| Known failure modes | Decision thresholds: >0.8 = proceed, 0.6–0.8 = refine-and-proceed, <0.6 = request clarification |

---

### report-generator

| Field | Value |
|---|---|
| Domain | Transform synthesized research findings into comprehensive, well-structured final reports |
| Tools | Read, Write, Edit |
| Dispatched by | `process-research` (mandatory final step, DISPATCHES.json mandatory binding); `process-analysis` (advisory for complex multi-agent evaluations) |
| Model | sonnet |
| Inputs | Synthesized research findings; optional: target audience, format type (technical/policy/comparison/academic/executive), length/depth requirements |
| Output contract | Markdown report with: Executive Summary (for reports >1000 words), Introduction, Key Findings (with citations [1][2]), Analysis and Synthesis, Contradictions and Debates, Conclusion, References; followed by AGENT OUTPUT METADATA YAML block |
| Known failure modes | All claims require supporting citations; no unsupported opinions permitted |

---

## Specialized

### api-designer

| Field | Value |
|---|---|
| Domain | REST and GraphQL API design, OpenAPI 3.1 specification, versioning strategy, developer experience |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-analysis` (DISPATCHES.json advisory); `process-planning` (advisory, SKILL.md reference for unfamiliar API behavior); `task-classifier` (API design/behavior domain row) |
| Model | sonnet |
| Inputs | API requirements, business domain models, client use cases; optionally: existing API to refactor or migrate |
| Output contract | OpenAPI 3.1 specification; pagination patterns; authentication flows; error catalog; webhook specifications; versioning strategy with sunset timelines |
| Known failure modes | None documented in agent body |

---

### api-security-audit

| Field | Value |
|---|---|
| Domain | API security audits: authentication vulnerabilities, authorization flaws, injection attacks, OWASP API Top 10, compliance (GDPR/HIPAA/PCI DSS) |
| Tools | Read, Write, Edit, Bash |
| Dispatched by | `process-analysis` (DISPATCHES.json advisory); `task-classifier` (Security domain row) |
| Model | sonnet |
| Inputs | API implementation (code, config, endpoints); optionally: specific vulnerability scope or compliance target |
| Output contract | Security audit report with specific, actionable recommendations and code examples; remediation steps per finding |
| Known failure modes | None documented in agent body |

---

### data-engineer

| Field | Value |
|---|---|
| Domain | ETL/ELT pipelines, data lake/warehouse design, stream processing, data quality, cost optimization |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (DISPATCHES.json advisory); `process-planning` (advisory for data pipeline architecture, SKILL.md reference); `process-analysis` (DISPATCHES.json advisory) |
| Model | sonnet |
| Inputs | Data pipeline requirements: sources, volume, velocity, SLA targets, cost constraints |
| Output contract | Pipeline architecture design; ETL/ELT implementation; orchestration configuration (Airflow/Prefect/Dagster); data quality framework; monitoring and governance setup; Excellence checklist verification |
| Known failure modes | None documented in agent body |

---

### debugger

| Field | Value |
|---|---|
| Domain | Systematic bug diagnosis, root cause analysis, stack trace interpretation, production debugging |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (conditional: when QA/review identifies runtime errors); `process-analysis` (DISPATCHES.json advisory for runtime errors and unexpected behavior) |
| Model | sonnet |
| Inputs | Error description, logs, stack traces, reproduction steps; optionally: code context |
| Output contract | Root cause identification; fix implementation; side-effect verification; knowledge documentation; postmortem with prevention measures |
| Known failure modes | None documented in agent body |

---

### git-flow-manager

| Field | Value |
|---|---|
| Domain | Git Flow workflow management: feature/release/hotfix branches, merging, PR generation, changelog |
| Tools | Read, Bash, Grep, Glob, Edit, Write |
| Dispatched by | direct dispatch — no skill binding in this repo |
| Model | sonnet |
| Inputs | Git Flow operation request (create branch, finish branch, create release, create PR) |
| Output contract | Structured status output with action taken (checkmarks), current repository status, next steps, warnings; status block format documented in agent body |
| Known failure modes | Documents explicit error handling for: direct push to protected branches, merge conflicts, invalid branch names |

---

### mcp-developer

| Field | Value |
|---|---|
| Domain | Build, debug, and optimize MCP servers and clients; JSON-RPC 2.0 compliance; TypeScript and Python SDKs |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (DISPATCHES.json advisory); `task-classifier` (MCP servers/clients build domain row, advisory) |
| Model | sonnet |
| Inputs | MCP integration requirements: data sources, tool functions, transport mechanism, security requirements, performance targets |
| Output contract | Production-ready MCP server/client implementation with: protocol handlers, resource endpoints, tool functions, security controls, comprehensive tests, monitoring; Excellence checklist verification |
| Known failure modes | None documented in agent body |

---

### mcp-registry-navigator

| Field | Value |
|---|---|
| Domain | MCP server discovery across registries, capability assessment, configuration generation, registry publishing |
| Tools | Read, Write, Edit, WebSearch |
| Dispatched by | direct dispatch — no skill binding in this repo |
| Model | sonnet |
| Inputs | MCP capability requirements; optionally: region, latency, transport preferences |
| Output contract | Discovery results (structured server list with capabilities); evaluation reports; production-ready configuration templates; integration guides; optimization recommendations |
| Known failure modes | None documented in agent body; agent body targets <30s discovery speed and 95%+ match rate |

---

### mcp-server-architect

| Field | Value |
|---|---|
| Domain | MCP server architecture: transport layer design, tool/resource/prompt definitions, completion support, session management, protocol compliance per MCP spec 2025-06-18 |
| Tools | Read, Write, Edit, Bash |
| Dispatched by | `task-classifier` (MCP servers/clients design domain row, advisory) |
| Model | sonnet |
| Inputs | MCP server domain and use cases; optionally: existing server to enhance |
| Output contract | Complete production-ready MCP server implementation with: stdio + Streamable HTTP transports, JSON Schema validation, tool annotations, completion support, secure session management, Docker containerization, documentation |
| Known failure modes | None documented in agent body |

---

### nosql-specialist

| Field | Value |
|---|---|
| Domain | NoSQL database design and optimization: MongoDB, Redis, Cassandra, DynamoDB, Neo4j |
| Tools | Read, Write, Edit, Bash |
| Dispatched by | `process-build` (DISPATCHES.json advisory); `task-classifier` (Redis/MongoDB/NoSQL domain row) |
| Model | sonnet |
| Inputs | Data model requirements, access patterns, consistency and scalability needs; optionally: existing schema to optimize |
| Output contract | Schema design with validation rules; index strategy; query patterns; performance optimization code; monitoring commands |
| Known failure modes | None documented in agent body |

---

### postgres-pro

| Field | Value |
|---|---|
| Domain | PostgreSQL performance tuning, query optimization, HA replication, backup/recovery, advanced features |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (DISPATCHES.json advisory); `db-migration-plan` skill (mandatory for query-plan evidence and index-type selection, SKILL.md binding); `task-classifier` (PostgreSQL domain row) |
| Model | sonnet |
| Inputs | PostgreSQL deployment context, performance metrics, or specific issue (slow queries, replication lag, backup gap) |
| Output contract | EXPLAIN analysis; configuration tuning recommendations; index strategy; replication architecture; backup/recovery runbook; monitoring dashboards; Excellence checklist verification |
| Known failure modes | None documented in agent body |

---

### powershell-7-expert

| Field | Value |
|---|---|
| Domain | PowerShell 7+ cross-platform automation: Azure, M365, Graph API, CI/CD pipelines, enterprise scripting |
| Tools | Read, Write, Edit, Bash, Glob, Grep |
| Dispatched by | `process-build` (DISPATCHES.json advisory); `task-classifier` (PowerShell/Windows domain row) |
| Model | sonnet |
| Inputs | Automation requirements: target platform (Azure/M365/CI), scale, idempotency needs, safety requirements (-WhatIf/-Confirm) |
| Output contract | PowerShell 7 scripts with: cross-platform path handling, idempotent operations, -WhatIf/-Confirm on state changes, structured CI/CD-ready output, secure secret handling |
| Known failure modes | None documented in agent body |

---

### competitive-analyst

| Field | Value |
|---|---|
| Domain | Apply competitive frameworks (SWOT, feature matrix, pricing grid, positioning map, Porter's Five Forces) to pre-gathered research data |
| Tools | Read, Write, Edit, Grep, Glob, WebFetch, WebSearch |
| Dispatched by | `task-classifier` (Competitive analysis domain row) — sequential handoff from research-orchestrator |
| Model | sonnet |
| Inputs | Pre-gathered research data (researcher output, vault notes, briefing docs); analysis goal |
| Output contract | Framework-applied analysis with confidence levels (High/Medium/Low); 3–5 ranked strategic recommendations; gap report if data insufficient; saved to `Projects/<name>/work/YYYY-MM-DD-competitive-analysis-<topic>.md` |
| Known failure modes | Agent body states: never fill data gaps by invention — marks gaps as `[NO DATA — needs research: description]`; returns gap report over weak analysis when critical data is missing |

---

### content-marketer

| Field | Value |
|---|---|
| Domain | Write external-audience content from provided source material: blog posts, case studies, award submissions, LinkedIn, white papers |
| Tools | Read, Write, Edit, Glob, Grep, WebFetch, WebSearch |
| Dispatched by | direct dispatch from research-orchestrator pipeline (task-classifier Content path: research-orchestrator → content-marketer); `process-build` DISPATCHES.json note explicitly deprecates dispatching content-marketer from inside process-build |
| Model | sonnet |
| Inputs | Source material (research notes, briefs, data, brand guidelines); target audience; format; word/character limits; scoring rubric (for award submissions) |
| Output contract | Draft content file saved to `Projects/<name>/work/YYYY-MM-DD-<content-type>-<topic>.md`; `[DATA NEEDED: description]` markers where data is missing; never fabricated metrics |
| Known failure modes | Agent body documents: fabrication prohibition enforced by `[DATA NEEDED]` markers; banned clichés list (synergy, leverage, unlock, game-changer, holistic, seamlessly, best-in-class) |

---

### vault-keeper

| Field | Value |
|---|---|
| Domain | Obsidian vault organization: inbox triage, daily note creation, file moves/archives, frontmatter fixes, wiki-link health |
| Tools | Read, Write, Edit, Glob, Grep, Bash |
| Dispatched by | direct dispatch — no skill binding in this repo |
| Model | haiku |
| Inputs | Operation type: inbox processing, daily note, move/archive, health check, or frontmatter/wiki-link fix |
| Output contract | Phase 1 (Inbox): one line per note — `filename | classification | destination`; Phase 2 (Daily Note): created `Daily Notes/YYYY-MM-DD.md`; Phase 3 (Move/Archive): confirmation of moves with wiki-link updates; Phase 4 (Health Check): fixed items list, flagged items list, items requiring user decision |
| Known failure modes | Agent reads CLAUDE.md before every operation for vault rules; task router determines phase before executing — routing error produces wrong phase output |

---

### workflow-orchestrator

| Field | Value |
|---|---|
| Domain | Design high-level n8n automation orchestration blueprints: state machines, branching logic, error recovery, parallel execution — design only, no JSON production |
| Tools | Read, Write, Edit, Glob, Grep |
| Dispatched by | `process-analysis` (DISPATCHES.json advisory for n8n workflow logic); `task-classifier` (n8n workflows design domain row) |
| Model | sonnet |
| Inputs | Process requirements; existing related workflows; project STATE.md |
| Output contract | Orchestration design document at `Projects/<name>/work/YYYY-MM-DD-orchestration-<workflow>.md` with: Mermaid `stateDiagram-v2`, Data Contracts table (step/input/output/side-effects), Error Handling Matrix (failure mode/retry/fallback/compensation per external-service step), Open Questions; handoff note to blueprint-mode |
| Known failure modes | Agent body states: only 1–3 clarifying questions if ambiguous; no design with unresolved ambiguities; every Mermaid state must have at least one exit transition; all conditions must be exact (not vague) |

---

## Productivity / PM

### pm-orchestrator

| Field | Value |
|---|---|
| Domain | Project lifecycle management for solo operators: phase detection, checkpoint protocols (5 questions + mandatory re-rank), viability gates, kill criteria, artifact ownership |
| Tools | all tools (no restriction declared in frontmatter) |
| Dispatched by | `pm` skill (mandatory dispatch via Agent tool, SKILL.md binding) |
| Model | sonnet |
| Inputs | Project name (or asks if ambiguous); reads PROJECT.md, STATE.md, task_plan.md directly |
| Output contract | Phase report (current phase, active tasks, blockers, next action); Checkpoint Protocol output (Q1–Q5 all answered from live files) PLUS the mandatory Re-Ranked Next-3-Tickets block (top 3 tickets with one-line justifications; promotions/demotions since last checkpoint — a checkpoint without this block is incomplete); artifact updates to PROJECT.md, STATE.md, task_plan.md; escalations when kill criteria met |
| Known failure modes | Agent body documents: must Read files, not answer from memory; "no reason" ranking justification is invalid; fewer than 3 open items — list all remaining |

---

### code-simplifier

| Field | Value |
|---|---|
| Domain | Mechanical hygiene cleanup on recently modified vault artifacts: n8n workflow JSON, Python hooks, Markdown skills — formatting, dead code, naming consistency, expression-syntax |
| Tools | Read (implied); operates as diff-proposal by default, does not write to disk unless explicitly told "apply" |
| Dispatched by | direct dispatch — no skill binding in this repo; on-demand only, not auto-triggered |
| Model | sonnet |
| Inputs | Recently modified code/config files in scope: n8n workflow JSON, `.claude/hooks/*.py`, `.claude/skills/<name>/SKILL.md` |
| Output contract | Per-refinement diff blocks: `File:`, `Why:`, `Before:`, `After:` — does NOT write to disk in default mode; flags architectural smells as `OUT OF SCOPE — route to architect-reviewer:` |
| Known failure modes | Agent body documents non-overlap with architect-reviewer (verified by inspection 2026-05-11); scope limited to current session's modified files only — not a whole-vault scan |

---

## Domain Examples

### n8n-workflow-architect

| Field | Value |
|---|---|
| Domain | Phase 1 of two-phase n8n orchestration: all discovery, template selection, node selection, architecture decisions; produces blueprint `.md` file |
| Tools | Read, Write, Edit, Glob, Grep, Bash, WebFetch, WebSearch, plus n8n-mcp tools: tools_documentation, list_nodes, search_nodes, get_node_essentials, get_node_info, get_node_documentation, list_tasks, get_node_for_task, get_templates_for_task, search_templates, list_node_templates, get_template, validate_node_minimal, validate_node_operation, n8n_get_workflow, n8n_get_workflow_structure, n8n_get_workflow_details, n8n_get_workflow_minimal, n8n_list_workflows, n8n_list_executions, n8n_get_execution, n8n_validate_workflow, n8n_health_check, n8n_diagnostic |
| Dispatched by | direct dispatch — no skill binding in this repo; CLAUDE.md Two-Phase Orchestration doctrine states dispatch before any non-trivial n8n build |
| Model | sonnet |
| Inputs | Workflow requirements; optionally: existing workflow ID (for redesign), execution history |
| Output contract | Blueprint `.md` file at `Projects/<name>/work/YYYY-MM-DD-blueprint-<workflow>.md` with: DISCOVERY INSIGHTS, SYSTEM ARCHITECTURE, INCREMENTAL BUILD PLAN (milestones of 3–5 nodes with validation checkpoints), CRITICAL CONFIGURATIONS, GUIDELINES COMPLIANCE MATRIX, AUTONOMOUS-LOOP ENTRY CLASSIFICATION, FLAG section (conditional human gate triggers), BUILDER HANDOFF specs |
| Known failure modes | Anti-Fabrication Rule: verify every file path, workflow ID, and node name via Read/Glob/MCP before citing; do NOT invent — surface as TBD or open question. Milestones >5 nodes are forbidden (Builder rejects). Never modify live workflow |

---

### n8n-workflow-builder

| Field | Value |
|---|---|
| Domain | Phase 2 of two-phase n8n orchestration: implement the architect's blueprint exactly via Spiral pattern (3–5 nodes per milestone, validate between); run autonomous QA loop when eligible |
| Tools | Read, Write, Edit, Glob, Grep, Bash, TodoWrite, plus n8n-mcp tools: tools_documentation, list_nodes, search_nodes, get_node_essentials, get_node_info, get_node_documentation, search_node_properties, get_property_dependencies, list_tasks, get_node_for_task, get_template, validate_node_minimal, validate_node_operation, validate_workflow, validate_workflow_connections, validate_workflow_expressions, n8n_create_workflow, n8n_update_partial_workflow, n8n_update_full_workflow, n8n_get_workflow, n8n_get_workflow_structure, n8n_get_workflow_details, n8n_get_workflow_minimal, n8n_validate_workflow, n8n_autofix_workflow, n8n_trigger_webhook_workflow, n8n_get_execution, n8n_list_executions, n8n_health_check, n8n_diagnostic, n8n_list_workflows |
| Dispatched by | direct dispatch from n8n-workflow-architect (when `autonomous_loop_eligible: true`) or user-approved (when blueprint frontmatter is `#approved`); REFUSES dispatch if blueprint status is `#pending-human-review` |
| Model | sonnet |
| Inputs | Blueprint `.md` file path from n8n-workflow-architect; blueprint must have status `#pending-builder-dispatch` or `#approved` |
| Output contract | BUILD PROGRESS milestone report (per-milestone validation status); VALIDATION RESULTS (per checkpoint); AUTONOMOUS LOOP status (iterations, green/cap/deadlock) when eligible; completion statement with workflow ID; NEVER activates workflow — surfaces Promotion Gate to user |
| Known failure modes | Agent body documents explicit failure table: validate_node_minimal failure before add = do not add + stop; validate_workflow failure after add = autofix only if blueprint authorizes + stop if still fails; deadlock (same error twice on same node) = stop + report; cap hit (10 iterations) = stop + report last 3 diagnostics; never improvises past blueprint gaps — always stops and reports |
