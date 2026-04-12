#!/usr/bin/env python3
"""PostToolUse hook (matcher: Write|Edit) — check memory file schema.

Fires on ALL Write|Edit operations. Immediately exits if the target file
is not in the memory directory. For memory files, checks that required
frontmatter fields are present. Emits soft warning (does NOT block).
"""
import json
import os
import re
import sys

REQUIRED_FIELDS = {"confidence", "last_verified", "expires", "type", "name", "description"}
VALID_TYPES = {"user", "feedback", "project", "reference", "finding", "hypothesis", "decision"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def is_memory_file(file_path):
    """Check if the file path is a memory .md file in the Claude projects memory dir."""
    if not file_path:
        return False
    normalized = file_path.replace("\\", "/")
    return (
        ".claude/projects/" in normalized
        and "/memory/" in normalized
        and normalized.endswith(".md")
        and not normalized.endswith("/MEMORY.md")
        and not normalized.endswith(".py")
    )


def extract_frontmatter(file_path):
    """Read and parse YAML frontmatter from a file."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    fm = {}
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            fm[key.strip()] = val.strip().strip('"').strip("'")
    return fm


def check_schema(fm):
    """Return list of warning messages for schema violations."""
    warnings = []

    missing = REQUIRED_FIELDS - set(fm.keys())
    if missing:
        warnings.append(f"Missing fields: {', '.join(sorted(missing))}")

    if fm.get("type") and fm["type"] not in VALID_TYPES:
        warnings.append(f"Invalid type '{fm['type']}' — expected one of: {', '.join(sorted(VALID_TYPES))}")

    if fm.get("confidence") and fm["confidence"] not in VALID_CONFIDENCE:
        warnings.append(f"Invalid confidence '{fm['confidence']}' — expected: high, medium, low")

    if fm.get("last_verified"):
        try:
            from datetime import datetime
            datetime.strptime(fm["last_verified"], "%Y-%m-%d")
        except ValueError:
            warnings.append(f"Invalid last_verified date format: '{fm['last_verified']}' — expected YYYY-MM-DD")

    return warnings


def main():
    payload_text = sys.stdin.read()
    if not payload_text:
        print("{}")
        return

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        print("{}")
        return

    # Extract file path from tool input
    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    file_path = tool_input.get("file_path", "")

    # Silent exit for non-memory files
    if not is_memory_file(file_path):
        print("{}")
        return

    # Read and check the file (it was just written/edited)
    fm = extract_frontmatter(file_path)
    if fm is None:
        print(json.dumps({
            "additionalContext": f"[MEMORY SCHEMA] Warning: {os.path.basename(file_path)} has no YAML frontmatter. Memory files require: {', '.join(sorted(REQUIRED_FIELDS))}"
        }))
        return

    warnings = check_schema(fm)
    if warnings:
        warning_text = "; ".join(warnings)
        print(json.dumps({
            "additionalContext": f"[MEMORY SCHEMA] {os.path.basename(file_path)}: {warning_text}"
        }))
    else:
        print("{}")


if __name__ == "__main__":
    main()
