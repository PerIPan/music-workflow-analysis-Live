#!/usr/bin/env python3
"""Test scripts/chart_html.py on synthetic songs (invented lyrics, temp folders, no audio).

A 4/4 song checks lyric placement (pickup pulled into the anchor, no spill past the next
anchor, unheard words a beat apart), the "?" rule, N.C., slash bass, pickup overlay, the
split mark, HTML escaping and the page's fit and print rules (label widths, room for the
"?", tight accidentals, meters printed without backgrounds); then the same song without
words or stem levels and with player-verified cells, and broken words files. Small songs
check lyric edge cases (a line sharing a pickup's or an ad-lib's cell, a line stopped at
its section's end, a repeated line, Greek words, a '♪' token), chord evidence (the "?"
without --compare, the split mark by coverage, odd labels, a stale grid). A 6+5 bar, a
3/4 bar (plus a tail bar past the last downbeat, and a row that repeats its section's name
in print) and a 2+2+3 bar check the grid; malformed data is refused, and the CLI renders a
data file and reports bad data without a traceback. Temp folders are removed at exit.
Run: python3 tests/test_chart_html.py
"""
import atexit, contextlib, io, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from chart_html import bass_em, label_em, lead_sheet, render  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="chart_html_"))
atexit.register(shutil.rmtree, TMP, True)
CELL = re.compile(r'<div class="(half[^"]*)"><div class="(chord[^"]*)"(?: style="[^"]*")?>'
                  r'(.*?)</div><div class="(lyric[^"]*)">(.*?)</div></div>')
WIDTH = re.compile(r'<div class="chord[^"]*"(?: style="--w:([\d.]+)(?:;--b:[\d.]+)?")?>')
PICKUP = re.compile(r'<span class="pickup[^"]*">.*?</span>')
ACC = lambda s: f'<span class="acc">{s}</span>'                  # a ♯ or ♭ in a chord name


def make_song(grouping, bar_len, nbars, chords, evidence=None, words=None, act=None,
              pulse_unit=4, t0=0.0):
    """Song folder with analysis/ files. evidence: {(bar, cell): (lv, status, triad, bass[,
    lv coverage])}, coverage 0.4 for change-inside, else 1; other chord cells get agreeing
    readers and no bass. Evidence cells carry their start time and grouping, as upstream."""
    d = Path(tempfile.mkdtemp(dir=TMP))
    a = d / "analysis"
    a.mkdir()
    put = lambda name, obj: (a / name).write_text(json.dumps(obj), encoding="utf-8")
    put("foundation.json", dict(downbeat_times=[t0 + bar_len * i for i in range(nbars + 1)],
                                grouping=grouping, pulse_unit=pulse_unit))
    ev = lambda k: (evidence or {}).get(k) or (chords.get(k, "N"), "agree", chords.get(k, "N"), {})
    cov = lambda e: e[4] if len(e) > 4 else 0.4 if e[1] == "change-inside" else 1.0
    keys = [(b, c) for b in range(1, nbars + 1) for c in range(1, len(grouping) + 1)]
    start = lambda b, c: round(t0 + bar_len * (b - 1 + sum(grouping[:c - 1]) / sum(grouping)), 3)
    put("chords_lv.json", dict(grouping=grouping, cells=[
        dict(bar=b, cell=c, t0=start(b, c), chord=ev((b, c))[0], status=ev((b, c))[1],
             coverage=cov(ev((b, c)))) for b, c in keys]))
    put("chord_proposal.json", dict(grouping=grouping, cells=[
        dict(bar=b, cell=c, t0=start(b, c), chord=ev((b, c))[2]) for b, c in keys]))
    put("bass_per_cell.json", dict(cells=[dict(bar=b, cell=c, pc_seconds=ev((b, c))[3])
                                          for b, c in keys]))
    if words is not None:
        put("words.json", dict(words=[dict(word=w, start=t, end=t + 0.2) for w, t in words]))
    if act is not None:
        put("stem_activity.json", act)
    return d


def build(S, d, name):
    out = render(dict(S, folder=str(d)), out=d / name)
    doc = out.read_text(encoding="utf-8")
    return doc, CELL.findall(doc)


def at(cells, n):
    """{(bar, cell): (classes, chord_class, chord_html, lyric_class, lyric_html)}."""
    return {(i // n + 1, i % n + 1): c for i, c in enumerate(cells)}


def widths(doc, n):
    """{(bar, cell): the label's --w in em, or None (no style: N.C., an empty cell)}."""
    return {(i // n + 1, i % n + 1): float(w) if w else None
            for i, w in enumerate(WIDTH.findall(doc))}


def lyric(cell):
    return PICKUP.sub("", cell[4])


# ---------------------------------------------------------------- the 4/4 song
CHORDS = {(1, 1): "N.C.", (1, 2): "N.C.", (2, 1): "C", (2, 2): "C", (3, 1): "C", (3, 2): "Em/D",
          (4, 1): "C", (4, 2): "C", (5, 1): "F#m7", (5, 2): "Bb", (6, 1): "G", (6, 2): "G",
          (7, 1): "D", (7, 2): "D", (8, 1): "N.C.", (8, 2): "N.C."}
EVIDENCE = {
    (2, 1): ("A:min", "root-disagree", "C", {"C": 0.8}),      # lv-chordia names A -> ?
    (2, 2): ("C:maj7", "root-disagree", "Am", {"C": 0.8}),    # triads only, bass plays C
    (3, 1): ("C:maj", "root-disagree", "Am", {"A": 0.8}),     # triads + bass on A -> ?
    (3, 2): ("E:min/b7", "root-disagree", "D", {"D": 0.9}),   # bass = the slash note
    (4, 1): ("C:maj", "near-tie", "C", {"C": 0.5}),           # a near-tie alone
    (4, 2): ("C:maj", "root-disagree", "Am", {"A": 0.1}),     # bass note too short to count
    (6, 1): ("G:maj", "change-inside", "G", {}),              # split mark
    (8, 1): ("C:maj", "agree", "C", {}),                      # N.C. is never marked
}
LYRICS = {
    (2, 1): ('Rock & roll <now> "go"', "adlib"),
    (3, 1): ("Hello there my friend", ""),
    (4, 1): ("Stay close and never ever leave", ""),
    (5, 1): ("Next line begins", ""),
    (6, 1): ("Quiet words nobody heard clearly", ""),
    (7, 2): ("Oh now", "pk pk-bridge"),
    (8, 1): ("(hey hey)", "adlib"),
}
# bar b = [1 + 2(b-1), 1 + 2b) s, cells of 1 s, beats of 0.5 s. "Hello" is sung in bar 2,
# "ever" after the next line's anchor (bar 5), "leave" and the bar-6 line are never heard.
WORDS = [("Hello", 4.6), ("there", 5.1), ("my", 5.4), ("friend", 6.2), ("Stay", 7.0),
         ("close", 7.4), ("and", 8.1), ("never", 8.5), ("ever", 9.1), ("Next", 9.2),
         ("line", 9.6), ("begins", 10.3)]
ACT = {s: [0.1 * i for i in range(8)] for s in ("drums", "bass", "other", "vocals")}
SONG = dict(title="Test Song", artist="Tom & Jerry <Band>", key_short="C major",
            words="words.json", chords=CHORDS, lyrics=LYRICS, bass_notes={(5, 2): "A"},
            sections=[('Intro & "more"', 1, 1, "intro", "count-in <b>two</b>", "N.C."),
                      ("Verse", 2, 5, "verse", "first verse", "C · Em/D"),
                      ("Bridge", 6, 8, "bridge", "lift", "G · D")],
            facts=[("Tempo", "120 BPM")], map_note="levels",
            notes=[("Idea", "<p>one loop</p>"), ("Open", "<ol><li>beat 1?</li></ol>", "open")],
            method="<p>{cells}|{lv_pct}|{tri_pct}|{n_q}</p>")


def main():
    fails = 0

    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{info}]"))

    d = make_song([2, 2], 2.0, 8, CHORDS, EVIDENCE, WORDS, ACT, t0=1.0)
    doc, cells = build(dict(SONG, placement="anchor"), d, "main.html")
    C = at(cells, 2)
    L = {k: lyric(v) for k, v in C.items()}
    check("16 cells, one per half-bar", len(cells) == 16, len(cells))
    check("pickup word sung in bar 2 pulled into the anchor",
          L[(3, 1)] == "Hello there my" and L[(2, 2)] == "", (L[(2, 2)], L[(3, 1)]))
    check("line split where it is sung", L[(3, 2)] == "friend", L[(3, 2)])
    check("nothing spills past the next anchor",
          L[(4, 1)] == "Stay close" and L[(4, 2)] == "and never ever leave"
          and L[(5, 1)] == "Next line" and L[(5, 2)] == "begins",
          [L[k] for k in ((4, 1), (4, 2), (5, 1), (5, 2))])
    check("unheard words a beat apart", [L[k] for k in ((6, 1), (6, 2), (7, 1))] ==
          ["Quiet words", "nobody heard", "clearly"], [L[k] for k in ((6, 1), (6, 2), (7, 1))])
    q = {k for k, v in C.items() if "q" in v[0].split()}
    check("? where lv-chordia names another root", (2, 1) in q, q)
    check("no ? for a triad-only objection the bass contradicts", (2, 2) not in q, q)
    check("? for triad objection + a bass note against the chart", (3, 1) in q, q)
    check("no ? when the bass plays the slash note", (3, 2) not in q, q)
    check("no ? for a near-tie or a bass note under 0.15 s",
          (4, 1) not in q and (4, 2) not in q, q)
    check("N.C. never marked, exactly 2 ?", q == {(2, 1), (3, 1)}, q)
    check("N.C. cells", C[(1, 1)][1:3] == ("chord rest", "N.C.") and
          C[(8, 2)][1:3] == ("chord rest", "N.C."), C[(1, 1)])
    check("slash chord -> Em (D)", C[(3, 2)][2] == 'Em<span class="bass">(D)</span>', C[(3, 2)][2])
    check("bass_notes + flat -> B♭ (A); sharp -> F♯m7 (accidentals in their own span)",
          C[(5, 2)][2] == f'B{ACC("♭")}<span class="bass">(A)</span>'
          and C[(5, 1)][2] == f'F{ACC("♯")}m7', (C[(5, 1)][2], C[(5, 2)][2]))
    check("pickup overlay in its cell, in the bridge colour",
          '<span class="pickup pk-bridge">Oh now</span>' in C[(7, 2)][4]
          and ".lyric .pickup.pk-bridge{color:#5b9a52}" in doc, C[(7, 2)][4])
    check("ad-lib whole and greyed", C[(8, 1)][3:] == ("lyric adlib", "(hey hey)"), C[(8, 1)])
    check("change-inside -> dashed underline + legend", "split" in C[(6, 1)][0].split()
          and ".half.split .chord{text-decoration:underline dashed" in doc
          and "Dashed underline = the chord changes" in doc, C[(6, 1)][0])
    check("escaped: title, lyric, section name",
          "<h1>Tom &amp; Jerry &lt;Band&gt; — Test Song · C major</h1>" in doc
          and C[(2, 1)][4] == "Rock &amp; roll &lt;now&gt; &quot;go&quot;"
          and "Intro &amp; &quot;more&quot;</span>" in doc, C[(2, 1)][4])
    check("html fields kept as html", "count-in <b>two</b>" in doc
          and '<div class="note-block open"><h3>Open</h3><ol>' in doc)
    check("bar-end on cell 2 only", all(("bar-end" in v[0].split()) == (k[1] == 2)
                                        for k, v in C.items()))
    check("Harte labels -> lead sheet (A:min, C:maj7, G/5, G/b7, F:maj/3, N, E:hdim7)",
          [lead_sheet(x) for x in ("A:min", "C:maj7", "G/5", "G/b7", "F:maj/3", "N", "E:hdim7")]
          == ["Am", "Cmaj7", "G/D", "G/F", "F/A", "N.C.", "Em7b5"])
    check("lead-sheet symbols pass through", [lead_sheet(x) for x in ("Em/D", "F#m7", "N.C.", "C6/9")]
          == ["Em/D", "F#m7", "N.C.", "C6/9"])
    check("4/4 legend wording", "Each bar = 2 half-cells (beats 1–2 / beats 3–4); a thick line "
          "ends the bar." in doc and "this half-bar's own reading" in doc)
    check("short rows keep cell width (1 bar, 3 bars)",
          '<span class="row-meta">bar 1</span>' in doc and doc.count('class="bars cols-2"') == 1
          and doc.count('class="bars cols-6"') == 1
          and ".bars.cols-6{grid-template-columns:repeat(6,minmax(0,1fr));max-width:75%}" in doc)
    check("columns can't grow with a wide label (minmax(0, 1fr) tracks)",
          ".bars{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));" in doc)
    check("2-cell shading", ".half:nth-child(4n+1),.half:nth-child(4n+2){background:#fbfbf8}"
          in doc)
    W = widths(doc, 2)
    near = lambda w, x: w is not None and abs(w - x) <= 0.011
    check("each label carries its width in em (none on N.C.): C, Em/D, B♭ (A)",
          W[(1, 1)] is None and near(W[(2, 1)], 0.72) and near(W[(3, 2)], 2.55)
          and near(W[(5, 2)], 2.05), {k: W[k] for k in ((1, 1), (2, 1), (3, 2), (5, 2))})
    check("label widths: a flat as narrow as a sharp, long labels wide",
          near(label_em("B♭", None), 1.26) and near(label_em("F♯m7", None), 2.8)
          and label_em("E♭maj7♯11", None) > 5, label_em("B♭", None))
    check("a label wider than its cell shrinks to fit it (container units), clipped at its edge",
          "container-type:inline-size;--cap:1.85rem}" in doc
          and ".chord[style]{--a:calc(100cqi - var(--room,0rem));" in doc
          and "font-size:min(var(--cap),calc(var(--a) / var(--w))," in doc
          and "overflow-x:clip}" in doc)
    check("a slash label carries its bass width (--b); the bass keeps a floor, the name fits "
          "beside it", re.search(r'<div class="chord" style="--w:2\.5\d;--b:1\.63">Em<span '
                               r'class="bass">', doc) and near(bass_em("D"), 1.63) and ".chord .bass{font-size:max(.5em,min(.6rem,"
          ".75em));" in doc and "max(calc((var(--a) - .6rem * var(--b,0)) / var(--n)),calc("
          "var(--a) / (var(--n) + .75 * var(--b,0)))))" in doc, bass_em("D"))
    check("chord font falls back to Georgia- or Times-metric serifs, not a wider default",
          'font-family:Georgia,Gelasio,"Liberation Serif",Tinos,"Times New Roman",serif;' in doc)
    check("a '?' cell keeps room for the mark", ".half.q{outline:1.5px dotted #b03030;"
          "outline-offset:-3px;--room:.6rem}" in doc and "margin:0 var(--room,0rem) 0 -.1em" in doc)
    check("accidentals set in a font with a narrow ♭ (Georgia has none)",
          '.chord .acc{font-family:STIXGeneral,"Apple Symbols","Segoe UI Symbol"' in doc)
    check("print: meters, bar shading and note tints print without background graphics",
          ".track,.meter,.bars,.note-block{-webkit-print-color-adjust:exact;"
          "print-color-adjust:exact}" in doc)
    check("print: the notes headings stay with their blocks",
          ".notes h2{break-after:avoid;page-break-after:avoid;" in doc)
    check("print: the chord size cap drops to 1.55rem", "--cap:1.55rem}" in doc)
    check("phone: long lyric words wrap; only 10+ letter words hyphenate, 5+ letters a side",
          "overflow-wrap:break-word}" in doc and ".lyric{-webkit-hyphens:auto;hyphens:auto;"
          "hyphenate-limit-chars:10 5 5;-webkit-hyphenate-limit-before:5;"
          "-webkit-hyphenate-limit-after:5}}" in doc)
    check("print: pale row heads darkened (WebKit prints them near-invisible)",
          " .row-meta,.row-note,.row.inst .row-name,.row.outro .row-name,.row.intro .row-name"
          "{color:#666}" in doc)
    check("pickup legend when the chart has a pickup", "Coloured words</b> = the next" in doc)
    check("song map: harmony + 4 stem meters", "<th>Harmony</th><th>Vocal</th><th>Bass</th>"
          "<th>Drums</th><th>Keys/gtr</th>" in doc and "<td>C · Em/D</td>" in doc)
    check("method placeholders", "<p>12|92|67|2</p>" in doc,
          re.search(r"Method &amp; confidence</h3>(.*?)</div>", doc).group(1))

    (d / "analysis" / "stem_activity.json").unlink()
    S = {k: v for k, v in SONG.items() if k != "words"}
    doc, cells = build(S, d, "bare.html")
    L = {k: lyric(v) for k, v in at(cells, 2).items()}
    check("no words file: lines whole at their anchor",
          L[(3, 1)] == "Hello there my friend" and L[(4, 1)] == "Stay close and never ever leave"
          and L[(3, 2)] == "" and "Each lyric line sits at the chord" in doc,
          (L[(3, 1)], L[(4, 1)]))
    check("no stem_activity.json: map without meters",
          "<th>Vocal</th>" not in doc and 'class="track"' not in doc and "<th>Harmony</th>" in doc)
    doc, cells = build(dict(S, verified=[(2, 1), (6, 1)]), d, "verified.html")
    C = at(cells, 2)
    check("player-verified cells lose their ? and split mark",
          {k for k, v in C.items() if "q" in v[0].split()} == {(3, 1)}
          and "split" not in C[(6, 1)][0].split() and ".half.split" not in doc)
    doc2, _ = build(dict(S, verified=[[2, 1], [6, 1]]), d, "verified.html")
    check("verified as JSON-style [bar, cell] lists works the same", doc2 == doc)

    wf = d / "analysis" / "words.json"
    wf.write_text('{"words": []}', encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        doc, cells = build(SONG, d, "nowords.html")
    L = {k: lyric(v) for k, v in at(cells, 2).items()}
    check("empty words list: lines whole at their anchor, anchor legend, a warning",
          L[(4, 1)] == "Stay close and never ever leave" and L[(4, 2)] == ""
          and "Each lyric line sits at the chord" in doc and "has no words" in err.getvalue(),
          (L[(4, 1)], err.getvalue()))
    for name, raw in (("0-byte words file", ""), ("words file without a words list", "{}")):
        wf.write_text(raw, encoding="utf-8")
        try:
            build(SONG, d, "bad.html")
            check(f"{name} refused, naming the file", False, "rendered")
        except ValueError as e:
            check(f"{name} refused, naming the file", "words.json" in str(e), e)

    # ------------------------------------------------------------ lyric placement edge cases
    def placed(grouping, bar_len, nbars, sections, lyrics, words, name):
        """The page of a one-chord song, and {(bar, cell): lyric html} of its non-empty cells."""
        n, last = len(grouping), sections[-1][2]
        ch = {(b, c): "C" for b in range(1, last + 1) for c in range(1, n + 1)}
        d = make_song(grouping, bar_len, nbars, ch, words=words)
        doc, cells = build(dict(title="Lyric", artist="Nobody", words="words.json", chords=ch,
                                sections=sections, lyrics=lyrics, placement="anchor"), d, name)
        return doc, {k: v[4] for k, v in at(cells, n).items() if v[4]}

    _, P = placed([3], 1.5, 5, [("Verse", 1, 3, "verse", ""), ("Chorus", 4, 5, "chorus", "")],
                  {(2, 1): ("copper kettles humming low", ""), (3, 1): ("Oh now", "pk pk-chorus"),
                   (4, 1): ("tin roofs", "")},
                  [("copper", 1.6), ("kettles", 2.0), ("humming", 2.5), ("low", 3.2),
                   ("Oh", 3.8), ("now", 4.1), ("tin", 4.6), ("roofs", 5.0)], "pickup.html")
    check("Rule 4: a line's last word shares the pickup's cell (3/4)",
          P == {(2, 1): "copper kettles humming",
                (3, 1): 'low<span class="pickup pk-chorus">Oh now</span>', (4, 1): "tin roofs"}, P)
    doc, P = placed([2, 2], 2.0, 5, [("Verse", 1, 5, "verse", "")],
                    {(2, 1): ("seven lanterns drift across the quiet bay", ""),
                     (2, 2): ("(ooh)", "adlib"), (5, 1): ("ferry bells", "")},
                    [("seven", 2.1), ("lanterns", 2.6), ("drift", 3.1), ("across", 4.2),
                     ("the", 4.6), ("quiet", 5.2), ("bay", 5.6), ("ferry", 8.1), ("bells", 8.4)],
                    "adlib.html")
    check("an ad-lib shares its cell with the lead line, which goes on past it",
          P == {(2, 1): "seven lanterns", (2, 2): 'drift<span class="adlib">(ooh)</span>',
                (3, 1): "across the", (3, 2): "quiet bay", (5, 1): "ferry bells"}
          and ".lyric .adlib{color:#aaa" in doc, P)
    _, P = placed([2, 2], 2.0, 6, [("Verse", 1, 2, "verse", ""), ("Inter", 3, 4, "inst", ""),
                                   ("Chorus", 5, 6, "chorus", "")],
                  {(2, 1): ("one two three four five six", ""), (5, 1): ("shine", "")},
                  [("one", 2.0), ("two", 2.5), ("three", 3.0), ("shine", 8.1)], "section.html")
    check("unheard words stop at the line's section end, not in the next section",
          P == {(2, 1): "one two", (2, 2): "three four five six", (5, 1): "shine"}, P)
    line = "amber rain falls on quiet wooden roofs"
    _, P = placed([3], 1.0, 10, [("Outro", 1, 8, "outro", "")], {(3, 1): (line, "")},
                  [(w, 2.1 + i) for i, w in enumerate(line.split())], "last.html")
    check("the last line runs to its section's last bar (no 4-bar cap, no unrendered bar)",
          P == {(3, 1): "amber", (4, 1): "rain", (5, 1): "falls", (6, 1): "on",
                (7, 1): "quiet", (8, 1): "wooden roofs"}, P)
    line = "paper lanterns drifting home"                # sung twice, a bar apart
    heard = [(w, b + dt) for b in (2.1, 4.1) for w, dt in zip(line.split(), (0, .4, 1, 1.4))]
    _, P = placed([2, 2], 2.0, 4, [("Verse", 1, 4, "verse", "")],
                  {(2, 1): (line, ""), (3, 1): (line, "")}, heard, "repeat.html")
    check("a repeated line keeps its own words (not the line before's, 2.5 s back)",
          P == {(2, 1): "paper lanterns", (2, 2): "drifting home",
                (3, 1): "paper lanterns", (3, 2): "drifting home"}, P)
    line = "salt wind rising"                           # sung 3x, Whisper heard 1st and 3rd
    three = {(1, 1): (line, ""), (2, 1): (line, ""), (3, 1): (line, "")}
    for early, name in ((0, "at its anchor"), (.4, "0.4 s early")):
        heard = [(w, b - early * (b > 0) + .3 * j) for b in (0.0, 4.0)
                 for j, w in enumerate(line.split())]
        _, P = placed([2, 2], 2.0, 4, [("Verse", 1, 4, "verse", "")], three, heard,
                      "dropped.html")
        check(f"a repeat Whisper missed leaves the next one its words (next sung {name})",
              P == {(1, 1): line, (2, 1): "salt wind", (2, 2): "rising", (3, 1): line}, P)
    heard = [(w, .3 * j) for j, w in enumerate("salt on stone".split())] + \
            [(w, 4.0 + .3 * j) for j, w in enumerate("salt and smoke".split())]
    _, P = placed([2, 2], 2.0, 4, [("Verse", 1, 4, "verse", "")],
                  {(1, 1): ("salt on stone", ""), (2, 1): ("salt wind rising", ""),
                   (3, 1): ("salt and smoke", "")}, heard, "shared.html")
    check("an unheard line leaves the next line its shared first word",
          P == {(1, 1): "salt on stone", (2, 1): "salt wind", (2, 2): "rising",
                (3, 1): "salt and smoke"}, P)
    heard = [(w, .3 * j) for j, w in enumerate(line.split())]
    _, P = placed([2, 2], 2.0, 4, [("Verse", 1, 4, "verse", "")],
                  {(1, 1): (line, ""), (2, 1): (line, "")}, heard, "second.html")
    check("a line keeps its own words when the unheard repeat after it wants them",
          P == {(1, 1): line, (2, 1): "salt wind", (2, 2): "rising"}, P)
    _, P = placed([2, 2], 2.0, 4, [("Verse", 1, 4, "verse", "")],
                  {(2, 1): ("ένα δύο τρία τέσσερα", ""), (3, 1): ("πέντε έξι επτά", "")},
                  list(zip("ένα δύο τρία τέσσερα πέντε έξι επτά".split(),
                           (2.1, 2.5, 3.2, 3.6, 4.1, 5.2, 5.6))), "greek.html")
    check("Greek words matched: each line split where sung",
          P == {(2, 1): "ένα δύο", (2, 2): "τρία τέσσερα", (3, 1): "πέντε", (3, 2): "έξι επτά"},
          P)
    _, P = placed([2, 2], 2.0, 4, [("Verse", 1, 4, "verse", "")],
                  {(2, 1): ("paper boats — ohhh", ""), (3, 1): ("harbour", "")},
                  [("paper", 2.1), ("boats", 2.4), ("ohhh", 2.5), ("♪", 3.6), ("harbour", 4.1)],
                  "punct.html")
    check("a '♪' token or a dash is no word", P == {(2, 1): "paper boats — ohhh",
                                                  (3, 1): "harbour"}, P)

    # ------------------------------------------------------------ chord evidence and labels
    ch = {(b, c): "A" for b in range(1, 5) for c in (1, 2)}
    ch.update({(3, 1): "C6/9", (3, 2): "C#/E#", (4, 1): "F#m7b5", (4, 2): "Gb/Cb"})
    ev = {(1, 1): ("N", "agree", "F#m", {"F#": 0.9}),                # lv-chordia hears no chord
          (1, 2): ("A:maj", "unchecked", "F#m", {"F#": 0.9}),        # run without --compare
          (2, 1): ("A:maj", "root-disagree", "D", {"A": 0.9}, 0.4)}  # change inside, relabelled
    d = make_song([2, 2], 2.0, 4, ch, ev)
    S = dict(title="Evidence", artist="Nobody", chords=ch, sections=[("Verse", 1, 4, "verse", "")])
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        doc, cells = build(S, d, "evidence.html")
    C = at(cells, 2)
    q = {k for k, v in C.items() if "q" in v[0].split()}
    check("? from triads + bass where lv-chordia hears N or ran without --compare",
          q == {(1, 1), (1, 2)}, q)
    sp = {k for k, v in C.items() if "split" in v[0].split()}
    check("split mark from lv coverage under half, whatever the status", sp == {(2, 1)}, sp)
    lab = [C[k][2] for k in ((3, 1), (3, 2), (4, 1), (4, 2))]
    check("labels: 6/9 is no slash chord; E♯ and C♭ bass (sans, no span); m7♭5",
          lab == ["C6/9", f'C{ACC("♯")}<span class="bass">(E♯)</span>',
                  f'F{ACC("♯")}m7{ACC("♭")}5', f'G{ACC("♭")}<span class="bass">(C♭)</span>'], lab)
    check("no pickup, no pickup legend", "Coloured words" not in doc)
    check("evidence made on this grid: no warning", err.getvalue() == "", err.getvalue())
    F = json.loads((d / "analysis" / "foundation.json").read_text(encoding="utf-8"))
    F["downbeat_times"] = [t + 1.0 for t in F["downbeat_times"]]     # beat 1 moved half a bar
    (d / "analysis" / "foundation.json").write_text(json.dumps(F), encoding="utf-8")
    with contextlib.redirect_stderr(err):
        build(S, d, "stale.html")
    check("evidence from another grid: warning", "chords_lv.json was made on another grid"
          in err.getvalue() and "chord_proposal.json" in err.getvalue(), err.getvalue())

    # ------------------------------------------------------------ 11/8 as 6+5
    ch = {(b, c): "Am" for b in range(1, 6) for c in (1, 2)}
    d = make_song([6, 5], 2.2, 5, ch, words=[("Cold", 0.1), ("winds", 1.0), ("carry", 1.3),
                                             ("one", 4.5)], pulse_unit=8)
    S = dict(title="Odd", artist="Nobody", words="words.json", chords=ch,
             sections=[("Verse", 1, 5, "verse", "")],
             lyrics={(1, 1): ("Cold winds carry", ""),
                     (3, 1): ("one two three four five six seven eight", "")})
    doc, cells = build(S, d, "odd.html")
    C = at(cells, 2)
    L = {k: lyric(v) for k, v in C.items()}
    check("6+5: 2 cells per bar, bar-end on the 5", len(cells) == 10 and all(
        ("bar-end" in v[0].split()) == (k[1] == 2) for k, v in C.items()), len(cells))
    check("6+5: columns to scale, short row too",
          ".bars{display:grid;grid-template-columns:repeat(4,minmax(0,6fr) minmax(0,5fr));"
          in doc and ".bars.cols-2{grid-template-columns:repeat(1,minmax(0,6fr) minmax(0,5fr));"
                     "max-width:25%}" in doc and doc.count('class="bars cols-2"') == 1)
    check("6+5: split at 6/11 of the bar, not the middle",
          L[(1, 1)] == "Cold winds" and L[(1, 2)] == "carry", (L[(1, 1)], L[(1, 2)]))
    check("6+5: unheard words an eighth (bar / 11) apart",
          L[(3, 1)] == "one two three four five six" and L[(3, 2)] == "seven eight",
          (L[(3, 1)], L[(3, 2)]))
    check("6+5 legend", "Each bar = 2 cells (eighths 1–6 / eighths 7–11, widths to scale)" in doc
          and "this cell's own reading" in doc)
    check("no harmony given: no Harmony column", "<th>Harmony</th>" not in doc)

    # ------------------------------------------------------------ 3/4, one cell per bar
    ch = {(b, 1): "G" for b in range(1, 12)}
    d = make_song([3], 1.5, 10, {k: v for k, v in ch.items() if k[0] <= 10},
                  words=[("Waltz", 1.5), ("along", 2.0), ("the", 2.6), ("river", 3.1),
                         ("bend", 3.8), ("Goodbye", 15.1), ("now", 15.6)])
    S = dict(title="Waltz", artist="Nobody", words="words.json", chords=ch,
             sections=[("Verse", 1, 10, "verse", ""), ("Outro", 11, 11, "outro", "ring out")],
             lyrics={(2, 1): ("Waltz along the river bend", ""), (11, 1): ("Goodbye now", "")})
    doc, cells = build(S, d, "waltz.html")
    C = at(cells, 1)
    L = {k: lyric(v) for k, v in C.items()}
    check("3/4: one cell per bar, every cell ends a bar", len(cells) == 11 and all(
        "bar-end" in v[0].split() for v in C.values()), len(cells))
    check("3/4: 8 bars a row, shorter rows at the same width",
          ".bars{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));" in doc
          and ".bars.cols-2{grid-template-columns:repeat(2,minmax(0,1fr));max-width:25%}" in doc
          and ".bars.cols-1{grid-template-columns:repeat(1,minmax(0,1fr));max-width:12.5%}"
          in doc and doc.count('class="bars cols-2"') == 1
          and doc.count('class="bars cols-1"') == 1)
    check("a section's later rows name it for print only, its first row doesn't",
          doc.count('class="row-name row-sec"') == 1 and '<span class="row-name row-sec">Verse'
          '</span><span class="row-meta">bars 9–10</span>' in doc
          and ".row-sec{display:none}" in doc and " .row-sec{display:inline;" in doc)
    check("1-cell shading", ".half:nth-child(2n+1){background:#fbfbf8}" in doc)
    check("3/4: words by bar", L[(2, 1)] == "Waltz along the" and L[(3, 1)] == "river bend",
          (L[(2, 1)], L[(3, 1)]))
    check("tail bar past the last downbeat (no duration_s)", L[(11, 1)] == "Goodbye now",
          L[(11, 1)])
    check("3/4 legend", "Each bar = 1 cell (beats 1–3); a thick line ends the bar." in doc)
    check("default method text: % of the cells each reader read (the tail bar has none)",
          "Of 11 chord cells, lv-chordia names the chart's root in 100% and the triad reader "
          "in 100% (of the cells each read); cells marked <b>?</b>: 0." in doc)

    # ------------------------------------------------------------ 7/8 as 2+2+3
    ch = {(b, c): "E" for b in range(1, 7) for c in (1, 2, 3)}
    d = make_song([2, 2, 3], 1.75, 6, ch, pulse_unit=8)
    S = dict(title="Seven", artist="Nobody", chords=ch, sections=[("Verse", 1, 6, "verse", "")])
    doc, cells = build(S, d, "seven.html")
    check("3-cell shading, 2 bars a row", len(cells) == 18
          and ".half:nth-child(6n+1),.half:nth-child(6n+2),.half:nth-child(6n+3)"
              "{background:#fbfbf8}" in doc
          and ".bars{display:grid;grid-template-columns:repeat(2,minmax(0,2fr) minmax(0,2fr) "
              "minmax(0,3fr));" in doc)
    doc, _ = build(dict(S, bars_per_row=3), d, "seven3.html")
    check("bars_per_row override", ".bars{display:grid;grid-template-columns:repeat(3,minmax(0,"
          "2fr) minmax(0,2fr) minmax(0,3fr));" in doc and "max-width:33.333%}" in doc
          and "max-width:66.667%}" in doc)
    doc2, _ = build(dict(S, key_short=None, words=None, bars_per_row=None, notes=None), d,
                    "none.html")
    doc, _ = build(S, d, "seven.html")
    check("an optional key set to None counts as left out", doc2 == doc)
    check("2+2+3 legend", "Each bar = 3 cells (eighths 1–2 / eighths 3–4 / eighths 5–7, widths "
          "to scale)" in doc)
    sec = lambda *spans: [(f"S{i}", b0, b1, "verse", "") for i, (b0, b1) in enumerate(spans)]
    for name, bad in (("chord off the grid refused", dict(S, chords={**ch, (7, 1): "E"})),
                      ("old map_harmony refused", dict(S, map_harmony={"Verse1": "E"})),
                      ("section gap refused", dict(S, sections=sec((1, 2), (4, 6)))),
                      ("section overlap refused", dict(S, sections=sec((1, 3), (3, 6)))),
                      ("sections out of order refused", dict(S, sections=sec((4, 6), (1, 3)))),
                      ("section from bar 0 refused", dict(S, sections=sec((0, 6)))),
                      ("chords past the last section refused", dict(S, sections=sec((1, 5)))),
                      ("section without its note refused",
                       dict(S, sections=[("Verse", 1, 6, "verse")])),
                      ("unknown section kind refused",
                       dict(S, sections=[("Pre", 1, 6, "pre", "")])),
                      ("notes as a dict refused", dict(S, notes={"Verse": "<p>x</p>"})),
                      ("lyric not a (text, kind) tuple refused", dict(S, lyrics={(2, 1): "Oh"})),
                      ("chords keyed by bar alone refused", dict(S, chords={1: "E"})),
                      ("a chord that is not text refused", dict(S, chords={**ch, (1, 1): 5})),
                      ("a single brace in method refused", dict(S, method="<p>{see notes}</p>")),
                      ("unknown SONG key refused", dict(S, lyric={(2, 1): ("Oh", "")}))):
        try:
            build(bad, d, "bad.html")
            check(name, False, "rendered")
        except ValueError as e:
            check(name, True, e)
    for name, bad, needle in (       # optional keys: a clear ValueError naming the problem
            ("verified as one bare pair refused", dict(S, verified=(2, 1)), "'verified'"),
            ("verified with a text bar refused", dict(S, verified=[("2", 1)]), "'verified'"),
            ("verified cell off the grid refused", dict(S, verified=[(9, 1)]), "(9, 1)"),
            ("bars_per_row 2.5 refused", dict(S, bars_per_row=2.5), "'bars_per_row'"),
            ("bars_per_row -2 refused", dict(S, bars_per_row=-2), "'bars_per_row'"),
            ("bars_per_row True refused", dict(S, bars_per_row=True), "'bars_per_row'"),
            ("misspelled lyric kind refused", dict(S, lyrics={(2, 1): ("Oh", "pickup")}),
             "'pickup'"),
            ("pickup of an unknown section kind refused",
             dict(S, lyrics={(2, 1): ("Oh", "pk pk-pre")}), "'pk pk-pre'"),
            ("unknown note class refused", dict(S, notes=[("Idea", "<p>x</p>", "opne")]),
             "'opne'"),
            ("bass note that is no note name refused", dict(S, bass_notes={(1, 1): "low A"}),
             "bass_notes"),
            ("title that is no text refused", dict(S, title=7), "'title'"),
            ("duration_s as m:ss refused", dict(S, duration_s="3:20"), "'duration_s'"),
            ("grouping with a 0 refused", dict(S, grouping=[2, 0, 5]), "'grouping'"),
            ("no sections refused", dict(S, sections=[]), "'sections'"),
            ("a fractional bar refused", dict(S, sections=[("Verse", 1, 6.0, "verse", "")]),
             "whole numbers")):
        try:
            build(bad, d, "bad.html")
            check(name, False, "rendered")
        except ValueError as e:
            check(name, needle in str(e), e)

    # ------------------------------------------------------------ CLI
    d = make_song([2, 2], 2.0, 8, CHORDS, EVIDENCE, t0=1.0)
    (d / "gen_v1.py").write_text(
        "SONG = dict(title='Cli Song', artist='Nobody', chords={(1, 1): 'C', (2, 2): 'G'},\n"
        "            sections=[('Verse', 1, 2, 'verse', '')])\n", encoding="utf-8")
    (d / "old.py").write_text("SONG = dict(title='x', artist='y', chords={}, map_harmony={},\n"
                              "            sections=[('Verse', 1, 2, 'verse', '')])\n",
                              encoding="utf-8")
    cwd = Path(tempfile.mkdtemp(prefix="cwd_", dir=TMP))
    run = lambda *args: subprocess.run([sys.executable, str(SCRIPTS / "chart_html.py"), *args],
                                       capture_output=True, text=True, cwd=cwd)
    r = run(str(d / "gen_v1.py"))
    check("CLI: default output next to the data file", r.returncode == 0
          and (d / "Nobody - Cli Song - Chords.html").exists(), r.stderr or r.stdout)
    r = run(str(d / "gen_v1.py"), "--out", "x.html")
    check("CLI: --out", r.returncode == 0 and (cwd / "x.html").exists(), r.stderr)
    check("CLI: no __pycache__ left in the song folder", not (d / "__pycache__").exists())
    r = run(str(d / "old.py"))
    check("CLI: bad data exits 1 with the reason", r.returncode == 1
          and "map_harmony" in r.stderr, r.stderr)
    (d / "slash.py").write_text(
        "SONG = dict(title='Up/Down', artist='Left/Right', chords={(1, 1): 'C'},\n"
        "            sections=[('Verse', 1, 2, 'verse', '')])\n", encoding="utf-8")
    r = run(str(d / "slash.py"))
    check("CLI: a / in artist or title becomes - in the default file name", r.returncode == 0
          and (d / "Left-Right - Up-Down - Chords.html").exists(), r.stderr or r.stdout)
    for name, src, needle in (
            ("verified as JSON-style lists renders", "verified=[[1, 1]]", None),
            ("bars_per_row 2.5: exit 1, the reason, no traceback", "bars_per_row=2.5",
             "bars_per_row"),
            ("a Python error in the data file: exit 1, no traceback", "oops=missing_name",
             "NameError")):
        (d / "opt.py").write_text(
            f"SONG = dict(title='Opt', artist='Nobody', chords={{(1, 1): 'C'}}, {src},\n"
            "            sections=[('Verse', 1, 2, 'verse', '')])\n", encoding="utf-8")
        r = run(str(d / "opt.py"), "--out", "opt.html")
        check(f"CLI: {name}", r.returncode == 0 if needle is None else
              r.returncode == 1 and needle in r.stderr and "Traceback" not in r.stderr,
              r.stderr)
    (d / "analysis" / "bass_per_cell.json").write_text('{"cells": [{"bar": 1}]}',
                                                        encoding="utf-8")
    r = run(str(d / "gen_v1.py"))
    check("CLI: a malformed analysis file: exit 1, no traceback", r.returncode == 1
          and "chart_html: KeyError" in r.stderr and "Traceback" not in r.stderr, r.stderr)
    # ---------------------------------------------------- the push and the band's stops
    ch = {(b, c): ("Cmaj7" if b % 2 else "Em") for b in range(1, 5) for c in (1, 2)}
    d = make_song([2, 2], 2.0, 4, ch, words=[("made", 0.1), ("a", 0.4), ("call", 0.55),
                                             ("to", 1.2), ("my", 1.5), ("other", 1.7),
                                             ("life", 2.3), ("once", 3.4), ("more", 3.7)])
    _, cells = build(dict(title="Push", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")],
                          lyrics={(1, 1): ("made a call to my other life", ""),
                                  (2, 2): ("once more", "")}), d, "push.html")
    P = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    check("a word sung within a dotted eighth of the next cell and held lands in it; one "
          "earlier stays",
          P == {(1, 1): "made a call", (1, 2): "to my", (2, 1): "other life",
                (2, 2): "once", (3, 1): "more"}, P)
    d = make_song([2, 2], 2.0, 4, ch, words=[("so", 3.2), ("I", 3.62), ("stepped", 3.88),
                                             ("outside", 4.3)])
    _, cells = build(dict(title="Push", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")],
                          lyrics={(2, 2): ("so I stepped outside", "")}), d, "pickup.html")
    P = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    check("a quick pickup into a pushed word stays: 'so I' | 'stepped outside'",
          P == {(2, 2): "so I", (3, 1): "stepped outside"}, P)
    d = make_song([2, 2], 2.0, 4, ch, words=[("and", 3.4), ("this", 3.6), ("double", 4.3),
                                             ("life", 4.6), ("tonight", 5.1)])
    lyr = {(3, 1): ("and this double life tonight", "")}
    _, cells = build(dict(title="Sung", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")], lyrics=lyr), d, "sung.html")
    P = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    _, cells = build(dict(title="Sung", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")], lyrics=lyr,
                          placement="anchor"), d, "anchored.html")
    A = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    d = make_song([2, 2], 2.0, 4, ch, words=[("coming", 2.2), ("snow", 2.6), ("jesus", 3.3),
                                             ("baby", 4.6)])
    _, cells = build(dict(title="Heard", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")],
                          lyrics={(2, 2): ("slow jazz is playing", "")}), d, "misheard.html")
    M = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    check("a misheard line is placed by its stand-ins in order, onset letter first: "
          "'snow jesus baby' times 'slow jazz is playing'",
          M == {(2, 2): "slow jazz is", (3, 1): "playing"}, M)
    d = make_song([2, 2], 2.0, 4, ch, words=[("lights", 2.2), ("are", 2.45), ("fluorescent", 3.4),
                                             ("and", 4.4)])
    _, cells = build(dict(title="Long", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")],
                          lyrics={(2, 1): ("lights are fluorescent and", "")}), d, "long.html")
    Lg = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    check("a long word reaches its stress later: 'fluorescent' 1.2 beats early still lands "
          "on the next bar (half a beat more push per syllable past the second)",
          Lg == {(2, 1): "lights are", (3, 1): "fluorescent and"}, Lg)
    d = make_song([2, 2], 2.0, 4, ch, words=[("night", 2.2), ("we", 3.45), ("coming", 4.4),
                                             ("and", 5.3), ("this", 5.5), ("life", 6.1)])
    _, cells = build(dict(title="Pick", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")],
                          lyrics={(2, 1): ("night", ""), (3, 1): ("we coming", ""),
                                  (4, 1): ("and this life", "")}), d, "linepickup.html")
    Pk = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    check("a line's first word on the last beat joins its line on the next bar; one sung "
          "earlier (beat 3) stays in its half",
          Pk == {(2, 1): "night", (3, 1): "we coming", (3, 2): "and this", (4, 1): "life"}, Pk)
    d = make_song([2, 2], 2.0, 4, ch, words=[("so", 1.0), ("I", 1.3)])
    _, cells = build(dict(title="Fix", artist="Nobody", words="words.json", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")],
                          lyrics={(1, 1): ("so I", ""), (1, 2): ("night", "fixed")}), d, "fixed.html")
    Fx = {k: re.sub("<[^>]+>", "", v[4]) for k, v in at(cells, 2).items() if v[4]}
    check("'fixed': a player's placement stays whole at its cell, whatever the timing",
          Fx == {(1, 1): "so I", (1, 2): "night"}, Fx)
    check("placement 'sung' (default): opening words stay where sung, before the anchor; "
          "'anchor' pulls them in",
          P == {(2, 2): "and this", (3, 1): "double life", (3, 2): "tonight"} and
          A == {(3, 1): "and this double life", (3, 2): "tonight"}, (P, A))
    ch = {(b, c): ("N.C." if b == 4 else "Am") for b in range(1, 5) for c in (1, 2)}
    d = make_song([2, 2], 2.0, 4, ch)
    (d / "analysis" / "band_level.json").write_text(json.dumps(
        {"grouping": [2, 2], "cells": [[1, 1, 1.0], [1, 2, 0.05], [2, 1, 0.9], [2, 2, 0.3],
                                       [3, 1, 1.1], [3, 2, 1.0], [4, 1, 0.0], [4, 2, 0.0]]}))
    doc, cells = build(dict(title="Stops", artist="Nobody", chords=ch,
                            sections=[("Verse", 1, 4, "verse", "")]), d, "stops.html")
    C = at(cells, 2)
    check("a bar where the band drops under 0.15 of its median is greyed whole (a stop bar); "
          "a quiet 0.3 and N.C. bars are not",
          [k for k, v in C.items() if "stop" in v[0].split()] == [(1, 1), (1, 2)] and
          "Grey chords" in doc, [k for k, v in C.items() if "stop" in v[0].split()])
    doc, _ = build(dict(title="Stops", artist="Nobody", chords=ch,
                        sections=[("Verse", 1, 4, "verse", "")]), make_song([2, 2], 2.0, 4, ch),
                   "nostops.html")
    ev = {(1, 2): ("C:maj", "root-disagree", "C", None), (3, 2): ("C:maj", "root-disagree", "C", None)}
    d = make_song([2, 2], 2.0, 4, ch, evidence=ev)
    (d / "analysis" / "band_level.json").write_text(json.dumps(
        {"grouping": [2, 2], "cells": [[b, k, 0.05 if b == 1 else 1.0] for b in (1, 2, 3, 4)
                                       for k in (1, 2)]}))
    _, cells = build(dict(title="Stops", artist="Nobody", chords=ch,
                          sections=[("Verse", 1, 4, "verse", "")]), d, "stopq.html")
    C = at(cells, 2)
    check("no '?' in a stop bar (nothing to read: the chart keeps the loop); elsewhere it stays",
          "q" not in C[(1, 2)][0].split() and "q" in C[(3, 2)][0].split(),
          (C[(1, 2)][0], C[(3, 2)][0]))
    check("no band_level.json: no stops, no legend line", "Grey chord" not in doc and
          'class="half stop' not in doc)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
