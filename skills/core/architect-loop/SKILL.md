---
name: architect-loop
description: "Design and structure Ralph Loop research prompts for complex tasks. Use when the user wants to prepare a deep research loop, says 'architect a loop', 'prepare a ralph loop', 'design a loop for', or when you identify a complex task that needs independent deep research before building. Also trigger proactively when the conversation reveals multiple open questions that need exhaustive investigation from source materials."
---

Architect a Ralph Loop prompt: structure open questions into a research plan that an autonomous Claude instance can execute independently.

## When This Skill Fires

The user (or you) has identified a complex task with multiple unknowns. Instead of guessing or building prematurely, we need to exhaust all information sources first. This skill turns that fuzzy need into a structured, executable research prompt.

## Do-NOT-use-when

- Task can be answered with a single fact lookup: use Quick inline instead
- Investigation needs the current conversation's context: Ralph Loop runs in fresh isolation
- The "open questions" are pure opinion or aesthetic judgment: Ralph Loop needs source materials to consult
- All required research has already been completed in this session: review existing artifacts instead

## Gotchas

- **Anchored hypotheses leak in**: if your loop prompt contains a proposed cause or conclusion, the autonomous Claude will validate-not-investigate. Strip hypotheses from the prompt before ship.
- **Source materials must be enumerated explicitly**: vague references to "the codebase" or "our docs" produce vague returns. Cite files, URLs, or directories the loop should consult.
- **Loop output is a research artifact, not a decision**: the loop returns findings; main session synthesizes and decides. Do not let the loop body propose direct fixes: that's anchored.

## Process

### Step 1: Identify the Active Project

Find the relevant project by its `STATE.md`. A directory IS a project if and only if it directly contains `STATE.md`, and projects nest one level: search `Projects/*/STATE.md` AND `Projects/*/*/STATE.md`. Refer to a project by its full relative identity (`Personal/Finance`, `Umbrella/Module-8B`), never by the bare leaf, because leaf names are not unique. The STATE.md contains current status, locked decisions, and verified facts: these become the "What You Know" section of the loop prompt.

### Step 2: Gather Open Questions

Review the conversation to identify what's unknown or unverified. Good questions are:
- Things we assumed but never checked against source materials
- Decisions that need data before they can be made
- Edge cases or ambiguities that could derail implementation
- "How does X actually work?" questions where X is documented somewhere

Bad questions (skip these):
- Things already answered in STATE.md
- Pure opinion questions with no source materials to consult
- Questions that can only be answered by building and testing

### Step 3: Map Source Materials

Scan the project directory for available source materials:

```
Glob for: Projects/[Name]/source-data/**/*
Glob for: Projects/[Name]/work/*
Glob for: Projects/[Name]/specs/*
```

List every file that could contain answers to the open questions. Note file sizes: large files (>50KB) should be read by Explore agents, not inline.

### Step 4: Structure into PROBLEM Sections

Group related questions into numbered PROBLEM sections. Each problem should have:

1. **Question**: the core unknown, stated clearly
2. **Research tasks**: numbered steps the loop should execute (read file X, extract Y, compare Z)
3. **Produce**: specific deliverables (tables, definitions, extracted context blocks)

Aim for 3-6 problems. Fewer means the problems are too broad; more means they should be grouped.

### Step 5: Write the Loop Prompt

Save to `Projects/[Name]/work/YYYY-MM-DD-[topic]-research-loop.md` using this structure:

```markdown
---
date: YYYY-MM-DD
tags: [#project-tag, #ralph-loop, #topic]
status: #active
purpose: Ralph Loop prompt: [one-line description]
---

# Ralph Loop: [Title]

## Context
[2-3 sentences: what we're researching and why. What the output will be used for.]

**You are NOT building anything.** Your job is to read all source materials, answer every open question below, and produce a requirements document that specialist agents can work from.

**Use agents aggressively.** You have access to the Agent tool. Spawn Explore agents to read large files in parallel. Use multiple agents simultaneously when questions are independent. Do NOT read large files inline: delegate to agents.

**Re-ground periodically.** Every few iterations: and after any compaction: re-read this prompt file plus the **What You Know** and **Source Materials** sections fresh before continuing. The loop accumulates context across iterations and the compaction summary is lossy; re-inject the spec rather than trusting the compressed version.

## What You Know (verified facts: do not re-research)
[Bullet list of confirmed facts from STATE.md and conversation. This prevents the loop from wasting time re-verifying things we already know.]

## Source Materials to Read
[Organized list of files with brief descriptions. Flag large files.]

---

## PROBLEM 1: [Title]

**Question:** [Core unknown]

**Research tasks:**
1. [Specific action: read file X, extract Y]
2. [Specific action]
3. [Specific action]

**Produce:**
- [Specific deliverable]
- [Specific deliverable]

---

[Repeat for each problem]

---

## Output Format

Save your complete findings to:
`Projects/[Name]/work/YYYY-MM-DD-[topic]-requirements.md`

Structure the output as:
1. **Problem 1 findings**: [what]
2. **Problem 2 findings**: [what]
[etc.]
5. **Open questions**: anything you couldn't resolve from source materials
6. **Recommendations**: changes to our approach based on what you found

Do NOT write the spec or prompt. That's the next step, done by specialist agents after this research is reviewed.
```

### Step 6: Generate the Command

Output the ready-to-paste command:

```
/ralph-loop:ralph-loop "[Read the loop prompt file path and execute all research tasks. Use agents aggressively: spawn Explore agents in parallel for large files. Save findings to the output path. When all problems are answered and the requirements doc is saved, output RESEARCH COMPLETE.]" --max-iterations [15-25 depending on complexity] --completion-promise "RESEARCH COMPLETE"
```

Choose `--max-iterations` based on problem count and source material volume:
- 3-4 problems, moderate sources: 15
- 4-6 problems, many large files: 20
- 6+ problems or very large corpus: 25

**Hard ceiling: NEVER exceed 30** (two-gate Gate-1-adjacent, [[2026-06-15-two-gate-enforcement-spec]] Area E). The 15-25 guidance above stands for normal use; 30 is the absolute upper cap regardless of corpus size. An unbounded loop multiplies irreversible-action exposure, so the cap is a safety floor, not a tuning knob. If a corpus seems to need more than 30 iterations, decompose it into separate loops instead of raising the cap.

### Step 7: Present for Review

Tell the user:
1. Where the loop prompt file was saved
2. How many problems and source files it covers
3. The ready-to-paste command
4. Encourage them to review/edit the prompt before running

## Rules

- **Never include implementation or building tasks**: the loop researches, it doesn't build
- **Every research task must reference a specific file or data source**: no vague "investigate X"
- **"What You Know" section is critical**: it prevents the loop from re-doing work we've already verified
- **Large files (>50KB) must be delegated to Explore agents**: the prompt should say this explicitly
- **The output file should be a requirements doc, not a spec**: specs come after the loop, built by specialist agents
- **Include the completion promise instruction in the prompt**: "When all problems are answered... output RESEARCH COMPLETE"
- **`--max-iterations` has a hard ceiling of 30**: never generate a command above it; 15-25 is the normal band. Decompose oversized corpora into multiple loops rather than raising the cap (two-gate Gate-1-adjacent, [[2026-06-15-two-gate-enforcement-spec]] Area E).
