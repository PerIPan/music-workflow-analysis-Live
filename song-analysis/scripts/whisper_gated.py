#!/usr/bin/env python3
"""Phase 5: lyric word timing with mlx-whisper, gated on where the vocal stem is sung.

An RMS gate on the separated vocal stem becomes Whisper's clip_timestamps, so
Whisper never transcribes silence. By default the vocal stem is also what gets
transcribed; --mix transcribes the full mix instead (still gated by the stem).
Measured with this exact setup on 6 Jam-ALT English songs: vocal stem 19.8% WER vs
full mix 23.6%, but the better source differs per song (by up to 25 points either
way). With canonical lyrics, transcribe both and let align_lyrics.py keep the one
that matches more of the lyrics (17.4% mean WER). Published results that favour the
mix (arXiv 2408.06370, 2506.15514) used Whisper without this gate. Also sets
large-v3-turbo's curated word-alignment heads, which mlx-whisper does not set
itself, and drops words whose whole span lies outside the gate.

Usage (the Whisper venv; Apple Silicon, needs mlx-whisper + librosa):
    <whisper-venv>/bin/python whisper_gated.py stems/htdemucs_ft/<song>/vocals.wav \
        [--mix <song.mp3>] [--language en] [--gate 0.1] [--out analysis/lyrics.json]
"""
import argparse, re, json
import numpy as np
import librosa
import mlx.core as mx
import mlx_whisper
from mlx_whisper.transcribe import ModelHolder

REPO = "mlx-community/whisper-large-v3-turbo"     # large-v3 = extra ~3 GB, no gain
TURBO_HEADS = b"ABzY8j^C+e0{>%RARaKHP%t(lGR*)0g!tONPyhe`"   # openai-whisper's mask
HOP = 512


def sung_clips(y, sr, gate):
    """RMS gate -> padded [start, end] clips: merge gaps < 1 s, cap 30 s, pad 0.4 s."""
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=HOP)[0]
    t = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP)
    sung = rms > gate * rms.max()
    segs, start = [], None
    for ti, on in zip(t, sung):
        if on and start is None: start = ti
        if not on and start is not None: segs.append([start, ti]); start = None
    if start is not None: segs.append([start, t[-1]])
    merged = []
    for s0, e0 in segs:
        if merged and s0 - merged[-1][1] < 1.0 and e0 - merged[-1][0] <= 30:
            merged[-1][1] = e0
        else:
            merged.append([s0, e0])
    dur = len(y) / sr
    # pad: sung onsets often lead the audible voice
    return [(max(0.0, s0 - 0.4), min(dur, e0 + 0.4)) for s0, e0 in merged], t, sung


# Phrases Whisper learned from subtitle credits and video outros; it emits them over music.
ARTEFACTS = ("thanks for watching", "thank you for watching", "please subscribe",
             "subscribe to", "subtitles by", "amara.org", "satsang with mooji",
             "transcribed by", "captions by")


def _key(w):
    return re.sub(r"[^\w\s.]", "", w.lower())


def drop_artefacts(words):
    """Remove runs of words that spell a known Whisper artefact (see ARTEFACTS)."""
    keys, bad = [_key(w["word"]) for w in words], set()
    for i in range(len(words)):
        for ph in ARTEFACTS:
            n = len(ph.split())
            if " ".join(keys[i:i + n]) == ph:
                bad.update(range(i, i + n))
    return ([w for i, w in enumerate(words) if i not in bad],
            [dict(words[i], reason="whisper artefact") for i in sorted(bad)])


def lonely_phrases(words, gap=10.0, max_words=4):
    """Short phrases with no other word within `gap` s on either side: (start, end, text)."""
    out, i = [], 0
    while i < len(words):
        j = i
        while j + 1 < len(words) and words[j + 1]["start"] - words[j]["end"] < gap:
            j += 1
        before = words[i]["start"] - words[i - 1]["end"] if i else gap
        after = words[j + 1]["start"] - words[j]["end"] if j + 1 < len(words) else gap
        if j - i + 1 <= max_words and before >= gap and after >= gap:
            out.append((words[i]["start"], words[j]["end"], " ".join(w["word"] for w in words[i:j + 1])))
        i = j + 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("vocals", help="separated vocal stem - drives the gate (and is "
                                   "transcribed unless --mix is given)")
    ap.add_argument("--mix", help="transcribe the full mix instead, still gated by the stem")
    ap.add_argument("--language", help="force it when auto-detect wobbles (chant, non-English)")
    ap.add_argument("--gate", type=float, default=0.1, help="fraction of max RMS counted as sung")
    ap.add_argument("--out", help="write words JSON here")
    a = ap.parse_args()

    y, sr = librosa.load(a.vocals, sr=16000, mono=True)
    clips, t, sung = sung_clips(y, sr, a.gate)
    ModelHolder.get_model(REPO, mx.float16).set_alignment_heads(TURBO_HEADS)
    res = mlx_whisper.transcribe(
        a.mix or a.vocals, path_or_hf_repo=REPO, word_timestamps=True,
        clip_timestamps=[x for c in clips for x in c],
        condition_on_previous_text=False,          # avoids hallucination drift
        hallucination_silence_threshold=2.0, language=a.language)

    def in_gate(w):                                # judge the WHOLE span, not the start
        m = (t >= w["start"]) & (t <= w["end"])
        return bool(m.any() and sung[m].any())

    allw = [dict(word=w["word"].strip(), start=round(w["start"], 3), end=round(w["end"], 3),
                 probability=round(w.get("probability", 0.0), 3))
            for seg in res["segments"] for w in seg.get("words", [])]
    words = [w for w in allw if in_gate(w)]
    dropped = [w for w in allw if not in_gate(w)]
    words, ghosts = drop_artefacts(words)
    dropped += ghosts
    for ph in lonely_phrases(words):
        print(f"CHECK BY EAR: '{ph[2]}' at {ph[0]:.1f}-{ph[1]:.1f} s stands alone "
              f"(>= 10 s from any other word) - a Whisper invention in an instrumental?")
    sung_s = sum(e - s for s, e in clips)
    print(f"{len(clips)} sung clips, {sung_s:.0f}/{len(y) / sr:.0f} s; "
          f"{len(words)} words kept, {len(dropped)} dropped as silence"
          f"{f' or known artefacts ({len(ghosts)})' if ghosts else ''}; "
          f"language {res.get('language')}")
    if a.out:
        json.dump(dict(model=REPO, source="mix" if a.mix else "vocals",
                   language=res.get("language"), clips=clips,
                       words=words, dropped=dropped), open(a.out, "w"),
                  indent=1, ensure_ascii=False)


if __name__ == "__main__":
    main()
