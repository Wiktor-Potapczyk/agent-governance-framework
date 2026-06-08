# Changelog

## 2026-06-08 — Governance-log miner skill + opt-in routing-table validation hook

### Skills

- **`skills/core/process-governance-mine/` (new):** Weekly retrospective skill that mines `governance-log.jsonl` for recurring failure patterns and emits a proposal artifact (`YYYY-MM-DD-governance-mine-proposals.md`). Proposal-only invariant: reads everything, writes exactly one content file. Complements `/hookify` (reactive, per-correction) with an aggregate view over a rolling 30-day window. High-severity gate C=3 (fabrication_detected, dark-zone with severity=high); normal gate C=10/D=3. Sig suppression via `miner-resolved.jsonl` ledger; regression detection automatic when a suppressed sig re-occurs above threshold. Core skill count: 16 → 17.

### Hooks

- **`hooks/mine_governance.py` (new helper) + `hooks/test_mine_governance.py` + `hooks/_test_fixtures/governance-log-sample.jsonl` + `hooks/_test_fixtures/miner-resolved-fixture.jsonl`:** Pure-stdlib miner implementation used by the `process-governance-mine` skill. Not an enforcement hook — never registered in settings. 39 tests covering recurrence gating, normalization, severity logic (D1 dark-zone per-record severity, D2 noise-event relabeling, D5 fraction-vs-path normalization), regression detection, suppression, and adversarial malformed-input robustness.
- **`hooks/disabled/routing-table-validation.py` (new, opt-in) + `hooks/disabled/test_routing_table_validation.py`:** PreToolUse Edit|Write|MultiEdit hook that denies edits to `CLAUDE.md` or any `SKILL.md` introducing a broken dispatch-name reference. Four gates: (a) target-file class, (b) dispatch-position detection (MUST DISPATCH: lines, subagent_type: fields, routing-table rows), (c) agent-name shape, (d) registry lookup. Fail-open on any ambiguity. Ships **unregistered** in `hooks/disabled/` — copy to active hooks dir and register in settings to arm. `DEPRECATED_ALLOWLIST` is empty by default; add retired agent names there to prevent false positives after renames.

## 2026-06-02 — Enforcement boundary-test harness + C5 structural gate + slop linter + 2 skills

A governance-hardening batch: closes the over-application root-cause workstream (BLOCK hooks blocking valid output) and the structural-gate family, plus two new process skills and a write-stage prose linter.

### Hooks

- **`hooks/prose-slop-check.py` (new) + `test_prose_slop_check.py`:** PostToolUse Write|Edit linter that flags LLM-slop vocabulary (delve / tapestry / multifaceted / furthermore / foster …) in generated prose. WARN-only (never blocks); calibrated against a corpus to 0 false-positives. Scoped to wiki/work prose, not code.
- **`hooks/subagent-quality-check.py` (fix) + `hooks/_subagent_quality_logic.py` (extracted) + `test_subagent_quality_check.py`:** fixed two over-application bugs found by the boundary harness — CHECK 2 no longer blocks a short *negative finding* that contains a refusal keyword ("I cannot reproduce the bug; it works on main." is a result, not a refusal) when a result-signal token co-occurs; CHECK 3 now accepts `Label: value` report blocks and known REPORT headers (QA/PENTEST/PM CHECKPOINT) as a structure type, so an unfenced report from a sub-agent passes. Detection logic extracted to a shared, test-covered helper.
- **`hooks/registry-staleness-check.py` (new):** SessionStart advisory — warns (non-blocking) when `registry.json` is older than a threshold, naming the regen command. Silent when fresh.

### Scripts

- **`scripts/structural_gates.py` (new) + `hooks/test_structural_gates_c5.py`:** the C1–C5 structural-gate family. C5 (new this batch) verifies every dispatch name in the compliance hooks resolves to a live registry agent/skill/alias/deprecation — guards the "agent silently dropped from the dispatch allow-list" regression class. WARN-class; FP-guarded against intentional phantoms.
- **`scripts/run_boundary_tests.py` (new):** coverage reporter for the BLOCK-hook false-positive guards — every BLOCK-class hook must carry named `test_fp_*` guards proving it stays silent on valid-but-superficially-suspicious input. Reports 8/8 covered.
- **`scripts/generate_registry.py` (new):** regenerates the agent/skill registry and now emits a plugins manifest (installed-plugin inventory + enabled-state) alongside agent/skill counts.

### Skills

- **`skills/core/db-migration-plan/` (new):** pre-migration planning skill — expand→migrate→contract sequencing, narrated index strategy, batched backfills, explicit rollback + point-of-no-return, verification checklist. Plans DDL; does not run it.
- **`skills/core/process-postmortem/` (new):** post-failure root-cause skill — timeline → proven root cause → contributing factors → prevention items fed back into hooks/memory. Distinct from the pre-ship QA/pentest gates.

### Docs/template

- `CLAUDE.md` — added the **dead-code sub-rule** (clean only the orphans your own edit created), **declarative-first for Build** (write the check before the implementation), and a **loop-tool selection** block (`/goal` for condition-gated, `architect-loop`/`verification-gated-research` for context-rot-sensitive research, `/workflows` for many-independent-unit fan-out, `/loop` for session-state maintenance).

## 2026-06-01 — `type: schema-doctrine` source exemption + citation-parser fix

Follow-up to the 2026-05-31 `type: generated` exemption. The SHA-256 citation binding (anti-fabrication) breaks not only for script-generated files but also for **hand-edited doctrine** files revised more than weekly (e.g. a governance constitution) — the pinned hash drifts on every edit. But unlike generated output, hand-edited doctrine is genuinely *mis-citable*, so a blanket SHA-skip would be an escape hatch. The resolution: a stricter exemption that drops the volatile whole-file hash but enforces cited-anchor existence.

### `hooks/_wiki_citation_logic.py`

- **New `type: schema-doctrine` handling in `validate_source_entries`:** skips the whole-file SHA drift-gate, but REQUIRES (a) `path` existence AND (b) the cited `anchor` heading to literally exist in the source file. Missing `anchor` field → `MISSING_ANCHOR` (blocking); anchor heading absent → `ORPHAN_ANCHOR` (blocking). Stricter than `type: generated` (path-only), because doctrine is mis-citable where deterministic script output is not. Anchor-existence is a cheap fabrication check that whole-file hashing never provided.
- **`parse_source_field` two-bug fix (latent in both the hook and any lint reusing it):** (1) the source-block collector dropped list items sitting at **zero indent** (only items indented under `source:` were collected); (2) the entry parser could not read the YAML **inline-flow** form `- {path: X, type: Y, anchor: Z}` — only the block-list form. A page using inline-flow therefore parsed as sourceless → false `MISSING_SOURCE`. Both forms now parse; values containing colons (timestamps) survive.
- Knowledge-base utility/catalog basenames (`README.md`, `tag-registry.md`, `dataview-queries.md`) added to `EXCLUDE_FILES` — navigational catalogs are not syntheses of raw docs, so a `source:` citation is meaningless for them (same class as `index.md`).

### `hooks/test_wiki_citation_logic.py` — new test suite (46 tests)

Added to the framework's hook test set (the citation logic was previously untested in-repo). Covers the inline-flow parser, block-list parity, and the full `type: schema-doctrine` matrix (existing anchor clean, stale-sha ignored, fabricated anchor → `ORPHAN_ANCHOR`, missing anchor → `MISSING_ANCHOR`, missing file → `ORPHAN_CITATION`).

### Docs/template

- `CLAUDE.md` — added `schema-doctrine` to the source `type` enum, a `type: schema-doctrine` exemption paragraph, and updated Wiki Layer Invariants #2/#3 (anchor enforcement + both source-form parsing + `ORPHAN_ANCHOR` finding).
- `skills/vault/process-ingest/SKILL.md` + `skills/vault/process-lint/SKILL.md` — documented the `schema-doctrine` exception alongside `generated`.

## 2026-05-31 — Governance self-logging instrument + type:generated source exemption + doc/template sync

### `hooks/_governance_logger.py` — new shared helper (E1 silent-zero fix)

`governance-log.py` (Stop hook) records Agent/Skill tool_use and turn classifications but is blind to hook firings — registered, actively-firing hooks showed 0 events in utilization audits ("silent-zero" finding). This module gives any hook a one-line way to append its own firing record to `hook-activity.jsonl`.

Failure-tolerance: `log_fire` never raises. Instrumentation failure silently no-ops and never crashes the host hook.

### `log_fire` wired into 5 hooks

The adoption snippet (try/except around import + `log_fire("<hook-name>")`) inserted into:

- `classifier-field-check.py` — after `stop_hook_active` guard
- `dispatch-compliance-check.py` — after `stop_hook_active` guard
- `work-verification-check.py` — after `stop_hook_active` guard
- `skill-routing-check.py` — after payload parse, before tool_input read
- `agent-registry-check.py` — after payload parse, before agent_type extract

All 6 modified files pass `python -m py_compile`.

### `type: generated` source exemption

Auto-generated sources (script outputs such as `registry.json`) are live data that changes on every regeneration. SHA-pinning them causes perpetual false `SOURCE_DRIFT`. The exemption skips the SHA truth-gate for `source[]` entries where `type: generated` while still enforcing path existence.

**Three surfaces updated:**

- `hooks/_wiki_citation_logic.py` — `validate_source_entries` skips hash check when `entry.get("type") == "generated"`
- `CLAUDE.md` — `type: generated` added to the `type:` enum in the wiki source-citation schema, with doctrine paragraph explaining the exemption
- `skills/vault/process-ingest/SKILL.md` — Step 2 SHA computation adds "Exception — type: generated" note; `type` enum in the Step 5 frontmatter template extended
- `skills/vault/process-lint/SKILL.md` — Pass A SHA hash check step adds skip note for `type: generated` entries

### `context-fill-log.py` archived

The file's own module docstring says "DO NOT REGISTER THIS HOOK" and it is a no-op stub. Moved to `_archived/hooks/context-fill-log.py` (new directory). References in CHANGELOG/architecture/hooks README are doc-only and preserved.

### `settings/settings.json.template` — 11 new hook registrations

Hooks that existed in `hooks/` but were missing from the template are now registered:

| Hook | Event | Notes |
|------|-------|-------|
| `session-start-log.py` | SessionStart | Session boundary marker for analytics |
| `session-start-orientation.py` | SessionStart | Active project STATE.md orientation |
| `user-prompt-state-inject.py` | UserPromptSubmit | Throttled re-orientation on long sessions |
| `wiki-citation-check.py` | PostToolUse Write\|Edit | M2 Layer 2 wiki citation validation |
| `inbox-auto-ingest.py` | PostToolUse Write\|Edit | LLM-Wiki ingest auto-trigger on Inbox writes |
| `checkpoint.py` | PostToolUse (all) | Periodic save checkpoint reminder |
| `bias-guard.py` | SubagentStart | Blind Analysis Rule injection for evaluator agents |
| `epistemic-check.py` | Stop | Haiku-evaluated overconfidence gate |
| `verifier-gate-check.py` | Stop | verification-gated-research skill contract enforcement |
| `task-plan-auto-sync.py` | Stop | QA PASS → task_plan.md auto-mark-done |
| `pre-compact.py` | PreCompact | State save before compaction (new PreCompact section) |

`weekly-usage.py` not registered — depends on the `claude_monitor` third-party package; opt-in for users who install that dependency.

### Documentation sync

- `README.md` — hook count updated from 17 to 28
- `docs/architecture.md` — Component Counts table updated (28 active hooks, 2 shared libraries, stub moved to archived)
- `hooks/README.md` — summary line updated (28 hooks, 8 event types), rows added for all 11 new hooks

---

## 2026-05-12 — H-4 v1.3 polish + code-simplifier agent

Ports two artifacts from the source workspace:

### `hooks/task-plan-auto-sync.py` — v1.2 → v1.3

Refactor + diagnostic-label clarification bundle. No behavioral change on the regex-only path (`H4_ENABLE_HAIKU=0` default). When the Haiku fallback is enabled:

- **Outcome labels:** `outcome="error"` now indicates non-zero subprocess exit (was `miss`); `outcome="interrupted"` now indicates user Ctrl-C during subprocess (was `miss`). Full enum: `hit | miss | error | timeout | invalid_output | cli_absent | interrupted`.
- **Write-path refactor:** the dedup → undo → apply → verify → record SYNCED sequence (previously duplicated across Haiku and regex branches in `main()`) is now a single helper `_execute_sync(match, assistant_text, source_label)`. Both call sites collapse to one line. SYNCED log lines now emit `SYNCED (regex)` / `SYNCED (haiku)` for attribution.
- **HAIKU_SINK rotation (LOW-1):** sink at `.claude/hooks/aggregates/h4-haiku-fallback.jsonl` rotates at 1 MB OR 30 days mtime age. Rotated archive name: `h4-haiku-fallback.jsonl.YYYY-MM-DD.<pid>` (PID suffix prevents same-date parallel-rotation collisions). Best-effort: any rotation exception is logged and swallowed; append never fails due to rotation.
- **QA-block-aware excerpt slicing (LOW-2):** Haiku fallback excerpt previously took `assistant_text[:EXCERPT_MAX]` (head 1500 chars), which could miss the QA REPORT block if it appeared past char 1500. Now prefers `extract_qa_block(assistant_text)` and falls back to head-slice only if no QA REPORT marker is found.
- **Selftest production-JSONL isolation (MED-4):** all `T-SM-HAIKU-MOCK-*` sub-tests run inside `_mock.patch(f"{__name__}._write_haiku_sink")` so no selftest entry can leak to the production JSONL sink. The `T-SM-HAIKU-MOCK-ISOLATION` sub-test asserts pre/post HAIKU_SINK byte count equality.

Selftest grew 15 → 19 cases (new: `T-SM-HAIKU-MOCK-E` for error outcome, `T-SM-HAIKU-MOCK-ISOLATION`, `T-SM-HAIKU-ROTATE`, `T-SM-HAIKU-EXCERPT-QA`). All 19 PASS.

### `agents/code-simplifier.md` — new (inspired-by Daisy Hollman)

Mechanical-tidiness specialist for write-stage cleanup AFTER substantive edits. Scope is **explicitly NOT architecture/SOLID/security** — those belong to `architect-review`. Scope IS: formatting consistency, dead code, leftover debug, naming consistency after rename, expression-syntax cleanup. On-demand only (no auto-trigger) to keep usage cost predictable.

Five refinement principles: preserve functionality / apply project standards / enhance clarity / maintain balance (don't over-simplify into cleverness) / focus scope (only touch what the current session touched).

Output format is diff-proposal (`File:` / `Why:` / `Before:` / `After:` blocks). Does not write to disk unless dispatching agent explicitly says "apply." If architectural smells are found, agent flags `OUT OF SCOPE — route to architect-review:` and stops.

Inspired-by attribution: `anthropics/claude-code/plugins/pr-review-toolkit/agents/code-simplifier.md` (Daisy Hollman, Anthropic). This port is re-skinned for generic project artifact classes — not a verbatim port.

### Not ported

A vault-personal Stop hook that detects idle-wait verdicts in assistant text and cross-references reversible open task_plan items, but its core detection regexes are hardcoded to a specific user-name marker pattern. Porting requires genericization to a user-configurable name template (e.g., env-var `H_USER_NAME` + templated regex generation) — meaningful work that wasn't in scope for this turn. Filed as backlog for a future framework distribution increment.

---

## 2026-05-11 — Knowledge Base Wiki adoption + n8n patterns extension + CLAUDE.md doctrine sync

This release ports the Karpathy LLM-Wiki Architecture pattern from the source project into the framework as an OPTIONAL adoption track, adds the n8n REPO-INTEL operational patterns + revises Two-Phase Orchestration to autonomy-first, codifies the Explicit Imperative fast path inline in `CLAUDE.md` (previously deferred from 2026-05-07), and adds Inbox Rule 6 for Ingest as a conditional rule that pairs with the new wiki track.

### Knowledge Base Wiki (OPTIONAL adoption)

New section in `CLAUDE.md` documenting the Karpathy LLM-Wiki pattern — three layers (raw/wiki/schema), three operations (Ingest/Query/Lint), and utility files (`Resources/KB/index.md`, `log.md` at workspace root). Adoption is OPTIONAL because it requires user setup (qmd MCP or equivalent search engine, `process-ingest`/`process-lint` skills, source-citation schema). Adopting it converts a "vague dumpster" of unread inbox notes into a structured, citation-backed knowledge layer.

### Wiki Layer Invariants (OPTIONAL — pairs with Knowledge Base Wiki)

New section in `CLAUDE.md` documenting the three enforcement layers that protect wiki integrity against LLM fabrication: skill-level hard gate in `process-ingest` (SHA-256 source binding before write); hook-level write check via `wiki-citation-check.py` (verifies citation paths exist + SHA matches at every write); lint-level periodic check via `process-lint` Pass A. Plus bootstrap-mode threshold: new wiki pages start `wiki_status: bootstrap`, user ratifies them, ≥10 ratified entries unlocks full LLM-authorship.

### n8n Workflow Patterns (OPTIONAL — for n8n users)

New section consolidating the upstream n8n discipline:

- **Core (ROMUALD-LEARN-R3):** Spiral Method (3-5 nodes per increment), validation sandwich, `update_partial_workflow` over `update_full_workflow`, `get_node_essentials()` over `get_node_info()`, webhook lifecycle gate, live workflow > cached file.
- **Operational (REPO-INTEL extension):** `patchNodeField` for single-field edits, IF/Switch `addConnection` branch parameter requirement, Code node `pairedItem` for non-1:1 outputs, SplitInBatches inverted output naming, cross-iteration accumulation via `$getWorkflowStaticData('global').accumulator`, `n8n_autofix_workflow` preview-first, `__rl` `cachedResultName` requirement, AI agent sub-workflow security P1-P5.

### Two-Phase Orchestration — revised (autonomy-first)

Supersedes the 2026-05-07 mandatory-human-gate version. Phase 1.5 (Conditional Human Gate) is now only fires if the blueprint contains explicit `FLAG:` lines or the architect cannot classify entry conditions for Phase 2's autonomous loop. Default: NO human gate at design-time. Mandatory human gate now lives at Phase 3 (Promotion Gate) — before re-enabling destructive output nodes AND before flipping a workflow to `active: true`. Rationale: Czlonkowski's autonomous webhook QA loop (POST test payload → read execution → diagnose → patch via `patchNodeField` → re-trigger, iteration cap 10) closes the catch-misunderstanding function the prior mandatory blueprint review provided. HITL frequency was a goal failure under the prior design; HITL belongs at irreversible-action boundaries, not every phase transition.

### CLAUDE.md — Explicit Imperative fast path codified inline

The 2026-05-07 changelog noted: "the corresponding `skills/core/task-classifier/SKILL.md` content update is deferred to the next increment." Partially landed here: the `CLAUDE.md` CRITICAL RULE: Task Classification section now describes the Step 3a fast path inline. The full `task-classifier/SKILL.md` content edit remains in backlog.

### Inbox Rule 6 (Ingest, conditional)

Inbox Processing Rules grow from 5 to 6. Rule 6 ("Ingest") fires after classify+route per rules 1-5, invokes `process-ingest`. Auto-triggered by `inbox-auto-ingest.py` hook on Inbox/ writes when the Knowledge Base Wiki track is adopted. Marked OPTIONAL so users without the wiki track can skip it.

### Distribution rationale

These additions are all OPTIONAL adoption tracks — they don't change framework behavior for users who don't adopt them. The framework's core (Working Philosophy, CRITICAL RULEs, Process skills, QA tiers) is unchanged. Users opting in get a path from "inbox dump" to "structured knowledge base", and n8n users get the upstream discipline that the source project derived empirically.

---

## 2026-05-07 — ADOPT-2 Skill Retrofit + Two-Phase Orchestration + Classifier Calibration

This release closes the ADOPT-2 skill-format adoption deferred in the 2026-04-21 sprint (per that release's "Deferred" note), ships a generalizable two-phase agent orchestration pattern with human gate, recalibrates the classifier for explicit imperatives, hardens compaction-snapshot framing, retracts an aspirational claim about decay-scoring infrastructure, and reconciles cross-document inventory drift across README/architecture/INSTALL/hooks-README.

### Skills — ADOPT-2 retrofit complete (19/19)

All 19 vault-owned core + vault-management skills updated to the standardized 3-section format:

- **Use-when** — when to invoke this skill
- **Do-NOT-use-when** — boundaries, with skip-rules referencing equivalent skills
- **Gotchas** — common failure modes specific to this skill (not boilerplate)

Format derived from architect-reviewer feedback during the pilot (`save`, `architect-loop`); architect-flagged anti-boilerplate constraints applied across the scale-out (no copy-paste rationales — each skill's Gotchas reflect its actual failure modes). Two pre-existing strict-YAML errors discovered and fixed during pentest: `ensemble/SKILL.md` and `verify/SKILL.md` had unquoted `MECHANISM: Ensemble` / `MECHANISM: CoVe` substrings that PyYAML `safe_load` rejected (Claude Code's runtime parser is lenient and skills loaded fine, but strict YAML tooling broke). Fix: quoted descriptions and replaced internal `MECHANISM:` colons with space-separated `MECHANISM `.

### Classifier — Step 3a Explicit Imperative Fast Path

Empirical observation: the classifier over-classified small explicit fixes (`rename X to Y`, `move X to Y`, `fix typo`, `delete unused X`, `add line W`, `rerun X`) as Analysis, triggering the full process skill + QA + PM dispatch chain on one-line edits. Governance-log analysis showed disproportionate ceremony cost on this task class.

**New Step 3a (precedes Step 3 Quick Check):** if the prompt matches an Explicit Imperative pattern, the burden of proof flips — default to Quick. Auto-escalate only if a depth signal is also present (composed depth ask, hypothesis preamble, "are you sure?" pattern, ambiguous target needing investigation).

This does not weaken Step 3's burden of proof for general ambiguity — it explicitly recognizes a class where ambiguity does NOT exist (the imperative names target and action precisely). Documented in `docs/architecture.md` Layer 0; the corresponding `skills/core/task-classifier/SKILL.md` content update is deferred to the next increment.

### Compaction snapshots — HISTORICAL REFERENCE framing

Compaction snapshots that survive into post-compaction sessions (via SessionStart `<persisted-output>`) were being read as authoritative current state. Caught after several sessions made decisions citing stale frame-targets, project IDs, or file paths.

**Fix:** SessionStart now wraps every persisted snapshot with an explicit `HISTORICAL REFERENCE ONLY (PRE-COMPACTION SNAPSHOT)` preamble and a closing reminder to verify against the live system. Frames the snapshot as a pointer set (this is what was being worked on) rather than a fact set (this is what is true now). No hook-code change — content-only wrap at the snapshot generation site. Documented in `docs/architecture.md`.

### Two-phase agent orchestration — generic pattern documented

For agent work where discovery/design and implementation must be separated by a human review gate (originally implemented for n8n workflow building), the framework now codifies a two-phase pattern in `docs/architecture.md`:

- **Phase 1 — Architect agent** owns discovery, template selection, design decisions, validation planning. Produces a `.md` blueprint with milestones (3-5 sub-steps each) and per-milestone validation checkpoints. Architect makes ZERO implementation moves.
- **Human gate** — blueprint frontmatter `status:` is `#pending-human-review` until the user flips it to `#approved` (verbal approval flips the field via Edit; manual flip also accepted).
- **Phase 2 — Builder agent** reads blueprint, refuses to run if `status` is anything other than `#approved`, implements EXACTLY per blueprint milestone-by-milestone, validates after every 3-5 sub-steps, STOPS and reports on any blueprint gap or validation failure.

Trust loop: the blueprint is human-readable in ≤30 seconds. If the architect misunderstood, the user catches it before any sub-step is built wrong. Per-milestone validation prevents error accumulation across long builds. The pattern is opt-in — for trivial single-step tasks, direct dispatch remains correct.

### Retraction — score-memory.py decay-scoring claim

The 2026-04-13 release referenced `score-memory.py` as a scheduled task for decay-based memory retirement. Empirical audit 2026-05-07: the script never existed in the repo or vault. The claim was aspirational and propagated across multiple cited locations. Decision: RETIRE rather than BUILD — there is no active dependency that requires the script, and the lifecycle-status memory schema fields (`status`, `superseded_by`, `last_accessed`) shipped 2026-04-21 supersede the original decay-scoring intent with a more deterministic mechanism. The 2026-04-13 entry's B3 line (line 124 below) was previously corrected with a parenthetical retraction; this release captures the position formally.

### Documentation drift — reconciled

Cross-document inventory drift discovered and fixed:

- `hooks/README.md` table referenced 3 files that do not exist in the repo (`check_forbidden_tokens.py`, `agent-registry-check.py`, `token-breakdown.py`) and omitted 3 active files (`context-fill-log.py` as a stub note, `session-start-log.py`, `epistemic-check.py`). Fixed.
- Component counts disagreed across `README.md`, `docs/architecture.md`, `INSTALL.md`, `hooks/README.md` (5 mismatches: agent count claimed as 25/29, hook count claimed as 12/18, etc.). Reconciled to filesystem-verified canonical values: 17 active enforcement hooks + 1 shared library (`sidecar_loader.py`) + 1 deferred stub (`context-fill-log.py`) + 4 disabled hook scripts (3 Python + 1 PowerShell); 29 governance agents in `agents/governance/` (one duplicate at `agents/pm-orchestrator.md` — see findings below); 12 core + 5 vault + 19 domain-examples skills.

### Documented findings (not fixed in this release)

- `agents/pm-orchestrator.md` is duplicated at `agents/governance/pm-orchestrator.md` — single canonical location not yet decided.
- `skills/save/` exists at `skills/` top level and at `skills/vault/save/` — likely a stray duplicate of the vault skill.
- `agents/domain-examples/` is empty — placeholder for future domain-example agent additions; INSTALL.md and README.md updated to describe it accurately.
- `hooks/disabled/` contains older copies of `agent-dispatch-check.py` and `epistemic-check.py` whose live counterparts also exist at `hooks/` — clarify-or-remove decision deferred.

### Deferred (next increment)

- Skill-content updates for Step 3a (`skills/core/task-classifier/SKILL.md`) and ADOPT-2 format propagation to framework-repo's own `skills/core/process-*/SKILL.md` files — content drift is a separate concern from doc drift addressed here.
- Shipping `n8n-workflow-architect.md` + `n8n-workflow-builder.md` as `agents/domain-examples/n8n/` reference implementations of the two-phase orchestration pattern.

## 2026-04-21 — Workflow Discipline + Adoption Sprint

### New CRITICAL RULEs
- **Task Plan Alignment** — at session start, verify the top-of-queue task_plan.md item still matches STATE.md Next.
- **Task Plan Sync** — update task_plan.md as part of every non-Quick task completion; the task is not complete until task_plan.md is synced.
- **/rewind discipline** — prefer /rewind for wrong/suboptimal answers over inline correction, unless the mistake will be referenced in subsequent turns or delegated agent prompts.

### Hooks
- `memory-schema-check.py` — added 3 optional lifecycle fields (`superseded_by`, `last_accessed`, `status`) with validation for date format and .md-filename-only refs. 73 existing memory files remain valid.
- `settings.json` — hardened pre-compact hook command to full `python.exe` absolute path to avoid Windows Store stub hazard.
- New PreToolUse Write|Edit matcher: forbidden-tokens grep gate (`check_forbidden_tokens.py` + `forbidden-tokens.json`) with project-level override support.

### Agents
- `pm-orchestrator.md` — Checkpoint Protocol body extended: "5 Questions + Re-Rank". Added mandatory "Re-Ranked Next-3-Tickets" output block with promotion/demotion tracking.

### Documented findings
- implementation-plan agent fabricates Bash + Read tool output, not only Write confirmations. Mitigation documented: always run main-session Glob to establish authoritative inventory before passing plans to downstream agents.

### Deferred
- Skill header retrofit (Use-when / Do-NOT-use-when / Gotchas sections across all SKILL.md files) — attempted and halted in planning: implementation-plan agent's fabricated inventory could not be trusted; ground-truth Glob by the orchestrator is required before re-attempt.

## 2026-04-19 — H11 Integration + Observability v2 Hook Fixes

### H11 integration shipped — post-compaction enforcement blind spot closed

The 2026-04-18 sidecar POC (`sidecar_loader.py` + `process-build/DISPATCHES.json`) is now wired into `dispatch-compliance-check.py` as a fallback when transcript classification blocks fall outside the hook's 200 KB read window (the canonical post-compaction bypass vector).

**Hook changes:**

- `hooks/dispatch-compliance-check.py` — 4 surgical edits:
  1. Import block: `sidecar_loader.mandatory_agent_names` with graceful `_SIDECAR_AVAILABLE` fallback on `ImportError`.
  2. Unconditional tool_use tracking: `all_dispatched` + `recent_process_skill` populated regardless of `found_contract`, feeding the fallback path without affecting the existing contract-present flow.
  3. Post-loop fallback: when the scan yields no contract but a `process-*` skill was invoked, load the skill's `DISPATCHES.json` and enforce its `mandatory_dispatches` list. Emits `h11_sidecar_fallback_activated` event for observability.
  4. Q4 gap closed (caught by adversarial review): terminal skills (`process-qa`, `process-pentest`) are excluded from overwriting `recent_process_skill`. Without this, invoking a terminal skill after a planning/build skill would nullify enforcement for the earlier skill.

**Sidecar files added:**

- `hooks/sidecar_loader.py` — POC shipped 2026-04-18 but never synced to this repo. Now present.
- `skills/core/{process-build,process-planning,process-research,process-analysis,process-qa,process-pentest}/DISPATCHES.json` — machine-readable dispatch contracts for all 6 process skills. Mandatory lists: process-planning `[implementation-plan, architect-reviewer, adversarial-reviewer]`; process-build `[implementation-plan, blueprint-mode, architect-reviewer]`; process-research `[report-generator]`; process-analysis / process-qa / process-pentest have empty mandatory lists (analysis is subject-dependent; qa/pentest are terminal).

**Verification:**

- Syntax: `ast.parse` on the modified hook exits 0.
- 4 behavioral tests (synthetic JSONL transcripts): fallback fires on process-planning invocation with missing mandatory dispatches (BLOCK); Quick silent on no-classification-no-skill session; existing contract-present path unchanged; Q4 regression test — planning-then-qa still enforces planning's mandatory list.
- 6/6 sidecars load via `sidecar_loader.py` self-test.

### Observability v2 — Ralph Loop implementation shipped (separate track)

A Ralph Loop earlier 2026-04-19 wired 6 P0 telemetry events + dashboard alert infrastructure. 7 iterations, all P0 events proven emitting. NOT included in this commit set — those hook edits live in the vault's `.claude/hooks/` and will propagate in a subsequent sync.

### Pattern captured — sidecar-file contracts for post-compaction enforcement

The combination (a) hook-based dispatch enforcement in an AI agent orchestration framework + (b) per-skill JSON sidecar as fallback when conversation history is compacted + (c) terminal-skill exclusion to prevent state-tracker overwrite nullification — does not appear in the public literature surveyed. Constituent components have precedent (sidecar configs: pre-commit, Conftest, Terraform state, Microsoft agent-governance-toolkit; file-fallback: solved in infrastructure-as-code but not agent governance; terminal-skill exclusion: no analog found). The assembly is novel in the agent-governance context. See the research repo insight `sidecar-files-for-post-compaction-enforcement.md` for the full write-up.

## 2026-04-18 — Infrastructure Audit Sprint (7 HIGH fixes + 4 adversarial-review fixes)

Comprehensive infrastructure audit across 5 surfaces (hooks, agents, skills, CLAUDE.md/MEMORY.md, cross-component deps) followed by Opus-4.7 adversarial self-review. 7 HIGH findings shipped + 4 additional bugs caught by adversarial review. 112/112 regression tests pass.

### Hook fixes shipped

- **H3 — `dispatch-compliance-check.py`:** Reject `MUST DISPATCH: none` on non-Quick tasks. Keystone fix — breaks the composed B1+B2+B3 enforcement bypass (fenced classification + empty dispatch + inline QA REPORT).
- **H5 — `work-verification-check.py`:** New CHECK 1b blocks inline QA/PENTEST REPORT without invoking `/process-qa` or `/process-pentest`. Previous CHECK 1 required BOTH conditions and missed the skipped-skill-entirely case.
- **H2 — `bash-safety-guard.py`:** Inert-context stripping. `python -c`, `bash -c`, `grep`, `echo`, heredocs now pre-stripped before pattern matching, reducing false positives on legitimate analytics/audit work without loosening real enforcement.
- **H7 — `epistemic-check.py`:** PATH robustness via `shutil.which("claude")` with fallback paths. Silent failures now log to `epistemic-check.log`.
- **H1 — `architect-review` → `architect-reviewer` consolidation:** Canonical name used across all skills + `KNOWN_DISPATCH_NAMES` in 3 hooks. Deprecated alias kept as backward-compat safety net. DAR pass-log alias-expanded.
- **O1 — `KNOWN_DISPATCH_NAMES` additions** (caught by adversarial review): `architect-reviewer` was missing from all 3 hooks' known-names sets after the H1 rename. `extract_dispatch_names()` silently dropped the token. Fixed by adding it.
- **O2 — `has_qa_report` regex tightened** (caught by adversarial review): Was matching narrative mentions like "as mentioned in the QA REPORT, all tests pass." Now requires structural block: `^\s*QA REPORT\s*[\n:].{0,500}?\b(?:PASS|FAIL)\b`. Same fix applied to PENTEST REPORT detection.
- **O4 — PM rubber-stamp gap** (caught by adversarial review): `check_pm_checkpoint_report` only verified report text presence, not that `pm-orchestrator` Agent was actually dispatched after `/pm`. Now tracks dispatches; BLOCKS when report present without orchestrator invocation. Closes a silent bypass documented by a failing test since 2026-04-13 but never implemented.

### Architectural findings (deferred as design decisions)

- **H6** — `governance-log.jsonl` rotation: deferred to the next-increment monitoring overhaul (now shipped as the observability v2 design, see research repo).
- **H9** — Content routing: `task-classifier` Content row now routes through `process-research` (if research needed) → `content-marketer` as terminal writer. Removed the broken `process-build with DOMAIN: content` path.
- **H10** — `process-planning` researcher-bypass closed: Step 2 now routes through `process-research` skill rather than dispatching `technical-researcher` / `research-analyst` directly. Respects the research entry-point rule.
- **H11 POC** — Sidecar file pattern verified (`DISPATCHES.json`). `sidecar_loader.py` reusable loader added. Next step is wiring `load_dispatches()` into `dispatch-compliance-check.py` as transcript-classification fallback.

### Pattern captured — "rubber-stamp enforcement gaps"

Hooks that verify output text but not real dispatch create silent bypass paths. The audit surfaced this in both `check_pm_checkpoint_report` (O4) and `work-verification-check` CHECK 1 (H5). Both were fixed; the pattern template is: `if has_output and not has_real_invocation: BLOCK`. Invoke-side verification complements output-side verification; AND/OR logic matters.

### Pattern captured — "abandoned-TDD"

Failing tests in this repo often encode unimplemented intent — someone wrote the test as TDD but never shipped the fix. Example: `test_pm_without_orchestrator_inline_report_blocked` was written 2026-04-13; implementation landed 2026-04-18 (as O4). Treat persistent failing tests as free bug reports.

### Regression

- 112/112 tests pass after all fixes.
- Composed B1+B2+B3 bypass attempt: BLOCKED by H3.
- Inline QA REPORT without `/process-qa`: BLOCKED by H5.
- Quick classification: preserved.
- Legitimate `architect-reviewer` dispatch via Agent hook: ALLOWED.

---

## 2026-04-13 — Alignment Fix Implementation (11/14 findings)

Comprehensive alignment analysis (8 routes, 14 findings) revealed that hooks enforce format, not correctness. This release fixes 11 of 14 findings across 4 phases.

### Phase 1: Structural Correctness

- **B4 fix:** Multiline MUST DISPATCH regex in `classifier-field-check.py` and `agent-dispatch-check.py`. Both now use `re.DOTALL` with FIELD_LABELS delimiter, matching `dispatch-compliance-check.py` pattern.
- **B5 fix:** `architect-review` vs `architect-reviewer` naming contract documented in all KNOWN_DISPATCH_NAMES copies.

### Phase 2: Alias Expansion (S3/B1)

- **SKILL_AGENT_ALIASES expanded** in `agent-dispatch-check.py` and `dispatch-compliance-check.py`:
  - `process-research`: +research-synthesizer, +report-generator (fixes B1: direct-dispatch path Step 4-5 was blocked)
  - `process-analysis`: expanded from 2 to 10 agents (all Step 2 specialists)
  - `process-planning`: expanded from 2 to 9 agents (Steps 2-4)
  - `process-build`: +prompt-engineer, +debugger
- **Canonical SKILL_AGENT_ALIASES** added to `scripts/shared/known_names.py`
- **Drift guard test** extended to cover SKILL_AGENT_ALIASES consistency across hooks + canonical

### Phase 3: Enforcement Uplift

- **S1 fix:** `classifier-field-check.py` now requires JUSTIFICATION field for Quick classifications (blocks if missing)
- **M1 fix:** `user-prompt-submit.py` adds 9 depth-signal patterns ("are you sure?", "analyze this", "why did", etc.) that inject stronger classifier warnings via additionalContext
- **B2 fix:** `process-step-check.py` `check_pm_checkpoint_report()` now verifies pm-orchestrator agent was dispatched, not just that a PM CHECKPOINT REPORT text block exists (prevents rubber-stamping)

### Phase 4: Independent Fixes

- **B3 fix:** Scheduled tasks (`daily-memory-update`, `weekly-memory-update`) corrected to reference actual hook script paths (note: the `score-memory.py` reference was retracted 2026-05-07 — the script never existed; decay-scoring claim retired as aspirational; see project research notes for details)
- **M4 fix:** 4 process skill docs corrected from "caught by the Stop hook" to "logged by the Stop hook — soft enforcement"
- **M6 fix:** `governance-log.py` no longer skips blocked turns; logs with `blocked_turn: true` field

### Deferred (3/14)

- **S2** (TaskCreate enforcement hook) — requires new hook architecture, deferred to next iteration
- **M3** (shared checkpoint timer) — low impact, fix complexity not justified
- **M5** (dark-zone enforcement) — needs 30 days of log data before hardening

### Test Progression

87 → 120 tests. 3 new test files: `test_classifier_field_check.py`, `test_user_prompt_submit.py`, `test_process_step_check.py`.

---

## 2026-04-06 — Quality Enforcement + PM Simplification

Major evolution from compliance-only to compliance + quality enforcement. Hooks now check tool usage during QA, not just format. PM trigger simplified from "2+ compounds" to "every non-Quick."

### New: work-verification-check.py (Stop hook #12)

Three checks forcing actual execution and autonomous exhaustion:
1. **QA/Pentest Execution (HARD):** QA REPORT filed with zero execution tools → block
2. **Premature Escalation (HARD):** Asking user for help with <3 tools used → block
3. **Zero-Work Non-Quick (SOFT):** Non-Quick + zero tools → governance log warning

### Rewritten: process-qa/SKILL.md

- Step 3 split into 3a (run test) / 3b (show raw output) / 3c (judge PASS/FAIL)
- Step 4 NEW — Coverage Check (mandatory before reporting)
- Evidence rules: "Looks correct" without specific output = INVALID
- Scope check: if N artifacts built, N must be tested
- Hook warning at bottom

### Rewritten: process-pentest/SKILL.md

- Step 3 split into 3a-3d matching process-qa pattern: State → Execute → Show raw → Judge

### Simplified: PM enforcement (every non-Quick)

Previous trigger (2+ compounds) was circular — depended on Claude's own classification behavior. Simplified to: every non-Quick task → pm in MUST DISPATCH. No compound counting.

Files updated:
- `skills/core/task-classifier/SKILL.md` — mandatory compounds table, PM enforcement text, PM SELF-CHECK, Step 6
- `hooks/classifier-field-check.py` — compound counting regex → simple non-Quick + pm check
- `settings/settings.local.json.example` — work-verification-check.py added to Stop hooks

### Updated: CLAUDE.md

- "Exhaust before asking" rule (4 steps: Execute, Read, Retry, Delegate)
- "Test what you build" rule (work-verification hook enforces)
- PM enforcement line: every non-Quick gets PM oversight
- Model cost rule phrasing tightened
- PreCompact hook auto-saves noted

---

## 2026-03-26 — Monitoring Coverage Extension

Added governance-log.jsonl writes to 4 enforcement hooks that were previously silent. All enforcement events (block/deny) now flow to the central governance log.

### Hooks updated

| Hook | Type | Event logged |
|------|------|-------------|
| `agent-dispatch-check.py` | PreToolUse:Agent | `deny` — undeclared agent dispatch |
| `subagent-quality-check.py` | SubagentStop | `block` — empty/error/unstructured agent output |
| `epistemic-check.py` | Stop | `block` — overconfident response (Haiku-evaluated) |
| `delegation-check.ps1` | Stop | `block` — APPROACH said delegate but no Agent tool used |

### Coverage: 11/16 hooks now log to governance-log.jsonl (was 7)

All enforcement hooks centrally logged. Remaining 5 are context-injection only.

---

## 2026-03-26 — PM Enforcement Hardening

Prompt-based PM enforcement was unreliable (LLM skipped pm in MUST DISPATCH despite 2+ compounds). Added hook-level enforcement + inline self-check.

### Changes

**task-classifier/SKILL.md**
- Added PM SELF-CHECK inline in the MUST DISPATCH template field — LLM reads it while writing the field, cannot miss it
- Text: "count the yes answers above. If 2 or more → pm MUST be in this list. The Stop hook will block you if it's missing."

**hooks/classifier-field-check.py**
- Added compound-counting logic after existing field checks
- Parses APPROACH section, counts compounds marked "yes", blocks if 2+ and pm not in MUST DISPATCH
- Fires on Stop event — post-hoc catch, forces re-classification

### Enforcement Architecture (updated)

| Layer | When | Type |
|-------|------|------|
| PM SELF-CHECK in template | During classification | Prompt (inline) |
| classifier-field-check.py | Stop (post-response) | Hook (hard block) |
| dispatch-compliance-check.py | Stop (post-response) | Hook (contract check) |
| check_pm_after_increment | Stop (post-response) | Hook (TaskCreate safety net) |
| check_pm_checkpoint_report | Stop (post-response) | Hook (artifact check) |

---

## 2026-03-26 — PM Integration Fix (Systemic)

PM lifecycle management elevated from optional overlay to enforced infrastructure, achieving parity with QA enforcement.

### Problem

PM (project management checkpoints) was weakly integrated into the governance system:
- Not in the classifier's mandatory compounds table
- process-planning had zero PM references (no STATE.md, appetite, or lifecycle awareness)
- No machine-checkable output artifact (QA had QA REPORT; PM had nothing)
- pm skill made a false trust assumption about pentest ordering
- Hook enforcement contained dead code (`pm_seen` variable never set to True)
- No reactive PM triggers for mid-session state changes

### Changes

**task-classifier/SKILL.md**
- Added PM to mandatory compounds table: 2+ compounds detected triggers PM
- Added PM reactive triggers: scope change, blocker reported, new workstream, phase transition
- Updated MUST DISPATCH rules to cover both floor rule and reactive triggers
- Updated Step 6 execution rules for consistency
- Reactive triggers escalate Quick to Analysis (state changes are never Quick)

**process-planning/SKILL.md**
- Step 1 now reads STATE.md and PROJECT.md if they exist (optional, graceful degradation)
- Appetite imported from PROJECT.md into Constraints
- Scope overflow flagged if plan exceeds declared appetite
- Explicit ownership note: does not write to STATE.md (pm-orchestrator owns it)

**pm/SKILL.md**
- Added PM CHECKPOINT REPORT artifact (machine-checkable, greppable by hooks)
  - Fields: Project, Phase, Viability (PASS/HOLD/KILL), Blockers, Next
- Removed false trust assumption ("do not re-check for pentest — it already ran")

**hooks/process-step-check.py**
- Removed `pm_seen` dead code (variable was never True; function worked correctly via reset mechanism)
- Simplified `check_pm_after_increment()`: removed redundant variable and unreachable final return
- Added `check_pm_checkpoint_report()`: second enforcement layer that verifies PM CHECKPOINT REPORT artifact exists after /pm invocation
- Reports are tracked per-invocation (text after latest /pm, not cumulative)

### Enforcement Architecture (after fix)

| Layer | Mechanism | What it checks |
|-------|-----------|----------------|
| Classifier | Mandatory compounds table | 2+ compounds OR reactive trigger → pm in MUST DISPATCH |
| dispatch-compliance-check.py | MUST DISPATCH contract | Was /pm actually invoked when declared? |
| process-step-check.py (safety net) | TaskCreate count | 2+ TaskCreate + pentest done → PM required |
| process-step-check.py (artifact) | PM CHECKPOINT REPORT | After /pm: was structured report produced with Viability verdict? |

### Verification

- Per-increment QA: 10/10 claims passed across 3 increments
- Tier 2 pentest: SHIP (0 HIGH, 2 MED — one fixed inline, one structural limitation)
- Sensitive data scan: CLEAN (no employer/NDA references)

### Discovery

The `pm_seen` variable in `check_pm_after_increment()` was initially diagnosed as a critical bug ("never set to True, causes unconditional blocking"). Adversarial review + manual trace revealed this was incorrect: the function works correctly via the reset mechanism (when /pm fires, `task_creates` resets to 0, triggering the early return before `pm_seen` is ever consulted). The variable was dead code, not a behavioral bug.
