---
name: bass-transcribe
description: Use when the user has played bass or another single-note instrument (or sung a line) and wants the take as a MIDI file, an Ableton Live clip, or a tab/chart.
---

# Bass Transcribe — played take → MIDI / Live clip / chart

Default for bass is the offline **pyin** pipeline. For vocals and expressive leads (sax,
synth lead) switch to **CREPE** (§2b). For in-Live plugin options (NeuralNote, Jam Origin)
read `references/realtime-options.md`.

**Why pyin, not CREPE, for bass:** in a side-by-side A/B in Live on a separated bass stem,
the CREPE line was rejected by ear ("CREPE is not for bass") — it over-segments a
slow-moving line into spurious adjacent notes. Published evidence agrees: pYIN beats CREPE
on bass lines because CREPE's training set has almost no sub-bass examples (Araz, ISMIR
2021 LBD), and no public pitch benchmark covers the bass register. pyin is also ~30×
faster. On vocals the same A/B went the other way — CREPE caught quiet, legato notes pyin
dropped.

## 1. Get the audio

- **User points at a file** — wav/mp3/aiff of the take. Mono preferred; DI cleaner than mic.
- **Record in Live** — audio track, arm, record the take. MCP **cannot export audio**:
  the user does File → Export, or point at the raw recording under the Set's
  `Samples/Recorded/` folder.
- Ask for (or detect) the take's **BPM** if the output will go into a Live clip.

## 2. Default pipeline — pyin → MIDI

```python
import librosa, numpy as np, pretty_midi

y, sr = librosa.load(AUDIO, sr=22050, mono=True)
HOP = 256                                                    # 11.6 ms
f0, voiced, vprob = librosa.pyin(y, sr=sr, fmin=40.0, fmax=220.0,   # E1 … A3
                                 frame_length=4096, hop_length=HOP)
t = librosa.times_like(f0, sr=sr, hop_length=HOP)
rms = librosa.feature.rms(y=y, frame_length=4096, hop_length=HOP)[0]
rms = rms / (rms.max() + 1e-9)

VPROB, MIN_LEN, GAP = 0.55, 0.10, 0.05   # voicing gate, min note s, bridgeable dropout s
pitch = np.where(voiced & (vprob >= VPROB),
                 np.round(librosa.hz_to_midi(np.nan_to_num(f0, nan=40.0))), -1).astype(int)
notes, cur = [], None
for i, (ti, p) in enumerate(zip(t, pitch)):
    if cur and p == cur['p']:
        cur['end'], cur['i1'] = ti, i                        # same pitch: extend
        continue
    if cur and p < 0 and ti - cur['end'] <= GAP:
        continue                                             # short dropout: bridge it
    if cur and cur['end'] - cur['start'] >= MIN_LEN:
        notes.append(cur)                                    # pitch change / long gap: close
    cur = {'p': p, 'start': ti, 'end': ti, 'i0': i, 'i1': i} if p >= 0 else None
if cur and cur['end'] - cur['start'] >= MIN_LEN:
    notes.append(cur)

pm = pretty_midi.PrettyMIDI()
inst = pretty_midi.Instrument(program=33)                    # Electric Bass (finger)
for n in notes:
    vel = int(np.clip(50 + 70 * rms[n['i0']:n['i1'] + 1].mean(), 35, 120))
    inst.notes.append(pretty_midi.Note(velocity=vel, pitch=n['p'],
                                       start=n['start'], end=n['end']))
pm.instruments.append(inst)
pm.write(OUT_MID)
```

Tuning knobs: `fmin=36` for drop-D (D1), `fmin=30` + `frame_length=8192` for a 5-string
low B; `fmax` up to ~400 Hz only for high solos (a wider range invites octave jumps);
`VPROB` up to 0.6–0.7 for noisy takes; `MIN_LEN` down to 0.06 for fast lines. Measured on
separated bass stems: ~13 s for a 2-minute song on an M3.

## 2b. Vocals and expressive leads — CREPE

Same segmentation, with CREPE's confidence in place of `vprob`:

```python
import crepe
y16, _ = librosa.load(AUDIO, sr=16000, mono=True)
t, freq, conf, _ = crepe.predict(y16, 16000, model_capacity='full', viterbi=True, step_size=10)
# pitch = where(conf >= 0.55, round(hz_to_midi(freq)), -1); then the loop above
```

`full` + viterbi is deterministic on CPU. Expect more notes than pyin, including breaths
and glottal onsets — post-filter sub-100 ms notes. CREPE `full` runs at ~1× real time; for
a quick preview, **SwiftF0** (`swift-f0==0.3.0`, ONNX, ~250× real time) agrees with it within
50 cents on 97–99% of frames both call voiced — but it voices only 27–80% of the frames
CREPE does, dropping exactly the quiet, sparse singing CREPE was chosen for. A sung line is never the
tonic source: on a drone track the singer never held the tonic, and the melody's longest
pitch class was the 2nd.

## 2c. Octave cross-check (when a line looks wrong, or on drone material)

Run a second tracker, band-limited to the same range, and flag where the two disagree by
more than 50 cents — don't auto-correct; listen to those spots.

```python
import crepe.core as cc
y16, _ = librosa.load(AUDIO, sr=16000, mono=True)
act = cc.get_activation(y16, 16000, model_capacity='tiny', step_size=10, verbose=0)
cents = np.linspace(0, 7180, 360) + 1997.3794084376191           # CREPE bin → cents
act[:, (cents < 1200 * np.log2(40 / 10)) | (cents > 1200 * np.log2(220 / 10))] = 0
f_crepe = 10 * 2 ** (cc.to_viterbi_cents(act) / 1200)            # band-limited Viterbi
t_crepe = np.arange(len(f_crepe)) * 0.01
# compare with pyin's f0 on t_crepe where both are voiced; flag |Δ| > 50 cents
```

Zeroing the out-of-band bins *before* Viterbi keeps the decoder inside the bass range
(filtering afterwards can't). `tiny` is ~17× faster than `full`. On separated bass stems
this flagged ~4% of frames on a busy line — almost all exact-octave splits — and ~9% on a
drone, where the disagreements also include harmonic locks, not just octaves.

## 3. Cleanup rules

- **Drop blips** < 80 ms (tracker flicker, fret noise).
- **Octave sanity**: 4-string bass ≈ MIDI 26–67 (drop-D D1 … 24th-fret G4). Tracker
  octave errors land a 5th/octave out — flag and correct outliers to the nearest
  in-range octave.
- **Legato-join** same-pitch notes split by < 50 ms gaps.
- **Ghost notes / slides** show as short low-confidence fragments — either drop (chart
  use) or keep (feel/groove analysis). Ask which the user wants.
- **Double-stops or chords played?** pyin is monophonic and will pick one note — rerun
  with **basic-pitch** (`basic-pitch <out_dir> <audio> --save-midi`) for those passages.

## 4. Outputs

1. **`.mid` file** — the pipeline's direct product; drag into any DAW.
2. **Live clip** via the `ableton-mcp` skill: convert seconds → Live beats. For a take
   recorded to Live's click, `beats = sec × BPM / 60` is exact; for a take played free or
   a song stem, map through the beat grid (`ableton-mcp` → "Timing: seconds → Live
   beats"). Size the clip in **BARS** (round up to 1/2/4/8…), push over the raw-TCP bulk
   path (or `add_notes_to_clip` in ≤140-note chunks — never two pushes to the same clip
   in parallel).
3. **Tab / chart** — bass tab or bar chart generation: chart craft lives in the
   `song-analysis` skill (`references/chart-and-lyrics.md`); pitch-class per `(bar, cell)`
   aggregation as in its Phase 4.

## 5. Verify before declaring done

Report note count, pitch range, and duration vs. take length. Sanity signals: a bass
take yields roughly 1–4 notes/second; a pitch histogram dominated by 2–5 pitch classes
(the song's roots). Wildly more notes → the `VPROB` gate is letting flicker through;
wildly fewer → gate too high, the take is quieter than expected, or the part is a drone
(few long notes is a legitimate answer).

## Local environment

Run with the analysis interpreter listed in the `song-analysis` skill's
`references/environment-setup.md` → "This machine" (librosa, crepe, basic-pitch,
pretty_midi).
