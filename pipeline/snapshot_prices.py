"""Fetch current market prices and publish one snapshot per UTC date."""

import argparse
from contextlib import closing
from datetime import date, datetime, timezone
import fcntl
from http.client import HTTPException
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import config


def fetch_json(url, *, fresh=False):
    headers = {"User-Agent": config.USER_AGENT}
    if fresh:
        headers["Cache-Control"] = "no-cache"
    request = Request(url, headers=headers)
    for attempt in range(6):
        try:
            with urlopen(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as exc:
            with closing(exc):
                if attempt == 5 or not (exc.code == 429 or 500 <= exc.code < 600):
                    raise
        except (OSError, HTTPException):
            if attempt == 5:
                raise
        time.sleep(min(60, 3 * 2**attempt))


def write_snapshot(folder, snapshot_date, reference):
    cards = json.loads(reference.read_text(encoding="utf-8"))["cards"]
    card_ids = list(dict.fromkeys(card["id"] for card in cards if card["_set"] in config.SETS))
    groups = {}
    for group_id in config.SETS.values():
        if groups:
            time.sleep(0.1)
        url = f"https://tcgcsv.com/tcgplayer/{config.TCGPLAYER_CATEGORY_ID}/{group_id}/prices"
        rows = fetch_json(url)["results"]
        if not isinstance(rows, list):
            raise ValueError(f"invalid TCGplayer results for group {group_id}")
        groups[str(group_id)] = rows

    cardmarket = {}
    for index, card_id in enumerate(card_ids):
        if index:
            time.sleep(0.05)
        try:
            url = f"https://api.tcgdex.net/v2/en/cards/{quote(card_id, safe='')}"
            prices = fetch_json(url, fresh=True)["pricing"]["cardmarket"]
        except (OSError, HTTPException, KeyError, TypeError, ValueError) as exc:
            print(f"Cardmarket {card_id}: {exc}", file=sys.stderr)
            continue
        if isinstance(prices, dict) and prices:
            cardmarket[card_id] = prices

    missing = len(card_ids) - len(cardmarket)
    if missing * 10 > len(card_ids):
        raise ValueError(f"Cardmarket prices missing for {missing}/{len(card_ids)} cards")

    fx = fetch_json("https://api.frankfurter.dev/v1/latest?from=EUR&to=USD")
    rate = fx["rates"]["USD"]
    files = {
        "tcgplayer.json": {"date": snapshot_date, "source": "tcgcsv_daily", "groups": groups},
        "cardmarket.json": {"date": snapshot_date, "source": "tcgdex", "cards": cardmarket},
        "fx.json": fx,
    }
    for name, payload in files.items():
        with (folder / name).open("w", encoding="utf-8") as stream:
            json.dump(payload, stream)
    (folder / "_SUCCESS").touch()
    print(
        f"snapshot {snapshot_date}: tcgplayer rows={sum(map(len, groups.values()))}, "
        f"cardmarket cards={len(cardmarket)}/{len(card_ids)}, fx={rate}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    args = parser.parse_args()
    try:
        if date.fromisoformat(args.date).isoformat() != args.date:
            raise ValueError("expected YYYY-MM-DD")
    except ValueError:
        print("--date must be a valid date in YYYY-MM-DD format", file=sys.stderr)
        return 1

    folder = config.SNAPSHOT_DIR / args.date
    reference = config.DATA_DIR / "tcgdex.json"
    marker = folder / "_SUCCESS"
    try:
        if marker.is_file():
            print(f"snapshot {args.date} already complete, skipping")
            return 0
        if not reference.is_file():
            raise FileNotFoundError("data/tcgdex.json is missing; run collect.py first")
        folder.mkdir(parents=True, exist_ok=True)
        # Concurrent writers for the same date share this lock. Readers use the marker.
        fd = os.open(folder, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            if marker.is_file():
                print(f"snapshot {args.date} already complete, skipping")
            else:
                write_snapshot(folder, args.date, reference)
        finally:
            os.close(fd)
    except (OSError, HTTPException, KeyError, TypeError, ValueError) as exc:
        print(f"snapshot {args.date}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
