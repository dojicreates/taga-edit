"""Add background music (from the MB folder) under the voice.

Usage:
    python tools/music.py list
    python tools/music.py render OUTPUT/video.mp4 OUTPUT/video_music.mp4 [--track song.mp3] [--start 0] [--level -3]

The music is:
  - taken only from the MB folder (mp3, wav, m4a, flac, ogg)
  - set to a level relative to the loudness of the voice (not the loudness of the file)
  - optionally lowered while someone speaks (ducking, --duck-ratio); off by default
  - faded in at the start, faded out at the end, and looped if it is shorter than the video

--track       file name in MB (default: the first one alphabetically, or a random one with --random)
--start       second of the track to start from (default 0)
--duck-ratio  ducking strength: 1 = no ducking (default), 1.4 = very light, 2 = medium, 6 = strong
--level       average music level relative to the average voice level, in dB (default -3)
"""
import argparse
import os
import random
import re
import subprocess
import sys

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MB = os.path.join(ROOT, "MB")
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")
EXT = (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac")


def tracks():
    if not os.path.isdir(MB):
        sys.exit(f"The folder {MB} does not exist.")
    t = sorted(f for f in os.listdir(MB) if f.lower().endswith(EXT))
    if not t:
        sys.exit("There is no audio file in MB.")
    return t


def duration(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of",
         "default=nw=1:nk=1", path], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def mean_volume(path, ss=None, t=None):
    cmd = [FFMPEG, "-hide_banner"]
    if ss is not None:
        cmd += ["-ss", str(ss)]
    if t is not None:
        cmd += ["-t", str(t)]
    cmd += ["-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    if not m:
        sys.exit(f"Could not measure the audio level of {path}.")
    return float(m.group(1))


def cmd_list(_a):
    for f in tracks():
        p = os.path.join(MB, f)
        print(f"{f}  ({duration(p):.0f}s, {mean_volume(p):.1f} dB avg)")


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    available = tracks()
    if a.track:
        if a.track not in available:
            sys.exit(f"{a.track} is not in MB. Available: {', '.join(available)}")
        name = a.track
    else:
        name = random.choice(available) if a.random else available[0]
    music = os.path.join(MB, name)

    vdur = duration(a.src)
    mdur = duration(music)
    voice = mean_volume(a.src)
    seg = min(vdur, max(mdur - a.start, 1))
    mus = mean_volume(music, a.start, seg)
    gain = voice + a.level - mus
    fade_out = min(1.8, vdur / 4)

    # If the track is shorter than the video, loop it.
    loop = "aloop=loop=-1:size=2147483647," if mdur - a.start < vdur else ""
    flt = (
        f"[1:a]aresample=48000,{loop}atrim=start={a.start}:duration={vdur},asetpts=PTS-STARTPTS,"
        f"volume={gain:.2f}dB,afade=t=in:st=0:d=1.0,afade=t=out:st={vdur - fade_out:.2f}:d={fade_out:.2f},"
        f"pan=stereo|c0=c0|c1=c1[m];"
        f"[0:a]aresample=48000,asplit=2[v][k];"
        + (f"[m][k]sidechaincompress=threshold=0.12:ratio={a.duck_ratio}:attack=20:release=500:"
           f"makeup=1:level_sc=1[md];" if a.duck_ratio > 1 else "[m]anull[md];[k]anullsink;")
        + f"[v][md]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=false[a]"
    )
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src), "-i", music,
         "-filter_complex", flt, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
         os.path.abspath(a.dst)],
        check=True, capture_output=True)
    print(f"Music: {name} (starts at {a.start:.0f}s, {gain:+.1f} dB)")
    print(f"Voice (avg): {voice:.1f} dB | Music (avg before ducking): {voice + a.level:.1f} dB")
    print(f"Saved: {os.path.abspath(a.dst)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--track")
    p.add_argument("--random", action="store_true")
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--level", type=float, default=-3.0)
    p.add_argument("--duck-ratio", type=float, default=1.0,
                   help="ducking strength (1 = none, 2 = medium, 6 = strong); default 1 (no ducking)")
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
