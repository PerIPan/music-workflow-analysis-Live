"""Synthetic analysed song folders for the ableton-song-remix tests (no real audio).

make_song() writes what song-analysis leaves behind: analysis/foundation.json (step
'meter'), analysis/stem_activity.json, analysis/bass_notes.json, a chart data file
gen_v1.py, tiny 16-bit WAV stems (8 kHz mono: silence or a quiet tone before bar 1, then
clicks) and an original mix. Invented titles and chords; no lyrics.
"""
from __future__ import annotations

import json, math, struct, wave
from pathlib import Path

SR = 8000


def write_wav(path: Path, dur: float, start: float, loud: bool = False) -> None:
    """Clicks every 0.5 s from start; before it silence, or a -6 dBFS tone if loud."""
    n = int(dur * SR)
    frames = bytearray()
    for i in range(n):
        t = i / SR
        if t < start:
            x = 0.5 * math.sin(2 * math.pi * 220 * t) if loud else 0.0
        elif (t - start) % 0.5 < 0.005:
            x = 0.3
        else:
            x = 0.0
        frames += struct.pack('<h', int(x * 32767))
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))


def make_song(root: Path, *, grouping=(2, 2), pulse_unit=4, bar_s=2.0, nbars=16, db0=0.5,
              drift=0.03, loud_pickup=False, wide_bar=None, chords=None, sections=None,
              bass_notes=None, outliers=(), name='Test Song') -> Path:
    """One song folder under root. wide_bar = (bar, factor) stretches one bar."""
    d = root / name.replace(' ', '')
    a = d / 'analysis'
    a.mkdir(parents=True)
    bpb = sum(grouping)
    lens = [bar_s * (1 + drift * math.sin(k)) for k in range(nbars)]
    if wide_bar:
        lens[wide_bar[0] - 1] *= wide_bar[1]
    db = [db0]
    for x in lens:
        db.append(round(db[-1] + x, 4))
    beats = [round(db[k] + j * lens[k] / bpb, 4) for k in range(nbars) for j in range(bpb)]
    beats.append(db[-1])
    F = dict(audio=f'{name}.wav', step='meter', beats_per_bar=bpb, pulse_unit=pulse_unit,
             time_signature=f'{bpb}/{pulse_unit}', grouping=list(grouping),
             downbeat_times=db, beat_times=beats, num_bars=nbars,
             bar_bpm=[round(60 * bpb * 4 / pulse_unit / x, 2) for x in lens],
             tempo_drift_pct=round(200 * drift, 1), tempo_outlier_bars=list(outliers),
             live_tempo=111.11)                          # deliberately not the mean
    (a / 'foundation.json').write_text(json.dumps(F))
    (a / 'stem_activity.json').write_text(json.dumps(
        {s: [0.0 if b < 2 else 0.9 for b in range(nbars)] for s in ('drums', 'bass', 'other')} |
        {'vocals': [0.5] * nbars}))
    (a / 'bass_notes.json').write_text(json.dumps({'notes': bass_notes if bass_notes is not None
                                                   else [dict(pitch=36, start=db[k] + 0.01,
                                                              end=db[k] + lens[k] / 2,
                                                              velocity=90)
                                                         for k in range(nbars)]}))
    ncell = len(grouping)
    if chords is None:
        loop = ['Cmaj7', 'F#m7', 'Em/D', 'D/F#']
        chords = {(b, c): loop[(b + c) % 4] for b in range(1, nbars + 1) for c in (1, ncell)}
        chords[(3, 1)] = 'N.C.'
        chords.pop((4, 1), None)
    if sections is None:
        h = nbars // 2
        sections = [('Intro', 1, 4, 'intro', ''), ('Verse', 5, h, 'verse', ''),
                    ('Chorus', h + 1, nbars, 'chorus', '')]
    song = dict(title=name, artist='Nobody', sections=sections, chords=chords,
                bass_notes=bass_notes_chart(ncell))
    (d / 'gen_v1.py').write_text('SONG = ' + repr(song) + '\n')
    stems = d / 'stems' / 'htdemucs_ft' / name.replace(' ', '')
    dur = db[-1] + 1.0
    for s in ('vocals', 'drums', 'bass', 'other'):
        write_wav(stems / f'{s}.wav', dur, db0, loud_pickup and s == 'vocals')
    write_wav(d / f'{name}.wav', dur, db0)
    return d


def bass_notes_chart(ncell: int) -> dict:
    return {(6, ncell): 'A'}
