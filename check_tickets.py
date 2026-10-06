"""
Checks Cinema City Poland's public JSON API to see if tickets for one or more
specific films have gone on sale yet, and sends a Telegram message the moment
each one does.

This uses Cinema City's own "quickbook" data API -- the same API their
website's JavaScript calls -- which is public, unauthenticated, and well
documented by other open-source "ticket watcher" projects for Cinema City's
other country sites (Czech, Hungarian, etc).
"""

import os
import sys
from datetime import datetime, timezone

import requests

# ---- Films to watch ----
# Add as many as you like. "flag_file" must be unique per film so each one's
# notification state is tracked independently.
FILMS = [
    {
        "id": "8105s2r",
        "title": "Diuna: Czesc trzecia",
        "url": "https://www.cinema-city.pl/filmy/diuna-czesc-trzecia/8105s2r",
        "flag_file": "notified_8105s2r.flag",
    },
    {
        "id": "8222s2r",
        "title": "Clayface",
        "url": "https://www.cinema-city.pl/filmy/clayface/8222s2r",
        "flag_file": "notified_8222s2r.flag",
    },
]

# ---- Shared configuration ----
TENANT_ID = "10103"  # Cinema City Poland's tenant ID
LANG = "pl_PL"
CHECK_UNTIL_DATE = "2026-12-25"  # covers both test films; push further out if needed

API_URL = (
    f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/{TENANT_ID}"
    f"/films/until/{CHECK_UNTIL_DATE}?attr=&lang={LANG}"
)


def already_notified(flag_file: str) -> bool:
    return os.path.exists(flag_file)


def mark_notified(flag_file: str) -> None:
    with open(flag_file, "w", encoding="utf-8") as f:
        f.write(f"Notified at {datetime.now(timezone.utc).isoformat()}\n")


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
    resp.raise_for_status()


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set.", file=sys.stderr)
        sys.exit(1)

    films_to_check = [f for f in FILMS if not already_notified(f["flag_file"])]
    if not films_to_check:
        print("All watched films have already been notified -- nothing to check.")
        return

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
        "Referer": "https://www.cinema-city.pl/filmy/diuna-czesc-trzecia/8105s2r",
        "Origin": "https://www.cinema-city.pl",
    }

    print(f"Checking: {API_URL}")
    resp = requests.get(API_URL, headers=headers, timeout=30)
    print(f"HTTP status: {resp.status_code}")
    if resp.status_code != 200:
        print(f"Response body (first 1000 chars): {resp.text[:1000]}")
    resp.raise_for_status()
    body = resp.text
    print(f"Response length: {len(body)} characters")

    for film in films_to_check:
        # Substring match rather than parsing the JSON schema strictly -- this
        # API isn't officially documented, so matching the film ID directly
        # in the raw text is more resilient than depending on exact key names.
        idx = body.find(film["id"])
        found = idx != -1
        print(f"[{film['title']}] Film ID '{film['id']}' found: {found}")

        if found:
            # Show the surrounding JSON so we can tell a real showtime entry
            # (should mention cinemas, dates, event IDs nearby) from a bare
            # "this film exists" metadata listing with no actual sessions.
            start = max(0, idx - 300)
            end = min(len(body), idx + 500)
            print(f"[{film['title']}] Context around match:\n{body[start:end]}")

            message = f"Tickets for {film['title']} are now on sale!\n{film['url']}"
            try:
                send_telegram(token, chat_id, message)
                mark_notified(film["flag_file"])
                print(f"[{film['title']}] Notification sent, state saved.")
            except requests.RequestException as e:
                # Don't let a Telegram failure stop the other films from being
                # checked, and don't mark as notified if the message never sent.
                print(f"[{film['title']}] Telegram send FAILED: {e}", file=sys.stderr)
                if e.response is not None:
                    print(f"[{film['title']}] Telegram response body: {e.response.text}", file=sys.stderr)
        else:
            print(f"[{film['title']}] Not yet on sale.")


if __name__ == "__main__":
    main()
