#!/usr/bin/env python3
"""Phase 8 helper: per-bar loudness of each stem -> stem_activity.json (the chart's song map).

One RMS value per bar for each demucs stem present (drums, bass, other, vocals), divided
by that stem's 95th-percentile bar: 1.0 is the stem's normal full level whatever the mix
balance, so entries, drop-outs and breakdowns read straight off the numbers and a quiet
stem is not mistaken for an absent one. The reference is at least a quarter of the stem's
loudest bar, so a stem heard in under 5% of the bars reads low where it is absent, and at
least -40 dBFS, so a stem that is only separation bleed reads low throughout. Bars come
from foundation.json's downbeat_times (a bar past the end of the audio reads 0); mono at
11025 Hz is plenty for a level. chart_html.py averages these per section.

It also writes band_level.json beside it: the band (every stem but the vocals, summed) per
cell of the grouping, divided by the song's median cell - where it drops under ~0.3 the
band stops and the voice is alone (a stop-time break), which the chart greys. Measured on
the first song: the stops read 0.04-0.07, the quietest played cells 0.4.

Usage (analysis venv: librosa, numpy):
    stem_activity.py stems/htdemucs_ft/<song> --foundation analysis/foundation.json \
        [--out analysis/stem_activity.json]
"""
import argparse, json, sys
from pathlib import Path
import numpy as np
import librosa

STEMS = ("drums", "bass", "other", "vocals")
SR = 11025
FLOOR = 0.01                     # -40 dBFS: a stem whose loudest bars stay under it is bleed


def bar_rms(y, sr, downbeats):
    """RMS of y between successive downbeats (one value per bar; 0 past the end of y)."""
    idx = [int(t * sr) for t in downbeats]
    segs = (y[a:b] for a, b in zip(idx[:-1], idx[1:]))
    return np.array([np.sqrt(np.mean(s ** 2)) if s.size else 0.0 for s in segs])


def activity(stem_dir, downbeats, sr=SR):
    """{stem: [per-bar RMS / the stem's reference level, rounded to 3]}."""
    out, short = {}, []
    for stem in STEMS:
        path = Path(stem_dir) / f"{stem}.wav"
        if not path.exists():
            continue
        y, _ = librosa.load(path, sr=sr, mono=True)
        if downbeats[-1] > len(y) / sr + 0.05:
            short.append(f"{stem}.wav ({len(y) / sr:.2f} s)")
        r = bar_rms(y, sr, downbeats)
        ref = max(float(np.percentile(r, 95)), 0.25 * float(r.max()), FLOOR)
        out[stem] = [round(float(v) / ref, 3) for v in r]
    if short:
        print(f"warning: the last downbeat ({downbeats[-1]:.2f} s) is past the end of "
              f"{', '.join(short)}; bars past the end read 0", file=sys.stderr)
    return out


def band_cells(stem_dir, downbeats, grouping, sr=SR):
    """[[bar, cell, band level / the median cell's]] - drums + bass + other summed."""
    ys = [librosa.load(Path(stem_dir) / f"{s}.wav", sr=sr, mono=True)[0]
          for s in STEMS if s != "vocals" and (Path(stem_dir) / f"{s}.wav").exists()]
    if not ys:
        return []
    n = min(len(y) for y in ys)
    band = sum(y[:n] for y in ys)
    edges = np.concatenate([[0], np.cumsum(grouping)]) / sum(grouping)
    cells = []
    for b, (t0, t1) in enumerate(zip(downbeats[:-1], downbeats[1:]), 1):
        for k in range(len(grouping)):
            a = int((t0 + (t1 - t0) * edges[k]) * sr)
            z = int((t0 + (t1 - t0) * edges[k + 1]) * sr)
            seg = band[a:z]
            cells.append([b, k + 1, float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0])
    played = [c[2] for c in cells if c[2] > 0]
    ref = max(float(np.median(played)) if played else 0.0, 1e-6)
    return [[b, k, round(v / ref, 3)] for b, k, v in cells]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stems", help="demucs output folder with drums/bass/other/vocals.wav")
    ap.add_argument("--foundation", required=True)
    ap.add_argument("--out", default="analysis/stem_activity.json")
    a = ap.parse_args()
    db = json.load(open(a.foundation))["downbeat_times"]
    act = activity(a.stems, db)
    if not act:
        raise SystemExit(f"no {'/'.join(STEMS)}.wav in {a.stems}")
    json.dump(act, open(a.out, "w"))
    F = json.load(open(a.foundation))
    cells = band_cells(a.stems, db, F.get("grouping") or [F.get("beats_per_bar", 4)])
    if cells:
        bl = Path(a.out).with_name("band_level.json")
        json.dump({"grouping": F.get("grouping"), "cells": cells}, open(bl, "w"))
        stops = [(b, k) for b, k, v in cells if v < 0.3]
        print(f"wrote {bl}: {len(stops)} cells where the band drops under 0.3 of its median")
    print(f"wrote {a.out}: bars at >= 0.25 of full level, of {len(db) - 1}: " + ", ".join(
        f"{s} {sum(v >= 0.25 for v in vals)}" for s, vals in act.items()))


if __name__ == "__main__":
    main()
