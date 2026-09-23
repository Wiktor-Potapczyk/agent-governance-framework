"""Invariant check for a MEMORY.md compaction.

MEMORY.md is the index loaded into context every session. Compacting it is
lossy by nature, so the one thing that must not change is REACHABILITY: every
memory file that had an index entry must still have one, and no entry may
point at a file that does not exist.

Usage: python check_memory_index.py <baseline.md> <candidate.md>
Exit 0 = invariant holds. Exit 1 = it does not.
"""
import os
import re
import sys

# Memory files follow a fixed naming convention. Anything else named in the
# index (STATE.md, task_plan.md, a vault reference doc) is a vault path, not a
# memory file, and is out of scope for this invariant.
# The `.md` suffix is OPTIONAL and the stem is what counts. MEMORY.md dropped
# extensions from its citations on 2026-09-09 to save bytes, which silently
# disarmed this check: the old pattern required `.md`, so it matched 1 ref
# instead of ~140 and still printed "INVARIANT: HOLDS". A check that cannot
# fail is worse than no check, because it is trusted. Matching the stem makes
# the invariant convention-independent.
#
# The trailing group is OPTIONAL, not absent: this pattern is imported by
# lint_pass_orphan_drift.py, which calls REF.fullmatch(stem + ".md"). Dropping
# `.md` entirely broke that caller and turned its baseline test red. Both forms
# must fullmatch. Changing a shared constant means checking its importers.
REF = re.compile(r"(?:feedback|finding|reference|decision|project|user|hypothesis)_[A-Za-z0-9_\-]+(?:\.md)?")


# Sanctioned renames. A compaction may FIX a pointer that was already broken,
# but only deliberately and only with the correction written down here, so the
# check stays strict instead of being loosened to accommodate a silent edit.
RENAMES = {
    # 2026-08-22: index pointed at a filename that never existed on disk
    # (...runonceforeacheitem...); the real file is ...runonceforeachitem...
    "reference_n8n_code_node_runonceforeacheitem_array_return_bug.md":
        "reference_n8n_code_node_runonceforeachitem_array_return_bug.md",
}


def stem(name):
    """Normalise a pointer to its extensionless stem, so the invariant holds
    across both citation conventions (`foo` and `foo.md`)."""
    return name[:-3] if name.endswith(".md") else name


RENAMES = {stem(k): stem(v) for k, v in RENAMES.items()}


def refs(path):
    with open(path, encoding="utf-8") as f:
        return {stem(x) for x in REF.findall(f.read())}


def main():
    base, cand = sys.argv[1], sys.argv[2]
    b, c = refs(base), refs(cand)
    b = {RENAMES.get(x, x) for x in b}
    here = os.path.dirname(os.path.abspath(base)) or "."

    lost = sorted(b - c)
    added = sorted(c - b)
    dangling = sorted(r for r in c
                      if r != "MEMORY" and not os.path.exists(os.path.join(here, r + ".md")))

    print(f"baseline refs: {len(b)}   candidate refs: {len(c)}")
    for label, items in (("LOST", lost), ("ADDED", added), ("DANGLING", dangling)):
        print(f"{label}: {len(items)}")
        for i in items[:20]:
            print("   ", i)

    size = os.path.getsize(cand)
    print(f"candidate bytes: {size}  (target < 17100)")

    ok = not lost and not dangling
    print("INVARIANT:", "HOLDS" if ok else "VIOLATED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
