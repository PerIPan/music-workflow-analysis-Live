#!/usr/bin/env python3
"""Test scripts/fetch_audio.py offline: ranking, rejects, names, file names, JS runtime lookup,
records, and search and download mode against a stand-in for yt-dlp.

Candidates are plain dicts shaped like yt-dlp's search entries, for invented artists and
songs; runtimes and ffmpeg are fake executables in temp folders; the stand-in yt_dlp module
serves invented results and 'downloads' a short WAV; nothing touches the network. The label
upload must beat an official video and a lyric re-upload; each reject family must reject, but
never for a word or an '@' of the song's own title or artist ("Live Wire", the band Live),
with one name given or both; a transliterated title still names the song; a matching length
beats views, and without one the median length of the named candidates decides. The printed
command must parse ('-M-') and carry an absolute song folder; download mode must refuse a live
stream and a WAV or another WAV's source.json in the way, keep the song folder out of yt-dlp's
output template, and report a failed download or search.
Run: python3 tests/test_fetch_audio.py
"""
import contextlib, io, itertools, json, os, shlex, subprocess, sys, tempfile, types, wave
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fetch_audio as fa  # noqa: E402

IDS = itertools.count(1)
ART, SONG = "Nova Tide", "Glass Harbour"
WATCH = "https://www.youtube.com/watch?v="


def entry(title, channel="Harbour Uploads", duration=201, views=1000, **kw):
    """A candidate as the flat YouTube search gives it (music results add music_rank etc.)."""
    return dict(id=f"vid{next(IDS):08d}", title=title, channel=channel, duration=duration,
                view_count=views, **kw)


def top(ranked):
    c = fa.pick(ranked)
    return c and c["title"]


def write_wav(path, seconds=1.5, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\0\0" * 2 * int(rate * seconds))


def fake_ytdlp(music=(), videos=(), watch=None, music_fails=False, disk_full=False):
    """A stand-in for the yt_dlp module. music: YouTube Music songs (full metadata, resolved by
    URL); videos: flat YouTube search results; watch: what any other URL resolves to. The
    download writes a short WAV where the output template points, reading '%%' as '%' as
    yt-dlp does; disk_full: it fails the way yt-dlp reports an OSError (not a DownloadError)."""
    class YoutubeDLError(Exception):
        pass

    class DownloadError(YoutubeDLError):
        pass

    class UnavailableVideoError(YoutubeDLError):
        pass

    templates = []

    class YoutubeDL:
        def __init__(self, params):
            self.params = params

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False, process=True):
            if "music.youtube.com" in url:
                if music_fails:
                    raise DownloadError("ERROR: music search unavailable")
                return dict(entries=[dict(id=m["id"], url=WATCH + m["id"]) for m in music])
            if url.startswith("ytsearch"):
                return dict(entries=[dict(v) for v in videos])
            vid = url.rsplit("=", 1)[-1]
            return dict(next((m for m in music if m["id"] == vid), None) or watch)

        def process_ie_result(self, info, download=True):
            tmpl = self.params["outtmpl"]["default"]
            templates.append(tmpl)
            if disk_full:
                raise UnavailableVideoError("Unable to download video: [Errno 28] No space left")
            path = Path(tmpl.replace("%(ext)s", "webm").replace("%%", "%"))
            path.parent.mkdir(parents=True, exist_ok=True)
            write_wav(path)
            return dict(info, requested_downloads=[dict(filepath=str(path))])

    return types.SimpleNamespace(
        YoutubeDL=YoutubeDL, templates=templates, version=types.SimpleNamespace(__version__="t"),
        utils=types.SimpleNamespace(YoutubeDLError=YoutubeDLError, DownloadError=DownloadError,
                                    UnavailableVideoError=UnavailableVideoError))


def quiet(fn, *args):
    """fn(*args) with stdout and stderr captured: (result or exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            result = fn(*args)
        except SystemExit as e:
            result = e.code
    return result, out.getvalue(), err.getvalue()


def main():
    fails = 0

    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"  [{info}]"))

    # ------------------------------------------------------------ label audio first
    video = entry(f"{ART} - {SONG} (Official Video)", ART, 214, 3_000_000, channel_is_verified=True)
    lyric = entry(f"{ART} - {SONG} (Lyrics)", "Lyric Lagoon", 201, 900_000)
    music = entry(SONG, ART, 201, 40_000, music_rank=1, artists=[ART], track=SONG,
                  channel_is_verified=True)
    topic = entry(SONG, f"{ART} - Topic", 201, 5_000)
    provided = entry(SONG, ART, 201, 5_000,       # a label upload on the artist's merged channel
                     description=f"Provided to YouTube by Tidal Records {SONG} · {ART} ℗ 2026")
    for label, cand in (("YouTube Music song", music), ("' - Topic' channel", topic),
                        ("'Provided to YouTube by'", provided)):
        for args, how in (((ART, SONG, None), "artist+title"), ((ART, SONG, 201.4), "+duration"),
                          ((None, None, None, f"{ART} {SONG}"), "query only")):
            R = fa.rank([video, lyric, cand], *args)
            check(f"{label} beats official video + lyric re-upload ({how})",
                  top(R) == SONG and R[0]["id"] == cand["id"], [(c["title"], c["score"]) for c in R])
    R = fa.rank([video, lyric, music], ART, SONG)
    check("reasons name the label and the lyric minus",
          "label audio (YouTube Music #1)" in R[0]["reasons"]
          and "lyric video" in next(c for c in R if c["id"] == lyric["id"])["reasons"])
    check("inputs are not modified", "score" not in music and "rank" not in video)
    first = entry(SONG, f"{ART} - Topic", 201, 3_000, music_rank=1, artists=[ART], track=SONG)
    master = entry(SONG, f"{ART} - Topic", 201, 80_000, music_rank=2, artists=[ART], track=SONG)
    R = fa.rank([first, master], query=f"{ART} {SONG}")
    check("two label uploads of the song: views decide, not YouTube Music's order",
          R[0]["id"] == master["id"], [(c["music_rank"], c["score"]) for c in R])

    # ------------------------------------------------------------ reject families
    good = entry(f"{ART} - {SONG} (Official Audio)", ART, 201, 20_000)
    samples = [("live", f"{ART} - {SONG} (Live at the Pier)"),
               ("cover", f"{SONG} - {ART} (Cover by The Lanterns)"),
               ("karaoke", f"{ART} - {SONG} (Karaoke Version)"),
               ("instrumental", f"{ART} - {SONG} (Instrumental)"),
               ("sped up", f"{ART} - {SONG} (Sped-Up)"),
               ("slowed", f"{ART} - {SONG} (slowed)"),
               ("reverb", f"{ART} - {SONG} [Reverb]"),
               ("nightcore", f"Nightcore - {SONG}"),
               ("8D", f"{ART} - {SONG} (8D Audio)"),
               ("remix", f"{ART} - {SONG} (Club Remix)"),
               ("remix", f"{ART} - {SONG} (Reworks)"),
               ("remix", f"{SONG} (Re-Worked)"),
               ("acoustic", f"{ART} - {SONG} (Acoustic)"),
               ("piano version", f"{ART} - {SONG} (Piano Version)"),
               ("medley", f"{ART} - {SONG} / Tin Lanterns Medley"),
               ("mashup", f"{ART} - {SONG} x Tin Lanterns (Mash-Up)"),
               ("reaction", f"FIRST TIME HEARING {ART} - {SONG} | REACTION"),
               ("tutorial", f"{SONG} - {ART} | Guitar Tutorial"),
               ("tutorial", f"{SONG} Bass Lesson"),
               ("loop", f"{ART} - {SONG} (Loop)"),
               ("1 hour", f"{ART} - {SONG} [1 HOUR]"),
               ("extended", f"{ART} - {SONG} (Extended Mix)"),
               ("live", f"{ART} - {SONG} @ The Pier Club"),
               ("live", f"{ART} Harbour Lights Tour Lisbon {SONG}")]
    for family, title in samples:
        bad = entry(title, "Somebody", 201, 5_000_000)
        R = fa.rank([bad, good], ART, SONG)
        c = next(c for c in R if c["id"] == bad["id"])
        check(f"rejected: {family} ({title!r})", family in c["rejected"] and top(R) == good["title"]
              and R[-1]["id"] == bad["id"], c["rejected"])
    c = fa.rank([entry(f"{ART} - {SONG} (Slowed + Reverb)")], ART, SONG)[0]
    check("slowed + reverb: both families", {"slowed", "reverb"} <= set(c["rejected"]), c["rejected"])
    for status, why in (("is_live", "live stream"), ("was_live", "past live stream")):
        c = fa.rank([entry(f"{ART} - {SONG}", live_status=status)], ART, SONG)[0]
        check(f"live_status {status} rejected", why in c["rejected"], c["rejected"])
    c = fa.rank([entry(f"{ART} - {SONG}", availability="needs_auth")], ART, SONG)[0]
    check("login wall rejected", c["rejected"] == ["needs login (needs_auth)"], c["rejected"])
    R = fa.rank([entry(f"{ART} - {SONG}", duration=45), entry(f"{ART} - {SONG}", duration=800)],
                ART, SONG)
    check("< 60 s and > 12 min rejected", [c["rejected"] for c in R] ==
          [["too short (0:45)"], ["too long (13:20)"]], [c["rejected"] for c in R])
    check("unless --duration says so (a 40 s or a 15 min song)",
          not fa.rank([entry(f"{ART} - {SONG}", duration=41)], ART, SONG, 40)[0]["rejected"]
          and not fa.rank([entry(f"{ART} - {SONG}", duration=905)], ART, SONG, 900)[0]["rejected"])
    check("whole words only: Alive, Oliver, Livery, Covering",
          not fa.rank([entry(f"{ART} - {SONG} (Alive Oliver Livery Covering)")], ART, SONG)[0]
          ["rejected"])

    # ------------------------------------------------------------ the song's own words
    R = fa.rank([entry(f"{ART} - Live Wire (Official Audio)", ART),
                 entry(f"{ART} - Live Wire (Live at the Pier)", ART)], ART, "Live Wire")
    check("title 'Live Wire': not rejected, its live version is",
          [bool(c["rejected"]) for c in R] == [False, True] and R[1]["rejected"] == ["live"],
          [(c["title"], c["rejected"]) for c in R])
    R = fa.rank([entry(f"{ART} - Live Wire", ART)], query=f"{ART} Live Wire")
    check("query 'Nova Tide Live Wire': not rejected", not R[0]["rejected"], R[0]["rejected"])
    R = fa.rank([entry(f"Live - {SONG} (Official Video)", "Live"),
                 entry(f"Live - {SONG} (Live)", "Live")], "Live", SONG)
    check("artist 'Live': not rejected, its live version is",
          [bool(c["rejected"]) for c in R] == [False, True], [(c["title"], c["rejected"]) for c in R])
    R = fa.rank([entry(f"Live - {SONG} (Official Video)", "Live")], query=f"Live {SONG}")
    check("query 'Live Glass Harbour': not rejected", not R[0]["rejected"], R[0]["rejected"])
    R = fa.rank([entry(f"{SONG} (Live at the Pier)", "Somebody"),
                 entry(f"Live - {SONG}", "Somebody")], "Live", SONG)
    check("artist 'Live': '<song> (Live at ...)' without the band's name is rejected",
          [c["title"] for c in R if c["rejected"]] == [f"{SONG} (Live at the Pier)"],
          [(c["title"], c["rejected"]) for c in R])
    band = [entry(SONG, "Live", 201, music_rank=1, track=SONG, artists=["Live"]),
            entry(f"{SONG} (Live)", "Live", 260, music_rank=2, track=f"{SONG} (Live)",
                  artists=["Live"]),
            entry(f"{SONG} (Live at the Pier)", "Live", 262, music_rank=3,
                  track=f"{SONG} (Live at the Pier)", artists=["Live"])]
    R = fa.rank(band, "Live", SONG)
    check("artist 'Live': the label's live tracks (band name not in the title) are rejected",
          top(R) == SONG and [c["rejected"] for c in R[1:]] == [["live"], ["live"]],
          [(c["title"], c["rejected"]) for c in R])
    R = fa.rank([entry("Cover Me Slowly", ART), entry("Cover Me Slowly (Cover)", "Somebody")],
                ART, "Cover Me Slowly")
    check("title 'Cover Me Slowly': not rejected, a cover of it is",
          [bool(c["rejected"]) for c in R] == [False, True], [(c["title"], c["rejected"]) for c in R])
    at_song = "Tides @ Midnight"
    at = [entry(at_song, ART, 238, 900_000, music_rank=1, track=at_song, artists=[ART],
                channel_is_verified=True),
          entry(f"{ART} - {at_song} (Official Video)", ART, 245, 5_000_000, channel_is_verified=True),
          entry(f"{ART} - {at_song} @ The Pier Club", "Somebody", 250)]
    for args, how in (((ART, at_song), "artist+title"), ((None, None, None, f"{ART} {at_song}"),
                                                         "query only")):
        R = {c["id"]: c for c in fa.rank(at, *args)}
        check(f"'@' in the song's title: not rejected, '@ The Pier Club' is ({how})",
              [R[c["id"]]["rejected"] for c in at] == [[], [], ["live"]]
              and fa.pick(fa.rank(at, *args))["id"] == at[0]["id"],
              [R[c["id"]]["rejected"] for c in at])
    R = fa.rank([entry(f"Lanterns @ Dusk - {SONG} (Official Video)", "Lanterns @ Dusk")],
                "Lanterns @ Dusk", SONG)
    check("'@' in the band's name: not rejected", not R[0]["rejected"], R[0]["rejected"])
    wire = [entry("Live Wire", ART, 201, 40_000, music_rank=1, track="Live Wire", artists=[ART],
                  channel_is_verified=True),
            entry(f"{ART} - Live Wire (Official Video)", ART, 214, 3_000_000,
                  channel_is_verified=True),
            entry("Tin Lanterns", ART, 190, 90_000, music_rank=2, track="Tin Lanterns",
                  artists=[ART], channel_is_verified=True)]
    for names in ((ART, None), (None, "Live Wire"), (ART, "Live Wire"), (None, None)):
        R = fa.rank(wire, *names, None, f"{ART} Live Wire")
        check(f"one name or both, with the query: {names} -> 'Live Wire', nothing rejected, "
              "the other song not named", top(R) == "Live Wire" and not any(c["rejected"] for c in R)
              and not next(c for c in R if c["title"] == "Tin Lanterns")["named"],
              [(c["title"], c["rejected"], c["named"]) for c in R])
    mine = entry(SONG, ART, 242, 379_000, music_rank=1, track=SONG, artists=[ART])
    theirs = entry(SONG, "Other Artist", 185, 17_000, music_rank=3, track=SONG,
                   artists=["Other Artist"])
    R = fa.rank([mine, theirs], None, SONG, 185.0, f"{ART} {SONG}")
    check("--title alone: another artist's song of that name is not named",
          fa.pick(R)["id"] == mine["id"] and not next(c for c in R if c is not R[0])["named"],
          [(c["channel"], c["named"]) for c in R])

    # ------------------------------------------------------------ spelling and script
    check("apostrophes: ' ’ ´ ʼ ′ ` all vanish", all(fa.words(f"Don{a}t Stop") == ["dont", "stop"]
                                                     for a in "'’´ʼ′`"))
    check("spelling(): Greek and Latin transliterations meet",
          len({fa.spelling(w) for w in ("συννεφιασμενη", "synnefiasmeni", "sinnefiasmeni")}) == 1
          and fa.spelling("frangosyriani") == fa.spelling("fragkosyriani") == "fragosiriani")
    label = entry("Galazia Kiriaki (Remastered 2014)", "Nikos Thalassinos - Topic", 201, 80_000,
                  music_rank=1, artists=["Nikos Thalassinos"],
                  track="Galazia Kiriaki (Remastered 2014)")
    fan = entry("ΓΑΛΑΖΙΑ ΚΥΡΙΑΚΗ - ΝΙΚΟΣ ΘΑΛΑΣΣΙΝΟΣ", "fanchannel99", 201, 1_000_000)
    other = entry("Asimenio Karavi", "Nikos Thalassinos - Topic", 199, 20_000, music_rank=2,
                  artists=["Nikos Thalassinos"], track="Asimenio Karavi")
    R = fa.rank([fan, other, label], query="Νίκος Θαλασσινός Γαλάζια Κυριακή")
    check("Greek-script query: the label's Latin-titled upload beats a Greek fan re-upload",
          fa.pick(R)["id"] == label["id"]
          and not next(c for c in R if c["id"] == other["id"])["named"],
          [(c["title"], c["named"], c["score"]) for c in R])
    spelled_y = entry("Nikos Thalassinos - Galazia Kyriaki", "fanchannel99", 201, 1_000_000)
    R = fa.rank([spelled_y, label], query="Nikos Thalassinos Galazia Kyriaki")
    check("Latin query spelled y: the label spelled i is still named, and wins",
          fa.pick(R)["id"] == label["id"] and all(c["named"] for c in R),
          [(c["title"], c["missing"]) for c in R])
    variants = [entry(t, "Nikos Thalassinos - Topic", 190, 10, track=t,
                      artists=["Nikos Thalassinos"]) for t in ("Agkalia", "Angalia", "Agalia")]
    R = fa.rank(variants, query="Νίκος Θαλασσινός Αγκαλιά")
    check("γκ as gk, ng or g: all named", all(c["named"] for c in R),
          [(c["title"], c["missing"]) for c in R])

    # ------------------------------------------------------------ length, views, names
    R = fa.rank([entry(f"{ART} - {SONG}", "Upload A", 212, 50_000_000),
                 entry(f"{ART} - {SONG}", "Upload B", 201, 800)], ART, SONG, 201.3)
    check("duration match beats 60,000x the views", R[0]["channel"] == "Upload B"
          and "length -0.3 s" in R[0]["reasons"], [(c["channel"], c["score"]) for c in R])
    R = fa.rank([entry(f"{ART} - {SONG}", "Upload A", 201, 50_000),
                 entry(f"{ART} - {SONG}", "Upload B", 201, 800)], ART, SONG, 201.0)
    check("equal length: views break the tie", R[0]["channel"] == "Upload A")
    off2 = entry(f"{ART} - {SONG} (Official Audio)", ART, 203, 40_000, channel_is_verified=True)
    R = fa.rank([dict(music, duration=206), off2], ART, SONG, 201.0)
    check("--duration: the artist's Official Audio 2 s off beats label audio 5 s off",
          R[0]["id"] == off2["id"], [(c["title"], c["score"]) for c in R])
    reup = entry(f"{ART} - {SONG}", "Somebody", 202, 40_000)
    R = fa.rank([dict(music, duration=206), reup], ART, SONG, 201.0)
    check("--duration: a re-upload 1 s off does not beat label audio 5 s off",
          R[0]["id"] == music["id"], [(c["title"], c["score"]) for c in R])
    R = fa.rank([dict(music, duration=202), off2], ART, SONG, 201.2)
    check("--duration: label audio within 2 s beats official audio within 2 s",
          R[0]["id"] == music["id"], [(c["title"], c["score"]) for c in R])
    pts = [round(fa.length_points(201 + s, 201, True)[0], 2) for s in (0, 1, 2, 3.5, 5, 10, 15, 18)]
    check("length curve: 45, 42.5, 40, 20, 0, -5, -10, then -11", pts ==
          [45, 42.5, 40, 20, 0, -5, -10, -11], pts)
    check("length curve continuous at 15 s", abs(fa.length_points(216.01, 201, True)[0] + 10) < 0.01)
    check("length unknown: no points, said so", fa.length_points(None, 201, True) ==
          (0.0, "length unknown"))
    named = [entry(f"{ART} - {SONG}", f"Up {d}", d, 1000) for d in (199, 202, 250, 251)]
    live = [entry(f"{ART} - {SONG} (Live {i})", f"Gig {i}", 300 + i, 1000) for i in range(5)]
    other = [entry(f"{ART} - Tin Lanterns", f"Other {i}", 250 + i, 1000) for i in range(5)]
    R = fa.rank(named + live + other, ART, SONG)
    check("no --duration: median of the named, not rejected candidates (226 s)",
          R[0]["length_ref"] == 226.0 and "vs median 3:46" in " ".join(R[0]["reasons"]),
          (R[0]["length_ref"], R[0]["reasons"]))
    near = fa.rank([entry(f"{ART} - {SONG}", f"Up {d}", d) for d in (199, 201, 203, 250)], ART, SONG)
    check("no --duration: the odd length out ranks last",
          near[-1]["duration"] == 250 and near[0]["length_ref"] == 202.0,
          [(c["duration"], c["score"]) for c in near])
    cover = entry(SONG, "Cover Crew - Topic", 201, 90_000)
    R = fa.rank([cover, video], ART, SONG)
    check("another artist's label upload: not named, below the right artist's video",
          R[0]["id"] == video["id"] and not R[1]["named"] and R[1]["missing"] == ["nova", "tide"],
          [(c["channel"], c["named"], c["missing"]) for c in R])
    other_song = entry("Tin Lanterns", ART, 201, 90_000, music_rank=2, artists=[ART],
                       track="Tin Lanterns")
    R = fa.rank([other_song, lyric], query=f"{ART} {SONG}")
    check("query words: the artist's other song ranks below a lyric video of this one",
          top(R) == lyric["title"] and R[1]["missing"] == ["glass", "harbour"],
          [(c["title"], c["missing"]) for c in R])
    fake = entry(f"{ART} - {SONG} (Official Audio)", "Random Reuploads", 201, 1000)
    plain = entry(f"{ART} - {SONG}", "Random Reuploads", 201, 1000)
    R = {c["id"]: c for c in fa.rank([fake, plain], ART, SONG)}
    check("'Official Audio' on a re-upload channel earns nothing",
          R[fake["id"]]["score"] == R[plain["id"]]["score"]
          and 'says "official audio" (re-upload channel)' in R[fake["id"]]["reasons"])
    vevo = fa.rank([entry(f"{ART} - {SONG}", "NovaTideVEVO", 201)], ART, SONG)[0]
    check("VEVO / Topic / 'The' channels are the artist's",
          "artist's channel" in vevo["reasons"] and fa.artist_key("The Nova Tide - Topic")
          == fa.artist_key("Nova Tide") == "novatide")
    check("empty input: nothing ranked, no pick", fa.rank([], ART, SONG) == [] and
          fa.pick([]) is None and fa.rank([], query="x") == [])
    R = fa.rank([entry(f"{ART} - {SONG} (Live)"), entry(f"{ART} - {SONG} (Karaoke)")], ART, SONG)
    check("all rejected: no pick", fa.pick(R) is None and all(c["rejected"] for c in R))
    check("odd metadata (artists [None], no title): ranked, no crash",
          len(fa.rank([dict(id="a"), dict(id="b", title=None, artists=[None], track=None)],
                      ART, SONG)) == 2)

    # ------------------------------------------------------------ merge, names, command, report
    flat = dict(id=music["id"], title=SONG, url="u", duration=None, view_count=None)
    dup = dict(id=music["id"], title=SONG, channel=ART, duration=201, view_count=77)
    M = fa.merge([dict(flat, music_rank=1, artists=[ART]), dup, dict(id=None)])
    check("merge by id: one candidate, gaps filled, music rank kept", len(M) == 1
          and M[0]["duration"] == 201 and M[0]["view_count"] == 77 and M[0]["music_rank"] == 1)
    desc = f"Provided to YouTube by Tidal Records\n\n{SONG} · {ART} · The Lanterns\n\nAlbum\n"
    S = fa.slim(dict(id="abc", title=SONG, channel="Tidal Records", description=desc))
    check("slim: track and artists from an auto-generated description, watch URL",
          (S["track"], S["artists"], S["url"]) == (SONG, [ART, "The Lanterns"],
                                                   "https://www.youtube.com/watch?v=abc")
          and fa.rank([S], ART, SONG)[0]["named"], S)
    S = fa.slim(dict(id="abc", title=SONG, track="Other", description=desc))
    check("slim: YouTube's own music metadata wins over the description", S["track"] == "Other"
          and "artists" not in S, S)
    long_desc = (f"Provided to YouTube by Tidal Records\n\n{SONG} · {ART}\n\nHarbour Lights\n\n"
                 + "x" * 300 + "\n\n℗ Tidal Records 1959\n\nReleased on: 1997-03-11\n")
    S = fa.slim(dict(id="abc", title=SONG, album="Harbour Lights", release_year=1997,
                     description=long_desc))
    check("slim: the ℗ year from the whole description, release year kept",
          (S.get("p_year"), S.get("release_year"), len(S["description"])) == (1959, 1997, 200), S)
    check("album note: ℗ year, else YouTube's release year, else the album alone",
          fa.album_note(S) == "album 'Harbour Lights' ℗ 1959"
          and fa.album_note(dict(album="Harbour Lights", release_year=1997))
          == "album 'Harbour Lights' (1997)" and fa.album_note(dict(album="A")) == "album 'A'"
          and fa.album_note(dict(release_year=1997)) is None)
    check("names inferred from the YouTube Music song that spells the query",
          fa.infer_names(f"{SONG} by {ART}", [music]) == (ART, SONG)
          and fa.infer_names(f"{ART} {SONG} live", [music]) == (None, None)
          and fa.infer_names(f"{ART} {SONG}", [video]) == (None, None))
    credited = dict(music, artists=[ART, ART, "Max Producer"])     # as a label delivered it
    check("artists: duplicates dropped, the first for file names, the query's subset inferred",
          fa.meta_artist(credited) == f"{ART}, Max Producer"
          and fa.meta_artist(credited, first=True) == ART
          and fa.meta_artist(dict(artists=["Tyler, The Poet"])) == "Tyler, The Poet"
          and fa.infer_names(f"{ART} {SONG}", [credited]) == (ART, SONG)
          and fa.infer_names(f"{ART} Max Producer {SONG}", [credited]) == (f"{ART}, Max Producer", SONG))
    for raw, want in ((f"{SONG} (2004 Remaster)", SONG), (f"{SONG} - 2011 Remaster", SONG),
                      (f"{SONG} (feat. Max Producer (Vocal)) [Remastered 2017])", SONG),
                      (f"{SONG} [Remastered]", SONG),
                      (f"{SONG} (Night Version)", f"{SONG} (Night Version)"),
                      ("(Remastered)", "(Remastered)"), (None, None)):
        check(f"base_title({raw!r}) -> {want!r}", fa.base_title(raw) == want, fa.base_title(raw))
    remastered = dict(music, track=f"{SONG} (2004 Remaster)",
                      artists=["Max Producer", f"{ART} (Vocal)"])
    check("names from a label track: remaster tail and role cut, the query's artist first",
          fa.infer_names(f"{ART} {SONG}", [remastered]) == (ART, SONG)
          and fa.file_names(remastered, f"{ART} {SONG}") == (ART, SONG)
          and fa.file_names(remastered, "something else") == ("Max Producer", SONG))
    cand = dict(credited, url="https://www.youtube.com/watch?v=abc")
    cmd = shlex.join(fa.download_argv("/venv/bin/python", "/s/fetch_audio.py", f"{ART} {SONG}",
                                      cand, None, None, "/Songs/Nova Tide", 201.4))
    check("download command: URL, names from metadata, out-dir, duration, then the query",
          shlex.split(cmd) == ["/venv/bin/python", "/s/fetch_audio.py",
                               "--url=https://www.youtube.com/watch?v=abc", f"--artist={ART}",
                               f"--title={SONG}", "--out-dir=/Songs/Nova Tide", "--duration=201.4",
                               "--", f"{ART} {SONG}"], cmd)
    dash = dict(url=WATCH + "m1", artists=["-M-"], track="-Qui de nous deux-")
    argv = shlex.split(shlex.join(fa.download_argv("py", "s.py", "-M- Qui de nous deux", dash,
                                                   None, None, "/-songs", 180)))
    a = fa.parser().parse_args(argv[2:])
    check("download command: values starting with '-' parse back ('-M-')",
          (a.url, a.artist, a.title, a.out_dir, a.duration, a.query)
          == (WATCH + "m1", "-M-", "-Qui de nous deux-", "/-songs", 180.0, "-M- Qui de nous deux"),
          vars(a))
    albummed = dict(music, album="Harbour Lights", p_year=1959, url=WATCH + music["id"])
    R = fa.rank([albummed] + [dict(c, url=WATCH + c["id"]) for c in
                              (video, other_song, entry(f"{ART} - {SONG} (Live)"))], ART, SONG)
    text = fa.report(R, ["head line"], "CMD")
    lines = text.splitlines()
    check("report: head, the pick marked, groups, command",
          lines[0] == "head line" and lines[3].startswith(" 1* ") and SONG in lines[3]
          and "not named in full (another song or artist?):" in lines
          and "rejected:" in lines and "  CMD" in lines and " rej " in text, text)
    check("report: album and ℗ year in the reasons and on the top-pick line",
          "album 'Harbour Lights' ℗ 1959" in R[0]["reasons"] and any(
              ln.startswith("* top pick:") and "album 'Harbour Lights' ℗ 1959" in ln for ln in lines),
          text)
    check("seconds(): 178.71, 2:58.71, 1:02:03", (fa.seconds("178.71"), fa.seconds("2:58.71"),
                                                  fa.seconds("1:02:03")) == (178.71, 178.71, 3723))
    for bad in ("inf", "nan", "-3", "1:2:3:4", "", "3 min"):
        try:
            fa.seconds(bad)
            check(f"seconds({bad!r}) refused", False, "accepted")
        except fa.argparse.ArgumentTypeError:
            check(f"seconds({bad!r}) refused", True)
    check("mmss(): 2:59, 2:58.7, 1:02:03", (fa.mmss(178.71), fa.mmss(178.71, 1), fa.mmss(3723))
          == ("2:59", "2:58.7", "1:02:03"))

    # ------------------------------------------------------------ file names
    long_name = fa.safe_name("Ω" * 300)
    cases = [("AC/DC", "AC-DC"), ("Title: Part 2", "Title - Part 2"), ("..", "audio"),
             ("", "audio"), ("Why?", "Why"), ('a<b>"c"*', "abc"), ("12:30", "12-30"),
             ("Bjo\u0308rk", "Bj\u00f6rk"), ("Sigur Rós – Hoppípolla", "Sigur Rós – Hoppípolla"),
             ("a\x00b\tc\n d", "ab c d"), (" .hidden. ", "hidden"),
             ("\u202eexe.wav", "exe.wav"), ("Glass\u200bHarbour", "GlassHarbour"),
             ("\u200fNova\u2066 Tide\u2069", "Nova Tide"),
             ("🏳\ufe0f\u200d🌈 Tide", "🏳\ufe0f\u200d🌈 Tide")]
    for raw, want in cases:
        check(f"safe_name({raw!r}) -> {want!r}", fa.safe_name(raw) == want, fa.safe_name(raw))
    check("very long: <= 200 bytes, cut on a character", len(long_name.encode()) <= 200
          and set(long_name) == {"Ω"} and len(long_name) == 100, len(long_name.encode()))
    check("wav_name: artist - title", fa.wav_name("AC/DC", "Title: Part 2", "x") ==
          "AC-DC - Title - Part 2.wav")
    check("wav_name: video title when a name is missing",
          fa.wav_name(None, SONG, f"{ART} - {SONG} (Official Audio)") ==
          f"{ART} - {SONG} (Official Audio).wav" and fa.wav_name(None, None, "..") == "audio.wav")
    check("wav_name: long names stay under the limit",
          len(fa.wav_name("A" * 150, "B" * 150, "x").encode()) <= 204)

    # ------------------------------------------------------------ JS runtime lookup
    def fake(name, text):
        d = Path(tempfile.mkdtemp(prefix="fetch_audio_rt_"))
        p = d / name
        p.write_text(f'#!/bin/sh\necho "{text}"\n')
        p.chmod(0o755)
        return str(d)

    node24, node20 = fake("node", "v24.11.0"), fake("node", "v20.1.0")
    deno24, deno22 = (fake("deno", "deno 2.4.0 (stable, release, aarch64-apple-darwin)"),
                      fake("deno", "deno 2.2.0 (stable, release, aarch64-apple-darwin)"))
    qjs, empty = fake("qjs", "QuickJS version 2024-01-13"), tempfile.mkdtemp()
    rt = lambda *dirs: fa.find_js_runtime(list(dirs))
    js, _ = rt(node24)
    check("node v24.11.0 found", js and (js["name"], js["version"]) == ("node", "24.11.0")
          and js["path"] == str(Path(node24) / "node"), js)
    js, notes = rt(node20)
    check("node v20.1.0 too old: none, with a note", js is None and len(notes) == 1
          and "node 20.1.0" in notes[0] and "too old" in notes[0], notes)
    js, notes = rt(node20, node24)
    check("an old node first on PATH, a new one later: the new one",
          js and js["version"] == "24.11.0" and len(notes) == 1, (js, notes))
    js, _ = rt(node24, deno24)
    check("deno 2.4.0 wins over node", js and (js["name"], js["version"]) == ("deno", "2.4.0"), js)
    js, _ = rt(deno22, node24)
    check("deno 2.2.0 too old: node instead", js and js["name"] == "node", js)
    js, _ = rt(qjs)
    check("quickjs found as qjs", js and (js["name"], js["version"]) == ("quickjs", "2024-01-13"), js)
    js, notes = rt(empty)
    check("nothing found: None, no notes", js is None and notes == [])
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join([node20, empty, node24])
    try:
        dirs = fa.search_dirs()
    finally:
        os.environ["PATH"] = saved
    js, notes = fa.find_js_runtime(dirs[-3:])
    check("PATH read in order after the venv's bin: the new node", dirs[-3:] == [node20, empty,
          node24] and dirs[0] == fa.sysconfig.get_path("scripts") and js["version"] == "24.11.0",
          (dirs, js))
    check("yt-dlp option: path of the runtime found, else yt-dlp's default",
          fa.js_option(rt(deno24)[0]) == {"deno": {"path": str(Path(deno24) / "deno")}}
          and fa.js_option(None) == {"deno": {}})
    warning = fa.runtime_warning(["node 20.1.0 at /x/node is too old (needs 22.0.0 or newer)"])
    check("warning names deno (recommended) and node >= 22", "deno >= 2.3 (recommended" in warning
          and "node >= 22" in warning and "node 20.1.0" in warning, warning)

    # ------------------------------------------------------------ records and CLI
    info = dict(id="vid00000001", title=SONG, channel=f"{ART} - Topic", duration=201,
                upload_date="20260101", view_count=1234, channel_is_verified=True,
                license="Creative Commons Attribution license (reuse allowed)",
                format_id="251", acodec="opus", abr=131.2, asr=48000, ext="webm",
                webpage_url="https://www.youtube.com/watch?v=vid00000001",
                artists=[ART, ART, "Max Producer"], track=f"{SONG} (2004 Remaster)",
                album="Harbour Lights", release_date="20040101", release_year=2004)
    rec = fa.source_record(info, query=f"{ART} {SONG}", file=f"{ART} - {SONG}.wav", artist=ART,
                           song=SONG, js_runtime="node 24.11.0", ytdlp_version="2026.08.19",
                           fetched_at="2026-09-30T12:00:00Z")
    need = {"file", "query", "artist", "song", "url", "id", "title", "channel",
            "channel_is_verified", "label_upload", "credits", "track", "album", "release_date",
            "release_year", "duration", "upload_date", "license", "view_count", "format", "yt_dlp",
            "js_runtime", "fetched_at", "rights", "wav"}
    check("source.json record: every field", need <= set(rec) and {"format_id", "acodec", "abr",
          "asr"} <= set(rec["format"]) and rec["format"]["asr"] == 48000
          and json.loads(json.dumps(rec)) == rec, sorted(need - set(rec)))
    check("source.json record: the names the WAV got, YouTube's credits, label upload, release",
          (rec["artist"], rec["song"], rec["credits"], rec["label_upload"], rec["release_year"],
           rec["channel_is_verified"]) == (ART, SONG, [ART, "Max Producer"], "Topic channel", 2004,
                                           True), rec)
    check("rights: the call is the user's; YouTube's Terms restrict downloading",
          rec["rights"] == fa.RIGHTS and "YouTube's Terms restrict downloading" in fa.RIGHTS
          and "right to use" in fa.RIGHTS)
    d = Path(tempfile.mkdtemp(prefix="fetch_audio_wav_"))
    write_wav(d / "t.wav")
    check("wav_facts: rate, channels, bits, length", fa.wav_facts(d / "t.wav") ==
          dict(sample_rate=48000, channels=2, bits=16, duration_s=1.5), fa.wav_facts(d / "t.wav"))
    broken = Path(fake("ffmpeg", "x")) / "ffmpeg"
    broken.write_text('#!/bin/sh\necho "Invalid data found when processing input" >&2\nexit 1\n')
    try:
        fa.decode(str(broken), d / "t.wav", d / "out.wav")
        check("decode: an ffmpeg failure raises with its message", False, "no error")
    except RuntimeError as e:
        check("decode: an ffmpeg failure raises with its message",
              "Invalid data found" in str(e) and not (d / "out.wav").exists(), e)

    run = lambda *args: subprocess.run([sys.executable, "-S", str(SCRIPTS / "fetch_audio.py"),
                                        *args], capture_output=True, text=True, cwd=d)
    r = run(f"{ART} {SONG}")
    check("CLI without yt-dlp: exit 2 with the install hint", r.returncode == 2
          and 'uv pip install --python .venv-ytdlp/bin/python -U "yt-dlp[default]"' in r.stderr
          and not r.stdout, r.stderr)
    r = run("--url", "https://www.youtube.com/watch?v=abc", "--out-dir", str(d))
    check("CLI download mode without yt-dlp: exit 2 too", r.returncode == 2
          and "yt-dlp[default]" in r.stderr, r.stderr)
    r = run(f"{ART} {SONG}", "--dry-run")
    check("CLI: --dry-run without --url is a usage error", r.returncode == 2
          and "go with --url" in r.stderr, r.stderr)
    r = run(f"{ART} {SONG}", "--duration", "three minutes")
    check("CLI: a bad --duration is a usage error", r.returncode == 2
          and "not a length" in r.stderr, r.stderr)
    r = run()
    check("CLI: no query and no URL is a usage error", r.returncode == 2, r.stderr)
    check("CLI wrote nothing", sorted(p.name for p in d.iterdir()) == ["t.wav"],
          sorted(p.name for p in d.iterdir()))

    # ------------------------------------------------------------ search and download modes
    tools = Path(tempfile.mkdtemp(prefix="fetch_audio_tools_"))
    ffmpeg = tools / "ffmpeg"                   # 'decodes' by copying: the fake download is a WAV
    ffmpeg.write_text('#!/bin/sh\nsrc=\nwhile [ $# -gt 1 ]; do [ "$1" = -i ] && src=$2; shift; '
                      'done\ncp "$src" "$1"\n')
    ffmpeg.chmod(0o755)
    label_song = dict(id="m1", title=SONG, channel=ART, duration=201, view_count=40_000,
                      artists=[ART], track=SONG, album="Harbour Lights", channel_is_verified=True)
    hits = [dict(id="v1", title=f"{ART} - {SONG} (Official Video)", channel=ART, duration=214,
                 view_count=3_000_000, channel_is_verified=True),
            dict(id="v2", title=f"{ART} - {SONG} (Lyrics)", channel="Lyric Lagoon", duration=201,
                 view_count=900_000)]
    yt = fake_ytdlp(music=[label_song], videos=hits)
    args = lambda *argv: fa.parser().parse_args(list(argv))

    rc, out, err = quiet(fa.find, yt, args(f"{ART} {SONG}", "--json", "--out-dir", "/songs"),
                         f"{ART} {SONG}", None)
    res = json.loads(out)
    back = fa.parser().parse_args(res["command_argv"][2:])
    check("search: label audio picked, both searches counted, the command parses back",
          rc == 0 and res["candidates"][res["pick"] - 1]["id"] == "m1"
          and res["searched"] == dict(youtube_music=1, youtube=2) and res["errors"] == []
          and (back.url, back.artist, back.title, back.out_dir) == (WATCH + "m1", ART, SONG, "/songs")
          and res["command"] == shlex.join(res["command_argv"]), (rc, out[:400], err))
    yt_down = fake_ytdlp(music=[label_song], videos=hits, music_fails=True)
    rc, out, err = quiet(fa.find, yt_down, args(f"{ART} {SONG}", "--out-dir", "/songs"),
                         f"{ART} {SONG}", None)
    rc2, out2, _ = quiet(fa.find, yt_down, args(f"{ART} {SONG}", "--json", "--out-dir", "/songs"),
                         f"{ART} {SONG}", None)
    res = json.loads(out2)
    check("search: a failed YouTube Music search is said in the header, the JSON and stderr",
          "YouTube Music: FAILED (see stderr); YouTube: 2 results" in out
          and "YouTube Music search failed" in err and res["searched"]["youtube_music"] is None
          and res["searched"]["youtube"] == 2 and len(res["errors"]) == 1, (out[:300], err))

    here = Path(tempfile.mkdtemp(prefix="fetch_audio_a_"))
    there = Path(tempfile.mkdtemp(prefix="fetch_audio_b_"))
    saved_env, saved_cwd = dict(os.environ), os.getcwd()
    sys.modules["yt_dlp"] = yt
    os.environ.update(PATH=os.pathsep.join([str(tools), os.defpath]), HOME=str(there))
    try:
        os.chdir(here)
        rc, out, err = quiet(fa.main, [f"{ART} {SONG}", "--out-dir", "songs"])
        cmd = next(ln.strip() for ln in out.splitlines() if ln.strip().startswith(sys.executable))
        folder = str(here.resolve() / "songs")
        os.chdir(there)
        rc2, out2, err2 = quiet(fa.main, shlex.split(cmd)[2:])
        rc3, out3, _ = quiet(fa.main, ["--url", WATCH + "m1", "--out-dir", "~/x", "--dry-run"])
    finally:
        os.chdir(saved_cwd)
        os.environ.clear()
        os.environ.update(saved_env)
        del sys.modules["yt_dlp"]
    check("CLI: the printed command carries the song folder as an absolute path",
          rc == 0 and f"--out-dir={folder}" in cmd.replace("'", "")
          and Path(folder, f"{ART} - {SONG}.wav").exists(), (cmd, folder, err))
    check("CLI: run from elsewhere, it writes the WAV and source.json there, nothing in the cwd",
          rc2 == 0 and sorted(p.name for p in Path(folder).iterdir()) == [f"{ART} - {SONG}.wav",
                                                                          "source.json"]
          and list(there.iterdir()) == [] and f"wrote {folder}/{ART} - {SONG}.wav" in out2,
          (out2, err2))
    check("CLI: '~' in --out-dir is the home folder", rc3 == 0
          and f"would write {there}/x/{ART} - {SONG}.wav"
          in out3.replace(str(there.resolve()), str(there)), out3[:300])

    song_dir = Path(tempfile.mkdtemp(prefix="fetch_audio_song_"))
    dl = lambda y, *argv: quiet(fa.fetch, y, args("--out-dir", str(song_dir), *argv), None,
                                str(ffmpeg))
    rc, out, err = dl(yt, "--url", WATCH + "m1", "--", f"{ART} {SONG}")
    first = json.loads((song_dir / "source.json").read_text())
    check("download: the WAV and source.json in the song folder, nothing else left",
          rc == 0 and sorted(p.name for p in song_dir.iterdir()) == [f"{ART} - {SONG}.wav",
                                                                     "source.json"]
          and first["file"] == f"{ART} - {SONG}.wav" and first["wav"]["sample_rate"] == 48000
          and first["artist"] == ART and first["song"] == SONG, (rc, out, err))
    check("download: yt-dlp's output template holds no part of the song folder",
          yt.templates and all(str(song_dir) not in t for t in yt.templates), yt.templates)
    plain = dict(id="p1", title=f"{ART} - {SONG} (Official Video)", channel=ART, duration=214)
    yt_plain = fake_ytdlp(watch=plain)
    rc, out, err = dl(yt_plain, "--url", WATCH + "p1")
    check("download: another WAV's source.json in the folder is not replaced without --force",
          rc == 1 and "describes" in err and "--force" in err
          and json.loads((song_dir / "source.json").read_text()) == first
          and len(list(song_dir.iterdir())) == 2, (rc, err))
    rc, out, err = dl(yt_plain, "--url", WATCH + "p1", "--force")
    check("download: with --force it is",
          rc == 0 and json.loads((song_dir / "source.json").read_text())["id"] == "p1", (rc, err))
    rc, out, err = dl(yt, "--url", WATCH + "m1", "--", f"{ART} {SONG}")
    check("download: an existing WAV is not replaced without --force", rc == 1 and "exists" in err,
          (rc, err))
    for how in ((), ("--dry-run",)):
        stream = fake_ytdlp(watch=dict(id="l1", title="beats all day", channel="Lofi Lagoon",
                                       live_status="is_live", is_live=True, duration=None))
        empty_dir = Path(tempfile.mkdtemp(prefix="fetch_audio_live_")) / "song"
        rc, out, err = quiet(fa.fetch, stream, args("--url", WATCH + "l1", "--out-dir",
                                                    str(empty_dir), *how), None, str(ffmpeg))
        check(" ".join(("download: a live stream is refused", *how)),
              rc == 1 and "live stream" in err and not empty_dir.exists() and not stream.templates,
              (rc, err))
    full = Path(tempfile.mkdtemp(prefix="fetch_audio_full_"))
    rc, out, err = quiet(fa.fetch, fake_ytdlp(music=[label_song], disk_full=True),
                         args("--url", WATCH + "m1", "--out-dir", str(full)), None, str(ffmpeg))
    check("download: a failed download (not a DownloadError) is reported, nothing left",
          rc == 1 and "download failed: Unable to download video" in err
          and list(full.iterdir()) == [], (rc, err))
    odd_root = Path(tempfile.mkdtemp(prefix="fetch_audio_pct_"))
    odd = odd_root / "Songs 100%% sure $HOME"
    yt_odd = fake_ytdlp(music=[label_song])
    rc, out, err = quiet(fa.fetch, yt_odd, args("--url", WATCH + "m1", "--out-dir", str(odd)),
                         None, str(ffmpeg))
    check("download: '%%' and '$HOME' in the folder name: everything lands in it",
          rc == 0 and [p.name for p in odd_root.iterdir()] == [odd.name]
          and sorted(p.name for p in odd.iterdir()) == [f"{ART} - {SONG}.wav", "source.json"],
          (rc, err, sorted(str(p) for p in odd_root.rglob("*"))))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
