#!/usr/bin/env python3
"""Drums stem -> labelled hits with the drummer's timing and dynamics (ADTOF), fills marked.

Why: a sketch that plays a generated backbeat sounds robotic; the drummer's own hits,
ghost notes and fills are in the stem. ADTOF (Frame_RNN, adtofAll; installed in its own
venv, never copied - CC BY-NC-SA) labels each onset kick / snare / hi-hat / tom /
cymbal. It is level-sensitive, so the stem is peak-normalised to -1 dBFS first (a stem at
-5 dBFS gave 15 hits for a song, normalised 181). ADTOF has no velocity: each hit's
velocity comes from the stem's peak in that class's band around the hit, scaled per class
(a ghost snare stays quiet next to a backbeat). ADTOF's cymbal class mixes crash and
ride: a cymbal hit in the loudest fifth, on a downbeat or a beat after the previous cymbal
hit, is a crash (49); the rest ride (51).
A bar with toms, or with twice the median hit count in its last beat, is a fill.

Times stay in seconds of the stem (= the mix); the remix plan maps them to Live beats.
GM pitches: kick 36, snare 38, closed hat 42, toms 48/45/43 (high/mid/low by pitch),
crash 49, ride 51.

Usage (ADTOF venv; TF_USE_LEGACY_KERAS=1 is set here):
    drum_transcribe.py stems/htdemucs_ft/<song>/drums.wav --foundation analysis/foundation.json \
        [--out analysis/drum_hits.json] [--midi analysis/drums.mid]
"""
from __future__ import annotations

import argparse, json, os, shutil, tempfile
from pathlib import Path

import numpy as np

ADTOF_TO_GM = {35: 36, 38: 38, 42: 42, 47: 45, 49: 51}
BANDS = {36: (40, 120), 38: (150, 5000), 42: (5000, 12000), 45: (70, 400), 51: (3000, 12000)}


def normalise(src: str, dst: str) -> None:
    import soundfile as sf
    y, sr = sf.read(src, always_2d=True)
    peak = float(np.abs(y).max()) or 1.0
    sf.write(dst, y * (10 ** (-1 / 20) / peak), sr)


def adtof_hits(wav: str) -> list[tuple[float, int]]:
    """[(seconds, ADTOF pitch)] for the normalised stem."""
    os.environ.setdefault('TF_USE_LEGACY_KERAS', '1')
    from adtof.model.model import Model
    import pretty_midi
    tmp = Path(tempfile.mkdtemp(prefix='adtof_'))
    try:
        (tmp / 'in').mkdir()
        normalise(wav, str(tmp / 'in' / 'drums.wav'))
        model, hp = Model.modelFactory(modelName='Frame_RNN', scenario='adtofAll', fold=0)
        model.predictFolder(str(tmp / 'in' / '*.wav'), str(tmp / 'out'), **hp)
        mid = next((tmp / 'out').glob('*.mid'))
        notes = pretty_midi.PrettyMIDI(str(mid)).instruments[0].notes
        return sorted((float(n.start), int(n.pitch)) for n in notes)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def band_peaks(y: np.ndarray, sr: int, hits: list[tuple[float, int]], win: float = 0.03
               ) -> list[float]:
    """Peak magnitude (dB) in each hit's band within +-win s, from one STFT."""
    import librosa
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    out = []
    for t, p in hits:
        lo, hi = BANDS[p]
        k0 = max(int((t - win) * sr / hop), 0)
        k1 = min(int((t + win) * sr / hop) + 1, S.shape[1])
        band = S[(f >= lo) & (f <= hi), k0:k1]
        out.append(20 * np.log10(float(band.sum(axis=0).max()) + 1e-9) if band.size else -120.0)
    return out


def velocities(db: list[float], pitch: list[int]) -> list[int]:
    """Per class: its loudest hits (95th percentile) -> 120, 30 dB below -> 30."""
    db, pitch = np.array(db), np.array(pitch)
    vel = np.zeros(len(db), dtype=int)
    for p in set(pitch.tolist()):
        m = pitch == p
        top = np.percentile(db[m], 95)
        vel[m] = np.clip(120 - (top - db[m]) * 3, 30, 120).astype(int)
    return vel.tolist()


def tom_pitches(y: np.ndarray, sr: int, times: list[float]) -> list[int]:
    """High / mid / low tom (48/45/43) by each hit's spectral centroid, in thirds."""
    import librosa
    if not times:
        return []
    cents = []
    for t in times:
        seg = y[int(t * sr):int((t + 0.12) * sr)]
        cents.append(float(librosa.feature.spectral_centroid(y=seg, sr=sr).mean())
                     if len(seg) > 512 else 0.0)
    lo, hi = np.percentile(cents, [33, 67]) if len(cents) > 2 else (min(cents), max(cents))
    return [48 if c > hi else 43 if c < lo else 45 for c in cents]


def fills(hits: list[dict], downbeats: list[float], beats_per_bar: int) -> list[int]:
    """1-based bars with a tom, or with twice the median hit count in their last beat."""
    n = len(downbeats) - 1
    tom = [0] * n
    last = [0] * n
    for h in hits:
        b = int(np.searchsorted(downbeats, h['t'], side='right')) - 1
        if not 0 <= b < n:
            continue
        if h['pitch'] in (43, 45, 48):
            tom[b] += 1
        beat = (h['t'] - downbeats[b]) / (downbeats[b + 1] - downbeats[b]) * beats_per_bar
        if beat >= beats_per_bar - 1:
            last[b] += 1
    played = sorted(x for x in last if x)
    med = played[len(played) // 2] if played else 0
    return [b + 1 for b in range(n) if tom[b] or (med and last[b] >= 2 * med)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('drums')
    ap.add_argument('--foundation', required=True)
    ap.add_argument('--out', default='analysis/drum_hits.json')
    ap.add_argument('--midi', default='analysis/drums.mid')
    a = ap.parse_args()
    import librosa, pretty_midi
    F = json.loads(Path(a.foundation).read_text())
    db_times = F['downbeat_times']
    raw = adtof_hits(a.drums)
    y, sr = librosa.load(a.drums, sr=22050, mono=True)
    pitch = [ADTOF_TO_GM[p] for _, p in raw]
    times = [t for t, _ in raw]
    toms = iter(tom_pitches(y, sr, [t for t, p in zip(times, pitch) if p == 45]))
    level = band_peaks(y, sr, list(zip(times, pitch)))
    vel = velocities(level, pitch)
    cym = [i for i, p in enumerate(pitch) if p == 51]
    loud = np.percentile([vel[i] for i in cym], 80) if cym else 999
    beat = float(np.median(np.diff(db_times))) / F['beats_per_bar']
    prev_cym = {j: times[k] for k, j in zip(cym, cym[1:])}   # the cymbal hit before each
    hits = []
    for i, (t, p) in enumerate(zip(times, pitch)):
        if p == 45:
            p = next(toms)
        elif p == 51 and vel[i] >= loud and (any(abs(t - d) < 0.04 for d in db_times)
                                             or t - prev_cym.get(i, -9) >= beat):
            p = 49
        hits.append(dict(t=round(t, 4), pitch=p, velocity=vel[i]))
    fb = fills(hits, db_times, F['beats_per_bar'])
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=0, is_drum=True)
    inst.notes = [pretty_midi.Note(velocity=h['velocity'], pitch=h['pitch'], start=h['t'],
                                   end=h['t'] + 0.1) for h in hits]
    pm.instruments.append(inst)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    pm.write(a.midi)
    Path(a.out).write_text(json.dumps({'source': 'ADTOF Frame_RNN adtofAll', 'fill_bars': fb,
                                       'hits': hits}, indent=1))
    names = {36: 'kick', 38: 'snare', 42: 'hat', 43: 'tom L', 45: 'tom M', 48: 'tom H',
             49: 'crash', 51: 'ride'}
    count = {names[p]: sum(h['pitch'] == p for h in hits) for p in names}
    print(f"{len(hits)} hits: {', '.join(f'{k} {v}' for k, v in count.items() if v)}")
    print(f"fills (bars): {fb if fb else 'none found'}")
    print(f'wrote {a.out}, {a.midi}')


if __name__ == '__main__':
    main()
