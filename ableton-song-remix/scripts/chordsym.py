#!/usr/bin/env python3
"""Lead-sheet chord labels -> root, chord tones and bass note (a closed grammar).

The remix writes bass and keys from the chart's labels, so a label it misreads becomes
wrong notes in Live. The grammar is closed: a label it does not know raises ValueError
naming the label instead of guessing.

Grammar: root [A-G] with # or b (also the sharp and flat signs), then one quality, then
alterations, then an optional slash bass note.
  quality     '' m min - dim ° aug + sus2 sus4 sus 5 6 m6 6/9 m6/9 7 maj7 M7 Δ7 Δ ma7
              m7 min7 -7 mMaj7 m(maj7) mM7 m7b5 ø ø7 dim7 °7 7sus4 7sus 9 maj9 m9 add9
              add2 madd9 11 m11 13
  alteration  b5 #5 b9 #9 #11 b13 add9 add11, bare or in parentheses: 7b9, 7(#9), C(add9)
  slash       /note name: 'Em/D', 'D/F#' ('C6/9' is one chord)
  no chord    'N.C.' or 'NC' -> None

Usage (python3, standard library only):
    from chordsym import parse
    parse('D/F#')  # {'root': 2, 'intervals': [0, 4, 7], 'pcs': [2, 6, 9], 'bass': 6, ...}
    python3 chordsym.py Cmaj7 'Em/D' N.C.        # prints what each label parses to
"""
from __future__ import annotations

import re
import sys

NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
# Intervals above the root, in chord-tone order (9th = 14, 11th = 17, 13th = 21).
QUALITY = {
    '': [0, 4, 7], 'm': [0, 3, 7], 'min': [0, 3, 7], '-': [0, 3, 7],
    'dim': [0, 3, 6], '°': [0, 3, 6], 'aug': [0, 4, 8], '+': [0, 4, 8],
    'sus2': [0, 2, 7], 'sus4': [0, 5, 7], 'sus': [0, 5, 7], '5': [0, 7],
    '6': [0, 4, 7, 9], 'm6': [0, 3, 7, 9], '6/9': [0, 4, 7, 9, 14], 'm6/9': [0, 3, 7, 9, 14],
    '7': [0, 4, 7, 10], 'maj7': [0, 4, 7, 11], 'M7': [0, 4, 7, 11], 'Δ7': [0, 4, 7, 11],
    'Δ': [0, 4, 7, 11], 'ma7': [0, 4, 7, 11],
    'm7': [0, 3, 7, 10], 'min7': [0, 3, 7, 10], '-7': [0, 3, 7, 10],
    'mMaj7': [0, 3, 7, 11], 'm(maj7)': [0, 3, 7, 11], 'mM7': [0, 3, 7, 11],
    'm7b5': [0, 3, 6, 10], 'ø': [0, 3, 6, 10], 'ø7': [0, 3, 6, 10],
    'dim7': [0, 3, 6, 9], '°7': [0, 3, 6, 9], '7sus4': [0, 5, 7, 10], '7sus': [0, 5, 7, 10],
    '9': [0, 4, 7, 10, 14], 'maj9': [0, 4, 7, 11, 14], 'm9': [0, 3, 7, 10, 14],
    'add9': [0, 4, 7, 14], 'add2': [0, 4, 7, 14], 'madd9': [0, 3, 7, 14],
    '11': [0, 7, 10, 14, 17], 'm11': [0, 3, 7, 10, 14, 17], '13': [0, 4, 7, 10, 14, 21],
}
ALTER = {'b5': ('5', 6), '#5': ('5', 8), 'b9': ('+', 13), '#9': ('+', 15),
         '#11': ('+', 18), 'b13': ('+', 20), 'add9': ('+', 14), 'add11': ('+', 17)}
_QUALS = sorted(QUALITY, key=len, reverse=True)          # longest match first


def note_pc(name: str) -> int:
    """'F#' -> 6, 'Bb' -> 10 (one accidental)."""
    m = re.fullmatch(r'([A-G])([#b]?)', name)
    if not m:
        raise ValueError(f'not a note name: {name!r}')
    return (NOTE[m.group(1)] + {'#': 1, 'b': -1, '': 0}[m.group(2)]) % 12


def parse(label: str) -> dict | None:
    """Parse one label. None for N.C.; ValueError for anything outside the grammar."""
    s = str(label).strip().replace('♯', '#').replace('♭', 'b')
    if s in ('N.C.', 'NC', 'N.C'):
        return None
    m = re.fullmatch(r'(.+?)/([A-G][#b]?)', s)
    body, slash = (m.group(1), m.group(2)) if m else (s, None)
    m = re.match(r'([A-G][#b]?)', body)
    if not m:
        raise ValueError(f'unknown chord label {label!r}: no root A-G')
    root = note_pc(m.group(1))
    rest = body[m.end():]
    qual = next((q for q in _QUALS if rest.startswith(q)), None)
    if qual is None:
        raise ValueError(f'unknown chord label {label!r}')
    ivs = list(QUALITY[qual])
    tail = rest[len(qual):]
    if tail.startswith('(') and tail.endswith(')'):
        tail = tail[1:-1]
    for tok in [t for t in re.split(r'[,\s]+|(?=[#b]\d)', tail) if t]:
        if tok not in ALTER:
            raise ValueError(f'unknown chord label {label!r}: {tok!r} is not b5 #5 b9 #9 '
                             '#11 b13 add9 add11')
        kind, iv = ALTER[tok]
        if kind == '5':
            ivs = [iv if x == 7 else x for x in ivs]
            if iv not in ivs:
                ivs.append(iv)
        elif iv not in ivs:
            ivs.append(iv)
    third = next((x for x in ivs if x in (3, 4)), None)
    seventh = next((x for x in ivs if x in (10, 11) or (qual in ('dim7', '°7') and x == 9)),
                   None)
    return {'label': str(label), 'root': root, 'intervals': ivs,
            'pcs': [(root + x) % 12 for x in ivs],
            'bass': note_pc(slash) if slash else root,
            'third': None if third is None else (root + third) % 12,
            'seventh': None if seventh is None else (root + seventh) % 12}


def main() -> None:
    for lab in sys.argv[1:]:
        try:
            print(f'{lab}: {parse(lab)}')
        except ValueError as e:
            sys.exit(f'chordsym: {e}')


if __name__ == '__main__':
    main()
