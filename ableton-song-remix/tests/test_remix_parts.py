#!/usr/bin/env python3
"""Test scripts/remix_parts.py on synthetic plans (no files, no Live).

Every preset in every meter (4/4, 3/4, 5/4, 6/8, 7/8, 12/8, 11/8 as 6+5) at tiers 1-3 with
fills: the drum part passes the playability check, notes stay inside the song, backbeat
kicks sit on the unit starts (11/8 -> beats 0 and 3.0 of the bar), the bass plays the
chord's bass (or the hint) at each chord, keys hold the 3rd and 7th. The checker refuses 3
hands at once, a 32nd roll, crash + hat, two hat voices, one-handed 16ths at 150 BPM, a
tom hit 3 times running and 3 kicks in a row. Swing never moves a pulse in 7/8 or 11/8;
16th hats fall back to 8ths above 130 BPM; the same seed gives the same notes. The
half-time snare sits on beat 3 in 4/4 whatever the chart's cells; tactus_root notes never
overlap; section downbeats are never humanized; parts carry the plan's fingerprint.
Run: python3 tests/test_remix_parts.py   (standard library only)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from chordsym import parse  # noqa: E402
from remix_parts import (PRESETS, drum_bar, make_parts, meter, plan_key,  # noqa: E402
                         validate_drums, voicing)

METERS = {'4/4': ([2, 2], 4), '3/4': ([3], 4), '5/4': ([3, 2], 4), '6/8': ([3, 3], 8),
          '7/8': ([2, 2, 3], 8), '12/8': ([3, 3, 3, 3], 8), '11/8': ([6, 5], 8)}
LOOP = ['Cmaj7', 'F#m7', 'Em/D', 'D/F#', 'G7', 'Am7b5', 'N.C.', 'Bb']


def synth_plan(grouping, unit, tempo=112.0, nbars=16, tier=None, preroll=0, preset='house'):
    bb = sum(grouping) * 4 / unit
    cb = [x * 4 / unit for x in grouping]
    chords = []
    for b in range(1, nbars + 1):
        for c in range(1, len(grouping) + 1):
            lab = LOOP[(b * len(grouping) + c) % len(LOOP)]
            p = parse(lab)
            chords.append(dict(bar=b, cell=c, label=lab, beats=cb[c - 1],
                               start_beat=(b - 1 + preroll) * bb + sum(cb[:c - 1]),
                               root=p and p['root'], pcs=p['pcs'] if p else [],
                               intervals=p['intervals'] if p else [], bass=p and p['bass']))
    tiers = tier or [1, 1, 2, 2] + [3] * (nbars - 4)
    secs = [dict(name='A', kind='verse', first_bar=1, last_bar=nbars // 2),
            dict(name='B', kind='chorus', first_bar=nbars // 2 + 1, last_bar=nbars)]
    for s in secs:
        s['start_beat'] = (s['first_bar'] - 1 + preroll) * bb
        s['end_beat'] = (s['last_bar'] + preroll) * bb
    return dict(preset=preset, seed=7, mode='remix', parts=['drums', 'bass', 'keys'],
                grid=dict(grouping=grouping, pulse_unit=unit, bar_beats=bb, cell_beats=cb,
                          time_signature=f'{sum(grouping)}/{unit}', preroll_bars=preroll,
                          chart_bars=nbars, total_bars=nbars + preroll,
                          total_beats=(nbars + preroll) * bb),
                tempo=dict(live=tempo), sections=secs, chords=chords,
                bass_hints=[dict(bar=6, cell=1, pc=9)],
                energy={p: tiers for p in ('drums', 'bass', 'keys')},
                bass_line=[dict(pitch=36, start_time=preroll * bb + 0.0, duration=1.0,
                                velocity=90)])


def main():
    fails = 0
    def check(name, cond, info=''):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))

    # every preset x meter
    for m, (grp, unit) in METERS.items():
        for pre in PRESETS:
            for tempo in (84.0, 150.0):
                plan = synth_plan(grp, unit, tempo, preset=pre)
                try:
                    res = make_parts(plan, sets=['fills=4'])
                    ok, info = True, ''
                except ValueError as e:
                    ok, info = False, str(e)
                bad = []
                if ok:
                    end = plan['grid']['total_beats']
                    bad = [n for ns in res['parts'].values() for n in ns
                           if n['start_time'] < 0 or n['start_time'] + n['duration'] > end + 1e-6]
                check(f'{m} {pre} {tempo:g} BPM: playable, inside the song',
                      ok and not bad, info or bad[:2])

    # kicks on unit starts
    for m, want in (('11/8', [0.0, 3.0]), ('4/4', [0.0, 2.0]), ('7/8', [0.0]),
                    ('5/4', [0.0, 3.0]), ('12/8', [0.0, 3.0])):
        grp, unit = METERS[m]
        plan = synth_plan(grp, unit, preset='synth-pop')
        res = make_parts(plan, sets=['swing=0.5', 'humanize_ms=0', 'fills=0', 'crash=0'])
        bb = plan['grid']['bar_beats']
        k = sorted({round(n['start_time'] - 8 * bb, 4) for n in res['parts']['drums']
                    if n['pitch'] == 36 and 8 * bb <= n['start_time'] < 9 * bb})
        check(f'{m} backbeat kicks at {want}', k == want, k)
    grp, unit = METERS['11/8']
    plan = synth_plan(grp, unit, preset='synth-pop')
    res = make_parts(plan, sets=['swing=0.5', 'humanize_ms=0', 'fills=0', 'crash=0'])
    sn = sorted({round(n['start_time'] - 8 * 5.5, 4) for n in res['parts']['drums']
                 if n['pitch'] == 38 and 44 <= n['start_time'] < 49.5})
    check('11/8 snares on eighths 4 and 10 (beats 1.5, 4.5)', sn == [1.5, 4.5], sn)

    # bass at chord onsets; keys 3rd + 7th
    plan = synth_plan([2, 2], 4, preset='synth-pop')
    res = make_parts(plan, sets=['humanize_ms=0'])
    bass = res['parts']['bass']
    hint = {(h['bar'], h['cell']): h['pc'] for h in plan['bass_hints']}
    wrong = []
    for c in plan['chords']:
        if c['root'] is None or plan['energy']['bass'][c['bar'] - 1] == 0:
            continue
        at = [n for n in bass if abs(n['start_time'] - c['start_beat']) < 1e-6]
        want = hint.get((c['bar'], c['cell']), c['bass'])
        if at and at[0]['pitch'] % 12 != want:
            wrong.append((c['bar'], c['cell'], c['label'], at[0]['pitch']))
    check('bass plays the chord bass (slash note, hint) at chord onsets', not wrong, wrong[:4])
    check('bass in E1-G2 except octave jumps', all(28 <= n['pitch'] <= 55 for n in bass))
    miss = []
    prev = None
    for lab in LOOP:
        p = parse(lab)
        if not p:
            continue
        v = voicing(p['intervals'], p['root'], prev, 'close')
        prev = v
        pcs = {x % 12 for x in v}
        if p['third'] is not None and p['third'] not in pcs or \
                p['seventh'] is not None and p['seventh'] not in pcs or \
                not all(52 <= x <= 76 for x in v):
            miss.append((lab, v))
    check('keys voicings hold the 3rd and 7th, in E3-E5', not miss, miss)

    # the playability checker refuses
    n = lambda p, t, v=90: dict(pitch=p, start_time=t, duration=0.1, velocity=v, mute=False)
    cases = {
        '3 hand hits at once': [n(38, 0), n(42, 0), n(50, 0)],
        '32nd roll at 120': [n(38, i * 0.125) for i in range(8)],
        'crash with hat': [n(49, 0), n(42, 0)],
        'two hat voices': [n(42, 0), n(46, 0)],
        'one-handed 16ths at 150': [n(42, i * 0.25) for i in range(16)] +
                                   [n(38, 1.0), n(38, 3.0)],
        'same tom 3 times running': [n(50, 0), n(50, 0.25), n(50, 0.5)],
        '3 kicks in a row on 16ths': [n(36, 0), n(36, 0.25), n(36, 0.5)],
    }
    for name, notes in cases.items():
        tempo = 150 if '150' in name else 120
        check(f'checker refuses: {name}', validate_drums(notes, tempo) != [])
    check('checker accepts 16th hats + backbeat at 120',
          validate_drums([n(42, i * 0.25) for i in range(16)] + [n(38, 1.0), n(38, 3.0)] +
                         [n(36, 0), n(36, 2)], 120) == [])
    check('checker accepts a flam grace note',
          validate_drums([n(38, 0.97, 40), n(38, 1.0)], 120) == [])

    # swing keeps pulses; hats above 130; determinism
    for m in ('7/8', '11/8'):
        grp, unit = METERS[m]
        plan = synth_plan(grp, unit, preset='lo-fi')
        straight = make_parts(plan, sets=['swing=0.5', 'humanize_ms=0'])['parts']['drums']
        swung = make_parts(plan, sets=['swing=0.62', 'humanize_ms=0'])['parts']['drums']
        on_pulse = lambda ns: sorted(round(x['start_time'], 4) for x in ns
                                     if abs(x['start_time'] * 2 - round(x['start_time'] * 2)) < 1e-6)
        check(f'{m}: swing never moves a pulse', on_pulse(straight) == on_pulse(swung) and
              straight != swung)
    plan = synth_plan([2, 2], 4, tempo=140.0, preset='house')
    hats = [x for x in make_parts(plan, sets=['humanize_ms=0', 'swing=0.5'])['parts']['drums']
            if x['pitch'] == 42]
    check('house 16th hats -> 8ths above 130 BPM',
          hats and all(abs(x['start_time'] * 2 - round(x['start_time'] * 2)) < 1e-6 for x in hats))
    plan = synth_plan([6, 5], 8, preset='lo-fi')
    a, b = make_parts(plan), make_parts(plan)
    c = make_parts(plan, seed=8)
    check('same seed, same notes; another seed differs', a['parts'] == b['parts'] and
          a['parts'] != c['parts'])
    tac, units = meter([6, 5], 8)
    check('11/8 tactus 3+3 | 3+2 eighths', [t[1] for t in tac] == [1.5, 1.5, 1.5, 1.0] and
          units == [[0, 1], [2, 3]], (tac, units))
    # half-time snare on beat 3 in 4/4, whatever cells the chart uses; 6/8 on eighth 4
    for grp, unit, want in (([2, 2], 4, 2.0), ([4], 4, 2.0), ([1, 1, 1, 1], 4, 2.0),
                            ([6], 8, 1.5), ([6, 5], 8, 3.0)):
        tac, units = meter(grp, unit)
        bar = drum_bar(dict(kick='sparse', snare='half', hats='8'), 0.0, sum(grp) * 4 / unit,
                       tac, units, 100.0, grp, unit, False)
        sn = [n['start_time'] for n in bar if n['pitch'] == 38]
        check(f'half-time snare, grouping {grp}/{unit}: at beat {want}', sn == [want], sn)

    # tactus_root: one note per tactus beat, none overlapping the next
    for grp, unit in (([2, 2], 4), ([6, 5], 8), ([3, 3], 8)):
        plan = synth_plan(grp, unit, preset='house')
        ns = make_parts(plan, sets=['bass.pattern=tactus_root', 'humanize_ms=0',
                                    'swing=0.5'])['parts']['bass']
        ov = [(a['start_time'], b['start_time']) for a, b in zip(ns, ns[1:])
              if a['start_time'] + a['duration'] > b['start_time'] + 1e-6]
        check(f'tactus_root {sum(grp)}/{unit}: no overlapping notes', ns and not ov, ov[:3])

    # section downbeats stay on the grid (the section clip starts with them)
    for pre in ('lo-fi', 'garage-punk', 'synth-pop'):
        plan = synth_plan([2, 2], 4, preset=pre, preroll=1)
        res = make_parts(plan, sets=['fills=0'])
        off = [(p, n['pitch'], n['start_time']) for p, ns in res['parts'].items() for n in ns
               for sec in plan['sections']
               if 0 < abs(n['start_time'] - sec['start_beat']) < 0.1]
        on = sum(abs(n['start_time'] - sec['start_beat']) < 1e-9
                 for ns in res['parts'].values() for n in ns for sec in plan['sections'])
        check(f'{pre}: section downbeats not humanized', on and not off, off[:4])
    plan = synth_plan([2, 2], 4)
    other = synth_plan([2, 2], 4, preroll=1)
    check('parts carry the plan fingerprint; another plan, another key',
          make_parts(plan)['plan_key'] == plan_key(plan) != plan_key(other))
    try:
        make_parts(synth_plan([2, 2], 4), sets=['drums.kick=twice'])
        check('--set refuses an unknown option', False)
    except ValueError:
        check('--set refuses an unknown option', True)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
