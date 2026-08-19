"""
Bash Safety Guard - PreToolUse Hook (matcher: Bash)
Blocks dangerous shell commands before execution.
Denies: rm -rf, force-push, credential exposure, destructive git ops, git-hook bypass
(--no-verify / -n on commit-class subcommands, -c core.hooksPath= overrides).

DRIFT NOTE (GAP-11, 2026-07-10): _IRREVERSIBLE_FALLBACK_SNAPSHOT below is a FROZEN
copy of _irreversible_surface.py IRREVERSIBLE_BASH_PATTERNS, transcribed 2026-07-10.
Update the snapshot whenever _irreversible_surface.py changes (risk R1; drift is a
process-lint Pass K candidate check).
"""

import sys
import json
import re
import os

_HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HOOK_DIR)


# ---------------------------------------------------------------------------
# FROZEN FALLBACK SNAPSHOT (GAP-11, 2026-07-10): a hardcoded copy of the core
# P1/P2/P3/P5 tuples from _irreversible_surface.py IRREVERSIBLE_BASH_PATTERNS
# (transcribed 2026-07-10; P4 external-curl-write is a predicate, not a tuple,
# so its degraded form stays a no-op predicate but ALARMS, below). Used ONLY when
# the canonical module fails to import, so Gate-1 never degrades to an empty
# surface. FROZEN COPY: update when _irreversible_surface.py changes (risk R1;
# candidate automated check: process-lint Pass K doctrine-drift).
# ---------------------------------------------------------------------------
_IRREVERSIBLE_FALLBACK_SNAPSHOT = [
    # P1: unflagged relative single-file rm
    (r'\brm\s+(?!-)(?!/)(?!["\']?[A-Za-z]:[/\\])[^\s;|&><]+', "rm on unflagged relative file (irreversible delete)"),
    # P2: normal (non-force) git push, tolerating git global options before `push`
    (r'\bgit\s+(?:(?:-C\s+\S+|-c\s+\S+|--[A-Za-z][\w-]*(?:=\S+)?|-[A-Za-z])\s+)*push\b',
     "git push (publication is effectively irreversible)"),
    # P3: DB destructive DDL/DML
    (r'\bDROP\s+(?:TABLE|DATABASE|SCHEMA)\b', "SQL DROP TABLE/DATABASE/SCHEMA (destructive DDL)"),
    (r'\bTRUNCATE\s+(?:TABLE\s+)?\w', "SQL TRUNCATE (destructive DML)"),
    (r'\bDELETE\s+FROM\s+\w+(?![^;]*\bWHERE\b)', "SQL unbounded DELETE (no WHERE clause)"),
    # P5: prod deploy (isolated -p example-build-oracle stage exempt)
    (r'\bdocker[\s-]+compose(?=\s)(?![^|;&\n]*-p\s+example-build-oracle\b)[^|;&\n]*\bup\b',
     "docker compose up (prod deploy; isolated -p example-build-oracle stage exempt)"),
    (r'\bdocker\s+build\b[^|;&\n]*-t\s+\S*:latest\b', "docker build -t *:latest (prod image build)"),
    (r'\bgit\s+archive\b.*\|\s*ssh\b', "git archive | ssh (VPS deploy pipe)"),
]


def _alarm_gate1_surface_degraded(detail):
    """GAP-11 (2026-07-10): make Gate-1 surface degradation LOUD. Appends a
    gate1_surface_degraded event to governance-log.jsonl (same JSONL shape as the
    deny events below) and prints a stderr warning. The GATE1_ALARM_LOG_PATH env
    override exists so unit tests can capture the alarm in a temp log instead of
    polluting the live governance log. Alarm failure must never crash the hook."""
    try:
        from datetime import datetime
        log_path = os.environ.get(
            "GATE1_ALARM_LOG_PATH",
            os.path.join(_HOOK_DIR, "governance-log.jsonl"),
        )
        entry = json.dumps({
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "schema": 2,
            "event": "gate1_surface_degraded",
            "hook": "bash-safety-guard",
            "session": "unknown",
            "detail": str(detail)[:200],
        })
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass
    try:
        sys.stderr.write(
            "BASH-SAFETY-GUARD WARNING: _irreversible_surface unavailable "
            "(%s); Gate-1 running on FROZEN fallback snapshot.\n" % str(detail)[:200]
        )
    except Exception:
        pass


# Two-Gate Gate-1 (2026-06-16): import the NEW canonical irreversible Bash surface
# from the shared module. These are APPENDED to BLOCKED_PATTERNS below: the existing
# force-push / rm-rf / hook-bypass block stays verbatim and ABOVE them in iteration
# order so its description fidelity is preserved.
# GAP-11 hardening (2026-07-10): the fallback is no longer fail-open-to-empty. On
# import failure the hook alarms (governance-log + stderr) and enforces the FROZEN
# snapshot above. Never [].
try:
    from _irreversible_surface import IRREVERSIBLE_BASH_PATTERNS
except Exception as _exc:
    _alarm_gate1_surface_degraded("IRREVERSIBLE_BASH_PATTERNS import failed: %r" % (_exc,))
    IRREVERSIBLE_BASH_PATTERNS = list(_IRREVERSIBLE_FALLBACK_SNAPSHOT)

# Two-Gate Gate-1 (2026-06-17): the external-curl-write deny is a PARSING predicate
# (replaces the old whole-segment-loopback P4 regex: confirmed under-block, pentest
# wf_aeee55d3-224 HIGH #B). It runs as a dedicated block in main() on the inert-stripped
# command. GAP-11 (2026-07-10): the ImportError fallback stays a no-op predicate (a
# frozen predicate copy is optional per spec) but the degradation now ALARMS loudly.
try:
    from _irreversible_surface import curl_external_write
except Exception as _exc:
    _alarm_gate1_surface_degraded("curl_external_write import failed: %r" % (_exc,))

    def curl_external_write(_command):
        return (False, None)

# owner ruling 2026-08-13: writes to hosts we own warn instead of denying. The
# fallback returns False so a degraded import keeps the STRICTER behaviour (deny),
# never the looser one.
try:
    from _irreversible_surface import curl_write_targets_warn_hosts_only
except Exception:

    def curl_write_targets_warn_hosts_only(_command):
        return False


# H2 fix (2026-04-18): pre-strip known-inert string contexts so blocked-pattern
# matches don't hit content inside string literals. A full shlex tokenizer
# would be the rigorous fix; this targeted preprocessor handles the 90% case
# (python -c, bash -c, grep patterns, echo, heredocs) without over-engineering.
# Rationale: the dangerous pattern `rm -rf /` should only be blocked when it
# would actually execute, not when it appears inside `python -c "print('rm -rf /')"`
# or `grep 'rm -rf' logs.txt` or an echo/print about the pattern.
_INERT_CONTEXT_PATTERNS = [
    # `python -c "…"` and `python -c '…'` (double or single quoted body)
    (re.compile(r'\bpython[0-9]*\s+-c\s+"(?:\\.|[^"\\])*"'), "python -c (double)"),
    (re.compile(r"\bpython[0-9]*\s+-c\s+'(?:\\.|[^'\\])*'"), "python -c (single)"),
    # `bash -c "…"` / `sh -c "…"` / `cmd -c` etc
    (re.compile(r'\b(?:bash|sh|zsh|cmd)\s+-c\s+"(?:\\.|[^"\\])*"'), "sh -c (double)"),
    (re.compile(r"\b(?:bash|sh|zsh|cmd)\s+-c\s+'(?:\\.|[^'\\])*'"), "sh -c (single)"),
    # `grep 'pattern'` / `grep -E "pattern"` etc: pattern is not a command
    (re.compile(r'\bgrep(?:\s+-[a-zA-Z]+)*\s+"(?:\\.|[^"\\])*"'), "grep (double)"),
    (re.compile(r"\bgrep(?:\s+-[a-zA-Z]+)*\s+'(?:\\.|[^'\\])*'"), "grep (single)"),
    # `echo "…"` / `printf "…"`: output, not execution
    (re.compile(r'\b(?:echo|printf)\s+"(?:\\.|[^"\\])*"'), "echo/printf (double)"),
    (re.compile(r"\b(?:echo|printf)\s+'(?:\\.|[^'\\])*'"), "echo/printf (single)"),
    # `-m "…"` / `-m '…'`: commit/tag message bodies are text, not shell.
    # Prevents false-positives like `git commit -m "added --no-verify support"`.
    # Negative lookbehind (?<!\w) ensures `-m` is a flag, not part of a longer word.
    (re.compile(r'(?<!\w)-m\s*"(?:\\.|[^"\\])*"'), "-m message (double-quoted, optional space)"),
    (re.compile(r"(?<!\w)-m\s*'(?:\\.|[^'\\])*'"), "-m message (single-quoted, optional space)"),
    # Heredocs: <<EOF … EOF (common delimiters)
    (re.compile(r'<<[-~]?\s*(\w+)\b[\s\S]*?^\1\b', re.MULTILINE), "heredoc"),
    (re.compile(r"<<[-~]?\s*'(\w+)'[\s\S]*?^\1\b", re.MULTILINE), "heredoc (single-quoted delim)"),
]


# Constructs whose exact boundaries this simple quote scanner does NOT model:
# command substitution (backtick, $(...)) , process substitution (<(...), >(...)),
# and ANSI-C / locale special quoting ($'...', $"..."). If any appear, we refuse to
# strip comments at all: see _strip_trailing_comments.
_COMMENT_UNSAFE_TOKENS = ("`", "$(", "$'", '$"', "<(", ">(")


def _strip_trailing_comments(command):
    """Replace unquoted bash `#` comments with a space so destructive keywords
    inside a trailing comment (`ls # DROP TABLE x later`) don't trigger a false
    deny (QA finding 2026-06-16).

    SAFETY GUARD (review 2026-06-16): if the command contains command/process
    substitution or special quoting (backtick, ``$(``, ``$'``, ``$"``, ``<(``,
    ``>(``), this scanner CANNOT reliably tell where those constructs end, so it
    returns the command UNCHANGED and strips nothing. Empirically, a `#` that this
    scanner would treat as a comment can sit inside such a construct while bash
    executes a `; cmd` tail right after the construct closes (confirmed for backtick
    substitution and ``$'...'`` ANSI-C quoting): stripping to end-of-line would then
    hide that live command (a critical under-block hole). Bailing reverts to the
    pre-change behavior (whole command scanned) for these rare cases: at worst an
    over-block, never an under-block.

    For the remaining (common) case with no such construct, this is quote-aware: a
    `#` inside single/double quotes is literal and left intact; a `#` only opens a
    comment when unquoted, unescaped, and at line-start or preceded by whitespace,
    running to end-of-line. Within that restricted grammar, bash never executes text
    after the comment marker, so stripping the span is safe."""
    if any(tok in command for tok in _COMMENT_UNSAFE_TOKENS):
        return command
    out = []
    in_single = False
    in_double = False
    escaped = False
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\" and not in_single:
            out.append(ch)
            escaped = True
            i += 1
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if ch == "#" and not in_single and not in_double:
            prev = command[i - 1] if i > 0 else None
            if prev is None or prev.isspace():
                # Comment runs to end of this line. Replace the span with a space,
                # preserving the newline so multi-line commands keep their structure.
                j = command.find("\n", i)
                out.append(" ")
                if j == -1:
                    break
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_inert_contexts(command):
    """Remove substrings that are known to be string literals or pattern args,
    not executable shell. Returns a cleaned command safe to pattern-match."""
    cleaned = _strip_trailing_comments(command)
    for pattern, _label in _INERT_CONTEXT_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return cleaned


# Windows reserved device names: creating these breaks OneDrive sync (Issue #16604)
WINDOWS_RESERVED_NAMES = {
    "nul", "con", "prn", "aux",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}

# Patterns that should NEVER execute without explicit user approval
BLOCKED_PATTERNS = [
    # Destructive file operations
    (r'\brm\s+(-[rfRF]+\s+|--force\s+|--recursive\s+)*/(?!(?:[a-z]/)?tmp/)', "rm -rf on non-tmp directory"),
    (r'\brm\s+(-[rfRF]+\s+)+\.(?![a-zA-Z])', "rm -rf on current directory"),
    # Destructive git operations
    # The option-skipping prefix is shared verbatim with the normal-push WARN row in
    # _IRREVERSIBLE_FALLBACK_SNAPSHOT (P2). Both rows must tolerate git's global options
    # (-C <dir>, -c k=v, --long, -x) sitting between `git` and `push`. Without it these
    # two rows required adjacency, so `git -C <path> push --force` matched neither and
    # fell through to the P2 WARN built for the additive, revertible push: the one
    # unrecoverable git operation was being downgraded to the safe one's treatment.
    # Measured 2026-08-06 by executing this hook over a deny/warn matrix, after the
    # evasion was used unknowingly during a history rewrite the same day.
    (r'\bgit\s+(?:(?:-C\s+\S+|-c\s+\S+|--[A-Za-z][\w-]*(?:=\S+)?|-[A-Za-z])\s+)*push\s+.*--force',
     "git force-push"),
    # `-f` must be its own token: the lookbehind stops a branch named `my-f` matching.
    (r'\bgit\s+(?:(?:-C\s+\S+|-c\s+\S+|--[A-Za-z][\w-]*(?:=\S+)?|-[A-Za-z])\s+)*push\b[^;|&]*?(?<![\w-])-f\b',
     "git force-push (-f)"),
    (r'\bgit\s+reset\s+--hard', "git reset --hard"),
    (r'\bgit\s+clean\s+-[fdxFDX]', "git clean (destructive)"),
    (r'\bgit\s+checkout\s+--\s+\.', "git checkout -- . (discard all changes)"),
    # Hook bypass: commits/pushes that skip pre-commit/pre-push/commit-msg/etc hooks
    # ECC-LEARN-A2 (2026-05-07, architect-revised): block --no-verify and -n short-form
    # scoped to hook-bearing subcommands (commit/push/merge/cherry-pick/rebase/am).
    # Scoping prevents false positives on read-only ops like `git log -S '--no-verify'`
    # (pickaxe diff search) and `git log -n 5` (count flag, also `-n` but on log not commit).
    # Also blocks core.hooksPath= overrides on any git invocation.
    # Known limitations (out of static-scan scope): git aliases that expand to --no-verify
    # are invisible (alias name only); compound shell assignments where --no-verify is
    # constructed before `git` is reached (e.g. `V=--no-verify; git commit $V`) evade
    # the post-`git` lookahead; subprocess wrappers (npm run, make targets) hide internals.
    (r'\bgit\s+(?:commit|push|merge|cherry-pick|rebase|am)\b.*--no-verify\b', "git --no-verify on hook-bearing subcommand (bypasses pre-commit/pre-push/commit-msg/pre-rebase hooks)"),
    (r'\bgit\s+(?:commit|push|merge|cherry-pick|rebase|am)\b.*\s-n\b', "git -n on hook-bearing subcommand (short form of --no-verify)"),
    (r'\bgit\s+.*-c\s+core\.hooksPath\s*=', "git -c core.hooksPath= override (disables hooks for this invocation)"),
    (r'\bGIT_HOOKS_PATH\s*=', "GIT_HOOKS_PATH= env var override (defensive: not a standard git mechanism but listed in spec)"),
    # Credential/secret exposure
    (r'\bcat\b.*\.(env|pem|key|secret)', "reading credential file"),
    (r'\becho\b.*\b(password|secret|token|api.key)\b.*>', "writing credentials to file"),
    # System-level danger
    (r'\bsudo\b', "sudo command"),
    (r'\bchmod\s+777\b', "chmod 777 (world-writable)"),
    (r'\bkill\s+-9\b', "kill -9"),
    # n8n specific
    (r'n8n_delete_workflow', "deleting n8n workflow"),
]

# Two-Gate Gate-1 (2026-06-16): append the NEW irreversible-surface patterns AFTER the
# existing block. Order matters: force-push patterns stay above the generic git-push
# pattern so `git push --force` reports the force-push description, not the normal one.
BLOCKED_PATTERNS.extend(IRREVERSIBLE_BASH_PATTERNS)

# ---------------------------------------------------------------------------
# WIKTOR RULING 2026-08-05: normal `git push` WARNS, it does not block.
#
# The Gate-1 design routed a normal push to a hard deny, on the theory that the
# human gate is the owner re-running it himself via the `!`-prefix bypass. In
# practice the command he pastes is the command the agent just composed and
# handed him verbatim, so the ritual moved no decision to a human: it only cost
# a round trip. His words: "What is the fucking purpose of me copying and
# pasting the exact command you have recommended to me? ... Of course the hook
# should remind you that your action might be destructive and you should think
# twice but not block you entirely."
#
# So the normal-push pattern is LIFTED OUT of BLOCKED_PATTERNS into
# WARN_PATTERNS, which permits the call and returns a caution the agent reads
# before the push runs. Everything else on the irreversible surface is
# untouched, and specifically STILL DENIED:
#   - force-push (--force / -f), which rewrites published history and is the
#     genuinely unrecoverable one, unlike a normal push which is additive and
#     revertable with `git revert`
#   - --no-verify and friends (hook bypass on commit/push/merge/rebase)
#   - unflagged relative rm, SQL DROP/TRUNCATE/unbounded DELETE, prod deploy,
#     external writes
# (Measured 2026-08-05 while verifying this change: a FLAGGED absolute-path
# delete such as `rm -rf /tmp/x` passes silently and always did. That is the
# Family-C calibration, not a hole this edit opened, but it is worth knowing
# the rm floor is narrower than the module docstring's "Denies: rm -rf" reads.)
# The push is still LOGGED to governance-log.jsonl, as a `warn` event rather
# than a `deny`, so the audit trail keeps every publication.
# ---------------------------------------------------------------------------
_NORMAL_PUSH_DESC = "git push (publication is effectively irreversible)"
WARN_PATTERNS = [(p, d) for (p, d) in BLOCKED_PATTERNS if d == _NORMAL_PUSH_DESC]
BLOCKED_PATTERNS = [(p, d) for (p, d) in BLOCKED_PATTERNS if d != _NORMAL_PUSH_DESC]


def _warn_and_allow(command, description, payload):
    """Permit the call, but hand back a caution the agent sees first."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": (
                f"BASH SAFETY (warning, not a block): '{description}'. "
                f"Command: {command[:100]}. "
                "Publishing is visible to everyone with access to the remote and "
                "cannot be un-seen; a wrong commit is corrected with `git revert`, "
                "not by deleting history. Check the branch and the remote are the "
                "ones you mean, then proceed."
            ),
        }
    }
    print(json.dumps(result))
    try:
        from _event_emit import emit_event
        from _governance_logger import session_from
        emit_event(
            event="warn",
            hook="bash-safety-guard",
            session=session_from(payload),
            extra={"pattern": description, "command_prefix": command[:50]},
        )
    except Exception:
        pass


def _warn_and_allow_curl(command, reason, payload):
    """Permit a curl write aimed only at infrastructure we own, with a caution.

    Separate from _warn_and_allow because that one's prose is about publishing a
    git push; the risk here is different and the agent should read the right one."""
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": (
                f"BASH SAFETY (warning, not a block): '{reason}', but every target is a "
                "host we administer, so this proceeds. "
                f"Command: {command[:100]}. "
                "It still changes live state: a workflow write publishes immediately, "
                "and a webhook call runs for real against whatever that workflow does. "
                "Snapshot before you edit, and check you are not pointed at production."
            ),
        }
    }
    print(json.dumps(result))
    try:
        from _event_emit import emit_event
        from _governance_logger import session_from
        emit_event(
            event="warn",
            hook="bash-safety-guard",
            session=session_from(payload),
            extra={"pattern": reason + " [self-hosted target]", "command_prefix": command[:50]},
        )
    except Exception:
        pass


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    command = tool_input.get("command", "")
    if not command:
        return

    # H2 fix (2026-04-18): pre-strip inert string contexts before pattern match.
    # Original command is preserved for logging + Windows-reserved-name check
    # (which operates on actual redirect targets, not string literals).
    scannable = strip_inert_contexts(command)

    # Check each pattern
    for pattern, description in BLOCKED_PATTERNS:
        if re.search(pattern, scannable, re.IGNORECASE):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"BASH SAFETY: Blocked '{description}'. "
                        f"Command: {command[:100]}... "
                        f"If this is intentional, ask the user to confirm."
                    ),
                }
            }
            print(json.dumps(result))
            # Log deny event (truncate command, never log credential content)
            # P1-D + P1-E fix (2026-04-09): added session + schema fields for analytics joins
            try:
                import os
                from _event_emit import emit_event
                from _governance_logger import session_from
                # session_id first, then the transcript stem. Deriving from the
                # transcript alone silently discarded a valid session_id and filed
                # the record as "unknown", which is_test_session reads as synthetic:
                # the hook was labelling its own real denies as test traffic.
                session_id = session_from(payload)
                emit_event(
                    event="deny",
                    hook="bash-safety-guard",
                    session=session_id,
                    extra={"pattern": description, "command_prefix": command[:50]},
                )
            except Exception:
                pass
            return

    # Warn-only surface (owner ruling 2026-08-05): runs AFTER the deny loop, so a
    # force-push -- which is still in BLOCKED_PATTERNS -- denies on the pass above and
    # never reaches here. Only a normal, additive push lands in this block.
    for pattern, description in WARN_PATTERNS:
        if re.search(pattern, scannable, re.IGNORECASE):
            _warn_and_allow(command, description, payload)
            return

    # External-curl-write predicate (Two-Gate Gate-1, 2026-06-17). Runs on the
    # inert-stripped command, AFTER the regex loop and as its own block (mirrors the
    # Windows-reserved-filename block below). Denies a curl that mutates REMOTE state
    # (explicit -X POST/PUT/PATCH/DELETE OR implicit body-bearing POST) while allowing
    # loopback-target writes: without the old under-block where a localhost token in a
    # header/body/query/path/referer suppressed the deny on a genuine remote write.
    # Fail-open: a predicate exception must never crash the hook.
    try:
        curl_deny, curl_reason = curl_external_write(scannable)
    except Exception:
        curl_deny, curl_reason = (False, None)
    if curl_deny:
        # owner ruling 2026-08-13: a write aimed ONLY at infrastructure we own
        # warns and proceeds. Prod, third-party APIs and message senders are
        # untouched and still deny below. Fail toward the deny on any exception.
        try:
            _warn_host_only = curl_write_targets_warn_hosts_only(scannable)
        except Exception:
            _warn_host_only = False
        if _warn_host_only:
            _warn_and_allow_curl(command, curl_reason, payload)
            return
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"BASH SAFETY: Blocked '{curl_reason}'. "
                    f"Command: {command[:100]}... "
                    f"If this is intentional, ask the user to confirm."
                ),
            }
        }
        print(json.dumps(result))
        try:
            import os
            from _event_emit import emit_event
            from _governance_logger import session_from
            session_id = session_from(payload)
            emit_event(
                event="deny",
                hook="bash-safety-guard",
                session=session_id,
                extra={"pattern": curl_reason, "command_prefix": command[:50]},
            )
        except Exception:
            pass
        return

    # Check for Windows reserved filenames in redirect targets and file creation
    # Matches: > nul, > ./nul, touch nul, cat > nul, echo > nul, etc.
    reserved_match = re.search(
        r'(?:>\s*|touch\s+|tee\s+)(?:\./)?(\w+)(?:\s|$)',
        command, re.IGNORECASE
    )
    if reserved_match:
        target_name = reserved_match.group(1).lower().split('.')[0]
        if target_name in WINDOWS_RESERVED_NAMES:
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"BASH SAFETY: Blocked creation of Windows reserved filename '{target_name}'. "
                        f"This breaks OneDrive sync for the entire folder (Issue #16604). "
                        f"Use a different filename."
                    ),
                }
            }
            print(json.dumps(result))
            try:
                import os
                from _event_emit import emit_event
                from _governance_logger import session_from
                session_id = session_from(payload)
                emit_event(
                    event="deny",
                    hook="bash-safety-guard",
                    session=session_id,
                    extra={
                        "pattern": f"windows-reserved-filename:{target_name}",
                        "command_prefix": command[:50],
                    },
                )
            except Exception:
                pass
            return

    # Command is safe: allow silently
    return


if __name__ == "__main__":
    main()
