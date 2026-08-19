---
date: 2026-08-11
tags: [hooks, spec, reference]
status: active
---

# Plain-Language Rules (PL-1 to PL-10)

This file is the spec of record for the plain-language documentation layer. CLAUDE.md carries only a short pointer to it. The base layer (CLAUDE.md Communication Style) governs conversational replies alone; this layer governs documentation surfaces alone. The two never compete on one surface.

Origin: [[2026-08-10-plain-language-standard-plan]] (plan of record, v2, owner-approved 2026-08-11) and [[2026-08-10-caveman-postmortem]] (Mechanism A, Mechanism B, MM1). Build record: [[2026-08-11-plain-language-stage1-build]].

Licensing note, restated from the plan of record: every wordlist below is vault-authored from scratch. Nothing is copied from any ASD source. This is a provenance claim checkable by authorship record only, since nobody on this project has read the actual ASD word list.

## The rules

### PL-1: Sentence length cap

- **Statement**: In documentation prose, keep sentences at 25 words or fewer. In numbered procedural steps, 20 words or fewer. Both numbers are calibration starting values, tunable in Stage 3, not spec constants.
- **Positive**: "Run the indexer. Then read the last 20 lines of the log."
- **Negative**: "In order to make sure that the indexer has completed successfully it is recommended that the log file be examined carefully for any errors that may have occurred at any point during the run."
- **Tier**: T1 (split on sentence-terminal punctuation, count words).
- **Provenance**: STE research sections 1b and 4 (thresholds flagged search-only); owner reframe "not too verbose" (2026-08-10).

### PL-2: One action per procedural step

- **Statement**: A numbered procedural step states one action. Split chained actions into separate steps.
- **Positive**: "1. Stop the workflow. 2. Export the JSON. 3. Check the credentials."
- **Negative**: "1. Stop the workflow and then export the JSON and check the credentials before continuing."
- **Tier**: T1 advisory heuristic only (flags " and then " and multi-imperative chains inside numbered steps). Full compliance is T3 judgment. Warns, never blocks.
- **Provenance**: STE research section 1c (procedural text is the target genre); owner reframe "concrete" (2026-08-10).

### PL-3: Active voice with a named actor

- **Statement**: In documentation prose, prefer active voice and name the actor. A sentence that hides who acts hides where a failure lives.
- **Positive**: "The hook blocks the write and logs the event."
- **Negative**: "The write is blocked and the event is logged."
- **Tier**: T1 as a low-confidence prefilter only (be-verb followed by a word ending in -ed), advisory, never block. T2 proper detection is gated on the WDAC import test (Stage 5).
- **Provenance**: STE research section 4 (Tier 1 crude heuristic, Tier 2 proper detection) and section 3 prior art.

### PL-4: Concrete values over vague quantifiers

- **Statement**: Where a concrete value exists, state it: the filename, the count, the command, the date. Do not substitute vague quantifiers.
- **Positive**: "Three hooks failed: `a.py`, `b.py`, `c.py`."
- **Negative**: "Several hooks appear to have various issues."
- **Tier**: T1 advisory. Vault-authored vague-quantifier list: "several", "various", "numerous", "a number of", "appropriate", "as needed", "some issues". Whether a concrete value actually exists is T3.
- **Provenance**: owner reframe, verbatim "concrete" (2026-08-10); caveman postmortem method gate.

### PL-5: Everyday words

- **Statement**: Prefer the common word. Enforced against a small vault-authored substitution list: utilize -> use, commence -> start, terminate -> stop, endeavor -> try, facilitate -> help, leverage (as a verb) -> use, prior to -> before, subsequent to -> after, in order to -> to, sufficient -> enough, demonstrate -> show.
- **Positive**: "Use the API before you start the export."
- **Negative**: "Utilize the API prior to commencing the export."
- **Tier**: T1 (substitution-list regex).
- **Provenance**: owner reframe "easy language" (2026-08-10); STE research section 2c HOLD (wordlists must be vault-authored, never ASD-derived).

### PL-6: No noun stacks

- **Statement**: No more than three nouns in a row. Break the stack with a preposition or restructure.
- **Positive**: "the measurement plan for the warn-rate calibration window"
- **Negative**: "the hook warn rate calibration window measurement plan"
- **Tier**: T2 only. NOT built in Stage 1; deferred to Stage 5 behind the WDAC import test, and advisory even then. The checker reports a structural zero for this rule until then.
- **Provenance**: STE research section 1b and section 4 Tier 2; section 3 prior art.

### PL-7: No filler on documentation surfaces

- **Statement**: The base layer's prohibited list (filler, hedging, throat-clearing) extends from conversational replies to documentation surfaces. Flagged phrases (vault-authored list): "it should be noted that", "it is important to note", "essentially", "basically", "as mentioned above", "needless to say".
- **Positive**: "The guard fails open on internal error."
- **Negative**: "It should be noted that the guard essentially fails open whenever an internal error happens to occur."
- **Tier**: T1 (phrase list, same scan-and-flag loop as `em-dash-guard.py`).
- **Provenance**: CLAUDE.md Communication Style Prohibited list (the base layer being extended); caveman postmortem Object 2 (COMP-2 and COMP-4, 2026-04-14).

### PL-8: Expand abbreviations at first use

- **Statement**: An abbreviation or internal code gets its expansion at first use in each document. No internal queue codes in prose.
- **Positive**: "WDAC (Windows Defender Application Control) blocks the import. Later mentions may say WDAC."
- **Negative**: "The fix is gated on WDAC and the VC redist." (as the first and only mention, expansion nowhere)
- **Tier**: T1 advisory (all-caps token with no prior parenthetical expansion in the same document; known-noisy, warn only). Full correctness is T3.
- **Provenance**: `feedback_no_abbreviations_in_prose.md` and `feedback_no_internal_queue_codes_in_prose.md`; owner reframe "easy language" (2026-08-10).

### PL-9: Destructive-action exception (the MM1 carve-out)

- **Statement**: For security warnings, destructive-action confirmations, and multi-step sequences where fragment ordering risks misunderstanding, terseness reverts to full explicit prose: complete sentences, articles included, no fragment compression, explicit ordering words. This exemption is TOTAL. Inside MM1-marked content, no PL rule, including PL-1, may produce a length or verbosity finding. PL-1 becomes authoring guidance only there.
- **Positive**: "This command permanently deletes the production table. It cannot be undone. Confirm that a backup exists before you run it."
- **Negative**: "Deletes prod table. No undo. Confirm backup."
- **Tier**: T3 for the register judgment; T1-implementable as a checker exemption via the structural marker below. This rule is primarily a constraint on the checker, not a scan. The checker reports a structural zero for this rule.
- **Provenance**: caveman postmortem Object 3 (MM1: identified 2026-05-08 after adversarial catch M-MISS-1, scoped XS, never built, "the one genuinely lost item"). This rule closes that four-month-old loss.

### PL-10: Provenance per rule

- **Statement**: Every rule in this standard, and every future addition or amendment to it, carries an inline citation to its originating decision or research file. A rule without provenance does not enter enforcement.
- **Positive**: this file: every PL block above and below ends with a Provenance line naming its origin.
- **Negative**: the caveman-lite Communication Style section, whose origin pointer died when its owning track archived (postmortem Mechanism A).
- **Tier**: T1 (lint: every `### PL-` block in this file must contain a `**Provenance**:` line; implemented as a doctrine-drift pytest in `test_plain_language_check.py`).
- **Provenance**: caveman postmortem, Mechanism A verdict (identity decoupling).

## MM1 marker convention (Stage 1 decision, 2026-08-11)

Chosen syntax: the HTML-comment pair `<!-- MM1 -->` ... `<!-- /MM1 -->` around the exempt block.

Rationale: block-delimited (one regex strips it), invisible in rendered Markdown, cannot collide with bold-label prose, and survives copy-paste into other documents. The rejected candidate (`**MM1:**` labeled line) marks only a point, not a span, and renders visibly.

MM1 trigger conditions (content qualifies when any holds):

1. It is a security warning (credential exposure, NDA surface, data-loss consequence).
2. It is a destructive-action confirmation touching the canonical Gate-1 irreversible surface.
3. It is a multi-step sequence where steps depend on prior steps and fragment ordering risks misunderstanding.

Edge behavior, implemented exactly by `strip_noise()` in `plain_language_check.py`:

| Case | Behavior |
|---|---|
| Closed block (`<!-- MM1 -->` ... `<!-- /MM1 -->`) | Content between markers is stripped before scanning. Zero findings of any PL rule inside, PL-1 included. |
| Unclosed `<!-- MM1 -->` (no matching close) | Exempts to end of document AND the checker emits a marker-hygiene advisory naming the unclosed marker. The advisory is not a PL finding and does not enter `per_rule_finding_counts`. |
| Nested markers | Treated as one span to the outermost close (depth-tracked: each inner open increments, each close decrements; the span ends when depth returns to zero). |
| Unmarked MM1-class content | Receives ordinary findings, including length findings. This is the accepted residual risk named in the plan of record, visible in the baseline report, not hidden. |

The marker, not the content, drives the exemption. The checker never infers MM1 status from meaning.

## Per-surface applicability matrix

Mechanical enforcement exists ONLY on the three hooked path-glob rows. On every other surface the rules, and the MM1 carve-out, are doctrine and review only.

| Surface | PL rules applied | Mode |
|---|---|---|
| `Projects/*/work/` build records, runbooks, specs (excludes `work/backups/`) | PL-1 to PL-8, PL-10 | Enforced (warn-only in Stage 2; per-rule block is future Stage 4) |
| `Resources/KB/` wiki pages | PL-1 to PL-8, PL-10 | Enforced (staged, as above) |
| `framework-repo/` README and `docs/` | PL-1 to PL-8, PL-10 | Enforced (staged, as above) |
| Conversational session replies | None | Exempt. Base layer (CLAUDE.md Communication Style) governs alone |
| Structured blocks (QA REPORT, PM CHECKPOINT, PENTEST, classifier) | None | Exempt (base-layer carve-out) |
| Code blocks, inline code, tables, frontmatter | None | Exempt (`strip_noise()`) |
| Code comments | None | Exempt (technical shorthand register) |
| Teams/Slack message drafts | PL-4, PL-5, PL-7 | Advisory by doctrine only, never block, no hook |
| `STATE.md`, `task_plan.md` | None | Exempt (status registers, not prose deliverables) |

The MM1 carve-out is cross-cutting: it applies on EVERY surface whenever content matches the trigger conditions. On non-hooked surfaces it is an authoring principle, not a mechanical guarantee.

## Enforcement contract

- **Hook**: `.claude/hooks/plain-language-guard.py`, PostToolUse on Write and Edit, path-scoped to the three enforced surfaces above. Advisory-first: it warns on findings and never blocks.
- **Per-write JSONL log**: for EVERY in-scope write, findings or none, the hook appends exactly one record to `.claude/hooks/aggregates/plain-language-warnings.jsonl` with fields `{ts, session, path, per_rule_finding_counts, total_findings}`. `per_rule_finding_counts` carries all ten PL keys with zeros included. One record per invocation, never per finding: the calibration denominator is the line count.
- **Blocks ship OFF**: the block-flip machinery exists in code (`BLOCK_ENABLED_RULES`), ships EMPTY, and no rule may enter it before Stage 4. Flip criteria per rule (future Stage 4 material): warn rate at or below 10 percent over at least 14 days AND at least 50 in-scope writes, a 20-sample false-positive audit with at most 2 false positives, and explicit owner sign-off.
- **Checker**: `.claude/hooks/plain_language_check.py`, importable module plus CLI lint mode; `.claude/hooks/test_plain_language_check.py` is its test suite.
- **Overlap verdict** (Stage 1 discovery gate, 2026-08-11): DISJOINT from `prose-slop-check.py`. Wordlists share zero entries (scripted set intersection); both warn-only; prose-slop warns only past its 2-distinct/3-total thresholds. Both hooks stand, cross-referenced in their headers.

## Guards (postmortem-derived, built alongside Stage 1)

- **Guard A**: `.claude/hooks/claude-md-provenance-check.py`. Warn-only PostToolUse hook scoped to vault-root CLAUDE.md: a rule-shaped change without an inline origin citation gets a one-line warning (Mechanism A countermeasure).
- **Guard B**: `.claude/hooks/deferral-resurface.py`. Standalone sweep (`--project Projects/<Name>`) that finds deferral-class markers (Tier 3, MEDIUM, DEFER, HOLD, unchecked Future Work items, REPORT-ONLY lines) and writes a proposal file to the project's `work/`; it edits nothing else (Mechanism B countermeasure). A warn-only close advisor mode fires when a project file flips to `status: done` or `status: archived`, reminding the closer to run the sweep.
