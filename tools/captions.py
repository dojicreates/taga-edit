"""Create captions (SRT) from the speech in a video, and optionally burn them into the video.

Usage:
    python tools/captions.py OUTPUT/video.mp4                 # writes OUTPUT/video.srt
    python tools/captions.py OUTPUT/video.mp4 --burn OUTPUT/video_captioned.mp4

--model      whisper model (default: medium). Smaller = faster but less accurate.
--language   spoken language code, e.g. en, tl, es (default: auto = detect automatically).
--max-words  most words in one caption (default: 4; 3 is recommended for the fancy style)
--font-size  font size when burning the plain style (default: 14)
--margin-v   height from the bottom when burning the plain style (default: 90)
--style      fancy (default): word-by-word highlight | plain: simple white text
"""
import argparse
import os
import subprocess
import sys

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = find("ffmpeg")


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def load_model(name):
    from faster_whisper import WhisperModel
    try:
        return WhisperModel(name, device="cuda", compute_type="float16"), "GPU"
    except Exception:
        return WhisperModel(name, device="cpu", compute_type="int8"), "CPU"


def transcribe(path, model_name, language):
    model, dev = load_model(model_name)
    print(f"Model: {model_name} ({dev})", flush=True)
    try:
        segments, _ = model.transcribe(
            path, language=None if language == "auto" else language,
            word_timestamps=True, vad_filter=True)
        words = [w for seg in segments for w in seg.words]
    except Exception as e:
        if dev == "GPU":
            print(f"The GPU failed ({e}); falling back to the CPU.", flush=True)
            from faster_whisper import WhisperModel
            model = WhisperModel(model_name, device="cpu", compute_type="int8")
            segments, _ = model.transcribe(
                path, language=None if language == "auto" else language,
                word_timestamps=True, vad_filter=True)
            words = [w for seg in segments for w in seg.words]
        else:
            raise
    return words


def build_captions(words, max_words, max_dur=2.8):
    caps, cur = [], []
    for w in words:
        cur.append(w)
        text = w.word.strip()
        ends_phrase = text.endswith((".", "?", "!", ","))
        too_long = len(cur) >= max_words or (w.end - cur[0].start) >= max_dur
        if too_long or ends_phrase:
            caps.append(cur)
            cur = []
    if cur:
        caps.append(cur)
    out = []
    for c in caps:
        text = " ".join(w.word.strip() for w in c).strip()
        if text:
            out.append((c[0].start, c[-1].end, text, c))
    return out


ACCENTS = ["00E5FF", "6B3BFF", "FFE500", "6BFF7C", "FF9A3B"]  # BGR: yellow, pink, cyan, green, blue


def ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def video_size(path):
    import json
    probe = find("ffprobe")
    out = subprocess.run(
        [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:stream_side_data=rotation", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    w, h = s["width"], s["height"]
    for sd in s.get("side_data_list", []):
        if abs(sd.get("rotation", 0)) in (90, 270):
            w, h = h, w
    return w, h


def write_ass(caps, w, h, path, size_frac, y_frac):
    """Short-form-video style captions: UPPERCASE, bold, every word is highlighted
    while it is spoken (changes colour and grows slightly), and each line pops in.
    The highlight colour changes with every caption."""
    size = int(w * size_frac)
    outline = max(6, w // 110)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: C,Arial Black,{size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,"
        f"0,0,0,0,100,100,1,0,1,{outline},{max(4, w // 200)},5,60,60,60,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    cx, cy = w // 2, int(h * y_frac)
    lines = []
    for ci, (s, e, _text, words) in enumerate(caps):
        accent = ACCENTS[ci % len(ACCENTS)]
        toks = [wd.word.strip().upper() for wd in words]
        fs = min(size, int(0.90 * w / (0.74 * max(len(" ".join(toks)), 1))))
        for k, wd in enumerate(words):
            ws = wd.start
            we = words[k + 1].start if k + 1 < len(words) else e
            if we - ws < 0.05:
                continue
            parts = []
            for j, tok in enumerate(toks):
                if j == k:
                    parts.append(f"{{\\1c&H{accent}&\\fscx115\\fscy115}}{tok}{{\\r}}")
                else:
                    parts.append(tok)
            body = " ".join(parts)
            pop = ""
            if k == 0:
                pop = "\\fscx80\\fscy80\\alpha&HFF&\\t(0,90,\\fscx100\\fscy100\\alpha&H00&)"
            lines.append(f"Dialogue: 0,{ass_time(ws)},{ass_time(we)},C,,0,0,0,,"
                         f"{{\\an5\\pos({cx},{cy})\\fs{fs}{pop}}}{body}")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(lines) + "\n")


def burn_ass(src, ass, dst):
    if os.path.exists(dst):
        sys.exit(f"{dst} already exists. Choose another name.")
    ass_dir, ass_name = os.path.split(os.path.abspath(ass))
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(src),
         "-vf", f"ass={ass_name}", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "copy", "-movflags", "+faststart", os.path.abspath(dst)],
        check=True, cwd=ass_dir)


def write_srt(caps, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, (s, e, t, _w) in enumerate(caps, 1):
            f.write(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n\n")


def burn(src, srt, dst, font_size, margin_v):
    if os.path.exists(dst):
        sys.exit(f"{dst} already exists. Choose another name.")
    # The subtitles filter is picky about Windows paths; run it inside the SRT folder.
    srt_dir, srt_name = os.path.split(os.path.abspath(srt))
    style = (f"FontName=Arial,FontSize={font_size},Bold=1,PrimaryColour=&H00FFFFFF,"
             f"OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,"
             f"Alignment=2,MarginV={margin_v}")
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(src),
         "-vf", f"subtitles={srt_name}:force_style='{style}'",
         "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-c:a", "copy", "-movflags", "+faststart", os.path.abspath(dst)],
        check=True, cwd=srt_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--srt", help="SRT path (default: next to the video)")
    ap.add_argument("--burn", metavar="DST", help="burn the captions into a new video")
    ap.add_argument("--model", default="medium")
    ap.add_argument("--language", default="auto")
    ap.add_argument("--max-words", type=int, default=4)
    ap.add_argument("--font-size", type=int, default=14)
    ap.add_argument("--margin-v", type=int, default=90)
    ap.add_argument("--style", choices=["fancy", "plain"], default="fancy",
                    help="fancy = highlight every word (default); plain = simple white text")
    ap.add_argument("--size", type=float, default=0.10, help="fancy: font size as a fraction of the width")
    ap.add_argument("--y", type=float, default=0.72, help="fancy: position from the top (0-1)")
    a = ap.parse_args()

    srt = a.srt or os.path.splitext(a.src)[0] + ".srt"
    if os.path.exists(srt):
        sys.exit(f"{srt} already exists. Choose another name with --srt.")

    words = transcribe(a.src, a.model, a.language)
    if not words:
        sys.exit("No speech was detected.")
    caps = build_captions(words, a.max_words)
    write_srt(caps, srt)
    print(f"{len(caps)} captions -> {os.path.abspath(srt)}")

    if a.burn and a.style == "fancy":
        w, h = video_size(a.src)
        ass = os.path.splitext(os.path.abspath(a.burn))[0] + "_captions.ass"
        write_ass(caps, w, h, ass, a.size, a.y)
        burn_ass(a.src, ass, a.burn)
        print(f"Saved: {os.path.abspath(a.burn)}")
    elif a.burn:
        burn(a.src, srt, a.burn, a.font_size, a.margin_v)
        print(f"Saved: {os.path.abspath(a.burn)}")


if __name__ == "__main__":
    main()
