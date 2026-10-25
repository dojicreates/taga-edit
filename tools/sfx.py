"""Gentle sound effects for kinetic text and morphing shapes (no background music).

The sounds are synthesised in code (nothing is downloaded, no copyright), short, and mixed in
quieter than the voice so they never get in the way.

Usage:
    python tools/sfx.py render OUTPUT/video.mp4 OUTPUT/video_sfx.mp4 --emphasis emphasis.json --morph morph.json
    python tools/sfx.py preview OUTPUT/sfx_preview     # write sample WAV files to listen to

It reads the same emphasis.json (kinetic.py) and morph.json (morph.py), so the sound always
matches the animation.

--level   how loud the SFX are relative to the average voice level, in dB (default -6).
          More negative = quieter. Each sound is also scaled on its own (slam louder,
          ticks quieter).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import wave

import numpy as np

from _bin import find

HERE = os.path.dirname(os.path.abspath(__file__))
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")
SR = 48000
RNG = np.random.default_rng(7)

# Relative level of each sound (1.0 = the main level set by --level)
GAIN = {"pop": 0.8, "thud": 1.0, "swish": 0.7, "tick": 0.45, "whoosh": 0.8,
        "thock": 0.8, "boom": 1.0, "sparkle": 0.7, "bloop": 0.7}


def t_axis(sec):
    return np.arange(int(SR * sec)) / SR


def norm(x, peak=0.9):
    m = np.max(np.abs(x)) or 1.0
    return x / m * peak


def fade(x, ms_in=2, ms_out=10):
    n_in, n_out = int(SR * ms_in / 1000), int(SR * ms_out / 1000)
    x = x.copy()
    if n_in:
        x[:n_in] *= np.linspace(0, 1, n_in)
    if n_out:
        x[-n_out:] *= np.linspace(1, 0, n_out)
    return x


def onepole(x, alpha):
    y = np.zeros_like(x)
    acc = 0.0
    for i in range(len(x)):
        a = alpha[i] if hasattr(alpha, "__len__") else alpha
        acc += a * (x[i] - acc)
        y[i] = acc
    return y


def sweep_noise(sec, f0, f1, peak_at=0.5):
    """Whoosh: noise passed through a moving band-pass filter (f0 -> f1)."""
    t = t_axis(sec)
    noise = RNG.standard_normal(len(t))
    f = f0 * (f1 / f0) ** (t / sec)
    a_hi = 1 - np.exp(-2 * np.pi * f * 1.6 / SR)
    a_lo = 1 - np.exp(-2 * np.pi * f * 0.6 / SR)
    band = onepole(noise, a_hi) - onepole(noise, a_lo)
    p = t / sec
    env = np.where(p < peak_at, (p / peak_at) ** 1.5, ((1 - p) / (1 - peak_at)) ** 1.3)
    return band * env


def make_pop(variant=0):
    t = t_axis(0.16)
    f = (520 + 80 * variant) * np.exp(-t * 22) + 260
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 32)
    click = RNG.standard_normal(len(t)) * np.exp(-t * 400) * 0.12
    return fade(norm(x + click))


def make_thud():
    t = t_axis(0.32)
    f = 150 * np.exp(-t * 11) + 62
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 11)
    hit = onepole(RNG.standard_normal(len(t)), 0.18) * np.exp(-t * 60) * 0.8
    return fade(norm(x + hit), 1, 30)


def make_swish():
    return fade(norm(sweep_noise(0.28, 700, 3800, 0.55)), 4, 25)


def make_whoosh():
    return fade(norm(sweep_noise(0.42, 350, 3200, 0.55)), 4, 40)


def make_tick():
    t = t_axis(0.035)
    x = np.sin(2 * np.pi * 2600 * t) * np.exp(-t * 170)
    x += RNG.standard_normal(len(t)) * np.exp(-t * 500) * 0.25
    return fade(norm(x), 1, 8)


def make_thock():
    t = t_axis(0.16)
    f = 230 * np.exp(-t * 18) + 130
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 26)
    x += RNG.standard_normal(len(t)) * np.exp(-t * 300) * 0.15
    return fade(norm(x), 1, 15)


def make_boom():
    t = t_axis(0.5)
    f = 180 * np.exp(-t * 7) + 70
    ph = 2 * np.pi * np.cumsum(f) / SR
    low = np.sin(ph) * np.exp(-t * 7)
    t2 = t[: int(SR * 0.2)]
    pop = np.sin(2 * np.pi * (700 * np.exp(-t2 * 20) + 300) * t2) * np.exp(-t2 * 22) * 0.5
    low[: len(pop)] += pop
    return fade(norm(low), 1, 60)


def make_sparkle():
    t = t_axis(0.7)
    x = np.zeros_like(t)
    for k, f in enumerate([2093, 2637, 3136, 3951, 4699, 5274]):
        st = int(SR * k * 0.045)
        tt = t[: len(t) - st]
        x[st:] += np.sin(2 * np.pi * f * tt) * np.exp(-tt * 9) * (0.7 ** k + 0.35)
    x += sweep_noise(0.7, 1500, 6000, 0.3) * 0.5
    return fade(norm(x), 1, 80)


def make_bloop():
    t = t_axis(0.2)
    f = 330 + 360 * (1 - np.exp(-t * 28))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * np.exp(-t * 18)
    return fade(norm(x), 2, 40)


def build_library():
    return {
        "pop": [make_pop(0), make_pop(1)], "thud": [make_thud()], "swish": [make_swish()],
        "whoosh": [make_whoosh()], "tick": [make_tick()], "thock": [make_thock()],
        "boom": [make_boom()], "sparkle": [make_sparkle()], "bloop": [make_bloop()],
    }


def save_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def highpass(x, hz=180):
    return x - onepole(x, 1 - np.exp(-2 * np.pi * hz / SR))


# ---- events from kinetic.py and morph.py ----

def kinetic_events(items):
    ev = []
    for it in items:
        s, e = float(it["start"]), float(it["end"])
        style = it.get("style", "pop")
        if style == "slam":
            ev.append((max(s - 0.02, 0), "swish", 0.6))
            ev.append((s + 0.10, "thud", 1.0))
        elif style == "box":
            ev.append((s, "pop", 1.0))
        elif style == "type":
            n = len(re.sub(r"\s", "", it["text"]))
            reveal = min(0.7, max(0.25, n * 0.045))
            step = reveal / n
            for k in range(0, n, 2):  # a tick on every second letter only
                ev.append((s + k * step, "tick", 1.0))
        elif style == "slide":
            ev.append((s, "swish", 0.9))
        else:  # pop
            ev.append((s, "pop", 1.0))
    return ev


def morph_events(items):
    ev = []
    for it in items:
        s = float(it["start"])
        typ = it.get("type", "circles_to_bars")
        d = float(it["end"]) - s
        if typ in ("circles_to_bars", "bars_to_circles", "circles_to_steps"):
            n = min(len(it.get("values") or it.get("labels") or [0, 0, 0]), 6)
            ev.append((s + 0.25, "pop", 0.8))
            ev.append((s + 1.15, "whoosh", 0.8))
            ev.append((s + 1.15 + 0.7 + 0.1 * (n - 1), "thock", 0.9))
        elif typ == "circles_to_one":
            n = int(it.get("count", 6))
            ev.append((s + 0.2, "pop", 0.8))
            ev.append((s + 1.05, "whoosh", 0.9))
            ev.append((s + 1.05 + n * 0.05 + 0.35, "boom", 1.0))
        elif typ == "ring_burst":
            ev.append((s + 0.05, "sparkle", 1.0))
            if it.get("text"):
                ev.append((s + 0.1, "bloop", 0.8))
        if typ != "ring_burst" and d > 1.0:
            ev.append((s + d - 0.4, "swish", 0.5))  # gentle exit
    return ev


def probe_duration(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of",
         "default=nw=1:nk=1", path], capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def voice_level(path):
    r = subprocess.run(
        [FFMPEG, "-hide_banner", "-i", path, "-vn", "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True)
    m = re.search(r"mean_volume: (-?[\d.]+) dB", r.stderr)
    if not m:
        sys.exit("The video has no audio, so there is nothing to mix the SFX into.")
    return float(m.group(1))


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    events = []
    for path, fn in ((a.emphasis, kinetic_events), (a.morph, morph_events)):
        if path:
            with open(path, encoding="utf-8-sig") as f:
                events += fn(json.load(f))
    if not events:
        sys.exit("There are no emphasis or morph items to add SFX to.")

    dur = probe_duration(a.src)
    mean = voice_level(a.src)
    base_peak = 10 ** ((mean + a.level) / 20)  # peak of a "1.0" sound
    lib = build_library()
    track = np.zeros(int(SR * (dur + 1)))
    counts = {}
    for t, name, scale in sorted(events):
        if t >= dur:
            continue
        i = counts.get(name, 0)
        counts[name] = i + 1
        wavf = highpass(lib[name][i % len(lib[name])])
        gain = base_peak * GAIN[name] * scale
        st = int(SR * t)
        seg = wavf[: len(track) - st] * gain
        track[st: st + len(seg)] += seg
    track = track[: int(SR * dur)]

    tmp = os.path.splitext(os.path.abspath(a.dst))[0] + "_sfx_track.wav"
    save_wav(tmp, track)
    try:
        subprocess.run(
            [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src), "-i", tmp,
             "-filter_complex",
             "[0:a]aresample=48000[v];[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0[s];"
             "[v][s]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=false[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", os.path.abspath(a.dst)],
            check=True, capture_output=True)
    finally:
        if not a.keep_track:
            os.remove(tmp)

    peak_db = 20 * np.log10(max(np.max(np.abs(track)), 1e-9))
    print(f"{len(events)} SFX ({', '.join(f'{k} x{v}' for k, v in sorted(counts.items()))})")
    print(f"Voice (avg): {mean:.1f} dB | loudest SFX: {peak_db:.1f} dB "
          f"({peak_db - mean:+.1f} dB relative to the average voice)")
    print(f"Saved: {os.path.abspath(a.dst)}")


def cmd_preview(a):
    os.makedirs(a.folder, exist_ok=True)
    for name, variants in build_library().items():
        for i, x in enumerate(variants):
            save_wav(os.path.join(a.folder, f"{name}{i if len(variants) > 1 else ''}.wav"),
                     highpass(x) * 0.7)
    print(f"Wrote sample sounds to {os.path.abspath(a.folder)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--emphasis", help="emphasis.json used by kinetic.py")
    p.add_argument("--morph", help="morph.json used by morph.py")
    p.add_argument("--level", type=float, default=-6.0,
                   help="SFX level relative to the average voice level, dB (default -6)")
    p.add_argument("--keep-track", action="store_true", help="keep the SFX track as a WAV file")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("preview")
    p.add_argument("folder")
    p.set_defaults(fn=cmd_preview)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
