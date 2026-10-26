"""Buds assistant: gestures on the earbuds -> listen -> understand -> speak back.

Uses the Bluetooth protocol code from `budslab` (lab/budslab). In a checkout it is found next to this package; installed, it is a dependency.
"""
import sys
from pathlib import Path

_LAB = Path(__file__).resolve().parents[2] / "lab"
if _LAB.is_dir() and str(_LAB) not in sys.path:
    sys.path.insert(0, str(_LAB))
