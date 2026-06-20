# Disabled Hooks

This directory holds hooks that ship with the framework but are NOT registered in the default config. Two kinds live here: (1) hooks disabled after an instructive failure: documented below because the failure modes reveal where the line is between useful enforcement and counterproductive restriction; (2) hooks that ship **opt-in / unregistered** by design: built and tested, but armed deliberately by the adopter rather than on by default (because the action they gate is high-stakes or context-dependent).

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

## routing-table-validation.py: opt-in (NOT a failure)

**What it does:** Fires on PreToolUse for `Edit|Write|MultiEdit`. Denies a write that would introduce a **broken dispatch-name reference**: an agent name in a clear dispatch position (`MUST DISPATCH:` line, `subagent_type:` field, or a routing-table row) inside `CLAUDE.md` or any `SKILL.md` that resolves to nothing in `registry.json`. Low-false-positive by design: it only denies the unambiguous case and ALLOWs on any ambiguity (fail-open), so it never blocks a legitimate edit.

**Why it ships disabled (opt-in):** unlike the two hooks above, this is not a disabled-after-failure case: it is built, tested (26 tests), and correct. It ships unregistered because arming a **blocking** hook on `CLAUDE.md` + every `SKILL.md` is a deliberate decision: it will gate the adopter's own edits to those files, and the registry it validates against must be complete (run `scripts/generate_registry.py` for the target project first). Arm it knowingly, not by default.

**To arm:** copy/symlink it into your active hooks dir and register it on `PreToolUse` with matcher `Edit|Write|MultiEdit` in `settings`. Populate `DEPRECATED_ALLOWLIST` with any retired-but-still-mentioned agent names so renames don't trip a false positive.

**The lesson:** a forcing function that blocks the highest-traffic files is high-leverage but high-blast-radius. Ship it ready, arm it deliberately, and prove the false-positive rate on a short trial before trusting it: the measure-then-gate discipline applied to the framework's own enforcement.
