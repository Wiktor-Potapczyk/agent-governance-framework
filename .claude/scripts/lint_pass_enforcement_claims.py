#!/usr/bin/env python3
"""Lint Pass V: ENFORCEMENT_CLAIM_STALE (ROAD-9, 2026-09-08).

Advisory drift check between doctrine's enforcement-tier claims and the
live enforcement reality. A claims registry
(`_state/enforcement-claims.json`) lists locations and expectations only:
(doctrine file, anchor text, claimed tier or registration, authority file).
This pass re-derives the ACTUAL tier from the authority at run time (hook
source markers, rules-file ruling paragraph, or settings registration) and
emits one ENFORCEMENT_CLAIM_STALE finding per mismatch. The registry never
stores a derived tier, and this pass never edits the registry, any doctrine
file, or any state file.

Anchor semantics: `anchor` must appear verbatim in `doctrine_file`. An
absent anchor is a FINDING (reason `anchor-missing`), not a skip: deleting
a monitored doctrine annotation is itself drift. A missing or unreadable
authority file, a malformed registry, or an unmatched `authority_anchor`
is a DERIVATION FAILURE (exit 2): doctrine drift is what is measured, a
broken measuring apparatus halts loudly instead.

CLI contract (shared by all lint_pass_* scripts):
  - always prints its measurement line:
      `ENFORCEMENT_CLAIMS claims=<n> ok=<k> stale=<s>`
  - finding: `ENFORCEMENT_CLAIM_STALE  id=<id> reason=<tier-mismatch|`
    `anchor-missing|registration-missing> claimed=<c> derived=<d>`
  - exit 0 clean, 1 findings, 2 derivation failure (prints
    `DERIVATION FAILURE: <detail>` and, per the fail-loud clause, no
    findings and no summary on that path; never a silent clean report)
"""
import argparse
import json
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
VAULT = SCRIPTS.parent.parent

HOOK_HEADER_LINES = 40
DENY_LITERAL_RE = re.compile(r'"permissionDecision"\s*:\s*"deny"')
ADVISORY_HEADER_MARKERS = ("advisory", "does not block", "never blocks",
                           "non-blocking")
WARN_HEADER_RE = re.compile(r"warn-only|\bWARNS\b")
# rules_md negation handling: consumed BEFORE token scoring; all four count
# as non-deny evidence, "would-block" is a counterfactual measurement
# compound, not a tier assertion (calibrated against the live layer-2
# wording of wiki-architecture.md).
NEGATED_FORMS = ("non-blocking", "never blocks", "not blocking",
                 "warn-only", "would-block")
DENY_TOKEN_RE = re.compile(r"\b(deny|denies|denied|blocks|block|blocking)\b",
                           re.IGNORECASE)
ADVISORY_TOKEN_RE = re.compile(r"\badvisory\b", re.IGNORECASE)
WARN_TOKEN_RE = re.compile(r"\b(warns|warn|warning)\b", re.IGNORECASE)
PY_NAME_RE = re.compile(r"([\w-]+\.py)")


class DerivationFailure(Exception):
    pass


def read_text(path, what):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise DerivationFailure(f"{what} unreadable ({path}): {e}")


def load_settings(settings_file, cache={}):
    key = str(settings_file)
    if key not in cache:
        try:
            cache[key] = json.loads(
                Path(settings_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise DerivationFailure(
                f"settings file unusable ({settings_file}): {e}")
    return cache[key]


def registered_events(settings, hook_filename):
    """Events whose registered commands mention hook_filename, sorted."""
    matched = set()
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise DerivationFailure("settings 'hooks' key is not an object")
    for event, entries in hooks.items():
        for entry in entries or []:
            for h in entry.get("hooks", []) or []:
                if hook_filename in h.get("command", ""):
                    matched.add(event)
    return sorted(matched)


def derive_hook_source(claim, vault_root, settings_file):
    source = read_text(vault_root / claim["authority_file"], "authority file")
    header = "\n".join(source.splitlines()[:HOOK_HEADER_LINES]).lower()
    deny_marker = bool(DENY_LITERAL_RE.search(source))
    advisory_marker = any(m in header for m in ADVISORY_HEADER_MARKERS)
    warn_marker = bool(WARN_HEADER_RE.search(
        "\n".join(source.splitlines()[:HOOK_HEADER_LINES])))
    if deny_marker and advisory_marker:
        raise DerivationFailure(
            f"{claim['id']}: hook source carries both a permissionDecision "
            "deny literal and an advisory header")
    if deny_marker:
        events = registered_events(load_settings(settings_file),
                                   Path(claim["authority_file"]).name)
        if events == ["PreToolUse"] or "PreToolUse" in events:
            return "deny"
        raise DerivationFailure(
            f"{claim['id']}: deny literal in source but registration is "
            f"{events or 'absent'}, not PreToolUse")
    if advisory_marker:
        return "advisory"
    if warn_marker:
        return "warn"
    raise DerivationFailure(
        f"{claim['id']}: zero tier markers in hook source header "
        f"({claim['authority_file']})")


def containing_paragraph(text, anchor):
    for block in re.split(r"\n\s*\n", text):
        if anchor in block:
            return block
    return None


def derive_rules_md(claim, vault_root):
    text = read_text(vault_root / claim["authority_file"], "authority file")
    authority_anchor = claim.get("authority_anchor")
    if not authority_anchor:
        raise DerivationFailure(
            f"{claim['id']}: rules_md claim without authority_anchor")
    para = containing_paragraph(text, authority_anchor)
    if para is None:
        raise DerivationFailure(
            f"{claim['id']}: authority_anchor not found in "
            f"{claim['authority_file']}")
    reduced = para
    negations_found = False
    warn_evidence = False
    for form in NEGATED_FORMS:
        if re.search(re.escape(form), reduced, re.IGNORECASE):
            negations_found = True
            if form == "warn-only":
                warn_evidence = True
            reduced = re.sub(re.escape(form), " ", reduced,
                             flags=re.IGNORECASE)
    deny_score = len(DENY_TOKEN_RE.findall(reduced))
    advisory_score = len(ADVISORY_TOKEN_RE.findall(reduced))
    warn_score = len(WARN_TOKEN_RE.findall(reduced))
    if deny_score and (advisory_score or negations_found):
        raise DerivationFailure(
            f"{claim['id']}: ruling region carries both deny and non-deny "
            "evidence after negation handling")
    if deny_score:
        return "deny"
    if advisory_score:
        return "advisory"
    if warn_evidence or warn_score:
        return "warn"
    raise DerivationFailure(
        f"{claim['id']}: zero tier keywords in the ruling region of "
        f"{claim['authority_file']}")


def derive_settings(claim, settings_file):
    m = PY_NAME_RE.search(claim["anchor"])
    if not m:
        raise DerivationFailure(
            f"{claim['id']}: settings claim anchor names no hook .py file")
    events = registered_events(load_settings(settings_file), m.group(1))
    if not events:
        return "unregistered"
    return "registered:" + "+".join(events)


def derive(claim, vault_root, settings_file):
    kind = claim.get("authority_kind")
    if kind == "hook_source":
        return derive_hook_source(claim, vault_root, settings_file)
    if kind == "rules_md":
        return derive_rules_md(claim, vault_root)
    if kind == "settings":
        return derive_settings(claim, settings_file)
    raise DerivationFailure(
        f"{claim.get('id', '?')}: unknown authority_kind {kind!r}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry-file", default=None,
                    help="default: <vault-root>/.claude/hooks/_state/"
                         "enforcement-claims.json")
    ap.add_argument("--settings-file", default=None,
                    help="default: <vault-root>/.claude/settings.local.json")
    ap.add_argument("--vault-root", default=str(VAULT))
    args = ap.parse_args(argv)

    vault_root = Path(args.vault_root)
    registry_file = args.registry_file or str(
        vault_root / ".claude" / "hooks" / "_state" /
        "enforcement-claims.json")
    settings_file = args.settings_file or str(
        vault_root / ".claude" / "settings.local.json")

    try:
        try:
            registry = json.loads(
                Path(registry_file).read_text(encoding="utf-8"))
            claims = registry["claims"]
            assert isinstance(claims, list)
        except (OSError, json.JSONDecodeError, KeyError, TypeError,
                AssertionError) as e:
            raise DerivationFailure(
                f"registry unusable ({registry_file}): {e}")

        findings = []
        for claim in claims:
            try:
                doctrine = read_text(vault_root / claim["doctrine_file"],
                                     "doctrine file")
                anchor = claim["anchor"]
                claimed = claim["claimed"]
                cid = claim["id"]
            except (KeyError, TypeError) as e:
                raise DerivationFailure(f"malformed claim entry: {e}")
            if anchor not in doctrine:
                findings.append((cid, "anchor-missing", claimed, "none"))
                continue
            derived = derive(claim, vault_root, settings_file)
            if derived == claimed:
                continue
            if claim.get("claim_kind") == "registration" \
                    and derived == "unregistered":
                findings.append((cid, "registration-missing", claimed,
                                 derived))
            else:
                findings.append((cid, "tier-mismatch", claimed, derived))
    except DerivationFailure as e:
        print(f"DERIVATION FAILURE: {e}")
        return 2

    n = len(claims)
    stale = len(findings)
    print(f"ENFORCEMENT_CLAIMS claims={n} ok={n - stale} stale={stale}")
    for cid, reason, claimed, derived in findings:
        print(f"ENFORCEMENT_CLAIM_STALE  id={cid} reason={reason} "
              f"claimed={claimed} derived={derived}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
