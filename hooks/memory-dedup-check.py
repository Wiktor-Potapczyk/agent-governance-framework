#!/usr/bin/env python3
"""PreToolUse hook (matcher: Write): check for near-duplicate memory files.

Fires on ALL Write operations. Immediately exits if the target file is not
in the memory directory. For new memory files, compares the description against
existing files using token overlap. Emits soft warning (does NOT block).
"""
import json
import os
import re
import sys

SIMILARITY_THRESHOLD = 0.65  # Token overlap ratio to flag as potential duplicate


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
    )


def get_memory_dir(file_path):
    """Derive the memory directory from the file path being written."""
    normalized = file_path.replace("\\", "/")
    idx = normalized.rfind("/memory/")
    if idx == -1:
        return None
    return normalized[:idx + len("/memory/")]


def tokenize(text):
    """Simple word tokenization for overlap comparison."""
    return set(re.findall(r'\w{3,}', text.lower()))


def extract_description_from_content(content):
    """Extract the description field from file content (not yet written to disk)."""
    match = re.search(r'^description:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    if match:
        return match.group(1)
    return ""


def extract_description_from_file(filepath):
    """Extract the description field from an existing file on disk."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            # Only read first 500 chars: frontmatter is at the top
            head = f.read(500)
    except (OSError, UnicodeDecodeError):
        return ""

    match = re.search(r'^description:\s*["\']?(.+?)["\']?\s*$', head, re.MULTILINE)
    return match.group(1) if match else ""


def compute_similarity(tokens_a, tokens_b):
    """Compute Jaccard similarity between two token sets."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


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

    tool_input = payload.get("tool_input", {})
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (json.JSONDecodeError, TypeError):
            tool_input = {}

    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "")

    # Silent exit for non-memory files
    if not is_memory_file(file_path):
        print("{}")
        return

    def _log(decision, detail=None):
        """Record this verdict to hook-activity.jsonl. Never raises (contract C2).

        Placed past the memory-path gate on purpose: this hook fires on every
        Write in the vault and only memory files are in its scope, so a record
        per non-memory Write measures nothing.
        """
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from _governance_logger import log_fire, session_from
            log_fire("memory-dedup-check", decision=decision, detail=detail,
                     session=session_from(payload))
        except Exception:
            pass

    # Extract description from the content being written
    new_desc = extract_description_from_content(content)
    if not new_desc:
        print("{}")
        _log("skip", "no-description")
        return

    new_tokens = tokenize(new_desc)
    if len(new_tokens) < 3:
        # Too few tokens for meaningful comparison
        print("{}")
        _log("skip", "too-few-tokens")
        return

    target_filename = os.path.basename(file_path)
    memory_dir = get_memory_dir(file_path)
    if not memory_dir or not os.path.isdir(memory_dir):
        print("{}")
        _log("skip", "no-memory-dir")
        return

    # Compare against all existing memory files
    duplicates = []
    try:
        for filename in os.listdir(memory_dir):
            if not filename.endswith(".md") or filename == "MEMORY.md":
                continue
            if filename == target_filename:
                continue  # Skip self (updating existing file)

            existing_desc = extract_description_from_file(os.path.join(memory_dir, filename))
            if not existing_desc:
                continue

            existing_tokens = tokenize(existing_desc)
            sim = compute_similarity(new_tokens, existing_tokens)

            if sim >= SIMILARITY_THRESHOLD:
                duplicates.append((filename, sim))
    except OSError:
        print("{}")
        _log("skip", "listdir-error")
        return

    # Emit first, log second. Nothing between the verdict and the stdout payload
    # may be able to swallow it (idiom from routing-table-validation.py).
    if duplicates:
        duplicates.sort(key=lambda x: -x[1])
        top = duplicates[0]
        print(json.dumps({
            "additionalContext": (
                f"[MEMORY DEDUP] Potential duplicate detected: '{target_filename}' is "
                f"{top[1]:.0%} similar to '{top[0]}'. "
                f"Consider updating the existing file instead of creating a new one."
            )
        }))
        _log("warn", f"{target_filename} ~{top[1]:.0%} {top[0]}")
    else:
        print("{}")
        _log("allow", target_filename)


if __name__ == "__main__":
    main()
