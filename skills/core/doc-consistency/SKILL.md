---
name: doc-consistency
description: Use when maintaining a documentation set: after a code/config change that any doc describes, before publishing a repo, or whenever asked to "update the docs" / "keep docs in sync" / "maintain the documentation". Catches the failure where one doc is updated and a sibling is left stale, shipping an internal contradiction (e.g. README says "87 agents", architecture.md says "51", the real on-disk count is something else). Enforces enumerating the FULL doc set first, then checks every cross-referenced value against its authoritative source, then LLM-reconciles the prose the deterministic check can't reach. NOT for writing new docs from scratch, NOT for prose-style linting, NOT for fixing a single named typo. Triggers: maintain docs, update the docs, keep docs in sync, doc drift, stale docs, docs consistency, README vs, doc set, are the docs current.
---

# Documentation Consistency

Doc drift is **the silent gap between what the system does and what the docs say**: and the most dangerous form is *cross-file*: two docs that describe the same fact differently, with no diff to flag it. A typical failure: a count/version/path is updated in `architecture.md` but `README.md` is left stale, and an internal contradiction ships. The root cause is treating the doc set piecemeal: updating the diff-adjacent doc and never enumerating the rest.

This skill makes the **full doc set** the unit of work, pins each doc's claimed values to an **authoritative source**, runs a **cheap deterministic contradiction check** before any reasoning, then **LLM-reconciles** the semantic drift a value-grep can't catch.

Classic linters (markdownlint, link-check) catch only *mechanical* drift. The drift this targets is *semantic and cross-file*. Only the doc-coupling manifest + reconciliation step catches it; pure linters never would.

## Use-when

- A code/config change landed that any doc describes (counts, versions, file lists, command names, paths)
- Before publishing or pushing a repo whose docs face an audience
- The user says "update the docs", "maintain the documentation", "keep the docs in sync", "are the docs current"
- A doc set spans multiple files that cross-reference the same facts (README + CHANGELOG + architecture + INDEX + docs/** etc.)

## Do-NOT-use-when

- Writing a brand-new doc from scratch with no existing set to stay consistent with
- Prose-quality / style / slop linting
- A single named typo or one-field edit
- Generating reference docs from code where they literally cannot drift (single-source-of-truth pattern): no consistency pass needed

## Gotchas

- **Enumerate-first is the whole point.** The failure mode is updating the doc in front of you and missing its siblings. Step 1 is a hard gate: list EVERY doc in scope before touching one.
- **UTF-8 on all reads.** `open()` on Windows defaults to a locale codec, not UTF-8: the deterministic checker opens every file with `encoding='utf-8'`. Keep that if you extend it.
- **The deterministic check is exact-value only.** It catches "doc A says 4, source says 5". It does NOT catch "doc A describes the flow one way, doc B another": that is Step 4's job.
- **No-Unsolicited-Changes still applies.** Step 4 PROPOSES fixes and gets the go before editing, unless the invocation was an explicit fix mode ("update the docs" is a fix mandate; "check the docs" is not).
- **Authoritative source must be real.** A manifest entry whose `expect` points at a countable thing on disk (file count, line-match count) is verifiable; a `literal` value is only as good as the human who set it. Prefer countable sources.
- **Pure-stdlib, no pip.** The checker imports only stdlib (json, re, os, glob, argparse). Keep it that way.

## Steps

### Step 1: ENUMERATE THE FULL DOC SET FIRST (hard gate)

**Do not read, check, or edit any doc until you have listed every doc in scope.** Do not rely on the git diff to tell you which docs matter: glob the set. Glob at minimum: `README*`, `CHANGELOG*`, `**/architecture*`, `**/INDEX*`, `INSTALL*`, `docs/**/*.md`, any `*-README.md`. The unit of work is the WHOLE set: never just the doc adjacent to the change. Skipping this reproduces the exact bug the skill exists to prevent.

### Step 2: DOC-COUPLING MANIFEST

Build or read `.doc-consistency.json` at the repo root (JSON, not YAML: the checker is stdlib-only and stdlib has no YAML parser). It maps each cross-referenced value to its **authoritative source** and every doc that **asserts** it. See `example.doc-consistency.json` for a worked example.

```json
{
  "root": ".",
  "checks": [
    {
      "id": "core-skills-count",
      "expect": { "count_files": {"dir": "skills/core", "glob": "*/SKILL.md"} },
      "asserted_in": [
        {"file": "README.md", "pattern": "(\\d+) core skills"},
        {"file": "docs/architecture.md", "pattern": "Core skills \\| (\\d+)"}
      ]
    }
  ]
}
```

`expect` is one of: `count_files` (live count of files matching a glob in a dir), `count_lines` (lines in a file matching a regex), or `literal` (a hand-set source-of-truth string). Each `asserted_in` regex has exactly one capture group = the value that doc claims. For each fact appearing in 2+ docs (or in a doc + on disk), add a check.

### Step 3: DETERMINISTIC PRE-CHECK

```bash
python skills/core/doc-consistency/check_doc_consistency.py .doc-consistency.json
```

Prints `[OK]` / `[MISMATCH]` / `[ERROR]` lines. Exit 0 = consistent; exit 1 = mismatch/error. Catches exact-value contradictions for near-zero cost. Fix mismatches (or propose them if not in fix-mandate mode: see Step 4), then re-run until clean.

### Step 4: LLM SEMANTIC RECONCILIATION

For each doc in the Step-1 set, reconcile against its authoritative source AND its sibling docs for drift the deterministic check cannot catch: the same fact described differently in prose, a renamed component still called by its old name, a removed feature still documented, an ordering/flow described inconsistently across two docs.

When two docs disagree at the prose level and the manifest has no `literal` entry for the fact, resolve in this order: (1) live system state if checkable, (2) the more recently modified file, (3) flag for a human decision with both versions quoted. Never silently pick one version as authoritative.

Report findings. PROPOSE fixes and get the go before editing: UNLESS the invocation was an explicit fix mandate ("update the docs", "keep them in sync"), in which case apply and report what changed. When the invocation phrase is ambiguous, default to propose-only mode. Always state which docs were reconciled and which were left untouched.

### Step 5: Quality check

- [ ] Step 1 enumerated the FULL set (not just diff-adjacent docs)
- [ ] Manifest covers every fact asserted in 2+ docs or in a doc + on disk
- [ ] Deterministic checker run and exits 0 (or every mismatch resolved/justified)
- [ ] Semantic reconciliation covered every doc in scope; untouched docs named
- [ ] Fixes followed propose-unless-fix-mandate
- [ ] Manifest committed alongside the docs so the next pass is cheap

## Notes

- The manifest is the durable artifact: commit it. The next maintenance pass starts at Step 3, not from scratch.
- This skill checks consistency; it does not author. New content comes from elsewhere; this keeps the set non-contradictory.
- A doc set with no manifest is checkable but not enforceable: write the manifest the first time you touch the set.
