"""Arabic Reel Studio: one command from a talking video to a captioned vertical reel.

  python reel.py doctor                 check ffmpeg, Python packages, fonts, disk
  python reel.py fonts                  download the free Arabic fonts
  python reel.py list                   videos waiting in the folder
  python reel.py edit <video>           cut, caption, export  (outputs in out/<name>/)
  python reel.py set captions.size=90   change one setting in brand.json (several allowed)
  python reel.py fix Cloud Claude       always write a caption word differently
  python reel.py show                   print the current settings
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rs_common import (DEFAULTS, FONTS_DIR, OUT_DIR, ROOT, brand_path, decode_audio, die, fmt_time,  # noqa: E402
                       font_manifest, load_brand, log, probe, save_brand)

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts", ".wav", ".m4a", ".mp3"}


# ------------------------------------------------------------------ doctor

def cmd_doctor() -> int:
    ok = True
    log(f"project folder: {ROOT}")
    log(f"python: {sys.version.split()[0]}")
    try:
        from rs_common import ffmpeg_bin
        import subprocess
        fb = ffmpeg_bin()
        filt = subprocess.run([fb, "-hide_banner", "-filters"], capture_output=True).stdout.decode("utf-8", "replace")
        ver = subprocess.run([fb, "-version"], capture_output=True).stdout.decode("utf-8", "replace").splitlines()[0]
        log(f"ffmpeg: {ver[:60]}")
        for need in (" ass ", " loudnorm ", " perspective ", " gblur "):
            if need not in filt:
                ok = False
                log(f"  MISSING ffmpeg filter:{need}(install a full ffmpeg build, see README)")
    except SystemExit:
        ok = False
        log("ffmpeg: NOT FOUND (see README)")
    try:
        import faster_whisper  # noqa: F401
        import numpy  # noqa: F401
        log("faster-whisper: ok")
    except Exception as e:
        ok = False
        log(f"faster-whisper: NOT INSTALLED ({e}). Run: python -m pip install -r requirements.txt")
    man = font_manifest()
    have = [f for f in man if (FONTS_DIR / man[f]["file"]).exists()]
    log(f"fonts: {', '.join(have) if have else 'none yet (run: python reel.py fonts)'}")
    if not have:
        ok = False
    else:
        try:
            from rs_selftest import rtl_ok
            good, detail = rtl_ok(have[0])
            log(f"arabic right-to-left captions: {'ok' if good else 'WRONG ORDER'} ({detail})")
            ok = ok and good
        except SystemExit:
            ok = False
    free = shutil.disk_usage(ROOT).free / 1e9
    log(f"free disk: {free:.1f} GB" + ("  (low: keep at least 3 GB free)" if free < 3 else ""))
    log(f"brand.json: {'found' if brand_path().exists() else 'not yet (open setup.html)'}")
    log("READY" if ok else "NOT READY")
    return 0 if ok else 1


# ------------------------------------------------------------------ settings

def _parse_value(v: str):
    try:
        return json.loads(v)
    except Exception:
        return v


def cmd_set(pairs: list[str]) -> int:
    cfg = load_brand()
    for p in pairs:
        if "=" not in p:
            die(f"use key=value, got: {p}")
        key, val = p.split("=", 1)
        node = cfg
        parts = key.strip().split(".")
        ref = DEFAULTS
        for part in parts[:-1]:
            if part not in node or not isinstance(node[part], dict):
                die(f"unknown setting: {key}")
            node = node[part]
            ref = ref.get(part, {})
        if parts[-1] not in ref:
            die(f"unknown setting: {key}")
        node[parts[-1]] = _parse_value(val)
        log(f"{key} = {json.dumps(node[parts[-1]], ensure_ascii=False)}")
    save_brand(cfg)
    return 0


def cmd_fix(wrong: str, right: str) -> int:
    cfg = load_brand()
    cfg["captions"].setdefault("replace", {})[wrong] = right
    save_brand(cfg)
    log(f"captions: '{wrong}' -> '{right}'")
    return 0


def cmd_show() -> int:
    print(json.dumps(load_brand(), ensure_ascii=False, indent=2))
    return 0


def cmd_list() -> int:
    vids = [p for p in sorted(ROOT.iterdir()) if p.is_file() and p.suffix.lower() in VIDEO_EXT]
    for p in vids:
        log(p.name)
    if not vids:
        log("no videos in the project folder yet")
    return 0


# ------------------------------------------------------------------ edit

def _phrases(words: list[dict], gap: float = 0.35) -> list[list[dict]]:
    out: list[list[dict]] = []
    for w in words:
        if out and w["s"] - out[-1][-1]["e"] <= gap:
            out[-1].append(w)
        else:
            out.append([w])
    return out


def choose_zooms(words: list[dict], audio16, cfg: dict, main_dur: float) -> list[tuple[float, float]]:
    import numpy as np
    z = cfg["zoom"]
    if not z.get("enabled", True) or not words:
        return []
    every = max(3.0, float(z.get("every", 6.0)))
    groups: list[list[dict]] = []
    for ph in _phrases(words, 0.15):   # short breaths split the edited speech into ideas
        if groups and groups[-1][-1]["e"] - groups[-1][0]["s"] < 0.9:
            groups[-1].extend(ph)
        else:
            groups.append(list(ph))
    cands = []
    for ph in groups:
        a, b = ph[0]["s"], ph[-1]["e"]
        if b - a < 0.9:
            continue
        seg = audio16[int(a * 16000):int(b * 16000)]
        if len(seg) == 0:
            continue
        loud = float(10 * np.log10(np.mean(seg.astype(np.float64) ** 2) + 1e-12))
        cands.append((loud, a, min(b + 0.15, a + 3.5, main_dur - 0.2)))
    cands.sort(reverse=True)
    picked: list[tuple[float, float]] = []
    budget = max(1, int(main_dur / every))
    for loud, a, b in cands:
        if len(picked) >= budget:
            break
        if all(abs(a - pa) >= every and (b < pa - 0.4 or a > pb + 0.4) for pa, pb in picked):
            picked.append((a, b))
    return sorted(picked)


def auto_title(words: list[dict], fixes: dict) -> str:
    from rs_arabic import clean_caption_word
    for ph in _phrases(words, 0.45):
        ws = [clean_caption_word(w["w"], True) for w in ph]
        ws = [fixes.get(w, w) for w in ws]
        ws = [w for w in ws if w]
        if len(ws) >= 2:
            return " ".join(ws[:6])
    return ""


def write_report(path: Path, src: Path, cfg: dict, info: dict, plan: dict, main_dur: float, end_dur: float,
                 n_words: int, zooms, loud_target: float) -> None:
    removed = sorted(plan["removed"], key=lambda r: r["a"])
    # merged removed time (silence cuts can overlap retake cuts)
    spans = []
    for r in removed:
        if spans and r["a"] <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], r["b"])
        else:
            spans.append([r["a"], r["b"]])
    total_cut = info["duration"] - main_dur
    by = {"silence": 0.0, "retake": 0.0, "filler": 0.0}
    cnt = {"silence": 0, "retake": 0, "filler": 0}
    for r in removed:
        by[r["why"]] += r["b"] - r["a"]
        cnt[r["why"]] += 1
    names = {"silence": "صمت طويل اختُصر", "retake": "إعادة أو بداية متعثرة (أبقينا المحاولة الأخيرة)",
             "filler": "صوت تردد مثل «اممم»"}
    L = []
    L.append(f"تقرير المونتاج: {src.name}")
    L.append("=" * 40)
    L.append(f"المدة الأصلية:  {info['duration']:.1f} ث")
    L.append(f"بعد القص:       {main_dur:.1f} ث" + (f"  + خاتمة {end_dur:.1f} ث" if end_dur else ""))
    L.append(f"المحذوف:        {total_cut:.1f} ث")
    L.append(f"  - إعادات وبدايات متعثرة: {cnt['retake']} مقطع")
    L.append(f"  - صمت مختصر: {cnt['silence']} موضع (أبقينا {cfg['cut']['keep_pause']:.2f} ث من كل وقفة)")
    if cnt["filler"]:
        L.append(f"  - أصوات تردد: {cnt['filler']}")
    L.append(f"كلمات في الترجمة: {n_words}   تقريبات (زووم): {len(zooms)}   مستوى الصوت: {loud_target:.0f} LUFS")
    L.append("")
    L.append("القص لا يمر داخل أي كلمة: كل قصة تقع داخل صمت مقاس من الصوت نفسه.")
    L.append("")
    L.append("التفاصيل (بتوقيت الفيديو الأصلي):")
    retakes = [r for r in removed if r["why"] != "silence"]
    for r in removed:
        if r["why"] == "silence" and any(q["a"] <= r["a"] and r["b"] <= q["b"] + 1e-6 for q in retakes):
            continue   # already inside a removed retake
        line = f"  {fmt_time(r['a'])} -> {fmt_time(r['b'])}  ({r['b'] - r['a']:.2f} ث)  {names[r['why']]}"
        if r["text"]:
            line += f"\n      «{r['text'].strip()}»"
        L.append(line)
    if plan["ghost_words"]:
        L.append("")
        L.append("كلمات تجاهلناها لأنها ظهرت في التفريغ فوق صمت (خطأ تعرّف شائع): "
                 + " ".join(w["w"].strip() for w in plan["ghost_words"]))
    L.append("")
    L.append("لتغيير النتيجة قل مثلاً: «قص أقل» أو «لا تحذف الإعادات» أو «كبّر الخط» ثم «عدّل الفيديو» من جديد.")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def cmd_edit(video: str, brand: str | None) -> int:
    import rs_captions as cap
    import rs_render as rr
    from rs_cut import kept_duration, plan_cuts
    from rs_transcribe import transcribe

    t_start = time.time()
    src = Path(video)
    if not src.is_absolute():
        src = (Path.cwd() / src) if (Path.cwd() / src).exists() else ROOT / src
    if not src.exists():
        die(f"video not found: {video}")
    cfg = load_brand(Path(brand) if brand else None)
    if not brand_path().exists() and not brand:
        log("note: brand.json not found, using default style (open setup.html to make yours)")

    free = shutil.disk_usage(ROOT).free / 1e9
    if free < 1.0:
        die(f"only {free:.1f} GB free on disk; free some space first")

    man = font_manifest()
    font = cfg.get("font", "Cairo")
    if font not in man or not (FONTS_DIR / man[font]["file"]).exists():
        log(f"font '{font}' not downloaded yet, fetching...")
        import subprocess
        subprocess.run([sys.executable, str(Path(__file__).with_name("fetch_fonts.py")), font])
        man = font_manifest()
        if font not in man:
            die(f"could not get font {font}")

    info = probe(src)
    if not info["has_audio"]:
        die("this file has no sound track; the tool needs a talking video")
    fps = int(cfg["export"]["fps"])

    out_dir = OUT_DIR / src.stem
    work = out_dir / "_work"
    cache = out_dir / ".cache"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    (work / "fonts").mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FONTS_DIR / man[font]["file"], work / "fonts" / Path(man[font]["file"]).name)

    log(f"[1/6] listening to {src.name} ({info['duration']:.1f}s)")
    audio = decode_audio(src, 16000)
    duration = len(audio) / 16000
    wcfg = cfg["whisper"]
    words = transcribe(src, wcfg["model"], wcfg["language"], cache / "transcript_source.json", audio)

    log("[2/6] planning cuts (only inside silences)")
    plan = plan_cuts(words, audio, 16000, duration, cfg, fps)
    keep = plan["keep"]
    main_dur = kept_duration(keep)

    log("[3/6] captions from the edited sound")
    cut_wav = work / "cut16k.wav"
    rr.cut_audio_wav(src, keep, fps, cut_wav)
    cut_audio = decode_audio(cut_wav, 16000)
    keep_hash = hashlib.sha1(json.dumps(keep).encode()).hexdigest()[:12]
    key_file = cache / f"transcript_cut_{keep_hash}.json"
    words_out = transcribe(src, wcfg["model"], wcfg["language"], key_file, cut_audio)
    words_out = [w for w in words_out if w["s"] < main_dur - 0.05]
    for w in words_out:
        w["e"] = min(w["e"], main_dur)
    for old in cache.glob("transcript_cut_*.json"):
        if old != key_file:
            old.unlink()

    end_dur = float(cfg["ending"]["seconds"]) if cfg["ending"].get("enabled", True) else 0.0
    zooms = choose_zooms(words_out, cut_audio, cfg, main_dur)
    events = cap.build_events(words_out, cfg, main_dur) + cap.end_card_events(cfg, main_dur, end_dur)
    cap.write_ass(work / "captions.ass", man[font]["ass_name"], cfg, events)

    log("[4/6] measuring loudness")
    loud = rr.measure_loudness(src, keep, fps, cfg, work)

    log(f"[5/6] rendering 1080x1920 ({main_dur + end_dur:.1f}s)")
    out_mp4 = out_dir / f"{src.stem}_reel.mp4"
    rr.render(src, info, cfg, keep, zooms, loud, main_dur, end_dur, work, out_mp4)

    log("[6/6] cover, subtitles, report")
    if cfg["cover"].get("enabled", True):
        title = (cfg["cover"].get("title") or "").strip() or auto_title(words_out, cfg["captions"].get("replace") or {})
        cap.write_ass(work / "cover.ass", man[font]["ass_name"], cfg, cap.cover_events(cfg, title))
        t_cover = rr.pick_cover_time(src, info, cfg, keep, main_dur)
        rr.render_cover(src, info, cfg, t_cover, work, out_dir / "cover.png")
    cap.write_srt(out_dir / "captions.srt", words_out, cfg, main_dur)
    write_report(out_dir / "edits.txt", src, cfg, info, plan, main_dur, end_dur, len(words_out), zooms,
                 cfg["audio"]["lufs"])
    (out_dir / "words.json").write_text(json.dumps(words_out, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)

    log("")
    log(f"DONE in {time.time() - t_start:.0f}s")
    log(f"video:  {out_mp4}")
    log(f"cover:  {out_dir / 'cover.png'}")
    log(f"report: {out_dir / 'edits.txt'}")
    log(f"before {info['duration']:.1f}s -> after {main_dur:.1f}s (+{end_dur:.1f}s ending), "
        f"cut {info['duration'] - main_dur:.1f}s, {len(zooms)} zooms")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "fonts":
        import subprocess
        return subprocess.run([sys.executable, str(Path(__file__).with_name("fetch_fonts.py")), *rest]).returncode
    if cmd == "set":
        return cmd_set(rest)
    if cmd == "fix":
        if len(rest) != 2:
            die('use: python reel.py fix "wrong word" "right word"')
        return cmd_fix(rest[0], rest[1])
    if cmd == "show":
        return cmd_show()
    if cmd == "list":
        return cmd_list()
    if cmd == "edit":
        if not rest:
            die("which video? e.g.  python reel.py edit myclip.mp4")
        brand = None
        if "--brand" in rest:
            i = rest.index("--brand")
            brand = rest[i + 1]
            rest = rest[:i] + rest[i + 2:]
        return cmd_edit(rest[0], brand)
    die(f"unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
