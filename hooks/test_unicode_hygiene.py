r"""Tests for _unicode_hygiene.py (Hermes P5 ingest hygiene, 2026-08-18).

Written RED before the module exists (declarative-first, source-plan Step 2).
Spec of record: Projects/Agent-Governance-Research/work/
2026-08-17-hermes-p5-ingest-hygiene-plan.md sections 4.1 and 4.2, executed per
2026-08-18-hermes-p5-build-implementation-plan.md Step 2.

Committed fixtures live in _test_fixtures/unicode-hygiene/ (cases a through e).
Case (f) long-path and case (g) unreadable are GENERATED AT TEST RUNTIME and
never committed: a committed 260+ character path would break git and OneDrive
on this machine.

Run: PYTHONIOENCODING=utf-8 "C:\Program Files\Python314\python.exe" -m pytest
     .claude/hooks/test_unicode_hygiene.py -q -p no:cacheprovider
"""
import hashlib
import os
import re
import shutil
import sys

import pytest

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
if HOOK_DIR not in sys.path:
    sys.path.insert(0, HOOK_DIR)

from _unicode_hygiene import (  # noqa: E402
    CLASS_TABLE,
    per_class_counts,
    sanitize_text,
    scan_file,
    scan_text,
)

FIXTURES = os.path.join(HOOK_DIR, "_test_fixtures", "unicode-hygiene")
MODULE_PATH = os.path.join(HOOK_DIR, "_unicode_hygiene.py")

COMMITTED_FIXTURES = [
    "clean.md",
    "class-bidi-override.md",
    "class-bidi-isolate.md",
    "class-bidi-mark.md",
    "class-zero-width.md",
    "class-bom-at-0.md",
    "class-feff-midfile.md",
    "class-soft-hyphen.md",
    "class-other-cf.md",
    "trojan-source.md",
    "bom-clean.md",
    "injection-canary.md",
]


def read_fixture(name):
    # encoding="utf-8" (NOT utf-8-sig) so a BOM stays visible as U+FEFF at
    # offset 0, exactly as scan_file's byte read sees it.
    with open(os.path.join(FIXTURES, name), encoding="utf-8", newline="") as f:
        return f.read()


def findings_for(findings, class_name):
    return [f for f in findings if f["class"] == class_name]


# ---------------------------------------------------------------- class table

def test_class_table_names_and_severities():
    expected = {
        "bidi-override": "warning",
        "bidi-isolate": "warning",
        "bidi-mark": "advisory",
        "zero-width": "advisory",
        "bom-at-0": "advisory",
        "feff-midfile": "warning",
        "soft-hyphen": "advisory",
        "other-cf": "advisory",
    }
    assert set(CLASS_TABLE) == set(expected)
    for name, sev in expected.items():
        assert CLASS_TABLE[name]["severity"] == sev


# ------------------------------------------------------- per-class detection

def test_clean_fixture_zero_findings():
    assert scan_text(read_fixture("clean.md")) == []


@pytest.mark.parametrize(
    "fixture,class_name,expected_positions",
    [
        ("class-bidi-override.md", "bidi-override", [(3, 8, 0x202A), (4, 6, 0x202E)]),
        ("class-bidi-isolate.md", "bidi-isolate", [(3, 3, 0x2066), (4, 3, 0x2069)]),
        ("class-bidi-mark.md", "bidi-mark", [(3, 3, 0x200E), (4, 3, 0x200F)]),
        ("class-zero-width.md", "zero-width",
         [(3, 3, 0x200B), (4, 3, 0x200C), (5, 3, 0x200D), (6, 3, 0x2060)]),
        ("class-bom-at-0.md", "bom-at-0", [(1, 1, 0xFEFF)]),
        ("class-feff-midfile.md", "feff-midfile", [(3, 4, 0xFEFF)]),
        ("class-soft-hyphen.md", "soft-hyphen", [(3, 3, 0x00AD)]),
        ("class-other-cf.md", "other-cf", [(3, 3, 0x2061), (4, 8, 0x061C)]),
    ],
)
def test_per_class_detection_counts_and_positions(fixture, class_name, expected_positions):
    text = read_fixture(fixture)
    findings = scan_text(text)
    # Only the expected class fires; each finding is one occurrence (count 1).
    assert all(f["class"] == class_name for f in findings), findings
    got = [(f["line"], f["col"], int(f["codepoint"][2:], 16)) for f in findings]
    assert got == expected_positions
    assert all(f["count"] == 1 for f in findings)


def test_finding_shape():
    findings = scan_text(read_fixture("trojan-source.md"))
    assert len(findings) == 1
    f = findings[0]
    assert set(f) >= {"class", "codepoint", "line", "col", "count"}
    assert f["codepoint"] == "U+202E"


# ------------------------------------------------------- BOM vs midfile split

def test_bom_at_offset_zero_is_not_midfile():
    findings = scan_text(read_fixture("bom-clean.md"))
    assert len(findings_for(findings, "bom-at-0")) == 1
    assert findings_for(findings, "feff-midfile") == []
    assert len(findings) == 1


def test_feff_midfile_is_not_bom():
    findings = scan_text(read_fixture("class-feff-midfile.md"))
    assert findings_for(findings, "bom-at-0") == []
    assert len(findings_for(findings, "feff-midfile")) == 1


# ------------------------------------------------------------- trojan source

def test_trojan_source_rlo_detected():
    findings = scan_text(read_fixture("trojan-source.md"))
    assert [(f["class"], f["line"], f["col"]) for f in findings] == [
        ("bidi-override", 4, 20)
    ]


# --------------------------------------------------------- injection fixture

def test_injection_fixture_zero_width_hidden_payload():
    text = read_fixture("injection-canary.md")
    # The canary string is present in the raw fixture (that is the payload).
    assert "HERMES-P5-CANARY" in text
    findings = scan_text(text)
    zw = findings_for(findings, "zero-width")
    assert len(zw) == 3
    assert findings == zw  # nothing else in this fixture


def test_injection_fixture_sanitize_reveals_hidden_words():
    text = read_fixture("injection-canary.md")
    # Zero-width chars split these words in the raw payload.
    assert "ignore" not in text and "append" not in text
    clean, manifest = sanitize_text(text)
    assert "ignore" in clean and "append" in clean
    assert len(manifest) == 3
    # sanitize reveals; it never deletes visible content.
    assert "HERMES-P5-CANARY" in clean


# ------------------------------------------------------------- sanitize_text

@pytest.mark.parametrize("fixture", COMMITTED_FIXTURES)
def test_sanitize_removes_every_target_and_is_idempotent(fixture):
    text = read_fixture(fixture)
    original_findings = scan_text(text)
    clean, manifest = sanitize_text(text)
    # Property: sanitized output re-scanned yields zero findings.
    assert scan_text(clean) == []
    # Manifest is complete: one entry per original finding, same coordinates.
    assert len(manifest) == len(original_findings)
    assert [(m["class"], m["line"], m["col"]) for m in manifest] == [
        (f["class"], f["line"], f["col"]) for f in original_findings
    ]
    # Idempotent: sanitizing clean text changes nothing and removes nothing.
    clean2, manifest2 = sanitize_text(clean)
    assert clean2 == clean
    assert manifest2 == []


def test_sanitize_strips_bom_at_0():
    clean, manifest = sanitize_text(read_fixture("bom-clean.md"))
    assert not clean.startswith("\ufeff")
    assert [m["class"] for m in manifest] == ["bom-at-0"]


# ---------------------------------------------------------- per_class_counts

def test_per_class_counts_all_keys_zero_included():
    counts = per_class_counts(scan_text(read_fixture("class-zero-width.md")))
    assert set(counts) == set(CLASS_TABLE)
    assert counts["zero-width"] == 4
    assert sum(v for k, v in counts.items() if k != "zero-width") == 0


# ------------------------------------------------- no file-write API contract

def test_module_source_has_no_file_write_api():
    with open(MODULE_PATH, encoding="utf-8") as f:
        source = f.read()
    pattern = re.compile(r"write_text|write_bytes|open\([^)]*[\"'](w|a|x|wb|ab)")
    assert pattern.search(source) is None


# ------------------------------------------ scan_file basics and consistency

def test_scan_file_matches_scan_text_on_normal_fixture():
    path = os.path.join(FIXTURES, "class-bidi-override.md")
    result = scan_file(path)
    assert result["readable"] is True
    assert result["error"] is None
    assert result["findings"] == scan_text(read_fixture("class-bidi-override.md"))


def test_scan_file_bom_bytes_classify_bom_at_0():
    result = scan_file(os.path.join(FIXTURES, "bom-clean.md"))
    assert result["readable"] is True
    assert [f["class"] for f in result["findings"]] == ["bom-at-0"]


# ------------------------------------------------ case (f): long-path handling

LONG_SEGMENT = "unicode-hygiene-longpath-segment-0123456789abcdef"


def _extended(path):
    r"""\\?\-prefixed fully qualified backslash form for test setup I/O."""
    return "\\\\?\\" + os.path.abspath(path)


@pytest.fixture
def long_path_fixture(tmp_path):
    base = str(tmp_path)
    path = os.path.abspath(base)
    while len(path) < 250:
        path = os.path.join(path, LONG_SEGMENT)
    file_path = os.path.join(path, "longpath-fixture.md")
    assert len(file_path) > 260
    os.makedirs(_extended(path), exist_ok=True)
    with open(_extended(file_path), "w", encoding="utf-8", newline="\n") as f:
        f.write("# long path fixture\n\nplanted \u202e char\n")
    yield file_path
    top = os.path.join(os.path.abspath(base), LONG_SEGMENT)
    shutil.rmtree(_extended(top), ignore_errors=True)


def test_scan_file_long_path_succeeds(long_path_fixture):
    # scan_file receives the RAW (non-prefixed) path over 260 chars and must
    # read it anyway: a scanner that silently skips unreadable files reports a
    # clean corpus it never read (source-plan 3.3).
    result = scan_file(long_path_fixture)
    assert result["readable"] is True
    assert [f["class"] for f in result["findings"]] == ["bidi-override"]


# --------------------------------------------- case (g): unreadable surfaces

def test_scan_file_unreadable_returns_readable_false():
    # A directory path deterministically fails open() on Windows. The contract:
    # readable False plus an error string, never an exception, never a silent
    # skip. Callers must render this as UNSCANNED_RAW_FILE.
    result = scan_file(FIXTURES)
    assert result["readable"] is False
    assert result["findings"] == []
    assert result["error"]


def test_scan_file_missing_file_returns_readable_false():
    result = scan_file(os.path.join(FIXTURES, "does-not-exist.md"))
    assert result["readable"] is False
    assert result["error"]


# ------------------------- Step 8 Track 1: SHA invariance + citation chain

def test_sha_invariance_ingest_pipeline_and_citation_chain():
    """Deterministic run of the ingest DATA flow over the injection fixture.

    Proves mechanically: scanning and sanitizing the extracted text leaves the
    raw file's bytes (and therefore every SHA computed from them) identical,
    and a wiki-page candidate committing that SHA validates cleanly through
    _wiki_citation_logic.validate_source_entries. No page is written to
    Resources/KB/ by this test.
    """
    from pathlib import Path

    from _wiki_citation_logic import parse_source_field, validate_source_entries

    # Derived from the module's own FIXTURES constant rather than rebuilt from
    # an assumed ".claude/hooks" layout. Every other test in this file already
    # goes through FIXTURES; this one hardcoded the vault's directory shape,
    # so it broke the moment the file was read anywhere else, and it would
    # equally have broken here if .claude/hooks ever moved. The pair only has
    # to satisfy root / fixture_rel == fixture_abs, which holds in both trees.
    root = Path(HOOK_DIR).parent
    fixture_abs = Path(FIXTURES) / "injection-canary.md"
    fixture_rel = fixture_abs.relative_to(root).as_posix()

    raw_before = fixture_abs.read_bytes()
    sha_before = hashlib.sha256(raw_before).hexdigest()

    # Ingest data flow, in memory only: scan, sanitize, distill a candidate.
    text = raw_before.decode("utf-8")
    findings = scan_text(text)
    assert findings, "injection fixture must carry hygiene findings"
    clean, manifest = sanitize_text(text)
    assert len(manifest) == len(findings)

    candidate = (
        "---\n"
        "date: 2026-08-18\n"
        "tags: [wiki, research]\n"
        "status: active\n"
        "wiki_status: bootstrap\n"
        "source:\n"
        f'  - path: "{fixture_rel}"\n'
        "    type: clipping\n"
        f'    sha256: "{sha_before}"\n'
        '    ingested_at: "2026-08-18T00:00:00Z"\n'
        "ingested_by: process-ingest-v1\n"
        "---\n"
        "\n"
        "# Local-first note apps (P5 pipeline candidate)\n"
        "\n"
        "Local-first software keeps the primary copy of data on the device\n"
        "and treats the server as a sync peer; CRDTs reconcile concurrent\n"
        "edits, so the app works offline by default.\n"
    )
    # The candidate summarizes content; it never obeys the embedded payload.
    assert "HERMES-P5-CANARY" not in candidate

    # SHA invariance: the raw file's bytes are untouched by the whole flow.
    raw_after = fixture_abs.read_bytes()
    assert raw_after == raw_before
    assert hashlib.sha256(raw_after).hexdigest() == sha_before

    # Citation chain stays green: zero findings, nothing blocking.
    entries = parse_source_field(candidate)
    assert entries and entries[0]["sha256"] == sha_before
    citation_findings, has_blocking = validate_source_entries(entries, root)
    assert citation_findings == []
    assert has_blocking is False
