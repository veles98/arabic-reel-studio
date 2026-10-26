"""Arabic captions as an ASS file, rendered by libass (HarfBuzz + FriBidi do the shaping and RTL)."""
from __future__ import annotations

from rs_arabic import clean_caption_word
from rs_common import hex_to_ass

W, H = 1080, 1920
SAFE_W = 760            # caption width limit: clear of the right-hand button column
RLM = "\u200f"  # right-to-left mark: keeps lines RTL even when they start with a Latin word
POS_Y = {"upper": 540, "middle": 960, "lower": 1300}   # centre line; IG bottom UI starts ~1560


def _cs(t: float) -> int:
    return max(0, int(round(t * 100)))


def _ts(cs: int) -> str:
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _est_width(text: str, size: float) -> float:
    # Arabic bold faces average a little under half an em per character; spaces are narrower.
    return sum(size * (0.30 if ch == " " else 0.52) for ch in text)


def header(font: str, cfg: dict) -> str:
    c = cfg["colors"]
    cap = cfg["captions"]
    size = int(cap["size"])
    outline = float(cap.get("outline", 5))
    shadow = 3 if cap.get("shadow", True) else 0
    text = hex_to_ass(c["text"])
    outl = hex_to_ass(c["outline"])
    box = hex_to_ass(c["box"], 0x18)
    back = "&H96000000"
    end_text = hex_to_ass(c.get("end_text", "#FFFFFF"))
    accent = hex_to_ass(c["accent"])
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "YCbCr Matrix: None",
        # Encoding -1 = libass picks the base direction from the text, so Arabic lines with
        # colour tags keep right-to-left word order (with 1, tagged runs are laid out LTR).
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{text},{accent},{outl},{back},-1,0,0,0,100,100,0,0,1,{outline},{shadow},5,60,60,60,-1",
        f"Style: Box,{font},{size},{text},{accent},{box},{back},-1,0,0,0,100,100,0,0,3,{max(10, size // 6)},0,5,60,60,60,-1",
        f"Style: End,{font},96,{end_text},{accent},{outl},{back},-1,0,0,0,100,100,0,0,1,0,0,5,60,60,60,-1",
        f"Style: Cover,{font},120,{text},{accent},{outl},{back},-1,0,0,0,100,100,0,0,1,7,4,5,60,60,60,-1",
        f"Style: CoverBox,{font},112,{text},{accent},{box},{back},-1,0,0,0,100,100,0,0,3,22,0,5,60,60,60,-1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    return "\n".join(lines) + "\n"


def chunk_words(words: list[dict], cfg: dict) -> list[list[dict]]:
    cap = cfg["captions"]
    style = cap.get("style", "word")
    per_line = max(2, min(4, int(cap.get("max_words", 3))))
    size = float(cap["size"]) * (0.86 if style == "block" else 1.0)
    max_words = per_line * 2 if style == "block" else per_line
    max_line_w = SAFE_W
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for i, w in enumerate(words):
        if cur:
            gap = w["s"] - cur[-1]["e"]
            text = " ".join(x["t"] for x in cur + [w])
            too_wide = style != "block" and _est_width(text, size) > max_line_w
            sentence_end = cur[-1]["raw"].rstrip().endswith((".", "؟", "?", "!", "،", ","))
            if len(cur) >= max_words or gap > 0.45 or too_wide or sentence_end:
                chunks.append(cur)
                cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    # avoid a lonely last word when the previous chunk can spare one
    for k in range(1, len(chunks)):
        if len(chunks[k]) == 1 and len(chunks[k - 1]) >= 3 and chunks[k][0]["s"] - chunks[k - 1][-1]["e"] < 0.3:
            chunks[k].insert(0, chunks[k - 1].pop())
    return [c for c in chunks if c]


def _line_text(ws: list[dict], active: int | None, text_c: str, accent_c: str) -> str:
    parts = []
    for i, w in enumerate(ws):
        if i == active:
            parts.append("{\\c" + accent_c + "}" + w["t"] + "{\\c" + text_c + "}")
        else:
            parts.append(w["t"])
    return RLM + " ".join(parts)


def _fit_scale(text_plain: str, size: float) -> str:
    est = _est_width(text_plain, size)
    if est <= SAFE_W:
        return ""
    k = max(60, int(100 * SAFE_W / est))
    return f"\\fscx{k}\\fscy{k}"


def build_events(words: list[dict], cfg: dict, main_end: float) -> list[str]:
    cap = cfg["captions"]
    if not cap.get("enabled", True) or not words:
        return []
    style = cap.get("style", "word")
    text_c = hex_to_ass(cfg["colors"]["text"])
    accent_c = hex_to_ass(cfg["colors"]["accent"])
    y = POS_Y.get(cap.get("position", "lower"), POS_Y["lower"])
    size = float(cap["size"])
    strip = bool(cap.get("strip_punctuation", True))

    fixes = cap.get("replace") or {}
    ws = []
    for w in words:
        t = clean_caption_word(w["w"], strip)
        t = fixes.get(t, t)
        if t:
            ws.append({"t": t, "raw": w["w"], "s": w["s"], "e": w["e"]})
    chunks = chunk_words(ws, cfg)
    ev = []
    style_name = "Box" if style == "boxed" else "Cap"
    for k, ch in enumerate(chunks):
        start = max(0.0, ch[0]["s"] - 0.04)
        nxt = chunks[k + 1][0]["s"] - 0.04 if k + 1 < len(chunks) else main_end
        end = min(max(ch[-1]["e"] + 0.25, start + 0.6), nxt, main_end)
        if end - start < 0.12:
            continue
        if style == "block":
            half = (len(ch) + 1) // 2
            lines = [ch[:half], ch[half:]] if len(ch) > 2 else [ch]
        else:
            lines = [ch]
        fsize = size * (0.86 if style == "block" else 1.0)
        widest = max((" ".join(w["t"] for w in ln) for ln in lines), key=len)
        fit = _fit_scale(widest, fsize)
        base = f"\\an5\\pos(540,{y})" + (f"\\fs{int(fsize)}" if style == "block" else "") + fit
        # one event per spoken word so the highlight follows the voice
        times = [start] + [w["s"] for w in ch[1:]] + [end]
        cs = [_cs(t) for t in times]
        for i in range(len(ch)):
            a, b = cs[i], cs[i + 1]
            if b <= a:
                continue
            idx = 0
            text_lines = []
            for ln in lines:
                act = i - idx if idx <= i < idx + len(ln) else None
                text_lines.append(_line_text(ln, act, text_c, accent_c))
                idx += len(ln)
            anim = ""
            if i == 0:
                anim = "\\fad(70,0)\\fscx92\\fscy92\\t(0,110,\\fscx100\\fscy100)" if not fit else "\\fad(70,0)"
            ev.append(f"Dialogue: 1,{_ts(a)},{_ts(b)},{style_name},,0,0,0,,{{{base}{anim}}}"
                      + "\\N".join(text_lines))
    return ev


def end_card_events(cfg: dict, t0: float, dur: float) -> list[str]:
    e = cfg["ending"]
    if not e.get("enabled", True):
        return []
    a, b = _ts(_cs(t0)), _ts(_cs(t0 + dur))
    accent = hex_to_ass(cfg["colors"]["accent"])
    out = []
    name = (cfg.get("name") or "").strip()
    handle = (cfg.get("handle") or "").strip()
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    text = (e.get("text") or "").strip()
    y = 820 if name else 900
    if name:
        out.append(f"Dialogue: 2,{a},{b},End,,0,0,0,,{{\\an5\\move(540,{y + 30},540,{y},0,350)\\fad(250,0)}}{RLM}{name}")
        y += 120
    if handle:
        out.append(f"Dialogue: 2,{a},{b},End,,0,0,0,,{{\\an5\\pos(540,{y})\\fs62\\c{accent}\\fad(350,0)}}‎{handle}")
        y += 110
    # thin accent rule
    out.append(f"Dialogue: 2,{a},{b},End,,0,0,0,,{{\\an5\\pos(540,{y})\\p1\\c{accent}\\bord0\\fad(400,0)}}"
               "m -90 -3 l 90 -3 l 90 3 l -90 3{\\p0}")
    y += 90
    if text:
        out.append(f"Dialogue: 2,{a},{b},End,,0,0,0,,{{\\an5\\pos(540,{y})\\fs70\\fad(500,0)}}{RLM}{text}")
    return out


def cover_events(cfg: dict, title: str) -> list[str]:
    words = title.split()
    if not words:
        return []
    if len(words) > 3:
        half = (len(words) + 1) // 2
        lines = [" ".join(words[:half]), " ".join(words[half:])]
    else:
        lines = [" ".join(words)]
    style = "CoverBox" if cfg["captions"].get("style") == "boxed" else "Cover"
    size = 120 if style == "Cover" else 112
    longest = max(lines, key=len)
    est = _est_width(longest, size)
    scale = "" if est <= 860 else f"\\fscx{int(100 * 860 / est)}\\fscy{int(100 * 860 / est)}"
    accent = hex_to_ass(cfg["colors"]["accent"])
    # last line in the accent colour gives the title a clear focal word group
    body = RLM + lines[0] if len(lines) == 1 else RLM + lines[0] + "\\N{\\c" + accent + "}" + RLM + lines[1]
    ev = [f"Dialogue: 1,0:00:00.00,0:00:10.00,{style},,0,0,0,,{{\\an5\\pos(540,900){scale}}}{body}"]
    handle = (cfg.get("handle") or "").strip()
    if handle:
        if not handle.startswith("@"):
            handle = "@" + handle
        ev.append(f"Dialogue: 1,0:00:00.00,0:00:10.00,End,,0,0,0,,{{\\an5\\pos(540,1520)\\fs52\\bord3}}‎{handle}")
    return ev


def write_ass(path, font: str, cfg: dict, events: list[str]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(header(font, cfg))
        for e in events:
            f.write(e + "\n")


def write_srt(path, words: list[dict], cfg: dict, main_end: float) -> None:
    fixes = cfg["captions"].get("replace") or {}
    ws = [{"t": fixes.get(clean_caption_word(w["w"], True), clean_caption_word(w["w"], True)), "raw": w["w"],
           "s": w["s"], "e": w["e"]} for w in words]
    ws = [w for w in ws if w["t"]]
    tmp = dict(cfg)
    tmp["captions"] = dict(cfg["captions"], style="block")
    chunks = chunk_words(ws, tmp)

    def srt_ts(t):
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    with open(path, "w", encoding="utf-8") as f:
        for i, ch in enumerate(chunks, 1):
            f.write(f"{i}\n{srt_ts(ch[0]['s'])} --> {srt_ts(min(ch[-1]['e'] + 0.2, main_end))}\n")
            f.write(" ".join(w["t"] for w in ch) + "\n\n")
