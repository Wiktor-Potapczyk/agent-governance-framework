# Detailed Report Template

Use this template when the report will be consumed by an AI agent implementing fixes, or when a full audit trail is needed. Invoke with `--detailed` flag.

## Template

```markdown
# n8n Review: {Workflow Name}

**Workflow ID:** {id} | **Nodes:** {count} | **Active:** {true/false} | **Date:** {today}

**Count Verification:**
| Metric | Count |
|---|---|
| Total nodes | {N} |
| External-service nodes | {N} |
| Unique credential IDs | {N} |
| Code nodes | {N} |
| Sticky notes | {N} |
| Execution Data nodes | {N} |

---

### G01 — Workflow Naming: PASS / FAIL
{Findings — what doesn't match the pattern. If PASS, just say "Compliant."}
**Fix:** {what to change}

### G02 — Node Naming: PASS / FAIL
**Default names found:** {count}
| Current Name | Node Type | Suggested Name | Severity |
|-------------|-----------|---------------|----------|

### G03 — Visual Chain: PASS / FAIL
{Findings from position data — disconnected nodes, flow direction issues}
{Flag "Visual inspection recommended" for crossing/spacing checks}

### G04 — Sticky Notes: PASS / FAIL
- Summary note: present / missing
- Section notes: {count found} / {count recommended}
- Warning notes: {assessment}
- Default-named notes: {count}

### G05 — Execution Data: PASS / FAIL
- Start node: present / missing
- Error path nodes: {count} / {count needed}
- Standard keys used: {list}
{Findings}

### G06 — Error Handling: PASS / FAIL
**External nodes without error handling:** {count}/{total}
| Node | Issue | Severity | Fix |
|------|-------|----------|-----|

**Global error workflow:** configured / not configured
**Retry config issues:** {findings}

### G07 — Security: PASS / FAIL
| Severity | Node | Issue | Fix |
|----------|------|-------|-----|

### G08 — Credentials Naming: PASS / FAIL
| Current Name | Matches Pattern? | Suggested Name |
|-------------|-----------------|---------------|

### G09 — Credentials Management: PASS / FAIL
{Findings — secrets in node params, unused credentials visible in JSON}

---

## Summary

| Area | Status | Critical | High | Medium | Low |
|------|--------|----------|------|--------|-----|
| G01 Workflow Naming | | | | | |
| G02 Node Naming | | | | | |
| G03 Visual Chain | | | | | |
| G04 Sticky Notes | | | | | |
| G05 Execution Data | | | | | |
| G06 Error Handling | | | | | |
| G07 Security | | | | | |
| G08 Credentials Naming | | | | | |
| G09 Credentials Management | | | | | |
| **Total** | | | | | |

## Priority Fixes

1. {Highest priority — CRITICAL items first}
2. {Next}
3. ...

## Notable Bugs

{Runtime bugs, malformed configurations, or logic errors found during review that don't fit a specific guideline but affect workflow correctness. Include: which node, what's wrong, expected runtime impact.}
```
