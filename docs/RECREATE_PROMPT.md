# Recreate prompt: the taga-edit video-editor skill (11 skills)

Paste everything below the line into Claude Code (an empty folder, Python 3.10+, Node 18+, FFmpeg 7+ available). It describes the whole project precisely enough to rebuild it, script by script, and to test each part.

---

You are going to build **taga-edit**, a Claude Code project-skill that acts as an automatic video editor for short vertical talking-head videos. Raw clips go in `INPUT/`; one finished video comes out in `OUTPUT/`. Build everything described here, test every script on a real short clip, and fix what fails. Do not ask questions; use the defaults given.

## 0. Ground rules for the build

- Language of all code, comments, messages and docs: English. Every script prints short, plain messages.
- All scripts are Python 3.10+ command-line tools in `tools/`, run from the project root as `python tools/<name>.py ...`. They use FFmpeg/ffprobe through subprocess, never through a library.
- A helper `tools/_bin.py` locates programs: a copy in `tools/ffmpeg/` (`ffmpeg(.exe)`, `ffprobe(.exe)`) wins, otherwise `shutil.which`. It also has `prepend_local_ffmpeg_to_path()`.
- Every script that writes a file **refuses to overwrite** an existing output (`sys.exit("<path> already exists. Choose another name.")`).
- Every script ends by printing the absolute path of what it saved (`Saved: <path>`).
- Required FFmpeg: **7 or newer**. Long filter graphs are passed through a temp file with `-/filter_complex <file>` (the old `-filter_complex_script` no longer exists in FFmpeg 7+; the inline `-filter_complex` is fine for short graphs).
- Video encode settings: `libx264 -crf 17 or 18 -preset medium -pix_fmt yuv420p -movflags +faststart`; audio `aac 192k`. Steps that do not touch video use `-c:v copy`; steps that do not touch audio use `-c:a copy`.
- Never hard-code personal paths, names, usernames, e-mails, sample content or machine details anywhere. Do not ship any media, music, logos, model files or binaries.
- Fonts: the on-screen text uses `Arial Black` (installed on Windows and macOS).

## 1. Project layout

```
taga-edit/
  .claude/skills/taga-edit/SKILL.md     the skill (see section 14)
  tools/_bin.py trim_dead_air.py captions.py kinetic.py morph.py sfx.py music.py images.py grade.py zoom.py join_clips.py
  INPUT/.gitkeep   OUTPUT/.gitkeep   MB/README.md   IMAGES/README.md   docs/
  requirements.txt   package.json   setup.ps1   setup.sh   .gitignore   LICENSE (MIT)   README.md
```

- `requirements.txt`: `faster-whisper>=1.2.1`, `numpy>=2.0`, `pillow>=11.0`.
- `package.json` (private): dependencies `gsap ^3.15.0`, `hyperframes ^0.8.193`.
- `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `node_modules/`, `tools/ffmpeg/`, `INPUT/*`, `OUTPUT/*`, `work/`, `MB/*`, `IMAGES/*`, with `!INPUT/.gitkeep !OUTPUT/.gitkeep !MB/README.md !IMAGES/README.md`.
- `setup.ps1` / `setup.sh`: check Python and Node, create `.venv`, `pip install -r requirements.txt`, `npm install`, create `work/`; on Windows offer to download a portable FFmpeg (gyan.dev essentials zip) into `tools\ffmpeg`; on macOS/Linux warn if ffmpeg/ffprobe are missing.
- `INPUT/` raw clips (never modified), `OUTPUT/` only final videos, `work/` scratch (intermediates, JSON specs, SRT/ASS/WAV), `MB/` the only source of music, `IMAGES/` the only source of logos/images.

## 2. `tools/trim_dead_air.py` - Dead Air Removal

CLI: `trim_dead_air.py SRC DST [--noise -35] [--min-silence 0.2] [--pad 0.04]`.

- Refuse if the video has no audio (ffprobe `-select_streams a`) or DST exists.
- Detect silence with `ffmpeg -vn -af silencedetect=noise=<noise>dB:d=<min-silence> -f null -`, parsing `silence_start:` / `silence_end:` from stderr. A final silence with no end runs to the end of the file.
- Keep-segments: `cursor=0`; for each silence `(s,e)`: end=`min(s+pad,total)`; if `end-cursor>0.05` keep `(cursor,end)`; `cursor = total if e is None else max(e-pad, cursor)`. After the loop keep `(cursor,total)` if `total-cursor>0.05`. If nothing is kept, exit with a message.
- Build the filter graph: per kept segment `[0:v]trim=start=S:end=E,setpts=PTS-STARTPTS[v{i}];[0:a]atrim=start=S:end=E,asetpts=PTS-STARTPTS[a{i}];`, then `[v0][a0]...concat=n=N:v=1:a=1[v][a]`. Write it to a temp file, run with `-/filter_complex`, `-map [v] -map [a]`, libx264 crf 18, aac 192k.
- Print `Original: Xs -> Trimmed: Ys (removed: Zs, N segments)`.
- Tuning knowledge: if room noise sits above the threshold nothing is detected (do not use below -38 dB); to catch more dead air raise `--noise` (-32); to protect soft words lower it (-38) or raise `--pad`.

## 3. `tools/captions.py` - Captions

CLI: `captions.py SRC [--srt PATH] [--burn DST] [--model medium] [--language auto] [--max-words 4] [--font-size 14] [--margin-v 90] [--style fancy|plain] [--size 0.10] [--y 0.72]`.

- Exposes `transcribe(path, model_name, language)` (used by `kinetic.py words`): loads `faster_whisper.WhisperModel` on CUDA float16 and falls back to CPU int8 (also fall back at transcription time if the GPU load succeeded but runs fail, e.g. a missing cuBLAS DLL). `model.transcribe(path, language=None if "auto", word_timestamps=True, vad_filter=True)`; returns the flat list of words (`.word .start .end`).
- `build_captions(words, max_words, max_dur=2.8)`: start a new caption after a word that ends with `. ? ! ,`, or when the caption has `max_words` words, or when it is `max_dur` seconds long. Each caption = (start, end, text, words).
- Always writes an SRT (refuse if it exists; default path next to the video). Print `N captions -> path`.
- `plain` style burn: ffmpeg `subtitles=<srt name>:force_style='FontName=Arial,FontSize=..,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=..'`, run with `cwd` set to the SRT folder (the subtitles filter is picky about Windows paths).
- `fancy` style (default) writes `<burn name>_captions.ass` and burns it with `-vf ass=<name>` (cwd = ASS folder):
  - ASS header: `PlayResX/Y` = video size (swap if rotation metadata is 90/270), `WrapStyle: 2`, `ScaledBorderAndShadow: yes`. One style `C`: font `Arial Black`, size `int(w*size)`, primary white, outline black, back `&H90000000`, `Spacing 1`, outline `max(6, w//110)`, shadow `max(4, w//200)`, alignment 5 (centre), margins 60.
  - UPPERCASE words. For each caption pick an accent colour (BGR) from `[00E5FF, 6B3BFF, FFE500, 6BFF7C, FF9A3B]` (yellow, pink, cyan, green, blue) by caption index. Font size per caption: `min(size, int(0.90*w / (0.74*len(text))))`.
  - For every word k of a caption emit one Dialogue event from that word's start to the next word's start (the last one to the caption end; skip events shorter than 0.05 s). The text shows the whole caption; word k gets `{\1c&H<accent>&\fscx115\fscy115}WORD{\r}`. The first event of a caption also gets a pop-in: `\fscx80\fscy80\alpha&HFF&\t(0,90,\fscx100\fscy100\alpha&H00&)`. Position: `\an5\pos(w/2, h*y)`.

## 4. `tools/kinetic.py` - Kinetic Text

CLI: `kinetic.py words SRC OUT.json [--model medium --language auto]` and `kinetic.py render SRC emphasis.json DST [--y 0.14] [--size 0.15] [--color FFE500]`.

- `words`: uses `captions.transcribe`; writes `[{"word","start","end"}]` (2 decimals).
- `emphasis.json`: list of `{"text","start","end","style","color"?,"rot"?,"y"?}`; styles `pop` (default), `slam`, `box`, `type`, `slide`. Items shorter than 0.5 s are extended to 0.5 s. Read JSON with `utf-8-sig` (Windows BOM).
- Text is uppercased; `wrap()` splits texts longer than 12 characters with spaces into two lines with the most even lengths (`\N`). Font size = `min(base, (0.84 - pad)*w / (0.74*longest_line))` where `base = int(w*size)` and pad = 0.08 for `box`.
- Palette rotating per item: `[FFE500, FF3B6B, 3BD9FF, 7CFF6B, FFFFFF]`; tilt rotating per item `[-4, 3, -3, 4, 0]` degrees (`\frz`). Position `\an5\pos(w/2, h*y)`.
- Event animations (ASS override tags, durations in ms):
  - `pop`: `\fscx55\fscy55\alpha&HFF&` -> `\t(0,110,\fscx125\fscy125\alpha&H00&)` -> `\t(110,220,\fscx100\fscy100)`, `\fad(0,120)`.
  - `slam`: start `\fscx320\fscy320\alpha&HFF&\frz(rot*3)` -> `\t(0,110,\fscx100\fscy100\alpha&H00&\frz rot)`, then shake `\t(110,150,\frz rot+4)\t(150,195,\frz rot-2)\t(195,240,\frz rot)`, `\fad(0,120)`.
  - `slide`: `\move(x, y+0.05h, x, y, 0, 180)` with alpha fade-in over 160 ms, `\fad(0,120)`.
  - `type`: one event per visible letter; hidden letters are kept in the string with `{\alpha&HFF&}` so the layout does not shift. Reveal time `min(0.7, max(0.25, letters*0.045))`, evenly split; last event runs to `end` with `\fad(0,120)`.
  - `box`: separate style `KB` with `BorderStyle 3` (opaque box using the outline colour), text colour `&H101010&`, `\3c` = item colour, outline thickness `max(16, w//60)`, no shadow; animates like `pop`.
- Style `K`: Arial Black, outline `max(6, w//110)`, shadow `max(4, w//200)`, centre aligned. Layer 1. Burn with `-vf ass=<name>` (cwd = ASS folder); the `.ass` is written next to DST.

## 5. `tools/morph.py` - Morphing Shapes (HyperFrames + GSAP)

CLI: `morph.py render SRC morph.json DST`.

- For each item generate a HyperFrames project folder (`index.html` + a copy of `node_modules/gsap/dist/gsap.min.js` as `gsap.min.js`), render it with `node_modules/.bin/hyperframes render <folder> -f 30 --format mov -o <x.mov>` (on Windows the binary is `hyperframes.cmd` and `shell=True`). `--format mov` is **required**: it gives a ProRes 4444 with alpha; without it the background is opaque white. A transparent body background alone is not enough.
- Composition: root `<div id="root" data-composition-id="root" data-start="0" data-duration=D data-width=W data-height=H data-fps="30">`; GSAP timeline created `paused:true` and registered as `window.__timelines["root"]`. GSAP is loaded from the local file (no CDN). Only `set/to/from/fromTo` are used.
- Fonts: `@font-face { font-family:'Arial Black'; src: local('Arial Black'), local('Arial-Black'); font-weight:900 }` and `font-family:'Arial Black', sans-serif`. HyperFrames' lint **errors** on any font family without an `@font-face`.
- Text style: white, uppercase, `-webkit-text-stroke:12px #000; paint-order: stroke fill`. Shapes: solid colour with `box-shadow: 0 0 38px <colour>99, 0 10px 0 rgba(0,0,0,0.35)`. Colour palette default `[FFE500, FF3B6B, 3BD9FF, 7CFF6B, C77DFF, FFFFFF]`.
- Panel size: `W = int(video_width*0.82)//2*2`; `H = int(W*ratio)//2*2` with ratio 0.42 for bars/steps and 0.50 for circles_to_one/ring_burst. Duration D = end - start. Title font `0.065W`, labels `0.045W`, numbers `0.05W`, big text `0.2H`.
- Types:
  - `circles_to_bars` / `bars_to_circles` / `circles_to_steps` (steps use ascending values `0.3 + 0.7*i/(n-1)`): up to 6 shapes; slot = W/n; bar width `bw = min(150, int(W/n*0.52))`, dot size `min(130,bw)`, baseline `H-90`, max bar height `H-90-100`; bars have 22 px radius, dots are circles; dot y = `baseline - maxH*0.55 - d/2 ± 34` alternating. Timeline per shape i: scale 0->1 at `0.25+0.09i` (0.4 s `back.out(2)`); float ±14 px (0.5 s `sine.inOut`); morph width/height/x/y/borderRadius at `1.15+0.1i` for 0.7 s `power3.inOut`; slight bounce `scaleY 1.07` then back (0.12 s + 0.18 s) after the morph; label fades in at morph+0.45, number at morph+0.55 (numbers only if supplied); everything fades and scales to 0.85 at `D-0.4+0.03i`. Title fades in at 0.1 and out at `D-0.4`. Labels sit under the baseline (y = baseline+18).
  - `circles_to_one`: `count` (default 6) small circles (size 0.16H) on an ellipse (`x=cx+cos(a)*0.34H*1.5`, `y=cy+sin(a)*0.34H*1.05`) pop in (0.15+0.07i), float ±16, converge to the centre and shrink (start `1.05+0.05i`, 0.5 s `power3.in`), then a big circle (diameter 0.64H) appears at `1.05+0.05n+0.35` with `elastic.out(1,0.5)` and its text pops in 0.1 s later; all exit at `D-0.4`.
  - `ring_burst`: a ring (14 px border, size 0.4H) scaling 0.2 -> 2.4 and fading over 0.8D, plus 14 dots flying outward in two radii; optional centre text; exit near the end.
- Overlay onto the video: for every MOV `[i:v]format=yuva444p,setpts=PTS-STARTPTS+<start>/TB[m]` then `[prev][m]overlay=x=(W-w)/2:y=<int(video_h*y)>:eof_action=pass:enable='between(t,start,end)'`, chained; `-map 0:a?`, `-c:v libx264 -crf 18`, `-c:a copy`. Default y: bars 0.38, circles_to_one 0.40, ring_burst 0.06.
- Render each morph in a temp dir and delete it afterwards.

## 6. `tools/sfx.py` - Sound Effects

CLI: `sfx.py render SRC DST [--emphasis emphasis.json] [--morph morph.json] [--level -6] [--keep-track]` and `sfx.py preview FOLDER`.

- All sounds are synthesised with numpy (48 kHz mono, fixed RNG seed 7), each normalised to peak 0.9 with short fades, then high-passed at 180 Hz (one-pole). Recipes (t in seconds):
  - `pop` (two variants, 0.16 s): sine with frequency `(520+80v)*exp(-22t)+260`, amplitude `exp(-32t)`, plus a click `noise*exp(-400t)*0.12`.
  - `thud` (0.32 s): sine `150*exp(-11t)+62` Hz, amplitude `exp(-11t)`, plus low-passed noise `*exp(-60t)*0.8`.
  - `swish` (0.28 s): swept band-pass noise 700 -> 3800 Hz, envelope peak at 55 %. `whoosh` (0.42 s): 350 -> 3200 Hz.
  - `tick` (0.035 s): 2600 Hz sine `exp(-170t)` + noise `exp(-500t)*0.25`.
  - `thock` (0.16 s): sine `230*exp(-18t)+130` Hz, `exp(-26t)`, + noise `exp(-300t)*0.15`.
  - `boom` (0.5 s): sine `180*exp(-7t)+70` Hz, `exp(-7t)`, plus a 0.2 s pop on top.
  - `sparkle` (0.7 s): six decaying sines (2093, 2637, 3136, 3951, 4699, 5274 Hz) starting 45 ms apart + swept noise 1500 -> 6000 Hz at half level.
  - `bloop` (0.2 s): rising sine `330+360*(1-exp(-28t))` Hz, `exp(-18t)`.
  - Swept noise = noise through two one-pole low-passes whose cut-offs follow `f(t)=f0*(f1/f0)^(t/dur)` (factors 1.6 and 0.6), subtracted.
- Relative level per sound: pop 0.8, thud 1.0, swish 0.7, tick 0.45, whoosh 0.8, thock 0.8, boom 1.0, sparkle 0.7, bloop 0.7.
- Event mapping. Kinetic: `slam` = swish at start-0.02 (x0.6) + thud at start+0.10; `box` and `pop` = pop at start; `slide` = swish (x0.9); `type` = tick on every second letter, timed exactly like the typing animation. Morph: bars/steps = pop at start+0.25 (x0.8), whoosh at start+1.15 (x0.8), thock at start+1.15+0.7+0.1(n-1) (x0.9); circles_to_one = pop at +0.2, whoosh at +1.05 (x0.9), boom at +1.05+0.05n+0.35; ring_burst = sparkle at +0.05 (+ bloop at +0.1 when it has text); any non-burst morph longer than 1 s also gets a swish at `end-0.4` (x0.5). Pop variants alternate.
- Level: measure the video's mean volume with `volumedetect`; the base peak is `10^((mean+level)/20)`; each event is scaled by base peak x relative level x event scale. Build one mono track the length of the video, write it as a WAV in a temp location next to DST, then mix: `[0:a]aresample=48000[v];[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0[s];[v][s]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=false[a]`, `-c:v copy`, aac 192k. **`level=false` is essential**: the limiter auto-levels by default and would change the voice volume.
- Print the number and kinds of SFX and the loudest SFX relative to the voice. The track WAV is deleted unless `--keep-track`.

## 7. `tools/music.py` - Background Music

CLI: `music.py list` and `music.py render SRC DST [--track NAME] [--random] [--start 0] [--level -3] [--duck-ratio 1]`.

- Music comes only from `<project>/MB` (`.mp3 .wav .m4a .flac .ogg .aac`). If the folder or its content is missing, exit with a clear message. `list` prints name, duration, average dB.
- Default track = first alphabetically (`--random` picks one). Gain = `voice_mean + level - music_mean` where means come from `volumedetect` (music measured over the part that is used). Music files are usually loud, so never use the file's own level.
- Filter: `[1:a]aresample=48000,[aloop=loop=-1:size=2147483647,]atrim=start=S:duration=D,asetpts=PTS-STARTPTS,volume=<gain>dB,afade=t=in:st=0:d=1.0,afade=t=out:st=D-F:d=F,pan=stereo|c0=c0|c1=c1[m]` with `F=min(1.8, D/4)` (loop only if the remaining track is shorter than the video). Voice: `[0:a]aresample=48000,asplit=2[v][k]`. If `--duck-ratio > 1`: `[m][k]sidechaincompress=threshold=0.12:ratio=R:attack=20:release=500:makeup=1:level_sc=1[md]`, else `[m]anull[md];[k]anullsink`. Final `[v][md]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95:level=false[a]`. Video copied; audio aac 192k.
- Defaults: level -3 dB, ducking off. (A stronger default level or ducking made the music inaudible during speech in testing.)

## 8. `tools/images.py` - Logos & Images

CLI: `images.py list` and `images.py render SRC DST --image NAME [--corner top-right] [--size 0.11] [--margin 0.04] [--start 0.3] [--end END] [--opacity 1.0] [--no-key]`.

- Images only from `<project>/IMAGES` (`.png .jpg .jpeg .webp .bmp`). If exactly one image exists it is the default.
- `describe()`: has-alpha check; for opaque images look at the four corners: all <=24 -> `black` background, all >=231 -> `white` background.
- `prepare()` (Pillow + numpy): with alpha keep it; for a black background `alpha = clip(max(R,G,B)/fg, 0, 1)` with `fg` = 95th percentile of channel-max over pixels >40, and un-premultiply the colour (`rgb/alpha`, clipped); for a white background the mirror image (`alpha=(255-min)/(255-fg)`, `fg`=5th percentile of min over pixels <215). Then **trim** the transparent border (alpha>8 bounding box + 4 % padding) so `--size` refers to the logo itself.
- Overlay: scale to `int(video_w*size)//2*2` wide (lanczos), `colorchannelmixer=aa=<opacity>`, `setpts=PTS+start/TB`, `fade in 0.4 s at start` and `fade out 0.5 s ending at end` (both `alpha=1`), overlay with `eof_action=pass` and `enable='between(t,start,end)'`; the image input is `-loop 1 -framerate 30 -t <end>`. Margins: `mx = int(w*margin)`, `my = int(w*margin + h*0.01)` (safe area). Corners: top-right (`W-w-mx`, `my`), top-left, bottom-right, bottom-left, center-top. Minimum visible time 1 s. Video encoded crf 18, audio copied.

## 9. `tools/grade.py` - Color Grading

CLI: `grade.py presets`, `grade.py render SRC DST [--preset cinematic] [overrides]`, `grade.py compare SRC OUT.png [--at 3] [--preset ..]` (original | graded side by side: `[0:v]split[a][b];[b]<filter>[g];[a][g]hstack=2,scale=1000:-1`, one frame).

Parameters and neutral values: contrast 1, saturation 1, brightness 0, gamma 1, s_curve 0, fade 0, warmth 0, teal 0, orange 0, vignette 0, grain 0, sharpen 0, bw false. Presets (overrides on the neutral base):

- `cinematic`: contrast 1.08, saturation 0.92, s_curve 0.05, fade 0.025, warmth 0.15, teal 0.6, orange 0.5, vignette 0.4, grain 3, sharpen 0.3 (brightness 0, gamma 1).
- `warm`: contrast 1.05, saturation 1.05, warmth 0.45, orange 0.4, vignette 0.2, fade 0.01, s_curve 0.03.
- `cool`: contrast 1.06, saturation 0.9, warmth -0.4, teal 0.7, vignette 0.25, fade 0.015, s_curve 0.04.
- `moody`: contrast 1.15, saturation 0.8, brightness -0.04, gamma 0.92, s_curve 0.08, fade 0.02, teal 0.5, orange 0.3, vignette 0.5, grain 4, sharpen 0.25.
- `vivid`: contrast 1.1, saturation 1.25, s_curve 0.05, sharpen 0.35. `bw`: bw true, contrast 1.15, s_curve 0.07, fade 0.02, vignette 0.3, grain 4, sharpen 0.3.

Filter chain in this order: `hue=s=0` (bw) -> `eq=contrast:saturation:brightness:gamma` -> `curves=all='0/f 0.25/(0.25-s+0.6f) 0.5/0.5 0.75/(0.75+s-0.2f) 1/(1-0.4f)'` (s = s_curve, f = fade; skipped if both 0) -> `colorbalance` (not for bw): shadows `rs=-0.08t gs=0.02t bs=0.07t`, mids `rm=0.06w bm=-0.06w`, highlights `rh=0.06o gh=0.01o bh=-0.06o` (t=teal, w=warmth, o=orange) -> `unsharp=5:5:(0.8*sharpen):5:5:0` -> `vignette=angle=A` with **`A = clamp(0.12 + 0.55*vignette, 0.1, 0.9)`** -> `noise=alls=<grain>:allf=t`. Do not feed raw `vignette=angle` values larger than about 0.9: they darken the frame by 25-40 % (measured: angle 0.3 loses 5 % of the luma, 0.75 loses 25 %, 1.0 loses 39 %). The cinematic preset should lower the average luma by roughly 9 %. Encode crf 17, audio copied.

## 10. `tools/zoom.py` - Smart Zoom

CLI: `zoom.py render SRC DST zoom.json` and `zoom.py suggest emphasis.json --duration SEC [--amount 1.07]` (prints JSON to stdout, comments to stderr).

- `zoom.json`: `{"center":[0.5,0.4], "keys":[[t, scale] or [t, scale, "punch"], ...]}`.
- Interpolation between consecutive keys, using `u=(t-t0)/(t1-t0)`: default **smoothstep** `u*u*(3-2u)`; a key marked `"punch"` is reached with **ease-out cubic** `1-(1-u)^3` (fast first, slow end). Before the first key the scale is the first value, after the last key the last value. Build one nested `if(lt(t,t1), z0+(z1-z0)*ease, ...)` expression.
- Render: `scale=w='trunc(iw*(Z)/2)*2':h='trunc(ih*(Z)/2)*2':eval=frame:flags=bicubic,crop=w=W:h=H:x='(iw-W)*cx':y='(ih-H)*cy',setsar=1` where W,H are the original size; the point (cx,cy) stays fixed. Encode crf 17, audio copied; output has the same resolution and frame count.
- **Validation** (exit with a helpful message, including the minimum duration needed): keys must be at least two and strictly increasing in time; scale >= 1.0; normal zoom-in speed <= 0.045 scale/s and scale <= 1.12; a `punch` must be an increase, last >= 0.25 s and reach <= 1.30; zoom-out speed <= 0.075 scale/s.
- `suggest`: rank emphasis items by weight (`slam` 3, `box` 2, others 1), consider only weight >= 2, at most `max(1, int(duration//7))` zooms, each: rise starts `max(0, start-1.2)`, rise 1.8 s, hold until the emphasis ends (at least 0.4 s), zoom out 2 s (clamped to the end of the video); skip a candidate that would sit within 2.5 s of a chosen one; skip if less than 1.5 s remain for the zoom out unless it ends at the end of the video.

## 11. `tools/join_clips.py` - Clip Joining and Transitions

CLI: `join_clips.py plan [--folder INPUT]` and `join_clips.py render DST [--folder INPUT] [--transition mix|zoom|flash|dip|none] [--trim]`.

- Clips = video files (`.mp4 .mov .mkv .m4v .avi .webm`) in the folder, sorted in **natural order** (digits compared as numbers, case-insensitive).
- `plan` (never renders): one video -> "nothing to join"; otherwise list order, resolution, fps, duration (and "(no audio)") and warnings: a clip without a number, missing numbers in the sequence, duplicate numbers, differing resolution/fps ("conformed to the first clip").
- `render`: needs >= 2 clips. With `--trim`, first run `trim_dead_air.py` (through `sys.executable`) on every clip into a temp dir. The first clip fixes width, height and fps. Per clip: `scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=<fps>,setpts=PTS-STARTPTS`, then the transition effects, then `format=yuv420p`. Audio per clip: `aresample=48000,aformat=channel_layouts=stereo` plus a 12 ms `afade` in (if not the first clip) and out (if not the last) to avoid clicks; a clip without audio gets `anullsrc=r=48000:cl=stereo` for its duration. Join with `concat=n=N:v=1:a=1`, crf 17, aac 192k.
- **Clips never overlap** (no `xfade`/`acrossfade`): overlapping clips would make two voices overlap and lose words, and shorten the video. Transitions are effects on the last D=0.2 s of the earlier clip and the first 0.2 s of the next, so total length = sum of clip lengths. Boundary kinds: `mix` alternates `zoom`, `flash`, `zoom`, ...; the others use one kind everywhere; `none` = hard cut.
  - `zoom`: out side `gt(t,dur-D)*((t-(dur-D))/D)^2`, in side `lt(t,D)*(1-t/D)^2`; scale factor `1+0.18*(sum)` applied with `scale=...:eval=frame` + `crop` (centre x, y at 0.45), plus `gblur=sigma=12:steps=2` enabled only in the last/first D/2.
  - `flash`: `eq=brightness='min(1, <same ramps>)':eval=frame` (ramps to white at the cut and back).
  - `dip`: `fade=t=out:st=dur-D:d=D` on the earlier clip and `fade=t=in:st=0:d=D` on the next.
- Print the clips, the transition at each boundary, the total length and the output path. The joined file belongs in `work/`, not `OUTPUT/`.

## 12. Build order and tests

Build in this order and test each script on a real 6-10 second talking clip (use FFmpeg to cut one or generate a test video with a sine voice if none is available): `_bin`, `trim_dead_air`, `grade`, `zoom`, `join_clips`, `captions`, `kinetic`, `morph`, `images` (make a test logo with Pillow: orange shape on black), `sfx`, `music` (generate a short mp3 with FFmpeg into `MB/`). Check: output durations, no overwrite, validation errors fire for a too-fast zoom, extract frames (`ffmpeg -ss T -frames:v 1`) at the interesting moments and look at them (caption highlight, kinetic text position, transitions at the clip boundary, logo background removed, morph shapes with transparent background), and verify with `volumedetect` that SFX and music do not change the voice level in untouched passages.

## 13. Full pipeline order (what the skill does)

1. `join_clips` (`--trim`, transitions) when several clips exist, else the single video.
2. `trim_dead_air` (only for a single video; skipped if joined with `--trim`).
3. `grade` (default `cinematic`) - footage only, before every overlay.
4. `zoom` (2-3 moments; 1-2 intense) - footage only, before every overlay; needs the emphasis list.
5. `captions` fancy, `--max-words 3`, burned.
6. `kinetic words` -> choose emphasis -> `kinetic render`.
7. `morph render`.
8. `images render` (logo, top-right).
9. `sfx render` with the same `emphasis.json` and `morph.json`.
10. `music render` -> final file in `OUTPUT/`.

Intermediate files live in `work/`. Only the final video is written to `OUTPUT/`.

## 14. The skill file `.claude/skills/taga-edit/SKILL.md`

Frontmatter: `name: taga-edit` and a description saying it is an AI video editor for short talking-head videos (join clips with transitions, dead air, grade, zoom, captions, kinetic text, morphing shapes, SFX, music, logo) to be used when the user says "taga-edit", "/taga-edit", or asks to edit the raw videos in INPUT. Body, in English, in this order:

1. Role, "reply in the user's language", run commands from the project root, run the full workflow when called without instructions.
2. Folders and tools (INPUT, OUTPUT, work, MB, IMAGES, tools, FFmpeg lookup, `.venv`, `node_modules`); how to call the scripts with the venv.
3. Rules: never modify INPUT; never overwrite OUTPUT; ffprobe first; music only from MB and images only from IMAGES (never download or generate them; the user owns the licensing responsibility); you cannot listen, so ask the user to check audio levels; report path and duration; only final videos in OUTPUT.
4. Thirteen sections: 1 source and output folders; 2 Dead Air Removal; 3 Captions; 4 Kinetic Text; 5 Morphing Shapes; 6 Sound Effects; 7 Background Music; 8 Logos & Images; 9 Color Grading; 10 Smart Zoom; 11 Clip Joining; 12 Transitions; 13 Full Workflow. Each section gives: when to use it, the exact commands, the options with defaults, the limits, the "how many / how often" guidance, ordering constraints, and what to report to the user. Include these judgement rules:
   - Kinetic text: many and frequent (about one per 2-3 s), mix styles, never overlapping, text at the top; keep emphasis at least 0.5 s away from clip boundaries.
   - Morphs: 3-4 per 20 s, different types, plus a short `ring_burst`; never invent numbers; never overlap two morphs; never put one over a face that is zoomed in.
   - Smart zoom: never nauseating; at most one per ~7 s; gentle 1.05-1.08 by default; intense (`punch`, 1.18-1.25) at most 1-2 per video, only on the heaviest moments, never back-to-back; always a slow zoom out; keep clear of clip boundaries and of morphs that cover the middle of the frame.
   - SFX: short, quiet (about 6-7 dB under the voice), highpassed, the voice untouched; ask the user to check the level.
   - Music: only from `MB/`; level relative to the voice (-3 dB default); ducking off by default; tell the user which track was used.
   - Logo: top-right, 11 % width, safe margin, background removed automatically; check frames for collisions.
   - Color grading: the user describes the look, you translate it to parameters (give the translation table: warmer = warmth+orange up; cooler = warmth down, teal up; more colourful = saturation up; muted = down; moody = preset or brightness down, contrast and vignette up; brighter = brightness/gamma up, vignette down; old film = grain, fade up, saturation down); always run `compare` first; check skin tones and measure luma (a drop above ~20 % is too dark); grade footage only, before overlays.
   - Clip joining: runs first and automatically; order from the natural file-name order; ask only when `plan` warns; later timestamps come from the joined video.
   - Transitions: short (0.2 s, never beyond 0.3 s), clips never overlap; tell the user which transition was used where.
5. Full workflow section: the ten steps of section 13 above plus "look at frames from every stage before reporting; list the emphasis items, morphs, zooms, transitions, the music track, and the final path".

## 15. Also write

- `README.md`: what it is, the 11-skill table, requirements, install (setup scripts), usage (`/taga-edit` with no instructions runs everything; single steps by asking), folder map, notes (music/images licensing is the user's responsibility, transcription is imperfect, the skill cannot hear audio), MIT licence.
- `docs/RECREATE_PROMPT.md` is this file (you do not need to recreate it).

When everything works, run the whole pipeline once on a short clip and report the output path and what each stage did.
