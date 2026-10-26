"""Shared helpers: paths, ffmpeg lookup, probing, settings (brand.json)."""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPTS_DIR.parent
# The project root is the folder that holds .claude/ (three levels up from scripts/).
ROOT = SKILL_DIR.parent.parent.parent
FONTS_DIR = ROOT / "fonts"
OUT_DIR = ROOT / "out"

# Every setting lives in brand.json. These are the defaults for anything missing.
DEFAULTS: dict = {
    "version": 1,
    "name": "",
    "handle": "",
    "font": "Cairo",
    "colors": {
        "text": "#FFFFFF",
        "accent": "#FFD23F",
        "outline": "#101010",
        "box": "#101010",
        "end_bg": "#101010",
        "end_text": "#FFFFFF",
    },
    "captions": {
        "enabled": True,
        "style": "word",          # word | block | boxed
        "position": "lower",      # upper | middle | lower
        "size": 92,               # px on a 1080x1920 frame
        "max_words": 3,           # 2-4 words per chunk (block style uses two lines of this)
        "outline": 5,
        "shadow": True,
        "strip_punctuation": True,
        "replace": {},            # caption spelling fixes, e.g. {"Cloud": "Claude"}
    },
    "cut": {
        "enabled": True,
        "keep_pause": 0.22,       # seconds of pause kept where a long silence was
        "min_silence": 0.40,      # silences shorter than this are left alone
        "remove_retakes": True,   # drop a false start when the next phrase repeats it
        "remove_fillers": True,   # drop isolated "اممم / اه"
    },
    "zoom": {
        "enabled": True,
        "strength": 1.08,         # 1.08 = 8% punch-in
        "every": 6.0,             # at most one zoom per this many seconds
    },
    "frame": {
        "horizontal": "blur",     # blur | smart | center   (for landscape sources)
    },
    "audio": {"lufs": -14.0, "true_peak": -1.5},
    "ending": {"enabled": True, "text": "تابعني لأكثر", "seconds": 2.5},
    "cover": {"enabled": True, "title": ""},
    "whisper": {"model": "medium", "language": "ar"},  # medium: best Arabic on CPU; small: faster,
    "export": {"fps": 30, "crf": 20, "preset": "medium"},
}

FONT_FAMILIES = ["Cairo", "Tajawal", "IBM Plex Sans Arabic", "Noto Kufi Arabic", "Readex Pro"]


def log(msg: str) -> None:
    print(msg, flush=True)


def die(msg: str, code: int = 1) -> None:
    print("ERROR: " + msg, file=sys.stderr, flush=True)
    sys.exit(code)


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def brand_path() -> Path:
    return ROOT / "brand.json"


def load_brand(path: Path | None = None) -> dict:
    p = path or brand_path()
    data = {}
    if p.exists():
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
    return deep_merge(DEFAULTS, data)


def save_brand(data: dict, path: Path | None = None) -> None:
    p = path or brand_path()
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------------------------------------------------------------- ffmpeg

def _which(name: str) -> str | None:
    env = os.environ.get("RS_FFMPEG_DIR")
    cands = []
    if env:
        cands.append(Path(env) / (name + (".exe" if os.name == "nt" else "")))
    local = ROOT / "tools" / "ffmpeg" / "bin" / (name + (".exe" if os.name == "nt" else ""))
    cands.append(local)
    for c in cands:
        if c.exists():
            return str(c)
    found = shutil.which(name)
    if found:
        return found
    # common install places that may not be on PATH until the terminal is reopened
    exe = name + (".exe" if os.name == "nt" else "")
    extra = []
    la = os.environ.get("LOCALAPPDATA")
    if la:
        extra.append(Path(la) / "Microsoft" / "WinGet" / "Links" / exe)
        extra += sorted((Path(la) / "Microsoft" / "WinGet" / "Packages").glob(f"Gyan.FFmpeg*/*/bin/{exe}"))
    extra += [Path("C:/ProgramData/chocolatey/bin") / exe, Path("C:/ffmpeg/bin") / exe,
              Path("/opt/homebrew/bin") / exe, Path("/usr/local/bin") / exe]
    for c in extra:
        if c.exists():
            return str(c)
    return None


def ffmpeg_bin() -> str:
    b = _which("ffmpeg")
    if not b:
        die("ffmpeg not found. Install it (see README) or set RS_FFMPEG_DIR to its bin folder.")
    return b


def ffprobe_bin() -> str:
    b = _which("ffprobe")
    if not b:
        die("ffprobe not found (it ships with ffmpeg).")
    return b


def run(cmd: list, cwd: Path | None = None, quiet: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", "replace")[-3000:]
        die(f"command failed: {Path(cmd[0]).name} ...\n{err}")
    return r


def probe(path: Path) -> dict:
    r = run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_streams",
             "-show_format", str(path)])
    info = json.loads(r.stdout.decode("utf-8", "replace"))
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
              and s.get("disposition", {}).get("attached_pic", 0) == 0), None)
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
    dur = float(info.get("format", {}).get("duration", 0) or 0)
    out = {"duration": dur, "has_video": v is not None, "has_audio": a is not None}
    if v:
        w, h = int(v["width"]), int(v["height"])
        rot = 0
        for sd in v.get("side_data_list", []) or []:
            if "rotation" in sd:
                rot = int(float(sd["rotation"]))
        if "rotate" in (v.get("tags") or {}):
            rot = int(v["tags"]["rotate"])
        if abs(rot) % 180 == 90:
            w, h = h, w
        out.update(width=w, height=h)
    return out


def decode_audio(path: Path, sr: int = 16000):
    """Decode any media file to mono float32 at `sr` using ffmpeg (no PyAV needed)."""
    import numpy as np
    r = run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sr),
             "-f", "f32le", "-"])
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def hex_to_ass(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS colour order)."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ffcolor(hex_color: str) -> str:
    return "0x" + hex_color.lstrip("#").upper()


def fmt_time(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:05.2f}"


def font_manifest() -> dict:
    p = FONTS_DIR / "manifest.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}
