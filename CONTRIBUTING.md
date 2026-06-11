# Contributing

**Audience:** developers who want to fork, adapt, or contribute to this framework.

This repository is a published form of a personal governance framework. It accepts issues and pull requests, but is maintained primarily as a personal tool — changes are driven by the author's own operational needs. External contributions that tighten enforcement, improve documentation, or fix bugs are welcome; domain-specific agents and skills belong in your own fork.

---

## Fork-and-adapt model

The recommended adoption path is a fork:

1. Fork the repository.
2. Install into your project following [INSTALL.md](INSTALL.md).
3. Customize agents, skills, and hooks to your domain — see [docs/customization.md](docs/customization.md) for formats and extension points.
4. Write your own CLAUDE.md using the shipped template as a starting point.
5. Commit your customizations to your fork.

The framework ships a domain-neutral core. Domain-specific additions (your agents, your hook thresholds, your CLAUDE.md content) belong in your fork, not in upstream PRs.

---

## Adding or modifying an agent

1. Create or edit the `.md` file in `agents/governance/` (or `agents/domain-examples/<domain>/` for worked examples).
2. Follow the Reference schema in [docs/documentation-standard.md](docs/documentation-standard.md) §3c — every field is required.
3. Add or update the entry in `docs/reference/agents.md`.
4. Update the count and category list in `docs/reference/setup-inventory.md`.
5. Run the doc-consistency check (see CI section below) — must exit 0.
6. Add a CHANGELOG `Added` or `Changed` line following [docs/documentation-standard.md](docs/documentation-standard.md) §5.

## Adding or modifying a skill

1. Create `skills/<tier>/<name>/SKILL.md` with `name` and `description` frontmatter.
2. Follow the Reference schema in [docs/documentation-standard.md](docs/documentation-standard.md) §3b.
3. Add or update the entry in `docs/reference/skills.md`.
4. Run the doc-consistency check.
5. Add a CHANGELOG line.

## Adding or modifying a hook

1. Place the hook `.py` file in `hooks/` (or `hooks/disabled/` for opt-in hooks).
2. Follow the Reference schema in [docs/documentation-standard.md](docs/documentation-standard.md) §3a — the **Logical paths** row must cite `test_<hook>.py` or enumerate branches directly.
3. Add or update the entry in `docs/reference/hooks.md`.
4. Register the hook in `settings/settings.json.example` if it should be active by default.
5. Run the doc-consistency check.
6. Add a CHANGELOG line.

---

## Documentation rule

**Changes ship with their documentation updates in the same commit.** This is §6.2 of the Documentation Standard — incorrect or missing docs are treated as a defect, not a follow-up task. Use the [§8 checklist](docs/documentation-standard.md#8-the-followable-checklist-use-this-every-time) before every commit.

---

## Running CI checks locally

The CI workflow (`.github/workflows/docs.yml`) runs three checks. Run them locally before pushing:

**Doc-consistency (pinned counts vs on-disk reality):**

```bash
python skills/core/doc-consistency/check_doc_consistency.py .doc-consistency.json
```

**Internal Markdown link integrity:**

```python
import os, re, sys, glob
broken = []
for md in glob.glob('**/*.md', recursive=True):
    if '/.git/' in md: continue
    with open(md, encoding='utf-8') as fh:
        txt = fh.read()
    txt = re.sub(r'```.*?```', '', txt, flags=re.S)
    txt = re.sub(r'`[^`\n]*`', '', txt)
    base = os.path.dirname(md)
    for link in re.findall(r'\]\((?!https?://|#|mailto:)([^)]+?)\)', txt):
        target = link.split('#')[0].strip()
        if not target:
            continue
        resolved = os.path.normpath(os.path.join(base, target))
        if not os.path.exists(resolved):
            broken.append(f"{md} -> {link}")
if broken:
    print(f"{len(broken)} broken internal link(s):")
    for b in broken: print("  " + b)
    sys.exit(1)
print("internal Markdown links OK")
```

**JSON validity:**

```python
import json, glob, sys
bad = []
for f in glob.glob('**/*.json', recursive=True) + glob.glob('**/*.json.example', recursive=True):
    if '/.git/' in f: continue
    try:
        with open(f, encoding='utf-8') as fh: json.load(fh)
    except Exception as e:
        bad.append(f"{f}: {e}")
if bad:
    print("invalid JSON:")
    for b in bad: print("  " + b)
    sys.exit(1)
print("all JSON valid")
```

---

## Code of conduct

Be direct, be accurate, and be kind. Disagreement is welcome; disrespect is not.

---

## About this repository

This is a personal governance framework published for the benefit of others building agent-governance tooling. Upstream issues and pull requests are read and considered, but the maintainer's own operational needs drive the roadmap. If the upstream direction does not match your needs, a fork is the right path — that is the intended adoption model.
