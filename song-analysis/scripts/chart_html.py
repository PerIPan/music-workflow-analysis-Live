#!/usr/bin/env python3
"""Phase 8: a per-song chart data file -> one self-contained chord+lyric HTML chart.

The data file holds what a person decides - chords per cell, sections, lyric anchors,
commentary. Everything measured is read from the song's analysis/ folder, so an upstream
re-run that keeps the bar grid re-renders without editing (a moved beat 1 shifts every
(bar, cell) key). Lyric lines anchor at the cell of the chord they resolve into (Rule 1,
references/chart-and-lyrics.md) and are split over the cells where Whisper heard their
words: pickup words sung before the anchor are pulled into it, nothing spills past the
next line's anchor or out of the line's section (a pickup or ad-lib shares its cell), and
words Whisper missed are interpolated between heard ones, a beat apart after the last (a
beat = the bar / the grouping's pulse count, so an eighth in 11/8). A cell gets a "?" when
lv-chordia names another root than the chart, or when the triad reader does and the bass
contradicts the chart too (the pitch class it sounds longest in the cell, 0.15 s or more,
is neither the root nor the slash bass). Near-ties and triad-only objections are not
marked: on real songs they flagged 20-50% of cells, mostly sus/add9 voicings. A cell whose
lv-chordia chord covers under half of it (a change inside) gets a dashed underline.
Evidence made on another grid, or with another grouping, is warned about.

Usage (python3, standard library only):
    chart_html.py <song>/gen_v1.py [--out PATH]     # default <folder>/<out>
    from chart_html import render; render(SONG)     # returns the path written

Reads <folder>/analysis/: foundation.json (downbeat_times, grouping, pulse_unit),
chords_lv.json, chord_proposal.json, bass_per_cell.json; if present stem_activity.json
(stem_activity.py; the song map's stem meters) and the Whisper words file named by 'words'.

SONG, the dict the data file defines. Cells are keyed (bar, cell): bars count from 1 on the
audio's bar grid, cells from 1, one per group of the grouping (4/4 as [2, 2]: beats 1-2 and
3-4; 11/8 as [6, 5]: two unequal cells; 3/4: one). Values marked html go in as-is (write
&amp; for &); all other text is escaped. An unknown key, a wrong shape or a Harte chord
label is refused with the reason.
  Required
    title, artist   str
    sections        [(name, first_bar, last_bar, kind, note_html[, harmony_html])] covering
                    every bar from 1 in order, no gap or overlap; one row block each, split
                    into rows of bars_per_row. kind colours the name: intro, verse, post
                    (post-chorus; a pre-chorus too), chorus, bridge, inst, outro. note_html
                    is the grey note beside the name; harmony_html fills the song map's
                    Harmony column (dropped when no section has one). The last section may
                    run one bar past the last downbeat (a chord ringing out).
    chords          {(bar, cell): label}, lead-sheet symbols: 'Cmaj7', 'F#m7', 'Em/D' (slash
                    + note name = bass note; 'C6/9' is one chord), 'N.C.'; # and b print as
                    sharp and flat signs. Not chords_lv.json's Harte labels ('A:min7').
                    No entry = empty (hold).
  Optional
    folder          song folder holding analysis/. Default, and base of a relative path:
                    the data file's folder (render() called directly: the working dir)
    out             file name in folder; default '<artist> - <title> - Chords.html' (with
                    / \\ : as -)
    key_short       key for the title line, e.g. 'E minor'
    lyrics          {(bar, cell): (text, kind)}, one line per anchor cell (the chord the
                    line resolves into). kind:
                      ''                      sung line, split over the cells where sung
                      'adlib'                 kept whole in its cell, greyed (beside the
                                              words of a line sung there)
                      'pk pk-<section kind>'  the next section's pickup, overlaid in this
                                              cell (beside the line's closing words) in
                                              that section's colour
    words           Whisper words file in analysis/, e.g. 'lyrics_mix.json' ({"words":
                    [{"word", "start"}, ...]}); without it, or with no words in it, every
                    line stays whole at its anchor
    bass_notes      {(bar, cell): 'A'}: bass note printed as (A) on a label with no slash
    verified        {(bar, cell), ...} a player confirmed: no "?" or split mark there
                    (say who checked in provenance)
    grouping        overrides foundation.json's; must match the grid the analysis used
    bars_per_row    default max(1, 8 // cells per bar): 4 bars of 4/4, 8 of 3/4
    duration_s      end of the audio, where a bar past the last downbeat ends; default
                    the last downbeat + one bar
    subline         html line under the title
    facts           [(label, value_html)]: header boxes (key, mode, tempo, meter, length)
    provenance      html: where meter, beat 1, tempo, key, chords and lyrics came from
    map_note        html paragraph under the song map
    notes           [(title_html, body_html[, cls])] commentary blocks. cls: '' plain,
                    'open' (open questions for a player), 'reading' (tinted like the legend)
    method          html of the "Method & confidence" block, run through str.format:
                    {cells} chord cells, {lv_pct} / {tri_pct} % of the cells lv-chordia /
                    the triad reader read whose root it agrees with, {n_q} cells marked "?"
                    (literal braces as {{ }}). Default: one sentence with those numbers.
"""
from __future__ import annotations

import argparse, difflib, html, importlib.util, json, re, sys, unicodedata
from pathlib import Path

PC = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6,
      'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11,
      'Cb': 11, 'Fb': 4, 'E#': 5, 'B#': 0}
STEMS = (('vocals', 'Vocal', 'v'), ('bass', 'Bass', 'b'), ('drums', 'Drums', 'd'),
         ('other', 'Keys/gtr', 'k'))
PICKUP_COLOURS = {'pk-bridge': '#5b9a52', 'pk-intro': '#888', 'pk-inst': '#888'}  # rest in CSS
UNITS = {8: 'eighth', 16: 'sixteenth'}                                       # else 'beat'
METHOD = ("<p>Of {cells} chord cells, lv-chordia names the chart's root in {lv_pct}% and "
          "the triad reader in {tri_pct}% (of the cells each read); cells marked <b>?</b>: "
          "{n_q}.</p>")


def root_pc(label: str | None) -> int | None:
    """Pitch class of a chord label's root ('Cmaj7', 'A:min7', 'F#m', 'Em/D'); None for N/N.C."""
    if not label or label.startswith('N'):
        return None
    m = re.match(r'([A-G])([#b]?)', label)
    return PC[m.group(1) + m.group(2)] if m else None


def split_slash(label: str) -> tuple[str, str | None]:
    """'Em/D' -> ('Em', 'D'); a slash not followed by a note name is part of the chord
    ('C6/9' -> ('C6/9', None))."""
    m = re.fullmatch(r'(.+)/([A-G][#b]?)', label)
    return (m.group(1), m.group(2)) if m else (label, None)


def pretty(s: str) -> str:
    """Typographic accidentals: F# -> F♯, Bb -> B♭, m7b5 -> m7♭5 (a b after a note letter
    or before a digit)."""
    return re.sub(r'b(?=\d)', '♭', re.sub(r'([A-G])b', r'\1♭', s.replace('#', '♯')))


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def norm(w: str) -> str:
    """As align_lyrics.py: lowercase, no accents or punctuation, final sigma as sigma; ’ as '.
    '' for a token with no letters ('—', '♪')."""
    t = unicodedata.normalize('NFD', w.lower().replace('’', "'"))
    t = ''.join(ch for ch in t if not unicodedata.combining(ch)).replace('ς', 'σ')
    return re.sub(r"[^\w']", '', t)


def mmss(t: float) -> str:
    return f'{int(t // 60)}:{int(t % 60):02d}'


class Grid:
    """Bar and cell times: cells cut at cumulative group fractions of each bar, the same
    cells as bass_notes.py, lv_chords.py and chord_proposal.py."""

    def __init__(self, downbeats: list[float], grouping: list[int]):
        self.db, self.n, self.bpb = list(downbeats), len(grouping), sum(grouping)
        acc, self.edges = 0, [0.0]
        for g in grouping:
            acc += g
            self.edges.append(acc / self.bpb)

    def start(self, key: tuple[int, int]) -> float:
        b0, b1 = self.db[key[0] - 1], self.db[key[0]]
        return b0 + (b1 - b0) * self.edges[key[1] - 1]

    def at(self, t: float) -> tuple[int, int]:
        """(bar, cell) holding time t, clamped to the first and the last cell."""
        db = self.db
        for i in range(len(db) - 1):
            if t < db[i + 1]:
                k = 1
                while k < self.n and t >= db[i] + (db[i + 1] - db[i]) * self.edges[k]:
                    k += 1
                return i + 1, k
        return len(db) - 1, self.n

    def prev(self, c: tuple[int, int]) -> tuple[int, int]:
        return (c[0], c[1] - 1) if c[1] > 1 else (c[0] - 1, self.n)

    def beat(self, bar: int) -> float:
        return (self.db[bar] - self.db[bar - 1]) / self.bpb


def flags(S: dict, lv: dict, tri: dict, bass: dict) -> set:
    """'?' when a cell's own evidence disagrees with the chart: lv-chordia (the primary reader)
    names another root, or the triad reader does and the bass plays a note that is neither the
    chart's root nor its slash bass. A triad objection alone is often a sus/add9 voicing."""
    out = set()
    for key, ch in S['chords'].items():
        r = root_pc(ch)
        if r is None:
            continue
        lr, tr = root_pc(lv.get(key, {}).get('chord')), root_pc(tri.get(key, {}).get('chord'))
        pcs = bass.get(key) or {}
        top = max(pcs, key=pcs.get) if pcs else None
        sb = split_slash(ch)[1]
        slash = root_pc(sb) if sb else r
        against = top is not None and pcs[top] >= 0.15 and PC[top] not in (r, slash)
        if (lr is not None and lr != r) or (tr is not None and tr != r and against):
            out.add(key)
    return out


def splits(S: dict, lv: dict) -> set:
    """Chord cells lv-chordia's chord covers under half of (a change falls inside the cell):
    lv_chords.py's change-inside, whose status a root disagreement may since have replaced."""
    return {k for k, ch in S['chords'].items()
            if root_pc(ch) is not None and lv.get(k, {}).get('coverage', 1) < 0.5}


def distribute(S: dict, grid: Grid, words: list | None) -> tuple[dict, dict]:
    """Split each sung line over the cells where its words are sung -> ({cell: text},
    {cell: (text, kind)} of the pickups and ad-libs, which stay whole in their cell beside
    any line words there). Word times come from a local alignment against Whisper's words
    (loose: first four letters, so talk ~ talking; tokens without letters, like '—' or '♪',
    are left out); unmatched words are interpolated between matched ones, from the anchor
    for a line's opening words, and a beat apart past the last match. Words sung before the
    line's anchor cell are pulled into it (the chord the phrase resolves into), and nothing
    spills past the next line's anchor or out of the line's section. With no words, every
    line stays whole."""
    entries = sorted(S.get('lyrics', {}).items())
    out, over = {}, {}
    stem = lambda w: norm(w)[:4]
    wt = [(s, w['start']) for w in words or () for s in [stem(w['word'])] if s]
    end = {b: b1 for _, b0, b1, *_ in S['sections'] for b in range(b0, b1 + 1)}
    sung = [k for k, (_, kind) in entries if kind != 'adlib' and 'pk' not in kind]
    for key, (text, kind) in entries:
        if kind == 'adlib' or 'pk' in kind:
            over[key] = (text, kind)
            continue
        if not words:
            out[key] = [text]
            continue
        bound = (end[key[0]] + 1, 1)
        nxt = min(next((k for k in sung if k > key), bound), bound)
        t_a = grid.start(key)
        t_n = grid.start(nxt) if nxt[0] < len(grid.db) else grid.db[-1]
        toks = text.split()
        stems = [stem(t) for t in toks]
        keep = [i for i, s in enumerate(stems) if s]
        win = [(w, t) for w, t in wt if t_a - 2.5 <= t < t_n + 0.3]
        sm = difflib.SequenceMatcher(a=[stems[i] for i in keep], b=[w for w, _ in win],
                                     autojunk=False)
        times = [None] * len(toks)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                times[keep[blk.a + k]] = win[blk.b + k][1]
        beat = grid.beat(key[0])
        known = [i for i, t in enumerate(times) if t is not None]
        for i in range(len(toks)):
            if times[i] is not None:
                continue
            lo = max((k for k in known if k < i), default=None)
            hi = min((k for k in known if k > i), default=None)
            if lo is not None and hi is not None:
                times[i] = times[lo] + (times[hi] - times[lo]) * (i - lo) / (hi - lo)
            elif hi is not None:                 # opening words: from the anchor onwards
                times[i] = t_a + (max(times[hi], t_a) - t_a) * i / hi
            elif lo is not None:                 # past the last match: a beat per word
                times[i] = times[lo] + beat * (i - lo)
            else:                                # nothing heard: a beat per word
                times[i] = t_a + beat * i
        last = key
        for tok, t in zip(toks, times):
            c = max(grid.at(t), key)
            while c >= nxt:                              # never spill into the next line
                c = grid.prev(c)
            c = max(c, last)                             # words stay in sung order
            out.setdefault(c, []).append(tok)
            last = c
    return {c: ' '.join(toks) for c, toks in out.items()}, over


# ------------------------------------------------------------------ html

def cell_html(S: dict, key: tuple, bar_end: bool, flagged: set, split: set, lyr: dict,
              over: dict) -> str:
    ch = S['chords'].get(key, '')
    if ch == 'N.C.':
        chord = '<div class="chord rest">N.C.</div>'
    else:
        name, slash = split_slash(ch)
        bass = slash or S.get('bass_notes', {}).get(key)
        b = f'<span class="bass">({esc(pretty(bass))})</span>' if bass else ''
        chord = f'<div class="chord">{esc(pretty(name))}{b}</div>'
    text, (otext, okind) = lyr.get(key, ''), over.get(key, ('', ''))
    ly, lcls = esc(text), 'lyric'
    if okind == 'adlib' and not text:                   # an ad-lib on its own: all greyed
        ly, lcls = esc(otext), 'lyric adlib'
    elif okind == 'adlib':                              # beside a sung line's words
        ly += f'<span class="adlib">{esc(otext)}</span>'
    elif okind:                                         # the next section's pickup
        ly += f'<span class="pickup {esc(okind.split()[-1])}">{esc(otext)}</span>'
    cls = ['half', 'bar-end' if bar_end else '', 'q' if key in flagged else '',
           'split' if key in split else '']
    return (f'<div class="{" ".join(c for c in cls if c)}">{chord}'
            f'<div class="{lcls}">{ly}</div></div>')


def rows_html(S: dict, n: int, per_row: int, flagged: set, split: set, lyr: dict,
              over: dict) -> str:
    out = []
    for name, b0, b1, kind, note, *_ in S['sections']:
        bars = list(range(b0, b1 + 1))
        for r, chunk in enumerate(bars[i:i + per_row] for i in range(0, len(bars), per_row)):
            start = r == 0
            cols = f'cols-{n * len(chunk)}' if len(chunk) < per_row else ''
            cells = ''.join(cell_html(S, (b, c), c == n, flagged, split, lyr, over)
                            for b in chunk for c in range(1, n + 1))
            rng = f'bar {chunk[0]}' if len(chunk) == 1 else f'bars {chunk[0]}–{chunk[-1]}'
            head = (f'<span class="row-name">{esc(name)}</span><span class="row-meta">{rng}</span>'
                    f'<span class="row-note">{note}</span>' if start else
                    f'<span class="row-meta">{rng}</span>')
            out.append(f'<div class="row {kind} {"section-start" if start else "section-cont"}">'
                       f'<div class="row-head">{head}</div>'
                       f'<div class="bars {cols}">{cells}</div></div>')
    return '\n'.join(out)


def meter(v: float, cls: str = '') -> str:
    return (f'<span class="track"><span class="meter {cls}" '
            f'style="width:{max(3, min(100, round(v * 100)))}%"></span></span>')


def map_html(S: dict, db: list, act: dict) -> str:
    """Song map: section, bars, start time, harmony, average stem level per section."""
    stems = [s for s in STEMS if s[0] in act]
    with_harmony = any(len(sec) > 5 for sec in S['sections'])
    rows = []
    for sec in S['sections']:
        name, b0, b1, kind = sec[:4]
        cells = f'<td>{sec[5] if len(sec) > 5 else ""}</td>' if with_harmony else ''
        for stem, _, cls in stems:
            vals = act[stem][b0 - 1:b1]
            cells += f'<td>{meter(sum(vals) / len(vals) if vals else 0, cls)}</td>'
        bars = f'{b0}–{b1}' if b1 > b0 else f'{b0}'
        rows.append(f'<tr><td class="sn {kind}">{esc(name)}</td><td class="mono">{bars}</td>'
                    f'<td class="mono">{mmss(db[b0 - 1])}</td>{cells}</tr>')
    head = ('<th>Harmony</th>' if with_harmony else '') + ''.join(
        f'<th>{label}</th>' for _, label, _ in stems)
    return ('<table class="map"><thead><tr><th>Section</th><th>Bars</th><th>Start</th>'
            f'{head}</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def stats(S: dict, lv: dict, tri: dict) -> dict:
    """Chord cells, and per reader the cells it read and those whose root it agrees with (a
    bar past the last downbeat has no reading)."""
    keys = [k for k, ch in S['chords'].items() if root_pc(ch) is not None]
    agree = lambda src: sum(root_pc(src[k].get('chord')) == root_pc(S['chords'][k])
                            for k in keys if k in src)
    return dict(cells=len(keys), lv=agree(lv), tri=agree(tri),
                lv_n=sum(k in lv for k in keys), tri_n=sum(k in tri for k in keys))


def grid_css(grouping: list[int], per_row: int) -> tuple[str, str]:
    """Grid rules for a full row of per_row bars and for shorter rows at the same cell width
    (unequal groups get proportional columns), and the alternate-bar shading."""
    n = len(grouping)
    if len(set(grouping)) == 1:
        tracks = lambda k: f'repeat({n * k},1fr)'
    else:
        tracks = lambda k: f'repeat({k},{" ".join(f"{g}fr" for g in grouping)})'
    rules = [f'.bars{{display:grid;grid-template-columns:{tracks(per_row)};border:1px solid '
             f'#d4d4d0;border-radius:3px;overflow:hidden}}']
    for k in range(1, per_row):
        pct = f'{100 * k / per_row:.3f}'.rstrip('0').rstrip('.')
        rules.append(f'.bars.cols-{n * k}{{grid-template-columns:{tracks(k)};max-width:{pct}%}}')
    shade = ','.join(f'.half:nth-child({2 * n}n+{c})' for c in range(1, n + 1))
    return ''.join(r + '\n' for r in rules), shade + '{background:#fbfbf8}\n'


def cells_legend(grouping: list[int], unit: str) -> str:
    """[2, 2] -> 'Each bar = 2 half-cells (beats 1–2 / beats 3–4); a thick line ends the bar.'"""
    n, spans, b = len(grouping), [], 0
    for g in grouping:
        spans.append(f'{unit} {b + 1}' if g == 1 else f'{unit}s {b + 1}–{b + g}')
        b += g
    even = len(set(grouping)) == 1
    what = '1 cell' if n == 1 else '2 half-cells' if n == 2 and even else f'{n} cells'
    return (f'Each bar = {what} ({" / ".join(spans)}{"" if even else ", widths to scale"}); '
            'a thick line ends the bar.')


CSS = """
body{font-family:-apple-system,"Helvetica Neue",Arial,sans-serif;max-width:1300px;margin:.8em auto;padding:0 .8em;color:#1a1a1a;background:#fff}
h1{font-size:1.15em;margin:0 0 .05em;font-weight:600}
.sub{color:#555;margin-bottom:.5em;font-size:.8em}
.hdr{display:grid;grid-template-columns:repeat(auto-fit,minmax(9.5em,1fr));gap:.15em 1.2em;padding:.35em .8em;background:#f6f6f4;border:1px solid #e3e3df;border-radius:4px;margin-bottom:.4em;font-size:.76em}
.hdr .k{color:#888;text-transform:uppercase;letter-spacing:.06em;font-size:.66em}
.hdr .v{font-weight:600}
.prov{font-size:.7em;color:#777;margin:0 0 .7em;line-height:1.45}
.prov b{color:#444}
.chart{overflow-x:auto}
.row{margin:.15em 0;page-break-inside:avoid;min-width:600px}
.row.section-start{margin-top:.9em;padding-top:.5em;border-top:2px solid #d8d8d4}
.row.section-start:first-of-type{margin-top:.2em;padding-top:0;border-top:none}
.row.section-start .row-name{font-size:.92em;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.row-head{display:flex;align-items:baseline;gap:.6em;margin:0 0 .12em .05em;flex-wrap:wrap}
.row-meta{font-family:Menlo,"Courier New",monospace;font-size:.7em;color:#999}
.row-note{font-size:.72em;color:#999;font-style:italic}
.row.verse .row-name{color:#4a6f96} .row.post .row-name{color:#b58632} .row.chorus .row-name{color:#b03030}
.row.inst .row-name{color:#777} .row.bridge .row-name{color:#5b9a52} .row.outro .row-name,.row.intro .row-name{color:#999}
@GRID@
.half{border-right:1px solid #ececea;padding:.45em .5em .4em;min-height:4.2em;background:#fff;position:relative}
@SHADE@
.half.bar-end{border-right:2px solid #b8b8b0}
.half:last-child{border-right:none}
.half.q{outline:1.5px dotted #b03030;outline-offset:-3px}
.half.q::after{content:"?";position:absolute;top:.15em;right:.35em;font-size:.8em;font-weight:800;color:#b03030}
.chord{font-size:1.85em;font-weight:700;color:#1a1a1a;font-family:Georgia,serif;line-height:1;min-height:1.05em;letter-spacing:-.02em;white-space:nowrap}
.chord.rest{color:#c5c5c5;font-style:italic;font-size:1.3em}
.chord .bass{font-size:.5em;font-weight:500;color:#4a6f96;margin-left:.22em;vertical-align:middle;letter-spacing:0;font-family:-apple-system,"Helvetica Neue",Arial,sans-serif}
.lyric{font-size:.68em;color:#666;margin-top:.5em;line-height:1.2;min-height:1.2em;font-style:italic}
.lyric.adlib{color:#aaa}
.lyric .pickup{font-weight:600;margin-left:.45em;font-style:normal;color:#b03030}
.lyric .pickup.pk-verse{color:#4a6f96} .lyric .pickup.pk-post{color:#b58632} .lyric .pickup.pk-outro{color:#888}
@EXTRA@
.notes{margin-top:1.8em;padding-top:.6em;border-top:2px solid #d8d8d4}
.notes h2{font-size:.95em;font-weight:700;text-transform:uppercase;letter-spacing:.05em;margin:0 0 .6em;color:#444}
.notes-grid{display:grid;grid-template-columns:1fr 1fr;gap:.7em 1.2em}
.note-block{font-size:.78em;line-height:1.45;padding:.55em .7em;background:#fafaf7;border:1px solid #eaeae5;border-radius:4px;page-break-inside:avoid}
.note-block.wide{grid-column:1/-1}
.note-block h3{font-size:.85em;font-weight:700;margin:0 0 .3em;color:#1a1a1a;text-transform:uppercase;letter-spacing:.04em}
.note-block p{margin:.3em 0 0;color:#555}
.note-block ul,.note-block ol{margin:.25em 0 0;padding-left:1.25em;color:#555}
.note-block li{margin-bottom:.2em}
.note-block code{font-family:Menlo,"Courier New",monospace;font-size:.92em;background:#f0efea;padding:.05em .3em;border-radius:2px;color:#333}
.note-block.reading{background:#f3f6fa;border-color:#d8e0e8}
.note-block.open{background:#fdf6f3;border-color:#f0dcd3}
table.map{width:100%;border-collapse:collapse;font-size:.95em;margin-top:.3em}
table.map th{text-align:left;font-size:.72em;text-transform:uppercase;letter-spacing:.06em;color:#888;border-bottom:1px solid #e3e3df;padding:.2em .4em;font-weight:600}
table.map td{border-bottom:1px solid #efefeb;padding:.25em .4em;vertical-align:middle;color:#444}
td.sn{font-weight:700;white-space:nowrap} td.sn.verse{color:#4a6f96} td.sn.chorus{color:#b03030}
td.sn.bridge{color:#5b9a52} td.sn.post{color:#b58632} td.sn.intro,td.sn.outro,td.sn.inst{color:#888}
.mono{font-family:Menlo,"Courier New",monospace;font-size:.9em;color:#888;white-space:nowrap}
.track{display:inline-block;width:52px;height:7px;background:#eeeeea;border-radius:2px;overflow:hidden;vertical-align:middle}
.meter{display:block;height:7px;background:#b03030;opacity:.8}
.meter.b{background:#4a6f96} .meter.d{background:#5b9a52} .meter.k{background:#b58632}
@media (max-width:720px){.notes-grid{grid-template-columns:1fr}.track{width:32px}}
@media print{body{max-width:100%;margin:0;padding:.3em}
 .chart{overflow:visible}.row{min-width:0}
 .row.section-start{margin-top:.4em;padding-top:.25em}
 .half{min-height:3.4em;padding:.3em .35em}.chord{font-size:1.55em}.lyric{font-size:.62em}
 .note-block{font-size:.7em;padding:.4em .55em}
 @page{size:A4 portrait;margin:.35in}}
"""
SPLIT_CSS = ('.half.split .chord{text-decoration:underline dashed #b58632;'
             'text-decoration-thickness:2px;text-underline-offset:.14em}')
ADLIB_CSS = '.lyric .adlib{color:#aaa;margin-left:.45em}'
KEYS = {'title', 'artist', 'sections', 'chords', 'folder', 'out', 'key_short', 'lyrics',
        'words', 'bass_notes', 'verified', 'grouping', 'bars_per_row', 'duration_s', 'subline',
        'facts', 'provenance', 'map_note', 'notes', 'method'}
KINDS = ('intro', 'verse', 'post', 'chorus', 'bridge', 'inst', 'outro')


def check_song(S: dict) -> None:
    """Refuse a SONG the renderer would misread - a missing or unknown key, a wrong shape, a
    Harte label, sections that skip, repeat or reorder bars - instead of rendering garbage."""
    if 'map_harmony' in S:
        raise ValueError("'map_harmony' is gone: give each section tuple its harmony text "
                         "as a 6th element")
    missing = [k for k in ('title', 'artist', 'sections', 'chords') if k not in S]
    unknown = sorted(set(S) - KEYS)
    if missing or unknown:
        raise ValueError(f'SONG keys missing {missing}, unknown {unknown} - see the docstring')
    tuples = lambda v, lo, hi: isinstance(v, (list, tuple)) and all(
        isinstance(x, (list, tuple)) and lo <= len(x) <= hi for x in v)
    shapes = (('sections', '(name, first_bar, last_bar, kind, note[, harmony])', 5, 6),
              ('facts', '(label, value)', 2, 2), ('notes', '(title, body[, cls])', 2, 3))
    for name, shape, lo, hi in shapes:
        if not tuples(S.get(name, []), lo, hi):
            raise ValueError(f"'{name}' must be a list of {shape} tuples")
    cell = lambda k: isinstance(k, tuple) and len(k) == 2 and all(isinstance(x, int) for x in k)
    for name in ('chords', 'lyrics', 'bass_notes'):
        v = S.get(name, {})
        if not isinstance(v, dict) or not all(cell(k) for k in v):
            raise ValueError(f"'{name}' must be a dict keyed by (bar, cell) tuples")
    bad = [k for k, v in S.get('lyrics', {}).items()
           if not (isinstance(v, (list, tuple)) and len(v) == 2)]
    if bad:
        raise ValueError(f'lyrics values must be (text, kind) tuples: {bad[:4]}')
    bad = [k for k, c in S['chords'].items() if not isinstance(c, str) or ':' in c
           or c in ('N', 'X')]
    if bad:
        raise ValueError("chords take lead-sheet symbols ('Am7', 'E/G#', 'N.C.'), not "
                         f"chords_lv.json's Harte labels: {bad[:4]}")
    first = 1
    for name, b0, b1, kind, *_ in S['sections']:
        if b0 != first or b1 < b0:
            raise ValueError(f'section {name!r} is bars {b0}-{b1}: sections run in bar order '
                             f'from bar 1 with no gap or overlap, so it starts at bar {first}')
        if kind not in KINDS:
            raise ValueError(f'section {name!r}: kind {kind!r} is not one of '
                             f'{", ".join(KINDS)} (a pre-chorus uses post)')
        first = b1 + 1


def check(S: dict, grid: Grid, last_bar: int) -> None:
    """Refuse cells off the bar grid or outside the sections instead of dropping them silently."""
    nbars = len(grid.db) - 1
    if last_bar > nbars:
        raise ValueError(f'sections run to bar {last_bar}; the beat grid has {nbars} bars '
                         '(one bar past the last downbeat is allowed)')
    bad = sorted(k for k in (*S['chords'], *S.get('lyrics', {}), *S.get('bass_notes', {}))
                 if not (1 <= k[0] <= last_bar and 1 <= k[1] <= grid.n))
    if bad:
        raise ValueError(f'cells outside the sections (bars 1-{last_bar}) or the '
                         f'{grid.n}-cell bar: {bad[:8]}')


def off_grid(doc: dict, grid: Grid, grouping: list) -> str | None:
    """Why an evidence file's cells are not this grid's (another grouping, or a cell that
    starts elsewhere: beat 1 or the bars moved since), or None."""
    if doc.get('grouping') and list(doc['grouping']) != grouping:
        return f"grouping {doc['grouping']}, the grid's is {grouping}"
    for c in doc['cells']:
        k = (c['bar'], c['cell'])
        if 't0' in c and k[0] < len(grid.db) and k[1] <= grid.n \
                and abs(c['t0'] - grid.start(k)) > 0.05:
            return (f"bar {k[0]} cell {k[1]} starts at {c['t0']:.2f} s, on the grid "
                    f"{grid.start(k):.2f} s")
    return None


def load_json(path: Path):
    """json.load that names the file when it isn't JSON."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f'{path}: not JSON ({e})') from None


def render(S: dict, out: str | Path | None = None) -> Path:
    """Write the chart for SONG dict S to out (default <folder>/<out>); returns the path."""
    check_song(S)
    folder = Path(S.get('folder', '.'))
    a = folder / 'analysis'
    rd = lambda name: load_json(a / name)
    F = rd('foundation.json')
    grouping = list(S.get('grouping') or F.get('grouping') or [])
    if not grouping:
        raise ValueError('no grouping in foundation.json: run foundation.py meter first '
                         '(never assume 4/4)')
    db = list(F['downbeat_times'])
    last_bar = max(sec[2] for sec in S['sections'])
    if last_bar == len(db):                       # one bar past the grid: a chord ringing out
        end = S.get('duration_s') or 0
        db.append(end if end > db[-1] else 2 * db[-1] - db[-2])
    grid = Grid(db, grouping)
    check(S, grid, last_bar)
    LV, TRI = rd('chords_lv.json'), rd('chord_proposal.json')
    for name, doc in (('chords_lv.json', LV), ('chord_proposal.json', TRI)):
        why = off_grid(doc, grid, grouping)
        if why:
            print(f'warning: {name} was made on another grid ({why}) - re-run it; the "?" and '
                  'split marks may be wrong', file=sys.stderr)
    lv = {(c['bar'], c['cell']): c for c in LV['cells']}
    tri = {(c['bar'], c['cell']): c for c in TRI['cells']}
    bass = {(c['bar'], c['cell']): c['pc_seconds'] for c in rd('bass_per_cell.json')['cells']}
    act = rd('stem_activity.json') if (a / 'stem_activity.json').exists() else {}
    stale = {s: len(v) for s, v in act.items() if len(v) != len(F['downbeat_times']) - 1}
    if stale:
        print(f'warning: stem_activity.json bars {stale} != {len(F["downbeat_times"]) - 1} '
              'on the grid - re-run stem_activity.py', file=sys.stderr)
    words = None
    if S.get('words'):
        W = rd(S['words'])
        words = W.get('words') if isinstance(W, dict) else None
        if not isinstance(words, list):
            raise ValueError(f'{a / S["words"]}: no "words" list (a Whisper words file)')
        if not words:
            print(f'warning: {a / S["words"]} has no words - each lyric line stays whole at '
                  'its anchor', file=sys.stderr)
            words = None

    verified = set(S.get('verified', ()))
    flagged, split = flags(S, lv, tri, bass) - verified, splits(S, lv) - verified
    lyr, over = distribute(S, grid, words)
    st = stats(S, lv, tri)
    per_row = S.get('bars_per_row') or max(1, 8 // grid.n)
    grid_rules, shade = grid_css(grouping, per_row)
    extra = [f'.lyric .pickup.{p}{{color:{c}}}' for p, c in PICKUP_COLOURS.items()
             if any(p in kind.split() for _, kind in over.values())]
    if split:
        extra.append(SPLIT_CSS)
    if any(kind == 'adlib' and k in lyr for k, (_, kind) in over.items()):
        extra.append(ADLIB_CSS)
    css = (CSS.replace('@GRID@\n', grid_rules).replace('@SHADE@\n', shade)
           .replace('@EXTRA@\n', ''.join(r + '\n' for r in extra)))

    key = f" · {esc(S['key_short'])}" if S.get('key_short') else ''
    name = f"{esc(S['artist'])} — {esc(S['title'])}"
    hdr = ''.join(f'<div><div class="k">{esc(k)}</div><div class="v">{v}</div></div>'
                  for k, v in S.get('facts', []))
    top = ''.join(line + '\n' for line in (
        S.get('subline') and f"<div class=\"sub\">{S['subline']}</div>",
        hdr and f'<div class="hdr">{hdr}</div>',
        S.get('provenance') and f"<div class=\"prov\">{S['provenance']}</div>") if line)
    blocks = ''.join(f'<div class="note-block {(rest or [""])[0]}"><h3>{title}</h3>{body}</div>'
                     for title, body, *rest in S.get('notes', []))
    pct = lambda x, n: round(100 * x / max(n, 1))
    try:
        method = S.get('method', METHOD).format(cells=st['cells'], n_q=len(flagged),
                                                lv_pct=pct(st['lv'], st['lv_n']),
                                                tri_pct=pct(st['tri'], st['tri_n']))
    except (KeyError, IndexError, ValueError) as e:
        raise ValueError(f"'method' takes {{cells}}, {{lv_pct}}, {{tri_pct}} and {{n_q}}; write "
                         f"other braces doubled ({e!r})") from None
    map_note = f"<p>{S['map_note']}</p>" if S.get('map_note') else ''
    halves = grid.n == 2 and grouping[0] == grouping[1]
    legend = [
        cells_legend(grouping, UNITS.get(F.get('pulse_unit'), 'beat')),
        '<b>Chord</b> = guitar/piano shape; <span style="color:#4a6f96">(D)</span> = bass note '
        "when it isn't the root.",
        "Lyrics sit where they're sung; pickup syllables are pulled into the chord the phrase "
        'lands on. Empty lyric = hold.' if words is not None else
        'Each lyric line sits at the chord the phrase lands on. Empty lyric = hold.',
        '<b style="color:#b03030">Coloured words</b> = the next section\'s pickup, starting '
        'inside this box.',
        f'<span style="color:#b03030">?</span> + dotted box = this '
        f"{'half-bar' if halves else 'cell'}'s own reading names a different chord — check by "
        'ear.']
    if split:
        legend.append('Dashed underline = the chord changes inside this cell — listen for where.')
    items = ''.join(f'<li>{x}</li>\n' for x in legend)
    doc = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} · Chords{key}</title>
<style>{css}</style></head><body>
<h1>{name}{key}</h1>
{top}<div class="chart">
{rows_html(S, grid.n, per_row, flagged, split, lyr, over)}
</div>
<section class="notes">
<h2>Song map</h2>
<div class="notes-grid"><div class="note-block wide">{map_html(S, db, act)}{map_note}</div></div>
<h2 style="margin-top:1em">Harmonic notes &amp; commentary</h2>
<div class="notes-grid">
{blocks}
<div class="note-block">
<h3>Method &amp; confidence</h3>{method}</div>
<div class="note-block reading"><h3>How to read the cells</h3><ul>
{items}</ul></div>
</div>
</section>
</body></html>
"""
    default = re.sub(r'[\\/:]', '-', f"{S['artist']} - {S['title']} - Chords.html")
    out = Path(out) if out else folder / S.get('out', default)
    out.write_text(doc, encoding='utf-8')
    n_ly = len(set(lyr) | {k for k, (_, kind) in over.items() if kind == 'adlib'})
    print(f"wrote {out}: {st['cells']} chord cells, lv-chordia root agrees {st['lv']}, "
          f"triads {st['tri']}, {len(flagged)} marked '?', {len(split)} split, "
          f"{n_ly} lyric cells")
    return out


def load_song(path: str | Path) -> dict:
    """SONG from a chart data file; 'folder' defaults to, and resolves against, its folder."""
    path = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f'_chart_{path.stem}', path)
    if spec is None:
        raise ValueError(f'{path}: not a Python file')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not isinstance(getattr(mod, 'SONG', None), dict):
        raise ValueError(f'{path} defines no SONG dict')
    S = dict(mod.SONG)
    S['folder'] = str(path.parent / S.get('folder', '.'))
    return S


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("song", help="chart data file defining SONG, e.g. <song folder>/gen_v1.py")
    ap.add_argument("--out", help="HTML path (default: <folder>/<SONG['out']>)")
    a = ap.parse_args()
    sys.dont_write_bytecode = True                # no __pycache__ in the song folder
    try:
        render(load_song(a.song), a.out)
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"chart_html: {e!r}" if isinstance(e, KeyError) else f"chart_html: {e}")


if __name__ == "__main__":
    main()
