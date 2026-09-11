"""
Scrapes a Facebook Page's public posts via the lightweight mbasic.facebook.com
interface (much simpler HTML than the main site) and writes an RSS feed.

Why mbasic.facebook.com: it serves plain, mostly-static HTML with minimal
JavaScript, so a simple requests+BeautifulSoup scraper can read it -- unlike
the main facebook.com site, which needs a full JS-rendering browser.

This needs your Facebook session cookies to get past the login wall, passed
in as environment variables (set as GitHub Actions Secrets, never hardcoded).

IMPORTANT: Facebook's HTML structure changes periodically and isn't meant to
be scraped, so the selectors below are a best-effort starting point, not a
guarantee. If the script stops finding posts, the site structure has likely
shifted and the CSS selectors below need updating -- open the page manually,
"View Source", and see what changed.
"""

import os
import sys
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator

# ---- Configuration ----
PAGE_PATH = "CinemaCityPoland"  # the part after facebook.com/
FEED_OUTPUT_PATH = "feed.xml"
MAX_ITEMS = 10

# ---- Load cookies from environment (set via GitHub Actions Secrets) ----
C_USER = os.environ.get("FB_C_USER", "")
XS = os.environ.get("FB_XS", "")
DATR = os.environ.get("FB_DATR", "")

if not C_USER or not XS:
    print("ERROR: FB_C_USER and FB_XS environment variables must be set.", file=sys.stderr)
    sys.exit(1)

cookies = {"c_user": C_USER, "xs": XS}
if DATR:
    cookies["datr"] = DATR

headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
}

url = f"https://mbasic.facebook.com/{PAGE_PATH}"

print(f"Fetching {url} ...")
response = requests.get(url, cookies=cookies, headers=headers, timeout=30)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

# ---- Parsing logic (this is the part most likely to need adjustment) ----
# mbasic Facebook posts are typically inside <div> or <article> blocks
# containing a link to "/story.php" or "/permalink.php" or similar.
# We look for links that look like individual post permalinks.

post_links = soup.find_all("a", href=True)
seen_hrefs = set()
items = []

for link in post_links:
    href = link["href"]
    if any(marker in href for marker in ["/story.php", "/permalink.php", "story_fbid="]):
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        full_url = href if href.startswith("http") else f"https://mbasic.facebook.com{href}"

        # Try to get nearby text as a rough "title" / summary.
        # This is approximate -- mbasic markup nests text unpredictably.
        parent = link.find_parent("div")
        text = parent.get_text(strip=True, separator=" ") if parent else link.get_text(strip=True)
        text = text[:300] if text else "(no text found)"

        items.append({"link": full_url, "title": text[:80] or "New post", "summary": text})

        if len(items) >= MAX_ITEMS:
            break

print(f"Found {len(items)} candidate post(s).")

if not items:
    print("WARNING: No posts found. The page structure may have changed, "
          "or the login wall wasn't bypassed. Check the raw HTML (see debug_output.html).", file=sys.stderr)
    with open("debug_output.html", "w", encoding="utf-8") as f:
        f.write(response.text)

# ---- Build the RSS feed ----
fg = FeedGenerator()
fg.title(f"{PAGE_PATH} - Facebook Page")
fg.link(href=f"https://www.facebook.com/{PAGE_PATH}", rel="alternate")
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
