"""Tests for lint_pass_enforcement_claims.py (ROAD-9, Pass V).

Declarative-first: written before the implementation. Every test builds its
own miniature vault tree under tmp_path (doctrine file, authority files of
each kind, fixture settings JSON, fixture registry) and runs the pass with
explicit --registry-file / --settings-file / --vault-root. No test reads or
writes the live .claude/hooks/_state/ directory.
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "lint_pass_enforcement_claims.py"

RULES_TEXT = (
    "# Fixture rules\n"
    "\n"
    "Intro paragraph, no tier words here.\n"
    "\n"
    "2. Hook-level: on every Write, mismatch emits an advisory warning, "
    "non-blocking, on the 29.2%-would-block measurement "
    "(ruled advisory in fixture 2026-09-08).\n"
    "\n"
    "Trailing paragraph.\n"
)

HOOK_ADVISORY_TEXT = (
    '#!/usr/bin/env python3\n'
    '"""fixture-hook.py (PostToolUse Write, ADVISORY v1, fixture).\n'
    '\n'
    'v1 = ADVISORY: emits a violation log.\n'
    '     Does NOT block the Write.\n'
    '"""\n'
    'import sys\n'
    'sys.exit(0)\n'
)

HOOK_DENY_TEXT = (
    '#!/usr/bin/env python3\n'
    '"""fixture-deny-hook.py (fixture, no header tier markers).\n'
    '"""\n'
    'import json, sys\n'
    'out = {"hookSpecificOutput": {\n'
    '    "permissionDecision": "deny",\n'
    '    "permissionDecisionReason": "fixture",\n'
    '}}\n'
    'print(json.dumps(out))\n'
)

DOCTRINE_TEXT = (
    "# Fixture doctrine\n"
    "\n"
    "- Claim one: No wiki-write-path hook blocks today.\n"
    "- Claim two: the hook is advisory, warn-only, never blocks.\n"
    "- Claim three: fixture-hook.py WIRED (PreToolUse).\n"
)


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8",
    )


def claim(cid, kind, anchor, claimed, authority_file, authority_kind,
          authority_anchor=None):
    c = {
        "id": cid,
        "claim_kind": kind,
        "doctrine_file": "doctrine.md",
        "anchor": anchor,
        "claimed": claimed,
        "authority_file": authority_file,
        "authority_kind": authority_kind,
        "provenance": "fixture",
    }
    if authority_anchor is not None:
        c["authority_anchor"] = authority_anchor
    return c


def rules_claim(claimed="advisory"):
    return claim("fx-rules", "tier", "No wiki-write-path hook blocks today",
                 claimed, "rules.md", "rules_md",
                 authority_anchor="ruled advisory in fixture 2026-09-08")


def hook_claim(claimed="advisory"):
    return claim("fx-hook", "tier",
                 "the hook is advisory, warn-only, never blocks",
                 claimed, "hooks/fixture-hook.py", "hook_source")


def settings_claim(claimed="registered:PreToolUse"):
    return claim("fx-settings", "registration", "fixture-hook.py WIRED",
                 claimed, "settings.json", "settings")


def build_tree(tmp_path, claims, doctrine=DOCTRINE_TEXT, rules=RULES_TEXT,
               hook=HOOK_ADVISORY_TEXT, register_hook=True,
               register_event="PreToolUse"):
    (tmp_path / "doctrine.md").write_text(doctrine, encoding="utf-8",
                                          newline="\n")
    (tmp_path / "rules.md").write_text(rules, encoding="utf-8", newline="\n")
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    (hooks_dir / "fixture-hook.py").write_text(hook, encoding="utf-8",
                                               newline="\n")
    settings = {"hooks": {"PreToolUse": [], "PostToolUse": []}}
    if register_hook:
        settings["hooks"][register_event] = [{
            "matcher": "Write|Edit",
            "hooks": [{"type": "command",
                       "command": "python hooks/fixture-hook.py"}],
        }]
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings, indent=2),
                             encoding="utf-8", newline="\n")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(
        json.dumps({"schema": 1, "generated_iso": "2026-09-08T00:00:00Z",
                    "claims": claims}, indent=2),
        encoding="utf-8", newline="\n")
    return registry_path, settings_path


def run_tree(tmp_path, registry_path, settings_path):
    return run("--registry-file", str(registry_path),
               "--settings-file", str(settings_path),
               "--vault-root", str(tmp_path))


def findings(stdout):
    return [l for l in stdout.splitlines()
            if l.startswith("ENFORCEMENT_CLAIM_STALE")]


def test_all_match_clean(tmp_path):
    reg, st = build_tree(tmp_path,
                         [rules_claim(), hook_claim(), settings_claim()])
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 0, r.stdout + r.stderr
    assert findings(r.stdout) == []
    assert "ENFORCEMENT_CLAIMS claims=3 ok=3 stale=0" in r.stdout


def test_tier_flip_one_finding(tmp_path):
    reg, st = build_tree(tmp_path,
                         [rules_claim(claimed="deny"), hook_claim(),
                          settings_claim()])
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 1, r.stdout + r.stderr
    f = findings(r.stdout)
    assert len(f) == 1
    assert "id=fx-rules" in f[0]
    assert "reason=tier-mismatch" in f[0]
    assert "claimed=deny" in f[0]
    assert "derived=advisory" in f[0]
    assert "ENFORCEMENT_CLAIMS claims=3 ok=2 stale=1" in r.stdout


def test_anchor_missing_is_a_finding(tmp_path):
    doctrine = DOCTRINE_TEXT.replace(
        "- Claim one: No wiki-write-path hook blocks today.\n", "")
    reg, st = build_tree(tmp_path,
                         [rules_claim(), hook_claim(), settings_claim()],
                         doctrine=doctrine)
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 1, r.stdout + r.stderr
    f = findings(r.stdout)
    assert len(f) == 1
    assert "id=fx-rules" in f[0]
    assert "reason=anchor-missing" in f[0]
    assert "derived=none" in f[0]


def test_registration_missing(tmp_path):
    reg, st = build_tree(tmp_path,
                         [rules_claim(), hook_claim(), settings_claim()],
                         register_hook=False)
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 1, r.stdout + r.stderr
    f = findings(r.stdout)
    assert len(f) == 1
    assert "id=fx-settings" in f[0]
    assert "reason=registration-missing" in f[0]
    assert "derived=unregistered" in f[0]


def test_authority_file_absent_exits_2(tmp_path):
    reg, st = build_tree(tmp_path, [rules_claim()])
    (tmp_path / "rules.md").unlink()
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "DERIVATION FAILURE" in r.stdout
    assert findings(r.stdout) == []


def test_malformed_registry_exits_2(tmp_path):
    reg, st = build_tree(tmp_path, [rules_claim()])
    reg.write_text("{not json", encoding="utf-8")
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "DERIVATION FAILURE" in r.stdout


def test_rules_md_zero_tier_keywords_exits_2(tmp_path):
    rules = ("# Fixture rules\n\n"
             "The check exists (ruled advisory in fixture 2026-09-08) "
             "and nothing more is said about it.\n")
    # strip every tier keyword from the ruling region except the anchor
    rules = rules.replace("ruled advisory in fixture",
                          "ruled in fixture")
    claims = [claim("fx-rules", "tier",
                    "No wiki-write-path hook blocks today", "advisory",
                    "rules.md", "rules_md",
                    authority_anchor="ruled in fixture 2026-09-08")]
    reg, st = build_tree(tmp_path, claims, rules=rules)
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "DERIVATION FAILURE" in r.stdout


def test_contradictory_hook_source_exits_2(tmp_path):
    # deny literal in source but PostToolUse-only registration
    claims = [hook_claim(claimed="deny")]
    reg, st = build_tree(tmp_path, claims, hook=HOOK_DENY_TEXT,
                         register_event="PostToolUse")
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "DERIVATION FAILURE" in r.stdout


def test_rules_md_negation_pin_derives_advisory(tmp_path):
    # region reads "non-blocking ... would-block ... advisory": the negated
    # and counterfactual forms are consumed, advisory wins, exit 0
    reg, st = build_tree(tmp_path, [rules_claim()])
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 0, r.stdout + r.stderr
    assert findings(r.stdout) == []
    assert "ok=1 stale=0" in r.stdout


def test_hook_source_advisory_header_derives_advisory(tmp_path):
    # modeled on the live ADVISORY-header shape ("ADVISORY v1",
    # "Does NOT block")
    reg, st = build_tree(tmp_path, [hook_claim()])
    r = run_tree(tmp_path, reg, st)
    assert r.returncode == 0, r.stdout + r.stderr
    assert findings(r.stdout) == []
    assert "ok=1 stale=0" in r.stdout
