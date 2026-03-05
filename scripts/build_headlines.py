#!/usr/bin/env python3
import json, re, time, sys
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET

FEEDS = {
  "canada": [
    ("CBC Top Stories", "https://www.cbc.ca/webfeed/rss/rss-topstories"),
  ],
  "nl": [
    ("CBC Newfoundland & Labrador", "https://www.cbc.ca/webfeed/rss/rss-canada-newfoundland"),
    ("VOCM", "https://vocm.com/feed/"),
  ],
  "world": [
    ("BBC World", "https://feeds.bbci.co.uk/news/rss.xml?edition=int"),
    ("CNN Top Stories", "https://rss.cnn.com/rss/cnn_topstories.rss"),
  ],
}

MIX = {"canada": 7, "nl": 7, "world": 7}
SNIPPET_LEN = 220

def strip_html(s: str) -> str:
  if not s: return ""
  s = re.sub(r"<[^>]*>", " ", s)
  s = re.sub(r"\s+", " ", s).strip()
  return s

def pick_img_from_html(html: str):
  if not html: return None
  m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
  return m.group(1) if m else None

def get_text(el, tag_names):
  for name in tag_names:
    child = el.find(name)
    if child is not None and (child.text or "").strip():
      return (child.text or "").strip()
  return ""

def get_link(el):
  # RSS: <link>text</link> ; Atom: <link href="..."/>
  link = el.find("link")
  if link is None: return ""
  href = link.attrib.get("href")
  if href: return href.strip()
  return (link.text or "").strip()

def get_image(el, desc_html):
  # media:content url="..."
  for tag in ["{http://search.yahoo.com/mrss/}content", "content"]:
    m = el.find(tag)
    if m is not None and "url" in m.attrib:
      return m.attrib["url"]
  # enclosure url=""
  enc = el.find("enclosure")
  if enc is not None and "url" in enc.attrib:
    return enc.attrib["url"]
  return pick_img_from_html(desc_html)

def fetch(url: str) -> bytes:
  req = Request(url, headers={"User-Agent": "KayPageBot/1.0"})
  with urlopen(req, timeout=20) as r:
    return r.read()

def parse_feed(source_name: str, url: str):
  raw = fetch(url)
  root = ET.fromstring(raw)

  # RSS 2.0
  items = root.findall(".//item")
  if items:
    out = []
    for it in items:
      title = get_text(it, ["title"])
      link = get_text(it, ["link"])
      desc = get_text(it, ["description", "content:encoded"])
      snippet = strip_html(desc)[:SNIPPET_LEN]
      img = get_image(it, desc)
      if title and link:
        out.append({"source": source_name, "title": title, "link": link, "snippet": snippet, "image": img})
    return out

  # Atom
  entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
  if entries:
    out = []
    for en in entries:
      title = get_text(en, ["{http://www.w3.org/2005/Atom}title"])
      link = ""
      # Atom links can have rel="alternate"
      for l in en.findall("{http://www.w3.org/2005/Atom}link"):
        if l.attrib.get("href") and (l.attrib.get("rel") in (None, "", "alternate")):
          link = l.attrib["href"].strip()
          break
      summ = get_text(en, ["{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"])
      snippet = strip_html(summ)[:SNIPPET_LEN]
      img = pick_img_from_html(summ)
      if title and link:
        out.append({"source": source_name, "title": title, "link": link, "snippet": snippet, "image": img})
    return out

  return []

def main():
  grouped = {"canada": [], "nl": [], "world": []}
  for group, feed_list in FEEDS.items():
    for name, url in feed_list:
      try:
        items = parse_feed(name, url)
        grouped[group].extend(items)
      except Exception as e:
        # keep going even if one feed dies
        print(f"WARN: {name} failed: {e}", file=sys.stderr)

  chosen = []
  for group in ["canada", "nl", "world"]:
    chosen.extend(grouped[group][:MIX[group]])

  payload = {
    "generated_utc": datetime.now(timezone.utc).isoformat(),
    "items": chosen
  }

  with open("data/headlines.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

  print(f"Wrote {len(chosen)} headlines")

if __name__ == "__main__":
  main()
