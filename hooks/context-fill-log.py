"""
Context Fill Percentage Logger — P1-C STUB (2026-04-09)

STATUS: DEFERRED TO ITERATION 4
This file exists as an anchor so P1-C references in the monitoring roadmap v3
and PRD have a traceable target. The full implementation is deferred pending
Iteration 4 design work.

What it will eventually do:
- Read CC context window fill percentage (from CC environment or transcript metadata)
- Log per-turn context_fill events to governance-log.jsonl
- Enable correlation of context pressure with governance quality (M-P5 in PRD)

Why deferred:
- No confirmed API for reading context fill from within a hook
- Requires PreToolUse or Stop hook integration (design TBD)
- M-P5 (Context Fill Percentage Per Turn) has no alert threshold defined yet
- C3 question (context efficiency) is covered by manual compaction timing review
  until this hook is built

References:
- Monitoring roadmap v3: Iteration 1 step P1-C (stub), Iteration 4 candidates
- Monitoring PRD: M-P5, P1-C prerequisite
- Research question C3: "Is context being used efficiently?"

DO NOT REGISTER THIS HOOK. It's a stub — running it does nothing useful.
When Iteration 4 revisits this, implement the logging logic in main() below
and add the hook registration to settings.local.json.
"""

import sys


def main():
    """Stub — does nothing. Consume stdin to avoid blocking the hook pipeline if ever called."""
    try:
        sys.stdin.read()
    except Exception:
        pass
    # No-op. See module docstring.
    return


if __name__ == "__main__":
    main()
