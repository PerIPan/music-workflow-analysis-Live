#!/usr/bin/env python3
"""Remix plan + parts -> an Ableton Live Session over the AbletonMCP TCP socket (9877).

Why: dozens of tracks, clips and warp markers and thousands of notes don't belong in the
conversation, and a half-built Set must stop loudly, not report done. Each command is
checked for status "success" AND no result.error (this Remote Script returns some
failures inside a success reply); the first failure exits 1 with the command and reply.

Builds, in order: the Set's meter (read back), tempo (read back), one audio track per kept
stem (+ the original mix, muted, for A/B in a sketch), one MIDI track per new part with an
instrument found by name in Live's browser, a FULL scene plus one scene per section, the
MIDI clips (FULL = whole song; section clips = that section, looping), then the stems: each
file loaded into the FULL slot, warped (vocals Complex Pro, drums Beats), its warp markers
replaced by one per downbeat so Live's bar N = the song's bar N (read back: every planned
marker there, none between them), looped to the song length, and copied into each section
scene looping that section; every stem's markers are read once more at the end. parts.json
must come from this plan (its plan_key), else the build refuses. Needs the patched Remote Script
(create_audio_clip, set_clip_warping, move_warp_marker, a working add_warp_marker; see
ableton-mcp/references/remote-script-patch.md): without it, exit 3 before any write.

A Set that already holds clips is refused (exit 2) unless --force (then tracks and scenes
are appended). Never run it while Claude is also calling mcp__ableton__* tools.

Usage (python3, standard library only):
    remix_build.py PLAN [--parts PARTS] [--dry-run] [--force] [--no-instruments]
Exit: 0 built, 1 a command failed, 2 Set not empty, 3 Remote Script not patched,
4 Live not reachable.
"""
from __future__ import annotations

import argparse, bisect, json, os, socket, sys, time
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from remix_parts import plan_key  # noqa: E402

ADDR = ('127.0.0.1', int(os.environ.get('LIVE_PORT', 9877)))      # override for tests
CHUNK = 300
POLL_S = float(os.environ.get('REMIX_POLL_S', 1.0))
SLICE_W = 0.05                  # beats: a note this close before a section start belongs to it


class Failed(Exception):
    def __init__(self, cmd: str, params: dict, reply):
        short = {k: (f'<{len(v)} notes>' if k == 'notes' else v) for k, v in params.items()}
        super().__init__(f'{cmd} {json.dumps(short)} -> {json.dumps(reply)[:400]}')
        self.reply = reply


class Stop(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


def live(cmd: str, **params):
    """One command per connection; returns the decoded JSON reply."""
    with socket.create_connection(ADDR, timeout=60) as s:
        s.sendall(json.dumps({'type': cmd, 'params': params}).encode())
        buf = b''
        while chunk := s.recv(65536):
            buf += chunk
            try:
                return json.loads(buf)
            except json.JSONDecodeError:
                continue
    raise ConnectionError(f'incomplete reply to {cmd}: {buf[:200]!r}')


def ok(reply) -> bool:
    """Success means status "success" and no error hidden in the result."""
    if not (isinstance(reply, dict) and reply.get('status') == 'success'):
        return False
    res = reply.get('result')
    return not (isinstance(res, dict) and (res.get('error') or res.get('success') is False))


class Sim:
    """Replies for --dry-run: an empty Set with 8 unnamed scenes; no socket is opened."""

    def __init__(self, plan: dict):
        self.tracks, self.scenes, self.plan = 0, 8, plan
        self.sig = (4, 4)

    def __call__(self, cmd: str, p: dict) -> dict:
        if cmd == 'get_capabilities':
            return {'remix_patch': 1}
        if cmd in ('get_session_info', 'health_check'):
            return {'tempo': self.plan['tempo']['live'], 'track_count': self.tracks,
                    'signature_numerator': self.sig[0], 'signature_denominator': self.sig[1]}
        if cmd == 'get_all_scenes':
            return {'scenes': [{'index': i, 'name': ''} for i in range(self.scenes)]}
        if cmd == 'set_signature':
            self.sig = (p['numerator'], p['denominator'])
        if cmd == 'get_signature':
            return {'numerator': self.sig[0], 'denominator': self.sig[1]}
        if cmd in ('create_audio_track', 'create_midi_track'):
            self.tracks += 1
            return {'index': self.tracks - 1}
        if cmd == 'create_scene':
            self.scenes += 1
            return {'index': self.scenes - 1}
        if cmd == 'search_browser':
            return {'results': [{'name': p['query'], 'uri': f"query:{p['query']}",
                                 'is_loadable': True}]}
        if cmd == 'get_track_info':
            return {'devices': [{'name': 'instrument'}], 'clip_slots': []}
        if cmd == 'get_clip_info':
            return {'has_clip': True, 'warping': True, 'loop_start': 0.0, 'start_marker': 0.0,
                    'loop_end': p.get('_loop_end', 0), 'sample_rate': 44100,
                    'sample_length': 44100 * 600}
        if cmd == 'get_warp_markers':
            return {'warp_markers': [{'beat_time': 0.0, 'sample_time': 0.0},
                                     {'beat_time': 1.0, 'sample_time': 0.5}]}
        if cmd == 'duplicate_clip':
            return {'new_index': p.get('_expect')}
        return {}


class Builder:
    def __init__(self, plan: dict, parts: dict, dry: bool, instruments: bool = True):
        self.plan, self.parts, self.dry, self.instruments = plan, parts, dry, instruments
        self.sim = Sim(plan) if dry else None
        self.sent: list[tuple[str, dict]] = []
        self.warnings: list[str] = []
        self.report: dict = {'tracks': {}, 'scenes': {}, 'instruments': {}, 'stems': {}}
        self.marks: dict = {}

    # -- transport
    def raw(self, cmd: str, **p):
        wire = {k: v for k, v in p.items() if not k.startswith('_')}
        self.sent.append((cmd, wire))
        if self.dry:
            show = {k: (f'<{len(v)} notes>' if k == 'notes' else v) for k, v in wire.items()}
            print(json.dumps({'type': cmd, 'params': show}, ensure_ascii=False))
            return {'status': 'success', 'result': self.sim(cmd, p)}
        return live(cmd, **wire)

    def __call__(self, cmd: str, **p) -> dict:
        r = self.raw(cmd, **p)
        if not ok(r):
            raise Failed(cmd, p, r)
        return r.get('result') or {}

    # -- steps
    def probe(self) -> int:
        try:
            self('health_check')
        except (ConnectionError, OSError) as e:
            raise Stop(4, f'Live not reachable on {ADDR[0]}:{ADDR[1]} ({e}): open Live with '
                          'the AbletonMCP control surface selected')
        r = self.raw('get_capabilities')
        if not ok(r) or (r.get('result') or {}).get('remix_patch', 0) < 1:
            raise Stop(3, 'the AbletonMCP Remote Script is not patched (no get_capabilities '
                          'remix_patch >= 1): apply ableton-mcp/references/'
                          'remote-script-patch.md, restart Live, re-run')
        info = self('get_session_info')
        scenes = self('get_all_scenes').get('scenes', [])
        used = []
        for i in range(int(info.get('track_count', 0))):
            t = self('get_track_info', track_index=i)
            if any(s.get('has_clip') for s in t.get('clip_slots', [])):
                used.append(t.get('name', str(i)))
        need = 1 + len(self.plan['sections'])
        named = [s for s in scenes[:need] if s.get('name')]
        if used or named:
            if not self.force:
                raise Stop(2, f'the Set is not empty (clips on {used[:5]}, named scenes '
                              f'{[s["name"] for s in named][:3]}): open a new Set, or '
                              '--force to append tracks and scenes')
            return len(scenes)
        return 0

    def setup(self) -> None:
        g, T = self.plan['grid'], self.plan['tempo']['live']
        self('set_signature', numerator=g['numerator'], denominator=g['denominator'])
        got = self('get_signature')
        if (got.get('numerator'), got.get('denominator')) != (g['numerator'], g['denominator']):
            raise Failed('get_signature', {}, got)
        self('set_tempo', tempo=T)
        got = self('get_session_info')
        if abs(float(got.get('tempo', 0)) - T) > 0.01:
            raise Failed('get_session_info (tempo)', {'tempo': T}, got)

    def tracks(self) -> dict:
        idx = {}
        for s in self.plan['stems']:
            t = self('create_audio_track', index=-1)['index']
            self('set_track_name', track_index=t, name=s['track_name'])
            if s['mute']:
                self('set_track_mute', track_index=t, mute=True)
            idx[s['name']] = t
        for p in self.plan['parts']:
            t = self('create_midi_track', index=-1)['index']
            self('set_track_name', track_index=t,
                 name=f"{p.upper()} · new ({self.parts['preset']})")
            idx[p] = t
        self.report['tracks'] = idx
        return idx

    def instrument(self, part: str, track: int) -> None:
        cat = 'drums' if part == 'drums' else 'sounds'
        for q in self.parts.get('search', {}).get(part, []):
            res = self('search_browser', query=q, category=cat).get('results', [])
            item = next((x for x in res if x.get('is_loadable') and x.get('uri')), None)
            if not item:
                continue
            r = self.raw('load_browser_item', track_index=track, item_uri=item['uri'])
            if not ok(r) and 'Timeout' not in json.dumps(r):
                continue                          # not found: try the next name
            for _ in range(15):                   # the load reply can't be trusted: poll
                devs = self('get_track_info', track_index=track).get('devices', [])
                if devs:
                    self.report['instruments'][part] = item.get('name')
                    return
                if not self.dry:
                    time.sleep(POLL_S)
        self.warnings.append(f'{part}: no instrument loaded (tried '
                             f"{self.parts.get('search', {}).get(part)}) - load one by hand")

    def scenes(self, base: int) -> None:
        have = len(self('get_all_scenes').get('scenes', []))
        need = 1 + len(self.plan['sections'])
        for _ in range(max(0, base + need - have)):
            self('create_scene', index=-1)
        song = self.plan['song']
        self('set_scene_name', scene_index=base,
             name=f"FULL · {song['title']} ({self.plan['mode']}, {self.parts['preset']})")
        for i, s in enumerate(self.plan['sections']):
            self('set_scene_name', scene_index=base + 1 + i,
                 name=f"{s['name']} · bars {s['first_bar']}-{s['last_bar']}")

    def clip_notes(self, track: int, slot: int, length: float, notes: list, name: str):
        self('create_clip', track_index=track, clip_index=slot, length=length)
        for i in range(0, len(notes), CHUNK):
            try:
                self('add_notes_to_clip', track_index=track, clip_index=slot,
                     notes=notes[i:i + CHUNK])
            except Failed as e:
                raise Failed('add_notes_to_clip', {'after_notes': i}, e.reply) from None
        self('set_clip_name', track_index=track, clip_index=slot, name=name)

    def midi(self, idx: dict, base: int) -> None:
        g = self.plan['grid']
        for p in self.plan['parts']:
            ns = self.parts['parts'].get(p, [])
            self.clip_notes(idx[p], base, g['total_beats'], ns, f'{p} · FULL')
            for i, s in enumerate(self.plan['sections']):
                a, b = s['start_beat'], s['end_beat']
                # a note humanized just before a section start is that section's downbeat
                sl = [dict(n, start_time=round(max(0.0, n['start_time'] - a), 6),
                           duration=round(min(n['duration'], b - max(a, n['start_time'])), 6))
                      for n in ns if a - SLICE_W <= n['start_time'] < b - SLICE_W]
                if sl:
                    self.clip_notes(idx[p], base + 1 + i, b - a, sl, f"{p} · {s['name']}")

    def beat_of(self, sec: float) -> float:
        m = self.plan['warp']['markers']
        xs = [x[0] for x in m]
        k = min(max(bisect.bisect_right(xs, sec) - 1, 0), len(m) - 2)
        (s0, b0), (s1, b1) = m[k], m[k + 1]
        return b0 + (sec - s0) * (b1 - b0) / (s1 - s0)

    def settle(self, track: int, slot: int) -> list:
        """Wait until Live has finished with a new file: its sample length above 0 and
        two reads of the warp markers a moment apart the same (Auto-Warp and decoding run
        in the background). Returns the settled markers."""
        prev = None
        for _ in range(40):
            info = self('get_clip_info', track_index=track, clip_index=slot)
            ms = self('get_warp_markers', track_index=track, clip_index=slot) \
                .get('warp_markers', [])
            sl = info.get('sample_length')
            key = (sl, [(round(m['beat_time'], 4), round(m['sample_time'], 4)) for m in ms])
            if ms and (sl is None or sl > 0) and (key == prev or self.dry):
                return ms
            prev = key
            time.sleep(POLL_S / 2)
        raise Failed('get_warp_markers (settle)', {'track_index': track},
                     'the markers or sample length kept changing')

    def check_markers(self, track: int, slot: int, want: list, what: str) -> None:
        """Every planned marker there (0.001 beat, 0.001 s), and no other marker except
        one past the last planned beat (Live's hidden end marker)."""
        got = self('get_warp_markers', track_index=track, clip_index=slot) \
            .get('warp_markers', [])
        hit = lambda x, s, b: abs(x['beat_time'] - b) < 1e-3 and abs(x['sample_time'] - s) < 1e-3
        missing = [(s, b) for s, b in want if not any(hit(x, s, b) for x in got)]
        extra = [x for x in got if not any(hit(x, s, b) for s, b in want)]
        last = max(b for _, b in want)
        stray = extra if len(extra) > 1 else [x for x in extra if x['beat_time'] <= last + 1e-3]
        if missing or stray:
            raise Failed(f'get_warp_markers ({what})',
                         {'missing': missing[:5],
                          'extra': [(x['sample_time'], x['beat_time']) for x in stray][:5]},
                         {'count': len(got), 'planned': len(want)})

    def warp(self, track: int, slot: int) -> list:
        """Replace Live's warp markers with the plan's: one per downbeat. Returns the
        markers the clip must now hold, as (sample seconds, beat)."""
        ms = self.settle(track, slot)
        vis = ms[:-1] if len(ms) > 1 else ms              # the last one is hidden
        for m in reversed(vis[1:]):
            self('delete_warp_marker', track_index=track, clip_index=slot,
                 beat_time=m['beat_time'])
        m0 = vis[0]
        s0 = float(m0['sample_time'])
        target = round(self.beat_of(s0), 6)
        if abs(target - m0['beat_time']) > 1e-4:
            self('move_warp_marker', track_index=track, clip_index=slot,
                 beat_time=m0['beat_time'], distance=round(target - m0['beat_time'], 6))
        plan_m = self.plan['warp']['markers']
        after = [(s, b) for s, b in plan_m if s > s0 + 0.001]
        # Live's first marker can sit past sample 0 (Auto-Warp puts it on the first onset):
        # the downbeats before it go in right to left, each one left of the current first
        before = [(s, b) for s, b in plan_m if s < s0 - 0.001]
        for s, b in after + list(reversed(before)):
            self('add_warp_marker', track_index=track, clip_index=slot, beat_time=b,
                 sample_time=s)
        want = sorted(before + [(s0, target)] + after, key=lambda x: x[1])
        if not self.dry:
            self.check_markers(track, slot, want, 'read-back')
        return want

    def audio(self, idx: dict, base: int) -> None:
        g = self.plan['grid']
        for s in self.plan['stems']:
            t = idx[s['name']]
            r = self.raw('create_audio_clip', track_index=t, clip_index=base,
                         file_path=s['path'])
            if not ok(r):
                if 'Timeout' not in json.dumps(r):
                    raise Failed('create_audio_clip', {'file_path': s['path']}, r)
                for _ in range(30):                   # slow import: poll, never re-send
                    if self('get_clip_info', track_index=t, clip_index=base).get('has_clip'):
                        break
                    time.sleep(POLL_S)
                else:
                    raise Failed('create_audio_clip (poll)', {'file_path': s['path']}, r)
            self('set_clip_warping', track_index=t, clip_index=base, warping=True)
            for _ in range(10):                       # Live defers the warp switch
                if self('get_clip_info', track_index=t, clip_index=base).get('warping'):
                    break
                if not self.dry:
                    time.sleep(POLL_S / 4)
            else:
                raise Failed('set_clip_warping', {'track_index': t}, 'warping stayed off')
            self('set_clip_warp_mode', track_index=t, clip_index=base, warp_mode=s['warp_mode'])
            want = self.warp(t, base)
            self.marks[t] = (s['name'], want)
            self('set_clip_loop', track_index=t, clip_index=base, looping=True,
                 loop_start=0.0, loop_end=g['total_beats'])
            self('set_clip_start_marker', track_index=t, clip_index=base, position=0.0)
            self('set_clip_name', track_index=t, clip_index=base, name=f"{s['name']} · FULL")
            info = self('get_clip_info', track_index=t, clip_index=base,
                        _loop_end=g['total_beats'])
            if abs(float(info.get('loop_end', 0)) - g['total_beats']) > 1e-3:
                self.warnings.append(f"{s['name']}: FULL loop end {info.get('loop_end')} != "
                                     f"{g['total_beats']} beats (file shorter?)")
            for k in ('loop_start', 'start_marker'):     # Live may clamp to the first sample
                v = info.get(k)
                if v is not None and abs(float(v)) > 1e-3:
                    self.warnings.append(f"{s['name']}: FULL {k} {v} != 0 (Live clamped it to "
                                         'the sample start?): the stem is off against the '
                                         'MIDI; re-plan with --preroll 0')
            for i, sec in enumerate(self.plan['sections']):
                slot = base + 1 + i
                got = self('duplicate_clip', track_index=t, clip_index=base, _expect=slot)
                if got.get('new_index') != slot:
                    raise Failed('duplicate_clip', {'expected_slot': slot}, got)
                self('set_clip_loop', track_index=t, clip_index=slot, looping=True,
                     loop_start=sec['start_beat'], loop_end=sec['end_beat'])
                self('set_clip_start_marker', track_index=t, clip_index=slot,
                     position=sec['start_beat'])
                self('set_clip_name', track_index=t, clip_index=slot,
                     name=f"{s['name']} · {sec['name']}")
            self.report['stems'][s['name']] = {'warp_markers': len(want), 'path': s['path']}
        if not self.dry:                          # late Auto-Warp or decoding changes
            for t, (name, want) in self.marks.items():
                self.check_markers(t, base, want, f'{name}, final check')

    def run(self, force: bool) -> None:
        self.force = force
        base = self.probe()
        self.setup()
        idx = self.tracks()
        if self.instruments:
            for p in self.plan['parts']:
                self.instrument(p, idx[p])
        self.scenes(base)
        self.midi(idx, base)
        self.audio(idx, base)
        self.report['scenes'] = {'full': base, 'sections': base + 1}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('plan')
    ap.add_argument('--parts', help='parts.json (default: beside the plan)')
    ap.add_argument('--dry-run', action='store_true', help='print the commands; no socket')
    ap.add_argument('--force', action='store_true', help='append to a Set that has clips')
    ap.add_argument('--no-instruments', action='store_true')
    a = ap.parse_args()
    plan_p = Path(a.plan)
    plan = json.loads(plan_p.read_text())
    parts_p = Path(a.parts) if a.parts else plan_p.parent / 'parts.json'
    if not parts_p.is_file():
        sys.exit(f'remix_build: {parts_p} not found: run remix_parts.py first')
    parts = json.loads(parts_p.read_text())
    if parts.get('plan_key') != plan_key(plan):
        sys.exit(f'remix_build: {parts_p} was made for another plan (the plan was re-run '
                 'since): re-run remix_parts.py on this plan first')
    missing = [s['path'] for s in plan['stems'] if not Path(s['path']).is_file()]
    if missing:
        sys.exit(f'remix_build: stem files missing: {missing}')
    b = Builder(plan, parts, a.dry_run, not a.no_instruments)
    try:
        b.run(a.force)
    except Stop as e:
        print(f'STOP: {e}')
        sys.exit(e.code)
    except Failed as e:
        print(f'FAILED after {len(b.sent)} commands: {e}')
        sys.exit(1)
    except OSError as e:                              # the connection dropped mid-build
        print(f'FAILED after {len(b.sent)} commands: Live stopped answering ({e})')
        sys.exit(4)
    for w in b.warnings:
        print(f'WARNING: {w}')
    if a.dry_run:
        print(f'dry run: {len(b.sent)} commands, nothing sent')
        return
    b.report.update(commands=len(b.sent), warnings=b.warnings,
                    tempo=plan['tempo']['live'], signature=plan['grid']['time_signature'])
    (plan_p.parent / 'build_report.json').write_text(json.dumps(b.report, indent=1))
    print(f"built: {len(b.sent)} commands; tracks {b.report['tracks']}; instruments "
          f"{b.report['instruments']}; FULL scene {b.report['scenes']['full'] + 1} in Live's "
          'UI. Fire FULL, then check bar 1, a mid-song chorus and the last chorus.')


if __name__ == '__main__':
    main()
