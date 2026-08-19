#!/usr/bin/env python3
"""Tests for session-work-orientation.py.

Covers:
  - project resolution: cwd -> Projects/<name> direct match, and the
    scan-Projects/*/-most-recent-STATE.md fallback when cwd does not resolve
  - work/ file counting: N (top-level .md count), M (>30d untouched),
    nested/non-.md exclusion
  - the under-30-day boundary (not stale just inside it, stale just past it)
  - the closed-track heuristic for K: hit, miss, and the "n/a" case when
    task_plan.md is missing
  - empty-payload fail-open: no project resolvable -> silent exit, no crash

Every test builds its own temp `Projects/` tree and monkeypatches the
module's VAULT / PROJECTS_DIR constants onto it; none of this ever touches
the real vault's Projects/ directory.
"""

import importlib.util
import json
import os
import sys
import time
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))


def _load(filename: str, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, str(Path(__file__).parent / filename)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


swo = _load("session-work-orientation.py", "session_work_orientation")

DAY = 24 * 60 * 60


def _touch(path: str, content: str = "x", mtime: float | None = None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _make_project(projects_dir: str, name: str, *, with_state: bool = True):
    """Create Projects/<name>/ with a work/ dir; returns the project path."""
    proj = os.path.join(projects_dir, name)
    os.makedirs(os.path.join(proj, "work"), exist_ok=True)
    if with_state:
        _touch(os.path.join(proj, "STATE.md"), "status: active\n")
    return proj


def _run_main(payload: dict | None):
    """Execute swo.main() with the given payload (None -> empty stdin)."""
    raw = json.dumps(payload) if payload is not None else ""
    with patch("sys.stdin", StringIO(raw)):
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            ret = swo.main()
            return ret, mock_out.getvalue()


class SessionWorkOrientationTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_vault = swo.VAULT
        self._orig_projects = swo.PROJECTS_DIR
        swo.VAULT = self._tmpdir.name
        swo.PROJECTS_DIR = os.path.join(self._tmpdir.name, "Projects")
        os.makedirs(swo.PROJECTS_DIR, exist_ok=True)

    def tearDown(self):
        swo.VAULT = self._orig_vault
        swo.PROJECTS_DIR = self._orig_projects
        self._tmpdir.cleanup()

    def _parse(self, output: str) -> str:
        data = json.loads(output.strip())
        return data["hookSpecificOutput"]["additionalContext"]

    # ------------------------------------------------------------------
    # Project resolution
    # ------------------------------------------------------------------

    def test_cwd_direct_match_resolves_project(self):
        """cwd inside Projects/<name>/... resolves that project directly,
        even when another project has a more recently touched STATE.md."""
        proj_a = _make_project(swo.PROJECTS_DIR, "ProjA")
        _make_project(swo.PROJECTS_DIR, "ProjB")  # more "active" by mtime below
        now = time.time()
        os.utime(os.path.join(swo.PROJECTS_DIR, "ProjB", "STATE.md"), (now, now))
        os.utime(os.path.join(proj_a, "STATE.md"), (now - DAY, now - DAY))
        _touch(os.path.join(proj_a, "work", "note.md"), mtime=now)

        ret, out = _run_main({"cwd": os.path.join(proj_a, "some", "subdir")})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertIn("ProjA", ctx)
        self.assertNotIn("ProjB", ctx)

    def test_scan_fallback_picks_most_recently_touched_project(self):
        """cwd is the vault root (no project match) -> scan Projects/*/ and
        pick the candidate whose STATE.md mtime is newest."""
        now = time.time()
        proj_old = _make_project(swo.PROJECTS_DIR, "Old")
        proj_new = _make_project(swo.PROJECTS_DIR, "New")
        os.utime(os.path.join(proj_old, "STATE.md"), (now - 5 * DAY, now - 5 * DAY))
        os.utime(os.path.join(proj_new, "STATE.md"), (now, now))
        _touch(os.path.join(proj_new, "work", "note.md"), mtime=now)

        ret, out = _run_main({"cwd": swo.VAULT})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertIn("New", ctx)

    def test_project_without_work_dir_is_skipped_by_scan(self):
        """A project lacking work/ is not a valid scan candidate."""
        no_work_proj = os.path.join(swo.PROJECTS_DIR, "NoWork")
        os.makedirs(no_work_proj, exist_ok=True)
        _touch(os.path.join(no_work_proj, "STATE.md"))
        has_work = _make_project(swo.PROJECTS_DIR, "HasWork")
        _touch(os.path.join(has_work, "work", "note.md"))

        ret, out = _run_main({"cwd": swo.VAULT})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertIn("HasWork", ctx)

    # ------------------------------------------------------------------
    # Work-dir counting (N, M) + exclusions
    # ------------------------------------------------------------------

    def test_basic_file_count_and_content(self):
        proj = _make_project(swo.PROJECTS_DIR, "PROJ-999")
        now = time.time()
        for i in range(3):
            _touch(os.path.join(proj, "work", f"note-{i}.md"), mtime=now)

        ret, out = _run_main({"cwd": proj})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertEqual(
            ctx,
            "[WORK-DIR ORIENTATION] PROJ-999: 3 work files, 0 untouched over 30 days, "
            "n/a from closed tracks",
        )

    def test_nested_and_non_md_files_excluded_from_count(self):
        """Single-pass os.scandir on work/ must not descend into subdirs, and
        must ignore non-.md files."""
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "real.md"), mtime=now)
        _touch(os.path.join(proj, "work", "notes.txt"), mtime=now)
        _touch(os.path.join(proj, "work", "backups", "old.md"), mtime=now)

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("1 work files", ctx)

    def test_under_30_day_boundary(self):
        """A file just inside 30 days is NOT stale; one just past it IS."""
        proj = _make_project(swo.PROJECTS_DIR, "Boundary")
        now = time.time()
        # Safely inside the 30-day window (29d 23h 59m 55s old).
        _touch(os.path.join(proj, "work", "fresh.md"), mtime=now - swo.STALE_SECONDS + 5)
        # Just past the 30-day window (30d 0h 0m 5s old).
        _touch(os.path.join(proj, "work", "stale.md"), mtime=now - swo.STALE_SECONDS - 5)

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("2 work files", ctx)
        self.assertIn("1 untouched over 30 days", ctx)

    # ------------------------------------------------------------------
    # Closed-track heuristic (K)
    # ------------------------------------------------------------------

    def test_closed_track_heuristic_hit(self):
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "2026-08-01-old-build.md"), mtime=now)
        _touch(
            os.path.join(proj, "task_plan.md"),
            "## Track: Something (2026-08-05): CLOSED RATIFIED\n\n"
            "Shipped via `work/2026-08-01-old-build.md`, done.\n",
        )

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("1 from closed tracks", ctx)

    def test_closed_track_heuristic_miss_when_outside_window(self):
        """The same basename mentioned far past the 300-char window after a
        CLOSED header does not count (and no CLOSED header at all -> 0)."""
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "2026-08-01-old-build.md"), mtime=now)
        padding = "x" * 400
        _touch(
            os.path.join(proj, "task_plan.md"),
            "## Track: Something (2026-08-05): CLOSED RATIFIED\n"
            + padding
            + "\nwork/2026-08-01-old-build.md mentioned too late to count.\n",
        )

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("0 from closed tracks", ctx)

    def test_no_closed_header_at_all_is_zero_not_na(self):
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        _touch(os.path.join(proj, "work", "note.md"))
        _touch(os.path.join(proj, "task_plan.md"), "## Track: Open work\n\n- [ ] todo\n")

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("0 from closed tracks", ctx)

    def test_missing_task_plan_reports_na(self):
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        _touch(os.path.join(proj, "work", "note.md"))
        self.assertFalse(os.path.isfile(os.path.join(proj, "task_plan.md")))

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("n/a from closed tracks", ctx)

    def test_negated_not_closed_header_not_counted(self):
        """A "NOT CLOSED" header must not count as closed."""
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "2026-08-01-old-build.md"), mtime=now)
        _touch(
            os.path.join(proj, "task_plan.md"),
            "## Track: Foo (2026-08-07) - NOT CLOSED, still active\n\n"
            "Shipped via `work/2026-08-01-old-build.md`, done.\n",
        )

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("0 from closed tracks", ctx)

    def test_negated_not_yet_closed_header_not_counted(self):
        """A "NOT YET CLOSED" header must not count as closed."""
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "2026-08-01-old-build.md"), mtime=now)
        _touch(
            os.path.join(proj, "task_plan.md"),
            "## Track: Foo (2026-08-07) - NOT YET CLOSED, still active\n\n"
            "Shipped via `work/2026-08-01-old-build.md`, done.\n",
        )

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("0 from closed tracks", ctx)

    def test_negated_not_yet_closed_hyphenated_header_not_counted(self):
        """A "NOT-YET-CLOSED" header (hyphenated, case varied) must not count."""
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "2026-08-01-old-build.md"), mtime=now)
        _touch(
            os.path.join(proj, "task_plan.md"),
            "## Track: Foo (2026-08-07) - not-yet-closed, still active\n\n"
            "Shipped via `work/2026-08-01-old-build.md`, done.\n",
        )

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("0 from closed tracks", ctx)

    def test_plain_closed_header_still_counted(self):
        """A header carrying both a negated and a plain CLOSED still counts,
        confirming the guard rejects only the negated occurrence, not the
        whole header."""
        proj = _make_project(swo.PROJECTS_DIR, "Proj")
        now = time.time()
        _touch(os.path.join(proj, "work", "2026-08-01-old-build.md"), mtime=now)
        _touch(
            os.path.join(proj, "task_plan.md"),
            "## Track: Foo (2026-08-07) - NOT YET CLOSED before, CLOSED now\n\n"
            "Shipped via `work/2026-08-01-old-build.md`, done.\n",
        )

        ret, out = _run_main({"cwd": proj})
        ctx = self._parse(out)
        self.assertIn("1 from closed tracks", ctx)

    # ------------------------------------------------------------------
    # cwd normalization (dot segments)
    # ------------------------------------------------------------------

    def test_dot_segment_cwd_resolves_via_direct_match(self):
        """A cwd with an embedded `.` segment still direct-matches its
        project, not the scan fallback's most-recently-touched pick."""
        proj_a = _make_project(swo.PROJECTS_DIR, "ProjA")
        _make_project(swo.PROJECTS_DIR, "ProjB")  # more "active" by mtime below
        now = time.time()
        os.utime(os.path.join(swo.PROJECTS_DIR, "ProjB", "STATE.md"), (now, now))
        os.utime(os.path.join(proj_a, "STATE.md"), (now - DAY, now - DAY))
        _touch(os.path.join(proj_a, "work", "note.md"), mtime=now)

        dotted_cwd = os.path.join(swo.PROJECTS_DIR, "ProjA", ".", "subdir")
        ret, out = _run_main({"cwd": dotted_cwd})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertIn("ProjA", ctx)
        self.assertNotIn("ProjB", ctx)

    def test_dot_segment_immediately_after_projects_dir_resolves_directly(self):
        """A `.` segment landing right after Projects/ itself (Projects/./
        ProjA/subdir, before the project name) must still direct-match
        ProjA. This pins the specific raw-string-slice defect: a
        normalized-prefix compare can decide the cwd is inside Projects/
        while a same-length slice of the UN-normalized cwd then misaligns
        and yields "." as the extracted name instead of "ProjA" -- silent
        because the caller's isdir() guard rejects "." and falls through to
        the scan fallback rather than emitting a wrong project name."""
        proj_a = _make_project(swo.PROJECTS_DIR, "ProjA")
        _make_project(swo.PROJECTS_DIR, "ProjB")  # more "active" by mtime below
        now = time.time()
        os.utime(os.path.join(swo.PROJECTS_DIR, "ProjB", "STATE.md"), (now, now))
        os.utime(os.path.join(proj_a, "STATE.md"), (now - DAY, now - DAY))
        _touch(os.path.join(proj_a, "work", "note.md"), mtime=now)

        dotted_cwd = os.path.join(swo.PROJECTS_DIR, ".", "ProjA", "subdir")
        ret, out = _run_main({"cwd": dotted_cwd})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertIn("ProjA", ctx)
        self.assertNotIn("ProjB", ctx)

    # ------------------------------------------------------------------
    # Fail-open
    # ------------------------------------------------------------------

    def test_empty_payload_no_project_fails_open_silently(self):
        """No cwd, no projects on disk at all -> exit 0, zero stdout."""
        ret, out = _run_main(None)
        self.assertEqual(ret, 0)
        self.assertEqual(out, "")

    def test_malformed_payload_json_fails_open(self):
        with patch("sys.stdin", StringIO("{not json")):
            with patch("sys.stdout", new_callable=StringIO) as mock_out:
                ret = swo.main()
        self.assertEqual(ret, 0)
        self.assertEqual(mock_out.getvalue(), "")

    def test_cwd_outside_projects_dir_falls_back_to_scan(self):
        proj = _make_project(swo.PROJECTS_DIR, "OnlyOne")
        _touch(os.path.join(proj, "work", "note.md"))

        ret, out = _run_main({"cwd": "C:\\Users\\someone\\Desktop\\Elsewhere"})
        self.assertEqual(ret, 0)
        ctx = self._parse(out)
        self.assertIn("OnlyOne", ctx)


if __name__ == "__main__":
    unittest.main()
