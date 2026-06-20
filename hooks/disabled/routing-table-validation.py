"""
routing-table-validation.py: PreToolUse Edit|Write|MultiEdit hook (opt-in)

Denies edits to CLAUDE.md or any .claude/skills/*/SKILL.md that would introduce
a broken dispatch-name reference: an agent name in a clear dispatch position that
does not resolve to any entry in registry.json.

This hook ships UNREGISTERED (disabled by default). To arm it, copy it to your
active hooks directory and add it to your settings.json/settings.local.json under
the PreToolUse event with matchers for Edit, Write, and MultiEdit.

DESIGN CONTRACT:
  - Fail-open on ANY ambiguity: parse errors, unreadable registry, unclear position.
  - Low false-positive: only DENY when ALL four gates (a/b/c/d) pass.
  - Deny protocol: emit the hookSpecificOutput/permissionDecision:deny JSON form.
    The {"decision":"block"} form is the SubagentStop protocol and is SILENTLY IGNORED
    on PreToolUse: do NOT use it.
  - To allow: print nothing, exit 0.
  - Exit 0 always.

Gate summary (ALL must hold to deny):
  (a) Target file is CLAUDE.md or .claude/skills/*/SKILL.md (case-insensitive).
  (b) Unresolved token is in a clear DISPATCH POSITION in a NEW/CHANGED line.
  (c) Token has agent-name SHAPE: ^[a-z][a-z0-9]+(?:[-_][a-z0-9]+)+$
  (d) Token resolves to nothing in registry.json agents union DEPRECATED_ALLOWLIST.

Dispatch positions recognised (case-insensitive):
  - "MUST DISPATCH: ...": comma-separated names after the colon
  - Markdown routing-table row "| ... | <name> | ... |" in agent/dispatch context
  - subagent_type: "<name>" or subagent_type=<name>

NOT a dispatch position (and therefore never blocked):
  - Free prose sentences, including "dispatches to X" verb phrases: these are
    indistinguishable from ordinary English and were a systematic false-positive
    source on CLAUDE.md (removed: _DISPATCH_PHRASE_RE detector).
  - Content inside fenced code blocks (``` ... ```)
  - Comment lines (# ...)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import PurePosixPath, Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Agents that are legitimately referenced in dispatch positions even though
# they may be deprecated or renamed in this project.
# Add retired agent names here to prevent false-positive blocks after a rename.
# Example: frozenset({"old-agent-name", "another-retired-name"})
DEPRECATED_ALLOWLIST: frozenset[str] = frozenset()

# Non-agent identifiers that are agent-shaped but are NOT agent names.
# Prevents false positives on structural terms that happen to look like agents.
NON_AGENT_IDENTIFIERS: frozenset[str] = frozenset({
    "must-dispatch",
    "pre-tool-use",
    "post-tool-use",
    "sub-agent",
    "fail-open",
})

# Agent-name shape: lowercase, >=2 kebab/snake segments, starts with [a-z].
AGENT_NAME_RE = re.compile(r'^[a-z][a-z0-9]+(?:[-_][a-z0-9]+)+$')

# Patterns for dispatch positions (applied per-line to new/changed content).
# Each returns zero or more candidate tokens to validate.

# MUST DISPATCH: token1, token2, token3
_MUST_DISPATCH_RE = re.compile(
    r'MUST\s+DISPATCH\s*:\s*(.+)',
    re.IGNORECASE,
)

# subagent_type: "name" or subagent_type=name or subagent_type: name
_SUBAGENT_TYPE_RE = re.compile(
    r'subagent_type\s*[=:]\s*"?([A-Za-z0-9_-]+)"?',
    re.IGNORECASE,
)

# Markdown routing-table row: | ... | <candidate> | ... |
# Only matches rows where we can detect an agent/dispatch table context
# (header contains "agent" or "dispatch": applied at caller, not here).
_MD_TABLE_CELL_RE = re.compile(
    r'^\s*\|(?:[^|]*\|)+\s*$'
)

# Fenced code block boundary
_FENCE_RE = re.compile(r'^\s*```')

# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _repo_root() -> str:
    """Walk up from __file__ to find the repo/project root (contains CLAUDE.md).

    Layout assumption: this hook lives at <root>/.claude/hooks/ or <root>/hooks/.
    Both are tried; falls back to three levels up if neither contains CLAUDE.md.
    """
    here = Path(os.path.abspath(__file__))
    # Try two-levels-up (<root>/.claude/hooks/file -> <root>)
    candidate_2up = here.parent.parent.parent
    if (candidate_2up / "CLAUDE.md").exists():
        return str(candidate_2up)
    # Try one-level-up (<root>/hooks/file -> <root>)
    candidate_1up = here.parent.parent
    if (candidate_1up / "CLAUDE.md").exists():
        return str(candidate_1up)
    return str(candidate_2up)


def _registry_path() -> str:
    here = Path(os.path.abspath(__file__))
    # Search for registry.json walking up from __file__.
    #
    # Supported layouts (where <root> is the project/repo root):
    #   Deployed:  <root>/.claude/hooks/routing-table-validation.py
    #   Disabled:  <root>/.claude/hooks/disabled/routing-table-validation.py
    #
    # Registry may sit at:
    #   <root>/.claude/registry.json  : standard (generate_registry.py output)
    #   <root>/registry.json          : non-standard flat layout
    #
    # Walk up at most 4 levels; try both locations at each level.
    probe = here.parent
    for _ in range(4):
        for rel in (".claude/registry.json", "registry.json"):
            candidate = probe / rel
            if candidate.exists():
                return str(candidate)
        probe = probe.parent
    # Fallback: same dir as this file's parent (will fail-open if absent)
    return str(here.parent.parent / ".claude" / "registry.json")


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def _load_registry_agents() -> set[str] | None:
    """
    Return lowercase set of valid dispatch targets from registry.json, or None on
    failure (fail-open). Includes both 'agents' and 'skills' keys: MUST DISPATCH
    legitimately lists skill names (e.g. process-qa, pm) as well as agent names.
    """
    rp = _registry_path()
    try:
        with open(rp, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        valid: set[str] = set()

        def _extract_keys(section: object) -> None:
            if isinstance(section, dict):
                for name in section.keys():
                    if name:
                        valid.add(name.lower())
            elif isinstance(section, list):
                for item in section:
                    if isinstance(item, dict):
                        name = item.get("name") or ""
                        if name:
                            valid.add(name.lower())

        _extract_keys(data.get("agents", {}))
        _extract_keys(data.get("skills", {}))

        return valid if valid else None
    except Exception:
        return None  # fail-open: cannot parse -> cannot validate -> allow


# ---------------------------------------------------------------------------
# File-class gate (gate a)
# ---------------------------------------------------------------------------

def _is_target_file(file_path: str) -> bool:
    """Return True if the file is CLAUDE.md or .claude/skills/*/SKILL.md."""
    if not file_path:
        return False
    # Normalise separators
    norm = file_path.replace("\\", "/")
    basename = norm.rsplit("/", 1)[-1].lower()

    if basename == "claude.md":
        return True

    # .claude/skills/<anything>/SKILL.md  (exactly one extra path component)
    # Accept case-insensitive match
    if basename == "skill.md":
        # check that two levels up is 'skills': .claude/skills/<name>/SKILL.md
        parts = norm.lower().rstrip("/").split("/")
        try:
            idx = len(parts) - 1  # last segment is 'skill.md'
            if idx >= 2 and parts[idx - 2] == "skills":
                return True
        except Exception:
            pass
    return False


# ---------------------------------------------------------------------------
# Fenced code block tracker
# ---------------------------------------------------------------------------

def _is_in_fence(line: str, in_fence: bool) -> tuple[bool, bool]:
    """Return (skip_line, new_in_fence_state)."""
    if _FENCE_RE.match(line):
        return True, not in_fence  # the fence delimiter itself is skipped
    return in_fence, in_fence


# ---------------------------------------------------------------------------
# Dispatch-position detection + token extraction (gate b)
# ---------------------------------------------------------------------------

def _extract_dispatch_tokens_from_line(line: str, surrounding_lines: list[str]) -> list[str]:
    """
    Extract candidate agent-name tokens from a line that is in a dispatch position.
    Returns empty list if the line is not in a dispatch position.
    """
    tokens: list[str] = []

    # MUST DISPATCH: ...
    m = _MUST_DISPATCH_RE.search(line)
    if m:
        raw = m.group(1)
        # Split on commas; take the first word-token of each segment
        for segment in raw.split(","):
            word = segment.strip().split()[0].rstrip(".,;:\"'`") if segment.strip() else ""
            if word:
                tokens.append(word.lower())
        return tokens  # definitive dispatch-position line, return immediately

    # subagent_type: "name"
    m = _SUBAGENT_TYPE_RE.search(line)
    if m:
        tokens.append(m.group(1).lower())
        return tokens

    # Markdown table row: only if surrounding context mentions agent/dispatch
    if _MD_TABLE_CELL_RE.match(line):
        context_text = " ".join(surrounding_lines).lower()
        if "agent" in context_text or "dispatch" in context_text or "routing" in context_text:
            # Extract all pipe-delimited cells
            cells = [c.strip() for c in line.split("|") if c.strip()]
            for cell in cells:
                # A cell that is purely an agent-name-shaped token
                candidate = cell.split()[0].rstrip(".,;:`\"'") if cell.split() else ""
                if candidate:
                    tokens.append(candidate.lower())

    return tokens


# ---------------------------------------------------------------------------
# Validation core
# ---------------------------------------------------------------------------

def _validate_text(text: str, registry_agents: set[str]) -> list[str]:
    """
    Scan text for dispatch-position lines; return list of unresolved agent tokens.
    Skips lines inside fenced code blocks. Only inspects dispatch-position tokens.
    """
    broken: list[str] = []
    lines = text.splitlines()
    in_fence = False

    for i, line in enumerate(lines):
        skip, in_fence = _is_in_fence(line, in_fence)
        if skip:
            continue

        # Skip comment lines
        if line.lstrip().startswith("#"):
            continue

        # Context window: 5 lines around current line for table-heading detection
        start = max(0, i - 5)
        end = min(len(lines), i + 6)
        surrounding = lines[start:i] + lines[i + 1:end]

        candidates = _extract_dispatch_tokens_from_line(line, surrounding)
        for token in candidates:
            # Gate (c): agent-name shape
            if not AGENT_NAME_RE.match(token):
                continue
            # Gate (d): resolves to nothing
            if token in NON_AGENT_IDENTIFIERS:
                continue
            if token in DEPRECATED_ALLOWLIST:
                continue
            if token in registry_agents:
                continue
            # All gates passed: broken reference
            if token not in broken:
                broken.append(token)

    return broken


# ---------------------------------------------------------------------------
# Resulting-content builders per tool type
# ---------------------------------------------------------------------------

def _get_new_strings_write(tool_input: dict) -> tuple[str, str]:
    """For Write: full content is new. Return (content_to_validate, file_path)."""
    content = tool_input.get("content") or ""
    file_path = tool_input.get("file_path") or ""
    return content, file_path


def _get_new_strings_edit(tool_input: dict) -> tuple[str, str]:
    """
    For Edit: return (new_string, file_path).
    Only validate tokens in new_string: pre-existing broken refs elsewhere
    must not block an unrelated edit.
    """
    new_string = tool_input.get("new_string") or ""
    file_path = tool_input.get("file_path") or ""
    return new_string, file_path


def _get_new_strings_multiedit(tool_input: dict) -> tuple[str, str]:
    """
    For MultiEdit: concatenate all new_strings from edits list.
    Only validate what's being introduced.
    """
    file_path = tool_input.get("file_path") or ""
    edits = tool_input.get("edits") or []
    combined = "\n".join(
        (e.get("new_string") or "")
        for e in edits
        if isinstance(e, dict)
    )
    return combined, file_path


# ---------------------------------------------------------------------------
# Deny emitter
# ---------------------------------------------------------------------------

def _emit_deny(broken_tokens: list[str], file_path: str) -> None:
    names = ", ".join(f'"{t}"' for t in broken_tokens)
    reason = (
        f"ROUTING_BROKEN: The following agent name(s) appear in a dispatch position "
        f"in '{file_path}' but resolve to nothing in registry.json: {names}. "
        f"Add the agent to registry.json or remove the reference. "
        f"If this name is intentionally retired, add it to DEPRECATED_ALLOWLIST "
        f"in routing-table-validation.py."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw or not raw.strip():
            return 0
        payload = json.loads(raw)
    except Exception:
        return 0  # fail-open: parse error -> allow

    try:
        tool_name = payload.get("tool_name", "")
        if tool_name not in ("Write", "Edit", "MultiEdit"):
            return 0

        tool_input = payload.get("tool_input") or {}
        if not isinstance(tool_input, dict):
            return 0

        # Dispatch to per-tool handler
        if tool_name == "Write":
            text_to_validate, file_path = _get_new_strings_write(tool_input)
        elif tool_name == "Edit":
            text_to_validate, file_path = _get_new_strings_edit(tool_input)
        else:  # MultiEdit
            text_to_validate, file_path = _get_new_strings_multiedit(tool_input)

        # Gate (a): only target files
        if not _is_target_file(file_path):
            return 0

        if not text_to_validate:
            return 0

        # Load registry: fail-open on failure
        registry_agents = _load_registry_agents()
        if registry_agents is None:
            return 0  # cannot validate -> allow

        broken = _validate_text(text_to_validate, registry_agents)
        if broken:
            _emit_deny(broken, file_path)

    except Exception:
        pass  # fail-open: any unexpected error -> allow

    return 0


if __name__ == "__main__":
    sys.exit(main())
