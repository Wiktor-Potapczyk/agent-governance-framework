# Disabled Hooks

These hooks were built, tested in production, and then disabled. The reasons are documented here because the failure modes are instructive — they reveal where the line is between useful enforcement and counterproductive restriction.

## epistemic-check.py

**What it did:** Fired on Stop. Attempted to evaluate whether Claude's output was epistemically sound — checking for overconfident claims, missing uncertainty markers, and conclusions that outran the evidence.

**Why it was disabled:** It never blocked once across hours of operation. It rubber-stamped everything. The hook passed when it should have caught overconfidence, and it could not distinguish between "correctly confident" and "incorrectly confident" because that distinction requires semantic understanding of the domain — which a regex or keyword-based hook cannot provide. An LLM-based hook would add latency and cost for marginal gain.

**The lesson:** Hooks should verify **process compliance**, not **output truth**. Process compliance is observable and binary: was the task-classifier invoked? Does the output contain a QA REPORT section? Did the model dispatch the agents it declared in MUST DISPATCH? These are checkable without understanding the content. Output truth — "is this claim correct?" — requires domain knowledge and semantic reasoning. That is a job for QA agents (process-qa, process-pentest), not hooks.

---

## delegation-check.ps1

**What it did:** Fired on PreToolUse for the Agent tool. Checked whether the agent being dispatched matched a pre-approved allowlist of agent names declared by the classifier. Dispatches not on the allowlist were blocked.

**Why it was disabled:** It was too restrictive. Real sessions routinely involve legitimate ad-hoc agent dispatches that were not pre-declared: a debugger agent called mid-task when an unexpected error surfaces, a quick verify call, a vault-keeper call to save a file. The allowlist model assumes the classifier can enumerate all agents needed before work begins — but work is iterative and needs emerge. Blocking undeclared dispatches punished legitimate adaptation.

**The lesson:** Hooks are **floors**, not **ceilings**. A floor enforces minimum standards: you must classify, you must produce a QA report, you must not run dangerous commands. A ceiling enforces maximum allowance: you may only do what was pre-approved. Ceilings prevent the system from adapting to reality. The correct response to an unexpected agent dispatch is to log it (for analysis), not block it. If you want to enforce that certain agents are always dispatched (floor), use dispatch-compliance-check.py instead — it verifies that declared MUST DISPATCH items actually happened, without blocking anything extra.
