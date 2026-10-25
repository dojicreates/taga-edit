"""Kinetic text for the emphasised moments of a video (ASS subtitles burned in by FFmpeg).

Two steps:

1) Get the transcript with a timestamp for every word:
    python tools/kinetic.py words OUTPUT/video.mp4 words.json

2) After choosing the emphasis items (emphasis.json), render:
    python tools/kinetic.py render OUTPUT/video.mp4 emphasis.json OUTPUT/video_kinetic.mp4

emphasis.json is a list of:
    {"text": "FREE", "start": 3.2, "end": 4.4, "style": "pop"}
style:
    pop    grows slightly past its size, then settles (default)
    slam   starts huge and drops into place with a little shake
    box    text inside a colourful box
    type   letters appear one by one
    slide  rises from below
Optional fields per item: "color" (hex RGB), "rot" (angle in degrees), "y" (position from the top, 0-1).
Without "color" the palette rotates. Without "rot" a slight tilt rotates.
"""
import argparse
import json
import os
import subprocess
import sys

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")

PALETTE = ["FFE500", "FF3B6B", "3BD9FF", "7CFF6B", "FFFFFF"]
TILTS = [-4, 3, -3, 4, 0]


def ass_time(t):
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def bgr(hex_rgb):
    h = hex_rgb.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&"


def video_size(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:stream_side_data=rotation", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)
    s = info["streams"][0]
    w, h = s["width"], s["height"]
    for sd in s.get("side_data_list", []):
        if abs(sd.get("rotation", 0)) in (90, 270):
            w, h = h, w
    return w, h


def wrap(text):
    """Split into two lines when long."""
    words = text.split()
    if len(text) <= 12 or len(words) < 2:
        return [text]
    best, gap = 1, 10**9
    for i in range(1, len(words)):
        d = abs(len(" ".join(words[:i])) - len(" ".join(words[i:])))
        if d < gap:
            best, gap = i, d
    return [" ".join(words[:best]), " ".join(words[best:])]


def fit_font(lines, width, base, pad=0.0):
    longest = max(len(l) for l in lines)
    return int(min(base, (0.84 - pad) * width / (0.74 * longest)))


def make_events(items, w, h, y_frac, base_size, default_color):
    events = []
    cx = w // 2
    for idx, it in enumerate(items):
        text = it["text"].strip().upper()
        start, end = float(it["start"]), float(it["end"])
        if end - start < 0.5:
            end = start + 0.5
        style = it.get("style", "pop")
        color = bgr(it["color"]) if it.get("color") else bgr(PALETTE[idx % len(PALETTE)])
        rot = it.get("rot", TILTS[idx % len(TILTS)])
        cy = int(h * float(it.get("y", y_frac)))
        lines = wrap(text)
        size = fit_font(lines, w, base_size, pad=0.08 if style == "box" else 0.0)
        joined = "\\N".join(lines)
        sname = "KB" if style == "box" else "K"
        base = f"\\an5\\fs{size}\\frz{rot}"
        if style == "box":
            base += f"\\1c&H101010&\\3c{color}"
        else:
            base += f"\\1c{color}"

        if style == "type":
            vis, i = [], 0
            while i < len(joined):
                if joined.startswith("\\N", i):
                    i += 2
                    continue
                vis.append(i)
                i += 1
            count = len(vis)
            reveal = min(0.7, max(0.25, count * 0.045))
            step = reveal / count
            for k in range(1, count + 1):
                cut = vis[k - 1] + 1
                shown, hidden = joined[:cut], joined[cut:]
                body = shown + ("{\\alpha&HFF&}" + hidden if hidden else "")
                s = start + (k - 1) * step
                e = start + k * step if k < count else end
                fade = "\\fad(0,120)" if k == count else ""
                events.append((s, e, sname, f"{{\\pos({cx},{cy}){base}{fade}}}{body}"))
        elif style == "slide":
            y0 = cy + int(h * 0.05)
            tags = (f"\\move({cx},{y0},{cx},{cy},0,180)\\alpha&HFF&"
                    f"\\t(0,160,\\alpha&H00&){base}\\fad(0,120)")
            events.append((start, end, sname, f"{{{tags}}}{joined}"))
        elif style == "slam":
            tags = (f"\\pos({cx},{cy}){base}\\fscx320\\fscy320\\alpha&HFF&\\frz{rot * 3}"
                    f"\\t(0,110,\\fscx100\\fscy100\\alpha&H00&\\frz{rot})"
                    f"\\t(110,150,\\frz{rot + 4})\\t(150,195,\\frz{rot - 2})"
                    f"\\t(195,240,\\frz{rot})\\fad(0,120)")
            events.append((start, end, sname, f"{{{tags}}}{joined}"))
        else:  # pop at box
            tags = (f"\\pos({cx},{cy}){base}\\fscx55\\fscy55\\alpha&HFF&"
                    f"\\t(0,110,\\fscx125\\fscy125\\alpha&H00&)"
                    f"\\t(110,220,\\fscx100\\fscy100)\\fad(0,120)")
            events.append((start, end, sname, f"{{{tags}}}{joined}"))
    return events


def write_ass(events, w, h, path):
    outline = max(6, w // 110)
    head = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {w}\nPlayResY: {h}\nWrapStyle: 2\nScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: K,Arial Black,100,&H0000E5FF,&H000000FF,&H00000000,&H90000000,"
        f"0,0,0,0,100,100,1,0,1,{outline},{max(4, w // 200)},5,40,40,40,1\n"
        f"Style: KB,Arial Black,100,&H00101010,&H000000FF,&H0000E5FF,&H90000000,"
        f"0,0,0,0,100,100,1,0,3,{max(16, w // 60)},0,5,40,40,40,1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head)
        for s, e, sname, text in events:
            f.write(f"Dialogue: 1,{ass_time(s)},{ass_time(e)},{sname},,0,0,0,,{text}\n")


def cmd_words(a):
    from captions import transcribe
    if os.path.exists(a.out):
        sys.exit(f"{a.out} already exists.")
    words = transcribe(a.src, a.model, a.language)
    data = [{"word": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
            for w in words]
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(data)} words -> {os.path.abspath(a.out)}")


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    with open(a.emphasis, encoding="utf-8-sig") as f:
        items = json.load(f)
    if not items:
        sys.exit("The emphasis list is empty.")
    w, h = video_size(a.src)
    events = make_events(items, w, h, a.y, int(w * a.size), bgr(a.color))
    ass_path = os.path.splitext(os.path.abspath(a.dst))[0] + ".ass"
    write_ass(events, w, h, ass_path)
    ass_dir, ass_name = os.path.split(ass_path)
    subprocess.run(
        [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src),
         "-vf", f"ass={ass_name}", "-c:v", "libx264", "-crf", "18",
         "-preset", "medium", "-c:a", "copy", "-movflags", "+faststart",
         os.path.abspath(a.dst)],
        check=True, cwd=ass_dir)
    print(f"{len(items)} emphasis items")
    print(f"Saved: {os.path.abspath(a.dst)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("words")
    p.add_argument("src")
    p.add_argument("out")
    p.add_argument("--model", default="medium")
    p.add_argument("--language", default="auto")
    p.set_defaults(fn=cmd_words)

    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("emphasis")
    p.add_argument("dst")
    p.add_argument("--y", type=float, default=0.14, help="position from the top (0-1)")
    p.add_argument("--size", type=float, default=0.15, help="font size as a fraction of the width")
    p.add_argument("--color", default="FFE500", help="default colour (hex RGB)")
    p.set_defaults(fn=cmd_render)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
