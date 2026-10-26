# استوديو الريلز العربي (Arabic Reel Studio)

أداة مجانية تشتغل على جهازك مع Claude Code: تعطيها فيديو تتكلم فيه، وترجع لك ريل عمودي جاهز للنشر.

**وش تسوي بالضبط؟**

- تقص الصمت الطويل، وتحذف البدايات المتعثرة والإعادات وتبقي آخر محاولة. القص يكون داخل الوقفات فقط، ولا يقطع أي كلمة.
- تكتب ترجمة عربية على الفيديو بحروف متصلة وترتيب صحيح من اليمين لليسار، والكلمة اللي تنطقها تتلوّن.
- تحول الفيديو إلى 1080×1920، وإذا كان أفقي تحطه كامل مع خلفية ضبابية أو تقصه.
- تضيف تقريب (زووم) خفيف على الجمل المهمة.
- تضبط الصوت على ‎-14 LUFS‎ (المستوى المناسب لانستقرام وتيك توك ويوتيوب شورتس).
- تضيف خاتمة فيها اسمك ومعرّفك وجملة مثل «تابعني لأكثر».
- تطلع لك غلاف `cover.png`، وملف ترجمة `captions.srt`، وتقرير `edits.txt` يشرح وش انقص وليش.

كل شي يصير على جهازك. ما تحتاج حساب ولا مفتاح API ولا اشتراك.

---

## الطريقة السريعة (مع Claude Code)

1. سوّ مجلد فاضي، وافتحه في Claude Code.
2. الصق هذي الجملة:

```
ثبّت لي استوديو الريلز العربي من https://github.com/YOUR-ACCOUNT/arabic-reel-studio في هذا المجلد، واتبع قسم «التثبيت عن طريق Claude» في ملف README.
```

3. بتنفتح صفحة الإعداد: اكتب اسمك ومعرّفك، واختر الخط والألوان وشكل الترجمة والخاتمة، واضغط «احفظ brand.json» واحفظه في نفس المجلد.
4. حط أي فيديو تتكلم فيه داخل المجلد، وقل لـ Claude: **«عدّل الفيديو»**.

النتيجة تطلع في مجلد `out/` باسم الفيديو.

### بعدها تقدر تقول مثلاً

| تقول | وش يصير |
|---|---|
| «كبّر الخط» أو «صغّر الخط» | يغيّر حجم الترجمة |
| «شيل الزوم» | بدون تقريب |
| «قص أكثر» أو «قص أقل» | وقفات أقصر أو أطول |
| «لا تحذف الإعادات» | يبقي كل المحاولات |
| «الترجمة فوق» أو «بالنص» أو «تحت» | يغيّر مكان الترجمة |
| «سطرين» أو «داخل صندوق» أو «كلمة كلمة» | يغيّر شكل الترجمة |
| «غيّر اللون إلى أخضر» | يغيّر لون الكلمة المنطوقة |
| «شيل الخاتمة» | بدون خاتمة |
| «الترجمة كتبت Cloud والصح Claude» | يصحح الكلمة في كل الفيديوهات الجاية |

Claude يعدّل الإعدادات في `brand.json` ويطلع الفيديو من جديد.

---

## المتطلبات

- ويندوز 10/11 أو ماك.
- مساحة فاضية 3 جيجا على الأقل (نموذج التفريغ نحو 1.5 جيجا ويتحمل أول مرة فقط).
- إنترنت أول مرة فقط (لتحميل البرامج والخطوط ونموذج التفريغ). بعدها يشتغل بدون إنترنت.

## التثبيت اليدوي

### ويندوز

افتح PowerShell واكتب:

```powershell
winget install -e --id Gyan.FFmpeg
winget install -e --id Python.Python.3.12
```

سكّر PowerShell وافتحه من جديد (عشان يتعرف على البرامج)، وبعدين داخل مجلد المشروع:

```powershell
python -m pip install -r requirements.txt
python .claude/skills/arabic-reel-studio/scripts/reel.py fonts
python .claude/skills/arabic-reel-studio/scripts/reel.py doctor
```

إذا ما عندك `winget`: نزّل Python من python.org (فعّل خيار Add to PATH)، ونزّل ffmpeg من gyan.dev وحط مجلد `bin` في مجلد المشروع باسم `tools/ffmpeg/bin`.

### ماك

افتح Terminal واكتب (يحتاج Homebrew من brew.sh):

```bash
brew install ffmpeg python
python3 -m pip install -r requirements.txt
python3 .claude/skills/arabic-reel-studio/scripts/reel.py fonts
python3 .claude/skills/arabic-reel-studio/scripts/reel.py doctor
```

إذا طلع آخر سطر `READY` فكل شي جاهز.

> faster-whisper يشتغل على المعالج (CPU) بدقة int8 افتراضياً، وما يحتاج كرت شاشة.

---

## التثبيت عن طريق Claude

(هذا القسم مكتوب لـ Claude Code. نفّذه خطوة خطوة، وكلّم المستخدم بالعربي وباختصار.)

1. Put the repository into the current folder:
   - If the folder is empty: `git clone https://github.com/YOUR-ACCOUNT/arabic-reel-studio .`
   - If it is not empty: clone into a temporary sub-folder and move its contents (including `.claude/`) up into the current folder.
   - If `git` is missing: download `https://github.com/YOUR-ACCOUNT/arabic-reel-studio/archive/refs/heads/main.zip`, extract it, and move the contents up the same way.
2. Check Python 3.9 or newer (`python --version`, on Mac `python3 --version`). If missing: Windows `winget install -e --id Python.Python.3.12`, Mac `brew install python`.
3. Check ffmpeg (`ffmpeg -version`). If missing: Windows `winget install -e --id Gyan.FFmpeg`, Mac `brew install ffmpeg`. The scripts also find a fresh winget install before the terminal is reopened.
4. `python -m pip install -r requirements.txt`
5. `python .claude/skills/arabic-reel-studio/scripts/reel.py fonts`
6. `python .claude/skills/arabic-reel-studio/scripts/reel.py doctor` must end with `READY`. If not, fix the line it reports and run it again.
7. Open the setup page: Windows `start "" setup.html`, Mac `open setup.html`.
8. Tell the user, in Arabic: fill the page, press «احفظ brand.json», save it into this folder, put a talking video in this folder, then say «عدّل الفيديو».
9. The editing skill is `.claude/skills/arabic-reel-studio/SKILL.md`. If Claude Code does not pick it up in this session, ask the user to close Claude Code and open it again in this folder.

---

## وين تروح الملفات؟

```
مجلد المشروع/
  setup.html            صفحة الإعداد
  brand.json            إعداداتك (تنحفظ من صفحة الإعداد)
  فيديوك.mp4            الفيديو الأصلي (ما يتغير)
  out/فيديوك/
    فيديوك_reel.mp4     الريل الجاهز
    cover.png           الغلاف
    captions.srt        الترجمة كنص
    edits.txt           تقرير المونتاج
```

## أسئلة سريعة

**كم ياخذ وقت؟** تقريباً دقيقة إلى دقيقتين لكل دقيقة فيديو على لابتوب عادي. أول مرة أطول لأنه يحمّل نموذج التفريغ.

**الترجمة فيها كلمة غلط؟** قل لـ Claude: «الترجمة كتبت كذا والصح كذا». التصحيح ينحفظ ويتطبق على الفيديوهات الجاية.

**يدعم اللهجات؟** نعم، يتعرف على الكلام العربي بشكل عام. الدقة أعلى مع صوت واضح ومايك قريب.

**أبي أسرع؟** قل «التفريغ بطيء» ويستخدم نموذج أصغر وأسرع (والدقة أقل شوي).

## الرخص

- كود الأداة: رخصة MIT (ملف `LICENSE`).
- الخطوط (Cairo, Tajawal, IBM Plex Sans Arabic, Noto Kufi Arabic, Readex Pro): رخصة SIL Open Font License، تتحمّل من Google Fonts مع ملف الرخصة داخل مجلد `fonts/`.
- faster-whisper (MIT) و ffmpeg (LGPL/GPL) تتثبت بشكل منفصل من مصادرها الرسمية.
