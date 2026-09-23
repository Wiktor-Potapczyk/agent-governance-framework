"""Tests for self-healing loop phase (a), TASK-001, TASK-002, TASK-005.

Spec: Projects/Vault-Maintenance/work/2026-09-16-self-healing-loop-spec.md,
section 7. Plan: Projects/Vault-Maintenance/work/backups/
2026-09-16-self-heal-phase-a-plan.md.

Covers:
  - zero occurrences of the literal Python314 interpreter path in settings.json
  - every .py hook command in settings.json routes through .claude/bin/py
  - .claude/bin/py resolver: live version-tuple invocation, VAULT_PYTHON
    precedence, non-existent VAULT_PYTHON falls through to the next candidate
  - identical old-vs-new stdout/exit-code behaviour for the six rewritten
    hook commands
  - .claude/bin/ps1 guard: exits 0 with empty output when PATH has no
    powershell binary
  - .claude/self-heal/ci-settings.json: parses, names exactly the two Gate-1
    guards, every command resolves to an existing file
  - local Gate-1 deny proof: bash-safety-guard.py, run through the resolver,
    denies `git push --force origin main`

Read-only against .claude/hooks/*.py (bash-safety-guard.py,
mcp-irreversible-guard.py, _irreversible_surface.py included): this file
never edits them, only exercises them as subprocesses.

State isolation: HOOK_ACTIVITY_LOG_PATH and GOVERNANCE_LOG_PATH are set to a
per-test tmp file for every subprocess hook invocation below, so no run here
writes to the live hook-activity.jsonl / governance-log.jsonl (both hooks
honor these env overrides; see _governance_logger.py and _event_emit.py).
pre-compact.py, checkpoint.py, and post-compact.py additionally touch state
files that have NO env-var override (~/.claude/pre-compact-recovery.md,
~/.claude/last-checkpoint, .claude/hooks/_state/last-compact.json); those
three are explicitly backed up before and restored after their tests run.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = VAULT / ".claude" / "settings.json"
BIN_PY = VAULT / ".claude" / "bin" / "py"
BIN_PS1 = VAULT / ".claude" / "bin" / "ps1"
HOOKS_DIR = VAULT / ".claude" / "hooks"
CI_SETTINGS_PATH = VAULT / ".claude" / "self-heal" / "ci-settings.json"

CLAUDE_PROJECT_DIR = str(VAULT).replace("\\", "/")

BASH_EXE = shutil.which("bash") or "bash"

LITERAL_PATH_TOKENS = (
    "Python314\\python.exe",
    "Python314/python.exe",
)

SIX_HOOK_NAMES = [
    "qmd-recall-nudge.py",
    "pre-compact.py",
    "post-compact.py",
    "checkpoint.py",
    "prose-codes-check.py",
    "bias-guard.py",
]

# Minimal per-event stdin payload for each of the six hooks, chosen (per each
# hook's own gating logic, read live) to exit quickly with no unintended
# side effect wherever the hook's own gating allows it.
PAYLOADS = {
    "qmd-recall-nudge.py": {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    },
    "pre-compact.py": {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "PreCompact",
    },
    "post-compact.py": {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "PostCompact",
        "reason": "test",
    },
    "checkpoint.py": {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
    },
    "prose-codes-check.py": {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "Stop",
        "stop_hook_active": False,
    },
    "bias-guard.py": {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "SubagentStart",
    },
}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _iter_commands(settings: dict):
    for event, entries in settings.get("hooks", {}).items():
        for entry in entries:
            for h in entry.get("hooks", []):
                cmd = h.get("command")
                if cmd is not None:
                    yield event, cmd


def _load_current_settings():
    return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))


def _load_head_settings():
    """Settings.json as committed at HEAD (pre-TASK-001/002 edit state)."""
    proc = subprocess.run(
        ["git", "show", "HEAD:.claude/settings.json"],
        cwd=str(VAULT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _find_command_for(data, needle):
    matches = [cmd for _event, cmd in _iter_commands(data) if needle in cmd]
    assert len(matches) == 1, f"expected exactly 1 command naming {needle!r}, got {matches}"
    return matches[0]


def _run(cmd, env=None, input_text=None, cwd=None, timeout=15):
    full_env = dict(os.environ)
    full_env["CLAUDE_PROJECT_DIR"] = CLAUDE_PROJECT_DIR
    if env:
        full_env.update(env)
    return subprocess.run(
        cmd,
        cwd=cwd or str(VAULT),
        input=input_text,
        capture_output=True,
        text=True,
        env=full_env,
        timeout=timeout,
    )


def _isolated_log_env(tmp_path):
    """HOOK_ACTIVITY_LOG_PATH / GOVERNANCE_LOG_PATH pointed at scratch files,
    so a subprocess hook run under test never writes the live logs."""
    return {
        "HOOK_ACTIVITY_LOG_PATH": str(tmp_path / "hook-activity.jsonl"),
        "GOVERNANCE_LOG_PATH": str(tmp_path / "governance-log.jsonl"),
        "GATE1_ALARM_LOG_PATH": str(tmp_path / "gate1-alarm.jsonl"),
    }


def _backup_file(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def _restore_file(path, content):
    if content is None:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)


def _checkpoint_state_path():
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, ".claude", "last-checkpoint")


def _recovery_state_path():
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, ".claude", "pre-compact-recovery.md")


def _last_compact_state_path():
    return str(HOOKS_DIR / "_state" / "last-compact.json")


def _run_hook_pair(hook_name, tmp_path, before_each=None):
    """Run the OLD (literal-path) and NEW (resolver) form of one hook command
    with the same minimal stdin payload. Returns (old_result, new_result)."""
    old_data = _load_head_settings()
    new_data = _load_current_settings()
    old_cmd = _find_command_for(old_data, hook_name)
    new_cmd = _find_command_for(new_data, hook_name)

    payload_text = json.dumps(PAYLOADS[hook_name])
    env = _isolated_log_env(tmp_path)

    if before_each:
        before_each()
    old_result = _run([BASH_EXE, "-c", old_cmd], env=env, input_text=payload_text)

    if before_each:
        before_each()
    new_result = _run([BASH_EXE, "-c", new_cmd], env=env, input_text=payload_text)

    return old_result, new_result


# ---------------------------------------------------------------------------
# settings.json portability
# ---------------------------------------------------------------------------

def test_no_python314_literal_path_in_settings_json():
    data = _load_current_settings()
    offenders = [
        (event, cmd) for event, cmd in _iter_commands(data)
        if any(tok in cmd for tok in LITERAL_PATH_TOKENS)
    ]
    assert offenders == [], f"literal Python314 interpreter path still present: {offenders}"


def test_every_py_hook_command_routes_through_bin_py():
    data = _load_current_settings()
    py_commands = [
        (event, cmd) for event, cmd in _iter_commands(data)
        if re.search(r'[^"]+\.py"', cmd)
    ]
    assert len(py_commands) == len(SIX_HOOK_NAMES), py_commands
    for event, cmd in py_commands:
        assert ".claude/bin/py" in cmd, f"{event}: {cmd!r} does not route through .claude/bin/py"


# ---------------------------------------------------------------------------
# .claude/bin/py resolver
# ---------------------------------------------------------------------------

def test_bin_py_resolver_prints_version_tuple_and_exits_zero():
    proc = _run([BASH_EXE, str(BIN_PY), "-c", "import sys; print(sys.version_info[:2])"])
    assert proc.returncode == 0, proc.stderr
    assert re.match(r"^\(\d+, \d+\)$", proc.stdout.strip()), proc.stdout


def test_bin_py_resolver_falls_through_on_nonexistent_vault_python():
    env = {"VAULT_PYTHON": "C:/definitely/does/not/exist/python.exe"}
    proc = _run([BASH_EXE, str(BIN_PY), "-c", "import sys; print(sys.version_info[:2])"], env=env)
    assert proc.returncode == 0, proc.stderr
    assert re.match(r"^\(\d+, \d+\)$", proc.stdout.strip()), proc.stdout


def test_bin_py_resolver_falls_through_when_vault_python_is_a_directory():
    """Self-heal phase (a) fix pass item 3 (adversarial review probe 5,
    reproduced live): `[ -x PATH ]` alone is true for a directory, so a
    VAULT_PYTHON pointing at one used to hard-crash the resolver (exit 126)
    instead of falling through to the next candidate."""
    env = {"VAULT_PYTHON": "C:/Windows"}
    proc = _run([BASH_EXE, str(BIN_PY), "-c", "import sys; print(sys.version_info[:2])"], env=env)
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert re.match(r"^\(\d+, \d+\)$", proc.stdout.strip()), proc.stdout


def test_bin_py_resolver_prefers_vault_python_when_set(tmp_path):
    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/bin/sh\necho STUB-INTERPRETER-INVOKED\n", encoding="utf-8")
    os.chmod(stub, 0o755)
    env = {"VAULT_PYTHON": str(stub)}
    proc = _run([BASH_EXE, str(BIN_PY), "-c", "print('should not run')"], env=env)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "STUB-INTERPRETER-INVOKED", proc.stdout


# ---------------------------------------------------------------------------
# Identical old-vs-new behaviour for the six rewritten hooks
# ---------------------------------------------------------------------------

def test_hook_identical_behaviour_qmd_recall_nudge(tmp_path):
    old, new = _run_hook_pair("qmd-recall-nudge.py", tmp_path)
    assert old.returncode == new.returncode == 0
    assert old.stdout == new.stdout == ""


def test_hook_identical_behaviour_bias_guard(tmp_path):
    old, new = _run_hook_pair("bias-guard.py", tmp_path)
    assert old.returncode == new.returncode == 0
    assert old.stdout == new.stdout == "{}\n"


def test_hook_identical_behaviour_prose_codes_check(tmp_path):
    old, new = _run_hook_pair("prose-codes-check.py", tmp_path)
    assert old.returncode == new.returncode == 0
    assert old.stdout == new.stdout == ""


def test_hook_identical_behaviour_checkpoint(tmp_path):
    """checkpoint.py's stdout depends on wall-clock idle time since the last
    write to ~/.claude/last-checkpoint (no env-var override exists). To make
    the OLD-vs-NEW comparison deterministic, the state file is reset to a
    fixed stale timestamp (300s+ in the past) immediately before EACH of the
    two subprocess runs, so both take the same >=300s branch regardless of
    real elapsed time between the two calls. The file's pre-test content is
    backed up and restored afterward so this test never corrupts the real
    checkpoint-cadence signal."""
    state_path = _checkpoint_state_path()
    original = _backup_file(state_path)
    try:
        def _reset_stale():
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                f.write(str(int(time.time()) - 301))

        old, new = _run_hook_pair("checkpoint.py", tmp_path, before_each=_reset_stale)
        assert old.returncode == new.returncode == 0
        assert old.stdout == new.stdout
        assert "[CHECKPOINT]" in old.stdout
    finally:
        _restore_file(state_path, original)


def test_hook_identical_behaviour_pre_compact(tmp_path):
    """pre-compact.py unconditionally writes ~/.claude/pre-compact-recovery.md
    and resets ~/.claude/last-checkpoint (neither has an env-var override).
    Both files are backed up before this test and restored after, so a live
    recovery snapshot or checkpoint cadence is never corrupted by this run."""
    recovery_path = _recovery_state_path()
    checkpoint_path = _checkpoint_state_path()
    recovery_backup = _backup_file(recovery_path)
    checkpoint_backup = _backup_file(checkpoint_path)
    try:
        old, new = _run_hook_pair("pre-compact.py", tmp_path)
        assert old.returncode == new.returncode == 0
        assert old.stdout == new.stdout == ""
    finally:
        _restore_file(recovery_path, recovery_backup)
        _restore_file(checkpoint_path, checkpoint_backup)


def test_hook_identical_behaviour_post_compact(tmp_path):
    """post-compact.py unconditionally writes
    .claude/hooks/_state/last-compact.json (no env-var override). Backed up
    before this test and restored after."""
    marker_path = _last_compact_state_path()
    marker_backup = _backup_file(marker_path)
    try:
        old, new = _run_hook_pair("post-compact.py", tmp_path)
        assert old.returncode == new.returncode == 0
        assert old.stdout == new.stdout == "{}\n"
    finally:
        _restore_file(marker_path, marker_backup)


# ---------------------------------------------------------------------------
# .claude/bin/ps1 guard
# ---------------------------------------------------------------------------

def test_ps1_guard_exits_zero_silent_when_no_powershell_on_path():
    # A minimal PATH that still resolves bash's own runtime deps (mingw64/usr
    # binaries) but excludes every Windows directory that carries powershell.
    minimal_path = "/usr/bin:/bin:/mingw64/bin"
    env = {"PATH": minimal_path}
    proc = _run(
        [BASH_EXE, str(BIN_PS1), "-ExecutionPolicy", "Bypass", "-NonInteractive", "-File", "does-not-matter.ps1"],
        env=env,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert proc.stderr == ""


def test_ps1_guard_exits_zero_on_non_windows_without_trying_pwsh(tmp_path):
    """Self-heal phase (a) fix pass item 12 (architect review Finding 5):
    on a non-Windows host, .claude/bin/ps1 must exit 0 silently WITHOUT
    ever trying pwsh, since GitHub's hosted Linux/macOS runners carry pwsh
    by default and would otherwise make this branch untested against the
    real target environment. A fake `uname` reporting "Linux" and a fake
    `pwsh` that would print a distinguishing marker if invoked are both
    placed first on PATH; pwsh must never fire."""
    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    uname_stub = fake_bin / "uname"
    uname_stub.write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
    os.chmod(uname_stub, 0o755)
    pwsh_stub = fake_bin / "pwsh"
    pwsh_stub.write_text("#!/bin/sh\necho PWSH-SHOULD-NOT-RUN\n", encoding="utf-8")
    os.chmod(pwsh_stub, 0o755)

    minimal_path = f"{fake_bin}:/usr/bin:/bin:/mingw64/bin"
    env = {"PATH": minimal_path}
    proc = _run(
        [BASH_EXE, str(BIN_PS1), "-ExecutionPolicy", "Bypass", "-NonInteractive", "-File", "does-not-matter.ps1"],
        env=env,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    assert proc.stdout == ""
    assert proc.stderr == ""


# ---------------------------------------------------------------------------
# .claude/self-heal/ci-settings.json
# ---------------------------------------------------------------------------

def test_ci_settings_json_parses():
    data = json.loads(CI_SETTINGS_PATH.read_text(encoding="utf-8"))
    assert "hooks" in data
    assert "PreToolUse" in data["hooks"]


def test_ci_settings_json_names_exactly_the_two_gate1_guards():
    data = json.loads(CI_SETTINGS_PATH.read_text(encoding="utf-8"))
    commands = [cmd for _event, cmd in _iter_commands(data)]
    named = set()
    for cmd in commands:
        for guard in ("bash-safety-guard.py", "mcp-irreversible-guard.py"):
            if guard in cmd:
                named.add(guard)
    assert named == {"bash-safety-guard.py", "mcp-irreversible-guard.py"}
    assert len(commands) == 2, commands


def test_ci_settings_every_command_resolves_to_an_existing_file():
    data = json.loads(CI_SETTINGS_PATH.read_text(encoding="utf-8"))
    for _event, cmd in _iter_commands(data):
        resolved = cmd.replace("$CLAUDE_PROJECT_DIR", CLAUDE_PROJECT_DIR)
        quoted_paths = re.findall(r'"([^"]+)"', resolved)
        file_paths = [p for p in quoted_paths if "/.claude/" in p]
        assert file_paths, resolved
        for p in file_paths:
            assert Path(p).is_file(), f"{p} (from command {cmd!r}) does not exist"


def test_ci_settings_matcher_and_timeout_match_settings_local_json():
    """Self-heal phase (a) fix pass item 9 (adversarial review probe 6,
    'dropped timeout on mcp-irreversible-guard: NEEDS CHANGE'): every guard
    ci-settings.json registers must carry the same matcher AND the same
    timeout (or matching absence of one) as the live, proven registration
    in settings.local.json, so the CI copy is never silently weaker."""
    ci_data = json.loads(CI_SETTINGS_PATH.read_text(encoding="utf-8"))
    local_data = json.loads(
        (VAULT / ".claude" / "settings.local.json").read_text(encoding="utf-8"))

    def _entries_by_guard(data):
        out = {}
        for entry in data.get("hooks", {}).get("PreToolUse", []):
            matcher = entry.get("matcher")
            for h in entry.get("hooks", []):
                cmd = h.get("command", "")
                for guard in ("bash-safety-guard.py", "mcp-irreversible-guard.py"):
                    if guard in cmd:
                        out[guard] = {"matcher": matcher, "timeout": h.get("timeout")}
        return out

    ci_entries = _entries_by_guard(ci_data)
    local_entries = _entries_by_guard(local_data)

    for guard in ("bash-safety-guard.py", "mcp-irreversible-guard.py"):
        assert guard in ci_entries, f"{guard} missing from ci-settings.json"
        assert guard in local_entries, f"{guard} missing from settings.local.json"
        assert ci_entries[guard]["matcher"] == local_entries[guard]["matcher"], guard
        assert ci_entries[guard]["timeout"] == local_entries[guard]["timeout"], guard


# ---------------------------------------------------------------------------
# Local Gate-1 deny proof (spec TASK-005)
# ---------------------------------------------------------------------------

def test_bash_safety_guard_denies_force_push_to_main_via_resolver(tmp_path):
    payload = {
        "session_id": "test-self-heal-phase-a",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push --force origin main"},
    }
    env = _isolated_log_env(tmp_path)
    proc = _run(
        [BASH_EXE, str(BIN_PY), str(HOOKS_DIR / "bash-safety-guard.py")],
        env=env,
        input_text=json.dumps(payload),
    )
    # bash-safety-guard.py's main() never calls sys.exit(); the deny signal
    # is carried entirely in the printed JSON's permissionDecision field, not
    # the process exit code (confirmed by direct read of the hook, which has
    # no `sys.exit` anywhere in the file).
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    out = json.loads(proc.stdout)
    hook_output = out["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "deny", out
    assert "force-push" in hook_output["permissionDecisionReason"].lower()
