/*
 * ADOPTED 2026-06-11 — Increment 2, procedure-layer migration (owner GO).
 * Source draft: (design records vault-internal)
 * Scope: routing-as-code — the script drives dispatch sequence; agents reason freely inside steps.
 * DISPATCHES.json stays authoritative for H11 read-only verification (do not retire it).
 * Quality gates inside derive pass/fail from execution evidence (raw tool output), never from report presence.
 */

export const meta = {
  name: 'process-research',
  description: 'Deterministic encoding of the process-research procedure (direct path 3B only): scope -> route (research-analyst / technical-researcher / research-orchestrator based on coverage flag) -> synthesis (research-synthesizer, mandatory if 2+ gatherers, enforced in code) -> report-generator (mandatory) -> quality gate. Ralph Loop path (3A) HALTs-and-hands-back to the main session — workflows cannot invoke the architect-loop skill. Routing-as-code; agents work freely inside steps.',
  phases: [
    { title: 'Scope', detail: 'read project state, emit RESEARCH SCOPE, classify coverage flag and ralph_loop_indicated' },
    { title: 'Research', detail: 'dispatch research-analyst / technical-researcher / research-orchestrator per coverage; parallel when both needed' },
    { title: 'Synthesis', detail: 'research-synthesizer mandatory when dispatch count >= 2 (enforced in code)' },
    { title: 'Report', detail: 'report-generator mandatory (DISPATCHES.json floor); writes output to disk with FILE CONTRACT' },
    { title: 'Quality', detail: 'gate on execution evidence: report file exists + all questions answered or flagged' },
  ],
}

// ---------------------------------------------------------------------------
// Typed schemas
// ---------------------------------------------------------------------------

// Step 1 output: RESEARCH SCOPE block + routing flags.
const SCOPE_SCHEMA = {
  type: 'object',
  required: ['scope_block', 'output_path', 'coverage', 'ralph_loop_indicated', 'rationale'],
  properties: {
    scope_block: { type: 'string', description: 'The literal RESEARCH SCOPE block: Questions (numbered list) / Sources available / Deliverable / Output path Projects/<name>/work/YYYY-MM-DD-<topic>-research.md.' },
    output_path: { type: 'string', description: 'The exact vault-relative output path for the research report (e.g. Projects/Foo/work/2026-06-11-topic-research.md). The script uses this — do NOT leave it only embedded in scope_block prose.' },
    coverage: { type: 'string', enum: ['web', 'technical', 'both', 'orchestrated'], description: 'web: research-analyst only; technical: technical-researcher only; both: both in parallel; orchestrated: research-orchestrator (4+ sub-questions).' },
    ralph_loop_indicated: { type: 'boolean', description: 'true if ALL of: 3+ distinct open questions AND 3+ source files or multiple web sources AND anchoring-risk from conversation context. When true the workflow HALTs and hands back to the main session for the architect-loop path.' },
    rationale: { type: 'string', description: 'one line per flag justifying the value from actual scope text.' },
  },
}

// Step 3 output per researcher: raw findings to feed synthesis.
const FINDINGS_SCHEMA = {
  type: 'object',
  required: ['agent_role', 'findings', 'sources_consulted'],
  properties: {
    agent_role: { type: 'string', description: 'which agent produced these findings (research-analyst / technical-researcher / research-orchestrator).' },
    findings: { type: 'string', description: 'the substantive findings text — not a summary of the process, the actual findings.' },
    sources_consulted: { type: 'array', items: { type: 'string' }, description: 'URLs, file paths, or source names consulted.' },
  },
}

// Step 4 output: synthesis (only when 2+ researchers dispatched).
const SYNTHESIS_SCHEMA = {
  type: 'object',
  required: ['synthesis_text', 'contradictions_resolved', 'unconfirmed_items'],
  properties: {
    synthesis_text: { type: 'string', description: 'merged, coherent synthesis of all research findings.' },
    contradictions_resolved: { type: 'array', items: { type: 'string' }, description: 'any contradictions between findings and how they were resolved.' },
    unconfirmed_items: { type: 'array', items: { type: 'string' }, description: 'claims that could not be confirmed from sources.' },
  },
}

// Step 5 output: report must be a FILE on disk.
const REPORT_SCHEMA = {
  type: 'object',
  required: ['report_path', 'report_exists', 'questions_answered'],
  properties: {
    report_path: { type: 'string', description: 'vault-relative path to the report .md the agent WROTE (must exist on disk; must match FILE CONTRACT path).' },
    report_exists: { type: 'boolean', description: 'agent confirmed the file exists after writing.' },
    questions_answered: { type: 'array', items: { type: 'string' }, description: 'list of scope questions answered. Any unanswered question must be listed with a note explaining why.' },
  },
}

// Step 6 output: quality gate.
const QUALITY_SCHEMA = {
  type: 'object',
  required: ['report_file_exists', 'all_questions_addressed', 'sources_cited', 'pass', 'evidence'],
  properties: {
    report_file_exists: { type: 'boolean', description: 'verified by actually reading the report_path file.' },
    all_questions_addressed: { type: 'boolean', description: 'every scope question is either answered or explicitly noted as unanswerable with a reason.' },
    sources_cited: { type: 'boolean', description: 'key claims have source citations in the report body.' },
    pass: { type: 'boolean', description: 'true only if ALL three checks above are true.' },
    evidence: { type: 'string', description: 'the tool calls used to verify (Read/Bash) — NOT "looks correct".' },
  },
}

// ---------------------------------------------------------------------------
// args contract (passed verbatim by the caller):
//   { project:      string          (required) — e.g. "MyProject"
//     question:     string          (required) — the research question
//     sources?:     array<string>   (optional) — known starting sources
//     constraints?: string          (optional) — environment limits
//   }
//
// HALT conditions: project or question missing.
// ---------------------------------------------------------------------------
let A = (typeof args === 'object' && args) ? args : {}
if (typeof args === 'string') {
  try { const p = JSON.parse(args); if (p && typeof p === 'object') A = p } catch (e) { /* fall through to HALT */ }
}
const PROJECT  = A.project  || 'UNKNOWN'
const QUESTION = A.question || ''
if (PROJECT === 'UNKNOWN' || !QUESTION) {
  log('HALT: malformed dispatch — args must be a JSON OBJECT {project, question, sources?, constraints?} with real values. Refusing to spawn agents on empty scope.')
  return { status: 'halted-malformed-args', received_args_type: typeof args, hint: 'pass args as a JSON object with non-empty project and question' }
}
const SOURCES = Array.isArray(A.sources) ? A.sources.join(', ') : (A.sources || '(none listed)')

// ---------------------------------------------------------------------------
// THE PROCEDURE
// ---------------------------------------------------------------------------

// --- Step 1: Define Scope + classify routing flags --------------------------
phase('Scope')
const scope = await agent(
  `You are the scope+classify node of the process-research procedure for project "${PROJECT}".

RESEARCH QUESTION: ${QUESTION}
CALLER CONSTRAINTS: ${A.constraints || '(none supplied)'}
KNOWN SOURCES: ${SOURCES}

1. Read Projects/${PROJECT}/PROJECT.md and Projects/${PROJECT}/STATE.md IF they exist (use the Read tool). Import context relevant to the research question. If a file does not exist, proceed without it.
2. Emit the RESEARCH SCOPE block:
   Questions: [numbered list — be specific; break the main question into sub-questions]
   Sources available: [known files, URLs, or "web search"]
   Deliverable: [format the output should take]
   Output path: Projects/${PROJECT}/work/YYYY-MM-DD-<topic>-research.md
3. Classify the routing flags from the ACTUAL scope:
   - coverage: 'web' | 'technical' | 'both' | 'orchestrated' (4+ sub-questions)
   - ralph_loop_indicated: true ONLY if ALL three criteria hold (3+ distinct open questions AND 3+ sources AND anchoring-risk from current context)
4. Extract output_path as a standalone field.

Do not gather research. Do not guess file contents.`,
  { schema: SCOPE_SCHEMA, label: `scope:${PROJECT}`, phase: 'Scope' }
)

if (!scope || !scope.scope_block) {
  log('Scope step returned nothing usable — halting.')
  return { status: 'scope-failed', project: PROJECT }
}

// Ralph Loop path (3A): HALT and hand back — a workflow cannot invoke the architect-loop skill.
if (scope.ralph_loop_indicated) {
  log('HALT: ralph_loop_indicated=true. The direct path (3B) is insufficient for this research scope. Per SKILL.md Step 3A: the caller must invoke the architect-loop skill via the prose path, then re-invoke process-research with the loop findings as input (or use the returned scope_block to start the loop).')
  return {
    status: 'ralph-loop-hand-back',
    project: PROJECT,
    scope,
    reason: 'ralph_loop_indicated=true — 3+ distinct questions + 3+ sources + anchoring risk. Use the SKILL.md Step 3A prose path: invoke architect-loop with the scope_block below, gather fresh-context findings, then re-invoke this workflow with those findings as the question parameter.',
    scope_block_for_loop: scope.scope_block,
  }
}

const OUTPUT_PATH = scope.output_path || ('Projects/' + PROJECT + '/work/research-undated.md')

// --- Step 3: Research dispatch — route per coverage flag --------------------
phase('Research')
// Coverage => dispatch set (entry-point rule enforced structurally: this script owns
// the dispatch; main session never reaches researchers directly).
let rawFindings = []

if (scope.coverage === 'orchestrated') {
  // 4+ sub-questions: research-orchestrator coordinates internally
  const orchResult = await agent(
    `You are research-orchestrator. Coordinate multi-phase research for project "${PROJECT}".

${scope.scope_block}

Conduct thorough multi-phase research. Coordinate research-analyst and technical-researcher as needed for full coverage. Gather findings from all relevant sources. Bias toward observable facts; do not pre-judge answers.`,
    { schema: FINDINGS_SCHEMA, label: 'research:orchestrated', phase: 'Research', agentType: 'research-orchestrator' }
  )
  if (orchResult) rawFindings.push(orchResult)
} else {
  // web, technical, or both — dispatch the appropriate agents in parallel
  const researchTasks = []

  if (scope.coverage === 'web' || scope.coverage === 'both') {
    researchTasks.push(() => agent(
      `You are research-analyst. Research the following for project "${PROJECT}" using web sources, trends, and multi-source synthesis.

${scope.scope_block}

Gather findings from web sources. State observable facts only — do not pre-judge answers. Cite sources for key claims.`,
      { schema: FINDINGS_SCHEMA, label: 'research:web', phase: 'Research', agentType: 'research-analyst' }
    ))
  }

  if (scope.coverage === 'technical' || scope.coverage === 'both') {
    researchTasks.push(() => agent(
      `You are technical-researcher. Research the following for project "${PROJECT}" using code repos, technical docs, and API behavior.

${scope.scope_block}

Gather findings from technical sources (repos, docs, code). State observable facts only — do not pre-judge answers. Cite sources for key claims.`,
      { schema: FINDINGS_SCHEMA, label: 'research:technical', phase: 'Research', agentType: 'technical-researcher' }
    ))
  }

  const results = (await parallel(researchTasks)).filter(Boolean)
  rawFindings = results
}

if (rawFindings.length === 0) {
  log('Research step returned no findings — halting.')
  return { status: 'research-failed', project: PROJECT, scope }
}

// --- Step 4: Synthesis — MANDATORY if 2+ dispatchers (enforced IN CODE) -----
// Count is derived from rawFindings.length, not agent judgment.
let synthesisText = rawFindings.length === 1 ? rawFindings[0].findings : null

if (rawFindings.length >= 2) {
  phase('Synthesis')
  log(`Synthesis mandatory: ${rawFindings.length} researcher agents dispatched (enforced in code).`)
  const synthesis = await agent(
    `You are research-synthesizer. Merge the findings below into a coherent synthesis for project "${PROJECT}".

SCOPE (questions to answer):
${scope.scope_block}

FINDINGS FROM EACH AGENT:
${rawFindings.map((f, i) => `--- Agent ${i + 1}: ${f.agent_role} ---\n${f.findings}`).join('\n\n')}

Merge findings into a coherent synthesis. Resolve contradictions (note how you resolved them). Flag any claims that could not be confirmed. Preserve source citations.`,
    { schema: SYNTHESIS_SCHEMA, label: 'synthesis', phase: 'Synthesis', agentType: 'research-synthesizer' }
  )
  if (!synthesis || !synthesis.synthesis_text) {
    log('Synthesis step returned nothing usable — halting.')
    return { status: 'synthesis-failed', project: PROJECT, scope, raw_findings: rawFindings }
  }
  synthesisText = synthesis.synthesis_text
}

// --- Step 5: Report (MANDATORY — DISPATCHES.json floor) ---------------------
phase('Report')
const report = await agent(
  `You are report-generator. Write the final research report for project "${PROJECT}".

SCOPE:
${scope.scope_block}

SYNTHESIZED FINDINGS:
${synthesisText}

FILE CONTRACT (non-negotiable):
1. WRITE the complete research report to EXACTLY this vault path: ${OUTPUT_PATH}
   Use the Write tool (default subagent — Write tool IS available to you). If Write is unavailable, use Bash (python with utf-8 encoding).
2. VERIFY it landed: Read the file and confirm content.
3. Return report_path as exactly "${OUTPUT_PATH}". Any other path, or a path you did not write-and-verify, is a contract violation.
4. Return report_exists = true only after confirming the file is on disk.
5. List every scope question and whether it was answered (questions_answered array).

Format: Follow the deliverable format from the scope block. Cite sources for key claims.`,
  { schema: REPORT_SCHEMA, label: 'report', phase: 'Report', agentType: 'report-generator' }
)

if (!report || !report.report_path) {
  log('Report step returned no report path — halting.')
  return { status: 'report-failed', project: PROJECT, scope }
}

// --- Step 6: Quality gate ---------------------------------------------------
phase('Quality')
const quality = await agent(
  `You are the quality gate for the process-research procedure. Verify the report EMPIRICALLY.

1. Use the Read tool to open ${report.report_path}. Set report_file_exists from whether the read succeeded.
2. For every question in the scope, confirm the report addresses it or explicitly notes it as unanswerable (all_questions_addressed).
3. Confirm key claims have source citations in the report body (sources_cited).
Set pass = (report_file_exists AND all_questions_addressed AND sources_cited). In evidence, name the actual tool calls you made — "looks correct" is not evidence.

Scope for reference:
${scope.scope_block}`,
  { schema: QUALITY_SCHEMA, label: 'quality-gate', phase: 'Quality' }
)

// Derive pass IN CODE from evidence sub-fields — never trust agent self-report.
const qualityPass = !!(quality
  && quality.report_file_exists
  && quality.all_questions_addressed
  && quality.sources_cited)

// ---------------------------------------------------------------------------
return {
  status: qualityPass ? 'complete' : 'quality-failed',
  project: PROJECT,
  scope,
  raw_findings_count: rawFindings.length,
  report,
  quality,
  quality_pass_derived: qualityPass,
}
