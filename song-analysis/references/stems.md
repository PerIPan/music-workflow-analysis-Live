# Stems — separation options, speed, cache, quality

Read this when Phase 2 is slow, a model isn't cached, or a stem sounds wrong.

## Default: `htdemucs_ft` on the GPU

```bash
ffmpeg -v error -i <song.mp3> -c:a pcm_s16le /tmp/<song>.wav
demucs -n htdemucs_ft -d mps -o stems /tmp/<song>.wav     # demucs 4.1.0, torch 2.14.0
```

- **Decode MP3 to WAV first.** demucs 4.1 reads MP3 with `sphn`, which skips the MP3
  encoder-delay trim: every stem starts 1105 samples (25 ms) late and runs long against the
  mix as librosa, soundfile, ffmpeg and demucs 4.0 read it. WAV input lines up exactly.
  The output folder is still named after the file stem.
- **Same model as 4.0.** 4.1 loads `htdemucs_ft` from Hugging Face
  (`~/.cache/huggingface/hub/models--adefossez--HTDemucs-ft`, 4 × 84 MB); the weights are
  bit-identical to 4.0's `.th` files, and separation matches within random-shift noise.
  It used about 3.5× less CPU and 20% less memory on a 4-minute song. Set
  `HF_HUB_OFFLINE=1` after the first download to skip the hub check.
- **`-d mps` on Apple Silicon** (4.1 picks MPS by default; 4.0 needed the flag — measured
  on an M3, 30 s clip: CPU 64.5 s, MPS 23.0 s).
- **Meter-only runs** need just the drums: `--two-stems=drums`.
- **Cache check first:** `validate_artifacts.py --check-cache` looks in both the Hugging Face
  cache (4.1) and `~/.cache/torch/hub/checkpoints` (4.0). `htdemucs_ft` is a bag of 4 models, 4 × 84 MB. Uncached, the
  command downloads silently for as long as the connection takes — ~100 min at 3 MB/min
  once — and piping through `tail` hides all progress. Don't assume it's cached because
  it was used on a previous song.

## Alternatives, measured

| Option | Speed (M3) | Use when |
|---|---|---|
| `htdemucs_ft -d mps` (demucs 4.1, torch 2.14) | 66 s for a 2-min song (4.0; 4.1 ~17% faster) | default |
| `mlx-demucs` (plain htdemucs) | 28 s for a 4-min song | batches; quality slightly below `_ft` |
| `demucs-mlx -n htdemucs_ft` | 96 s for the same 2-min song | never — slower than torch MPS, same output (22–29 dB SNR) |
| `htdemucs_6s` | — | run **after** `htdemucs_ft` when the song carries guitar or piano; keep only `guitar.wav` / `piano.wav`; never for bass (bleeds keys into it) |
| BS-RoFormer-SW 6-stem (`audio-separator`) | 0.67× real time | a real piano/guitar stem matters; no chord gain (92.1 vs 91.5%), 699 MB, licence undeclared |

`mlx-demucs`: call its venv binary directly — `uv run mlx-demucs` re-resolves dependencies
over the network and hangs 10+ minutes. Its README lists `htdemucs_ft`, but only plain
htdemucs weights ship with it.

## Quality checks

- Listen to `bass.wav` alone: piano/guitar bleed means separation struggled; suppress
  bass-derived annotations where it does.
- Before the bass enters, the bass stem contains bleed — find the entry bar.
- The drums stem can be quiet (peaks around −5 dBFS): normalise before any level-sensitive
  tool (ADTOF).
