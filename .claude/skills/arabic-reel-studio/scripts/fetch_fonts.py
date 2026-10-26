"""Download the free Arabic fonts (SIL Open Font License) from Google Fonts.

Each font is saved under fonts/<Family>/ together with its OFL.txt licence.
Run:  python fetch_fonts.py            (all five families)
      python fetch_fonts.py Cairo      (one family)
"""
from __future__ import annotations

import json
import re
import struct
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rs_common import FONTS_DIR, FONT_FAMILIES, log  # noqa: E402

LICENCE_SLUG = {
    "Cairo": "cairo",
    "Tajawal": "tajawal",
    "IBM Plex Sans Arabic": "ibmplexsansarabic",
    "Noto Kufi Arabic": "notokufiarabic",
    "Readex Pro": "readexpro",
}
WEIGHTS = (700,)


def _get(url: str) -> bytes:
    # A plain user agent makes Google Fonts serve full TrueType files (not woff2 subsets).
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/4.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def font_family_name(data: bytes) -> str | None:
    """Read the family name (name id 1) from a TrueType/OpenType file."""
    try:
        num_tables = struct.unpack(">H", data[4:6])[0]
        for i in range(num_tables):
            rec = data[12 + 16 * i: 28 + 16 * i]
            tag, _, off, _ = struct.unpack(">4sIII", rec)
            if tag != b"name":
                continue
            _, count, str_off = struct.unpack(">HHH", data[off:off + 6])
            best = None
            for j in range(count):
                pid, eid, lid, nid, ln, so = struct.unpack(
                    ">HHHHHH", data[off + 6 + 12 * j: off + 18 + 12 * j])
                if nid != 1:
                    continue
                raw = data[off + str_off + so: off + str_off + so + ln]
                if pid == 3:
                    name = raw.decode("utf-16-be", "replace")
                    if lid == 0x409:
                        return name
                    best = best or name
                elif pid == 1 and best is None:
                    best = raw.decode("latin-1", "replace")
            return best
    except Exception:
        return None
    return None


def fetch(family: str, manifest: dict) -> None:
    folder = FONTS_DIR / family.replace(" ", "")
    folder.mkdir(parents=True, exist_ok=True)
    for w in WEIGHTS:
        target = folder / f"{family.replace(' ', '')}-{w}.ttf"
        if not target.exists():
            css = _get("https://fonts.googleapis.com/css2?family="
                       + family.replace(" ", "+") + f":wght@{w}").decode("utf-8")
            urls = re.findall(r"url\((https://[^)]+\.ttf)\)", css)
            if not urls:
                raise RuntimeError(f"no TrueType link for {family} {w}")
            target.write_bytes(_get(urls[0]))
        name = font_family_name(target.read_bytes()) or family
        manifest[family] = {"file": str(target.relative_to(FONTS_DIR)).replace("\\", "/"),
                            "ass_name": name}
    lic = folder / "OFL.txt"
    if not lic.exists():
        lic.write_bytes(_get("https://raw.githubusercontent.com/google/fonts/main/ofl/"
                             + LICENCE_SLUG[family] + "/OFL.txt"))
    log(f"font ok: {family}  ({manifest[family]['ass_name']})")


def main() -> None:
    wanted = sys.argv[1:] or FONT_FAMILIES
    FONTS_DIR.mkdir(exist_ok=True)
    mpath = FONTS_DIR / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    failed = []
    for fam in wanted:
        if fam not in LICENCE_SLUG:
            log(f"unknown font: {fam}. Choose one of: {', '.join(LICENCE_SLUG)}")
            continue
        try:
            fetch(fam, manifest)
        except Exception as e:  # network trouble should not stop the others
            failed.append(fam)
            log(f"font FAILED: {fam}: {e}")
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (FONTS_DIR / "README.txt").write_text(
        "These fonts are licensed under the SIL Open Font License 1.1 (see OFL.txt in each folder).\n"
        "Downloaded from Google Fonts by fetch_fonts.py.\n", encoding="utf-8")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
