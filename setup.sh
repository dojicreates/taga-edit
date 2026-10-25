#!/usr/bin/env bash
# One-time setup for macOS / Linux. Run from the project root:  bash setup.sh
set -euo pipefail

command -v python3 >/dev/null || { echo "Python 3.10+ is required."; exit 1; }
command -v node >/dev/null || { echo "Node.js 18+ is required."; exit 1; }
command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null || \
  echo "WARNING: FFmpeg 7+ (with ffprobe) was not found on PATH. Install it (for example: brew install ffmpeg)."

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
npm install
mkdir -p work
echo "Done. Open this folder in Claude Code and call the taga-edit skill."
