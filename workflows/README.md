# Workflow Scripts

**Audience:** Operators installing or adapting this framework.

These are the **procedure-layer workflow scripts**: deterministic encodings of the six core process skills (`process-planning`, `process-pentest`, `process-build`, `process-research`, `process-analysis`, `process-qa`). Each script is invoked by the Claude Code **Workflow tool** (`{scriptPath: "..."}`) and drives the multi-agent dispatch sequence by construction, not by prompt compliance.

---

## What these are

The process skills define *which procedure to follow* (routing + prose spec). The workflow scripts define *how that procedure executes* (agent dispatch order, typed schemas, PASS/FAIL computation in code). The relationship is:

- **SKILL.md** = spec-of-record + explicit fallback. The prose body is authoritative; the `## ⚡ Workflow-enforced` section at the top of each skill is the thin invoker stub that calls the script.
- **workflow script** = routing-as-code. The script drives dispatch order, enforces synthesis when ≥2 agents fire, derives PASS/FAIL from typed evidence fields, and HALTs before spawning agents if required args are missing.
- **DISPATCHES.json** = machine-readable dispatch contract for H11 verification. This file survives the workflow conversion unchanged: it is read-only audit material, not execution logic.

---

## Invariants (every script honours all of these)

1. **Parse-if-string + HALT.** The Workflow harness may deliver `args` as a JSON-encoded string. Every script attempts `JSON.parse(args)` when `typeof args === 'string'`, then HALTs with a clear error if required fields are still missing after parsing. No agent is spawned on empty scope.

2. **Typed schemas on every agent call.** All `agent()` calls carry a `schema:` field. This forces structured output and makes the script's PASS/FAIL logic deterministic: it reads specific typed fields, it does not grep prose.

3. **FILE CONTRACT.** Any agent that must produce a file on disk receives an explicit FILE CONTRACT: write to exactly the stated vault-relative path, verify the file exists after writing, return the path and an existence flag. The quality gate reads the file to confirm: not the agent's self-report.

4. **PASS/FAIL derived in code.** Pass conditions are evaluated by the script reading typed evidence sub-fields (e.g. `quality.report_file_exists && quality.all_questions_addressed`). An agent's prose `"PASS"` does not gate the return value; the code does.

5. **DISPATCHES.json untouched.** Routing-as-code does not retire the machine-readable dispatch sidecar. The H11 read-only check still validates that the expected dispatch names appear.

6. **HALT paths return, never throw.** When a script detects an unrecoverable condition (missing args, decomposition mode that requires invoking another skill, Ralph Loop hand-back), it `return`s a typed `{status: 'halted-...'}` object with a `reason` field. The main session reads `status` and routes accordingly.

---

## Scripts

| Script | Phases | Key HALT paths |
|---|---|---|
| `process-planning.js` | Scope → Design → Review → Revise → Quality | malformed args; spec gap flagged for owner decision |
| `process-pentest.js` | Surface → Execute → Report | malformed args; no runnable attack ideas |
| `process-build.js` | Scope → Plan → Build → Review → Revise → Quality | malformed args; plan fabrication guard; spec gap flagged |
| `process-research.js` | Scope → Research → Synthesis → Report → Quality | malformed args; `ralph_loop_indicated=true` → hands back to main session |
| `process-analysis.js` | Scope → Analyze → Synthesis → Report → Quality | malformed args; `decomposition` mode → hands back with sub-task list |
| `process-qa.js` | Scope → Execute → Report | malformed args; coverage mismatch padded as FAIL |

### Special return statuses

- `status: 'ralph-loop-hand-back'` (process-research): scope step classified ≥3 open questions + ≥3 sources + anchoring risk. The workflow cannot invoke the architect-loop skill. The return includes `scope_block_for_loop` for the main session to start a Ralph Loop manually.
- `status: 'decomposition-hand-back'` (process-analysis): scope step chose decomposition mode. The return includes `decomposition_subtasks`; the main session executes each via the prose skill path.
- `status: 'halted-malformed-args'`: required args were missing or unparseable. Inspect `received_args_type` and `hint` in the return.

---

## How to adapt for your installation

1. **Install to `.claude/workflows/`**: copy the six scripts into your `.claude/workflows/` directory (or wherever your Claude Code project loads workflows from). The path must be absolute.

2. **Update the scriptPath in each SKILL.md stub**: each process skill has a `## ⚡ Workflow-enforced` section with `scriptPath: "{{VAULT_ROOT}}/.claude/workflows/<name>.js"`. Replace `{{VAULT_ROOT}}` with the absolute path to your project root on the installing machine.

3. **Session-cache gotcha**: after editing a workflow script mid-session, invoke it by `scriptPath` in the Workflow tool call, not by the script's `meta.name`. The name-to-path mapping is session-cached and will not pick up edits until the next session restart.

4. **DISPATCHES.json**: the `DISPATCHES.json` sidecar in each skill directory maps skill name to expected dispatch set. Do not delete it; it is the H11 read-only verification source used by `dispatch-compliance-check.py`.

5. **Hook preconditions for process-qa**: `process-qa.js` relies on three hook fixes (described in its file header) in `process-step-check.py` and `work-verification-check.py`. Without these, the `work-verification-check` will false-block a Workflow-driven QA run because the execution tools run inside the workflow subagent and are invisible to the main transcript. Ship the three updated hook files before wiring the process-qa SKILL.md stub.

---

## Reference

- Architecture overview: [`docs/architecture.md`](../docs/architecture.md): Layer 1 (procedure layer)
- Per-workflow attributes table: [`docs/reference/workflows.md`](../docs/reference/workflows.md)
- Decision rationale: [`docs/adr/0004-routing-as-code-workflow-enforcement.md`](../docs/adr/0004-routing-as-code-workflow-enforcement.md), [`docs/adr/0006-full-procedure-layer-migration.md`](../docs/adr/0006-full-procedure-layer-migration.md)
- Skill stubs: `skills/core/process-*/SKILL.md` (the `## ⚡ Workflow-enforced` section in each)
