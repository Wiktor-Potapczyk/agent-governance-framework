// Executable check for the auto-fail rule in process-qa.js satisfiesExecuteClass().
// Origin: 2026-09-09 defect, an execute-class agent PASS was overridden to FAIL because
// tool_used read "Bash, PowerShell" and the matcher used exact string equality.
// Run: node .claude/workflows/test_process_qa_toolclass.mjs   (exit 0 = pass, 1 = fail)
import { readFileSync } from 'node:fs'

const SRC = '.claude/workflows/process-qa.js'
const src = readFileSync(SRC, 'utf8')

// Lift the two declarations out of the workflow source so the check tests the REAL code,
// not a copy that can drift away from it.
const setLine = src.match(/^const EXECUTE_TOOLS = .*$/m)
const fnBody = src.match(/^function satisfiesExecuteClass[\s\S]*?^\}/m)
if (!setLine || !fnBody) {
  console.error('FAIL: could not locate EXECUTE_TOOLS or satisfiesExecuteClass in ' + SRC)
  process.exit(1)
}
const satisfiesExecuteClass = new Function(`${setLine[0]}\n${fnBody[0]}\nreturn satisfiesExecuteClass`)()

// [tool_used, expected] — expected true means an execute-class PASS must survive.
const CASES = [
  ['Bash', true],
  ['PowerShell', true],
  ['bash', true],
  ['mcp__codegraph__query', true],
  ['Bash, PowerShell', true],          // the defect: two real tools, one string
  ['PowerShell, Bash', true],
  ['Bash + PowerShell', true],
  ['Read, Bash (grep/sed/wc)', true],  // descriptive parenthetical around a real tool
  ['Grep + Bash (grep -in)', true],
  ['Bash (heredoc)', true],
  ['Read', false],                     // must still fail closed
  ['Grep', false],
  ['Read, Grep', false],
  ['none', false],
  ['', false],
  [null, false],
]

let failed = 0
for (const [input, expected] of CASES) {
  const actual = satisfiesExecuteClass(input)
  const ok = actual === expected
  if (!ok) failed++
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${JSON.stringify(input)} -> ${actual} (expected ${expected})`)
}
console.log(`\n${CASES.length - failed}/${CASES.length} passed`)
process.exit(failed === 0 ? 0 : 1)
