#!/usr/bin/env python3
"""Test scripts/remix_build.py against a stateful mock of the patched Remote Script.

A 4/4 song with a pickup (1 bar of pre-roll) and an 11/8 song: the meter is set and read
back before any clip, the tempo read back, tracks named, the FULL + section scenes named,
MIDI clips pushed in chunks, each stem loaded, warped (a separate command after the load),
its markers replaced by one per downbeat (the first moved onto the grid, the rest added in
order) and read back, looped to the song, and copied per section with the section's loop.
Live's first marker past sample 0 (Auto-Warp) still gets every downbeat; a stray marker
between downbeats fails the read-back; a file still decoding is waited for; a FULL
loop_start Live clamped is a warning; a section clip keeps a downbeat note humanized just
before the section; parts.json from an older plan is refused.
Refusals: an unpatched Remote Script exits 3 before any write; a Set with clips exits 2
(--force appends); an error inside a success reply exits 1 and stops; a failed note chunk
exits 1; no Live exits 4. --dry-run opens no socket. Temp folders are removed at exit.
Run: python3 tests/test_remix_build.py   (standard library only)
"""
import atexit, json, os, shutil, socket, subprocess, sys, tempfile, threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'scripts'
sys.path.insert(0, str(HERE))
from fixtures import make_song  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix='remix_build_'))
atexit.register(shutil.rmtree, TMP, True)
WRITES = ('set_', 'create_', 'add_', 'delete_', 'move_', 'load_', 'duplicate_')


class MockLive:
    """Enough of the patched Remote Script: tracks, scenes, clips, notes, warp markers."""

    def __init__(self, patched=True, swallow=(), fail_on=None, clips_on_track=False,
                 first_at=0.0, inject=False, decode_reads=0, clamp=False):
        self.patched, self.swallow, self.fail_on = patched, set(swallow), fail_on
        self.first_at, self.inject, self.clamp = first_at, inject, clamp
        self.decode_reads = decode_reads          # get_clip_info reads with sample_length 0
        self.calls, self.tempo, self.sig = [], 120.0, (4, 4)
        self.scenes = [''] * 8
        self.tracks = []
        if clips_on_track:
            self.tracks.append(dict(name='old', audio=False, devices=[],
                                    slots={0: dict(notes=[1], name='x')}))
        self.srv = socket.socket()
        self.srv.bind(('127.0.0.1', 0))
        self.srv.listen(16)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            c, _ = self.srv.accept()
            data = b''
            while True:
                data += c.recv(65536)
                try:
                    msg = json.loads(data)
                    break
                except json.JSONDecodeError:
                    continue
            self.calls.append(msg)
            try:
                res = self.handle(msg['type'], msg['params'])
                rep = {'status': 'success', 'result': res}
                if msg['type'] in self.swallow:
                    rep['result'] = {'error': 'swallowed failure'}
                if self.fail_on and self.fail_on(msg, len(self.calls)):
                    rep = {'status': 'error', 'message': 'injected failure'}
            except (KeyError, ValueError, IndexError) as e:
                rep = {'status': 'error', 'message': str(e)}
            c.sendall(json.dumps(rep).encode())
            c.close()

    def clip(self, p):
        return self.tracks[p['track_index']]['slots'][p['clip_index']]

    def handle(self, t, p):
        if t == 'health_check':
            return {'status': 'ok'}
        if t == 'get_capabilities':
            if not self.patched:
                raise ValueError(f'Unknown command: {t}')
            return {'remix_patch': 1}
        if t == 'get_session_info':
            return {'tempo': self.tempo, 'track_count': len(self.tracks),
                    'signature_numerator': self.sig[0], 'signature_denominator': self.sig[1]}
        if t == 'get_all_scenes':
            return {'scenes': [{'index': i, 'name': n} for i, n in enumerate(self.scenes)]}
        if t == 'get_track_info':
            tr = self.tracks[p['track_index']]
            return {'name': tr['name'], 'devices': tr['devices'],
                    'clip_slots': [{'index': i, 'has_clip': i in tr['slots']}
                                   for i in range(len(self.scenes))]}
        if t == 'set_signature':
            self.sig = (p['numerator'], p['denominator'])
            return {'success': True}
        if t == 'get_signature':
            return {'numerator': self.sig[0], 'denominator': self.sig[1]}
        if t == 'set_tempo':
            self.tempo = p['tempo']
            return {'tempo': self.tempo}
        if t in ('create_audio_track', 'create_midi_track'):
            self.tracks.append(dict(name='', audio=t == 'create_audio_track', devices=[],
                                    slots={}, mute=False))
            return {'index': len(self.tracks) - 1}
        if t == 'set_track_name':
            self.tracks[p['track_index']]['name'] = p['name']
            return {'name': p['name']}
        if t == 'set_track_mute':
            self.tracks[p['track_index']]['mute'] = p['mute']
            return {}
        if t == 'search_browser':
            return {'results': [{'name': p['query'] + ' Kit', 'uri': 'uri:' + p['query'],
                                 'is_loadable': True}]}
        if t == 'load_browser_item':
            self.tracks[p['track_index']]['devices'].append({'name': p['item_uri']})
            return {'loaded': True}
        if t == 'create_scene':
            self.scenes.append('')
            return {'index': len(self.scenes) - 1}
        if t == 'set_scene_name':
            self.scenes[p['scene_index']] = p['name']
            return {}
        if t == 'create_clip':
            tr = self.tracks[p['track_index']]
            if tr['audio'] or p['clip_index'] in tr['slots'] or p['clip_index'] >= len(self.scenes):
                raise ValueError('bad create_clip')
            tr['slots'][p['clip_index']] = dict(notes=[], length=p['length'], name='')
            return {}
        if t == 'add_notes_to_clip':
            self.clip(p)['notes'] += p['notes']
            return {'note_count': len(p['notes'])}
        if t == 'set_clip_name':
            self.clip(p)['name'] = p['name']
            return {}
        if t == 'create_audio_clip':
            tr = self.tracks[p['track_index']]
            if not tr['audio'] or p['clip_index'] in tr['slots'] or not os.path.isfile(p['file_path']):
                raise ValueError('bad create_audio_clip')
            import wave
            with wave.open(p['file_path']) as w:
                length = w.getnframes() / w.getframerate()
            tr['slots'][p['clip_index']] = dict(file=p['file_path'], length_s=length,
                                                warping=False, markers=[], name='', adds=0,
                                                reads=0)
            return {'sample_rate': 8000}
        if t == 'set_clip_warping':
            c = self.clip(p)
            c['warping'] = p['warping']
            f = self.first_at                     # Auto-Warp: the first marker on an onset
            c['markers'] = [[0.0, f], [(c['length_s'] - f) * self.tempo / 60, c['length_s']]]
            c['mode'] = None
            return {}
        if t == 'get_clip_info':
            tr = self.tracks[p['track_index']]
            c = tr['slots'].get(p['clip_index'])
            if not c:
                return {'has_clip': False}
            out = {'has_clip': True, 'warping': c.get('warping'), 'loop_start': c.get('ls'),
                   'loop_end': c.get('le'), 'looping': c.get('looping'),
                   'start_marker': c.get('start')}
            if 'length_s' in c:
                c['reads'] += 1
                out.update(sample_rate=8000, sample_length=0 if c['reads'] <= self.decode_reads
                           else int(c['length_s'] * 8000))
            return out
        if t == 'set_clip_warp_mode':
            if p['warp_mode'] not in ('complex_pro', 'beats', 'tones'):
                raise ValueError('bad warp mode')
            self.clip(p)['mode'] = p['warp_mode']
            return {}
        if t == 'get_warp_markers':
            c = self.clip(p)
            if not c['warping']:
                return {'error': 'Warping is disabled'}
            if c['reads'] <= self.decode_reads:   # still decoding: no markers yet
                return {'warp_markers': []}
            if self.inject and c['adds'] >= 3 and not c.get('injected'):
                (b1, s1), (b2, s2) = c['markers'][1], c['markers'][2]
                c['markers'].insert(2, [(b1 + b2) / 2, (s1 + s2) / 2])   # a late Auto-Warp marker
                c['injected'] = True
            return {'warp_markers': [{'beat_time': b, 'sample_time': s} for b, s in c['markers']]}
        if t == 'delete_warp_marker':
            c = self.clip(p)
            vis = c['markers'][:-1]
            hit = [m for m in vis[1:] if abs(m[0] - p['beat_time']) < 1e-3]
            if not hit:
                return {'error': 'No warp marker found'}
            c['markers'].remove(hit[0])
            return {'success': True}
        if t == 'move_warp_marker':
            c = self.clip(p)
            m = next(m for m in c['markers'] if abs(m[0] - p['beat_time']) < 1e-3)
            m[0] += p['distance']
            return {}
        if t == 'add_warp_marker':
            c = self.clip(p)
            b, s = p['beat_time'], p['sample_time']
            ms = c['markers']
            left = [m for m in ms if m[0] < b - 1e-9]
            right = [m for m in ms if m[0] > b + 1e-9]
            if (left and left[-1][1] >= s) or (right and right[0][1] <= s and
                                               right[0] is not ms[-1]):
                raise ValueError('marker out of order')
            c['adds'] += 1
            hidden = ms.pop()
            ms.append([b, s])
            ms.sort()
            last = ms[-1]
            slope = (last[0] - ms[-2][0]) / (last[1] - ms[-2][1]) if len(ms) > 1 else 1
            ms.append([last[0] + (hidden[1] - last[1]) * slope, hidden[1]])
            return {}
        if t == 'set_clip_loop':
            c = self.clip(p)
            ls = p['loop_start'] + (0.5 if self.clamp and 'file' in c and p['loop_start'] == 0
                                    else 0)
            c.update(looping=p['looping'], ls=ls, le=p['loop_end'])
            return {}
        if t == 'set_clip_start_marker':
            self.clip(p)['start'] = p['position']
            return {'success': True}
        if t == 'duplicate_clip':
            tr = self.tracks[p['track_index']]
            new = next(i for i in range(p['clip_index'] + 1, len(self.scenes))
                       if i not in tr['slots'])
            tr['slots'][new] = json.loads(json.dumps(tr['slots'][p['clip_index']]))
            return {'new_index': new}
        raise ValueError(f'Unknown command: {t}')


def run(script, *args, port=None):
    env = dict(os.environ, REMIX_POLL_S='0.01')
    if port:
        env['LIVE_PORT'] = str(port)
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True, env=env)


def prepare(song, *args, out=None):
    out = out or song / 'remix' / 'plan.json'
    r1 = run('remix_plan.py', song, '--out', out, *args)
    r2 = run('remix_parts.py', out)
    assert r1.returncode == 0 and r2.returncode == 0, (r1.stderr, r2.stderr)
    return out


def main():
    fails = 0
    def check(name, cond, info=''):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))

    s44 = make_song(TMP / 'a', loud_pickup=True, nbars=8,
                    sections=[('Intro', 1, 2, 'intro', ''), ('Verse', 3, 8, 'verse', '')])
    plan_p = prepare(s44, '--mode', 'sketch')
    plan = json.loads(plan_p.read_text())
    m = MockLive()
    r = run('remix_build.py', plan_p, port=m.port)
    types = [c['type'] for c in m.calls]
    check('sketch build exits 0', r.returncode == 0, r.stdout + r.stderr)
    first_clip = types.index('create_clip')
    check('meter set and read back before any clip',
          types.index('set_signature') < types.index('get_signature') < first_clip)
    check('tempo set and read back', m.tempo == plan['tempo']['live'])
    names = [t['name'] for t in m.tracks]
    check('tracks: stem, muted mix, new parts', names == [
        'VOX · orig', 'MIX · orig (A/B)', 'DRUMS · new (as-analysed)',
        'BASS · new (as-analysed)', 'KEYS · new (as-analysed)'] and m.tracks[1]['mute'], names)
    check('FULL + one scene per section, named',
          m.scenes[0].startswith('FULL') and m.scenes[1] == 'Intro · bars 1-2'
          and m.scenes[2] == 'Verse · bars 3-8', m.scenes[:3])
    parts = json.loads((plan_p.parent / 'parts.json').read_text())
    full = m.tracks[2]['slots'][0]
    check('FULL drum clip = whole song, every note pushed',
          full['length'] == plan['grid']['total_beats'] and
          len(full['notes']) == len(parts['parts']['drums']))
    vox = m.tracks[0]['slots'][0]
    ia, iw = types.index('create_audio_clip'), types.index('set_clip_warping')
    check('stem loaded, then warped in a separate command, Complex Pro',
          ia < iw and vox['warping'] and vox['mode'] == 'complex_pro')
    want = [[b, s] for s, b in plan['warp']['markers']]
    got = vox['markers'][:-1]
    check('warp markers = one per downbeat, pre-roll first marker on the grid',
          got[1:] == want and abs(got[0][0] - (4.0 - plan['warp']['markers'][0][0] *
                                               4 / (plan['warp']['markers'][1][0] -
                                                    plan['warp']['markers'][0][0]))) < 1e-3,
          (got[:3], want[:2]))
    adds = [c['params']['beat_time'] for c in m.calls if c['type'] == 'add_warp_marker'
            and c['params']['track_index'] == 0]
    check('markers added in beat order', adds == sorted(adds) and len(adds) == len(want))
    check('FULL audio loops the song from beat 0',
          vox['looping'] and vox['ls'] == 0 and vox['le'] == plan['grid']['total_beats']
          and vox['start'] == 0)
    sec = m.tracks[0]['slots'][2]
    check('section copy loops its section (pre-roll included)',
          sec['looping'] and sec['ls'] == 12.0 and sec['le'] == 36.0 and sec['start'] == 12.0,
          (sec.get('ls'), sec.get('le')))
    check('build_report.json written', (plan_p.parent / 'build_report.json').is_file())
    check('the stock-fork traps are never sent',
          not {'create_locator', 'delete_locator'} & set(types))

    # 11/8
    s118 = make_song(TMP / 'b', grouping=(6, 5), pulse_unit=8, bar_s=4.18, nbars=6, db0=0.0,
                     drift=0.01, sections=[('Song', 1, 6, 'verse', '')])
    p118 = prepare(s118, '--preset', 'lo-fi')
    m = MockLive()
    r = run('remix_build.py', p118, port=m.port)
    vox = m.tracks[0]['slots'][0] if m.tracks else {}
    check('11/8 build: signature 11/8, markers every 5.5 beats',
          r.returncode == 0 and m.sig == (11, 8) and
          [x[0] for x in vox['markers'][:3]] == [0.0, 5.5, 11.0], r.stdout + r.stderr)
    check('11/8 section clip = 6 bars of 5.5 beats',
          m.tracks[1]['slots'][1]['length'] == 33.0)

    # Live's first marker past sample 0; a late stray marker; a file still decoding
    s_on = make_song(TMP / 'c', nbars=8, db0=0.0,
                     sections=[('Intro', 1, 2, 'intro', ''), ('Verse', 3, 8, 'verse', '')])
    p_on = prepare(s_on)
    plan_on = json.loads(p_on.read_text())
    m = MockLive(first_at=5.0)
    r = run('remix_build.py', p_on, port=m.port)
    got = {(round(b, 3), round(s, 3)) for b, s in m.tracks[0]['slots'][0]['markers']} \
        if m.tracks else set()
    missing = [x for x in plan_on['warp']['markers']
               if (round(x[1], 3), round(x[0], 3)) not in got]
    check("Live's first marker at 5 s: the downbeats before it get markers too",
          r.returncode == 0 and not missing, (r.stdout[-300:], missing[:3]))
    m = MockLive(inject=True)
    r = run('remix_build.py', p_on, port=m.port)
    check('a stray marker between downbeats fails the read-back (exit 1)',
          r.returncode == 1 and 'extra' in r.stdout, r.stdout[-300:])
    m = MockLive(decode_reads=3)
    r = run('remix_build.py', p_on, port=m.port)
    first_edit = next((i for i, c in enumerate(m.calls) if c['type'] in
                       ('delete_warp_marker', 'move_warp_marker', 'add_warp_marker')), 0)
    reads = sum(c['type'] == 'get_clip_info' for c in m.calls[:first_edit])
    check('a file still decoding (sample length 0, no markers) is waited for',
          r.returncode == 0 and reads >= 4, (reads, r.stdout[-300:]))
    m = MockLive(clamp=True)
    r = run('remix_build.py', p_on, port=m.port)
    check('a FULL loop_start Live clamped -> a warning',
          r.returncode == 0 and 'FULL loop_start' in r.stdout, r.stdout[-300:])

    # section clips: a downbeat humanized a hair early stays in its own section
    sys.path.insert(0, str(SCRIPTS))
    import contextlib, io
    from remix_build import Builder
    parts_on = json.loads((p_on.parent / 'parts.json').read_text())
    a = plan_on['sections'][1]['start_beat']
    fake = dict(parts_on, parts={'drums': [
        dict(pitch=42, start_time=a - 0.5, duration=0.25, velocity=80, mute=False),
        dict(pitch=36, start_time=a - 0.01, duration=0.25, velocity=110, mute=False)]})
    plan_d = dict(plan_on, parts=['drums'])
    b = Builder(plan_d, fake, dry=True, instruments=False)
    with contextlib.redirect_stdout(io.StringIO()):
        b.midi({'drums': 5}, 0)
    clips = {}
    for cmd, prm in b.sent:
        if cmd == 'add_notes_to_clip':
            clips.setdefault(prm['clip_index'], []).extend(prm['notes'])
    check('a note 0.01 beat before a section start opens that section clip at 0',
          [(n['pitch'], n['start_time']) for n in clips.get(2, [])] == [(36, 0.0)] and
          [n['pitch'] for n in clips.get(1, [])] == [42], clips)
    for pre in ('lo-fi', 'garage-punk'):
        out = prepare(s_on, '--preset', pre, out=s_on / pre / 'plan.json')
        pl = json.loads(out.read_text())
        pa = json.loads((out.parent / 'parts.json').read_text())
        b = Builder(pl, pa, dry=True, instruments=False)
        with contextlib.redirect_stdout(io.StringIO()):
            b.midi({p: i for i, p in enumerate(pl['parts'])}, 0)
        lost = []
        for p, ns in pa['parts'].items():
            for i, sec in enumerate(pl['sections']):
                want = sum(abs(n['start_time'] - sec['start_beat']) < 0.05 for n in ns)
                got = sum(1 for cmd, prm in b.sent if cmd == 'add_notes_to_clip'
                          and prm['track_index'] == pl['parts'].index(p)
                          and prm['clip_index'] == 1 + i
                          for n in prm['notes'] if n['start_time'] < 1e-6)
                if want != got:
                    lost.append((p, sec['name'], want, got))
        check(f'{pre}: every section clip holds its downbeat notes', not lost, lost)

    # parts.json from an older plan
    stale = make_song(TMP / 'd', loud_pickup=True, nbars=8,
                      sections=[('Intro', 1, 2, 'intro', ''), ('Verse', 3, 8, 'verse', '')])
    sp = prepare(stale, '--preroll', '0')
    run('remix_plan.py', stale, '--out', sp, '--preroll', '1')
    r = run('remix_build.py', sp, '--dry-run')
    check('parts.json from an older plan -> refused, re-run remix_parts',
          r.returncode != 0 and 'remix_parts.py' in r.stderr, r.stdout[-200:] + r.stderr)
    run('remix_parts.py', sp)
    r = run('remix_build.py', sp, '--dry-run')
    check('after re-running remix_parts the build goes', r.returncode == 0, r.stderr)

    # refusals
    m = MockLive(patched=False)
    r = run('remix_build.py', plan_p, port=m.port)
    check('unpatched Remote Script -> exit 3, no write sent',
          r.returncode == 3 and not any(c['type'].startswith(WRITES) for c in m.calls),
          r.stdout)
    m = MockLive(clips_on_track=True)
    r = run('remix_build.py', plan_p, port=m.port)
    check('Set with clips -> exit 2, nothing written',
          r.returncode == 2 and not any(c['type'].startswith(WRITES) for c in m.calls), r.stdout)
    m = MockLive(clips_on_track=True)
    r = run('remix_build.py', plan_p, '--force', port=m.port)
    check('--force appends tracks after the old ones and scenes after the old rows',
          r.returncode == 0 and m.tracks[0]['name'] == 'old' and m.tracks[1]['name'] == 'VOX · orig'
          and m.scenes[8].startswith('FULL'), r.stdout)
    m = MockLive(swallow={'set_signature'})
    r = run('remix_build.py', plan_p, port=m.port)
    check('error inside a success reply -> exit 1, stops before any clip',
          r.returncode == 1 and 'set_signature' in r.stdout and
          'create_clip' not in [c['type'] for c in m.calls], r.stdout)
    m = MockLive(swallow={'add_warp_marker'})
    r = run('remix_build.py', plan_p, port=m.port)
    check('swallowed warp-marker error -> exit 1', r.returncode == 1 and 'add_warp_marker' in r.stdout)
    count = {'n': 0}
    def second_chunk(msg, _):
        if msg['type'] == 'add_notes_to_clip':
            count['n'] += 1
            return count['n'] == 2
    m = MockLive(fail_on=second_chunk)
    r = run('remix_build.py', p118, port=m.port)
    check('failed note chunk -> exit 1 naming it', r.returncode == 1 and
          'add_notes_to_clip' in r.stdout, r.stdout)
    closed = socket.socket()
    closed.bind(('127.0.0.1', 0))
    port = closed.getsockname()[1]
    closed.close()
    r = run('remix_build.py', plan_p, port=port)
    check('no Live -> exit 4', r.returncode == 4, r.stdout)
    r = run('remix_build.py', plan_p, '--dry-run', port=port)
    check('--dry-run prints the commands without a socket',
          r.returncode == 0 and '"create_audio_clip"' in r.stdout and 'nothing sent' in r.stdout,
          r.stdout[-300:] + r.stderr)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
