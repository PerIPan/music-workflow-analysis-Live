#!/usr/bin/env python3
"""Test scripts/align_lyrics.py: canonical text keeps its words, Whisper gives the times.

Synthetic song: three sections (one labelled), a mantra line repeated four times of
which Whisper keeps only two, a misheard word, a Greek line with accents and final
sigma, and a hallucinated word in a gap. Run: python3 tests/test_align_lyrics.py
"""
import atexit, json, shutil, subprocess, sys, tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "align_lyrics.py"
LYRICS = """Lay awake at night
Wondering how could I

[Chorus]
Om shanti om
Om shanti om
Om shanti om
Om shanti om

Σε αγαπώ πολύ
Let it get this way
"""
# (word, start) as Whisper might return them: misheard "wandering", only 2 of 4 mantra
# repeats, a hallucinated "thank" in a gap, Greek without accents
WHISPER = [("Lay", 10.0), ("awake", 10.4), ("at", 10.8), ("night", 11.0),
           ("Wandering", 12.0), ("how", 12.5), ("could", 12.8), ("I", 13.1),
           ("Om", 20.0), ("shanti", 20.4), ("om", 20.9),
           ("thank", 22.0),
           ("Om", 24.0), ("shanti", 24.4), ("om", 24.9),
           ("σε", 40.0), ("αγαπω", 40.4), ("πολυ", 41.0),
           ("Let", 44.0), ("it", 44.3), ("get", 44.5), ("this", 44.8), ("way", 45.0)]


def main():
    d = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, d, True)            # removed at exit
    (d / "l.txt").write_text(LYRICS, encoding="utf-8")
    json.dump({"words": [dict(word=w, start=t, end=t + 0.3) for w, t in WHISPER]},
              open(d / "w.json", "w"), ensure_ascii=False)
    json.dump({"downbeat_times": [8.0 + 2.0 * i for i in range(30)], "grouping": [2, 2]},
              open(d / "f.json", "w"))
    r = subprocess.run([sys.executable, str(SCRIPT), "--lyrics", str(d / "l.txt"),
                        "--words", str(d / "w.json"), "--foundation", str(d / "f.json"),
                        "--out", str(d / "a.json"), "--sections", str(d / "s.json")],
                       capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode:
        print(r.stderr); sys.exit(1)
    L = json.load(open(d / "a.json"))["lines"]
    S = json.load(open(d / "s.json"))["sections"]
    fails = 0
    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{info}]"))
    check("canonical text kept (all 8 lines)", len(L) == 8, len(L))
    check("misheard word still matches its line", L[1]["start"] == 12.0, L[1]["start"])
    check("mantra repeats kept, in order", [l["text"] for l in L[2:6]] == ["Om shanti om"] * 4)
    starts = [l["start"] for l in L[2:6]]
    check("dropped repeats get interpolated times between neighbours",
          all(s is not None for s in starts) and starts == sorted(starts), starts)
    check("Greek line matched despite accents / final sigma", L[6]["start"] == 40.0, L[6]["start"])
    check("section labels + start times", [(s["label"], s["t"]) for s in S] ==
          [("S1", 10.0), ("Chorus", 20.0), ("S3", 40.0)], [(s["label"], s["t"]) for s in S])
    check("sections carry (bar, cell)", S[1]["where"] == [7, 1], S[1]["where"])
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
