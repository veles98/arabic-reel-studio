"""Checks that this machine's ffmpeg/libass draws Arabic captions right to left.

Renders one caption whose first word is coloured red and checks that the red word ends up on
the RIGHT of the rest of the line (correct Arabic reading order).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from rs_common import DEFAULTS, FONTS_DIR, deep_merge, ffmpeg_bin, font_manifest


def rtl_ok(font: str = "Cairo") -> tuple[bool, str]:
    import rs_captions as cap
    man = font_manifest()
    if font not in man:
        return False, "font not downloaded"
    cfg = deep_merge(DEFAULTS, {"colors": {"text": "#FFFFFF", "accent": "#FF0000"},
                                "captions": {"outline": 0, "shadow": False}})
    words = [{"w": "وعدتكم", "s": 0.0, "e": 0.5}, {"w": "لو", "s": 0.5, "e": 0.8},
             {"w": "وصلنا", "s": 0.8, "e": 1.2}]
    events = cap.build_events(words, cfg, 2.0)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        (tdp / "fonts").mkdir()
        shutil.copy2(FONTS_DIR / man[font]["file"], tdp / "fonts")
        cap.write_ass(tdp / "t.ass", man[font]["ass_name"], cfg, events)
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1",
                            "-ss", "0.3", "-frames:v", "1", "-vf", "ass=t.ass:fontsdir=fonts,format=rgb24",
                            "-f", "rawvideo", "-"], capture_output=True, cwd=td)
    if len(r.stdout) != 1080 * 1920 * 3:
        return False, "render failed: " + r.stderr.decode("utf-8", "replace")[-300:]
    a = np.frombuffer(r.stdout, np.uint8).reshape(1920, 1080, 3).astype(int)
    red = np.nonzero((a[:, :, 0] > 150) & (a[:, :, 1] < 90) & (a[:, :, 2] < 90))[1]
    white = np.nonzero(a.min(axis=2) > 170)[1]
    if len(red) == 0 or len(white) == 0:
        return False, "caption not visible"
    ok = red.min() > white.max() - 2
    return ok, f"first word x {red.min()}-{red.max()}, rest x {white.min()}-{white.max()}"
