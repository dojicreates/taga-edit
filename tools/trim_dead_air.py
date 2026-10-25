"""Remove dead air (silent gaps) from a video with FFmpeg.

Usage:
    python tools/trim_dead_air.py INPUT/video.mp4 OUTPUT/video_trimmed.mp4
        [--noise -35] [--min-silence 0.2] [--pad 0.04]

--noise        dB threshold; anything quieter than this counts as silence
--min-silence  shortest silence (seconds) that gets cut
--pad          seconds of margin kept on each side of every cut

Needs FFmpeg 7 or newer (uses the -/filter_complex option).
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

from _bin import find

FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")


def duration(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", path],
        capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def has_audio(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True).stdout
    return bool(out.strip())


def detect_silences(path, noise, min_silence):
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", path, "-vn", "-af",
         f"silencedetect=noise={noise}dB:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", r.stderr)]
    silences = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        silences.append((max(s, 0.0), e))
    return silences


def keep_segments(silences, total, pad):
    segs, cursor = [], 0.0
    for s, e in silences:
        end = min(s + pad, total)
        if end - cursor > 0.05:
            segs.append((cursor, end))
        cursor = total if e is None else max(e - pad, cursor)
    if total - cursor > 0.05:
        segs.append((cursor, total))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--noise", type=float, default=-35)
    ap.add_argument("--min-silence", type=float, default=0.2)
    ap.add_argument("--pad", type=float, default=0.04)
    a = ap.parse_args()

    if not has_audio(a.src):
        sys.exit("This video has no audio, so there is no dead air to detect.")
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")

    total = duration(a.src)
    segs = keep_segments(detect_silences(a.src, a.noise, a.min_silence), total, a.pad)
    if not segs:
        sys.exit("The whole video is silent; nothing would be left.")

    parts = []
    for i, (s, e) in enumerate(segs):
        parts.append(f"[0:v]trim=start={s:.3f}:end={e:.3f},setpts=PTS-STARTPTS[v{i}];")
        parts.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}];")
    joined = "".join(f"[v{i}][a{i}]" for i in range(len(segs)))
    parts.append(f"{joined}concat=n={len(segs)}:v=1:a=1[v][a]")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write("\n".join(parts))
        script = f.name
    try:
        subprocess.run(
            [FFMPEG, "-hide_banner", "-y", "-i", a.src,
             "-/filter_complex", script, "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-crf", "18", "-preset", "medium",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", a.dst],
            check=True)
    finally:
        os.remove(script)

    new = duration(a.dst)
    print(f"Original: {total:.1f}s -> Trimmed: {new:.1f}s "
          f"(removed: {total - new:.1f}s, {len(segs)} segments)")
    print(f"Saved: {os.path.abspath(a.dst)}")


if __name__ == "__main__":
    main()
