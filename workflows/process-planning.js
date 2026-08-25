/*
 * ADOPTED 2026-06-11: live procedure-layer workflow (owner GO; Action-0.1 calibration explicitly waived).
 * Source draft: Projects/your-project/work/2026-06-09-process-planning-workflow-draft.js (review trail there).
 * Scope: routing-as-code: the script drives dispatch sequence; agents reason freely inside steps.
 * DISPATCHES.json stays authoritative for H11 read-only verification (do not retire it).
 * Quality gates inside derive pass/fail from execution evidence (raw tool output), never from report presence.
 */

export const meta = {
  name: 'process-planning',
  description: 'Deterministic encoding of the process-planning procedure: scope+classify -> (research gate) -> design (implementation-plan) -> mandatory parallel review (architect + adversarial [+ prompt-engineer]) -> capped revise loop -> execution-evidence quality gate. Routing-as-code; agents work freely inside steps.',
  phases: [
    { title: 'Scope', detail: 'read project state, emit PLANNING SCOPE, type the judgment flags' },
    { title: 'Design', detail: 'implementation-plan produces the sequenced plan artifact' },
    { title: 'Review', detail: 'architect-reviewer + adversarial-reviewer (+ prompt-engineer if LLM prompts), in parallel' },
    { title: 'Revise', detail: 'route blocking issues back to implementation-plan; capped at 2 rounds' },
    { title: 'Quality', detail: 'gate on execution evidence: plan file exists + has acceptance criteria' },
  ],
}

// ---------------------------------------------------------------------------
// Typed schemas: judgment nodes return DATA, not prose (corpus Reframe 2).
// ---------------------------------------------------------------------------

// Step 1 output: the PLANNING SCOPE block + the typed conditional-dispatch flags.
const SCOPE_SCHEMA = {
  type: 'object',
  required: ['scope_block', 'research_needed', 'high_stakes', 'llm_prompts', 'exceeds_appetite', 'rationale'],
  properties: {
    scope_block: { type: 'string', description: 'The literal PLANNING SCOPE block: Goal / Constraints (incl. appetite from PROJECT.md) / Inputs (incl. current phase from STATE.md) / Deliverable / Output path.' },
    research_needed: { type: 'boolean', description: 'SKILL Step 2 trigger: unfamiliar domain, multiple non-obvious approaches, or dependencies needing investigation.' },
    high_stakes: { type: 'boolean', description: 'multi-phase, cross-system, or irreversible decisions: ADDS scrutiny; never removes the adversarial-reviewer floor.' },
    llm_prompts: { type: 'boolean', description: 'plan involves LLM prompts or agent design -> prompt-engineer joins review.' },
    exceeds_appetite: { type: 'boolean', description: 'true if the plan scope exceeds the PROJECT.md appetite (must be surfaced before proceeding).' },
    rationale: { type: 'string', description: 'one line per flag justifying the boolean from the actual scope text: no guessing.' },
  },
}

// Step 3 output: the plan must be a FILE on disk (execution evidence), not prose-in-return.
const PLAN_SCHEMA = {
  type: 'object',
  required: ['plan_path', 'has_acceptance_criteria', 'step_count', 'summary'],
  properties: {
    plan_path: { type: 'string', description: 'vault-relative path to the plan .md the agent WROTE (must exist on disk).' },
    has_acceptance_criteria: { type: 'boolean', description: 'does every step carry an acceptance criterion?' },
    step_count: { type: 'integer' },
    summary: { type: 'string', description: 'one-paragraph summary of the plan.' },
  },
}

// Step 4 output: each reviewer returns a structured verdict.
const REVIEW_SCHEMA = {
  type: 'object',
  required: ['verdict', 'blocking_issues', 'notes'],
  properties: {
    verdict: { type: 'string', enum: ['APPROVE', 'APPROVE_WITH_NOTES', 'REQUEST_CHANGES'] },
    blocking_issues: { type: 'array', items: { type: 'string' }, description: 'issues that MUST be fixed before the plan can ship. Empty unless verdict is REQUEST_CHANGES.' },
    notes: { type: 'array', items: { type: 'string' }, description: 'non-blocking observations.' },
  },
}

// ---------------------------------------------------------------------------
// Dual-judge divergence gate (DEF-3 / TA-3 FLAG F3, Tier B; owner-APPROVED 2026-07-16).
// Pure comparison of the TWO mandatory reviewers' ship/no-ship sides. When architect
// and adversarial land on OPPOSITE sides of the ship line, the workflow escalates to
// owner carrying BOTH verdicts instead of silently converging
// ([[feedback_surface_divergent_verdicts_dont_collapse]]). Unexported (only
// `export const meta` may be top-level: finding_workflow_script_second_export_breaks_sandbox);
// the fixture test slices this block by the markers below (never imports the module).
// No agent/parallel/log/args/Date/fs references: must be evaluable in isolation.
// >>> DIVERGENCE_HELPER_START
function classifyDivergence(architectVerdict, adversarialVerdict) {
  function sideOf(v) {
    if (!v || typeof v !== 'object' || !v.verdict) return 'missing'
    if (v.verdict === 'REQUEST_CHANGES') return 'no-ship'
    if (Array.isArray(v.blocking_issues) && v.blocking_issues.length >= 1) return 'no-ship'
    return 'ship'
  }
  const architect_side = sideOf(architectVerdict)
  const adversarial_side = sideOf(adversarialVerdict)
  // A single missing reviewer is NOT divergence (handled by the empty-set guard or
  // the existing blocking-extraction path). Divergence requires TWO present verdicts
  // on opposite sides of the ship line.
  const diverge =
    (architect_side === 'ship' && adversarial_side === 'no-ship') ||
    (architect_side === 'no-ship' && adversarial_side === 'ship')
  let reason
  if (architect_side === 'missing' || adversarial_side === 'missing') {
    reason = `no divergence: a mandatory reviewer is missing (architect=${architect_side}, adversarial=${adversarial_side}): single-reviewer failure is not a ship-line disagreement.`
  } else if (diverge) {
    reason = `dual-judge divergence: architect side=${architect_side}, adversarial side=${adversarial_side}: the two reviewers sit on opposite sides of the ship line.`
  } else {
    reason = `no divergence: architect and adversarial agree (both side=${architect_side}).`
  }
  return { diverge, architect_side, adversarial_side, reason }
}
// <<< DIVERGENCE_HELPER_END

// Step 6 output: the quality gate verdict (gates on real artifact state).
const QUALITY_SCHEMA = {
  type: 'object',
  required: ['plan_file_exists', 'criteria_present', 'dependencies_sequenced', 'risks_noted', 'constraints_respected', 'pass', 'evidence'],
  properties: {
    plan_file_exists: { type: 'boolean', description: 'verified by actually reading the plan_path file.' },
    criteria_present: { type: 'boolean', description: 'acceptance criteria found in the file body (SKILL Step 6.4).' },
    dependencies_sequenced: { type: 'boolean', description: 'steps are sequenced with clear dependencies (SKILL Step 6.3).' },
    risks_noted: { type: 'boolean', description: 'risks and unknowns are explicitly noted (SKILL Step 6.5).' },
    constraints_respected: { type: 'boolean', description: 'plan honors the scope-block constraints/appetite (SKILL Step 6.1/6.2).' },
    pass: { type: 'boolean', description: 'true only if ALL five checks above are true.' },
    evidence: { type: 'string', description: 'the tool calls used to verify (Read/Bash): NOT "looks correct".' },
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// args contract (passed verbatim by the caller):
//   { project: string,                 // e.g. "your-project"
//     goal: string,                    // the one-sentence planning goal
//     constraints?: string,            // any caller-supplied constraints
//     researchFindings?: string }      // synthesized findings IF research already done
//
// PROVENANCE WARNING (architect note N2): researchFindings MUST be the SYNTHESIZED
// output of the process-research skill: NOT ad-hoc research. The research gate
// below only checks PRESENCE, not provenance, so passing raw/unsynthesized findings
// here silently bypasses the H10 entry-point quality gates. The caller is on the
// honor system for this until process-research itself is converted.
//
// DEFERRED (architect note N5): SKILL.md Step 3 says "consider" llm-architect /
// data-engineer parallel dispatches for LLM-system / data-pipeline architecture
// plans. They are `allowed_specialists` (not mandatory) in DISPATCHES.json, so
// omitting them is not a contract violation. Deferred to a later draft; would be a
// conditional design-phase dispatch gated on an `architecture_class` scope flag.
let A = (typeof args === 'object' && args) ? args : {}
// 2026-06-11 hardening (acceptance runs 1+2): the harness can deliver args as a
// JSON-encoDED STRING; the old object-only guard silently discarded it and the
// run proceeded on empty scope (~400K subagent tokens each). Parse-if-string,
// then HALT before spawning any agent if required fields are still missing.
if (typeof args === 'string') {
  try { const p = JSON.parse(args); if (p && typeof p === 'object') A = p } catch (e) { /* fall through to HALT */ }
}
const PROJECT = A.project || 'UNKNOWN'
const GOAL = A.goal || '(no goal supplied)'
if (PROJECT === 'UNKNOWN' || !A.goal) {
  log('HALT: malformed dispatch - args must be a JSON OBJECT {project, goal, constraints?, researchFindings?} with real values. Refusing to spawn agents on empty scope.')
  return { status: 'halted-malformed-args', received_args_type: typeof args, hint: 'pass args as a JSON object with non-empty project and goal' }
}

// Research precondition gate (see KNOWN OPEN DESIGN QUESTION at top).
// The live skill routes research through the process-research SKILL; a workflow
// cannot invoke a skill, so rather than violating H10 by dispatching researchers
// directly, we HALT and hand back when research is needed but findings weren't
// supplied. This keeps the entry-point rule intact.
function researchGate(scope) {
  if (scope.research_needed && !A.researchFindings) {
    log(`HALT: research_needed=true but no researchFindings supplied. Per H10 the caller must run the process-research skill first, then re-invoke this workflow with args.researchFindings. (A workflow cannot invoke a skill.)`)
    return { halted: true, reason: 'research-precondition-not-met' }
  }
  return { halted: false }
}

// ---------------------------------------------------------------------------
// THE PROCEDURE
// ---------------------------------------------------------------------------

// --- Step 1: Define Scope + classify the typed judgment flags ----------------
phase('Scope')
const scope = await agent(
  `You are the scope+classify node of the process-planning procedure for project "${PROJECT}".

GOAL: ${GOAL}
CALLER CONSTRAINTS: ${A.constraints || '(none supplied)'}

1. Read Projects/${PROJECT}/PROJECT.md and Projects/${PROJECT}/STATE.md IF they exist (use the Read tool). Import the appetite (Small/Medium/Large) from PROJECT.md and the current phase + active tasks from STATE.md. If a file does not exist, proceed without it.
2. Emit the PLANNING SCOPE block (Goal / Constraints [include appetite] / Inputs [include current phase] / Deliverable / Output path Projects/${PROJECT}/work/YYYY-MM-DD-<plan-name>.md).
3. Set the typed flags from the ACTUAL scope text (not assumptions): research_needed, high_stakes, llm_prompts, exceeds_appetite. Give a one-line rationale per flag.

Do not design the plan. Do not guess file contents: if you could not read a file, say so in the rationale.`,
  { schema: SCOPE_SCHEMA, label: `scope:${PROJECT}`, phase: 'Scope' }
)

// Null guard (architect note N1): a null scope return must fail descriptively, not
// dereference into an opaque TypeError downstream.
if (!scope || !scope.scope_block) {
  log('Scope step returned nothing usable: halting.')
  return { status: 'scope-failed', project: PROJECT }
}

// N4: this is a warn-and-CONTINUE, intentionally asymmetric with the research gate
// (which HALTS). SKILL.md Step 1 says "flag explicitly before proceeding": a flag,
// not a stop. The oversized plan still gets built but the flag travels in the return.
if (scope.exceeds_appetite) {
  log(`FLAG: plan scope exceeds PROJECT.md appetite: surface to owner before proceeding (SKILL Step 1 rule).`)
}

const gate = researchGate(scope)
if (gate.halted) {
  return { status: 'halted', stage: 'research-gate', scope, reason: gate.reason }
}

// --- Step 3: Design (implementation-plan) ------------------------------------
// (Step 2 research is the precondition gate above; findings, if any, flow in via args.)
phase('Design')
// 2026-06-11 run-4 fix: extract the mandatory output path from the scope block
// (the scope agent dates it; scripts cannot call Date). The design agent MUST
// write to exactly this path -- run 4 failed because the agent returned a
// fabricated plan/ path it never wrote (write-restricted agentType).
const pathMatch = (scope.scope_block || '').match(/Output path:\s*(\S+\.md)/)
const PLAN_PATH = pathMatch ? pathMatch[1] : 'Projects/' + PROJECT + '/work/plan-undated.md'
async function design(feedback) {
  return agent(
    `You are implementation-plan producing the sequenced plan for project "${PROJECT}".

${scope.scope_block}

${A.researchFindings ? 'RESEARCH FINDINGS (already gathered via process-research):\n' + A.researchFindings : 'No research phase was required.'}
${feedback ? '\nREVISION REQUIRED: address these blocking issues from review:\n- ' + feedback.join('\n- ') : ''}

Produce a detailed plan with sequenced steps, dependencies, acceptance criteria per step, and risk flags. Every step MUST have an acceptance criterion.

FILE CONTRACT (non-negotiable):
1. WRITE the complete plan document to EXACTLY this vault path: ${PLAN_PATH}
   Use the Write tool; if Write is unavailable in your context, create the file via Bash (python with utf-8 encoding).
2. VERIFY it landed: Read the file (or Bash cat) and confirm the content.
3. Return plan_path as exactly "${PLAN_PATH}". Any other path, or a path you did not write-and-verify, is a contract violation: reviewers Read this file from disk and reject the run. Do not fabricate file reads: base the plan on the scope block + findings above.`,
    { schema: PLAN_SCHEMA, label: feedback ? 'design:revise' : 'design', phase: 'Design' }
  )
}
let plan = await design(null)

// Null guard (architect note N1): no plan artifact ⇒ stop; the review loop derefs plan.plan_path.
if (!plan || !plan.plan_path) {
  log('Design step returned no plan artifact: halting.')
  return { status: 'design-failed', project: PROJECT, scope }
}

// --- Step 4 + 5: Mandatory parallel review, then capped revise loop ----------
// architect-reviewer ALWAYS. adversarial-reviewer ALWAYS (DISPATCHES.json floor:
// "Planning -> adversarial-reviewer always required"). prompt-engineer IF llm_prompts.
const MAX_REVISE_ROUNDS = 2  // [[feedback_adversarial_loop_ratchets_past_necessity]]: CONVERGED != keep going.

function reviewPrompt(role, lens) {
  return `You are ${role}. Review the plan at ${plan.plan_path} for project "${PROJECT}" against this scope:

${scope.scope_block}

${lens}

RUBRIC (GAP-2 Tier A, 2026-07-10): walk EVERY criterion below IN ORDER against the actual plan text, quoting the specific step or section as evidence, BEFORE you decide anything. State the verdict LAST (reason-then-verdict).
R1 Acceptance criteria: every step carries a falsifiable acceptance criterion.
   pass anchor: "Acceptance: grep returns exactly 2 registrations; suite exit 0."
   fail anchor: a step ending "then verify it works" with no observable check.
R2 Real inputs: every file/path the plan cites as an EXISTING input is real; verify with Read/Glob when in doubt.
   pass anchor: every cited input path opens on disk.
   fail anchor: the plan references an input file that does not exist.
R3 Sequencing: steps are ordered with explicit dependencies; nothing consumes an output produced only by a later step.
   pass anchor: "Step 4 depends on Step 2's consumer list" and Step 2 precedes it.
   fail anchor: a step consumes an artifact a later step creates.
R4 Risk handling: every blocking risk carries a mitigation or an explicit acceptance; irreversible steps name a rollback.
   pass anchor: "config flip mitigated by backup + deny-probe + restore path."
   fail anchor: an irreversible step with no rollback noted.
R5 Scope fit: the plan honors the scope-block constraints and appetite; no unsolicited additions.
   pass anchor: the plan's touch list is a subset of the scoped surface.
   fail anchor: the plan edits files the scope never named.

GRADING DISCIPLINE: judge each criterion ONLY as met / partially met / not met, with quoted evidence. NO free-form numeric grading of any kind (no N-out-of-10, no percentages, no numeric self-assessed certainty).

VERDICT MAPPING (decide LAST, only after all five criteria are walked):
- APPROVE: every criterion met.
- APPROVE_WITH_NOTES: no criterion not-met; partials go into notes.
- REQUEST_CHANGES: any criterion not met in a way that breaks execution; each such failure becomes a blocking_issue naming the criterion (R1-R5) and the offending plan text.

Return verdict (APPROVE / APPROVE_WITH_NOTES / REQUEST_CHANGES), blocking_issues (only if REQUEST_CHANGES), and notes. Read the plan file yourself; do not assume its contents.`
}

let round = 0
let review
let reviewFailed = false
while (true) {
  phase('Review')
  const reviewers = [
    () => agent(reviewPrompt('architect-reviewer', 'Assess feasibility, completeness, SOLID, over-engineering, missing edge cases, and whether every step has an acceptance criterion.'),
      { schema: REVIEW_SCHEMA, label: `review:architect`, phase: 'Review', agentType: 'architect-reviewer' }),
    () => agent(reviewPrompt('adversarial-reviewer', 'Challenge the plan\'s assumptions. Try to find where it fails: unstated dependencies, optimistic sequencing, an irreversible step with no rollback, a constraint silently violated.'),
      { schema: REVIEW_SCHEMA, label: `review:adversarial`, phase: 'Review', agentType: 'adversarial-reviewer' }),
  ]
  if (scope.llm_prompts) {
    reviewers.push(() => agent(reviewPrompt('prompt-engineer', 'Review only the LLM-prompt / agent-design aspects of the plan: prompt clarity, output contracts, failure handling, eval strategy.'),
      { schema: REVIEW_SCHEMA, label: `review:prompt-engineer`, phase: 'Review', agentType: 'prompt-engineer' }))
  }
  const rawVerdicts = await parallel(reviewers)
  const verdicts = rawVerdicts.filter(Boolean)
  review = verdicts

  // BLOCKING FIX B1 (architect): an empty verdict set is NOT convergence. If every
  // reviewer agent failed/returned null, do not let blocking.length===0 masquerade
  // as "all approved": stop with an explicit failure status.
  if (verdicts.length === 0) {
    log(`All ${reviewers.length} reviewer agents returned no verdict: this is a review FAILURE, not convergence. Stopping.`)
    reviewFailed = true
    break
  }

  // Dual-judge divergence gate (DEF-3 / TA-3 FLAG F3, Tier B). The two mandatory
  // reviewers are dispatched in a fixed order (architect first, adversarial second)
  // and parallel() preserves input order, so read them from the UNFILTERED array
  // (a null architect must NOT shift adversarial into slot 0). prompt-engineer, when
  // present, is slot 2 and is excluded from the ship-line pair by design.
  const architectVerdict = rawVerdicts[0]
  const adversarialVerdict = rawVerdicts[1]
  const divergence = classifyDivergence(architectVerdict, adversarialVerdict)
  if (divergence.diverge) {
    log(`ESCALATION: dual-judge divergence: architect=${architectVerdict.verdict} (side=${divergence.architect_side}) vs adversarial=${adversarialVerdict.verdict} (side=${divergence.adversarial_side}). Surfacing BOTH verdicts to owner; NOT converging (feedback_surface_divergent_verdicts_dont_collapse).`)
    return {
      status: 'review-divergence',
      review_divergence: true,
      divergence: { architect: architectVerdict, adversarial: adversarialVerdict, classification: divergence },
      project: PROJECT, scope, plan, review, revise_rounds: round,
    }
  }

  const blocking = verdicts
    .filter(v => v.verdict === 'REQUEST_CHANGES')
    .flatMap(v => v.blocking_issues || [])

  if (blocking.length === 0) {
    log(`Review converged at round ${round}: no blocking issues across ${verdicts.length} reviewers.`)
    break
  }
  if (round >= MAX_REVISE_ROUNDS) {
    log(`Revise cap (${MAX_REVISE_ROUNDS}) reached with ${blocking.length} blocking issue(s) still open: STOP and surface to owner rather than ratcheting.`)
    break
  }
  round += 1
  phase('Revise')
  log(`Revise round ${round}: routing ${blocking.length} blocking issue(s) back to implementation-plan.`)
  plan = await design(blocking)
}

// B1 follow-through: if review never produced a verdict, do not proceed to the
// quality gate as if the plan were vetted: surface the failure to the caller.
if (reviewFailed) {
  return { status: 'review-agents-all-failed', project: PROJECT, scope, plan, revise_rounds: round }
}

// --- Step 6: Quality gate: EXECUTION EVIDENCE, not REPORT presence -----------
phase('Quality')
const quality = await agent(
  `You are the quality gate for the process-planning procedure. Verify the plan EMPIRICALLY: do not trust the summary.

1. Use the Read tool to open ${plan.plan_path}. Set plan_file_exists from whether the read succeeded.
2. Confirm acceptance criteria are actually present in the file body (criteria_present).
3. Confirm steps are sequenced with clear dependencies (dependencies_sequenced).
4. Confirm risks and unknowns are explicitly noted (risks_noted).
5. Confirm the plan respects the scope-block constraints/appetite (constraints_respected).

DISCIPLINE (GAP-2 Tier A): walk checks 1-5 IN ORDER, citing for each the tool call you made and the literal content that decides it, BEFORE setting any boolean (reason-then-verdict). Each check is strictly true/false on that evidence; NO free-form numeric grading of any kind (no N-out-of-10, no percentages, no numeric self-assessed certainty).
Set pass = (plan_file_exists AND criteria_present AND dependencies_sequenced AND risks_noted AND constraints_respected). In evidence, name the actual tool calls you made: "looks correct" is not evidence.

Scope for reference:
${scope.scope_block}`,
  { schema: QUALITY_SCHEMA, label: 'quality-gate', phase: 'Quality' }
)

// Pentest hardening (gate on evidence, not self-report: corpus Reframe 2, same
// principle as the B1 fix): derive pass in CODE from the evidence sub-fields. Do
// NOT trust the agent's self-reported `quality.pass`: a quality agent that
// misreports pass=true while a sub-check is false must NOT yield a false 'complete'.
const qualityPass = !!(quality
  && quality.plan_file_exists
  && quality.criteria_present
  && quality.dependencies_sequenced
  && quality.risks_noted
  && quality.constraints_respected)

// ---------------------------------------------------------------------------
return {
  status: qualityPass ? 'complete' : 'quality-failed',
  project: PROJECT,
  scope,
  plan,
  review,
  revise_rounds: round,
  quality,
  quality_pass_derived: qualityPass,
}
