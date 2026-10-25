"""Join the clips in INPUT (CLIP 1, CLIP 2, CLIP 3, ...) into one video, with transitions.

Usage:
    python tools/join_clips.py plan [--folder INPUT]
    python tools/join_clips.py render <dst.mp4> [--folder INPUT] [--transition mix] [--trim]

The order comes from the file names in natural order (CLIP 2 before CLIP 10).
"plan" does not render; it only shows the order, the warnings, and whether anything needs joining.
If there is only one video in the folder, there is nothing to join.

Transitions between clips (--transition, default "mix"):
  zoom    fast zoom-through with blur at the end of a clip, settling back to normal at the start of the next
  flash   short white flash between two clips
  dip     quick fade to black and back
  mix     alternates zoom and flash (default)
  none    no transition (hard cut)
Clips never overlap: the sound is continuous (no overlapping voices, no lost words); the transition
lives in the last 0.2 s of the earlier clip and the first 0.2 s of the next one, so the total length
does not shrink. --trim: remove the dead air of every clip first (trim_dead_air.py) before joining,
so trimming never cuts through a transition afterwards.

"render" makes one video with the same resolution, fps and audio format (taken from the first clip)
so the join is seamless. Write dst to a temporary folder, not to OUTPUT.
"""
import argparse
import json
import os
import re
import subprocess
import sys

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")
EXT = (".mp4", ".mov", ".mkv", ".m4v", ".avi", ".webm")


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def find_clips(folder):
    files = [f for f in os.listdir(folder) if f.lower().endswith(EXT)]
    return sorted(files, key=natural_key)


def probe(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate,sample_rate,channels:format=duration",
         "-of", "json", path], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
    num, den = v["r_frame_rate"].split("/")
    return {"w": v["width"], "h": v["height"], "fps": float(num) / float(den),
            "audio": a is not None, "dur": float(j["format"]["duration"])}


def numbers(files):
    nums = []
    for f in files:
        m = re.findall(r"\d+", os.path.splitext(f)[0])
        nums.append(int(m[-1]) if m else None)
    return nums


def cmd_plan(a):
    files = find_clips(a.folder)
    if not files:
        sys.exit("There is no video in the folder.")
    info = [probe(os.path.join(a.folder, f)) for f in files]
    if len(files) == 1:
        print(f"Only one video ({files[0]}); nothing to join.")
        return
    total = sum(i["dur"] for i in info)
    print(f"{len(files)} clips to join ({total:.1f}s in total):")
    for k, (f, i) in enumerate(zip(files, info), 1):
        print(f"  {k}. {f}  {i['w']}x{i['h']} {i['fps']:.0f}fps {i['dur']:.1f}s"
              f"{'' if i['audio'] else '  (no audio)'}")
    nums = numbers(files)
    if None in nums:
        print("WARNING: a clip has no number in its name; the order is alphabetical.")
    else:
        miss = [n for n in range(nums[0], nums[-1] + 1) if n not in nums]
        if miss:
            print(f"WARNING: numbers missing from the sequence: {miss}")
        if len(set(nums)) != len(nums):
            print("WARNING: two clips share the same number.")
    first = info[0]
    diff = [f for f, i in zip(files, info)
            if (i["w"], i["h"]) != (first["w"], first["h"]) or abs(i["fps"] - first["fps"]) > 0.5]
    if diff:
        print(f"NOTE: {', '.join(diff)} differ in resolution or fps; they are conformed to the first clip.")


TRANSITION_D = 0.2   # seconds
ZOOM_AMOUNT = 0.18


def side_kinds(n, mode):
    """Transition kind at every boundary (n-1 boundaries)."""
    if mode == "none":
        return []
    cycle = {"zoom": ["zoom"], "flash": ["flash"], "dip": ["dip"], "mix": ["zoom", "flash"]}[mode]
    return [cycle[i % len(cycle)] for i in range(n - 1)]


def clip_filters(k, n, dur, w, h, fps, kinds):
    """Filters for one clip: normalise + effect at the start (if there is a previous clip) and at the end (if there is a next one)."""
    d = TRANSITION_D
    f = [f"scale={w}:{h}:force_original_aspect_ratio=decrease",
         f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2", "setsar=1", f"fps={fps}", "setpts=PTS-STARTPTS"]
    in_kind = kinds[k - 1] if k > 0 and kinds else None
    out_kind = kinds[k] if k < n - 1 and kinds else None
    t_out = dur - d

    if "zoom" in (in_kind, out_kind):
        parts = []
        if out_kind == "zoom":
            parts.append(f"gt(t,{t_out:.3f})*pow((t-{t_out:.3f})/{d},2)")
        if in_kind == "zoom":
            parts.append(f"lt(t,{d})*pow(1-t/{d},2)")
        z = f"(1+{ZOOM_AMOUNT}*({'+'.join(parts)}))"
        f.append(f"scale=w='trunc({w}*{z}/2)*2':h='trunc({h}*{z}/2)*2':eval=frame:flags=bicubic")
        f.append(f"crop=w={w}:h={h}:x='(iw-{w})/2':y='(ih-{h})*0.45'")
        en = []
        if out_kind == "zoom":
            en.append(f"gt(t,{dur - d / 2:.3f})")
        if in_kind == "zoom":
            en.append(f"lt(t,{d / 2:.3f})")
        f.append(f"gblur=sigma=12:steps=2:enable='{'+'.join(en)}'")
        f.append("setsar=1")
    if "flash" in (in_kind, out_kind):
        parts = []
        if out_kind == "flash":
            parts.append(f"gt(t,{t_out:.3f})*pow((t-{t_out:.3f})/{d},2)")
        if in_kind == "flash":
            parts.append(f"lt(t,{d})*pow(1-t/{d},2)")
        f.append(f"eq=brightness='min(1,{'+'.join(parts)})':eval=frame")
    if out_kind == "dip":
        f.append(f"fade=t=out:st={t_out:.3f}:d={d}")
    if in_kind == "dip":
        f.append(f"fade=t=in:st=0:d={d}")
    f.append("format=yuv420p")
    return ",".join(f)


def trim_clips(folder, files, tmp):
    """Remove the dead air of every clip with trim_dead_air.py."""
    out = []
    for f in files:
        dst = os.path.join(tmp, "t_" + os.path.splitext(f)[0] + ".mp4")
        r = subprocess.run([sys.executable, os.path.join(HERE, "trim_dead_air.py"),
                            os.path.join(folder, f), dst],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"Could not trim {f}: {r.stderr.strip() or r.stdout.strip()}")
        print("  trim:", f, "->", r.stdout.strip().splitlines()[0])
        out.append(dst)
    return out


def cmd_render(a):
    import shutil
    import tempfile
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    names = find_clips(a.folder)
    if len(names) < 2:
        sys.exit("Not enough clips to join (at least two are needed).")
    tmp = tempfile.mkdtemp(prefix="join_")
    try:
        paths = [os.path.join(a.folder, f) for f in names]
        if a.trim:
            paths = trim_clips(a.folder, names, tmp)
        info = [probe(p) for p in paths]
        w, h, fps = info[0]["w"], info[0]["h"], round(info[0]["fps"])
        n = len(paths)
        kinds = side_kinds(n, a.transition)
        cmd = [FFMPEG, "-hide_banner", "-y"]
        for p in paths:
            cmd += ["-i", p]
        parts, labels, extra = [], [], 0
        for k, i in enumerate(info):
            parts.append(f"[{k}:v]{clip_filters(k, n, i['dur'], w, h, fps, kinds)}[v{k}]")
            af = ["aresample=48000", "aformat=channel_layouts=stereo"]
            if k > 0:
                af.append("afade=t=in:st=0:d=0.012")
            if k < n - 1:
                af.append(f"afade=t=out:st={max(i['dur'] - 0.012, 0):.3f}:d=0.012")
            if i["audio"]:
                parts.append(f"[{k}:a]{','.join(af)}[a{k}]")
            else:
                idx = n + extra
                extra += 1
                cmd += ["-f", "lavfi", "-t", f"{i['dur']}", "-i", "anullsrc=r=48000:cl=stereo"]
                parts.append(f"[{idx}:a]anull[a{k}]")
            labels.append(f"[v{k}][a{k}]")
        parts.append("".join(labels) + f"concat=n={n}:v=1:a=1[v][a]")
        cmd += ["-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
                os.path.abspath(a.dst)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(r.stderr[-1500:])
        dur = sum(i["dur"] for i in info)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{n} clips joined: {', '.join(names)}")
    if kinds:
        print("Transitions: " + ", ".join(f"{names[i]} -> {names[i + 1]}: {kd}"
                                          for i, kd in enumerate(kinds)))
    print(f"Total length: {dur:.1f}s | {w}x{h} {fps}fps")
    print(f"Saved: {os.path.abspath(a.dst)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--folder", default=os.path.join(ROOT, "INPUT"))
    p.set_defaults(fn=cmd_plan)
    p = sub.add_parser("render")
    p.add_argument("dst")
    p.add_argument("--folder", default=os.path.join(ROOT, "INPUT"))
    p.add_argument("--transition", default="mix", choices=["mix", "zoom", "flash", "dip", "none"])
    p.add_argument("--trim", action="store_true",
                   help="remove the dead air of each clip before joining")
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
