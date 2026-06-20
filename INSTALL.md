# Installation Guide

## Prerequisites

- **Claude Code CLI** installed and authenticated (`claude --version` should return a version string)
- **Python 3.10+** on your system PATH (`python --version` to verify). On Windows, Python must be accessible as `python` from the shell you use with Claude Code. If only `python3` is on PATH, either add an alias or update the hook commands in settings accordingly.
- **Node.js 18+** on your system PATH (`node --version` to verify). Required by the workflow scripts (`workflows/*.js`) and by hook commands in `settings.json.template` that invoke `node` directly (the `Bash(node:*)` permission entries).
- **jq** on your system PATH (`jq --version` to verify). Required by certain hook commands in `settings.json.template` (the `Bash(jq:*)` permission entries). Install via your package manager (e.g., `brew install jq`, `apt install jq`, or download from https://jqlang.github.io/jq/).
- **Hook dependencies:** all hooks in `hooks/*.py` are pure Python standard-library. No `pip install` or `requirements.txt` is needed for the hooks themselves.
- **Test suite:** `hooks/test_*.py` files are present and can be run with `python -m pytest hooks/` or `python hooks/test_<name>.py` directly. They are not wired into any CI configuration in this repo; running them is optional but recommended after install to verify your path setup.

## 1. Clone the Repository

```bash
git clone https://github.com/Wiktor-Potapczyk/agent-governance-framework.git
cd agent-governance-framework
```

## 2. Copy Governance Agents

Agents can be installed globally (available in all Claude Code sessions) or per-project.

**Global install:**
```bash
cp agents/governance/*.md ~/.claude/agents/
```

**Per-project install:**
```bash
cp agents/governance/*.md /your/project/.claude/agents/
```

The 28 governance agents cover: research pipeline (orchestrator, analyst, synthesizer, reporter, query-clarifier, research-coordinator, technical-researcher), planning (implementation-plan, architect-review, adversarial-reviewer), building (blueprint-mode, debugger, api-designer, data-engineer), AI/prompts (prompt-engineer, llm-architect), MCP development (mcp-developer, mcp-server-architect, mcp-registry-navigator), database specialists (postgres-pro, nosql-specialist), platform specialists (powershell-7-expert), security audit (api-security-audit), git flow (git-flow-manager), vault/productivity (vault-keeper, content-marketer, competitive-analyst), and PM (pm-orchestrator).

## 3. Copy Hooks

Hooks must be accessible at the paths you will register in settings. A project-level `.claude/hooks/` directory is the recommended location.

```bash
mkdir -p /your/project/.claude/hooks
cp hooks/*.py /your/project/.claude/hooks/
```

Do not copy the `disabled/` subdirectory unless you intend to activate those hooks.

**Note:** All hooks use `os.path.dirname(__file__)` for any relative path resolution internally. They function correctly from any install location as long as the path registered in settings points to the actual file.

## 4. Copy Core Skills

```bash
mkdir -p /your/project/.claude/skills
cp -r skills/core/* /your/project/.claude/skills/
```

Core skills include: `task-classifier`, `process-research`, `process-analysis`, `process-build`, `process-planning`, `process-qa`, `process-pentest`, `process-postmortem`, `process-governance-mine`, `doc-consistency`, `verify`, `verification-gated-research`, `ensemble`, `architect-loop`, `db-migration-plan`, `index`, and `pm`.

## 5. Configure Settings

**Two settings templates ship with this repo: choose the right one:**

- `settings/settings.json.example` and `settings/settings.local.json.example` register **6 hooks** (a minimal starter subset). Good for a quick first install.
- `settings/settings.json.template` registers **all 35 hooks** (the full framework). This is the recommended production starting point. See `settings/settings.json.template.README.md` for the automated substitution one-liner that replaces `{{VAULT_ROOT}}` and `{{HOME_OR_VAULT}}` placeholders across the template.

Copy the example settings file (minimal 6-hook subset):

```bash
cp settings/settings.json.example /your/project/.claude/settings.local.json
```

Or copy the full 35-hook template and run the substitution documented in `settings/settings.json.template.README.md`:

```bash
cp settings/settings.json.template /your/project/.claude/settings.json
# then substitute {{VAULT_ROOT}} and {{HOME_OR_VAULT}} per the README
```

Open the file and replace every `/path/to/your/hooks/` placeholder (or the `{{VAULT_ROOT}}` tokens if using the full template) with the absolute path to the directory where you copied the hooks in step 3.

**Example (macOS/Linux):**
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"/home/youruser/project/.claude/hooks/user-prompt-submit.py\""
          }
        ]
      }
    ]
  }
}
```

**Example (Windows):**
```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python \"C:/Users/youruser/project/.claude/hooks/user-prompt-submit.py\""
          }
        ]
      }
    ]
  }
}
```

**Hook registration format explained:**

Each hook entry requires:
- `event type` -- the Claude Code lifecycle event (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `Stop`)
- `matcher` (optional) -- filters the hook to specific tools (e.g., `"Bash"`, `"Skill"`). Omit to match all tools for that event.
- `type: "command"` -- always this value for Python hooks
- `command` -- the shell command Claude Code will execute, with the absolute path to the `.py` file in quotes

**Settings file locations:**

| Scope | Path |
|---|---|
| Global (all projects) | `~/.claude/settings.json` |
| Project-level | `/your/project/.claude/settings.local.json` |

Project-level settings take precedence over global settings for conflicting keys. Hook lists are merged, not overridden.

## 6. Configure CLAUDE.md

The `CLAUDE.md` file is the model's operating manual. It is loaded into every session as system context.

The repo root includes a `CLAUDE.md` that is already genericized (owner name, role, and company appear as `[Your Name]`, `[Your Role]`, `[Your Company]` placeholders). Use it as your starting template: copy it to your project root and fill in the placeholders. You will still need to customise the sections below for your specific setup:

- Your working philosophy and principles
- Directory structure and file conventions
- Critical rules (task classification, QA, delegation, no-unsolicited-changes)
- Agent registry summary
- Tool and environment quirks specific to your setup
- State management conventions

Place it at the project root or your home directory depending on intended scope.

## 7. Verify Hook Installation

Test that the hooks execute correctly by piping a minimal payload through the entry-point hook:

```bash
echo '{"prompt":"test","transcript_path":""}' | python /your/project/.claude/hooks/user-prompt-submit.py
```

Expected output is a JSON object with a `hookSpecificOutput` key. If you see a Python traceback instead, check that Python 3.10+ is on PATH and the file path is correct.

To verify the Stop hooks:

```bash
echo '{"session_id":"test","transcript_path":""}' | python /your/project/.claude/hooks/classifier-field-check.py
```

Each hook exits with code 0 on success. A non-zero exit code means the hook blocked the action (for enforcement hooks) or encountered an error.

## 8. Optional: Domain-Example Components

The repository includes domain-specific agents and skills as worked examples. These are not required for the governance framework to operate.

**Domain-example agents:** `agents/domain-examples/` is currently a placeholder for project-specific agent examples; reference implementations may be added in future releases. The domain-flavored agents that ship today live in `agents/governance/` and can be used directly: `content-marketer.md`, `competitive-analyst.md`, `vault-keeper.md`.

**Domain-example skills** (19 total in `skills/domain-examples/`):
- Apify: 12 skills covering scraping, lead generation, market research, and more
- n8n: 7 skills covering workflow patterns, node configuration, and code generation

**Vault management skills** (7 total in `skills/vault/`):
- `save`, `inbox`, `standup`, `daily`, `maintain` -- for knowledge-base management workflows
- `process-ingest`, `process-lint` -- for the LLM-Wiki ingest and consistency-lint operations

Copy any of these the same way as core skills:

```bash
cp -r skills/domain-examples/n8n/* /your/project/.claude/skills/
```

## Workflow scripts (procedure-layer enforcement)

Copy `workflows/*.js` into your `.claude/workflows/`. Then replace `{{VAULT_ROOT}}` in the six process-skill `SKILL.md` stubs (the `scriptPath` field in each). The Workflow tool requires an absolute path, so this substitution is mandatory before the skills will work.

**Automated substitution (bash):**
```bash
VAULT_ROOT="/absolute/path/to/your/vault"
for f in skills/core/process-*/SKILL.md; do
  sed -i "s|{{VAULT_ROOT}}|${VAULT_ROOT}|g" "$f"
done
```

**Automated substitution (PowerShell):**
```powershell
$VaultRoot = "C:\Users\you\Vault"
Get-ChildItem -Path "skills\core\process-*\SKILL.md" | ForEach-Object {
  (Get-Content $_.FullName) -replace '\{\{VAULT_ROOT\}\}', $VaultRoot |
  Set-Content $_.FullName
}
```

Two rules from live operation: always invoke by `scriptPath`, never by name (named invocation resolves from a session cache, so mid-session script edits are silently ignored), and pass `args` as a JSON object (the scripts also tolerate a stringified object via a parse-if-string guard).

## Troubleshooting

**Hook not firing:** Confirm the absolute path in settings matches the actual file location. Paths with spaces must be quoted inside the command string.

**Python not found on Windows:** Claude Code on Windows may run hooks through a different shell than your terminal. Verify `python` resolves correctly in that context, or use the full path to the Python executable in the hook command (e.g., `"C:/Python312/python.exe"`).

**Classifier enforcement blocking every response:** The `classifier-field-check.py` Stop hook looks for classifier output fields in the transcript. If you have not invoked the `task-classifier` skill, the hook will log a block. Invoke `/task-classifier` at the start of any non-trivial task to satisfy it.

**Subagent quality check failing on short outputs:** The `subagent-quality-check.py` hook blocks empty outputs (under 5 characters) and short outputs that contain a refusal keyword: but a short *negative finding* (e.g. "I cannot reproduce the bug; it works on the main branch") is exempted when it carries a result-signal token, so legitimate short findings pass. It also flags long outputs with no structure, where `Label: value` report blocks and known REPORT headers (QA/PENTEST/PM CHECKPOINT) count as structure. A genuine empty or pure-refusal output is the expected block: prompt the agent to produce a structured result.
