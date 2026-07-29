---
name: n8n-review
description: Review n8n workflows against team quality guidelines. Validates naming, visual chain, sticky notes, execution data, error handling, security, and credentials. Use when a user wants to audit, review, or check an n8n workflow for quality and compliance.
---

# n8n Workflow Review

Review an n8n workflow against the team's quality guidelines and produce a findings report.

## Use-when

- User asks to "audit", "review", "check", or "validate" an n8n workflow
- Pre-production quality gate before activating a workflow
- Periodic compliance check on existing workflows (security, error handling, naming)

## Do-NOT-use-when

- User wants to RENAME nodes or DOCUMENT a workflow — use `n8n-reviewer` (broader scope: review + rename + document + full mode)
- User wants to BUILD or MODIFY a workflow — use `n8n-workflow-architect` (design) → `n8n-workflow-builder` (implementation)
- User wants to UNDERSTAND a workflow's logic for onboarding — produce a Mermaid logic diagram + WHY-prose instead (per logic-diagram-first feedback memory)

## Gotchas

- **Findings report only — no edits applied** — this skill produces a report; modifications belong to the architect+builder two-phase pattern.
- **Live workflow > cached file** — fetch via `mcp n8n_get_workflow` with `full=true`; never review a stale workflow JSON dump unless the user explicitly says it's current.
- **Default report mode is concise** — full audit (`--detailed` flag) only on user request; concise is the right default for the team-handoff use case.

## Input

The user provides a workflow identifier — either:
- A workflow ID (e.g., `tORXmcQlh4g0A62T`)
- A workflow name to search for
- A file path to a workflow JSON export

**Report mode (optional):** The user can request `--detailed` for the full audit report (see `references/report-template-detailed.md`). Default is concise.

## Process

### Step 1: Fetch the workflow

Get the full workflow JSON:
- If workflow ID: use `mcp n8n_get_workflow` with `full=true`
- If workflow name: use `mcp n8n_list_workflows` to find the ID, then fetch
- If file path: read the file

Verify the JSON contains `nodes` array and `connections` object. If either is missing, tell the user this isn't a valid n8n workflow export.

### Step 2: Load guidelines

Read `references/guidelines.md` — this contains all 9 guideline areas with rules and checklists.

### Step 3: Dispatch review agent

Dispatch a **Sonnet** agent with:
1. The full workflow JSON
2. The full guidelines reference text
3. The report template (below)

The agent's prompt must include the complete workflow JSON and the complete guidelines text — do not summarize or truncate either. The agent needs both in full to produce accurate findings.

**Agent dispatch template:**

```
Review this n8n workflow against the team guidelines. Produce a findings report.

## Guidelines

{paste full content of references/guidelines.md}

## Workflow JSON

{paste full workflow JSON}

## Pre-Analysis (mandatory)

Before writing the report, extract and verify these counts from the JSON:

1. Total nodes: length of the `nodes` array
2. External-service nodes: count nodes where type contains `httpRequest`, `googleDrive`, `googleSheets`, `googleGemini`, `executeWorkflow`, `slack`, `supabase`, `airtable`, or any other API/database/external-service type. Exclude trigger nodes.
3. Credential references: count unique credential IDs across all nodes
4. Code nodes: count nodes where type is `n8n-nodes-base.code`
5. Sticky notes: count nodes where type contains `stickyNote`
6. Execution Data nodes: count nodes where type is `n8n-nodes-base.executionData`

Report these exact counts in the header. Do not estimate or round.

## Instructions

Walk through each guideline area (1-8). For each:
1. Check every applicable rule against the workflow JSON
2. If all rules pass, write one line: "PASS — no issues."
3. If any rule fails, list each issue as: Problem → Fix. One line per issue. No explanations unless the problem is non-obvious.

Specific checks:
- G07 (Security): search the ENTIRE workflow JSON for hardcoded URLs. Report exact count and every node name.
- G08 (Credentials): check names against `{Service} — {Environment} — {Scope}` pattern.
- Code nodes: check for silent failure suppression (catch-and-return-null), unguarded JSON.parse(), mixed-language comments.
- Merge nodes: check for combineAll cartesian product risk.
- Trigger: check if required inputs are validated before downstream use.
- Node types: check if all instances of the same type share the same typeVersion.
- Look for alwaysOutputData on any node — this can mask failures.

Be concise. Problem → Fix. No tutorials, no explanations of why rules exist. We know.

Output the report in the exact format specified below.
```

### Step 4: Save and present report

Save the agent's report to:
```
Projects/n8n-guidelines/reviews/{workflow-name}-{YYYY-MM-DD}.md
```

Use kebab-case for the workflow name (e.g., `awards-s2a-interpret-2026-03-31.md`). Create the `reviews/` directory if it doesn't exist.

Then show the report to the user with a one-line summary and the file path at the top.

## Report Template (Concise — Default)

```markdown
# n8n Review: {Workflow Name}

**ID:** {id} | **Nodes:** {count} | **Active:** {true/false} | **Date:** {today}
**Result:** {N}/8 passed

---

## 1. Naming Conventions

{PASS or:}
`{current name}` → `{fixed name}`
{any additional naming issues, one per line}

## 2. Node Naming

{PASS or:}
| Current Name | → | New Name | Issue |
|---|---|---|---|
| {old} | → | {new} | {Default / Misleading / Service prefix / Title Case} |

## 3. Visual Chain

{PASS or:}
- {issue} — {description with coordinates if relevant}
Visual inspection recommended for connection crossings.

## 4. Sticky Notes

{PASS or:}
- Missing: {what's needed — header, warnings, section markers}
- Add: {count} notes minimum for {N}-node workflow

## 5. Execution Data

{PASS or:}
- Missing: {what's needed — start node, error path nodes}
- Keys: {recommended keys for this workflow}

## 6. Error Handling

{PASS or:}

**Critical:**
- {problem} → {fix}

**Important:**
- {problem} → {fix}

| Node | Timeout | Retries |
|------|---------|---------|
| {node} | {seconds}s | {count} |

## 7. Security

{PASS or:}
- {problem} → {fix}

Hardcoded URLs: {exact count} nodes — {list all node names}

## 8. Credentials

{PASS or:}
| Current Name | → | Correct Name | Issue |
|---|---|---|---|
| {old} | → | {Service} — {Env} — {Scope} | {issue type} |

---

## Priority Fixes

### P1 — Critical
- [ ] {fix} ({Section N})

### P2 — Important
- [ ] {fix} ({Section N})

### P3 — Improvement
- [ ] {fix} ({Section N})

## Room for Improvement

{Things that aren't violations but could be better — architectural suggestions, optimization opportunities, patterns that would make the workflow more robust. Skip if nothing worth noting.}
```

## Notes

- This skill produces a **report only** — it does not modify the workflow.
- For the detailed audit report (severity matrix, per-finding severity tags, Notable Bugs section), use `--detailed` flag. Template at `references/report-template-detailed.md`.
- For large workflows (50+ nodes), the review may need to be done in the main session rather than a subagent to avoid context limits.
