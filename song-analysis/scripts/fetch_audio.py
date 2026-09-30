#!/usr/bin/env python3
"""Phase 0 (optional): a song's name -> its recording on YouTube -> <Artist> - <Title>.wav.

For when the user names a song instead of handing over a file ("analyse <title> by
<artist>"). Search mode lists the likely uploads, best first, and downloads nothing (yt-dlp
may refresh its own cache, ~/.cache/yt-dlp); show the top pick to the user - title, channel, length and, for label audio, album and year (a live album
or a re-recording can carry the plain title) - and once they confirm it, download mode puts
the WAV in the song folder.

YouTube Music first: its song results are the labels' own uploads of the studio master
("Provided to YouTube by ...", the "- Topic" channels) - the recording the analysis is about.
A plain YouTube search adds the artist's official audio and videos, and everything else.
rank(), a pure function over plain dicts, favours label audio, the artist's own or a verified
channel and "Official Audio", and rejects other recordings of the song - live ("Song @ The
Venue" too), cover, karaoke, instrumental, sped up, slowed, reverb, nightcore, 8D, remix or
rework, acoustic, piano version, medley, mashup, reaction, tutorial, loop, 1 hour, extended -
but never for a word or an "@" of the song's own title or the artist's name ("Live Forever";
the band Live where its name stands outside brackets: "Song (Live)" is still rejected). The
uploads that name the song come first: every word of artist + title (of the query when not
both are known) in the video's title, track, channel or artists, in any spelling or script
(Greek folded to Latin, y as i, ch as h, ...: labels transliterate every which way). Lyric
videos lose a little (re-uploads, often re-encoded). Length settles the rest: with --duration
(the length of a copy the user has) "Official Audio" on the artist's channel within ~2 s beats
label audio there 5 s or more off (a re-upload does not), and > 15 s off costs points; without
it, the median length of the candidates that name the song counts a little. Views break ties.
The download is the best audio stream decoded by ffmpeg to 16-bit PCM WAV at its own rate,
stereo kept: Phase 2 wants WAV anyway (demucs reads MP3 without the gapless trim).

Only for study of a recording you have the right to use: YouTube's Terms restrict
downloading, so that call is yours. Nothing is uploaded or shared; no cookies, logins or
browser profiles are used.

Usage (yt-dlp's venv python; plain python3 only imports the helpers for the tests):
    fetch_audio.py "Artist Title" [--artist A --title T] [--duration SEC|M:SS] [--out-dir DIR] \
        [--json]
    fetch_audio.py --url URL [--artist A --title T] [--out-dir DIR] [--duration SEC] \
        [--dry-run] [--force] [-- "Artist Title"]
Search mode prints which searches ran, then rank, score, length, channel, title, URL and
reasons per candidate, marks the top pick and prints the command that downloads it into DIR
(default: the working folder; made absolute, so the command runs from anywhere); --json
prints the same as JSON. Download mode writes DIR/<Artist> - <Title>.wav (names from
--artist/--title, else YouTube's music metadata - the credited artist the query names, the
track without a remaster or feat. tail - else the video title) and DIR/source.json (where the
audio came from, the format taken, the tools); without --force it replaces neither an existing
WAV nor a source.json about another WAV; a live stream is refused; --dry-run resolves and
prints both, downloading nothing. Exit 0 ok; 1 nothing found, all rejected, a live stream, a
file in the way or download failed; 2 yt-dlp or ffmpeg missing, or bad arguments.

Needs yt-dlp (Unlicense) in its own venv, and this script run with that venv's python:
    uv venv --python 3.12 .venv-ytdlp && \
        uv pip install --python .venv-ytdlp/bin/python -U "yt-dlp[default]"
a JavaScript runtime for YouTube's challenges, looked up in the venv's bin and on PATH: deno
>= 2.3 (recommended; "yt-dlp[default,deno]" installs it into the venv), node >= 22 or
quickjs; and ffmpeg on PATH (ffprobe is not needed).
"""
from __future__ import annotations

import argparse, datetime, json, math, os, re, shlex, shutil, statistics, subprocess, sys
import sysconfig, tempfile, unicodedata, urllib.parse, wave
from collections import Counter
from pathlib import Path

INSTALL = ('uv venv --python 3.12 .venv-ytdlp && uv pip install --python .venv-ytdlp/bin/python '
           '-U "yt-dlp[default]"')
RIGHTS = ("Only for study of a recording you have the right to use; YouTube's Terms restrict "
          "downloading, so that call is yours. Nothing is uploaded or shared.")
MUSIC_SEARCH = 'https://music.youtube.com/search?q={}#songs'
N_MUSIC, N_VIDEO = 3, 8
# yt-dlp name, executable, version flag, version pattern, minimum version - in yt-dlp's order
RUNTIMES = (('deno', 'deno', '--version', r'^deno (\S+)', (2, 3, 0)),
            ('node', 'node', '--version', r'^v(\S+)', (22, 0, 0)),
            ('quickjs', 'qjs', '--help', r'^QuickJS(-ng)?\s+version\s+(\S+)', (2023, 12, 9)))
NOISE = {'by', 'song', 'official', 'audio', 'video', 'lyrics', 'lyric', 'feat', 'ft', 'featuring'}
REJECT = (('live', r'live|unplugged|concerts?|tour|festival|tiny desk|sessions?'),
          ('cover', r'covers?|covered|originally performed by|in the style of|made famous by|tribute'),
          ('karaoke', r'karaoke|backing track|sing ?along'),
          ('instrumental', r'instrumentals?|a ?capp?ella'),
          ('sped up', r'sped ?up|speed ?up'),
          ('slowed', r'slowed'),
          ('reverb', r'reverb'),
          ('nightcore', r'nightcore'),
          ('8D', r'8d'),
          ('bass boosted', r'bass ?boosted'),
          ('remix', r'remix(?:es|ed)?|rmx|bootleg|re ?works?|re ?worked'),
          ('acoustic', r'acoustic|stripped'),
          ('piano version', r'piano (?:version|ver)'),
          ('medley', r'medley'),
          ('mashup', r'mash ?up'),
          ('reaction', r'reaction|reacts?|reacting'),
          ('tutorial', r'tutorial|lessons?|how to play|chords|tabs'),
          ('loop', r'loop(?:s|ed)?'),
          ('1 hour', r'(?:\d+|one|ten) ?(?:hours?|hrs?)'),
          ('extended', r'extended'),
          ('full album', r'full (?:album|ep)'),
          ('interview', r'interview|podcast|documentary|behind the song|making of|explained|meaning'),
          ('snippet', r'snippet|teaser|trailer|preview'),
          ('demo', r'demo'))
REJECT_RE = tuple((name, re.compile(rf'\b(?:{p})\b')) for name, p in REJECT)
AT_RE = re.compile(r'(?<!\S)@(?!\S)')                              # 'Song @ The Venue'
BRACKETS = re.compile(r'[(\[{][^)\]}]*[)\]}]')
APOSTROPHES = re.compile("['’‘‛`´ʼ′＇]")                           # cut before NFKD splits ´
LYRIC_RE = re.compile(r'\b(?:lyrics?|letra|paroles)\b')
OFFICIAL = ((re.compile(r'\bofficial audio\b'), 'official audio', 10.0),
            (re.compile(r'\bvisuali[sz]er\b'), 'visualizer', 5.0),
            (re.compile(r'\bofficial (?:music )?video\b'), 'official video', 2.0))
LABEL, OWN_CHANNEL, VERIFIED, LYRIC_VIDEO = 40.0, 15.0, 5.0, -4.0    # label uploads: views decide
STRONG = ((0, 45.0), (2, 40.0), (5, 0.0), (15, -10.0))    # (seconds off --duration, points)
WEAK = ((0, 8.0), (2, 6.0), (15, 0.0))                     # (seconds off the median, points)
CHANNEL_TAILS = ('topic', 'vevo', 'official', 'music', 'tv', 'channel')
STATUS = {'is_live': 'live stream', 'post_live': 'live stream', 'was_live': 'past live stream',
          'is_upcoming': 'not out yet'}
NOT_READY = {'is_live': 'a live stream', 'post_live': 'a live stream still being processed',
             'is_upcoming': 'not out yet'}
LOCKED = {'needs_auth', 'premium_only', 'subscriber_only', 'private'}
FIELDS = ('id', 'title', 'channel', 'channel_is_verified', 'duration', 'view_count', 'live_status',
          'availability', 'artist', 'artists', 'track', 'album', 'license', 'upload_date',
          'release_date', 'release_year')
GREEK = {'ου': 'ou', 'αυ': 'av', 'ευ': 'ev', 'θ': 'th', 'χ': 'h', 'ψ': 'ps', 'ξ': 'x',
         **dict(zip('αβγδεζηικλμνοπρστυφω', 'avgdeziiklmnoprstifo'))}
GREEK_RE = re.compile('|'.join(sorted(GREEK, key=len, reverse=True)))
SPELL = (('y', 'i'), ('kh', 'h'), ('ch', 'h'), ('ei', 'i'), ('oi', 'i'), ('ai', 'e'), ('gk', 'g'),
         ('ng', 'g'))
TAIL = re.compile(r'\s+(?:[(\[](?:feat\b|ft\b|featuring\b|[^()\[\]]*remaster)'
                  r'|[-–—]\s+[^-–—]*remaster).*$', re.I)
ROLE = re.compile(r'\s*\([^()]*\)$')                              # a credit's '(Vocal)'
P_YEAR = re.compile(r'℗\D{0,25}?((?:18|19|20)\d\d)')


# ------------------------------------------------------------------ names and words

def words(s: str | None) -> list[str]:
    """Lower-case word tokens without accents or apostrophes, & as 'and':
    'Beyoncé – Don’t Stop & Go' -> ['beyonce', 'dont', 'stop', 'and', 'go']."""
    s = unicodedata.normalize('NFKD', APOSTROPHES.sub('', s or '')).casefold()
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.findall(r'\w+', s.replace('&', ' and '))


def spelling(w: str) -> str:
    """A word of words() in one spelling, so transliterations match: Greek by sound in Latin,
    y as i, ch/kh as h, ei/oi as i, ai as e, gk/ng as g, doubled letters once: 'συννεφιασμενη',
    'synnefiasmeni', 'sinnefiasmeni' -> 'sinefiasmeni'; 'frangosyriani' -> 'fragosiriani'."""
    w = GREEK_RE.sub(lambda m: GREEK[m.group()], w)
    for a, b in SPELL:
        w = w.replace(a, b)
    return re.sub(r'(.)\1+', r'\1', w)


def artist_key(s: str | None) -> str:
    """'The Nova Tide', 'Nova Tide - Topic', 'NovaTideVEVO' -> 'novatide'."""
    ws = words(s)
    if len(ws) > 1 and ws[0] == 'the':
        ws = ws[1:]
    k, cut = ''.join(ws), True
    while cut:
        cut = False
        for tail in CHANNEL_TAILS:
            if k.endswith(tail) and len(k) > len(tail):
                k, cut = k[:-len(tail)], True
    return k


def meta_artists(e: dict) -> list[str]:
    """The artists in YouTube's music metadata, a role in brackets cut ('X (Vocal)' -> 'X'),
    duplicates dropped (labels list some twice)."""
    names = e.get('artists') or ([e['artist']] if e.get('artist') else [])
    return list(dict.fromkeys(ROLE.sub('', a).strip() or a for a in names
                              if isinstance(a, str) and a.strip()))


def meta_artist(e: dict, first: bool = False) -> str | None:
    """meta_artists joined; first=True: only the first, the main artist (for file names)."""
    names = meta_artists(e)
    return (names[0] if first else ', '.join(names)) if names else None


def base_title(t: str | None) -> str | None:
    """A track name without a remaster or feat. tail: 'Song (2004 Remaster)', 'Song - 2011
    Remaster', 'Song (feat. X (Vocal)) [Remastered 2017]' -> 'Song'."""
    return (TAIL.sub('', t).strip() or t) if t else t


def file_names(c: dict, query: str | None) -> tuple[str | None, str | None]:
    """(artist, title) for the WAV from YouTube's music metadata: the first credited artist the
    query names, else the first credit (a composer may be credited first); base_title(track)."""
    credits, qw = meta_artists(c), set(words(query))
    named = [a for a in credits if words(a) and set(words(a)) <= qw]
    return (named or credits or [None])[0], base_title(c.get('track'))


def safe_name(s: str | None, limit: int = 200) -> str:
    """s as one safe file name: NFC; ': ' -> ' - '; / \\ | : -> '-'; < > " ? * dropped, and
    control and format characters (bidi overrides, zero-width spaces; the joiners that build
    emoji and some scripts stay); whitespace collapsed; no leading/trailing dots or spaces; at
    most `limit` UTF-8 bytes (cut on a character); 'audio' if nothing is left."""
    s = unicodedata.normalize('NFC', s or '')
    s = re.sub(r'\s*:\s+', ' - ', s)
    s = re.sub(r'[/\\|:]', '-', s)
    s = re.sub(r'\s+', ' ', re.sub(r'[<>"?*]', '', s))
    s = ''.join(c for c in s if unicodedata.category(c) != 'Cc'
                and (unicodedata.category(c) != 'Cf' or c in '\u200c\u200d')).strip(' .')
    s = s.encode('utf-8')[:limit].decode('utf-8', 'ignore').rstrip(' .')
    return s or 'audio'


def wav_name(artist: str | None, title: str | None, fallback: str | None) -> str:
    """'<Artist> - <Title>.wav' when both are known, else '<fallback (the video title)>.wav'."""
    stem = f'{safe_name(artist)} - {safe_name(title)}' if artist and title else safe_name(fallback)
    return safe_name(stem) + '.wav'


def seconds(s: str) -> float:
    """'178.71', '2:58.71' or '1:02:03' -> seconds (an argparse type)."""
    try:
        parts = [float(p) for p in s.split(':')]
    except ValueError:
        parts = []
    if not 1 <= len(parts) <= 3 or any(p < 0 or not math.isfinite(p) for p in parts):
        raise argparse.ArgumentTypeError(f'not a length: {s!r} (seconds, m:ss or h:mm:ss)')
    return float(sum(p * 60 ** i for i, p in enumerate(reversed(parts))))


def mmss(t: float | None, digits: int = 0) -> str:
    """178.71 -> '2:59' ('2:58.7' with digits=1); 3723 -> '1:02:03'; None -> '?'."""
    if t is None:
        return '?'
    t = round(float(t), digits)
    m, s = divmod(t, 60)
    h, m = divmod(int(m), 60)
    sec = f'{s:0{3 + digits}.{digits}f}' if digits else f'{int(s):02d}'
    return f'{h}:{m:02d}:{sec}' if h else f'{m}:{sec}'


def short(n: float) -> str:
    """1117 -> '1.1k', 472304 -> '472k', 3e6 -> '3.0M'."""
    for div, unit in ((1e9, 'B'), (1e6, 'M'), (1e3, 'k')):
        if n >= div:
            return f'{n / div:.1f}{unit}' if n / div < 10 else f'{n / div:.0f}{unit}'
    return str(int(n))


# ------------------------------------------------------------------ ranking (pure)

def strip_words(ws: list[str], protect: Counter) -> list[str]:
    """ws minus the song's own words, each as often as the song has it: 'Live Forever (Live)'
    minus 'live forever' leaves 'live'."""
    budget, left = Counter(protect), []
    for w in ws:
        if budget[w] > 0:
            budget[w] -= 1
        else:
            left.append(w)
    return left


def own_words(c: dict, artist: str | None, title: str | None) -> Counter:
    """The song's words c's title may use without being rejected: the title's, and the artist's
    where the name stands outside brackets ('Live - Song (Live)' spends one 'live' on the band,
    'Song (Live)' none)."""
    outside, name = words(BRACKETS.sub(' ', c.get('title') or '')), words(artist)
    named = bool(name) and any(outside[i:i + len(name)] == name for i in range(len(outside)))
    return Counter(words(title)) + (Counter(name) if named else Counter())


def rejections(c: dict, protect: Counter, ats: int, lo: float, hi: float) -> list[str]:
    """Why c is another recording or out of reach: title words (the song's own words taken
    out first), more ' @ ' than the song's name has ('Song @ The Venue'), live status, a login
    wall, a length outside [lo, hi]."""
    title = c.get('title') or ''
    text = ' '.join(strip_words(words(title), protect))
    out = [name for name, rx in REJECT_RE if rx.search(text)]
    if 'live' not in out and len(AT_RE.findall(title)) > ats:
        out.append('live')
    if c.get('live_status') in STATUS:
        out.append(STATUS[c['live_status']])
    if c.get('availability') in LOCKED:
        out.append(f"needs login ({c['availability']})")
    d = c.get('duration')
    if d is not None and not lo <= d <= hi:
        out.append(f"too {'short' if d < lo else 'long'} ({mmss(d)})")
    return out


def label_kind(c: dict) -> str | None:
    """How c shows it is the label's upload of the master, if it does."""
    if c.get('music_rank'):
        return f"YouTube Music #{c['music_rank']}"
    if (c.get('channel') or '').endswith(' - Topic'):
        return 'Topic channel'
    if (c.get('description') or '').lstrip().startswith('Provided to YouTube by'):
        return 'Provided to YouTube'
    return None


def album_note(c: dict) -> str | None:
    """"album 'Time Out' ℗ 1959" for a label upload (℗ year from its description, else
    YouTube's release year in brackets), else None."""
    if not c.get('album'):
        return None
    year = (f" ℗ {c['p_year']}" if c.get('p_year') else
            f" ({c['release_year']})" if c.get('release_year') else '')
    return f"album {c['album']!r}{year}"


def own_channel(channel: str | None, artist: str | None, query: str | None) -> bool:
    """Is the channel the artist's ('Nova Tide', 'Nova Tide - Topic', 'NovaTideVEVO')? With no
    artist name, a channel named like the query's first or last words counts."""
    key = artist_key(channel)
    if not key:
        return False
    if artist:
        return key in {artist_key(a) for a in (artist, *re.split(r'\s*[,&]\s*', artist))}
    qw = words(query)
    return any(key in (artist_key(' '.join(qw[:k])), artist_key(' '.join(qw[-k:])))
               for k in range(1, len(qw)))


def length_points(d: float | None, ref: float | None, strong: bool) -> tuple[float, str | None]:
    """Points for |d - ref| on a piecewise-linear curve (STRONG against --duration: 2 s off
    keeps 40 of 45, 5 s off none, so the artist's Official Audio within 2 s outweighs label
    audio 5 s off; WEAK against the median); beyond 15 s a penalty."""
    if d is None:
        return 0.0, 'length unknown'
    if ref is None:
        return 0.0, None
    diff = round(d - ref, 1) + 0.0                                  # + 0.0: no '-0.0'
    a, curve = abs(d - ref), STRONG if strong else WEAK
    if a > curve[-1][0]:
        pts = -min(30.0, 10 + (a - 15) / 3) if strong else -8.0
    else:
        (x0, y0), (x1, y1) = next(seg for seg in zip(curve, curve[1:]) if a <= seg[1][0])
        pts = y0 + (y1 - y0) * (a - x0) / (x1 - x0)
    return pts, f'length {diff:+.1f} s' + ('' if strong else f' vs median {mmss(ref)}')


def score(c: dict, ref: float | None, strong: bool, artist: str | None, query: str | None,
          protect: Counter) -> tuple[float, list[str]]:
    """Points for being the studio master from a trustworthy uploader, and the reasons."""
    pts, why = 0.0, []
    if c['rejected']:
        why.append('rejected: ' + ', '.join(c['rejected']))
    if c['missing']:
        why.append('missing: ' + ', '.join(c['missing']))
    label = label_kind(c)
    if label:
        pts += LABEL
        why.append(f'label audio ({label})')
    own = own_channel(c.get('channel'), artist, query)
    if own:
        pts += OWN_CHANNEL
        why.append("artist's channel")
    if c.get('channel_is_verified'):
        pts += VERIFIED
        why.append('verified')
    tw = words(c.get('title'))
    for rx, name, p in OFFICIAL:
        if rx.search(' '.join(tw)):
            trusted = own or label or c.get('channel_is_verified')
            pts += p if trusted else 0
            why.append(name if trusted else f'says "{name}" (re-upload channel)')
            break
    if LYRIC_RE.search(' '.join(strip_words(tw, protect))):
        pts += LYRIC_VIDEO
        why.append('lyric video')
    lp, lr = length_points(c.get('duration'), ref, strong)
    pts += lp
    if lr:
        why.append(lr)
    if c.get('view_count'):
        pts += 0.5 * math.log10(1 + c['view_count'])
        why.append(f"{short(c['view_count'])} views")
    note = album_note(c)
    if note:
        why.append(note)
    return round(pts, 1), why


def rank(entries: list[dict], artist: str | None = None, title: str | None = None,
         duration: float | None = None, query: str | None = None) -> list[dict]:
    """Candidates best first, as copies with rank, score, named, missing, rejected, reasons
    and length_ref (--duration or the median). Order: not rejected, then naming the song
    (every word of artist + title - with only one of them or neither, of the query plus the
    name given - in the video's title, track, channel or artists, in any spelling()), then
    score."""
    both = bool(words(artist) and words(title))
    at = lambda s: len(AT_RE.findall(s or ''))                      # noqa: E731
    if both:
        basis, ats = words(artist) + words(title), at(artist) + at(title)
    else:
        basis = list((Counter(words(query)) | Counter(words(artist) + words(title))).elements())
        ats = max(at(query), at(artist) + at(title))
    want = [w for w in dict.fromkeys(basis) if w not in NOISE]
    lo, hi = (min(60.0, duration / 2), max(720.0, duration * 2)) if duration else (60.0, 720.0)
    out = []
    for e in entries:
        c = dict(e)
        hay = {spelling(w) for w in (*words(c.get('title')), *words(c.get('track')),
                                     *words(c.get('channel')), *words(meta_artist(c)))}
        c['missing'] = [w for w in want if spelling(w) not in hay]
        c['named'] = not c['missing']
        protect = own_words(c, artist, title) if both else Counter(basis)
        c['rejected'] = rejections(c, protect, ats, lo, hi)
        out.append((c, protect))
    pool = [c['duration'] for c, _ in out if c['named'] and not c['rejected'] and c.get('duration')]
    if len(pool) < 2:
        pool = [c['duration'] for c, _ in out if not c['rejected'] and c.get('duration')]
    ref = duration or (statistics.median(pool) if pool else None)
    for c, protect in out:
        c['score'], c['reasons'] = score(c, ref, bool(duration), artist, query, protect)
        c['length_ref'] = ref
    ranked = sorted((c for c, _ in out), key=lambda c: (bool(c['rejected']), not c['named'],
                                                        -c['score']))
    for i, c in enumerate(ranked, 1):
        c['rank'] = i
    return ranked


def pick(ranked: list[dict]) -> dict | None:
    """The best candidate that is not rejected, if any."""
    return next((c for c in ranked if not c['rejected']), None)


def art_track(desc: str | None) -> tuple[str | None, list[str]]:
    """Track and artists from YouTube's auto-generated description of a label upload:
    'Provided to YouTube by <label>\\n\\n<Track> · <Artist> · <Artist>\\n\\n<Album> ...'."""
    lines = [s.strip() for s in (desc or '').splitlines() if s.strip()]
    if len(lines) > 1 and lines[0].startswith('Provided to YouTube by') and ' · ' in lines[1]:
        track, *artists = lines[1].split(' · ')
        return track, artists
    return None, []


def slim(e: dict, **extra) -> dict:
    """The fields ranking and the report use, the watch URL, the description's start and its
    ℗ year; track and artists from an auto-generated description when the metadata lacks them."""
    c = {k: e[k] for k in FIELDS if e.get(k) is not None}
    c['url'] = f"https://www.youtube.com/watch?v={e['id']}"
    track, artists = art_track(e.get('description'))
    if track and not (c.get('track') or c.get('artists') or c.get('artist')):
        c['track'], c['artists'] = track, artists
    if e.get('description'):
        c['description'] = e['description'][:200]
        year = P_YEAR.search(e['description'])
        if year:
            c['p_year'] = int(year.group(1))
    return {**c, **extra}


def merge(entries: list[dict]) -> list[dict]:
    """One candidate per video id, in first-seen order; a field keeps the first value given
    (so put the resolved YouTube Music results first)."""
    out: dict[str, dict] = {}
    for e in entries:
        if not e.get('id'):
            continue
        cur = out.setdefault(e['id'], {})
        for k, v in e.items():
            if cur.get(k) in (None, '') and v not in (None, ''):
                cur[k] = v
    return list(out.values())


def infer_names(query: str, entries: list[dict]) -> tuple[str | None, str | None]:
    """(artist, title) from the first YouTube Music song whose track name (base_title()) plus
    the artists the query names spell exactly the query's words, in any order (credited artists
    the query leaves out, e.g. a producer, are left out); else (None, None)."""
    want = set(words(query)) - NOISE
    for c in sorted((c for c in entries if c.get('music_rank')), key=lambda c: c['music_rank']):
        track = base_title(c.get('track'))
        named = [a for a in meta_artists(c) if words(a) and set(words(a)) <= want]
        spelled = set(words(track)).union(*(words(a) for a in named))
        if track and named and set(words(track)) <= want and spelled == want:
            return ', '.join(named), track
    return None, None


def download_argv(python: str, script: str, query: str | None, cand: dict,
                  artist: str | None, title: str | None, out_dir: str,
                  duration: float | None = None) -> list[str]:
    """The command that downloads cand, as argv (names from the search, else file_names());
    each value joined to its option and the query after '--', so '-M-' stays a value."""
    meta_artist_, meta_title = file_names(cand, query)
    artist, title = artist or meta_artist_, title or meta_title
    argv = [python, script, f"--url={cand['url']}"]
    if artist and title:
        argv += [f'--artist={artist}', f'--title={title}']
    argv.append(f'--out-dir={out_dir}')
    if duration:
        argv.append(f'--duration={duration:g}')
    return argv + (['--', query] if query else [])


def report(ranked: list[dict], head: list[str], command: str | None) -> str:
    """The search result as text: named candidates, then the ones that miss a word of the
    song, then the rejected; two lines each; the top pick marked * and its command."""
    top = pick(ranked)
    lines = [*head, '', ' #   score  length  channel | title']
    groups = (('', lambda c: not c['rejected'] and c['named']),
              ('not named in full (another song or artist?):',
               lambda c: not c['rejected'] and not c['named']),
              ('rejected:', lambda c: bool(c['rejected'])))
    for heading, keep in groups:
        rows = [c for c in ranked if keep(c)]
        if rows and heading:
            lines.append(heading)
        for c in rows:
            sc = 'rej' if c['rejected'] else f"{c['score']:.1f}"
            lines += [f"{c['rank']:>2}{'*' if c is top else ' '} {sc:>6}  "
                      f"{mmss(c.get('duration')):>6}  {c.get('channel') or '?'} | "
                      f"{(c.get('title') or '?').strip()}",
                      f"{'':20}{c.get('url') or c.get('id')}  {'; '.join(c['reasons'])}"]
    if top:
        warn = '' if top['named'] else ' - it misses a word of the song: check it'
        album = f', {album_note(top)}' if album_note(top) else ''
        lines += ['', f"* top pick: #{top['rank']} {top.get('title')!r} ({top.get('channel')}, "
                      f"{mmss(top.get('duration'))}{album}){warn}. Confirm it with the user, then:",
                  f'  {command}', f'  ({RIGHTS})']
    return '\n'.join(lines)


# ------------------------------------------------------------------ tools and records

def search_dirs() -> list[str]:
    """Where to look for a JS runtime: this Python's bin (yt-dlp[default,deno] puts deno
    there), then PATH."""
    dirs = [sysconfig.get_path('scripts'), *os.environ.get('PATH', '').split(os.pathsep)]
    return list(dict.fromkeys(d for d in dirs if d))


def find_js_runtime(dirs: list[str]) -> tuple[dict | None, list[str]]:
    """The first usable runtime in yt-dlp's order (deno, node, quickjs), each looked for in
    every dir: ({'name', 'version', 'path'} or None, notes on the ones too old)."""
    notes = []
    for name, exe, flag, pattern, minimum in RUNTIMES:
        for d in dirs:
            path = os.path.join(d, exe)
            if not (os.path.isfile(path) and os.access(path, os.X_OK)):
                continue
            try:
                r = subprocess.run([path, flag], capture_output=True, text=True, timeout=15,
                                   stdin=subprocess.DEVNULL)
            except (OSError, subprocess.SubprocessError):
                continue
            m = re.search(pattern, r.stdout + r.stderr, re.M)
            if not m:
                notes.append(f'{path}: no version in its {flag} output')
                continue
            version = m.group(m.lastindex)
            vt = tuple(int(x) for x in re.findall(r'\d+', version)[:3])
            if vt >= minimum or (name == 'quickjs' and m.group(1)):     # any quickjs-ng
                return dict(name=name, version=version, path=path), notes
            notes.append(f"{name} {version} at {path} is too old (needs "
                         f"{'.'.join(map(str, minimum))} or newer)")
    return None, notes


def js_option(js: dict | None) -> dict:
    """yt-dlp's js_runtimes option: the runtime found, else yt-dlp's default (deno)."""
    return {js['name']: {'path': js['path']}} if js else {'deno': {}}


def runtime_warning(notes: list[str]) -> str:
    return ('fetch_audio: warning: no usable JavaScript runtime, so YouTube may withhold formats. '
            'Install deno >= 2.3 (recommended; uv pip install --python .venv-ytdlp/bin/python '
            '"yt-dlp[default,deno]" puts it in the venv) or node >= 22.'
            + ''.join(f'\n  {n}' for n in notes))


def source_record(info: dict, *, query: str | None, file: str, artist: str | None,
                  song: str | None, js_runtime: str | None, ytdlp_version: str, fetched_at: str,
                  wav: dict | None = None) -> dict:
    """What source.json holds: the names the WAV got, the upload (whether it is the label's,
    YouTube's credits and release), the audio format taken, the tools, the rights."""
    return dict(
        file=file, query=query, artist=artist, song=song,
        url=info.get('webpage_url') or f"https://www.youtube.com/watch?v={info.get('id')}",
        id=info.get('id'), title=info.get('title'), channel=info.get('channel'),
        channel_is_verified=info.get('channel_is_verified'), label_upload=label_kind(info),
        credits=meta_artists(info), track=info.get('track'), album=info.get('album'),
        release_date=info.get('release_date'), release_year=info.get('release_year'),
        duration=info.get('duration'), upload_date=info.get('upload_date'),
        license=info.get('license'), view_count=info.get('view_count'),
        format=dict(format_id=info.get('format_id'), acodec=info.get('acodec'),
                    abr=info.get('abr') or info.get('tbr'), asr=info.get('asr'),
                    ext=info.get('ext')),
        yt_dlp=ytdlp_version, js_runtime=js_runtime, fetched_at=fetched_at, wav=wav,
        rights=RIGHTS)


def wav_facts(path: str | Path) -> dict:
    with wave.open(str(path), 'rb') as w:
        rate, n = w.getframerate(), w.getnframes()
        return dict(sample_rate=rate, channels=w.getnchannels(), bits=8 * w.getsampwidth(),
                    duration_s=round(n / rate, 3))


def decode(ffmpeg: str, src: Path, dst: Path) -> None:
    """Any audio (or video) file -> 16-bit PCM WAV at its own sample rate and channel count."""
    r = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-y', '-i', str(src), '-vn',
                        '-c:a', 'pcm_s16le', str(dst)], capture_output=True, text=True)
    if r.returncode or not dst.exists():
        raise RuntimeError(f'ffmpeg could not decode {src.name}: {r.stderr.strip()[-400:]}')


class Log:
    """yt-dlp logger: its warnings to stderr once each; errors come back as exceptions."""
    seen: set = set()

    def debug(self, msg: str) -> None:
        pass

    info = debug
    error = debug

    def warning(self, msg: str) -> None:
        if msg not in self.seen:
            self.seen.add(msg)
            print(f'yt-dlp warning: {msg}', file=sys.stderr)


def ydl_opts(js: dict | None) -> dict:
    """Quiet, one video per URL, the JS runtime found. No cookies or logins, ever."""
    return dict(quiet=True, noprogress=True, noplaylist=True, logger=Log(),
                js_runtimes=js_option(js))


# ------------------------------------------------------------------ network

def search(yt_dlp, query: str, js: dict | None) -> tuple[list[dict], dict, list[str]]:
    """YouTube Music's top song results resolved to full metadata, then a plain YouTube
    search (flat entries), merged by video id; with how many results each search gave (None:
    it failed) and the errors, which also go to stderr."""
    base, found, errors = ydl_opts(js), [], []
    searched: dict[str, int | None] = dict(youtube_music=None, youtube=None)
    try:
        with yt_dlp.YoutubeDL(dict(base, extract_flat='in_playlist', playlistend=N_MUSIC)) as ydl:
            music = ydl.extract_info(MUSIC_SEARCH.format(urllib.parse.quote_plus(query)),
                                     download=False)
        n = 0
        with yt_dlp.YoutubeDL(base) as ydl:
            for n, e in enumerate((music or {}).get('entries') or [], 1):
                try:
                    e = ydl.extract_info(e['url'], download=False, process=False)
                except yt_dlp.utils.YoutubeDLError as err:
                    errors.append(f'YouTube Music #{n} not resolved: {err}')
                found.append(slim(e, music_rank=n))
        searched['youtube_music'] = n
    except yt_dlp.utils.YoutubeDLError as err:
        errors.append(f'YouTube Music search failed: {err}')
    try:
        with yt_dlp.YoutubeDL(dict(base, extract_flat='in_playlist')) as ydl:
            videos = ydl.extract_info(f'ytsearch{N_VIDEO}:{query}', download=False)
        hits = [slim(e) for e in (videos or {}).get('entries') or [] if e and e.get('id')]
        found += hits
        searched['youtube'] = len(hits)
    except yt_dlp.utils.YoutubeDLError as err:
        errors.append(f'YouTube search failed: {err}')
    for msg in errors:
        print(f'fetch_audio: {msg}', file=sys.stderr)
    return merge(found), searched, errors


def js_label(js: dict | None) -> str | None:
    return f"{js['name']} {js['version']}" if js else None


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def find(yt_dlp, a: argparse.Namespace, query: str, js: dict | None) -> int:
    """Search mode: rank, print (text or JSON), download nothing."""
    cands, searched, errors = search(yt_dlp, query, js)
    artist, title, inferred = a.artist, a.title, False
    if not (artist or title):
        artist, title = infer_names(query, cands)
        inferred = bool(artist)
    ranked = rank(cands, artist, title, a.duration, query)
    top = pick(ranked)
    argv = top and download_argv(sys.executable, os.path.abspath(__file__), query, top, artist,
                                 title, a.out_dir, a.duration)
    cmd = argv and shlex.join(argv)
    ref = ranked[0]['length_ref'] if ranked else None
    if a.json:
        print(json.dumps(dict(query=query, artist=artist, title=title,
                              names_from='YouTube Music' if inferred else None,
                              duration=a.duration, length_ref=ref, js_runtime=js_label(js),
                              searched=searched, errors=errors, pick=top and top['rank'],
                              command=cmd, command_argv=argv, rights=RIGHTS,
                              candidates=ranked), indent=1, ensure_ascii=False))
    else:
        if artist and title:
            names = (f'  |  artist {artist!r}, title {title!r}'
                     + (' (from YouTube Music; --artist/--title to override)' if inferred else ''))
        else:
            one = f' and {artist or title!r}' if artist or title else ''
            names = f'  |  every word of the query{one} must show (any spelling or script)'
        length = (f'target {mmss(a.duration, 1)} (--duration)' if a.duration else
                  f'no --duration: compared with the median of the named candidates, {mmss(ref)}')
        ran = '; '.join(f'{label}: ' + (f'{n} {unit}' if n is not None else 'FAILED (see stderr)')
                        for label, n, unit in (('YouTube Music', searched['youtube_music'],
                                                'songs resolved'),
                                               ('YouTube', searched['youtube'], 'results')))
        print(report(ranked, [f'search {query!r}{names}', f'length: {length}',
                              f'{len(ranked)} candidates ({ran}); JS runtime: '
                              f'{js_label(js) or "none"}'], cmd))
    if not ranked:
        failed = ' (a search failed, see above: re-run the yt-dlp install line to update it)'
        print('fetch_audio: nothing found' + (failed if errors else '') + ' - check the spelling, '
              'pass --artist and --title, or give a --url', file=sys.stderr)
        return 1
    if not top:
        print('fetch_audio: every candidate was rejected - pass --artist/--title (words of the '
              "song's own name are never grounds to reject), or give a --url", file=sys.stderr)
        return 1
    return 0


def fetch(yt_dlp, a: argparse.Namespace, js: dict | None, ffmpeg: str | None) -> int:
    """Download mode: resolve --url, refuse a playlist or a live stream, name the WAV, refuse to
    replace it or another WAV's source.json, download the best audio into a temp folder, decode
    it to WAV, write source.json."""
    opts = dict(ydl_opts(js), format='bestaudio/best', fixup='never')
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(a.url, download=False)
    except yt_dlp.utils.YoutubeDLError as e:
        print(f'fetch_audio: {e}', file=sys.stderr)
        return 1
    if info.get('_type') in ('playlist', 'multi_video') or not info.get('id'):
        print('fetch_audio: --url must be a single video, not a playlist', file=sys.stderr)
        return 1
    status = 'is_live' if info.get('is_live') else info.get('live_status')
    if status in NOT_READY:
        print(f'fetch_audio: {a.url} is {NOT_READY[status]}, not a recording to download',
              file=sys.stderr)
        return 1
    out_dir = Path(a.out_dir)
    meta_artist_, meta_title = file_names(info, a.query)
    artist, song = a.artist or meta_artist_, a.title or meta_title
    name = wav_name(artist, song, info.get('title'))
    wav, src_json = out_dir / name, out_dir / 'source.json'
    if wav.exists() and not a.force:
        print(f'fetch_audio: {wav} exists - pass --force to replace it', file=sys.stderr)
        return 1
    if src_json.exists() and not a.force:
        try:
            about = json.loads(src_json.read_text(encoding='utf-8')).get('file')
        except (OSError, ValueError, AttributeError):
            about = None
        if about != name:
            print(f"fetch_audio: {src_json} describes {repr(about) if about else 'another file'} "
                  '- pass --force to replace it, or use another --out-dir', file=sys.stderr)
            return 1
    meta = dict(query=a.query, file=name, artist=artist, song=song, js_runtime=js_label(js),
                ytdlp_version=yt_dlp.version.__version__)
    if a.dry_run:
        print(f'would write {wav}\nand {src_json}:\n' + json.dumps(
            source_record(info, **meta, fetched_at=utc_now()), indent=1, ensure_ascii=False))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    dl = Path(tempfile.mkdtemp(prefix='fetch_audio-'))      # system temp: yt-dlp's outtmpl
    part = Path(tempfile.mkdtemp(prefix='.fetch_audio-', dir=out_dir))    # expands % and $
    try:
        print(f"downloading {info.get('title')!r} (format {info.get('format_id')}, "
              f"{info.get('acodec')}, {info.get('asr')} Hz) ...", file=sys.stderr)
        tmpl = os.path.join(str(dl).replace('%', '%%'), 'download.%(ext)s')
        with yt_dlp.YoutubeDL(dict(opts, outtmpl={'default': tmpl})) as ydl:
            done = ydl.process_ie_result(info, download=True)
        src = next((Path(d['filepath']) for d in done.get('requested_downloads') or []
                    if d.get('filepath')), None)
        if src is None or not src.exists():
            raise RuntimeError('yt-dlp reported no downloaded file')
        decode(ffmpeg, src, part / 'audio.wav')
        os.replace(part / 'audio.wav', wav)
    except (yt_dlp.utils.YoutubeDLError, RuntimeError, OSError) as e:
        print(f'fetch_audio: download failed: {e}', file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(dl, ignore_errors=True)
        shutil.rmtree(part, ignore_errors=True)
    facts = wav_facts(wav)
    record = source_record(done, **meta, fetched_at=utc_now(), wav=facts)
    src_json.write_text(json.dumps(record, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    fmt = record['format']
    print(f"wrote {wav}: {facts['sample_rate']} Hz, {facts['channels']} ch, {facts['bits']}-bit, "
          f"{mmss(facts['duration_s'], 1)} (YouTube: {mmss(record['duration'])}) from format "
          f"{fmt['format_id']} ({fmt['acodec']}, {fmt['abr'] and round(fmt['abr'])} kbps)")
    print(f"wrote {src_json}" + (f" (license: {record['license']})" if record['license'] else ''))
    off = record['duration'] and facts['duration_s'] - record['duration']
    if off and abs(off) > 2:
        print(f'warning: the WAV is {off:+.1f} s against YouTube\'s length - incomplete download?',
              file=sys.stderr)
    if a.duration and abs(facts['duration_s'] - a.duration) > 2:
        print(f"note: the WAV is {facts['duration_s'] - a.duration:+.1f} s against --duration - "
              'another cut of the song?', file=sys.stderr)
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('query', nargs='?',
                    help='"Artist Title" as typed into YouTube (recorded in source.json)')
    ap.add_argument('--artist', help='the artist as credited: stricter matching, the WAV name')
    ap.add_argument('--title', help='the song title: stricter matching, the WAV name')
    ap.add_argument('--duration', type=seconds,
                    help="length of the user's own copy (s or m:ss): the closest upload wins")
    ap.add_argument('--json', action='store_true', help='search mode: print JSON')
    ap.add_argument('--url', help='download mode: the video the user confirmed')
    ap.add_argument('--out-dir', default='.',
                    help='song folder for the WAV and source.json (default: here, made absolute)')
    ap.add_argument('--dry-run', action='store_true', help='with --url: resolve and print only')
    ap.add_argument('--force', action='store_true',
                    help='with --url: replace an existing WAV, or a source.json about another')
    return ap


def main(argv: list[str] | None = None) -> None:
    ap = parser()
    a = ap.parse_args(argv)
    if (a.dry_run or a.force) and not a.url:
        ap.error('--dry-run and --force go with --url')
    query = a.query or (f'{a.artist} {a.title}' if a.artist and a.title else None)
    if not (a.url or query):
        ap.error('give "Artist Title" (or --artist and --title) to search, or --url to download')
    a.out_dir = os.path.abspath(os.path.expanduser(a.out_dir))
    try:
        import yt_dlp
    except ImportError:
        print(f'fetch_audio: yt-dlp is not installed for {sys.executable}. Install it in its own '
              f'venv and run this script with that python:\n  {INSTALL}', file=sys.stderr)
        sys.exit(2)
    ffmpeg = shutil.which('ffmpeg')
    if a.url and not a.dry_run and not ffmpeg:
        print('fetch_audio: ffmpeg not found on PATH - it decodes the download to WAV '
              '(macOS: brew install ffmpeg)', file=sys.stderr)
        sys.exit(2)
    js, notes = find_js_runtime(search_dirs())
    if not js:
        print(runtime_warning(notes), file=sys.stderr)
    sys.exit(fetch(yt_dlp, a, js, ffmpeg) if a.url else find(yt_dlp, a, query, js))


if __name__ == '__main__':
    main()
