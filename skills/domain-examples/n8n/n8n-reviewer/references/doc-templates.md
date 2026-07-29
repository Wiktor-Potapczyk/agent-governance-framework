# Documentation Templates

## Sticky Note Template (In-Workflow)

This sticky note gets added to the workflow JSON as a new node. Position it at the top-left of the canvas, before all other nodes.

### Template

```
# {Workflow Name}

**Purpose:** {One sentence describing what this workflow does and why}

**Inputs:**
- Trigger: {trigger type — webhook, schedule, manual, sub-workflow call}
- {List each input field/parameter with a brief description}

**Outputs:**
- {What gets written, sent, or returned — e.g., "Updates Google Sheet rows with validation results"}
- {List each output destination}

**Flow:**
1. {Step 1 — e.g., "Receives contact list from parent workflow"}
2. {Step 2 — e.g., "Marks contacts as 'In Process' on the sheet"}
3. {Step 3}
...

**Docs:** {Confluence link — leave as placeholder if not known: "[Confluence Documentation](https://confluence.example.com/display/TEAM/workflow-name)"}
```

### Sticky Note Node JSON

When inserting this into the workflow, use this structure:

```json
{
  "parameters": {
    "content": "# Workflow Name\n\n**Purpose:** ...\n\n**Inputs:**\n- ...\n\n**Outputs:**\n- ...\n\n**Flow:**\n1. ...\n\n**Docs:** [Confluence](https://...)",
    "height": 300,
    "width": 800,
    "color": 5
  },
  "type": "n8n-nodes-base.stickyNote",
  "position": [-1600, -600],
  "typeVersion": 1,
  "id": "<generate-a-uuid>",
  "name": "Workflow Summary"
}
```

**Positioning:** Find the minimum x-position among all nodes in the workflow and subtract 200. Find the minimum y-position and subtract 400. This places the summary sticky note above and to the left of the workflow start.

**Color values:** 1=blue, 2=green, 3=yellow, 4=red, 5=purple, 6=teal, 7=orange. Use 5 (purple) for the summary sticky note to distinguish it from section sticky notes.

---

## Confluence Documentation Template — Markdown Format

```markdown
# {Workflow Name}

## Table of Contents
- [Overview](#overview)
- [Workflow Details](#workflow-details)
- [Technical Specifications](#technical-specifications)
- [Logic & Processing](#logic--processing)
- [Error Handling](#error-handling)
- [Dependencies](#dependencies)
- [Additional Resources](#additional-resources)

---

## Overview

### Purpose
{2-3 sentences explaining what this workflow does, in plain language that a non-technical stakeholder could understand.}

### Business Value
{Why does this workflow exist? What manual process does it replace? What business outcome does it enable?}

### Quick Facts
| Property | Value |
|----------|-------|
| **Workflow ID** | {n8n workflow ID if known} |
| **Status** | Active / Draft / Deprecated |
| **Owner** | {Team or person responsible} |
| **Created** | {Date} |
| **Last Modified** | {Date} |
| **Environment** | Production / Staging / Development |
| **Execution Frequency** | {e.g., "On-demand via parent workflow", "Every 15 minutes", "Webhook-triggered"} |

---

## Workflow Details

### Trigger
{How the workflow starts — webhook, schedule, manual trigger, called by another workflow, etc. Include any trigger configuration details.}

### Inputs
| Input | Type | Source | Description |
|-------|------|--------|-------------|
| {field name} | {string/array/object} | {where it comes from} | {what it contains} |

### Outputs
| Output | Destination | Description |
|--------|-------------|-------------|
| {what is produced} | {where it goes — Google Sheet, API, webhook response, etc.} | {details} |

---

## Technical Specifications

### External Services & APIs
| Service | Purpose | Node(s) | Authentication |
|---------|---------|---------|----------------|
| {e.g., Google Sheets} | {what it's used for} | {which nodes use it} | {credential name} |
| {e.g., Apify} | {what it's used for} | {which nodes} | {credential name} |

### Credentials Used
| Credential Name | Service | Type | Notes |
|----------------|---------|------|-------|
| {e.g., "My Dev Client"} | Google Sheets | OAuth2 | {any relevant notes} |

### Data Sources & Destinations
| Type | Name/Location | Access Pattern |
|------|--------------|----------------|
| Source | {e.g., Google Sheet "Prospects"} | Read rows by filter |
| Destination | {e.g., Same Google Sheet} | Update rows by row_number |

---

## Logic & Processing

### Flow Diagram (Text)
```
{Trigger} → {Step 1} → {Step 2} → {Decision Point}
                                         ├── {Path A} → {Result A}
                                         └── {Path B} → {Result B}
```

### Step-by-Step Processing

#### Step 1: {Step Name}
- **Node(s):** {node names involved}
- **What happens:** {describe the processing}
- **Input:** {what data comes in}
- **Output:** {what data goes out}

#### Step 2: {Step Name}
...

### Decision Points
| Decision | Condition | Path A | Path B |
|----------|-----------|--------|--------|
| {e.g., "Response Type"} | {what's being checked} | {where items go} | {where errors go} |

---

## Error Handling

### Error Strategies
| Scenario | Handling | Node(s) |
|----------|----------|---------|
| {e.g., "API scrape fails"} | {what happens — retry, stop, skip, etc.} | {which nodes} |

### Retry Configuration
| Node | Retry on Fail | Wait Between Tries | Max Retries |
|------|--------------|--------------------|-----------|
| {node name} | Yes/No | {ms} | {count} |

### Known Failure Modes
- {List any known scenarios where the workflow can fail and what to do about them}

---

## Dependencies

### Upstream
- {What triggers or feeds this workflow — e.g., "Parent workflow: Contact Enrichment Pipeline"}

### Downstream
- {What depends on this workflow's output — e.g., "Outreach sequences use the validated contact data"}

### External Dependencies
- {Third-party services that must be available — e.g., "Apify LinkedIn scraper must be active"}
- {Rate limits or quotas to be aware of}

---

## Additional Resources

- **n8n Workflow Link:** {link to workflow in n8n editor}
- **Related Workflows:** {links to connected workflows}
- **Runbook:** {link to operational runbook if one exists}
- **Slack Channel:** {where to ask questions}
- **Last Reviewed:** {date of last documentation review}
```

---

## Confluence Documentation Template — XHTML Storage Format

Use this format when the user wants to upload directly to Confluence via the API. This is Confluence's native storage format.

```xml
<ac:structured-macro ac:name="toc">
  <ac:parameter ac:name="maxLevel">3</ac:parameter>
</ac:structured-macro>

<h1>{Workflow Name}</h1>

<h2>Overview</h2>

<h3>Purpose</h3>
<p>{2-3 sentences explaining what this workflow does.}</p>

<h3>Business Value</h3>
<p>{Why does this workflow exist?}</p>

<h3>Quick Facts</h3>
<table>
  <tbody>
    <tr><th>Property</th><th>Value</th></tr>
    <tr><td>Workflow ID</td><td>{id}</td></tr>
    <tr><td>Status</td><td>{status}</td></tr>
    <tr><td>Owner</td><td>{owner}</td></tr>
    <tr><td>Created</td><td>{date}</td></tr>
    <tr><td>Last Modified</td><td>{date}</td></tr>
    <tr><td>Environment</td><td>{env}</td></tr>
    <tr><td>Execution Frequency</td><td>{frequency}</td></tr>
  </tbody>
</table>

<h2>Workflow Details</h2>

<h3>Trigger</h3>
<p>{Trigger description}</p>

<h3>Inputs</h3>
<table>
  <tbody>
    <tr><th>Input</th><th>Type</th><th>Source</th><th>Description</th></tr>
    <tr><td>{field}</td><td>{type}</td><td>{source}</td><td>{description}</td></tr>
  </tbody>
</table>

<h3>Outputs</h3>
<table>
  <tbody>
    <tr><th>Output</th><th>Destination</th><th>Description</th></tr>
    <tr><td>{output}</td><td>{destination}</td><td>{description}</td></tr>
  </tbody>
</table>

<h2>Technical Specifications</h2>

<h3>External Services &amp; APIs</h3>
<table>
  <tbody>
    <tr><th>Service</th><th>Purpose</th><th>Node(s)</th><th>Authentication</th></tr>
    <tr><td>{service}</td><td>{purpose}</td><td>{nodes}</td><td>{auth}</td></tr>
  </tbody>
</table>

<h3>Credentials Used</h3>
<table>
  <tbody>
    <tr><th>Credential Name</th><th>Service</th><th>Type</th><th>Notes</th></tr>
    <tr><td>{name}</td><td>{service}</td><td>{type}</td><td>{notes}</td></tr>
  </tbody>
</table>

<h3>Data Sources &amp; Destinations</h3>
<table>
  <tbody>
    <tr><th>Type</th><th>Name/Location</th><th>Access Pattern</th></tr>
    <tr><td>{type}</td><td>{name}</td><td>{pattern}</td></tr>
  </tbody>
</table>

<h2>Logic &amp; Processing</h2>

<h3>Flow Diagram</h3>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">text</ac:parameter>
  <ac:plain-text-body><![CDATA[{text flow diagram}]]></ac:plain-text-body>
</ac:structured-macro>

<h3>Step-by-Step Processing</h3>
<h4>Step 1: {Name}</h4>
<ul>
  <li><strong>Node(s):</strong> {nodes}</li>
  <li><strong>What happens:</strong> {description}</li>
  <li><strong>Input:</strong> {input}</li>
  <li><strong>Output:</strong> {output}</li>
</ul>

<h3>Decision Points</h3>
<table>
  <tbody>
    <tr><th>Decision</th><th>Condition</th><th>Path A</th><th>Path B</th></tr>
    <tr><td>{decision}</td><td>{condition}</td><td>{path_a}</td><td>{path_b}</td></tr>
  </tbody>
</table>

<h2>Error Handling</h2>

<h3>Error Strategies</h3>
<table>
  <tbody>
    <tr><th>Scenario</th><th>Handling</th><th>Node(s)</th></tr>
    <tr><td>{scenario}</td><td>{handling}</td><td>{nodes}</td></tr>
  </tbody>
</table>

<h2>Dependencies</h2>

<h3>Upstream</h3>
<ul><li>{upstream dependency}</li></ul>

<h3>Downstream</h3>
<ul><li>{downstream dependency}</li></ul>

<h3>External Dependencies</h3>
<ul><li>{external dependency}</li></ul>

<h2>Additional Resources</h2>
<ul>
  <li><strong>n8n Workflow Link:</strong> <a href="{url}">{url}</a></li>
  <li><strong>Related Workflows:</strong> {links}</li>
  <li><strong>Last Reviewed:</strong> {date}</li>
</ul>
```

---

## Filling in the Templates

When analyzing a workflow to fill in these templates, trace the data flow from start to finish:

1. **Start at the trigger node** — identify the type (webhook, schedule, sub-workflow call) and what data it receives
2. **Follow the connections** — for each node in order, note what it does to the data
3. **Track decision points** — Switch and IF nodes create branches; document each path
4. **Identify outputs** — where does data leave the workflow? (API calls, sheet updates, webhook responses, sub-workflow returns)
5. **Catalog external services** — every node with a `credentials` object talks to an external service
6. **Note error handling** — nodes with `onError`, error output connections, or Stop and Error nodes

For the text flow diagram, use arrows and indentation to show the flow. Keep it readable — abbreviate node names if needed but make the flow clear.
