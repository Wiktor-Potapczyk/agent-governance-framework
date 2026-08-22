# Disabled Hooks

This directory holds hooks that ship with the framework but are NOT registered in the default config. Three kinds live here: (1) hooks disabled after an instructive failure: documented below because the failure modes reveal where the line is between useful enforcement and counterproductive restriction; (2) hooks that ship **opt-in / unregistered** by design: built and tested, but armed deliberately by the adopter rather than on by default (because the action they gate is high-stakes or context-dependent); (3) hooks **retired from the maintainer's own deployment**: still correct, working code, kept here as a reference implementation rather than deleted, because a working pattern has value even after its author stopped running it.

## config-protection.py

**What it did:** Fired on PreToolUse for `Write|Edit|MultiEdit`. Hard-blocked writes to three protected files (a local settings file, a registry file, and a persistent memory index), on the theory that a config file controlling hook registration should not be silently editable by the agent it governs.

**Why it was retired:** the guard blocked an already-approved batch of edits twice in one working day, and the only compliant paths were a session relaunch or a manual re-paste of a command the maintainer had already typed once. The maintainer's ruling: *"let's just remove that guard, it's nonsense anyways."* This is the same shape as the reversible-surface calibration documented for `bash-safety-guard.py`'s normal-push handling: a gate whose only real effect is making a human re-run an agent-composed action verbatim moves no decision to a human, it only costs a round trip.

**The lesson:** a hard PreToolUse deny on a *reversible* file (one with git history, diffable and revertable) is the wrong enforcement shape once the adopter has already delegated that decision. Warn-and-record (advisory logging, a changelog discipline, a full-suite regression gate on hook edits) recovers most of the safety value without the retry tax. See also `hooks/hook-write-regression-gate.py` and `claude-md-provenance-check.py`, which cover related ground without a hard block.

---

## agent-registry-check.py

**What it did:** Fired on SubagentStart. When a generic/untyped agent (general-purpose, explore, plan) was dispatched, scored the dispatch prompt's words against registry keyword lists and suggested specialist agents in `additionalContext`. Advisory only: it never blocked.

**Why it was retired:** retired from the maintainer's own deployment in the same pass as `config-protection.py`. Unlike that hook, no specific failure narrative is recorded for this one in the source project's own memory: the two were cut together as a batch, and this file's individual rationale was not separately documented. Recorded here as an honest gap rather than an invented one.

**Kept as a reference implementation:** the code is correct and does what its docstring says. If your adopter workflow leans on generic-agent dispatches and would benefit from a keyword-nudge toward specialists, this is a working starting point; just be aware it lacks an independently-recorded justification for staying off by default beyond "the maintainer stopped using it."

---

## em-dash-guard.py

**What it did / does:** Fires on Stop. Scans the assistant's last response for "fancy" dash characters (en dash, em dash, minus sign, and similar Unicode look-alikes) in prose, and hard-blocks the turn if any are found outside of code spans, tables, or frontmatter.

**Why it ships opt-in:** this is a personal writing-style preference, not a process-compliance check. It enforces "the maintainer never uses these characters" rather than anything about whether the agent did its job correctly, so it does not fit the framework's own stated design principle that hooks should verify process compliance, not judge output quality. It is a genuinely useful pattern for an adopter who wants a specific prose convention mechanically enforced (soft instructions alone land roughly 25% compliance in this framework's own measurements), but the convention itself is not universal, so it ships armed only by choice.

**To arm:** copy/symlink into your active hooks dir and register on `Stop` with no matcher.

---

## prose-codes-check.py

**What it did / does:** Fires on Stop. Sibling of `em-dash-guard.py` (same transcript-parse and strip-noise idiom): blocks a response that uses invented internal shorthand codes in prose (e.g. a made-up `T-C1` or `D-3` style reference) instead of a plain-language description, while allowing real ticket-key prefixes and workflow shorthand through an allow-list.

**Why it ships opt-in:** same reasoning as `em-dash-guard.py` -- this enforces a specific human's readability preference for prose, not a process gate. The allow-list (`ALLOW_PREFIXES`) is a placeholder pattern (`PROJ|TEAM|OPS|PLAT`) in this shipped copy; substitute your own project's real ticket-key prefixes before arming it, or every one of your own tickets will read as an invented code and trip the block.

**To arm:** copy/symlink into your active hooks dir and register on `Stop` with no matcher. Edit `ALLOW_PREFIXES` first.

---

## epistemic-check.py

**What it did:** Fired on Stop. Attempted to evaluate whether Claude's output was epistemically sound: checking for overconfident claims, missing uncertainty markers, and conclusions that outran the evidence.

**Why it was disabled:** It never blocked once across hours of operation. It rubber-stamped everything. The hook passed when it should have caught overconfidence, and it could not distinguish between "correctly confident" and "incorrectly confident" because that distinction requires semantic understanding of the domain: which a regex or keyword-based hook cannot provide. An LLM-based hook would add latency and cost for marginal gain.

**The lesson:** Hooks should verify **process compliance**, not **output truth**. Process compliance is observable and binary: was the task-classifier invoked? Does the output contain a QA REPORT section? Did the model dispatch the agents it declared in MUST DISPATCH? These are checkable without understanding the content. Output truth: "is this claim correct?": requires domain knowledge and semantic reasoning. That is a job for QA agents (process-qa, process-pentest), not hooks.

---

## delegation-check.ps1

**What it did:** Fired on PreToolUse for the Agent tool. Checked whether the agent being dispatched matched a pre-approved allowlist of agent names declared by the classifier. Dispatches not on the allowlist were blocked.

**Why it was disabled:** It was too restrictive. Real sessions routinely involve legitimate ad-hoc agent dispatches that were not pre-declared: a debugger agent called mid-task when an unexpected error surfaces, a quick verify call, a vault-keeper call to save a file. The allowlist model assumes the classifier can enumerate all agents needed before work begins: but work is iterative and needs emerge. Blocking undeclared dispatches punished legitimate adaptation.

**The lesson:** Hooks are **floors**, not **ceilings**. A floor enforces minimum standards: you must classify, you must produce a QA report, you must not run dangerous commands. A ceiling enforces maximum allowance: you may only do what was pre-approved. Ceilings prevent the system from adapting to reality. The correct response to an unexpected agent dispatch is to log it (for analysis), not block it. If you want to enforce that certain agents are always dispatched (floor), use dispatch-compliance-check.py instead: it verifies that declared MUST DISPATCH items actually happened, without blocking anything extra.

---

## pretooluse-payload-probe.py: diagnostic (NOT a failure)

**What it does:** Fires on PreToolUse for `Write|Edit|MultiEdit`. Appends ONE metadata-only JSONL record per matched call: the payload's key names, the `agent_type` value (or an explicit absent marker), the tool name, and whether a transcript path was present. Never file bodies, never prompts, never content.

**Why it ships here:** It is a temporary probe by design, deregistered after its measurement window. It ships because the pattern is the reusable part: before building hook logic on a payload field (say, "does `agent_type` reach PreToolUse for all subagent types?"), run a probe like this and measure what actually arrives instead of trusting documentation or memory. The header documents the metadata-only discipline that makes such a probe safe to leave in a tree.

**To arm:** register on `PreToolUse` with matcher `Write|Edit|MultiEdit`; the log appears under `hooks/_state/`. Deregister when your question is answered.

**The lesson:** payload shape is an empirical question. A field being present for one agent class proves nothing about the others; a ten-line probe settles it in a day of normal traffic.

---

## routing-table-validation.py: opt-in (NOT a failure)

**What it does:** Fires on PreToolUse for `Edit|Write|MultiEdit`. Denies a write that would introduce a **broken dispatch-name reference**: an agent name in a clear dispatch position (`MUST DISPATCH:` line, `subagent_type:` field, or a routing-table row) inside `CLAUDE.md` or any `SKILL.md` that resolves to nothing in `registry.json`. Low-false-positive by design: it only denies the unambiguous case and ALLOWs on any ambiguity (fail-open), so it never blocks a legitimate edit.

**Why it ships disabled (opt-in):** unlike `epistemic-check.py` and `delegation-check.ps1` above, this is not a disabled-after-failure case: it is built, tested (26 tests), and correct. It ships unregistered because arming a **blocking** hook on `CLAUDE.md` + every `SKILL.md` is a deliberate decision: it will gate the adopter's own edits to those files, and the registry it validates against must be complete (run `scripts/generate_registry.py` for the target project first). Arm it knowingly, not by default.

**To arm:** copy/symlink it into your active hooks dir and register it on `PreToolUse` with matcher `Edit|Write|MultiEdit` in `settings`. Populate `DEPRECATED_ALLOWLIST` with any retired-but-still-mentioned agent names so renames don't trip a false positive.

**The lesson:** a forcing function that blocks the highest-traffic files is high-leverage but high-blast-radius. Ship it ready, arm it deliberately, and prove the false-positive rate on a short trial before trusting it: the measure-then-gate discipline applied to the framework's own enforcement.
