"""ffmpeg filter graphs: cut, vertical framing, zoom, captions, end card, loudness, cover."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import numpy as np

from rs_common import ffcolor, ffmpeg_bin, run

W, H = 1080, 1920


# ------------------------------------------------------------------ selection expressions

def select_expr(keep: list[tuple[float, float]]) -> str:
    eps = 0.0005
    return "+".join(f"gte(t\\,{a - eps:.4f})*lt(t\\,{b - eps:.4f})" for a, b in keep)


def audio_chain(keep, fps: int) -> str:
    # 48 kHz frames of exactly one video frame each, so audio and picture are cut on the same grid
    n = 48000 // fps
    return (f"asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,"
            f"asetnsamples=n={n}:p=0,aselect='{select_expr(keep)}',asetpts=N/SR/TB")


# ------------------------------------------------------------------ framing

_CROP_CACHE: dict = {}


def smart_crop_x(src: Path, src_w: int, src_h: int, duration: float) -> float:
    """Pick a fixed horizontal crop for a landscape clip from where the detail is."""
    if str(src) in _CROP_CACHE:
        return _CROP_CACHE[str(src)]
    h = 192
    w = int(round(src_w * h / src_h / 2)) * 2
    acc = np.zeros(w)
    for k in range(10):
        t = duration * (k + 0.5) / 10
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{t:.2f}", "-i", str(src), "-frames:v", "1",
                            "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True)
        if len(r.stdout) != w * h:
            continue
        img = np.frombuffer(r.stdout, np.uint8).reshape(h, w).astype(np.float32)
        gx = np.abs(np.diff(img, axis=1))
        gy = np.abs(np.diff(img, axis=0))
        acc[:-1] += gx.sum(axis=0)
        acc += gy.sum(axis=0)
    win = int(round(h * 9 / 16))
    if acc.sum() <= 0 or win >= w:
        return 0.5
    centre_bias = 1.0 - 0.25 * np.abs(np.linspace(-1, 1, w - win + 1))
    sums = np.convolve(acc, np.ones(win), "valid") * centre_bias
    x = int(np.argmax(sums))
    _CROP_CACHE[str(src)] = x / max(1, (w - win))
    return _CROP_CACHE[str(src)]


def frame_filter(info: dict, cfg: dict, src: Path) -> str:
    """Filter text taking [in] video to a 1080x1920 frame. Returns a chain fragment (no labels)."""
    w, h = info["width"], info["height"]
    if w / h <= 0.66:   # already vertical (or close): fill and centre-crop
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    mode = cfg["frame"].get("horizontal", "blur")
    if mode in ("smart", "center"):
        fx = 0.5 if mode == "center" else smart_crop_x(src, w, h, info["duration"])
        return f"scale=-2:{H},crop={W}:{H}:(iw-{W})*{fx:.3f}:0,setsar=1"
    # blurred fill: the full picture in the upper-middle, a soft blurred copy behind it
    return (f"split=2[bgs][fgs];"
            f"[bgs]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=14,"
            f"eq=brightness=-0.09:saturation=1.15,scale={W}:{H}[bg];"
            f"[fgs]scale={W}:-2[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2-110,setsar=1")


def zoom_filter(events: list[tuple[float, float]], strength: float, fps: int) -> str:
    if not events:
        return ""
    r = 0.32
    terms = []
    for a, b in events:
        x = f"max(0\\,min(min((in/{fps}-{a:.3f})/{r}\\,({b:.3f}-in/{fps})/{r})\\,1))"
        terms.append(f"({x})*({x})*(3-2*({x}))")
    z = f"(1+{strength - 1:.4f}*({'+'.join(terms)}))"
    mx = f"W/2*(1-1/{z})"
    my = f"H/2*(1-1/{z})"
    return (f"perspective=x0='{mx}':y0='{my}':x1='W-{mx}':y1='{my}':"
            f"x2='{mx}':y2='H-{my}':x3='W-{mx}':y3='H-{my}':interpolation=cubic:eval=frame")


# ------------------------------------------------------------------ loudness

def measure_loudness(src: Path, keep, fps: int, cfg: dict, workdir: Path) -> dict:
    a = cfg["audio"]
    graph = (f"[0:a]{audio_chain(keep, fps)},highpass=f=70,"
             f"acompressor=threshold=-21dB:ratio=2.5:attack=8:release=160:makeup=2,"
             f"loudnorm=I={a['lufs']}:TP={a['true_peak']}:LRA=11:print_format=json[a]")
    gfile = workdir / "measure.txt"
    gfile.write_text(graph, encoding="utf-8")
    r = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(src), "-/filter_complex", str(gfile),
                        "-map", "[a]", "-f", "null", "-"], capture_output=True, cwd=str(workdir))
    txt = r.stderr.decode("utf-8", "replace")
    m = re.findall(r"\{[^{}]*\"input_i\"[^{}]*\}", txt, re.S)
    if not m:
        raise RuntimeError("loudness measurement failed:\n" + txt[-1500:])
    return json.loads(m[-1])


def cut_audio_wav(src: Path, keep, fps: int, out: Path) -> None:
    graph = f"[0:a]{audio_chain(keep, fps)},aresample=16000,aformat=channel_layouts=mono[a]"
    gfile = out.parent / "cutaudio.txt"
    gfile.write_text(graph, encoding="utf-8")
    run([ffmpeg_bin(), "-v", "error", "-y", "-i", str(src), "-/filter_complex", str(gfile), "-map", "[a]",
         "-c:a", "pcm_s16le", str(out)])


# ------------------------------------------------------------------ main render

def render(src: Path, info: dict, cfg: dict, keep, zoom_events, loud: dict, main_dur: float,
           end_dur: float, workdir: Path, out_mp4: Path) -> None:
    fps = int(cfg["export"]["fps"])
    a = cfg["audio"]
    sel = select_expr(keep)
    total = main_dur + end_dur
    end_bg = ffcolor(cfg["colors"]["end_bg"])
    parts = []
    if info["has_video"]:
        parts.append(f"[0:v]setpts=PTS-STARTPTS,fps={fps},select='{sel}',setpts=N/FRAME_RATE/TB,"
                     f"{frame_filter(info, cfg, src)}[framed]")
    else:
        parts.append(f"color=c={end_bg}:s={W}x{H}:r={fps}:d={main_dur:.3f},setsar=1[framed]")
    chain = "[framed]"
    z = zoom_filter(zoom_events, float(cfg["zoom"]["strength"]), fps) if cfg["zoom"].get("enabled") else ""
    if z:
        parts.append(f"{chain}{z}[zoomed]")
        chain = "[zoomed]"
    if end_dur > 0:
        parts.append(f"{chain}format=yuv420p,trim=duration={main_dur:.4f},"
                     f"fade=t=out:st={max(0.0, main_dur - 0.3):.3f}:d=0.3:color={end_bg}[main]")
        parts.append(f"color=c={end_bg}:s={W}x{H}:r={fps}:d={end_dur:.3f},format=yuv420p,setsar=1[endv]")
        parts.append("[main][endv]concat=n=2:v=1:a=0[joined]")
        chain = "[joined]"
    parts.append(f"{chain}ass=captions.ass:fontsdir=fonts,format=yuv420p[v]")
    parts.append(
        f"[0:a]{audio_chain(keep, fps)},highpass=f=70,"
        f"acompressor=threshold=-21dB:ratio=2.5:attack=8:release=160:makeup=2,"
        f"apad=whole_dur={total:.3f},"
        f"loudnorm=I={a['lufs']}:TP={a['true_peak']}:LRA=11:measured_I={loud['input_i']}:"
        f"measured_TP={loud['input_tp']}:measured_LRA={loud['input_lra']}:"
        f"measured_thresh={loud['input_thresh']}:offset={loud['target_offset']}:linear=true,"
        f"aresample=48000,atrim=duration={total:.3f}[a]")
    gfile = workdir / "graph.txt"
    gfile.write_text(";\n".join(parts), encoding="utf-8")
    ex = cfg["export"]
    run([ffmpeg_bin(), "-hide_banner", "-v", "error", "-y", "-i", str(src), "-/filter_complex", str(gfile),
         "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", str(ex.get("preset", "medium")),
         "-crf", str(ex.get("crf", 20)), "-pix_fmt", "yuv420p", "-profile:v", "high", "-r", str(fps),
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart",
         "-t", f"{total:.3f}", str(out_mp4)], cwd=workdir)


# ------------------------------------------------------------------ cover

def pick_cover_time(src: Path, info: dict, cfg: dict, keep, main_dur: float) -> float:
    """Return a source time for the cover: the sharpest, well-exposed frame among candidates."""
    if not info["has_video"]:
        return 0.0
    best, best_t = -1.0, keep[0][0]
    frame = frame_filter(info, cfg, src)
    for k in range(8):
        t_out = main_dur * (0.12 + 0.76 * k / 7)
        acc, t_src = 0.0, None
        for a, b in keep:
            if acc + (b - a) >= t_out:
                t_src = a + (t_out - acc)
                break
            acc += b - a
        if t_src is None:
            continue
        r = subprocess.run([ffmpeg_bin(), "-v", "error", "-ss", f"{t_src:.3f}", "-i", str(src), "-frames:v", "1",
                            "-filter_complex", f"[0:v]{frame},scale=216:384,format=gray[o]", "-map", "[o]",
                            "-f", "rawvideo", "-"], capture_output=True)
        if len(r.stdout) != 216 * 384:
            continue
        img = np.frombuffer(r.stdout, np.uint8).reshape(384, 216).astype(np.float32)
        lap = img[1:-1, 1:-1] * 4 - img[:-2, 1:-1] - img[2:, 1:-1] - img[1:-1, :-2] - img[1:-1, 2:]
        sharp = float(lap.var())
        mean = float(img.mean())
        exposure = 1.0 - min(1.0, abs(mean - 120) / 120)
        score = (sharp + 1.0) * (0.3 + exposure)
        if score > best:
            best, best_t = score, t_src
    return best_t


def render_cover(src: Path, info: dict, cfg: dict, t_src: float, workdir: Path, out_png: Path) -> None:
    if info["has_video"]:
        inp = ["-ss", f"{t_src:.3f}", "-i", str(src)]
        head = f"[0:v]{frame_filter(info, cfg, src)},"
    else:
        inp = ["-f", "lavfi", "-i", f"color=c={ffcolor(cfg['colors']['end_bg'])}:s={W}x{H}:d=1"]
        head = "[0:v]"
    graph = head + "eq=brightness=-0.07:saturation=1.05,vignette=PI/5,ass=cover.ass:fontsdir=fonts[o]"
    run([ffmpeg_bin(), "-v", "error", "-y", *inp, "-frames:v", "1", "-filter_complex", graph, "-map", "[o]",
         str(out_png)], cwd=workdir)
