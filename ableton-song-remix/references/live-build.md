# The Live build: grid, warping, scenes, verification

## Grid and tempo (remix_plan.py)

- `bar_beats = beats_per_bar × 4 / pulse_unit` (4/4 → 4, 6/8 → 3, 7/8 → 3.5, 11/8 → 5.5);
  cell lengths are the grouping's groups × 4 / pulse_unit (11/8 as 6+5 → 3.0 + 2.5).
- **Live tempo T.** `keep` = `60 × Σ bar_beats / Σ bar seconds` over the bars not in
  `tempo_outlier_bars`, rounded to 0.01. Not `live_tempo`: that is a median of beat gaps on
  madmom's 10 ms grid and runs 1–2% off on real songs. `round` = the nearest whole BPM.
- **Stretch per bar** `r = T × bar seconds / (bar_beats × 60)`. Any bar beyond ±15%
  (a rubato intro, a fermata, a far tempo) is NEEDS A DECISION: stretch anyway or pick
  another tempo.
- **Pre-roll P.** 0 when every kept stem is below −45 dBFS before bar 1 (then chart bar =
  Live bar). Otherwise the fewest whole bars that hold the pickup; more than 4 is NEEDS A
  DECISION, and an explicit `--preroll N` (0–8) is the answer. Every Live position then
  shifts by P bars, and the plan says so.
- **Warp map.** One point per downbeat: `(downbeat seconds, (k + P) × bar_beats)`, the
  same for every stem (they share demucs's timeline), plus the end of a last bar that rings
  past the final downbeat when the file covers it. The sketch's MIX is the source mp3 on
  the same map; an mp3 decoder delay (up to ~25 ms) shows as a flam against the vocal. If
  the A/B check hears one, load a WAV decoded the same way demucs read the file.
- **Parts belong to one plan.** `parts.json` carries the plan's fingerprint (`plan_key`);
  after any re-run of the plan, re-run `remix_parts.py`, or the build refuses the parts.

## Command sequence (remix_build.py)

One JSON command per connection to `127.0.0.1:9877`; each reply must be `status: success`
with no `result.error`.

| Step | Commands |
|---|---|
| probe (read-only) | `health_check`; `get_capabilities` (needs `remix_patch ≥ 1`, else exit 3); `get_session_info`; `get_all_scenes`; `get_track_info` per track (clips → exit 2 unless `--force`) |
| meter, tempo | `set_signature` → `get_signature` (compare); `set_tempo` → `get_session_info` (±0.01) |
| tracks | per stem `create_audio_track` + `set_track_name` (`VOX · orig`; the sketch's `MIX · orig (A/B)` also `set_track_mute`); per part `create_midi_track` + `set_track_name` (`DRUMS · new (house)`) |
| instruments | per part, each preset name in turn: `search_browser` → `load_browser_item` → poll `get_track_info` until a device shows (the load reply can't be trusted; a timeout is polled, never re-sent) |
| scenes | row 0 = FULL, row s = section s; missing rows `create_scene`; `set_scene_name` (`Verse 1 · bars 5-20`) |
| MIDI | FULL: `create_clip` (whole song) + `add_notes_to_clip` × 300-note chunks + `set_clip_name`; each section: its notes shifted to 0 in a section-long clip (looping by default; humanize never moves a section downbeat, and a note up to 0.05 beat early still opens its section); no notes → no clip, so launching the scene stops that track |
| stems | `create_audio_clip` into the FULL slot (a timeout is polled with `get_clip_info`); `set_clip_warping` (a separate command: Live defers it; read back); `set_clip_warp_mode` (vocals/other/bass/mix `complex_pro`, drums `beats`); the markers (below); `set_clip_loop` 0 → song length; `set_clip_start_marker` 0 (`get_clip_info` read-back: `loop_end`, `loop_start`, `start_marker`; a mismatch is a warning); then per section `duplicate_clip` (lands in the next empty slot below = that section's row) + `set_clip_loop` + `set_clip_start_marker` to the section |

**Warp markers** (per stem): wait until Live has finished with the file (`get_clip_info`
`sample_length` above 0 and two `get_warp_markers` reads alike) → `delete_warp_marker`
every visible marker but the first (the last one is hidden; leave it) → `move_warp_marker`
the first onto the plan's grid (its sample time mapped through the warp map; before bar 1
that is a negative beat) → `add_warp_marker {beat_time, sample_time}` for every downbeat
after it, in order, then for every downbeat before it (Auto-Warp can put Live's first
marker on a later onset), right to left → `get_warp_markers` again: every planned marker
within 0.001 beat and 0.001 s, and no other marker except one past the last downbeat (the
hidden end). Once all stems are in, every stem's markers are read once more.

## After the build

- `build_report.json` beside the plan: tracks, instruments that loaded, markers per stem,
  warnings (a FULL loop end, loop start or start marker that Live clamped, an instrument
  not found).
- Launch FULL: every track plays the whole song in sync. Section scenes loop their section.
- Recording to the Arrangement, saving, the Master limiter and export are the user's.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| exit 3 "not patched" | the stock Remote Script, or Live not restarted after the patch | apply `ableton-mcp/references/remote-script-patch.md`, restart Live |
| exit 2 "Set is not empty" | clips or named scenes already there | a new Set, or `--force` to append |
| "parts.json was made for another plan" | the plan was re-run after the parts | re-run `remix_parts.py` on the plan, then the build |
| `add_warp_marker` fails mid-stem | a marker out of order with Live's own (Auto-Warp left markers the build didn't clear, or Live's hidden end marker sits before the song's end), or a segment outside 5–999 BPM | read `get_warp_markers` and note it in the report; turn Auto-Warp Long Samples off (Settings → Record, Warp & Launch), open a new Set and re-run the build |
| `move_warp_marker` refused | Live won't put the first marker at a negative beat | rerun the plan with `--preroll 1`, then `remix_parts.py` again, in a new empty Set |
| read-back names missing or extra markers | a marker skipped, or Live added one (late Auto-Warp) | check `get_warp_markers` against `plan.json`; Auto-Warp off, a new Set, re-run |
| WARNING FULL `loop_start` / `start_marker` ≠ 0 | Live clamped the loop to the sample's first frame (pre-roll ≥ 1) | the FULL stem is off against the MIDI: re-plan with `--preroll 0` (then `remix_parts.py`), a new Set |
| no instrument on a track | the preset's names aren't in this library | load one by hand, then edit the preset's `search` list |
