r"""Every vault path an agent definition points at must exist.

WHY
---
`pm-orchestrator.md` carried a MANDATORY LOOKUP block naming a PM-Lifecycle work
directory that does not exist. The project had been archived into
Agent-Governance-Research and the pointers were never followed. The agent was
instructed to "read the research library first, then answer grounded in what it
says", and the library was not there, so every dispatch that needed grounding
either answered ungrounded or spent tool calls discovering the path was dead.
It was the audit's own PM checkpoint that finally reported it, which is the
slowest possible detector.

A dead pointer in an agent definition is invisible by construction: nothing
imports it, nothing lints it, and the agent that follows it is the only thing
that finds out. That is the same shape as the rest of this audit, a control
reporting success it has not earned, so it gets the same treatment: an
executable check rather than a note.

SCOPE, AND WHY IT IS NARROW
---------------------------
Only vault-rooted paths inside backticks, in the 33 definitions the vault owns.
Plugin-supplied agents are not ours to edit. Anything with a space, a glob, an
angle bracket or a square bracket is a template or an illustration rather than a
pointer, and is skipped. That leaves roughly a dozen real references, of which
exactly one was dead when this was written.

The zero-denominator guard below is not decoration. This file's own subject is
suites that pass while verifying nothing: if the pattern or the root list ever
stops matching, `checked` collapses to zero and the dead-path assertion becomes
trivially true. So an empty denominator fails first and loudly.
"""

import glob
import os
import re

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKTICKED = re.compile(r"`([^`\n]+)`")
VAULT_ROOTS = ("Projects/", "Resources/", ".claude/", "Templates/", "Archives/",
               "Inbox/", "Notes/")
# A template or an illustration, not a pointer to a real file.
NOT_A_POINTER = (" ", "*", "<", "[", "{")


def _references():
    """Yield (definition, path) for every vault-rooted backticked path."""
    for path in sorted(glob.glob(os.path.join(VAULT, ".claude", "agents", "*.md"))):
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
        for raw in BACKTICKED.findall(body):
            ref = raw.strip()
            if not ref.startswith(VAULT_ROOTS):
                continue
            if any(ch in ref for ch in NOT_A_POINTER):
                continue
            yield os.path.basename(path), ref


def test_scanner_finds_something_to_check():
    """Fail loudly on an empty denominator rather than passing vacuously."""
    found = list(_references())
    assert found, (
        "the scanner matched zero vault-rooted path references across every agent "
        "definition, which is far more likely to mean the pattern or the root list "
        "broke than that the references are gone. Until this finds something, the "
        "dead-path test below proves nothing.")


def test_no_agent_definition_points_at_a_missing_path():
    dead = [(d, r) for d, r in _references()
            if not os.path.exists(os.path.join(VAULT, r))]
    assert not dead, (
        "agent definition(s) point at paths that do not exist, so an agent told to "
        "ground itself in them cannot:\n  "
        + "\n  ".join(f"{d} -> {r}" for d, r in dead)
        + "\nIf a reference is a deliberate historical quotation rather than a live "
          "pointer, write it without backticks; see the note in pm-orchestrator.md.")
