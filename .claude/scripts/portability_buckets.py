"""Portability bucket table: A3 of the blueprint implementation plan.

Spec of record: Projects/Vault-Maintenance/work/2026-09-22-blueprint-implementation-plan.md
section "Implementation Phase A3: Path portability of the code that runs".

Scans code-that-runs (hooks, scripts, self-heal scripts, workflows, bin
resolvers, control-probes.json) for the machine tokens imported BY IDENTITY
from o17_portability_manifest.py (NAME_RE, VAULT_RE, INTERP_RE, PROFILE_RE),
plus two literal tokens (Desktop/Vault, Python314) that catch prose mentions
the drive-letter-anchored regexes miss.

Every file that carries at least one hit line resolves to exactly one bucket,
in this precedence order:

    self-locating         > hard-coded-vault-literal > interpreter-path
    > fixture              > profile-path             > prose-or-comment

self-locating   : file uses `parents[` and does NOT assign a path variable
                  from a literal drive-path string (Path(__file__) pattern).
hard-coded-vault-literal
                : a line assigns a name from a literal string/Path(...) whose
                  text matches the imported VAULT_RE (the three known hooks'
                  `VAULT = Path(r"C:\\...")` shape).
interpreter-path: a machine-token hit line (Python314) sits inside a
                  subprocess/Popen call, a genuine interpreter relaunch.
fixture         : the file lives under a _test_fixtures/_probe_fragments
                  path, is named test_*, is control-probes.json, or its
                  content is declared reference/probe data (an
                  `_static_entries()`-shaped function or an O17 `TOKEN_INFO`
                  literal) rather than a resolved or compared path.
profile-path    : a bare user-profile hit (PROFILE_RE) with no vault suffix
                  (VAULT_RE does not also match), e.g. npm globals.
prose-or-comment: every other hit line (comment, docstring, printed string).

No value from any secret store is read or written here; this module only
counts and classifies path syntax already present in tracked source.
"""
import argparse
import re
import sys
from datetime import date as _date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import o17_portability_manifest as o17m  # noqa: E402

# Imported by identity (GUD-001), never copied.
NAME_RE = o17m.NAME_RE
VAULT_RE = o17m.VAULT_RE
INTERP_RE = o17m.INTERP_RE
PROFILE_RE = o17m.PROFILE_RE

VAULT_ROOT = Path(__file__).resolve().parents[2]

# Literal tokens the drive-letter-anchored regexes above miss: a forward-slash
# mention with no drive letter ("...lives in Desktop/Vault") and a bare
# interpreter version mention with no "Program Files" prefix.
EXTRA_LITERAL_TOKENS = ("Desktop/Vault", "Python314")

ASSIGN_LITERAL_RE = re.compile(r'^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:Path\()?r?["\']')
FULL_LITERAL_RE = re.compile(r'^\s*[A-Za-z_][A-Za-z0-9_]*\s*=\s*(?:Path\()?r?(["\'])(?P<val>.*?)\1\)?\s*(?:#.*)?$')
SUBPROCESS_RE = re.compile(r"subprocess\.(?:run|call|check_call|check_output|Popen)\(|(?<![A-Za-z_])Popen\(")
FIXTURE_CONTENT_RE = re.compile(r"_static_entries\s*\(|^\s*TOKEN_INFO\s*=", re.MULTILINE)
FIXTURE_PATH_MARKERS = ("_test_fixtures", "_probe_fragments")

BUCKETS = (
    "self-locating",
    "hard-coded-vault-literal",
    "interpreter-path",
    "fixture",
    "profile-path",
    "prose-or-comment",
)

CONVERSION_NOTE = {
    "self-locating": "already self-locating, no change",
    "hard-coded-vault-literal": "convert to Path(__file__).resolve().parents[{n}]",
    "interpreter-path": "later slice: .claude/bin/py interpreter order, not converted here",
    "fixture": "fixture/reference data, excluded from conversion",
    "profile-path": "later slice: {{npm}}-style value, not converted here",
    "prose-or-comment": "comment/prose only, no change",
}

# Default scan population (Part 1 of this objective).
DEFAULT_GLOBS = (
    ("hooks", ".claude/hooks", "*.py"),
    ("scripts", ".claude/scripts", "*.py"),
    ("self-heal-scripts", ".claude/self-heal/scripts", "*.py"),
    ("workflows", ".claude/workflows", "*"),
    ("bin", ".claude/bin", "*"),
)
DEFAULT_SINGLE_FILES = (".claude/hooks/control-probes.json",)

DEFAULT_OUT = Path("Projects/Vault-Maintenance/work/2026-09-22-portability-buckets.md")


def default_population(vault_root=VAULT_ROOT):
    """Return the code-that-runs population this objective scans."""
    vault_root = Path(vault_root)
    paths = []
    for _label, rel_dir, pattern in DEFAULT_GLOBS:
        d = vault_root / rel_dir
        if not d.is_dir():
            continue
        for p in sorted(d.glob(pattern)):
            if p.is_file():
                paths.append(p)
    for rel in DEFAULT_SINGLE_FILES:
        p = vault_root / rel
        if p.is_file():
            paths.append(p)
    return paths


def _read_lines(path):
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return text, text.splitlines()


def _is_hit(line):
    if NAME_RE.search(line) or VAULT_RE.search(line) or INTERP_RE.search(line) or PROFILE_RE.search(line):
        return True
    return any(tok in line for tok in EXTRA_LITERAL_TOKENS)


def _has_self_locating(lines):
    return any("parents[" in line for line in lines)


def _has_hard_coded_vault_literal(lines):
    for line in lines:
        if ASSIGN_LITERAL_RE.match(line) and VAULT_RE.search(line):
            return True
    return False


def _has_interpreter_path_in_subprocess(lines):
    for i, line in enumerate(lines):
        if not (INTERP_RE.search(line) or "Python314" in line):
            continue
        window = "\n".join(lines[max(0, i - 3):i + 1])
        if SUBPROCESS_RE.search(window):
            return True
    return False


def _is_fixture_path(rel_path):
    parts = Path(rel_path).parts
    if any(marker in parts for marker in FIXTURE_PATH_MARKERS):
        return True
    name = Path(rel_path).name
    return name.startswith("test_") or name == "control-probes.json"


def _has_fixture_content(text):
    return bool(FIXTURE_CONTENT_RE.search(text))


def _has_profile_no_vault(lines):
    for line in lines:
        if PROFILE_RE.search(line) and not VAULT_RE.search(line):
            return True
    return False


def depth(file, vault_root=VAULT_ROOT):
    """Directory levels between vault_root and file's own directory.

    This is `n` for the `Path(__file__).resolve().parents[n]` idiom, per
    o17_portability_figures.py's n=2 precedent for `.claude/scripts/x.py`.
    """
    file_dir = Path(file).resolve().parent
    vault_root = Path(vault_root).resolve()
    rel = file_dir.relative_to(vault_root)
    return len(rel.parts)


def _rel_path(path, vault_root):
    try:
        return Path(path).resolve().relative_to(Path(vault_root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _full_vault_literal_line(lines):
    """Line number of an assignment whose literal IS the vault root, exactly
    (nothing appended). Only such a literal survives round-trip through the
    parents[n] idiom; a longer literal (a full file path used as test
    fixture/comparison data) would lose its suffix if converted.
    """
    for i, line in enumerate(lines, start=1):
        if not ASSIGN_LITERAL_RE.match(line):
            continue
        m = FULL_LITERAL_RE.match(line)
        if m and VAULT_RE.fullmatch(m.group("val")):
            return i
    return None


def classify_file(path, vault_root=VAULT_ROOT):
    """Return a bucket row dict for one file, or None if it has no hits."""
    text, lines = _read_lines(path)
    hit_lines = [i for i, line in enumerate(lines, start=1) if _is_hit(line)]
    if not hit_lines:
        return None
    rel = _rel_path(path, vault_root)

    if _has_self_locating(lines) and not _has_hard_coded_vault_literal(lines):
        bucket = "self-locating"
    elif _has_hard_coded_vault_literal(lines):
        bucket = "hard-coded-vault-literal"
    elif _has_interpreter_path_in_subprocess(lines):
        bucket = "interpreter-path"
    elif _is_fixture_path(rel) or _has_fixture_content(text):
        bucket = "fixture"
    elif _has_profile_no_vault(lines):
        bucket = "profile-path"
    else:
        bucket = "prose-or-comment"

    row = {"file": rel, "bucket": bucket, "lines": hit_lines}
    if bucket == "hard-coded-vault-literal":
        row["convertible"] = _full_vault_literal_line(lines) is not None
    return row


def scan(paths, vault_root=VAULT_ROOT):
    """Classify every path in `paths`. Rows: {file, bucket, lines}."""
    rows = []
    for p in paths:
        row = classify_file(p, vault_root)
        if row is not None:
            rows.append(row)
    return rows


def _conversion(row, vault_root=VAULT_ROOT):
    bucket = row["bucket"]
    if bucket == "hard-coded-vault-literal":
        if row.get("convertible", True):
            n = depth(vault_root / row["file"], vault_root)
            return CONVERSION_NOTE[bucket].format(n=n)
        return (
            "left unconverted: literal extends past the vault root (a full path used "
            "as test fixture or comparison data), parents[n] cannot reproduce the suffix"
        )
    return CONVERSION_NOTE[bucket]


def _top_dir(rel_path):
    parts = Path(rel_path).parts
    if len(parts) >= 3 and parts[0] == ".claude":
        return "/".join(parts[:3]) if parts[1] == "self-heal" else "/".join(parts[:2])
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else "(root)"


def write_report(rows, out_path, generated=None):
    """Write the per-bucket, per-directory, per-file markdown report.

    Returns the per-bucket count dict; counts sum to len(rows).
    """
    generated = generated or _date.today().isoformat()
    bucket_counts = {b: 0 for b in BUCKETS}
    dir_counts = {}
    for r in rows:
        bucket_counts[r["bucket"]] += 1
        d = _top_dir(r["file"])
        dir_counts.setdefault(d, {b: 0 for b in BUCKETS})
        dir_counts[d][r["bucket"]] += 1

    lines = [
        "---",
        f"date: {generated}",
        "tags: [project/vault-maintenance, audit, hooks]",
        "status: active",
        "---",
        "",
        "Hub: [[moc-agent-governance]]. Plan: [[2026-09-22-harness-migration-blueprint-plan]].",
        "",
        "# Portability bucket table (A3)",
        "",
        f"Generated {generated}. Scanned {len(rows)} file(s) with at least one machine-token hit "
        "line, out of the code-that-runs population (`.claude/hooks/*.py`, `.claude/scripts/*.py`, "
        "`.claude/self-heal/scripts/*.py`, `.claude/workflows/*`, `.claude/bin/*`, "
        "`.claude/hooks/control-probes.json`). Tokens: `NAME_RE`, `VAULT_RE`, `INTERP_RE`, "
        "`PROFILE_RE` imported by identity from `o17_portability_manifest.py`, plus the literal "
        "tokens `Desktop/Vault` and `Python314`.",
        "",
        "## Bucket counts",
        "",
        "| Bucket | Files |",
        "|---|---|",
    ]
    for b in BUCKETS:
        lines.append(f"| {b} | {bucket_counts[b]} |")
    lines += [
        f"| **total** | **{len(rows)}** |",
        "",
        "## Per-directory counts",
        "",
        "| Directory | " + " | ".join(BUCKETS) + " | Total |",
        "|---|" + "---|" * (len(BUCKETS) + 1),
    ]
    for d in sorted(dir_counts):
        counts = dir_counts[d]
        total = sum(counts.values())
        lines.append(
            f"| {d} | " + " | ".join(str(counts[b]) for b in BUCKETS) + f" | {total} |"
        )
    lines += [
        "",
        "## Per-file table",
        "",
        "| File | Bucket | Hits | Conversion proposed |",
        "|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: r["file"]):
        lines.append(
            f"| `{r['file']}` | {r['bucket']} | {len(r['lines'])} | {_conversion(r)} |"
        )
    lines.append("")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return bucket_counts


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="write the report to --out")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    rows = scan(default_population(), VAULT_ROOT)
    counts = {b: sum(1 for r in rows if r["bucket"] == b) for b in BUCKETS}
    print(f"scanned files with hits: {len(rows)}")
    for b in BUCKETS:
        print(f"{b}: {counts[b]}")

    if args.write:
        out_path = Path(args.out)
        if not out_path.is_absolute():
            out_path = VAULT_ROOT / out_path
        write_report(rows, out_path, generated=args.date)
        print(f"report written: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
