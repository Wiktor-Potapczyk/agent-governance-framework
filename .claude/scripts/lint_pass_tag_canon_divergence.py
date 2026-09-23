#!/usr/bin/env python3
"""Lint Pass P: TAG_CANON_DIVERGENCE (ROAD-4, 2026-09-08).

Advisory weekly three-way diff of the tag canon sources:
  1. CANONICAL_TAGS in .claude/hooks/tag-variant-check.py (AST-extracted)
  2. FALLBACK_CANONICAL_TAGS in .claude/hooks/vault-structure-check.py
     (AST-extracted)
  3. CLAUDE.md canon = backticked tokens on the "- Tags (canonical" line
     UNION the "- Status:" line (pinned two-line decision, plan discovery 3:
     both hook sets carry the four status values as tags, so a
     tags-line-only parse mis-reports 9 findings instead of 5)

No set is re-typed (generator-derivation rule). All three extractions are
fail-loud: an empty or missing extraction exits 2 and never reports clean
(a hook refactor that renames a set variable must break this pass loudly).

Every `project/`-prefixed member (including the `project/<name>`
placeholder) is exempted from all three sources before the diff:
tag-variant-check.py validates that namespace at runtime outside its set,
while FALLBACK_CANONICAL_TAGS bakes in ~24 concrete project/* literals.

One finding per tag not present in all three sources:
`TAG_CANON_DIVERGENCE  tag=<t> present=<src-list> absent=<src-list>`

Going green requires the owner canonical-list rulings (trust-roadmap
section 6, rulings 2 and 3); the measure itself runs regardless.

CLI contract: always-print measurement line; exit 0 clean, 1 findings,
2 derivation failure.
"""
import argparse
import ast
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent
DEFAULT_TAG_VARIANT = VAULT / ".claude" / "hooks" / "tag-variant-check.py"
DEFAULT_VAULT_STRUCTURE = VAULT / ".claude" / "hooks" / "vault-structure-check.py"
DEFAULT_CLAUDE_MD = VAULT / "CLAUDE.md"

TAGS_LINE = re.compile(r"^- Tags \(canonical.*$", re.MULTILINE)
STATUS_LINE = re.compile(r"^- Status:.*$", re.MULTILINE)


def extract_assign(source_path, name):
    """AST-extract the literal assigned to `name` in a Python source file."""
    tree = ast.parse(Path(source_path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise LookupError(f"no assignment to {name} in {source_path}")


def claude_md_canon(path):
    text = Path(path).read_text(encoding="utf-8")
    tags_m = TAGS_LINE.search(text)
    status_m = STATUS_LINE.search(text)
    if not tags_m or not status_m:
        return None
    tokens = set(re.findall(r"`([^`]+)`", tags_m.group(0)))
    tokens |= set(re.findall(r"`([^`]+)`", status_m.group(0)))
    # Keep only tag-shaped tokens: lowercase kebab, optional single
    # project/-style segment (the `<name>` placeholder included). This
    # drops the non-tag backticked mentions that share the two anchor
    # lines: the spec path, the bare `#`, and the `status:` field name in
    # the Status line's parenthetical (a YAML field, not a tag; without
    # this filter it surfaced as a spurious sixth finding).
    tokens = {t for t in tokens
              if re.fullmatch(r"[a-z0-9-]+(?:/[a-z0-9<>-]+)?", t)}
    return tokens or None


def drop_project(tags):
    return {t for t in tags if not t.startswith("project/")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag-variant-source", default=str(DEFAULT_TAG_VARIANT))
    ap.add_argument("--vault-structure-source", default=str(DEFAULT_VAULT_STRUCTURE))
    ap.add_argument("--claude-md", default=str(DEFAULT_CLAUDE_MD))
    args = ap.parse_args(argv)

    sources = {}
    try:
        sources["tag-variant-check"] = set(
            extract_assign(args.tag_variant_source, "CANONICAL_TAGS"))
        sources["vault-structure-check"] = set(
            extract_assign(args.vault_structure_source, "FALLBACK_CANONICAL_TAGS"))
    except (OSError, LookupError, ValueError, SyntaxError) as e:
        print(f"DERIVATION FAILURE: set extraction: {e}")
        return 2
    try:
        claude = claude_md_canon(args.claude_md)
    except OSError as e:
        print(f"DERIVATION FAILURE: cannot read {args.claude_md}: {e}")
        return 2
    if claude is None:
        print(f"DERIVATION FAILURE: Tags/Status anchor lines missing in {args.claude_md}")
        return 2
    sources["claude-md"] = claude

    for label in sources:
        sources[label] = drop_project(sources[label])
        if not sources[label]:
            print(f"DERIVATION FAILURE: empty canon set from {label}")
            return 2

    universe = set().union(*sources.values())
    divergent = []
    for tag in sorted(universe):
        present = [s for s in ("tag-variant-check", "vault-structure-check", "claude-md")
                   if tag in sources[s]]
        absent = [s for s in ("tag-variant-check", "vault-structure-check", "claude-md")
                  if tag not in sources[s]]
        if absent:
            divergent.append((tag, present, absent))

    print("TAG_CANON sizes "
          f"tag-variant-check={len(sources['tag-variant-check'])} "
          f"vault-structure-check={len(sources['vault-structure-check'])} "
          f"claude-md={len(sources['claude-md'])} divergent={len(divergent)}")
    for tag, present, absent in divergent:
        print(f"TAG_CANON_DIVERGENCE  tag={tag} "
              f"present={','.join(present)} absent={','.join(absent)}")
    return 1 if divergent else 0


if __name__ == "__main__":
    sys.exit(main())
