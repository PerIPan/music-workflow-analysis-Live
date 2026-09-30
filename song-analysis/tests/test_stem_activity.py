#!/usr/bin/env python3
"""Test scripts/stem_activity.py on synthetic stems (sine tones in a temp folder).

A drum stem loud for 10 bars, at half amplitude for 5 and silent for 5 must read 1.0, 0.5
and 0 (normalised by its 95th-percentile bar); a steady bass stem reads 1.0 everywhere;
missing stems are left out and an empty folder is an error. A vocal heard in 1 bar of 20
and a bleed-only stem read low where they are absent; bars past the end of the audio read 0.
Run with the analysis venv: <venv>/bin/python tests/test_stem_activity.py
"""
import atexit, json, math, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
import soundfile as sf

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stem_activity.py"
SR, BAR, NBARS = 22050, 1.0, 20


def tone(amps):
    """One bar of a 220 Hz sine per amplitude."""
    t = np.arange(int(SR * BAR)) / SR
    return np.concatenate([a * np.sin(2 * np.pi * 220 * t) for a in amps]).astype(np.float32)


def main():
    fails = 0

    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{info}]"))

    d = Path(tempfile.mkdtemp(prefix="stem_activity_"))
    atexit.register(shutil.rmtree, d, True)            # removed at exit
    stems = d / "stems"
    stems.mkdir()
    sf.write(stems / "drums.wav", tone([0.8] * 10 + [0.4] * 5 + [0.0] * 5), SR)
    sf.write(stems / "bass.wav", tone([0.3] * NBARS), SR)
    json.dump({"downbeat_times": [BAR * i for i in range(NBARS + 1)]}, open(d / "f.json", "w"))
    r = subprocess.run([sys.executable, str(SCRIPT), str(stems), "--foundation", str(d / "f.json"),
                        "--out", str(d / "a.json")], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        print(r.stderr); sys.exit(1)
    A = json.load(open(d / "a.json"))
    near = lambda xs, v: all(abs(x - v) < 0.02 for x in xs)
    check("only the stems present, in order", list(A) == ["drums", "bass"], list(A))
    check("one value per bar", all(len(v) == NBARS for v in A.values()), {k: len(v) for k, v in A.items()})
    dr = A["drums"]
    check("full level reads 1.0", near(dr[1:9], 1.0), dr[:10])
    check("half amplitude reads 0.5", near(dr[11:14], 0.5), dr[10:15])
    check("silence reads 0", near(dr[16:], 0.0), dr[15:])
    check("a steady quiet stem is still 1.0", near(A["bass"][1:-1], 1.0), A["bass"])
    empty = d / "empty"
    empty.mkdir()
    r = subprocess.run([sys.executable, str(SCRIPT), str(empty), "--foundation", str(d / "f.json"),
                        "--out", str(d / "b.json")], capture_output=True, text=True)
    check("no stems -> error", r.returncode != 0 and "no drums" in r.stderr, r.stderr)

    sparse = d / "sparse"
    sparse.mkdir()
    sf.write(sparse / "vocals.wav", tone([0.01] * (NBARS - 1) + [0.8]), SR)   # 1 sung bar
    sf.write(sparse / "other.wav", tone([0.002] * NBARS), SR)                # bleed, -57 dBFS
    r = subprocess.run([sys.executable, str(SCRIPT), str(sparse), "--foundation", str(d / "f.json"),
                        "--out", str(d / "c.json")], capture_output=True, text=True)
    A = json.load(open(d / "c.json")) if r.returncode == 0 else {}
    vo, ot = A.get("vocals", [1.0]), A.get("other", [1.0])
    check("a stem heard in 1 bar of 20 reads < 0.1 where absent", max(vo[:-1]) < 0.1, vo)
    check("a bleed-only stem reads < 0.25 throughout", max(ot) < 0.25, ot)

    json.dump({"downbeat_times": [BAR * i for i in range(NBARS + 1)] + [BAR * (NBARS + 1)]},
              open(d / "g.json", "w"))                                        # a bar past the audio
    r = subprocess.run([sys.executable, str(SCRIPT), str(stems), "--foundation", str(d / "g.json"),
                        "--out", str(d / "e.json")], capture_output=True, text=True)
    A = json.load(open(d / "e.json")) if r.returncode == 0 else {}
    dr = A.get("drums", [math.nan])
    check("a bar past the end of the audio reads 0, the rest unchanged (no NaN)",
          len(dr) == NBARS + 1 and all(math.isfinite(v) for v in dr) and dr[-1] == 0
          and near(dr[1:9], 1.0), dr)
    check("... with a warning", "past the end" in r.stderr, r.stderr)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
