#!/usr/bin/env python3
"""PostToolUse hook (matcher: Write|Edit): check memory file schema.

Fires on ALL Write|Edit operations. Immediately exits if the target file
is not in the memory directory. For memory files, checks that:
  1. Frontmatter is valid YAML (PyYAML; fail-open if unavailable).
  2. All required fields are present and well-formed.
Emits soft warnings (does NOT block).
"""
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# PyYAML guard: fail-open if not installed
# ---------------------------------------------------------------------------
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

REQUIRED_FIELDS = {"confidence", "last_verified", "expires", "type", "name", "description"}
VALID_TYPES = {"user", "feedback", "project", "reference", "finding", "hypothesis", "decision"}
VALID_CONFIDENCE = {"high", "medium", "low"}

# Optional lifecycle fields (added 2026-04-21).
# superseded_by: filename of the memory that replaces this one (must end in .md).
# last_accessed: ISO 8601 date of last reference/load (YYYY-MM-DD).
# status: lifecycle state; if 'superseded', superseded_by SHOULD also be set (soft warn only).
VALID_STATUS = {"active", "deprecated", "archived", "superseded"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    """Read and parse YAML frontmatter from a file using naive line-by-line parser.

    Used as fallback when YAML_AVAILABLE is False, and for the no-frontmatter
    detection path.  Returns a dict on success, None if no frontmatter found,
    None on read error.
    """
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


def validate_yaml(file_path):
    """Validate that the frontmatter block is parseable YAML.

    Returns:
        "OK": parse succeeded (frontmatter present and valid).
        None: could not check (read error, no frontmatter, or
                         YAML_AVAILABLE is False): caller treats as pass-through.
        <error string>: one-line parse error description.
    """
    if not YAML_AVAILABLE:
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None  # No frontmatter: existing path handles this case.

    raw_block = match.group(1)
    try:
        yaml.safe_load(raw_block)
        return "OK"
    except yaml.YAMLError as exc:
        # Build a compact one-line description.
        if hasattr(exc, "problem") and exc.problem:
            mark = ""
            if hasattr(exc, "problem_mark") and exc.problem_mark is not None:
                mark = f" (line {exc.problem_mark.line + 1}, col {exc.problem_mark.column + 1})"
            return f"{exc.problem}{mark}"
        return str(exc).splitlines()[0]


def _frontmatter_from_yaml(file_path):
    """Return frontmatter dict parsed via PyYAML, or None on any error.

    Used in place of the naive parser when YAML_AVAILABLE is True, giving
    accurate field extraction even for multi-line / quoted values.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return None

    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None

    try:
        parsed = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None  # validate_yaml will already surface this error.

    if not isinstance(parsed, dict):
        return {}

    # Flatten nested metadata: block BEFORE stringifying, so _flatten_metadata
    # can inspect the raw dict value.  Stringifying first would lose the dict.
    parsed = _flatten_metadata(parsed)

    # Normalise values to strings for the existing check_schema logic.
    return {k: str(v) if v is not None else "" for k, v in parsed.items()}


def _flatten_metadata(fm):
    """Return a copy of fm with metadata: sub-keys merged to top level.

    If fm contains a key 'metadata' whose value is a dict, the returned dict
    is: metadata-dict items THEN top-level items (so top-level wins on conflict).
    Fields absent from BOTH levels remain absent: no masking.
    If there is no 'metadata' dict key, returns a shallow copy of fm unchanged.
    """
    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        return dict(fm)
    # Build: start from metadata sub-keys, then overlay top-level keys.
    merged = dict(meta)
    merged.update(fm)          # top-level wins on conflict
    # Remove the 'metadata' wrapper key itself: it is not a schema field.
    merged.pop("metadata", None)
    return merged


def check_schema(fm):
    """Return list of warning messages for schema violations."""
    warnings = []

    missing = REQUIRED_FIELDS - set(fm.keys())
    if missing:
        warnings.append(f"Missing fields: {', '.join(sorted(missing))}")

    if fm.get("type") and fm["type"] not in VALID_TYPES:
        warnings.append(f"Invalid type '{fm['type']}': expected one of: {', '.join(sorted(VALID_TYPES))}")

    if fm.get("confidence") and fm["confidence"] not in VALID_CONFIDENCE:
        warnings.append(f"Invalid confidence '{fm['confidence']}': expected: high, medium, low")

    if fm.get("last_verified"):
        try:
            from datetime import datetime
            datetime.strptime(fm["last_verified"], "%Y-%m-%d")
        except ValueError:
            warnings.append(f"Invalid last_verified date format: '{fm['last_verified']}': expected YYYY-MM-DD")

    # Optional field: superseded_by
    if "superseded_by" in fm and fm["superseded_by"] not in ("", "null", "~"):
        val = fm["superseded_by"]
        if "/" in val or "\\" in val:
            warnings.append(f"superseded_by must be a bare filename, not a path (got: {val})")
        elif not val.endswith(".md"):
            warnings.append(f"Invalid superseded_by '{val}': must be a .md filename")

    # Optional field: last_accessed
    if "last_accessed" in fm and fm["last_accessed"] not in ("", "null", "~"):
        try:
            from datetime import datetime
            datetime.strptime(fm["last_accessed"], "%Y-%m-%d")
        except ValueError:
            warnings.append(f"Invalid last_accessed date format: '{fm['last_accessed']}': expected YYYY-MM-DD")

    # Optional field: status
    if "status" in fm and fm["status"] not in ("", "null", "~"):
        if fm["status"] not in VALID_STATUS:
            warnings.append(
                f"Invalid status '{fm['status']}': expected one of: {', '.join(sorted(VALID_STATUS))}"
            )
        elif fm["status"] == "superseded":
            superseded_by_val = fm.get("superseded_by", "")
            if not superseded_by_val or superseded_by_val in ("null", "~", ""):
                warnings.append("status is 'superseded' but superseded_by is missing or null (soft warning)")

    return warnings


_SESSION = None  # set from the payload in main(); None when identity is absent


def _log_fire(decision, detail=None):
    """Record this firing to hook-activity.jsonl. Never raises (contract C1)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import log_fire
        log_fire("memory-schema-check", decision=decision, detail=detail,
                 session=_SESSION)
    except Exception:
        pass


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

    global _SESSION
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from _governance_logger import session_from
        _SESSION = session_from(payload)
    except Exception:
        _SESSION = None

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

    basename = os.path.basename(file_path)
    all_warnings = []

    # ------------------------------------------------------------------
    # Step 1: YAML validity check (new, additive)
    # ------------------------------------------------------------------
    yaml_result = validate_yaml(file_path)
    if yaml_result not in (None, "OK"):
        all_warnings.append(
            f"[MEMORY YAML INVALID] {basename}: {yaml_result}: "
            f"Quote any value containing a colon-space, e.g. description: \"foo: bar\"."
        )

    # ------------------------------------------------------------------
    # Step 2: Field / type / date schema check (existing behaviour)
    # ------------------------------------------------------------------
    # If the YAML did not parse, the field check would run on naive-parser
    # output of corrupt content and produce unreliable warnings. Skip it :
    # the [MEMORY YAML INVALID] warning already tells the author to fix the
    # frontmatter; the field check re-runs cleanly on the next write.
    if yaml_result not in (None, "OK"):
        _log_fire("yaml-invalid", basename)
        print(json.dumps({"additionalContext": " | ".join(all_warnings)}))
        return

    # Use PyYAML-parsed dict when available (more accurate); fall back to
    # naive parser when YAML_AVAILABLE is False.
    if YAML_AVAILABLE and yaml_result == "OK":
        fm = _frontmatter_from_yaml(file_path)
    else:
        fm = extract_frontmatter(file_path)

    if fm is None:
        # No frontmatter at all: emit the existing no-frontmatter warning.
        all_warnings.append(
            f"[MEMORY SCHEMA] Warning: {basename} has no YAML frontmatter. "
            f"Memory files require: {', '.join(sorted(REQUIRED_FIELDS))}"
        )
        _log_fire("no-frontmatter", basename)
        print(json.dumps({"additionalContext": " | ".join(all_warnings)}))
        return

    # Note: nested `metadata:` blocks are flattened inside
    # `_frontmatter_from_yaml` (the YAML path) before this point, so `fm` is
    # already uniform. The naive `extract_frontmatter` fallback cannot
    # represent a nested block as a dict at all, so there is nothing to
    # flatten on that path either. No `_flatten_metadata` call belongs here.
    schema_warnings = check_schema(fm)
    for w in schema_warnings:
        all_warnings.append(f"[MEMORY SCHEMA] {basename}: {w}")

    if all_warnings:
        _log_fire("warn", "%s n=%d" % (basename, len(all_warnings)))
        print(json.dumps({"additionalContext": " | ".join(all_warnings)}))
    else:
        _log_fire("ok", basename)
        print("{}")


if __name__ == "__main__":
    main()
