"""MOC member-list backfill — populate a `## Members` section in each MOC.

Inverts the wikilink graph: any file in the vault that contains `[[moc-X]]`
becomes a member of `moc-X`. The MOC then gets a `## Members` section listing
those files alphabetically as bulleted wikilinks.

Doctrine (L31 conservative defaults, 2026-05-24):
- Exclude paths: archive dirs, backup dirs, scratch dirs, the MOC itself,
  the `Inbox/`, `Daily Notes/`, `Templates/`, `.claude/`, `.obsidian/`, `.git/`.
- Exclude basenames: `STATE.md`, `PROJECT.md`, `task_plan.md`, `MEMORY.md`,
  `Home.md`, `CLAUDE.md`, `README.md`, `INDEX.md`, `log.md`.
  (These are infrastructure files; their wikilinks-to-MOCs are navigational
  not membership-establishing — listing them would drown the MOC.)
- Members sorted alphabetically by basename (case-insensitive).
- If the MOC already has a `## Members` section, replace its contents.
  Otherwise, append a new section at end of file.
- Idempotent: re-running on a backfilled MOC produces the same output.

Run: `python .claude/scripts/moc_member_backfill.py [--dry-run]`
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
KB_DIR = VAULT / "Resources" / "KB"

EXCLUDE_PATH_PARTS = {
    ".claude", ".obsidian", ".git",
    "Inbox", "Daily Notes", "Templates", "Archives",
}
EXCLUDE_SUBSTRINGS = ("/archive/", "/backups/", "/_backup-", "/_scratch")

EXCLUDE_BASENAMES = {
    "STATE.md", "PROJECT.md", "task_plan.md", "MEMORY.md",
    "Home.md", "CLAUDE.md", "README.md", "ARCHITECTURE.md",
    "INDEX.md", "log.md",
}

WIKILINK_RE = re.compile(r"\[\[(moc-[a-z0-9\-]+)(?:[\|#][^\]]*)?(?:\.md)?\]\]", re.IGNORECASE)

SECTION_MARK_BEGIN = "<!-- moc:members:begin -->"
SECTION_MARK_END = "<!-- moc:members:end -->"


def _path_excluded(p: Path) -> bool:
    rel = p.relative_to(VAULT).as_posix()
    rel_lower = rel.lower()
    # Path-part exclusions (any segment in the deny list)
    parts = set(p.relative_to(VAULT).parts)
    if parts & EXCLUDE_PATH_PARTS:
        return True
    # Substring exclusions
    for s in EXCLUDE_SUBSTRINGS:
        if s in "/" + rel_lower:
            return True
    if p.name in EXCLUDE_BASENAMES:
        return True
    return False


def _moc_basename(moc_name: str) -> str:
    """Normalize moc reference: trim variants and lowercase."""
    return moc_name.lower().strip()


def _strip_members_section(text: str) -> str:
    """Remove the moc:members:begin..end block so re-scans are idempotent.

    Without this, the script picks up its own backfilled `[[moc-X]]` member
    bullets on the next run, creating a feedback loop between MOCs that
    cross-list each other.
    """
    pattern = re.compile(
        rf"{re.escape(SECTION_MARK_BEGIN)}.*?{re.escape(SECTION_MARK_END)}",
        re.DOTALL,
    )
    return pattern.sub("", text)


def _scan_vault_for_members() -> dict[str, list[Path]]:
    """Walk the vault, return {moc-name -> sorted list of member Paths}."""
    members: dict[str, set[Path]] = {}
    for p in VAULT.rglob("*.md"):
        if _path_excluded(p):
            continue
        # Don't include MOCs in their OWN member list (but a MOC CAN
        # be a member of another MOC if it links to it — handled below
        # by `p != target_moc`).
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Strip the auto-generated Members section before scanning, so
        # backfilled links don't feed back into the index.
        text = _strip_members_section(text)
        for m in WIKILINK_RE.finditer(text):
            moc_name = _moc_basename(m.group(1))
            target_moc = KB_DIR / f"{moc_name}.md"
            if not target_moc.is_file():
                continue
            if p.resolve() == target_moc.resolve():
                continue  # MOC linking to itself doesn't count
            members.setdefault(moc_name, set()).add(p)
    return {
        k: sorted(v, key=lambda x: (x.name.lower(), str(x).lower()))
        for k, v in members.items()
    }


def _render_members_section(member_paths: list[Path]) -> str:
    """Render the section block. Each member as a wikilink with parent dir hint."""
    lines = [SECTION_MARK_BEGIN, "## Members", ""]
    if not member_paths:
        lines.append("_No inbound `[[moc-name]]` links found._")
    else:
        lines.append(f"_{len(member_paths)} file(s) linking here._")
        lines.append("")
        for mp in member_paths:
            stem = mp.stem
            # Parent dir hint for disambiguation
            try:
                parent_rel = mp.parent.relative_to(VAULT).as_posix()
            except ValueError:
                parent_rel = mp.parent.name
            lines.append(f"- [[{stem}]] — `{parent_rel}/`")
    lines.append("")
    lines.append(SECTION_MARK_END)
    return "\n".join(lines)


def _upsert_section(moc_text: str, new_section: str) -> tuple[str, str]:
    """Insert or replace the marked section. Returns (new_text, action)."""
    if SECTION_MARK_BEGIN in moc_text and SECTION_MARK_END in moc_text:
        # Replace existing block
        pattern = re.compile(
            rf"{re.escape(SECTION_MARK_BEGIN)}.*?{re.escape(SECTION_MARK_END)}",
            re.DOTALL,
        )
        new = pattern.sub(new_section, moc_text, count=1)
        return new, "replaced"
    # Append at end
    sep = "\n\n" if not moc_text.endswith("\n") else "\n"
    return moc_text + sep + new_section + "\n", "appended"


def backfill_moc(moc_path: Path, member_paths: list[Path], dry_run: bool) -> dict:
    text = moc_path.read_text(encoding="utf-8")
    new_section = _render_members_section(member_paths)
    new_text, action = _upsert_section(text, new_section)
    changed = new_text != text
    if changed and not dry_run:
        moc_path.write_text(new_text, encoding="utf-8")
    return {
        "moc": moc_path.name,
        "members": len(member_paths),
        "action": action,
        "changed": changed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    members_map = _scan_vault_for_members()
    moc_files = sorted(KB_DIR.glob("moc-*.md"))

    print(f"Scan: {sum(len(v) for v in members_map.values())} membership relations across {len(members_map)} MOCs.")
    print(f"Backfilling {len(moc_files)} MOCs (dry_run={args.dry_run})...")
    print()

    rows = []
    for moc in moc_files:
        moc_name = moc.stem.lower()
        members = members_map.get(moc_name, [])
        result = backfill_moc(moc, members, args.dry_run)
        rows.append(result)
        flag = "C" if result["changed"] else "."
        print(f"  [{flag}] {result['moc']:45s} members={result['members']:3d}  action={result['action']}")

    print()
    changed = sum(1 for r in rows if r["changed"])
    print(f"Done. {changed}/{len(rows)} MOCs {'would be ' if args.dry_run else ''}updated.")


if __name__ == "__main__":
    main()
