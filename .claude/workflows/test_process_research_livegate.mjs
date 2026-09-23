/*
 * test_process_research_livegate.mjs — declarative acceptance test for the
 * process-research live-citation recurrence fix (2026-06-21).
 *
 * RECURRENCE DRIVER: finding_process_research_gatherers_skip_live_web (3rd+ recurrence;
 * repro wf_dd9d1d30-426). Training-only research reports that demanded live verification
 * were passing the Step-6 quality gate silently. This test pins the ENFORCEMENT contract.
 *
 * CRUX (verified during planning): process-research.js CANNOT be imported by standard
 * node — its module body has top-level `return` statements that are legal only in the
 * /workflows sandbox, not standard ESM (`SyntaxError: Illegal return statement`). So this
 * test does NOT `await import()` the workflow module. Instead it slices the marked
 * LIVE_GATE_HELPER block out of the source text, strips `export`, and evaluates that
 * REAL source in isolation via a data: URL import. This exercises the actual helper
 * source (not a duplicated copy) while keeping the build to exactly two files.
 *
 * Run: node .claude/workflows/test_process_research_livegate.mjs   (exit 0 = pass, 1 = fail)
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execSync } from 'node:child_process'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const TARGET = path.join(__dirname, 'process-research.js')

let passed = 0
let failed = 0
function check(name, cond, detail) {
  const ok = !!cond
  console.log(`  [${ok ? 'PASS' : 'FAIL'}] ${name}${ok ? '' : (detail ? ' — ' + detail : '')}`)
  if (ok) passed++; else failed++
}

console.log('\nprocess-research live-citation gate — declarative acceptance test')
console.log('='.repeat(72))

const src = fs.readFileSync(TARGET, 'utf-8')

// (d) marker presence — guards the test's own slice contract.
const hasStart = src.includes('// >>> LIVE_GATE_HELPER_START')
const hasEnd = src.includes('// <<< LIVE_GATE_HELPER_END')
check('(d) slice markers present verbatim', hasStart && hasEnd,
  `START=${hasStart} END=${hasEnd}`)

// Slice the helper block out of the source and load the REAL source in isolation.
let mod = null
let loadErr = null
try {
  const m = src.match(/\/\/ >>> LIVE_GATE_HELPER_START[\s\S]*?\n([\s\S]*?)\/\/ <<< LIVE_GATE_HELPER_END/)
  if (!m) throw new Error('could not slice LIVE_GATE_HELPER block (markers missing or malformed)')
  const sliced = m[1].replace(/\bexport\s+function\b/, 'function')
  const moduleSrc = sliced + '\nexport { evaluateLiveCitationGate }\n'
  const dataUrl = 'data:text/javascript,' + encodeURIComponent(moduleSrc)
  mod = await import(dataUrl)
} catch (e) {
  loadErr = e
}
check('helper sliced + loaded from real source', mod && typeof mod.evaluateLiveCitationGate === 'function',
  loadErr ? String(loadErr && loadErr.message) : 'no export')

const G = mod ? mod.evaluateLiveCitationGate : () => ({ liveGatePass: true, reason: 'STUB-NOT-LOADED' })

// (a) FAIL case: scope required live + zero live citations => gate FAILS with a live-web reason.
const a = G({ liveRequired: true, liveCitationCount: 0 })
check('(a) live required + 0 citations => liveGatePass false',
  a.liveGatePass === false, `got ${a.liveGatePass}`)
check('(a) reason mentions live/zero',
  /live|zero/i.test(a.reason || ''), `reason="${a.reason}"`)

// (b1) no-false-positive: live required but citations present => PASS.
const b1 = G({ liveRequired: true, liveCitationCount: 2 })
check('(b1) live required + 2 citations => liveGatePass true',
  b1.liveGatePass === true, `got ${b1.liveGatePass}`)

// (b2) no-false-positive: scope not requiring live => PASS (strict no-op).
const b2 = G({ liveRequired: false, liveCitationCount: 0 })
check('(b2) live NOT required + 0 citations => liveGatePass true (no-op)',
  b2.liveGatePass === true, `got ${b2.liveGatePass}`)

// (b3) robustness: empty/undefined input => defaults to not-required no-op, never crashes.
let b3 = null, b3err = null
try { b3 = G({}) } catch (e) { b3err = e }
check('(b3) empty input => liveGatePass true, no crash',
  b3 && b3.liveGatePass === true, b3err ? String(b3err.message) : `got ${b3 && b3.liveGatePass}`)

// (c) parse smoke: process-research.js still parses under node --check.
let parseOk = false, parseErr = ''
try { execSync(`node --check "${TARGET}"`, { stdio: 'pipe' }); parseOk = true }
catch (e) { parseErr = String((e && e.stderr) || (e && e.message) || e) }
check('(c) process-research.js passes node --check', parseOk, parseErr)

console.log('='.repeat(72))
console.log(`Results: ${passed} passed, ${failed} failed out of ${passed + failed} checks`)
process.exit(failed ? 1 : 0)
