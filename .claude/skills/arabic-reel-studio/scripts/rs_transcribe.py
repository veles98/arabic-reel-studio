"""Arabic speech-to-text with word timestamps (faster-whisper, CPU int8)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from rs_common import decode_audio, log

SR = 16000
_MODELS: dict = {}


def transcribe(media: Path, model_name: str = "small", language: str = "ar",
               cache: Path | None = None, audio=None) -> list[dict]:
    """Return [{"w": word, "s": start, "e": end, "p": probability}, ...] on the source timeline."""
    st = media.stat()
    key = {"file": media.name, "size": st.st_size, "mtime": int(st.st_mtime),
           "model": model_name, "lang": language}
    if cache and cache.exists():
        data = json.loads(cache.read_text(encoding="utf-8"))
        if data.get("key") == key:
            log(f"transcript: reusing cache ({len(data['words'])} words)")
            return data["words"]

    from faster_whisper import WhisperModel  # imported late so `doctor` can report it cleanly

    if audio is None:
        audio = decode_audio(media, SR)
    t0 = time.time()
    if model_name not in _MODELS:
        log(f"transcript: loading model '{model_name}' (the first run downloads it once)...")
        _MODELS[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    model = _MODELS[model_name]
    segments, _info = model.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        beam_size=5,
        condition_on_previous_text=False,  # keeps retakes as spoken instead of "fixing" them
        vad_filter=False,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if not text:
                continue
            words.append({"w": text, "s": round(float(w.start), 3), "e": round(float(w.end), 3),
                          "p": round(float(w.probability), 3)})
    log(f"transcript: {len(words)} words in {time.time() - t0:.0f}s")
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"key": key, "words": words}, ensure_ascii=False),
                         encoding="utf-8")
    return words
