/*
 * ADOPTED 2026-06-11 — Increment 2, procedure-layer migration (owner GO).
 * Source draft: (design records vault-internal)
 * Scope: routing-as-code — the script drives dispatch sequence; agents reason freely inside steps.
 * DISPATCHES.json stays authoritative for H11 read-only verification (do not retire it).
 * Quality gates inside derive pass/fail from execution evidence (raw tool output), never from report presence.
 */

export const meta = {
  name: 'process-build',
  description: 'Deterministic encoding of the process-build procedure: scope -> implementation-plan (plan) -> blueprint-mode (build) -> mandatory parallel review (architect-reviewer + adversarial-reviewer [+ prompt-engineer if llm_prompts]) -> capped revise loop -> execution-evidence quality gate. Routing-as-code; agents work freely inside steps.',
  phases: [
    { title: 'Scope', detail: 'read project state, classify typed flags, emit BUILD SCOPE block' },
    { title: 'Plan', detail: 'implementation-plan produces the sequenced implementation plan artifact' },
    { title: 'Build', detail: 'blueprint-mode implements per the plan; artifact written to the scoped output path' },
    { title: 'Review', detail: 'architect-reviewer + adversarial-reviewer (+ prompt-engineer if llm_prompts), in parallel' },
    { title: 'Revise', detail: 'route blocking issues back to blueprint-mode; capped at 2 rounds' },
    { title: 'Quality', detail: 'gate on execution evidence: artifact file exists + acceptance criteria met' },
  ],
}

// ---------------------------------------------------------------------------
// Typed schemas — judgment nodes return DATA, not prose (corpus Reframe 2).
// ---------------------------------------------------------------------------

// Step 1 output: the BUILD SCOPE block + typed conditional-dispatch flags.
const SCOPE_SCHEMA = {
  type: 'object',
  required: ['scope_block', 'output_path', 'underspecified', 'n8n_domain', 'llm_prompts', 'rationale'],
  properties: {
    scope_block: { type: 'string', description: 'The literal BUILD SCOPE block: Goal / Inputs (specs, requirements) / Tech / Output path Projects/<name>/work/YYYY-MM-DD-<artifact>.' },
    output_path: { type: 'string', description: 'The exact vault-relative output path extracted from scope_block (e.g. Projects/Foo/work/2026-06-11-thing.js). The script uses this — do NOT leave it embedded only in scope_block prose.' },
    underspecified: { type: 'boolean', description: 'true if no spec/requirements exist — triggers route-to-planning HALT.' },
    n8n_domain: { type: 'boolean', description: 'true if the build involves n8n workflow JSON or n8n node changes — triggers n8n-chain HALT.' },
    llm_prompts: { type: 'boolean', description: 'true if the artifact contains LLM prompts or agent designs — adds prompt-engineer to review.' },
    rationale: { type: 'string', description: 'one line per flag justifying the boolean from actual scope text.' },
  },
}

// Step 2 output: the implementation plan must be a FILE on disk (execution evidence).
const PLAN_SCHEMA = {
  type: 'object',
  required: ['plan_path', 'has_acceptance_criteria', 'step_count', 'summary'],
  properties: {
    plan_path: { type: 'string', description: 'vault-relative path to the plan .md the agent WROTE (must exist on disk).' },
    has_acceptance_criteria: { type: 'boolean', description: 'does every implementation step carry an acceptance criterion?' },
    step_count: { type: 'integer' },
    summary: { type: 'string', description: 'one-paragraph summary of the plan.' },
  },
}

// Step 3 output: the build artifact — must be a verified FILE on disk.
const BUILD_SCHEMA = {
  type: 'object',
  required: ['artifact_path', 'artifact_exists', 'summary'],
  properties: {
    artifact_path: { type: 'string', description: 'vault-relative path to the artifact the agent WROTE and verified (must exist on disk; must match the FILE CONTRACT path).' },
    artifact_exists: { type: 'boolean', description: 'agent confirmed the file exists by Reading or Bashing it after writing.' },
    summary: { type: 'string', description: 'one-paragraph description of what was built.' },
  },
}

// Step 4 output: each reviewer returns a structured verdict.
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'blocking_issues', 'notes'],
  properties: {
    verdict: { type: 'string', enum: ['APPROVE', 'APPROVE_WITH_NOTES', 'REQUEST_CHANGES'] },
    blocking_issues: { type: 'array', items: { type: 'string' }, description: 'issues that MUST be fixed before the artifact can ship. Empty unless verdict is REQUEST_CHANGES.' },
    notes: { type: 'array', items: { type: 'string' }, description: 'non-blocking observations.' },
  },
}

// Step 6 output: the quality gate verdict (gates on real artifact state).
const QUALITY_SCHEMA = {
  type: 'object',
  required: ['artifact_file_exists', 'criteria_met', 'no_unsolicited_changes', 'pass', 'evidence'],
  properties: {
    artifact_file_exists: { type: 'boolean', description: 'verified by actually reading the artifact_path file.' },
    criteria_met: { type: 'boolean', description: 'all acceptance criteria from the plan are satisfied per the artifact content.' },
    no_unsolicited_changes: { type: 'boolean', description: 'no changes beyond the stated spec were applied (SKILL.md Step 5 check).' },
    pass: { type: 'boolean', description: 'true only if ALL three checks above are true.' },
    evidence: { type: 'string', description: 'the tool calls used to verify (Read/Bash/Glob) — NOT "looks correct".' },
  },
}

// ---------------------------------------------------------------------------
// args contract (passed verbatim by the caller):
//   { project:      string  (required) — e.g. "MyProject"
//     spec:         string  (required) — what to build, OR path to spec/blueprint
//     constraints?: string             — any caller-supplied constraints
//     llm_prompts?: boolean            — pre-declare if known (scope agent may override)
//     n8n_domain?:  boolean            — pre-declare if known; scope agent confirms
//   }
//
// HALT conditions: project or spec missing.
// ---------------------------------------------------------------------------
let A = (typeof args === 'object' && args) ? args : {}
if (typeof args === 'string') {
  try { const p = JSON.parse(args); if (p && typeof p === 'object') A = p } catch (e) { /* fall through to HALT */ }
}
const PROJECT = A.project || 'UNKNOWN'
const SPEC    = A.spec    || ''
if (PROJECT === 'UNKNOWN' || !SPEC) {
  log('HALT: malformed dispatch — args must be a JSON OBJECT {project, spec, constraints?, llm_prompts?, n8n_domain?} with real values. Refusing to spawn agents on empty scope.')
  return { status: 'halted-malformed-args', received_args_type: typeof args, hint: 'pass args as a JSON object with non-empty project and spec' }
}

// ---------------------------------------------------------------------------
// THE PROCEDURE
// ---------------------------------------------------------------------------

// --- Step 1: Define Scope + classify typed flags ----------------------------
phase('Scope')
const scope = await agent(
  `You are the scope+classify node of the process-build procedure for project "${PROJECT}".

SPEC / WHAT TO BUILD: ${SPEC}
CALLER CONSTRAINTS: ${A.constraints || '(none supplied)'}
CALLER FLAGS (advisory; you override based on actual scope): llm_prompts=${A.llm_prompts || false}, n8n_domain=${A.n8n_domain || false}

1. Read Projects/${PROJECT}/PROJECT.md and Projects/${PROJECT}/STATE.md IF they exist (use the Read tool). Import any active tasks and context. If a file does not exist, proceed without it.
2. Emit the BUILD SCOPE block:
   Goal: [what is being built — one sentence]
   Inputs: [specs, requirements, or designs this builds from]
   Tech: [language, platform, framework]
   Output path: Projects/${PROJECT}/work/YYYY-MM-DD-<artifact-name>.<ext>
3. Set the typed flags from the ACTUAL scope text:
   - underspecified: no spec/requirements exist → must route to Planning
   - n8n_domain: involves n8n workflow JSON or n8n node edits
   - llm_prompts: artifact contains LLM prompts or agent designs
4. Extract the output_path from the scope block as a standalone field (e.g. "Projects/Foo/work/2026-06-11-thing.js").

Do not build. Do not guess file contents — if you could not read a file, say so in the rationale.`,
  { schema: SCOPE_SCHEMA, label: `scope:${PROJECT}`, phase: 'Scope' }
)

if (!scope || !scope.scope_block) {
  log('Scope step returned nothing usable — halting.')
  return { status: 'scope-failed', project: PROJECT }
}

// underspecified: route to Planning (SKILL.md Step 1 — no spec means Planning, not Build)
if (scope.underspecified) {
  log('HALT: spec is underspecified — no requirements exist. Per SKILL.md Step 1, route to process-planning first.')
  return { status: 'route-to-planning', project: PROJECT, scope, reason: 'underspecified: spec/requirements are missing — run process-planning first, then re-invoke with the resulting spec' }
}

// n8n domain: constitutional two-phase orchestration is its own HITL process
if (scope.n8n_domain) {
  log('HALT: n8n domain detected. The n8n Two-Phase Orchestration is a constitutional process with a mandatory human promotion gate. Do not re-encode it here.')
  return { status: 'route-to-n8n-chain', project: PROJECT, scope, reason: 'n8n_domain=true — invoke n8n-workflow-architect (Phase 1 design) then n8n-workflow-builder (Phase 2 implementation) via the Two-Phase Orchestration path defined in CLAUDE.md' }
}

// Extract the output path (scope agent dates it; scripts cannot call Date)
const pathMatch = (scope.output_path || scope.scope_block || '').match(/Projects\/[^\s]+\.\w+/)
const ARTIFACT_PATH = scope.output_path || (pathMatch ? pathMatch[0] : 'Projects/' + PROJECT + '/work/artifact-undated.md')

// ---------------------------------------------------------------------------
// --- Step 2: Plan (implementation-plan) -------------------------------------
phase('Plan')
async function plan(feedback) {
  return agent(
    `You are implementation-plan producing the sequenced implementation plan for project "${PROJECT}".

${scope.scope_block}

${feedback ? '\nREVISION REQUIRED — address these blocking issues from review:\n- ' + feedback.join('\n- ') : ''}

Produce a detailed sequenced plan with clear steps, dependencies, and acceptance criteria per step. Every step MUST have an acceptance criterion.

FILE CONTRACT (non-negotiable):
1. WRITE the complete plan document to a vault path under Projects/${PROJECT}/work/ (YYYY-MM-DD-<name>-plan.md).
   Use the Write tool; if unavailable, use Bash (python with utf-8 encoding).
2. VERIFY it landed: Read the file and confirm content.
3. Return plan_path as the exact path you wrote and verified. Any path you did not write-and-verify is a contract violation.

FABRICATION WARNING: do NOT invent file inventories. If you reference existing source files, verify they exist via Glob or Read first. Invented ghost files will be caught by the downstream build agent.`,
    { schema: PLAN_SCHEMA, label: feedback ? 'plan:revise' : 'plan', phase: 'Plan' }
  )
}
let implementationPlan = await plan(null)

if (!implementationPlan || !implementationPlan.plan_path) {
  log('Plan step returned no plan artifact — halting.')
  return { status: 'plan-failed', project: PROJECT, scope }
}

// Fabrication guard: verify any file inventory the plan cites actually exists.
// The quality/verify step below also catches missing artifacts, but a pre-build
// check here avoids spawning blueprint-mode against a plan built on ghost files.
const planVerify = await agent(
  `You are a pre-build sanity check. Read the implementation plan at ${implementationPlan.plan_path}. For any source files, scripts, or artifacts the plan references as EXISTING inputs, verify they exist on disk using Glob or Read. List any referenced files that do NOT exist. If none are missing, say so explicitly.

Return a JSON object: { "missing_inputs": ["path1", ...], "all_inputs_verified": boolean }`,
  { schema: { type: 'object', required: ['missing_inputs', 'all_inputs_verified'], properties: { missing_inputs: { type: 'array', items: { type: 'string' } }, all_inputs_verified: { type: 'boolean' } } }, label: 'plan-verify', phase: 'Plan' }
)
if (planVerify && planVerify.missing_inputs && planVerify.missing_inputs.length > 0) {
  log(`Fabrication guard: plan references ${planVerify.missing_inputs.length} input file(s) that do not exist on disk: ${planVerify.missing_inputs.join(', ')}. Halting before build.`)
  return { status: 'plan-fabricated-inputs', project: PROJECT, scope, plan: implementationPlan, missing_inputs: planVerify.missing_inputs }
}

// ---------------------------------------------------------------------------
// --- Step 3: Build (blueprint-mode) -----------------------------------------
phase('Build')
async function build(feedback) {
  return agent(
    `You are blueprint-mode implementing the build for project "${PROJECT}".

IMPLEMENTATION PLAN (at ${implementationPlan.plan_path}): Read this file — do not assume its contents.
${scope.scope_block}
${feedback ? '\nREVISION REQUIRED — address these blocking issues from review:\n- ' + feedback.join('\n- ') : ''}

Implement according to the plan. Follow existing patterns in the codebase. Include error handling at system boundaries only.

FILE CONTRACT (non-negotiable):
1. WRITE the completed artifact to EXACTLY this vault path: ${ARTIFACT_PATH}
   Use the Write tool (default subagent — Write tool IS available to you). If Write is unavailable, use Bash (python with utf-8 encoding).
2. VERIFY it landed: Read the file and confirm the content matches what you wrote.
3. Return artifact_path as exactly "${ARTIFACT_PATH}". Any other path, or a path you did not write-and-verify, is a contract violation.
4. Return artifact_exists = true only after confirming the file is on disk.

Do not apply changes beyond what the plan specifies. No unsolicited additions.`,
    { schema: BUILD_SCHEMA, label: feedback ? 'build:revise' : 'build', phase: 'Build' }
  )
}
let buildResult = await build(null)

if (!buildResult || !buildResult.artifact_path) {
  log('Build step returned no artifact path — halting.')
  return { status: 'build-failed', project: PROJECT, scope, plan: implementationPlan }
}

// ---------------------------------------------------------------------------
// --- Step 4 + 5: Mandatory parallel review, then capped revise loop ---------
// architect-reviewer ALWAYS. adversarial-reviewer ALWAYS.
// prompt-engineer IF llm_prompts.
const MAX_REVISE_ROUNDS = 2  // cap revise loop — CONVERGED != keep going.

function reviewPrompt(role, lens) {
  return `You are ${role}. Review the artifact at ${buildResult.artifact_path} for project "${PROJECT}" against this plan and scope.

PLAN (read it): ${implementationPlan.plan_path}
${scope.scope_block}

${lens}

Return verdict (APPROVE / APPROVE_WITH_NOTES / REQUEST_CHANGES), blocking_issues (only if REQUEST_CHANGES), and notes. Read the artifact file yourself — do not assume its contents.`
}

let round = 0
let review
let reviewFailed = false
while (true) {
  phase('Review')
  const reviewers = [
    () => agent(reviewPrompt('architect-reviewer', 'Assess correctness, completeness, SOLID principles, adherence to the plan, over-engineering, missing edge cases.'),
      { schema: REVIEW_SCHEMA, label: 'review:architect', phase: 'Review', agentType: 'architect-reviewer' }),
    () => agent(reviewPrompt('adversarial-reviewer', 'Challenge the build\'s assumptions. Try to find where it fails: unstated dependencies, optimistic code paths, an irreversible action with no rollback, a constraint silently violated, a security gap.'),
      { schema: REVIEW_SCHEMA, label: 'review:adversarial', phase: 'Review', agentType: 'adversarial-reviewer' }),
  ]
  if (scope.llm_prompts) {
    reviewers.push(() => agent(reviewPrompt('prompt-engineer', 'Review only the LLM-prompt / agent-design aspects: prompt clarity, output contracts, failure handling, eval strategy.'),
      { schema: REVIEW_SCHEMA, label: 'review:prompt-engineer', phase: 'Review', agentType: 'prompt-engineer' }))
  }
  const verdicts = (await parallel(reviewers)).filter(Boolean)
  review = verdicts

  // Empty verdict set is NOT convergence (architect note N1 / B1 fix pattern from process-planning.js).
  if (verdicts.length === 0) {
    log(`All ${reviewers.length} reviewer agents returned no verdict — this is a review FAILURE, not convergence. Stopping.`)
    reviewFailed = true
    break
  }

  const blocking = verdicts
    .filter(v => v.verdict === 'REQUEST_CHANGES')
    .flatMap(v => v.blocking_issues || [])

  if (blocking.length === 0) {
    log(`Review converged at round ${round}: no blocking issues across ${verdicts.length} reviewers.`)
    break
  }
  if (round >= MAX_REVISE_ROUNDS) {
    log(`Revise cap (${MAX_REVISE_ROUNDS}) reached with ${blocking.length} blocking issue(s) still open — STOP and surface to the owner rather than ratcheting.`)
    break
  }
  round += 1
  phase('Revise')
  log(`Revise round ${round}: routing ${blocking.length} blocking issue(s) back to blueprint-mode.`)
  buildResult = await build(blocking)
  if (!buildResult || !buildResult.artifact_path) {
    log('Revise-round build returned no artifact - halting (architect F-2 guard).')
    return { status: 'build-revise-failed', project: PROJECT, scope }
  }
}

if (reviewFailed) {
  return { status: 'review-agents-all-failed', project: PROJECT, scope, plan: implementationPlan, build: buildResult, revise_rounds: round }
}

// ---------------------------------------------------------------------------
// --- Step 6: Quality gate — EXECUTION EVIDENCE, not REPORT presence ---------
phase('Quality')
const quality = await agent(
  `You are the quality gate for the process-build procedure. Verify the artifact EMPIRICALLY — do not trust the build summary.

1. Use the Read tool to open ${buildResult.artifact_path}. Set artifact_file_exists from whether the read succeeded.
2. Read the plan at ${implementationPlan.plan_path}. For each acceptance criterion, confirm it is satisfied in the artifact (criteria_met).
3. Confirm no unsolicited changes were applied — the artifact addresses only what is specified in the plan scope (no_unsolicited_changes).
Set pass = (artifact_file_exists AND criteria_met AND no_unsolicited_changes). In evidence, name the actual tool calls you made — "looks correct" is not evidence.

Scope for reference:
${scope.scope_block}`,
  { schema: QUALITY_SCHEMA, label: 'quality-gate', phase: 'Quality' }
)

// Derive pass IN CODE from evidence sub-fields — never trust agent self-report (Reframe 2).
const qualityPass = !!(quality
  && quality.artifact_file_exists
  && quality.criteria_met
  && quality.no_unsolicited_changes)

// ---------------------------------------------------------------------------
return {
  status: qualityPass ? 'complete' : 'quality-failed',
  project: PROJECT,
  scope,
  plan: implementationPlan,
  build: buildResult,
  review,
  revise_rounds: round,
  quality,
  quality_pass_derived: qualityPass,
}
