/*
 * test_process_qa_scoring.mjs: regression guard for the 2026-08-07 PowerShell false-FAIL bug.
 *
 * GUARDS: process-qa.js Step 3's execute-class auto-FAIL override (the branch that logs
 * "AUTO-FAIL claim ...: execute-class but tool_used=... is not Bash/PowerShell/MCP"). Before the
 * 2026-08-07 fix, EXECUTE_TOOLS did not list PowerShell/powershell, so an agent that genuinely
 * ran a hook via PowerShell and reported PASS with real evidence was wrongly overridden to FAIL.
 * The fix added PowerShell and powershell to the EXECUTE_TOOLS whitelist in process-qa.js.
 *
 * This test re-derives EXECUTE_TOOLS and satisfiesExecuteClass from the LIVE process-qa.js source
 * text at runtime (via regex extraction, not a hand-copied paraphrase), so it tests the file as it
 * actually is, not a frozen snapshot. It then runs the exact Step-3 per-claim decision branch
 * against three synthetic cases and fails loudly if the whitelist regresses.
 *
 * RUN: node .claude/workflows/test_process_qa_scoring.mjs
 * Exit 0: all three cases scored as expected. Exit 1: a case mismatched (regression), or the
 * source shape changed enough that extraction failed.
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SRC_PATH = path.join(__dirname, 'process-qa.js')
const src = fs.readFileSync(SRC_PATH, 'utf-8')

// Re-derive EXECUTE_TOOLS and satisfiesExecuteClass verbatim from the live source text.
const setMatch = src.match(/const EXECUTE_TOOLS = new Set\(\[[^\]]*\]\)/)
const fnMatch = src.match(/function satisfiesExecuteClass\(toolUsed\) \{[\s\S]*?\n\}/)

if (!setMatch || !fnMatch) {
  console.error('FAIL: could not extract EXECUTE_TOOLS / satisfiesExecuteClass from process-qa.js. Source shape changed, update this test.')
  process.exit(1)
}

// eval is scoped to this file and re-derives code from process-qa.js source text read above via
// fs, not from external or user input. This mirrors the throwaway verification approach used to
// prove the original fix, kept here as a permanent, runnable guard.
// eslint-disable-next-line no-eval
const satisfiesExecuteClass = eval(`${setMatch[0]}\n${fnMatch[0]}\nsatisfiesExecuteClass`)

// Replicates process-qa.js Step 3's per-claim decision branch (the execute-class auto-FAIL
// override plus the no-evidence override), so this test exercises the same code path the
// workflow runs at QA time, not a paraphrase of it.
function scoreClaim(res) {
  let result = res.result
  if (res.claim_class === 'execute' && !satisfiesExecuteClass(res.tool_used)) {
    result = 'FAIL'
  }
  if (!res.evidence && result !== 'UNTESTED') {
    result = 'FAIL'
  }
  return result
}

const cases = [
  {
    label: 'execute-class claim, verified via PowerShell, agent reported PASS with evidence',
    res: { claim_class: 'execute', tool_used: 'PowerShell', result: 'PASS', evidence: 'exit 0, real command output' },
    expected: 'PASS',
  },
  {
    label: 'execute-class claim, verified via Bash, agent reported PASS with evidence',
    res: { claim_class: 'execute', tool_used: 'Bash', result: 'PASS', evidence: 'exit 0, real command output' },
    expected: 'PASS',
  },
  {
    label: 'execute-class claim, verified via Read only, agent reported PASS with evidence',
    res: { claim_class: 'execute', tool_used: 'Read', result: 'PASS', evidence: 'read the file, looks correct' },
    expected: 'FAIL',
  },
]

console.log('\nRegression guard: process-qa.js Step 3 execute-class scoring (2026-08-07 PowerShell fix)')
console.log('='.repeat(88))

let failed = 0
for (const c of cases) {
  const actual = scoreClaim(c.res)
  const ok = actual === c.expected
  const status = ok ? 'PASS' : 'FAIL'
  console.log(`  [${status}] ${c.label}: expected ${c.expected}, scored ${actual}`)
  if (!ok) failed++
}

console.log('='.repeat(88))
console.log(`Results: ${cases.length - failed} passed, ${failed} failed out of ${cases.length} cases`)
process.exit(failed ? 1 : 0)
