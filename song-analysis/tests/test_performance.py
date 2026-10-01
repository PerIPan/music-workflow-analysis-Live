#!/usr/bin/env python3
"""Test the performance readers on synthetic data (no audio, no ADTOF).

strum_pattern.py: 16ths per bar by meter (4/4 16, 6/8 12, 11/8 22); an onset snaps to its
bar-relative 16th through the downbeats (tempo drift doesn't smear it); one a hair before
the next downbeat counts as that bar's step 0; weak onsets are ignored; a section's pattern
is the steps hit in half its bars, strokes D on 8ths and U between; plan.json sections.
drum_transcribe.py: velocities per class (a ghost snare stays quiet next to a backbeat);
fill bars = a tom, or twice the median hits in the last beat.
Run: <analysis venv>/bin/python song-analysis/tests/test_performance.py   (numpy)
"""
import json, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'scripts'))
import numpy as np  # noqa: E402
from strum_pattern import grid, sections_of, steps_per_bar, summarise  # noqa: E402
from drum_transcribe import fills, velocities  # noqa: E402

fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))


check('steps per bar: 4/4 16, 6/8 12, 11/8 22',
      [steps_per_bar(dict(beats_per_bar=b, pulse_unit=u)) for b, u in ((4, 4), (6, 8), (11, 8))]
      == [16, 12, 22])
db = [0.0, 2.0, 4.2, 6.2]                                  # bar 2 is 10% longer
t = np.array([0.0, 0.5, 1.0 + 0.01, 2.0 + 0.75 * 2.2, 4.19, 1.25])
s = np.array([0.9, 0.5, 0.7, 0.8, 0.6, 0.05])
bars = grid(t, s, db, 16)
check('onsets snap to bar-relative 16ths (bar 2 drifts, step 12 still 12)',
      [k for k, x in enumerate(bars[0]) if x] == [0, 4, 8] and
      [k for k, x in enumerate(bars[1]) if x] == [12], bars[:2])
check('an onset a hair before the next downbeat is that bar\'s step 0; weak ones ignored',
      bars[2][0] == 0.6 and bars[0][10] == 0)
sm = summarise([[1, 0, 1, 1] + [0] * 12, [1, 0, 1, 0] + [0] * 12, [1, 0, 0, 1] + [0] * 12], 0.5)
check("a section's pattern: steps hit in at least half its bars; D on 8ths, U between",
      sm['pattern'][:4] == [1, 0, 1, 1] and sm['strokes'][:4] == 'D.DU' and
      sm['share'][:4] == [1.0, 0.0, 0.67, 0.67], sm)
tmp = Path(tempfile.mkdtemp())
(tmp / 'plan.json').write_text(json.dumps({'sections': [
    {'name': 'Verse', 'first_bar': 1, 'last_bar': 8}, {'name': 'Chorus', 'first_bar': 9,
                                                       'last_bar': 20}]}))
(tmp / 'sections.json').write_text(json.dumps({'sections': [
    {'label': 'V', 'where': [3, 1]}, {'label': 'C', 'where': [9, 1]}]}))
check('sections from a remix plan (clipped to the song) or sections.json (+ an Intro)',
      [(x['name'], x['first_bar'], x['last_bar']) for x in sections_of(str(tmp / 'plan.json'), 16)]
      == [('Verse', 1, 8), ('Chorus', 9, 16)] and
      [(x['name'], x['first_bar'], x['last_bar'])
       for x in sections_of(str(tmp / 'sections.json'), 16)]
      == [('Intro', 1, 2), ('V', 3, 8), ('C', 9, 16)])

v = velocities([-10, -10, -30, -12, -40], [38, 38, 38, 36, 36])
check('velocities per class: the loud snares ~120, a ghost snare 20 dB down quiet, kicks '
      'scaled on their own', v[0] == v[1] >= 115 and v[2] < 70 and v[3] >= 115, v)
hits = [dict(t=x, pitch=36) for x in (0.0, 2.0, 4.0, 6.0)] + \
    [dict(t=1.6, pitch=38), dict(t=3.6, pitch=38), dict(t=5.6, pitch=38)] + \
    [dict(t=7.5 + 0.1 * k, pitch=38) for k in range(5)] + [dict(t=3.7, pitch=45)]
check('fill bars: a tom (bar 2), twice the median hits in the last beat (bar 4)',
      fills(hits, [0.0, 2.0, 4.0, 6.0, 8.0], 4) == [2, 4], fills(hits, [0, 2, 4, 6, 8], 4))
sys.exit(1 if fails else 0)
