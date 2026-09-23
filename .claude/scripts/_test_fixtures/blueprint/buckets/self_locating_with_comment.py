"""Fixture: self-locating file that also carries a token-bearing comment.

Path convention note (documentation only, never resolved): the machine
username appears here in its long form WiktorPotapczyk or short form
WIKTOR~1, exactly like the real o17_portability_figures.py docstring this
fixture is modeled on.
"""
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
PROJECTS = VAULT / "Projects"
