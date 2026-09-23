#!/usr/bin/env python3
"""Lint Pass R: ORPHAN_DRIFT (ROAD-6, 2026-09-08).

Weekly recomputation of orphan counts on two layers, reported as a stamped
delta against `_state/orphan-baseline.json` (shape mirrors
lint-cadence.json). Implements the resolution set fresh from the
process-lint SKILL.md Step 6.9 rules (there is no Pass J module on disk to
import; plan discovery 2):

  - resolution targets = every vault .md note stem, Archives INCLUDED as
    valid targets (the historical 982-vs-99 bug class), PLUS memory-folder
    filenames; when the memory folder is absent, link stems matching
    check_memory_index.py's REF filename pattern are treated as resolvable
  - placeholder, bash/code, and relative-path link shapes are dropped
    before counting (fenced code blocks and inline code spans are stripped
    first)
  - archived files are valid link TARGETS but not link SOURCES for the
    raw layer (per Step 6.9); the wiki layer's sources are the #wiki pages
    themselves, wherever they live

Layers:
  - raw: files under Projects/*/work/ (any project nesting depth) and
    Notes/ with zero inbound wikilinks from any other non-archived vault
    note, MINUS the valid-orphan classes parsed from spec R6's own
    "Valid-orphan classes" bullet list (anchored parse, fail-loud, never
    retyped) and MINUS work/backups/
  - wiki: #wiki-tagged pages with zero inbound wikilink from another
    #wiki page (R6's actual criterion)

Run 1 has no prior stamp: it prints prev=none delta=n/a, its counts become
the baseline, and the three non-interchangeable historical figures (93.6
percent naive, 882, 590) are never cited as comparable.

CLI contract: both ORPHAN_DRIFT layer blocks always print; exit 0 when no
layer drifted (run 1 included), 1 when any delta is nonzero, 2 on
derivation failure (before any state write).
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from check_memory_index import REF  # noqa: E402  (memory filename pattern, never retyped)

VAULT = SCRIPTS.parent.parent
DEFAULT_SPEC = VAULT / "Projects" / "Vault-Maintenance" / "work" / "2026-05-11-target-structure-spec.md"
DEFAULT_STATE = VAULT / ".claude" / "hooks" / "_state" / "orphan-baseline.json"

SKIP_DIRS = {".git", ".obsidian", ".claude", "node_modules", "__pycache__"}
FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
WIKILINK = re.compile(r"\[\[([^\]\[]+?)\]\]")
FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"`[^`\n]*`")
DROP_CHARS = set('<>$*{}"')


def derive_memory_dir():
    """TASK-034 (migration plan Phase 1): VAULT_MEMORY_ROOT override, then the
    live Path.home()-derived path, then the committed mirror fallback. See
    lint_pass_memory_overfill.derive_memory_file's docstring for the full
    contract; this function mirrors it exactly, returning the directory
    itself rather than a MEMORY.md path inside it."""
    override = os.environ.get("VAULT_MEMORY_ROOT")
    if override:
        return Path(override)
    enc = re.sub(r"[:\\/]", "-", str(VAULT))
    live = Path.home() / ".claude" / "projects" / enc / "memory"
    if live.is_dir():
        return live
    return VAULT / ".claude" / "user-claude-mirror" / "memory"


def parse_tags(text):
    m = FRONTMATTER.match(text)
    if not m:
        return []
    block = m.group(1)
    tm = re.search(r"^tags:\s*(.*)$", block, re.MULTILINE)
    if not tm:
        return []
    inline = tm.group(1).strip()
    if inline.startswith("["):
        return [t.strip().strip("'\"").lstrip("#")
                for t in inline.strip("[]").split(",") if t.strip()]
    if inline:
        return [inline.strip("'\"").lstrip("#")]
    tags = []
    for ln in block[tm.end():].splitlines():
        lm = re.match(r"^\s+-\s+(.+)$", ln)
        if lm:
            tags.append(lm.group(1).strip().strip("'\"").lstrip("#"))
        elif ln.strip():
            break
    return tags


def extract_links(text):
    """(kept_stems, dropped_count) for one document."""
    body = FENCE.sub("", text)
    body = INLINE_CODE.sub("", body)
    kept, dropped = [], 0
    for raw in WIKILINK.findall(body):
        target = re.split(r"[#|]", raw, maxsplit=1)[0].strip()
        if (not target or any(c in DROP_CHARS for c in target)
                or target.startswith("./") or target.startswith("../")):
            dropped += 1
            continue
        stem = target.rsplit("/", 1)[-1].strip()
        if stem.lower().endswith(".md"):
            stem = stem[:-3]
        if not stem:
            dropped += 1
            continue
        kept.append(stem)
    return kept, dropped


def parse_valid_orphan_classes(spec_path):
    """(path_classes, conditional_classes) from spec R6's own bullet list.

    path_classes: list of compiled prefix regexes.
    conditional_classes: list of (prefix regex, tag-that-exempts) pairs; a
    candidate matching the prefix WITHOUT the tag is a valid orphan.
    Returns None on any parse failure (fail-loud at the caller).
    """
    text = Path(spec_path).read_text(encoding="utf-8")
    m = re.search(r"\*\*Valid-orphan classes.*?$(.*?)^\*\*", text,
                  re.DOTALL | re.MULTILINE)
    if not m:
        return None
    path_classes, conditional = [], []
    for line in m.group(1).splitlines():
        if not line.strip().startswith("- "):
            continue
        tokens = re.findall(r"`([^`]+)`", line)
        if not tokens:
            continue
        tag_tokens = [t for t in tokens if t.startswith("#")]
        path_tokens = [t for t in tokens if not t.startswith("#")]
        for tok in path_tokens:
            pattern = re.sub(r"<[^>]+>|\*", "\x00", tok)
            pattern = re.escape(pattern).replace("\x00", "[^/]+")
            rx = re.compile("^" + pattern, re.IGNORECASE)
            if "WITHOUT" in line and tag_tokens:
                conditional.append((rx, tag_tokens[0].lstrip("#")))
            else:
                path_classes.append(rx)
    if len(path_classes) + len(conditional) < 8 or not conditional:
        return None
    return path_classes, conditional


def fmt_delta(count, prev):
    if prev is None:
        return "prev=none delta=n/a", False
    d = count - prev
    if d == 0:
        return f"prev={prev} delta=0", False
    return f"prev={prev} delta={d:+d}", True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(VAULT))
    ap.add_argument("--state-file", default=str(DEFAULT_STATE))
    ap.add_argument("--spec", default=str(DEFAULT_SPEC))
    ap.add_argument("--memory-dir", default=None)
    args = ap.parse_args(argv)

    try:
        classes = parse_valid_orphan_classes(args.spec)
    except OSError as e:
        print(f"DERIVATION FAILURE: cannot read spec {args.spec}: {e}")
        return 2
    if classes is None:
        print("DERIVATION FAILURE: R6 Valid-orphan classes list did not parse "
              f"in {args.spec}")
        return 2
    path_classes, conditional_classes = classes

    root = Path(args.root)
    if not root.is_dir():
        print(f"DERIVATION FAILURE: root not a directory: {root}")
        return 2

    memory_dir = Path(args.memory_dir) if args.memory_dir else derive_memory_dir()
    memory_stems = set()
    memory_fallback = False
    if memory_dir.is_dir():
        memory_stems = {p.stem for p in memory_dir.glob("*.md")}
    else:
        memory_fallback = True  # REF-shaped stems treated as resolvable

    # corpus walk
    notes = {}  # relpath(posix) -> {tags, links, dropped}
    for path in root.rglob("*.md"):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        links, dropped = extract_links(text)
        notes[rel.as_posix()] = {
            "tags": parse_tags(text), "links": links, "dropped": dropped,
        }

    stems = {rel.rsplit("/", 1)[-1][:-3] for rel in notes}  # all notes incl. Archives
    total_links = sum(len(n["links"]) for n in notes.values())
    total_dropped = sum(n["dropped"] for n in notes.values())
    unresolved = 0
    for n in notes.values():
        for stem in n["links"]:
            if stem in stems or stem in memory_stems:
                continue
            if memory_fallback and REF.fullmatch(stem + ".md"):
                continue
            unresolved += 1

    # inbound maps
    raw_inbound = set()   # stems linked from any non-archived note
    wiki_inbound = set()  # stems linked from any #wiki page
    for rel, n in notes.items():
        is_archived = rel.lower().startswith("archives/")
        is_wiki = "wiki" in n["tags"]
        self_stem = rel.rsplit("/", 1)[-1][:-3]
        for stem in n["links"]:
            if stem == self_stem:
                continue
            if not is_archived:
                raw_inbound.add(stem)
            if is_wiki:
                wiki_inbound.add(stem)

    # raw layer
    raw_orphans = []
    for rel, n in notes.items():
        if not (re.match(r"^Projects/.+/work/", rel, re.IGNORECASE)
                or rel.lower().startswith("notes/")):
            continue
        if "/work/backups/" in rel.lower():
            continue
        if any(rx.match(rel) for rx in path_classes):
            continue
        if any(rx.match(rel) and tag not in n["tags"]
               for rx, tag in conditional_classes):
            continue
        stem = rel.rsplit("/", 1)[-1][:-3]
        if stem not in raw_inbound:
            raw_orphans.append(rel)

    # wiki layer
    wiki_orphans = []
    for rel, n in notes.items():
        if "wiki" not in n["tags"]:
            continue
        stem = rel.rsplit("/", 1)[-1][:-3]
        if stem not in wiki_inbound:
            wiki_orphans.append(rel)

    # prior stamp
    state_path = Path(args.state_file)
    prev_raw = prev_wiki = None
    if state_path.is_file():
        try:
            prior = json.loads(state_path.read_text(encoding="utf-8"))
            prev_raw = prior.get("raw_count")
            prev_wiki = prior.get("wiki_count")
        except (OSError, json.JSONDecodeError):
            print(f"DERIVATION FAILURE: unreadable state file {state_path}")
            return 2

    fallback_note = " (memory-fallback pattern mode)" if memory_fallback else ""
    print(f"ORPHAN_LINKS total={total_links} dropped={total_dropped} "
          f"unresolved={unresolved} notes={len(notes)}{fallback_note}")
    raw_part, raw_drift = fmt_delta(len(raw_orphans), prev_raw)
    wiki_part, wiki_drift = fmt_delta(len(wiki_orphans), prev_wiki)
    print(f"ORPHAN_DRIFT  layer=raw count={len(raw_orphans)} {raw_part}")
    print(f"ORPHAN_DRIFT  layer=wiki count={len(wiki_orphans)} {wiki_part}")

    state_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = {
        "last_iso": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw_count": len(raw_orphans),
        "wiki_count": len(wiki_orphans),
    }
    with open(state_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(stamp, f, indent=2)
        f.write("\n")

    return 1 if (raw_drift or wiki_drift) else 0


if __name__ == "__main__":
    sys.exit(main())
