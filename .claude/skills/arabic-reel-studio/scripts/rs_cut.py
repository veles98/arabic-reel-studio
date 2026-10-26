"""Decide what to cut.

Rules:
  * Cuts only ever happen inside silence measured from the audio itself, so no word is cut.
  * Long pauses are shortened to `keep_pause`.
  * A false start / retake (a phrase that the speaker then says again) is removed as a whole
    block, from the pause before it to the pause before the new take. The last take is kept.
"""
from __future__ import annotations

import numpy as np

from rs_arabic import is_filler, normalize

HOP = 0.01   # 10 ms analysis step
WIN = 0.03   # 30 ms window
PAD_AFTER = 0.09   # never cut closer than this after speech ends
PAD_BEFORE = 0.06  # ...or this before speech starts


# ------------------------------------------------------------------ audio analysis

def frame_db(audio: np.ndarray, sr: int) -> np.ndarray:
    hop, win = int(sr * HOP), int(sr * WIN)
    if len(audio) < win:
        return np.full(1, -120.0)
    c = np.concatenate([[0.0], np.cumsum(audio.astype(np.float64) ** 2)])
    starts = np.arange(0, len(audio) - win + 1, hop)
    energy = (c[starts + win] - c[starts]) / win
    return 10 * np.log10(energy + 1e-12)


def silence_runs(db: np.ndarray, min_len: float) -> tuple[list[tuple[float, float]], float]:
    """Return silent intervals (seconds) of at least min_len, and the threshold used."""
    floor = float(np.percentile(db, 8))
    speech = float(np.percentile(db, 95))
    thr = max(floor + 9.0, speech - 34.0)
    thr = min(thr, speech - 14.0)
    silent = db < thr
    # ignore tiny clicks: a loud blip shorter than 50 ms between two silent stretches
    n = len(silent)
    i = 0
    while i < n:
        if not silent[i]:
            j = i
            while j < n and not silent[j]:
                j += 1
            if j - i <= 5 and i > 20 and j < n - 20 and silent[i - 20:i].all() and silent[j:j + 20].all():
                silent[i:j] = True
            i = j
        else:
            i += 1
    runs = []
    i = 0
    while i < n:
        if silent[i]:
            j = i
            while j < n and silent[j]:
                j += 1
            a = i * HOP + (WIN - HOP) if i > 0 else 0.0   # sound may reach the end of the last loud window
            b = j * HOP if j < n else n * HOP + WIN
            if b - a >= min_len or i == 0 or j == n:
                runs.append((a, b))
            i = j
        else:
            i += 1
    return runs, thr


# ------------------------------------------------------------------ fuzzy word matching

def _lev_ratio(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))


def _same(a: str, b: str) -> bool:
    if a.startswith("و") and len(a) > 2:
        a = a[1:]
    if b.startswith("و") and len(b) > 2:
        b = b[1:]
    return _lev_ratio(a, b) >= 0.7


def _fuzzy_lcs(a: list[str], b: list[str]) -> int:
    m, n = len(a), len(b)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            dp[i + 1][j + 1] = dp[i][j] + 1 if _same(a[i], b[j]) else max(dp[i][j + 1], dp[i + 1][j])
    return dp[m][n]


# ------------------------------------------------------------------ plan

def plan_cuts(words: list[dict], audio: np.ndarray, sr: int, duration: float, cfg: dict,
              fps: int) -> dict:
    cut = cfg["cut"]
    db = frame_db(audio, sr)
    runs, thr = silence_runs(db, float(cut["min_silence"]))
    keep_pause = float(cut["keep_pause"])

    # Words that sit almost entirely in silence are recognition noise (Whisper sometimes invents
    # a phrase over silence). They are dropped from the logic and reported.
    def is_ghost(s: float, e: float) -> bool:
        for a, b in runs:
            inside = s >= a - 0.02 and e <= b + 0.02
            if inside and (b - a >= 2.0 or (s - a >= 0.25 and b - e >= 0.25)):
                return True
        return False

    real_words, ghost_words = [], []
    for w in words:
        (ghost_words if is_ghost(w["s"], w["e"]) else real_words).append(w)

    removed: list[dict] = []   # {"a","b","why","text"}

    if cut.get("enabled", True):
        # 1) shorten pauses
        for a, b in runs:
            if a <= 0.0:          # leading silence
                ca, cb = 0.0, b - 0.10
            elif b >= duration - 0.02:  # trailing silence
                ca, cb = a + 0.35, duration
            else:
                keep_after = max(PAD_AFTER, keep_pause * 0.6)
                keep_before = max(PAD_BEFORE, keep_pause * 0.4)
                ca, cb = a + keep_after, b - keep_before
            if cb - ca >= 0.06:
                removed.append({"a": ca, "b": cb, "why": "silence", "text": ""})

        # 2) phrases = speech between the silences
        bounds = [0.0]
        for a, b in runs:
            if a > 0 and b < duration - 0.02:
                bounds.append((a + b) / 2)
        bounds.append(duration + 1)
        phrases = []
        for k in range(len(bounds) - 1):
            lo, hi = bounds[k], bounds[k + 1]
            ws = [w for w in real_words if lo <= (w["s"] + w["e"]) / 2 < hi]
            phrases.append({"lo": lo, "hi": min(hi, duration), "words": ws})

        # the cut point inside a silence, mirroring the pause-shortening above
        def cut_in(bound_index: int) -> float:
            if bound_index == 0:
                return 0.0
            mid = bounds[bound_index]
            for a, b in runs:
                if a <= mid <= b:
                    return a + max(PAD_AFTER, keep_pause * 0.6)
            return mid

        # 3) retakes / false starts (keep the last take)
        if cut.get("remove_retakes", True):
            i = 0
            while i < len(phrases) - 1:
                found = None
                block: list[str] = []
                for j in range(i + 1, len(phrases)):
                    block += [normalize(w["w"]) for w in phrases[j - 1]["words"]]
                    block = [t for t in block if t]
                    if phrases[j]["lo"] - phrases[i]["lo"] > 30.0:
                        break
                    if not block or not phrases[j]["words"]:
                        continue   # a new take must begin with recognised speech
                    after: list[str] = []
                    for p in phrases[j:]:
                        after += [t for t in (normalize(w["w"]) for w in p["words"]) if t]
                        if len(after) >= len(block) + 3:
                            break
                    if not after:
                        break
                    # the new take must START like the old one (first word, allowing one word of
                    # timing slack on either side) and then repeat most of it in order
                    anchored = any(_same(block[x], after[y])
                                   for x in range(min(2, len(block))) for y in range(min(2, len(after))))
                    score = _fuzzy_lcs(block, after[:len(block) + 2]) / len(block)
                    single_ok = len(block) > 1 or (len(after) > 1 and _same(block[0], after[0]))
                    if anchored and single_ok and score >= 0.6:
                        found = j
                        break
                if found is not None:
                    text = " ".join(w["w"] for p in phrases[i:found] for w in p["words"])
                    removed.append({"a": cut_in(i), "b": cut_in(found), "why": "retake", "text": text})
                    i = found
                else:
                    i += 1

        # 4) isolated fillers ("اممم") and short noises with no words
        if cut.get("remove_fillers", True):
            for k, p in enumerate(phrases):
                dur = p["hi"] - p["lo"]
                if p["words"] and all(is_filler(w["w"]) for w in p["words"]) and dur < 2.0:
                    removed.append({"a": cut_in(k), "b": cut_in(k + 1) if k + 1 < len(bounds) - 1 else duration,
                                    "why": "filler", "text": " ".join(w["w"] for w in p["words"])})

    # union of removed intervals -> kept segments, snapped to the frame grid
    spans = sorted((max(0.0, r["a"]), min(duration, r["b"])) for r in removed if r["b"] > r["a"])
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 1e-6:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    keep = []
    t = 0.0
    for a, b in merged:
        if a > t:
            keep.append((t, a))
        t = max(t, b)
    if t < duration:
        keep.append((t, duration))
    snapped = []
    for a, b in keep:
        a2, b2 = round(a * fps) / fps, round(b * fps) / fps
        if b2 - a2 >= 2.0 / fps:
            snapped.append((a2, b2))
    if not snapped:
        snapped = [(0.0, round(duration * fps) / fps)]

    return {"keep": snapped, "removed": removed, "threshold_db": thr,
            "ghost_words": ghost_words, "words": real_words}


def map_time(t: float, keep: list[tuple[float, float]]) -> float | None:
    """Source time -> output time (None if that moment was cut)."""
    out = 0.0
    for a, b in keep:
        if a <= t <= b:
            return out + (t - a)
        out += b - a
    return None


def kept_duration(keep: list[tuple[float, float]]) -> float:
    return sum(b - a for a, b in keep)
