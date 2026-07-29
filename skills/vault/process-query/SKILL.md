---
name: process-query
description: Use when answering a question from the LLM-Wiki layer, synthesizing a cited answer from accumulated wiki knowledge, or user says "/process-query". Produces a cited answer from Resources/KB/ wiki pages; optionally files the answer back as a new bootstrap wiki page. Implements Karpathy LLM-Wiki Query operation with anti-fabrication gate.
---

# process-query — Karpathy LLM-Wiki Query Operation

You have been routed here to answer a question from the wiki layer. Retrieve relevant wiki pages, gate on coverage, synthesize with citations, optionally file the answer back as a new wiki page.

## Use-when

- A question the wiki layer may already answer (accumulated research, findings, reference knowledge)
- User says `/process-query` or "query the wiki"
- Want a synthesized answer with citations drawn from existing wiki pages rather than general LLM knowledge
- Deciding whether a synthesized answer is durable enough to persist as a new wiki page

## Do-NOT-use-when

- Question needs a NEW raw source integrated — that is an Ingest operation; use `process-ingest`
- Wiki-layer health check — use `process-lint`
- Answer requires live-system data not in the wiki (n8n execution state, Jira ticket details, Supabase rows) — go to the live system directly
- Single-fact grep lookup answerable in one tool call — handle inline, no skill dispatch needed

## Gotchas

- **Wiki layer is small and mostly bootstrap-status.** Coverage gaps are normal; halting with `INSUFFICIENT_WIKI_COVERAGE` is the correct outcome when the wiki cannot support the question. It is not a failure.
- **Filed-back pages are `#wiki`-tagged.** The `wiki-citation-check.py` PostToolUse hook gates every Write to a `#wiki`-tagged file: it requires `source[].path` to exist on disk and recomputes SHA-256 to compare against `source[].sha256`. Compute hashes at write time using the Read tool result; do not guess or copy old hashes.
- **`wiki-derived` source hashes drift.** A query-answer page cites other wiki pages, which are LLM-owned and mutable. When a cited wiki page is later edited, the committed SHA drifts and process-lint reports `SOURCE_DRIFT` / `STALE_PAGE` on the query-answer page. This is expected for `wiki-derived` citations, not corruption — treat as advisory.
- **Do NOT synthesize from general LLM knowledge when wiki coverage is thin.** That defects the wiki's provenance guarantee. Emit `INSUFFICIENT_WIKI_COVERAGE` instead.

## Steps

### Step 0 — Pre-flight classification

Before retrieval, classify the question. Does it require: (a) real-time state (n8n execution results, Jira ticket status, Supabase rows), OR (b) information that could only exist in raw/live data, not in accumulated wiki knowledge?

If yes to either → emit `NON_WIKI_QUESTION — route to live system` and STOP. Do not enter retrieval.

### Step 1 — Frame

Emit a QUERY SCOPE block (plain text, not fenced):

QUERY SCOPE
Question: <verbatim question>
Expected answer shape: <sentence | list | structured summary>
File-back anticipated: yes | no | unknown

### Step 2 — Retrieve

If the qmd MCP server is loaded (tool listing includes `mcp__qmd__*`):
- Call `mcp__qmd__query` with `collection: "agr-kb"` (= `Resources/KB/`), one or more `{type:'lex', query:'<key noun phrase>'}` sub-queries, and an `intent` describing the question.
- Retrieve 3-10 candidate pages. Use `multi_get` to batch-read page bodies.

If qmd MCP is unavailable (fallback):
- Read `Resources/KB/index.md` to enumerate wiki pages.
- Grep `Resources/KB/` for key nouns from the question.
- Read top 3-10 candidate pages directly via Read tool.

Collect the candidate wiki pages and read their full bodies.

### Step 3 — Coverage gate (anti-fabrication HARD GATE)

Assess: do the retrieved wiki pages contain material that substantively answers the question?

Coverage is SUFFICIENT **if and only if** at least one retrieved wiki page contains **verbatim text** (a phrase or sentence) that directly asserts the information the question asks for — text you can quote in the answer body. Paraphrase is not sufficient. Thematic adjacency ("the page is about the topic") is not sufficient. For a multi-part question, each part needs its own supporting verbatim text — parts with no support are INSUFFICIENT even if other parts are covered. When in doubt, emit `INSUFFICIENT_WIKI_COVERAGE`.

If coverage is INSUFFICIENT:
- Emit `INSUFFICIENT_WIKI_COVERAGE`
- Name specifically what is missing (which topic, which claim gap)
- If a relevant raw source exists in `Inbox/`, `Clippings/`, or `Projects/*/work/`, suggest running `process-ingest` on it first
- STOP. Do not synthesize. Do not answer from general knowledge.

This gate is the mirror of process-ingest's `CITATION_NOT_FOUND` gate. The same provenance guarantee applies.

### Step 4 — Synthesize

Write the answer. Rules:
- Every factual claim carries an inline citation `[[wiki-page-name]]` to the wiki page it is drawn from.
- No uncited claims. If a claim cannot be attributed to a retrieved wiki page, drop it.
- Synthesis inferences ("X and Y together suggest Z") are permitted but must cite both source pages.
- Length matches the expected answer shape from QUERY SCOPE.

**Pre-delivery per-claim audit (required, not optional).** Before delivering the answer, enumerate every factual claim in the draft — one bullet per claim. For each, name the wiki page it cites and quote the supporting phrase from that page. Any claim with no quotable source phrase: DROP it — do not soften it, remove it. If dropping leaves the question unanswered, return to Step 3 and emit `INSUFFICIENT_WIKI_COVERAGE`. A wikilink in prose is not proof of citation; the per-claim quote is.

### Step 5 — Decide file-back

Is the answer durable and reusable (would be valuable as standing wiki knowledge), or is it a one-off answer for this session?

- **One-off** (ephemeral, narrow, or session-specific) → deliver inline, skill done. Go to Step 7 (QUERY REPORT only).
- **Durable** (cross-session reference value, synthesizes across multiple wiki pages, fills a notable gap in the wiki) → proceed to Step 6.

Default to one-off when uncertain. Do not inflate the wiki with low-value entries.

### Step 6 — File-back

Write a new wiki page to `Resources/KB/`. Filename: `YYYY-MM-DD-query-<slug>.md`.

Frontmatter:

```yaml
---
date: YYYY-MM-DD
tags: [wiki, query-answer, <topic>]
status: active
wiki_status: bootstrap   # filed-back query pages always start bootstrap; Wiktor promotes to ratified
source:
  - path: "Resources/KB/<wiki-page-1>.md"
    type: wiki-derived
    sha256: "<SHA-256 of that wiki page's current bytes>"
    ingested_at: "<ISO 8601 timestamp>"
  - path: "Resources/KB/<wiki-page-2>.md"
    type: wiki-derived
    sha256: "<SHA-256>"
    ingested_at: "<ISO 8601 timestamp>"
authored_by: process-query-v1
---
```

**`wiki-derived` source type:** query-answer pages synthesize from other wiki pages, not from raw-layer sources. `wiki-derived` extends the CLAUDE.md `source:` enum (`clipping | work-artifact | daily-note | external | inbox-item`) for this case. Every `source:` entry for a filed-back query page uses `type: wiki-derived`.

**SHA computation:** for each cited wiki page, compute SHA-256 of its current bytes:

```bash
/c/Program\ Files/Python314/python -c "import hashlib; print(hashlib.sha256(open(r'PATH','rb').read()).hexdigest())"
```

Commit the hash to `source[].sha256`. The `wiki-citation-check.py` hook will verify this at write time.

**Pre-write hard gate:** run the SHA command for every `source:` path BEFORE writing the page. If any command fails (file not found, error), STOP — the source path is wrong; correct it before writing. Never write a placeholder or blank `sha256` — the hook rejects the write and the attempt is wasted.

Page body:
- Open with the question as an H2 or bold lead
- Synthesized answer with inline `[[wikilink]]` citations
- Section `## Sources` listing cited wiki pages
- Section `## Related` — **MANDATORY:** at least one `[[moc-X]]` backlink to a MOC covering the topic. A filed-back page with no MOC link is an orphan no review flow surfaces.

**Reciprocal wiring (mandatory).** After writing the page: Edit the MOC you linked to add the new page as a member, and Edit at least one cited wiki page to add a `[[wikilink]]` back to the new page. A page that cites others but is never cited is an island — mirror process-ingest Step 6 cross-linking.

After writing the page:

**Update `Resources/KB/index.md`:** append a new row for the filed-back page (Path, Title, wiki_status: bootstrap, source count, date).

**Append to `log.md`** at vault root:

```
## YYYY-MM-DD HH:MM — Query — QUERY-NNN

**Operation:** Query
**Question:** <verbatim question, one line>
**Agent:** process-query-v1
**Wiki pages queried:** <count>
**Wiki pages used in answer:** <count>
**Filed back:** yes — <path> | no (one-off)
**log.md entry:** QUERY-NNN
**Status:** SUCCESS | PARTIAL

---
```

NNN is the next sequential number — grep `^## .* — Query — QUERY-` in `log.md` to find max + 1. If no matching lines exist, start at `QUERY-001`. NEVER edit an existing log entry. Append only.

### Step 7 — Output

Emit a QUERY REPORT block (plain text, not fenced):

QUERY REPORT
Question: <verbatim question>
Wiki pages retrieved: <count> (<comma-separated page names>)
Coverage verdict: SUFFICIENT | INSUFFICIENT_WIKI_COVERAGE
Filed-back page: <Resources/KB/path> | not filed (one-off answer)
log.md entry: QUERY-NNN | N/A (one-off)
Status: SUCCESS | INSUFFICIENT_WIKI_COVERAGE | NON_WIKI_QUESTION | FAILED

Status values: `SUCCESS` = cited answer delivered. `INSUFFICIENT_WIKI_COVERAGE` = wiki too thin to answer (not an error — an expected outcome). `NON_WIKI_QUESTION` = Step 0 routed it to the live system. `FAILED` = operational failure (tool error, hook rejection, SHA mismatch blocking write).

## Rules

- **Anti-fabrication:** never answer from general LLM knowledge when wiki coverage is insufficient — emit `INSUFFICIENT_WIKI_COVERAGE` and stop.
- **Every synthesized claim is cited** to a specific wiki page via `[[wikilink]]`.
- **Filed-back pages are always `wiki_status: bootstrap`.** The skill never self-ratifies. Wiktor promotes to `ratified`.
- **qmd query is lex-only on this machine.** Never issue `type:'vec'` or `type:'hyde'` sub-queries.
- **`log.md` is append-only.** Never edit existing entries.
- **`source:` entries for filed-back pages use `type: wiki-derived`** — this is the correct type for wiki-page-to-wiki-page synthesis.
- **Emit QUERY SCOPE and QUERY REPORT as plain text, NOT inside triple-backtick fences.** The Stop hook strips fenced blocks.
- **SHA-256 must be computed fresh at write time** — never copy a hash from memory or a prior run.

## Output

The skill's terminal output is the QUERY REPORT block defined in Step 7 — emitted as plain text, never fenced. If the answer was filed back, the additional outputs are the new wiki page in `Resources/KB/`, its row in `index.md`, and the `QUERY-NNN` entry in `log.md`.
