# Installation Guide

## Prerequisites

- **Claude Code CLI** installed and authenticated (`claude --version` should return a version string)
- **Python 3.10+** on your system PATH (`python --version` to verify)
- On Windows: Python must be accessible as `python` from the shell you use with Claude Code. If only `python3` is on PATH, either add an alias or update the hook commands in settings accordingly.

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

The 25 governance agents cover: research pipeline (orchestrator, analyst, synthesizer, reporter), planning (implementation-plan, architect-review, adversarial-reviewer), building (blueprint-mode, debugger, api-designer, data-engineer), and specialist roles (prompt-engineer, llm-architect, mcp-developer, and others).

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

Core skills include: `task-classifier`, `process-research`, `process-analysis`, `process-build`, `process-planning`, `process-qa`, `process-pentest`, `verify`, `ensemble`, `architect-loop`, and `pm`.

## 5. Configure Settings

Copy the example settings file:

```bash
cp settings/settings.json.example /your/project/.claude/settings.local.json
```

Open the file and replace every `/path/to/your/hooks/` placeholder with the absolute path to the directory where you copied the hooks in step 3.

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

A template is not included in this repository because CLAUDE.md is highly environment-specific. Use the structure from the companion research repository as a reference, then write your own covering:

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

**Domain-example agents** (4 total in `agents/domain-examples/`):
- `content-marketer.md`, `competitive-analyst.md`, `workflow-orchestrator.md`, `vault-keeper.md`

**Domain-example skills** (19 total in `skills/domain-examples/`):
- Apify: 12 skills covering scraping, lead generation, market research, and more
- n8n: 7 skills covering workflow patterns, node configuration, and code generation

**Vault management skills** (5 total in `skills/vault/`):
- `save`, `inbox`, `standup`, `daily`, `maintain` -- for knowledge-base management workflows

Copy any of these the same way as core skills:

```bash
cp -r skills/domain-examples/n8n/* /your/project/.claude/skills/
cp agents/domain-examples/workflow-orchestrator.md /your/project/.claude/agents/
```

## Troubleshooting

**Hook not firing:** Confirm the absolute path in settings matches the actual file location. Paths with spaces must be quoted inside the command string.

**Python not found on Windows:** Claude Code on Windows may run hooks through a different shell than your terminal. Verify `python` resolves correctly in that context, or use the full path to the Python executable in the hook command (e.g., `"C:/Python312/python.exe"`).

**Classifier enforcement blocking every response:** The `classifier-field-check.py` Stop hook looks for classifier output fields in the transcript. If you have not invoked the `task-classifier` skill, the hook will log a block. Invoke `/task-classifier` at the start of any non-trivial task to satisfy it.

**Subagent quality check failing on short outputs:** The `subagent-quality-check.py` hook blocks outputs under 5 characters and flags outputs under 100 characters that contain error keywords. If a legitimate subagent produces a short response, this is expected behavior -- the agent should be prompted to produce structured output.
