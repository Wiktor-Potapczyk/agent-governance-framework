# Skills Reference

**Audience:** Operators and contributors deploying or extending this framework.
**Mode:** Reference — describes what each skill IS (fields, behaviour, contract). For why the framework is shaped this way, see `docs/concepts/`. For setup steps, see `INSTALL.md`.

A skill is a Markdown procedure loaded by Claude Code's skill loader (walks `skills/<name>/SKILL.md`). Skills are stateless routing/process documents — they do not execute code themselves; they instruct the agent on which specialist agents to dispatch, what structured output blocks to produce, and what quality gates to pass.

---

## Summary table

| Skill | Type | One-line purpose |
|---|---|---|
| **Core** | | |
| `architect-loop` | routing | Structure a Ralph Loop research prompt for complex multi-question investigations |
| `db-migration-plan` | process | Produce a safe expand→migrate→contract plan before any schema change |
| `doc-consistency` | process | Keep a multi-file documentation set internally consistent |
| `ensemble` | process | Run 4 parallel thinking lenses and produce a divergence map |
| `index` | utility | Connect a new finding to existing research threads in INDEX.md |
| `pm` | routing | Dispatch pm-orchestrator for a PM checkpoint on the active project |
| `process-analysis` | process | Evaluate, investigate, or decompose tasks routed by task-classifier |
| `process-build` | process | Plan → Build → Review pipeline for implementation tasks |
| `process-governance-mine` | process | Mine governance-log.jsonl for recurring failure patterns; emit proposals only |
| `process-pentest` | process | Adversarial execution of an entire increment before shipping |
| `process-planning` | process | Design, spec, and sequence work; always includes architect-review |
| `process-postmortem` | process | Reconstruct root cause after a production failure; output durable prevention items |
| `process-qa` | process | Empirical claim-by-claim verification of task outputs |
| `process-research` | process | Route research tasks via Ralph Loop or direct specialist delegation |
| `task-classifier` | routing | Classify every substantive task before work begins; emit MUST DISPATCH contract |
| `verification-gated-research` | process | Exhaustive research via external ledger + separate verifier agent gate |
| `verify` | utility | CoVe step-level reasoning verification (one round) |
| **Vault** | | |
| `daily` | utility | Create today's daily note with tasks pulled from task_plan.md |
| `inbox` | utility | Classify and route all notes in Inbox/ per vault rules |
| `maintain` | utility | Inventory and archive stale work files; delegate to avoid context trashing |
| `process-ingest` | process | Integrate a raw source into the LLM-Wiki layer with SHA-bound citation |
| `process-lint` | process | Full wiki-layer health check: citation, orphan, index, log, staleness passes |
| `save` | utility | Checkpoint session state to STATE.md, PROJECT.md, task_plan.md, and memory |
| `standup` | utility | Quick bullet-point summary of in-progress, blocked, and next items |
| **Top-level** | | |

---

## Core skills

### architect-loop

| Field | Value |
|---|---|
| Type | routing |
| Frontmatter | `name: architect-loop`; trigger phrases: "architect a loop", "prepare a ralph loop", "design a loop for", complex task with multiple open questions |
| Use-when | A complex task has multiple unknowns; investigation needs fresh, unanchored context before building |
| Do-NOT-use-when | 1–2 clear questions with known sources (use `process-research` direct path); building or implementing (loop researches, never builds) |
| Dispatches | No downstream agents — produces a loop prompt file and a ready-to-paste `/ralph-loop:ralph-loop` command for the user to review |
| Steps | Read STATE.md → gather open questions → map source files → group into PROBLEM sections (3–6) → write loop prompt to `work/YYYY-MM-DD-[topic]-research-loop.md` → generate command with `--max-iterations` → present for review. Full procedure: [`skills/core/architect-loop/SKILL.md`](../../skills/core/architect-loop/SKILL.md) |
| Outputs | Loop prompt `.md` file in `Projects/[Name]/work/`; ready-to-paste `/ralph-loop` command |
| Enforced by | `dispatch-compliance-check.py` (lists `architect-loop` as a known dispatch target; verifies it was invoked when MUST DISPATCH names it) |

---

### db-migration-plan

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: db-migration-plan`; trigger phrases: migration, schema change, add column, add index, alter table, backfill, zero-downtime, ALTER, DDL |
| Use-when | Schema change is planned but not yet applied; table has live readers/writers; zero-downtime ordering matters |
| Do-NOT-use-when | Migration already ran and broke → `process-postmortem`; brand-new table no live code reads; query performance with no schema change → `postgres-pro` directly |
| Dispatches | `postgres-pro` (for EXPLAIN, lock analysis, index-type selection — advisory) |
| Steps | Capture live schema state → sequence with expand→migrate→contract → narrate every index (columns, type, order, write-tradeoff) → produce rollback path + verification checklist → quality check. Full procedure: [`skills/core/db-migration-plan/SKILL.md`](../../skills/core/db-migration-plan/SKILL.md) |
| Outputs | Migration plan `.md` at `Projects/[Name]/work/YYYY-MM-DD-migration-[table].md`; MIGRATION SCOPE block; per-step SQL + lock + rollback |
| Enforced by | process discipline (no dedicated hook) |

---

### doc-consistency

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: doc-consistency`; trigger phrases: maintain docs, update the docs, keep docs in sync, doc drift, stale docs, README vs, are the docs current |
| Use-when | A code/config change landed that any doc describes; before pushing a repo; doc set spans multiple files cross-referencing the same facts |
| Do-NOT-use-when | Writing a new doc from scratch with no existing set; prose-quality linting; a single named typo; generating reference docs from code (single-source-of-truth pattern) |
| Dispatches | None — runs deterministic checker script (`skills/core/doc-consistency/check_doc_consistency.py`) plus LLM semantic reconciliation inline |
| Steps | Enumerate full doc set (hard gate) → build or read `.doc-consistency.json` manifest → run deterministic pre-check → LLM semantic reconciliation → quality check. Full procedure: [`skills/core/doc-consistency/SKILL.md`](../../skills/core/doc-consistency/SKILL.md) |
| Outputs | Enumerated doc set; `.doc-consistency.json` manifest; deterministic checker exit code; proposed or applied fixes |
| Enforced by | process discipline (no dedicated hook); doc-consistency checker is the machine layer |

---

### ensemble

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: ensemble`; trigger: user says `/ensemble`, task-classifier outputs `MECHANISM: Ensemble`, framing/design/architecture question needing multiple perspectives |
| Use-when | Question involves framing, design, architecture, or option comparison with no single correct answer |
| Do-NOT-use-when | Quick tasks; reasoning/logic/math (use `/verify`); factual lookups |
| Dispatches | 4 parallel Agent dispatches — Lens A (Reframing), Lens B (Decomposition), Lens C (Stakeholder), Lens D (Adversarial); all dispatched in one message |
| Steps | Frame and de-bias question → present to user for approval (mandatory) → dispatch 4 agents in parallel → produce divergence map → verify key claims with grounding check → offer full outputs on demand. Full procedure: [`skills/core/ensemble/SKILL.md`](../../skills/core/ensemble/SKILL.md) |
| Outputs | Divergence map block (LENS A–D positions, DIVERGENCE, CONVERGENCE, SHARPEST INSIGHT, GROUNDING CHECK) |
| Enforced by | process discipline (no dedicated hook) |

---

### index

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: index`; trigger: user says `/index`, "index this", "where does this fit", "check the index"; proactively after any substantive finding |
| Use-when | New finding, thought, or file needs to be connected to existing research threads; promoting work from `work/` to `research/` |
| Do-NOT-use-when | INDEX.md does not exist (offer to create it); content is too vague to index |
| Dispatches | None |
| Steps | Read INDEX.md → identify new content → compare against each thread (extends / contradicts / depends on / unrelated) → output connections and recommendation (UPDATE / NEW THREAD / DUPLICATE) → execute if approved. Full procedure: [`skills/core/index/SKILL.md`](../../skills/core/index/SKILL.md) |
| Outputs | Index Check block with connections, recommendation, and promotion path; INDEX.md edit if approved |
| Enforced by | process discipline (no dedicated hook) |

---

### pm

| Field | Value |
|---|---|
| Type | routing |
| Frontmatter | `name: pm`; trigger: user says `/pm`, "where are we on [project]", "project status check", between increments |
| Use-when | Between increments; at session start; scope change, blocker, new workstream, or phase-transition signal (reactive triggers — escalate Quick to Analysis) |
| Do-NOT-use-when | Mid-task inline work (pm is a checkpoint, not a step) |
| Dispatches | `pm-orchestrator` (mandatory; the Stop hook verifies it was invoked after every `/pm` call) |
| Steps | Identify active project from `Projects/*/STATE.md` → dispatch `pm-orchestrator` with project path and checkpoint instructions → relay output verbatim → produce PM CHECKPOINT REPORT block. Full procedure: [`skills/core/pm/SKILL.md`](../../skills/core/pm/SKILL.md) |
| Outputs | PM CHECKPOINT REPORT block (Project / Phase / Viability / Blockers / Next) |
| Enforced by | `process-step-check.py` (Stop hook — verifies pm-orchestrator Agent was dispatched after the `/pm` Skill call and that PM CHECKPOINT REPORT block is present); `dispatch-compliance-check.py` (verifies `pm` was invoked when MUST DISPATCH names it); `classifier-field-check.py` (verifies `pm` appears in MUST DISPATCH for every non-Quick task) |

---

### process-analysis

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-analysis`; routed to by `task-classifier` for Analysis-type tasks |
| Use-when | Evaluating artifacts against a rubric; investigating causes or behavior; decomposing a Compound task into sub-tasks |
| Do-NOT-use-when | Single factual lookup (Quick); building or implementing (that is `process-build`) |
| Dispatches | Specialist agents per subject (prompt-engineer, architect-review, debugger, api-designer, data-engineer, n8n-workflow-architect, api-security-audit); `research-synthesizer` when 2+ agents contributed (mandatory); `report-generator` for final output |
| Steps | Define ANALYSIS SCOPE block (mode + subject + question + deliverable) → assign specialist(s) → synthesize if 2+ agents (mandatory) → report. Full procedure: [`skills/core/process-analysis/SKILL.md`](../../skills/core/process-analysis/SKILL.md) |
| Outputs | ANALYSIS SCOPE block; specialist agent output(s); synthesis (when multi-agent); final assessment saved to `Projects/[Name]/work/` |
| Enforced by | `process-step-check.py` (Stop hook — checks ANALYSIS SCOPE block present, synthesis dispatched when 2+ agents contributed) |
| Workflow-enforced | `workflows/process-analysis.js` (adopted 2026-06-11) — scriptPath: `{{VAULT_ROOT}}/.claude/workflows/process-analysis.js`. HALT paths: `decomposition-hand-back` (mode=decomposition), `halted-malformed-args`. See [`docs/reference/workflows.md`](workflows.md). |

---

### process-build

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-build`; routed to by `task-classifier` for Build-type tasks (and Content, which is Build with DOMAIN: content) |
| Use-when | Implementing code, scripts, n8n workflow JSON, or content; always requires a spec/requirements as input |
| Do-NOT-use-when | No spec exists (route to Planning first); evaluating without building (use `process-analysis`) |
| Dispatches | `implementation-plan` (planning); `blueprint-mode` (build); `architect-review` (mandatory review); `prompt-engineer` (mandatory in parallel when artifact contains LLM prompts); `debugger` (on failure) |
| Steps | Define BUILD SCOPE block → delegate to `implementation-plan` → delegate to `blueprint-mode` → mandatory `architect-review` (+ `prompt-engineer` if LLM prompts) → quality check including live verification. Full procedure: [`skills/core/process-build/SKILL.md`](../../skills/core/process-build/SKILL.md) |
| Outputs | BUILD SCOPE block; implementation plan; built artifact at `Projects/[Name]/work/`; review report |
| Enforced by | `process-step-check.py` (Stop hook — checks BUILD SCOPE block and architect-reviewer dispatch); `dispatch-compliance-check.py` (verifies `process-build` invoked when MUST DISPATCH names it; checks `architect-reviewer` and `implementation-plan` were dispatched) |
| Workflow-enforced | `workflows/process-build.js` (adopted 2026-06-11) — scriptPath: `{{VAULT_ROOT}}/.claude/workflows/process-build.js`. HALT paths: `halted-malformed-args`. See [`docs/reference/workflows.md`](workflows.md). |

---

### process-governance-mine

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-governance-mine`; trigger: user says `/process-governance-mine`, "run governance mine", weekly cadence reminder from the maintainer's SessionStart cadence hook (not shipped in this repo) |
| Use-when | Weekly retrospective sweep of governance-log.jsonl; after a high-incident period; before a harness-architecture review |
| Do-NOT-use-when | Fixing a hook or CLAUDE.md directly (proposals only — fixes go through `/hookify` or a separate Build task); log file is empty; investigating a single incident (use `process-qa`); validating wiki structure (use `process-lint`) |
| Dispatches | None — calls `mine_governance.py` helper directly |
| Steps | Run `mine_governance.py` → compute `surfaced_count` per sig_id → write proposal file to `Projects/[Name]/work/YYYY-MM-DD-governance-mine-proposals.md` → emit summary line → update `.claude/hooks/_state/governance-mine-cadence.json`. Full procedure: [`skills/core/process-governance-mine/SKILL.md`](../../skills/core/process-governance-mine/SKILL.md) |
| Outputs | One proposals `.md` file; one cadence state JSON update; one-line summary. **Hard invariant: no edits to CLAUDE.md, hook logic, skills, the governance log, or the resolved ledger.** |
| Enforced by | process discipline (no dedicated hook); the proposal-only invariant is structural, not hook-enforced |

---

### process-pentest

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-pentest`; invoked after all tasks in an increment are complete, before reporting back |
| Use-when | An entire increment is complete and needs adversarial testing; Tier 2 verification (complements per-task QA) |
| Do-NOT-use-when | Per-task verification (that is `process-qa`); read-only review (pentesting requires execution tools) |
| Dispatches | None — executes tests directly using Bash, Read, Write, MCP tools |
| Steps | Define PENTEST SCOPE → identify attack surface → execute tests per category (boundary / adversarial / regression / failure modes / integration) each with state→execute→raw-output→judge sequence → write PENTEST REPORT with Untested Surface → act on findings. Full procedure: [`skills/core/process-pentest/SKILL.md`](../../skills/core/process-pentest/SKILL.md) |
| Outputs | PENTEST REPORT block (findings table, Untested Surface, Recommendation: SHIP / FIX-THEN-SHIP / ESCALATE, PASS/FAIL) |
| Enforced by | `work-verification-check.py` (Stop hook — blocks a PENTEST REPORT filed with zero execution tool calls) + `process-step-check.py` (Stop hook — tracks `pentest_seen`; hard-blocks increment completion paths that require the pentest report) |
| Workflow-enforced | `workflows/process-pentest.js` (adopted 2026-06-11) — scriptPath: `{{VAULT_ROOT}}/.claude/workflows/process-pentest.js`. HALT paths: `halted-malformed-args`. See [`docs/reference/workflows.md`](workflows.md). |

---

### process-planning

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-planning`; routed to by `task-classifier` for Planning-type tasks |
| Use-when | Designing architecture, sequencing work, creating a spec; always when building something that has no existing spec |
| Do-NOT-use-when | Requirements are missing (route to Research first); task is implementing, not designing |
| Dispatches | `implementation-plan` (primary plan); `llm-architect` or `data-engineer` (parallel, for specialised domains); `architect-review` (mandatory); `prompt-engineer` (when plan involves LLM prompts); `adversarial-reviewer` (mandatory for high-stakes multi-phase or irreversible plans) |
| Steps | Read STATE.md/PROJECT.md for appetite/phase → define PLANNING SCOPE block → optional research step → delegate to `implementation-plan` → mandatory `architect-review` → revise loop → quality check. Full procedure: [`skills/core/process-planning/SKILL.md`](../../skills/core/process-planning/SKILL.md) |
| Outputs | PLANNING SCOPE block; sequenced plan with acceptance criteria saved to `Projects/[Name]/work/`; review report |
| Enforced by | `process-step-check.py` (Stop hook — checks PLANNING SCOPE block and architect-reviewer dispatch); `dispatch-compliance-check.py` (verifies `process-planning` invoked when MUST DISPATCH names it; checks `implementation-plan` and `adversarial-reviewer` dispatched) |
| Workflow-enforced | `workflows/process-planning.js` (adopted 2026-06-11) — scriptPath: `{{VAULT_ROOT}}/.claude/workflows/process-planning.js`. HALT paths: `halted-malformed-args`. See [`docs/reference/workflows.md`](workflows.md). |

---

### process-postmortem

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-postmortem`; trigger phrases: postmortem, what went wrong, incident, why did X break, root cause; `disallowed-tools: [AskUserQuestion]` |
| Use-when | A production or test failure already happened; n8n execution silently failed; a migration/deploy/hook/automation regressed; a near-miss worth capturing |
| Do-NOT-use-when | Pre-ship verification (`process-qa` / `process-pentest`); diagnosing a bug about to be fixed in the same task with no durable-learning angle (`process-analysis` Investigation mode); velocity retro; zero recoverable evidence |
| Dispatches | None — reconstructs from evidence (logs, n8n executions, git, files) without asking questions |
| Steps | Define POSTMORTEM SCOPE → reconstruct evidence-bound timeline → 5-why root-cause chain (proven vs hypothesis tagged) → silent-failure check → contributing factors → prevention items (reversible vs maintainer-gated) → write artifact + feedback loop (memory file, `/hookify` if rule-shaped). Full procedure: [`skills/core/process-postmortem/SKILL.md`](../../skills/core/process-postmortem/SKILL.md) |
| Outputs | POSTMORTEM REPORT block (root cause, silent-failure, contributing factors, prevention items, open questions, untested); dated `.md` artifact in `Projects/[Name]/work/` |
| Enforced by | process discipline (no dedicated hook) |

---

### process-qa

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-qa`; mandatory compound for every non-Quick task; invoked by `task-classifier` MUST DISPATCH |
| Use-when | Any non-Quick task produces claims that need empirical verification before reporting back |
| Do-NOT-use-when | No verifiable claims exist; adversarial break-testing of an entire increment (that is `process-pentest`) |
| Dispatches | `debugger` (for runtime errors on FAIL); no agent dispatch for the core verification path — tests are executed directly |
| Steps | List all verifiable claims (QA SCOPE) → select verification method per claim type → execute each claim (run → show raw output → judge PASS/FAIL) → coverage check → write QA REPORT with Untested Surface → escalate FAILs (report only, do not fix). Full procedure: [`skills/core/process-qa/SKILL.md`](../../skills/core/process-qa/SKILL.md) |
| Outputs | QA REPORT block (claims table with PASS/FAIL/MANUAL counts, evidence column, Untested Surface) |
| Enforced by | `work-verification-check.py` (Stop hook — blocks QA REPORT with zero execution tool calls; blocks non-Quick task completion without `process-qa` invocation); `dispatch-compliance-check.py` (verifies `process-qa` in MUST DISPATCH for every non-Quick task and that it was invoked) |
| Workflow-enforced | `workflows/process-qa.js` (adopted 2026-06-11) — scriptPath: `{{VAULT_ROOT}}/.claude/workflows/process-qa.js`. HALT paths: `halted-malformed-args`. TRANSCRIPT RELAY: after Workflow returns, relay `qa_scope_text` + `qa_report_text` as plain unfenced text. See [`docs/reference/workflows.md`](workflows.md). |

---

### process-research

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-research`; routed to by `task-classifier` for Research-type tasks |
| Use-when | Open questions needing source materials; 1–2 questions (direct path) or 3+ with multiple sources (Ralph Loop path) |
| Do-NOT-use-when | Task is building or implementing; single factual lookup (Quick); academic literature review (use ARS skills) |
| Dispatches | **Ralph Loop path:** `architect-loop` skill. **Direct path:** `research-analyst` (web/trends), `technical-researcher` (code/APIs), or both in parallel; `research-orchestrator` for complex 4+ sub-question tasks. Mandatory: `research-synthesizer` when 2+ agents contributed; `report-generator` for final output |
| Steps | Define RESEARCH SCOPE → choose path (Ralph Loop if 3+ questions + 3+ sources + bias risk; direct otherwise) → run path → mandatory synthesis (2+ agents) → report-generator. Full procedure: [`skills/core/process-research/SKILL.md`](../../skills/core/process-research/SKILL.md) |
| Outputs | RESEARCH SCOPE block; research findings; synthesis; final report saved to `Projects/[Name]/work/` |
| Enforced by | `process-step-check.py` (Stop hook — checks synthesis dispatched when 2+ agents); `dispatch-compliance-check.py` (verifies `process-research` invoked when MUST DISPATCH names it) |
| Workflow-enforced | `workflows/process-research.js` (adopted 2026-06-11) — scriptPath: `{{VAULT_ROOT}}/.claude/workflows/process-research.js`. HALT paths: `ralph-loop-hand-back`, `halted-malformed-args`. See [`docs/reference/workflows.md`](workflows.md). |

---

### task-classifier

| Field | Value |
|---|---|
| Type | routing |
| Frontmatter | `name: task-classifier`; invoked at the start of every substantive task |
| Use-when | Before any non-trivial work — determines task type and mandatory dispatch contract |
| Do-NOT-use-when | Already classified in the current turn; explicit imperative fast-path Quick tasks where burden of proof is met |
| Dispatches | Routes to: `process-research` (Research), `process-analysis` (Analysis / Compound), `process-build` (Build / Content), `process-planning` (Planning); emits MUST DISPATCH contract for all compounds and mandatory pm + process-qa on every non-Quick task |
| Steps | IMPLIES sentence (Step 0) → type matrix scan → domain detection → challenge approach (MISSED line) → Quick check → Ralph Loop check → emit classification block (IMPLIES / TASK TYPE / DOMAIN / APPROACH / MISSED / MUST DISPATCH) → invoke process skill via Skill tool. Full procedure: [`skills/core/task-classifier/SKILL.md`](../../skills/core/task-classifier/SKILL.md) |
| Outputs | Classification block (all 6 fields mandatory for non-Quick); MUST DISPATCH list as enforcement contract |
| Enforced by | `classifier-field-check.py` (Stop hook — verifies IMPLIES, TASK TYPE, APPROACH, MISSED, MUST DISPATCH fields present; verifies `pm` appears in MUST DISPATCH for non-Quick tasks); `dispatch-compliance-check.py` (verifies items in MUST DISPATCH were actually invoked) |

---

### verification-gated-research

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: verification-gated-research`; trigger: multi-source depth investigation where self-graded loop would satisfice |
| Use-when | Research/depth-analysis task with multiple distinct sub-questions; prior investigation was shallow; breadth-first one-pass coverage would miss depth |
| Do-NOT-use-when | Quick single-fact lookups; 1–2 question task with one known source (use `process-research` direct path); building or implementing |
| Dispatches | Fresh-context worker `Agent` dispatches (one per question cluster); one separate verifier `Agent` (description must contain "verifier") — generator and verifier are always distinct agents |
| Steps | Write backlog ledger file before any dispatch → dispatch fresh-context workers (parallel when independent) → dispatch separate verifier → loop FAIL units back → completion only when all ledger rows are VERIFIED or UNREACHABLE-VALID. Full procedure: [`skills/core/verification-gated-research/SKILL.md`](../../skills/core/verification-gated-research/SKILL.md) |
| Outputs | Backlog ledger `.md` at `Projects/[Name]/work/`; verified findings deliverable; all ledger rows in terminal state |
| Enforced by | `verifier-gate-check.py` (Stop hook — blocks completion when this skill was invoked but no separate-verifier Agent dispatch with "verifier" in description is found in the transcript) |

---

### verify

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: verify`; trigger: user says `/verify`, task-classifier routes with `MECHANISM: CoVe`, medium/low confidence in reasoning steps |
| Use-when | Verifying logic, reasoning steps, factual claims, or math in the current response |
| Do-NOT-use-when | Knowledge-dependent tasks (use external sources); framing/design decisions (use `ensemble`); already applied once this response (one-round limit) |
| Dispatches | None — inline CoVe application |
| Steps | Rate confidence per reasoning step → for medium/low steps: state claim → independently re-derive from first principles → flag contradictions → propagate revisions downstream. Apply once only. Full procedure: [`skills/core/verify/SKILL.md`](../../skills/core/verify/SKILL.md) |
| Outputs | Inline verification result: "No issues found." or enumerated contradictions/assumptions; `[NEEDS RESEARCH]` flags for missing data |
| Enforced by | process discipline (no dedicated hook) |

---

## Vault skills

### daily

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: daily`; `disable-model-invocation: true`; trigger: "daily note", "create daily", `/daily` |
| Use-when | Creating today's dated daily note in `Daily Notes/` |
| Do-NOT-use-when | Today's note already exists (reports the existing file instead) |
| Dispatches | None |
| Steps | Check if today's note exists → read `task_plan.md` for incomplete In-Progress tasks → create `Daily Notes/YYYY-MM-DD.md` with Tasks / Log / Notes / End-of-Day sections → report filename. Full procedure: [`skills/vault/daily/SKILL.md`](../../skills/vault/daily/SKILL.md) |
| Outputs | `Daily Notes/YYYY-MM-DD.md` |
| Enforced by | process discipline (no dedicated hook) |

---

### inbox

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: inbox`; `disable-model-invocation: true`; trigger: "process inbox", "sort inbox", `/inbox` |
| Use-when | Processing all notes in `Inbox/` — classify, tag, and route each |
| Do-NOT-use-when | Inbox is empty (reports that instead) |
| Dispatches | `vault-keeper` agent |
| Steps | Read every file in `Inbox/` → classify each (Task / Idea / Meeting note / Research / Personal) → add YAML frontmatter → rename kebab-case → move to correct folder → report one line per note. Full procedure: [`skills/vault/inbox/SKILL.md`](../../skills/vault/inbox/SKILL.md) |
| Outputs | Moved files with canonical frontmatter; one-line report per note |
| Enforced by | process discipline (no dedicated hook) |

---

### maintain

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: maintain`; trigger: "maintain", "clean up files", "organize work directory", "archive stale files", `/maintain` |
| Use-when | After a major project milestone when work/ files have accumulated; when work directory needs pruning |
| Do-NOT-use-when | Project has no `work/` directory; file count is small enough to handle inline without context risk |
| Dispatches | One general-purpose `Agent` (mandatory — reading all work files inline trashes main-session context) |
| Steps | Identify active project → read STATE.md → spawn agent with classification rules (KEEP / ARCHIVE / MERGE / DELETE) → agent presents classification table, executes moves, updates STATE.md Work Files section → review summary. Full procedure: [`skills/vault/maintain/SKILL.md`](../../skills/vault/maintain/SKILL.md) |
| Outputs | Archived files; updated STATE.md Work Files section; summary (X kept, Y archived, Z merged) |
| Enforced by | process discipline (no dedicated hook) |

---

### process-ingest

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-ingest`; trigger: `inbox-auto-ingest` hook on Inbox/ writes; manual invocation on Clippings/ or Inbox/ file |
| Use-when | A raw source document needs integration into the LLM-Wiki layer (Karpathy Ingest operation) |
| Do-NOT-use-when | Source already has `#wiki` tag (update, not ingest); source is a Daily Note (stays raw layer); source is a `.claude/` infra file (schema layer); quick one-line edits |
| Dispatches | None — runs inline with Read/Write/Edit tools and optional `qmd` MCP query |
| Steps | Read raw source → compute SHA-256 (M2 crypto binding) → search wiki for related pages via qmd or index.md → hard citation gate (CITATION_NOT_FOUND halts on missing support) → write wiki page with `source:` field + `wiki_status: bootstrap` → update 3-10 related wiki pages → update `Resources/KB/index.md` → append `log.md` entry → move raw source from Inbox/ if applicable. Full procedure: [`skills/vault/process-ingest/SKILL.md`](../../skills/vault/process-ingest/SKILL.md) |
| Outputs | INGEST REPORT block (SHA, pages created/updated, citation counts, log entry number, status); wiki page(s) in `Resources/KB/` or `Notes/`; `log.md` append |
| Enforced by | `wiki-citation-check.py` (PostToolUse Write hook — blocks any Write to a `#wiki`-tagged file missing `source:` field or with SHA mismatch) |

---

### process-lint

| Field | Value |
|---|---|
| Type | process |
| Frontmatter | `name: process-lint`; trigger: user says `/process-lint`, "run lint", "check wiki health"; weekly cadence reminder from the maintainer's SessionStart cadence hook (not shipped in this repo) |
| Use-when | Periodic wiki-layer health check; after bulk ingest (10+ pages); before promoting bootstrap entries to ratified |
| Do-NOT-use-when | Wiki has zero pages; verifying a single specific claim (`process-qa`); intending to fix problems (lint is read-only) |
| Dispatches | None — reads all wiki pages inline |
| Steps | Inventory all `#wiki`-tagged files → Pass A (citation validation: file existence + SHA match + anchor + content overlap) → Pass B (orphan wiki pages: missing `source:`) → Pass C (index completeness: `Resources/KB/index.md` gaps) → Pass D (log continuity: `log.md` unlogged pages) → Pass E (stale pages: hash change + old `updated` date) → write lint report to `work/` → append LINT log.md entry. Full procedure: [`skills/vault/process-lint/SKILL.md`](../../skills/vault/process-lint/SKILL.md) |
| Outputs | LINT REPORT block (total pages, citation_resolve_rate, error/warning/advisory counts, report path, log entry); dated `.md` lint report in `Projects/[Name]/work/` |
| Enforced by | process discipline (no dedicated hook; the maintainer's SessionStart cadence hook — not shipped in this repo — emits a reminder when last lint > 7 days) |

---

### save (vault)

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: save`; trigger: user says `/save`, asks to checkpoint, wants to persist progress before ending a session |
| Use-when | End-of-session or end-of-milestone state persistence |
| Do-NOT-use-when | No active project (nothing to save to) |
| Dispatches | None |
| Steps | Identify active project → update STATE.md (status / built / next / decisions / work files) → optionally promote to PROJECT.md → optionally mark task_plan.md items → save reusable knowledge to memory files (with type/confidence/expiry schema) + append to `memory-log.jsonl` → update MEMORY.md → report what was saved. Full procedure: [`skills/vault/save/SKILL.md`](../../skills/vault/save/SKILL.md) |
| Outputs | Updated STATE.md; optionally updated PROJECT.md and task_plan.md; new or updated memory files; `memory-log.jsonl` entries; MEMORY.md update |
| Enforced by | process discipline (no dedicated hook) |

---

### standup

| Field | Value |
|---|---|
| Type | utility |
| Frontmatter | `name: standup`; trigger: "standup", "what's in progress", `/standup` |
| Use-when | Quick session-start orientation or status check |
| Do-NOT-use-when | Full project checkpoint needed (use `/pm` instead) |
| Dispatches | None |
| Steps | Read `task_plan.md` and active project briefs → output bullet-point summary (In Progress / Blocked / Up Next). Full procedure: [`skills/vault/standup/SKILL.md`](../../skills/vault/standup/SKILL.md) |
| Outputs | Three-section bullet list |
| Enforced by | process discipline (no dedicated hook) |

---

## Domain-example skills

Domain examples ship as adapters that apply core framework process to a specific platform. They are not full process skills — each is a reference/guide document loaded as context when the operator works with that platform. Full per-skill sections are omitted; the summary table below covers all 19.

| Skill | Platform | One-line purpose |
|---|---|---|
| `apify-actor-development` | Apify | Develop, debug, and deploy Apify Actors for scraping and automation |
| `apify-actorization` | Apify | Convert existing JavaScript/TypeScript or Python projects into Apify Actors |
| `apify-audience-analysis` | Apify / social | Analyse audience demographics and behaviour across major social platforms |
| `apify-brand-reputation-monitoring` | Apify / review sites | Track reviews, ratings, and brand sentiment across Google Maps, TripAdvisor, Facebook, and others |
| `apify-competitor-intelligence` | Apify / social | Analyse competitor content, pricing, ads, and market positioning |
| `apify-content-analytics` | Apify / social | Measure engagement metrics and campaign ROI across social platforms |
| `apify-ecommerce` | Apify / e-commerce | Scrape pricing intelligence, reviews, and seller data from Amazon, Walmart, eBay, and others |
| `apify-influencer-discovery` | Apify / social | Find and evaluate influencers and track collaboration performance |
| `apify-lead-generation` | Apify / web | Generate B2B/B2C leads by scraping Google Maps, social platforms, and search results |
| `apify-market-research` | Apify / web | Analyse market conditions, geography, pricing, and product validation |
| `apify-trend-analysis` | Apify / social | Discover and track emerging trends across Google Trends and social platforms |
| `apify-ultimate-scraper` | Apify / web | General-purpose Apify scraper for platforms not covered by specialised skills |
| `n8n-code-javascript` | n8n | Write JavaScript in n8n Code nodes with correct `$input`/`$json`/`$node` syntax |
| `n8n-code-python` | n8n | Write Python in n8n Code nodes with correct `_input`/`_json`/`_node` syntax |
| `n8n-expression-syntax` | n8n | Validate and fix n8n `{{}}` expression syntax errors |
| `n8n-mcp-tools-expert` | n8n / MCP | Guide effective use of n8n-mcp MCP tools for node search, validation, and configuration |
| `n8n-node-configuration` | n8n | Operation-aware node configuration guidance and property-dependency resolution |
| `n8n-validation-expert` | n8n | Interpret validation errors and guide fixes including false-positive handling |
| `n8n-workflow-patterns` | n8n | Proven architectural patterns for n8n workflow design |
