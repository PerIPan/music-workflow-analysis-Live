---
name: ableton-mcp
description: Use when controlling Ableton Live through the AbletonMCP server — tracks, clips, scenes, MIDI notes, instruments and effects, device parameters, mixing, automation, tempo or time signature — or when the Live connection or a tool call fails.
---

# Ableton Live via MCP

Claude drives a live Ableton Set through the AbletonMCP server (jpoindexter fork v2.0.0,
128 tools, all prefixed `mcp__ableton__`). Limits below are for this fork.

**References (read on demand):**
- `references/setup-install.md` — first-time install (Remote Script + server + verify)
- `references/troubleshooting.md` — connection failures, tool errors
- `references/als-xml.md` — reading Arrangement content from the saved `.als` (MCP can't)
- `references/remote-script-patch.md` — the local patch that adds audio-file loading and
  working warp commands (`ableton-song-remix` needs it)

For arrangement *craft* (section design, bass/drum patterns, FX chains) use the
`ableton-arrangement` skill; this skill is the mechanics and the gotchas.

## Mental model

- **Live and stateful.** Every call mutates the open Set immediately. No preview/dry-run.
  Undo is Live's own Cmd/Ctrl-Z.
- **Single session.** Controls one Ableton instance — the frontmost open Set. No diffing
  two Sets, no background operation. Two clients on one Live collide; work sequentially.
- **No autosave.** Claude can't save/open/new a Set — the USER Cmd-S's. After a Set
  switch, the server re-attaches to the new frontmost Set.
- **Deferred tools (Claude Code).** Load schemas before first use:
  `ToolSearch select:mcp__ableton__<name>`.
- **Reason in BARS, never seconds.** Sizes and positions are bar counts; convert
  everything to bars up front.

## Tool map

| Area | Representative tools |
|---|---|
| Transport | start/stop_playback, start/stop_recording, set_tempo, set_metronome, jump_to_time, capture_midi |
| Tracks | create_midi/audio/group_track, set_track_name/volume/pan/mute/solo/arm/color, set_track_input/output_routing, delete/duplicate_track, freeze/flatten |
| Clips | create/delete/duplicate/fire/stop_clip, set_clip_name/color/loop/gain/pitch, get_clip_notes |
| MIDI notes | add_notes_to_clip, remove_notes (range), remove_all_notes, transpose_notes, quantize_clip_notes, humanize_clip_timing/velocity |
| Devices / FX | search_browser, load_instrument_or_effect, get/set_device_parameter, toggle/delete_device, move_device_left/right, get_rack_chains |
| Scenes | create/delete/duplicate/fire_scene, set_scene_name/color, get_all_scenes |
| Mixing | set_send_level, get/set_return_volume/pan, set_master_volume/pan |
| Automation | get/set/clear_clip_automation, toggle_session_record, set_overdub |
| AI helpers | get_scale_notes, generate_drum_pattern, generate_bassline |

Most tools take `(track_index, clip_index)` — both **0-based** (Live's UI is 1-based:
"track 3" in the UI = index 2).

## Capabilities vs hard limits (all observed in testing)

**Reachable:** Session-view clip CRUD + MIDI editing, track/scene CRUD, device loading +
any device parameter on regular tracks, transport, mixing/sends, clip automation,
humanize, generative helpers.

**Not reachable — plan around:**
- ❌ Effects on the **Master track** — user adds limiter/EQ manually.
- ❌ **Stamping clips into Arrangement** — only real-time recording reaches Arrangement
  (and session-fire→arrangement-record produced an empty arrangement). Bounce loops via
  **Resample** into a session audio clip, or drag manually.
- ❌ **Firing an empty slot to record** — "click empty slot to record" is UI-only.
- ❌ **Render/export audio** — user does File → Export.
- ❌ **Return-track device parameters** — rejected ("Track index out of range"). Use
  set_return_volume/pan, or move the FX to a regular track.
- ⚠️ **Per-clip mute** — no clean toggle; `set_clip_gain` 0 (reversible) or UI Deactivate.
- ⚠️ **Follow Actions** unreachable — use launch quantization for count-ins/progressions.
- ⚠️ **`set_clip_automation` "Volume"** works on simple instrument tracks; rack-based
  tracks (drum racks, amp racks) often reject it → fall back to per-note velocity or a
  Utility device.
- ⚠️ **No visual feedback** — no screenshot tool. Workaround: macOS `screencapture` +
  Read the PNG.

## Hard rules (gotchas that bite)

1. **Load with `load_instrument_or_effect`**, not `load_item_to_track` (errors "Unknown
   command"). URIs are HTML-encoded: `query:AudioFx#EQ%20Eight`.
   ⚠️ **Its success message lies about the device list** — it returns
   `"Loaded instrument ... Devices on track:"` with the list *empty* even when the load
   worked. Don't retry on the strength of that; confirm with `get_track_info(track_index)`
   and read the `devices` array.
2. **Instruments/presets live under the `sounds` browser category**, not `instruments`
   (returns nothing). Pianos: `query:Sounds#Piano & Keys`; guitars:
   `query:Sounds#Guitar & Plucked`. Use `search_browser(query, category="sounds")`.
   Search matches **literal preset names**, so instrument nicknames miss: `"Rhodes"`
   returns nothing, `"Electric Piano"` finds *Electric Piano Daze*. Search the generic
   name, not the iconic one.
3. **Chunk note pushes ≤140 notes** per `add_notes_to_clip` MCP call (larger has failed
   silently). **Never two pushes to the same clip in one parallel batch** — they race.
   Sequential per clip; parallelize only across different clips. For hundreds of notes use
   the raw-TCP bulk path below (300 per chunk works there).
4. **Reading a big clip can exceed the response token limit.** Generate notes in a
   script → save JSON → push from that. Don't round-trip 500 notes through a read.
5. **`remove_notes(from_time, time_span, from_pitch, pitch_span)` for surgical edits** —
   prefer over `remove_all_notes`. **Always assume the user hand-edited the clip** —
   read or remove-by-range rather than wiping. **`remove_all_notes` only clears 0 → clip
   length**: notes at negative times or past the end survive. To truly clear a clip:
   `remove_all_notes`, then `remove_notes(from_time=-16, time_span=16 + length + 16)`,
   then confirm with `get_clip_notes`.
6. **Effects load at the END of the chain.** Build in order or reorder with
   `move_device_left/right`.
7. **EQ Eight freq is normalized 0–1:** `value = log10(freq/20) / 3` (1 kHz ≈ 0.566,
   250 Hz ≈ 0.366, 130 Hz ≈ 0.271). Band N (A-set) param indices: On `4+(N-1)*10`, Type
   `5+…`, Freq `6+…`, Gain `7+…`, Q `8+…`. Filter types: 0=HP48 1=HP12 2=LowShelf 3=Bell
   4=Notch 5=HighShelf 6=LP12 7=LP48.
8. **Distortion:** `Overdrive` — Drive/Tone/Dry-Wet on 0–100. `Saturator` —
   Drive/Output/Dry-Wet on 0–1, Type 0–7 (hard curve = fuzz). `Pedal`/`Amp` are
   Suite-only — Saturator/Overdrive are the universal fallback.
9. **Creating a track/scene at a low index shifts everything after it.** Re-check indices
   (`get_session_info`) or append at the end (`index = -1`).
10. **Humanize in layers** — `humanize_clip_velocity(~0.08)` + `humanize_clip_timing(~0.04)`;
    apply twice if it still sounds programmed.
11. **Toggles don't tell you the prior state.** `toggle_arrangement_record`,
    `toggle_session_record`, `toggle_device` flip whatever is there. Parse the reply
    ("… is now on/off"); if it's not the state you wanted, toggle again and re-check. Read
    first where a getter exists (`get_metronome_state`).
12. **Warn before arming a track that has Arrangement content.** With arrangement record
    on, Live draws red overdub indicators on those clips — they look like deletion but are
    only a preview. Say so before arming, then confirm with `get_arrangement_length` and
    `get_track_info` that nothing changed. If the user reports "content deleted", verify
    with reads before anyone reaches for undo or reload (unsaved Session work is at risk).
13. **Read clip names before inferring harmony.** Users label clips with the chords
    ("verse – Am Em x 4"). The label gives *which* chords; the note timing gives *bars per
    chord* (the label doesn't — "x 4" can mean 2 bars each). Arrangement clips aren't
    visible over MCP: read the `.als` (`references/als-xml.md`).

## Session-jam patterns (song-agnostic)

- **One scene per feel/groove**; launching a scene starts all its clips bar-quantized.
- **Shared click track** (Simpler + clave at one pitch), a click clip per scene; mute to
  toggle.
- **A REC audio track per live instrument** — armed, monitored, for takes.
- **A muted NOTES track** whose clip *names* carry tips/roadmaps.
- **Count-in without Follow Actions:** click-only clip + 1–2-bar launch quantization;
  fire the groove during the count bar, it drops on the next downbeat.
- **Odd meters:** set the Set's signature over raw TCP (`set_signature`, below) so the
  grid and bar numbers match — one meter per Set. For scenes in different meters, use
  clip length instead: 5/4 = 5-beat clips, 7/8 = 3.5-beat clips — the same length for
  every clip in the scene **including the click**.
- **Whole song in one scene (through-composed):** full-song-length clips per track with
  an energy arc; **leave a track empty for a live player** (e.g. no bass clip for a
  bassist).
- **Label everything:** chords/patterns in `set_clip_name`, matching clip colors,
  paste-ready "Edit Info Text" blocks for the user.

### Working method that scales

Generate notes in a script → save JSON → push over the raw-TCP bulk path (or ≤140-note
MCP chunks) — deterministic, reviewable, revertible. High-pass synths/keys so a live bass owns the lows. Test one
section, get direction, then propagate.

## Timing: seconds → Live beats

Live's tempo and clip positions count **quarter notes**, whatever the meter.
- `set_tempo(pulse_bpm × 4 / pulse_unit)` — with an eighth-note pulse (`pulse_unit` 8),
  halve it; passing the eighth-note pulse straight in doubles the tempo.
- One bar = `beats_per_bar × 4 / pulse_unit` Live beats (4/4 → 4, 7/8 → 3.5, 11/8 → 5.5).
- **Map analysed audio through the real beat grid, not one BPM.** Played music drifts
  (150–171 BPM inside one song has been measured), so `beats = sec × BPM / 60` accumulates
  error over minutes. For a take recorded to Live's click, the fixed formula is exact.

```python
bt = np.asarray(beat_times); n = np.arange(len(bt))           # from foundation.json
def to_live_beats(t, pulse_unit):
    p = np.interp(t, bt, n)                                    # fractional pulse index
    p = np.where(t < bt[0], (t - bt[0]) / (bt[1] - bt[0]), p)  # extrapolate the ends
    p = np.where(t > bt[-1], n[-1] + (t - bt[-1]) / (bt[-1] - bt[-2]), p)
    return np.round(p * 4 / pulse_unit * 4) / 4                # Live beats, 16th grid
```

- **Pre-roll:** anything before the first tracked beat comes out negative, and notes at
  negative clip times never play. Shift the whole part by one bar and lengthen the clip.
- If `foundation.json` reports tempo drift above ~±3%, don't collapse to one BPM: build
  on the warped grid above and tell the user the Live tempo is the median.

## Bulk path: raw TCP on port 9877

The Remote Script takes one JSON command per connection on `127.0.0.1:9877` —
`{"type": <command>, "params": {…}}` — the same commands the MCP tools wrap, plus a few
with no MCP tool. Use it for bulk writes (it keeps thousands of notes out of the
conversation); use MCP tools for reads and verification. Sequential per clip.

```python
import json, socket
def live(cmd, **params):
    with socket.create_connection(("127.0.0.1", 9877), timeout=60) as s:
        s.sendall(json.dumps({"type": cmd, "params": params}).encode())
        buf = b""
        while chunk := s.recv(65536):
            buf += chunk
            try: return json.loads(buf)
            except json.JSONDecodeError: continue
        raise ConnectionError(f"incomplete reply: {buf[:200]!r}")

for i in range(0, len(notes), 300):
    r = live("add_notes_to_clip", track_index=T, clip_index=C, notes=notes[i:i + 300])
    assert r.get("status") == "success", r          # stop on the first failed chunk
```

**`scripts/push_notes.py`** does all of this: chunked push that exits non-zero on the
first failed chunk, `--clear` (including out-of-bounds notes), `--signature 11/8` with
read-back, and `--from-seconds foundation.json` for the beat-grid mapping and pre-roll
above. Standard library only; tested against a mock socket
(`tests/test_push_notes.py`).

**Time signature** (no MCP tool): `live("set_signature", numerator=11, denominator=8)`,
then read it back with `live("get_signature")` (verified on Live 12.4). It sets one global
meter for the Set —
the Live Object Model has no API for meter changes along the Arrangement.

**Audio files and warping — patched Remote Script only** (raw TCP, no MCP tool;
`references/remote-script-patch.md`, then restart Live): `create_audio_clip {track_index,
clip_index, file_path}` loads a file into an empty Session slot; `set_clip_warping` (Live
defers it — read back with `get_clip_info`); a working `add_warp_marker {beat_time,
sample_time}` (seconds) and `move_warp_marker {beat_time, distance}`; `set_clip_warp_mode`
with Live's real indices (`complex_pro` = 6; the stock script sends 5 = REX). These raise
real errors. `get_capabilities` → `remix_patch: 1` tells a patched script from the stock
one ("Unknown command") without writing anything. On the stock script never pass
`complex_pro`, and don't call `add_warp_marker`, `create_locator` or `delete_locator`.

## Local environment (this machine)

- `.mcp.json` in `~/dev/abletonAI/` runs `~/dev/abletonAI/.venv-ableton-mcp/bin/ableton-mcp`:
  the fork installed editable (branch `mcp-sdk-compat`, SDK 1.30.0 — see setup-install.md);
  Remote Script from the same checkout installed.
- Recording session output to audio: empty-slot record needs a UI click — use Resample
  workflow instead.
- Source doc (read-only): `~/dev/abletonAI/audio-analysis/WORKFLOW-ableton-mcp.md`.
