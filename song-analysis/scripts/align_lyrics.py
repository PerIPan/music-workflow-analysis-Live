#!/usr/bin/env python3
"""Phase 6: align the canonical lyrics to Whisper's words -> line timings and sections.

Whisper's own text is not the lyrics: it drops lines (worse on repeated or sparse
singing), mishears words and splits phrases differently. This keeps the canonical
text and borrows only the TIMES: a monotonic sequence alignment (Needleman-Wunsch)
with fuzzy word matching pairs canonical words with Whisper words; unmatched
canonical words - Whisper deletions are normal - get times interpolated between
their matched neighbours. Repeated lines (mantras, choruses) stay; run this before
any "drop repeated words" clean-up.

Canonical text: one lyric line per line; a blank line starts a new section; an
optional "[Chorus]"-style line labels the section that follows.

Several --words files (e.g. Whisper on the vocal stem and on the mix) are all aligned
and the one matching the most canonical words is kept - on six benchmark songs that
picked the lower-WER transcription every time the two differed.

Usage (any Python 3.8+; stdlib only):
    align_lyrics.py --lyrics lyrics.txt --words analysis/lyrics.json [--words mix.json] \
        [--foundation analysis/foundation.json] [--out analysis/lyrics_aligned.json] \
        [--sections analysis/sections.json]
"""
import argparse, bisect, difflib, json, re, sys, unicodedata

GAP = -1.0
MATCH_MIN = 0.7          # token similarity needed to count as the same word


def norm(tok):
    """Lowercase, strip accents (NFD) and punctuation; Greek final sigma -> sigma."""
    t = unicodedata.normalize("NFD", tok.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch)).replace("ς", "σ")
    return re.sub(r"[^\w']", "", t)


def script_of(tokens):
    greek = sum(any("Ͱ" <= ch <= "Ͽ" for ch in t) for t in tokens)
    return "greek" if greek > len(tokens) / 2 else "latin"


def parse_lyrics(text):
    """-> lines [{text, section, words:[norm tokens]}], sections [{label, first_line}]."""
    lines, sections, label, new_sec = [], [], None, True
    for raw in text.splitlines():
        s = raw.strip()
        if not s:
            new_sec = True
            continue
        m = re.fullmatch(r"\[(.+)\]", s)
        if m:
            label, new_sec = m.group(1), True
            continue
        if new_sec:
            sections.append(dict(label=label or f"S{len(sections) + 1}", first_line=len(lines)))
            label, new_sec = None, False
        toks = [norm(w) for w in s.split()]
        lines.append(dict(text=s, section=len(sections) - 1, words=[t for t in toks if t]))
    return lines, sections


def align(ref, hyp):
    """Needleman-Wunsch over token lists; returns {ref_index: hyp_index} for matches."""
    cache = {}
    def sim(a, b):
        k = (a, b)
        if k not in cache:
            cache[k] = 1.0 if a == b else difflib.SequenceMatcher(None, a, b).ratio()
        return cache[k]
    n, m = len(ref), len(hyp)
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    P = [[0] * (m + 1) for _ in range(n + 1)]          # 0 diag, 1 up (skip ref), 2 left
    for i in range(1, n + 1):
        S[i][0], P[i][0] = S[i - 1][0] + GAP, 1
    for j in range(1, m + 1):
        S[0][j], P[0][j] = S[0][j - 1] + GAP, 2
    for i in range(1, n + 1):
        ri, Si, Sp = ref[i - 1], S[i], S[i - 1]
        for j in range(1, m + 1):
            s = sim(ri, hyp[j - 1])
            diag = Sp[j - 1] + (2 * s if s >= MATCH_MIN else -1.0)
            up, left = Sp[j] + GAP, Si[j - 1] + GAP
            # ties go to "skip the canonical word": traced back from the end, that lands
            # matches on the EARLIEST repeat of a repeated line, so a section's first
            # line is anchored, not interpolated, when Whisper drops later repeats
            if up >= diag and up >= left:
                Si[j], P[i][j] = up, 1
            elif diag >= left:
                Si[j], P[i][j] = diag, 0
            else:
                Si[j], P[i][j] = left, 2
    pairs, i, j = {}, n, m
    while i > 0 and j > 0:
        if P[i][j] == 0:
            if sim(ref[i - 1], hyp[j - 1]) >= MATCH_MIN:
                pairs[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif P[i][j] == 1:
            i -= 1
        else:
            j -= 1
    return pairs


def locate(t, downbeats, grouping):
    """(bar, cell) for time t on the song's own grid; None outside it."""
    i = bisect.bisect_right(downbeats, t) - 1
    if i < 0 or i >= len(downbeats) - 1:
        return None
    frac = (t - downbeats[i]) / (downbeats[i + 1] - downbeats[i]) * sum(grouping)
    edge, cell = 0, 0
    for k, g in enumerate(grouping):
        if frac >= edge:
            cell = k
        edge += g
    return [i + 1, cell + 1]


def sung_not_in_text(lines, ref_tokens, pairs, hyp, gap=1.5):
    """{line index: [words]} - Whisper words just before a line's first matched word (within
    gap s, after the previous line's last match) that no canonical word took: words the
    singer sings that the lyrics page left out (a lyrics site wrote "Coming back for you",
    the singer sang "I'm coming back for you")."""
    used = set(pairs.values())
    out, k, prev_last = {}, 0, -1
    for li, l in enumerate(lines):
        idx = range(k, k + len(l["words"]))
        k += len(l["words"])
        hits = [pairs[i] for i in idx if i in pairs]
        if not hits:
            continue
        first = min(hits)
        extra = [hyp[j]["word"].strip() for j in range(max(prev_last + 1, 0), first)
                 if j not in used and hyp[first]["start"] - hyp[j]["start"] <= gap]
        if extra:
            out[li] = extra
        prev_last = max(hits)
    return out


VOCABLES = {"oh", "ohh", "ohhh", "ooh", "oooh", "ah", "ahh", "aah", "yeah", "hey", "mm", "mmm",
            "whoa", "woah", "uh", "na", "la", "ha", "ay", "eh"}


def sung_after(lines, pairs, hyp, before, gap=1.5):
    """{line index: [words]} - Whisper words just after a line's last matched word (within
    gap s, before the next line's first match) that no lyric word took and that the next
    line doesn't claim (sung_not_in_text): the "oh" after "...up all night" that a lyrics
    page leaves out."""
    used = set(pairs.values())
    spans, k = [], 0
    for l in lines:
        hits = [pairs[i] for i in range(k, k + len(l["words"])) if i in pairs]
        spans.append((min(hits), max(hits)) if hits else None)
        k += len(l["words"])
    claimed = {w for ws in before.values() for w in ws}
    out = {}
    for li, sp in enumerate(spans):
        if not sp:
            continue
        nxt = next((s[0] for s in spans[li + 1:] if s), len(hyp))
        ws = [hyp[j]["word"].strip() for j in range(sp[1] + 1, nxt)
              if j not in used and hyp[j]["start"] - hyp[sp[1]]["start"] <= gap
              and norm(hyp[j]["word"]) in VOCABLES      # held sounds; other extras are
                                                        # usually a misheard next line
              and not (li + 1 in before and hyp[j]["word"].strip() in before[li + 1])]
        if ws:
            out[li] = ws
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--lyrics", required=True, help="canonical lyrics text")
    ap.add_argument("--words", required=True, action="append",
                    help="whisper_gated.py output; repeat to keep the best-matching one")
    ap.add_argument("--foundation", help="adds (bar, cell) to lines and sections")
    ap.add_argument("--out", default="analysis/lyrics_aligned.json")
    ap.add_argument("--sections", default="analysis/sections.json")
    a = ap.parse_args()

    lines, sections = parse_lyrics(open(a.lyrics, encoding="utf-8").read())
    ref_tokens = [(li, t) for li, l in enumerate(lines) for t in l["words"]]
    best = None
    for path in a.words:
        hyp = [w for w in json.load(open(path))["words"] if norm(w["word"])]
        if script_of([t for _, t in ref_tokens]) != script_of([norm(w["word"]) for w in hyp]):
            print(f"WARNING: {path}: the canonical lyrics and Whisper's words are in different "
                  f"scripts (e.g. Greeklish vs Greek) - transliterate one side.")
        pairs = align([t for _, t in ref_tokens], [norm(w["word"]) for w in hyp])
        if len(a.words) > 1:
            print(f"  {path}: {len(pairs)}/{len(ref_tokens)} canonical words matched")
        if best is None or len(pairs) > len(best[1]):
            best = (hyp, pairs, path)
    hyp, pairs, source = best
    if len(a.words) > 1:
        print(f"  keeping {source}")

    # times for every canonical word: matched, else interpolated between matched anchors
    anchors = sorted(pairs.items())
    starts, ends, how = [], [], []
    for k in range(len(ref_tokens)):
        if k in pairs:
            w = hyp[pairs[k]]
            starts.append(w["start"]); ends.append(w["end"]); how.append("matched")
            continue
        prev = max((x for x in anchors if x[0] < k), default=None)
        nxt = min((x for x in anchors if x[0] > k), default=None)
        if prev and nxt:
            t0, t1 = hyp[prev[1]]["end"], hyp[nxt[1]]["start"]
            f = (k - prev[0]) / (nxt[0] - prev[0])
            starts.append(t0 + f * (t1 - t0)); ends.append(starts[-1]); how.append("interpolated")
        else:
            starts.append(None); ends.append(None); how.append("unplaced")

    F = json.load(open(a.foundation)) if a.foundation else None
    where = ((lambda t: locate(t, F["downbeat_times"], F["grouping"])) if F
             else (lambda t: None))
    out_lines, k = [], 0
    for li, l in enumerate(lines):
        n = len(l["words"])
        idx = range(k, k + n); k += n
        matched = sum(how[i] == "matched" for i in idx)
        st = next((starts[i] for i in idx if starts[i] is not None), None)
        en = next((ends[i] for i in reversed(idx) if ends[i] is not None), None)
        out_lines.append(dict(text=l["text"], section=l["section"], start=st, end=en,
                              matched=round(matched / max(n, 1), 2),
                              where=where(st) if st is not None else None))
    extra = sung_not_in_text(lines, ref_tokens, pairs, hyp)
    for li, ws in extra.items():
        out_lines[li]["sung_before"] = ws
    after = sung_after(lines, pairs, hyp, extra)
    for li, ws in after.items():
        out_lines[li]["sung_after"] = ws
    secs = []
    for s in sections:
        first = out_lines[s["first_line"]]
        secs.append(dict(label=s["label"], first_line=first["text"], t=first["start"],
                         where=first["where"]))
    weak = [l for l in out_lines if l["matched"] < 0.3]
    json.dump(dict(lines=out_lines, source=source,
                   words_matched=round(len(pairs) / max(len(ref_tokens), 1), 2)),
              open(a.out, "w"), indent=1, ensure_ascii=False)
    json.dump(dict(sections=[s for s in secs if s["t"] is not None]), open(a.sections, "w"),
              indent=1, ensure_ascii=False)
    print(f"{len(lines)} lines, {len(sections)} sections; {len(pairs)}/{len(ref_tokens)} "
          f"canonical words matched ({len(pairs) / max(len(ref_tokens), 1):.0%}); "
          f"{len(weak)} lines under 30% matched (timing interpolated - check by ear)")
    for li, ws in sorted(after.items()):
        print(f"SUNG, NOT IN THE TEXT: after line {li + 1} - Whisper heard {' '.join(ws)!r} "
              f"right after it (a held 'oh'?); if sung, add it as its own line (CHECK BY EAR)")
    for li, ws in sorted(extra.items()):
        print(f"SUNG, NOT IN THE TEXT: line {li + 1} - Whisper heard {' '.join(ws)!r} just "
              f"before it; if the singer sings it, add it to lyrics.txt (CHECK BY EAR)")
    for s in secs:
        print(f"  {s['label']:10s} {s['t'] if s['t'] is None else round(s['t'], 2)}s "
              f"{'' if not s['where'] else 'bar %d cell %d' % tuple(s['where'])}  {s['first_line'][:40]}")


if __name__ == "__main__":
    main()
