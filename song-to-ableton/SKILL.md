---
name: song-to-ableton
description: Use when the user wants an existing song rebuilt, covered or reinterpreted in Ableton Live — analysis feeding a Live build, end to end. For analysis alone use song-analysis; for a take the user played, bass-transcribe. To keep the original vocal or stems (a remix or a sketch), ableton-song-remix.
---

# Song → Ableton (end-to-end orchestrator)

```
  existing audio ──▶  A. ANALYSIS                      ──▶  C. HANDOFF      ──▶  B. ABLETON (MCP)
                      stems · bars/BPM/key · chords          bars + chords +      build/reinterpret:
                      · bass MIDI · lyrics · drum read        drum logic           tempo · clips · MIDI
                                                                                   · devices · scenes · mix
```

**ASK FIRST:** "Do you want song analysis, Ableton building, or both?" Then route only
to what's needed.

> **GOLDEN RULE: reason in BARS, never seconds.** Every length and position is a bar
> count (1, 2, 4, 8, 16, 32…). Convert any "first 16 seconds" to bars and stay in bars.

## Routing

| Need | Skill |
|---|---|
| Analyze the recording (tempo/bars, stems, chords, lyrics, drum read, chart) | `song-analysis` |
| Drive Live — tracks, clips, notes, devices, mixing; connection issues | `ableton-mcp` |
| Arrangement craft — sections, bass/drum patterns, FX chains, dynamics | `ableton-arrangement` |
| The user plays bass (or another mono instrument) and wants it as MIDI | `bass-transcribe` |
| **Remix or sketch an analysed song**: the original vocal (or any stems) warped onto Live's bar grid, new drums/bass/keys on the chart's chords, or a sketch as analysed with the mix muted for A/B | `ableton-song-remix` |

## The handoff (analysis output → Ableton input)

| Analysis output | Use in Ableton |
|---|---|
| `pulse_bpm`, `pulse_unit`, `beats_per_bar`, `num_bars` | `set_tempo(pulse_bpm × 4 / pulse_unit)` — Live's tempo counts quarter notes. One bar = `beats_per_bar × 4 / pulse_unit` Live beats (4/4 → 4, 7/8 → 3.5, 11/8 → 5.5); size clips in whole bars |
| `chords_lv` (checked by `chord_proposal`) per `(bar, cell)` | chord clips on a synth/keys track; the band chart is `song-analysis` Phase 8 (`chart_html.py`) |
| `bar_bpm`, `tempo_drift_pct` | above ~±3% drift, place notes through the beat grid, not one BPM (`ableton-mcp` → "Timing") |
| bass MIDI (root line) | reference clip — or **leave the bass slot empty** for a live bassist |
| drum-pattern read | match the original's kick/snare logic (or `generate_drum_pattern`); never impose a rock backbeat on a non-rock song |
| key/mode | scale + voicings (mind major-triads-under-minor-melody — Trap 2 in `song-analysis`) |
| section map | scenes (jam) or arrangement sections; mirror parallel sections |

**Reinterpreting in a new genre:** keep the **harmonic + rhythmic skeleton** (chords per
bar, original drum logic, section lengths) from analysis; change instrumentation and
energy in Ableton. Analysis says *what the song is*; the build decides *how it sounds*.
When the original vocal (or other stems) should stay in, use `ableton-song-remix`: it
builds the whole Session from the chart in scripts. A **sketch** (the song as analysed:
vocal on the grid, the mix muted for A/B, the chart's chords, the transcribed bass, a drum
part) is its `--mode sketch`. With stems on the grid, Live's tempo is the plan's tempo
(the mean of the steady bars), not `pulse_bpm`.

## Quickstart

1. Drop `<song>.mp3` + `lyrics.txt` in a song folder.
2. Run the `song-analysis` pipeline: pulse + key (`foundation.py pulse`) → stems
   (`htdemucs_ft`) → **meter sweep, then `foundation.py meter` (never assume 4/4 — answer
   its questions with the user)** → bass via pyin → lyrics (`whisper_gated.py`) → chords
   (`lv_chords.py`, cross-checked by `chord_proposal.py`).
3. Open Ableton; verify the MCP connection (`health_check` — see `ableton-mcp`).
4. Build, e.g.: "At <BPM> in <key>, build a Session scene with these chords per bar
   <chord_proposal>, a drum pattern matching <kick/snare logic>, and leave the bass slot
   empty for me to play."

## Troubleshooting (route, don't debug here)

- Noisy bass MIDI → pyin, not basic-pitch or CREPE; bass bleed → `htdemucs_ft` + suppress
  pre-bass-entry bars; too few snares detected → `delta≈0.15`, un-normalized envelope
  (all in `song-analysis`).
- Can't connect / tools missing / device errors → `ableton-mcp`
  references/troubleshooting.md.

## Local environment

Interpreters and song folders: the `song-analysis` skill's
`references/environment-setup.md` → "This machine". Live connection: the `ableton-mcp`
skill.
