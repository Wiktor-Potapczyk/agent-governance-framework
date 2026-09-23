"""RED-first suite for docs_stub_generate.py (O19).

Plan of record: Projects/Agent-Governance-Research/work/
2026-09-04-o19-stub-generator-plan.md (D1-D10, S3 test list).
Fixtures: .claude/scripts/_test_fixtures/docs_stub/ (mini inventory + rationale).

All writes are confined to pytest tmp_path; the fixture files are read-only
inputs. The suite never touches the live docs tree or the live aggregates.
"""

import json
import re
from pathlib import Path

import pytest

import docs_stub_generate as dsg

FIX = Path(__file__).resolve().parent / "_test_fixtures" / "docs_stub"

GEN_BEGIN = "<!-- GENERATED:BEGIN owned by docs_stub_generate.py; regeneration rewrites this block -->"
GEN_END = "<!-- GENERATED:END -->"
PROSE_BEGIN = "<!-- PROSE:BEGIN preserved byte-identical across regeneration -->"
PROSE_END = "<!-- PROSE:END -->"

FANCY_DASHES = "\u2012\u2013\u2014\u2015\u2e3a\u2e3b\ufe63\uff0d\u2212"


def load_fixture():
    inv = json.loads((FIX / "inventory.json").read_text(encoding="utf-8"))
    rat = json.loads((FIX / "rationale.json").read_text(encoding="utf-8"))
    return inv, rat


def write_inputs(tmp_path, inv, rat):
    tmp_path.mkdir(parents=True, exist_ok=True)
    ip = tmp_path / "inventory.json"
    rp = tmp_path / "rationale.json"
    ip.write_text(json.dumps(inv), encoding="utf-8")
    rp.write_text(json.dumps(rat), encoding="utf-8")
    return ip, rp


def run_main(tmp_path, inv=None, rat=None, out=None, extra=None):
    """Run dsg.main against (possibly modified) fixture copies; return exit code."""
    finv, frat = load_fixture()
    inv = finv if inv is None else inv
    rat = frat if rat is None else rat
    ip, rp = write_inputs(tmp_path, inv, rat)
    out = out or (tmp_path / "out")
    args = ["--inventory", str(ip), "--rationale", str(rp), "--out", str(out)]
    if extra:
        args += extra
    return dsg.main(args), out


def tree_bytes(out):
    return {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in sorted(out.rglob("*.md"))
    }


def page(out, rel):
    return (out / rel).read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1-2 slugify


def test_slugify_basics():
    assert dsg.slugify("Hello World") == "hello-world"
    assert dsg.slugify("A__B..C") == "a-b-c"
    assert dsg.slugify("-x-") == "x"
    assert dsg.slugify("settings.json:PostToolUse[0.0]") == "settings-json-posttooluse-0-0"


def test_slugify_dotted_and_all_symbol():
    assert dsg.slugify("2.11.2") == "2-11-2"
    assert dsg.slugify("@@@") == "unnamed"
    assert dsg.slugify("") == "unnamed"


# ------------------------------------------------------- 3-8 validation set


def test_slug_collision_fails_loud(tmp_path):
    inv, _ = load_fixture()
    dup = json.loads(json.dumps(next(r for r in inv["rows"] if r["name"] == "eta-agent@px@px")))
    dup["name"] = "eta.agent@px@px"  # same slug as eta-agent@px@px
    inv["rows"].append(dup)
    inv["twin_summary"]["not-applicable"] += 1
    inv["plugin_cache_enumeration"]["row_counts"]["agent"] += 1
    code, out = run_main(tmp_path, inv=inv)
    assert code == 2
    assert not out.exists() or not any(out.rglob("*.md"))


def test_total_vs_twin_summary_mismatch_fails(tmp_path):
    inv, _ = load_fixture()
    inv["twin_summary"]["identical"] += 1
    code, out = run_main(tmp_path, inv=inv)
    assert code == 2
    assert not out.exists() or not any(out.rglob("*.md"))


def test_per_kind_plugin_count_mismatch_fails(tmp_path):
    inv, _ = load_fixture()
    inv["plugin_cache_enumeration"]["row_counts"]["agent"] = 5
    code, out = run_main(tmp_path, inv=inv)
    assert code == 2


def test_skill_reconciliation_line_and_missing_blk004(tmp_path, capsys):
    code, _ = run_main(tmp_path)
    assert code == 0
    got = capsys.readouterr().out
    assert (
        "skill: 1 cache-enumerated + 1 BLK-004 registry-only = 2 plugin"
        " + 1 vault-owned = 3 total" in got
    )
    inv, _ = load_fixture()
    del inv["plugin_cache_enumeration"]["row_counts"]["blk004_unresolved_registry_entries"]
    code, _ = run_main(tmp_path / "red", inv=inv)
    assert code == 2


def test_rationale_join_gap_fails(tmp_path):
    _, rat = load_fixture()
    rat["rows"] = [r for r in rat["rows"] if r["name"] != "alpha-agent"]
    code, _ = run_main(tmp_path, rat=rat)
    assert code == 2
    _, rat2 = load_fixture()
    rat2["rows"].append(dict(rat2["rows"][0], name="ghost-agent"))
    code, _ = run_main(tmp_path / "extra", rat=rat2)
    assert code == 2


def test_stamp_drift_fails(tmp_path):
    _, rat = load_fixture()
    rat["source_asset_inventory_generated_at"] = "2026-01-01T00:00:00Z"
    code, out = run_main(tmp_path, rat=rat)
    assert code == 2
    assert not out.exists() or not any(out.rglob("*.md"))


# ------------------------------------------------------ 9-16 page rendering


def test_page_byte_layout(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    text = page(out, "agent/alpha-agent.md")
    assert text.startswith(
        '---\ncomponent: "alpha-agent"\nkind: "agent"\n'
        'source_inventory_generated_at: "2026-09-04T00:00:00Z"\n---\n\n'
        "# agent: alpha-agent\n\n"
    )
    for marker in (GEN_BEGIN, GEN_END, PROSE_BEGIN, PROSE_END):
        assert text.count(marker) == 1
    assert (
        text.index(GEN_BEGIN) < text.index(GEN_END)
        < text.index(PROSE_BEGIN) < text.index(PROSE_END)
    )
    assert "- **Path:** `.claude/agents/alpha-agent.md`" in text
    assert "- **Provenance:** authored-in-harness" in text
    assert "- **Twin state:** divergent" in text
    assert text.endswith(PROSE_END + "\n")
    # generated pages exist for every fixture row (12), sharded by kind
    assert len(list(out.rglob("*.md"))) == 12


def test_why_seeded_from_extracted_excerpt(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    text = page(out, "agent/alpha-agent.md")
    assert "Use this agent to test the docs stub generator." in text
    assert "(machine-filled from rationale-index.json; extraction locus: frontmatter)" in text


def test_no_stated_why_renders_unfilled_variant(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    text = page(out, "telemetry-sink/omega-log-jsonl.md")
    assert "UNFILLED-WHY (no machine source; tier policy in README.md)" in text


def test_plugin_and_null_path_rendering(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    hook = page(out, "hook/beta-hook-px-px.md")
    assert "UNFILLED-WHY (no machine source; tier policy in README.md)" in hook
    assert (
        "UNFILLED-HOW (see tier policy in README.md; plugin-internal mechanism, "
        "upstream source at `C:/plugins/cache/px/px/1.0.0/hooks/beta-hook.py`)" in hook
    )
    null_row = page(out, "skill/2-11-2.md")
    assert "- **Path:** (none recorded; unresolved registry entry, blocked: `BLK-004`)" in null_row
    assert "no upstream source recorded" in null_row


def test_settings_registration_template_how(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    hook_reg = page(out, "settings-registration/settings-json-posttooluse-0-0.md")
    assert "template-derived" in hook_reg
    assert "`.claude/settings.json`" in hook_reg
    assert "hook event `PostToolUse`" in hook_reg
    assert "matcher: Write" in hook_reg
    assert "`python check.py`" in hook_reg
    mcp_reg = page(out, "settings-registration/mcp-zeta.md")
    assert "MCP server `zeta`" in mcp_reg
    assert "`node zeta.js`" in mcp_reg


def test_sentinel_vocabulary(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    no_path_pages = [
        ("hook/beta-hook-px-px.md", "NO_SOURCE_FOR_PLUGIN_HOOK"),
        ("skill/delta-skill-px-px.md", "NO_SOURCE_FOR_PLUGIN_SKILL"),
        ("skill/2-11-2.md", "NO_SOURCE_FOR_UNRESOLVED_PLUGIN_COMPONENT"),
        ("settings-registration/mcp-zeta.md", "UNRESOLVED_REGISTRATION"),
    ]
    for rel, code_name in no_path_pages:
        text = page(out, rel)
        assert "No telemetry path exists for this row" in text, rel
        assert f"`{code_name}`" in text, rel
        assert "Instrumented, observed zero times" not in text, rel
    awaiting = page(out, "workflow/epsilon-flow.md")
    assert "Instrumented, observed zero times" in awaiting
    assert "`AWAITING_FIRST_OBSERVATION`" in awaiting
    assert "excluded" in awaiting  # pre-plumbing exclusion stated
    assert "No telemetry path exists for this row" not in awaiting


def test_real_usage_variants(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    alpha = page(out, "agent/alpha-agent.md")
    assert "Recorded use count 42" in alpha
    assert "First seen 2026-05-01T10:00:00; last seen 2026-09-01T10:00:00." in alpha
    assert "Days since last use: 3; dormant: false." in alpha
    omega = page(out, "telemetry-sink/omega-log-jsonl.md")
    assert "Writer fire count sum: 7" in omega
    eps = page(out, "workflow/epsilon-flow.md")
    assert "Note: workflow-identity plumbing landed 2026-09-01" in eps


def test_edges_marked_never_dropped(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    alpha = page(out, "agent/alpha-agent.md")
    assert "  - outbound dispatched_by process-build\n" in alpha
    assert "  - inbound mentioned_in CLAUDE.md [unresolved: prose mention only]\n" in alpha
    null_row = page(out, "skill/2-11-2.md")
    assert "- **Edges:** (no edges recorded)" in null_row


# --------------------------------------------- 17-21 preservation and merge


def _hand_touch_why(out, rel, paragraph):
    p = out / rel
    text = p.read_text(encoding="utf-8")
    text = text.replace("\n\n## How", "\n\n" + paragraph + "\n\n## How", 1)
    p.write_bytes(text.encode("utf-8"))
    return p.read_bytes()


def test_prose_preserved_byte_identical(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    _hand_touch_why(out, "agent/alpha-agent.md", "Hand paragraph for preservation proof.")
    before = dsg.split_blocks(page(out, "agent/alpha-agent.md"))["prose"]
    code2, out2 = run_main(tmp_path / "rerun", out=out)
    assert code2 == 0
    after = dsg.split_blocks(page(out, "agent/alpha-agent.md"))["prose"]
    assert before == after


def test_preservation_red_branch_detects_clobber(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    original = dsg.split_blocks(page(out, "agent/alpha-agent.md"))["prose"]
    clobbered_page = page(out, "agent/alpha-agent.md").replace(
        "## Why", "## Why (clobbered)", 1
    )
    clobbered = dsg.split_blocks(clobbered_page)["prose"]
    assert original != clobbered  # the byte-compare helper catches a clobber


def test_pristine_marker_reseed_rule(tmp_path):
    # First run with WHY machine source absent -> pristine UNFILLED-WHY marker.
    _, rat = load_fixture()
    for r in rat["rows"]:
        if r["name"] == "alpha-agent":
            r["rationale"] = ""
            r["extraction_status"] = "NO_STATED_WHY"
            r["extraction_locus"] = None
    code, out = run_main(tmp_path, rat=rat)
    assert code == 0
    assert "UNFILLED-WHY (no machine source; tier policy in README.md)" in page(
        out, "agent/alpha-agent.md"
    )
    # Machine source appears -> pristine marker is re-seeded.
    code2, _ = run_main(tmp_path / "rerun", out=out)
    assert code2 == 0
    text = page(out, "agent/alpha-agent.md")
    assert "UNFILLED-WHY" not in text
    assert "Use this agent to test the docs stub generator." in text
    # Hand-touched WHY is preserved even when a machine source exists.
    p = out / "agent" / "alpha-agent.md"
    p.write_bytes(
        page(out, "agent/alpha-agent.md")
        .replace("Use this agent to test the docs stub generator.", "Hand-written why.", 1)
        .encode("utf-8")
    )
    code3, _ = run_main(tmp_path / "rerun2", out=out)
    assert code3 == 0
    assert "Hand-written why." in page(out, "agent/alpha-agent.md")


def test_generated_block_rewritten_wholesale(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    p = out / "agent" / "alpha-agent.md"
    pristine = p.read_bytes()
    mutated = page(out, "agent/alpha-agent.md").replace(
        "- **Provenance:** authored-in-harness", "- **Provenance:** MUTATED", 1
    )
    p.write_bytes(mutated.encode("utf-8"))
    code2, _ = run_main(tmp_path / "rerun", out=out)
    assert code2 == 0
    assert p.read_bytes() == pristine
    assert "MUTATED" not in page(out, "agent/alpha-agent.md")


def test_malformed_markers_fail_loud_zero_writes(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    victim = out / "agent" / "alpha-agent.md"
    broken = page(out, "agent/alpha-agent.md").replace(GEN_END + "\n", "", 1)
    victim.write_bytes(broken.encode("utf-8"))
    sibling = out / "workflow" / "epsilon-flow.md"
    sibling_before = sibling.read_bytes()
    code2, _ = run_main(tmp_path / "rerun", out=out)
    assert code2 == 2
    assert victim.read_bytes() == broken.encode("utf-8")  # not clobbered
    assert sibling.read_bytes() == sibling_before  # zero writes elsewhere


# ------------------------------------------- 22-25 determinism and confinement


def test_determinism_byte_identical_tree(tmp_path):
    code1, out1 = run_main(tmp_path / "a")
    code2, out2 = run_main(tmp_path / "b")
    assert code1 == 0 and code2 == 0
    assert tree_bytes(out1) == tree_bytes(out2)
    first = tree_bytes(out1)
    code3, _ = run_main(tmp_path / "c", out=out1)  # regenerate in place
    assert code3 == 0
    assert tree_bytes(out1) == first


def test_write_confinement_on_failure(tmp_path):
    _, rat = load_fixture()
    rat["source_asset_inventory_generated_at"] = "1999-01-01T00:00:00Z"
    out = tmp_path / "out"
    out.mkdir()
    code, _ = run_main(tmp_path, rat=rat, out=out)
    assert code == 2
    assert list(out.rglob("*")) == []  # failing validation writes nothing
    stray = [
        p
        for p in tmp_path.rglob("*")
        if p.is_file() and p.name not in ("inventory.json", "rationale.json")
    ]
    assert stray == []  # nothing written outside --out either


def test_no_fancy_dash_glyphs_in_output(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    for rel, data in tree_bytes(out).items():
        text = data.decode("utf-8")
        assert not any(ch in text for ch in FANCY_DASHES), rel


def test_readme_and_template_never_overwritten(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    readme = out / "README.md"
    template = out / "template.md"
    readme.write_bytes(b"README SENTINEL\n")
    template.write_bytes(b"TEMPLATE SENTINEL\n")
    code, _ = run_main(tmp_path, out=out)
    assert code == 0
    assert readme.read_bytes() == b"README SENTINEL\n"
    assert template.read_bytes() == b"TEMPLATE SENTINEL\n"


# ------------------------------------------------------------ 26 kind scoping


def test_unknown_kind_fails_loud(tmp_path, capsys):
    code, out = run_main(tmp_path, extra=["--kind", "bogus-kind-typo"])
    assert code == 2
    err = capsys.readouterr().err
    assert "bogus-kind-typo" in err
    for valid in ("agent", "hook", "skill", "settings-registration"):
        assert valid in err  # diagnostic names the valid kinds
    assert not out.exists() or not any(out.rglob("*.md"))


# -------------------------------------------- 27-33 plugin-level WHY (O23, D8)

PLUGIN_WHY_LABEL = "(plugin-level WHY; per-component WHY declined by ruling)"
PX_WHY = "Test plugin px provides fixture components for the docs stub suite."
PX_UPSTREAM = "C:/plugins/cache/px/px/1.0.0"

# Fixture pages owned by plugin px (provenance plugin:px/px, plus the bare
# provenance plugin:px on the BLK-004 row 2.11.2 -> same derived name 'px').
PX_PAGES = (
    "hook/beta-hook-px-px.md",
    "skill/delta-skill-px-px.md",
    "skill/2-11-2.md",
    "agent/eta-agent-px-px.md",
    "mcp-server/theta-px.md",
)
OWNED_PAGES = (
    "agent/alpha-agent.md",
    "mcp-server/gamma-server.md",
    "settings-registration/settings-json-posttooluse-0-0.md",
    "settings-registration/mcp-zeta.md",
    "skill/toolkit-code-review.md",
    "telemetry-sink/omega-log-jsonl.md",
    "workflow/epsilon-flow.md",
)


def write_plugin_why(out, mapping):
    out.mkdir(parents=True, exist_ok=True)
    (out / "_plugin-why.json").write_text(json.dumps(mapping), encoding="utf-8")


def px_mapping():
    return {"px": {"why": PX_WHY, "upstream": PX_UPSTREAM}}


def test_plugin_why_absent_keeps_markers(tmp_path):
    # Backward compatible: no _plugin-why.json in the out root -> exit 0 and
    # every plugin page keeps the pristine UNFILLED-WHY marker.
    code, out = run_main(tmp_path)
    assert code == 0
    assert not (out / "_plugin-why.json").exists()
    for rel in PX_PAGES:
        assert dsg.UNFILLED_WHY in page(out, rel), rel


def test_plugin_why_seeds_pristine_markers_in_place(tmp_path):
    # The O23 wiring path: stubs exist with pristine markers, the file lands,
    # a re-run seeds every plugin page (bare provenance plugin:px included).
    code, out = run_main(tmp_path)
    assert code == 0
    write_plugin_why(out, px_mapping())
    code2, _ = run_main(tmp_path / "rerun", out=out)
    assert code2 == 0
    for rel in PX_PAGES:
        text = page(out, rel)
        assert dsg.UNFILLED_WHY not in text, rel
        assert PX_WHY in text, rel
        assert f"Upstream: `{PX_UPSTREAM}`" in text, rel
        assert PLUGIN_WHY_LABEL in text, rel


def test_plugin_why_seeds_fresh_renders_too(tmp_path):
    # File present before the first run -> fresh pages are born seeded.
    out = tmp_path / "out"
    write_plugin_why(out, px_mapping())
    code, _ = run_main(tmp_path, out=out)
    assert code == 0
    for rel in PX_PAGES:
        text = page(out, rel)
        assert dsg.UNFILLED_WHY not in text, rel
        assert PX_WHY in text, rel
        assert PLUGIN_WHY_LABEL in text, rel


def test_plugin_why_missing_entry_fails_loud_names_plugin(tmp_path, capsys):
    # A plugin-provenance row whose plugin has no entry is exit 2, zero writes,
    # and the failure names the plugin.
    out = tmp_path / "out"
    write_plugin_why(out, {"not-px": {"why": "x", "upstream": "y"}})
    code, _ = run_main(tmp_path, out=out)
    assert code == 2
    err = capsys.readouterr().err
    assert "'px'" in err
    assert not any(out.rglob("*.md"))  # all-or-nothing: nothing written


def test_plugin_why_malformed_fails_loud(tmp_path):
    out = tmp_path / "out"
    write_plugin_why(out, {"px": {"upstream": "y"}})  # 'why' missing
    code, _ = run_main(tmp_path, out=out)
    assert code == 2
    out2 = tmp_path / "out2"
    out2.mkdir()
    (out2 / "_plugin-why.json").write_text("[]", encoding="utf-8")  # not a dict
    code2, _ = run_main(tmp_path / "b", out=out2)
    assert code2 == 2
    out3 = tmp_path / "out3"
    out3.mkdir()
    (out3 / "_plugin-why.json").write_text("{not json", encoding="utf-8")
    code3, _ = run_main(tmp_path / "c", out=out3)
    assert code3 == 2


def test_plugin_why_never_touches_vault_owned(tmp_path):
    # Vault-owned pages are byte-identical between a run without the file and
    # a run with it; the marker-reseed join applies to plugin rows only.
    code_a, out_a = run_main(tmp_path / "a")
    assert code_a == 0
    out_b = tmp_path / "b" / "out"
    write_plugin_why(out_b, px_mapping())
    code_b, _ = run_main(tmp_path / "b", out=out_b)
    assert code_b == 0
    for rel in OWNED_PAGES:
        assert (out_a / rel).read_bytes() == (out_b / rel).read_bytes(), rel
    # The owned page whose WHY is the pristine marker keeps it: no plugin
    # paragraph ever lands on a vault-owned row.
    assert dsg.UNFILLED_WHY in page(out_b, "telemetry-sink/omega-log-jsonl.md")


# ------------------------------------- 34-36 _generated.json stamp (Phase C)


def test_generated_json_stamp_written_on_non_dry_run(tmp_path):
    code, out = run_main(tmp_path)
    assert code == 0
    stamp_path = out / "_generated.json"
    assert stamp_path.exists()
    stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp["generated_at"])
    assert stamp["source_inventory_generated_at"] == "2026-09-04T00:00:00Z"
    assert stamp["kinds"] is None
    assert stamp["pages_planned"] == 12
    assert stamp["written"] == 12
    assert stamp["unchanged"] == 0


def test_generated_json_stamp_reflects_kind_scope_and_unchanged(tmp_path):
    code, out = run_main(tmp_path, extra=["--kind", "agent"])
    assert code == 0
    stamp = json.loads((out / "_generated.json").read_text(encoding="utf-8"))
    assert stamp["kinds"] == ["agent"]
    assert stamp["pages_planned"] == 2
    code2, _ = run_main(tmp_path / "rerun", out=out, extra=["--kind", "agent"])
    assert code2 == 0
    stamp2 = json.loads((out / "_generated.json").read_text(encoding="utf-8"))
    assert stamp2["written"] == 0
    assert stamp2["unchanged"] == 2


def test_generated_json_stamp_not_written_on_dry_run(tmp_path):
    out = tmp_path / "out"
    code, _ = run_main(tmp_path, out=out, extra=["--dry-run"])
    assert code == 0
    assert not (out / "_generated.json").exists()


def test_plugin_why_hand_edit_preserved_and_deterministic(tmp_path):
    out = tmp_path / "out"
    write_plugin_why(out, px_mapping())
    code, _ = run_main(tmp_path, out=out)
    assert code == 0
    # Hand-edit one seeded plugin WHY: it is no longer pristine, so it is
    # preserved byte-identical through the next run even with the file present.
    victim = out / "hook" / "beta-hook-px-px.md"
    assert PX_WHY in page(out, "hook/beta-hook-px-px.md")  # seed landed
    victim.write_bytes(
        page(out, "hook/beta-hook-px-px.md")
        .replace(PX_WHY, "Hand-written plugin why.", 1)
        .encode("utf-8")
    )
    hand = victim.read_bytes()
    code2, _ = run_main(tmp_path / "rerun", out=out)
    assert code2 == 0
    assert victim.read_bytes() == hand
    # Determinism with the file present: an immediate re-run changes nothing.
    before = tree_bytes(out)
    code3, _ = run_main(tmp_path / "rerun2", out=out)
    assert code3 == 0
    assert tree_bytes(out) == before
