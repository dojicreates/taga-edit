# taga-edit

**An AI video editor skill for [Claude Code](https://claude.com/claude-code), by Doji Creates.**

Drop your raw clips into `INPUT/`, call the skill, and get one finished short-form video in `OUTPUT/`: joined, trimmed, colour graded, captioned and animated, with sound effects, music and your logo.

Built for short vertical talking-head videos (Reels, TikTok, Shorts), but every step works on any video. Everything runs on your own computer. Nothing is uploaded.

## What it does (11 skills)

| # | Skill | What it does |
|---|-------|--------------|
| 1 | **Dead Air Removal** | Cuts silent gaps (tight by default, with a small margin). |
| 2 | **Captions** | Word-by-word highlighted captions from speech (Whisper, runs locally). |
| 3 | **Kinetic Text** | Big animated text on the key words (pop, slam, box, type, slide). |
| 4 | **Morphing Shapes** | Circles that become a bar chart, merge into one circle, burst, and more. |
| 5 | **Sound Effects** | Gentle synthesised SFX matched to the text and shapes (no music). |
| 6 | **Background Music** | Music from your `MB/` folder, levelled against the voice. |
| 7 | **Logos & Images** | Places your logo (or any picture) from `IMAGES/`, background removed automatically. |
| 8 | **Color Grading** | Presets such as `cinematic`, `warm`, `moody`; describe the look you want. |
| 9 | **Smart Zoom** | Slow, gentle zooms, plus an optional fast punch-in with a slow zoom out. |
| 10 | **Clip Joining** | If `INPUT/` has `CLIP 1`, `CLIP 2`, ... they are joined first, in order. |
| 11 | **Transitions** | Zoom-through, flash or dip between clips, without overlapping the sound. |

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.10+ and Node.js 18+
- FFmpeg **7 or newer** (with ffprobe). The Windows setup script can download a portable copy.
- Built and tested on Windows. macOS and Linux should work (the font `Arial Black` must be installed for the text styles).
- Optional: an NVIDIA GPU makes transcription faster. CPU works too.

## Install

Download this repository (green **Code** button, then **Download ZIP**) or clone it, then run the setup once.

Windows (PowerShell):

```powershell
.\setup.ps1
```

macOS / Linux:

```bash
bash setup.sh
```

This creates `.venv/`, installs `faster-whisper`, `numpy`, `pillow` and the Node packages (`hyperframes`, `gsap`). The first caption run downloads a Whisper model (about 1.5 GB for `medium`).

## Use

1. Put your video, or numbered clips such as `CLIP 1.mp4`, `CLIP 2.mp4`, in `INPUT/`.
2. (Optional) Put background music in `MB/` and your logo in `IMAGES/`.
3. Open this folder in Claude Code and call the skill:

   ```
   /taga-edit
   ```

   With no extra instructions it runs the full workflow. You can also ask for one step, for example *"remove the dead air only"*, *"make it warmer"*, or *"add my logo at the bottom-left"*.
4. Your finished video appears in `OUTPUT/`. Only the final video is saved there; intermediate files go to `work/`.

## Folders

```
taga-edit/
  .claude/skills/taga-edit/SKILL.md   the skill (the instructions Claude follows)
  tools/                              the scripts behind each skill
  INPUT/    your raw clips (never modified)
  OUTPUT/   finished videos
  MB/       background music you may use
  IMAGES/   logos and pictures you may use
  work/     scratch files (created automatically, git-ignored)
  docs/     RECREATE_PROMPT.md, a full specification to rebuild this project from scratch
```

## Using the tools directly

Every script has a docstring and `--help`:

```bash
python tools/trim_dead_air.py INPUT/video.mp4 work/trimmed.mp4
python tools/grade.py presets
python tools/join_clips.py plan
```

## Good to know

- **Music and images are yours to license.** None are included. Make sure you have the right to use what you put in `MB/` and `IMAGES/`, especially for commercial videos.
- Transcription is automatic and imperfect. Check names and technical terms in the captions.
- The skill cannot listen to audio. Check the volume of the sound effects and music yourself, and ask for them to be raised or lowered.
- Defaults are tuned for talking-head videos. Change them by asking, or edit the options in each script.

## Credits

Created by **Doji Creates**.

Built with [Claude Code](https://claude.com/claude-code) by Anthropic. It uses these open-source projects, each under its own licence:

- [FFmpeg](https://ffmpeg.org) for all video and audio processing
- [HyperFrames](https://github.com/heygen-com/hyperframes) (HeyGen) and [GSAP](https://gsap.com) for the morphing shapes
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and OpenAI Whisper for captions
- [Pillow](https://python-pillow.org) and [NumPy](https://numpy.org) for image and sound processing

## License

[MIT](LICENSE) © 2026 Doji Creates
