"""Tests for registry-staleness-check.py.

Written 2026-09-10; this guard had no suite. It reads registry.json's
generated_at and advises regeneration past 7 days. The registry is the vault's
asset inventory, and doctrine treats it as the single source of truth for what
agents and skills exist, so a silently stale one makes every count downstream
wrong while looking authoritative.

Two behaviours are worth pinning because both fail quietly:

  1. SILENCE WHEN FRESH. A hook that advises on every session start gets
     filtered out by the reader, at which point the real 30-day-stale warning
     lands in a stream nobody reads.
  2. The generated_at FIELD wins over file mtime. Any touch of the file, an
     autosave checkout included, refreshes mtime without regenerating
     anything, so an mtime-only check reports a stale registry as fresh.

The hook derives the vault as hook_dir/../.., which is why _hooktest copies to
a production-depth path.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from _hooktest import isolate, run_isolated

HOOK = "registry-staleness-check.py"


def seed_registry(tmp_path, generated_at=None, omit_field=False):
    """Place a registry.json in the isolated vault. Returns its path."""
    hook = isolate(HOOK, tmp_path)
    registry = hook.parent.parent / "registry.json"
    data = {"agents": [], "skills": []}
    if not omit_field and generated_at is not None:
        data["generated_at"] = generated_at
    registry.write_text(json.dumps(data), encoding="utf-8")
    return registry


def advisory(tmp_path):
    proc, _ = run_isolated(HOOK, {"session_id": "s-1"}, tmp_path)
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return ""
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


def iso_days_ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_a_fresh_registry_is_silent(tmp_path):
    """Zero noise when fresh is the property that keeps the stale warning
    legible when it does fire."""
    seed_registry(tmp_path, iso_days_ago(1))
    assert advisory(tmp_path) == ""


def test_a_registry_at_the_threshold_is_still_silent(tmp_path):
    seed_registry(tmp_path, iso_days_ago(6))
    assert advisory(tmp_path) == ""


@pytest.mark.parametrize("days", [8, 30, 200])
def test_a_stale_registry_advises_regeneration(days, tmp_path):
    seed_registry(tmp_path, iso_days_ago(days))
    out = advisory(tmp_path)
    assert "[REGISTRY]" in out
    assert "generate_registry.py" in out
    assert str(days) in out or str(days - 1) in out


def test_the_generated_at_field_beats_file_mtime(tmp_path):
    """The load-bearing one. The file is written right now, so its mtime is
    seconds old; only reading generated_at can see that the CONTENT is stale.
    An mtime-only check would call this fresh, and every autosave checkout
    would reset the clock without regenerating anything."""
    seed_registry(tmp_path, iso_days_ago(90))
    out = advisory(tmp_path)
    assert "[REGISTRY]" in out, "stale content reported as fresh"


def test_a_missing_generated_at_falls_back_to_mtime(tmp_path):
    """Fallback must not crash or claim staleness on a just-written file."""
    seed_registry(tmp_path, omit_field=True)
    assert advisory(tmp_path) == ""


def test_a_naive_timestamp_without_a_zone_is_accepted(tmp_path):
    """Generators have emitted both naive and offset-aware stamps; rejecting
    naive ones would silently fall through to mtime forever."""
    naive = (datetime.now(timezone.utc) - timedelta(days=40)).strftime(
        "%Y-%m-%dT%H:%M:%S")
    seed_registry(tmp_path, naive)
    assert "[REGISTRY]" in advisory(tmp_path)


def test_a_z_suffixed_timestamp_is_accepted(tmp_path):
    z = (datetime.now(timezone.utc) - timedelta(days=40)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    seed_registry(tmp_path, z)
    assert "[REGISTRY]" in advisory(tmp_path)


def test_a_missing_registry_is_a_note_not_an_alarm(tmp_path):
    """First run should get a gentle pointer, not a staleness warning about a
    file that never existed."""
    isolate(HOOK, tmp_path)  # no registry.json placed
    out = advisory(tmp_path)
    assert "not found" in out
    assert "generate_registry.py" in out


def test_a_corrupt_registry_does_not_crash_the_session(tmp_path):
    hook = isolate(HOOK, tmp_path)
    (hook.parent.parent / "registry.json").write_text("{ not json",
                                                      encoding="utf-8")
    proc, _ = run_isolated(HOOK, {"session_id": "s-1"}, tmp_path)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("raw", ["", "not json at all"])
def test_malformed_payloads_exit_clean(raw, tmp_path):
    seed_registry(tmp_path, iso_days_ago(1))
    proc, _ = run_isolated(HOOK, raw, tmp_path)
    assert proc.returncode == 0, proc.stderr
