"""_command_class.py must agree with isReadOnlyCommand in process-qa.js.

One table, run through the Python port here and through the JS function via
node. A drift between the two means the workflow path and the Stop hook would
disagree about what counts as execution."""
import json
import shutil
import subprocess
from pathlib import Path

import _command_class as cc

HOOKS = Path(__file__).resolve().parent
SCRIPT = HOOKS.parent / "workflows" / "process-qa.js"

TABLE = [
    ("cat tool.py", True), ("sed -n 1,40p tool.py", True), ("grep -n onError flow.json", True),
    ("git show HEAD:tool.py", True), ("git diff --stat", True), ("ls -la .claude/hooks", True),
    ("cat tool.py | head -20", True), ("Get-Content tool.py", True), ("none", True), ("", True),
    ('python -c "print(open(\'x.py\').read())"', True), ('bash -c "cat x.py"', True), ('sh -c "sed -n 1,50p x.py"', True),
    ('node -e "console.log(1)"', True), ('powershell -Command "Get-Content x.py"', True), ("'cat' x.py", True),
    ("nl x.py", True), ("while read l; do echo $l; done < x.py", True), ('"C:/Program Files/Python314/python.exe" -c "print(1)"', True),
    ("bash tool.py --input a", False), ("python -m pytest test_tool.py -q", False), ("cat in.json | python tool.py", False),
    ("(cd /c/x && bash tool.py)", False), ('PYTHONIOENCODING=utf-8 "C:/Program Files/Python314/python.exe" tool.py', False),
    ("git commit -m x", False), ("node run.mjs && echo done", False), ("curl -X POST https://h/webhook", False),
    ('"C:/Program Files/Python314/python.exe" -c "import subprocess; subprocess.run([\'x\'])"', False),
    ('bash -c "python tool.py"', False), ('powershell -Command "& ./tool.ps1"', False),
    ('node -e "require(\'./tool.js\').main()"', False),
]


def test_the_python_port_scores_the_table():
    for cmd, expected in TABLE:
        assert cc.is_read_only_command(cmd) is expected, cmd


def test_the_js_function_scores_the_same_table():
    node = shutil.which("node")
    assert node, "node is needed to hold the two implementations together"
    harness = r"""
import { readFileSync } from 'node:fs'
const src = readFileSync(process.argv[2], 'utf8')
const start = src.indexOf('const READ_ONLY_PROGRAMS')
const end = src.indexOf('// A run-class claim must invoke the artifact')
const fn = new Function(src.slice(start, end) + '\nreturn isReadOnlyCommand')()
const table = JSON.parse(readFileSync(process.argv[3], 'utf8'))
console.log(JSON.stringify(table.map(([c]) => fn(c))))
"""
    tmp = HOOKS / "_command_class_harness.tmp.mjs"
    tbl = HOOKS / "_command_class_table.tmp.json"
    try:
        tmp.write_text(harness, encoding="utf-8")
        tbl.write_text(json.dumps(TABLE), encoding="utf-8")
        r = subprocess.run([node, str(tmp), str(SCRIPT), str(tbl)], capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        got = json.loads(r.stdout.strip())
    finally:
        tmp.unlink(missing_ok=True)
        tbl.unlink(missing_ok=True)
    for (cmd, expected), js in zip(TABLE, got):
        assert js is expected, f"js disagrees on {cmd!r}"
