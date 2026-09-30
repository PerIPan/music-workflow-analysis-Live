#!/usr/bin/env python3
"""Phase 4: bass stem -> notes (pyin) -> bass.mid + seconds of each pitch class per cell.

pyin, not CREPE: in a side-by-side A/B on a separated bass stem the CREPE line was
rejected by ear (over-segmented), and pYIN beats CREPE on bass lines in published
tests (CREPE has little sub-bass training data). Same pipeline as the
bass-transcribe skill, plus the per-(bar, cell) pitch-class totals the chord and
mode steps read.

Usage (analysis venv: librosa, numpy, pretty_midi):
    bass_notes.py stems/htdemucs_ft/<song>/bass.wav --foundation analysis/foundation.json \
        [--bass-entry-bar N] [--fmin 40] [--fmax 220] [--outdir analysis]
"""
import argparse, bisect, json
from pathlib import Path
import numpy as np
import librosa

PCN = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def pyin_notes(path, fmin, fmax, vprob=0.55, min_len=0.10, gap=0.05):
    y, sr = librosa.load(path, sr=22050, mono=True)
    hop = 256
    f0, voiced, vp = librosa.pyin(y, sr=sr, fmin=fmin, fmax=fmax, frame_length=4096,
                                  hop_length=hop)
    t = librosa.times_like(f0, sr=sr, hop_length=hop)
    rms = librosa.feature.rms(y=y, frame_length=4096, hop_length=hop)[0]
    rms = rms / (rms.max() + 1e-9)
    pitch = np.where(voiced & (vp >= vprob),
                     np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=fmin))), -1).astype(int)
    notes, cur = [], None
    for i, (ti, p) in enumerate(zip(t, pitch)):
        if cur and p == cur["p"]:
            cur["end"], cur["i1"] = ti, i
            continue
        if cur and p < 0 and ti - cur["end"] <= gap:
            continue
        if cur and cur["end"] - cur["start"] >= min_len:
            notes.append(cur)
        cur = dict(p=p, start=ti, end=ti, i0=i, i1=i) if p >= 0 else None
    if cur and cur["end"] - cur["start"] >= min_len:
        notes.append(cur)
    return [dict(pitch=int(n["p"]), start=round(float(n["start"]), 3),
                 end=round(float(n["end"]), 3),
                 velocity=int(np.clip(50 + 70 * rms[n["i0"]:n["i1"] + 1].mean(), 35, 120)))
            for n in notes]


def cells(downbeats, grouping):
    bpb = sum(grouping)
    edges = np.concatenate([[0], np.cumsum(grouping)]) / bpb
    for i, (b0, b1) in enumerate(zip(downbeats[:-1], downbeats[1:])):
        for k in range(len(grouping)):
            yield i + 1, k + 1, b0 + (b1 - b0) * edges[k], b0 + (b1 - b0) * edges[k + 1]


def downbeat_check(per_cell, grouping, downbeat_pulse, min_sec=0.15, min_changes=8):
    """Where in the bar does the bass change pitch? A loop that changes on a later cell
    (beat 3 of 4/4) almost always means beat 1 is off by that cell's offset. Returns
    (cell, share, suggested downbeat_pulse) when a later cell takes at least twice the
    changes of cell 1, else None."""
    counts, prev = [0] * len(grouping), None
    for c in per_cell:
        pcs = c["pc_seconds"]
        top = max(pcs, key=pcs.get) if pcs else None
        if top is None or pcs[top] < min_sec:
            continue
        if prev is not None and top != prev:
            counts[c["cell"] - 1] += 1
        prev = top
    total = sum(counts)
    k = max(range(len(counts)), key=counts.__getitem__)
    if total < min_changes or k == 0 or counts[k] < 2 * counts[0]:
        return None
    return k + 1, counts[k] / total, (downbeat_pulse + sum(grouping[:k])) % sum(grouping)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bass")
    ap.add_argument("--foundation", required=True)
    ap.add_argument("--bass-entry-bar", type=int, default=1,
                    help="ignore notes before this bar (pre-entry content is stem bleed)")
    ap.add_argument("--fmin", type=float, default=40.0, help="E1; 36 for drop-D, 30 for low B")
    ap.add_argument("--fmax", type=float, default=220.0)
    ap.add_argument("--outdir", default="analysis")
    a = ap.parse_args()
    F = json.load(open(a.foundation))
    out = Path(a.outdir)
    notes = pyin_notes(a.bass, a.fmin, a.fmax)
    db, grouping = F["downbeat_times"], F["grouping"]
    entry_t = db[a.bass_entry_bar - 1] if a.bass_entry_bar > 1 else 0.0
    notes = [n for n in notes if n["start"] >= entry_t]

    import pretty_midi
    pm = pretty_midi.PrettyMIDI()
    inst = pretty_midi.Instrument(program=33)
    inst.notes = [pretty_midi.Note(velocity=n["velocity"], pitch=n["pitch"], start=n["start"],
                                   end=n["end"]) for n in notes]
    pm.instruments.append(inst)
    pm.write(str(out / "bass.mid"))
    json.dump(dict(fmin=a.fmin, fmax=a.fmax, bass_entry_bar=a.bass_entry_bar, notes=notes),
              open(out / "bass_notes.json", "w"), indent=1)

    starts = [n["start"] for n in notes]
    per_cell, total = [], np.zeros(12)
    for bar, cell, t0, t1 in cells(db, grouping):
        pcs = np.zeros(12)
        for n in notes[max(bisect.bisect_left(starts, t0) - 20, 0):bisect.bisect_right(starts, t1)]:
            ov = min(t1, n["end"]) - max(t0, n["start"])
            if ov > 0:
                pcs[n["pitch"] % 12] += ov
        total += pcs
        per_cell.append(dict(bar=bar, cell=cell, pc_seconds={PCN[i]: round(float(v), 3)
                                                            for i, v in enumerate(pcs) if v > 0}))
    json.dump(dict(cells=per_cell), open(out / "bass_per_cell.json", "w"), indent=1)
    top = np.argsort(total)[::-1][:3]
    share = total / max(total.sum(), 1e-9)
    print(f"{len(notes)} bass notes ({len(notes) / max(notes[-1]['end'] - notes[0]['start'], 1):.2f}/s)"
          if notes else "no bass notes found")
    print("longest-sustained pitch classes: " +
          ", ".join(f"{PCN[i]} {share[i]:.0%}" for i in top) + " (tonic candidate = the first)")
    shifted = downbeat_check(per_cell, grouping, F.get("downbeat_pulse", 0))
    if shifted:
        cell, frac, dp = shifted
        print(f"DOWNBEAT CHECK: {frac:.0%} of bass changes land on cell {cell}, not cell 1 - "
              f"beat 1 is probably off. Unless the harmony is deliberately pushed, re-run "
              f"foundation.py meter --downbeat-pulse {dp} (plus your --cycle/--grouping), "
              f"then this script, before anything else keyed by bar.")


if __name__ == "__main__":
    main()
