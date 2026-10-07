"""
Checks Cinema City Poland's public JSON API to see if a specific film has a
showing on (or after) a specific target date yet, and sends a Telegram
message the moment it does.

Why target dates matter: a film can go "on sale" for a limited preview
screening (e.g. Dec 15) well before its wide release date (e.g. Dec 18)
actually unlocks. Just checking "does this film ID appear anywhere" isn't
enough -- we need to look at the actual event dates attached to it.

Uses Cinema City's public "quickbook" data API (the same one their website's
own JavaScript calls).
"""

import os
import sys
from datetime import datetime, timezone

import requests

# ---- Films to watch ----
# target_date: only notify once a showing exists ON or AFTER this date.
# Set to None to notify as soon as the film has ANY showing at all.
FILMS = [
    {
        "id": "8105s2r",
        "title": "Diuna: Czesc trzecia",
        "url": "https://www.cinema-city.pl/filmy/diuna-czesc-trzecia/8105s2r",
        "flag_file": "notified_8105s2r.flag",
        "target_date": "2026-12-18",
    },
    {
        "id": "8222s2r",
        "title": "Clayface",
        "url": "https://www.cinema-city.pl/filmy/clayface/8222s2r",
        "flag_file": "notified_8222s2r.flag",
        "target_date": None,
    },
]

TENANT_ID = "10103"
LANG = "pl_PL"
CHECK_UNTIL_DATE = "2026-12-25"

API_URL = (
    f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/{TENANT_ID}"
    f"/films/until/{CHECK_UNTIL_DATE}?attr=&lang={LANG}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    "Referer": "https://www.cinema-city.pl/filmy/diuna-czesc-trzecia/8105s2r",
    "Origin": "https://www.cinema-city.pl",
}


def already_notified(flag_file: str) -> bool:
    return os.path.exists(flag_file)


def mark_notified(flag_file: str) -> None:
    with open(flag_file, "w", encoding="utf-8") as f:
        f.write(f"Notified at {datetime.now(timezone.utc).isoformat()}\n")


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
    resp.raise_for_status()


def extract_event_date(event: dict) -> str:
    """Try a few likely field names/formats since this API isn't documented."""
    for key in ("businessDate", "date", "eventDateTime", "startTime", "showTime"):
        value = event.get(key)
        if value:
            return str(value)[:10]  # just the YYYY-MM-DD part
    return ""


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

    print(f"Checking: {API_URL}")
    resp = requests.get(API_URL, headers=HEADERS, timeout=30)
    print(f"HTTP status: {resp.status_code}")
    resp.raise_for_status()

    try:
        data = resp.json()
    except ValueError:
        print("ERROR: response wasn't valid JSON. First 1000 chars:", file=sys.stderr)
        print(resp.text[:1000], file=sys.stderr)
        sys.exit(1)

    body_section = data.get("body", {})
    events = body_section.get("events", [])
    print(f"Total events in response: {len(events)}")

    for film in films_to_check:
        matching_events = [e for e in events if e.get("filmId") == film["id"]]
        dates_found = sorted({extract_event_date(e) for e in matching_events if extract_event_date(e)})
        print(f"[{film['title']}] Showing dates found: {dates_found}")

        if not matching_events:
            print(f"[{film['title']}] No events at all yet.")
            continue

        target_date = film.get("target_date")
        if target_date:
            qualifying = [d for d in dates_found if d >= target_date]
            found = bool(qualifying)
            print(f"[{film['title']}] Target date {target_date} -- qualifying dates: {qualifying}")
        else:
            found = True  # any showing at all counts

        if found:
            message = f"Tickets for {film['title']} are now on sale!\n{film['url']}\nDates seen: {', '.join(dates_found)}"
            try:
                send_telegram(token, chat_id, message)
                mark_notified(film["flag_file"])
                print(f"[{film['title']}] Notification sent, state saved.")
            except requests.RequestException as e:
                print(f"[{film['title']}] Telegram send FAILED: {e}", file=sys.stderr)
        else:
            print(f"[{film['title']}] On sale, but not yet for the target date.")


if __name__ == "__main__":
    main()
