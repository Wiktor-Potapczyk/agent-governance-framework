"""
_irreversible_surface.py: single source of the NEW canonical irreversible surface.

Two-Gate Autonomy Enforcement, Gate-1 (reversibility HARD FLOOR).
Spec: Projects/your-project/work/2026-06-15-two-gate-enforcement-spec.md
Build plan: .../work/2026-06-16-two-gate-build-implementation-plan.md

This module is imported by BOTH Gate-1 hooks so the canonical surface is defined
exactly once ("extend, do not duplicate"):
  - bash-safety-guard.py  imports IRREVERSIBLE_BASH_PATTERNS and appends it to its
    existing BLOCKED_PATTERNS list. The force-push / rm-rf / hook-bypass block that
    already lives in bash-safety-guard.py is NOT moved here: it stays verbatim in
    its existing block (KEEP-verbatim constraint), and it stays ABOVE these new
    patterns in iteration order so its description fidelity is preserved.
  - mcp-irreversible-guard.py imports IRREVERSIBLE_MCP_TOOLS (PreToolUse mcp__.*).

Every surface here maps to permissionDecision:"deny" in ALL contexts (the vault is
universal bypassPermissions, so "ask" is a no-op: deny is the only stop). The human
gate is the established !-prefix manual-bash bypass (skips PreToolUse hooks), identical
to today's force-push handling.

Regex-composition notes (handed to architect-reviewer):
  - No nested unbounded quantifiers over overlapping classes anywhere below
    (no `(a+)+`-shape) → no catastrophic backtracking. Each `*`/`+` is a single
    star over a single (often negated) class; lookaheads contain at most one `.*`.
  - The new patterns inherit strip_inert_contexts() for free: bash-safety-guard runs
    that pre-stripper before the match loop, so a pattern inside echo/grep/-m/python -c/
    sh -c/heredoc string literals is removed before these patterns ever see it.
  - These patterns assume single-line commands (no re.DOTALL); `[^|;&\\n]` segment
    guards keep curl/docker matches inside one command segment.
"""

import re

# ---------------------------------------------------------------------------
# Gate-1 Bash surface: appended to bash-safety-guard.BLOCKED_PATTERNS.
# Each tuple is (regex_string, human-description). Matched with re.IGNORECASE
# against the inert-context-stripped command, exactly like the existing patterns.
# ---------------------------------------------------------------------------
IRREVERSIBLE_BASH_PATTERNS = [
    # P1: unflagged relative single-file rm (spec row 1b). The existing rm rules
    # only fire on a destructive flag OR a leading-/ path; a plain `rm notes.md`
    # (no flag, relative, non-/tmp) escapes them and executes. Deny it.
    # Target must NOT start with:
    #   - '-' (a flag)
    #   - '/' (Unix absolute: that is 1a's job, and /tmp stays allowed)
    #   - an optional quote then a Windows drive root [A-Za-z]:[/\] (absolute: the
    #     analog of 1a's leading-/; P1 is the RELATIVE-file rule). Without this guard
    #     `rm "C:/Users/.../x.py"` was a confirmed false-positive deny (review 2026-06-16):
    #     the `"` is not `/`, so the old (?!/) guard treated the quoted Windows abs path
    #     as relative and denied a legitimate absolute-path removal.
    # strip_inert_contexts removes rm inside echo/-m/quoted strings before this runs.
    (r'\brm\s+(?!-)(?!/)(?!["\']?[A-Za-z]:[/\\])[^\s;|&><]+', "rm on unflagged relative file (irreversible delete)"),

    # P2: normal (non-force) git push (spec row 3, hard deny per the owner 2026-06-16).
    # Force-push (--force / -f) is denied by the EXISTING block above this one, so it
    # keeps its own description; this catches every other push.
    # The (?:...)* group tolerates git GLOBAL options before the `push` subcommand :
    # `git -C <path> push`, `git -c name=value push`, `git --no-pager push` were all
    # confirmed bypasses (review 2026-06-16) because the old `\bgit\s+push\b` required
    # push to immediately follow git. Each alternative consumes one global-option token
    # (the -C/-c forms also swallow their following argument), then a mandatory \s+; the
    # group cannot match `push` itself (it requires a leading '-'), so `git push origin`
    # still matches with zero group iterations, and `git diff -- push.txt` does NOT
    # (diff/-- are not consumed and push.txt sits after a non-option token).
    (r'\bgit\s+(?:(?:-C\s+\S+|-c\s+\S+|--[A-Za-z][\w-]*(?:=\S+)?|-[A-Za-z])\s+)*push\b',
     "git push (publication is effectively irreversible)"),

    # P3: DB destructive DDL/DML (spec row 2). DROP TABLE/DATABASE/SCHEMA, TRUNCATE,
    # and unbounded DELETE (no WHERE clause). A DROP/DELETE inside an echo/-c string
    # is inert-stripped first: accepted gap.
    (r'\bDROP\s+(?:TABLE|DATABASE|SCHEMA)\b', "SQL DROP TABLE/DATABASE/SCHEMA (destructive DDL)"),
    (r'\bTRUNCATE\s+(?:TABLE\s+)?\w', "SQL TRUNCATE (destructive DML)"),
    # The WHERE lookahead is scoped to the CURRENT statement via [^;]* (not .*): a
    # `DELETE FROM logs; SELECT ... WHERE id=1` was a confirmed false-negative (review
    # 2026-06-16) because `.*` scanned past the `;` and found WHERE in a LATER statement,
    # suppressing the deny on the unbounded DELETE. [^;]* stops at the statement boundary.
    (r'\bDELETE\s+FROM\s+\w+(?![^;]*\bWHERE\b)', "SQL unbounded DELETE (no WHERE clause)"),

    # P4: external curl write: now handled by curl_external_write() predicate, wired
    # as a dedicated block in bash-safety-guard.py main(). The old whole-segment
    # loopback lookahead was a confirmed under-block (pentest wf_aeee55d3-224 HIGH #B):
    # a loopback token anywhere in the segment (query param / path / header value / -d
    # body / --referer) suppressed the deny on a genuine remote write, and the -X-only
    # trigger missed implicit-POST (curl --data ... with no -X). The predicate parses
    # the curl argv, isolates the TARGET URL(s) from flag VALUES, and denies a write
    # only when a target host is non-loopback. It is NOT a regex tuple in this list.

    # P5: prod deploy (spec row 6): docker compose up, docker build -t *:latest,
    # and the `git archive HEAD` piped-to-a-remote-shell VPS-deploy pipe.
    #
    # EXEMPTION (2026-06-18, the owner "the guard is too harsh"): the isolated build-oracle
    # test stage is invoked as `docker compose -p example-build-oracle ...up` and is the
    # REVERSIBLE opposite of a prod deploy: a throwaway, host-port-less, own-network/own-
    # volume project torn down with `down -v` before+after, zero prod contact (the build-
    # oracle spec's 6 isolation invariants). Gate-1 is a reversibility floor, so a provably
    # reversible isolated stage must NOT be on it. The negative lookahead exempts ONLY that
    # named project; a real prod deploy (`-f docker-compose.example-ui.yml`/`.embed.yml`, a
    # bare `docker compose up`, or anything without `-p example-build-oracle`) is STILL denied.
    # The lookahead is segment-scoped ([^|;&\n]*), matching the existing P4/P5 idiom; it is
    # keyed to the honest-agent threat model (an honest agent does not forge the project name
    # to smuggle a prod deploy: the verifier's stated threat model, not an adversary).
    # `compose(?=\s)` requires compose to be the SUBCOMMAND word (followed by whitespace),
    # so the `-f docker-compose.build-oracle.yml` FILENAME token (compose followed by '.')
    # is NOT matched as the command: without this, the filename occurrence (which has no
    # `-p example-build-oracle` ahead of it) defeated the exemption and false-denied the stage.
    (r'\bdocker[\s-]+compose(?=\s)(?![^|;&\n]*-p\s+example-build-oracle\b)[^|;&\n]*\bup\b',
     "docker compose up (prod deploy; isolated -p example-build-oracle stage exempt)"),
    (r'\bdocker\s+build\b[^|;&\n]*-t\s+\S*:latest\b', "docker build -t *:latest (prod image build)"),
    (r'\bgit\s+archive\b.*\|\s*ssh\b', "git archive | ssh (VPS deploy pipe)"),
]


# ---------------------------------------------------------------------------
# Gate-1 MCP surface: imported by mcp-irreversible-guard.py.
#
# NO blanket / wildcard entries (a `mcp__.*` deny would block read tools). Every key
# is an EXACT mcp__<server>__<tool> name. The value is either:
#   - NAME_SUFFICIENT  → deny purely on the tool name (irreversible regardless of args)
#   - a predicate fn   → deny only when predicate(tool_input) is True (dual-use tools
#                         that MUST stay allowed for normal work)
#
# This enumeration is CONSERVATIVE and is FLAGGED FOR WIKTOR SIGN-OFF (spec open
# decision 2). Candidate additions (more hostinger VPS/DNS deletes, etc.) are listed
# in the build record, deliberately not silently included.
# ---------------------------------------------------------------------------
NAME_SUFFICIENT = "name-sufficient"


def _n8n_activation_flip(tool_input):
    """Deny an n8n partial/full workflow update ONLY when it flips active:true
    (spec row 5 'activation flip'). A normal partial edit (the core of the n8n build
    loop) must stay allowed: a blanket name-deny would break the build workflow."""
    if not isinstance(tool_input, dict):
        return False
    if tool_input.get("active") is True:
        return True
    settings = tool_input.get("settings")
    if isinstance(settings, dict) and settings.get("active") is True:
        return True
    return False


def _datatable_destructive(tool_input):
    """Deny n8n datatable management only on destructive operations (drop/delete/
    truncate/clear); allow reads/inserts."""
    if not isinstance(tool_input, dict):
        return False
    op = str(tool_input.get("operation", "")).lower()
    return any(k in op for k in ("drop", "delete", "truncate", "clear"))


IRREVERSIBLE_MCP_TOOLS = {
    # --- name-sufficient deny (irreversible regardless of payload) ---
    "mcp__n8n-mcp__n8n_delete_workflow": NAME_SUFFICIENT,
    "mcp__n8n-priv__n8n_delete_workflow": NAME_SUFFICIENT,
    "mcp__plugin_github_github__delete_file": NAME_SUFFICIENT,
    "mcp__plugin_github_github__merge_pull_request": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__VPS_deleteProjectV1": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__VPS_recreateVirtualMachineV1": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__VPS_restoreBackupV1": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__VPS_restoreSnapshotV1": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__VPS_setRootPasswordV1": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__domains_purchaseNewDomainV1": NAME_SUFFICIENT,
    "mcp__hostinger-mcp__billing_deletePaymentMethodV1": NAME_SUFFICIENT,
    # --- dual-use, payload-conditional deny (must stay allowed for normal work) ---
    "mcp__n8n-mcp__n8n_update_partial_workflow": _n8n_activation_flip,
    "mcp__n8n-mcp__n8n_update_full_workflow": _n8n_activation_flip,
    "mcp__n8n-priv__n8n_update_partial_workflow": _n8n_activation_flip,
    "mcp__n8n-priv__n8n_update_full_workflow": _n8n_activation_flip,
    "mcp__n8n-mcp__n8n_manage_datatable": _datatable_destructive,
    "mcp__n8n-priv__n8n_manage_datatable": _datatable_destructive,
}


def mcp_tool_is_irreversible(tool_name, tool_input):
    """Return (is_irreversible: bool, reason_marker: str|None) for an MCP call.
    Used by mcp-irreversible-guard.py. Unknown / read tools → (False, None)."""
    rule = IRREVERSIBLE_MCP_TOOLS.get(tool_name)
    if rule is None:
        return (False, None)
    if rule == NAME_SUFFICIENT:
        return (True, "name-sufficient")
    # rule is a predicate
    try:
        if rule(tool_input):
            return (True, "payload-condition")
    except Exception:
        return (False, None)
    return (False, None)


# ---------------------------------------------------------------------------
# Gate-1 Bash predicate: external curl write (replaces the old P4 regex).
#
# Wired as a DEDICATED check block in bash-safety-guard.py main() (mirroring the
# Windows-reserved-filename block), NOT as a BLOCKED_PATTERNS regex tuple. Why a
# predicate and not a regex: the deny must key on the TARGET URL's host, but a curl
# command carries loopback tokens in many non-target places (query params, path
# segments, -H header values, -d body, --referer). A regex that scans the whole
# segment for a loopback token (the old P4) under-blocked every remote write that
# merely *mentioned* localhost (pentest wf_aeee55d3-224 HIGH #B). This parses the
# argv, isolates the target(s) from flag VALUES, and decides on the target host.
#
# Pure stdlib (shlex + string ops). No unbounded regex over user input → no ReDoS.
# The one compiled helper-regex (_CURL_SCHEME_RE) is screened at import below.
# ---------------------------------------------------------------------------

# scheme:// prefix (http://, https://, ftp://, ws://, ...): bounded, anchored,
# single class star; no backtracking risk. Screened at import.
_CURL_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")

# Loopback hosts, whole-label match only (the precise inverse of the substring
# defect): localhost-test / localhost.evil.com / 127.0.0.1.attacker.com are REMOTE.
_CURL_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

# Write methods (explicit -X / --request) that mutate remote state.
_CURL_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Explicit non-mutating methods: an explicit GET/HEAD/etc never denies even with a body.
_CURL_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# Body-bearing flags → implicit write intent when no explicit method is given.
_CURL_BODY_FLAGS = frozenset({
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode",
    "--data-ascii", "-F", "--form", "-T", "--upload-file",
    "--json",  # curl 7.82+ JSON shorthand: implies POST + body (2026-06-17 QA #B follow-up).
})
# NOTE (ordering dependency): every flag here that also appears in _CURL_VALUE_FLAGS
# relies on the body-flag branch running BEFORE the value-flag branch in
# _curl_eval_single_invocation. Adding a new body flag ONLY to _CURL_VALUE_FLAGS would
# silently suppress implicit-write detection. Keep new body flags in BOTH sets.

# Value-taking flags whose ARGUMENT must be consumed and must NEVER be treated as a
# target URL. The load-bearing entries are the ones whose values are where incidental
# loopback tokens live (-H/--header/--referer/-e/-d/--data*/-b/--cookie/-F/--form/
# -T/--upload-file). -X/--request and the rest are consumed so their values aren't
# mistaken for targets either. (--url is handled specially: its value IS a target.)
_CURL_VALUE_FLAGS = frozenset({
    "-H", "--header",
    "--referer", "-e",
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--data-ascii",
    "--json",
    "-b", "--cookie",
    "-F", "--form",
    "-T", "--upload-file",
    "-X", "--request",
    "-u", "--user",
    "-A", "--user-agent",
    "-o", "--output",
    "-w", "--write-out",
    "-x", "--proxy",
    "-E", "--cert",
    "--key",
    "--cacert",
    "--connect-to",
    "--resolve",
})

# Bare segment separators shlex leaves as standalone tokens: end of the curl invocation.
_CURL_SEPARATORS = frozenset({"|", ";", "&", "&&", "||"})

# Single-CHARACTER short flags for the bundle walker (Step C glued short-form). In a
# glued bundle like `-sSXDELETE` each char is its own flag; the FIRST value-taking
# char consumes the REST of the bundle as its value (curl semantics). These let the
# walker find an embedded -X / body flag / value flag that is NOT the first char of
# the bundle (review 2026-06-17 under-block: `-sSXDELETE`, `-fXPUT`, `-kXPATCH`,
# `-sSXPOST` were all silently passed because only tok[:2] was inspected).
#   - body short flags: rest of bundle (or next token) is the body → write intent.
_CURL_SHORT_BODY_FLAGS = frozenset({"d", "F", "T"})
#   - other value-taking short flags: rest of bundle (or next token) is the value,
#     which is consumed and must NEVER be treated as a target. Mirrors curl's
#     value-taking single-letter options (-H header, -e referer, -b cookie, etc.).
_CURL_SHORT_VALUE_FLAGS = frozenset({
    "H", "e", "b", "u", "A", "o", "w", "x", "E", "K", "c", "C", "D",
    "m", "P", "r", "t", "U", "Y", "y", "z",
})


def _curl_host_is_loopback(url):
    """Extract the host from a (possibly scheme-less) URL/authority and report
    whether it is a loopback host on a WHOLE-LABEL match."""
    s = url.strip()
    # strip scheme
    s = _CURL_SCHEME_RE.sub("", s)
    # take authority up to first path / query / fragment delimiter
    for delim in ("/", "?", "#"):
        idx = s.find(delim)
        if idx != -1:
            s = s[:idx]
    # strip credentials user:pass@host
    at = s.rfind("@")
    if at != -1:
        s = s[at + 1:]
    # IPv6 bracket form [::1]:port → ::1
    if s.startswith("["):
        end = s.find("]")
        if end != -1:
            host = s[1:end]
            return host.lower() in _CURL_LOOPBACK_HOSTS
    # strip trailing :port (only when the remainder is digits, to avoid eating ::1)
    colon = s.rfind(":")
    if colon != -1 and s[colon + 1:].isdigit():
        s = s[:colon]
    return s.lower() in _CURL_LOOPBACK_HOSTS


def _curl_token_looks_like_target(tok):
    """A non-flag token is a target candidate iff it is a scheme-bearing URL OR a
    scheme-less bare authority (host[:port][/path]). Reject pure local file paths and
    obvious non-URLs (a token with no '.', no ':' and no '/' is not a host)."""
    if not tok or tok.startswith("-"):
        return False
    if _CURL_SCHEME_RE.match(tok):
        return True
    # scheme-less: accept host[:port]/path or bare host. Require a dot (domain) or a
    # ':' (host:port) or a '/' (host/path) so that a stray non-URL positional (rare)
    # is not mistaken for a host. A bare 'localhost' has none of these but is handled
    # because the loopback set is checked directly: but a bare 'localhost' with no
    # path is a read by default anyway. Conservative: treat host-with-dot/colon/slash
    # OR an exact loopback label as a target.
    head = tok.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    bare_host = head.split(":", 1)[0]
    if "." in head or ":" in head or "/" in tok:
        return True
    if bare_host.lower() in _CURL_LOOPBACK_HOSTS:
        return True
    return False


def _curl_eval_single_invocation(tokens, start):
    """Evaluate ONE curl invocation whose `curl` token is at index `start` in the
    `tokens` argv. Parses from `start + 1` up to (but not including) the first bare
    segment separator shlex preserved. Returns (is_remote_write: bool, end_index: int)
    where end_index is the index of the separator that terminated this invocation (or
    len(tokens) if none): the caller resumes the search for the NEXT curl from there.

    is_remote_write is True iff this invocation has WRITE intent (explicit
    -X POST/PUT/PATCH/DELETE OR implicit body-bearing POST) AND at least one TARGET
    host is remote (non-loopback)."""
    method = None
    has_body_flag = False
    targets = []

    i = start + 1
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        # End of this curl invocation at the first bare separator shlex preserved.
        if tok in _CURL_SEPARATORS:
            break

        # --flag=value glued form
        if tok.startswith("--") and "=" in tok:
            flag, _, val = tok.partition("=")
            if flag in ("-X", "--request"):
                method = val.strip().upper()
            elif flag == "--url":
                targets.append(val)
            elif flag in _CURL_BODY_FLAGS:
                has_body_flag = True
            # other --flag=value: value is consumed inline, never a target
            i += 1
            continue

        # Glued short-form bundle (single dash, len>2, not "--"): e.g. -Xvalue, -dvalue,
        # or a bundle of booleans with a value-taking flag somewhere inside (-sSXDELETE).
        # Walk the bundle char by char: each char is its own short flag, and the FIRST
        # value-taking char consumes the REST of the bundle as its value (curl semantics).
        # If that value-taking char is the LAST char (rest empty), its value is the NEXT
        # token. This is the fix for the review under-block where -X embedded after a
        # boolean (e.g. -sSXDELETE) was never seen because only tok[:2] was inspected.
        if (tok.startswith("-") and not tok.startswith("--") and len(tok) > 2):
            body = tok[1:]  # drop the leading '-'
            consumed_next = False
            for k, ch in enumerate(body):
                rest = body[k + 1:]
                if ch == "X":
                    # method = rest of bundle, or NEXT token if rest is empty
                    if rest:
                        method = rest.strip().upper()
                    elif i + 1 < n:
                        method = tokens[i + 1].strip().upper()
                        consumed_next = True
                    break  # X's value consumes the remainder of the bundle
                if ch in _CURL_SHORT_BODY_FLAGS:
                    has_body_flag = True
                    if not rest and i + 1 < n:
                        consumed_next = True  # body value is the next token (still not a target)
                    break  # value consumes the remainder
                if ch in _CURL_SHORT_VALUE_FLAGS:
                    if not rest and i + 1 < n:
                        consumed_next = True  # value is the next token (consumed, not a target)
                    break  # value consumes the remainder
                # else: boolean short flag (e.g. -s, -S, -L, -k): consumes nothing,
                # keep scanning the bundle for a later value-taking flag.
            i += 2 if consumed_next else 1
            continue

        # bare -X / --request : method is the NEXT token
        if tok in ("-X", "--request"):
            if i + 1 < n:
                method = tokens[i + 1].strip().upper()
                i += 2
            else:
                i += 1
            continue

        # bare --url : the NEXT token IS an explicit target
        if tok == "--url":
            if i + 1 < n:
                targets.append(tokens[i + 1])
                i += 2
            else:
                i += 1
            continue

        # bare body flag : sets intent, consumes its value (value is NOT a target)
        if tok in _CURL_BODY_FLAGS:
            has_body_flag = True
            i += 2 if (i + 1 < n) else 1
            continue

        # bare value-taking flag : consume its value (value is NOT a target: this is
        # exactly where incidental loopback tokens live in headers / cookies / referer)
        if tok in _CURL_VALUE_FLAGS:
            i += 2 if (i + 1 < n) else 1
            continue

        # any other flag (boolean) consumes no value
        if tok.startswith("-"):
            i += 1
            continue

        # positional, non-flag, not consumed as a flag value → target candidate
        if _curl_token_looks_like_target(tok):
            targets.append(tok)
        i += 1

    # `i` now points at the terminating separator or len(tokens). Note: a value-taking
    # flag at the very end of the invocation may have consumed the separator token as its
    # "value" (i += 2 stepping over a `|`/`;`); to keep the NEXT-curl search robust we
    # clamp the returned end index to the actual separator position if `i` overshot it.
    end = i
    if end > start + 1:
        for j in range(start + 1, min(i, n)):
            if tokens[j] in _CURL_SEPARATORS:
                end = j
                break

    # Write intent: explicit write method, OR implicit body-bearing write when no
    # explicit method is set. An explicit read method (GET/HEAD/...) is never a write.
    if method in _CURL_READ_METHODS:
        write_intent = False
    elif method in _CURL_WRITE_METHODS:
        write_intent = True
    elif method is None and has_body_flag:
        write_intent = True
    else:
        write_intent = False

    if not write_intent:
        return (False, end)

    if not targets:
        # Cannot identify any target → fail-toward-allow (a write curl with no URL
        # won't reach a remote). Documented as Untested Surface.
        return (False, end)

    # Remote write iff ANY target host is remote (conservative for multi-URL invocations).
    for url in targets:
        if not _curl_host_is_loopback(url):
            return (True, end)
    return (False, end)


def curl_external_write(command):
    """Return (True, reason) to DENY a curl that mutates REMOTE state; (False, None)
    otherwise. A loopback-target write (local API testing) is allowed; a remote-target
    write: explicit -X POST/PUT/PATCH/DELETE OR implicit body-bearing POST: is denied,
    even when localhost tokens appear in non-target positions (headers, body, query,
    path, referer). Fail-toward-allow only when no target can be identified.

    EVERY curl invocation in the command is evaluated, not just the first: a pipeline /
    chain such as `curl <read-url> | curl -X POST <remote>` (pipe), `... ; curl -X DELETE
    <remote>` (semicolon), or `... && curl -X POST <remote>` (AND chain) is denied on the
    SECOND curl. The single-invocation evaluator parses up to the first bare separator,
    then this loop resumes scanning for the next `curl` token after that separator. This
    closes the multi-curl-pipeline under-block (review 2026-06-17): the old single-pass
    form stopped at the first curl and silently allowed a remote write later in the chain.

    Pure stdlib string parsing; never raises for normal input. The caller still wraps
    it in try/except for defense-in-depth (fail-open)."""
    if "curl" not in command:
        return (False, None)

    # Tokenize. shlex models quotes/escapes; fall back to whitespace split on
    # unbalanced quotes so we never crash.
    try:
        import shlex
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    except Exception:
        tokens = command.split()

    n = len(tokens)
    i = 0
    while i < n:
        t = tokens[i]
        # Strip leading shell-grouping / substitution punctuation so a subshell or
        # command-substitution prefix does not hide the curl token (`(curl ...)`,
        # `` `curl ... ``, `$(curl ...`). The old \bcurl\b regex matched these via the
        # word boundary; this preserves that behaviour after the move to tokenizing.
        t_clean = t.lstrip("(`${")
        base = t_clean.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower()
        if base == "curl" or base == "curl.exe":
            is_remote_write, end = _curl_eval_single_invocation(tokens, i)
            if is_remote_write:
                return (True, "external curl write (remote state mutation)")
            # Resume AFTER this invocation's terminating separator (or its end). Guard
            # against a non-advancing index so the loop always terminates.
            i = end + 1 if end > i else i + 1
            continue
        i += 1

    return (False, None)


# ---------------------------------------------------------------------------
# WIKTOR RULING 2026-08-13: a curl write to infrastructure we own WARNS, it does
# not deny. This extends the 2026-08-05 normal-push ruling to the same failure
# mode, in his words: "cant you call it yourself? my only job here is to fucking
# copy and paste a command". The `!`-prefix ritual moves no decision to a human
# when the command he pastes is the one the agent just composed and handed him.
#
# Scope is deliberately narrow. Only hosts listed here warn; EVERYTHING else on
# the external-write surface still denies, specifically including the production
# n8n instance, every third-party API, and every outbound message sender. A write
# to a dev instance we administer is recoverable (workflows have version history
# and we snapshot before editing); a write to prod or to someone else's system is
# the class the Gate-1 floor exists for.
#
# Adding a host here widens the autonomous surface, so it is a deliberate act:
# see finding_narrowing_gate1_deny_pattern_can_open_floor_hole for why this is a
# host-scoped carve-out rather than a loosened pattern. The call is still LOGGED
# to governance-log.jsonl as a `warn`, so the audit trail keeps every write.
# ---------------------------------------------------------------------------
CURL_WARN_HOSTS = frozenset({
    "n8n.internal.example.com",
})

# Path-scoped warn carve-out, added 2026-08-25.
#
# Why this is a PATH list and not another CURL_WARN_HOSTS entry: api.github.com is
# not one surface. The same host serves `DELETE /repos/{o}/{r}` (deletes the
# repository) and `PATCH /repos/{o}/{r}` (can flip a private repo PUBLIC, which
# for an operator under an NDA is the worst outcome available). Host-scoping the
# way the issue tracker was host-scoped would move BOTH of those to warn to buy
# one PR edit. So the carve-out names the paths that are additive and undoable.
#
# Pull-request METADATA only: base branch, title, body, state. Explicitly NOT
# `/merge`, which lands code and is the irreversible half of a PR.
CURL_WARN_URL_PATTERNS = (
    re.compile(
        r"^https?://api\.github\.com/repos/[^/\s]+/[^/\s]+/pulls/\d+/?(?:\?|$)",
        re.IGNORECASE,
    ),
)


def _curl_url_is_warn_scoped(url):
    """True when a single URL is warn-eligible, by host allowlist OR path pattern."""
    for rx in CURL_WARN_URL_PATTERNS:
        if rx.match(url.strip()):
            return True
    return False


_CURL_URL_HOST_RE = re.compile(r"https?://([^/\s\"'>\\]+)", re.IGNORECASE)
_CURL_FULL_URL_RE = re.compile(r"https?://[^\s\"'>\\]+", re.IGNORECASE)


def curl_write_targets_warn_hosts_only(command):
    """True only when the command contains at least one http(s) URL and EVERY one
    of them points at a host in CURL_WARN_HOSTS.

    Conservative by construction: no URL found, or any URL outside the allowlist,
    returns False so the caller keeps denying. A chain that touches a warn host
    AND a third-party host therefore still denies, which is the point -- the
    carve-out must not become a laundering route for an off-list write.

    Pure stdlib; never raises for normal input."""
    urls = _CURL_FULL_URL_RE.findall(command or "")
    hosts = _CURL_URL_HOST_RE.findall(command or "")
    if not hosts:
        return False
    # A URL that matches a warn PATH pattern qualifies on its own, so drop it from the
    # host check below. Conservative by construction: anything not matched still has to
    # clear the host allowlist, and one unqualified URL keeps the whole command denied.
    remaining = []
    for u in urls:
        if not _curl_url_is_warn_scoped(u):
            m = _CURL_URL_HOST_RE.match(u)
            if m:
                remaining.append(m.group(1))
    if urls and not remaining:
        return True
    hosts = remaining or hosts
    for raw in hosts:
        host = raw.strip().lower()
        if "@" in host:            # strip user:pass@
            host = host.rsplit("@", 1)[-1]
        if host.startswith("[") and "]" in host:   # bracketed IPv6
            host = host[1:host.index("]")]
        elif ":" in host:          # strip :port
            host = host.rsplit(":", 1)[0]
        if host not in CURL_WARN_HOSTS:
            return False
    return True


# Self-screen: every Bash pattern must compile. Done at import so a broken regex
# surfaces immediately rather than at first match.
for _rx, _desc in IRREVERSIBLE_BASH_PATTERNS:
    re.compile(_rx)

# The predicate's one compiled helper-regex is screened too (it is compiled at module
# top, but re-compile here to keep the import-time self-screen contract explicit:
# a broken pattern would already have raised at the assignment above).
re.compile(_CURL_SCHEME_RE.pattern)
