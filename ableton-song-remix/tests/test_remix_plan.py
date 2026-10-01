#!/usr/bin/env python3
"""Test scripts/remix_plan.py on synthetic analysed songs (temp folders, tiny WAVs).

A drifting 4/4 song (2+2) checks the grid, tempo 'keep' = the mean of the steady bars (not
live_tempo), the pre-roll rule (silent pickup -> 0 bars, loud -> 1), one warp marker per
downbeat at (bar - 1 + P) * bar_beats, chord holds, N.C., slash bass, the bass hint, the
kept stems deciding which parts are new, energy tiers, and the sketch (the mix muted, the
transcribed bass in beats). An 11/8 song (6+5, eighth pulse) checks 5.5-beat bars and
unequal cells. Harte labels read through chart_html.lead_sheet. NEEDS A DECISION (exit 2)
on a 30% bar; errors (exit 1) on a missing chart or an unknown chord label. Temp folders
are removed at exit.
Run: python3 tests/test_remix_plan.py
"""
import atexit, json, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / 'scripts' / 'remix_plan.py'
sys.path.insert(0, str(HERE))
from fixtures import make_song  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='remix_plan_'))
atexit.register(shutil.rmtree, TMP, True)
fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))


def plan(song, *args):
    out = song / 'remix' / 'p.json'
    r = subprocess.run([sys.executable, str(SCRIPT), str(song), '--out', str(out), *args],
                       capture_output=True, text=True)
    return r, (json.loads(out.read_text()) if r.returncode == 0 else None)


def main():
    # 4/4, drifting, silent pickup
    s = make_song(TMP / 'a')
    r, p = plan(s)
    check('4/4 plan exits 0', r.returncode == 0, r.stderr)
    g, t = p['grid'], p['tempo']
    check('4/4 bar = 4 beats, cells [2, 2]', g['bar_beats'] == 4 and g['cell_beats'] == [2, 2])
    F = json.loads((s / 'analysis' / 'foundation.json').read_text())
    db = F['downbeat_times']
    mean = round(60 * 4 * 16 / (db[-1] - db[0]), 2)
    check('tempo keep = mean of the bars, not live_tempo',
          t['keep'] == mean and t['live'] == mean and t['live'] != F['live_tempo'],
          (t, mean))
    check('silent pickup -> no pre-roll', g['preroll_bars'] == 0 and g['total_bars'] == 16)
    m = p['warp']['markers']
    check('one warp marker per downbeat', len(m) == 17 and
          all(abs(m[k][0] - db[k]) < 1e-4 and m[k][1] == 4 * k for k in range(17)), m[:3])
    ch = {(c['bar'], c['cell']): c for c in p['chords']}
    check('N.C. has no root', ch[(3, 1)]['root'] is None and ch[(3, 1)]['pcs'] == [])
    check('a missing cell holds the previous chord', ch[(4, 1)]['label'] == ch[(3, 2)]['label'])
    sl = next(c for c in p['chords'] if c['label'] == 'Em/D')
    check('slash chord: bass D, chord E G B', sl['bass'] == 2 and sorted(sl['pcs']) == [4, 7, 11])
    check('(bar, cell) -> Live beat', ch[(5, 2)]['start_beat'] == 18.0 and ch[(5, 2)]['beats'] == 2)
    check('bass hint kept', p['bass_hints'] == [{'bar': 6, 'cell': 2, 'pc': 9}])
    check('remix keeps vocals, writes drums bass keys',
          [x['name'] for x in p['stems']] == ['vocals'] and p['parts'] == ['drums', 'bass', 'keys'])
    check('energy: quiet first bars -> tier 0, then 3',
          p['energy']['drums'][:2] == [0, 0] and p['energy']['drums'][4] == 3, p['energy']['drums'])
    check('sections in Live beats', p['sections'][1]['start_beat'] == 16.0 and
          p['sections'][-1]['end_beat'] == 64.0)

    # loud pickup, keep vocals + drums, round tempo
    s = make_song(TMP / 'b', loud_pickup=True)
    r, p = plan(s, '--keep', 'vocals,drums', '--tempo', 'round')
    check('loud pickup -> 1 bar pre-roll', r.returncode == 0 and p['grid']['preroll_bars'] == 1,
          r.stderr)
    check('pre-roll shifts markers and chords by one bar',
          p['warp']['markers'][0][1] == 4.0 and p['chords'][0]['start_beat'] == 4.0)
    check('kept drums -> no new drums', p['parts'] == ['bass', 'keys'])
    check('tempo round is whole', p['tempo']['live'] == round(p['tempo']['keep']))

    # a guitar song: the guitar stem comes from the extra htdemucs_6s run
    r, _ = plan(s, '--keep', 'vocals,guitar')
    check('kept guitar without htdemucs_6s -> refused, names the run',
          r.returncode != 0 and 'htdemucs_6s' in r.stdout + r.stderr, r.stdout + r.stderr)
    ft = next((s / 'stems' / 'htdemucs_ft').iterdir())
    six = s / 'stems' / 'htdemucs_6s' / ft.name
    six.mkdir(parents=True)
    shutil.copy(ft / 'vocals.wav', six / 'guitar.wav')
    r, p = plan(s, '--keep', 'vocals,guitar')
    g = next((x for x in p['stems'] if x['name'] == 'guitar'), {}) if p else {}
    check('kept guitar: from htdemucs_6s, its own track; vocals still from htdemucs_ft',
          r.returncode == 0 and '/htdemucs_6s/' in g.get('path', '') and
          g.get('track_name') == 'GTR · orig' and
          '/htdemucs_ft/' in p['stems'][0]['path'], r.stdout + r.stderr)

    # sketch
    r, p = plan(s, '--mode', 'sketch')
    mix = [x for x in p['stems'] if x['role'] == 'ref'] if p else []
    check('sketch: preset as-analysed, mix muted',
          r.returncode == 0 and p['preset'] == 'as-analysed' and mix and mix[0]['mute'], r.stderr)
    bl = p['bass_line'] if p else []
    check('sketch: transcribed bass in beats, on 16ths, after the pre-roll',
          len(bl) == 16 and all(n['start_time'] * 4 == int(n['start_time'] * 4) for n in bl)
          and bl[0]['start_time'] == 4.0, bl[:2])

    # 11/8 as 6+5, eighth pulse
    s = make_song(TMP / 'c', grouping=(6, 5), pulse_unit=8, bar_s=4.18, nbars=8, db0=0.0,
                  drift=0.01, sections=[('Song', 1, 8, 'verse', '')])
    r, p = plan(s, '--preset', 'lo-fi')
    g = p['grid'] if p else {}
    check('11/8: bar 5.5 beats, cells [3.0, 2.5], signature 11/8',
          r.returncode == 0 and g['bar_beats'] == 5.5 and g['cell_beats'] == [3.0, 2.5]
          and (g['numerator'], g['denominator']) == (11, 8), r.stderr)
    ch = {(c['bar'], c['cell']): c for c in p['chords']} if p else {}
    check('11/8: bar 2 cell 2 at beat 8.5', ch.get((2, 2), {}).get('start_beat') == 8.5)
    check('11/8: markers every 5.5 beats', [m[1] for m in p['warp']['markers'][:3]] == [0, 5.5, 11])

    # decisions and errors
    s = make_song(TMP / 'd', wide_bar=(5, 1.3))
    r, _ = plan(s)
    check('30% bar -> NEEDS A DECISION, exit 2',
          r.returncode == 2 and 'NEEDS A DECISION' in r.stdout and '[5]' in r.stdout, r.stdout)
    r, _ = plan(s, '--stretch-anyway')
    check('--stretch-anyway -> exit 0', r.returncode == 0, r.stderr)
    s = make_song(TMP / 'e')
    (s / 'gen_v1.py').unlink()
    r, _ = plan(s)
    check('no chart -> exit 1 naming Phase 8', r.returncode == 1 and 'Phase 8' in r.stderr, r.stderr)
    s = make_song(TMP / 'f', chords={(1, 1): 'Cfoo'})
    r, _ = plan(s)
    check('unknown label -> exit 1 naming the cell',
          r.returncode == 1 and 'bar 1 cell 1' in r.stderr and 'Cfoo' in r.stderr, r.stderr)
    # a pickup longer than 4 bars: auto asks; an explicit --preroll N up to 8 is the answer
    s = make_song(TMP / 'h', loud_pickup=True, db0=9.0)
    r, p = plan(s)
    check('5-bar pickup, --preroll auto -> NEEDS A DECISION offering --preroll 5',
          r.returncode == 2 and '--preroll 5' in r.stdout, r.stdout + r.stderr)
    for n in ('5', '6', '8'):
        r, p = plan(s, '--preroll', n)
        check(f'--preroll {n} is kept (exit 0)', r.returncode == 0 and
              p['grid']['preroll_bars'] == int(n) and p['warp']['markers'][0][1] == int(n) * 4,
              r.stdout + r.stderr)
    r, p = plan(s, '--preroll', '9')
    check('--preroll 9 -> exit 1', r.returncode == 1, r.stderr)
    r, p = plan(s, '--mode', 'sketch', '--preset', 'house', '--preroll', '5')
    check('sketch + --preset house -> a NOTE, preset as-analysed',
          r.returncode == 0 and 'ignored in sketch mode' in r.stdout and
          p['preset'] == 'as-analysed', r.stdout + r.stderr)

    s = make_song(TMP / 'g', chords={(1, 1): 'A:min', (2, 1): 'G/b7', (3, 1): 'N'})
    r, p = plan(s)
    ch = {(c['bar'], c['cell']): c for c in p['chords']} if p else {}
    check("Harte labels read as the chart does (lead_sheet): A:min, G/b7, N",
          r.returncode == 0 and ch[(1, 1)]['label'] == 'Am' and ch[(2, 1)]['label'] == 'G/F'
          and ch[(2, 1)]['bass'] == 5 and ch[(3, 1)]['root'] is None, r.stderr)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
