"""Declarative-first suite for .claude/scripts/o17_portability_manifest.py (O17).

Written before the generator exists (red state on record). The module import
lives in a pytest fixture, not at module top, so collection succeeds while
every test fails with ModuleNotFoundError until the generator lands.

Covers, per the O17 round-5 spec and the 2026-09-02 implementation plan:
  - generation determinism (byte-equal double run on the fixture trio)
  - CHECK (a): pass branch plus all six tamper variants (one hook tuple
    dropped, one permission row dropped, env section dropped, MCP-enablement
    section dropped, whole mcp-servers section dropped, one server row
    dropped), each flagged with its exact finding code
  - CHECK (b): pass branch, then UNLISTED_TOKEN on a substitution table
    missing a bucket-2 token
  - CHECK (c): pass branch (three named states), then
    UNCLASSIFIED_SETTINGS_ROW on fixture_settings_extra_row.json
  - CHECK (d): pass branch, MCP_ROW_NOT_MACHINE_BOUND on a tampered manifest,
    SECRET_VALUE_IN_TRACKED_ARTIFACT on the planted-dummy fixture
  - CHECK (e) parse part: PARSE_FAILURE on an unparseable settings file
  - criterion identity: MACHINE_TOKEN is o17_portability_figures.MACHINE_TOKEN
  - no-secret-output: generated artifacts never contain a credential value
  - empty population: generator CLI exits non-zero on zero hook tuples

All credential-shaped fixture values start with O17-DUMMY- so no fixture can
collide with a real secret.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import o17_portability_figures as figures

SCRIPTS = Path(__file__).resolve().parent
FIXDIR = SCRIPTS / "_test_fixtures" / "o17"
FIX_SETTINGS = FIXDIR / "fixture_settings.json"
FIX_LOCAL = FIXDIR / "fixture_settings_local.json"
FIX_MCP = FIXDIR / "fixture_mcp.json"
FIX_EXTRA = FIXDIR / "fixture_settings_extra_row.json"
FIX_SECRET_TABLE = FIXDIR / "fixture_substitution_with_secret.md"
DATE = "2026-09-02"
JSON_BLOCK = re.compile("```json\n(.*?)\n```", re.DOTALL)


@pytest.fixture(scope="module")
def o17m():
    import o17_portability_manifest as m
    return m


@pytest.fixture()
def generated(o17m, tmp_path):
    """Generate manifest + substitution table from the fixture trio."""
    manifest = tmp_path / "manifest.md"
    subtable = tmp_path / "subtable.md"
    data = o17m.generate(FIX_SETTINGS, FIX_LOCAL, FIX_MCP, DATE, manifest, subtable)
    return o17m, manifest, subtable, data


def read_block(path):
    m = JSON_BLOCK.search(path.read_text(encoding="utf-8"))
    assert m, f"no json block in {path}"
    return json.loads(m.group(1))


def tamper_block(path, mutate):
    """Mutate the json block of a generated artifact in place."""
    text = path.read_text(encoding="utf-8")
    m = JSON_BLOCK.search(text)
    assert m, f"no json block in {path}"
    block = json.loads(m.group(1))
    mutate(block)
    new = text[: m.start(1)] + json.dumps(block, indent=2, sort_keys=True) + text[m.end(1):]
    path.write_text(new, encoding="utf-8", newline="\n")


def codes(findings):
    return [c for c, _ in findings]


# --- criterion identity (design decision 1) ---

def test_criterion_identity(o17m):
    assert o17m.MACHINE_TOKEN is figures.MACHINE_TOKEN
    assert o17m.SECRET_KEY is figures.SECRET_KEY


# --- generation ---

def test_generate_deterministic(o17m, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    o17m.generate(FIX_SETTINGS, FIX_LOCAL, FIX_MCP, DATE, a / "m.md", a / "s.md")
    o17m.generate(FIX_SETTINGS, FIX_LOCAL, FIX_MCP, DATE, b / "m.md", b / "s.md")
    assert (a / "m.md").read_bytes() == (b / "m.md").read_bytes()
    assert (a / "s.md").read_bytes() == (b / "s.md").read_bytes()


def test_no_secret_output(generated):
    _, manifest, subtable, _ = generated
    for p in (manifest, subtable):
        assert "O17-DUMMY-CREDENTIAL-VALUE" not in p.read_text(encoding="utf-8")


def test_move_count_and_resident_list(generated):
    _, manifest, _, _ = generated
    block = read_block(manifest)
    # exactly one fixture local hook tuple is PORTABLE-AS-IS (echo o17-fixture-local-portable)
    assert block["portable_as_is_move_count"] == 1
    # fixture settings.json: interpreter row + wrapper row are bucket-2 hooks; echo row is portable
    assert len(block["resident_with_tokens"]) == 2


def test_empty_population_exits_nonzero(tmp_path):
    empty = tmp_path / "empty_settings.json"
    empty.write_text('{"permissions": {"allow": ["x"]}, "hooks": {}}', encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "o17_portability_manifest.py"), "generate",
         "--date", DATE,
         "--settings", str(empty), "--local", str(FIX_LOCAL), "--mcp", str(FIX_MCP),
         "--out-manifest", str(tmp_path / "m.md"), "--out-subtable", str(tmp_path / "s.md")],
        capture_output=True, text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode != 0


# --- CHECK (a) ---

def test_check_a_pass(generated):
    o17m, manifest, _, _ = generated
    assert o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP) == []


def test_check_a_missing_hook_tuple(generated):
    o17m, manifest, _, _ = generated
    tamper_block(manifest, lambda b: b["sections"]["hooks"].pop(0))
    assert "MISSING_HOOK_TUPLE" in codes(o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP))


def test_check_a_missing_permission_row(generated):
    o17m, manifest, _, _ = generated
    tamper_block(manifest, lambda b: b["sections"]["permissions"].pop(0))
    assert "MISSING_PERMISSION_ROW" in codes(o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP))


def test_check_a_missing_section_env(generated):
    o17m, manifest, _, _ = generated
    tamper_block(manifest, lambda b: b["sections"].pop("env"))
    found = o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP)
    assert ("MISSING_SECTION", "env") in [(c, d.split(":")[0]) for c, d in found]


def test_check_a_missing_section_mcp_enablement(generated):
    o17m, manifest, _, _ = generated
    tamper_block(manifest, lambda b: b["sections"].pop("mcp_enablement"))
    found = o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP)
    assert ("MISSING_SECTION", "mcp-enablement") in [(c, d.split(":")[0]) for c, d in found]


def test_check_a_missing_section_mcp_servers(generated):
    o17m, manifest, _, _ = generated
    tamper_block(manifest, lambda b: b["sections"].pop("mcp_servers"))
    found = o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP)
    assert ("MISSING_SECTION", "mcp-servers") in [(c, d.split(":")[0]) for c, d in found]


def test_check_a_missing_server_row(generated):
    o17m, manifest, _, _ = generated
    tamper_block(manifest, lambda b: b["sections"]["mcp_servers"].pop(0))
    assert "MISSING_SERVER_ROW" in codes(o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL, FIX_MCP))


# --- CHECK (b) ---

def test_check_b_pass(generated):
    o17m, manifest, subtable, _ = generated
    assert o17m.check_b(manifest, subtable) == []


def test_check_b_unlisted_token(generated):
    o17m, manifest, subtable, _ = generated
    tamper_block(subtable, lambda b: b["tokens"].pop("vault-root-prefix"))
    assert "UNLISTED_TOKEN" in codes(o17m.check_b(manifest, subtable))


# --- CHECK (c) ---

def test_check_c_pass(generated):
    o17m, manifest, _, _ = generated
    findings, states = o17m.check_c(manifest, FIX_SETTINGS)
    assert findings == []
    # fixture settings.json: 5 rows -> 2 portable-as-is (echo hook + clean
    # permission), 3 resident-with-tokens (interpreter hook, wrapper hook,
    # machine-path permission), 0 machine-bound
    assert states == {"PORTABLE-AS-IS": 2, "RESIDENT-WITH-TOKENS": 3, "MACHINE-BOUND": 0}


def test_check_c_extra_row_unclassified(generated):
    o17m, manifest, _, _ = generated
    findings, _ = o17m.check_c(manifest, FIX_EXTRA)
    assert "UNCLASSIFIED_SETTINGS_ROW" in codes(findings)


# --- CHECK (d) ---

def test_check_d_pass(generated):
    o17m, manifest, subtable, _ = generated
    assert o17m.check_d(manifest, FIX_MCP, [manifest, subtable]) == []


def test_check_d_mcp_row_not_machine_bound(generated):
    o17m, manifest, subtable, _ = generated

    def force_portable(b):
        b["sections"]["mcp_servers"][0]["bucket"] = "PORTABLE-AS-IS"

    tamper_block(manifest, force_portable)
    assert "MCP_ROW_NOT_MACHINE_BOUND" in codes(o17m.check_d(manifest, FIX_MCP, [manifest, subtable]))


def test_check_d_secret_value_in_tracked_artifact(generated):
    o17m, manifest, subtable, _ = generated
    findings = o17m.check_d(manifest, FIX_MCP, [manifest, subtable, FIX_SECRET_TABLE])
    assert "SECRET_VALUE_IN_TRACKED_ARTIFACT" in codes(findings)
    # counts and paths only, never the matched value
    for _, detail in findings:
        assert "O17-DUMMY-CREDENTIAL-VALUE" not in detail


# --- CHECK (e) parse part ---

def test_check_e_parse_failure(o17m, tmp_path):
    bad = tmp_path / "bad_settings.json"
    bad.write_text('{"hooks": {', encoding="utf-8")
    assert "PARSE_FAILURE" in codes(o17m.check_e(bad, FIX_LOCAL))


def test_check_e_pass(o17m):
    assert o17m.check_e(FIX_SETTINGS, FIX_LOCAL) == []


# --- CHECK (a) spelling normalisation (architect 3, adversarial 8) ---

FIX_LOCAL_PORTABLE = FIXDIR / "fixture_settings_local_portable.json"


def test_normalise_row_collapses_every_vault_spelling(o17m):
    """The four spellings the vault uses all resolve to one token."""
    tail = r"\.claude\hooks\x.py"
    spellings = [
        '"C:\\Program Files\\Python314\\python.exe" '
        '"C:\\Users\\WiktorPotapczyk\\Desktop\\Vault' + tail + '"',
        '"C:/Program Files/Python314/python.exe" '
        '"C:/Users/WiktorPotapczyk/Desktop/Vault/.claude/hooks/x.py"',
        '"C:/Program Files/Python314/python.exe" '
        '"/c/Users/WiktorPotapczyk/Desktop/Vault/.claude/hooks/x.py"',
        'bash "$CLAUDE_PROJECT_DIR/.claude/bin/py" '
        '"$CLAUDE_PROJECT_DIR/.claude/hooks/x.py"',
        'bash "${CLAUDE_PROJECT_DIR}/.claude/bin/py" '
        '"${CLAUDE_PROJECT_DIR}/.claude/hooks/x.py"',
        '"C:/Program Files/Python314/python.exe" '
        '"//c/Users/WIKTOR~1/Desktop/Vault/.claude/hooks/x.py"',
    ]
    normalised = {o17m.normalise_row(s) for s in spellings}
    assert len(normalised) == 1, normalised
    assert normalised == {'<PY> "$CLAUDE_PROJECT_DIR/.claude/hooks/x.py"'}


def test_normalise_row_still_separates_different_hooks(o17m):
    """Normalisation must not make two different hooks look like one."""
    a = 'bash "$CLAUDE_PROJECT_DIR/.claude/bin/py" "$CLAUDE_PROJECT_DIR/.claude/hooks/a.py"'
    b = 'bash "$CLAUDE_PROJECT_DIR/.claude/bin/py" "$CLAUDE_PROJECT_DIR/.claude/hooks/b.py"'
    assert o17m.normalise_row(a) != o17m.normalise_row(b)


def test_normalise_row_leaves_an_unrecognised_interpreter_verbatim(o17m):
    row = 'pwsh -File "$CLAUDE_PROJECT_DIR/.claude/hooks/x.ps1"'
    assert o17m.normalise_row(row) == row


def test_check_a_passes_against_the_portable_twin_of_the_same_wiring(o17m, generated):
    """The manifest is generated from the absolute-path fixture; checking it
    against the $CLAUDE_PROJECT_DIR twin of the same wiring is clean. This is
    the 144-finding case: same rows, two spellings."""
    _m, manifest, _, _ = generated

    assert o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL_PORTABLE, FIX_MCP) == []


def test_check_a_still_catches_a_real_change_in_the_portable_twin(o17m, generated, tmp_path):
    """Control: rename one hook script in the twin and the finding returns."""
    _m, manifest, _, _ = generated
    data = json.loads(FIX_LOCAL_PORTABLE.read_text(encoding="utf-8"))
    data["hooks"]["Stop"][0]["hooks"][0]["command"] = (
        'bash "$CLAUDE_PROJECT_DIR/.claude/bin/py" '
        '"$CLAUDE_PROJECT_DIR/.claude/hooks/fx-local-RENAMED.py"'
    )
    tampered = tmp_path / "twin_renamed.json"
    tampered.write_text(json.dumps(data), encoding="utf-8")

    findings = o17m.check_a(manifest, FIX_SETTINGS, tampered, FIX_MCP)

    # exactly two: the live row the manifest lacks, and the manifest row the
    # live parse lacks. The home and project-key normalisation must not blur
    # a renamed hook into a match.
    assert [c for c, _ in findings] == ["MISSING_HOOK_TUPLE", "MISSING_HOOK_TUPLE"], findings


# --- CHECK (a) across two machines: different home, different user name ---

ALPHA_HOME = "C:/Users/AlphaUser"
ALPHA_VAULT = "C:/Users/AlphaUser/Desktop/Vault"
BETA_HOME = "D:/Users/BetaUsers"
BETA_VAULT = "D:/Work/clone"


def _two_machine_local(home_fwd, home_bs, home_msys2, home_short, vault_fwd, key):
    """One settings.local.json spelled for one machine.

    The spellings are written out by hand rather than taken from
    path_spellings, so the test states the expected forms independently of
    the code that produces them.
    """
    return {
        "env": {"O17_FIXTURE_WINDOW": "123456"},
        "enabledMcpjsonServers": ["alpha", "beta", "delta", "gamma"],
        "permissions": {
            "allow": [
                f"Read({home_msys2}/**)",
                f"Read({home_short}/.claude/skills/**)",
                f"Bash(export PATH=\"{home_fwd}/AppData/Roaming/npm:$PATH\")",
                f"Bash(cp \"{home_bs}/.claude/projects/{key}/memory/x.md\" .)",
                f"Read({home_fwd}/AppData/Local/Temp/claude/{key}/scratchpad/**)",
                f"Edit({vault_fwd}//.obsidian//**)",
                "Read(E:/shared/reference/**)",
                "Bash(git status)",
            ]
        },
        "hooks": {
            "PreToolUse": [{
                "matcher": "Write",
                "hooks": [{
                    "type": "command",
                    "command": f"python \"{vault_fwd}/.claude/hooks/fx-local-a.py\"",
                }],
            }],
            "Stop": [{
                "matcher": "",
                "hooks": [{
                    "type": "command",
                    "command": f"python \"{vault_fwd}/.claude/hooks/fx-local-b.py\"",
                }],
            }],
        },
    }


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_check_a_matches_across_two_machines_with_different_homes(o17m, tmp_path):
    """The measured failure: a target renders settings.local.json with its own
    home, so every permission row carrying a home path (21 live, plus 5
    carrying the project key) was reported missing. The manifest records the
    generating machine's home, vault and project key; check takes the checked
    machine's; both map onto the same tokens."""
    alpha_key = o17m.compute_project_key(ALPHA_VAULT)
    beta_key = o17m.compute_project_key(BETA_VAULT)

    alpha_local = _write(tmp_path / "alpha.json", _two_machine_local(
        ALPHA_HOME, r"C:\Users\AlphaUser", "//c/Users/AlphaUser",
        "//c/Users/ALPHAU~1", ALPHA_VAULT, alpha_key,
    ))
    beta_local = _write(tmp_path / "beta.json", _two_machine_local(
        BETA_HOME, r"D:\Users\BetaUsers", "//d/Users/BetaUsers",
        "//d/Users/BETAUS~1", BETA_VAULT, beta_key,
    ))

    manifest = tmp_path / "manifest.md"
    o17m.generate(
        FIX_SETTINGS, alpha_local, FIX_MCP, DATE, manifest, tmp_path / "subtable.md",
        home=ALPHA_HOME, vault=ALPHA_VAULT,
    )

    findings = o17m.check_a(
        manifest, FIX_SETTINGS, beta_local, FIX_MCP,
        home=BETA_HOME, vault=BETA_VAULT,
    )

    assert findings == [], findings


def test_check_a_still_reports_a_row_pointing_somewhere_else(o17m, tmp_path):
    """Control for the test above: the normalisation is narrow. A rule that
    names a directory which is neither home nor vault still differs."""
    alpha_key = o17m.compute_project_key(ALPHA_VAULT)
    beta_key = o17m.compute_project_key(BETA_VAULT)

    alpha_local = _write(tmp_path / "alpha.json", _two_machine_local(
        ALPHA_HOME, r"C:\Users\AlphaUser", "//c/Users/AlphaUser",
        "//c/Users/ALPHAU~1", ALPHA_VAULT, alpha_key,
    ))
    beta_data = _two_machine_local(
        BETA_HOME, r"D:\Users\BetaUsers", "//d/Users/BetaUsers",
        "//d/Users/BETAUS~1", BETA_VAULT, beta_key,
    )
    beta_data["permissions"]["allow"] = [
        "Read(E:/somewhere-else-entirely/**)" if r == "Read(E:/shared/reference/**)" else r
        for r in beta_data["permissions"]["allow"]
    ]
    beta_local = _write(tmp_path / "beta.json", beta_data)

    manifest = tmp_path / "manifest.md"
    o17m.generate(
        FIX_SETTINGS, alpha_local, FIX_MCP, DATE, manifest, tmp_path / "subtable.md",
        home=ALPHA_HOME, vault=ALPHA_VAULT,
    )

    findings = o17m.check_a(
        manifest, FIX_SETTINGS, beta_local, FIX_MCP,
        home=BETA_HOME, vault=BETA_VAULT,
    )

    codes = codes_of = [c for c, _ in findings]
    assert codes_of.count("MISSING_PERMISSION_ROW") == 2, findings
    assert "MISSING_HOOK_TUPLE" not in codes


def test_generate_records_the_machine_it_ran_on(o17m, generated):
    """The recorded block is what lets the checker map two machines onto one
    set of tokens. Paths only, never a credential."""
    _m, manifest, _s, _data = generated
    block, errs = o17m._read_block(manifest)
    assert errs == []
    machine = block["machine"]
    assert machine["home"] == str(o17m.default_home()).replace(chr(92), "/").rstrip("/")
    assert machine["project_key"] == o17m.compute_project_key(machine["vault"])
    assert "/" in machine["vault"]


def test_path_spellings_covers_the_six_forms_and_the_8_3_variant(o17m):
    spellings = set(o17m.path_spellings("C:/Users/AlphaUser"))
    assert "C:/Users/AlphaUser" in spellings
    assert "C:" + chr(92) + "Users" + chr(92) + "AlphaUser" in spellings
    assert "C:" + chr(92) * 2 + "Users" + chr(92) * 2 + "AlphaUser" in spellings
    assert "C://Users//AlphaUser" in spellings
    assert "/c/Users/AlphaUser" in spellings
    assert "//c/Users/AlphaUser" in spellings
    assert "//c/Users/ALPHAU~1" in spellings
    # longest first, so a shorter spelling can never eat a longer one's prefix
    lengths = [len(s) for s in o17m.path_spellings("C:/Users/AlphaUser")]
    assert lengths == sorted(lengths, reverse=True)


def test_short_name_rule_reproduces_the_live_name_re_pair(o17m):
    """The generic 8.3 rule is not a second copy of NAME_RE's pair."""
    long_name, short_name = o17m.NAME_RE.pattern.split("|")
    assert o17m._short_name(long_name) == short_name
    assert o17m._short_name("Bob") is None


def test_tracked_settings_json_normalises_against_the_recorded_machine(o17m, tmp_path):
    """.claude/settings.json is tracked, so a clone carries the generating
    machine's own file and its rows name that machine's home wherever they
    are checked out. Normalising them against the CHECKED machine's home
    reported 2 identical rows as different on the scratch target."""
    tracked = _write(tmp_path / "settings.json", {
        "permissions": {"allow": [f"Bash({ALPHA_HOME}/.claude/plugins/cache/x/**)"]},
        "hooks": {"Stop": [{"matcher": "", "hooks": [
            {"type": "command", "command": "echo o17-fixture-resident"},
        ]}]},
    })
    alpha_key = o17m.compute_project_key(ALPHA_VAULT)
    alpha_local = _write(tmp_path / "alpha.json", _two_machine_local(
        ALPHA_HOME, r"C:\Users\AlphaUser", "//c/Users/AlphaUser",
        "//c/Users/ALPHAU~1", ALPHA_VAULT, alpha_key,
    ))
    beta_local = _write(tmp_path / "beta.json", _two_machine_local(
        BETA_HOME, r"D:\Users\BetaUsers", "//d/Users/BetaUsers",
        "//d/Users/BETAUS~1", BETA_VAULT, o17m.compute_project_key(BETA_VAULT),
    ))

    manifest = tmp_path / "manifest.md"
    o17m.generate(
        tracked, alpha_local, FIX_MCP, DATE, manifest, tmp_path / "subtable.md",
        home=ALPHA_HOME, vault=ALPHA_VAULT,
    )

    findings = o17m.check_a(
        manifest, tracked, beta_local, FIX_MCP, home=BETA_HOME, vault=BETA_VAULT,
    )

    assert findings == [], findings


def test_live_vault_for_only_resolves_a_real_dotclaude_parent(o17m, tmp_path):
    claude = tmp_path / "checkout" / ".claude"
    claude.mkdir(parents=True)
    settings = claude / "settings.local.json"
    settings.write_text("{}", encoding="utf-8")
    assert o17m.live_vault_for(settings) == str((tmp_path / "checkout").resolve())

    nested = claude / "blueprint"
    nested.mkdir()
    portable = nested / "settings.local.portable.json"
    portable.write_text("{}", encoding="utf-8")
    assert o17m.live_vault_for(portable) == str(o17m.VAULT)


def test_check_a_collapses_the_8_3_short_name_in_a_permission_rule(o17m, generated):
    """The twin spells one permission rule with the 8.3 short user name; the
    two rules denote one path, so they are one row."""
    _m, manifest, _, _ = generated
    live_rule = "Read(//c/Users/WiktorPotapczyk/**)"
    twin_rule = "Read(//c/Users/WIKTOR~1/**)"

    assert o17m.normalise_row(live_rule) == o17m.normalise_row(twin_rule)
    perm_findings = [
        f for f in o17m.check_a(manifest, FIX_SETTINGS, FIX_LOCAL_PORTABLE, FIX_MCP)
        if f[0] == "MISSING_PERMISSION_ROW"
    ]
    assert perm_findings == []
