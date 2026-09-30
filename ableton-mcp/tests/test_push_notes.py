#!/usr/bin/env python3
"""Test scripts/push_notes.py against a mock Remote Script (no Live needed).

Checks chunking, stop-on-failure (exit 1, no false "pushed"; also for an error inside a
success reply), the out-of-bounds clear, set/get_signature read-back, and seconds -> Live
beats with pre-roll.
Run: python3 tests/test_push_notes.py   (standard library only)
"""
import atexit, json, os, shutil, socket, subprocess, sys, tempfile, threading
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "push_notes.py"


class MockLive:
    def __init__(self, fail_on_call=None, swallow_on_call=None):
        self.calls, self.sig, self.fail_on = [], (4, 4), fail_on_call
        self.swallow_on = swallow_on_call
        self.srv = socket.socket(); self.srv.bind(("127.0.0.1", 0)); self.srv.listen(5)
        self.port = self.srv.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            c, _ = self.srv.accept(); data = b""
            while True:
                data += c.recv(65536)
                try: msg = json.loads(data); break
                except json.JSONDecodeError: continue
            self.calls.append(msg); p = msg["params"]
            if msg["type"] == "set_signature": self.sig = (p["numerator"], p["denominator"])
            res = {"numerator": self.sig[0], "denominator": self.sig[1]} \
                if msg["type"] == "get_signature" else {}
            status = "error" if len(self.calls) == self.fail_on else "success"
            if len(self.calls) == self.swallow_on:              # error inside a success reply
                res = {"error": "swallowed"}
            c.sendall(json.dumps({"status": status, "result": res}).encode()); c.close()


def run(mock, *args):
    env = dict(os.environ, LIVE_PORT=str(mock.port))
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True, env=env)


def main():
    fails = 0
    def check(name, cond, info=""):
        nonlocal fails
        fails += not cond
        print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  [{info}]" if not cond else ""))

    d = Path(tempfile.mkdtemp())
    atexit.register(shutil.rmtree, d, True)            # removed at exit
    beats = d / "beats.json"
    json.dump([dict(pitch=60, start_time=i * .25, duration=.25, velocity=90, mute=False)
               for i in range(700)], open(beats, "w"))

    m = MockLive(); r = run(m, 0, 1, beats, "--clear", 64, "--signature", "11/8")
    types = [c["type"] for c in m.calls]
    check("happy path exits 0", r.returncode == 0, r.stderr)
    check("signature set and read back", m.sig == (11, 8) and "get_signature" in types)
    rm = next(c["params"] for c in m.calls if c["type"] == "remove_notes")
    check("clear sweeps negative times", rm["from_time"] < 0 and rm["time_span"] >= 64 + 16)
    sizes = [len(c["params"]["notes"]) for c in m.calls if c["type"] == "add_notes_to_clip"]
    check("chunks of 300", sizes == [300, 300, 100], sizes)

    m = MockLive(fail_on_call=2); r = run(m, 0, 1, beats)
    check("failed chunk exits 1", r.returncode == 1 and "FAILED after 300" in (r.stderr + r.stdout),
          r.stderr.strip())

    m = MockLive(swallow_on_call=2); r = run(m, 0, 1, beats)
    check("error inside a success reply exits 1", r.returncode == 1 and "FAILED after 300"
          in (r.stderr + r.stdout), r.stderr.strip())

    secs, fnd = d / "secs.json", d / "found.json"
    json.dump({"beat_times": [0.5 + 0.4 * i for i in range(40)], "pulse_unit": 8,
               "beats_per_bar": 11}, open(fnd, "w"))
    json.dump([dict(pitch=64, start=0.1, end=0.5), dict(pitch=64, start=0.5 + 0.4 * 11, end=5.3)],
              open(secs, "w"))
    m = MockLive(); r = run(m, 0, 1, secs, "--from-seconds", fnd)
    starts = [n["start_time"] for c in m.calls for n in c["params"].get("notes", [])]
    # 0.1 s is one eighth before beat 0 -> -0.5; pre-roll shifts by one 11/8 bar (5.5)
    check("seconds -> beats with pre-roll", starts == [5.0, 11.0] and "pre-roll" in r.stdout, starts)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
