/*
 * ADOPTED 2026-06-11 — Increment 2, procedure-layer migration (Wiktor GO).
 * Source draft: Projects/Agent-Governance-Research/work/2026-06-11-procedure-layer-migration-plan.md Part C §process-qa.
 * REBUILT 2026-09-21 after the adversarial review of the QA contract
 *   (Projects/Vault-Maintenance/work/2026-09-21-review-process-qa-contract-adversarial.md):
 *   - the scope node may ADD claims (untaken paths, the second caller, target correctness) and
 *     its additions are kept, tagged origin=scope; a longer list is no longer discarded (finding 1)
 *   - a `run` claim class exists that only an invocation of the artifact satisfies, and the
 *     execute agents return the literal `command`, which is checked for read-only shapes
 *     (cat, sed -n, grep, git show ...) instead of trusting the tool name (findings 2, 3, 12, 14)
 *   - the scope node names the untested surface as paths; "none deliberately" is written only
 *     when it affirmatively returns an empty list with a reason (findings 4, 5)
 *   - the report carries `Verifier: workflow` (finding 6) and a status of complete-with-gaps
 *     when anything is untested (finding 11)
 *   - the script returns a ready qa_log_entry; process-step-check.py now opens the qa-log
 *     the relay names and matches its counts (finding 8)
 * Scope: terminal execution-class workflow — the script drives per-claim execution and computes
 *   PASS/FAIL counts IN CODE from typed per-claim evidence fields. Self-report is checked, never trusted.
 * DISPATCHES.json stays authoritative for H11 read-only verification (do not retire it).
 *
 * HOOK PRECONDITIONS (must be on disk before this workflow's thin-invoker SKILL.md is swapped in):
 *   B-1 (process-step-check.py): recognizes Workflow process-qa AND survives the tool_result wrapper reset.
 *   B-2 (work-verification-check.py): sets has_process_qa=True via Workflow invocation (clears CHECK 1b).
 *   B-3 (work-verification-check.py): qa_via_workflow flag suppresses CHECK 1's zero-execution-tools block.
 * Without B-2+B-3, a Workflow process-qa run false-blocks on CHECK 1 because execution tools run
 * inside the workflow subagent and are invisible to the main-transcript tool list.
 * The evidence obligation does NOT vanish — it MOVES into the typed per-claim fields below.
 */

export const meta = {
  name: 'process-qa',
  description: 'Terminal execution-class workflow: scope (assign claim classes, ADD claims for untaken paths and target correctness, name the untested surface) -> per-claim execute-agents (each runs real tools and returns the literal command plus typed evidence) -> PASS/FAIL computed IN CODE (read-only commands never satisfy execute or run; run must invoke the artifact) -> QA SCOPE, QA REPORT and a qa-log entry assembled for relay. Args: {project, claims, deliverable?, source?, constraints?}.',
  phases: [
    { title: 'Scope', detail: 'normalize claims; scope agent assigns claim_class, adds claims the builder left out, names the untested surface' },
    { title: 'Execute', detail: 'one agent per claim — runs real tools, returns the literal command and typed evidence; parallel' },
    { title: 'Report', detail: 'PASS/FAIL derived in code from the command and evidence fields; QA SCOPE, QA REPORT and qa-log entry assembled for relay' },
  ],
}

// O9 increment 2 (2026-09-01): workflow-identity marker. Every subagent
// prompt begins with 'WORKFLOW-ID: <name>' as its literal first line so
// the SubagentStop observer (subagent-quality-check.py) can attribute the
// completion to this workflow in governance-log.jsonl. Inert metadata
// only: no other prompt text changes. All dispatch sites below call
// wfAgent; zero bare agent( call sites may remain outside this line.
const wfAgent = (prompt, opts) => agent('WORKFLOW-ID: process-qa\n\n' + prompt, opts)  // literal: runner strips export const meta, no runtime binding (crash 2026-09-01 wf_31f32926-f97)

// ---------------------------------------------------------------------------
// Claim classes
//   run     : only an invocation of the artifact with real inputs satisfies it
//             (the script ran, the hook fired through its entry point, the
//             workflow executed, the request was sent). A unit test, a
//             validator, a grep or a read does not.
//   execute : a command must run (a test suite, a validator, a probe); a
//             read-only command does not satisfy it.
//   read    : Read/Grep/Glob is sufficient (file exists, contains X).
//   mcp     : a live-system query through an MCP tool.
// ---------------------------------------------------------------------------
const CLAIM_CLASSES = ['run', 'execute', 'read', 'mcp']
const MAX_ADDED_CLAIMS = 6

// ---------------------------------------------------------------------------
// Typed schemas
// ---------------------------------------------------------------------------

// Step 1 output: normalized, typed claim list, widened by the scope node.
const SCOPE_SCHEMA = {
  type: 'object',
  required: ['scope_summary', 'typed_claims', 'added_claims', 'untested_surface', 'untested_empty_reason'],
  properties: {
    scope_summary: { type: 'string', description: 'one-sentence statement of what is being QA\'d and from what source.' },
    typed_claims: {
      type: 'array',
      description: 'the caller\'s claims, in the caller\'s order, each with claim_class assigned.',
      items: {
        type: 'object',
        required: ['claim', 'claim_class', 'artifact'],
        properties: {
          claim: { type: 'string', description: 'the specific, verifiable claim (verbatim from the caller).' },
          claim_class: { type: 'string', enum: CLAIM_CLASSES, description: 'run: the artifact must be invoked; execute: a command must run; read: Read/Grep suffices; mcp: a live MCP query.' },
          artifact: { type: 'string', description: 'file path, script name, or system reference this claim is about. Empty string if not applicable.' },
        },
      },
    },
    added_claims: {
      type: 'array',
      description: 'claims the caller did not write and the deliverable needs: untaken paths (the no-input default, error branches, the second caller, the empty input), effects on consumers, and one claim that the artifact built is the one the task asked for. Empty only when the deliverable has none of these.',
      items: {
        type: 'object',
        required: ['claim', 'claim_class', 'artifact', 'why'],
        properties: {
          claim: { type: 'string' },
          claim_class: { type: 'string', enum: CLAIM_CLASSES },
          artifact: { type: 'string' },
          why: { type: 'string', description: 'which omission this closes (untaken path, second caller, target correctness, consumer effect).' },
        },
      },
    },
    untested_surface: {
      type: 'array',
      description: 'paths of the deliverable that NO claim (caller or added) will exercise, named as paths, not categories: "the no-input default of X", "the 502 branch of Y", "Z under the real cron". Empty only when every live path has a claim.',
      items: { type: 'string' },
    },
    untested_empty_reason: { type: 'string', description: 'when untested_surface is empty: why every live path is covered. Empty string otherwise.' },
  },
}

// Step 2 output per claim: the execution result with typed evidence.
const CLAIM_RESULT_SCHEMA = {
  type: 'object',
  required: ['claim', 'claim_class', 'tool_used', 'command', 'result', 'evidence'],
  properties: {
    claim: { type: 'string', description: 'the claim that was tested (verbatim).' },
    claim_class: { type: 'string', enum: CLAIM_CLASSES, description: 'the required tool class.' },
    tool_used: { type: 'string', description: 'the actual tool invoked (e.g. "Bash", "Read", "Grep", "mcp__n8n__*"). Use "none" only if truly not executed.' },
    command: { type: 'string', description: 'the LITERAL command line or MCP call that produced the evidence, exactly as run (for Read/Grep: the path or pattern). "none" if nothing ran.' },
    result: { type: 'string', enum: ['PASS', 'FAIL', 'UNTESTED'], description: 'PASS: evidence confirms the claim. FAIL: evidence refutes it or required tool was not used. UNTESTED: could not be verified due to environment constraint.' },
    evidence: { type: 'string', description: 'the LITERAL key output from the tool call that produced this judgment. A finding without real evidence is invalid — set result to FAIL or UNTESTED rather than inventing output.' },
  },
}

// ---------------------------------------------------------------------------
// args contract (passed verbatim by the caller):
//   { project:       string          (required) — project name; routes output/log references
//     claims:        array           (required, >=1) — claims to verify. Each element either a plain
//                                    string or {claim: string, artifact?: string, claim_class?: 'run'|'execute'|'read'|'mcp'}.
//     deliverable?:  string          (strongly recommended) — what was built, its entry points and
//                                    its callers, so the scope node can add claims for the paths
//                                    the builder did not list. When absent the scope node says so
//                                    and the untested surface records it.
//     source?:       string          (optional) — what produced the claims (task/step ref for QA SCOPE)
//     constraints?:  string          (optional) — environment limits (e.g. "static only", "no live n8n")
//   }
//
// HALT conditions: project missing; claims missing / empty / not an array.
//
// TRANSCRIPT RELAY CONTRACT (critical for process-step-check.py):
//   This workflow returns qa_scope_text, qa_report_text and qa_log_entry as plain strings.
//   The thin-invoker SKILL.md instructs the main session to append qa_log_entry verbatim to the
//   project's work/qa-log.md and to relay the compact form (QA SCOPE pointer, QA REPORT:, PASS line)
//   as plain unfenced text. process-step-check.py opens the named qa-log and matches the counts.
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
    : { claim: c.claim || String(c), claim_class: (CLAIM_CLASSES.includes(c.claim_class) ? c.claim_class : null), artifact: c.artifact || '' }
)

const SOURCE_LABEL = A.source || '(no source label supplied)'
const DELIVERABLE = (typeof A.deliverable === 'string' && A.deliverable.trim()) ? A.deliverable.trim() : ''
const CALLER_COUNT = normalizedClaims.length

// ---------------------------------------------------------------------------
// THE PROCEDURE
// ---------------------------------------------------------------------------

// --- Step 1: Scope — assign claim_class, widen the list, name the untested surface ---
phase('Scope')
const scopeResult = await wfAgent(
  `You are the scope node of the process-qa procedure for project "${PROJECT}".

SOURCE (what produced these claims): ${SOURCE_LABEL}
CONSTRAINTS: ${A.constraints || '(none supplied)'}
DELIVERABLE (what was built, its entry points, its callers): ${DELIVERABLE || '(NOT SUPPLIED by the caller: say so in untested_surface as "the deliverable was not described, so untaken paths could not be enumerated")'}

CALLER'S CLAIMS (${CALLER_COUNT} total, written by the session that did the work):
${normalizedClaims.map((c, i) => `${i + 1}. claim: "${c.claim}" | artifact: "${c.artifact}" | caller claim_class: ${c.claim_class || '(omitted — you assign)'}`).join('\n')}

You have three jobs. Do all three.

1. Assign claim_class to every caller claim where omitted, and correct one that is plainly wrong:
   - run: the claim is about what the artifact DOES when invoked (a script's output, a hook firing, a workflow executing, a request being served). Only running the artifact itself with real inputs can verify it. A unit test, a validator, a grep, a read do not.
   - execute: a command must run to verify it (a test suite, a validator, a probe script), but the artifact itself need not be invoked.
   - read: file exists, contains X, config registered. Read/Grep is sufficient.
   - mcp: live system state through an MCP tool (n8n, a database, a work tracker).
   Rules: behaviour of code, hooks, workflows and APIs is run or execute, never read. When in doubt between run and execute, assign run. When in doubt between execute and read, assign execute.

2. Add the claims the caller did not write. A builder lists what he did; verification needs what could be wrong. From the DELIVERABLE description, add (up to ${MAX_ADDED_CLAIMS}):
   - one claim per live path no caller claim exercises: the no-input default, the empty input, each error branch, the second caller, the scheduled or unattended entry
   - one claim that the artifact built is the artifact the task asked for (target correctness), naming where the task's target is stated
   - one claim per consumer of the artifact that the change could affect
   Each added claim gets claim_class by the same rules and a 'why' naming the omission it closes. Every run claim names the artifact to invoke in its artifact field (a path, a workflow id, an entry point); a run claim without one cannot pass. If the DELIVERABLE is not supplied, add what the claims themselves imply and say in untested_surface that the paths could not be enumerated.

3. Name untested_surface: every path of the deliverable that no claim (caller or added) will exercise, as concrete paths ("the no-input default of run_daily.py", "the 502 branch of the callback poster", "the cron entry under the real scheduler"), never categories ("edge cases", "performance"). If, and only if, every live path has a claim, return an empty list and put the reason in untested_empty_reason.

Return scope_summary, typed_claims (the caller's claims, same order, classes assigned), added_claims, untested_surface, untested_empty_reason.`,
  { schema: SCOPE_SCHEMA, label: `scope:${PROJECT}`, phase: 'Scope' }
)

if (!scopeResult || !Array.isArray(scopeResult.typed_claims) || scopeResult.typed_claims.length === 0) {
  log('Scope step returned no typed claims — halting.')
  return { status: 'scope-failed', project: PROJECT }
}

// Merge: the caller's claims keep their order and text. The scope node's
// class is taken only when it is stricter than a caller-pinned class (build
// review N8: a scope node could downgrade a pinned `run` to `read`); an
// omitted class takes the scope node's, then `execute`. Additions are
// deduplicated against the caller's claims and each other (N15) and appended
// tagged origin=scope; overflow past MAX_ADDED_CLAIMS is surfaced, not dropped.
// Until 2026-09-21 a length mismatch discarded the scope node's whole list.
const CLASS_RANK = { read: 0, mcp: 1, execute: 2, run: 3 }
const normKey = t => String(t || '').toLowerCase().replace(/\s+/g, ' ').trim()
const typedClaims = normalizedClaims.map((c, i) => {
  const sc = scopeResult.typed_claims[i] || {}
  const scopeCls = CLAIM_CLASSES.includes(sc.claim_class) ? sc.claim_class : null
  let cls
  if (c.claim_class) {
    cls = (scopeCls && CLASS_RANK[scopeCls] > CLASS_RANK[c.claim_class]) ? scopeCls : c.claim_class
  } else {
    cls = scopeCls || 'execute'
  }
  return { claim: c.claim, claim_class: cls, artifact: c.artifact || sc.artifact || '', origin: 'caller' }
})
const seenKeys = new Set(typedClaims.map(t => normKey(t.claim)))
const addedRaw = Array.isArray(scopeResult.added_claims) ? scopeResult.added_claims : []
const addedAll = []
for (const a of addedRaw) {
  if (!a || typeof a.claim !== 'string' || !a.claim.trim()) continue
  const key = normKey(a.claim)
  if (seenKeys.has(key)) continue
  seenKeys.add(key)
  addedAll.push({
    claim: a.claim.trim(),
    claim_class: CLAIM_CLASSES.includes(a.claim_class) ? a.claim_class : 'execute',
    artifact: a.artifact || '',
    origin: 'scope',
    why: a.why || '',
  })
}
const addedClaims = addedAll.slice(0, MAX_ADDED_CLAIMS)
const addedOverflow = addedAll.slice(MAX_ADDED_CLAIMS)
for (const a of addedClaims) typedClaims.push(a)
if (addedClaims.length) log(`Scope node added ${addedClaims.length} claim(s): ${addedClaims.map(a => a.why || a.claim).join('; ')}`)
if (addedOverflow.length) log(`Scope node named ${addedOverflow.length} more claim(s) past the cap of ${MAX_ADDED_CLAIMS}; recorded as untested`)

const untestedSurface = (Array.isArray(scopeResult.untested_surface) ? scopeResult.untested_surface : [])
  .filter(u => typeof u === 'string' && u.trim())
  .map(u => u.trim())
const untestedEmptyReason = (typeof scopeResult.untested_empty_reason === 'string') ? scopeResult.untested_empty_reason.trim() : ''
if (!DELIVERABLE && !untestedSurface.some(u => /deliverable was not described/i.test(u))) {
  untestedSurface.push('the deliverable was not described to the scope node, so its untaken paths were not enumerated')
}
for (const a of addedOverflow) untestedSurface.push(`${a.claim} (named by the scope node past the cap, not tested)`)
// The floor SKILL.md states: an invocable deliverable gets at least one run claim.
if (DELIVERABLE && !typedClaims.some(t => t.claim_class === 'run')) {
  untestedSurface.push('no run-class claim: the deliverable was never invoked as a whole by this QA')
}

// ---------------------------------------------------------------------------
// --- Step 2: Execute — one agent per claim, in parallel --------------------
phase('Execute')
// Set of tool names that satisfy execute-class claims.
// Instance-bound MCP servers are deliberately not enumerated here: this file
// ships to devices that have none, and a claim verified only through a tenant
// MCP call now has no qualifying token and is auto-failed, which is the same
// fail-closed direction the tokenizer below already takes.
const EXECUTE_TOOLS = new Set(['Bash', 'bash', 'PowerShell', 'powershell', 'mcp__n8n', 'mcp__codegraph'])
// tool_used is model-written free text, so it arrives as "Bash, PowerShell" or
// "Read, Bash (grep/sed)" whenever a claim genuinely needed more than one tool.
// Matching that whole string by equality overrode real agent PASS verdicts to FAIL
// (2026-09-09 defect; check: test_process_qa_toolclass.mjs). Tokenize, then ask
// whether ANY token is an execution tool. Still fails closed: a claim verified with
// Read or Grep alone has no qualifying token and is auto-failed exactly as before.
function satisfiesExecuteClass(toolUsed) {
  if (!toolUsed || typeof toolUsed !== 'string') return false
  const tokens = toolUsed
    .replace(/\([^)]*\)/g, ' ')   // drop parenthetical detail: "Bash (heredoc)" -> "Bash"
    .split(/[,+/&]|\band\b/i)      // "Bash, PowerShell" / "Grep + Bash" / "Bash and PowerShell"
    .map(t => t.trim())
    .filter(Boolean)
  return tokens.some(t =>
    EXECUTE_TOOLS.has(t) || t.startsWith('mcp__') || t.toLowerCase() === 'bash' || t.toLowerCase() === 'powershell'
  )
}

// The tool name says nothing about what ran: under the harness's auto mode
// every file read goes through Bash as cat, sed -n or grep, and the adversarial
// review measured "Bash (cat the file)" passing the execute gate. The command
// is checked instead. A command is read-only when every segment of it (split
// on pipes and && / ; / ||, outside quotes) starts with a program that only
// reads, or is an interpreter whose inline payload only reads (build review N3:
// `bash -c "cat f"`, `python -c "print(open(f).read())"`, `powershell -Command
// "Get-Content f"` were scored as execution by a bare program allowlist).
const READ_ONLY_PROGRAMS = new Set([
  'cat', 'head', 'tail', 'sed', 'grep', 'rg', 'egrep', 'fgrep', 'awk', 'cut', 'sort', 'uniq', 'wc', 'tr', 'nl', 'tac', 'rev',
  'column', 'paste', 'base64', 'strings', 'od', 'xxd', 'hexdump', 'ls', 'dir', 'find', 'stat', 'file', 'less', 'more', 'echo',
  'printf', 'type', 'tee', 'jq', 'yq', 'get-content', 'gc', 'select-string', 'get-childitem', 'gci', 'get-item', 'format-list',
  'select-object', 'test', '[', '[[', 'true', 'false', 'pwd', 'realpath', 'basename', 'dirname', 'md5sum', 'sha256sum', 'diff',
  'cmp', 'while', 'for', 'if', 'read', 'done', 'do', 'fi', 'then', 'else', 'export', 'set', 'cd', 'sleep',
])
const READ_ONLY_GIT = new Set(['show', 'diff', 'log', 'status', 'ls-files', 'blame', 'rev-parse', 'cat-file', 'grep', 'branch', 'remote', 'describe', 'shortlog'])
const SHELL_INLINE = { bash: ['-c'], sh: ['-c'], zsh: ['-c'], dash: ['-c'], cmd: ['/c', '/k'], powershell: ['-command', '-c'], pwsh: ['-command', '-c'] }
const CODE_INLINE = { python: ['-c'], python3: ['-c'], py: ['-c'], node: ['-e', '--eval', '-p', '--print'], deno: ['eval'], ruby: ['-e'], perl: ['-e'] }
const EXEC_MARKERS = /subprocess|os\.system|os\.exec|popen|runpy|importlib|__import__|child_process|execsync|spawn|\bexec\s*\(|\beval\s*\(|start-process|invoke-expression|invoke-command|\biex\b|pytest|unittest|\bmain\s*\(|\.run\s*\(|\bsystem\s*\(/i
const READ_ONLY_IMPORTS = new Set(['json', 'io', 're', 'os', 'os.path', 'pathlib', 'sys', 'hashlib', 'csv', 'datetime', 'collections', 'itertools', 'glob', 'fs', 'path', 'string', 'textwrap', 'pprint'])
const PATH_FLAGS = new Set(['-file', '--file', '-f', '-script', '--script'])

// A rough shell tokenizer: whitespace-separated, quotes kept as one token.
function _tokenize(segment) {
  const out = []
  let cur = '', q = null, quoted = false
  for (const ch of segment) {
    if (q) {
      if (ch === q) { q = null } else { cur += ch }
    } else if (ch === '"' || ch === "'") {
      q = ch; quoted = true
    } else if (/\s/.test(ch)) {
      if (cur.length || quoted) { out.push({ text: cur, quoted }) }
      cur = ''; quoted = false
    } else {
      cur += ch
    }
  }
  if (cur.length || quoted) out.push({ text: cur, quoted })
  return out
}

// Split on | || && ; outside quotes.
function _segments(command) {
  const segs = []
  let cur = '', q = null
  const c = String(command)
  for (let i = 0; i < c.length; i++) {
    const ch = c[i]
    if (q) { cur += ch; if (ch === q) q = null; continue }
    if (ch === '"' || ch === "'") { q = ch; cur += ch; continue }
    if (ch === '|' || ch === '&' || ch === ';') {
      if (cur.trim()) segs.push(cur)
      cur = ''
      if ((ch === '|' || ch === '&') && c[i + 1] === ch) i++
      continue
    }
    cur += ch
  }
  if (cur.trim()) segs.push(cur)
  return segs
}

function _stripComment(segment) {
  let q = null, out = ''
  for (const ch of segment) {
    if (q) { out += ch; if (ch === q) q = null; continue }
    if (ch === '"' || ch === "'") { q = ch; out += ch; continue }
    if (ch === '#') break
    out += ch
  }
  return out
}

// program name and the tokens after it, with env assignments, subshell parens
// and wrappers (sudo, time, env, exec) removed
function _programAndArgs(segment) {
  let toks = _tokenize(segment.replace(/^[\s(]+/, ''))
  while (toks.length && !toks[0].quoted && /^[A-Za-z_][A-Za-z0-9_]*=/.test(toks[0].text)) toks.shift()
  while (toks.length && ['sudo', 'time', 'nice', 'env', 'exec', 'command'].includes(toks[0].text.toLowerCase())) toks.shift()
  if (!toks.length) return { prog: '', args: [] }
  const prog = toks[0].text.replace(/\\/g, '/').split('/').pop().toLowerCase().replace(/\.exe$/, '')
  return { prog, args: toks.slice(1) }
}

function _inlineIsReadOnly(prog, code) {
  if (SHELL_INLINE[prog]) return isReadOnlyCommand(code)
  if (EXEC_MARKERS.test(code)) return false
  const imports = [...code.matchAll(/\b(?:import|from)\s+([A-Za-z_][\w.]*)/g)].map(m => m[1].toLowerCase())
  if (imports.some(mod => !READ_ONLY_IMPORTS.has(mod) && !READ_ONLY_IMPORTS.has(mod.split('.')[0]))) return false
  if (/\brequire\s*\(\s*['"](?!fs|path|os)/i.test(code)) return false
  return true
}

function _segmentIsReadOnly(segment) {
  const { prog, args } = _programAndArgs(segment)
  if (!prog) return true
  if (prog === 'git') return READ_ONLY_GIT.has((args[0] && args[0].text.toLowerCase() === '-c' ? (args[2] || {}).text : (args[0] || {}).text || '').toLowerCase())
  if (READ_ONLY_PROGRAMS.has(prog)) return true
  const flags = SHELL_INLINE[prog] || CODE_INLINE[prog]
  if (flags) {
    for (let i = 0; i < args.length; i++) {
      if (flags.includes(args[i].text.toLowerCase())) {
        return args[i + 1] ? _inlineIsReadOnly(prog, args[i + 1].text) : true
      }
    }
    return false  // an interpreter given a script file runs it
  }
  return false
}

function isReadOnlyCommand(command) {
  if (!command || typeof command !== 'string') return true
  const c = command.trim()
  if (!c || c.toLowerCase() === 'none') return true
  const segments = _segments(c).map(_stripComment).map(x => x.trim()).filter(Boolean)
  if (segments.length === 0) return true
  return segments.every(_segmentIsReadOnly)
}

// A run-class claim must invoke the artifact: in a segment that is not
// read-only, the artifact's basename is the program, a positional argument, or
// a path or URL whose last component is the artifact (build review N4: a
// substring test let a comment, a log file name, or any MCP tool name pass).
// Inline-code payloads and the values of ordinary option flags do not count.
function invokesArtifact(command, artifact, toolUsed) {
  if (!artifact || !artifact.trim()) return false
  const base = artifact.replace(/\\/g, '/').split('/').pop().toLowerCase()
  const stem = base.replace(/\.[a-z0-9]+$/, '')
  const matches = t => {
    const tb = t.replace(/\\/g, '/').replace(/[?#].*$/, '').split('/').pop().toLowerCase().split('::')[0]
    return tb === base || (stem.length >= 6 && tb === stem)
  }
  if (typeof toolUsed === 'string' && toolUsed.startsWith('mcp__')) {
    const hay = String(command || '').toLowerCase()
    return hay.includes(artifact.toLowerCase()) || (base.length >= 6 && hay.includes(base))
  }
  for (const seg of _segments(String(command || '')).map(_stripComment)) {
    if (_segmentIsReadOnly(seg)) continue
    const { prog, args } = _programAndArgs(seg)
    const first = _tokenize(seg.replace(/^[\s(]+/, ''))[0]
    if (first && matches(first.text)) return true
    const flags = SHELL_INLINE[prog] || CODE_INLINE[prog] || []
    for (let i = 0; i < args.length; i++) {
      const a = args[i]
      if (flags.includes(a.text.toLowerCase())) {
        // a shell payload is a command of its own; an interpreter payload is code, not an invocation
        if (SHELL_INLINE[prog] && args[i + 1] && invokesArtifact(args[i + 1].text, artifact, toolUsed)) return true
        i++; continue
      }
      if (!a.quoted && a.text.startsWith('-')) {
        if (PATH_FLAGS.has(a.text.toLowerCase()) && args[i + 1] && matches(args[i + 1].text)) return true
        if (!a.text.includes('=')) i++                                 // skip an ordinary flag's value
        continue
      }
      if (matches(a.text)) return true
    }
  }
  return false
}

const CLASS_RULES = {
  run: '- This is a RUN-class claim. You MUST invoke the artifact itself with real inputs (run the script, fire the hook through its entry point, execute the workflow, send the request) and report the exact command in `command`. A unit test, a validator, a grep or a read of the file does NOT satisfy it and will be scored FAIL in code. If the artifact cannot be invoked in this environment, set result=UNTESTED and name the blocker.',
  execute: '- This is an EXECUTE-class claim. You MUST run a command (Bash, PowerShell, or an MCP execution tool) and report it in `command`. A read-only command (cat, sed -n, head, grep, ls, git show, git diff) is scored FAIL in code — reading a script is not testing it.',
  mcp: '- This is an MCP-class claim. Use the appropriate MCP tool (load via ToolSearch if needed) and put the call in `command`. If the MCP tool is unavailable in this environment, set result=UNTESTED and explain the blocker in evidence.',
  read: '- This is a READ-class claim. Use Read, Grep, or Glob to verify; put the path or pattern in `command`.',
}

const executeAgents = typedClaims.map((tc, i) => () => wfAgent(
  `You are executing ONE QA verification for project "${PROJECT}".

CLAIM: ${tc.claim}
REQUIRED TOOL CLASS: ${tc.claim_class}
ARTIFACT: ${tc.artifact || '(see claim)'}
ORIGIN: ${tc.origin === 'scope' ? 'added by the scope node (' + (tc.why || 'untaken path') + ')' : 'the caller'}
DELIVERABLE: ${DELIVERABLE || '(not described)'}
CONSTRAINTS: ${A.constraints || '(none)'}

TOOL RULES — READ CAREFULLY:
${CLASS_RULES[tc.claim_class] || CLASS_RULES.execute}

Your job is to try to REFUTE the claim, not to confirm it. Run the thing, look at what came back, and judge.
For run and execute classes: if you genuinely cannot run the test due to an environment constraint, set result=UNTESTED and explain the exact blocker in evidence — do NOT fabricate output.

Fill tool_used with the ACTUAL tool you called (e.g. "Bash", "Read", "mcp__codegraph__query"). Fill command with the LITERAL command line or call, exactly as run. Fill evidence with the LITERAL key output from that call (truncate to ~300 chars). Set result: PASS (evidence confirms claim), FAIL (evidence refutes or required tool not used), UNTESTED (environment constraint prevents execution).

SELF-CHECK before returning: for each PASS you are about to report — can you name the specific command that produced the evidence, and did that command run the thing the claim is about? If not, the claim is FAIL or UNTESTED, not PASS.`,
  { schema: CLAIM_RESULT_SCHEMA, label: `execute:claim:${i}`, phase: 'Execute' }
))

const rawResults = await parallel(executeAgents)

// ---------------------------------------------------------------------------
// --- Step 3: Compute PASS/FAIL IN CODE (self-report is checked, not trusted) ---
phase('Report')

const claimResults = []
for (let i = 0; i < typedClaims.length; i++) {
  const tc = typedClaims[i]
  const res = rawResults[i]

  if (!res) {
    // Agent returned null — treat as FAIL
    claimResults.push({
      claim: tc.claim, claim_class: tc.claim_class, origin: tc.origin,
      tool_used: 'none', command: 'none', result: 'FAIL',
      evidence: '(agent returned null — no execution evidence)',
    })
    continue
  }

  let result = res.result  // start with agent's report
  const command = (typeof res.command === 'string') ? res.command : ''
  let override = ''

  // AUTO-FAIL rule (plan Part C): execute-class claim verified by Read/Grep only → FAIL.
  if ((tc.claim_class === 'execute' || tc.claim_class === 'run') && !satisfiesExecuteClass(res.tool_used)) {
    result = 'FAIL'
    override = `execute-class but tool_used="${res.tool_used}" is not Bash/PowerShell/MCP`
  }
  // 2026-09-21: the command decides, not the tool name. A read-only command
  // never satisfies execute or run, whatever tool ran it.
  if (!override && (tc.claim_class === 'execute' || tc.claim_class === 'run') && result !== 'UNTESTED' && isReadOnlyCommand(command)) {
    result = 'FAIL'
    override = `${tc.claim_class}-class but the command was read-only or missing: "${command || 'none'}"`
  }
  // run-class: the artifact itself must have been invoked.
  if (!override && tc.claim_class === 'run' && result !== 'UNTESTED' && !(tc.artifact && tc.artifact.trim())) {
    result = 'FAIL'
    override = 'run-class claim names no artifact to invoke'
  }
  if (!override && tc.claim_class === 'run' && result !== 'UNTESTED' && !invokesArtifact(command, tc.artifact, res.tool_used)) {
    result = 'FAIL'
    override = `run-class but the command did not invoke the artifact "${tc.artifact}": "${command || 'none'}"`
  }
  // mcp-class: the tool must be an MCP tool.
  if (!override && tc.claim_class === 'mcp' && result !== 'UNTESTED' && !(typeof res.tool_used === 'string' && res.tool_used.includes('mcp__'))) {
    result = 'FAIL'
    override = `mcp-class but tool_used="${res.tool_used}" is not an MCP tool`
  }
  // Null evidence + non-UNTESTED → FAIL.
  if (!override && !res.evidence && result !== 'UNTESTED') {
    result = 'FAIL'
    override = 'no evidence provided'
  }
  if (override) log(`AUTO-FAIL claim ${i + 1}: ${override}. Overriding agent result="${res.result}".`)

  claimResults.push({
    claim: tc.claim, claim_class: tc.claim_class, origin: tc.origin,
    tool_used: res.tool_used || 'none',
    command: command || 'none',
    result,
    evidence: (res.evidence || '(no evidence)') + (override ? ` [scored FAIL in code: ${override}]` : ''),
  })
}

// Coverage rule: every typed claim (caller and added) has a result.
const EXPECTED_COUNT = typedClaims.length
if (claimResults.length !== EXPECTED_COUNT) {
  log(`COVERAGE MISMATCH: expected ${EXPECTED_COUNT} results, got ${claimResults.length}. Padding missing entries as FAIL.`)
  while (claimResults.length < EXPECTED_COUNT) {
    const idx = claimResults.length
    claimResults.push({
      claim: typedClaims[idx] ? typedClaims[idx].claim : `(missing claim ${idx + 1})`,
      claim_class: 'execute', origin: typedClaims[idx] ? typedClaims[idx].origin : 'caller',
      tool_used: 'none', command: 'none', result: 'FAIL',
      evidence: '(coverage gap — no agent result returned for this claim)',
    })
  }
}

// Derive counts IN CODE.
const passCount     = claimResults.filter(r => r.result === 'PASS').length
const failCount     = claimResults.filter(r => r.result === 'FAIL').length
const untestedCount = claimResults.filter(r => r.result === 'UNTESTED').length
const totalCount    = claimResults.length
const runCount      = claimResults.filter(r => r.claim_class === 'run' && r.result === 'PASS').length

const failLines = claimResults
  .filter(r => r.result === 'FAIL')
  .map(r => `${r.claim} (tool_used: ${r.tool_used}, command: ${r.command}, evidence: ${r.evidence})`)
  .join('; ')

// The Untested line: the scope node's named surface plus any claim that came
// back UNTESTED. "none deliberately" is written only when the scope node
// affirmatively returned an empty surface with a reason.
const untestedClaimLines = claimResults
  .filter(r => r.result === 'UNTESTED')
  .map(r => `${r.claim} (${r.evidence})`)
const untestedAll = [...untestedSurface, ...untestedClaimLines]
let untestedText
if (untestedAll.length > 0) {
  untestedText = untestedAll.join('; ')
} else if (untestedEmptyReason) {
  untestedText = `none deliberately (scope node: ${untestedEmptyReason})`
} else {
  untestedText = 'the scope node named no untested path and gave no reason; treat the surface as unstated'
}
const hasGaps = untestedAll.length > 0 || !untestedEmptyReason

// ---------------------------------------------------------------------------
// Assemble QA SCOPE + QA REPORT as plain text for transcript relay, and the
// qa-log entry the main session appends verbatim.
// ---------------------------------------------------------------------------
const qa_scope_text = `QA SCOPE
${claimResults.map(r => `- [${r.claim_class}${r.origin === 'scope' ? ', added by scope' : ''}] ${r.claim}`).join('\n')}
Source: ${SOURCE_LABEL}${DELIVERABLE ? `\nDeliverable: ${DELIVERABLE}` : ''}`

const qa_report_text = `QA REPORT
PASS: ${passCount} / ${totalCount}
FAIL: ${failCount > 0 ? failLines : 'none'}
Untested: ${untestedText}
Verifier: workflow`

// Workflow scripts cannot call Date (it breaks resume), so the caller passes
// args.stamp as "YYYY-MM-DD HH:MM local". Without it the header says so, and
// process-step-check will not find a today-dated entry until the caller fixes it.
const stamp = (typeof A.stamp === 'string' && /^\d{4}-\d{2}-\d{2}/.test(A.stamp))
  ? A.stamp
  : 'STAMP-MISSING (pass args.stamp)'
const evidenceLines = claimResults
  .map((r, i) => `- C${i + 1} ${r.result}${r.origin === 'scope' ? ' (added by scope)' : ''}: ${r.tool_used}; command: ${r.command}; ${r.evidence}`)
  .join('\n')
const qa_log_entry = `\n\n## ${stamp}, ${SOURCE_LABEL} (workflow path, one agent per claim)\n\n${qa_scope_text}\n\nEvidence\n${evidenceLines}\n\n${qa_report_text}\n`

const compact_relay = `QA SCOPE: ${totalCount} claims, detail in ${PROJECT}/work/qa-log.md\nQA REPORT:\nPASS: ${passCount} / ${totalCount} | FAIL: ${failCount > 0 ? failLines : 'none'} | Untested: ${untestedText} | Verifier: workflow`

// Overall pass: no FAILs. Anything untested is a gap, reported as such.
const overallPass = failCount === 0

// ---------------------------------------------------------------------------
return {
  status: !overallPass ? 'quality-failed' : (hasGaps ? 'complete-with-gaps' : 'complete'),
  project: PROJECT,
  pass_count: passCount,
  fail_count: failCount,
  untested_count: untestedCount,
  total_count: totalCount,
  caller_claim_count: CALLER_COUNT,
  added_claim_count: addedClaims.length,
  run_claims_passed: runCount,
  untested_surface: untestedAll,
  claim_results: claimResults,
  overall_pass: overallPass,
  verifier: 'workflow',
  // Transcript relay fields — the thin-invoker SKILL.md instructs the main session to append
  // qa_log_entry to work/qa-log.md and to output compact_relay as plain unfenced text.
  qa_scope_text,
  qa_report_text,
  qa_log_entry,
  compact_relay,
}
