"""Portability regression test for generate_registry.py (TASK-002, migration
plan Phase 1: 2026-09-15-scheduled-jobs-off-laptop-plan.md).

generate_registry.py:17 already reads VAULT_DIR before falling back to the
hardcoded Windows path -- confirmed by direct read, no code change needed.
This test pins that behavior so a future edit cannot silently regress it
(TASK-002's own CHECK: a VAULT_DIR-scoped run produces the same counts as an
unset run against the same asset population; exercised here on a small
scratch fixture rather than the full live vault, to keep the suite fast).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "generate_registry.py"
PY = sys.executable


def _make_scratch_vault(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    skills = tmp_path / ".claude" / "skills" / "sample-skill"
    agents.mkdir(parents=True)
    skills.mkdir(parents=True)
    (agents / "sample-agent.md").write_text(
        "---\ndescription: A sample agent for portability testing.\n---\nBody.\n",
        encoding="utf-8",
    )
    (skills / "SKILL.md").write_text(
        "---\ndescription: A sample skill for portability testing.\n---\nBody.\n",
        encoding="utf-8",
    )
    return tmp_path


def _run(vault_dir):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", VAULT_DIR=str(vault_dir))
    return subprocess.run(
        [PY, str(SCRIPT), "--no-validate"],
        capture_output=True, text=True, env=env, timeout=60,
    )


def test_vault_dir_env_is_honored_over_hardcoded_default(tmp_path):
    """The local scratch agent/skill (VAULT_DIR-scoped) must be found. Total
    counts are NOT asserted at exactly 1: scan_plugin_agents()/scan_plugin_
    skills() are anchored at Path.home() (this machine's real plugin cache),
    independent of VAULT_DIR by design, so the real cache's population rides
    along -- the portability claim under test is the LOCAL half only."""
    scratch = _make_scratch_vault(tmp_path)
    r = _run(scratch)
    assert r.returncode == 0, r.stdout + r.stderr
    out = scratch / ".claude" / "registry.json"
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["agents"]["sample-agent"]["source"] == "local"
    assert data["skills"]["sample-skill"]["source"] == "local"
    assert data["counts"]["agents"] >= 1
    assert data["counts"]["skills"] >= 1


def test_two_vault_dir_scoped_runs_are_count_stable(tmp_path):
    """Same population, VAULT_DIR set both times: counts must not drift run
    to run (the actual shape of TASK-002's CHECK -- a set run reproduces the
    same counts as another run over the same asset population)."""
    scratch = _make_scratch_vault(tmp_path)
    first = _run(scratch)
    assert first.returncode == 0, first.stdout + first.stderr
    first_counts = json.loads((scratch / ".claude" / "registry.json").read_text(
        encoding="utf-8"))["counts"]

    second = _run(scratch)
    assert second.returncode == 0, second.stdout + second.stderr
    second_counts = json.loads((scratch / ".claude" / "registry.json").read_text(
        encoding="utf-8"))["counts"]

    assert first_counts["agents"] == second_counts["agents"]
    assert first_counts["skills"] == second_counts["skills"]


# --- TASK-033 (migration plan Phase 1, 2026-09-15): plugin-cache snapshot
# fallback --------------------------------------------------------------------

SNAPSHOT = {
    "generated_at": "2026-09-15T12:00:00",
    "plugin_source": "snapshot",
    "plugins": {
        "code-reviewer@claude-plugins-official": {
            "name": "code-reviewer", "marketplace": "claude-plugins-official",
            "version": "1.2.0", "enabled": True,
        },
        "ralph-loop@claude-plugins-official": {
            "name": "ralph-loop", "marketplace": "claude-plugins-official",
            "version": "0.3.0", "enabled": False,
        },
    },
}


def test_falls_back_to_snapshot_when_live_plugin_cache_absent(tmp_path):
    """TEST-008: with ~/.claude/plugins absent, registry.json falls back to
    .claude/plugins-snapshot.json and reports non-zero plugin counts, tagged
    plugin_source: "snapshot"."""
    scratch = _make_scratch_vault(tmp_path)
    snapshot_path = scratch / ".claude" / "plugins-snapshot.json"
    snapshot_path.write_text(json.dumps(SNAPSHOT), encoding="utf-8")

    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()  # no .claude/plugins under it -- live cache absent

    env = dict(os.environ, PYTHONIOENCODING="utf-8", VAULT_DIR=str(scratch),
              USERPROFILE=str(fake_home), HOME=str(fake_home))
    r = subprocess.run([PY, str(SCRIPT), "--no-validate"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr

    data = json.loads((scratch / ".claude" / "registry.json").read_text(encoding="utf-8"))
    assert data["plugin_source"] == "snapshot"
    assert data["counts"]["plugins_total"] == 2
    assert data["counts"]["plugins_enabled"] == 1
    names = {p["name"] for p in data["plugins"]}
    assert names == {"code-reviewer", "ralph-loop"}


# ---------------------------------------------------------------------------
# Plugin entries when the plugin cache cannot be seen (2026-09-20).
#
# The cloud docs job runs this generator on a runner that has no
# ~/.claude/plugins/cache. It used to write a registry with every
# plugin-sourced agent and skill dropped (32 agents instead of 92, 64 known
# dispatch names instead of about 270), every morning from 2026-09-16, and
# the laptop put them back whenever something there happened to regenerate.
# plugins-snapshot.json carries plugin NAMES, not their agent and skill
# files, so it could never fill the gap. A run that cannot see the cache now
# keeps the plugin entries of the registry it is about to replace.
# ---------------------------------------------------------------------------

def _prior_registry(scratch, agents, skills):
    path = scratch / ".claude" / "registry.json"
    path.write_text(json.dumps({"generated_at": "2026-01-01T00:00:00", "agents": agents,
                                "skills": skills, "plugins": []}), encoding="utf-8")
    return path


def _run_without_plugin_cache(scratch, tmp_path):
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir(exist_ok=True)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", VAULT_DIR=str(scratch),
               USERPROFILE=str(fake_home), HOME=str(fake_home))
    r = subprocess.run([PY, str(SCRIPT), "--no-validate"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((scratch / ".claude" / "registry.json").read_text(encoding="utf-8")), r.stdout


PLUGIN_AGENT = {"name": "code-reviewer", "description": "Reviews code.", "source": "plugin:claude-plugins-official"}
PLUGIN_SKILL = {"name": "ars-full", "description": "Academic pipeline.", "source": "plugin:academic-research-skills"}


def test_a_run_that_cannot_see_the_plugin_cache_keeps_the_plugin_entries(tmp_path):
    scratch = _make_scratch_vault(tmp_path)
    _prior_registry(scratch,
                    {"code-reviewer": PLUGIN_AGENT,
                     "gone-local-agent": {"name": "gone-local-agent", "source": "local"}},
                    {"ars-full": PLUGIN_SKILL})

    data, out = _run_without_plugin_cache(scratch, tmp_path)

    assert data["plugin_entries"] == "carried-over"
    assert data["agents"]["code-reviewer"] == PLUGIN_AGENT
    assert data["skills"]["ars-full"] == PLUGIN_SKILL
    # local entries always come fresh from disk: the stale one is gone
    assert "gone-local-agent" not in data["agents"]
    assert data["agents"]["sample-agent"]["source"] == "local"
    assert data["counts"]["agents"] == 2 and data["counts"]["skills"] == 2
    assert "carried over" in out


def test_a_local_component_still_wins_over_a_carried_plugin_entry_of_the_same_name(tmp_path):
    scratch = _make_scratch_vault(tmp_path)
    _prior_registry(scratch, {"sample-agent": dict(PLUGIN_AGENT, name="sample-agent")}, {})

    data, _ = _run_without_plugin_cache(scratch, tmp_path)

    assert data["agents"]["sample-agent"]["source"] == "local"


def test_entries_of_a_plugin_source_the_snapshot_no_longer_lists_are_dropped(tmp_path):
    """The laptop writes the snapshot on every autosave, so it knows which
    plugin sources are installed even when their files cannot be seen."""
    scratch = _make_scratch_vault(tmp_path)
    (scratch / ".claude" / "plugins-snapshot.json").write_text(json.dumps({
        "plugins": {"x@claude-plugins-official": {"name": "x", "enabled": True,
                                                 "marketplace": "claude-plugins-official"}}}),
        encoding="utf-8")
    _prior_registry(scratch, {"code-reviewer": PLUGIN_AGENT}, {"ars-full": PLUGIN_SKILL})

    data, _ = _run_without_plugin_cache(scratch, tmp_path)

    assert "code-reviewer" in data["agents"]
    assert "ars-full" not in data["skills"], "its plugin source is not installed any more"


def test_a_missing_or_broken_prior_registry_is_not_fatal(tmp_path):
    scratch = _make_scratch_vault(tmp_path)
    data, _ = _run_without_plugin_cache(scratch, tmp_path)
    assert data["plugin_entries"] == "absent"
    assert set(data["agents"]) == {"sample-agent"}

    (scratch / ".claude" / "registry.json").write_text("{not json", encoding="utf-8")
    data, out = _run_without_plugin_cache(scratch, tmp_path)
    assert data["plugin_entries"] == "absent"
    assert "[WARN]" in out

    _prior_registry(scratch, ["not", "a", "dict"], {"ars-full": "not a dict either"})
    data, _ = _run_without_plugin_cache(scratch, tmp_path)
    assert data["plugin_entries"] == "absent"


def test_a_run_that_can_see_the_plugin_cache_is_the_authority(tmp_path):
    """On the laptop the cache is read live, and a plugin entry that is no
    longer in it is dropped rather than carried over."""
    scratch = _make_scratch_vault(tmp_path)
    _prior_registry(scratch, {"code-reviewer": PLUGIN_AGENT}, {})
    fake_home = tmp_path / "fake_home"
    agents_dir = fake_home / ".claude" / "plugins" / "cache" / "some-marketplace" / "p" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "live-agent.md").write_text(
        "---\ndescription: A live plugin agent.\n---\nBody.\n", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", VAULT_DIR=str(scratch),
               USERPROFILE=str(fake_home), HOME=str(fake_home))
    r = subprocess.run([PY, str(SCRIPT), "--no-validate"],
                       capture_output=True, text=True, env=env, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads((scratch / ".claude" / "registry.json").read_text(encoding="utf-8"))

    assert data["plugin_entries"] == "live"
    assert "live-agent" in data["agents"]
    assert "code-reviewer" not in data["agents"]
