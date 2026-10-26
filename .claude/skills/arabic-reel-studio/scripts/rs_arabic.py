"""Small Arabic text helpers (normalising for comparison, cleaning for captions)."""
from __future__ import annotations

import re

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_PUNCT = re.compile(r"[\.\,\!\?\:\;\"\'\(\)\[\]\{\}«»…،؛؟\-–—_/\\]+")

FILLERS = {"اه", "ااه", "اهه", "ام", "امم", "اممم", "مم", "ممم", "اا", "ااا", "ايي", "uh", "um", "hmm",
           "eh", "ah"}


def normalize(word: str) -> str:
    w = _DIACRITICS.sub("", word)
    w = re.sub("[إأآٱ]", "ا", w)
    w = w.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    w = _PUNCT.sub("", w)
    return w.strip().lower()


def clean_caption_word(word: str, strip_punct: bool) -> str:
    w = word.strip()
    if strip_punct:
        w = _PUNCT.sub("", w).strip()
    # characters that have a meaning in ASS must not reach the subtitle file
    return w.replace("{", "").replace("}", "").replace("\\", "")


def is_filler(word: str) -> bool:
    return normalize(word) in FILLERS
