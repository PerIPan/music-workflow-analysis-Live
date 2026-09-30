#!/usr/bin/env python3
"""Test bass_notes.downbeat_check on synthetic per-cell bass tables.

A 4-bar C-C-Bb-Bb loop read on a grid shifted by two beats changes on cell 2 every time:
the check must flag it and suggest the shifted downbeat. The same loop on the right grid,
a walking bass (changes on both cells), an 11/8 loop and a sparse part must stay silent
or name the right cell. Run with the analysis venv: <venv>/bin/python tests/test_downbeat_check.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bass_notes import downbeat_check  # noqa: E402


def table(cells_per_bar, pcs):
    """pcs: one pitch class (or None) per cell, in order."""
    return [dict(bar=i // cells_per_bar + 1, cell=i % cells_per_bar + 1,
                 pc_seconds={p: 0.8} if p else {}) for i, p in enumerate(pcs)]


def main():
    loop_ok = ["C", "C", "C", "C", "A#", "A#", "A#", None] * 12        # changes on cell 1
    loop_shift = [None, "C", "C", "C", "C", "A#", "A#", "A#"] * 12     # grid 2 beats early
    walk = ["C", "E", "G", "E", "F", "A", "C", "A"] * 12               # moves every cell
    sparse = ["C", "C", "A#", "A#"] + [None] * 20                      # too few changes
    cases = [
        ("loop on the right grid", downbeat_check(table(2, loop_ok), [2, 2], 0), None),
        ("loop on a shifted grid", downbeat_check(table(2, loop_shift), [2, 2], 0), (2, 2)),
        ("shift wraps the bar", downbeat_check(table(2, loop_shift), [2, 2], 3), (2, 1)),
        ("walking bass", downbeat_check(table(2, walk), [2, 2], 0), None),
        ("11/8 loop shifted by the 6", downbeat_check(table(2, loop_shift), [6, 5], 0), (2, 6)),
        ("sparse part", downbeat_check(table(2, sparse), [2, 2], 0), None),
    ]
    fails = 0
    for name, got, want in cases:
        ok = (got is None) if want is None else (got is not None and (got[0], got[2]) == want)
        print(f"{'ok  ' if ok else 'FAIL'} {name}: {got}")
        fails += not ok
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
