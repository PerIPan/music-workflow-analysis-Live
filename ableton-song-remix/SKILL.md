---
name: ableton-song-remix
description: Use when the user wants an analysed song remixed or sketched in Ableton Live — keeping the original vocal or other stems, with new drums, bass or keys in a new style or tempo.
---

# Song remix in Ableton Live

Builds a Live Session from a song that `song-analysis` has finished:
- **The kept stems** (default: the vocal) are loaded and warped with one marker per
  downbeat, so Live's bar N is the song's bar N. Live's tempo can then move freely.
- **New parts** (drums, bass, keys) follow the chart's chord in every (bar, cell), in the
  song's own meter: 11/8 grouped 6+5 gets an 11/8 groove grouped 6+5.
- **A sketch** plays what the band played (preset `as-analysed`): the kept vocal, the
  original mix muted for A/B, the **drummer's transcribed hits** with their fills and
  dynamics (`drum_hits.json`), the transcribed bass (half-quantized: the push stays), and
  the chart's chords on the **guitar's own strums** (`strum.json`; a strum an 8th before a
  change plays the new chord). Without those files (song-analysis Phase 4b) it falls back
  to a generated drum part with fills at section ends and the chords on keys — robotic;
  run Phase 4b first.

> **Bars, never seconds.** Live beat of (bar, cell) = `(bar − 1 + P) × bar_beats + cell
> offset`, with `bar_beats = beats_per_bar × 4 / pulse_unit` and P the pre-roll bars.

**References (read on demand):**
- `references/presets.md` — the presets, the meter engine, the playability rules, the chord grammar, `--set` knobs
- `references/live-build.md` — the command sequence, warping, scenes, verification, failure modes
- `ableton-mcp` → `references/remote-script-patch.md` — the Remote Script commands this skill needs

## Prerequisites

1. **An analysed song.** The folder needs `analysis/foundation.json` (meter step), the
   stems (`stems/htdemucs_ft/<name>/`) and the chart data file `gen_v<N>.py`. Missing?
   Run `song-analysis` first; a song name is enough (it fetches the recording).
2. **Live 12 running with the patched AbletonMCP Remote Script** (`create_audio_clip`,
   `set_clip_warping`, a working `add_warp_marker`). After patching, restart Live.
   `remix_build.py` stops with exit 3 before writing anything if the patch isn't loaded.
3. **A new, empty Set.** A Set with clips or named scenes is refused (exit 2); `--force`
   appends. Ask for this and step 4 in one message, right before the build.
4. **Auto-Warp Long Samples off** (Live Settings → Record, Warp & Launch) — ask the user
   before the build. Left on, Live adds its own markers seconds after the load; the build
   then clears them and warps the stem again (up to 3 tries, a warning each), which is slower.

## Ask first (one message; defaults in brackets)

1. **Remix or sketch?** [remix]
2. **Style preset:** `house`, `synth-pop`, `lo-fi`, `garage-punk` (sketch: `as-analysed`).
   Propose two that suit the song's tempo and feel; plain words map to `--set` knobs
   (`references/presets.md`).
3. **Tempo:** keep [the song's mean tempo], round it, or a new BPM. A bar stretched more
   than ±15% smears the vocal: the plan stops with NEEDS A DECISION and names the bars.
4. **Stems kept:** [vocals]; add drums, bass or other to keep them (no new part is written
   for a kept role). A guitar- or piano-led song: offer `guitar` / `piano` — they come from
   the extra `htdemucs_6s` run (song-analysis Phase 2; run it first if missing). A guitar
   track playing the chart's chords is the other way: the keys part on a guitar sound.

Say the plan back in one line before building.

## Steps

| Step | Command (scripts in this skill) | Output |
|---|---|---|
| 1 Check | `python3 <skills>/song-analysis/scripts/validate_artifacts.py <song>/analysis` | ok, or run `song-analysis` |
| 2 Plan | `remix_plan.py <song> --mode remix --preset house --tempo keep --keep vocals` | `<song>/remix/<slug>/plan.json` |
| 3 Parts | `remix_parts.py <plan> [--set drums.kick=four]` | `parts.json`, a drum grid per pattern |
| 4 Review | `remix_build.py <plan> --dry-run` | the command list; nothing sent |
| 5 Build | `remix_build.py <plan>` | the Session; `build_report.json` |

Every track gets a starting effects chain by role (vocal/bass/keys: EQ Eight → Compressor;
drums: Drum Buss → EQ Eight; the muted A/B mix stays clean) at Live's defaults — set by ear.
`--no-fx` skips it; `--master` puts EQ Eight → Glue Compressor → Limiter on Live's Master
track (opt-in). The build also lays every section clip onto the Arrangement at its section's
start, so the song plays from bar 1 there (`--no-arrangement`: Session only). Both need
patch 2 and Live 12.3+; with patch 1 the build warns, uses the browser and a `MASTER_BUS` track.

All scripts run with `python3` and the standard library. `NEEDS A DECISION` (exit 2 from
the plan) is a question for the user: ask, then re-run with the answer (`--tempo <BPM>` /
`--stretch-anyway` / `--preroll N`). After any re-run of the plan, re-run step 3: the
build refuses parts made for another plan.

- **Plan:** Live's tempo = the mean of the steady bars (not `live_tempo`); P = 0 unless a
  kept stem sounds before bar 1. Say back the tempo, the stretch range, P and the sections.
- **Parts:** show the printed drum grid; the drum part must pass the playability check.
- **Build:** the order is meter, tempo, tracks, instruments, scenes (FULL + one per
  section), MIDI clips, then the stems (load, warp, markers, loop, section copies).
- **Listen:** fire FULL; check bar 1, a mid-song chorus and the last chorus (drift shows
  late in the song), the chords against the chart, and the drum part with a drummer's eye.
- **Sketch:** run song-analysis Phase 4b first (both stem splits, `drum_transcribe.py`,
  `strum_pattern.py`), then `remix_plan.py <song> --mode sketch` and steps 3–5. Only
  without a drum transcription: pick the drum template from the chart's groove note
  (e.g. `--set drums.kick=four`).

## Hard rules

1. **Never assume 4/4.** Meter, grouping and pulse unit come from `foundation.json`; the
   build sets and reads back the Set's signature before any clip.
2. **Chords come from the chart data file**, never raw `chords_lv.json`. An unknown label
   stops the plan; `N.C.` means bass and keys rest.
3. **Drummer-playable.** The checker must pass: at most 2 hands and one hit per foot per
   onset, one hi-hat voice, a crash replaces the hat, each hand ≤ 16ths (8ths above
   130 BPM), no 32nds, ≤ 2 kicks in a row on 16ths, no tom hit 3 times running.
4. **Check `status` and `result.error`** on every reply; this Remote Script returns some
   failures as success. The build stops on the first failure (exit 1).
5. **Never drive `mcp__ableton__*` tools during a build** — two clients on one Live collide.
6. **Never overwrite the user's work.** New tracks are appended and named `· orig` / `· new`.

## Limits

- **No save or export.** The user saves (Collect All and Save) and exports. Clip
  envelopes may not survive the copy to the Arrangement (none are written by the build).
- **One meter per Set.** The grouping lives in the patterns; irregular single bars aren't
  in the analysis grid, so the remix doesn't have them either.
- **Section scenes start on the section's first bar**, so a vocal pickup sung in the bar
  before is cut there; the FULL scene keeps it.
- **The kept vocal is only as clean as the separation.** Listen to `vocals.wav` alone.
- **Instruments** are searched by name in the user's library; the build reports what
  loaded and warns where nothing did.

## Local environment

Interpreters and song folders: `song-analysis` → `references/environment-setup.md` →
"This machine". Live connection and the patch: `ableton-mcp`.
