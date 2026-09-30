# Presets, meter engine, playability, chord grammar

Everything here lives in `scripts/remix_parts.py` (presets as data in `PRESETS`) and
`scripts/chordsym.py`.

## Presets

Each part plays one pattern per energy tier (1–3); tier 0 rests. Tiers come per bar from
the original stem that part replaces (drums → drums, bass → bass, other → keys), relative
to that stem's 90th percentile (≥ 0.75 → 3, ≥ 0.45 → 2, ≥ 0.12 → 1), smoothed over 2-bar
blocks from each section start. Without `stem_activity.json`, the section kind decides
(intro 1, verse 2, post 2, chorus 3, bridge 1, inst 2, outro 1). Where the old drums stop,
the new ones stop.

| Preset | Drums (tier 1 → 3) | Bass | Keys | Swing / humanize |
|---|---|---|---|---|
| `house` | four-on-the-floor kick, open hat on the offbeats; + clap backbeat and quiet closed 16ths | root hold → offbeat 8ths | pad → offbeat stabs | 0.54 / 2 ms |
| `synth-pop` | backbeat kick, 8th hats; + snare; 16th hats at tier 3 | root hold → 8ths → octave 8ths | pad → 8th arpeggio | 0.50 / 3 ms |
| `lo-fi` | kick on 1, half-time snare; backbeat, 8th hats, ghost snares at tier 3 | root hold → long root + approach note | rootless pad → comping | 0.58 / 12 ms |
| `garage-punk` | backbeat, 8th hats → ride; fills every 8 bars | root hold → 8ths | power chords, one per cell | 0.50 / 6 ms |
| `as-analysed` (sketch) | bar-start kick → backbeat + 8th hats | the transcribed line (`bass_notes.json`) | the chart's chord once per cell | straight, none |

- Crashes (with a kick) land on section starts at tier ≥ 2 and after every fill; the crash
  replaces the hat at that onset.
- Fills: the last unit of the bar (at most 2 beats), snare → high → mid → low tom, 16ths
  up to 130 BPM, 8ths above, hands alternating.
- 16th hats fall back to 8ths above 130 BPM (one hand can't keep 16ths there).
- The instrument search tries `search` names in order (drums in the `drums` category, bass
  and keys in `sounds`); edit the preset to match the user's library.

## `--set` knobs (remix_parts.py)

| Key | Values |
|---|---|
| `drums.kick` | `four` (every felt beat), `backbeat` (unit starts), `sparse` (bar start) |
| `drums.snare` | `backbeat` (unit ends), `clap`, `half` (first beat of the second metric unit: beat 3 in 4/4, eighth 7 in 11/8 6+5), `none` |
| `drums.hats` | `8`, `16`, `tactus`, `offbeat` (open hat), `offbeat+16`, `ride8` |
| `bass.pattern` | `root_hold`, `tactus_root`, `drive8`, `offbeat8`, `octave8`, `lofi`, `as-analysed` |
| `keys.rhythm` | `pad`, `block`, `stab_off`, `arp8`, `comp` |
| `keys.voicing` | `close`, `rootless`, `power` |
| `swing`, `humanize_ms`, `fills` (0 none, −1 section ends, N every N bars), `crash`, `ghosts`, `kick_run` | numbers |

A `drums.*`, `bass.*` or `keys.*` key sets every tier. The user's words map onto them:
"keep the bass line" → `bass.pattern=as-analysed` (or `--keep vocals,bass`), "straight" →
`swing=0.5`, "busier drums" → `drums.hats=16`, "kick on every beat" → `drums.kick=four`.
Say back any word that has no knob.

## Meter engine

- **Pulse** = one step of the grouping: a quarter (pulse_unit 4) or an eighth (8).
- **Felt beats (tactus):** quarter pulses are each a beat; eighth-pulse groups split into
  2s and 3s — 2 → 2, 3 → 3, 4 → 2+2, 5 → 3+2, 6 → 3+3, 7 → 2+2+3, 8 → 3+3+2, 9 → 3+3+3.
- **Units** (for the backbeat): if every group is one felt beat (6/8, 12/8, 7/8), the bar's
  beats split into 2s and 3s; otherwise each group's beats do. Kick on a unit's first beat,
  snare on its last.

| Meter (grouping) | Felt beats (Live beats) | Backbeat |
|---|---|---|
| 4/4 (2+2) | 1 1 1 1 | K S K S |
| 3/4 (3) | 1 1 1 | K . S |
| 5/4 (3+2) | 1 × 5 | K . S K S |
| 6/8 (3+3) | 1.5 1.5 | K S |
| 7/8 (2+2+3) | 1 1 1.5 | K . S |
| 12/8 (3+3+3+3) | 1.5 × 4 | K S K S |
| 11/8 (6+5) | 1.5 1.5 \| 1.5 1 | K S \| K S — kick on eighths 1 and 7, snare on 4 and 10 |

**Swing** moves only the subdivision under the pulse (8ths under a quarter pulse, 16ths
under an eighth pulse), so the pulse grid — and every odd-meter group — never moves.
Validation runs on the straight grid, before swing and humanize. Humanize never moves a section's downbeat or a crash landing, so each section clip starts with its downbeat.

## Playability check (`validate_drums`)

Feet: kick (36) right, hi-hat pedal (44) left; every other hit needs a hand.
1. Per onset (±5 ms): at most 2 hand hits, one hit per foot, one hi-hat voice (42/44/46),
   no crash with a hat or ride.
2. Hands are assigned greedily (cymbals right, drums left, switching when a hand is busy);
   each hand's hits at least a 16th apart up to 130 BPM, an 8th above.
3. Both hands together never faster than 16ths (no 32nds), except a flam grace note
   (velocity ≤ 60, ≤ 35 ms before its main note).
4. At most 2 kicks in a row on 16ths (`kick_run`; garage-punk 3); no tom 3 times running.

A violation exits 1 naming the chart bar, the beat and the rule.

## Bass and keys

- **Segments:** consecutive cells in one bar with the same chord; each pattern starts on
  the segment, so every chord change is played.
- **Bass:** E1–G2 (MIDI 28–43), nearest to the previous note; slash chords play the slash
  note; the chart's `bass_notes` hints win in their cell.
- **Keys:** chord tones in E3–E5 (52–76), the inversion with the least movement from the
  previous voicing, pulled toward MIDI 64. The 5th goes first when a chord has more than 4
  tones; the 3rd and the 7th always stay. Slash chords voice the upper chord.

## Chord grammar (`chordsym.py`, closed)

- Root `A`–`G` with `#`/`b` (or ♯/♭).
- Qualities: `` `m` `min` `-` `dim` `°` `aug` `+` `sus2` `sus4` `sus` `5` `6` `m6` `6/9`
  `7` `maj7` `M7` `Δ7` `Δ` `m7` `mMaj7` `m(maj7)` `m7b5` `ø` `ø7` `dim7` `°7` `7sus4` `9`
  `maj9` `m9` `add9` `add2` `madd9` `11` `m11` `13`.
- Alterations `b5 #5 b9 #9 #11 b13 add9 add11`, bare or in parentheses.
- Slash bass: `/` + a note name (`Em/D`, `D/F#`; `C6/9` is one chord). `N.C.`/`NC` = rest.
- Anything else stops the plan with the bar, cell and label — fix the chart, never guess.
