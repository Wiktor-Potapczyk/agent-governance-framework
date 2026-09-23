#!/usr/bin/env python3
"""Mirror the irreplaceable part of the user-level ~/.claude into the vault repo.

Why this exists (measured 2026-09-09): `~/.claude` is not a git repository, is
not inside one, and is not synced anywhere. It holds the memory folder (926
files at the time of writing), the hook wiring in settings.json, and the
user-level skills. A disk failure loses all of it with no second copy, and
cross-session memory is not re-derivable by anyone.

The vault repo already has a 30-minute commit task and a daily push, so
mirroring into it buys off-machine backup with no new remote and no new
scheduled task.

WHAT IS COPIED, and nothing else:
  - projects/<vault-id>/memory/     the irreplaceable part, ~7.5 MB
  - skills/                          user-level skills, ~1.4 MB
  - settings.json, settings.local.json   the hook wiring

WHAT IS DELIBERATELY NOT COPIED:
  - secrets/   Credentials must never enter git in plaintext. They are also a
               different risk class: a PAT is re-issuable from its source, so
               losing one costs a few minutes. Memory is not re-issuable by
               anyone, which is why it is worth backing up and secrets are not.
               This exclusion is asserted in code below and pinned by a test.
  - jobs/, sessions/, *.jsonl transcripts, caches, file-history
               Bulk (about 5.5 GB of the 5.5 GB total) and either disposable
               scratch or reconstructible.

NDA note: memory files carry client and ticket detail, so the mirror is vault
content and must never be copied into a public repo. Publication is a
deliberate per-file merge and the NDA gate scans the published diff, so the
existing controls cover it; do not add this path to any publication set.

Exit codes: 0 mirrored (or already current), 2 a source path is missing or a
safety assertion failed. Never silently partial.
"""
import argparse
import hashlib
import re
import shutil
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
USER_CLAUDE = Path.home() / ".claude"
VAULT_ID = "C--Users-WiktorPotapczyk-Desktop-Vault"
DEST_REL = Path(".claude") / "user-claude-mirror"

# Any path containing one of these segments must never be mirrored.
FORBIDDEN_SEGMENTS = ("secrets", "jobs", "sessions", "shell-snapshots",
                      "file-history", "cache", "image-cache", "downloads")

# Content gate, added after the first live run (2026-09-09) tried to mirror a
# live GitHub PAT sitting in plaintext inside settings.json. Excluding the
# `secrets/` DIRECTORY was never enough: a credential in a file we deliberately
# chose to back up sails straight past a path-based rule. Any file whose
# content matches one of these is REFUSED, never scrubbed. Scrubbing would risk
# writing a corrupted settings file, and a partial redaction that missed one
# token would be worse than skipping the file outright.
CREDENTIAL_PATTERNS = re.compile(
    r"ghp_[A-Za-z0-9]{20,}"          # GitHub personal access token
    r"|github_pat_[A-Za-z0-9_]{20,}"
    r"|figd_[A-Za-z0-9_\-]{20,}"     # Figma
    r"|xox[baprs]-[A-Za-z0-9\-]{10,}"  # Slack
    r"|sk-[A-Za-z0-9]{20,}"          # OpenAI-style
    r"|sk_live_[A-Za-z0-9]{10,}"
    r"|AIza[A-Za-z0-9_\-]{30,}"      # Google API key
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\."  # JWT
)
TEXT_SUFFIXES = {".json", ".md", ".txt", ".yaml", ".yml", ".tmpl",
                 ".py", ".js", ".ps1", ".sh", ".env", ".ini", ".cfg"}


def carries_credential(path):
    """True if the file's text contains a credential-shaped token.

    Binary and unreadable files are treated as NOT carrying one: they are not
    mirrored by this tool in practice, and guessing at binary content would
    produce false refusals that quietly shrink the backup."""
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return bool(CREDENTIAL_PATTERNS.search(text))


def sources(user_claude, vault_id):
    """(source_path, destination_subpath) pairs. Directories are copied whole."""
    proj = user_claude / "projects" / vault_id
    return [
        (proj / "memory", Path("memory")),
        (user_claude / "skills", Path("skills")),
        (user_claude / "settings.json", Path("settings.json")),
        (user_claude / "settings.local.json", Path("settings.local.json")),
    ]


def is_forbidden(rel_posix):
    parts = {p.lower() for p in Path(rel_posix).parts}
    return bool(parts & set(FORBIDDEN_SEGMENTS))


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(131072), b""):
            h.update(chunk)
    return h.hexdigest()


def mirror_file(src, dst):
    """Copy only when content differs. Returns True if written."""
    if dst.exists() and dst.stat().st_size == src.stat().st_size and \
            digest(dst) == digest(src):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def run(user_claude, dest_root, vault_id):
    copied = 0
    unchanged = 0
    total_bytes = 0
    missing = []
    refused = []

    for src, sub in sources(user_claude, vault_id):
        if not src.exists():
            missing.append(str(src))
            continue
        if src.is_file():
            files = [(src, dest_root / sub)]
        else:
            files = []
            for p in src.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(src)
                if is_forbidden(rel.as_posix()):
                    continue
                files.append((p, dest_root / sub / rel))
        for s, d in files:
            # Belt and braces: the destination itself must never land inside a
            # forbidden segment, whatever the source layout looks like.
            if is_forbidden(d.relative_to(dest_root).as_posix()):
                print(f"SAFETY: refusing forbidden destination {d}")
                return 2, copied, unchanged, total_bytes, refused
            if carries_credential(s):
                # Never mirrored, and if a previous run already copied it,
                # remove that copy now rather than leaving a stale credential.
                refused.append(str(s))
                if d.exists():
                    d.unlink()
                continue
            if mirror_file(s, d):
                copied += 1
            else:
                unchanged += 1
            total_bytes += s.stat().st_size

    if missing:
        for m in missing:
            print(f"MISSING SOURCE: {m}")
        return 2, copied, unchanged, total_bytes, refused
    return 0, copied, unchanged, total_bytes, refused


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-claude", default=str(USER_CLAUDE))
    ap.add_argument("--dest", default=str(VAULT / DEST_REL))
    ap.add_argument("--vault-id", default=VAULT_ID)
    args = ap.parse_args(argv)

    dest_root = Path(args.dest)
    dest_root.mkdir(parents=True, exist_ok=True)
    code, copied, unchanged, total, refused = run(
        Path(args.user_claude), dest_root, args.vault_id)

    # Assert the invariant on the RESULT, not just on the intent: nothing under
    # the destination may sit in a forbidden segment. A mirror that silently
    # carried secrets into git would be worse than no mirror at all.
    leaked = [p for p in dest_root.rglob("*")
              if p.is_file() and is_forbidden(
                  p.relative_to(dest_root).as_posix())]
    if leaked:
        print(f"SAFETY: {len(leaked)} forbidden file(s) present under {dest_root}")
        return 2

    # A refusal is printed loudly and per file. A credential sitting in a file
    # we meant to back up is a standing problem in the SOURCE, not a mirror
    # detail, and silently shrinking the backup would hide it.
    for r in refused:
        print(f"REFUSED (credential-shaped content, not mirrored): {r}")
    print(f"MIRROR copied={copied} unchanged={unchanged} "
          f"refused={len(refused)} bytes={total} dest={dest_root}")
    if code == 0 and refused:
        return 1
    return code


if __name__ == "__main__":
    sys.exit(main())
