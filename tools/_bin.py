"""Locate external programs.

A copy placed in tools/ffmpeg/ (ffmpeg, ffprobe) wins; otherwise the program found on PATH is used.
"""
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))


def find(name):
    for ext in (".exe", ""):
        local = os.path.join(HERE, "ffmpeg", name + ext)
        if os.path.isfile(local):
            return local
    return shutil.which(name) or name


def prepend_local_ffmpeg_to_path():
    """Let child programs (for example HyperFrames) also find the local FFmpeg."""
    local = os.path.join(HERE, "ffmpeg")
    if os.path.isdir(local):
        os.environ["PATH"] = local + os.pathsep + os.environ.get("PATH", "")
