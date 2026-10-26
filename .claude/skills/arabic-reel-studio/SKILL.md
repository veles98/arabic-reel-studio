---
name: arabic-reel-studio
description: Edit a talking video into a finished Arabic vertical reel (1080x1920) - cuts long silences and false starts only inside pauses, burns word-by-word Arabic captions, adds gentle zooms, -14 LUFS sound, an end card, cover.png and an edit report. Use when the user says «عدّل الفيديو», «مونتاج», «سوّ مونتاج», «جهّز الريل», "edit the video", or asks to change the result («كبّر الخط», «شيل الزوم», «قص أكثر», «غيّر اللون»...).
---

# Arabic Reel Studio

Everything runs locally: Python + ffmpeg + faster-whisper on the CPU. No accounts, no API keys.
Talk to the user in simple Arabic. Keep replies short.

All paths below are relative to the project folder (the folder that contains `setup.html`).
`RS` means: `python .claude/skills/arabic-reel-studio/scripts/reel.py`
(on Mac use `python3` if `python` is missing).

## 1. Before the first edit

1. Run `RS doctor`. If it does not end with `READY`, follow the install section of `README.md`
   (ffmpeg, Python packages, fonts) and run it again. Do not continue on `NOT READY`.
2. Settings file `brand.json` must sit in the project folder.
   - If it is missing, look for the newest `brand.json` in the user's Downloads folder
     (`%USERPROFILE%\Downloads` on Windows, `~/Downloads` on Mac). If found, move it here and tell the user.
   - If it is not anywhere, open the setup page for them
     (Windows: `start "" setup.html`, Mac: `open setup.html`) and say:
     «عبّ صفحة الإعداد واضغط "احفظ brand.json" واحفظه في مجلد المشروع، وبعدها قل: عدّل الفيديو».
     If they paste the JSON text from the page instead, save it as `brand.json` exactly as pasted.
   - The edit also works without `brand.json` (default look), so if the user wants to go ahead, go ahead.

## 2. «عدّل الفيديو»

1. Find the video: `RS list` shows video files in the project folder.
   - One file: use it. Several: use the one the user named, otherwise the newest; say which one you picked.
   - None: ask the user to drop the video into the project folder.
2. Run `RS edit "<file name>"`. It takes about 1–2 minutes per minute of video on a normal laptop
   (the first run also downloads the speech model once, about 1.5 GB for "medium").
   Use a long timeout (10 minutes) or run it in the background and wait for it.
3. When it ends with `DONE`, read `out/<video name>/edits.txt` and reply in 3–5 short Arabic lines:
   the length before → after, what was removed (pauses, retakes), and where the files are:
   - `out/<name>/<name>_reel.mp4` the reel, ready for Instagram, TikTok and YouTube Shorts
   - `out/<name>/cover.png` the cover
   - `out/<name>/captions.srt` the subtitles as text
   - `out/<name>/edits.txt` what was cut and why
   Then offer the common changes in one line («تبي الخط أكبر؟ بدون زووم؟ قص أكثر؟»).
4. On `ERROR`, read the message, fix what you can (missing ffmpeg, missing font, wrong file name)
   and run again. Explain anything you cannot fix in one plain sentence.

## 3. Changing the result

All settings live in `brand.json`. Change them with `RS set key=value` (several at once is fine),
then run `RS edit` again on the same video. The speech transcript is cached, so a re-edit is faster.

| The user says | Run |
|---|---|
| «كبّر الخط» / «صغّر الخط» | `RS set captions.size=<current ±10>` (range 60–124; `RS show` shows the current value) |
| «شيل الزوم» / «رجّع الزوم» | `RS set zoom.enabled=false` / `true` |
| «زووم أقوى» / «أخف» | `RS set zoom.strength=1.12` / `1.05` |
| «قص أكثر» / «أسرع» | `RS set cut.keep_pause=0.12 cut.min_silence=0.3` |
| «قص أقل» / «خلّه طبيعي أكثر» | `RS set cut.keep_pause=0.35 cut.min_silence=0.6` |
| «لا تقص شي» | `RS set cut.enabled=false` |
| «لا تحذف الإعادات» | `RS set cut.remove_retakes=false` |
| «الترجمة فوق / بالنص / تحت» | `RS set captions.position=upper` / `middle` / `lower` |
| «كلمتين / ثلاث / أربع كلمات» | `RS set captions.max_words=2` / `3` / `4` |
| «كلمة كلمة» / «سطرين» / «داخل صندوق» | `RS set captions.style=word` / `block` / `boxed` |
| «بدون ترجمة» | `RS set captions.enabled=false` |
| «غيّر لون الكلمة إلى أخضر» | `RS set colors.accent="#3DDC97"` (use a clear hex colour that fits the request) |
| «غيّر الخط إلى تجوال» | `RS set font="Tajawal"` (Cairo, Tajawal, IBM Plex Sans Arabic, Noto Kufi Arabic, Readex Pro) |
| «شيل الخاتمة» / «غيّر جملة الخاتمة إلى ...» | `RS set ending.enabled=false` / `RS set ending.text="..."` |
| «عنوان الغلاف ...» | `RS set cover.title="..."` |
| «الفيديو الأفقي قصّه بدل الضباب» | `RS set frame.horizontal=smart` (or `center`, or back to `blur`) |
| «الترجمة كتبت كلمة غلط» | `RS fix "الكلمة الغلط" "الصح"` (one word each), then edit again |
| «التفريغ بطيء» | `RS set whisper.model=small` (faster, less accurate Arabic) |

For anything else, open `brand.json`, change the matching field (keep valid JSON), and edit again.
To restyle everything, open `setup.html` again; it can load the current `brand.json`.

## Rules

- Never cut inside a word. The tool only cuts inside measured silence; do not hand-edit the cut list.
- Keep the user's original video untouched; outputs only go to `out/`.
- Do not upload anything anywhere. Everything stays on the user's computer.
- If disk space is under 3 GB, say so before editing long videos.
