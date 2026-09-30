#!/usr/bin/env python3
"""Remix plan + style preset -> new drums, bass and keys as Live notes (parts.json).

Why: the new parts must follow the analysed chords per (bar, cell) and keep the song's
meter. A meter engine builds every pattern from the grouping, not from 4/4 templates: an
11/8 bar grouped 6+5 is felt as beats of 3+3 | 3+2 eighths, kick on eighths 1 and 7, snare
on 4 and 10. Every drum part must pass a drummer-playability check (at most 2 hands and
one hit per foot per onset, one hi-hat voice, a crash replaces the hat, each hand no
faster than 16ths - 8ths above 130 BPM, no 32nds, at most 2 kicks in a row on 16ths, no
tom hit 3 times running) or the script exits 1 naming the bar and rule.

Notes are Live beats from Live bar 1 (pre-roll included), the add_notes_to_clip format.
Swing moves only the subdivision under the pulse, so it never bends an odd-meter group.
parts.json carries the plan's fingerprint (plan_key): re-run this after any re-run of the
plan, or remix_build refuses the stale parts.

Usage (python3, standard library only):
    remix_parts.py PLAN [--preset house] [--set drums.kick=four] [--set swing=0.55]
        [--seed N] [--out PARTS]                      # default: parts.json beside PLAN
--set keys: drums.kick (four|backbeat|sparse), drums.snare (backbeat|clap|half|none),
drums.hats (8|16|tactus|offbeat|offbeat+16|ride8), bass.pattern (root_hold|tactus_root|
drive8|offbeat8|octave8|lofi|as-analysed), keys.rhythm (pad|block|stab_off|arp8|comp),
keys.voicing (close|rootless|power), swing, humanize_ms, fills (0, -1 section ends, N
bars), crash (0/1), ghosts (0/1), kick_run. A drums/bass/keys key applies to every tier.
"""
from __future__ import annotations

import argparse, copy, hashlib, json, math, random, sys
from pathlib import Path

KICK, SNARE, CLAP, CH, OH, CRASH, RIDE = 36, 38, 39, 42, 46, 49, 51
TOMS_FILL = (38, 50, 47, 43)                              # snare, hi, mid, low tom
HAND_FREE = {35, 36, 44}                                  # feet
CYMBALS = {42, 46, 49, 51, 52, 53, 55, 57, 59}
HATS = {42, 44, 46}
CRASHES = {49, 52, 55, 57}
TOMS = {41, 43, 45, 47, 48, 50}

PRESETS = {
    'house': dict(
        swing=0.54, humanize_ms=2, fills=0, crash=1, ghosts=0, kick_run=2,
        drums={1: dict(kick='four', snare='none', hats='offbeat'),
               2: dict(kick='four', snare='clap', hats='offbeat+16'),
               3: dict(kick='four', snare='clap', hats='offbeat+16')},
        bass={1: 'root_hold', 2: 'offbeat8', 3: 'offbeat8'},
        keys={1: 'pad', 2: 'stab_off', 3: 'stab_off'}, voicing='close',
        search=dict(drums=['909 Core Kit', '909', 'Kit'], bass=['Sub Bass', 'Bass'],
                    keys=['Stab', 'Electric Piano', 'Piano'])),
    'synth-pop': dict(
        swing=0.5, humanize_ms=3, fills=-1, crash=1, ghosts=0, kick_run=2,
        drums={1: dict(kick='backbeat', snare='none', hats='8'),
               2: dict(kick='backbeat', snare='backbeat', hats='8'),
               3: dict(kick='backbeat', snare='backbeat', hats='16')},
        bass={1: 'root_hold', 2: 'drive8', 3: 'octave8'},
        keys={1: 'pad', 2: 'pad', 3: 'arp8'}, voicing='close',
        search=dict(drums=['808 Core Kit', '808', 'Kit'], bass=['Synth Bass', 'Bass'],
                    keys=['Pad', 'Synth', 'Piano'])),
    'lo-fi': dict(
        swing=0.58, humanize_ms=12, fills=0, crash=0, ghosts=1, kick_run=2,
        drums={1: dict(kick='sparse', snare='half', hats='8'),
               2: dict(kick='backbeat', snare='backbeat', hats='8'),
               3: dict(kick='backbeat', snare='backbeat', hats='8')},
        bass={1: 'root_hold', 2: 'lofi', 3: 'lofi'},
        keys={1: 'pad', 2: 'comp', 3: 'comp'}, voicing='rootless',
        search=dict(drums=['Kit'], bass=['Bass'], keys=['Electric Piano', 'Piano'])),
    'garage-punk': dict(
        swing=0.5, humanize_ms=6, fills=8, crash=1, ghosts=0, kick_run=3,
        drums={1: dict(kick='backbeat', snare='backbeat', hats='8'),
               2: dict(kick='backbeat', snare='backbeat', hats='8'),
               3: dict(kick='backbeat', snare='backbeat', hats='ride8')},
        bass={1: 'root_hold', 2: 'drive8', 3: 'drive8'},
        keys={1: 'block', 2: 'block', 3: 'block'}, voicing='power',
        search=dict(drums=['Kit'], bass=['Bass'], keys=['Guitar', 'Organ'])),
    'as-analysed': dict(
        swing=0.5, humanize_ms=0, fills=0, crash=0, ghosts=0, kick_run=2,
        drums={1: dict(kick='sparse', snare='none', hats='tactus'),
               2: dict(kick='backbeat', snare='backbeat', hats='8'),
               3: dict(kick='backbeat', snare='backbeat', hats='8')},
        bass={1: 'as-analysed', 2: 'as-analysed', 3: 'as-analysed'},
        keys={1: 'block', 2: 'block', 3: 'block'}, voicing='close',
        search=dict(drums=['Kit'], bass=['Bass'], keys=['Piano'])),
}
OPTIONS = {'drums.kick': ('four', 'backbeat', 'sparse'),
           'drums.snare': ('backbeat', 'clap', 'half', 'none'),
           'drums.hats': ('8', '16', 'tactus', 'offbeat', 'offbeat+16', 'ride8'),
           'bass.pattern': ('root_hold', 'tactus_root', 'drive8', 'offbeat8', 'octave8',
                            'lofi', 'as-analysed'),
           'keys.rhythm': ('pad', 'block', 'stab_off', 'arp8', 'comp'),
           'keys.voicing': ('close', 'rootless', 'power')}
SCALARS = {'swing': float, 'humanize_ms': float, 'fills': int, 'crash': int, 'ghosts': int,
           'kick_run': int}
SPLIT23 = {1: [1], 2: [2], 3: [3], 4: [2, 2], 5: [3, 2], 6: [3, 3], 7: [2, 2, 3],
           8: [3, 3, 2], 9: [3, 3, 3]}
EPS = 1e-6


def split23(n: int) -> list[int]:
    """Split n pulses (or tactus beats) into groups of 2 and 3, as players count them."""
    if n in SPLIT23:
        return SPLIT23[n]
    return [3] * (n // 3 - (n % 3 == 1)) + ([2, 2] if n % 3 == 1 else [2] * (n % 3 // 2))


def meter(grouping: list[int], pulse_unit: int) -> tuple[list[tuple], list[list[int]]]:
    """Tactus beats [(offset, length, group)] in Live beats, and units (lists of tactus
    indices) for backbeat placement: kick on a unit's first beat, snare on its last."""
    pb = 4 / pulse_unit
    tactus, pos = [], 0
    for gi, g in enumerate(grouping):
        for p in ([1] * g if pulse_unit == 4 else split23(g)):
            tactus.append((pos * pb, p * pb, gi))
            pos += p
    per_group = [[i for i, t in enumerate(tactus) if t[2] == gi] for gi in range(len(grouping))]
    units = []
    if all(len(x) == 1 for x in per_group):
        i = 0
        for u in split23(len(tactus)):
            units.append(list(range(i, i + u)))
            i += u
    else:
        for idx in per_group:
            i = 0
            for u in split23(len(idx)):
                units.append(idx[i:i + u])
                i += u
    return tactus, units


def note(pitch: int, t: float, dur: float, vel: int) -> dict:
    return dict(pitch=int(pitch), start_time=round(t, 6), duration=round(max(dur, 0.05), 6),
                velocity=int(max(1, min(127, vel))), mute=False)


# ---------------------------------------------------------------- drums

def drum_bar(cfg: dict, t0: float, bar_beats: float, tactus: list, units: list,
             tempo: float, grouping: list, pulse_unit: int, ghosts: bool) -> list[dict]:
    out = []
    starts = [t0 + tactus[u[0]][0] for u in units]
    ends = [t0 + tactus[u[-1]][0] for u in units if len(u) > 1]
    k = cfg['kick']
    kt = ([t0 + x[0] for x in tactus] if k == 'four' else starts if k == 'backbeat'
          else [t0])
    out += [note(KICK, t, 0.25, 115 if abs(t - t0) < EPS else 105) for t in kt]
    s = cfg['snare']
    if s in ('backbeat', 'clap'):
        out += [note(CLAP if s == 'clap' else SNARE, t, 0.25, 104) for t in ends]
    elif s == 'half':                         # the second metric unit's first beat
        g2 = t0 + tactus[units[1][0] if len(units) > 1 else -1][0]
        out.append(note(SNARE, g2, 0.25, 104))
    if ghosts and s in ('backbeat', 'clap') and tempo <= 120:
        out += [note(SNARE, t - 0.25, 0.2, 32) for t in ends if t - 0.25 > t0 + EPS]
    h = cfg['hats']
    sixteen = tempo <= 130
    grid = lambda step: [t0 + i * step for i in range(int(round(bar_beats / step)))]
    mids = [t0 + round((x[0] + x[1] / 2) * 4) / 4 for x in tactus]
    if h == '8':
        out += [note(CH, t, 0.2, 72 if (t - t0) % 1 < EPS else 58) for t in grid(0.5)]
    elif h == '16':
        out += [note(CH, t, 0.15, 70 if (t - t0) % 0.5 < EPS else 50)
                for t in grid(0.25 if sixteen else 0.5)]
    elif h == 'tactus':
        out += [note(CH, t0 + x[0], 0.2, 70) for x in tactus]
    elif h == 'ride8':
        out += [note(RIDE, t, 0.3, 78 if (t - t0) % 1 < EPS else 64) for t in grid(0.5)]
    elif h in ('offbeat', 'offbeat+16'):
        out += [note(OH, t, 0.25, 82) for t in mids]
        if h == 'offbeat+16':
            out += [note(CH, t, 0.12, 48) for t in grid(0.25 if sixteen else 0.5)
                    if all(abs(t - m) > EPS for m in mids)]
    return out


def fill(t_from: float, t_to: float, tempo: float) -> list[dict]:
    """Snare -> high -> mid -> low tom over at most 2 beats, hands alternating R/L."""
    step = 0.25 if tempo <= 130 else 0.5
    t_from = max(t_from, t_to - 2.0)
    n = int(round((t_to - t_from) / step))
    return [note(TOMS_FILL[min(3, i * 4 // max(n, 1))], t_from + i * step, step,
                 104 if i % 2 == 0 else 88) for i in range(n)]


def drums(plan: dict, pre: dict) -> list[dict]:
    g, T = plan['grid'], plan['tempo']['live']
    bb, P = g['bar_beats'], g['preroll_bars']
    tactus, units = meter(g['grouping'], g['pulse_unit'])
    tier = plan['energy']['drums']
    first = {s['first_bar'] for s in plan['sections']}
    last_of = {s['last_bar']: s for s in plan['sections']}
    sec_of = {b: s for s in plan['sections'] for b in range(s['first_bar'], s['last_bar'] + 1)}
    out, crash_at = [], set()
    for b in range(1, g['chart_bars'] + 1):
        t = tier[b - 1]
        if t == 0:
            continue
        t0 = (b - 1 + P) * bb
        bar = drum_bar(pre['drums'][t], t0, bb, tactus, units, T, g['grouping'],
                       g['pulse_unit'], bool(pre['ghosts']) and t == 3)
        if t >= 2 and (pre['crash'] and b in first and b > 1 or b in crash_at):
            bar = [n for n in bar if n['pitch'] not in (CH, OH, RIDE)
                   or abs(n['start_time'] - t0) > EPS]
            bar.append(note(CRASH, t0, 1.0, 100))
            if not any(n['pitch'] == KICK and abs(n['start_time'] - t0) < EPS for n in bar):
                bar.append(note(KICK, t0, 0.25, 112))
        f = pre['fills']
        in_sec = b - sec_of[b]['first_bar'] + 1
        if f and t >= 2 and b < g['chart_bars'] and (b in last_of or f > 0 and in_sec % f == 0):
            u0 = t0 + tactus[units[-1][0]][0]
            fs = fill(u0, t0 + bb, T)
            lo = fs[0]['start_time'] if fs else t0 + bb
            bar = [n for n in bar if n['start_time'] < lo - EPS or n['pitch'] == KICK and
                   abs(n['start_time'] - lo) < EPS]
            bar += fs
            crash_at.add(b + 1)
        out += bar
    return sorted(out, key=lambda n: (n['start_time'], n['pitch']))


def validate_drums(notes: list[dict], tempo: float, bar_beats: float = 4.0, preroll: int = 0,
                   kick_run: int = 2) -> list[str]:
    """Drummer-playability check on the straight (unswung, unhumanized) grid. Returns the
    violations, each naming the chart bar and the rule; [] = playable."""
    tol = 0.005 * tempo / 60                                # 5 ms in beats
    grace_gap = 0.035 * tempo / 60
    ev = sorted(notes, key=lambda n: n['start_time'])
    groups: list[list] = []
    for n in ev:
        if groups and n['start_time'] - groups[-1][0] <= tol:
            groups[-1][1].append(n)
        else:
            groups.append([n['start_time'], [n]])
    where = lambda t: (f'bar {int((t + EPS) // bar_beats) + 1 - preroll} '
                       f'beat {(t % bar_beats) + 1:g}')
    v, hand_min = [], (0.25 if tempo <= 130 else 0.5)
    last = {'R': -1e9, 'L': -1e9}
    last_any, kicks, hand_seq = -1e9, [], []
    for gi, (t, grp) in enumerate(groups):
        p = [n['pitch'] for n in grp]
        if sum(x in (35, 36) for x in p) > 1 or p.count(44) > 1:
            v.append(f'{where(t)}: one foot plays two hits')
        if sum(x in HATS for x in p) > 1:
            v.append(f'{where(t)}: two hi-hat voices at once')
        if any(x in CRASHES for x in p) and any(x in (42, 46, 51) for x in p):
            v.append(f'{where(t)}: crash with hat or ride (one cymbal hand)')
        hands = [n for n in grp if n['pitch'] not in HAND_FREE]
        if any(x in (35, 36) for x in p):
            kicks.append(t)
        if len(hands) > 2:
            v.append(f'{where(t)}: {len(hands)} hand hits at once')
        nxt = groups[gi + 1][0] if gi + 1 < len(groups) else None
        if hands and all(n['velocity'] <= 60 for n in hands) and nxt is not None \
                and nxt - t <= grace_gap:
            continue                                        # flam grace note
        if hands and t - last_any < 0.25 - tol:
            v.append(f'{where(t)}: hands faster than 16ths (32nds)')
        used: set = set()
        for n in sorted(hands, key=lambda n: n['pitch'] not in CYMBALS):
            pref = 'R' if n['pitch'] in CYMBALS else 'L'
            order = [pref, 'L' if pref == 'R' else 'R']
            free = [h for h in order if h not in used and t - last[h] >= hand_min - tol]
            if not free:
                v.append(f'{where(t)}: a hand faster than '
                         f'{"16ths" if hand_min == 0.25 else "8ths (above 130 BPM)"}')
                free = [h for h in order if h not in used] or order
            used.add(free[0])
            last[free[0]] = t
            hand_seq.append((t, n['pitch']))
        if hands:
            last_any = t
    run = 1
    for a, b in zip(kicks, kicks[1:]):
        if b - a < 0.25 - tol:
            v.append(f'{where(b)}: kicks faster than 16ths')
        run = run + 1 if abs(b - a - 0.25) <= tol else 1
        if run > kick_run:
            v.append(f'{where(b)}: {run} kicks in a row on 16ths')
    run = 1
    for (a, pa), (b, pb) in zip(hand_seq, hand_seq[1:]):
        run = run + 1 if pa == pb and pa in TOMS and b - a <= 0.25 + tol else 1
        if run > 2:
            v.append(f'{where(b)}: the same tom 3 times running')
    return v


# ---------------------------------------------------------------- harmony

def segments(plan: dict) -> list[dict]:
    """Consecutive cells in one bar with the same chord (and bass hint) -> one segment."""
    hint = {(h['bar'], h['cell']): h['pc'] for h in plan['bass_hints']}
    out = []
    for c in plan['chords']:
        key = (c['bar'], c['label'], hint.get((c['bar'], c['cell'])))
        if out and out[-1]['key'] == key:
            out[-1]['end'] = c['start_beat'] + c['beats']
            out[-1]['cells'].append((c['start_beat'], c['beats']))
        else:
            out.append(dict(key=key, bar=c['bar'], chord=c, start=c['start_beat'],
                            end=c['start_beat'] + c['beats'],
                            bass=hint.get((c['bar'], c['cell']), c['bass']),
                            cells=[(c['start_beat'], c['beats'])]))
    return out


def near(pc: int, prev: int, lo: int = 28, hi: int = 43) -> int:
    return min((pc + 12 * k for k in range(12) if lo <= pc + 12 * k <= hi),
               key=lambda m: (abs(m - prev), m))


def grid_in(s: float, e: float, step: float, t0: float) -> list[float]:
    k = math.ceil((s - t0) / step - EPS)
    out = []
    while t0 + k * step < e - EPS:
        out.append(t0 + k * step)
        k += 1
    return out


def bass(plan: dict, pre: dict) -> list[dict]:
    g = plan['grid']
    bb, P = g['bar_beats'], g['preroll_bars']
    tactus, _ = meter(g['grouping'], g['pulse_unit'])
    tier = plan['energy']['bass']
    segs = segments(plan)
    if all(pre['bass'][t] == 'as-analysed' for t in (1, 2, 3)):
        return [note(n['pitch'], n['start_time'], n['duration'], n['velocity'])
                for n in plan['bass_line']]
    out, prev = [], 36
    for i, sg in enumerate(segs):
        t = tier[sg['bar'] - 1]
        if t == 0 or sg['chord']['root'] is None:
            continue
        pat = pre['bass'][t] if pre['bass'][t] != 'as-analysed' else 'root_hold'
        t0 = (sg['bar'] - 1 + P) * bb
        s, e = sg['start'], sg['end']
        r = near(sg['bass'], prev)
        tac_len = [(t0 + x[0], x[1]) for x in tactus if s - EPS <= t0 + x[0] < e - EPS]
        tac = [x for x, _ in tac_len]
        if pat == 'root_hold':
            out.append(note(r, s, e - s, 100))
        elif pat == 'tactus_root':                  # each note inside its own tactus beat
            out += [note(r, x, 0.9 * min(ln, e - x), 100) for x, ln in tac_len or [(s, e - s)]]
        elif pat in ('drive8', 'octave8'):
            for j, x in enumerate(grid_in(s, e, 0.5, t0)):
                up = pat == 'octave8' and j % 2 == 1
                out.append(note(r + 12 if up else r, x, 0.45, 100 if j % 2 == 0 else 90))
        elif pat == 'offbeat8':
            offs = [x for x in grid_in(s, e, 0.5, t0) if all(abs(x - y) > EPS for y in tac)]
            out += [note(r, x, 0.4, 100) for x in (offs or [s])]
        elif pat == 'lofi':
            nxt = segs[i + 1] if i + 1 < len(segs) else None
            last_t = tac[-1] if len(tac) > 1 else None
            if last_t is None:
                out.append(note(r, s, e - s, 96))
            else:
                out.append(note(r, s, last_t - s, 96))
                if nxt and nxt['chord']['root'] is not None and nxt['bass'] != sg['bass']:
                    ap = near((nxt['bass'] - 1) % 12, r)
                else:
                    ap = near((sg['chord']['root'] + 7) % 12, r)
                out.append(note(ap, last_t, e - last_t, 84))
        prev = r
    return out


def voicing(intervals: list[int], root: int, prev: list[int] | None, style: str) -> list[int]:
    """Chord tones in E3-E5 (52-76) with the least movement from the previous voicing,
    pulled toward MIDI 64. Keeps the 3rd and 7th; drops the 5th first."""
    ivs = sorted(set(intervals))
    if style == 'power':
        pcs = [root % 12, (root + 7) % 12]
        cands = [[b, b + 7, b + 12] for b in range(40, 65) if b % 12 == pcs[0]]
        return min(cands, key=lambda v: abs(sum(v) / 3 - 58))
    while len(ivs) > 4 and 7 in ivs:
        ivs.remove(7)
    if style == 'rootless' and len(ivs) >= 4 and 0 in ivs:
        ivs.remove(0)
    while len(ivs) > 4:
        ivs.remove(max(x for x in ivs if x not in (3, 4, 10, 11)))
    pcs = [(root + x) % 12 for x in ivs]
    cands = []
    for r in range(len(pcs)):
        order = pcs[r:] + pcs[:r]
        for base in range(52, 65):
            if base % 12 != order[0]:
                continue
            v = [base]
            for pc in order[1:]:
                m = v[-1] + 1
                while m % 12 != pc:
                    m += 1
                v.append(m)
            if v[-1] <= 76:
                cands.append(v)
    def cost(v: list[int]) -> float:
        c = abs(sum(v) / len(v) - 64) * 0.3
        if prev:
            c += sum(abs(a - b) for a, b in zip(sorted(v), sorted(prev))) \
                if len(v) == len(prev) else abs(sum(v) / len(v) - sum(prev) / len(prev)) * 2
        return c
    return min(cands, key=cost)


def keys(plan: dict, pre: dict) -> list[dict]:
    g = plan['grid']
    bb, P = g['bar_beats'], g['preroll_bars']
    tactus, units = meter(g['grouping'], g['pulse_unit'])
    unit_starts = {u[0] for u in units}
    tier = plan['energy']['keys']
    out, prev = [], None
    for sg in segments(plan):
        t = tier[sg['bar'] - 1]
        ch = sg['chord']
        if t == 0 or ch['root'] is None:
            continue
        v = voicing(ch['intervals'], ch['root'], prev, pre['voicing'])
        prev = v
        rhythm = pre['keys'][t]
        t0 = (sg['bar'] - 1 + P) * bb
        s, e = sg['start'], sg['end']
        tac = [t0 + x[0] for x in tactus if s - EPS <= t0 + x[0] < e - EPS]
        if rhythm == 'pad':
            hits = [(s, e - s, 70)]
        elif rhythm == 'block':
            hits = [(cs, cb, 82) for cs, cb in sg['cells']]
        elif rhythm == 'stab_off':
            offs = [x for x in grid_in(s, e, 0.5, t0) if all(abs(x - y) > EPS for y in tac)]
            hits = [(x, 0.25, 86) for x in (offs or [s])]
        elif rhythm == 'comp':
            cs = [t0 + tactus[i][0] for i in range(len(tactus)) if i not in unit_starts
                  and s - EPS <= t0 + tactus[i][0] < e - EPS]
            hits = [(x, 0.4, 78) for x in (cs or [s])]
        elif rhythm == 'arp8':
            for j, x in enumerate(grid_in(s, e, 0.5, t0)):
                out.append(note(sorted(v)[j % len(v)], x, 0.45, 76))
            continue
        else:
            raise ValueError(f'unknown keys rhythm {rhythm!r}')
        out += [note(m, x, d, vel) for x, d, vel in hits for m in v]
    return out


# ---------------------------------------------------------------- feel

def swing_humanize(notes: list[dict], plan: dict, amount: float, ms: float, seed: int,
                   skip: set) -> list[dict]:
    """MPC-style swing on the subdivision under the pulse only (the pulse grid never
    moves), then seeded timing (+-ms) and velocity (+-8) jitter; landings in skip (crashes,
    section downbeats) stay on the grid, so a section's clip starts with its downbeat."""
    g, T = plan['grid'], plan['tempo']['live']
    pulse = 4 / g['pulse_unit']
    sub = pulse / 2
    rng = random.Random(seed)
    end = g['total_beats']
    out = []
    for n in notes:
        n = dict(n)
        t = n['start_time']
        x = t % pulse                                       # bars hold whole pulses
        if abs(amount - 0.5) > EPS and abs(x - sub) < EPS:
            t += 2 * sub * amount - sub
        if ms and round(n['start_time'], 4) not in skip:
            t += rng.uniform(-ms, ms) / 1000 * T / 60
            n['velocity'] = max(1, min(127, n['velocity'] + rng.randint(-8, 8)))
        n['start_time'] = round(min(max(t, 0.0), end - 0.05), 6)
        n['duration'] = round(min(n['duration'], end - n['start_time']), 6)
        out.append(n)
    return out


def apply_sets(pre: dict, sets: list[str]) -> dict:
    pre = copy.deepcopy(pre)
    for s in sets:
        k, _, val = s.partition('=')
        k, val = k.strip(), val.strip()
        if k in SCALARS:
            pre[k] = SCALARS[k](val)
        elif k in OPTIONS:
            if val not in OPTIONS[k]:
                raise ValueError(f'--set {k} takes {", ".join(OPTIONS[k])}; got {val!r}')
            part, field = k.split('.')
            if part == 'drums':
                for t in (1, 2, 3):
                    pre['drums'][t] = dict(pre['drums'][t], **{field: val})
            elif k == 'keys.voicing':
                pre['voicing'] = val
            else:
                pre[part] = {t: val for t in (1, 2, 3)}
        else:
            raise ValueError(f'--set {k!r}: unknown key; see --help')
    return pre


def grid_print(notes: list[dict], plan: dict, bar: int) -> str:
    """One bar of drums on the 16th grid, pulses numbered."""
    g = plan['grid']
    bb, P = g['bar_beats'], g['preroll_bars']
    t0 = (bar - 1 + P) * bb
    cols = int(round(bb / 0.25))
    per_pulse = int(round(4 / g['pulse_unit'] / 0.25))
    head = ''.join(f'{i // per_pulse + 1:<2}' if i % per_pulse == 0 else '. '
                   for i in range(cols))
    label = f"{g['time_signature']} {'+'.join(map(str, g['grouping']))}"
    names = {KICK: 'kick', SNARE: 'snare', CLAP: 'clap', CH: 'hat', OH: 'open hat',
             RIDE: 'ride', CRASH: 'crash', 50: 'tom hi', 47: 'tom mid', 43: 'tom lo'}
    w = max(len(label), *map(len, names.values()))
    rows = [f'{label:<{w}} | {head}']
    for p, nm in names.items():
        hits = {int(round((n['start_time'] - t0) / 0.25)) for n in notes
                if n['pitch'] == p and t0 - EPS <= n['start_time'] < t0 + bb - EPS}
        if hits:
            rows.append(f'{nm:<{w}} | ' + ''.join('x ' if i in hits else '. '
                                                  for i in range(cols)))
    return '\n'.join(rows)


def plan_key(plan: dict) -> str:
    """Fingerprint of the plan the parts were made for; remix_build refuses a mismatch."""
    return hashlib.sha1(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:16]


def make_parts(plan: dict, preset: str | None = None, sets: list[str] = (),
               seed: int | None = None) -> dict:
    name = preset or plan['preset']
    if name not in PRESETS:
        raise ValueError(f'unknown preset {name!r}: {", ".join(PRESETS)}')
    pre = apply_sets(PRESETS[name], list(sets))
    seed = plan['seed'] if seed is None else seed
    g, T = plan['grid'], plan['tempo']['live']
    parts, report = {}, {'preset': name, 'seed': seed, 'sets': list(sets)}
    downbeats = {round(s['start_beat'], 4) for s in plan['sections']}
    if 'drums' in plan['parts']:
        d = drums(plan, pre)
        bad = validate_drums(d, T, g['bar_beats'], g['preroll_bars'], pre['kick_run'])
        if bad:
            raise ValueError('drum part not playable: ' + '; '.join(bad[:6]))
        land = {round(n['start_time'], 4) for n in d if n['pitch'] == CRASH} | downbeats
        parts['drums'] = swing_humanize(d, plan, pre['swing'], pre['humanize_ms'], seed, land)
        report['grid_bars'] = sorted({s['first_bar'] for s in plan['sections']
                                      if plan['energy']['drums'][s['first_bar'] - 1]})
    if 'bass' in plan['parts']:
        b = bass(plan, pre)
        as_an = all(pre['bass'][t] == 'as-analysed' for t in (1, 2, 3))
        parts['bass'] = b if as_an else swing_humanize(b, plan, pre['swing'],
                                                       pre['humanize_ms'], seed + 1, downbeats)
    if 'keys' in plan['parts']:
        parts['keys'] = swing_humanize(keys(plan, pre), plan, pre['swing'],
                                       pre['humanize_ms'], seed + 2, downbeats)
    end = g['total_beats']
    for p, ns in parts.items():
        over = [n for n in ns if n['start_time'] + n['duration'] > end + 1e-6]
        if over:
            raise ValueError(f'{p}: {len(over)} notes run past the end ({end} beats)')
    report['sections'] = [
        dict(name=s['name'], bars=f"{s['first_bar']}-{s['last_bar']}",
             tiers={p: max(plan['energy'][p][s['first_bar'] - 1:s['last_bar']])
                    for p in parts},
             notes={p: sum(s['start_beat'] <= n['start_time'] < s['end_beat'] for n in ns)
                    for p, ns in parts.items()})
        for s in plan['sections']]
    return dict(schema='ableton-song-remix.parts/1', plan_key=plan_key(plan), preset=name,
                seed=seed,
                search=pre['search'], parts=parts, report=report,
                straight_drums=d if 'drums' in plan['parts'] else [])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('plan')
    ap.add_argument('--preset', choices=list(PRESETS))
    ap.add_argument('--set', action='append', default=[], metavar='KEY=VALUE')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--out')
    a = ap.parse_args()
    plan_p = Path(a.plan)
    plan = json.loads(plan_p.read_text())
    try:
        res = make_parts(plan, a.preset, a.set, a.seed)
    except ValueError as e:
        sys.exit(f'remix_parts: {e}')
    straight = res.pop('straight_drums')
    out = Path(a.out) if a.out else plan_p.parent / 'parts.json'
    out.write_text(json.dumps(res, indent=1))
    print(f"preset {res['preset']}, seed {res['seed']}: " +
          ', '.join(f'{p} {len(n)} notes' for p, n in res['parts'].items()))
    print(f"{'section':<16} {'bars':<9} " + ' '.join(f'{p:<12}' for p in res['parts']))
    for s in res['report']['sections']:
        print(f"{s['name'][:15]:<16} {s['bars']:<9} " +
              ' '.join(f"t{s['tiers'][p]} {s['notes'][p]:>5} n  " for p in res['parts']))
    shown = set()
    for b in res['report'].get('grid_bars', []):
        txt = grid_print(straight, plan, b)
        body = txt.split('\n', 1)[-1]
        if body not in shown:
            shown.add(body)
            print(f'\nbar {b}:\n{txt}')
    print(f'drums playable: yes' if 'drums' in res['parts'] else '')
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
