# Chart structure, lyric placement, and HTML output

Read this when producing the chord+lyric chart (Phase 8 of the song-analysis skill).

## Chart structure

### One row per section

Every section starts a new row. Within a section, `chart_html.py` starts a new row every
`bars_per_row` bars (see Row width). Pair-symmetric sections (Chorus 1 / Chorus 2)
**must use the same row split** for visual readability.

### Bar numbering

**Chart bar = audio bar.** Do not insert "virtual" bars to make the chart breathe. If a
section ends with a sustained chord, use the natural audio bar where it sustains. This
keeps the chart trivially mappable back to audio for re-checking. The renderer draws only
the audio's bars, plus the bar that starts at the last downbeat (a final chord ringing
out). A hold the beat tracker skipped goes in the row note (e.g. "fermata after bar 32"),
not in an extra bar.

### Cells per bar

One cell per metric group of the bar — the `grouping` in `foundation.json`. In 4/4 that is
two half-bars (beats 1–2 and 3–4); an 11/8 bar split 6+5 has two unequal cells; a 3/4
bar has one. The half-cell wording below is the 4/4 case. Each cell shows:
- **Chord** (large) — guitar/piano shape
- **(bass note)** in small blue parens — only if bass differs from chord root (slash-chord notation)
- **Lyric** (small italic) — words sung in this cell

Key the chord dict by `(bar, cell)` so chords can change mid-bar (which they often do —
see "Bass walks" below).

### Row width

A full row holds as many whole bars as fit in 8 cells (`bars_per_row`, default
`max(1, 8 // cells per bar)`: 4 bars of 4/4, 8 of 3/4, 2 of a three-cell bar). A shorter
last row keeps the same cell width instead of stretching, and unequal groups get
proportional columns (6+5 → 6:5). Columns keep that share whatever the labels: a label too
wide for its cell (a phone, print, a long `C♯m7♭5/G♯` in a 5-eighth cell) shrinks to fit,
keeping clear of the "?" mark, instead of widening its column and pushing the bar lines.
A slash chord's bass note shrinks with its chord only down to .6rem (then to three
quarters of the chord's size in a very narrow cell), so it stays readable. Sharps and
flats are set in a symbol font, since Georgia has no ♭ (`B♭`, not `B ♭`). Without Georgia
the chord falls back to Georgia-metric Gelasio or to Times-metric serifs, which are
narrower; a wider default serif (DejaVu Serif, up to 17% wider) would clip a label's end.
On a phone, lyric words wrap inside their cell; only a word of 10+ letters is hyphenated,
with 5+ letters either side, so a hyphen never looks like a syllable split.

## Lyric placement rules

Vocalists anticipate beats — pickup syllables come early, resolutions land late. Raw
Whisper word-onset timing produces awkward, visually misleading placements.

You choose each line's anchor (Rule 1) and the pickups (Rule 4) in the data file;
`chart_html.py` does the rest: it splits each line over the cells where Whisper heard its
words, keeps them in sung order, pulls early syllables into the anchor and never lets a
line reach the next line's anchor or leave its section (Rules 3 and 5); a pickup or an
ad-lib shares its cell with the line's words. A line looks up to 2.5 s back for early
syllables, but never at words an earlier sung line matched, so a repeated line (the same
words twice in a row) splits where it is sung instead of taking the first one's times. Nor
does it take words the next sung line needs when they start nearer that line's anchor
(Whisper often hears a repeat once): the line then counts as unheard and the next keeps
its words.
Words Whisper missed are interpolated between heard ones, and set a beat apart after the
last heard word.

### Rule 1 (the big one): Anchor at the chord that resolves the phrase

**Each lyric phrase visually lives in the cell of the chord it resolves INTO**, not where
the pickup syllable was sung. Pickup syllables are absorbed. Bands read cell-to-chord — a
pickup syllable visually attached to the wrong chord causes them to play that chord with
the wrong feel.

```
Sung:    [A♭ bar...] "Pickup words here,"|[E♭ bar] "and the phrase"  [A♭ bar] "ends"
Chart:   [A♭]                              |[E♭]    "Pickup words here, / and the phrase"  [A♭] "ends"
                                            ^ phrase anchored at the E♭ change
```

Apply per line: identify the chord the line *resolves on* (usually a chord change near the
phrase end) and anchor the line at that chord's cell; the renderer pulls earlier-sung
words into it.

### Rule 2: Empty cells = sustain or rest

A cell with no lyric means the previous chord/lyric sustains, or it's an instrumental
rest. Don't fill empty cells with filler — the band reads emptiness as "hold". Common
patterns:

- Phrase ends mid-bar → next half-cell empty until the next phrase's resolution chord
- Section closes with a sustained chord → trailing cells of that bar empty
- 1–2 beats of silence between phrases → that half-cell empty

### Rule 3: Words go where they're sung, in order

After the anchor, each word lands in the cell where Whisper heard it; a word never lands
left of the one before it, so a phrase sung late pushes its tail right.

### Rule 4: Section-pickup overlay

When a phrase from the *next* section is sung inside the *current* section's last filled
cell, render it as a colored overlay in the same cell (e.g. the bridge's last A♭ box
contains both the bridge's closing words and the chorus link's pickup words). Don't
displace the current section's lyric; co-habit. In the data file:
`(40, 2): ('Hey now', 'pk pk-chorus')` — the kind names the next section's kind, which
sets the colour.

### Rule 5: No spill into the next line or section

No word of a line goes past the next line's anchor or out of the line's section, so a
section's last line never spills into the next section (an instrumental break stays
empty). A word that would spill stops in the cell before, in sung order.

## Iteration with the player (band perspective)

Patterns that recur across songs:

- **"Anchor at the chord, not the syllable."** Pickups are visual artifacts; the chart's
  job is to show *where to play the chord change*. Rule 1.
- **"Chord and lyric must live on the same row."** Row breaks fall every `bars_per_row`
  bars from the section start; if a phrase straddles one, change `bars_per_row` or start a
  section there. If the chorus's opening line lives on the chorus row, the chorus's E♭→F
  lift must live there too — even if it's the section's first bar.
- **"Verses with `(2-chord bar | 1-chord bar)` pairs."** Many songs use
  antecedent-consequent verse patterns: the first bar walks two chords (e.g. `i → ♭VI`)
  and the second bar answers with one sustained chord. Once you spot the pattern,
  sight-reading the section gets dramatically easier — note it in the chart header.
- **"Mirror parallel sections visually."** The renderer breaks every section every
  `bars_per_row` bars from its first bar, so parallel sections of equal length get the same
  row split — keep their bar ranges the same length, even when the lyric distribution
  differs. The band's eye expects symmetry.
- **"Bass walks: one chord or two — look above the bass."** When bass moves `C → A♭`
  across a bar's cells, it is *two chords* (Cm → A♭) if the upper voicing re-attacks or
  its pitch-class set changes, and *one chord over a moving bass* (Cm/A♭, or a drone) if
  the voicing holds. Both happen; the test is Trap 1 in the skill. Key the chord dict by
  `(bar, cell)`, not by `bar`, so either reading fits.
- **"Bass annotation only when it differs from chord root."** No redundant `(C)` under a
  `Cm` chord. Slash chord notation (`G/B` rendered as `G (B)`) is what bands actually read.
- **"Bass enters at bar X — suppress before."** Most songs have an instrumental setup of
  1–8 bars before bass enters. Stem separation picks up bleed in those bars; suppress
  annotations before the documented bass-entry bar.
- **"Chart bar = audio bar."** Never insert a bar; a hold the beat tracker skipped goes in
  the row note.

A correction is a data-file edit — the chord dict, the sections, the lyric anchors — and a
re-render: the renderer redoes the rows and the lyric cascade. Re-render and look.

## Showing uncertainty

A chart that looks equally sure everywhere hides the ~30% of automated calls that are
wrong on modal-mixture songs — and wastes the player's verification pass. Carry the
evidence through:

- **Header line:** meter, grouping, key/mode and where each came from — e.g.
  "11/8 as 6+5 (sweep HIGH; beat 1 chosen by the player) · E Lydian (bass pedal + ♯4 in
  32/32 bars)". Read it from `foundation.json` → `provenance` and `mode.json`.
  Audio fetched by `fetch_audio.py` adds its source from `source.json` (`url`,
  `label_upload` or `channel`, `fetched_at`, `format`, `wav`) — e.g. "Audio: the label's
  upload on YouTube (youtube.com/watch?v=…), fetched 2026-09-30; opus 131 kbps → 48 kHz WAV".
- **Cells:** `chart_html.py` gives a chord cell a dotted outline and a small "?" when its
  own evidence names another root: lv-chordia (the primary reader) names a different
  root, or the triad reader does *and* the bass contradicts the chart — the pitch class
  the bass sounds longest in the cell (`bass_per_cell.json`, 0.15 s or more) is neither
  the chart's root nor its slash bass. A cell whose lv-chordia chord covers under half of
  it (`coverage` below 0.5: a chord change falls inside it) gets a dashed underline. The
  page's legend explains both.
- **Not marked:** `near-tie` cells and triad-only objections (the bass backs the chart).
  On real songs they marked 20–50% of cells, mostly sus/add9 voicings a triad template
  can't name — a chart that questions every other cell sends the player nowhere. They stay
  in `chords_lv.json` for a closer look.
- **After the player's pass,** list the confirmed cells in the data file's `verified` as
  `(bar, cell)` pairs (`[[9, 1], [12, 2]]` works too; their "?" and dashed underline go)
  and say who checked in the provenance line — the chart then shows what a musician
  checked, not just what software guessed.

## HTML output — `scripts/chart_html.py`

The chart is rendered, not hand-written. A per-song data file (`gen_v<N>.py` in the song
folder, a new N per revision) holds the decisions as a `SONG` dict; the renderer reads
everything measured from `analysis/`:

```bash
python3 scripts/chart_html.py gen_v1.py         # → <artist> - <title> - Chords.html beside it
python3 scripts/chart_html.py gen_v1.py --out <shared folder>/<name>.html
```

**The data file** is Python that defines `SONG`. `title`, `artist`, `sections` and
`chords` are required; every key is in the script's docstring, and an unknown key or a
wrong shape, type or lyric kind is refused with the reason. A minimal example (an
invented song):

```python
SONG = dict(
    title='Paper Lanterns', artist='Nobody', key_short='A minor',
    words='lyrics_mix.json',                                     # a file in analysis/
    sections=[('Intro', 1, 2, 'intro', ''),                      # (name, first bar, last bar,
              ('Verse', 3, 6, 'verse', 'first verse', 'i → ♭VI'),  #  kind, note html[, harmony])
              ('Chorus', 7, 9, 'chorus', 'last chord rings')],
    chords={(1, 1): 'Am', (1, 2): 'Am', (2, 1): 'F', (2, 2): 'F'},   # ... one per cell
    lyrics={(4, 1): ('Salt on the ferry rail', ''),              # {(bar, cell): (text, kind)}
            (6, 2): ('Oh oh', 'pk pk-chorus')},
    facts=[('Tempo · Meter', '120 BPM · 4/4'), ('Key', 'A minor')],   # [(label, value html)]
    provenance='<b>Meter</b> 4/4 (sweep HIGH; beat 1 chosen by the analyst) · ...',
    notes=[('Verse', '<p><code>i → ♭VI</code></p>'),              # [(title, body html[, 'open'])]
           ('Open questions for a player', '<ol><li>Bar 5: C or Am/C?</li></ol>', 'open')],
)
```

- `sections`: cover every bar from 1, in order, with no gap or overlap. Kinds: intro,
  verse, post (post-chorus; a pre-chorus uses it too), chorus, bridge, inst, outro. The
  last section may include the bar that starts at the last downbeat (a final chord ringing
  out; set `duration_s` to the audio length).
- `chords`: a lead-sheet symbol in every cell, repeated while it holds (`'Am7'`, `'E/G#'`
  prints E (G♯), `'N.C.'` a rest). Never `chords_lv.json`'s Harte labels (`'A:min7'`,
  `'E:maj/3'`, `'N'`): they are refused.
- `lyrics`: seed from `analysis/lyrics_aligned.json` (each line's `text` at its `where`),
  then move each anchor per Rule 1 and mark the pickups (`'pk pk-<next section's kind>'`)
  and ad-libs (`'adlib'`: whole in its cell, greyed).
- `words`: the transcription `align_lyrics.py` kept — `lyrics_aligned.json`'s `source`
  without `analysis/`.
- `provenance`: the header line described in Showing uncertainty.
- `method`: run through `str.format` with `{cells}`, `{lv_pct}`, `{tri_pct}` and `{n_q}`;
  write literal braces as `{{ }}`.

Required inputs: `foundation.json`, `chords_lv.json`, `chord_proposal.json` and
`bass_per_cell.json` (evidence made on another grid is warned about: re-run it). Optional:
the words file (without one, lines stay whole at their anchor) and `stem_activity.json`
(`scripts/stem_activity.py`: each stem's level per bar, 1.0 = its usual full level).

**The page** is one self-contained file (inline CSS, no external assets): it opens on any
device and can sit in any shared folder. It prints to A4 (`@media print` tightens fonts
and padding): about 11 rows (44 bars of 4/4) of chart per page, then the song map and the
commentary — a 100-bar song takes 4 pages. A row that is not its section's first repeats
the section name in print only, so a page that starts mid-section says where it is (row
heads print darker than on screen: Safari prints the pale greys near-invisible); the
commentary heading stays with its notes; the song map's level meters and the bar shading
print even with the browser's background graphics off. Print with the browser's headers
and footers off (they add the date and the file path). In order:
- title and key; header facts (tempo, meter, key/mode, length); the provenance line;
- the chart — per section its name, bar range and note, then rows of cells (chord large,
  bass note in blue parens, lyric small italic), alternate bars shaded, a thick line at
  each bar's end, "?" marks and dashed underlines;
- the song map — section, bars, start time, harmony, average vocal/bass/drums/keys level;
- the commentary — harmonic notes in scale-degree terms (`i → ♭VI → iv`, `♭III rising
  into IV`), which bands read once and internalise; arrangement and groove notes; the open
  questions for the player; then "Method & confidence" and a legend for reading the cells.
