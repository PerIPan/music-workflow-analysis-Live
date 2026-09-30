#!/usr/bin/env python3
"""Test scripts/chordsym.py: the chord grammar table, slash bass vs 6/9, sharp and flat
signs, half-diminished and diminished sevenths, alterations, N.C., and that an unknown
label raises instead of being guessed.
Run: python3 tests/test_chordsym.py   (standard library only)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chordsym import parse  # noqa: E402

TABLE = {                        # label: (sorted pitch classes, bass pc)
    'C': ([0, 4, 7], 0), 'Am': ([0, 4, 9], 9), 'Cmaj7': ([0, 4, 7, 11], 0),
    'F#m7': ([1, 4, 6, 9], 6), 'Em/D': ([4, 7, 11], 2), 'D/F#': ([2, 6, 9], 6),
    'C6/9': ([0, 2, 4, 7, 9], 0), 'Am7b5': ([0, 3, 7, 9], 9), 'Bø': ([2, 5, 9, 11], 11),
    'B°7': ([2, 5, 8, 11], 11), 'Bdim': ([2, 5, 11], 11), 'Caug': ([0, 4, 8], 0),
    'Gsus4': ([0, 2, 7], 7), 'Dsus2': ([2, 4, 9], 2), 'E5': ([4, 11], 4),
    'G7': ([2, 5, 7, 11], 7), 'CΔ7': ([0, 4, 7, 11], 0), 'Cadd9': ([0, 2, 4, 7], 0),
    'Am9': ([0, 4, 7, 9, 11], 9), 'C7(b9)': ([0, 1, 4, 7, 10], 0), 'C7#9': ([0, 3, 4, 7, 10], 0),
    'F♯m': ([1, 6, 9], 6), 'B♭maj7/D': ([2, 5, 9, 10], 2), 'Cm(maj7)': ([0, 3, 7, 11], 0),
    'G7sus4': ([0, 2, 5, 7], 7), 'C7b5': ([0, 4, 6, 10], 0),
}


def main():
    fails = 0
    def check(name, cond, info=''):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))

    for lab, (pcs, bass) in TABLE.items():
        try:
            c = parse(lab)
            got = (sorted(c['pcs']), c['bass'])
        except ValueError as e:
            got = str(e)
        check(f'{lab} -> {pcs} bass {bass}', got == (pcs, bass), got)
    check('N.C. and NC -> None', parse('N.C.') is None and parse('NC') is None)
    c = parse('F#m7')
    check('3rd and 7th reported', c['third'] == 9 and c['seventh'] == 4)
    check('dim7 seventh is the bb7', parse('B°7')['seventh'] == 8)
    for bad in ('Hm', 'Cfoo', 'C7(b10)', 'A:min7', 'Cmaj7/X', ''):
        try:
            parse(bad)
            check(f'{bad!r} refused', False, 'parsed')
        except ValueError:
            check(f'{bad!r} refused', True)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
