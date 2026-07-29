# n8n Workflow Style Guide

This is the team's source of truth for workflow quality. The n8n-reviewer skill reads this file and enforces these rules. Edit this file to customize what gets flagged during reviews.

---

## Naming Conventions

Good node names tell you what the node does at a glance — without opening it. Someone unfamiliar with the workflow should be able to read the node names left-to-right and understand the flow.

### By Node Type

| Node Type | Pattern | Good Examples | Bad Examples |
|-----------|---------|---------------|-------------|
| Code | verb + object | "Validate Name", "Format Payload", "Build Apify Request" | "Code", "Code1", "Code2" |
| HTTP Request | verb + resource | "Fetch LinkedIn Profile", "Post to Slack", "Get OAuth Token" | "HTTP Request", "HTTP Request1" |
| Google Sheets | operation + context | "Update Contact Status", "Read Prospect List", "Append Results" | "Google Sheets", "Google Sheets1" |
| Split Out | "Split {field}" | "Split Contacts", "Split Line Items" | "Split Out", "Split Out1" |
| Merge | "Merge {description}" | "Merge Validated + Skipped", "Combine API Results" | "Merge", "Merge1" |
| Switch | "Route by {condition}" | "Route by Response Type", "Route by Status" | "Switch", "Switch1" |
| IF | "If {condition}" | "If Contact Valid", "If Has Email" | "IF", "IF1" |
| Set | "Set {what}" | "Set Default Values", "Set Status Fields" | "Set", "Set1" |
| NoOp | section label or flow marker | "Validation Start", "Skip Path" | "->", "-->", "NoOp" |
| Sticky Note | section heading | "Pre-Processing", "Validation", "Post Processing" | "Sticky Note", "Sticky Note1", "Sticky Note2" |
| Stop and Error | error context | "Fail: Apify Scrape Error", "Fail: Missing Required Fields" | "Stop and Error" |
| Wait | wait context | "Wait 5s for API Rate Limit" | "Wait" |
| Execute Workflow | sub-workflow name | "Run Contact Validation", "Run Email Enrichment" | "Execute Workflow" |
| Webhook | trigger context | "Receive Inbound Lead", "CRM Update Webhook" | "Webhook" |

### General Rules

- Names should be **unique** within a workflow — no two nodes with the same name
- Keep names under **40 characters** when possible
- Use **Title Case** for node names
- Avoid abbreviations unless universally understood (API, URL, ID are fine; "Fmt" for "Format" is not)
- Don't include the node type in the name — the icon already shows that ("Code: Validate Name" is redundant, just "Validate Name")

---

## Security Rules

These protect against common vulnerabilities in n8n workflows. Issues flagged as critical must be resolved before deploying to production.

### Secrets & Credentials (Critical)
- Never hardcode API keys, tokens, passwords, or secrets in node parameters — use n8n's credential system
- Watch for string literals that look like secrets: long alphanumeric strings, strings starting with `sk-`, `pk-`, `Bearer `, `Basic `, `ghp_`, `xoxb-`, `AKIA`
- Credential *names* in the JSON are references, not secrets — but note that they reveal infrastructure details

### Network Security (Critical)
- All HTTP endpoints must use `https://` — flag any `http://` URLs
- Webhook nodes must have authentication enabled (check for `authentication` in webhook node parameters)

### Code Safety (Critical)
- Code nodes must not use `eval()`, `new Function()`, `exec()`, `child_process`, `require('child_process')`, `require('fs')` for writes, or `process.env` to read secrets directly
- Flag any dynamic code execution patterns

### Data Protection (Warning)
- Sensitive field names (password, secret, token, ssn, credit_card, social_security, bank_account) should not appear unmasked in HTTP request bodies, webhook responses, or log outputs
- If a workflow sends data to external services, verify it's not over-sharing (sending entire records when only specific fields are needed)

### Loop Safety (Warning)
- Check for circular connections in the workflow graph that could cause infinite execution
- In Code nodes, flag `while(true)` or unbounded loops without clear exit conditions
- Flag workflows that trigger themselves (Execute Workflow calling the same workflow ID)

---

## Quality Rules

These enforce maintainability and efficiency based on DRY (Don't Repeat Yourself) and ATOMIC (each unit does one thing) principles.

### DRY Violations (Warning)
- No two Code nodes should contain substantially similar logic (>60% overlap in structure). If they do, extract the shared logic into a sub-workflow or a single parameterized Code node
- The same n8n expression repeated in 3 or more nodes should be consolidated into a Set node that computes the value once
- If multiple nodes make HTTP requests to the same API with similar configurations, consider whether they can be consolidated

### ATOMIC Principle (Warning)
- A single Code node should have one clear responsibility. Flag Code nodes that:
  - Exceed 50 lines of code
  - Contain multiple distinct logical sections (data transformation + validation + API call in one node)
  - Have inline comments marking different "phases" or "steps" — this suggests the node should be split
- Each workflow should have a single clear purpose. If a workflow does two unrelated things, suggest splitting it

### Error Handling (Warning)
- Nodes that interact with external services (HTTP Request, API nodes, database nodes) should have error handling configured:
  - `onError` field set to `continueErrorOutput` or `continueRegularOutput` with error handling downstream
  - OR a connected error output path
- Every workflow should have at least one error handling strategy (Stop and Error node, error output path, or try/catch in Code nodes)
- Flag workflows where errors would silently disappear (no error output connected, `onError` set to ignore)

### Unused Nodes (Info)
- Nodes that appear in the `nodes` array but are not referenced in the `connections` object (and aren't sticky notes or the trigger node) are likely leftovers from development. Flag them for removal.
- NoOp nodes used purely as visual arrows ("->", "-->") with no meaningful routing purpose should be flagged for removal or renaming

### Efficiency (Info)
- Flag Google Sheets nodes that read entire sheets when a filter or range would suffice
- Flag patterns where data is fetched, transformed, and then most of it is discarded — suggest filtering earlier in the pipeline
- Note any nodes with `retryOnFail: true` and very short `waitBetweenTries` values (<1000ms) — this can hammer external APIs

---

## Documentation Requirements

### In-Workflow Documentation
- Every workflow must have a **summary sticky note** positioned at the top-left of the canvas
- The summary sticky note should contain: workflow name, purpose, inputs, outputs, flow summary, and a link to detailed docs
- Each major section/phase of the workflow should have its own sticky note explaining what that section does
- Sticky note colors should be used consistently to indicate sections (the team can define their own color scheme)

### External Documentation
- Production workflows require a Confluence page with full technical documentation
- The documentation should be kept in sync with the workflow — when the workflow changes, the docs should be updated
- At minimum, external docs should cover: purpose, trigger, inputs/outputs, external services used, credentials, and the processing flow

---

## How to Customize This Guide

This file is the single source of truth for the n8n-reviewer skill. To customize:

- **Add a rule**: Add it under the appropriate section with a severity level (Critical/Warning/Info)
- **Remove a rule**: Delete or comment out the rule (prefix with `<!-- -->`)
- **Change severity**: Move the rule to a different severity section
- **Add node naming patterns**: Add a row to the naming conventions table
- **Change thresholds**: Edit the numbers (e.g., change "50 lines" for ATOMIC to "100 lines" if your team prefers)

The skill will enforce whatever is in this file and nothing more.
