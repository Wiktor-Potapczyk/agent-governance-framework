"""Read-only or execution: classify a shell command by what it runs.

Python port of `isReadOnlyCommand` in `.claude/workflows/process-qa.js`
(2026-09-21). The two are kept in step by `test_command_class.py`, which runs
the same table through both. A command is read-only when every segment of it
(split on | || && ; outside quotes) starts with a program that only reads, or
is an interpreter whose inline payload only reads. Anything else is execution.
Used by work-verification-check.py to say when a QA turn's Bash calls read
files and ran nothing.
"""
import re

READ_ONLY_PROGRAMS = {
    'cat', 'head', 'tail', 'sed', 'grep', 'rg', 'egrep', 'fgrep', 'awk', 'cut', 'sort', 'uniq', 'wc', 'tr', 'nl', 'tac', 'rev',
    'column', 'paste', 'base64', 'strings', 'od', 'xxd', 'hexdump', 'ls', 'dir', 'find', 'stat', 'file', 'less', 'more', 'echo',
    'printf', 'type', 'tee', 'jq', 'yq', 'get-content', 'gc', 'select-string', 'get-childitem', 'gci', 'get-item', 'format-list',
    'select-object', 'test', '[', '[[', 'true', 'false', 'pwd', 'realpath', 'basename', 'dirname', 'md5sum', 'sha256sum', 'diff',
    'cmp', 'while', 'for', 'if', 'read', 'done', 'do', 'fi', 'then', 'else', 'export', 'set', 'cd', 'sleep',
}
READ_ONLY_GIT = {'show', 'diff', 'log', 'status', 'ls-files', 'blame', 'rev-parse', 'cat-file', 'grep', 'branch', 'remote', 'describe', 'shortlog'}
SHELL_INLINE = {'bash': ['-c'], 'sh': ['-c'], 'zsh': ['-c'], 'dash': ['-c'], 'cmd': ['/c', '/k'], 'powershell': ['-command', '-c'], 'pwsh': ['-command', '-c']}
CODE_INLINE = {'python': ['-c'], 'python3': ['-c'], 'py': ['-c'], 'node': ['-e', '--eval', '-p', '--print'], 'deno': ['eval'], 'ruby': ['-e'], 'perl': ['-e']}
EXEC_MARKERS = re.compile(r"subprocess|os\.system|os\.exec|popen|runpy|importlib|__import__|child_process|execsync|spawn|\bexec\s*\(|\beval\s*\(|start-process|invoke-expression|invoke-command|\biex\b|pytest|unittest|\bmain\s*\(|\.run\s*\(|\bsystem\s*\(", re.IGNORECASE)
READ_ONLY_IMPORTS = {'json', 'io', 're', 'os', 'os.path', 'pathlib', 'sys', 'hashlib', 'csv', 'datetime', 'collections', 'itertools', 'glob', 'fs', 'path', 'string', 'textwrap', 'pprint'}
WRAPPERS = {'sudo', 'time', 'nice', 'env', 'exec', 'command'}


def _tokenize(segment):
    out, cur, q, quoted = [], '', None, False
    for ch in segment:
        if q:
            if ch == q:
                q = None
            else:
                cur += ch
        elif ch in ('"', "'"):
            q, quoted = ch, True
        elif ch.isspace():
            if cur or quoted:
                out.append((cur, quoted))
            cur, quoted = '', False
        else:
            cur += ch
    if cur or quoted:
        out.append((cur, quoted))
    return out


def _segments(command):
    segs, cur, q = [], '', None
    c = str(command)
    i = 0
    while i < len(c):
        ch = c[i]
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in ('"', "'"):
            q = ch
            cur += ch
        elif ch in ('|', '&', ';'):
            if cur.strip():
                segs.append(cur)
            cur = ''
            if ch in ('|', '&') and i + 1 < len(c) and c[i + 1] == ch:
                i += 1
        else:
            cur += ch
        i += 1
    if cur.strip():
        segs.append(cur)
    return segs


def _strip_comment(segment):
    q, out = None, ''
    for ch in segment:
        if q:
            out += ch
            if ch == q:
                q = None
            continue
        if ch in ('"', "'"):
            q = ch
            out += ch
            continue
        if ch == '#':
            break
        out += ch
    return out


def _program_and_args(segment):
    toks = _tokenize(re.sub(r'^[\s(]+', '', segment))
    while toks and not toks[0][1] and re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', toks[0][0]):
        toks.pop(0)
    while toks and toks[0][0].lower() in WRAPPERS:
        toks.pop(0)
    if not toks:
        return '', []
    prog = re.sub(r'\.exe$', '', toks[0][0].replace('\\', '/').split('/')[-1].lower())
    return prog, toks[1:]


def _inline_is_read_only(prog, code):
    if prog in SHELL_INLINE:
        return is_read_only_command(code)
    if EXEC_MARKERS.search(code):
        return False
    for m in re.finditer(r'\b(?:import|from)\s+([A-Za-z_][\w.]*)', code):
        mod = m.group(1).lower()
        if mod not in READ_ONLY_IMPORTS and mod.split('.')[0] not in READ_ONLY_IMPORTS:
            return False
    if re.search(r"\brequire\s*\(\s*['\"](?!fs|path|os)", code, re.IGNORECASE):
        return False
    return True


def _segment_is_read_only(segment):
    prog, args = _program_and_args(segment)
    if not prog:
        return True
    if prog == 'git':
        sub = (args[2][0] if args and args[0][0].lower() == '-c' and len(args) > 2 else (args[0][0] if args else '')).lower()
        return sub in READ_ONLY_GIT
    if prog in READ_ONLY_PROGRAMS:
        return True
    flags = SHELL_INLINE.get(prog) or CODE_INLINE.get(prog)
    if flags:
        for i, (text, _q) in enumerate(args):
            if text.lower() in flags:
                return _inline_is_read_only(prog, args[i + 1][0]) if i + 1 < len(args) else True
        return False
    return False


def is_read_only_command(command):
    """True when nothing in `command` can have run the deliverable."""
    if not command or not isinstance(command, str):
        return True
    c = command.strip()
    if not c or c.lower() == 'none':
        return True
    segments = [x.strip() for x in (_strip_comment(s) for s in _segments(c)) if x.strip()]
    if not segments:
        return True
    return all(_segment_is_read_only(s) for s in segments)
