---
name: blueprint
description: Runs bootstrap_machine.py end to end to reproduce the vault's harness mechanism on a new machine (manifest-driven sparse clone, secret-free template render, check, acceptance). Invoke on "set up this harness on a new machine", "reproduce the setup", "bootstrap a machine", or "blueprint".
---

# Blueprint: the harness mechanism on a new machine

One runner, `.claude/scripts/bootstrap_machine.py` (wrapped by
`bootstrap_machine.ps1`), does the clone, scaffold, render, check and
acceptance probe. This skill drives it and reports back. Plan:
[[2026-09-22-harness-migration-blueprint-plan]]. Reference:
[[setup-recreation-runbook]].

## Profiles

`--profile bare`, the default: the mechanism plus an empty vault skeleton,
naming no employer, client, tracker or n8n instance. No secret file, no
values file. Term list: `.claude/scripts/blueprint_workbound.py`, the one
place to widen.

`--profile full`: this workstation, `Resources/KB` and the work bucket
included, owing the 5 secret files and 5 values below.

## Use-when

- The owner is onboarding a new laptop, VM or replacement device and wants
  the harness mechanism, not the vault's content.
- The request names "reproduce the setup," "bootstrap a machine" or
  "blueprint."

## Do-not-use-when

- The owner wants the whole vault, notes and history included: that is a
  plain `git clone`, no runner needed.
- The task edits a hook, script or skill on the current machine: ordinary
  build work.
- One secret, plugin or scheduled task is missing on an already-set-up
  machine: fix it directly.

## Gotchas

- The runner lives inside the repository it clones. On a new device, before
  any checkout exists, extract `bootstrap_machine.py`,
  `blueprint_render.py`, `blueprint_workbound.py`, `blueprint_manifest.py`
  and `o17_portability_manifest.py` from a `--no-checkout` clone with
  `git show HEAD:<path>` (exact commands in the runbook), then `--dry-run`
  from that temp copy.
- `blueprint_render.py generate` always writes three sidecars, empty lists
  included, into `templates/<profile>/`. In full,
  `_secrets-referenced.json` is the superset (7 files);
  `_missing-secrets.json` and `_values-needed.json` are slices, not the
  copy list, so a device also needs every file marked
  `exists_on_source: true`. In bare all three are empty by design.
- Hand-editing `bootstrap-values.json` does nothing: every `--apply`
  rewrites it from computed values and never reads one back. Use
  `--values-extra <file>`, a JSON file of `{"key": "value"}` pairs.
- A missing `claude` CLI fails `--acceptance`: not a skip, never a pass.
  `--no-probe` records `SKIPPED-BY-FLAG` and still never exits 0.
- `blueprint_manifest_check`'s `STALE_COUNT` line is informational: a count
  drifts whenever the manifest is older than the checkout, and it does not
  fail the row.
- `hooks_suite` passes with known failures only when every failing test id
  sits inside `mechanism-only-known-failures.json` (38 ids, five files, all
  content-absence). Any failure outside that list blocks.
- In bare, `workbound_scan` scans the placed wiring and the target's
  `CLAUDE.md` for a work-bound term and fails on any hit; an
  `install_prereqs` row for a server or plugin the profile does not place
  reads `NOT-IN-PROFILE`, not `FAIL`.
- Never open a directory named `secrets/`. Never quote a credential-looking
  value anywhere.

## Steps

1. Ask the owner which profile, and why. Then: same Windows username and
   lockdown as the source machine, or not; GitHub access to the private
   vault's own repository; does vault content follow later.
2. Run `bootstrap_machine.ps1 --dry-run --target <dir>`. It prints the
   profile, the pattern and bucket counts, a read-only preflight, and the
   step table, and writes nothing.
3. Run `bootstrap_machine.ps1 --apply --target <dir> --home <dir>`. In bare
   that is the whole command; steps 4 to 6 do not apply.
4. Full only: add `--profile full --secrets-dir <dir>`. With no secrets
   copied and no values supplied it stops at the render step and names what
   is missing.
5. Full only: read the three sidecars in `templates/full/` and report the
   named files and values. The owner creates or copies the secret files
   (the session never opens that folder) and supplies a `--values-extra`
   JSON file.
6. Full only: rerun `--apply` with both flags.
7. Run `--check --target <dir> --home <dir>` and read its table.
8. Run `--acceptance --target <dir> --home <dir>` and read its table and
   exit code.
9. Report back: the acceptance table, any failing row's detail, the
   NOT-IN-SLICE-1 commands (plugins, scheduled tasks, mirror restore,
   `codegraph index build`, `qmd index build`), and the four conditions the
   probe does not cover (a non-Quick ceremony, a Gate-1 smoke test, MCP
   servers answering, a session start at zero staleness).

## Bare profile facts (2026-09-23)

- Bare is the default. It ships about 1,540 tracked files, replaces five files
  with scrubbed twins on the target (CLAUDE.md, .gitignore, control-probes.json,
  the prerequisite manifest, .claude/settings.json) and regenerates three
  (registry.json, the dispatch-name inventory, Home.md). The `workbound_scan`
  row scans the whole target tree and every written file; 0 hits is the bar.
- Bare owes no secret file and no value, so `--secrets-dir` and
  `--values-extra` are not needed. Placed servers: codegraph, memory, qmd.
- The owner's own name and the private remote's name survive by design; use
  `--origin-url` to point the device at a neutrally named mirror.
- Before the plugin install, expect `install_prereqs_check` at PENDING-SLICE-2
  and `hooks_suite` red on the dispatch-name tests; both clear after the
  NOT-IN-SLICE-1 plugin step.
