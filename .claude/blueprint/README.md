# Blueprint manifest

`manifest.json` classifies every tracked path in this repository into one of
seven buckets: `core` (mechanism code that runs on every clone), `overlay`
(private, never-publish machine or scratch state that still belongs in a
mechanism-only clone), `knowledge` (the `Resources/KB` wiki corpus),
`schema` (skeleton and doctrine files with no vault content), `instance`
(vault content that travels only when content follows), `archive`
(retired material), and `work` (company and client material, named by a term
in its own path; see `.claude/scripts/blueprint_workbound.py`). It derives
one sparse-checkout pattern list per profile, `sparse_patterns` (full) and
`sparse_patterns_bare`, records `work_paths` (the work-bound files the bare
profile excludes one by one because they sit inside a core directory), a
`profiles` block with each profile's pattern and file counts, and
`extra_core_paths` (the deep harness
dependencies that live under an instance-bucket directory and must travel
anyway), and carries two fields other steps fill in: `machine_local` (named
machine-provisioned items with their plan step) and `secrets.items` (written
by `blueprint_render.py generate`, one row per `{{secret:<file>}}` the
templates reference, each with `exists_on_source`). Regenerating the manifest
preserves `secrets.items` rather than blanking a field this generator does
not own.

## Regenerate

```
PYTHONIOENCODING=utf-8 "C:/Program Files/Python314/python.exe" .claude/scripts/blueprint_manifest.py generate --date YYYY-MM-DD
```

Deterministic: the same tracked-file population and date produce
byte-identical output. Run after any change that adds, removes, or
reclassifies a top-level or `.claude/` second-segment path.

## Check

```
PYTHONIOENCODING=utf-8 "C:/Program Files/Python314/python.exe" .claude/scripts/blueprint_manifest.py check
```

Exit 0 clean, exit 2 on findings, exit 1 if the manifest is missing or
malformed. Findings are the self-consistency ones (an unclassified path, an
instance path leaked into `sparse_patterns`, a live `.mcp.json` secret value
found in the manifest) plus, inside a git checkout, the live re-derivation
against `git ls-files`: `UNCLASSIFIED_TOP_LEVEL_PATH` for a tracked unit the
manifest never classified, `STALE_UNIT` for the reverse, `MISSING_PATTERN`
for a pattern deleted from the manifest, `STALE_PATTERN` for the reverse.
`--no-verify-live` runs the self-consistency half alone. Outside a git
checkout the live half prints `LIVE_VERIFY: skipped`, which is a skip, never
a pass.

A per-bucket count drift prints as `INFO STALE_COUNT: <bucket>: manifest
<n>, live <n>` and does NOT gate: it is not counted in `FINDINGS` and does
not change the exit code. A count differs whenever the manifest is older
than the checkout, which is the normal state of every clone (the target is
cloned at HEAD, `manifest.json` was written at an earlier commit) and of
this vault after any autosave commit. One regenerate clears it. The four
codes above are classification gaps, which do not clear on their own, so
those still gate.

## What consumes this

The pattern lists feed `bootstrap_machine.py` (Implementation Phase A4),
which sparse-clones this repository on a new machine. `--profile full` uses
`sparse_patterns`: `core`, `overlay`, `knowledge`, `schema` and `work`.
`--profile bare`, the default, uses `sparse_patterns_bare`: `core`,
`overlay` and `schema`, minus every `work_paths` entry, minus `CLAUDE.md`
(the runner places a scrubbed twin of it instead). `machine_local`
names what the runner and Phase B's owner-present steps must still
provision by hand or by script; no value, only names and provisioning
pointers. `secrets.items` is written by `blueprint_render.py generate`, which
also writes three sidecars beside the templates every run, empty lists
included: `_secrets-referenced.json` (every secret file the templates name,
with `exists_on_source`), `_missing-secrets.json` (the `exists_on_source:
false` slice, the files the owner must create) and `_values-needed.json`
(every `{{value:<key>}}` the target machine must supply). Templates live per
profile, in `templates/full/` and `templates/bare/`; all three of the bare
profile's sidecars are empty lists, which is its whole claim.

Classification rules, buckets, and the exact override table live in
`.claude/scripts/blueprint_manifest.py`; tests in
`.claude/scripts/test_blueprint_manifest.py`.
