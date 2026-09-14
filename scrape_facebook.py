"""
Fetches a Facebook Page's PUBLIC posts anonymously (no login/cookies) via
two candidate sources, and writes an RSS feed from whichever works:

  1. The Facebook "Page Plugin" embed -- a widget Facebook provides
     specifically for showing a public Page's posts on external websites,
     with no login required by design.
  2. mbasic.facebook.com -- the lightweight, low-JS mobile interface,
     fetched anonymously this time (no cookies).

We deliberately do NOT send session cookies here. A cookie replayed from an
unrecognized server (like a GitHub Actions runner) can look like a hijacked
session and trigger a security checkpoint -- worse than just being
anonymous. An anonymous request to a fully public Page should get the same
"logged-out preview" a real visitor without an account would see.

IMPORTANT: Facebook's HTML structure changes periodically and isn't meant
to be scraped, so the parsing logic below is a best-effort starting point,
not a guarantee. If it stops finding posts, check the diagnostic output
this script prints -- it shows exactly what each source actually returned.
"""

import os
import sys
import urllib.parse
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# ---- Configuration ----
PAGE_PATH = "CinemaCityPoland"  # the part after facebook.com/
FEED_OUTPUT_PATH = "feed.xml"
MAX_ITEMS = 10

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

page_url = f"https://www.facebook.com/{PAGE_PATH}"
plugin_url = (
    "https://www.facebook.com/plugins/page.php?"
    + urllib.parse.urlencode({
        "href": page_url,
        "tabs": "timeline",
        "small_header": "false",
        "hide_cover": "false",
        "show_facepile": "false",
    })
)


def fetch_and_report(label, url):
    print(f"\n==== Trying: {label} ====")
    print(f"URL: {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"Request failed: {e}")
        return ""
    text = resp.text
    lower = text.lower()
    print(f"HTTP status: {resp.status_code}")
    print(f"Response length: {len(text)} characters")
    print(f"Contains 'login': {'login' in lower}")
    print(f"Contains the page name: {PAGE_PATH.lower() in lower}")
    print("---- First 1500 characters ----")
    print(text[:1500])
    print("---- End snippet ----")
    return text


# Try the Page Plugin first (built for public, no-login embedding).
plugin_html = fetch_and_report("Page Plugin (no cookies)", plugin_url)

# Fallback: plain mbasic fetch, also anonymous.
mbasic_html = fetch_and_report(
    "mbasic (no cookies)", f"https://mbasic.facebook.com/{PAGE_PATH}"
)

# Use whichever response looks more promising for the actual parsing step.
response_text = plugin_html or mbasic_html or ""
soup = BeautifulSoup(response_text, "html.parser")

# ---- Parsing logic (this is the part most likely to need adjustment) ----
# Look for links that look like individual post permalinks.
post_links = soup.find_all("a", href=True)
seen_hrefs = set()
items = []

for link in post_links:
    href = link["href"]
    if any(marker in href for marker in ["/story.php", "/permalink.php", "story_fbid=", "/posts/"]):
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        full_url = href if href.startswith("http") else f"https://www.facebook.com{href}"

        parent = link.find_parent("div")
        text = parent.get_text(strip=True, separator=" ") if parent else link.get_text(strip=True)
        text = text[:300] if text else "(no text found)"

        items.append({"link": full_url, "title": text[:80] or "New post", "summary": text})

        if len(items) >= MAX_ITEMS:
            break

print(f"\nFound {len(items)} candidate post(s).")

if not items:
    print("WARNING: No posts found in either source -- see diagnostic output above.", file=sys.stderr)
    with open("debug_output.html", "w", encoding="utf-8") as f:
        f.write(response_text)

# ---- Build the RSS feed ----
fg = FeedGenerator()
fg.title(f"{PAGE_PATH} - Facebook Page")
fg.link(href=page_url, rel="alternate")
fg.description(f"Unofficial RSS feed for the {PAGE_PATH} Facebook Page")

for item in items:
    fe = fg.add_entry()
    fe.title(item["title"])
    fe.link(href=item["link"])
    fe.description(item["summary"])
    fe.guid(item["link"], permalink=True)
    fe.pubDate(datetime.now(timezone.utc))

fg.rss_file(FEED_OUTPUT_PATH)
print(f"Wrote {FEED_OUTPUT_PATH} with {len(items)} item(s).")
