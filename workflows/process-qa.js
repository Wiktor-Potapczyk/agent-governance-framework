/*
 * ADOPTED 2026-06-11 — Increment 2, procedure-layer migration (owner GO).
 * Source draft: (design records vault-internal)
 * Scope: terminal execution-class workflow — the script drives per-claim execution and computes
 *   PASS/FAIL counts IN CODE from typed per-claim evidence fields. Never trust agent self-report.
 * DISPATCHES.json stays authoritative for H11 read-only verification (do not retire it).
 *
 * HOOK PRECONDITIONS (must be on disk before this workflow's thin-invoker SKILL.md is swapped in):
 *   (process-step-check.py): recognizes Workflow process-qa AND survives the tool_result wrapper reset.
 *   (work-verification-check.py): sets has_process_qa=True via Workflow invocation (clears CHECK 1b).
 *   (work-verification-check.py): qa_via_workflow flag suppresses CHECK 1's zero-execution-tools block.
 * Without those two work-verification fixes, a Workflow process-qa run false-blocks on CHECK 1 because execution tools run
 * inside the workflow subagent and are invisible to the main-transcript tool list.
 * The evidence obligation does NOT vanish — it MOVES into the typed per-claim fields below.
 */

export const meta = {
  name: 'process-qa',
  description: 'Terminal execution-class workflow: scope -> per-claim execute-agents (each runs real Bash/MCP/Read and returns typed evidence) -> PASS/FAIL computed IN CODE from evidence fields (auto-FAIL if execution-class claim verified by Read/Grep only) -> QA SCOPE + QA REPORT text assembled in code for transcript relay. Args: {project, claims, source?, constraints?}.',
  phases: [
    { title: 'Scope', detail: 'normalize claims to typed objects; scope agent assigns claim_class where omitted' },
    { title: 'Execute', detail: 'one agent per claim — runs real tools, returns typed evidence; parallel' },
    { title: 'Report', detail: 'PASS/FAIL derived in code from evidence fields; QA SCOPE + QA REPORT assembled for relay' },
  ],
}

// ---------------------------------------------------------------------------
// Typed schemas
// ---------------------------------------------------------------------------

// Step 1 output: normalized, typed claim list.
const SCOPE_SCHEMA = {
  type: 'object',
  required: ['scope_summary', 'typed_claims'],
  properties: {
    scope_summary: { type: 'string', description: 'one-sentence statement of what is being QA\'d and from what source.' },
    typed_claims: {
      type: 'array',
      description: 'the claims to verify, each typed with the required tool class.',
      items: {
        type: 'object',
        required: ['claim', 'claim_class', 'artifact'],
        properties: {
          claim: { type: 'string', description: 'the specific, verifiable claim.' },
          claim_class: { type: 'string', enum: ['execute', 'read', 'mcp'], description: 'execute: requires Bash or execution of code/hook/API; read: Read/Grep is sufficient; mcp: requires an MCP query to a live system.' },
          artifact: { type: 'string', description: 'file path, script name, or system reference this claim is about. Empty string if not applicable.' },
        },
      },
    },
  },
}

// Step 2 output per claim: the execution result with typed evidence.
const CLAIM_RESULT_SCHEMA = {
  type: 'object',
  required: ['claim', 'claim_class', 'tool_used', 'result', 'evidence'],
  properties: {
    claim: { type: 'string', description: 'the claim that was tested (verbatim from typed_claims).' },
    claim_class: { type: 'string', enum: ['execute', 'read', 'mcp'], description: 'the required tool class.' },
    tool_used: { type: 'string', description: 'the actual tool invoked (e.g. "Bash", "Read", "Grep", "mcp__n8n__*"). Use "none" only if truly not executed.' },
    result: { type: 'string', enum: ['PASS', 'FAIL', 'UNTESTED'], description: 'PASS: evidence confirms the claim. FAIL: evidence refutes it or required tool was not used. UNTESTED: could not be verified due to environment constraint.' },
    evidence: { type: 'string', description: 'the LITERAL key output from the tool call that produced this judgment. A finding without real evidence is invalid — set result to FAIL or UNTESTED rather than inventing output.' },
  },
}

// ---------------------------------------------------------------------------
// args contract (passed verbatim by the caller):
//   { project:       string          (required) — project name; routes output/log references
//     claims:        array           (required, >=1) — claims to verify. Each element either a plain
//                                    string or {claim: string, artifact?: string, claim_class?: 'execute'|'read'|'mcp'}.
//                                    The script normalizes strings to objects; scope agent assigns
//                                    claim_class where omitted.
//     source?:       string          (optional) — what produced the claims (task/step ref for QA SCOPE)
//     constraints?:  string          (optional) — environment limits (e.g. "static only", "no live n8n")
//   }
//
// HALT conditions: project missing; claims missing / empty / not an array.
//
// TRANSCRIPT RELAY CONTRACT (critical for process-step-check.py):
//   This workflow returns qa_scope_text and qa_report_text as plain strings.
//   The thin-invoker SKILL.md instructs the main session to relay BOTH fields verbatim,
//   as plain unfenced text (process-step-check strips fences before matching literal strings).
//   The relay is visible to the hook ONLY because of the turn-boundary fix (tool_result wrapper no longer
//   resets scan state) — if that fix is not on disk, the hook silently skips enforcement.
// ---------------------------------------------------------------------------
let A = (typeof args === 'object' && args) ? args : {}
if (typeof args === 'string') {
  try { const p = JSON.parse(args); if (p && typeof p === 'object') A = p } catch (e) { /* fall through to HALT */ }
}
const PROJECT = A.project || 'UNKNOWN'
const CLAIMS_RAW = A.claims

// HALT before spawning any agent if required fields missing.
if (PROJECT === 'UNKNOWN') {
  log('HALT: malformed dispatch — project is required.')
  return { status: 'halted-malformed-args', received_args_type: typeof args, hint: 'pass args as a JSON object with non-empty project and claims array' }
}
if (!CLAIMS_RAW || !Array.isArray(CLAIMS_RAW) || CLAIMS_RAW.length === 0) {
  log('HALT: malformed dispatch — claims must be a non-empty array.')
  return { status: 'halted-malformed-args', received_args_type: typeof args, hint: 'claims must be a non-empty array of strings or {claim, artifact?, claim_class?} objects' }
}

// Normalize claims: strings → objects (claim_class left empty for scope agent to fill).
const normalizedClaims = CLAIMS_RAW.map(c =>
  typeof c === 'string'
    ? { claim: c, claim_class: null, artifact: '' }
    : { claim: c.claim || String(c), claim_class: c.claim_class || null, artifact: c.artifact || '' }
)

const SOURCE_LABEL = A.source || '(no source label supplied)'
const EXPECTED_COUNT = normalizedClaims.length  // coverage rule: N claims in → N results out

// ---------------------------------------------------------------------------
// THE PROCEDURE
// ---------------------------------------------------------------------------

// --- Step 1: Scope — assign claim_class where omitted -----------------------
phase('Scope')
const scopeResult = await agent(
  `You are the scope node of the process-qa procedure for project "${PROJECT}".

SOURCE (what produced these claims): ${SOURCE_LABEL}
CONSTRAINTS: ${A.constraints || '(none supplied)'}

CLAIMS TO QA (${normalizedClaims.length} total):
${normalizedClaims.map((c, i) => `${i + 1}. claim: "${c.claim}" | artifact: "${c.artifact}" | caller claim_class: ${c.claim_class || '(omitted — you assign)'}`).join('\n')}

For each claim where claim_class is omitted, assign it:
  - execute: requires running code, a hook, a script, an API call, or Bash execution
  - read: file existence, content match, config registered — Read/Grep is sufficient
  - mcp: requires querying a live system via MCP (n8n, database, etc.)

Rules:
  - Code/hook/workflow behavior → execute (NEVER read — reading a script is not testing it)
  - File exists / contains X → read
  - Live system state → mcp
  - When in doubt between execute and read, assign execute

Return scope_summary (one sentence describing what is being QA\'d) and typed_claims (the full list with claim_class assigned for all items).`,
  { schema: SCOPE_SCHEMA, label: `scope:${PROJECT}`, phase: 'Scope' }
)

if (!scopeResult || !Array.isArray(scopeResult.typed_claims) || scopeResult.typed_claims.length === 0) {
  log('Scope step returned no typed claims — halting.')
  return { status: 'scope-failed', project: PROJECT }
}

// Use the scope agent's typed list; fall back to normalized input if lengths mismatch.
const typedClaims = scopeResult.typed_claims.length === normalizedClaims.length
  ? scopeResult.typed_claims
  : normalizedClaims.map((c, i) => ({
      claim: c.claim,
      claim_class: c.claim_class || 'execute',
      artifact: c.artifact,
    }))

// ---------------------------------------------------------------------------
// --- Step 2: Execute — one agent per claim, in parallel --------------------
phase('Execute')
// Set of tool names that satisfy execute-class claims.
const EXECUTE_TOOLS = new Set(['Bash', 'bash', 'mcp__n8n', 'mcp__supabase', 'mcp__codegraph'])
function satisfiesExecuteClass(toolUsed) {
  if (!toolUsed || toolUsed === 'none') return false
  // Any tool starting with mcp__ counts as execution for mcp-class too.
  return EXECUTE_TOOLS.has(toolUsed) || toolUsed.startsWith('mcp__') || toolUsed.toLowerCase() === 'bash'
}

const executeAgents = typedClaims.map((tc, i) => () => agent(
  `You are executing ONE QA verification for project "${PROJECT}".

CLAIM: ${tc.claim}
REQUIRED TOOL CLASS: ${tc.claim_class}
ARTIFACT: ${tc.artifact || '(see claim)'}
CONSTRAINTS: ${A.constraints || '(none)'}

TOOL RULES — READ CAREFULLY:
${tc.claim_class === 'execute'
  ? '- This is an EXECUTE-class claim. You MUST use Bash or an MCP execution tool. Using Read or Grep alone auto-FAILs this claim — reading a script is not testing it.'
  : tc.claim_class === 'mcp'
    ? '- This is an MCP-class claim. Use the appropriate MCP tool (load via ToolSearch if needed). If the MCP tool is unavailable in this environment, set result=UNTESTED and explain the blocker in evidence.'
    : '- This is a READ-class claim. Use Read, Grep, or Glob to verify.'
}

For execute-class: if you genuinely cannot run the test due to an environment constraint, set result=UNTESTED and explain the exact blocker in evidence — do NOT fabricate output.
For read-class: Grep for expected content, Read the file, or Glob for existence.
For mcp-class: use ToolSearch to load the MCP tool if needed.

Fill tool_used with the ACTUAL tool you called (e.g. "Bash", "Read", "mcp__codegraph__query"). Fill evidence with the LITERAL key output from that call (truncate to ~300 chars). Set result: PASS (evidence confirms claim), FAIL (evidence refutes or required tool not used), UNTESTED (environment constraint prevents execution).

SELF-CHECK before returning: for each PASS you are about to report — can you name the specific tool call that produced the evidence? If not, the claim is FAIL or UNTESTED, not PASS.`,
  { schema: CLAIM_RESULT_SCHEMA, label: `execute:claim:${i}`, phase: 'Execute' }
))

const rawResults = await parallel(executeAgents)

// ---------------------------------------------------------------------------
// --- Step 3: Compute PASS/FAIL IN CODE (never trust agent self-report) ------
phase('Report')

const claimResults = []
for (let i = 0; i < typedClaims.length; i++) {
  const tc = typedClaims[i]
  const res = rawResults[i]

  if (!res) {
    // Agent returned null — treat as FAIL
    claimResults.push({
      claim: tc.claim,
      claim_class: tc.claim_class,
      tool_used: 'none',
      result: 'FAIL',
      evidence: '(agent returned null — no execution evidence)',
    })
    continue
  }

  let result = res.result  // start with agent's report

  // AUTO-FAIL rule: execute-class claim verified by Read/Grep only → FAIL.
  if (tc.claim_class === 'execute' && !satisfiesExecuteClass(res.tool_used)) {
    result = 'FAIL'
    log(`AUTO-FAIL claim ${i + 1}: execute-class but tool_used="${res.tool_used}" is not Bash/MCP. Overriding agent result="${res.result}".`)
  }

  // Null evidence + non-UNTESTED → FAIL.
  if (!res.evidence && result !== 'UNTESTED') {
    result = 'FAIL'
    log(`AUTO-FAIL claim ${i + 1}: no evidence provided. Overriding agent result="${res.result}".`)
  }

  claimResults.push({
    claim: tc.claim,
    claim_class: tc.claim_class,
    tool_used: res.tool_used || 'none',
    result,
    evidence: res.evidence || '(no evidence)',
  })
}

// Coverage rule: N claims in → N results out (enforced in code against args.claims.length).
if (claimResults.length !== EXPECTED_COUNT) {
  log(`COVERAGE MISMATCH: expected ${EXPECTED_COUNT} results (from args.claims), got ${claimResults.length}. Padding missing entries as FAIL.`)
  while (claimResults.length < EXPECTED_COUNT) {
    const idx = claimResults.length
    claimResults.push({
      claim: normalizedClaims[idx] ? normalizedClaims[idx].claim : `(missing claim ${idx + 1})`,
      claim_class: 'execute',
      tool_used: 'none',
      result: 'FAIL',
      evidence: '(coverage gap — no agent result returned for this claim)',
    })
  }
}

// Derive counts IN CODE.
const passCount    = claimResults.filter(r => r.result === 'PASS').length
const failCount    = claimResults.filter(r => r.result === 'FAIL').length
const untestedCount = claimResults.filter(r => r.result === 'UNTESTED').length
const totalCount   = claimResults.length

const failLines = claimResults
  .filter(r => r.result === 'FAIL')
  .map(r => `- ${r.claim} (tool_used: ${r.tool_used}, evidence: ${r.evidence})`)
  .join('\n')

const untestedLines = claimResults
  .filter(r => r.result === 'UNTESTED')
  .map(r => `- ${r.claim} (${r.evidence})`)
  .join('\n')

// ---------------------------------------------------------------------------
// Assemble QA SCOPE + QA REPORT as plain text for transcript relay.
// CRITICAL: process-step-check.py matches literal strings after fence-stripping.
// These blocks MUST be relayed by the main session as plain unfenced text.
// ---------------------------------------------------------------------------
const qa_scope_text = `QA SCOPE
${claimResults.map(r => `- ${r.claim}`).join('\n')}
Source: ${SOURCE_LABEL}`

const qa_report_text = `QA REPORT
PASS: ${passCount} / ${totalCount}
FAIL: ${failCount > 0 ? failLines : 'none'}
Untested: ${untestedCount > 0 ? untestedLines : 'none deliberately'}`

// Overall pass: no FAILs (UNTESTED items are a surface gap, not failures).
const overallPass = failCount === 0

// ---------------------------------------------------------------------------
return {
  status: overallPass ? 'complete' : 'quality-failed',
  project: PROJECT,
  pass_count: passCount,
  fail_count: failCount,
  untested_count: untestedCount,
  total_count: totalCount,
  claim_results: claimResults,
  overall_pass: overallPass,
  // Transcript relay fields — the thin-invoker SKILL.md instructs the main session to
  // output BOTH of these verbatim as plain unfenced text (see TRANSCRIPT RELAY CONTRACT above).
  qa_scope_text,
  qa_report_text,
}
