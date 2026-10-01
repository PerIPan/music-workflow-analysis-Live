#!/usr/bin/env python3
"""Our chord reading vs a chord tab, per section: what agrees, what to check by ear.

Why: the chart is our own reading (lv-chordia, the triad cross-check, the bass); a tab
from the web is a second opinion, often simplified (one shape for a whole riff) or wrong
(a transposed key, a missing passing chord). Read first, then compare - never copy a tab
into the chart. For each tab section (tab_chords.json from lyrics_from_page.py) matched in
order to sections.json by label, it lists both chord vocabularies (root + major/minor) and
flags: a chord only in the tab (a passing chord shorter than a cell? check the bass), only
in ours (a tab simplification?), and the same root with the other quality (third by ear).

Usage (python3, standard library only):
    tab_compare.py --tab analysis/tab_chords.json --chords analysis/chords_lv.json \
        --sections analysis/sections.json [--bass analysis/bass_per_cell.json]
"""
from __future__ import annotations

import argparse, json, re
from pathlib import Path

NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
NAMES = ['C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B']


def simple(label: str) -> tuple[int, str] | None:
    """(root pc, 'maj'|'min') from 'F#', 'Bm7', 'A/C#', 'F#:min', 'B:maj7'; None for N.C."""
    m = re.match(r'^([A-G])([#b]?)(.*)$', label.strip())
    if not m:
        return None
    pc = (NOTE[m.group(1)] + {'#': 1, 'b': -1, '': 0}[m.group(2)]) % 12
    rest = m.group(3).split('/')[0].lstrip(':')
    minor = bool(re.match(r'^(m(?!aj)|min|-)', rest)) or rest.startswith('dim')
    return pc, 'min' if minor else 'maj'


def name(c: tuple[int, str]) -> str:
    return NAMES[c[0]] + ('m' if c[1] == 'min' else '')


def spans(sections: list[dict], nbars: int) -> list[tuple[str, int, int]]:
    starts = [s['where'][0] for s in sections]
    return [(s['label'], starts[i], (starts[i + 1] - 1) if i + 1 < len(starts) else nbars)
            for i, s in enumerate(sections)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tab', required=True)
    ap.add_argument('--chords', required=True, help='chords_lv.json (cells with bar, chord)')
    ap.add_argument('--sections', required=True)
    ap.add_argument('--bass', help='bass_per_cell.json: does the bass ever play a tab-only root?')
    a = ap.parse_args()
    tab = json.loads(Path(a.tab).read_text())['sections']
    cells = json.loads(Path(a.chords).read_text())['cells']
    secs = json.loads(Path(a.sections).read_text())['sections']
    bass = json.loads(Path(a.bass).read_text())['cells'] if a.bass else []
    nbars = max(c['bar'] for c in cells)
    ours = spans(secs, nbars)
    used, agree, total = set(), 0, 0
    print(f"{'section':12} {'bars':8} {'tab':28} {'ours':28} check")
    for t in tab:
        key = t['section'].lower()
        hit = next((i for i, (lab, _, _) in enumerate(ours)
                    if i not in used and lab.lower().split()[0] == key.split()[0]), None)
        if hit is None:
            print(f"{t['section']:12} {'-':8} (no section of ours with this label)")
            continue
        used.add(hit)
        lab, b0, b1 = ours[hit]
        tv = [c for c in map(simple, t['chords']) if c]
        ov = [c for c in (simple(c['chord']) for c in cells if b0 <= c['bar'] <= b1) if c]
        ts, os_ = set(tv), set(ov)
        flags = []
        for c in sorted(ts - os_):
            other = (c[0], 'min' if c[1] == 'maj' else 'maj')
            if other in os_:
                flags.append(f'{name(c)} vs our {name(other)}: the third by ear')
            else:
                heard = sum(1 for x in bass if b0 <= x['bar'] <= b1
                            and x['pc_seconds'].get(NAMES[c[0]].replace('Eb', 'D#')
                                                    .replace('Ab', 'G#').replace('Bb', 'A#'), 0)
                            >= 0.15) if bass else None
                flags.append(f'{name(c)} only in the tab' +
                             ('' if heard is None else
                              f' (bass on it in {heard} cells)' if heard else
                              ' (never in the bass: a passing chord over a held bass?)'))
        for c in sorted(os_ - ts):
            if (c[0], 'min' if c[1] == 'maj' else 'maj') not in ts:
                flags.append(f'{name(c)} only in ours')
        total += len(ts | os_)
        agree += len(ts & os_)
        fmt = lambda v: ' '.join(name(c) for c in sorted(v, key=lambda c: (c[0], c[1])))
        print(f"{t['section']:12} {b0:>3}-{b1:<4} {fmt(ts):28} {fmt(os_):28} "
              f"{'; '.join(flags) or 'agree'}")
    print(f'chord vocabulary agreement: {agree}/{total} (root + major/minor, per section)')


if __name__ == '__main__':
    main()
