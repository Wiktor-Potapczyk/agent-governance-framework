#!/usr/bin/env python
"""PreToolUse hook. Refuses a Write or Edit to a documentation surface whose
prose is too bold-heavy or reaches for a stock AI word, BEFORE the file lands.

WHY THIS EXISTS SEPARATELY FROM plain-language-guard.py. That guard runs
PostToolUse. Its own docstring states the consequence plainly: "the write it is
scanning has already landed on disk", and "genuine write-time prevention would
need a separate PreToolUse companion hook, which is explicitly out of Stage 1
scope". This is that companion. The evidence that the distinction matters is in
that guard's own log: 446 in-scope writes, 266 carrying findings, nothing
changed, because a warning after the fact is free to ignore.

ONE RULE ENGINE, NOT A THIRD. strip_noise, BOLD_SPAN and WORDLIST are imported
from reply-style-guard.py rather than reimplemented, so the reply surface and
the file surface cannot drift apart in what they consider prose or what they
consider a stock word. plain-language-guard.py keeps its own PL-1 to PL-10 rule
set; the two are complementary and stay separate. That split was the
reconciliation a PM checkpoint asked for before this hook was built.

THRESHOLD, and the correction to how it was set. A raw bold COUNT does not
transfer from replies to files: the median guarded file already holds 19 bold
spans simply because it is long. Density does transfer. Measured over 365 files
in the three guarded surfaces, with code, tables and structured blocks stripped:

  bold spans per 1000 prose words: median 15.6, p75 23.7, p90 32.0, max 75.3

This first shipped at 25, firing on 22.5 percent of that corpus, on my own
argument that the vault's 10-percent bar was calibrated for a warn-only hook
where a warning is free, whereas a block before the write costs only a rewrite.
A PM checkpoint rejected that: .claude/rules/plain-language.md sets four gates
before any rule may block (warn rate at or below 10 percent over 14 days and at
least 50 writes, a 20-sample false-positive audit, and explicit owner sign-off),
none of which were run, and the argument for skipping them was mine rather than
a ratified exception. Wiktor named the mechanism, not the number.

So the limit is 33, the tightest value that clears the documented bar, firing on
9.0 percent of the corpus. The argument for 25 was not wrong, but it is a
proposal, and it stays a proposal until the gates are run or the owner rules.
BOLD_PER_1000 is one constant, meant to be tuned from this hook's own log rather
than argued about.

SCOPE. Only the three surfaces plain-language-guard.py already claims:
Projects/*/work/ (excluding work/backups/), Resources/KB/, and the framework
repo's README and docs/. Everything else, including code, STATE.md and
task_plan.md, is untouched. Files under 50 prose words are skipped: a density
ratio over a short file is noise.

FAIL-OPEN. Any internal error allows the write. A broken style guard must never
be able to stop work.

MEASURABILITY. Logs the allow path as well as the block path, for the same
reason the reply guard does: a guard that writes a record only when it blocks
has a false-negative rate nobody can ever measure.
"""

import importlib.util
import json
import os
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

# Bold spans per 1000 prose words. See the docstring for the distribution this
# came from, and why 25 was rejected in favour of the documented bar.
BOLD_PER_1000 = 33

MIN_WORDS = 50

GUARDED = (
    ("projects", "work"),
    ("resources", "kb"),
    ("framework-repo", "docs"),
)


def _engine():
    """Import the reply guard's rule engine. One definition of prose and one
    wordlist across both surfaces, so they cannot drift."""
    path = os.path.join(HOOKS_DIR, "reply-style-guard.py")
    spec = importlib.util.spec_from_file_location("reply_style_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def in_scope(path):
    """True only for the three documentation surfaces, excluding work/backups/."""
    if not path or not path.lower().endswith(".md"):
        return False
    p = path.replace("\\", "/").lower()
    if "/work/backups/" in p:
        return False
    if "/projects/" in p and "/work/" in p:
        return True
    if "/resources/kb/" in p:
        return True
    if "/framework-repo/" in p and ("/docs/" in p or p.endswith("/readme.md")):
        return True
    return False


def content_of(tool_name, tool_input):
    """The prose about to be written. For Write that is the whole file; for Edit
    it is the replacement text, which is the only part this write introduces."""
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name in ("Edit", "MultiEdit"):
        if "new_string" in tool_input:
            return tool_input.get("new_string", "")
        edits = tool_input.get("edits") or []
        return "\n".join(e.get("new_string", "") for e in edits if isinstance(e, dict))
    return ""


def _log(decision, path=None, detail=None):
    """One record per in-scope invocation, allow as well as block. Never raises.

    Converged onto _governance_logger.log_fire 2026-08-31 (owner-delegated
    dark-controls fix): the hand-rolled append wrote the same sink but was
    invisible to the matrix scan's helper signatures, so this hook read as
    DARK while demonstrably live. The TESTING seam stays ours; log_fire adds
    the HOOK_ACTIVITY_LOG_PATH redirect on top, strictly more isolated."""
    if os.environ.get("WRITE_STYLE_GUARD_TESTING"):
        return
    try:
        sys.path.insert(0, HOOKS_DIR)
        from _governance_logger import log_fire
        # Path first (architect finding 2026-08-31): log_fire truncates
        # detail to 200 chars, so the queryable path must survive truncation.
        log_fire("write-style-guard", decision=decision,
                 detail=((f"path={path}" + (f" {detail}" if detail else ""))
                         if path else detail),
                 session=_log.session)
    except Exception:
        pass


_log.session = None


def evaluate(text, mod):
    """Return a list of (rule, detail). Separated from I/O so the tests can
    drive it directly and so the density maths is inspectable."""
    prose = mod.strip_noise(text)
    words = len(prose.split())
    found = []
    if words >= MIN_WORDS:
        bold = len(mod.BOLD_SPAN.findall(prose))
        density = bold / words * 1000
        if density >= BOLD_PER_1000:
            found.append((
                "bold",
                "%d bold spans over %d words of prose, %.0f per 1000 (limit %d)"
                % (bold, words, density, BOLD_PER_1000),
            ))
    for pattern, label in mod.WORDLIST:
        import re
        m = re.search(pattern, prose, flags=re.IGNORECASE)
        if m:
            found.append(("wordlist", "%s (%s)" % (m.group(0), label)))
    return found


def allow():
    return None


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    # Valid JSON of the wrong shape is still unusable input. Without this,
    # a bare array or scalar reached .get and printed an AttributeError
    # traceback. See test_hooks_survive_malformed_payload.py.
    if not isinstance(payload, dict):
        return 0
    _log.session = payload.get("session_id")
    try:
        tool_name = payload.get("tool_name", "")
        tool_input = payload.get("tool_input", {})
        if isinstance(tool_input, str):
            try:
                tool_input = json.loads(tool_input)
            except Exception:
                tool_input = {}
        path = tool_input.get("file_path", "")
        if not in_scope(path):
            return 0
        text = content_of(tool_name, tool_input)
        if not text.strip():
            return 0
        mod = _engine()
        violations = evaluate(text, mod)
    except Exception as exc:
        _log("skip", detail="internal error: %s" % type(exc).__name__)
        return 0

    if not violations:
        _log("allow", path=path)
        return 0

    detail = "; ".join("%s: %s" % (r, d) for r, d in violations)
    reason_lines = ["WRITE STYLE: rewrite this content before saving it."]
    for rule, d in violations:
        if rule == "bold":
            reason_lines.append(
                "  Too much bold: %s. Let the sentences carry the weight." % d
            )
        else:
            reason_lines.append(
                "  Stock AI phrasing: %s. Use the plain word, or put it in "
                "backticks if you are naming the word rather than using it." % d
            )
    reason_lines.append(
        "  Code, tables and structured blocks are exempt and were not counted."
    )
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "\n".join(reason_lines),
        }
    }
    print(json.dumps(result))
    _log("block", path=path, detail=detail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
