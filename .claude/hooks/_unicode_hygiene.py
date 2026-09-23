r"""_unicode_hygiene.py - shared Unicode-hygiene detector (Hermes P5, 2026-08-18).

Detects the invisible and bidirectional character classes that make a raw
source file a prompt-injection carrier (Trojan-Source bidi overrides, hidden
zero-width payloads). Pure stdlib (unicodedata, os, sys), Python 3.14.

Pattern: pure logic in an underscore module with thin I/O wrappers as
consumers, following _wiki_citation_logic.py. Consumers:
  - unicode-hygiene-check.py (PostToolUse hook, tool-written raw arrivals)
  - process-lint Pass M (weekly sweep over the raw layer at rest)
  - process-ingest Step 1.5 (scan + sanitize extracted text at point of use)

CONTRACT (source-plan 4.2, tested by test_unicode_hygiene.py):
  - ONE class table, defined here, imported everywhere. No consumer holds a
    private copy.
  - NO file-write API exists in this module. It never writes, edits,
    normalizes, or "cleans" any file. The raw layer is immutable; sanitization
    applies ONLY to in-memory text a caller passes in.
  - scan_file never raises on unreadable input: it returns readable=False so
    callers must surface UNSCANNED_RAW_FILE, never skip silently
    (source-plan 3.3: a scanner that silently skips unreadable files reports
    a clean corpus it never read).

Spec of record: Projects/Agent-Governance-Research/work/
2026-08-17-hermes-p5-ingest-hygiene-plan.md sections 4.1 and 4.2.
"""
import os
import unicodedata

# ---------------------------------------------------------------------------
# The one class table (source-plan 4.1). Severities are calibration starting
# values justified by the measured zero base rate; tunable by Wiktor later.
# ---------------------------------------------------------------------------
CLASS_TABLE = {
    "bidi-override": {"severity": "warning", "codepoints": "U+202A..U+202E"},
    "bidi-isolate": {"severity": "warning", "codepoints": "U+2066..U+2069"},
    "bidi-mark": {"severity": "advisory", "codepoints": "U+200E, U+200F"},
    "zero-width": {
        "severity": "advisory",
        "codepoints": "U+200B, U+200C, U+200D, U+2060",
    },
    "bom-at-0": {"severity": "advisory", "codepoints": "U+FEFF at offset 0"},
    "feff-midfile": {"severity": "warning", "codepoints": "U+FEFF at offset > 0"},
    "soft-hyphen": {"severity": "advisory", "codepoints": "U+00AD"},
    "other-cf": {
        "severity": "advisory",
        "codepoints": "any remaining category-Cf character",
    },
}

_BIDI_MARK = frozenset((0x200E, 0x200F))
_ZERO_WIDTH = frozenset((0x200B, 0x200C, 0x200D, 0x2060))


def classify_char(ch, offset):
    """Class name for one character at absolute text offset, or None.

    Named classes are checked first; any remaining Unicode category-Cf
    character closes the category as other-cf.
    """
    cp = ord(ch)
    if cp == 0xFEFF:
        return "bom-at-0" if offset == 0 else "feff-midfile"
    if 0x202A <= cp <= 0x202E:
        return "bidi-override"
    if 0x2066 <= cp <= 0x2069:
        return "bidi-isolate"
    if cp in _BIDI_MARK:
        return "bidi-mark"
    if cp in _ZERO_WIDTH:
        return "zero-width"
    if cp == 0x00AD:
        return "soft-hyphen"
    if unicodedata.category(ch) == "Cf":
        return "other-cf"
    return None


def _walk(text):
    """Yield (offset, line, col, class_name) for every target-class character.

    line and col are 1-based; col counts characters in the current line.
    Deterministic, no I/O.
    """
    line = 1
    col = 0
    for offset, ch in enumerate(text):
        col += 1
        cls = classify_char(ch, offset)
        if cls is not None:
            yield offset, line, col, cls
        if ch == "\n":
            line += 1
            col = 0


def scan_text(text):
    """Scan in-memory text. Returns a list of Finding dicts, one per
    occurrence: {class, codepoint, line, col, count}. Deterministic, no I/O.
    """
    return [
        {
            "class": cls,
            "codepoint": "U+%04X" % ord(text[offset]),
            "line": line,
            "col": col,
            "count": 1,
        }
        for offset, line, col, cls in _walk(text)
    ]


def per_class_counts(findings):
    """Aggregate findings into {class_name: count} with zeros included for
    every class in CLASS_TABLE (stable JSONL schema for consumers)."""
    counts = {name: 0 for name in CLASS_TABLE}
    for f in findings:
        counts[f["class"]] += 1
    return counts


def _extended_path(path):
    r"""\\?\-prefixed fully qualified backslash form of path.

    os.path.abspath removes relative segments and normalizes to backslashes,
    which the \\?\ prefix requires (the prefix disables path normalization).
    UNC paths get the \\?\UNC\server\share form.
    """
    abs_path = os.path.abspath(path)
    if abs_path.startswith("\\\\"):
        return "\\\\?\\UNC" + abs_path[1:]
    return "\\\\?\\" + abs_path


def _read_bytes(path):
    r"""Read raw bytes. Returns (data, None) or (None, error_string).

    First a plain open; on OSError under Windows, one retry through the
    extended-length \\?\ form to clear the 260-character path limit
    (source-plan 3.3: 2 of 21 Clippings live at 297-character paths).
    Never raises.
    """
    p = os.fspath(path)
    try:
        with open(p, "rb") as f:
            return f.read(), None
    except OSError as first_err:
        if os.name == "nt" and not str(p).startswith("\\\\?\\"):
            try:
                with open(_extended_path(p), "rb") as f:
                    return f.read(), None
            except OSError:
                pass
        return None, "%s: %s" % (type(first_err).__name__, first_err)


def scan_file(path):
    """Scan one file on disk. Returns a ScanResult dict:
      {path, readable, findings, error}

    Reads bytes, decodes UTF-8 with errors="replace". A read failure returns
    readable=False and the error string INSTEAD of raising, so callers must
    render it as UNSCANNED_RAW_FILE, never skip it.
    """
    data, err = _read_bytes(path)
    if data is None:
        return {
            "path": str(path),
            "readable": False,
            "findings": [],
            "error": err,
        }
    text = data.decode("utf-8", errors="replace")
    return {
        "path": str(path),
        "readable": True,
        "findings": scan_text(text),
        "error": None,
    }


def sanitize_text(text):
    """Remove every target-class character from in-memory text.

    Returns (clean_text, removal_manifest) where the manifest lists one entry
    per removal with the same {class, codepoint, line, col} coordinates
    scan_text reports, so an ingest report can show exactly what was removed.
    bom-at-0 is stripped like everything else. Idempotent: sanitizing already
    clean text returns it unchanged with an empty manifest.

    In-memory ONLY. This module has no file-write API; the raw file a caller
    extracted this text from is never modified, and the SHA computed from its
    raw bytes is identical before and after (asserted by Step 8's
    SHA-invariance test).
    """
    manifest = []
    remove_offsets = set()
    for offset, line, col, cls in _walk(text):
        remove_offsets.add(offset)
        manifest.append(
            {
                "class": cls,
                "codepoint": "U+%04X" % ord(text[offset]),
                "line": line,
                "col": col,
            }
        )
    if not remove_offsets:
        return text, []
    clean = "".join(
        ch for offset, ch in enumerate(text) if offset not in remove_offsets
    )
    return clean, manifest
