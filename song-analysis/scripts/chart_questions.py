#!/usr/bin/env python3
"""The chart's open calls as questions for the player, each with its evidence and options.

Why: a "?" in a printed chart waits for someone to notice it; a player checking on their
instrument answers in seconds when asked directly. After chart_html.py, this lists what
the chart is unsure of - cells marked "?" (the readers name another root), skipping
verified cells and stop bars - with the chart's chord, what lv-chordia, the triad reader
and the bass heard, and the parallel section's chord when the section repeats (counted
from the start, or from the end when the two differ in length - turnarounds close them). Ask them
a few at a time - and cells that break their section's repeating pattern even where the
readers agree (pattern_breaks); each answer goes back into the data file (a fix in `chords`, the cell
in `verified`), then re-render.

Usage (python3, standard library only; from the song folder):
    chart_questions.py gen_v1.py [--json analysis/questions.json] [--max 12]
"""
from __future__ import annotations

import argparse, json, runpy, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chart_html import STOP, flags, lead_sheet  # noqa: E402


def load(a: Path, name: str, key: str = 'cells') -> list:
    p = a / name
    return json.loads(p.read_text()).get(key, []) if p.exists() else []


def questions(S: dict, a: Path) -> list[dict]:
    """One dict per open cell: bar, cell, section, chart, lv, triads, bass, parallel, options."""
    lv = {(c['bar'], c['cell']): c for c in load(a, 'chords_lv.json')}
    tri = {(c['bar'], c['cell']): c for c in load(a, 'chord_proposal.json')}
    bass = {(c['bar'], c['cell']): c['pc_seconds'] for c in load(a, 'bass_per_cell.json')}
    stops = {b for b, k, v in load(a, 'band_level.json') if v < STOP}
    verified = {tuple(k) for k in S.get('verified', [])}
    open_ = sorted(k for k in flags(S, lv, tri, bass) if k not in verified and k[0] not in stops)
    sec = {b: (n, b0) for n, b0, b1, *_ in S['sections'] for b in range(b0, b1 + 1)}
    kinds = {}
    for n, b0, b1, kind, *_ in S['sections']:
        kinds.setdefault(kind, []).append((n, b0, b1))
    out = []
    for key in open_:
        name, b0 = sec.get(key[0], ('?', key[0]))
        kind = next((k for n, s0, s1, k, *_ in S['sections'] if s0 <= key[0] <= s1), None)
        b1 = next(s1 for n, s0, s1, *_ in S['sections'] if s0 == b0)
        par = []                         # same length: count from the start; else from the end
        for n, p0, p1 in kinds.get(kind, []):  # (turnarounds close a section)
            if p0 == b0:
                continue
            pb = p0 + key[0] - b0 if p1 - p0 == b1 - b0 else p1 - (b1 - key[0])
            if p0 <= pb <= p1:
                par.append(S['chords'].get((pb, key[1])))
        pcs = bass.get(key) or {}
        top = max(pcs, key=pcs.get) if pcs and max(pcs.values()) >= 0.15 else None
        chart = S['chords'][key]
        heard = [lead_sheet(x) for x in (lv.get(key, {}).get('chord'), tri.get(key, {}).get('chord'))
                 if x and x != 'N']
        opts = list(dict.fromkeys([chart] + heard + [p for p in par if p]))
        out.append(dict(bar=key[0], cell=key[1], section=name, chart=chart,
                        lv=lv.get(key, {}).get('chord'), triads=tri.get(key, {}).get('chord'),
                        bass=top, parallel=sorted({p for p in par if p}), options=opts[:4]))
    return out


def pattern_breaks(S: dict, agree: float = 0.65, repeats: int = 3) -> list[dict]:
    """Cells that break their section's repeating pattern: the shortest period (1, 2 or 4
    bars) at which at least `agree` of the section's cells match their position's usual
    chord, seen at least `repeats` times; a cell counts only when the usual chord comes at
    its position both before and after it in the section (a break inside the pattern - a
    turnaround or a different first cycle closes or opens it and is not asked about). A reader can
    agree with itself and still break the pattern (a verse played F# F# A B every time but
    charted A on one B bar - the player heard B)."""
    verified = {tuple(k) for k in S.get('verified', [])}
    ch = S['chords']
    out = []
    for name, b0, b1, *_ in S['sections']:
        bars = list(range(b0, b1 + 1))
        keys = [k for k in sorted(ch) if b0 <= k[0] <= b1 and ch[k] != 'N.C.']
        for per in (1, 2, 4):
            if len(bars) < per * repeats:
                break
            pos = {}
            for k in keys:
                pos.setdefault(((k[0] - b0) % per, k[1]), []).append(k)
            usual = {q: max(set(ch[k] for k in ks), key=[ch[k] for k in ks].count)
                     for q, ks in pos.items()}
            hits = sum(ch[k] == usual[((k[0] - b0) % per, k[1])] for k in keys)
            if keys and hits / len(keys) >= agree:
                for q, ks in pos.items():
                    same = [k for k in ks if ch[k] == usual[q]]
                    if len(same) < repeats:
                        continue
                    out += [dict(bar=k[0], cell=k[1], section=name, chart=ch[k],
                                 usual=usual[q], like=[s[0] for s in same][:4])
                            for i, k in enumerate(ks) if ch[k] != usual[q] and k not in verified
                            and any(ch[x] == usual[q] for x in ks[:i])      # the usual chord
                            and any(ch[x] == usual[q] for x in ks[i + 1:])]  # on both sides
                break
    return sorted(out, key=lambda x: (x['bar'], x['cell']))


def weak_lines(a: Path, share: float = 0.5) -> list[dict]:
    """Lines Whisper heard less than `share` of (lyrics_aligned.json 'matched'): their words
    are placed by misheard stand-ins or guesses - ask the player where they fall (a bridge
    heard as 'snow jesus baby' came out one to two beats early, line after line)."""
    p = a / 'lyrics_aligned.json'
    lines = json.loads(p.read_text()).get('lines', []) if p.exists() else []
    return [dict(where=l.get('where'), matched=l.get('matched'),
                 start=' '.join(l['text'].split()[:3]))
            for l in lines if (l.get('matched') or 0) < share]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('data', help='the chart data file, e.g. gen_v1.py')
    ap.add_argument('--json', help='also write the questions here')
    ap.add_argument('--max', type=int, default=12)
    a = ap.parse_args()
    S = runpy.run_path(a.data)['SONG']
    folder = Path(S.get('folder') or Path(a.data).resolve().parent)
    qs = questions(S, folder / 'analysis')
    if not qs:
        print('no open chord calls: every "?" is verified or in a stop bar')
    for q in qs[:a.max]:
        half = 'first' if q['cell'] == 1 else 'second'
        par = f", parallel section: {'/'.join(q['parallel'])}" if q['parallel'] else ''
        print(f"bar {q['bar']} ({half} half, {q['section']}): chart {q['chart']}; lv-chordia "
              f"{q['lv']}, triads {q['triads']}, bass {q['bass'] or 'none'}{par} -> "
              f"ask: {' / '.join(q['options'])}?")
    if len(qs) > a.max:
        print(f'... {len(qs) - a.max} more (--max)')
    for b in pattern_breaks(S):
        half = 'first' if b['cell'] == 1 else 'second'
        print(f"pattern break: bar {b['bar']} ({half} half, {b['section']}): chart {b['chart']}, "
              f"but the section plays {b['usual']} there every other time (bars "
              f"{', '.join(map(str, b['like']))}) -> ask: {b['chart']} / {b['usual']}?")
    weak = weak_lines(folder / 'analysis')
    for w in weak:
        at = 'bar %d.%d' % tuple(w['where']) if w['where'] else 'unplaced'
        print(f"placement check: the line starting '{w['start']}…' ({at}) - Whisper heard "
              f"{w['matched']:.0%} of its words; ask where each word falls")
    if a.json:
        Path(a.json).write_text(json.dumps(qs, indent=1))


if __name__ == '__main__':
    main()
