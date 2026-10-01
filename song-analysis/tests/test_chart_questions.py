#!/usr/bin/env python3
"""Test chart_questions.py on a synthetic chart (no audio).

A cell whose reader names another root is asked about, with the chart's chord first among
the options, what lv-chordia, the triads and the bass heard, and the parallel section's
chord - counted from the end when the parallel section is longer (a turnaround); verified
cells and stop bars are not asked; with nothing open it says so.
Run: python3 song-analysis/tests/test_chart_questions.py   (standard library only)
"""
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from chart_questions import questions  # noqa: E402

fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))


d = Path(tempfile.mkdtemp())
a = d / 'analysis'
a.mkdir()
chords = {(b, c): 'Am' for b in range(1, 15) for c in (1, 2)}
chords[(4, 2)] = chords[(14, 2)] = 'F#m7'                  # the turnarounds
lv = [dict(bar=b, cell=c, chord='A:min', coverage=1) for b, c in chords]
for x in lv:
    if (x['bar'], x['cell']) in ((4, 2), (2, 1), (3, 1), (12, 1)):
        x['chord'] = 'E:min/2' if x['bar'] == 4 else 'C:maj'
    if (x['bar'], x['cell']) == (14, 2):
        x['chord'] = 'F#:min7'                             # chorus 2's turnaround: agreed
(a / 'chords_lv.json').write_text(json.dumps({'cells': lv}))
(a / 'chord_proposal.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=c, chord='F#m' if (b, c) == (14, 2) else 'Am') for b, c in chords]}))
(a / 'bass_per_cell.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=c, pc_seconds={'F#': 0.4} if (b, c) in ((4, 2), (14, 2)) else {'A': 0.4})
    for b, c in chords]}))
(a / 'band_level.json').write_text(json.dumps({'cells': [[b, c, 0.05 if b == 12 else 1.0]
                                                         for b, c in chords]}))
S = dict(chords=chords, verified=[(3, 1)],
         sections=[('Chorus 1', 1, 4, 'chorus', ''), ('Verse', 5, 8, 'verse', ''),
                   ('Chorus 2', 9, 14, 'chorus', '')])
Q = questions(S, a)
got = {(q['bar'], q['cell']): q for q in Q}
check('asked: the cells a reader disputes; not the verified one, not the stop bar',
      sorted(got) == [(2, 1), (4, 2)], sorted(got))
q = got.get((4, 2), {})
check("a question carries the chart's chord first, the readers' and the bass",
      q.get('options', [None])[0] == 'F#m7' and 'Em/F#' in q.get('options', []) and
      q.get('bass') == 'F#', q)
check('the parallel section counted from its end when it is longer (turnaround 4 <-> 14)',
      q.get('parallel') == ['F#m7'], q.get('parallel'))
S['verified'] += [(2, 1), (4, 2)]
check('nothing open: no questions', questions(S, a) == [])
from chart_questions import weak_lines  # noqa: E402
(a / 'lyrics_aligned.json').write_text(json.dumps({'lines': [
    dict(text='heard every word here', matched=1.0, where=[1, 1]),
    dict(text='slow jazz is playing', matched=0.25, where=[3, 2])]}))
W = weak_lines(a)
check('a line Whisper heard under half of is a placement question (first words, where)',
      W == [dict(where=[3, 2], matched=0.25, start='slow jazz is')], W)
sys.exit(1 if fails else 0)
