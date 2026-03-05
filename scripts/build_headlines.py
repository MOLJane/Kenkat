#!/usr/bin/env python3
import json, re, os, sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from xml.etree import ElementTree as ET

OUT_DIR = "data"
OUT_PATH = os.path.join(OUT_DIR, "headlines.json")

FEEDS = [
  ("CBC Top Stories", "https://www.cbc.ca/webfeed/rss/rss-topstories"),
  ("CBC Newfoundland & Labrador", "https://www.cbc.ca/webfeed/rss/rss-canada-newfoundland"),
  ("VOCM", "https://vocm.com/feed/"),
  ("BBC World", "https://feeds.bbci.co.uk/news/rss.xml?edition=int"),
]

MAX_ITEMS_PER_FEED = 6
SNIPPET_LEN = 180
FETCH_TIMEOUT = 6  # seconds per feed

IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)

def strip_html(s: str) -> str:
  if not s: return ""
  s = re.sub(r"<[^>]+>", " ", s)
  s = re.sub(r"\s+", " ", s).strip()
  return s

def first_text(parent, names):
  for child in list(parent):
    tag = child.tag.split("}")[-1]
    if tag in names and (child.text or "").strip():
      return (child.text or "").strip()
  return ""

def find_link(item):
  # RSS: <link>text</link> ; Atom: <link href="..."/>
  for child in list(item):
    tag = child.tag.split("}")[-1]
    if tag == "link":
      href = (child.attrib.get("href") or "").strip()
      if href:
        return href
      txt = (child.text or "").strip()
      if txt:
        return txt
  return ""

def image_from_description(html):
  if not html: return ""
  m = IMG_RE.search(html)
  return m.group(1).strip() if m else ""

def find_image(item, desc_html):
  # media:content url="..."
  for child in list(item):
    tag = child.tag.split("}")[-1]
    if tag == "content" and (child.attrib.get("url") or "").strip():
      return child.attrib["url"].strip()

  # enclosure url="..."
  for child in list(item):
    tag = child.tag.split("}")[-1]
    if tag == "enclosure" and (child.attrib.get("url") or "").strip():
      return child.attrib["url"].strip()

  # fallback: <img> in description
  return image_from_description(desc_html)

def fetch_bytes(url):
  req = Request(url, headers={"User-Agent": "KayPageBot/1.0 (+github actions)"})
  with urlopen(req, timeout=FETCH_TIMEOUT) as r:
    return r.read()

def parse_feed(name, url):
  xml_bytes = fetch_bytes(url)
  root = ET.fromstring(xml_bytes)

  items = root.findall(".//item")
  out = []
  if items:
    for it in items[:MAX_ITEMS_PER_FEED]:
      title = first_text(it, {"title"}) or "(no title)"
      link  = first_text(it, {"link"}) or url
      desc  = first_text(it, {"description"}) or first_text(it, {"encoded"}) or ""
      snippet = strip_html(desc)[:SNIPPET_LEN]
      pub = first_text(it, {"pubDate"})[:80]
      image = find_image(it, desc)
      if title and link:
        out.append({"source": name, "title": title, "link": link, "snippet": snippet, "pub": pub, "image": image})
    return out

  # Atom fallback
  entries = root.findall(".//{*}entry")
  for en in entries[:MAX_ITEMS_PER_FEED]:
    title = first_text(en, {"title"}) or "(no title)"
    link = ""
    for l in en.findall(".//{*}link"):
      href = (l.attrib.get("href") or "").strip()
      if href and (l.attrib.get("rel") in (None, "", "alternate")):
        link = href
        break
    summ = first_text(en, {"summary"}) or first_text(en, {"content"}) or ""
    snippet = strip_html(summ)[:SNIPPET_LEN]
    image = image_from_description(summ)
    pub = (first_text(en, {"updated"}) or first_text(en, {"published"}))[:80]
    if title and link:
      out.append({"source": name, "title": title, "link": link, "snippet": snippet, "pub": pub, "image": image})
  return out

def main():
  all_items = []
  errors = []

  print("Building headlines.json...")
  for name, url in FEEDS:
    try:
      print(f" - fetch {name}")
      items = parse_feed(name, url)
      print(f"   got {len(items)} items")
      all_items.extend(items)
    except (HTTPError, URLError, TimeoutError, ET.ParseError) as e:
      msg = f"{name} failed: {e}"
      print("   WARN:", msg)
      errors.append(msg)
    except Exception as e:
      msg = f"{name} failed: {repr(e)}"
      print("   WARN:", msg)
      errors.append(msg)

  os.makedirs(OUT_DIR, exist_ok=True)
  payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "count": len(all_items),
    "items": all_items,
    "errors": errors,
  }

  with open(OUT_PATH, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

  print(f"Wrote {OUT_PATH} with {len(all_items)} items")
  if errors:
    print("Non-fatal feed errors:")
    for e in errors:
      print(" -", e)

if __name__ == "__main__":
  sys.exit(main() or 0)
