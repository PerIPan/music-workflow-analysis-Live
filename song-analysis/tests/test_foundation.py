#!/usr/bin/env python3
"""Test scripts/foundation.py's meter step: it must stop and ask instead of guessing.

Uses a synthetic beat grid and hand-written detect_meter.py results (no audio,
no madmom). Run: python3 tests/test_foundation.py
"""
import atexit, json, shutil, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "foundation.py"


def run(d, cons, *args):
    beats = [0.38 * i + (0.002 * i if i > 100 else 0) for i in range(176)]   # drifts late
    json.dump({"pulse_bpm": 157.9, "beat_times": beats, "key_top2": [["E major", 0.6]]},
              open(d / "f.json", "w"))
    json.dump({"consensus": cons}, open(d / "m.json", "w"))
    r = subprocess.run([sys.executable, str(SCRIPT), "meter", "--foundation", str(d / "f.json"),
                        "--meter", str(d / "m.json"), *map(str, args)], capture_output=True, text=True)
    return r, (json.load(open(d / "f.json")) if r.returncode == 0 else None)


def main():
    fails = 0
    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{info}]"))
    d = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, d, True)            # removed at exit
    odd = dict(cycle=11, grouping=[5, 6], downbeat_pulse=6,
               alternative=dict(grouping=[6, 5], downbeat_pulse=0))

    r, _ = run(d, None)
    check("INCONCLUSIVE asks the user", r.returncode and "count" in r.stderr, r.stderr)
    r, _ = run(d, dict(cycle=8, grouping=[4, 4], downbeat_pulse=1))
    check("phrase cycle 8 asks", r.returncode and "--cycle 4" in r.stderr, r.stderr)
    r, F = run(d, dict(cycle=8, grouping=[4, 4], downbeat_pulse=5), "--cycle", 4)
    check("--cycle 4 -> 4/4 as 2+2, downbeat folded", F and F["grouping"] == [2, 2]
          and F["downbeat_pulse"] == 1 and F["time_signature"] == "4/4", F and F["grouping"])
    r, _ = run(d, odd, "--pulse-unit", 8)
    check("ambiguous beat 1 asks", r.returncode and "--use-alternative" in r.stderr, r.stderr)
    r, _ = run(d, odd, "--use-alternative")
    check("odd cycle without pulse unit asks", r.returncode and "eighth" in r.stderr, r.stderr)
    r, F = run(d, odd, "--use-alternative", "--pulse-unit", 8)
    check("11/8 as 6+5 from the alternative", F and F["grouping"] == [6, 5]
          and F["downbeat_times"][0] == 0.0 and F["time_signature"] == "11/8", F and F["grouping"])
    check("Live tempo in quarters", F and abs(F["live_tempo"] - F["bar_bpm"][0] / 2) < 1, F and F["live_tempo"])
    check("drift detected", F and F["tempo_drift_pct"] > 0.3, F and F["tempo_drift_pct"])
    r, _ = run(d, odd, "--grouping", "4,4", "--pulse-unit", 8)
    check("grouping must sum to the cycle", r.returncode and "sums to" in r.stderr, r.stderr)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
