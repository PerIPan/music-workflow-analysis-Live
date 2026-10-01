#!/usr/bin/env python3
"""Strumming pattern: guitar stem -> the 16th-note rhythm it plays, per bar and per section.

Why: a chart says which chord, not how the guitar plays it; a sketch or a band needs the
rhythm too. The guitar stem comes from the extra htdemucs_6s run (Phase 2: the 4-stem
other.wav mixes guitars with keys and pads). Each onset is snapped to the nearest 16th of
its bar (bar-relative, through the downbeats, so tempo drift doesn't smear the grid); a
section's pattern is the steps hit in at least half of its bars (--min-share), with the
mean strength per step as the accent. `onsets` keeps every strum's real time and strength
(the remix sketch plays those). Stroke directions are the hand-motion convention
(down on the 8ths, up on the 16ths between: the hand keeps moving), not measured.

Usage (analysis venv: librosa, numpy):
    strum_pattern.py stems/htdemucs_6s/<song>/guitar.wav --foundation analysis/foundation.json \
        [--sections analysis/sections.json] [--min-share 0.5] [--out analysis/strum.json]
"""
from __future__ import annotations

import argparse, json
from pathlib import Path

import numpy as np


def steps_per_bar(F: dict) -> int:
    """16ths in one bar: 4/4 -> 16, 6/8 -> 12, 11/8 -> 22."""
    quarters = F['beats_per_bar'] * 4 / F.get('pulse_unit', 4)
    return int(round(quarters * 4))


def onsets(path: str, sr: int = 22050, hop: int = 256) -> tuple[np.ndarray, np.ndarray]:
    """Onset times (s) and strengths (0-1, by the song's 95th percentile) of the stem."""
    import librosa
    y, sr = librosa.load(path, sr=sr, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    idx = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop,
                                     backtrack=False, units='frames')
    t = librosa.frames_to_time(idx, sr=sr, hop_length=hop)
    s = env[idx] / (np.percentile(env[idx], 95) + 1e-9) if len(idx) else env[idx]
    return t, np.clip(s, 0, 1)


def grid(times: np.ndarray, strength: np.ndarray, downbeats: list, steps: int,
         floor: float = 0.15) -> list[list[float]]:
    """Per bar, the strongest onset on each 16th step (0 = none); onsets weaker than
    floor are bleed or string noise and ignored."""
    bars = [[0.0] * steps for _ in range(len(downbeats) - 1)]
    for t, s in zip(times, strength):
        if s < floor:
            continue
        b = int(np.searchsorted(downbeats, t, side='right')) - 1
        if not 0 <= b < len(bars):
            continue
        pos = (t - downbeats[b]) / (downbeats[b + 1] - downbeats[b]) * steps
        k = int(round(pos))
        if k == steps:                         # the next bar's downbeat, a hair early
            if b + 1 < len(bars):
                bars[b + 1][0] = max(bars[b + 1][0], float(s))
            continue
        bars[b][k] = max(bars[b][k], float(s))
    return bars


def direction(step: int) -> str:
    return 'D' if step % 2 == 0 else 'U'


def summarise(bars: list[list[float]], min_share: float) -> dict:
    """The steps hit in at least min_share of the bars, their share and mean accent."""
    if not bars:
        return {'bars': 0, 'pattern': [], 'share': [], 'accent': []}
    a = np.array(bars)
    hit = a > 0
    share = hit.mean(axis=0)
    accent = np.where(hit.any(axis=0), a.sum(axis=0) / np.maximum(hit.sum(axis=0), 1), 0)
    pat = [int(x >= min_share) for x in share]
    return {'bars': len(bars), 'pattern': pat, 'share': [round(float(x), 2) for x in share],
            'accent': [round(float(x), 2) for x in accent],
            'strokes': ''.join(direction(k) if p else '.' for k, p in enumerate(pat)),
            'onsets_per_bar': round(float(hit.sum(axis=1).mean()), 1)}


def sections_of(path: str | None, nbars: int) -> list[dict]:
    """[{name, first_bar, last_bar}] from sections.json (each runs to the next one's bar),
    from a remix plan.json (the chart's named sections), or the whole song."""
    if not path or not Path(path).is_file():
        return [{'name': 'Song', 'first_bar': 1, 'last_bar': nbars}]
    secs = json.loads(Path(path).read_text())['sections']
    if secs and 'first_bar' in secs[0]:        # a remix plan.json: the chart's sections
        return [{'name': s['name'], 'first_bar': max(1, s['first_bar']),
                 'last_bar': min(nbars, s['last_bar'])} for s in secs]
    starts = [max(1, int(s['where'][0])) for s in secs]
    out = []
    if starts and starts[0] > 1:
        out.append({'name': 'Intro', 'first_bar': 1, 'last_bar': starts[0] - 1})
    for i, s in enumerate(secs):
        last = starts[i + 1] - 1 if i + 1 < len(secs) else nbars
        if last >= starts[i]:
            out.append({'name': s.get('label') or f'S{i + 1}', 'first_bar': starts[i],
                        'last_bar': last})
    return out


def show(steps: int, per_beat: int = 4) -> str:
    return ' '.join(str(k // per_beat + 1) if k % per_beat == 0 else
                    {1: 'e', 2: '&', 3: 'a'}.get(k % per_beat, '.') for k in range(steps))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('guitar')
    ap.add_argument('--foundation', required=True)
    ap.add_argument('--sections', help='sections.json (Phase 6) or a remix plan.json; '
                    'default: one section')
    ap.add_argument('--min-share', type=float, default=0.5,
                    help='a step belongs to the pattern when hit in this share of the bars')
    ap.add_argument('--out', default='analysis/strum.json')
    a = ap.parse_args()
    F = json.loads(Path(a.foundation).read_text())
    db = F['downbeat_times']
    steps = steps_per_bar(F)
    t, s = onsets(a.guitar)
    bars = grid(t, s, db, steps)
    secs = sections_of(a.sections, len(bars))
    print(f'{len(t)} onsets, {steps} steps per bar; strokes D/U by convention, not measured')
    print(f"{'':16}{show(steps)}")
    out = []
    for sec in secs:
        sm = summarise(bars[sec['first_bar'] - 1:sec['last_bar']], a.min_share)
        out.append(dict(sec, **sm))
        if sm['bars']:
            print(f"{sec['name'][:10]:10} {sec['first_bar']:>3}-{sec['last_bar']:<3}"
                  f"{' '.join(sm['strokes'])}   ({sm['onsets_per_bar']}/bar)")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    keep = s >= 0.15                              # as grid(): weaker is bleed or noise
    Path(a.out).write_text(json.dumps({'steps_per_bar': steps, 'min_share': a.min_share,
                                       'onsets': [[round(float(x), 4), round(float(y), 3)]
                                                  for x, y in zip(t[keep], s[keep])],
                                       'sections': out,
                                       'bars': [[round(x, 2) for x in b] for b in bars]},
                                      indent=1))
    print(f'wrote {a.out}')


if __name__ == '__main__':
    main()
