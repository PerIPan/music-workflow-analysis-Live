---
name: song-analysis
description: Use when a song recording has to become tempo, time signature, key, stems, a bass line, chords per bar, lyric timing, a drum-pattern read, or a chord+lyric chart for a band — including songs in odd or unknown meters.
---

# Song Analysis — recording → bars, chords, lyrics, chart

Song-agnostic pipeline, validated over many real projects (dream pop, Greek laiko, punk
reinterpretations, drone/devotional). Works for any song, genre, key or meter.

**Deliverable:** one self-contained HTML per song — the chord+lyric chart plus the
commentary (Phase 8). The JSON artifacts are working files, not the answer.

**References (read on demand):**
- `references/meter-detection.md` — how the meter sweep works, reading its output, calibration
- `references/stems.md` — separation options, speeds, cache, quality checks
- `references/chord-proposal.md` — chord benchmark, the triad cross-check, the major-bias trap
- `references/chart-and-lyrics.md` — chart structure, the lyric-placement rules, HTML output
- `references/drum-pattern-analysis.md` — kick/snare pattern reading; optional ADTOF
- `references/modal-theory.md` — the 7 modes and the mode test, power chords, Byzantine ≠ Phrygian
- `references/lead-and-keys-extraction.md` — isolated guitar/piano lines via `htdemucs_6s`
- `references/environment-setup.md` — venvs, pinned versions, folder layout, this machine

## Inputs

1. **Audio** — mp3/wav of the full mix. **Only a name?** Phase 0 fetches the recording
   (opt-in; the user confirms the pick before anything is downloaded).
2. **Lyrics** — canonical text from an official source. Section labels (Verse, Chorus,
   Bridge…) come from this, not from the analyzer. **Not supplied? Get them before
   Phase 1** — Phase 6 needs them and a late search stalls the run.
   `scripts/lyrics_from_page.py <URL> --out lyrics.txt --chords-out analysis/tab_chords.json`
   moves a lyrics or chord-tab page's text into the song folder and prints only counts.
   **Never retype lyrics through your own output** — copyrighted text is blocked
   ("Output blocked by content filtering policy") and search tools won't reproduce it
   either. If a site answers 403/404, search for another (songlyrics.com,
   lyricsondemand.com, the band's Bandcamp, a chord-tab site). Such text is unofficial:
   say so in the provenance. Whisper only times it (Phase 6); use Whisper's text as the
   lyrics only when no page has the song.

## Tool per step

| Phase | Tool | Output |
|---|---|---|
| 0 Audio (optional) | **`scripts/fetch_audio.py`** (yt-dlp: YouTube Music first; the user confirms the pick) | `<Artist> - <Title>.wav`, `source.json` |
| 1 Pulse + key | **`scripts/foundation.py pulse`** (madmom beats + CNN key) | `foundation.json` (step 1) |
| 2 Stems | **demucs `htdemucs_ft -d mps`** | `stems/htdemucs_ft/<song>/` |
| 3 Meter | **`scripts/detect_meter.py`** → **`scripts/foundation.py meter`** | `meter.json`, `foundation.json` (step 2) |
| 4 Bass, tonic, mode | **`scripts/bass_notes.py`** (pyin) → **`scripts/mode_test.py`** | `bass.mid`, `bass_per_cell.json`, `mode.json` |
| 4b Performance | **`scripts/drum_transcribe.py`** (ADTOF) + **`scripts/strum_pattern.py`** | `drum_hits.json`, `drums.mid`, `strum.json` |
| 5 Lyrics | **`scripts/whisper_gated.py`** (gated by the vocal stem; stem and mix) | `lyrics.json`, `lyrics_mix.json` |
| 6 Sections | **`scripts/align_lyrics.py`** (canonical lyrics ↔ word times) | `lyrics_aligned.json`, `sections.json` |
| 7 Chords | **`scripts/lv_chords.py`**, cross-checked by **`scripts/chord_proposal.py`**, then **`scripts/tab_compare.py`** | `chords_lv.json`, `chord_proposal.json` |
| 8 Chart | **`scripts/stem_activity.py`** → **`scripts/chart_html.py`** (per-song data file) | `stem_activity.json`, `band_level.json`, self-contained **HTML** chart |

`<venv>` = the analysis venv; Whisper, lv-chordia and yt-dlp have their own
(`references/environment-setup.md`). Below, `ST=stems/htdemucs_ft/<song>`. After any
phase, `scripts/validate_artifacts.py analysis` checks the hand-offs (grid, grouping,
cell coverage, time order) — run it before building on a result.

**Run order.** Start stems (Phase 2) in the background first — several songs one after
another, not at once, on one GPU — and do Phase 1 and the lyrics meanwhile. Whisper
(Phase 5) needs only the vocal stem: background it while the meter is settled. Everything
keyed by `(bar, cell)` — lyric alignment, chords, mode — waits for the **downbeat check**
in Phase 4; moving beat 1 afterwards means re-running all of it.

## Phase 0 — Audio from a song's name (optional)

Only when the user names a song instead of giving a file; needs the yt-dlp venv
(`references/environment-setup.md`, step 6).

```bash
<ytdlp-venv>/bin/python scripts/fetch_audio.py --artist="<Artist>" --title="<Title>" \
    --out-dir="<song folder>" [--duration=<length of the user's copy, s or m:ss>]
```

YouTube Music first (the labels' own uploads), then YouTube; uploads titled live, cover,
karaoke, remix, sped up and the like are rejected, the rest ranked — 5–10 s, nothing
downloaded. Spell the names properly (they name the WAV); Greek matches in either
alphabet. `--duration` settles it: the label's or the artist's upload within ~2 s of the
user's copy comes first.
1. Tell the user the `* top pick` line — title, channel, length, album and year — and wait
   for a yes. Label uploads sharing a title can be different recordings (a live album, a
   re-recording, a budget compilation): name the album. Not label audio, or "misses a word
   of the song"? Show the top three and let the user choose.
2. On a yes, run the printed command; for another candidate, change its `--url=` (and
   `--artist=` if the performer differs). It writes `<Artist> - <Title>.wav` and
   `source.json` (URL, channel, format, dates, licence) into the song folder; cite it in
   the chart's provenance line (`references/chart-and-lyrics.md`).
3. Fetch only what the user has the right to study: YouTube's Terms restrict downloading.
   No cookies or logins, ever.

## Phase 1 — Pulse and key (no meter assumed)

```bash
<venv>/bin/python scripts/foundation.py pulse <song.mp3> --out analysis/foundation.json
```

Tracks beats with **no bar assumption** — never pass `beats_per_bar=(3, 4)`: a constrained
candidate list can't say "neither", so it returns the least-bad option with full
confidence and every bar count inherits it. Writes `pulse_bpm`, `beat_times`,
`key_top2` and `tempo_octave`: a pulse above 160 BPM is flagged as probably eighth notes
(a 91 BPM soul track was tracked at 182), one below 70 as possibly half-time. If the
user's count disagrees, re-run with `--min-bpm`/`--max-bpm` to force the other octave.
A GRID REPAIR over a long stretch (a quiet intro) is the same slip — check the octave.
**Cross-check online:** look the song up on songbpm.com and tunebat.com (page tools work
there). They catch a gross error, but often list the doubled octave (a song at 87 shown as
174, "87 half-time") and the melody's key — they don't decide the octave or the tonic;
note what they say in the provenance.

**Key: the top two are the melody's key, not the tonic.** The madmom CNN beats chroma +
Krumhansl by ~20 MIREX points and fixes relative-major/minor flips, but knows only 24
major/minor keys, and its probability is not a confidence on modal or drone material (a
Lydian track came out as the wrong key at p = 0.59). After Phase 4, take the pitch class
the bass sustains longest: if it disagrees, trust the pedal as the tonic and name the mode
with the mode test (`references/modal-theory.md`).

## Phase 2 — Stems

**Decide the split from the purpose, early** (ask with the inputs if unclear: chart only,
drums/bass, or the guitar/piano parts too — e.g. for a Live sketch or remix):

| Purpose / song | Run | Keep |
|---|---|---|
| **default** (a full analysis, a Live sketch or remix) | `htdemucs_ft`, **then** `htdemucs_6s` | the four from `_ft` + only `guitar.wav` / `piano.wav` from `_6s` |
| only a chart, the drums or the bass, and the user says so | `htdemucs_ft` (4 stems) | all four |

The 4-stem `_ft` is the cleaner split (vocals, drums, bass): never replace it with the
6-stem run, which bleeds keys into the bass. In `other.wav` the guitars, keys and pads are
one mix, so a guitar-led song needs the extra run.

```bash
ffmpeg -v error -i <song.mp3> -c:a pcm_s16le /tmp/<song>.wav     # decode first (see below)
demucs -n htdemucs_ft -d mps -o stems /tmp/<song>.wav   # → $ST/{bass,drums,vocals,other}.wav
demucs -n htdemucs_6s -d mps -o stems /tmp/<song>.wav   # guitar/piano songs: keep only
                                                        # stems/htdemucs_6s/<song>/{guitar,piano}.wav
```

**Decode MP3 to WAV first:** demucs 4.1 reads MP3 without the gapless trim, so every stem
starts 25 ms late against the mix — enough to smear bass and beat timing. `-d mps` on Apple
Silicon (otherwise CPU, ~3× slower). A fetched WAV needs no decode: copy it to
`/tmp/<song>.wav` (a name without spaces, so `$ST` needs no quoting). **Check the model cache first** —
uncached, `htdemucs_ft` downloads 4 × 84 MB silently. Listen to `bass.wav` alone: piano or
guitar in it means separation struggled. Faster/other options and timings:
`references/stems.md`.

## Phase 3 — Meter (sweep every cycle, then decide)

```bash
<venv>/bin/python scripts/detect_meter.py <song.mp3> --drums $ST/drums.wav \
    --bass $ST/bass.wav --other $ST/other.wav \
    --foundation analysis/foundation.json --json analysis/meter.json
<venv>/bin/python scripts/foundation.py meter [--pulse-unit 8] [--use-alternative | --cycle N ...]
```

The sweep folds band-limited onsets onto every period 2–25 and ranks by accent contrast;
songs without a kit still carry the cycle in the bass and harmony, so always pass
`--bass` and `--other`. It reports a cycle, the downbeat (counted with the kick) and the
main split (`grouping`, e.g. 6+5) — or **INCONCLUSIVE**.

If the sweep is INCONCLUSIVE or the pulse is slow, it also tries a 2× (eighth-note) grid
— a half-time grid hides odd cycles — and prints the result with the command to adopt it.
It warns when successive beat intervals run in a 3:2 ratio: the tracker may be following
aksak groups (2+2+3) as uneven beats.

`foundation.py meter` then writes `beats_per_bar`, `pulse_unit`, `time_signature`,
`grouping`, `downbeat_times`, `num_bars`, `bar_bpm`, `tempo_drift_pct` (spread of the middle
90% of bars), `tempo_outlier_bars` (more than 5% off) and `live_tempo`. A tracker that drops
a tempo octave for a stretch is repaired in Phase 1 (`grid_repair` lists where).
**It stops with a question instead of guessing** — put that question to the user and
re-run with their answer: INCONCLUSIVE (count along), a phrase-length cycle (8/16 → 4/4?),
a bare duple (2/4 or 4/4?), two equally strong accents (which one is beat 1?), or an odd
cycle (eighth or quarter pulse — 11/8 vs 11/4 doubles Live's tempo). INCONCLUSIVE with
one band clear (often the bass, when the kit enters late) — put that band's cycle and
beat 1 to the user as the proposal, then `--cycle`/`--downbeat-pulse`. Reading the sweep,
calibration, and why beat trackers' own downbeats aren't used:
`references/meter-detection.md`.

**Four-on-the-floor kits** (kick on every beat) give the kick band no cycle, so the sweep
reports INCONCLUSIVE or a bare duple; the bass and harmonic bands carry the meter, and a
2-and-4 backbeat can't tell pulse 0 from pulse 2. When you must pick beat 1 yourself,
weigh (strongest first): the first full-band hit at the song's start (a drum-only pickup
before it is common); the phase where bass and chords change (Phase 4 downbeat check).
Cymbal accents alone are weak — a crash pattern can sit on beat 3. `--cycle` and
`--downbeat-pulse` are recorded as `user` in `provenance`; if you chose them, not the
player, say so in the chart header and list it as an open question.

**Cells.** Everything downstream (bass, chords, lyrics, chart) is keyed by `(bar, cell)`,
one cell per group in `grouping`: 4/4 → 2+2 (the familiar half-bars), 3/4 → one cell,
6/8 → 3+3, 11/8 as 6+5 → two unequal cells. Never split an odd bar at its midpoint.

**Sanity checks:** `tempo_drift_pct` above ~3% means one BPM misplaces notes by the end —
place them through the beat grid (`ableton-mcp` → "Timing"). Watch half/double time on
slow songs (60–90 BPM) — count along. A `num_bars` far from
`duration ÷ (beats_per_bar × beat)` means rubato, a wrong tempo octave or a wrong meter.

## Phase 4 — Bass, tonic and mode

```bash
<venv>/bin/python scripts/bass_notes.py $ST/bass.wav --foundation analysis/foundation.json \
    --bass-entry-bar <N> --outdir analysis
<venv>/bin/python scripts/mode_test.py --other $ST/other.wav \
    --foundation analysis/foundation.json --bass-cells analysis/bass_per_cell.json \
    [--sections analysis/sections.json] --out analysis/mode.json
```

`bass_notes.py`: **pyin** (why not CREPE: the `bass-transcribe` skill) → `bass.mid` and
each pitch class's sounding time per `(bar, cell)`. basic-pitch only if the part is
polyphonic.

**Downbeat check — before anything else keyed by bar.** `bass_notes.py` counts where in
the bar the bass changes pitch. If a later cell takes most changes (a loop moving on beat
3 of 4/4), it prints `DOWNBEAT CHECK` with the corrected `--downbeat-pulse`: re-run
`foundation.py meter` with it, then `bass_notes.py`. The one legitimate exception is
harmony deliberately pushed off beat 1 — confirm with the song-start hit before shifting.
 **The tonic is the pitch class the bass sustains longest** — not the key
estimate. `mode_test.py` then names the mode by dueling characteristic degrees bar by bar
(3 vs ♭3, 4 vs ♯4, 7 vs ♭7, 2 vs ♭2, 6 vs ♭6); a degree that doesn't sound doesn't vote,
so a drone with no 6th reports "6th undetermined" instead of a guess. On a player-verified
Lydian track: tonic E (57% of bass time), ♯4 in 32/32 bars — where the key CNN said G♯
minor. With `sections.json` it runs per section and flags a tonic change only if it holds
8+ bars. Method: `references/modal-theory.md`.

**Spell pitch classes from the key signature.** Flats for flat and neutral keys; sharps
for sharp keys — in F♯ minor a flat table writes the tonic `G♭m` and the dominant `D♭7`.

- Sub-0.5 s detections are noisy; ≥ 0.7 s sustained notes are usually right.
- Bass pedals, walks, sits on 3rds/5ths — it's a *clue* to the root, not the chord.
- **Bass enters late** in most songs: `bass_notes.py` prints `BASS ENTRY: bar N` when it
  finds one — re-run it with `--bass-entry-bar N` and pass the same to `chord_proposal.py`
  (earlier notes are stem bleed).

## Phase 4b — Performance: the drummer's hits and the guitar's strumming

```bash
<adtof-venv>/bin/python scripts/drum_transcribe.py $ST/drums.wav \
    --foundation analysis/foundation.json                 # → drum_hits.json, drums.mid
<venv>/bin/python scripts/strum_pattern.py stems/htdemucs_6s/<song>/guitar.wav \
    --foundation analysis/foundation.json [--sections analysis/sections.json] # → strum.json
```

A chart says which chord; a band (and a Live sketch) also needs **how** it's played.
`drum_transcribe.py` labels every hit (ADTOF: kick, snare, hat, toms, cymbals; the stem
is peak-normalised first) with a velocity from the stem, and lists the **fill bars** — a
tom when toms are rare; twice the usual tom bar when the drummer grooves on the toms (a
surf beat put toms in half the bars); or a crowded last beat. On the first two songs they
sat before section changes. It can't tell crash from ride well (one cymbal class). A
guitar under 4 attacks a bar holds its chords (reverb, surf): no strum pattern is read. `strum_pattern.py` snaps the
guitar's onsets to the 16ths of each bar and prints each section's pattern (`D`/`U` by
the hand-motion convention, not measured) — on its first song it showed the verse push on
4& the player described. Both keep every hit's real time and strength for the sketch.
Skip 4b when the purpose is only a chart.

## Phase 5 — Lyric timing (Whisper, gated by the vocal stem)

```bash
<whisper-venv>/bin/python scripts/whisper_gated.py $ST/vocals.wav [--language en] \
    --out analysis/lyrics.json
<whisper-venv>/bin/python scripts/whisper_gated.py $ST/vocals.wav --mix <song.mp3> \
    [--language en] --out analysis/lyrics_mix.json          # when canonical lyrics exist
```

An RMS gate on the vocal stem, fed to Whisper as `clip_timestamps`, keeps it from
transcribing silence; the script also sets large-v3-turbo's word-alignment heads and drops
words whose *whole* span is silent. **Which audio to transcribe is song-dependent:**
measured with this exact setup on 6 benchmark songs, the vocal stem averaged 19.8% word
error and the full mix 23.6%, but either one won by up to 25 points on single songs
(published results favouring the mix used Whisper without the gate). With canonical
lyrics, transcribe both and let Phase 6 keep the one matching more of the lyrics — that
picked the better transcription every time (17.9%). Without lyrics, use the vocal stem.
Force `--language` when detection wobbles (chant, non-English). Keep repeated lines —
mantras are lyrics — until Phase 6 has aligned them. Whisper invents subtitle phrases over
music ("Thanks for watching"): known ones are dropped, and `CHECK BY EAR` names any short
phrase standing alone in an instrumental stretch.

Map each word to a bar:

```python
def locate(t, downbeats, beats_per_bar):     # from foundation.json — never assume 4
    for i in range(len(downbeats)-1):
        if downbeats[i] <= t < downbeats[i+1]:
            return (i+1, (t - downbeats[i]) / (downbeats[i+1] - downbeats[i]) * beats_per_bar)
    return None
```

## Phase 6 — Sections (canonical lyrics aligned to the word times)

```bash
python3 scripts/align_lyrics.py --lyrics lyrics.txt --words analysis/lyrics.json \
    --words analysis/lyrics_mix.json --foundation analysis/foundation.json
    # keeps the better transcription → lyrics_aligned.json, sections.json
```

Keeps the **canonical text** and borrows only Whisper's times: a monotonic alignment with
fuzzy word matching (accents and Greek final sigma normalised) pairs canonical words with
heard words; dropped lines — normal on repeats — get times interpolated between matched
neighbours, and lines under 30% matched are flagged; `SUNG, NOT IN THE TEXT` names Whisper
words sung just before a line that the page left out ("I'm coming back…" written
"Coming back…") — check by ear, add them. In `lyrics.txt` a blank line starts a
section and a `[Chorus]` line labels it; each section gets its first line's time and
`(bar, cell)`. On the benchmark, 83% of line starts landed within 1 s (median error
~0.5 s) and 98% of section starts within 2 s. Automatic segmentation can *suggest* boundaries, never decide them:
`as_seg` (barwise CBM on this song's own bars, `penalty_weight=0`) hit 80% of
lyric-anchored boundaries within ±1 bar on the one reference song with section truth,
27% within ±0.5 s.

## Phase 7 — Chords (lv-chordia, cross-checked)

```bash
<venv>/bin/python scripts/chord_proposal.py --other $ST/other.wav --bass $ST/bass.wav \
    --foundation analysis/foundation.json --bass-entry-bar <N> \
    --out analysis/chord_proposal.json                           # triad cross-check
<lv-venv>/bin/python scripts/lv_chords.py <song.mp3> --foundation analysis/foundation.json \
    --compare analysis/chord_proposal.json --out analysis/chords_lv.json
```

**lv-chordia is the provisional primary reading** — it names 7ths and inversions, which
the triad method can't, and led it on all three benchmark songs (two scored against
another automatic tool, one against a player's ear; `references/chord-proposal.md`). Three
songs is a small sample: it is weakest on rare qualities, and anything beyond 7ths
(add9, ♯11) is untested — read those by ear. Run it on the **full mix**.

**The triad method is the independent cross-check** (bass-root constraint with slash
relaxation, major bias **0**, flip count, per-cell margin). `--compare` lists cells where
the two disagree on the root — check those by ear with the Trap 1 tests.

**Read first, then check against a tab** (when `lyrics_from_page.py` found one):
`tab_compare.py --tab analysis/tab_chords.json --chords analysis/chords_lv.json
--sections analysis/sections.json --bass analysis/bass_per_cell.json` lists per section
the chords only in the tab (never in the bass → a passing chord over a held bass, or
wrong), only in ours (a tab simplification?), and the same root with the other third.
A tab is a second opinion — often simplified or transposed — never the chart's source;
name it and the agreement in the provenance, and its disagreements in the open questions.

**Where the bass drops out, agreement proves little.** In a breakdown both readers hear
only the upper voices, and chords sharing them pass for each other: both said Am where the
player heard G (a chorus-2 turnaround, bass out) — the parallel chorus-1 bar, with bass,
read G. In bass-less cells, chart what the parallel section plays and list it for the ear.

## Phase 8 — Chart

```bash
<venv>/bin/python scripts/stem_activity.py $ST --foundation analysis/foundation.json \
    --out analysis/stem_activity.json            # per-bar stem levels for the song map,
                                                 # + band_level.json: the band's stops
python3 scripts/chart_html.py gen_v1.py          # in the song folder; --out to write elsewhere
```

The chart is rendered: you write the decisions (sections, a chord per `(bar, cell)`, each
lyric line at its anchor cell, the header, provenance and commentary) as a `SONG` dict in
`gen_v<N>.py` (a new N per revision); `chart_html.py` reads everything measured from
`analysis/`, so a re-run that keeps the bar grid needs only a re-render (a moved beat 1
shifts every key). Chords may be `chords_lv.json`'s labels (`A:min`, `G/b7`): the renderer
converts them. Read `references/chart-and-lyrics.md` first. Core invariants:
- Each section starts a new row; parallel sections get identical row splits.
- Chart bar = audio bar; the renderer adds none (a final chord may ring on the bar that
  starts at the last downbeat).
- **Every word sits where it is sung** (Rule 1, player-checked): a word held across a
  half-bar boundary, sung within a dotted eighth before it, sits after it ("…once more"
  on the next bar's chord); stop bars (the band out under the voice) are greyed, with no
  "?". `placement: 'anchor'` (pickups pulled into the chord the phrase resolves into) only
  if the band asks for it.
- **Show the evidence:** the `provenance` line says where meter, grouping and mode came
  from (`foundation.json` → `provenance`, `mode.json`); the renderer marks "?" where a
  cell's own reading names another root, so the player's check goes where it's needed.
- The commentary (`notes`): per-section harmonic notes in scale degrees,
  arrangement/groove notes (entries, drops, turnarounds), and the open questions for the
  player (every call you made that the player hasn't confirmed).

**Player check — ask, don't wait.** A "?" in a printed chart waits for someone to notice
it; a player on their instrument answers in seconds. After rendering, run
`python3 scripts/chart_questions.py gen_v1.py` (the open cells: chart chord, what
lv-chordia, the triads and the bass heard, the parallel section's chord) and ask the
player directly, up to four cells per round, the chart's chord first; ask the same way
about `SUNG, NOT IN THE TEXT` words and the lines it lists as `placement check` (Whisper
heard under half of them — on Body Heat the bridge, placed one to two beats early, line
after line, until the player pinned each word: `'fixed'` lyrics). Put each answer in the
data file (a fix in `chords`, the cell in `verified`, a word in the lyrics), re-render, and
say in `provenance` what the player checked. On Body Heat six cells took one round, and
the chart printed with no "?".

**What next (Live optional).** Only if the Live skills are installed and
`mcp__ableton__health_check` answers, ask once: "The chart is done. Want a **sketch in
Live** (the vocal on Live's grid, the chart's chords, the bass line and a drum part, the
original mix muted for A/B) or a **remix** (keep the vocal; new drums, bass and keys on
these chords in a style you pick), or stop here?" Both are `ableton-song-remix` (sketch =
`--mode sketch`); they need Live 12 and the patched Remote Script
(`ableton-mcp/references/remote-script-patch.md`). Otherwise stop at the chart.

## Benchmark

`bench/run_bench.py` scores the artifacts against local ground truth (never committed):
meter by bar length in seconds (so tempo octave doesn't matter), grouping, chords with
mir_eval, section boundaries, mode, lyric WER and line timing. Set `$MWS_BENCH_ROOT` to
the folder with `manifest.json`; `--baseline` fails on a 2-point drop. Human ceiling for
chords: expert annotators agree on 73% (maj/min) / 54% (full labels) of segments.

## Hard rules — the cardinal traps

### Trap 1 — A bass walk is one chord or two; the upper voicing decides

Bass moving within a bar (`C → A♭`) has two readings, and both are common: one held chord
over a moving bass (`Cm/A♭`, or a drone with a walking bass), or **two chords**
(`Cm → A♭`). The bass alone can't tell them apart, and a bass-constrained matcher follows
the bass, so it reports two chords either way. Look above the bass:
- **Re-attack** — a new voicing struck where the bass moves = two chords.
- **Register-pooled chroma** — pool chroma per cell in the chord instrument's register
  (high-pass above ~165 Hz). The pitch-class set changes with the bass = two chords; it
  stays put = one chord over a moving bass.

### Trap 2 — "Minor key" ≠ minor chords

Key estimators report the **melody's mode**, not chord quality. Many songs put major
triads under a minor melody — the bittersweet sound. Never propagate the key label to
chord quality; test each chord (major vs minor third, `chord-proposal.md`). Modal songs
often pivot between relative major and minor — label the key as a pair (`E♭ / Cm`).

### Trap 3 — The meter you never tested for looks like no meter at all

An odd cycle folded onto the wrong period gives a **flat** profile, not a low one — 11
folded onto 2, 3, 4 or 6 smears to near-uniform. Uniform contrast everywhere means the
right period hasn't been tested yet, never "no time signature". Assume odd meters are
live (`references/meter-detection.md`).

**Verify with a player.** Automated signals are wrong ~30% of the time on modal-mixture
songs. A musician who knows the song is ground truth — plan a verification pass before
declaring the chart done.

## Lessons learned

1. Trust the user's ear over any analyzer. Ask them to count — a player's count settles
   in seconds what a sweep can only rank. When the player says "I think" or "not sure"
   and the bass and both readers agree against it, show that evidence (the bass note, the
   vocal stem's level per beat for a word's place) before changing the chart — a player
   heard A on two bars whose bass plays C, then asked to check, and the C stood.
2. Never hand an analyzer a candidate list it can't say "none of these" to — a constrained
   `beats_per_bar` and a key-gated major bias both produced confident wrong answers that
   survived every downstream check.
3. Chord-recognition tools are starting points, never ground truth.
4. Whisper timing is precise to the consonant; the singer pushes into the beat — place
   by timing plus the push (Rule 1), and score any placement change against the player's
   corrections before showing a new chart. A lyrics page can drop sung words:
   `align_lyrics.py` prints `SUNG, NOT IN THE TEXT`.
5. `basic-pitch` duplicates notes at exact octaves and invents low-register content the
   stem doesn't contain. Floor it at the instrument's range (C3 for a piano out of
   `other.wav`) before pushing anything to Ableton.
6. A chart correction is a data-file edit (chords, sections, lyric anchors) plus a
   re-render; the renderer redoes the rows and the lyric cascade.
7. Mirror parallel sections visually; overlay section-boundary pickups in the same cell.

## Local environment

Venvs, interpreters and cached models on this machine: `references/environment-setup.md`
→ "This machine". Scripts here supersede the older helpers in the tooling root.
