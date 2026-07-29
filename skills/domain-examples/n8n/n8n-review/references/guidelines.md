# n8n Workflow Guidelines — Review Reference

This file consolidates all 9 team guideline areas. Use it to evaluate workflow JSON against each area and produce findings.

---

## G01 — Workflow Naming

**Pattern:** `{Project} — {Stage}: {Action}` (omit Stage if standalone)
- Use n8n native tags for status: only `WIRED` (production) and `TEMPLATE`
- No default names (`My workflow`, `New Workflow`)
- Version prefix if coexisting: `V2 - Awards — S2a: Interpret`
- Title Case, under 60 characters
- Deprecated workflows should be tagged and archived, not left active

**Workflow settings:**
- **Execution order:** Check `settings.executionOrder`. `v1` is the recommended depth-first order (completes each branch before starting next). `v0` is legacy breadth-first (interleaves branches). If set to `v0` or missing, flag as LOW — recommend setting to `v1`.

**Checklist:**
- [ ] Name follows `{Project} — {Stage}: {Action}` pattern
- [ ] n8n tags applied (`WIRED` or `TEMPLATE` where applicable)
- [ ] No default or placeholder names
- [ ] Version prefix only if multiple versions coexist
- [ ] Execution order is `v1` (not legacy `v0`)

---

## G02 — Node Naming

**Patterns by type:**

| Node Type | Pattern | Bad Examples |
|-----------|---------|-------------|
| Code | verb + object | "Code", "Code1" |
| HTTP Request | verb + resource | "HTTP Request", "HTTP Request1" |
| Google Sheets | operation + context | "Google Sheets", "Google Sheets1" |
| Split Out | "Split {field}" | "Split Out", "Split Out1" |
| Merge | "Merge {description}" | "Merge", "Merge1" |
| Switch | "Route by {condition}" | "Switch", "Switch1" |
| IF | "If {condition}" | "IF", "IF1" |
| Set | "Set {what}" | "Set", "Set1" |
| NoOp | section label or purpose | "->", "-->", "NoOp" |
| Stop and Error | error context | "Stop and Error" |
| Wait | wait context | "Wait" |
| Execute Workflow | sub-workflow purpose | "Execute Workflow" |
| Webhook | trigger context | "Webhook" |
| Sticky Note | section heading | "Sticky Note1" |

**Rules:**
- Title Case always
- Under 40 characters
- No default names — zero tolerance
- Don't include node type in name (icon shows it)
- Names must match current behavior (update after refactoring)
- **Name must match actual behavior:** Check HTTP Request nodes — if the name says "Download" but the method is POST/PUT/PATCH, the name is wrong (and vice versa). Check "Prepare for X" nodes — verify X matches what actually happens downstream. Behavioral mismatches are HIGH severity because they actively mislead operators during debugging.
- Unique within workflow
- No non-standard abbreviations (API/URL/ID fine; Fmt/Val/Proc not)
- **Node type version consistency:** Check `typeVersion` across nodes of the same type. If one node is on a different version than its siblings, flag as LOW — different versions may have different default behaviors, request formats, or response structures. List the outlier nodes.
- **Code comments language consistency:** Code node comments and variable names should be in the team's working language. Mixed-language comments reduce the maintainability pool. Flag as LOW.

**Checklist:**
- [ ] Zero default-named nodes
- [ ] Names describe what the node does, not what type it is
- [ ] Title Case, under 40 characters
- [ ] Names unique within the workflow
- [ ] Names match current node behavior
- [ ] HTTP nodes named "Download/Fetch/Get" actually use GET method
- [ ] HTTP nodes named "Upload/Send/Push" actually use POST/PUT method
- [ ] "Prepare for X" nodes — X matches the downstream operation
- [ ] Same node types share the same typeVersion (report outliers)

---

## G03 — Visual Chain

**Rules:**
- Flow direction: left to right. Trigger leftmost, outputs rightmost.
- No crossing connections. Use Do Nothing (NoOp) nodes as routing anchors if needed.
- Consistent spacing — equal horizontal and vertical gaps.
- Group related nodes visually; separate sections with whitespace.
- Error paths below the happy path.
- Parallel branches stacked vertically, primary/most-common on top.
- Clean up after development: no disconnected nodes, straightened paths.

**Checklist:**
- [ ] Flow reads left to right
- [ ] Trigger is the leftmost node
- [ ] No crossing connections
- [ ] Error paths below the happy path
- [ ] Parallel branches stacked vertically
- [ ] Related nodes grouped with consistent spacing
- [ ] No disconnected/orphaned nodes
- [ ] Final outputs are the rightmost nodes

**Note:** Visual chain can only be partially checked from JSON (positions, disconnected nodes). Connection crossings require visual inspection. Report what you CAN determine from position data and flag "visual inspection recommended" for the rest.

---

## G04 — Sticky Notes

**Rules:**
- Summary sticky note mandatory — top-left, purple (color 5). Must contain: name, purpose, inputs, outputs, flow summary.
- Section notes (teal, color 6) where they add clarity — don't force on self-explanatory sections.
- Warning notes (red, color 4) for non-obvious behavior: rate limits, fragile dependencies, manual steps.
- TODO notes (yellow, color 3) — must be resolved before tagging WIRED.
- Complex multi-branch workflows (3+ branches): use different colors per branch instead of all teal.
- No default-named sticky notes ("Sticky Note1").
- Keep content concise — bullet points, not paragraphs.
- Position notes above/near the nodes they describe.

**Color codes:** 1=blue, 2=green, 3=yellow, 4=red, 5=purple, 6=teal, 7=orange

**Checklist:**
- [ ] Summary sticky note present at top-left (purple)
- [ ] Section notes where they add clarity
- [ ] Warning notes for non-obvious behavior (red)
- [ ] No default-named sticky notes
- [ ] All TODO notes resolved before production
- [ ] Notes positioned near the nodes they describe

---

## G05 — Execution Data

The Execution Data node (`n8n-nodes-base.executionData`) annotates executions with custom key-value metadata for filtering and debugging.

**Placement:**
- **Start of workflow** — required. Right after trigger. Captures run identifiers.
- **End of error path** — required. Captures what failed and why.
- **End of happy path** — only if there's a meaningful filterable value. Don't add just to say "success."

**Standard keys:**

| Key | When to use |
|-----|-------------|
| `errorReason` | Required on failure paths — what broke and why |
| `source` | On failure paths — which node caused the error |
| `processedCount` | When the workflow processes countable items |

**Skipped keys:** `status` (redundant — n8n UI shows success/error), `trigger source` (trigger node is always visible).

**Rules:**
- Keys must be unique-identifiable per run (not static across all executions)
- Values must be short, filterable strings — no JSON blobs
- Document domain-specific keys in summary sticky note
- Name Execution Data nodes descriptively per G02

**Checklist:**
- [ ] Execution Data node at start of workflow
- [ ] Execution Data node on error paths (`errorReason` + `source`)
- [ ] End-of-happy-path node only if meaningful filterable value exists
- [ ] Values are short, filterable strings
- [ ] Keys are unique-identifiable per run
- [ ] Domain-specific keys documented in summary sticky note

---

## G06 — Error Handling

**Rules:**
- **Every node that can fail** must have its error output wired. This is NOT limited to external-service nodes — it includes:
  - External-service nodes (HTTP Request, Google Sheets, database, API, DataTable)
  - executeWorkflow — **BUT see caveat below about `waitForSubWorkflow`**
  - LLM nodes (chainLlm, agent) — these have error outputs at index 1
  - Agent nodes — error output at index 1
  - splitInBatches — can have error outputs
  Nodes that do NOT need error wiring:
  - Code nodes — they crash natively, errorWorkflow catches them
  - Set nodes — they don't fail
  - SMTP / notification nodes at end of flow — pipeline's job is already done
  Error handling options for failable nodes:
  - `onError: continueErrorOutput` with connected error output (preferred)
  - `onError: continueRegularOutput` with downstream validation
- **ALWAYS use NoOp routing anchors** — every error output routes through a NoOp chain to Handle Error, never directly. This creates a clean horizontal error highway at the bottom of the canvas. Even if a node is adjacent to Handle Error, use a NoOp. Pattern: ErrorSource → NoOp → NoOp → ... → Handle Error → Stop: Error + Tag: Error. One NoOp per error source, chained left-to-right.
- **Execute Workflow node caveat:** `onError: continueErrorOutput` + `waitForSubWorkflow: false` = known n8n bug (sub-workflow runs 0 nodes, silent failure). Either use `waitForSubWorkflow: true` with `continueErrorOutput` (recommended for pipelines), or use `waitForSubWorkflow: false` without `continueErrorOutput`. Never combine fire-and-forget with continueErrorOutput. See: https://community.n8n.io/t/execute-workflow-wait-for-sub-workflow-false-sub-workflow-aborts/53771
- Never use `onError: ignore` — silent failure is the worst outcome
- Error output paths must lead somewhere useful: Stop and Error, notification, fallback logic, or Execution Data node
- Stop and Error messages must be descriptive: what failed, likely cause, what to check
- Retry config for HTTP/API nodes: `retryOnFail: true`, `waitBetweenTries: 5000`, `maxTries: 3`
- **Hybrid error handling pattern:** Production workflows use two mechanisms together:
  - `errorWorkflow` setting catches unhandled crashes (production executions only — manual editor runs don't trigger it)
  - Stop and Error nodes catch expected failures with descriptive messages (the message appears in the Teams alert)
  - A workflow with neither is not production-ready
- **Connect to centralized error handling:** Every production workflow must:
  - Set `errorWorkflow` in workflow settings → W1: Error Receiver
  - Register in Workflows DataTable (workflow_id, workflow_name, project_id, is_critical)
  - Register project in Projects DataTable if new (project_id, project_name, owner_email for @mentions)
  - `is_critical: true` = immediate Teams alert. `is_critical: false` = silent log, escalates after 3+ errors in 12h
- **Converged error handler pattern:** Do NOT create a separate Stop and Error node per error source. Instead, all error outputs converge to a single `Handle Error` Code node → single `Stop: Error` node. The Code node builds a descriptive message using trigger context (`run_id`, `award`, etc.) and the error source. This keeps the canvas clean and gives one place to add notification logic (email, Slack, Teams). Pattern:
  ```
  [Node A error output] ──┐
  [Node B error output] ──┤──→ Handle Error (Code) ──→ Stop: Error
  [IF false branch]    ───┘
  ```
  The `Handle Error` Code node should reference the trigger node to pull identifiers: `$('TriggerName').first().json.run_id`
- **Stop and Error message format:** `"Error in {workflow}: {description} for run_id '{run_id}'"` — include enough context to diagnose without opening the execution
- Explicit timeouts on slow API calls (scraping, LLM, batch endpoints)
- Validate API responses — don't trust 200 OK blindly
- **Silent failure suppression in Code nodes:** Check all Code nodes for patterns that catch errors and return null, undefined, empty objects, or default values instead of re-throwing or routing to an error path. Common anti-patterns:
  - `if (response.error) { return null; }` followed by `.filter(x => x !== null)`
  - `try { ... } catch(e) { return {}; }` — swallowing errors silently
  - Returning a smaller dataset without logging or signaling that items were dropped
  These patterns are CRITICAL because they produce data loss without visibility — the workflow appears to succeed while silently discarding failed items.
- **Unguarded deserialization:** Check Code nodes for `JSON.parse()` calls without surrounding try/catch. LLM outputs, API responses, and webhook payloads are all unreliable input — parsing them without error handling is HIGH severity. The fix is either try/catch with a descriptive error message, or upstream validation that the string is valid JSON before parsing.
- **Cartesian product risk in Merge nodes:** Check Merge nodes configured with `combineBy: combineAll`. This mode multiplies every item from input 1 by every item from input 2. Flag as MEDIUM if one input is guaranteed to be a single item (fragile assumption), HIGH if both inputs can produce multiple items. Preferred fix: use `combineByPosition` or add explicit validation that one input is single-item.
- **Trigger input validation:** For Execute Workflow Trigger nodes, check if critical input fields are validated before use. If fields are `required: false` but the workflow will fail without them, add a Code or IF node immediately after the trigger to validate required inputs and throw a descriptive Stop and Error. Flag as MEDIUM.

**Checklist:**
- [ ] All external-service nodes have error handling configured
- [ ] Zero instances of `onError: ignore`
- [ ] Error output paths lead to useful destinations (not disconnected)
- [ ] Stop and Error nodes have descriptive, actionable messages
- [ ] Retry config: `waitBetweenTries: 5000`, `maxTries: 3`
- [ ] Hybrid pattern: `errorWorkflow` setting + Stop and Error nodes on expected failures
- [ ] `errorWorkflow` points to W1: Error Receiver
- [ ] Workflow registered in Workflows DataTable (project_id, is_critical)
- [ ] Project registered in Projects DataTable (owner_email for @mentions)
- [ ] Explicit timeouts on slow API calls
- [ ] API responses validated before use
- [ ] Code nodes do not silently suppress errors (no catch-and-return-null patterns)
- [ ] All JSON.parse() calls in Code nodes are wrapped in try/catch
- [ ] Merge nodes using `combineAll` — verify single-item guarantee on one input
- [ ] Trigger inputs validated for required fields before downstream use

---

## G07 — Security

**Hardcoded secrets (CRITICAL):**
- Never hardcode API keys, tokens, passwords in node parameters
- Red flags: strings starting with `sk-`, `pk-`, `Bearer `, `Basic `, `ghp_`, `xoxb-`, `AKIA`
- Red flags: long alphanumeric strings (32+ chars) that look like keys
- Red flags: values in fields named `apiKey`, `token`, `password`, `secret`, `authorization`

**Hardcoded service URLs and configuration:**
- Count every occurrence of hardcoded service URLs (e.g., Supabase, Firebase, API base URLs) across both Code node `jsCode` and HTTP Request node `url` parameters. Report the exact count and list every node. These are not secrets but are portability/maintenance risks — a single configuration change requires editing N nodes individually with risk of partial updates.

**Network (CRITICAL):**
- All HTTP Request URLs must use `https://` (localhost exception)
- **Dynamic URL scheme enforcement:** When an HTTP Request node's URL comes from a dynamic expression (`{{ $json.someUrl }}`), there is no compile-time guarantee it uses HTTPS. Add an upstream validation node or inline expression that rejects `http://` URLs. Flag as HIGH — dynamic URLs from external sources (webhooks, API responses) may contain HTTP schemes, transmitting data unencrypted.
- Webhook triggers must have `authentication` configured (not `none` or missing)

**Code safety (CRITICAL):**
- No `eval()`, `new Function()`, `exec()`, `require('child_process')`, `require('fs')` writes, `process.env`, `while(true)` in Code nodes

**Loop safety:**
- No self-triggering (Execute Workflow calling same workflow ID)
- No circular connections in the workflow graph

**Data protection:**
- Send only required fields to external services (data minimization)
- Sensitive field names (`password`, `token`, `ssn`, `credit_card`, `social_security`, `bank_account`) must not appear unmasked in HTTP bodies, webhook responses, or logs

**Checklist:**
- [ ] Zero hardcoded secrets in any node parameter
- [ ] All URLs use `https://`
- [ ] Dynamic URLs validated for HTTPS scheme before use
- [ ] Hardcoded service URLs counted precisely — exact count and every node listed
- [ ] Webhook triggers have authentication configured
- [ ] Code nodes: no eval, exec, child_process, process.env
- [ ] No self-triggering workflows
- [ ] No circular connections
- [ ] External API calls send only required fields
- [ ] Sensitive field names not exposed in outputs

---

## G08 — Credentials Naming

**Pattern:** `{Service} — {Environment} — {Scope}`
- Service: the platform/API (Google Sheets, Apify, Slack, OpenAI)
- Environment: `Prod`, `Dev`, `Staging`, `Test`
- Scope: `Team`, person name, or project name

**Rules:**
- Always include environment tag
- No default names ("Google OAuth2 account", "My credential")
- Distinguish shared (`Team`) from personal (person name)
- Project scope when needed (`OpenAI — Prod — Awards Project`)
- Update names when purpose changes (dev promoted to prod → rename)
- Title Case, em dashes as separators, under 50 characters

**Checklist:**
- [ ] All credentials follow `{Service} — {Environment} — {Scope}` pattern
- [ ] Environment tag present and matches actual usage
- [ ] No default credential names
- [ ] Shared vs personal clearly marked

---

## G09 — Credentials Management

**Rules:**
- All secrets through n8n's credential system — never in Set nodes, Code nodes, workflow parameters, or static data
- One credential per purpose — don't reuse general keys across unrelated workflows if scoped keys are available
- Test credentials in isolation before wiring into complex workflows
- Document credential metadata (creation date, expiry, rotation schedule)
- Rotate non-auto-refreshing credentials (quarterly default)
- Remove unused credentials periodically
- Don't expose credential names in externally shared workflow exports
- **Unnecessary credential attachment:** Check HTTP Request nodes that fetch or upload to presigned URLs (URLs containing tokens, signatures, or query-string auth). If the node also has credentials configured, the API key/token header is being sent to the presigned endpoint unnecessarily — this leaks credentials to the storage provider. Fix: remove credential from nodes using presigned URLs.

**Checklist:**
- [ ] All secrets through credential system — zero in node parameters
- [ ] Each credential has a single clear purpose
- [ ] No unused credentials lingering
- [ ] Credential names not exposed in shared exports
- [ ] No unnecessary credentials on presigned URL requests
