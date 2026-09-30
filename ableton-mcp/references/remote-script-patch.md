# Remote Script patch: audio loading and warping (for ableton-song-remix)

The stock AbletonMCP Remote Script can't load an audio file, can't switch Warp on, and its
`add_warp_marker` calls a method Live doesn't have. `ableton-song-remix` needs all three.
The patch is `remote-script-remix.patch` beside this file (a diff of
`AbletonMCP_Remote_Script/__init__.py` against upstream ableton-mcp `main`, MIT-licensed).

- **Apply:** `git -C <your ableton-mcp clone> apply <this repo>/ableton-mcp/references/remote-script-remix.patch`,
  then **restart Live** (it loads Remote Scripts at start-up).
- **Check:** the raw-TCP command `get_capabilities` → `{"remix_patch": 1, ...}`.

## Commands after the patch

| Command | Params | Live API | Notes |
|---|---|---|---|
| `get_capabilities` | — | none (read-only) | `{"remix_patch": 1, "commands": [...]}`; the stock script answers "Unknown command" |
| `create_audio_clip` | `track_index, clip_index, file_path[, name]` | `ClipSlot.create_audio_clip(path)` (Live 12) | audio track, not frozen, empty slot, an existing absolute path ending .wav/.aif/.aiff/.flac/.mp3/.ogg; returns `sample_rate`, `sample_length`, `warping` |
| `set_clip_warping` | `track_index, clip_index, warping` | `Clip.warping` | Live defers it: read back with `get_clip_info` before the next warp command |
| `add_warp_marker` (fixed) | `track_index, clip_index, beat_time[, sample_time]` | `Clip.add_warp_marker(Live.Clip.WarpMarker(beat_time=b, sample_time=s))` | `sample_time` in seconds; omitted → `beat_to_sample_time(b) / sample_rate` (as Ableton's MxDCore does). Raises if Live didn't add it (the sample time must lie between the neighbours'; segments 5–999 BPM) |
| `move_warp_marker` | `track_index, clip_index, beat_time, distance` | `Clip.move_warp_marker(beat_time, distance)` | raises if no marker at `beat_time` or the move didn't take |
| `set_clip_warp_mode` (fixed) | `track_index, clip_index, warp_mode` | `Clip.warp_mode` | names per the LOM: beats 0, tones 1, texture 2, repitch 3, complex 4, rex 5, complex_pro 6. The stock script mapped `complex_pro` to 5 (REX) and silently took unknown names as Beats; now they are errors, and a mode not in `available_warp_modes` too |
| `get_clip_warp_info` (fixed) | — | — | the name table now includes `rex`, so index 6 reads `complex_pro` |
| `get_clip_info` (extended) | `track_index, clip_index` | `Clip.sample_length`, `Clip.sample_rate` | audio clips also return `sample_length` and `sample_rate` (0 or changing while Live still decodes the file) |

All of them raise on failure, so the reply is `status: error` with the reason — not an
error hidden inside a success reply, as other commands in this script still do (check
`result.error` on every reply anyway).

## The code (what the patch does)

1. At the top: `import Live`, and
   ```python
   WARP_MODE_NAMES = ["beats", "tones", "texture", "repitch", "complex", "rex", "complex_pro"]
   AUDIO_FILE_EXTS = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg")
   ```
2. In the socket-thread `elif` chain (next to `get_all_track_names`):
   `elif command_type == "get_capabilities": response["result"] = {"remix_patch": 1, ...}`.
3. Add `"create_audio_clip", "set_clip_warping", "move_warp_marker"` to the list of
   state-changing commands **and** a branch for each in `main_thread_task` (a command in
   only one of the two answers "Unknown command").
4. The methods:
   ```python
   def _create_audio_clip(self, track_index, clip_index, file_path, name=None):
       slot = self._validate_clip_slot(track_index, clip_index)
       track = self._song.tracks[track_index]
       # refuse: not track.has_audio_input, track.is_frozen, slot.has_clip,
       # a relative / missing path, a non-audio extension
       slot.create_audio_clip(file_path)
       ...                                  # return sample_rate, sample_length, warping

   def _add_warp_marker(self, track_index, clip_index, beat_time, sample_time=None):
       clip = self._warped_audio_clip(track_index, clip_index)   # raises if not warped audio
       if sample_time is None:
           sample_time = clip.beat_to_sample_time(beat_time) / float(clip.sample_rate)
       clip.add_warp_marker(Live.Clip.WarpMarker(beat_time=beat_time, sample_time=sample_time))
       # raise unless a marker now sits at beat_time

   def _move_warp_marker(self, track_index, clip_index, beat_time, distance):
       clip = self._warped_audio_clip(track_index, clip_index)
       clip.move_warp_marker(beat_time, distance)                # raise unless it moved

   def _set_clip_warping(self, track_index, clip_index, warping):
       self._validate_clip_slot(track_index, clip_index).clip.warping = bool(warping)
   ```
   and in `_set_clip_warp_mode` look the name up in `WARP_MODE_NAMES` (raise on an unknown
   name or a mode outside `clip.available_warp_modes`).

## Still broken in the stock script (not patched)

- `create_locator` ignores its time and name and toggles a cue at the playhead;
  `delete_locator` writes a read-only property. Don't call either.
- No command stamps a Session clip into the Arrangement.
- `set_clip_start_marker`, `set_signature`, `get_warp_markers` and `delete_warp_marker`
  return failures inside a success reply.
