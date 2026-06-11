# ADR-0006: Full Procedure-Layer Migration to Workflow Scripts

**Status:** Accepted
**Date:** 2026-06-11

## Context and Problem Statement

ADR-0004 documented routing-as-code as a pilot direction with two converted skills (process-planning, process-pentest) and a calibration gate before full adoption. The gate required a human output-quality baseline to be established before expanding, because dispatch-by-construction makes "did we dispatch?" tautological as a success metric.

The pilot ran across a realistic workload. The following evidence justified full adoption:

- Output quality from Workflow-dispatched skills was equivalent to prose-path output for the same prompt class.
- The calibration gate was waived by the owner after reviewing pilot execution logs.
- The remaining four skills (process-research, process-analysis, process-build, process-qa) had structurally similar dispatch sequences and benefit from the same determinism as the two already converted.
- The three-file triplication (prose SKILL.md, DISPATCHES.json sidecar, enforcement hooks) was confirmed to create real drift risk over time.

## Decision Drivers

- The pilot validated the enabling assumption: Claude Code workflow sub-agents have the full tool surface (shell, file-read, dynamic tool-loading, MCP).
- Six concrete workflow scripts are now shipped and verified with `node --check`.
- The `workflows/` artifact class is a net addition; no hooks or skills are removed.
- DISPATCHES.json survives as a read-only H11 audit artifact — the compliance hook reads it for post-compaction fallback; retiring it would break that fallback.

## Considered Options

1. **Full migration (all six process skills)** — ship `workflows/process-*.js` for all six; update SKILL.md stubs with `## ⚡ Workflow-enforced` sections pointing to the scripts.
2. **Incremental expansion** — convert two more skills (process-research, process-analysis) now; defer process-build and process-qa until after another calibration round.
3. **Keep at two-skill pilot** — leave the pilot at process-planning and process-pentest; treat routing-as-code as an optional layer.

## Decision Outcome

**Chosen option: full migration (option 1).**

All six core process skills are now backed by deterministic workflow scripts in `workflows/`. Each SKILL.md carries a `## ⚡ Workflow-enforced (ADOPTED 2026-06-11)` section that provides the scriptPath, args contract, dispatch-sequence description, and HALT paths. The prose body of each SKILL.md survives unchanged below a `---` separator as spec-of-record and explicit fallback for operators who cannot or choose not to use the Workflow tool.

**Consequences:**

- *Positive:* dispatch sequence for all six process skills is now a construction-time property.
- *Positive:* the three-file drift risk (prose / DISPATCHES.json / hooks) is eliminated for the process-skill routing layer.
- *Positive:* typed schemas on every `agent()` call inside the scripts make PASS/FAIL logic deterministic and verifiable.
- *Negative:* `workflows/` is a new artifact class that adopters must install. Setup cost is one copy operation per skill.
- *Negative:* the session-cache gotcha (after editing a workflow script mid-session, invoke by `scriptPath` not by name) adds a small operator-knowledge requirement; documented in `workflows/README.md`.
- *Neutral:* DISPATCHES.json is retained as a read-only H11 audit artifact; `dispatch-compliance-check.py` continues to read it for post-compaction fallback.

## Workflow Script Invariants

All six scripts in `workflows/` follow these invariants (enforced by code structure, not by prose):

1. **Parse-if-string + HALT guard** — all scripts guard against `args` delivered as a JSON string vs. object; halt with `status: 'halted-malformed-args'` before spawning any agents if required fields are missing.
2. **Typed schemas on every `agent()` call** — forces structured output; PASS/FAIL logic evaluates typed fields, not prose self-report.
3. **FILE CONTRACT pattern** — agents that must produce files receive an explicit FILE CONTRACT; the quality gate reads the file to confirm.
4. **PASS/FAIL derived in code** — pass conditions evaluate typed evidence sub-fields, never prose agent self-report.
5. **DISPATCHES.json untouched** — the H11 sidecar is never modified by workflow scripts; it remains the read-only verification source for `dispatch-compliance-check.py`.
6. **HALT paths return, not throw** — all HALT conditions (`halted-malformed-args`, `ralph-loop-hand-back`, `decomposition-hand-back`) return a structured object rather than throwing an error, so callers can inspect the result.

## Relationship to Previous ADRs

- **ADR-0004** — this ADR amends ADR-0004. The pilot direction (status: Pilot, 2026-06-09) is superseded by this accepted decision. ADR-0004 is retained as the rationale record for the routing-as-code concept and the two-skill pilot.
- **ADR-0002** — the hooks-over-prompts rationale extends to workflow scripts: construction-time routing is a stronger guarantee than runtime hook enforcement, which is itself stronger than prose instruction.
