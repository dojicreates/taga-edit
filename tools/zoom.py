"""Slow, gentle zoom in / zoom out on the footage (never nauseating, never distracting).

Usage:
    python tools/zoom.py suggest emphasis.json --duration 21.8 > zoom.json
    python tools/zoom.py render INPUT/video.mp4 OUTPUT/video_zoom.mp4 zoom.json

zoom.json:
    {"center": [0.5, 0.4],
     "keys": [[0, 1.0], [0.7, 1.0], [2.5, 1.07], [3.3, 1.07], [5.3, 1.0]]}

"keys" is a list of [time in seconds, scale]. Between two keys the motion is smooth (ease-in and
ease-out), so there is no abrupt start or stop. Scale 1.0 = no zoom; higher = zoomed in. Going back
down is a zoom out.
"center" is the point in the frame that stays fixed while zooming (x, y as a fraction of the width
and height). The default [0.5, 0.4] keeps a face in the frame.

INTENSE zoom (for emotion and weight): a fast punch-in followed by a slow zoom out.
Add a third element "punch" to the key the fast move arrives at:
    {"keys": [[0,1.0],[1.6,1.0],[1.9,1.2,"punch"],[3.0,1.2],[6.4,1.0]]}
The punch is fast at the start and settles slowly (ease-out). The zoom out afterwards is slow.

LIMITS (the script rejects anything outside them, so the result is easy on the eyes):
  - normal zoom: up to 1.12 (usually 1.05 to 1.08), zooming in no faster than 0.045 scale per second
  - punch-in: up to 1.30, and the move takes at least 0.25 s
  - zoom out: no faster than 0.075 scale per second (for example 0.2 over 2.7 s or longer)
"""
import argparse
import json
import os
import subprocess
import sys

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")

MAX_SCALE = 1.12
MAX_SPEED = 0.045  # scale per second, zooming in
MAX_OUT_SPEED = 0.075  # scale per second, zooming out
MAX_PUNCH = 1.30
MIN_PUNCH_IN = 0.25  # seconds
WEIGHT = {"slam": 3, "box": 2, "pop": 1, "type": 1, "slide": 1}


def video_info(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


def validate(keys):
    if len(keys) < 2:
        sys.exit("At least two keys are required.")
    for (t0, z0, _e0), (t1, z1, e1) in zip(keys, keys[1:]):
        if t1 <= t0:
            sys.exit(f"Key times must increase: {t0} -> {t1}")
        dt, dz = t1 - t0, z1 - z0
        if e1 == "out":
            if dz <= 0:
                sys.exit(f"'punch' is only for zooming in ({t0}s to {t1}s).")
            if dt < MIN_PUNCH_IN - 1e-9:
                sys.exit(f"The punch-in from {t0}s to {t1}s is too abrupt. "
                         f"Make it at least {MIN_PUNCH_IN}s.")
            if z1 > MAX_PUNCH:
                sys.exit(f"The punch-in is too close ({z1}); max {MAX_PUNCH}.")
        elif dz > 0:
            if dz / dt > MAX_SPEED + 1e-9:
                sys.exit(f"Zooming in from {t0}s to {t1}s is too fast "
                         f"({dz / dt:.3f}/s, max {MAX_SPEED}). Make it at least "
                         f"{dz / MAX_SPEED:.1f}s, or mark it \"punch\" if it is meant to be intense.")
            if z1 > MAX_SCALE:
                sys.exit(f"A normal zoom must not exceed {MAX_SCALE} "
                         f"(use \"punch\" to go closer).")
        elif -dz / dt > MAX_OUT_SPEED + 1e-9:
            sys.exit(f"Zooming out from {t0}s to {t1}s is too fast "
                     f"({-dz / dt:.3f}/s, max {MAX_OUT_SPEED}). Make it at least "
                     f"{-dz / MAX_OUT_SPEED:.1f}s.")
    if min(z for _, z, _ in keys) < 1.0:
        sys.exit("The scale cannot be below 1.0.")


def scale_expr(keys):
    """Smooth piecewise scale expression of time t.
    Default: smoothstep (ease-in-out). "punch": ease-out cubic (fast at first, slow at the end)."""
    expr = f"{keys[-1][1]}"
    for (t0, z0, _e0), (t1, z1, e1) in reversed(list(zip(keys, keys[1:]))):
        u = f"((t-{t0})/({t1 - t0}))"
        if e1 == "out":
            ease = f"(1-pow(1-{u},3))"
        else:
            ease = f"({u}*{u}*(3-2*{u}))"
        seg = f"{z0}+({z1 - z0})*{ease}"
        expr = f"if(lt(t,{t1}),{seg},{expr})"
    return f"if(lt(t,{keys[0][0]}),{keys[0][1]},{expr})"


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    with open(a.spec, encoding="utf-8-sig") as f:
        spec = json.load(f)
    keys = [(float(k[0]), float(k[1]), "out" if len(k) > 2 and k[2] == "punch" else "smooth")
            for k in spec["keys"]]
    validate(keys)
    cx, cy = spec.get("center", [0.5, 0.4])
    w, h, dur = video_info(a.src)
    z = scale_expr(keys)
    flt = (f"scale=w='trunc(iw*({z})/2)*2':h='trunc(ih*({z})/2)*2':eval=frame:flags=bicubic,"
           f"crop=w={w}:h={h}:x='(iw-{w})*{cx}':y='(ih-{h})*{cy}',setsar=1")
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src), "-vf", flt,
         "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", os.path.abspath(a.dst)],
        check=True, capture_output=True)
    ins = [(z1, e1) for (_, z0, _), (_, z1, e1) in zip(keys, keys[1:]) if z1 > z0]
    print(f"{len(ins)} zoom-ins ({sum(1 for _, e in ins if e == 'out')} intense), "
          f"highest scale {max(z for _, z, _ in keys):.2f}")
    print(f"Saved: {os.path.abspath(a.dst)}")


def cmd_suggest(a):
    """Suggest a few zooms based on the weight of the emphasis items. Review and adjust the result."""
    with open(a.emphasis, encoding="utf-8-sig") as f:
        items = json.load(f)
    cand = sorted(items, key=lambda it: (-WEIGHT.get(it.get("style", "pop"), 1), it["start"]))
    picks, busy = [], []
    max_n = max(1, int(a.duration // 7))
    for it in cand:
        if len(picks) >= max_n or WEIGHT.get(it.get("style", "pop"), 1) < 2:
            break
        s, e = float(it["start"]), float(it["end"])
        rise = 1.8
        t0 = max(0.0, s - 1.2)
        t1 = t0 + rise
        t2 = max(e, t1 + 0.4)
        t3 = min(t2 + 2.0, a.duration)
        if t3 - t2 < 1.5 and t3 < a.duration:
            continue
        if any(not (t3 + 2.5 < b0 or t0 - 2.5 > b1) for b0, b1 in busy):
            continue
        busy.append((t0, t3))
        picks.append((t0, t1, t2, t3, it["text"]))
    picks.sort()
    keys, last = [[0.0, 1.0]], 0.0
    for t0, t1, t2, t3, _txt in picks:
        if t0 > last:
            keys.append([round(t0, 2), 1.0])
        t2 = min(t2, a.duration)
        keys += [[round(t1, 2), a.amount], [round(t2, 2), a.amount]]
        if t3 > t2 + 0.01:
            keys.append([round(t3, 2), 1.0])
        last = t3
    spec = {"center": [0.5, 0.4], "keys": keys}
    print(json.dumps(spec))
    for t0, t1, t2, t3, txt in picks:
        print(f"# {txt}: in {t0:.1f}-{t1:.1f}s, hold until {t2:.1f}s, out until {t3:.1f}s",
              file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("spec")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("suggest")
    p.add_argument("emphasis")
    p.add_argument("--duration", type=float, required=True)
    p.add_argument("--amount", type=float, default=1.07)
    p.set_defaults(fn=cmd_suggest)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
