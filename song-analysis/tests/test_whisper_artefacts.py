#!/usr/bin/env python3
"""Test whisper_gated.drop_artefacts and lonely_phrases on invented word lists.

Run with the Whisper venv (the module imports mlx): <whisper-venv>/bin/python tests/test_whisper_artefacts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from whisper_gated import drop_artefacts, lonely_phrases  # noqa: E402


def W(*items):
    return [dict(word=w, start=s, end=s + 0.3) for w, s in items]


def main():
    song = W(("the", 10), ("river", 10.4), ("runs", 10.8), ("slow", 11.2), ("tonight", 11.6))
    ghost = W(("Satsang", 40), ("with", 40.5), ("Mooji", 41))
    thanks = W(("Thanks", 80), ("for", 80.3), ("watching!", 80.6))
    kept, gone = drop_artefacts(song + ghost + thanks)
    cases = [
        ("known artefacts dropped", [w["word"] for w in kept], [w["word"] for w in song]),
        ("dropped words carry a reason", {g["reason"] for g in gone}, {"whisper artefact"}),
        ("a real line is untouched", len(drop_artefacts(song)[1]), 0),
        ("a word merely containing 'with' stays", len(drop_artefacts(W(("with", 1), ("you", 1.4)))[1]), 0),
        ("a lone short phrase is flagged", [p[2] for p in lonely_phrases(song + W(("oh", 30), ("yeah", 30.4)) +
                                                                          W(("come", 50), ("home", 50.4), ("now", 50.8), ("and", 56), ("stay", 56.4)))],
         ["oh yeah"]),
        ("a sung passage is not flagged", lonely_phrases(song), []),
    ]
    fails = 0
    for name, got, want in cases:
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f": got {got!r}, want {want!r}"))
        fails += not ok
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
