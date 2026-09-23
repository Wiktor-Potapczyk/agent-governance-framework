"""Fixture: install_prereqs.py-shaped declared reference data.

The machine tokens below are DATA inside a probe table, never a path
computed or compared at runtime. This is the case the fixture bucket exists
to carve out of hard-coded-vault-literal.
"""
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def _static_entries():
    return [
        {
            "id": "python-interpreter",
            "probe": {
                "type": "executable",
                "path": "C:\\Program Files\\Python314\\python.exe",
            },
        },
        {
            "id": "npm-qmd-cli",
            "probe": {
                "type": "file_exists",
                "path": "C:\\Users\\WiktorPotapczyk\\AppData\\Roaming\\npm\\qmd.js",
            },
        },
    ]
