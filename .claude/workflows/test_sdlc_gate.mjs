/*
 * test_sdlc_gate.mjs — Reintroduction guard for the retired SDLC Layer-2 sdlcEntryGate.
 *
 * HISTORY: the original test exercised the live sdlcEntryGate helper (33 tests).
 * That helper was RETIRED 2026-06-18: it called require('fs') which the /workflows
 * sandbox does not provide, so it fail-opened on every call and enforcement was ZERO.
 * Build record: Projects/Agent-Governance-Research/work/2026-06-18-layer2-retire-build-record.md
 *
 * PURPOSE NOW: assert that the gate strings are ABSENT from all six workflow scripts.
 * This is a permanent regression guard that catches silent reintroduction of the dead
 * code. If the guard exits 1, a banned symbol was reintroduced and must be removed.
 *
 * Run: node .claude/workflows/test_sdlc_gate.mjs   (exit 0 = all absent, 1 = reintroduced)
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const WORKFLOWS = [
  'process-qa.js',
  'process-pentest.js',
  'process-build.js',
  'process-planning.js',
  'process-analysis.js',
  'process-research.js',
]

// Both the function name and the invocation variable are banned.
const BANNED = ['sdlcEntryGate', '__sdlcGate']

let passed = 0
let failed = 0

console.log('\nReintroduction guard: sdlcEntryGate ABSENT from all six workflow scripts')
console.log('='.repeat(72))

for (const wf of WORKFLOWS) {
  const src = fs.readFileSync(path.join(__dirname, wf), 'utf-8')
  const hits = BANNED.filter(sym => src.includes(sym))
  const ok = hits.length === 0
  const status = ok ? 'PASS' : 'FAIL'
  console.log(`  [${status}] ${wf}: gate strings absent${ok ? '' : ' — REINTRODUCED: ' + hits.join(', ')}`)
  if (ok) passed++; else failed++
}

console.log('='.repeat(72))
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} scripts`)
process.exit(failed ? 1 : 0)
