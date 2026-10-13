"""
Checks Cinema City Poland's public JSON API for REAL showtimes (not just
catalog listings) of specific films on specific target dates, across all
Warsaw cinemas, and sends a Telegram message the moment a target date opens.

Two endpoints are used:
  1. cinemas/with-event/until/{date} -- lists all cinemas (id + name), so we
     can automatically find the Warsaw ones without hardcoding IDs blindly.
  2. film-events/in-cinema/{cinemaId}/at-date/{date} -- the REAL showtime
     data for one cinema on one date. If our film's ID appears here, tickets
     for that date at that cinema are genuinely on sale.

(The earlier films/until/{date} endpoint only returns a film catalog with
static metadata like releaseDate -- NOT actual ticket availability. That's
why it falsely triggered before.)
"""

import os
import sys
import time
from datetime import datetime, timezone

import requests

# ---- Films to watch ----
# target_date: the specific date we want tickets to exist for.
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
        "target_date": "2026-10-28",
    },
]

TENANT_ID = "10103"
LANG = "pl_PL"

BASE = f"https://www.cinema-city.pl/pl/data-api-service/v1/quickbook/{TENANT_ID}"

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


def api_get(path: str) -> dict:
    """GET with retries -- an occasional 403/429/5xx from a shared cloud IP is
    usually transient, so wait a bit and try again before giving up."""
    url = f"{BASE}/{path}"
    delays = [5, 15]  # seconds to wait before 2nd and 3rd attempts
    for attempt in range(len(delays) + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code in (403, 429) or resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} for {url}", response=resp)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == len(delays):
                raise
            print(f"  Request failed ({e}); retrying in {delays[attempt]}s...")
            time.sleep(delays[attempt])


# Warsaw cinemas, found earlier via the cinema-list endpoint. Hardcoded so the
# run doesn't depend on (and can't fail at) an extra request.
WARSAW_CINEMAS = [
    {"id": "1074", "name": "Warszawa - Arkadia"},
    {"id": "1061", "name": "Warszawa - Bemowo"},
    {"id": "1096", "name": "Warszawa - Białołęka Galeria Północna"},
    {"id": "1069", "name": "Warszawa - Janki"},
    {"id": "1070", "name": "Warszawa - Mokotów"},
    {"id": "1068", "name": "Warszawa - Promenada"},
    {"id": "1060", "name": "Warszawa - Sadyba"},
]


def get_warsaw_cinemas() -> list:
    return WARSAW_CINEMAS


def check_film_at_cinema_date(cinema_id: str, date: str, film_id: str):
    """True = film listed, False = checked fine but not listed, None = the check itself failed."""
    try:
        data = api_get(f"film-events/in-cinema/{cinema_id}/at-date/{date}?attr=&lang={LANG}")
    except (requests.RequestException, ValueError) as e:
        print(f"  Could not check cinema {cinema_id} on {date}: {e}", file=sys.stderr)
        return None
    films = data.get("body", {}).get("films", {})
    # 'films' here is often a dict keyed by film id, or a list -- handle both
    if isinstance(films, dict):
        found = film_id in films
    elif isinstance(films, list):
        found = any(f.get("id") == film_id for f in films)
    else:
        found = False
    return found


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

    warsaw_cinemas = get_warsaw_cinemas()



    had_total_failure = False

    for film in films_to_check:
        print(f"\n[{film['title']}] Checking target date {film['target_date']} across {len(warsaw_cinemas)} Warsaw cinema(s)...")
        found_at = []
        errors = 0
        for cinema in warsaw_cinemas:
            cid = cinema.get("id")
            name = cinema.get("name")
            result = check_film_at_cinema_date(cid, film["target_date"], film["id"])
            if result is None:
                errors += 1
                print(f"  ERROR checking {name} (id {cid})")
            elif result:
                found_at.append(name)
                print(f"  FOUND at {name} (id {cid})")
            else:
                print(f"  not yet at {name} (id {cid})")

        if found_at:
            message = (
                f"Tickets for {film['title']} on {film['target_date']} are now on sale!\n"
                f"{film['url']}\nCinemas: {', '.join(found_at)}"
            )
            try:
                send_telegram(token, chat_id, message)
                mark_notified(film["flag_file"])
                print(f"[{film['title']}] Notification sent, state saved.")
            except requests.RequestException as e:
                print(f"[{film['title']}] Telegram send FAILED: {e}", file=sys.stderr)
        elif errors == len(warsaw_cinemas):
            # Every check failed -- this is NOT "not on sale", it's "couldn't look".
            print(f"[{film['title']}] ALL checks failed -- could not determine sale status.", file=sys.stderr)
            had_total_failure = True
        else:
            note = f" ({errors} check(s) errored)" if errors else ""
            print(f"[{film['title']}] Not yet on sale for {film['target_date']} anywhere in Warsaw{note}.")

    if had_total_failure:
        sys.exit(1)  # make the run show as failed so it doesn't pass silently


if __name__ == "__main__":
    main()
