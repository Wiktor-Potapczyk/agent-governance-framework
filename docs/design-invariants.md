# Design invariants

Named rules this framework treats as load-bearing. A change that violates one of these needs a deliberate decision, not a drive-by edit. Curated from the repository's own ADRs, architecture doc, and hook history: none of these are invented for this page.

## Enforcement over advisory

Hooks achieve what prompts do not. Measured: prompts alone hold roughly 25% compliance on stated rules, and hooks enforcing the same rules hold roughly 90%. Every critical rule in `CLAUDE.md` has a corresponding enforcement hook for this reason.

Origin: [ADR-0002](adr/0002-hooks-enforce-process-not-prompts.md).

## Blind analysis

A delegation message to an evaluating agent states only what to examine and the criteria. It carries no hypothesis, no prior conclusion, and no proposed cause: an agent anchors on whatever framing it is handed, so the framing stays empty. Named exceptions cover agents that need directed context (`blueprint-mode`, `implementation-plan`, `content-marketer`, `adversarial-reviewer`).

Origin: `docs/architecture.md` Layer 2 (Agent Delegation), `CLAUDE.md` Delegation section.

## Fail-open guards

A broken guard must never stop work. Nearly every hook in this repository catches its own exceptions and allows the action rather than blocking on an internal error: see the Failure mode row for each entry in [reference/hooks.md](reference/hooks.md). The one deliberate exception is Gate 1: `bash-safety-guard.py` ships a frozen fallback snapshot of the irreversible-action surface, so an import failure degrades to a known pattern list instead of an empty one. For a deny-class security hook, failing open to nothing is worse than lagging.

Origin: `docs/reference/hooks.md` (repo-wide pattern), [ADR-0007](adr/0007-two-gate-autonomy.md) (the Gate-1 exception).

## Measure before gating

A threshold comes from a measured distribution, not a guess. `prose-slop-check.py` is calibrated against a corpus to zero false positives before it ships. The classifier's Explicit Imperative fast path was added after governance-log analysis showed disproportionate ceremony cost on one-line edits, not from a stylistic preference.

Origin: `docs/reference/hooks.md` (`prose-slop-check.py` entry), `docs/architecture.md` Layer 0 (Explicit Imperative Fast Path).

## No silent caps

Dropped coverage must be reported. Every QA and pentest report, at every tier, must declare an Untested Surface: what was not tested and why. A report that omits it is incomplete by definition, not merely thin.

Origin: [ADR-0003](adr/0003-three-tier-qa-falsification.md).

## A gate that cannot fail is not a gate

`epistemic-check.py` never blocked once across hours of live operation, and was retired for exactly that: a gate that rubber-stamps everything gives no signal, which is worse than no gate (see `hooks/disabled/README.md`). The positive form of the same rule: `dispatch-compliance-check.py`'s H3 check treats an empty MUST DISPATCH declaration on a non-Quick task as a hard block, not a silent pass, because an empty selection is exactly the case a permissive gate would wave through.

Origin: `hooks/disabled/README.md` (`epistemic-check.py`), `docs/reference/hooks.md` (`dispatch-compliance-check.py` H3).

## Further reading

The theory and empirical basis behind these invariants live in the companion research repository: <https://github.com/Wiktor-Potapczyk/agent-governance-research>.
