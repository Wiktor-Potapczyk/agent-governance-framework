#!/usr/bin/env python3
"""sample-qa-artifacts.py — Action 0.1 calibration sampler (CAL-1).

Samples QA-PASS artifacts from Projects/*/work/ over a configurable lookback
window. Output is a per-artifact block with path, recent commit, and any
embedded QA REPORT or PM CHECKPOINT REPORT block extracted from the file.

Wiktor opens each sampled artifact, reads it, and judges it against the
3-axis calibration rubric in [[2026-05-26-action-0-1-calibration-protocol]].

Usage:
  python .claude/scripts/sample-qa-artifacts.py             # default: 7-day window, sample 8
  python .claude/scripts/sample-qa-artifacts.py --days 14   # custom lookback
  python .claude/scripts/sample-qa-artifacts.py --n 5       # custom sample size
  python .claude/scripts/sample-qa-artifacts.py --seed 42   # reproducible sampling
"""
from __future__ import annotations

import argparse
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Force UTF-8 stdout on Windows so em-dashes in git commit subjects + any
# unicode in QA REPORT bodies don't mojibake under cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

VAULT = Path(os.environ.get("VAULT_ROOT", ""))
PROJECTS = VAULT / "Projects"

QA_BLOCK_RE = re.compile(r"^QA REPORT\b.*?(?=\n\n|\Z)", re.MULTILINE | re.DOTALL)
PM_BLOCK_RE = re.compile(r"^PM CHECKPOINT REPORT\b.*?(?=\n\n|\Z)", re.MULTILINE | re.DOTALL)
PASS_HINT_RE = re.compile(r"\bPASS:?\s*(\d+)\s*/\s*(\d+)", re.IGNORECASE)
QA_COMMIT_RE = re.compile(r"\bQA\s+\d+/\d+\s+PASS\b|\bQA\s+PASS\b", re.IGNORECASE)


def _git(*args, cwd=VAULT):
    try:
        out = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _candidate_files(days: int) -> list[Path]:
    """Files modified in the lookback window, restricted to Projects/*/work/."""
    cutoff = datetime.now() - timedelta(days=days)
    candidates: list[Path] = []
    for work_dir in PROJECTS.glob("*/work"):
        if not work_dir.is_dir():
            continue
        for f in work_dir.glob("*.md"):
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
            except OSError:
                continue
            if mtime >= cutoff:
                candidates.append(f)
    return candidates


def _extract_blocks(path: Path) -> dict:
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {"qa": None, "pm": None, "qa_pass": None}
    qa_match = QA_BLOCK_RE.search(body)
    pm_match = PM_BLOCK_RE.search(body)
    qa_block = qa_match.group(0)[:600] if qa_match else None
    pm_block = pm_match.group(0)[:400] if pm_match else None
    qa_pass = None
    if qa_block:
        m = PASS_HINT_RE.search(qa_block)
        if m:
            n, total = int(m.group(1)), int(m.group(2))
            qa_pass = (n, total)
    return {"qa": qa_block, "pm": pm_block, "qa_pass": qa_pass}


def _last_commit_touching(path: Path) -> str:
    rel = path.relative_to(VAULT).as_posix()
    line = _git("log", "-1", "--format=%h %s", "--", rel)
    return line or "(untracked or no commit)"


def _qa_pass_files_from_git(days: int) -> set[str]:
    """Files touched by commits whose subject/body matches a QA-PASS marker.

    This vault practice: QA REPORTs go to conversation transcripts and commit
    messages, not embedded in artifact bodies. So the QA-PASS signal lives in
    git log, not in file content.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    log = _git("log", f"--since={since}", "--pretty=format:%H%n%B%n--END--", "--name-only")
    if not log:
        return set()

    qa_files: set[str] = set()
    blocks = log.split("--END--")
    for block in blocks:
        lines = [ln for ln in block.strip().splitlines() if ln]
        if len(lines) < 2:
            continue
        # First line is the commit SHA; the body+filenames follow.
        # Heuristic: scan everything; if any line matches QA_COMMIT_RE,
        # collect lines that look like vault paths.
        text = "\n".join(lines)
        if not QA_COMMIT_RE.search(text):
            continue
        for ln in lines[1:]:
            if ln.endswith(".md") and "/work/" in ln.replace("\\", "/"):
                qa_files.add(ln.replace("\\", "/"))
    return qa_files


def _filter_qa_pass(candidates: list[Path], days: int) -> list[tuple[Path, dict]]:
    """Keep artifacts touched by QA-PASS commits OR with embedded QA REPORT block."""
    qa_files = _qa_pass_files_from_git(days)
    kept: list[tuple[Path, dict]] = []
    for path in candidates:
        blocks = _extract_blocks(path)
        rel = path.relative_to(VAULT).as_posix()
        if blocks["qa"] or rel in qa_files:
            blocks["qa_source"] = "embedded" if blocks["qa"] else "commit-message"
            kept.append((path, blocks))
    return kept


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7, help="lookback window in days (default 7)")
    ap.add_argument("--n", type=int, default=8, help="sample size target (default 8; clamped to candidate count)")
    ap.add_argument("--seed", type=int, default=None, help="seed for reproducible sampling")
    ap.add_argument("--qa-only", action="store_true",
                    help="filter to artifacts touched by 'QA PASS' commit OR with embedded QA REPORT block")
    args = ap.parse_args(argv)

    candidates = _candidate_files(args.days)
    pool_label = f"work/*.md files modified within {args.days}d"
    if args.qa_only:
        with_qa = _filter_qa_pass(candidates, args.days)
        pool_label += " with QA PASS in commit-msg OR embedded block"
    else:
        with_qa = [(p, _extract_blocks(p)) for p in candidates]

    if not with_qa:
        print(f"# Calibration sample - {datetime.now().isoformat(timespec='seconds')}")
        print(f"# Pool: {pool_label}")
        print(f"# Candidates found: 0")
        print()
        print("No artifacts match. Try --days <larger> or drop --qa-only.")
        return 0

    rng = random.Random(args.seed)
    sample_size = min(args.n, len(with_qa))
    sample = rng.sample(with_qa, sample_size)

    print(f"# Calibration sample - {datetime.now().isoformat(timespec='seconds')}")
    print(f"# Pool: {pool_label}")
    print(f"# Pool size: {len(with_qa)} / Sampled: {sample_size}")
    print(f"# Seed: {args.seed if args.seed is not None else 'random'}")
    print()
    print("---")

    for i, (path, blocks) in enumerate(sample, 1):
        rel = path.relative_to(VAULT).as_posix()
        commit = _last_commit_touching(path)
        qa_pass = blocks["qa_pass"]
        pass_str = f"{qa_pass[0]}/{qa_pass[1]}" if qa_pass else "n/a"
        qa_source = blocks.get("qa_source", "n/a")
        print(f"\n## {i}. `{rel}`")
        print(f"- Last commit: `{commit}`")
        print(f"- QA PASS: {pass_str} (source: {qa_source})")
        if blocks["qa"]:
            print()
            print("```")
            print(blocks["qa"])
            print("```")
        if blocks["pm"]:
            print()
            print("```")
            print(blocks["pm"])
            print("```")

    print()
    print("---")
    print(f"\n**Calibration rubric:** judge each sample on 3 axes (substantive / gap / cost). "
          f"See [[2026-05-26-action-0-1-calibration-protocol]] section Rubric.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
