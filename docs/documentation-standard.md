# The Documentation Standard

**One followable standard for how this framework documents itself** — the repository and its docs — so the docs stay orderly, complete, and current. Derived from established industry frameworks (Diátaxis, arc42/C4, ADR/MADR, Keep a Changelog, SemVer, standard-readme, docs-as-code) and adapted to the place those frameworks leave a gap: documenting a markdown/skill/hook/agent-heavy repository rather than a conventional code library.

This is the format. When you document anything here, you follow these rules.

**Scope.** This standard governs the published repository in full. It is **process doctrine, not a runtime hook** — deliberately NOT enforced by a blocking hook (that approach was tried and rejected as over-engineering). Its single enforcement point is the **documentation-sync push gate** (§7): the §8 checklist is the *what*, and the doc-consistency + Definition-of-Done pass at push time is the *when-checked*. Nothing self-executes on every keystroke — and that is intentional.

---

## 0. The governing decisions (why this shape)

1. **Diátaxis governs *where* a doc goes.** Every doc is exactly one of four modes — Tutorial, How-to, Reference, Explanation — never mixed in one file. (diataxis.fr)
2. **The attributes-table is the unit of Reference.** Because the artifacts here are hooks/skills/agents (configurable entities), not functions, each is documented with a uniform field table — the dominant convention for config-heavy repos (Ansible modules, Terraform variables, CrewAI concepts). Narrative prose is NOT the reference form.
3. **The "why" lives in ONE decision store, never inline in a reference table.** Decision-from-description separation (Nygard; arc42 §9). See §4 for the single-authority rule that avoids competing "why" corpora.
4. **Single-source-of-truth is absolute.** A fact lives in exactly one doc; everything else links to it. No copied counts, no restated rules. (Google style guide; Write the Docs)
5. **Docs change in the same commit as the thing they describe.** Incorrect docs are worse than missing docs. (Write the Docs; Google)
6. **Completeness is the bar: every functionality AND every logical path.** "Mentioned" is not "documented." Within a doc's scope, cover concepts in full or not at all — a partial map misleads. (Write the Docs)

---

## 1. The required document set

`.github/` is the home for repo-meta; root stays clean for the front-door docs.

| Document | Mode | Purpose | Canonical path | Required? |
|---|---|---|---|---|
| `README.md` | mixed entry | Front door: what it is, install, usage, links out | root | **Always** |
| `CHANGELOG.md` | reference | Human-readable release history (Keep a Changelog) | root | **Always** |
| `docs/architecture.md` | explanation | The layer model + how the pieces fit | `docs/` | **Always** |
| `docs/reference/` | reference | Attributes-table pages — per hook/skill/agent class | `docs/reference/` | If non-trivial |
| `docs/adr/NNNN-*.md` | decision log | Immutable MADR decision records | `docs/adr/` | As decisions are made |
| `docs/concepts/` | explanation | Why the architecture is shaped this way; mental models | `docs/concepts/` | If non-trivial |
| `INSTALL.md` | how-to | Setup steps | root | **Always** |
| `CONTRIBUTING.md` | how-to | How to contribute + the rules (incl. this standard) | root or `.github/` | If public |
| `LICENSE` | — | Legal terms | root | **Always** |

**README section order** (standard-readme): Title → one-line description (<120 chars) → TOC (if >100 lines) → Install → Usage → Architecture summary (link to architecture.md) → Contributing → License (last). Cognitive funnel: broad first, narrow last.

---

## 2. Diátaxis routing (where does this doc go?)

Decide the mode before you write. Pick the ONE that fits; if it feels like two, it is two docs.

| If the doc… | …it is | …and lives in |
|---|---|---|
| teaches a newcomer by doing, start-to-finish | **Tutorial** | `docs/tutorials/` |
| helps someone accomplish a specific goal | **How-to** | `docs/how-to/` |
| describes what a thing IS (fields, behavior, contract) | **Reference** | `docs/reference/` |
| explains WHY — rationale, model, tradeoffs | **Explanation** | `docs/concepts/` or an ADR |

**The no-mixing rule:** a reference page does not contain a tutorial; a how-to does not digress into architectural rationale (link to the concept/ADR instead). **Clarification:** a one-line `Rationale` field or a `Use-when` pointer *inside* a reference attributes-table is NOT mode-mixing — those are cross-reference fields (a link + a sentence), not the prose explanation/tutorial sections the rule forbids. A reference table may *point at* the why; it must not *contain* the multi-paragraph why.

---

## 3. The artifact Reference schema (the heart of this standard)

Every **hook**, **skill**, and **agent** gets a Reference entry with a uniform attributes table. This is how a config/markdown repo documents "every functionality and every logical path." No published cross-tool standard exists for this — this IS the standard here.

### 3a. Hook reference template

```
### <hook-filename.py>
| Field | Value |
|---|---|
| Event | PreToolUse / PostToolUse / Stop / SubagentStop / SessionStart / … |
| Matcher | tool(s) / pattern it fires on |
| Registered in | the settings file, or unregistered-by-design |
| Action | block / warn / log / inject-context |
| Inputs | what it reads (stdin JSON fields, files, env) |
| Outputs / Side-effects | what it writes, blocks, or emits |
| Logical paths | each branch: condition → outcome |
| Failure mode | behavior on bad input (fail-open vs fail-closed) |
| Rationale | one line + link to the decision record that motivated it |
```

The **Logical paths** row enumerates each branch. **The code is the source of truth, not this row** — so the row cites the hook's `test_<hook>.py` where one exists (the test file is the verified, executable branch enumeration). Maintain it under the §6.2 same-commit rule. **Honest limitation:** a hand-maintained branch table that has gone stale is *worse* than an absent one, because a reader trusts it. If you cannot keep the enumeration current, write "see `test_<hook>.py` for the authoritative branch set" + a one-line summary rather than a fake-complete table.

### 3b. Skill reference template

```
### <skill-name>
| Field | Value |
|---|---|
| Type | process / routing / utility / domain |
| Frontmatter | name + description (required); trigger phrases |
| Use-when / Do-NOT-use-when | the routing contract |
| Dispatches | agents/skills it routes to |
| Steps | the numbered procedure (or link if long) |
| Outputs | artifacts/blocks it must produce |
| Enforced by | the hook that verifies it ran (if any) |
```

### 3c. Agent reference template

```
### <agent-name>
| Field | Value |
|---|---|
| Domain | what it specializes in |
| Tools | tool surface (and any restriction) |
| Dispatched by | which skill(s) route to it; mandatory vs advisory |
| Model | default model |
| Inputs | what its dispatch prompt must contain |
| Output contract | the structured block/report it returns |
| Known failure modes | documented risks |
```

**Control-flow across artifacts** (which hook fires in what order, which skill dispatches which agent) is documented ONCE in an Explanation page (`docs/concepts/execution-model.md`) with a flow diagram — NOT repeated in each artifact's reference entry (single-source-of-truth).

---

### 3d. Workflow script reference template (added 2026-06-11)

Workflow scripts are the fourth artifact class. Their reference entries (see `docs/reference/workflows.md`) extend the skill template (3b) with four fields: **Invocation** (Workflow tool, absolute `scriptPath`), **Args contract** (required/optional fields + the HALT behavior on missing input), **Phases** (the meta-declared sequence with the dispatches inside each), and **Fallback** (the prose SKILL.md path and when it applies).

## 4. The decision log (ADRs)

Every significant, costly, or hard-to-reverse choice → one MADR file in `docs/adr/`, numbered sequentially. Append-only: a reversed decision gets a NEW superseding ADR; the old one's Status flips to "Superseded by ADR-NNNN" but is never deleted.

**MADR fields:** Status / Date frontmatter → Context and Problem Statement → Decision Drivers → Considered Options → Decision Outcome (incl. Consequences, positive AND negative) → Pros and Cons of the Options.

**Single-authority rule (avoids competing "why" stores).** Where a project keeps decision rationale in more than one place (e.g. an inline spec rule, a decision-memo corpus, and this ADR log), authority is assigned, not shared: the spec states the rule in force; the decision-memo corpus is the source of truth for *why*; a repo ADR is a **published, derived** view that adds no new decision content. When they disagree, the live system wins over a published snapshot. This keeps "why" single-sourced.

---

## 5. CHANGELOG

`CHANGELOG.md` follows Keep a Changelog 1.1.0:
- An `## [Unreleased]` block at the top accumulates changes as they land.
- Categories, only these, in this order: **Added / Changed / Deprecated / Removed / Fixed / Security**.
- Latest entry first; every entry **dated**; written for humans.

Every artifact added or changed produces a CHANGELOG line in the same commit.

**On SemVer (deliberately optional):** with no version-pinned downstream consumers, MAJOR.MINOR.PATCH numbers would be labeling overhead with zero consumer-protection value. We use **date-based** entries. Flag a behavioral break with `**BREAKING:**` in the entry. If the repo ever gains pinned consumers, adopt SemVer then.

---

## 6. Maintainability rules (non-negotiable)

1. **Single-source-of-truth.** A count/rule/fact appears in ONE place; everything else links. Counts live in the registry + the doc-consistency manifest — docs cite, never restate them.
2. **Freshness = same-commit.** Change an artifact → update its reference entry + CHANGELOG in the same commit.
3. **Completeness within scope.** Every functionality present as an artifact AND covered in reference; every logical path traceable. No partial coverage.
4. **Mode separation.** Never mix Diátaxis modes in one file (§2).
5. **ARID, not DRY.** Accept *some* repetition for readability — don't force a reader through three links to assemble one answer.
6. **Ownership.** `CODEOWNERS` (or the INDEX) names who maintains each doc area. Unowned docs rot.
7. **Audience-first.** Each doc names its reader (newcomer / contributor / operator) and is written for that one reader.

---

## 7. Enforcement (docs-as-code) — and its honest limits

The automated layers verify *consistency* of what exists; they do NOT verify *completeness* of what the standard requires. Completeness is a human-process gate. Do not over-trust the green checkmark.

| Layer | Checks | Does NOT check |
|---|---|---|
| **doc-consistency checker** (`.doc-consistency.json` manifest) | pinned counts match reality, no stale paths/names, cross-doc facts agree; exit 0 before push | whether a required reference entry / logical-paths row / ADR was actually *written* |
| **INDEX link-integrity** | every internal Markdown link target resolves on disk | whether the linked doc is complete |
| **markdownlint** (candidate, not yet wired) | heading hierarchy, list consistency | semantics |
| **documentation Definition-of-Done** (human-process) | artifacts land, README checked, every functionality+path documented, fast-forward | only as reliable as the operator running it — this is the completeness gate, NOT machine-enforced |

The honest picture: completeness rests on the DoD being run, which is process discipline. That is an accepted limit. The mitigation is that the DoD is invoked on every repository update, and this standard's §8 checklist is its content.

---

## 8. The followable checklist (use this every time)

**When you ADD an artifact** (hook/skill/agent/workflow):
- [ ] Create its Reference entry from §3 (all fields; logical-paths row cites the test)
- [ ] If it embodies a non-obvious choice → write an ADR (§4)
- [ ] Add a CHANGELOG `Added` line (§5)
- [ ] Update the INDEX with a one-line pointer
- [ ] If it changes execution order → update `docs/concepts/execution-model.md`
- [ ] Run doc-consistency → 0 mismatch

**When you CHANGE an artifact:**
- [ ] Update its Reference entry in the SAME commit (esp. logical-paths)
- [ ] CHANGELOG `Changed`/`Fixed`/`Deprecated` line
- [ ] If it reverses a prior decision → new superseding ADR
- [ ] doc-consistency → 0

**When you REMOVE an artifact:**
- [ ] Delete its Reference entry; CHANGELOG `Removed` line
- [ ] Fix or remove inbound links (no orphans)
- [ ] doc-consistency → 0

**When you write a NEW doc:**
- [ ] Decide the Diátaxis mode FIRST (§2); put it in the right folder
- [ ] One mode only — no mixing
- [ ] Name its audience in the first lines
- [ ] Link, don't restate, any fact owned elsewhere

---

## 9. What this standard deliberately does NOT do

- It does not adopt C4 diagrams as mandatory (a single architecture.md layer diagram suffices; C4 is available if a container/component view is ever needed).
- It does not require full arc42 (12 sections is overkill; we take §1 goals, §5 building blocks = the reference set, §6 runtime = the execution-model concept doc, §9 decisions = the ADR log, §12 glossary).
- It does not mandate a doc-site generator (MkDocs/Docusaurus) — docs are read in-repo as Markdown. A future increment if the doc set outgrows flat files.

These omissions are choices, not gaps — recorded so a future reader does not "fix" them by accident.

---

## Sources

Diátaxis (diataxis.fr) · arc42 (arc42.org) · C4 model (c4model.com) · ADR/Nygard (cognitect.com, 2011) · MADR (adr.github.io/madr) · Keep a Changelog (keepachangelog.com) · Semantic Versioning (semver.org) · standard-readme (github.com/RichardLitt/standard-readme) · Art of README (github.com/hackergrrl/art-of-readme) · docs-as-code (writethedocs.org) · Google developer documentation style guide (developers.google.com/style).
