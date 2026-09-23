r"""
Tests for em-dash-guard.py (Stop hook).

Runs the hook as a subprocess, piping a Claude Code Stop payload to stdin that
points at a temp JSONL transcript. Asserts exit code 2 (block) only when a fancy
dash appears in PROSE, and 0 (allow) otherwise. Run:

    python .claude/hooks/test_em_dash_guard.py
"""

import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "em-dash-guard.py")

# Literal glyphs (consistent with the hook's detection list).
EM = "—"        # U+2014 em dash
EN = "–"        # U+2013 en dash
HBAR = "―"      # U+2015 horizontal bar
MINUS = "−"     # U+2212 minus sign
FIGURE = "‒"    # U+2012 figure dash


def run(assistant_text=None, stop_hook_active=False, transcript_exists=True,
        raw_payload=None, extra_lines=None, content_blocks=None):
    """Invoke the hook with a transcript whose last assistant message is
    `assistant_text` (or explicit `content_blocks`). Returns (returncode, stderr)."""
    tdir = tempfile.mkdtemp()
    tpath = os.path.join(tdir, "transcript.jsonl")
    if transcript_exists:
        lines = list(extra_lines or [])
        if content_blocks is not None:
            lines.append({"type": "assistant", "message": {"content": content_blocks}})
        elif assistant_text is not None:
            lines.append({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": assistant_text}]},
            })
        with open(tpath, "w", encoding="utf-8") as f:
            for ln in lines:
                f.write(json.dumps(ln) + "\n")
    payload = raw_payload
    if payload is None:
        payload = json.dumps({"transcript_path": tpath, "stop_hook_active": stop_hook_active})
    proc = subprocess.run([sys.executable, HOOK], input=payload.encode("utf-8"),
                          capture_output=True)
    return proc.returncode, proc.stderr.decode("utf-8", "replace")


CASES = []


def case(name, want_block, **kw):
    CASES.append((name, want_block, kw))


# --- Blocking cases (exit 2) ---
case("em dash in prose", True, assistant_text=f"This is a sentence {EM} with a dash.")
case("en dash in prose", True, assistant_text=f"Range 1{EN}10 in prose.")
case("horizontal bar in prose (substitution glyph)", True,
     assistant_text=f"Done {HBAR} now substituting a bar.")
case("minus sign in prose (substitution glyph)", True,
     assistant_text=f"Done {MINUS} now substituting a minus.")
case("figure dash in prose", True, assistant_text=f"A figure {FIGURE} dash here.")
case("prose line with pipes AND an em dash is NOT exempted", True,
     assistant_text=f"Options: insert | update | delete {EM} pick one.")
case("dash only in the second text block", True, content_blocks=[
    {"type": "text", "text": "First block is clean."},
    {"type": "text", "text": f"Second block {EM} has a dash."},
])

# --- Allow cases (exit 0) ---
case("clean prose, hyphens only", False,
     assistant_text="day-to-day self-hosted well-known. No fancy dashes here.")
case("em dash only inside fenced code", False,
     assistant_text="Here is code:\n```\nx = 1  # note — a dash\n```\nDone.")
case("em dash only inside inline code", False,
     assistant_text="The char `—` is U+2014. I describe it without typing it.")
case("the literal word em-dash with hyphen", False,
     assistant_text="I will not use the em-dash or en-dash in prose.")
case("em dash inside a real markdown table row", False,
     assistant_text=f"| col | val |\n| a | x {EM} y |\n\nText after table.")
case("loop-safety: stop_hook_active suppresses block", False,
     assistant_text=f"Still has {EM} dash but stop_hook_active.", stop_hook_active=True)
case("missing transcript fails open", False, transcript_exists=False)
case("empty stdin fails open", False, raw_payload="")
case("bad json stdin fails open", False, raw_payload="{not json")
case("no assistant text fails open", False, assistant_text=None,
     extra_lines=[{"type": "user", "message": {"content": "hi"}}])


def test_em_dash_guard_cases():
    """pytest entry point for the cases above.

    Added 2026-08-22. `pytest hooks/` collects only test_-prefixed functions
    and classes; every case in this file was reachable solely through main(),
    so pytest collected ZERO tests here while collecting 2,809 across the other
    124 test files. That is how the damage went unnoticed: a scrub pass blanked
    the guard's dash table AND this file's dash fixtures in the same edit, so
    the guard stopped seeing dashes and the only thing that would have said so
    was never being run.

    One function, so the standalone runner keeps working unchanged and CI sees
    the same 17 cases. Per-case granularity is deliberately traded for zero new
    dependencies: the assertion message names every failing case.
    """
    failures = []
    for name, want_block, kw in CASES:
        rc, _err = run(**kw)
        if (rc == 2) != want_block:
            failures.append(f"{name}: want_block={want_block} got_rc={rc}")
    assert not failures, "em-dash-guard cases failed:\n  " + "\n  ".join(failures)


def main():
    passed = failed = 0
    for name, want_block, kw in CASES:
        rc, err = run(**kw)
        got_block = (rc == 2)
        ok = (got_block == want_block)
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"[{status}] {name}: want_block={want_block} got_rc={rc}")
        if not ok and err:
            print(f"        stderr: {err.strip()[:160]}")
    print(f"\nTOTAL: {passed} passed, {failed} failed, {len(CASES)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
