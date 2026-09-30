#!/usr/bin/env python3
"""Push a notes JSON into a Live clip over the Remote Script's raw TCP socket (9877).

Keeps hundreds of notes out of the conversation and stops on the first failed
chunk (exit 1) instead of reporting a partial push as done.

Notes are either Live-beat notes, the add_notes_to_clip format:
    [{"pitch": 64, "start_time": 0.0, "duration": 0.5, "velocity": 90, "mute": false}]
or, with --from-seconds foundation.json, analysed notes in seconds:
    [{"pitch": 64, "start": 12.31, "end": 12.84, "velocity": 90}]
which are mapped through the song's real beat grid (not one BPM) and shifted a
bar later if any land before the first tracked beat (they would never play).

Usage (any Python 3.8+, standard library only):
    push_notes.py <track_index> <clip_index> <notes.json> [--chunk 300]
        [--from-seconds analysis/foundation.json] [--clear 64] [--signature 11/8]
"""
import argparse, bisect, json, math, os, socket, sys

ADDR = ("127.0.0.1", int(os.environ.get("LIVE_PORT", 9877)))   # override for tests


def live(cmd, **params):
    """One command per connection; returns the decoded JSON reply."""
    with socket.create_connection(ADDR, timeout=60) as s:
        s.sendall(json.dumps({"type": cmd, "params": params}).encode())
        buf = b""
        while chunk := s.recv(65536):
            buf += chunk
            try:
                return json.loads(buf)
            except json.JSONDecodeError:
                continue
    raise ConnectionError(f"incomplete reply to {cmd}: {buf[:200]!r}")


def ok(reply):
    """Success = status "success" and no error hidden in the result (this fork returns
    some failures inside a success reply)."""
    if not (isinstance(reply, dict) and reply.get("status") == "success"):
        return False
    res = reply.get("result")
    return not (isinstance(res, dict) and res.get("error"))


def from_seconds(notes, foundation_path):
    """Seconds -> Live beats (quarter notes) through the beat grid, 16th-snapped."""
    F = json.load(open(foundation_path))
    bt = [float(x) for x in F["beat_times"]]
    unit = F.get("pulse_unit", 4)

    def pulse(t):                                  # fractional pulse index, extrapolated
        if t <= bt[0]:
            return (t - bt[0]) / (bt[1] - bt[0])
        if t >= bt[-1]:
            return len(bt) - 1 + (t - bt[-1]) / (bt[-1] - bt[-2])
        i = bisect.bisect_right(bt, t) - 1
        return i + (t - bt[i]) / (bt[i + 1] - bt[i])

    def beats(t):
        return round(pulse(t) * 4 / unit * 4) / 4

    s = [beats(x["start"]) for x in notes]
    e = [beats(x["end"]) for x in notes]
    shift = 0.0
    if s and min(s) < 0:
        bar = F.get("beats_per_bar", 4) * 4 / unit
        shift = bar * math.ceil(-min(s) / bar)
        print(f"pre-roll: notes start before the first beat - shifted {shift:g} beats; "
              f"lengthen the clip by that much")
    return [dict(pitch=int(x["pitch"]), start_time=a + shift, duration=max(b - a, 0.25),
                 velocity=int(x.get("velocity", 90)), mute=False)
            for x, a, b in zip(notes, s, e)]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("track", type=int)
    ap.add_argument("clip", type=int)
    ap.add_argument("notes")
    ap.add_argument("--chunk", type=int, default=300)
    ap.add_argument("--from-seconds", metavar="FOUNDATION",
                    help="notes are in seconds; map through this foundation.json")
    ap.add_argument("--clear", type=float, metavar="LENGTH",
                    help="first remove ALL notes, including ones outside 0..LENGTH beats")
    ap.add_argument("--signature", help="also set the Set's meter, e.g. 11/8")
    a = ap.parse_args()

    notes = json.load(open(a.notes))
    if a.from_seconds:
        notes = from_seconds(notes, a.from_seconds)

    if a.signature:
        num, den = (int(x) for x in a.signature.split("/"))
        live("set_signature", numerator=num, denominator=den)
        got = live("get_signature").get("result", {})
        print(f"signature now {got.get('numerator')}/{got.get('denominator')}")
        if (got.get("numerator"), got.get("denominator")) != (num, den):
            sys.exit("signature did not take")

    if a.clear is not None:
        # remove_all_notes only clears 0..clip length; negative-time and trailing notes
        # survive, so sweep a wide range as well
        for cmd, p in (("remove_all_notes", {}),
                       ("remove_notes", dict(from_time=-16.0, time_span=a.clear + 32.0,
                                             from_pitch=0, pitch_span=128))):
            r = live(cmd, track_index=a.track, clip_index=a.clip, **p)
            if not ok(r):
                sys.exit(f"{cmd} failed: {r}")

    pushed = 0
    for i in range(0, len(notes), a.chunk):
        part = notes[i:i + a.chunk]
        r = live("add_notes_to_clip", track_index=a.track, clip_index=a.clip, notes=part)
        if not ok(r):
            sys.exit(f"chunk {i}-{i + len(part)} FAILED after {pushed} notes: {r}")
        pushed += len(part)
    print(f"pushed {pushed} notes to track {a.track} clip {a.clip} - verify with get_clip_notes")


if __name__ == "__main__":
    main()
