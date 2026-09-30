#!/usr/bin/env python3
"""Test scripts/bass_notes.py + scripts/mode_test.py on synthetic drones.

Each case: sustained tones for the harmony over a sine bass on the tonic. The mode
test must name Lydian and Dorian from their characteristic degrees, and must say
"undetermined" instead of guessing when the drone has no 6th.
Run with the analysis venv: <venv>/bin/python tests/test_mode_test.py
"""
import atexit, json, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

S = Path(__file__).resolve().parents[1] / "scripts"
SR, BARS, BAR = 22050, 8, 2.0
CASES = [  # name, tonic MIDI (bass), harmony MIDI notes, expected mode (substring)
    ("E lydian", 40, [64, 68, 70, 71, 75, 62 + 16], "lydian"),      # E G# A# B D# (+E)
    ("D dorian", 38, [62, 65, 69, 71, 72, 64], "dorian"),           # D F A B C E
    ("A minor, no 6th", 45, [69, 72, 76, 71], "6th undetermined"),  # A C E B only
]


def tone(midi, dur, amp):
    t = np.arange(int(SR * dur)) / SR
    return amp * np.sin(2 * np.pi * 440 * 2 ** ((midi - 69) / 12) * t)


def main():
    fails = 0
    for name, tonic, notes, want in CASES:
        d = Path(tempfile.mkdtemp())
        atexit.register(shutil.rmtree, d, True)            # removed at exit
        dur = BARS * BAR
        rng = np.random.default_rng(0)
        sf.write(d / "other.wav", sum(tone(n, dur, 0.1) for n in notes)
                 + 0.002 * rng.standard_normal(int(SR * dur)), SR)
        sf.write(d / "bass.wav", tone(tonic, dur, 0.5), SR)
        json.dump({"downbeat_times": [i * BAR for i in range(BARS + 1)], "grouping": [2, 2]},
                  open(d / "f.json", "w"))
        py = sys.executable
        subprocess.run([py, str(S / "bass_notes.py"), str(d / "bass.wav"), "--foundation",
                        str(d / "f.json"), "--outdir", str(d)], capture_output=True, check=True)
        subprocess.run([py, str(S / "mode_test.py"), "--other", str(d / "other.wav"),
                        "--foundation", str(d / "f.json"), "--bass-cells",
                        str(d / "bass_per_cell.json"), "--out", str(d / "m.json")],
                       capture_output=True, check=True)
        got = json.load(open(d / "m.json"))["song"]
        ok = want in got["mode"] and got["tonic"] == ["C", "C#", "D", "D#", "E", "F", "F#",
                                                     "G", "G#", "A", "A#", "B"][tonic % 12]
        fails += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:18s} got {got['tonic']} {got['mode']}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
