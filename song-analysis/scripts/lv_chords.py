#!/usr/bin/env python3
"""Phase 7 primary: large-vocabulary chord recognition (lv-chordia) snapped to cells.

Runs lv-chordia (ISMIR 2019 large-vocabulary model: 7ths, inversions, sus) on the
full mix and assigns each (bar, cell) the chord that covers most of it. Cells
come from foundation.json's `grouping`, the same grid as chord_proposal.py.
With --compare, lists the cells where the triad cross-check disagrees on the
root - look at those by ear (Trap 1: static voicing over a moving bass).

Usage (the lv-chordia venv: pip install lv-chordia==1.1.0 librosa==0.11.0):
    <lv-venv>/bin/python lv_chords.py <song.mp3> --foundation analysis/foundation.json \
        [--compare analysis/chord_proposal.json] [--out analysis/chords_lv.json]
"""
import argparse, json, sys
from collections import Counter

NOTES = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6,
         "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}


def root_pc(label):
    """Pitch class of a Harte label ('F#:min7/b3') or a plain name ('F#m'); None for N/X."""
    if not label or label in ("N", "X"):
        return None
    head = label.split(":")[0].split("/")[0]
    name = head[:2] if head[1:2] in ("#", "b") else head[:1]
    return NOTES.get(name)


_TEMP_WAVS = []


def decodable(path):
    """librosa >= 1.0 decodes only what libsndfile reads (wav/flac/ogg/mp3); 0.11 fell back
    to audioread. Transcode anything else (m4a, aac, webm, mp4) to a temp wav with ffmpeg;
    the temp files are removed when the script exits. Always absolute: lv-chordia resolves
    a relative path against its own package directory, not the working directory."""
    import os
    import soundfile as sf
    path = os.path.abspath(path)
    try:
        sf.info(path)
        return path
    except Exception:
        import atexit, os, subprocess, tempfile
        fd, out = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, out], check=True)
        if not _TEMP_WAVS:
            atexit.register(lambda: [os.remove(p) for p in _TEMP_WAVS if os.path.exists(p)])
        _TEMP_WAVS.append(out)
        return out


def cells_of(downbeats, grouping):
    bpb = sum(grouping)
    edges = [0]
    for g in grouping:
        edges.append(edges[-1] + g)
    for i, (b0, b1) in enumerate(zip(downbeats[:-1], downbeats[1:])):
        for k in range(len(grouping)):
            yield i + 1, k + 1, b0 + (b1 - b0) * edges[k] / bpb, b0 + (b1 - b0) * edges[k + 1] / bpb


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("audio", help="full mix (scored better than a bass+other sum)")
    ap.add_argument("--foundation", required=True)
    ap.add_argument("--grouping", help="override, e.g. 2,2 or 6,5")
    ap.add_argument("--vocab", default="submission",
                    help="submission (default) | ismir2017 | full (untested upstream)")
    ap.add_argument("--compare", help="chord_proposal.py JSON to cross-check roots against")
    ap.add_argument("--out")
    a = ap.parse_args()

    F = json.load(open(a.foundation))
    grouping = [int(x) for x in a.grouping.split(",")] if a.grouping else F.get("grouping")
    if not grouping:
        sys.exit("No grouping. Run detect_meter.py first and set foundation.json "
                 "'grouping' (4/4 -> [2, 2]) or pass --grouping. Never assume 4/4.")

    from lv_chordia import chord_recognition      # heavy import: after arg checks
    segs = chord_recognition(decodable(a.audio), a.vocab)

    cells = []
    for bar, cell, t0, t1 in cells_of(F["downbeat_times"], grouping):
        best, cover = "N", 0.0
        for s in segs:
            o = min(t1, s["end_time"]) - max(t0, s["start_time"])
            if o > cover:
                best, cover = s["chord"], o
        cells.append(dict(bar=bar, cell=cell, t0=round(t0, 3), t1=round(t1, 3), chord=best,
                          coverage=round(cover / (t1 - t0), 2)))   # < 1: a change inside

    bars = {}
    for c in cells:
        bars.setdefault(c["bar"], []).append(c["chord"])
    print(f"{len(segs)} segments -> {len(cells)} cells over {len(bars)} bars, grouping {grouping}")
    print("bars:", " ".join("|".join(dict.fromkeys(v)) for _, v in sorted(bars.items())))
    print("most common:", ", ".join(f"{k} ({v})" for k, v in
                                    Counter(c["chord"] for c in cells).most_common(8)))

    disagree = []
    for c in cells:                                  # status: how far to trust this cell
        c["status"] = "unchecked" if not a.compare else "agree"
        if c["coverage"] < 0.5:
            c["status"] = "change-inside"
    if a.compare:
        tri = {(c["bar"], c["cell"]): c for c in json.load(open(a.compare))["cells"]}
        for c in cells:
            t = tri.get((c["bar"], c["cell"]))
            if not t:
                continue
            if root_pc(t["chord"]) is not None and root_pc(c["chord"]) is not None \
                    and root_pc(t["chord"]) != root_pc(c["chord"]):
                disagree.append((c["bar"], c["cell"], c["chord"], t["chord"]))
                c["status"] = "root-disagree"
            elif c["status"] == "agree" and t.get("margin", 1) < 0.01:
                c["status"] = "near-tie"
        st = Counter(c["status"] for c in cells)
        print("cell status: " + ", ".join(f"{k} {v}" for k, v in st.most_common()))
        print(f"root disagreements with the triad cross-check: {len(disagree)}/{len(cells)}"
              + (" - check these by ear" if disagree else ""))
        for d in disagree[:12]:
            print(f"  bar {d[0]} cell {d[1]}: lv {d[2]}  vs  triads {d[3]}")

    if a.out:
        json.dump(dict(model="lv-chordia 1.1.0", vocab=a.vocab, grouping=grouping,
                       segments=segs, cells=cells, root_disagreements=disagree),
                  open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()
