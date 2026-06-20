---
name: process-ingest
description: "Use when a raw source document (Inbox/, Clippings/) needs to be integrated into the LLM-Wiki. Reads the source, computes SHA hash, writes summary wiki page with source citation, updates 3-10 related wiki pages, updates index.md + log.md. Auto-triggered by inbox-auto-ingest hook on Inbox writes; also manually invokable. Implements Karpathy LLM-Wiki Ingest operation with 3-layer fabrication mitigation."
---

# process-ingest: Karpathy LLM-Wiki Ingest Operation

You have been routed here because a raw source needs to be integrated into the LLM-Wiki layer. Read the source, write a wiki summary, cross-reference related pages, update index.md + log.md.

## Use-when

- A new file landed in `Inbox/` and the `inbox-auto-ingest` hook triggered ingest
- User explicitly invokes `process-ingest` on a Clippings/ or Inbox/ file
- A raw artifact (research result, work file) needs wiki promotion

## Do-NOT-use-when

- Source is already in wiki layer (file tagged `#wiki`): that's an update, not an ingest; use Edit directly
- Source is a Daily Note: those stay in raw layer; do not promote
- Source is a `.claude/` infra file: those are schema layer
- Quick one-line edits: direct Edit is fine; ingest is for synthesis work

## Gotchas

- **Fabrication risk is the primary failure mode for this skill**: documented LLM-fabrication incidents in production vaults make the 3-layer mitigation in Steps 4-6 non-negotiable.
- **Crypto hash is the truth layer**: Layer 1's "did you read the source" claim is verifiable only via SHA hash of bytes you actually read via Read tool. No shortcuts.
- **No write to wiki without `source:` field.** Hook `wiki-citation-check` blocks any wiki Write missing `source:` + valid hash. If you bypass and write anyway, the write fails.
- **Bootstrap mode is active until 10 ratified entries exist.** Until then, every wiki page you create gets `wiki_status: bootstrap` frontmatter and is surfaced for owner review before treating it as ground truth.

## Steps

### Step 1: Read raw source

Use the Read tool on the source file. If file is >8K tokens, read in sections (Read with offset/limit). Capture:
- Title (from frontmatter or H1)
- Key claims (max 10, verbatim phrases not paraphrases)
- Entities mentioned (people, products, tools, projects)
- Tags implied (per workspace CLAUDE.md canonical tag list)

### Step 2: Compute SHA-256 hash of raw source (M2 crypto binding)

Compute SHA-256 of the source file's raw bytes using the Python available on your system:

```bash
python -c "import hashlib; print(hashlib.sha256(open(r'PATH','rb').read()).hexdigest())"
```

Record this hash. It will be committed to the wiki page's `source:` field. This is the cryptographic commitment to "the source contained this exact byte stream when I wrote this claim."

**Exception: `type: generated`:** if the source is an auto-generated file (a script output such as `registry.json`), set `type: generated` in the `source:` entry and OMIT the `sha256` field. SHA-pinning a regenerated file produces perpetual false `SOURCE_DRIFT` on every regeneration; all enforcement layers skip the SHA gate for `type: generated` sources while still verifying path existence. See CLAUDE.md `type: generated` exemption.

**Exception: `type: schema-doctrine`:** if the source is a *hand-edited doctrine* file revised more than ~weekly (e.g. a governance constitution), set `type: schema-doctrine`, OMIT `sha256`, and ALWAYS include `anchor` (the cited heading). The SHA gate is skipped (the file is too volatile to pin) but enforcement REQUIRES the `anchor` heading to exist in the source: stricter than `type: generated` because hand-edited doctrine is mis-citable. See CLAUDE.md `type: schema-doctrine` exemption.

### Step 3: Search wiki for related pages

If qmd MCP server is loaded (check via tool listing for `qmd` server):
- Call `qmd query` with the top 3-5 key nouns from raw doc
- Get 3-10 top results

If qmd not available (fallback):
- Read `Resources/KB/index.md`
- Find pages where tag overlap or title-keyword match is high
- Pick 3-10 candidates

Identify the 3-10 wiki pages that SHOULD update based on this new source.

### Step 4: Hard citation gate (M2 Layer 1)

**For each claim you plan to encode in a wiki page write, you MUST locate the supporting verbatim text in the raw source via Read tool result.**

If text not found in source after exhaustive search:
- Do NOT write the claim
- Halt with `CITATION_NOT_FOUND` for that claim
- Either drop the claim OR find a different source that supports it

Do NOT write wiki content from memory. Every factual claim must be anchored to a Read tool result from a `source:` document.

**Distinguish:**
- **Direct factual claim** ("X uses Y", "Project foo has feature bar") → REQUIRES verbatim anchor in source
- **Synthesis/inference** ("X and Y suggest Z pattern") → REQUIRES at least one `source:` entry but anchor heading optional; lint will flag with WEAK_CITATION if content-match fails

### Step 5: Write wiki page (with source: field)

Write the wiki page to `Resources/KB/` or `Notes/` (with `#wiki` tag). Frontmatter:

```yaml
---
date: YYYY-MM-DD
tags: [wiki, <topic>, <project/X>]
status: "#active"
wiki_status: bootstrap   # all v1 pages start bootstrap; owner promotes to ratified
source:
  - path: "Clippings/some-article.md"
    type: clipping        # clipping | work-artifact | daily-note | external | inbox-item | generated | schema-doctrine
    anchor: "## Section Title"
    sha256: "<hash from Step 2>"
    ingested_at: "<ISO 8601 timestamp>"
ingested_by: process-ingest-v1
---
```

Page body:
- Open with 1-3 line summary
- Numbered or bulleted key claims (each with citation reference if multiple sources)
- Cross-links to 1-3 related wiki pages via `[[wikilink]]`
- Section "## Related" with `[[moc-X]]` MOC backlink

### Step 6: Update related wiki pages

For each of the 3-10 related pages identified in Step 3:
- Read the page
- Determine if this new source adds, contradicts, or extends existing content
- Make targeted edits via Edit tool
- Append the new source entry to its `source:` field (including SHA hash and ingested_at)
- Add a wikilink to the new page in a "Related" or similar section

**CRITICAL: SHA recommit on edit:**

When you Edit a related wiki page, you change its bytes. The hook's SOURCE_DRIFT check on subsequent reads will fire because every existing `source[].sha256` was committed against the file's bytes at original ingest time, NOT against the now-edited bytes. To prevent SOURCE_DRIFT noise on every later operation:

1. Do NOT update `source[].sha256` for entries you didn't touch: those reference the original raw doc, not this wiki page itself; their hashes still match their raw sources.
2. After editing the wiki page, the wiki page's OWN bytes have changed. Other wiki pages that cite THIS edited page (rare: wiki pages rarely cite each other in source:) would see SOURCE_DRIFT. Track that case via Lint's Pass A.
3. For `source:` entries you ADD in Step 6 (the new ingest's source), compute fresh SHA against the new source's current bytes: same protocol as Step 5.
4. The wiki page's own modification of the `source:` array is OK; the hook validates `source:` bytes against cited file bytes, NOT against wiki page bytes.

Said simply: `source:` hashes refer to RAW source files (Clippings/, work/), not to the wiki page itself. Editing a wiki page does not invalidate its own `source:` hashes: those hashes are about the cited raw doc's content. They become invalid only if the cited raw doc itself changes.

### Step 7: Update index.md

Update `Resources/KB/index.md`:
- Find row for the new wiki page (match on Path column)
- If exists: update Last Updated + Source Count via Edit
- If not exists: append new row in alphabetical insertion

Update index.md's own `last_modified` frontmatter.

### Step 8: Append log.md entry

Append to `log.md` (workspace root) using the schema from your workspace CLAUDE.md `## Karpathy LLM-Wiki Architecture` section:

```markdown
## YYYY-MM-DD HH:MM: Ingest: INGEST-NNN

**Operation:** Ingest
**Source:** <workspace-relative path to raw doc>
**Agent:** process-ingest-v1
**Duration:** <seconds>
**Wiki pages updated:** <comma-separated paths>
**Index updated:** yes
**Citations written:** <integer count>
**Lint findings:** N/A
**Status:** SUCCESS | PARTIAL
**Notes:** <optional one-liner; mention any CITATION_NOT_FOUND claims that were dropped>

---
```

NNN is the next sequential number: grep `^## .*: Ingest: INGEST-` log.md to find the max + 1.

NEVER edit an existing log entry. Append only. The `wiki-citation-check` hook blocks edits to existing entries.

### Step 9: Move raw source from Inbox/ (if applicable)

If source was in `Inbox/`, move it per your workspace CLAUDE.md Inbox-processing rules (Rules 1-5):
1. **Task** → `Projects/[X]/task_plan.md` extraction + move
2. **Idea** → tag #idea + Project/Areas
3. **Meeting note** → date+attendees+actions + Project
4. **Research** → tag #research + Resources/ or Project
5. **Personal** → Areas/Personal/

If source was in Clippings/ or already in destination, no move needed. Clippings/ files STAY in Clippings/ (immutable raw layer).

## Token budget

Target: ≤10K tokens per ingest (raw read + 3-10 wiki page reads + writes + log/index updates combined).

If estimate exceeds 10K before starting: emit `BUDGET_EXCEEDED` warning, ask user before proceeding. Rate-limit windows constrain per-ingest budget.

## Rules

- **Never write wiki content without a `source:` field with valid SHA hash.** Hook blocks the write; the write FAILS. No bypassing.
- **Never write wiki content from memory.** Every claim anchors to a Read tool result.
- **All new wiki pages start `wiki_status: bootstrap`.** Promoted to `ratified` only by owner review.
- **All wiki pages get `#wiki` tag**: this is the disambiguator between LLM-owned and human-owned notes in Notes/.
- **log.md is append-only.** Never edit existing entries.
- **index.md must be updated before log.md**: log entry references index state at time of writing.
- **Honor existing Inbox processing rules (CLAUDE.md Rules 1-5)**: extend, don't replace.
- **If qmd MCP not loaded, fall back to index.md scan + tag overlap**: don't fail-fast.

## Output

End the operation with a short structured report:

```
INGEST REPORT
Source: <path>
SHA: <hex>
Wiki pages created: <count>
Wiki pages updated: <count>
Citations written: <count>
CITATION_NOT_FOUND drops: <count or 0>
log.md entry: INGEST-NNN
index.md updated: yes/no
Status: SUCCESS | PARTIAL | FAILED
```
