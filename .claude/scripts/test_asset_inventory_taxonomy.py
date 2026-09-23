"""O13 unit tests: the metric-1 skip-taxonomy classifier, the windowed
accounting, and the enumeration-set fingerprint in asset_inventory.py.

Loads the generator as a module (import executes only constants and
function definitions; main() is __main__-guarded) and exercises the pure
functions directly, plus the two streaming processors against tmp_path
fixtures. Never touches the live sinks.

Build record: Projects/Agent-Governance-Research/work/2026-09-01-o13-build-record.md
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "asset_inventory.py"
_spec = importlib.util.spec_from_file_location("asset_inventory_o13_under_test", SCRIPT)
mod = importlib.util.module_from_spec(_spec)
# dataclasses resolves the defining module through sys.modules at class
# creation, so the module must be registered before exec_module.
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)


MEMBERSHIP = {
    "builtin_floor": mod.BUILTIN_DISPATCH_FLOOR,
    "skill_names": {"process-qa", "pm", "n8n-reviewer", "explore-skill"},
    "agent_match_set": {"architect-reviewer", "adversarial-reviewer",
                        "n8n-reviewer", "pr-review-toolkit:silent-failure-hunter"},
    "plugin_agent_bare_names": {"silent-failure-hunter", "code-reviewer"},
}


def _counts(block):
    return {k: v["count"] for k, v in block["buckets"].items()}


class TestClassifySkips:
    def test_governance_skill_buckets_and_sum(self):
        unmatched = Counter({
            "architect-reviewer": 395,      # agent name -> cross_field_mislabel
            "adversarial-reviewer": 228,    # agent name -> cross_field_mislabel
            "silent-failure-hunter": 3,     # plugin bare name -> cross_field_mislabel (skill scope)
            "general-purpose": 2,           # builtin floor
            "totally-unknown": 7,           # genuinely unknown
        })
        block = mod.classify_skips(unmatched, "governance_skill", MEMBERSHIP)
        c = _counts(block)
        assert c["cross_field_mislabel"] == 395 + 228 + 3
        assert c["builtin_floor"] == 2
        assert c["plugin_unqualified"] == 0  # structurally empty on skill side
        assert c["genuinely_unknown"] == 7
        assert block["total_skips"] == sum(unmatched.values())

    def test_governance_agent_buckets_and_sum(self):
        unmatched = Counter({
            "general-purpose": 449,
            "explore": 32,
            "": 4,
            "fork": 1,
            "process-qa": 5,               # skill name -> cross_field_mislabel
            "silent-failure-hunter": 1,    # plugin bare name -> plugin_unqualified
            "None": 3,                     # stringified null -> genuinely_unknown
            "workflow-orchestrator": 3,    # retired -> genuinely_unknown
        })
        block = mod.classify_skips(unmatched, "governance_agent", MEMBERSHIP)
        c = _counts(block)
        assert c["builtin_floor"] == 449 + 32 + 4 + 1
        assert c["cross_field_mislabel"] == 5
        assert c["plugin_unqualified"] == 1
        assert c["genuinely_unknown"] == 6
        assert block["total_skips"] == sum(unmatched.values())

    def test_precedence_builtin_floor_beats_cross_field(self):
        # A value in BOTH the builtin floor and the skill set classifies as
        # builtin_floor (fixed precedence).
        membership = dict(MEMBERSHIP)
        membership["skill_names"] = MEMBERSHIP["skill_names"] | {"explore"}
        block = mod.classify_skips(Counter({"explore": 9}), "governance_agent", membership)
        assert _counts(block)["builtin_floor"] == 9
        assert _counts(block)["cross_field_mislabel"] == 0

    def test_precedence_cross_field_beats_plugin_unqualified_on_skill_side(self):
        # silent-failure-hunter is a plugin bare name; on the skill side it
        # classifies as cross_field_mislabel because that bucket precedes
        # plugin_unqualified and includes plugin bare names by definition.
        block = mod.classify_skips(Counter({"silent-failure-hunter": 4}),
                                   "governance_skill", MEMBERSHIP)
        assert _counts(block)["cross_field_mislabel"] == 4
        assert _counts(block)["plugin_unqualified"] == 0

    def test_hook_scope_unparseable_plus_unknown(self):
        block = mod.classify_skips(Counter({"staleness_check": 78, "None": 1}),
                                   "hook", MEMBERSHIP,
                                   unparseable_count=70,
                                   unparseable_bucket="unparseable")
        c = _counts(block)
        assert c == {"unparseable": 70, "genuinely_unknown": 79}
        assert block["total_skips"] == 149
        assert "builtin_floor_note" not in block

    def test_builtin_floor_note_is_permanent_statement(self):
        block = mod.classify_skips(Counter({"general-purpose": 1}),
                                   "governance_agent", MEMBERSHIP)
        assert "never trends to zero" in block["builtin_floor_note"]

    def test_deterministic_and_top_values_ordering(self):
        unmatched = Counter({"b-unknown": 5, "a-unknown": 5, "c-unknown": 9})
        b1 = mod.classify_skips(unmatched, "governance_skill", MEMBERSHIP)
        b2 = mod.classify_skips(Counter(dict(reversed(list(unmatched.items())))),
                                "governance_skill", MEMBERSHIP)
        assert json.dumps(b1, sort_keys=True) == json.dumps(b2, sort_keys=True)
        # count desc, then name asc
        assert b1["buckets"]["genuinely_unknown"]["top_values"] == [
            ["c-unknown", 9], ["a-unknown", 5], ["b-unknown", 5]]


class TestWindow:
    def test_window_bounds_exactly_30_days(self):
        s_iso, e_iso, s_cmp, e_cmp = mod.window_bounds("2026-09-01T12:00:00Z")
        assert s_iso == "2026-08-02T12:00:00Z"
        assert e_iso == "2026-09-01T12:00:00Z"
        assert s_cmp == "2026-08-02T12:00:00" and e_cmp == "2026-09-01T12:00:00"

    def test_ts_in_window_boundaries_inclusive_and_none(self):
        s, e = "2026-08-02T12:00:00", "2026-09-01T12:00:00"
        assert mod.ts_in_window("2026-08-02T12:00:00", s, e) is True
        assert mod.ts_in_window("2026-09-01T12:00:00", s, e) is True
        assert mod.ts_in_window("2026-08-02T11:59:59", s, e) is False
        assert mod.ts_in_window(None, s, e) is None
        assert mod.ts_in_window("garbage", s, e) is None

    def test_governance_windowed_accounting(self, tmp_path):
        log = tmp_path / "gov.jsonl"
        recs = [
            # in window, matched agent, one matched + one unmatched skill item
            {"ts": "2026-08-20 10:00:00", "event": "agent_dispatched",
             "agent_type": "architect-reviewer",
             "skill_context": ["process-qa", "architect-reviewer"]},
            # out of window entirely
            {"ts": "2026-07-01 10:00:00", "event": "agent_dispatched",
             "agent_type": "architect-reviewer", "skill_context": ["process-qa"]},
            # in window, unmatched agent
            {"ts": "2026-08-21 10:00:00", "event": "agent_dispatched",
             "agent_type": "general-purpose", "skill_context": []},
            # no ts: agent and its one skill item land in no_ts
            {"event": "agent_dispatched", "agent_type": "architect-reviewer",
             "skill_context": ["pm"]},
        ]
        log.write_text("\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
        out = mod.process_governance_log(
            log, {"architect-reviewer"}, {"process-qa", "pm"},
            window_start_cmp="2026-08-02T12:00:00",
            window_end_cmp="2026-09-01T12:00:00")
        wa, wsk = out["windowed_agent"], out["windowed_skill"]
        assert wa["matched"] == 1
        assert wa["no_ts"] == 1
        assert dict(wa["unmatched_values"]) == {"general-purpose": 1}
        assert wsk["matched"] == 1
        assert wsk["no_ts"] == 1
        assert dict(wsk["unmatched_values"]) == {"architect-reviewer": 1}
        # all-history figures unchanged by the windowing
        assert out["total_agent_dispatched"] == 4
        assert out["skipped_agent"] == 1
        # one unmatched skill item all-history: rec1's architect-reviewer
        # (process-qa and pm both match; rec4's pm matches despite no ts)
        assert out["skipped_skill"] == 1

    def test_hook_windowed_accounting_counts_unparseable_line_as_no_ts(self, tmp_path):
        log = tmp_path / "hook.jsonl"
        lines = [
            json.dumps({"ts": "2026-08-20 10:00:00", "hook": "known-hook"}),
            json.dumps({"ts": "2026-07-01 10:00:00", "hook": "known-hook"}),
            json.dumps({"ts": "2026-08-21 10:00:00", "hook": "mystery"}),
            "{not json",
        ]
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out = mod.process_hook_activity(
            log, {"known-hook"},
            window_start_cmp="2026-08-02T12:00:00",
            window_end_cmp="2026-09-01T12:00:00")
        w = out["windowed"]
        assert w["matched"] == 1
        assert w["no_ts"] == 1
        assert dict(w["unmatched_values"]) == {"mystery": 1}
        assert out["total_lines"] == 4
        assert out["skipped"] == 2

    def test_windowed_scope_block_reconciles(self):
        block = mod.windowed_scope_block(
            {"matched": 10, "no_ts": 2,
             "unmatched_values": Counter({"general-purpose": 3, "unknown-x": 1})},
            "governance_agent", MEMBERSHIP)
        assert block["total_in_scope"] == block["matched"] + block["skipped"]
        assert block["skipped"] == 6
        assert block["skip_taxonomy"]["total_skips"] == 6
        assert block["skip_taxonomy"]["buckets"]["unparseable_or_no_ts"]["count"] == 2


class TestEnumerationFingerprint:
    def test_order_independent_and_deterministic(self):
        fp1 = mod.enumeration_fingerprint({"b", "a"}, {"x"}, {"s1", "s2"})
        fp2 = mod.enumeration_fingerprint({"a", "b"}, {"x"}, {"s2", "s1"})
        assert fp1 == fp2

    def test_digests_are_hex64_and_sizes_correct(self):
        fp = mod.enumeration_fingerprint({"a", "b"}, {"x"}, {"s1", "s2", "s3"})
        for k in ("hook_match_set_sha256", "agent_match_set_sha256",
                  "skill_match_set_sha256", "combined_sha256"):
            assert len(fp[k]) == 64 and int(fp[k], 16) >= 0
        assert fp["hook_match_set_size"] == 2
        assert fp["agent_match_set_size"] == 1
        assert fp["skill_match_set_size"] == 3

    def test_set_change_moves_exactly_that_digest_and_combined(self):
        base = mod.enumeration_fingerprint({"a"}, {"x"}, {"s"})
        changed = mod.enumeration_fingerprint({"a", "NEW"}, {"x"}, {"s"})
        assert base["hook_match_set_sha256"] != changed["hook_match_set_sha256"]
        assert base["agent_match_set_sha256"] == changed["agent_match_set_sha256"]
        assert base["skill_match_set_sha256"] == changed["skill_match_set_sha256"]
        assert base["combined_sha256"] != changed["combined_sha256"]
