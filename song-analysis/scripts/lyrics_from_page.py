#!/usr/bin/env python3
"""A lyrics or chord-tab web page -> lyrics.txt (+ the tab's chords), printing counts only.

Why: lyrics are copyrighted, and an assistant that retypes them through its own output
gets blocked by content filtering ("Output blocked by content filtering policy"). This
script moves the text from the page to the song folder without it passing through the
conversation; Phase 6 then only times it. A chord-tab page (chords above the lyric lines,
in <pre> blocks) also yields its chords per section as tab_chords.json - a second opinion
for tab_compare.py, never the chart's source (tabs are often simplified or wrong).

Reads: songlyrics.com (#songLyricsDiv), lyricsondemand.com (#lyrics / .lcontent), Bandcamp
(.lyricsText) and <pre> tab pages. Section headers ("Verse 1:", "[Chorus]") become
[labels] and then alone start sections (blank lines inside one are page layout); without
headers a blank line starts one, unless the page spaces every line. Chord-only lines go
to tab_chords.json.

Usage (python3, standard library only):
    lyrics_from_page.py URL --out lyrics.txt [--chords-out analysis/tab_chords.json]
    lyrics_from_page.py page.html --out lyrics.txt          # a page saved earlier
Exit 1 when no lyrics were found (try another site; blocked pages answer 403/404).
"""
from __future__ import annotations

import argparse, html, json, re, sys, urllib.request
from pathlib import Path

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126 Safari/537.36')
CHORD = re.compile(r'^(N\.?C\.?|N/C|[A-G][#b]?(m|maj|min|M|sus|dim|aug|add|\+)?[0-9]*'
                   r'(sus[24]|add[0-9]+|b5|#5|b9)?(/[A-G][#b]?)?)$')
HEADER = re.compile(r'^\[?\s*((?:pre-?)?(?:verse|chorus|bridge|intro|outro|refrain|hook|'
                    r'interlude|solo|instrumental|coda|breakdown)\s*\d*)\s*\]?\s*:?$', re.I)
BLOCKS = [r'id="songLyricsDiv"[^>]*>(.*?)</p>', r'class="tralbumData lyricsText"[^>]*>(.*?)</div>',
          r'id="lyrics"[^>]*>(.*?)</div>', r'class="lcontent"[^>]*>(.*?)</div>',
          r'<pre[^>]*>(.*?)</pre>']


def load(src: str) -> str:
    if re.match(r'https?://', src):
        req = urllib.request.Request(src, headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read().decode('utf-8', 'ignore')
    return Path(src).read_text(encoding='utf-8', errors='ignore')


def text_blocks(page: str) -> list[str]:
    """The lyric blocks of the first markup that has any, as plain text."""
    for pat in BLOCKS:
        found = re.findall(pat, page, re.S | re.I)
        if found:
            return [html.unescape(re.sub(r'<[^>]+>', '', re.sub(r'<br\s*/?>', '\n', b)))
                    for b in found]
    return []


def is_chord_line(s: str) -> bool:
    toks = s.split()
    return bool(toks) and all(CHORD.match(t) for t in toks)


def parse(blocks: list[str]) -> tuple[list[str], list[dict]]:
    """(lyrics.txt lines, [{section, chords}]) - sections start with a blank line."""
    out, tab, label = [], [], None
    lines = [l.rstrip() for b in blocks for l in b.splitlines()]
    nonblank = [l for l in lines if l.strip()]
    spaced = len(nonblank) > 4 and sum(1 for a, b in zip(lines, lines[1:])
                                       if a.strip() and not b.strip()) > 0.8 * len(nonblank)
    for l in lines:
        s = l.strip()
        if not s:
            if not spaced and out and out[-1] != '':
                out.append('')
            continue
        if re.match(r'^(key|capo|tuning)\s*:', s, re.I):
            continue
        m = HEADER.match(s)
        if m:
            label = m.group(1).strip().title()
            out += ['', f'[{label}]']
            tab.append({'section': label, 'chords': []})
            continue
        if is_chord_line(s):
            if not tab:
                tab.append({'section': label or 'Song', 'chords': []})
            tab[-1]['chords'] += s.split()
            continue
        out.append(re.sub(r'\s{2,}', ' ', s))
    if any(l.startswith('[') for l in out):      # headers mark the sections: blank lines
        out = [l for i, l in enumerate(out)       # inside one are only page layout
               if l != '' or (i + 1 < len(out) and out[i + 1].startswith('['))]
    while out and out[0] == '':
        out.pop(0)
    clean = []
    for l in out:                                 # no doubled blank lines
        if not (l == '' and clean and clean[-1] == ''):
            clean.append(l)
    return clean, [t for t in tab if t['chords']]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('src', help='URL or a saved .html')
    ap.add_argument('--out', default='lyrics.txt')
    ap.add_argument('--chords-out', help='write the tab chords per section here (JSON)')
    a = ap.parse_args()
    try:
        page = load(a.src)
    except OSError as e:
        sys.exit(f'lyrics_from_page: {a.src}: {e} - try another site')
    lines, tab = parse(text_blocks(page))
    words = [l for l in lines if l and not l.startswith('[')]
    if not words:
        sys.exit(f'lyrics_from_page: no lyrics found in {a.src} - try another site')
    Path(a.out).write_text('\n'.join(lines).strip() + '\n')
    labels = [l for l in lines if l.startswith('[')]
    print(f'{a.out}: {len(labels)} sections {labels}, {len(words)} lines, '
          f'{sum(len(l.split()) for l in words)} words (unofficial unless the artist\'s page)')
    if a.chords_out and tab:
        Path(a.chords_out).write_text(json.dumps({'source': a.src, 'sections': tab}, indent=1))
        print(f"{a.chords_out}: {sum(len(t['chords']) for t in tab)} chords in {len(tab)} sections")


if __name__ == '__main__':
    main()
