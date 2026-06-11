/*
 * ADOPTED 2026-06-11 — Increment 2, procedure-layer migration (owner GO).
 * Source draft: (design records vault-internal)
 * Scope: routing-as-code — the script drives dispatch sequence; agents reason freely inside steps.
 * DISPATCHES.json stays authoritative for H11 read-only verification (do not retire it).
 * Quality gates inside derive pass/fail from execution evidence (raw tool output), never from report presence.
 */

export const meta = {
  name: 'process-analysis',
  description: 'Deterministic encoding of the process-analysis procedure (Evaluation + Investigation modes). Decomposition mode HALTs-and-hands-back — it invokes other process skills, which a workflow cannot do. Scope -> mode branch -> specialist fan-out -> synthesis (research-synthesizer, mandatory if 2+ specialists, enforced in code) -> report (conditional on complex flag) -> quality gate. Routing-as-code; agents work freely inside steps.',
  phases: [
    { title: 'Scope', detail: 'emit ANALYSIS SCOPE block, infer or confirm mode, build specialist list, flag rubric requirements' },
    { title: 'Analyze', detail: 'dispatch specialists in parallel per scope subjects list; bias-guard: prompts contain scope facts only' },
    { title: 'Synthesis', detail: 'research-synthesizer mandatory when dispatch count >= 2 (enforced in code)' },
    { title: 'Report', detail: 'report-generator conditional on complex flag; otherwise synthesis/single-agent output is the deliverable' },
    { title: 'Quality', detail: 'gate on execution evidence: output file exists + all criteria addressed' },
  ],
}

// ---------------------------------------------------------------------------
// Typed schemas
// ---------------------------------------------------------------------------

// Step 1 output: ANALYSIS SCOPE block + routing data.
const SCOPE_SCHEMA = {
  type: 'object',
  required: ['scope_block', 'output_path', 'mode', 'subjects', 'rubric', 'complex', 'rationale'],
  properties: {
    scope_block: { type: 'string', description: 'The literal ANALYSIS SCOPE block: Mode / Subject / Question-or-rubric / Deliverable / Output path Projects/<name>/work/YYYY-MM-DD-<subject>-analysis.md.' },
    output_path: { type: 'string', description: 'The exact vault-relative output path (e.g. Projects/Foo/work/2026-06-11-foo-analysis.md). The script uses this — do NOT leave it only in scope_block prose.' },
    mode: { type: 'string', enum: ['evaluation', 'investigation', 'decomposition'], description: 'Evaluation: artifact vs rubric. Investigation: causal/behavioral chain. Decomposition: break compound into sub-tasks (triggers HALT).' },
    subjects: { type: 'array', items: { type: 'string', enum: ['prompt-engineer', 'architect-reviewer', 'debugger', 'api-designer', 'data-engineer', 'n8n-workflow-architect', 'api-security-audit', 'adversarial-reviewer'] }, description: 'ordered list of specialist agents to dispatch, drawn from the allowed_specialists table in SKILL.md. Bias guard: populated from scope facts only.' },
    rubric: { type: 'string', description: 'The rubric to evaluate against (evaluation mode) or the core question (investigation mode). For evaluation mode this field MUST be non-empty — if no rubric was supplied, the scope agent defines one before returning.' },
    complex: { type: 'boolean', description: 'true if the analysis warrants a formal report-generator pass (multi-agent evaluation or substantial investigation).' },
    decomposition_subtasks: { type: 'array', items: { type: 'string' }, description: 'only populated for decomposition mode: the numbered sub-task list with TYPE + DOMAIN + dependencies. The HALT carries this so the main session can execute sub-tasks via the prose path.' },
    rationale: { type: 'string', description: 'one line per field justifying the value from actual scope text.' },
  },
}

// Step 2 output per specialist: findings against the rubric/question.
const SPECIALIST_SCHEMA = {
  type: 'object',
  required: ['agent_role', 'findings', 'verdict_or_conclusion'],
  properties: {
    agent_role: { type: 'string', description: 'which specialist agent produced these findings.' },
    findings: { type: 'string', description: 'substantive analysis findings — evidence cited with line numbers or specific examples.' },
    verdict_or_conclusion: { type: 'string', description: 'the specialist\'s verdict (evaluation) or conclusion (investigation).' },
  },
}

// Step 3 output: synthesis (only when 2+ specialists dispatched).
const SYNTHESIS_SCHEMA = {
  type: 'object',
  required: ['synthesis_text', 'contradictions_resolved', 'unified_verdict'],
  properties: {
    synthesis_text: { type: 'string', description: 'merged coherent analysis from all specialist findings.' },
    contradictions_resolved: { type: 'array', items: { type: 'string' }, description: 'contradictions between specialist assessments and how they were resolved.' },
    unified_verdict: { type: 'string', description: 'the synthesized verdict or conclusion.' },
  },
}

// Step 4 output: optional report file on disk.
const REPORT_SCHEMA = {
  type: 'object',
  required: ['report_path', 'report_exists'],
  properties: {
    report_path: { type: 'string', description: 'vault-relative path to the report .md the agent WROTE (must exist on disk; must match FILE CONTRACT path).' },
    report_exists: { type: 'boolean', description: 'agent confirmed the file exists after writing.' },
  },
}

// Step 5 output: quality gate.
const QUALITY_SCHEMA = {
  type: 'object',
  required: ['output_file_exists', 'all_criteria_addressed', 'evidence_cited', 'pass', 'evidence'],
  properties: {
    output_file_exists: { type: 'boolean', description: 'verified by actually reading the output_path file.' },
    all_criteria_addressed: { type: 'boolean', description: 'every rubric criterion (evaluation) or every aspect of the core question (investigation) is addressed with a clear assessment.' },
    evidence_cited: { type: 'boolean', description: 'findings include line numbers, specific examples, or tool results — not unsupported assertions.' },
    pass: { type: 'boolean', description: 'true only if ALL three checks above are true.' },
    evidence: { type: 'string', description: 'the tool calls used to verify (Read/Bash) — NOT "looks correct".' },
  },
}

// ---------------------------------------------------------------------------
// args contract (passed verbatim by the caller):
//   { project:       string                                    (required)
//     subject:       string                                    (required) — what to analyze
//     mode?:         'evaluation'|'investigation'|'decomposition'  (scope agent infers when omitted)
//     rubric?:       string                                    (optional, evaluation mode)
//     constraints?:  string                                    (optional)
//   }
//
// HALT conditions: project or subject missing; decomposition mode (always hand back).
// ---------------------------------------------------------------------------
let A = (typeof args === 'object' && args) ? args : {}
if (typeof args === 'string') {
  try { const p = JSON.parse(args); if (p && typeof p === 'object') A = p } catch (e) { /* fall through to HALT */ }
}
const PROJECT = A.project || 'UNKNOWN'
const SUBJECT = A.subject || ''
if (PROJECT === 'UNKNOWN' || !SUBJECT) {
  log('HALT: malformed dispatch — args must be a JSON OBJECT {project, subject, mode?, rubric?, constraints?} with real values. Refusing to spawn agents on empty scope.')
  return { status: 'halted-malformed-args', received_args_type: typeof args, hint: 'pass args as a JSON object with non-empty project and subject' }
}

// ---------------------------------------------------------------------------
// THE PROCEDURE
// ---------------------------------------------------------------------------

// --- Step 1: Define Scope + classify mode and specialist list ---------------
phase('Scope')
const scope = await agent(
  `You are the scope+classify node of the process-analysis procedure for project "${PROJECT}".

SUBJECT TO ANALYZE: ${SUBJECT}
MODE (caller hint, may be empty): ${A.mode || '(infer from subject)'}
RUBRIC (caller-supplied if any): ${A.rubric || '(none — define one if evaluation mode)'}
CALLER CONSTRAINTS: ${A.constraints || '(none supplied)'}

1. Read Projects/${PROJECT}/PROJECT.md and Projects/${PROJECT}/STATE.md IF they exist (use the Read tool). Import context. If a file does not exist, proceed without it.
2. Emit the ANALYSIS SCOPE block:
   Mode: [Evaluation | Investigation | Decomposition]
   Subject: [what is being evaluated, investigated, or decomposed]
   Question: [Evaluation: the rubric. Investigation: the core question. Decomposition: the compound request]
   Deliverable: [assessment / reasoning chain / sub-task list]
   Output path: Projects/${PROJECT}/work/YYYY-MM-DD-<subject>-analysis.md
3. Set the typed fields:
   - mode: evaluation | investigation | decomposition (infer if not supplied)
   - subjects: list of specialist agents from the allowed list [prompt-engineer, architect-reviewer, debugger, api-designer, data-engineer, n8n-workflow-architect, api-security-audit, adversarial-reviewer] — POPULATE FROM SCOPE FACTS ONLY (no pre-judgment)
   - rubric: for evaluation mode, this MUST be non-empty — define a rubric if the caller did not supply one
   - complex: true if multiple specialists or substantial investigation warrants a formal report
   - decomposition_subtasks: ONLY if mode=decomposition — numbered sub-task list with TYPE + DOMAIN + dependencies (cap 1 level: if a sub-task looks Compound, flatten it)
4. Extract output_path as a standalone field.

BIAS GUARD: populate the subjects list from observable scope facts only — no hypotheses, no proposed conclusions.`,
  { schema: SCOPE_SCHEMA, label: `scope:${PROJECT}`, phase: 'Scope' }
)

if (!scope || !scope.scope_block) {
  log('Scope step returned nothing usable — halting.')
  return { status: 'scope-failed', project: PROJECT }
}

// Decomposition mode HALTs — it invokes other process skills, which a workflow cannot do.
if (scope.mode === 'decomposition') {
  log('HALT: decomposition mode — invoking other process skills per sub-task is impossible inside a workflow. Returning sub-task list to the main session for prose-path execution.')
  return {
    status: 'decomposition-hand-back',
    project: PROJECT,
    scope,
    decomposition_subtasks: scope.decomposition_subtasks || [],
    reason: 'Decomposition mode produces a sub-task list; each sub-task must be executed by invoking the appropriate process skill (process-build, process-research, etc.) from the main session. The workflow cannot invoke skills. Use the returned decomposition_subtasks list to execute each sub-task in order via the prose skill path.',
  }
}

// Evaluation mode guard: rubric MUST be non-empty (required schema field when mode=evaluation)
if (scope.mode === 'evaluation' && (!scope.rubric || scope.rubric.trim() === '')) {
  log('HALT: evaluation mode but no rubric — the scope agent must define a rubric before specialists dispatch. This is a scope step failure.')
  return { status: 'scope-failed-no-rubric', project: PROJECT, scope, reason: 'evaluation mode requires a rubric; re-invoke with a rubric in args or let the scope agent define one (check the scope_block)' }
}

const OUTPUT_PATH = scope.output_path || ('Projects/' + PROJECT + '/work/analysis-undated.md')
const specialists = Array.isArray(scope.subjects) ? scope.subjects : []

if (specialists.length === 0) {
  log('Scope returned no specialist agents — halting (cannot analyze without at least one specialist).')
  return { status: 'scope-failed-no-specialists', project: PROJECT, scope }
}

// --- Step 2: Specialist fan-out (in parallel) --------------------------------
phase('Analyze')
log(`Dispatching ${specialists.length} specialist(s) in parallel: ${specialists.join(', ')}`)

const specialistTasks = specialists.map((agentName, i) => () => agent(
  `You are ${agentName} conducting a ${scope.mode} analysis for project "${PROJECT}".

ANALYSIS SCOPE:
${scope.scope_block}

RUBRIC / CORE QUESTION:
${scope.rubric}

${scope.mode === 'evaluation'
  ? `Evaluate the subject against EVERY criterion in the rubric above. For each criterion, provide a clear assessment with evidence (line numbers, specific examples). Do NOT skip criteria or gloss over them. State observable facts only — no pre-judged conclusions.`
  : `Investigate the core question by tracing behavior, reasoning from observations to conclusions. Consider alternative explanations and rule them out with evidence. For each step in your reasoning, cite specific evidence (tool output, file content, specific examples). State observable facts only.`
}

ARTIFACT to examine: ${SUBJECT}

Read and examine the artifact using Read/Glob/Grep tools. Do not invent content — if a file does not exist, state that explicitly.`,
  { schema: SPECIALIST_SCHEMA, label: `analyze:${agentName}:${i}`, phase: 'Analyze', agentType: agentName }
))

const specialistResults = (await parallel(specialistTasks)).filter(Boolean)

if (specialistResults.length === 0) {
  log('All specialist agents returned nothing — halting.')
  return { status: 'analyze-failed', project: PROJECT, scope }
}

// --- Step 3: Synthesis — MANDATORY if 2+ specialists (enforced IN CODE) -----
// Dispatch count derived from specialistResults.length, never agent judgment.
let analysisText = specialistResults.length === 1 ? (specialistResults[0].findings + '\n\n' + specialistResults[0].verdict_or_conclusion) : null

if (specialistResults.length >= 2) {
  phase('Synthesis')
  log(`Synthesis mandatory: ${specialistResults.length} specialist agents dispatched (enforced in code).`)
  const synthesis = await agent(
    `You are research-synthesizer. Merge the specialist findings below into a unified ${scope.mode} analysis for project "${PROJECT}".

ANALYSIS SCOPE:
${scope.scope_block}

SPECIALIST FINDINGS:
${specialistResults.map((s, i) => `--- Specialist ${i + 1}: ${s.agent_role} ---\nFindings: ${s.findings}\nVerdict/Conclusion: ${s.verdict_or_conclusion}`).join('\n\n')}

Merge findings, resolve any contradictions between specialist assessments (note how), produce a unified verdict or conclusion. Preserve evidence citations.`,
    { schema: SYNTHESIS_SCHEMA, label: 'synthesis', phase: 'Synthesis', agentType: 'research-synthesizer' }
  )
  if (!synthesis || !synthesis.synthesis_text) {
    log('Synthesis step returned nothing usable — halting.')
    return { status: 'synthesis-failed', project: PROJECT, scope, specialist_results: specialistResults }
  }
  analysisText = synthesis.synthesis_text + '\n\nUnified verdict/conclusion: ' + synthesis.unified_verdict
}

// --- Step 4: Report (conditional on complex flag) ---------------------------
let reportPath = OUTPUT_PATH
let reportResult = null

if (scope.complex) {
  phase('Report')
  reportResult = await agent(
    `You are report-generator. Write the final analysis report for project "${PROJECT}".

SCOPE:
${scope.scope_block}

ANALYSIS (synthesized findings):
${analysisText}

FILE CONTRACT (non-negotiable):
1. WRITE the complete analysis report to EXACTLY this vault path: ${OUTPUT_PATH}
   Use the Write tool (default subagent — Write tool IS available to you). If Write is unavailable, use Bash (python with utf-8 encoding).
2. VERIFY it landed: Read the file and confirm content.
3. Return report_path as exactly "${OUTPUT_PATH}". Any other path you did not write-and-verify is a contract violation.
4. Return report_exists = true only after confirming the file is on disk.`,
    { schema: REPORT_SCHEMA, label: 'report', phase: 'Report', agentType: 'report-generator' }
  )
  if (reportResult && reportResult.report_path) {
    reportPath = reportResult.report_path
  }
} else {
  // For simple single-agent analysis, write the output directly.
  // The quality gate verifies the file exists — it must be written here.
  const writeResult = await agent(
    `You are a writing agent for project "${PROJECT}". Write the analysis output to disk.

ANALYSIS CONTENT:
${analysisText}

SCOPE (for context):
${scope.scope_block}

FILE CONTRACT (non-negotiable):
1. WRITE the analysis to EXACTLY this vault path: ${OUTPUT_PATH}
   Use the Write tool (default subagent — Write tool IS available to you). If Write is unavailable, use Bash (python with utf-8 encoding).
2. VERIFY it landed: Read the file and confirm content.
3. Return report_path as exactly "${OUTPUT_PATH}" and report_exists = true only after confirming.`,
    { schema: REPORT_SCHEMA, label: 'write-output', phase: 'Report' }
  )
  if (writeResult && writeResult.report_path) {
    reportPath = writeResult.report_path
    reportResult = writeResult
  }
}

// --- Step 5: Quality gate ---------------------------------------------------
phase('Quality')
const quality = await agent(
  `You are the quality gate for the process-analysis procedure. Verify the analysis output EMPIRICALLY.

1. Use the Read tool to open ${reportPath}. Set output_file_exists from whether the read succeeded.
2. Confirm every criterion in the rubric (evaluation) or every aspect of the core question (investigation) is addressed with a clear assessment (all_criteria_addressed).
3. Confirm findings include evidence citations — line numbers, specific examples, or tool results (evidence_cited).
Set pass = (output_file_exists AND all_criteria_addressed AND evidence_cited). In evidence, name the actual tool calls you made — "looks correct" is not evidence.

Scope for reference:
${scope.scope_block}`,
  { schema: QUALITY_SCHEMA, label: 'quality-gate', phase: 'Quality' }
)

// Derive pass IN CODE from evidence sub-fields — never trust agent self-report.
const qualityPass = !!(quality
  && quality.output_file_exists
  && quality.all_criteria_addressed
  && quality.evidence_cited)

// ---------------------------------------------------------------------------
return {
  status: qualityPass ? 'complete' : 'quality-failed',
  project: PROJECT,
  scope,
  specialist_count: specialistResults.length,
  report_path: reportPath,
  quality,
  quality_pass_derived: qualityPass,
}
