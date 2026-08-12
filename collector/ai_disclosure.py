"""Steam AI Generated Content Disclosure.

Steam requires developers to declare AI-generated content, but the declaration
only exists on the rendered store page - it is absent from the appdetails API and
from SteamSpy. So this reads the store page and pulls the disclosure block out.

The scope classification matters more than the yes/no: "AI-assisted translation"
and "the majority of audio and visual assets are generated" are both disclosures,
and lumping them together would be misleading.
"""
import html as H
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (compatible; game-trends/1.0; weekly research)",
      # age gate would otherwise hide the page for mature titles
      "Cookie": "birthtime=568022401; wants_mature_content=1; lastagecheckage=1-0-1988"}
HEADING = "AI Generated Content Disclosure"


def classify(note):
    """Bucket a disclosure by how deep the AI use goes."""
    if not note:
        return "unspecified"
    n = note.lower()
    if any(k in n for k in ("majority of audio and visual", "all the pictures are generated",
                            "all art", "fully generated", "most of the art")):
        return "core assets"
    visual = any(k in n for k in ("background", "visual asset", "image", "art asset", "ui icon",
                                  "ui asset", "visually enhanced", "cg", "character art", "picture"))
    audio = any(k in n for k in ("voice", "music", "sound effect", "text-to-speech", "audio"))
    trans = any(k in n for k in ("translat", "localiz", "localis", "deepl"))
    if visual and audio:
        return "visuals + audio"
    if visual:
        return "some visuals"
    if audio:
        return "audio only"
    if trans:
        return "translation only"
    return "unspecified"


def check(appid, timeout=30):
    """Return (disclosed, note, scope). disclosed is None if the page was unreachable."""
    url = f"https://store.steampowered.com/app/{int(appid)}/?cc=us&l=english"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception:
        return None, None, None
    if HEADING not in page:
        return False, None, None
    m = re.search(HEADING + r".{0,1200}", page, re.S)
    txt = re.sub(r"<[^>]+>", " ", m.group(0) if m else "")
    txt = H.unescape(re.sub(r"\s+", " ", txt)).replace(HEADING, "").strip()
    txt = re.split(r"System Requirements|Minimum:|More like this|What Curators|Mature Content Description",
                   txt)[0]
    txt = txt.replace("The developers describe how their game uses AI Generated Content like this:",
                      "").strip()
    txt = txt[:400]
    return True, txt, classify(txt)
