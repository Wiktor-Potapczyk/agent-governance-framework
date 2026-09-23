#!/usr/bin/env python3
"""Classify drift between a public framework-repo file and its live vault twin.

WHY THIS IS A SCRIPT AND NOT AN INLINE PASS
-------------------------------------------
The 2026-08-23 recon produced a twin classification (412 twins, 272 identical,
45 scrub-only, 72 content-drift, 23 scrub-landed-on-data) that lived only in a
transcript and an output JSON. The derivation was not re-runnable, so nobody
could check it or re-run it after the repo moved. A number handed to a decision
maker has to be reproducible from committed inputs.

WHAT "SCRUB-SHAPED" MEANS
------------------------
The public repo is a scrubbed copy: employer and infrastructure tokens are
replaced before publication. A line that differs ONLY by such a substitution is
the scrub working as designed. A line that differs any other way is real content
drift between what runs and what is published, which is what the audit cares
about.

The forbidden-token list is READ FROM the shipped scrubber config rather than
restated here, so this classifier cannot drift from the gate that actually runs.
Restating the list would also put the tokens themselves into a file that may one
day be published, which is the thing the gate exists to prevent.

TWO NORMALISATIONS, BOTH LOAD-BEARING
-------------------------------------
1. Newlines. The vault is CRLF in places and the repo is LF, so without
   normalising, every line of every file reads as changed and the classifier
   reports total drift everywhere.
2. Comments and docstrings. A substitution landing inside a comment is prose and
   is the scrub working. The same substitution landing inside a regex, a path
   constant, or a data literal is a DEFECT: it changes behaviour. That
   distinction is the whole reason this pass is worth running, and it is
   invisible unless comment spans are identified separately.

Usage:
    python .claude/scripts/twin_drift_classify.py            # classify PENDING rows
    python .claude/scripts/twin_drift_classify.py --write    # write results back
"""

import difflib
import io
import json
import os
import re
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER = os.path.join(VAULT, "Projects", "Agent-Governance-Research", "work",
                      "2026-08-19-harness-audit-coverage-ledger.json")
FR = "Projects/Agent-Governance-Research/framework-repo/"

_COMMENT_RE = re.compile(r"(#.*$)|(//.*$)|(<!--.*?-->)", re.MULTILINE | re.DOTALL)
_CODEISH = (".py", ".js", ".json", ".jsonl", ".ps1", ".sh", ".ini", ".yml", ".yaml",
            ".gitignore", ".gitattributes")


def _tokens():
    """Read the scrub vocabulary from the shipped checker's own config."""
    sys.path.insert(0, os.path.join(VAULT, ".claude", "scripts"))
    try:
        import check_forbidden_tokens as cft
        cfg = cft.load_config(os.path.join(VAULT, "README.md"),
                              os.path.join(VAULT, ".claude", "scripts",
                                           "check_forbidden_tokens.py"))
        out = []
        for entry in (cfg or []):
            tok = entry.get("token") or entry.get("pattern")
            if tok:
                out.append(str(tok))
        return out
    except Exception:
        return []


_DASHES = "".join(chr(c) for c in (0x2014, 0x2013, 0x2012, 0x2015, 0x2212, 0xFF0D, 0xFE58))
_SCRUB_PUNCT = _DASHES + ":,;()"


def _dash_scrub_equal(old_line, new_line):
    """True when two lines differ only by a dash-to-punctuation substitution.

    Heuristic, and stated as one. It removes the dash glyphs AND the punctuation
    they are typically replaced by from both sides, so it can also swallow a real
    edit that only changed a comma. That direction of error is the safe one here:
    it under-reports content drift rather than inventing it, and every verdict it
    produces is recorded per file so a reader can re-diff any row by hand.
    """
    if not any(d in old_line for d in _DASHES):
        return False
    strip = lambda t: "".join(ch for ch in t if ch not in _SCRUB_PUNCT).split()
    return strip(old_line) == strip(new_line)


def _read(path):
    try:
        with io.open(path, encoding="utf-8", errors="replace", newline="") as fh:
            return fh.read().replace("\r\n", "\n").replace("\r", "\n")
    except OSError:
        return None


def _prose_mask(text, path):
    """Per-line: is this line PROSE (comment or docstring) rather than data?

    A line-prefix test is not enough and reporting one as if it were is a defect.
    A substitution on the second line of a module docstring starts with no marker
    at all, so a prefix test calls it data and the classifier reports a
    scrub-landed-on-data finding for what is plainly prose. That is a control
    claiming a finding it has not earned, which is the thing this audit exists to
    catch, so docstring SPANS are tracked with the tokenizer rather than guessed.
    """
    lines = text.splitlines()
    mask = [False] * (len(lines) + 1)
    if not path.endswith(".py"):
        return [True] * (len(lines) + 1)  # prose files are prose throughout
    try:
        import tokenize
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                for ln in range(tok.start[0], tok.end[0] + 1):
                    if 0 <= ln < len(mask):
                        mask[ln] = True
    except Exception:
        # Tokenizer failed (syntax error, partial file). Fall back to the prefix
        # test rather than silently calling everything prose.
        for i, line in enumerate(lines, start=1):
            st = line.strip()
            mask[i] = (not st) or st.startswith(("#", '"' * 3, "'" * 3))
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            mask[i] = True
    return mask


def classify(repo_path, vault_path, tokens):
    a, b = _read(vault_path), _read(repo_path)
    if a is None or b is None:
        return {"verdict": "UNREADABLE", "changed": 0, "scrub": 0, "content": 0,
                "scrub_on_data": 0}
    if a == b:
        return {"verdict": "IDENTICAL", "changed": 0, "scrub": 0, "content": 0,
                "scrub_on_data": 0}

    changed = scrub = content = on_data = 0
    prose = _prose_mask(a, repo_path)
    sm = difflib.SequenceMatcher(None, a.splitlines(), b.splitlines())
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        base_line = i1 + 1
        old = a.splitlines()[i1:i2]
        new = b.splitlines()[j1:j2]
        for k in range(max(len(old), len(new))):
            changed += 1
            o = old[k] if k < len(old) else ""
            n = new[k] if k < len(new) else ""
            # Scrub-shaped: the vault line reduces to the repo line once every
            # known token is removed from BOTH sides.
            oc, nc = o, n
            for t in tokens:
                oc = re.sub(re.escape(t), "", oc, flags=re.IGNORECASE)
                nc = re.sub(re.escape(t), "", nc, flags=re.IGNORECASE)
            hit = any(re.search(re.escape(t), o, re.IGNORECASE) for t in tokens)
            if not hit:
                # Second scrub class, and empirically the DOMINANT one: the
                # publication pass rewrites the dash glyphs Wiktor never uses into
                # a colon or a comma. Detected by removing both the dash glyphs and
                # the punctuation they are replaced by from each side; if the lines
                # then match, the only difference was that substitution.
                hit = _dash_scrub_equal(o, n)
                if hit:
                    oc, nc = "", ""
            if hit and oc.strip() == nc.strip():
                scrub += 1
                idx = base_line + k
                if idx < len(prose) and not prose[idx]:
                    on_data += 1
            else:
                content += 1

    if content:
        verdict = "CONTENT-DRIFT"
    elif on_data:
        verdict = "SCRUB-ON-DATA"
    else:
        verdict = "SCRUB-ONLY"
    return {"verdict": verdict, "changed": changed, "scrub": scrub,
            "content": content, "scrub_on_data": on_data}


def main():
    write = "--write" in sys.argv
    doc = json.load(io.open(LEDGER, encoding="utf-8"))
    tokens = _tokens()
    print("scrub tokens loaded from the shipped checker:", len(tokens))
    if not tokens:
        print("NOTE: zero tokens loaded from the shipped checker. The dash-substitution "
              "class below still applies, but token-based scrubs cannot be recognised.")

    # Select by SUBJECT, not by status. Selecting on PENDING made the script
    # classify zero rows on its second run, because --write clears that status.
    # A re-runnable artifact that cannot reproduce its own number on re-run is
    # not one, and that was the whole justification for writing this file.
    rows = [r for r in doc["ledger"]
            if str(r.get("role", "")).startswith("framework-repo artifact")]
    tally = {}
    for row in rows:
        twin = row.get("twin")
        if not twin:
            continue
        res = classify(os.path.join(VAULT, row["path"].replace("/", os.sep)),
                       os.path.join(VAULT, twin.replace("/", os.sep)), tokens)
        tally[res["verdict"]] = tally.get(res["verdict"], 0) + 1
        if write:
            row["drift"] = res
            row["status"] = "AUDITED"
            if res["verdict"] in ("CONTENT-DRIFT", "SCRUB-ON-DATA"):
                row["findings"] = (row.get("findings") or []) + [
                    f"{res['verdict']}: {res['content']} content-shaped and "
                    f"{res['scrub_on_data']} scrub-on-data line(s) differ from the live twin"]

    print("rows classified:", sum(tally.values()))
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4d}  {k}")
    if write:
        import collections
        doc["pending"] = sum(1 for r in doc["ledger"]
                             if str(r.get("status", "")).startswith("PENDING"))
        doc["by_status"] = dict(collections.Counter(str(r.get("status")) for r in doc["ledger"]))
        io.open(LEDGER, "w", encoding="utf-8").write(
            json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        print("written. pending now:", doc["pending"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
