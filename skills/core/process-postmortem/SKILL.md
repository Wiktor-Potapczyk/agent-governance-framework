---
name: process-postmortem
description: Use AFTER something failed in production or testing: an n8n workflow silently dropped data, a Supabase migration broke, an automation produced wrong output, a hook misfired, a deploy regressed. Produces a dated root-cause artifact (timeline → proven root cause → contributing factors → prevention items) and feeds the prevention items back into memory/hooks. NOT a pre-ship quality gate (that's process-qa / process-pentest) and NOT a velocity retro (that's the gstack /retro skill). Triggers: postmortem, what went wrong, incident, why did X break, root cause.
disallowed-tools: [AskUserQuestion]
---

# Post-Incident Postmortem

A postmortem is **falsification applied to a failure**: the goal is the *proven* root cause, not the first plausible story. The vault's QA tiers prove absence of *found* bugs pre-ship; this skill captures what a real failure taught us *after* ship, and turns it into a durable guard so the same class can't recur silently.

`disallowed-tools: [AskUserQuestion]`: a postmortem reconstructs from evidence (logs, executions, git, files), not from interrogation. If a fact is missing, record it as an Open Question, don't block on asking.

## Use-when

- A production/test failure already happened and you need the root cause + a prevention
- An n8n execution silently failed, mis-routed, or dropped data
- A migration, deploy, hook, or automation regressed observed behavior
- A "near miss" worth capturing (it didn't break, but would have under slightly different conditions)

## Do-NOT-use-when

- Pre-ship verification of work you just built → `process-qa` (Tier 1) / `process-pentest` (Tier 2)
- Diagnosing a bug you're about to fix in the same task with no durable-learning angle → `process-analysis` Investigation mode
- Weekly velocity / commit-pattern retrospective → the gstack `/retro` skill (different artifact entirely)
- A failure with zero recoverable evidence → record a one-line "unreconstructable" note and stop; do not fabricate a timeline

## Gotchas

- **First plausible cause ≠ root cause.** Apply 5-why: keep asking "why" until the answer is a process/design fact you can guard, not a surface symptom. Stop when the next "why" leaves the system's control boundary.
- **Separate PROVEN from HYPOTHESIS.** Every causal claim is tagged `[proven: <evidence>]` or `[hypothesis: <what would confirm it>]`. A postmortem built on unverified causes is a story, not an RCA: the same trap process-qa guards against.
- **The silent-failure check is mandatory.** For every failure, ask: did anything show green while being wrong? Silent success is the documented worst failure class for autonomous agents. Name where the green-but-wrong signal was.
- **No blame, no fix-in-place.** A postmortem reports; it does not fix. Prevention items become tickets/hooks/memos via the normal channels: fixing inline contaminates the analysis and violates No-Unsolicited-Changes.

## Step 1: Scope

Write this block (plain text, not fenced):

POSTMORTEM SCOPE
Incident: [one sentence: what failed, where, when]
Detection: [how it surfaced: who/what noticed, and how late]
Evidence available: [n8n execution IDs, governance-log entries, git SHAs, files, screenshots]
Blast radius: [what was affected: data, downstream workflows, user-visible output]
Output path: Projects/[Name]/work/YYYY-MM-DD-postmortem-[incident].md

If there is no recoverable evidence, say so and stop: do not reconstruct a timeline from assumption.

## Step 2: Reconstruct the timeline (evidence-bound)

Build a chronological timeline from real artifacts. For n8n: fetch the live execution (`n8n_executions`/`n8n_get_workflow`) and inspect every node's in/out: a green status over a silent-failure substrate is not success. For code/hooks: git log + the governance-log.jsonl entries + the relevant file state at the time. Each timeline row cites its evidence. Tag inferred steps `[hypothesis]`.

## Step 3: Root cause (5-why, falsification-gated)

Run the 5-why from the symptom down to a guardable process/design fact. At each level tag `[proven: evidence]` or `[hypothesis: what would confirm]`. The root cause is the deepest PROVEN level whose correction would have prevented the incident. If the chain bottoms out in a hypothesis, say so: an unproven root cause is a finding to verify, not a conclusion.

Then the **silent-failure check** (mandatory): where did something report success/green while being wrong? If nowhere, state that explicitly.

## Step 4: Contributing factors

List the conditions that made the failure possible or worse but weren't the root cause (missing guard, absent test, stale doc, over-broad permission, a known-but-unmitigated pattern). Cross-reference any matching `reference_*` memo or wiki page: if this failure matches a documented pattern that wasn't applied, that gap IS a contributing factor.

## Step 5: Prevention items (the payload)

For each prevention, state: what guard, which layer (hook / skill / memo / test / doc), and reversibility. Classify each:
- **Reversible + additive** (new memo, new test, new non-blocking hook) → propose for immediate build via the normal process skill.
- **Doctrine / blocking / destructive** (CLAUDE.md edit, blocking hook, asset removal) → stage for the owner; do not auto-apply.

A postmortem with zero prevention items is incomplete: if the failure was truly unpreventable, say *why* (and that itself is a finding).

## Step 6: Output + feedback loop

Write the artifact to the Step-1 path with frontmatter (`date`, `tags: [project/<name>, analysis, audit]`, `status: active`) and an inbound wikilink from STATE.md or the project MOC (stewardship rule). Then:
- If a durable lesson emerged → write/update a `finding_*` or `reference_*` memory file + MEMORY.md pointer + memory-log entry.
- If a prevention is rule-shaped (tool-specific, regex-detectable, enforce-at-runtime) → self-invoke `/hookify` per the CLAUDE.md self-invoke doctrine.
- Surface the owner-gated prevention items explicitly; do not silently apply them.

## Output format

POSTMORTEM REPORT
Incident: [one line]
Root cause: [the deepest proven level] [proven: evidence]
Silent-failure: [where green-but-wrong appeared, or "none: failed loudly"]
Contributing factors: [bulleted]
Prevention: reversible (proposed): [bulleted, with layer]
Prevention: owner-gated (staged): [bulleted, with why gated]
Open questions: [unresolved / unreconstructable items]
Untested: [what this analysis could not establish: mandatory, mirrors the QA Untested-Surface rule]
