#!/usr/bin/env python3
"""Cut a CalVer changelog entry + local annotated tag for a repo-sync pass.

Given a repo (a normal git working copy), determines the boundary of the
previous release, collects the commit subjects since that boundary, writes
a generated changelog entry, and creates a local annotated git tag on HEAD
carrying that entry as its message. Never pushes anything — commits and
tags are published by a separate, owner-run push.

Boundary rule (no --repo state beyond git and CHANGELOG.md is consulted):
    1. If any `v*` tags exist, the newest one by (year, month, day, suffix)
       is the boundary.
    2. Otherwise, CHANGELOG.md's dated headings are scanned (both the plain
       `## YYYY-MM-DD: ...` form and this script's own `## vYYYY.MM.DD
       (YYYY-MM-DD)` form). The newest heading dated *strictly before* the
       release date being cut is the boundary — a heading dated the same day
       as the release documents work that belongs to THIS release, not a
       prior one, so it is skipped rather than collapsing the range to zero
       commits. The heading's date is mapped to the last commit at or before
       that date (`git log --before`).
    3. If neither yields a boundary, the full history reachable from HEAD is
       used (a genuinely first-ever release).

Usage:
    python repo_release.py --repo <path> --date YYYY-MM-DD [--dry-run]

Exit codes:
    0  success (entry written + tag created, or dry-run printed)
    1  usage / git / repo-state error
    2  zero commits since the resolved boundary (loud failure, not a no-op)
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

DEFAULT_REPO = (
    Path(__file__).resolve().parents[2]
    / "Projects"
    / "Agent-Governance-Research"
    / "framework-repo"
)

TAG_RE = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?$")
CHANGELOG_PLAIN_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}):")
CHANGELOG_TAG_HEADING_RE = re.compile(
    r"^## v\d{4}\.\d{2}\.\d{2}(?:\.\d+)? \((\d{4}-\d{2}-\d{2})\)"
)


class ReleaseError(RuntimeError):
    """Usage / git / repo-state error (exit 1)."""


class NoCommitsSinceBoundary(RuntimeError):
    """Zero commits since the resolved boundary (exit 2, loud failure)."""


def run_git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise ReleaseError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def tag_sort_key(tag: str) -> tuple[int, int, int, int] | None:
    m = TAG_RE.match(tag)
    if not m:
        return None
    year, month, day, suffix = m.groups()
    return (int(year), int(month), int(day), int(suffix) if suffix else 0)


def list_version_tags(repo: Path) -> list[str]:
    """Return v* release tags, newest first, by (year, month, day, suffix)."""
    out = run_git(repo, "tag", "-l", "v*")
    tags = [t for t in out.splitlines() if t.strip()]
    keyed = [(tag_sort_key(t), t) for t in tags]
    keyed = [(k, t) for k, t in keyed if k is not None]
    keyed.sort(key=lambda kt: kt[0], reverse=True)
    return [t for _, t in keyed]


def read_text_preserve_eol(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    return text.replace("\r\n", "\n"), eol


def write_text_preserve_eol(path: Path, text: str, eol: str) -> None:
    if eol == "\r\n":
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def parse_changelog_headings(changelog_text: str) -> list[date]:
    """Dated headings found in CHANGELOG.md, in file order (newest first)."""
    dates: list[date] = []
    for line in changelog_text.split("\n"):
        m = CHANGELOG_PLAIN_HEADING_RE.match(line)
        if m:
            dates.append(datetime.strptime(m.group(1), "%Y-%m-%d").date())
            continue
        m = CHANGELOG_TAG_HEADING_RE.match(line)
        if m:
            dates.append(datetime.strptime(m.group(1), "%Y-%m-%d").date())
    return dates


def commit_at_or_before(repo: Path, cutoff: date) -> str | None:
    out = run_git(
        repo, "log", "HEAD", f"--before={cutoff.isoformat()} 23:59:59",
        "-1", "--format=%H",
    ).strip()
    return out or None


def determine_boundary(repo: Path, release_date: date) -> tuple[str | None, str]:
    """Return (boundary_ref_or_None, human-readable description)."""
    tags = list_version_tags(repo)
    if tags:
        newest = tags[0]
        return newest, f"newest v* tag: {newest}"

    changelog_path = repo / "CHANGELOG.md"
    headings: list[date] = []
    if changelog_path.exists():
        text, _ = read_text_preserve_eol(changelog_path)
        headings = parse_changelog_headings(text)

    prior = [d for d in headings if d < release_date]
    if prior:
        boundary_date = max(prior)
        commit = commit_at_or_before(repo, boundary_date)
        if commit:
            return (
                commit,
                f"no v* tags; newest CHANGELOG.md heading before {release_date.isoformat()} "
                f"is {boundary_date.isoformat()} (commit {commit[:7]})",
            )
        return (
            None,
            f"no v* tags; CHANGELOG.md heading {boundary_date.isoformat()} found but no "
            "commit exists at/before it; using full history from repo root",
        )

    return (
        None,
        "no v* tags and no CHANGELOG.md entry predating the release date; "
        "using full commit history from repo root",
    )


def collect_commit_subjects(repo: Path, boundary_ref: str | None) -> list[str]:
    range_arg = f"{boundary_ref}..HEAD" if boundary_ref else "HEAD"
    out = run_git(repo, "log", range_arg, "--pretty=format:%s")
    return [line for line in out.split("\n") if line.strip()]


def next_tag_name(repo: Path, release_date: date) -> str:
    base = f"v{release_date:%Y.%m.%d}"
    existing = {t.strip() for t in run_git(repo, "tag", "-l").splitlines() if t.strip()}
    if base not in existing:
        return base
    n = 1
    while f"{base}.{n}" in existing:
        n += 1
    return f"{base}.{n}"


def build_entry(tag_name: str, release_date: date, subjects: list[str]) -> str:
    heading = f"## {tag_name} ({release_date.isoformat()})"
    bullets = "\n".join(f"- {s}" for s in subjects)
    return f"{heading}\n\n{bullets}"


def prepend_changelog(repo: Path, entry: str) -> Path:
    changelog_path = repo / "CHANGELOG.md"
    if changelog_path.exists():
        text, eol = read_text_preserve_eol(changelog_path)
        lines = text.split("\n")
    else:
        text, eol = "", "\n"
        lines = []

    if lines and lines[0].startswith("# ") and not lines[0].startswith("## "):
        title, rest = lines[0], lines[1:]
        while rest and rest[0] == "":
            rest.pop(0)
        new_lines = [title, "", *entry.split("\n"), "", *rest]
    else:
        new_lines = [*entry.split("\n"), "", *lines]

    new_text = "\n".join(new_lines).rstrip("\n") + "\n"
    write_text_preserve_eol(changelog_path, new_text, eol)
    return changelog_path


def create_tag(repo: Path, tag_name: str, message: str, commit: str = "HEAD") -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(message + "\n")
        msg_path = Path(fh.name)
    try:
        # --cleanup=verbatim: the default `strip` cleanup treats any line
        # starting with "#" as a comment and drops it, which would silently
        # eat the entry's own "## vYYYY.MM.DD (...)" heading line.
        run_git(
            repo, "tag", "-a", tag_name, "-F", str(msg_path),
            "--cleanup=verbatim", commit,
        )
    finally:
        msg_path.unlink(missing_ok=True)


def valid_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--date must be YYYY-MM-DD, got {value!r}") from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=DEFAULT_REPO, help="Path to the repo clone")
    parser.add_argument("--date", type=valid_date, required=True, help="Release date, YYYY-MM-DD")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print the entry and tag name; write nothing"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo = args.repo.resolve()

    if not (repo / ".git").exists():
        print(f"ERROR: {repo} is not a git repository root", file=sys.stderr)
        return 1

    try:
        boundary_ref, boundary_desc = determine_boundary(repo, args.date)
        subjects = collect_commit_subjects(repo, boundary_ref)
        if not subjects:
            raise NoCommitsSinceBoundary(
                f"NO_COMMITS_SINCE_BOUNDARY: zero commits since boundary ({boundary_desc}); "
                "nothing to release."
            )
        tag_name = next_tag_name(repo, args.date)
        entry = build_entry(tag_name, args.date, subjects)
    except NoCommitsSinceBoundary as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ReleaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Boundary: {boundary_desc}")
    print(f"Tag: {tag_name}")
    print(f"Commits: {len(subjects)}")
    print()
    print(entry)

    if args.dry_run:
        return 0

    changelog_path = prepend_changelog(repo, entry)
    try:
        create_tag(repo, tag_name, entry)
    except ReleaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"Wrote {changelog_path}")
    print(f"Created local annotated tag {tag_name} on HEAD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
