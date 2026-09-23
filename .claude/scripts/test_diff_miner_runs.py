#!/usr/bin/env python3
"""Tests for diff_miner_runs.py (N3) — the recurrence-diff measurement leg.

Stdlib unittest, fully deterministic (fixed now_date, temp fixture files, no
clock reads, no network, no live-log dependency).

Covers all four verdict classes: RESOLVED, OPEN, REGRESSED, NEW — including the
PINNED anti-masking case (spec Section 9, R2): a ledgered-but-recurring sig_id
that the real-ledger (suppressed) mine() call HIDES must be classified REGRESSED
by the diff script. If that assertion is absent the acceptance FAILS.

Run: python .claude/scripts/test_diff_miner_runs.py
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import diff_miner_runs as dmr
from diff_miner_runs import (
    RESOLVED,
    OPEN,
    REGRESSED,
    NEW,
    classify,
    diff_runs,
    _ledger_sig_ids,
    _load_prior_counts,
)

# Fixed reference date for determinism.
_NOW = date(2026, 6, 10)


def _emit_records(fh, event, agent_type, hook, reason, n, start_day, now=_NOW):
    """Write n admitted 'deny'/block-class records spread across n distinct days
    ending at (now - start_day). Each record is a distinct calendar day so the
    miner's distinct-days gate (D>=3) is satisfied when n>=3.

    Uses event='deny' with a non-empty block_reason so the record is admitted by
    mine()'s allowlist, and a fixed reason so all n collapse to ONE sig_id.
    """
    for i in range(n):
        d = now - timedelta(days=start_day + i)
        rec = {
            "ts": d.isoformat() + "T12:00:00Z",
            "event": event,
            "agent_type": agent_type,
            "hook": hook,
            "block_reason": reason,
            # REV-7 (2026-08-01) made miner admission a positive UUID-shape allowlist
            # instead of a literal-exclusion list, so a fixture representing REAL
            # session activity must carry a UUID-shaped id or it is filtered out.
            "session": "692cfdb4-b18a-4c31-9f77-1a2b3c4d5e6f",
        }
        fh.write(json.dumps(rec) + "\n")


def _sig_id_for(event_label, agent_type, hook, reason):
    """Compute the sig_id the miner will assign, using the miner's own helpers,
    so the test asserts against real sig_ids (no hardcoded hashes)."""
    from mine_governance import _sig_id, _sig_key, _normalize_reason
    key = _sig_key(event_label, agent_type, hook, _normalize_reason(reason))
    return _sig_id(key)


class DiffMinerRunsTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="diffminer_")

        # Build a log with THREE distinct recurring sigs, each count=12 over 12
        # distinct days (well above the normal-severity gate C=10, D>=3):
        #   S_OPEN      — deny/agentX/hookA  (never ledgered)          -> OPEN
        #   S_REGRESS   — deny/agentY/hookB  (ledgered but recurring)  -> REGRESSED
        #   (a fourth ledgered sig S_RESOLVED is in the ledger but ABSENT from the
        #    log entirely -> RESOLVED)
        self.log = os.path.join(self.tmp, "log.jsonl")
        with open(self.log, "w", encoding="utf-8") as fh:
            _emit_records(fh, "deny", "agentX", "hookA",
                          "open reason alpha", n=12, start_day=0)
            _emit_records(fh, "deny", "agentY", "hookB",
                          "regressing reason beta", n=12, start_day=0)

        self.sid_open = _sig_id_for("deny", "agentX", "hookA", "open reason alpha")
        self.sid_regress = _sig_id_for("deny", "agentY", "hookB", "regressing reason beta")
        # A sig that is ledgered but never appears in the log -> RESOLVED.
        self.sid_resolved = _sig_id_for("deny", "agentZ", "hookC", "resolved reason gamma")
        # A brand-new sig for the NEW class: present in log, not ledgered, not in prior.
        self.sid_new = self.sid_open  # will re-key below for the NEW-specific test

        # Real ledger: suppresses S_REGRESS and S_RESOLVED.
        self.ledger = os.path.join(self.tmp, "ledger.jsonl")
        with open(self.ledger, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"sig_id": self.sid_regress,
                                 "resolved_ts": "2026-05-01",
                                 "resolution": "accepted-as-designed",
                                 "note": "ruled"}) + "\n")
            fh.write(json.dumps({"sig_id": self.sid_resolved,
                                 "resolved_ts": "2026-05-01",
                                 "resolution": "tuned",
                                 "note": "ruled"}) + "\n")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    # ------------------------------------------------------------------
    # Sanity: the real-ledger (suppressed) mine() call HIDES the regressing sig.
    # This is the masking the diff script must defeat.
    # ------------------------------------------------------------------
    def test_real_ledger_call_hides_regressing_sig(self):
        from mine_governance import mine, WINDOW_DAYS
        # The ledgered sig regressed BEFORE resolved_ts=2026-05-01? No: our records
        # are dated late May/June (now=2026-06-10), i.e. AFTER resolved_ts. The
        # miner's regression logic re-surfaces a post-resolved recurrence, so to
        # make the ledger genuinely HIDE it we set resolved_ts AFTER the records.
        # Re-point the ledger to a resolved_ts later than every record so the
        # miner suppresses (no post-resolved occurrences).
        late_ledger = os.path.join(self.tmp, "ledger_late.jsonl")
        with open(late_ledger, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"sig_id": self.sid_regress,
                                 "resolved_ts": "2026-06-30",
                                 "resolution": "accepted-as-designed",
                                 "note": "ruled"}) + "\n")
        suppressed = mine(self.log, _NOW, WINDOW_DAYS, resolved_ledger_path=late_ledger)
        supp_ids = {r["sig_id"] for r in suppressed}
        self.assertNotIn(self.sid_regress, supp_ids,
                         "real-ledger mine() should HIDE the ledgered sig")

    # ------------------------------------------------------------------
    # PINNED anti-masking case (R2): ledgered-but-recurring -> REGRESSED.
    # The diff uses the UNSUPPRESSED (empty-ledger) call, so the sig is visible;
    # classify() marks it REGRESSED because it is ledgered AND recurs at >= prior.
    # ------------------------------------------------------------------
    def test_ledgered_but_recurring_is_regressed(self):
        # Ledger with a late resolved_ts so the operational call would suppress it.
        late_ledger = os.path.join(self.tmp, "ledger_late.jsonl")
        with open(late_ledger, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"sig_id": self.sid_regress,
                                 "resolved_ts": "2026-06-30",
                                 "resolution": "accepted-as-designed",
                                 "note": "ruled"}) + "\n")
        # Prior run recorded the regressing sig at count 12.
        prior = os.path.join(self.tmp, "prior.json")
        with open(prior, "w", encoding="utf-8") as fh:
            json.dump({"sig_counts": {self.sid_regress: 12, self.sid_open: 12}}, fh)

        classified, unsuppressed, suppressed = diff_runs(
            self.log, late_ledger, _NOW, prior_path=prior
        )
        # The operational (suppressed) call hides it...
        self.assertNotIn(self.sid_regress, {r["sig_id"] for r in suppressed})
        # ...but the diff classifies it REGRESSED, defeating the mask.
        self.assertIn(self.sid_regress, classified)
        self.assertEqual(classified[self.sid_regress]["verdict"], REGRESSED,
                         "ledgered-but-recurring sig MUST be REGRESSED (R2)")

    # ------------------------------------------------------------------
    # OPEN: present, not ledgered, seen in prior.
    # ------------------------------------------------------------------
    def test_open_class(self):
        prior = os.path.join(self.tmp, "prior.json")
        with open(prior, "w", encoding="utf-8") as fh:
            json.dump({"sig_counts": {self.sid_open: 12}}, fh)
        classified, _u, _s = diff_runs(self.log, self.ledger, _NOW, prior_path=prior)
        self.assertIn(self.sid_open, classified)
        self.assertEqual(classified[self.sid_open]["verdict"], OPEN)
        self.assertFalse(classified[self.sid_open]["ledgered"])

    # ------------------------------------------------------------------
    # NEW: present, not ledgered, absent from prior.
    # ------------------------------------------------------------------
    def test_new_class(self):
        # Empty prior => S_OPEN is not in prior => NEW.
        classified, _u, _s = diff_runs(self.log, self.ledger, _NOW, prior_path=None)
        self.assertIn(self.sid_open, classified)
        self.assertEqual(classified[self.sid_open]["verdict"], NEW)

    # ------------------------------------------------------------------
    # RESOLVED: ledgered, absent from the current unsuppressed run.
    # ------------------------------------------------------------------
    def test_resolved_class(self):
        prior = os.path.join(self.tmp, "prior.json")
        with open(prior, "w", encoding="utf-8") as fh:
            json.dump({"sig_counts": {self.sid_resolved: 12}}, fh)
        classified, _u, _s = diff_runs(self.log, self.ledger, _NOW, prior_path=prior)
        self.assertIn(self.sid_resolved, classified)
        self.assertEqual(classified[self.sid_resolved]["verdict"], RESOLVED)
        self.assertEqual(classified[self.sid_resolved]["count"], 0)

    # ------------------------------------------------------------------
    # All four classes present simultaneously in one classify() call.
    # ------------------------------------------------------------------
    def test_all_four_classes_in_one_run(self):
        late_ledger = os.path.join(self.tmp, "ledger_mixed.jsonl")
        with open(late_ledger, "w", encoding="utf-8") as fh:
            # S_REGRESS ledgered late (recurs -> REGRESSED)
            fh.write(json.dumps({"sig_id": self.sid_regress,
                                 "resolved_ts": "2026-06-30",
                                 "resolution": "accepted-as-designed"}) + "\n")
            # S_RESOLVED ledgered, absent from log (-> RESOLVED)
            fh.write(json.dumps({"sig_id": self.sid_resolved,
                                 "resolved_ts": "2026-05-01",
                                 "resolution": "tuned"}) + "\n")
        # Prior contains S_REGRESS and S_OPEN (so S_OPEN -> OPEN);
        # S_new sig is not manufactured here; the second recurring sig without a
        # prior entry becomes NEW. Use S_open as OPEN and force a NEW via a prior
        # that omits it.
        prior = os.path.join(self.tmp, "prior_mixed.json")
        with open(prior, "w", encoding="utf-8") as fh:
            json.dump({"sig_counts": {self.sid_regress: 12}}, fh)  # omit sid_open

        classified, _u, _s = diff_runs(self.log, late_ledger, _NOW, prior_path=prior)
        verdicts = {sid: info["verdict"] for sid, info in classified.items()}
        # sid_open: not ledgered, not in prior -> NEW
        self.assertEqual(verdicts.get(self.sid_open), NEW)
        # sid_regress: ledgered, recurs at >= prior -> REGRESSED
        self.assertEqual(verdicts.get(self.sid_regress), REGRESSED)
        # sid_resolved: ledgered, absent -> RESOLVED
        self.assertEqual(verdicts.get(self.sid_resolved), RESOLVED)
        # Assert all four labels are representable: add an OPEN by re-running with
        # a prior that includes sid_open.
        prior2 = os.path.join(self.tmp, "prior_open.json")
        with open(prior2, "w", encoding="utf-8") as fh:
            json.dump({"sig_counts": {self.sid_open: 12, self.sid_regress: 12}}, fh)
        classified2, _u2, _s2 = diff_runs(self.log, late_ledger, _NOW, prior_path=prior2)
        self.assertEqual(classified2[self.sid_open]["verdict"], OPEN)
        self.assertEqual(classified2[self.sid_regress]["verdict"], REGRESSED)
        # Four distinct verdict labels observed across the two runs.
        seen = {verdicts[self.sid_open], verdicts[self.sid_regress],
                verdicts[self.sid_resolved], classified2[self.sid_open]["verdict"]}
        self.assertEqual(seen, {NEW, REGRESSED, RESOLVED, OPEN})

    # ------------------------------------------------------------------
    # Missing prior handled gracefully (no crash; present sigs are NEW).
    # ------------------------------------------------------------------
    def test_missing_prior_graceful(self):
        classified, _u, _s = diff_runs(self.log, self.ledger, _NOW, prior_path="/does/not/exist")
        self.assertIn(self.sid_open, classified)
        # not ledgered, no prior -> NEW
        self.assertEqual(classified[self.sid_open]["verdict"], NEW)

    # ------------------------------------------------------------------
    # Helpers: ledger reader + prior loader tolerate junk.
    # ------------------------------------------------------------------
    def test_ledger_reader_tolerates_missing(self):
        self.assertEqual(_ledger_sig_ids(None), set())
        self.assertEqual(_ledger_sig_ids("/nope"), set())

    def test_prior_loader_tolerates_missing_and_bare_dict(self):
        self.assertEqual(_load_prior_counts(None), {})
        bare = os.path.join(self.tmp, "bare.json")
        with open(bare, "w", encoding="utf-8") as fh:
            json.dump({self.sid_open: 5}, fh)
        self.assertEqual(_load_prior_counts(bare), {self.sid_open: 5})


    # ------------------------------------------------------------------
    # GAP fix: nonexistent --log path must exit non-zero and write no snapshot.
    # ------------------------------------------------------------------
    def test_nonexistent_log_path_exits_nonzero(self):
        import subprocess
        bogus_log = os.path.join(self.tmp, "does_not_exist.jsonl")
        out_path = os.path.join(self.tmp, "should_not_be_created.json")
        script = os.path.join(_THIS_DIR, "diff_miner_runs.py")
        result = subprocess.run(
            [sys.executable, script,
             "--log", bogus_log,
             "--ledger", self.ledger,
             "--out", out_path],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0,
                            "script must exit non-zero when --log path does not exist")
        self.assertFalse(os.path.exists(out_path),
                         "script must NOT write a snapshot when --log does not exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
