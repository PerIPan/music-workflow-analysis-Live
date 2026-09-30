#!/usr/bin/env python3
"""Analysed song folder -> remix plan (plan.json): the grid, tempo, warp map, sections, chords.

Why: the Live build and the new parts must share one bar grid. The plan fixes it once,
in bars: Live beat of (bar, cell) = (bar - 1 + P) * bar_beats + the cell's offset, where
bar_beats = beats_per_bar * 4 / pulse_unit (4/4 -> 4, 11/8 -> 5.5) and P is the pre-roll
(whole bars that hold a pickup the kept stems sing or play before bar 1). Each kept stem
is warped in Live with one marker per downbeat, so Live's bar N is the song's bar N and
Live's tempo can move freely.

Tempo 'keep' is the duration-weighted mean tempo of the steady bars (tempo_outlier_bars
left out), not foundation.json's live_tempo (a median of 10 ms-quantized beat gaps, off by
1-2% on real songs). A bar that Live would stretch by more than --stretch-limit, or (with
--preroll auto) a pickup longer than 4 bars, stops with NEEDS A DECISION (exit 2); an
explicit --preroll N (0-8) is the answer.

Reads song-analysis output: analysis/foundation.json (step 'meter'), the chart data file
gen_v<N>.py (highest N; sections and chords per (bar, cell), through chart_html's own
loader, its lead_sheet() for Harte labels, and its checks), stems/htdemucs_ft/<name>/*.wav,
and if present analysis/stem_activity.json (energy per bar) and analysis/bass_notes.json
(sketch bass).

Usage (python3, standard library only):
    remix_plan.py SONG_DIR [--mode remix|sketch] [--preset house] [--tempo keep|round|BPM]
        [--keep vocals[,drums,bass,other]] [--chart gen_v2.py] [--preroll auto|N]
        [--stretch-limit 0.15] [--stretch-anyway] [--seed N] [--slug NAME] [--out PLAN]
        [--force]
Exit: 0 written, 1 error, 2 NEEDS A DECISION.
"""
from __future__ import annotations

import argparse, bisect, json, math, re, sys, wave, zlib
from array import array
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / 'song-analysis' / 'scripts'))
from chordsym import note_pc, parse  # noqa: E402

PRESETS = ('house', 'synth-pop', 'lo-fi', 'garage-punk', 'as-analysed')
STEMS = ('vocals', 'drums', 'bass', 'other')
PART_OF_STEM = {'drums': 'drums', 'bass': 'bass', 'other': 'keys'}   # kept stem -> no new part
TRACK_NAME = {'vocals': 'VOX', 'drums': 'DRUMS', 'bass': 'BASS', 'other': 'KEYS/GTR',
              'mix': 'MIX'}
WARP_MODE = {'vocals': 'complex_pro', 'drums': 'beats', 'bass': 'complex_pro',
             'other': 'complex_pro', 'mix': 'complex_pro'}
KIND_TIER = {'intro': 1, 'verse': 2, 'post': 2, 'chorus': 3, 'bridge': 1, 'inst': 2,
             'outro': 1}
SILENT_DB = -45.0


class Decision(Exception):
    """A choice the script can't make; exit 2 with the question."""


def fail(msg: str) -> None:
    sys.exit(f'remix_plan: {msg}')


def find_chart(song: Path, chart: str | None) -> Path:
    if chart:
        p = Path(chart)
        p = p if p.is_absolute() else song / p
        if not p.is_file():
            fail(f'chart data file {p} not found')
        return p
    found = sorted(song.glob('gen_v*.py'),
                   key=lambda p: int(re.sub(r'\D', '', p.stem) or 0))
    if not found:
        fail(f'no chart data file gen_v<N>.py in {song}: finish song-analysis Phase 8 first')
    return found[-1]


def find_stems(song: Path, need: list[str]) -> Path:
    base = song / 'stems' / 'htdemucs_ft'
    dirs = [d for d in sorted(base.glob('*')) if d.is_dir()
            and all((d / f'{s}.wav').is_file() for s in need)]
    if not dirs:
        fail(f'no stems folder under {base} with {", ".join(s + ".wav" for s in need)}: '
             'run song-analysis Phase 2 (htdemucs_ft)')
    if len(dirs) > 1:
        fail(f'several stem folders under {base}: {[d.name for d in dirs]} - keep one')
    return dirs[0]


def find_mix(song: Path, audio: str | None) -> Path:
    cands = []
    if audio:
        cands += [song / audio, song.parent / audio, song / Path(audio).name]
    cands += sorted(p for ext in ('wav', 'mp3', 'flac', 'aif', 'aiff')
                    for p in song.glob(f'*.{ext}'))
    for p in cands:
        if p.is_file():
            return p.resolve()
    fail(f'original mix not found in {song} (foundation.json audio={audio!r})')


def wav_info(path: Path, before_s: float) -> tuple[float, float | None]:
    """(length in seconds, peak dBFS before before_s); peak None if the WAV isn't PCM 16."""
    try:
        with wave.open(str(path)) as w:
            sr, n, width, ch = w.getframerate(), w.getnframes(), w.getsampwidth(), \
                w.getnchannels()
            length = n / sr
            if width != 2 or before_s <= 0:
                return length, (None if width != 2 else -200.0)
            a = array('h', w.readframes(min(n, int(before_s * sr))))
            if sys.byteorder == 'big':
                a.byteswap()
            peak = max((abs(x) for x in a), default=0) / 32768.0
            return length, (20 * math.log10(peak) if peak > 0 else -200.0)
    except (wave.Error, EOFError) as e:
        fail(f'{path}: not a readable WAV ({e})')


def keep_tempo(db: list[float], bar_beats: float, outliers: set[int]) -> float:
    bars = [k for k in range(len(db) - 1) if k + 1 not in outliers] or range(len(db) - 1)
    return 60.0 * bar_beats * len(bars) / sum(db[k + 1] - db[k] for k in bars)


def tiers(levels: list[float], sections: list[tuple], nbars: int, kind_of: dict) -> list[int]:
    """Energy tier 0-3 per bar from one stem's per-bar level, relative to its 90th
    percentile, then the rounded mean over 2-bar blocks from each section start."""
    if not levels:
        return [KIND_TIER.get(kind_of[b], 2) for b in range(1, nbars + 1)]
    s = sorted(levels)
    p90 = s[min(len(s) - 1, int(0.9 * len(s)))] or 1.0
    raw = []
    for b in range(1, nbars + 1):
        r = levels[min(b, len(levels)) - 1] / p90
        raw.append(3 if r >= 0.75 else 2 if r >= 0.45 else 1 if r >= 0.12 else 0)
    out = raw[:]
    for _, b0, b1, *_ in sections:
        for a in range(b0, b1 + 1, 2):
            blk = raw[a - 1:min(a + 1, b1)]
            t = int(sum(blk) / len(blk) + 0.5)
            for b in range(a, min(a + 1, b1) + 1):
                out[b - 1] = t
    return out


def build(a: argparse.Namespace) -> dict:
    song = Path(a.song).resolve()
    F = json.loads((song / 'analysis' / 'foundation.json').read_text())
    if F.get('step') != 'meter':
        fail('foundation.json is not at step "meter": run foundation.py meter first')
    bpb, unit = int(F['beats_per_bar']), int(F['pulse_unit'])
    db = [float(x) for x in F['downbeat_times']]
    n = len(db) - 1

    sys.dont_write_bytecode = True                      # no __pycache__ in the song folder
    import chart_html                                   # song-analysis, sibling skill
    chart = find_chart(song, a.chart)
    S = chart_html.load_song(chart)
    if isinstance(S.get('chords'), dict):               # Harte labels, as the chart reads them
        S['chords'] = {k: chart_html.lead_sheet(c) if isinstance(c, str) else c
                       for k, c in S['chords'].items()}
    try:
        chart_html.check_song(S)
    except ValueError as e:
        fail(f'{chart.name}: {e}')
    grouping = list(S.get('grouping') or F['grouping'])    # the chart's cells win, as in the chart
    if sum(grouping) != bpb or unit not in (4, 8):
        fail(f'grouping {grouping} must sum to beats_per_bar {bpb}, pulse_unit 4 or 8')
    bar_beats = bpb * 4 / unit
    cell_beats = [g * 4 / unit for g in grouping]
    cell_off = [sum(cell_beats[:i]) for i in range(len(cell_beats))]
    sections = [tuple(x) for x in S['sections']]
    L = sections[-1][2]
    if L > n + 1:
        fail(f'chart sections run to bar {L}; the grid has {n} bars (+1 allowed)')
    if len(grouping) < max((c for _, c in S['chords']), default=1):
        fail(f'chart cells exceed the grouping {grouping}')

    sketch = a.mode == 'sketch'
    preset = 'as-analysed' if sketch else a.preset
    if sketch and a.preset not in (None, 'as-analysed'):
        print(f'NOTE: --preset {a.preset} ignored in sketch mode (as-analysed)')
    keep = [s.strip() for s in a.keep.split(',') if s.strip()]
    bad = [s for s in keep if s not in STEMS]
    if bad or not keep:
        fail(f'--keep takes {",".join(STEMS)}; got {a.keep!r}')
    stem_dir = find_stems(song, keep)

    # tempo
    outliers = set(F.get('tempo_outlier_bars', []))
    keep_t = round(keep_tempo(db, bar_beats, outliers), 2)
    if a.tempo == 'keep':
        T = keep_t
    elif a.tempo == 'round':
        T = float(round(keep_t))
    else:
        try:
            T = float(a.tempo)
        except ValueError:
            fail(f'--tempo takes keep, round or a BPM; got {a.tempo!r}')
    if not 20 <= T <= 999:
        fail(f'tempo {T} outside 20-999')
    ratio = [T * (db[k + 1] - db[k]) / (bar_beats * 60) for k in range(n)]
    wide = [k + 1 for k, r in enumerate(ratio) if abs(r - 1) > a.stretch_limit]
    if wide and not a.stretch_anyway:
        raise Decision(f'at {T} BPM Live would stretch bars {wide[:12]}'
                       f'{" ..." if len(wide) > 12 else ""} by more than '
                       f'{a.stretch_limit:.0%} (ratios {min(ratio):.3f}-{max(ratio):.3f}). '
                       'Ask: stretch anyway (--stretch-anyway), or another --tempo?')

    # stems + pre-roll
    stems = []
    for s in keep:
        p = (stem_dir / f'{s}.wav').resolve()
        length, peak = wav_info(p, db[0])
        stems.append(dict(name=s, role='keep', path=str(p), length_s=round(length, 4),
                          peak_before_db=None if peak is None else round(peak, 1),
                          track_name=f'{TRACK_NAME[s]} · orig', warp_mode=WARP_MODE[s],
                          mute=False))
    if sketch:
        mix = find_mix(song, F.get('audio'))
        length = wav_info(mix, 0)[0] if mix.suffix.lower() == '.wav' else stems[0]['length_s']
        stems.append(dict(name='mix', role='ref', path=str(mix), length_s=round(length, 4),
                          peak_before_db=None, track_name='MIX · orig (A/B)',
                          warp_mode=WARP_MODE['mix'], mute=True))
    bar0 = db[1] - db[0]
    if a.preroll == 'auto':
        loud = [s['name'] for s in stems if s['role'] == 'keep' and
                (s['peak_before_db'] is None or s['peak_before_db'] > SILENT_DB)]
        P = math.ceil(db[0] / bar0 - 1e-6) if loud and db[0] > 0.01 else 0
        if P > 4:                                       # an explicit --preroll N is the answer
            raise Decision(f'the kept stems sound {db[0]:.2f}s before bar 1 = {P} bars of '
                           'pre-roll. Ask: drop the pickup (--preroll 0) or keep it '
                           f'(--preroll {P}, at most 8)?')
    else:
        P = int(a.preroll)
    total_bars = P + L
    total_beats = total_bars * bar_beats

    # warp map: one marker per downbeat (+ the end of a ringing last bar, if in the file)
    shortest = min(s['length_s'] for s in stems)
    marks = [[round(db[k], 5), round((k + P) * bar_beats, 6)] for k in range(n + 1)]
    if L > n and db[n] + (db[n] - db[n - 1]) < shortest:
        marks.append([round(db[n] + db[n] - db[n - 1], 5), round((n + 1 + P) * bar_beats, 6)])
    marks = [m for m in marks if m[0] < shortest - 0.001]

    # sections, chords, hints, energy
    kind_of = {b: k for _, b0, b1, k, *_ in sections for b in range(b0, b1 + 1)}
    secs = [dict(name=nm, kind=k, first_bar=b0, last_bar=b1,
                 start_beat=(b0 - 1 + P) * bar_beats, end_beat=(b1 + P) * bar_beats)
            for nm, b0, b1, k, *_ in sections]
    chords, cur = [], 'N.C.'
    for b in range(1, L + 1):
        for c in range(1, len(grouping) + 1):
            cur = S['chords'].get((b, c), cur)
            try:
                ch = parse(cur)
            except ValueError as e:
                fail(f'bar {b} cell {c}: {e}')
            chords.append(dict(bar=b, cell=c, label=cur,
                               start_beat=(b - 1 + P) * bar_beats + cell_off[c - 1],
                               beats=cell_beats[c - 1],
                               root=None if ch is None else ch['root'],
                               pcs=[] if ch is None else ch['pcs'],
                               intervals=[] if ch is None else ch['intervals'],
                               bass=None if ch is None else ch['bass']))
    hints = [dict(bar=b, cell=c, pc=note_pc(v)) for (b, c), v in
             sorted(S.get('bass_notes', {}).items())]
    act_p = song / 'analysis' / 'stem_activity.json'
    act = json.loads(act_p.read_text()) if act_p.is_file() else {}
    energy = {part: tiers(act.get(stem, []), sections, L, kind_of)
              for stem, part in (('drums', 'drums'), ('bass', 'bass'), ('other', 'keys'))}
    parts = [p for p in ('drums', 'bass', 'keys')
             if p not in {PART_OF_STEM[s] for s in keep if s in PART_OF_STEM}]

    def beat_of(t: float) -> float:
        k = min(max(bisect.bisect_right(db, t) - 1, 0), n - 1)
        return (k + P + (t - db[k]) / (db[k + 1] - db[k])) * bar_beats

    bass_line = []
    bn = song / 'analysis' / 'bass_notes.json'
    if preset == 'as-analysed' and 'bass' in parts and bn.is_file():
        for x in json.loads(bn.read_text()).get('notes', []):
            s0 = round(beat_of(float(x['start'])) * 4) / 4
            s1 = round(beat_of(float(x['end'])) * 4) / 4
            if 0 <= s0 < total_beats:
                bass_line.append(dict(pitch=int(x['pitch']), start_time=s0,
                                      duration=max(min(s1, total_beats) - s0, 0.25),
                                      velocity=int(x.get('velocity', 90))))

    num, den = bpb, unit
    title = S['title']
    return dict(
        schema='ableton-song-remix.plan/1', mode=a.mode, preset=preset,
        seed=a.seed if a.seed is not None else zlib.crc32(f'{title}|{preset}'.encode()) % 10000,
        song=dict(title=title, artist=S['artist'], folder=str(song), chart=chart.name,
                  stems_dir=str(stem_dir)),
        grid=dict(time_signature=f'{num}/{den}', numerator=num, denominator=den,
                  pulse_unit=unit, grouping=grouping, bar_beats=bar_beats,
                  cell_beats=cell_beats, song_bars=n, chart_bars=L, preroll_bars=P,
                  total_bars=total_bars, total_beats=total_beats),
        tempo=dict(live=T, keep=keep_t, live_tempo=F.get('live_tempo'), choice=a.tempo,
                   stretch_min=round(min(ratio), 3), stretch_max=round(max(ratio), 3),
                   outlier_bars=sorted(outliers)),
        warp=dict(markers=marks, note='[seconds in the stem file, Live beat]; one per downbeat'),
        stems=stems, parts=parts, sections=secs, chords=chords, bass_hints=hints,
        energy=energy, bass_line=bass_line)


def summary(p: dict) -> str:
    g, t = p['grid'], p['tempo']
    grp = '+'.join(map(str, g['grouping']))
    lines = [f"{p['song']['artist']} - {p['song']['title']}: {p['mode']}, preset {p['preset']}",
             f"meter {g['time_signature']} ({grp}), bar = {g['bar_beats']:g} Live beats; "
             f"{g['chart_bars']} chart bars + {g['preroll_bars']} pre-roll = "
             f"{g['total_bars']} bars ({g['total_beats']:g} beats)",
             f"Live tempo {t['live']} (keep {t['keep']}; live_tempo {t['live_tempo']}); "
             f"Live stretch per bar {t['stretch_min']}-{t['stretch_max']}",
             f"stems: {', '.join(s['name'] + (' (muted A/B)' if s['mute'] else '') for s in p['stems'])}"
             f"; new parts: {', '.join(p['parts']) or 'none'}",
             f"warp markers per stem: {len(p['warp']['markers'])}",
             'sections: ' + ', '.join(f"{s['name']} {s['first_bar']}-{s['last_bar']}"
                                      for s in p['sections'])]
    if g['preroll_bars']:
        lines.append(f"NOTE: Live bar = chart bar + {g['preroll_bars']} (pickup before bar 1)")
    return '\n'.join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('song', help='song folder that song-analysis finished')
    ap.add_argument('--mode', choices=('remix', 'sketch'), default='remix')
    ap.add_argument('--preset', choices=PRESETS, help='default house (sketch: as-analysed)')
    ap.add_argument('--tempo', default='keep', help='keep, round or a BPM')
    ap.add_argument('--keep', default='vocals', help='original stems to keep, e.g. vocals,bass')
    ap.add_argument('--chart', help='chart data file (default: the highest gen_v<N>.py)')
    ap.add_argument('--preroll', default='auto', help="auto or whole bars before bar 1")
    ap.add_argument('--stretch-limit', type=float, default=0.15)
    ap.add_argument('--stretch-anyway', action='store_true')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--slug', help='remix folder name (default <preset>-<tempo>)')
    ap.add_argument('--out', help='plan path (default SONG/remix/<slug>/plan.json)')
    ap.add_argument('--force', action='store_true', help='overwrite a plan already built')
    a = ap.parse_args()
    if a.mode == 'remix' and a.preset is None:
        a.preset = 'house'
    if a.preroll != 'auto' and not (a.preroll.isdigit() and int(a.preroll) <= 8):
        fail('--preroll takes auto or 0-8')
    try:
        plan = build(a)
    except Decision as e:
        print(f'NEEDS A DECISION: {e}')
        sys.exit(2)
    except (OSError, ValueError, KeyError) as e:
        fail(str(e))
    slug = a.slug or ('sketch' if plan['mode'] == 'sketch' else plan['preset']) + \
        f"-{round(plan['tempo']['live'])}"
    out = Path(a.out) if a.out else Path(plan['song']['folder']) / 'remix' / slug / 'plan.json'
    if (out.parent / 'build_report.json').exists() and not a.force:
        fail(f'{out.parent} was already built in Live; --force to overwrite the plan')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(plan, indent=1))
    print(summary(plan))
    print(f'wrote {out}')


if __name__ == '__main__':
    main()
