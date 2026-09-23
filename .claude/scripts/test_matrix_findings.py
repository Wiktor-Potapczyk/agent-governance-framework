"""Tests for the matrix-as-gate checks (contract C5).

Written 2026-08-01, before the implementation.

C5 as originally worded says "a registered asset without a matrix row is a
lint finding". Taken literally that is close to vacuous: the matrix is
GENERATED from the settings files, so a registered hook always has a row. The
checks with real content are the ones where generation cannot paper over a
problem:

  MISSING_SOURCE    a hook is registered but its .py file is not on disk
  DARK_HOOK         a registered hook writes to no sink at all (contract C1)
  HOOK_NAME_DRIFT   a hook emits a `hook:` value that is not its own filename

The last one is inherited from the C7 audit, which found that convergence on
the shared writer does NOT fix naming drift: the helper takes `hook` as an
unchecked caller string. A rule that is only a convention drifts, so it needs
a check, and this is where it belongs.
"""

import importlib.util
import json
import os
import tempfile
import unittest


def _load(vault_dir=None):
    if vault_dir:
        os.environ["VAULT_DIR"] = str(vault_dir)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hook_activity_report.py")
    spec = importlib.util.spec_from_file_location("har_findings", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Fixture:
    """Builds a throwaway vault with its own settings file and hook sources."""

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.hooks = os.path.join(self.dir, ".claude", "hooks")
        os.makedirs(self.hooks)

    def hook(self, name, body):
        with open(os.path.join(self.hooks, name + ".py"), "w", encoding="utf-8") as fh:
            fh.write(body)

    def register(self, names, event="PostToolUse"):
        settings = {
            "hooks": {
                event: [{
                    "hooks": [
                        {"command": "python .claude/hooks/%s.py" % n} for n in names
                    ]
                }]
            }
        }
        p = os.path.join(self.dir, ".claude", "settings.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(settings, fh)


class MissingSourceTests(unittest.TestCase):
    def test_registered_hook_with_no_file_on_disk_is_a_finding(self):
        fx = _Fixture()
        fx.register(["ghost-hook"])
        m = _load(fx.dir)
        kinds = [f["kind"] for f in m.matrix_findings()]
        self.assertIn("MISSING_SOURCE", kinds)

    def test_the_finding_names_the_hook(self):
        fx = _Fixture()
        fx.register(["ghost-hook"])
        m = _load(fx.dir)
        f = [f for f in m.matrix_findings() if f["kind"] == "MISSING_SOURCE"][0]
        self.assertEqual(f["hook"], "ghost-hook")


class DarkHookTests(unittest.TestCase):
    def test_a_hook_with_no_sink_is_a_finding(self):
        fx = _Fixture()
        fx.hook("silent-hook", "print('{}')\n")
        fx.register(["silent-hook"])
        m = _load(fx.dir)
        kinds = [f["kind"] for f in m.matrix_findings()]
        self.assertIn("DARK_HOOK", kinds)

    def test_a_hook_that_logs_fires_is_not_a_finding(self):
        fx = _Fixture()
        fx.hook("loud-hook", "from _governance_logger import log_fire\nlog_fire('loud-hook')\n")
        fx.register(["loud-hook"])
        m = _load(fx.dir)
        kinds = [f["kind"] for f in m.matrix_findings()]
        self.assertNotIn("DARK_HOOK", kinds)


class NameDriftTests(unittest.TestCase):
    def test_emitting_a_different_name_than_the_filename_is_a_finding(self):
        fx = _Fixture()
        fx.hook("thing-check", 'from _event_emit import emit_event\nemit_event(event="e", hook="thing", session="s")\n')
        fx.register(["thing-check"])
        m = _load(fx.dir)
        drift = [f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"]
        self.assertEqual(len(drift), 1)
        self.assertEqual(drift[0]["hook"], "thing-check")
        self.assertIn("thing", drift[0]["detail"])

    def test_matching_name_is_not_a_finding(self):
        fx = _Fixture()
        fx.hook("thing-check", 'from _event_emit import emit_event\nemit_event(event="e", hook="thing-check", session="s")\n')
        fx.register(["thing-check"])
        m = _load(fx.dir)
        self.assertEqual([f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"], [])

    def test_underscores_and_hyphens_are_the_same_name(self):
        # check_forbidden_tokens.py legitimately emits "check-forbidden-tokens".
        fx = _Fixture()
        fx.hook("check_forbidden_tokens",
                'from _event_emit import emit_event\nemit_event(event="e", hook="check-forbidden-tokens", session="s")\n')
        fx.register(["check_forbidden_tokens"])
        m = _load(fx.dir)
        self.assertEqual([f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"], [])

    def test_a_name_in_the_module_docstring_is_not_counted(self):
        # _governance_logger's docstring shows log_fire("this-hook-name").
        fx = _Fixture()
        fx.hook("doc-check", '"""Example: emit_event(event="e", hook="not-me", session="s")"""\nprint("{}")\nfrom _event_emit import emit_event\n')
        fx.register(["doc-check"])
        m = _load(fx.dir)
        self.assertEqual([f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"], [])

    def test_a_local_helper_named_log_fire_is_not_mistaken_for_the_shared_one(self):
        # _log_fire("ok") contains the substring log_fire("ok"). A naive pattern
        # reads the decision string as a hook name. This bit me while measuring.
        fx = _Fixture()
        fx.hook("wrapper-check",
                'from _governance_logger import log_fire\n'
                'def _log_fire(d):\n    log_fire("wrapper-check", decision=d)\n'
                '_log_fire("ok")\n')
        fx.register(["wrapper-check"])
        m = _load(fx.dir)
        self.assertEqual([f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"], [])


class GrandfatherTests(unittest.TestCase):
    """Two hooks drift today. They are listed explicitly so NEW drift still
    fails while the known exceptions stay visible and reviewable, rather than
    the check being weakened to accommodate them."""

    def test_the_known_exceptions_are_named_not_silently_skipped(self):
        m = _load()
        self.assertIn("dispatch-compliance-check", m.HOOK_NAME_GRANDFATHERED)
        self.assertIn("verifier-gate-check", m.HOOK_NAME_GRANDFATHERED)

    def test_a_grandfathered_hook_produces_no_finding(self):
        fx = _Fixture()
        fx.hook("dispatch-compliance-check",
                'from _event_emit import emit_event\nemit_event(event="e", hook="dispatch-compliance", session="s")\n')
        fx.register(["dispatch-compliance-check"])
        m = _load(fx.dir)
        self.assertEqual([f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"], [])


class VocabularyGeneratorTests(unittest.TestCase):
    """Hermes P3 step 4 (2026-08-18): failing-first tests for the telemetry
    vocabulary generator. Written BEFORE the --vocab implementation, per the
    declarative-first Build rule. They pin the exact behaviors step 5 must
    implement: literal derivation from writer source (kwarg, dict-key and
    wrapper-call-site forms), grandfather passthrough as data, artifact shape
    with an isolated generation stamp, and byte-identical regeneration on an
    unchanged tree. Fixtures are throwaway vaults; no live sink path appears
    anywhere in this class."""

    def _fx(self):
        fx = _Fixture()
        fx.hook("alpha-check",
                'from _event_emit import emit_event\n'
                'emit_event(event="alpha_fired", hook="alpha-check", session="s")\n')
        fx.hook("beta-guard",
                'from _governance_logger import log_fire\n'
                'log_fire("beta-guard", decision="beta-warn")\n')
        fx.register(["alpha-check", "beta-guard"])
        return fx

    def test_event_literals_derive_from_writer_source(self):
        m = _load(self._fx().dir)
        v = m.vocab_dict()
        vals = {e["value"]: e
                for e in v["sinks"]["governance-log.jsonl"]["axes"]["event"]["values"]}
        self.assertIn("alpha_fired", vals)
        self.assertIn("hooks/alpha-check.py", vals["alpha_fired"]["writers"])

    def test_decision_literals_derive_from_writer_source(self):
        m = _load(self._fx().dir)
        v = m.vocab_dict()
        vals = {e["value"]: e
                for e in v["sinks"]["hook-activity.jsonl"]["axes"]["decision"]["values"]}
        self.assertIn("beta-warn", vals)
        self.assertIn("hooks/beta-guard.py", vals["beta-warn"]["writers"])

    def test_wrapper_call_site_literals_derive(self):
        # the dominant live idiom: a local helper whose parameter is literally
        # named `decision`, with string-literal call sites (em-dash-guard,
        # git-credential-scope-check, memory-schema-check, ...)
        fx = _Fixture()
        fx.hook("gamma-check",
                'from _governance_logger import log_fire\n'
                'def _log(decision, detail=None):\n'
                '    log_fire("gamma-check", decision=decision, detail=detail)\n'
                '_log("gamma-quiet")\n')
        fx.register(["gamma-check"])
        m = _load(fx.dir)
        vals = {e["value"] for e in
                m.vocab_dict()["sinks"]["hook-activity.jsonl"]["axes"]["decision"]["values"]}
        self.assertIn("gamma-quiet", vals)

    def test_grandfathered_values_survive_generation_as_data(self):
        # `override` was written by config-protection.py, removed 2026-08-07;
        # the 4 real historical records stay legal via the reviewed grandfather
        # list, carried as data so the honesty class survives generation.
        m = _load(self._fx().dir)
        self.assertTrue(any(
            g["value"] == "override"
            for g in m.VOCAB_GRANDFATHERED["governance-log.jsonl"]["event"]))
        vals = {e["value"]: e
                for e in m.vocab_dict()["sinks"]["governance-log.jsonl"]["axes"]["event"]["values"]}
        self.assertIn("override", vals)
        self.assertTrue(vals["override"]["grandfathered"])

    def test_artifact_shape_three_sinks_and_isolated_stamp(self):
        m = _load(self._fx().dir)
        v = m.vocab_dict()
        self.assertEqual(sorted(v), ["generated", "sinks"])
        self.assertEqual(sorted(v["sinks"]),
                         ["governance-log.jsonl", "hook-activity.jsonl",
                          "plain-language-warnings.jsonl"])
        self.assertIn("at", v["generated"])
        self.assertIn("generator", v["generated"])
        self.assertIn("inputs", v["generated"])

    def test_vocab_write_is_deterministic_outside_stamp(self):
        fx = self._fx()
        m = _load(fx.dir)
        p1 = os.path.join(fx.dir, "v1.json")
        p2 = os.path.join(fx.dir, "v2.json")
        m.write_vocab(p1)
        m.write_vocab(p2)
        with open(p1, encoding="utf-8") as fh:
            a = json.load(fh)
        with open(p2, encoding="utf-8") as fh:
            b = json.load(fh)
        a.pop("generated")
        b.pop("generated")
        self.assertEqual(a, b)

    def test_vocab_write_twice_to_same_path_is_byte_identical(self):
        # stamp-only-on-content-change: an unchanged tree regenerates the
        # identical file, stamp included
        fx = self._fx()
        m = _load(fx.dir)
        p = os.path.join(fx.dir, "v.json")
        m.write_vocab(p)
        with open(p, "rb") as fh:
            first = fh.read()
        m.write_vocab(p)
        with open(p, "rb") as fh:
            second = fh.read()
        self.assertEqual(first, second)

    def test_live_vault_derives_all_ten_pl_rule_keys(self):
        os.environ.pop("VAULT_DIR", None)
        m = _load()
        keys = {e["value"] for e in
                m.vocab_dict()["sinks"]["plain-language-warnings.jsonl"]
                ["axes"]["per_rule_finding_counts_keys"]["values"]}
        self.assertEqual(keys, {"PL-%d" % i for i in range(1, 11)})

    def test_existing_cli_flags_still_dispatched(self):
        # no-regression stub: the four pre-existing flags survive the vocab
        # additions; behavior-level no-regression is the build CHECK's diff of
        # captured pre-build outputs against fresh runs
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "hook_activity_report.py")
        with open(p, encoding="utf-8") as fh:
            src = fh.read()
        for flag in ("--yield", "--matrix", "--findings", "--json",
                     "--vocab", "--vocab-write"):
            self.assertIn('"%s"' % flag, src)


class LiveVaultTests(unittest.TestCase):
    def test_the_live_vault_has_no_ungrandfathered_name_drift(self):
        os.environ.pop("VAULT_DIR", None)
        m = _load()
        drift = [f for f in m.matrix_findings() if f["kind"] == "HOOK_NAME_DRIFT"]
        self.assertEqual(drift, [], "unexpected drift: %s" % drift)

    def test_the_live_vault_has_no_dark_hooks(self):
        os.environ.pop("VAULT_DIR", None)
        m = _load()
        dark = [f for f in m.matrix_findings() if f["kind"] == "DARK_HOOK"]
        self.assertEqual(dark, [], "unexpected dark hooks: %s" % dark)


if __name__ == "__main__":
    unittest.main()
