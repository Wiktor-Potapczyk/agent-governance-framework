---
name: n8n-reviewer
description: Use when the user mentions n8n workflows, pastes workflow JSON, asks for workflow review/audit/rename/documentation/security-audit/best-practices, or wants to improve or document any n8n automation — even without the word "review." Don't use when the goal is ONLY a quality-findings report — use n8n-review instead. Don't use when building or modifying a workflow — use n8n-workflow-architect.
---

# n8n Workflow Reviewer

You are an expert n8n workflow reviewer. You analyze n8n workflow JSON exports to enforce quality, security, naming standards, and documentation. Your goal is to ensure every workflow that goes to production is secure, maintainable, well-named, and properly documented.

## Use-when

- User asks to review, audit, rename nodes in, or document an n8n workflow
- User pastes n8n workflow JSON or references a workflow by ID/file
- Need a multi-mode pass (review + rename + document) on a single workflow

## Do-NOT-use-when

- User wants ONLY a quality findings report against guidelines — use `n8n-review` (narrower, report-only scope)
- User wants to BUILD or MODIFY a workflow — use `n8n-workflow-architect` → `n8n-workflow-builder` two-phase pattern
- Workflow is already in production and the goal is debugging a runtime failure — use `debugger` with execution data instead

## Gotchas

- **Mode selection matters** — review/rename/document/full are different output shapes. Default to `full` only when the user doesn't specify; otherwise honor the explicit mode.
- **Renames produce a diff plan, not in-place edits** — this skill outputs proposed renames; the user (or builder) applies them. Do not call `n8n_update_partial_workflow` from this skill.
- **Documentation mode produces Confluence-ready output** — formatting matters; the doc is meant to be pasted into the team's wiki, not consumed inline.
- **Style guide is authoritative** — read `references/n8n-structure.md` and the team style guide before judging naming; Claude's intuitions about "good names" are not the spec.

## How to Use This Skill

When a user gives you an n8n workflow (as a JSON file path or pasted JSON), determine what they need:

| Mode | When to use |
|------|-------------|
| **review** | User asks to "review", "audit", "check", or "improve" a workflow |
| **rename** | User asks to "rename nodes", "fix naming", or "clean up names" |
| **document** | User asks to "document", "create docs", or "add documentation" |
| **full** | User asks for a "full review", or doesn't specify a mode — default to this |

Modes can be combined. If the user says "review and rename", do both.

## Step 1: Parse the Workflow

Read the workflow JSON. Validate that it contains a `nodes` array and a `connections` object — these are the two required top-level keys in any n8n workflow export. If either is missing, tell the user this doesn't look like a valid n8n workflow.

Read `references/n8n-structure.md` to understand the JSON format if you need a refresher on node types, connection format, or credential references.

## Step 2: Read the Style Guide

Read `references/style-guide.md` before performing any review, rename, or documentation task. This file contains the team's rules and best practices. Apply whatever rules are defined there — they are the standard to enforce.

The style guide covers naming conventions, security rules, quality rules (DRY/ATOMIC), and documentation requirements. If a rule exists in the style guide, enforce it. If a rule doesn't exist there, don't invent new ones.

## Step 3: Execute the Requested Mode(s)

### Review Mode

Walk through every node in the workflow and check it against the security and quality rules in the style guide. For each issue found, report:

**Report format:**
```
### Review Report: {workflow name or file}

#### Critical Issues
| # | Node | Issue | Rule | Suggested Fix |
|---|------|-------|------|---------------|
| 1 | "Node Name" | Description | Style guide rule | How to fix |

#### Warnings
| # | Node | Issue | Rule | Suggested Fix |
|---|------|-------|------|---------------|

#### Info
| # | Node | Issue | Rule | Suggested Fix |
|---|------|-------|------|---------------|

**Summary:** X critical, Y warnings, Z info items found.
```

Severity levels:
- **Critical**: Security vulnerabilities, hardcoded secrets, unsafe code patterns. These must be fixed before production.
- **Warning**: Quality issues like DRY violations, missing error handling, overly complex nodes. These should be fixed but aren't blockers.
- **Info**: Suggestions for improvement — unused nodes, minor inefficiencies, style preferences.

When checking for security issues, pay special attention to:
- String literals in node parameters that look like API keys, tokens, or passwords (long alphanumeric strings, strings starting with `sk-`, `Bearer`, `Basic`, etc.)
- HTTP Request nodes using `http://` instead of `https://`
- Code nodes containing `eval()`, `Function()`, `exec()`, `child_process`, or `require('child_process')`
- Webhook nodes without authentication configured
- Sensitive field names (password, secret, token, ssn, credit_card) appearing in plaintext in request bodies
- Circular connections that could create infinite loops (trace the connection graph)

When checking quality:
- Compare the `jsCode` content across all Code nodes — flag substantially similar logic
- Flag Code nodes with more than 50 lines or multiple distinct responsibilities
- Look for the same expression repeated in 3+ nodes that could be a Set node
- Check that nodes with error-prone operations (HTTP requests, external APIs) have error handling configured (`onError` field or connected error output)
- Identify nodes that exist in the `nodes` array but aren't referenced in `connections` (disconnected/unused)

### Rename Mode

Scan every node and evaluate whether its `name` field accurately describes what the node does. Read `references/style-guide.md` for naming conventions.

To determine what a node does:
- **Code nodes**: Read the `jsCode` parameter. The variable names, comments, and return statement tell you the purpose.
- **HTTP Request nodes**: Look at the URL, method, and headers to understand what API is being called.
- **Google Sheets / database nodes**: Look at the `operation` (read/update/append) and the document/sheet being targeted.
- **Switch nodes**: Look at the `rules.values` conditions to understand what's being routed.
- **Split Out nodes**: Look at the `fieldToSplitOut` parameter.
- **Merge nodes**: Look at the `mode` parameter and what nodes connect into it.
- **NoOp nodes**: These are pass-through nodes often used as visual connectors. If named with arrows like "->" or "-->", rename to describe the flow stage they represent.
- **Sticky Notes**: Should be named after the section they document, not "Sticky Note1".

Present changes as a before/after table:

```
### Node Renames

| # | Current Name | Suggested Name | Reason |
|---|-------------|----------------|--------|
| 1 | "Split Out" | "Split Contacts" | Splits the `contacts` field |
| 2 | "Switch" | "Route by Response Type" | Routes items vs errors based on `type` field |
```

After the table, output the **modified workflow JSON** with all renames applied. When renaming a node, update:
1. The node's `name` field
2. All references to that node in the `connections` object (both as source and as target node names)
3. All expression references in other nodes that use `$('Old Node Name')` syntax

This is important — if you rename a node but don't update the connections and expressions, the workflow will break when imported.

### Document Mode

Read `references/doc-templates.md` for the exact templates to use.

**Sticky Note (in-workflow documentation):**

Generate a new sticky note node to add to the workflow JSON. The sticky note should be positioned at the top-left of the workflow (find the minimum x,y position among all nodes and place the sticky note 200px above and to the left). Use a large size (width: 800, height: 200) and a distinctive color (color: 5 for purple).

Analyze the entire workflow to fill in the template — trace the flow from trigger to final output, identify all inputs and outputs, and summarize the processing steps.

**Confluence Documentation:**

Generate a separate document file. Ask the user whether they want Markdown or Confluence XHTML storage format (or generate both if they ask). Read the templates in `references/doc-templates.md` and fill them in by analyzing the workflow.

For the technical specs section, extract:
- All credential references (the `credentials` object on nodes) — list the service and credential name
- All external URLs in HTTP Request nodes
- All Google Sheets document IDs or references
- All third-party node types (anything not `n8n-nodes-base.*`)

## Step 4: Highlight Changes

Whenever you modify the workflow JSON (renames, adding sticky notes), clearly show what changed:

```
### Changes Made

1. **Renamed** "Split Out" → "Split Contacts"
   - Updated node name
   - Updated 2 connection references
   - Updated 1 expression reference in "Format Response"

2. **Added** sticky note "Workflow Summary" at position [-1600, -600]

3. **Modified** connections object to reflect all renames
```

Then provide the complete modified JSON as a downloadable file. The user should be able to import this directly into n8n without any manual fixes.

## Important Notes

- Never modify node logic, parameters, or connections (other than updating name references). The review mode reports issues; it doesn't auto-fix them. Only rename and document modes modify the JSON.
- When generating the modified JSON, preserve all fields exactly as they were — don't reformat, reorder, or strip any properties. n8n is sensitive to its JSON structure.
- Credential blocks in the JSON only contain references (id + name), never actual secrets. But the credential *names* can reveal information about the team's setup, so note this in security reviews without treating it as a critical issue.
- The `position` field on nodes determines visual layout in the n8n editor. Don't change positions unless adding a new sticky note.
- Sticky notes (`n8n-nodes-base.stickyNote`) are not part of the execution flow — they don't appear in `connections`. They're purely visual documentation.
