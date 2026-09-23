# Test-round addendum

Concatenated onto `PROMPT.md` ONLY when `vault-self-heal.yml` is dispatched
with `test_round: true`. Never read on a normal, scheduled round. It exists
so the loop's own plumbing (shadow workspace, runner hooks, apply step,
staging guard, push, PR body, PR creation, checks chaining, owner-comment
listener) can be exercised end to end on a throwaway target without the
spike's dangerous instruction.

Do exactly this and nothing else:

1. Create `_claude/scripts/test_self_heal_spike_scratch.py` (in your
   workspace the vault's `.claude` directory is mounted as `_claude`, see
   the "Your workspace" section of the system prompt) containing one
   trivial passing pytest test (a function named `test_scratch_passes` that
   asserts `1 + 1 == 2`) with a two-line module docstring saying it is a
   throwaway file from a self-heal test round and may be deleted.
2. Run `bash _claude/bin/py -m pytest _claude/scripts/test_self_heal_spike_scratch.py -q -p no:cacheprovider` and report the result line in your final message.
3. Do not edit, create or delete any other file. Do not run git commands.
4. In your final message name the file in its real form,
   `.claude/scripts/test_self_heal_spike_scratch.py`, and end with the line
   `TEST ROUND COMPLETE`.
