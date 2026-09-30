# Environment setup (first-time install)

Read this only when the toolchain isn't installed yet, or a venv broke.

Five virtualenvs, one per role — TensorFlow (basic-pitch, crepe, ADTOF), torch (demucs,
lv-chordia) and Whisper's MLX stack don't mix well, so keep them apart. Versions below are
the latest releases as of September 2026 and were verified with this skill's scripts and
benchmark (every output byte-identical to the previous stack); pin them. Uses
[uv](https://docs.astral.sh/uv/). Apple Silicon recommended; CUDA also works for demucs.
Also needs **ffmpeg** on the PATH (MP3 decoding before separation, and m4a/aac/webm input).

```bash
echo 'setuptools<81' > /tmp/build-constraints.txt     # for crepe's legacy build (see notes)

# (1) Analysis — madmom, librosa, basic-pitch, crepe; runs scripts/*.py   (Python 3.12)
uv venv --python 3.12 .venv-bp && P=.venv-bp/bin/python
uv pip install --python $P 'numpy==2.5.3' 'cython==3.3.0' 'setuptools==80.10.2' wheel
uv pip install --python $P --no-build-isolation \
    'madmom @ git+https://github.com/CPJKU/madmom@27f032e8947204902c675e5e341a3faf5dc86dae'
uv pip install --python $P 'librosa==1.0.0' 'scipy==1.18.1' 'numba==0.67.0' \
    'soundfile==0.14.0' 'mir_eval==0.8.2' 'pretty_midi==0.2.11.post0' 'resampy==0.4.2' \
    'scikit-learn==1.9.1' 'tensorflow==2.21.0' 'tf-keras==2.21.0' 'keras==3.12.1' 'coremltools==9.0'
uv pip install --python $P --no-deps 'basic-pitch==0.4.0'
uv pip install --python $P --build-constraints /tmp/build-constraints.txt 'crepe==0.0.16'

# (2) Stems — demucs   (Python 3.11)
uv venv --python 3.11 .venv-demucs
uv pip install --python .venv-demucs/bin/python 'demucs==4.1.0' 'torch==2.14.0' numpy
# first run downloads htdemucs_ft from Hugging Face (4 × 84 MB, ~/.cache/huggingface/hub)

# (3) Lyrics — Whisper on Apple Silicon   (any recent Python; verified on 3.13)
python3 -m venv ~/mlx-openai-whisper
~/mlx-openai-whisper/bin/pip install 'mlx-whisper==0.4.3' 'librosa==0.11.0'
# first use downloads mlx-community/whisper-large-v3-turbo (~1.5 GB)

# (4) Chords — lv-chordia   (Python 3.12; weights bundled)
uv venv --python 3.12 .venv-lvchordia
uv pip install --python .venv-lvchordia/bin/python 'lv-chordia==1.1.0' 'librosa==1.0.0' \
    'torch==2.14.0' 'soundfile==0.14.0' 'mir_eval==0.8.2'

# (5) Optional — ADTOF drum transcription   (Python 3.10)
python3.10 -m venv .venv-adtof && source .venv-adtof/bin/activate
pip install 'numpy==1.26.4' 'tensorflow==2.21.0' 'tf_keras==2.21.0' 'pretty_midi==0.2.11'
pip install git+https://github.com/MZehren/ADTOF.git     # CC BY-NC-SA: install, never vendor
deactivate                      # set TF_USE_LEGACY_KERAS=1 before importing it
```

Notes:
- **madmom** comes from git (PyPI 0.16.1 is from 2018). The pinned commit is madmom's own
  "NumPy compatibility update": it builds on NumPy 2 with Cython 3 and
  `--no-build-isolation`, and beats and key came out bit-identical to NumPy 1.26 on the
  benchmark songs. On about one song in ten its tracker can drop a single beat at a
  borderline passage (the same size as its run-to-run wobble) — if you re-run a song
  analysed on an older stack, re-check the downbeat answer you gave `foundation.py meter`.
- **setuptools < 81** stays installed: resampy (used by basic-pitch) and crepe's build
  still import `pkg_resources`, which setuptools 81 removed.
- **basic-pitch** is installed with `--no-deps` because its metadata pins
  `tensorflow-macos` on Python 3.12, which has no wheels; it runs on TF 2.21 (output
  identical to the old stack; coremltools warns the combination is untested).
- **librosa 1.0** no longer falls back to audioread, so it reads only what libsndfile
  reads (wav, flac, ogg, mp3). The scripts transcode anything else (m4a, aac, webm) with
  ffmpeg to a temporary WAV. The Whisper venv stays on 0.11 until it is re-benchmarked.
- **demucs 4.1** needs numpy installed explicitly on Apple Silicon (its metadata only
  lists it for Intel Macs), no longer needs torchaudio, and must get **WAV input**:
  it reads MP3 without the gapless trim, shifting every stem 25 ms late
  (`references/stems.md`).
- Not on Apple Silicon: `openai-whisper` instead of `mlx-whisper` (drop the alignment-head
  line in `whisper_gated.py`).
- **mlx-demucs** (optional batch path) runs **plain htdemucs** (not `_ft`) ~9× faster than
  torch-CPU demucs; for `_ft`, use torch demucs on MPS instead.
- Tests (offline, synthetic): in `song-analysis/`, `.venv-bp/bin/python` runs
  `tests/test_detect_meter.py`, `test_chord_proposal.py`, `test_mode_test.py`,
  `test_downbeat_check.py` and `test_stem_activity.py`;
  `python3` runs `tests/test_foundation.py`, `test_align_lyrics.py` and
  `test_chart_html.py`; in `ableton-mcp/`, `python3 tests/test_push_notes.py`.

## Per-song working directory

Created fresh for each song:

```
<song-slug>/
├── <song>.mp3                          # input
├── lyrics.txt                          # input (canonical text)
├── PLAN.md                             # decisions log
├── analysis/
│   ├── foundation.json                 # foundation.py: pulse + key, then meter fields
│   ├── meter.json                      # detect_meter.py --json
│   ├── bass.mid, bass_notes.json       # bass_notes.py (pyin)
│   ├── bass_per_cell.json              # seconds per pitch class per (bar, cell)
│   ├── mode.json                       # mode_test.py — tonic, mode, per-section
│   ├── lyrics.json, lyrics_mix.json    # whisper_gated.py words (vocal stem, full mix)
│   ├── lyrics_aligned.json             # align_lyrics.py — canonical lines with times
│   ├── sections.json                   # align_lyrics.py — section starts, (bar, cell)
│   ├── chords_lv.json                  # lv_chords.py — primary chord reading
│   ├── chord_proposal.json             # chord_proposal.py — triad cross-check
│   └── stem_activity.json              # stem_activity.py — per-bar stem levels (song map)
├── stems/htdemucs_ft/<song>/           # {bass,drums,vocals,other}.wav
├── gen_v<N>.py                         # chart data (SONG) for scripts/chart_html.py
└── <artist> - <title> - Chords.html    # chart_html.py output
```

The chart lands beside its data file; `--out` writes it anywhere else (e.g. a shared
cloud-storage folder).

## This machine

The one place for local paths — every skill in this repo points here.

| Role | Interpreter / binary |
|---|---|
| Analysis (Python 3.12: madmom, librosa 1.0, numpy 2, basic-pitch, crepe; runs `scripts/*.py`) | `~/dev/abletonAI/audio-analysis/.venv-bp/bin/python` |
| Stems (demucs 4.1.0, torch 2.14.0) | `~/dev/abletonAI/audio-analysis/.venv-demucs/bin/python -m demucs` |
| Chords (Python 3.12: lv-chordia, librosa 1.0, torch 2.14) | `~/dev/abletonAI/audio-analysis/.venv-lvchordia/bin/python` |
| Lyrics (mlx-whisper; only `whisper-large-v3-turbo` is cached) | `~/mlx-openai-whisper/bin/python` |
| Drums (ADTOF, optional) | `~/dev/abletonAI/audio-analysis/.venv-adtof/bin/python` |
| Batch stems (plain htdemucs, MLX) | `~/dev/abletonAI/audio-analysis/mlx-demucs/.venv/bin/mlx-demucs` |
| Trial venvs kept for re-runs | `.venv-asseg` (sections), `.venv-swiftf0`, `.venv-sep047` (+ `models-audio-separator/`) |

Song folders live in `~/dev/abletonAI/`. Older helpers in the tooling root
(`analyze_chords.py`, `scripts/transcribe_bass_pyin.py`, the old chart and note
generators `gen_*.py`) predate these skills' scripts — `analyze_chords.py` still has a
0.05 major bias; prefer `scripts/`. A song folder's `gen_v<N>.py` is not one of them: it
is chart data for `chart_html.py`.
