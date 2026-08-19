r"""
Deferral Resurface (Guard B) - standalone sweep + close-advisor hook mode.

Mechanism B countermeasure from the caveman postmortem
(Projects/your-project/work/2026-08-10-caveman-postmortem.md):
MM1 and the "Caveman deep-dive" line both died as tier-scoped deferrals no
mechanism ever resurfaced; a mechanical status sweep then certified unfinished
business as done. This guard makes deferred items visible at project close.

MODE 1, SWEEP (standalone):
    python deferral-resurface.py --project Projects/<Name>
  Scans the project's task_plan.md, work/, and archive/ for deferral-class
  markers:
    - the postmortem's class: Tier 3 / MEDIUM / DEFER(RED) / HOLD
    - unchecked "[ ]" items under a Future Work or Deferred heading
    - REPORT-ONLY and owner-decision-pending lines
  Output: ONE proposal file, Projects/<Name>/work/
  YYYY-MM-DD-deferral-resurface-proposal.md, listing every hit with file path,
  line number, verbatim quote, and an empty owner-disposition line
  (adopt / re-ticket / reject). Each quote is written inside a fenced code
  block (backtick-fence length sized to the quote itself) so raw source
  content, including any dash glyph the source line happens to carry, sits
  on the glyph-exempt surface rather than in the report's own authored prose
  (2026-08-11 post-review fix; see Post-review corrections addendum,
  2026-08-11-plain-language-stage1-build-report.md). A clean project yields
  a proposal stating zero items explicitly. The sweep NEVER edits
  task_plan.md, STATE.md, frontmatter status, or any existing file
  (proposal-generating output only, per the governance-mine precedent).
  Prior proposal files are excluded from scanning so reruns do not quote
  themselves.

MODE 2, CLOSE ADVISOR (PostToolUse Write|Edit hook; fires when invoked with a
  hook payload on stdin and no --project argument): self-scoped to writes that
  set status: done or status: archived in a project-level file
  (Projects/*/STATE.md, PROJECT.md, or task_plan.md frontmatter). On match:
  one-line advisory reminding the closer to run the sweep, plus a fire record.
  NEVER blocks. The advisor exists so this guard does not itself die of
  Mechanism B (a sweep nobody triggers).

Untested surface, named per the build plan: marker recall is heuristic. A
deferral phrased without any marker word is missed. The proposal file's own
header restates this.

Built by the plain-language Stage 1 build (2026-08-11); spec:
.claude/plain-language-rules.md (Guards section). Tests:
test_deferral_resurface.py.

EXIT CODES
  0 = always (both modes; the advisor never blocks, the sweep fails soft).
"""

import json
import os
import re
import sys
from datetime import date

MARKER_CLASS_RE = re.compile(r"\b(?:Tier 3|MEDIUM|DEFER(?:RED)?|HOLD)\b")
REPORT_ONLY_RE = re.compile(r"\bREPORT-ONLY\b|\bowner-decision-pending\b", re.IGNORECASE)
DEFERRAL_HEADING_RE = re.compile(r"^#{1,6}\s.*\b(?:future work|deferred)\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s")
UNCHECKED_RE = re.compile(r"^\s*[-*]\s*\[ \]")
PROPOSAL_SUFFIX = "deferral-resurface-proposal.md"

_STATUS_FLIP_RE = re.compile(r"status:\s*(?:done|archived)\b", re.IGNORECASE)
_PROJECT_FILE_RE = re.compile(
    r"projects[\\/][^\\/]+[\\/](?:STATE\.md|PROJECT\.md|task_plan\.md)$",
    re.IGNORECASE,
)


def _fence_for(text):
    """Return a backtick fence at least one tick longer than the longest run
    of backticks in text, so a quoted line that itself contains backticks
    cannot prematurely close the fence."""
    runs = re.findall(r"`+", text)
    longest = max((len(r) for r in runs), default=0)
    return "`" * max(3, longest + 1)


def scan_file(path, rel):
    """Return hit dicts for one file: {file, line, quote, marker_class}."""
    hits = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except Exception:
        return hits
    in_deferral_section = False
    for line_no, line in enumerate(lines, 1):
        if HEADING_RE.match(line):
            in_deferral_section = bool(DEFERRAL_HEADING_RE.match(line))
        quote = line.strip()
        if not quote:
            continue
        marker = None
        if MARKER_CLASS_RE.search(line):
            marker = "tier/defer/hold class"
        elif REPORT_ONLY_RE.search(line):
            marker = "report-only / owner-decision-pending"
        elif in_deferral_section and UNCHECKED_RE.match(line):
            marker = "unchecked item under a deferral heading"
        if marker:
            hits.append({
                "file": rel, "line": line_no,
                "quote": quote[:200], "marker_class": marker,
            })
    return hits


def sweep(project_dir):
    """Scan the project tree; write exactly one proposal file; return its path."""
    targets = []
    task_plan = os.path.join(project_dir, "task_plan.md")
    if os.path.isfile(task_plan):
        targets.append((task_plan, "task_plan.md"))
    for sub in ("work", "archive"):
        base = os.path.join(project_dir, sub)
        for root, _dirs, files in os.walk(base):
            for name in sorted(files):
                if not name.endswith(".md") or name.endswith(PROPOSAL_SUFFIX):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, project_dir).replace("\\", "/")
                targets.append((full, rel))

    hits = []
    for full, rel in targets:
        hits.extend(scan_file(full, rel))

    today = date.today().isoformat()
    proposal_path = os.path.join(project_dir, "work", f"{today}-{PROPOSAL_SUFFIX}")
    lines = [
        "---",
        f"date: {today}",
        "tags: [audit, planning]",
        "status: waiting",
        "---",
        "",
        "# Deferral-Resurface Proposal (Guard B sweep)",
        "",
        f"Project: `{os.path.basename(os.path.normpath(project_dir))}`. "
        f"Generated by `.claude/hooks/deferral-resurface.py`. PROPOSAL ONLY: "
        f"this sweep edits no existing file; every disposition below is the "
        f"owner's call.",
        "",
        "Untested surface: marker recall is heuristic (Tier 3 / MEDIUM / DEFER / "
        "HOLD / REPORT-ONLY / owner-decision-pending / unchecked items under "
        "Future Work or Deferred headings). A deferral phrased without any "
        "marker word is missed by this sweep.",
        "",
    ]
    if not hits:
        lines.append("Zero deferral-class items found in task_plan.md, work/, and archive/.")
    else:
        lines.append(f"{len(hits)} deferral-class item(s) found:")
        lines.append("")
        for n, hit in enumerate(hits, 1):
            fence = _fence_for(hit["quote"])
            lines.extend([
                f"## Hit {n}: {hit['file']}:{hit['line']} [{hit['marker_class']}]",
                "",
                fence,
                hit["quote"],
                fence,
                "",
                "Owner disposition (adopt / re-ticket / reject): _",
                "",
            ])
    os.makedirs(os.path.dirname(proposal_path), exist_ok=True)
    with open(proposal_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"proposal written: {proposal_path} ({len(hits)} hit(s))")
    return proposal_path


def _log_fire(payload, decision, detail=None):
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire, session_from
        log_fire("deferral-resurface", decision=decision, detail=detail,
                 session=session_from(payload))
    except Exception:
        pass


def advisor():
    """Close-advisor hook mode. Warn-only, fail-open, exit 0 always."""
    try:
        payload_text = sys.stdin.read()
        if not payload_text:
            return 0
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            return 0
        tool_input = payload.get("tool_input") or {}
        file_path = (tool_input.get("file_path") or "").replace("\\", "/")
        if not _PROJECT_FILE_RE.search(file_path):
            return 0
        added = tool_input.get("new_string")
        if added is None:
            added = tool_input.get("content") or ""
        if not _STATUS_FLIP_RE.search(added):
            return 0
        project = "/".join(file_path.split("/")[:-1])
        sys.stderr.write(
            f"[deferral-resurface ADVISE] project closing ({os.path.basename(file_path)} "
            f"sets status done/archived); run "
            f"`python .claude/hooks/deferral-resurface.py --project {project}` "
            f"before certifying done, so tier-scoped deferrals resurface "
            f"(Mechanism B guard). (advisory - write was kept.)\n"
        )
        _log_fire(payload, "warn", file_path)
        return 0
    except Exception:
        return 0  # fail-open


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--project" in args:
        try:
            project_dir = args[args.index("--project") + 1]
        except IndexError:
            print("usage: deferral-resurface.py --project Projects/<Name>")
            return 0
        if not os.path.isabs(project_dir):
            project_dir = os.path.join(os.getcwd(), project_dir)
        try:
            sweep(project_dir)
        except Exception as exc:
            print(f"sweep failed soft: {exc}")
        return 0
    return advisor()


if __name__ == "__main__":
    sys.exit(main())
