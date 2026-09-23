---
name: doc-consistency
description: Use when maintaining a documentation set — after a code/config change that any doc describes, before publishing a repo, or whenever asked to "update the docs" / "keep docs in sync" / "maintain the documentation". Catches the failure where one doc is updated and a sibling is left stale, shipping an internal contradiction (e.g. README says "87 agents", architecture.md says "51", the real on-disk count is something else). Enforces enumerating the FULL doc set first, then checks every cross-referenced value against its authoritative source, then LLM-reconciles the prose the deterministic check can't reach. NOT for writing new docs from scratch (that's content-marketer), NOT for prose-style linting (that's prose-slop-check), NOT for fixing a single named typo (that's a Quick edit). Triggers — maintain docs, update the docs, keep docs in sync, doc drift, stale docs, docs consistency, README vs, doc set, are the docs current.
---

# Documentation Consistency

Doc drift is **the silent gap between what the system does and what the docs say** — and the most dangerous form is *cross-file*: two docs that describe the same fact differently, with no diff to flag it. The failure this skill exists for: counts/versions/paths were updated in `architecture.md` but `README.md` was left stale, and an internal contradiction shipped to a public repo. The root cause was treating the doc set piecemeal — updating the diff-adjacent doc and never enumerating the rest.

This skill makes the **full doc set** the unit of work, pins each doc's claimed values to an **authoritative source**, runs a **cheap deterministic contradiction check** before any reasoning, then **LLM-reconciles** the semantic drift a value-grep can't catch.

Classic linters (markdownlint, link-check) catch only *mechanical* drift. The drift we actually hit is *semantic and cross-file*. Only the doc-coupling manifest + reconciliation step catches it; pure linters never would.

## Use-when

- A code/config change landed that any doc describes (counts, versions, file lists, command names, paths)
- Before publishing or pushing a repo whose docs face an audience
- The user says "update the docs", "maintain the documentation", "keep the docs in sync", "are the docs current"
- A doc set spans multiple files that cross-reference the same facts (README + CHANGELOG + architecture + INDEX + docs/** + CLAUDE.md)

## Do-NOT-use-when

- Writing a brand-new doc from scratch with no existing set to stay consistent with → `content-marketer`
- Prose-quality / style / slop linting → `prose-slop-check` hook (already runs on Write|Edit)
- A single named typo or one-field edit → Quick inline edit (the classifier fast-path)
- Generating reference docs from code where they literally cannot drift → just generate them (single-source-of-truth pattern); no consistency pass needed

## Gotchas

- **Enumerate-first is the whole point.** The failure mode is updating the doc in front of you and missing its siblings. Step 1 is a hard gate: list EVERY doc in scope before touching one. Skipping it reproduces the exact bug this skill was built for ([[feedback_maintain_docs_consider_all]]).
- **Windows / cp1252.** `open()` on Windows defaults to a locale codec, not UTF-8 — the deterministic checker opens every file with `encoding='utf-8'`. If you extend it, keep that ([[reference_python_windows_open_defaults_to_locale_not_utf8]]).
- **The deterministic check is exact-value only.** It catches "doc A says 4, source says 5". It does NOT catch "doc A describes the flow one way, doc B another" — that is Step 4's job. Do not expect the script to find semantic drift.
- **No-Unsolicited-Changes still applies.** Step 4 PROPOSES fixes and gets the go before editing, unless the user explicitly invoked a fix mode ("update the docs" is a fix mandate; "check the docs" is not).
- **Authoritative source must be real.** A manifest entry whose `expect` points at a countable thing on disk (file count, line-match count) is verifiable; a `literal` value is only as good as the human who set it. Prefer countable sources over literals.
- **Pure-stdlib, no pip.** The checker imports only stdlib (json, re, os, glob, argparse) — WDAC blocks unsigned binaries and the vault has no guarantee of pip deps. Keep it that way.

## Steps

### Step 1 — ENUMERATE THE FULL DOC SET FIRST (hard gate)

**HARD GATE. Do not read, check, or edit any doc until you have output the complete DOC-SET SCOPE block below.** Do not rely on conversation context or the git diff to tell you which docs matter — run the globs. If you cannot enumerate the full set because the project root is ambiguous, stop and ask. Proceeding without the enumeration reproduces the exact bug this skill was built to prevent.

    DOC-SET SCOPE
    Repo/project: [name]
    Docs in scope: [every .md that documents the system — README, CHANGELOG, architecture, INDEX, docs/**, INSTALL, CLAUDE.md, hooks-README, ...]
    Trigger: [what changed / why this pass is running]

Glob at minimum: `README*`, `CHANGELOG*`, `**/architecture*`, `**/INDEX*`, `INSTALL*`, `docs/**/*.md`, `CLAUDE.md`, any `*-README.md`. The unit of work is the WHOLE set — never just the doc adjacent to the change.

If a doc set has >~20 files or per-doc checks would benefit from parallel isolation, see **Seam B** (escalate to `/workflows`).

### Step 2 — DOC-COUPLING MANIFEST

Build or read the manifest: `.doc-consistency.json` at the repo root (JSON, not YAML — the deterministic checker is stdlib-only and stdlib has no YAML parser). The manifest is the enumeration artifact AND the touch-X-update-Y coupling: it maps each cross-referenced value to its **authoritative source** and every doc that **asserts** it.

Schema (see `example.doc-consistency.json` for a worked example against this vault's AGF repo):

```json
{
  "root": ".",
  "checks": [
    {
      "id": "core-skills-count",
      "expect": { "count_files": {"dir": "skills/core", "glob": "*"} },
      "asserted_in": [
        {"file": "README.md", "pattern": "(\\d+) core skills"},
        {"file": "docs/architecture.md", "pattern": "Core skills \\| (\\d+)"}
      ]
    }
  ]
}
```

`expect` is the authoritative value, one of: `count_files` (live count of files matching a glob in a dir), `count_lines` (lines in a file matching a regex), or `literal` (a hand-set source-of-truth string — use sparingly). Each `asserted_in` regex has exactly one capture group = the value that doc claims. If no manifest exists, author one from the Step-1 enumeration: for each fact that appears in 2+ docs (or in a doc + on disk), add a check.

### Step 3 — DETERMINISTIC PRE-CHECK (cheap, before any LLM reasoning)

Run the helper before reasoning about anything:

```bash
python .claude/skills/doc-consistency/check_doc_consistency.py path/to/.doc-consistency.json
```

It reads the manifest, computes each authoritative value, compares every doc's claimed value against it, and prints `[OK]` / `[MISMATCH]` / `[ERROR]` lines. Exit 0 = all consistent; exit 1 = at least one mismatch or error. This catches the exact-value contradictions (the README-vs-architecture class) for near-zero cost. Fix mismatches it finds (or propose them if not in fix-mandate mode — see Step 4), then re-run until clean.

**Optional add-on (not required):** `markdown-link-check` (pure-Node) for dead links. Mechanical only — secondary to the value check. Do not hard-require it.

### Step 4 — LLM SEMANTIC RECONCILIATION

For each doc in the Step-1 set, reconcile against its authoritative source AND its sibling docs for drift the deterministic check cannot catch: the same fact described differently in prose, a renamed component still called by its old name, a removed feature still documented, an ordering/flow described inconsistently across two docs.

When two docs disagree at the prose level and the manifest has no `literal` entry for the fact, resolve in this order: (1) live system state if checkable, (2) the more recently modified file, (3) flag for user decision with both versions quoted. Never silently pick one version as authoritative.

Report findings. Per No-Unsolicited-Changes: PROPOSE the fixes, get the go, then edit — UNLESS the invocation was an explicit fix mandate ("update the docs", "keep them in sync"), in which case apply and report what changed. When the invocation phrase is ambiguous (e.g. "maintain the docs", "doc drift", "are the docs current"), default to propose-only mode and state "Invocation interpreted as check-only — confirm to apply fixes." Always state which docs were reconciled and which were left untouched (the untested-surface discipline).

**Seam A (optional) — qmd candidate-finder.** For a large prose corpus that is qmd-indexed (`agr-kb`), `mcp__qmd__query` can surface doc-pairs that discuss the same subsystem so you reconcile the right pairs instead of every N×N combination. Retrieval only — qmd ranks docs, it cannot detect contradictions. Use it to *find* candidate pairs, not to *judge* them.

**Seam B (optional) — /workflows escalation at large N.** When the doc set is large enough that per-doc semantic checks save material wall-clock by running in parallel, escalate to a `/workflows` script: enumerate → parallel per-doc claims-extraction → central reconcile (the dedup/contradiction-merge needs all claims at once — a barrier) → parallel fix. Documented as *when to escalate*, not built here. The single-pass skill is correct for the common case (one repo, ~3–15 docs).

### Step 5 — Quality check

- [ ] Step 1 enumerated the FULL set (not just diff-adjacent docs) — the hard gate
- [ ] Manifest covers every fact asserted in 2+ docs or in a doc + on disk
- [ ] Deterministic checker run and exits 0 (or every mismatch is resolved/justified)
- [ ] Semantic reconciliation covered every doc in scope; untouched docs named
- [ ] Fixes followed No-Unsolicited-Changes (proposed unless fix-mandate)
- [ ] Manifest committed alongside the docs so the next pass is cheap

## Notes

- The manifest is the durable artifact — commit it. The next maintenance pass starts from Step 3 (run the checker), not from scratch.
- This skill checks consistency; it does not author. New content comes from `content-marketer`; this keeps the set non-contradictory.
- A doc set with no manifest is checkable but not enforceable — write the manifest the first time you touch the set.
