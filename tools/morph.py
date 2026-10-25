"""Morphing shapes as a video overlay (HyperFrames + GSAP -> transparent MOV -> FFmpeg overlay).

Usage:
    python tools/morph.py render OUTPUT/video.mp4 morph.json OUTPUT/video_morph.mp4

morph.json is a list of items. Common fields: "type", "start", "end" (seconds in the video),
"title" (optional), "colors" (hex list, optional), "y" (position from the top, 0-1, optional).

Types:
  circles_to_bars   circles that turn into a bar chart.
                    "labels": [...], "values": [0-1, ...] (up to 6), "numbers": [...] (real numbers only)
  bars_to_circles   the reverse: bars that turn into circles.   (same fields)
  circles_to_steps  circles that turn into a rising staircase (growth). "labels": [...] (up to 6)
  circles_to_one    many small circles that merge into one big circle with text.
                    "text": "GOAL", "count": 6
  ring_burst        a short burst of circles and a ring (emphasis). "text" optional. 1-1.5 s.

"values" are relative heights, not real numbers.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

from _bin import find, prepend_local_ffmpeg_to_path

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")
GSAP = os.path.join(ROOT, "node_modules", "gsap", "dist", "gsap.min.js")
HF_BIN = os.path.join(ROOT, "node_modules", ".bin", "hyperframes.cmd" if os.name == "nt" else "hyperframes")
prepend_local_ffmpeg_to_path()
FPS = 30
DEFAULT_COLORS = ["FFE500", "FF3B6B", "3BD9FF", "7CFF6B", "C77DFF", "FFFFFF"]

HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  @font-face { font-family: 'Arial Black'; src: local('Arial Black'), local('Arial-Black'); font-weight: 900; }
  html, body { margin: 0; padding: 0; background: transparent; }
  #root { position: relative; width: __W__px; height: __H__px; overflow: hidden;
          font-family: 'Arial Black', sans-serif; font-weight: 900; }
  .txt { color: #fff; text-transform: uppercase; white-space: nowrap; text-align: center;
         -webkit-text-stroke: 12px #000; paint-order: stroke fill; }
  #title { position: absolute; left: 0; width: __W__px; top: 6px; opacity: 0;
           font-size: __TS__px; letter-spacing: 1px; }
  .shape { position: absolute; left: 0; top: 0; }
  .lbl { position: absolute; top: 0; opacity: 0; font-size: __LS__px; }
  .num { position: absolute; top: 0; opacity: 0; font-size: __NS__px; }
  #big { position: absolute; left: 0; top: 0; display: flex; align-items: center;
         justify-content: center; font-size: __BS__px; line-height: 1; }
</style>
</head>
<body>
<div id="root" data-composition-id="root" data-start="0" data-duration="__D__"
     data-width="__W__" data-height="__H__" data-fps="__FPS__">
  <div id="title" class="txt">__TITLE__</div>
  <div id="stage"></div>
</div>
<script src="./gsap.min.js"></script>
<script>
  const cfg = __CFG__;
  const stage = document.getElementById("stage");
  const root = document.getElementById("root");
  const tl = gsap.timeline({ paused: true });
  const D = cfg.duration, W = cfg.W, H = cfg.H;
  const col = (i) => "#" + cfg.colors[i % cfg.colors.length];
  const glow = (c) => "0 0 38px " + c + "99, 0 10px 0 rgba(0,0,0,0.35)";
  const mk = (cls, id) => { const e = document.createElement("div");
    e.className = cls; e.id = id; stage.appendChild(e); return e; };

  if (cfg.title) tl.to("#title", { opacity: 1, duration: 0.3 }, 0.1)
                   .to("#title", { opacity: 0, duration: 0.3 }, D - 0.4);

  if (cfg.type === "circles_to_bars" || cfg.type === "bars_to_circles" ||
      cfg.type === "circles_to_steps") {
    const n = cfg.values.length;
    const base = cfg.baseline, maxH = cfg.maxH, bw = cfg.barW, d = cfg.dot;
    const slot = W / n;
    const rev = cfg.type === "bars_to_circles";
    cfg.values.forEach((v, i) => {
      const cx = slot * i + slot / 2;
      const h = Math.max(bw * 0.6, v * maxH);
      const el = mk("shape", "s" + i);
      el.style.background = col(i); el.style.boxShadow = glow(col(i));
      const lbl = mk("lbl txt", "l" + i);
      lbl.textContent = cfg.labels[i] || "";
      lbl.style.left = (cx - slot / 2) + "px"; lbl.style.width = slot + "px";
      const num = mk("num txt", "n" + i);
      num.textContent = (cfg.numbers && cfg.numbers[i]) || "";
      num.style.left = (cx - slot / 2) + "px"; num.style.width = slot + "px";

      const dotY = base - maxH * 0.55 - d / 2 + (i % 2 ? -34 : 34);
      const barY = base - h;
      const dot = { w: d, h: d, y: dotY, r: d / 2 };
      const bar = { w: bw, h: h, y: barY, r: 22 };
      const A = rev ? bar : dot, B = rev ? dot : bar;
      gsap.set(el, { width: A.w, height: A.h, x: cx - A.w / 2, y: A.y,
                     borderRadius: A.r, scale: 0, transformOrigin: "50% 50%" });
      gsap.set(lbl, { y: base + 18 });
      gsap.set(num, { y: base - h - 74 });

      const t0 = 0.25 + i * 0.09, m0 = 1.15 + i * 0.1;
      tl.to(el, { scale: 1, duration: 0.4, ease: "back.out(2)" }, t0);
      tl.to(el, { y: A.y + (i % 2 ? 14 : -14), duration: 0.5, ease: "sine.inOut" }, t0 + 0.4);
      tl.to(el, { width: B.w, height: B.h, x: cx - B.w / 2, y: B.y,
                  borderRadius: B.r, duration: 0.7, ease: "power3.inOut" }, m0);
      // slight bounce after the morph
      tl.to(el, { scaleY: 1.07, duration: 0.12, transformOrigin: "50% 100%" }, m0 + 0.7)
        .to(el, { scaleY: 1, duration: 0.18 }, m0 + 0.82);
      tl.to(lbl, { opacity: 1, duration: 0.3 }, m0 + 0.45);
      if (cfg.numbers && cfg.numbers[i]) tl.to(num, { opacity: 1, duration: 0.3 }, m0 + 0.55);
      tl.to([el, lbl, num], { opacity: 0, scale: 0.85, duration: 0.3 }, D - 0.4 + i * 0.03);
    });
  }

  if (cfg.type === "circles_to_one") {
    const n = cfg.count, cx = W / 2, cy = H / 2, R = H * 0.34, big = H * 0.64;
    const bigEl = mk("shape", "big0");
    bigEl.style.background = col(0); bigEl.style.boxShadow = glow(col(0));
    const txt = mk("txt", "big");
    txt.textContent = cfg.text; txt.id = "big"; txt.style.width = big + "px"; txt.style.height = big + "px";
    gsap.set(bigEl, { width: big, height: big, x: cx - big / 2, y: cy - big / 2,
                      borderRadius: big / 2, scale: 0, transformOrigin: "50% 50%" });
    gsap.set(txt, { x: cx - big / 2, y: cy - big / 2, opacity: 0, scale: 0.6 });
    const sm = Math.round(H * 0.16);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 - Math.PI / 2;
      const px = cx + Math.cos(a) * R * 1.5, py = cy + Math.sin(a) * R * 1.05;
      const el = mk("shape", "c" + i);
      el.style.background = col(i + 1); el.style.boxShadow = glow(col(i + 1));
      gsap.set(el, { width: sm, height: sm, x: px - sm / 2, y: py - sm / 2,
                     borderRadius: sm / 2, scale: 0, transformOrigin: "50% 50%" });
      const t0 = 0.15 + i * 0.07;
      tl.to(el, { scale: 1, duration: 0.35, ease: "back.out(2.2)" }, t0);
      tl.to(el, { y: py - sm / 2 + (i % 2 ? 16 : -16), duration: 0.5, ease: "sine.inOut" }, t0 + 0.35);
      const m0 = 1.05 + i * 0.05;
      tl.to(el, { x: cx - sm / 2, y: cy - sm / 2, scale: 0.5, duration: 0.5, ease: "power3.in" }, m0);
      tl.to(el, { opacity: 0, duration: 0.1 }, m0 + 0.5);
    }
    const g0 = 1.05 + n * 0.05 + 0.35;
    tl.to(bigEl, { scale: 1, duration: 0.55, ease: "elastic.out(1, 0.5)" }, g0);
    tl.to(txt, { opacity: 1, scale: 1, duration: 0.35, ease: "back.out(2)" }, g0 + 0.1);
    tl.to([bigEl, txt], { opacity: 0, scale: 0.8, duration: 0.3 }, D - 0.4);
  }

  if (cfg.type === "ring_burst") {
    const n = 14, cx = W / 2, cy = H / 2;
    const ring = mk("shape", "ring");
    ring.style.border = "14px solid " + col(0); ring.style.boxSizing = "border-box";
    ring.style.boxShadow = glow(col(0));
    const rs = H * 0.4;
    gsap.set(ring, { width: rs, height: rs, x: cx - rs / 2, y: cy - rs / 2,
                     borderRadius: rs / 2, scale: 0.2, opacity: 1, transformOrigin: "50% 50%" });
    tl.to(ring, { scale: 2.4, opacity: 0, duration: D * 0.8, ease: "power2.out" }, 0.05);
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2, s = Math.round(H * (i % 2 ? 0.07 : 0.1));
      const el = mk("shape", "b" + i);
      el.style.background = col(i); el.style.boxShadow = glow(col(i));
      gsap.set(el, { width: s, height: s, x: cx - s / 2, y: cy - s / 2,
                     borderRadius: s / 2, scale: 0.4, transformOrigin: "50% 50%" });
      const dist = H * (i % 2 ? 0.95 : 0.7);
      tl.to(el, { x: cx - s / 2 + Math.cos(a) * dist * 1.5, y: cy - s / 2 + Math.sin(a) * dist,
                  scale: 1, duration: D * 0.75, ease: "power3.out" }, 0.05);
      tl.to(el, { opacity: 0, duration: D * 0.3 }, D * 0.55);
    }
    if (cfg.text) {
      const txt = mk("txt", "big"); txt.textContent = cfg.text; txt.id = "big";
      txt.style.width = W + "px"; txt.style.height = H + "px";
      gsap.set(txt, { x: 0, y: 0, opacity: 0, scale: 0.5 });
      tl.to(txt, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(3)" }, 0.1);
      tl.to(txt, { opacity: 0, duration: 0.2 }, D - 0.25);
    }
  }

  window.__timelines = window.__timelines || {};
  window.__timelines["root"] = tl;
</script>
</body>
</html>
"""

HEIGHT_RATIO = {"circles_to_bars": 0.42, "bars_to_circles": 0.42, "circles_to_steps": 0.42,
                "circles_to_one": 0.5, "ring_burst": 0.5}
DEFAULT_Y = {"circles_to_bars": 0.38, "bars_to_circles": 0.38, "circles_to_steps": 0.38,
             "circles_to_one": 0.40, "ring_burst": 0.06}


def video_info(path):
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:stream_side_data=rotation", "-of", "json", path],
        capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    w, h = s["width"], s["height"]
    for sd in s.get("side_data_list", []):
        if abs(sd.get("rotation", 0)) in (90, 270):
            w, h = h, w
    return w, h


def build_project(item, vw, folder):
    typ = item.get("type", "circles_to_bars")
    if typ not in HEIGHT_RATIO:
        sys.exit(f"Unknown type: {typ}")
    values = (item.get("values") or [0.4, 0.7, 1.0])[:6]
    if typ == "circles_to_steps":
        n = len(item.get("labels") or values)
        values = [0.3 + 0.7 * i / max(n - 1, 1) for i in range(n)]
    W = int(vw * 0.82) // 2 * 2
    H = int(W * HEIGHT_RATIO[typ]) // 2 * 2
    dur = round(float(item["end"]) - float(item["start"]), 2)
    n = len(values)
    bw = min(150, int(W / n * 0.52))
    cfg = {
        "type": typ, "W": W, "H": H, "duration": dur, "values": values,
        "labels": item.get("labels", []), "numbers": item.get("numbers"),
        "title": item.get("title", ""), "text": item.get("text", ""),
        "count": int(item.get("count", 6)),
        "colors": [c.lstrip("#") for c in item.get("colors", DEFAULT_COLORS)],
        "baseline": H - 90, "maxH": H - 90 - 100, "barW": bw, "dot": min(130, bw),
    }
    html = (HTML.replace("__W__", str(W)).replace("__H__", str(H))
            .replace("__D__", str(dur)).replace("__FPS__", str(FPS))
            .replace("__TS__", str(int(W * 0.065))).replace("__LS__", str(int(W * 0.045)))
            .replace("__NS__", str(int(W * 0.05))).replace("__BS__", str(int(H * 0.2)))
            .replace("__TITLE__", item.get("title", ""))
            .replace("__CFG__", json.dumps(cfg)))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copy(GSAP, os.path.join(folder, "gsap.min.js"))
    return W, H


def render_item(folder, out_mov):
    subprocess.run([HF_BIN, "render", folder, "-f", str(FPS), "--format", "mov",
                    "-o", out_mov], check=True, shell=(os.name == "nt"))


def cmd_render(a):
    if os.path.exists(a.dst):
        sys.exit(f"{a.dst} already exists. Choose another name.")
    with open(a.spec, encoding="utf-8-sig") as f:
        items = json.load(f)
    if not items:
        sys.exit("The morph list is empty.")
    vw, vh = video_info(a.src)
    tmp = tempfile.mkdtemp(prefix="morph_")
    try:
        movs = []
        for i, it in enumerate(items):
            folder = os.path.join(tmp, f"m{i}")
            W, H = build_project(it, vw, folder)
            mov = os.path.join(tmp, f"m{i}.mov")
            print(f"Rendering morph {i + 1}/{len(items)} "
                  f"({it.get('type', 'circles_to_bars')}, {W}x{H})...", flush=True)
            render_item(folder, mov)
            movs.append((it, mov))

        cmd = [FFMPEG, "-hide_banner", "-y", "-i", os.path.abspath(a.src)]
        for _, mov in movs:
            cmd += ["-i", mov]
        chain, last = [], "0:v"
        for i, (it, _) in enumerate(movs, start=1):
            s, e = float(it["start"]), float(it["end"])
            typ = it.get("type", "circles_to_bars")
            y = int(vh * float(it.get("y", DEFAULT_Y[typ])))
            chain.append(f"[{i}:v]format=yuva444p,setpts=PTS-STARTPTS+{s}/TB[m{i}]")
            chain.append(f"[{last}][m{i}]overlay=x=(W-w)/2:y={y}:eof_action=pass:"
                         f"enable='between(t,{s},{e})'[o{i}]")
            last = f"o{i}"
        cmd += ["-filter_complex", ";".join(chain), "-map", f"[{last}]", "-map", "0:a?",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-c:a", "copy",
                "-movflags", "+faststart", os.path.abspath(a.dst)]
        subprocess.run(cmd, check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(items)} morphs")
    print(f"Saved: {os.path.abspath(a.dst)}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render")
    p.add_argument("src")
    p.add_argument("spec")
    p.add_argument("dst")
    p.set_defaults(fn=cmd_render)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
