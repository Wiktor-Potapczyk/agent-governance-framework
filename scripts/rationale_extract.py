#!/usr/bin/env python3
"""rationale_extract.py - O6 per-component why-layer generator.

Origin: O6 of Projects/Agent-Governance-Research/work/2026-08-30-harness-spec-objectives.md,
coverage option (a) per the 2026-08-30 delegated ruling: rationale for all vault-owned
components, extracted by generator from each component's own stated purpose; hand-written
entries only where extraction finds nothing.

Population
----------
A row from .claude/hooks/aggregates/asset-inventory.json is "vault-owned" iff its
provenance is exactly "authored-in-harness", OR its provenance starts with "junction:"
(the one NTFS-junction skill the O8 evidence names as included alongside the
authored-in-harness set). Plugin-sourced rows (provenance starts with "plugin:") are
out of scope; they are documented in aggregate only, per the ruling.

Extraction, per kind
---------------------
hook / settings-registration / telemetry-sink (resolved to a script): the script's
module docstring (or, for .sh/.ps1, its leading '#'-comment header block), preferring
a paragraph that contains one of the why-markers WHY, "Empirical trigger", Origin,
Rationale, "exists because" over the first paragraph.
skill: SKILL.md frontmatter `description`, plus the first bullet under a `## Use-when`
heading if the description does not already contain the phrase "use when".
agent: frontmatter `description`, first sentence only.
workflow: the `description` field inside the `export const meta = {...}` block.
mcp-server (and settings-registration rows named `mcp:<server>`): the line in
CLAUDE.md that names the server inside its "MCP servers" bullet, if present.

Every rationale is a verbatim extract, trimmed to 400 characters. Nothing is
invented or paraphrased. A component whose source carries no stated why gets
extraction_status NO_STATED_WHY -- a finding, not a failure.

Usage:
    "C:\\Program Files\\Python314\\python.exe" .claude/scripts/rationale_extract.py
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Layout adaptation (published copy): harness root from VAULT_DIR (repo keeps
# scripts/ at top level, not under .claude/).
VAULT = Path(os.environ.get("VAULT_DIR", "C:/Users/exampleuser/Workspace"))
DEFAULT_ASSET_INVENTORY = VAULT / ".claude" / "hooks" / "aggregates" / "asset-inventory.json"
DEFAULT_CLAUDE_MD = VAULT / "CLAUDE.md"
DEFAULT_OUTPUT_JSON = VAULT / ".claude" / "hooks" / "aggregates" / "rationale-index.json"
DEFAULT_OUTPUT_MD = VAULT / ".claude" / "hooks" / "aggregates" / "rationale-index.md"

GENERATOR_VERSION = "1.0"
MAX_LEN = 400

STATUS_EXTRACTED = "EXTRACTED"
STATUS_NONE = "NO_STATED_WHY"

LOCUS_DOCSTRING = "docstring"
LOCUS_FRONTMATTER = "frontmatter"
LOCUS_META = "meta"
LOCUS_CLAUDE_MD = "claude-md"

WHY_MARKERS = [
    re.compile(r"\bWHY\b"),
    re.compile(r"Empirical trigger", re.IGNORECASE),
    re.compile(r"\bOrigin\b", re.IGNORECASE),
    re.compile(r"\bRationale\b", re.IGNORECASE),
    re.compile(r"exists because", re.IGNORECASE),
]

CLAUDE_MD_MCP_ANCHOR = "MCP servers"


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def resolve_path(path_str: str, vault: Path = VAULT) -> Path:
    """A row's `path` (or a reachability source_file) is vault-relative for
    authored-in-harness rows but absolute for the one junction row. Handle both."""
    p = Path(path_str)
    if p.is_absolute():
        return p
    return vault / p


def to_rel_str(path: Path, vault: Path = VAULT) -> str:
    try:
        rel = path.resolve().relative_to(vault.resolve())
        return str(rel).replace("\\", "/")
    except (ValueError, OSError):
        return str(path).replace("\\", "/")


# ---------------------------------------------------------------------------
# Text primitives
# ---------------------------------------------------------------------------

def split_paragraphs(text: str) -> list[str]:
    if not text:
        return []
    blocks = re.split(r"\n\s*\n", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def find_why_paragraph(paragraphs: list[str]) -> Optional[str]:
    if not paragraphs:
        return None
    for para in paragraphs:
        if any(marker.search(para) for marker in WHY_MARKERS):
            return para
    return paragraphs[0]


def trim(text: str) -> str:
    text = text.strip()
    return text[:MAX_LEN] if len(text) > MAX_LEN else text


# ---------------------------------------------------------------------------
# Source-file extraction (docstring-equivalent, any kind pointing at a script)
# ---------------------------------------------------------------------------

def extract_py_docstring(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    return ast.get_docstring(tree, clean=True)


def extract_leading_comment_block(path: Path) -> Optional[str]:
    """Header-comment equivalent of a module docstring, for .sh / .ps1 scripts."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    out: list[str] = []
    started = False
    for line in lines:
        s = line.strip()
        if not started:
            if s.startswith("#!"):
                continue
            if s.startswith("#"):
                started = True
                out.append(s.lstrip("#").strip())
                continue
            break
        if s.startswith("#"):
            out.append(s.lstrip("#").strip())
        else:
            break
    return "\n".join(out) if out else None


def extract_from_script_path(rel_or_abs_path: str) -> tuple[str, str, Optional[str], Optional[str]]:
    """Returns (rationale, status, locus, source_path) for any resolvable script,
    regardless of which row kind pointed at it."""
    p = resolve_path(rel_or_abs_path)
    source_path = to_rel_str(p)
    if not p.exists():
        return "", STATUS_NONE, None, source_path

    if p.suffix == ".py":
        doc = extract_py_docstring(p)
    elif p.suffix in (".sh", ".ps1"):
        doc = extract_leading_comment_block(p)
    else:
        doc = None

    if not doc:
        return "", STATUS_NONE, None, source_path

    paragraphs = split_paragraphs(doc)
    para = find_why_paragraph(paragraphs)
    if not para:
        return "", STATUS_NONE, None, source_path
    return trim(para), STATUS_EXTRACTED, LOCUS_DOCSTRING, source_path


# ---------------------------------------------------------------------------
# Frontmatter (skills, agents)
# ---------------------------------------------------------------------------

def extract_frontmatter_field(text: str, field: str) -> Optional[str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    block = m.group(1)
    fm = re.search(rf"^{field}:\s*(.*)$", block, re.MULTILINE)
    if not fm:
        return None
    raw = fm.group(1).strip()
    if raw.startswith('"'):
        qm = re.match(r'"((?:[^"\\]|\\.)*)"', raw)
        if qm:
            return qm.group(1).replace('\\"', '"').replace("\\n", " ")
        return raw.strip('"')
    if raw.startswith("'"):
        qm = re.match(r"'((?:[^'\\]|\\.)*)'", raw)
        if qm:
            return qm.group(1).replace("\\'", "'")
        return raw.strip("'")
    return raw


def extract_use_when_line(text: str) -> Optional[str]:
    m = re.search(r"^##\s*Use-when\s*\n+(.*?)(?:\n##|\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        return None
    for line in m.group(1).splitlines():
        line = line.strip()
        if line:
            return line.lstrip("- ").strip()
    return None


def extract_skill_rationale(row: dict) -> tuple[str, str, Optional[str], Optional[str]]:
    skill_dir = resolve_path(row["path"])
    skill_md = skill_dir / "SKILL.md"
    source_path = to_rel_str(skill_md)
    if not skill_md.exists():
        return "", STATUS_NONE, None, source_path
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return "", STATUS_NONE, None, source_path
    desc = extract_frontmatter_field(text, "description")
    if not desc:
        return "", STATUS_NONE, None, source_path
    rationale = desc
    if "use when" not in desc.lower():
        use_line = extract_use_when_line(text)
        if use_line:
            rationale = f"{desc} Use-when: {use_line}"
    return trim(rationale), STATUS_EXTRACTED, LOCUS_FRONTMATTER, source_path


def extract_agent_rationale(row: dict) -> tuple[str, str, Optional[str], Optional[str]]:
    p = resolve_path(row["path"])
    source_path = to_rel_str(p)
    if not p.exists():
        return "", STATUS_NONE, None, source_path
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return "", STATUS_NONE, None, source_path
    desc = extract_frontmatter_field(text, "description")
    if not desc:
        return "", STATUS_NONE, None, source_path
    sm = re.match(r"^(.*?[.!?])(?:\s|$)", desc, re.DOTALL)
    sentence = sm.group(1).strip() if sm else desc
    return trim(sentence), STATUS_EXTRACTED, LOCUS_FRONTMATTER, source_path


# ---------------------------------------------------------------------------
# Workflow meta description
# ---------------------------------------------------------------------------

def extract_workflow_rationale(row: dict) -> tuple[str, str, Optional[str], Optional[str]]:
    p = resolve_path(row["path"])
    source_path = to_rel_str(p)
    if not p.exists():
        return "", STATUS_NONE, None, source_path
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return "", STATUS_NONE, None, source_path
    idx = text.find("export const meta")
    if idx == -1:
        idx = text.find("const meta")
    if idx == -1:
        return "", STATUS_NONE, None, source_path
    window = text[idx: idx + 4000]
    m = re.search(r"description:\s*'((?:[^'\\]|\\.)*)'", window)
    if not m:
        m = re.search(r'description:\s*"((?:[^"\\]|\\.)*)"', window)
    if not m:
        return "", STATUS_NONE, None, source_path
    val = m.group(1).replace("\\'", "'").replace('\\"', '"')
    return trim(val), STATUS_EXTRACTED, LOCUS_META, source_path


# ---------------------------------------------------------------------------
# CLAUDE.md MCP-section line (mcp-server rows, and mcp: settings-registrations)
# ---------------------------------------------------------------------------

def _claude_md_mcp_line(server_name: str, claude_md_path: Path) -> Optional[str]:
    if not claude_md_path.exists():
        return None
    try:
        text = claude_md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    name_re = re.compile(rf"\b{re.escape(server_name)}\b")
    anchor_line = None
    for line in text.splitlines():
        if CLAUDE_MD_MCP_ANCHOR in line and name_re.search(line):
            anchor_line = line.strip()
            break
    if anchor_line:
        return anchor_line
    for line in text.splitlines():
        if "MCP" in line and name_re.search(line):
            return line.strip()
    return None


def extract_mcpserver_rationale(row: dict, claude_md_path: Path) -> tuple[str, str, Optional[str], Optional[str]]:
    line = _claude_md_mcp_line(row["name"], claude_md_path)
    source_path = to_rel_str(claude_md_path)
    if not line:
        return "", STATUS_NONE, None, source_path
    return trim(line), STATUS_EXTRACTED, LOCUS_CLAUDE_MD, source_path


# ---------------------------------------------------------------------------
# settings-registration: resolve to the hook/script it registers, or to an
# mcp: server name, then reuse the extractors above.
# ---------------------------------------------------------------------------

_RESOLVES_TO_HOOK_RE = re.compile(r"resolves to hook '([^']+)'")
_SCRIPT_PATH_RE = re.compile(r"([A-Za-z]:[\\/][^'\"]+?\.(?:py|sh|ps1))")


def _resolve_settings_registration_script(row: dict) -> Optional[str]:
    hook_name = None
    for ev in row.get("reachability", []):
        m = _RESOLVES_TO_HOOK_RE.search(ev.get("detail", "") or "")
        if m:
            hook_name = m.group(1)
            break
    if hook_name:
        candidate = VAULT / ".claude" / "hooks" / f"{hook_name}.py"
        if candidate.exists():
            return to_rel_str(candidate)

    for ev in row.get("reachability", []):
        detail = ev.get("detail", "") or ""
        m = _SCRIPT_PATH_RE.search(detail)
        if m:
            candidate = resolve_path(m.group(1))
            if candidate.exists():
                return to_rel_str(candidate)
    return None


def extract_settings_registration_rationale(row: dict, claude_md_path: Path) -> tuple[str, str, Optional[str], Optional[str]]:
    name = row["name"]
    if name.startswith("mcp:"):
        server = name.split(":", 1)[1]
        return extract_mcpserver_rationale({"name": server}, claude_md_path)

    script_rel = _resolve_settings_registration_script(row)
    if script_rel is None:
        return "", STATUS_NONE, None, None
    return extract_from_script_path(script_rel)


# ---------------------------------------------------------------------------
# telemetry-sink: resolve to the script the entry points at (a representative
# writer), reuse the script extractor.
# ---------------------------------------------------------------------------

def extract_telemetry_sink_rationale(row: dict) -> tuple[str, str, Optional[str], Optional[str]]:
    stem = Path(row["name"]).stem
    writers = [
        ev.get("source_file")
        for ev in row.get("reachability", [])
        if ev.get("type") == "EVD-010" and ev.get("source_file")
    ]
    chosen = None
    for w in writers:
        if Path(w).stem == stem:
            chosen = w
            break
    if chosen is None and writers:
        chosen = writers[0]
    if chosen is None:
        return "", STATUS_NONE, None, row.get("path")
    return extract_from_script_path(chosen)


# ---------------------------------------------------------------------------
# Population + dispatch
# ---------------------------------------------------------------------------

def is_vault_owned(row: dict) -> bool:
    prov = row.get("provenance", "") or ""
    return prov == "authored-in-harness" or prov.startswith("junction:")


def extract_row(row: dict, claude_md_path: Path) -> dict:
    kind = row.get("kind")
    try:
        if kind == "hook":
            rationale, status, locus, source_path = extract_from_script_path(row["path"])
        elif kind == "skill":
            rationale, status, locus, source_path = extract_skill_rationale(row)
        elif kind == "agent":
            rationale, status, locus, source_path = extract_agent_rationale(row)
        elif kind == "workflow":
            rationale, status, locus, source_path = extract_workflow_rationale(row)
        elif kind == "mcp-server":
            rationale, status, locus, source_path = extract_mcpserver_rationale(row, claude_md_path)
        elif kind == "settings-registration":
            rationale, status, locus, source_path = extract_settings_registration_rationale(row, claude_md_path)
        elif kind == "telemetry-sink":
            rationale, status, locus, source_path = extract_telemetry_sink_rationale(row)
        else:
            rationale, status, locus, source_path = "", STATUS_NONE, None, row.get("path")
    except Exception as exc:  # extraction must never crash the whole run
        print(f"[rationale_extract] WARN: {row.get('name')!r} ({kind}) raised {exc!r}, "
              f"treating as {STATUS_NONE}", file=sys.stderr)
        rationale, status, locus, source_path = "", STATUS_NONE, None, row.get("path")

    return {
        "name": row.get("name"),
        "kind": kind,
        "source_path": source_path,
        "rationale": rationale,
        "extraction_status": status,
        "extraction_locus": locus,
    }


# ---------------------------------------------------------------------------
# Run + render
# ---------------------------------------------------------------------------

def load_asset_inventory(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_index(asset_inventory_path: Path, claude_md_path: Path) -> dict:
    inventory = load_asset_inventory(asset_inventory_path)
    all_rows = inventory.get("rows", [])
    owned = [r for r in all_rows if is_vault_owned(r)]
    owned_sorted = sorted(owned, key=lambda r: (r.get("kind") or "", r.get("name") or ""))

    rows_out = [extract_row(r, claude_md_path) for r in owned_sorted]

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_version": GENERATOR_VERSION,
        "source_asset_inventory": to_rel_str(asset_inventory_path),
        "source_asset_inventory_generated_at": inventory.get("generated_at"),
        "population_definition": "provenance == 'authored-in-harness' OR provenance startswith 'junction:'",
        "row_count": len(rows_out),
        "rows": rows_out,
    }


def render_summary_md(index: dict) -> str:
    rows = index["rows"]
    kinds = sorted({r["kind"] for r in rows})
    lines = [
        "# Rationale Index Summary",
        "",
        f"Generated: {index['generated_at']}. Source: `{index['source_asset_inventory']}` "
        f"(generated_at {index['source_asset_inventory_generated_at']}). "
        f"Population: {index['row_count']} rows ({index['population_definition']}).",
        "",
    ]
    for kind in kinds:
        subset = [r for r in rows if r["kind"] == kind]
        extracted = sum(1 for r in subset if r["extraction_status"] == STATUS_EXTRACTED)
        none_count = sum(1 for r in subset if r["extraction_status"] == STATUS_NONE)
        lines.append(f"## {kind}")
        lines.append("")
        lines.append(f"- {STATUS_EXTRACTED}: {extracted}")
        lines.append(f"- {STATUS_NONE}: {none_count}")
        lines.append("")

    no_stated = [r for r in rows if r["extraction_status"] == STATUS_NONE]
    lines.append(f"## {STATUS_NONE} components ({len(no_stated)})")
    lines.append("")
    if no_stated:
        for r in no_stated:
            src = r["source_path"] or "(unresolved)"
            lines.append(f"- {r['name']} ({r['kind']}) - {src}")
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)


def write_outputs(index: dict, output_json: Path, output_md: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_summary_md(index), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract per-component why-layer rationale rows.")
    parser.add_argument("--asset-inventory", type=Path, default=DEFAULT_ASSET_INVENTORY)
    parser.add_argument("--claude-md", type=Path, default=DEFAULT_CLAUDE_MD)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    index = build_index(args.asset_inventory, args.claude_md)
    write_outputs(index, args.output_json, args.output_md)
    extracted = sum(1 for r in index["rows"] if r["extraction_status"] == STATUS_EXTRACTED)
    none_count = sum(1 for r in index["rows"] if r["extraction_status"] == STATUS_NONE)
    print(f"rationale_extract: {index['row_count']} rows ({extracted} EXTRACTED, {none_count} NO_STATED_WHY) "
          f"-> {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
