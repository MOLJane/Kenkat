#!/usr/bin/env python3
import json, re, sys, os
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.parse import urljoin
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

# ---- OPTIONAL "pretty cards" fallback ----
# If RSS has no image, try <meta property="og:image" ...> from the article page.
ENABLE_OG_IMAGE_FALLBACK = True
# Prevent Actions from hanging: scrape at most N items total
OG_IMAGE_MAX_TOTAL = 10
# Only scrape for these sources (tune as you like)
OG_IMAGE_ALLOWED_SOURCES = {"CBC Top Stories", "CBC Newfoundland & Labrador", "BBC World", "CNN Top Stories"}

# Namespaces commonly seen in feeds
NS = {
  "media": "http://search.yahoo.com/mrss/",
  "content": "http://purl.org/rss/1.0/modules/content/",
  "atom": "http://www.w3.org/2005/Atom",
}

def strip_html(s: str) -> str:
  if not s:
    return ""
  s = re.sub(r"<[^>]*>", " ", s)
  s = re.sub(r"\s+", " ", s).strip()
  return s

def pick_img_from_html(html: str):
  if not html:
    return None
  m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
  return m.group(1).strip() if m else None

def fetch_bytes(url: str, timeout: int = 20) -> bytes:
  req = Request(url, headers={
    "User-Agent": "KayPageBot/2.0 (+https://github.com/moljane/Kenkat)",
    "Accept": "*/*",
  })
  with urlopen(req, timeout=timeout) as r:
    return r.read()

def fetch_text(url: str, timeout: int = 20) -> str:
  return fetch_bytes(url, timeout=timeout).decode("utf-8", errors="replace")

def safe_findtext(el, path: str) -> str:
  t = el.findtext(path)
  return (t or "").strip()

def get_rss_description(it) -> str:
  # Prefer content:encoded if present
  encoded = safe_findtext(it, f"{{{NS['content']}}}encoded")
  if encoded:
    return encoded
  desc = safe_findtext(it, "description")
  return desc

def get_rss_link(it) -> str:
  return safe_findtext(it, "link")

def get_media_image(it, base_url: str, desc_html: str):
  # 1) media:thumbnail url=
  thumb = it.find(f"{{{NS['media']}}}thumbnail")
  if thumb is not None and thumb.attrib.get("url"):
    return urljoin(base_url, thumb.attrib["url"].strip())

  # 2) media:content url=
  mc = it.find(f"{{{NS['media']}}}content")
  if mc is not None and mc.attrib.get("url"):
    return urljoin(base_url, mc.attrib["url"].strip())

  # 3) enclosure url=
  enc = it.find("enclosure")
  if enc is not None and enc.attrib.get("url"):
    return urljoin(base_url, enc.attrib["url"].strip())

  # 4) first <img> from description/content
  img = pick_img_from_html(desc_html)
  if img:
    return urljoin(base_url, img.strip())

  return None

def get_atom_link(en) -> str:
  # Atom links can have rel="alternate"
  for l in en.findall(f"{{{NS['atom']}}}link"):
    href = (l.attrib.get("href") or "").strip()
    rel = (l.attrib.get("rel") or "").strip()
    if href and (rel in ("", "alternate")):
      return href
  return ""

def get_atom_summary(en) -> str:
  summ = safe_findtext(en, f"{{{NS['atom']}}}summary")
  if summ:
    return summ
  cont = safe_findtext(en, f"{{{NS['atom']}}}content")
  return cont

def og_image_from_page(article_url: str):
  try:
    html = fetch_text(article_url, timeout=12)
    # property="og:image" content="..."
    m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
    if not m:
      # Some pages use name="og:image"
      m = re.search(r'<meta[^>]+name=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html, flags=re.I)
    if m:
      return m.group(1).strip()
  except Exception:
    return None
  return None

def parse_feed(source_name: str, url: str):
  raw = fetch_bytes(url)
  root = ET.fromstring(raw)

  # RSS 2.0
  items = root.findall(".//item")
  if items:
    out = []
    for it in items:
      title = safe_findtext(it, "title")
      link = get_rss_link(it)
      desc_html = get_rss_description(it)
      snippet = strip_html(desc_html)[:SNIPPET_LEN]
      img = get_media_image(it, url, desc_html)
      if title and link:
        out.append({
          "source": source_name,
          "title": title,
          "link": link,
          "snippet": snippet,
          "pub": safe_findtext(it, "pubDate"),
          "image": img or ""
        })
    return out

  # Atom
  entries = root.findall(".//atom:entry", namespaces=NS)
  if entries:
    out = []
    for en in entries:
      title = safe_findtext(en, f"{{{NS['atom']}}}title")
      link = get_atom_link(en)
      summ_html = get_atom_summary(en)
      snippet = strip_html(summ_html)[:SNIPPET_LEN]
      img = pick_img_from_html(summ_html)
      if title and link:
        out.append({
          "source": source_name,
          "title": title,
          "link": link,
          "snippet": snippet,
          "pub": safe_findtext(en, f"{{{NS['atom']}}}updated"),
          "image": (img or "")
        })
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
        print(f"WARN: {name} failed: {e}", file=sys.stderr)

  chosen = []
  for group in ["canada", "nl", "world"]:
    chosen.extend(grouped[group][:MIX[group]])

  # Optional og:image fill-in (limited so Actions won't hang)
  if ENABLE_OG_IMAGE_FALLBACK:
    filled = 0
    for item in chosen:
      if filled >= OG_IMAGE_MAX_TOTAL:
        break
      if item.get("image"):
        continue
      if item.get("source") not in OG_IMAGE_ALLOWED_SOURCES:
        continue
      link = item.get("link") or ""
      if not link.startswith("http"):
        continue
      og = og_image_from_page(link)
      if og:
        item["image"] = og
        filled += 1

  payload = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "count": len(chosen),
    "items": chosen
  }

  os.makedirs("data", exist_ok=True)
  with open("data/headlines.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

  print(f"Wrote {len(chosen)} headlines")

if __name__ == "__main__":
  main()
