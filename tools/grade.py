"""Color grade a video with FFmpeg (default look: cinematic).

Usage:
    python tools/grade.py presets
    python tools/grade.py render INPUT/video.mp4 OUTPUT/video_graded.mp4 [--preset cinematic] [overrides]
    python tools/grade.py compare INPUT/video.mp4 compare.png [--preset cinematic] [--at 3.0]

The user describes the look; translate it into the parameters below. Start from the closest
preset and override only what is needed.

Parameters (all optional overrides; the cinematic defaults are in parentheses):
  --contrast     1.0 = unchanged (1.08)
  --saturation   1.0 = unchanged; lower = more muted (0.92)
  --brightness   -0.2 to 0.2, 0 = unchanged (0)
  --gamma        1.0 = unchanged; above 1 brightens the midtones (1.0)
  --s-curve      0 to 0.15: extra contrast in the shadows/highlights (0.05)
  --fade         0 to 0.1: raises the blacks (lifted blacks, matte look) (0.025)
  --warmth       -1 (cool) to +1 (warm): midtones (0.15)
  --teal         0 to 1: teal in the shadows (0.6)
  --orange       0 to 1: orange in the highlights (0.5)
  --vignette     0 to 1: darkens the edges (0.4)
  --grain        0 to 12: fine film grain (3)
  --sharpen      0 to 1: slight sharpening (0.3)
  --bw           black and white
"""
import argparse
import os
import subprocess
import sys

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")

BASE = {"contrast": 1.0, "saturation": 1.0, "brightness": 0.0, "gamma": 1.0, "s_curve": 0.0,
        "fade": 0.0, "warmth": 0.0, "teal": 0.0, "orange": 0.0, "vignette": 0.0,
        "grain": 0.0, "sharpen": 0.0, "bw": False}

PRESETS = {
    "cinematic": dict(contrast=1.08, saturation=0.92, brightness=0.0, gamma=1.0,
                      s_curve=0.05, fade=0.025, warmth=0.15, teal=0.6, orange=0.5,
                      vignette=0.4, grain=3, sharpen=0.3),
    "warm": dict(contrast=1.05, saturation=1.05, warmth=0.45, orange=0.4, vignette=0.2,
                 fade=0.01, s_curve=0.03),
    "cool": dict(contrast=1.06, saturation=0.9, warmth=-0.4, teal=0.7, vignette=0.25,
                 fade=0.015, s_curve=0.04),
    "moody": dict(contrast=1.15, saturation=0.8, brightness=-0.04, gamma=0.92, s_curve=0.08,
                  fade=0.02, teal=0.5, orange=0.3, vignette=0.5, grain=4, sharpen=0.25),
    "vivid": dict(contrast=1.1, saturation=1.25, s_curve=0.05, sharpen=0.35),
    "bw": dict(contrast=1.15, s_curve=0.07, fade=0.02, vignette=0.3, grain=4, sharpen=0.3, bw=True),
}


def params(a):
    p = dict(BASE)
    p.update(PRESETS[a.preset])
    for k in BASE:
        v = getattr(a, k, None)
        if v is not None and v is not False:
            p[k] = v
    return p


def build_filter(p):
    f = []
    if p["bw"]:
        f.append("hue=s=0")
    f.append(f"eq=contrast={p['contrast']:.3f}:saturation={0 if p['bw'] else p['saturation']:.3f}"
             f":brightness={p['brightness']:.3f}:gamma={p['gamma']:.3f}")
    s, fd = p["s_curve"], p["fade"]
    if s or fd:
        pts = [(0, fd), (0.25, max(0.25 - s + fd * 0.6, 0)), (0.5, 0.5),
               (0.75, min(0.75 + s - fd * 0.2, 1)), (1, 1 - fd * 0.4)]
        f.append("curves=all='" + " ".join(f"{x}/{y:.4f}" for x, y in pts) + "'")
    if not p["bw"]:
        w, t, o = p["warmth"], p["teal"], p["orange"]
        if w or t or o:
            f.append(
                f"colorbalance=rs={-0.08 * t:.3f}:gs={0.02 * t:.3f}:bs={0.07 * t:.3f}"
                f":rm={0.06 * w:.3f}:bm={-0.06 * w:.3f}"
                f":rh={0.06 * o:.3f}:gh={0.01 * o:.3f}:bh={-0.06 * o:.3f}")
    if p["sharpen"]:
        f.append(f"unsharp=5:5:{0.8 * p['sharpen']:.2f}:5:5:0")
    if p["vignette"]:
        angle = min(max(0.12 + 0.55 * p["vignette"], 0.1), 0.9)
        f.append(f"vignette=angle={angle:.2f}")
    if p["grain"]:
        f.append(f"noise=alls={p['grain']:.0f}:allf=t")
    return ",".join(f)


def add_args(p):
    p.add_argument("--preset", default="cinematic", choices=sorted(PRESETS))
    for k, typ in (("contrast", float), ("saturation", float), ("brightness", float),
                   ("gamma", float), ("s_curve", float), ("fade", float), ("warmth", float),
                   ("teal", float), ("orange", float), ("vignette", float), ("grain", float),
                   ("sharpen", float)):
        p.add_argument("--" + k.replace("_", "-"), dest=k, type=typ)
    p.add_argument("--bw", action="store_true", default=False)


def cmd_presets(_a):
    for name, v in PRESETS.items():
        print(f"{name}: " + ", ".join(f"{k}={x}" for k, x in v.items()))


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    p = params(a)
    vf = build_filter(p)
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src), "-vf", vf,
         "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", os.path.abspath(a.dst)],
        check=True, capture_output=True)
    print(f"Preset: {a.preset}")
    print("Settings: " + ", ".join(f"{k}={v}" for k, v in p.items() if v != BASE[k]))
    print(f"Saved: {os.path.abspath(a.dst)}")


def cmd_compare(a):
    """Write a PNG with the original and graded frame side by side."""
    p = params(a)
    vf = build_filter(p)
    flt = f"[0:v]split[a][b];[b]{vf}[g];[a][g]hstack=2,scale=1000:-1"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-ss", str(a.at), "-i", os.path.abspath(a.src),
         "-frames:v", "1", "-filter_complex", flt, os.path.abspath(a.out)],
        check=True, capture_output=True)
    print(f"Saved: {os.path.abspath(a.out)} (left: original, right: graded)")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("dst")
    add_args(p)
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("compare")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--at", type=float, default=3.0)
    add_args(p)
    p.set_defaults(fn=cmd_compare)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
