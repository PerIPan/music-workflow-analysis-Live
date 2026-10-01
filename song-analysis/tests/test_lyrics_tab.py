#!/usr/bin/env python3
"""Test lyrics_from_page.py and tab_compare.py on synthetic pages (no network).

lyrics_from_page: a <pre> chord tab -> section labels from its headers, chord lines out of
the lyrics and into tab_chords per section, blank lines inside a labelled section dropped
(they are page layout), Key:/Capo: lines skipped; a lyrics page that spaces every line
keeps one section; no lyrics -> exit 1. tab_compare: root + major/minor from tab and Harte
labels; a tab-only chord the bass never plays is flagged as a passing chord; the same root
with the other third is flagged for the ear; full agreement says so.
Run: python3 song-analysis/tests/test_lyrics_tab.py   (standard library only)
"""
import json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from lyrics_from_page import parse, text_blocks  # noqa: E402
from tab_compare import simple  # noqa: E402

fails = 0


def check(name, cond, info=''):
    global fails
    fails += not cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f'  [{info}]' if not cond else ''))


TAB = """<html><pre>Key: Am
Capo: 2

Verse 1:

Am        G
la la one
lo lo two

Am   F    G
la la three

Chorus:
C  G  Am
sing it out
</pre></html>"""
lines, tab = parse(text_blocks(TAB))
check('tab page: [labels] from headers, chord lines out, Key/Capo skipped',
      lines == ['[Verse 1]', 'la la one', 'lo lo two', 'la la three', '', '[Chorus]',
                'sing it out'], lines)
check('tab chords per section, in order',
      tab == [{'section': 'Verse 1', 'chords': ['Am', 'G', 'Am', 'F', 'G']},
              {'section': 'Chorus', 'chords': ['C', 'G', 'Am']}], tab)
SPACED = ('<p id="songLyricsDiv" class="songLyricsV14">' +
          '<br>\n<br>\n'.join(f'line {k}' for k in range(8)) + '</p>')
check('a lyrics page that spaces every line keeps one section',
      parse(text_blocks(SPACED))[0] == [f'line {k}' for k in range(8)])
tmp = Path(tempfile.mkdtemp())
(tmp / 'empty.html').write_text('<html><body>nothing here</body></html>')
r = subprocess.run([sys.executable, str(SCRIPTS / 'lyrics_from_page.py'), str(tmp / 'empty.html'),
                    '--out', str(tmp / 'l.txt')], capture_output=True, text=True)
check('no lyrics on the page -> exit 1, nothing written',
      r.returncode == 1 and not (tmp / 'l.txt').exists(), r.stderr)

check('chord names: tab and Harte labels to root + major/minor',
      [simple(x) for x in ('F#', 'Bm7', 'A/C#', 'F#:min', 'B:maj7', 'Ebm', 'N.C.')] ==
      [(6, 'maj'), (11, 'min'), (9, 'maj'), (6, 'min'), (11, 'maj'), (3, 'min'), None])
(tmp / 'tab.json').write_text(json.dumps({'sections': [
    {'section': 'Verse 1', 'chords': ['F#', 'E', 'A', 'B']},
    {'section': 'Chorus', 'chords': ['F#', 'Bm']}]}))
cells = [dict(bar=b, cell=1, chord=c) for b, c in
         [(1, 'F#:min'), (2, 'A:maj'), (3, 'B:maj'), (4, 'F#:maj'), (5, 'B:min')]]
(tmp / 'ch.json').write_text(json.dumps({'cells': cells}))
(tmp / 'sec.json').write_text(json.dumps({'sections': [
    {'label': 'Verse 1', 'where': [1, 1]}, {'label': 'Chorus', 'where': [4, 1]}]}))
(tmp / 'bass.json').write_text(json.dumps({'cells': [
    dict(bar=b, cell=1, pc_seconds={p: 0.5}) for b, p in [(1, 'F#'), (2, 'A'), (3, 'B')]]}))
r = subprocess.run([sys.executable, str(SCRIPTS / 'tab_compare.py'), '--tab', str(tmp / 'tab.json'),
                    '--chords', str(tmp / 'ch.json'), '--sections', str(tmp / 'sec.json'),
                    '--bass', str(tmp / 'bass.json')], capture_output=True, text=True)
out = r.stdout
verse = next((l for l in out.splitlines() if l.startswith('Verse 1')), '')
chorus = next((l for l in out.splitlines() if l.startswith('Chorus')), '')
check('tab-only E never in the bass -> a passing chord; F# vs our F#m -> the third by ear',
      'E only in the tab (never in the bass' in verse and 'F# vs our F#m' in verse, out)
check('a section that matches says agree; the agreement count is printed',
      chorus.rstrip().endswith('agree') and 'agreement: ' in out, out)
sys.exit(1 if fails else 0)
