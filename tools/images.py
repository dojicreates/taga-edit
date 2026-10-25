"""Place a logo or image on the video (from the IMAGES folder).

Usage:
    python tools/images.py list
    python tools/images.py render OUTPUT/video.mp4 OUTPUT/video_logo.mp4 --image logo.png
        [--corner top-right] [--size 0.11] [--start 0.3] [--end <end>] [--opacity 1.0]

Images are taken only from the IMAGES folder. The script is smart about the following:
  - If an image has no transparency but a black or white background (common for logos), the
    background is removed automatically and the edges stay clean. Use --no-key to keep the full square.
  - Empty transparent borders are trimmed, so --size refers to the logo itself.
  - It is placed inside a safe area (not at the very edge, so social-app UI does not cover it).
  - It fades in at the start and fades out at the end.

--corner   top-right (default) | top-left | bottom-right | bottom-left | center-top
--size     image width as a fraction of the video width (default 0.11)
--margin   distance from the edge as a fraction of the width (default 0.04); the top gets an extra
           0.01 of the height (safe area)
--start/--end   seconds during which it is visible (default: the whole video, starting at 0.3 s)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMAGES = os.path.join(ROOT, "IMAGES")
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")
EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def image_files():
    if not os.path.isdir(IMAGES):
        sys.exit(f"The folder {IMAGES} does not exist.")
    f = sorted(x for x in os.listdir(IMAGES) if x.lower().endswith(EXT))
    if not f:
        sys.exit("There is no image in IMAGES.")
    return f


def describe(path):
    im = Image.open(path)
    has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
    rgb = np.asarray(im.convert("RGB")).astype(np.int32)
    h, w = rgb.shape[:2]
    corners = np.array([rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]])
    bg = None
    if not has_alpha:
        if corners.max() <= 24:
            bg = "black"
        elif corners.min() >= 231:
            bg = "white"
    return im.size, has_alpha, bg


def trim(im, pad=0.04):
    """Trim the empty (transparent) border so the size applies to the logo itself."""
    box = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if not box:
        return im
    p = int(max(box[2] - box[0], box[3] - box[1]) * pad)
    box = (max(box[0] - p, 0), max(box[1] - p, 0),
           min(box[2] + p, im.width), min(box[3] + p, im.height))
    return im.crop(box)


def prepare(path, key, out_png):
    """Write an RGBA PNG; removes a black/white background when needed."""
    im = Image.open(path)
    size, has_alpha, bg = describe(path)
    if has_alpha:
        trim(im.convert("RGBA")).save(out_png)
        return "has a transparent background"
    rgb = np.asarray(im.convert("RGB")).astype(np.float64)
    if key and bg == "black":
        mx = rgb.max(axis=2)
        solid = mx[mx > 40]
        fg = np.percentile(solid, 95) if solid.size else 255.0
        alpha = np.clip(mx / fg, 0, 1)
        safe = np.where(alpha[..., None] > 0.01, alpha[..., None], 1.0)
        color = np.clip(rgb / safe, 0, 255)
        note = "removed the black background"
    elif key and bg == "white":
        mn = rgb.min(axis=2)
        solid = mn[mn < 215]
        fg = np.percentile(solid, 5) if solid.size else 0.0
        alpha = np.clip((255.0 - mn) / max(255.0 - fg, 1.0), 0, 1)
        safe = np.where(alpha[..., None] > 0.01, alpha[..., None], 1.0)
        color = np.clip(255.0 - (255.0 - rgb) / safe, 0, 255)
        note = "removed the white background"
    else:
        alpha = np.ones(rgb.shape[:2])
        color = rgb
        note = "background left as is"
    out = np.dstack([color, alpha * 255]).astype(np.uint8)
    trim(Image.fromarray(out, "RGBA")).save(out_png)
    return note


def video_info(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return j["streams"][0]["width"], j["streams"][0]["height"], float(j["format"]["duration"])


def cmd_list(_a):
    for f in image_files():
        size, alpha, bg = describe(os.path.join(IMAGES, f))
        extra = "has a transparent background" if alpha else (
            f"{bg} background (removed automatically)" if bg else "solid background")
        print(f"{f}  {size[0]}x{size[1]}  {extra}")


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    names = image_files()
    name = a.image or (names[0] if len(names) == 1 else None)
    if not name or name not in names:
        sys.exit(f"Choose an image with --image. Available: {', '.join(names)}")
    vw, vh, dur = video_info(a.src)
    start = a.start
    end = a.end if a.end is not None else dur
    end = min(end, dur)
    if end - start < 1.0:
        sys.exit("The image would be visible for less than 1 s.")

    lw = int(vw * a.size) // 2 * 2
    mx = int(vw * a.margin)
    my = int(vw * a.margin + vh * 0.01)
    pos = {
        "top-right": (f"W-w-{mx}", f"{my}"), "top-left": (f"{mx}", f"{my}"),
        "bottom-right": (f"W-w-{mx}", f"H-h-{my}"), "bottom-left": (f"{mx}", f"H-h-{my}"),
        "center-top": ("(W-w)/2", f"{my}"),
    }[a.corner]

    tmp = tempfile.mkdtemp(prefix="img_")
    png = os.path.join(tmp, "logo.png")
    try:
        note = prepare(os.path.join(IMAGES, name), not a.no_key, png)
        fin, fout = 0.4, 0.5
        flt = (
            f"[1:v]format=rgba,scale={lw}:-1:flags=lanczos,"
            f"colorchannelmixer=aa={a.opacity},setpts=PTS+{start}/TB,"
            f"fade=t=in:st={start}:d={fin}:alpha=1,"
            f"fade=t=out:st={end - fout}:d={fout}:alpha=1[l];"
            f"[0:v][l]overlay=x={pos[0]}:y={pos[1]}:eof_action=pass:"
            f"enable='between(t,{start},{end})'[v]"
        )
        subprocess.run(
            [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src),
             "-loop", "1", "-framerate", "30", "-t", f"{end}", "-i", png,
             "-filter_complex", flt, "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy",
             "-movflags", "+faststart", os.path.abspath(a.dst)],
            check=True, capture_output=True)
    finally:
        for f in os.listdir(tmp):
            os.remove(os.path.join(tmp, f))
        os.rmdir(tmp)
    print(f"Image: {name} ({note}), {a.corner}, {lw}px wide, {start:.1f}s to {end:.1f}s")
    print(f"Saved: {os.path.abspath(a.dst)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--image")
    p.add_argument("--corner", default="top-right",
                   choices=["top-right", "top-left", "bottom-right", "bottom-left", "center-top"])
    p.add_argument("--size", type=float, default=0.11)
    p.add_argument("--margin", type=float, default=0.04)
    p.add_argument("--start", type=float, default=0.3)
    p.add_argument("--end", type=float)
    p.add_argument("--opacity", type=float, default=1.0)
    p.add_argument("--no-key", action="store_true", help="do not remove a black/white background")
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
