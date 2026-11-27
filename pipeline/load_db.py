"""Load CardPulse's raw JSON and completed daily snapshots into SQLite.

From the repository root:
    python pipeline/load_db.py [--rebuild] [--db PATH]
"""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

import config


PRICE_UPSERT = """
INSERT INTO price_observations
    (card_id, printing, market, price_date, price, currency, source, loaded_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (card_id, printing, market, price_date) DO UPDATE SET
    price = excluded.price,
    currency = excluded.currency,
    source = excluded.source,
    loaded_at = excluded.loaded_at
WHERE (CASE excluded.source
           WHEN 'tcgcsv_daily' THEN 3
           WHEN 'tcgcsv_archive' THEN 2
           ELSE 1 END)
   >= (CASE price_observations.source
           WHEN 'tcgcsv_daily' THEN 3
           WHEN 'tcgcsv_archive' THEN 2
           ELSE 1 END)
"""


def read_json(path: Path):
    """Read a UTF-8 JSON input, preserving errors for the CLI to report."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def positive_price(value):
    """Return a positive finite price, or None for missing/invalid API values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if not (0 < amount < float("inf")):
        return None
    return amount


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def price_date(value):
    """Convert an ISO timestamp to its UTC date (sources already use UTC)."""
    return str(value)[:10] if value else None


def load_sets(conn, tcgdex):
    with conn:
        for item in tcgdex["sets"]:
            sid = item["id"]
            if sid not in config.SETS:
                continue
            conn.execute("""
                INSERT INTO sets
                    (set_id, name, series, release_date, logo_url, tcgplayer_group_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (set_id) DO UPDATE SET
                    name = excluded.name,
                    series = excluded.series,
                    release_date = excluded.release_date,
                    logo_url = excluded.logo_url,
                    tcgplayer_group_id = excluded.tcgplayer_group_id
            """, (sid, item["name"], item.get("serie"),
                  item.get("releaseDate"), item.get("logo"), config.SETS[sid]))


def load_pokemon(conn, pokeapi):
    with conn:
        for item in pokeapi.values():
            stats = item["stats"]
            keys = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")
            values = [int(stats[key]) for key in keys]
            types = item["types"]
            generation = item["generation"].removeprefix("generation-").upper()
            conn.execute("""
                INSERT INTO pokemon
                    (dex_id, name, generation, type_primary, type_secondary,
                     hp, attack, defense, sp_attack, sp_defense, speed,
                     base_stat_total, is_legendary, is_mythical, capture_rate, sprite_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (dex_id) DO UPDATE SET
                    name = excluded.name,
                    generation = excluded.generation,
                    type_primary = excluded.type_primary,
                    type_secondary = excluded.type_secondary,
                    hp = excluded.hp,
                    attack = excluded.attack,
                    defense = excluded.defense,
                    sp_attack = excluded.sp_attack,
                    sp_defense = excluded.sp_defense,
                    speed = excluded.speed,
                    base_stat_total = excluded.base_stat_total,
                    is_legendary = excluded.is_legendary,
                    is_mythical = excluded.is_mythical,
                    capture_rate = excluded.capture_rate,
                    sprite_url = excluded.sprite_url
            """, (int(item["id"]), item["name"], generation, types[0],
                  types[1] if len(types) > 1 else None, *values, sum(values),
                  int(bool(item["legendary"])), int(bool(item["mythical"])),
                  item.get("capture_rate"), item.get("sprite")))


def card_printings(card):
    """Only TCGplayer printing objects with a usable product ID are joinable."""
    tp = ((card.get("pricing") or {}).get("tcgplayer") or {})
    return [(config.norm_printing(key), int(value["productId"]))
            for key, value in tp.items()
            if isinstance(value, dict) and value.get("productId")]


def primary_printing(printings):
    names = [printing for printing, _ in printings]
    return next((name for name in config.PRIMARY_PRINTING_ORDER if name in names),
                names[0] if names else None)


def load_cards(conn, tcgdex):
    valid_dex = {row[0] for row in conn.execute("SELECT dex_id FROM pokemon")}
    cards = [c for c in tcgdex["cards"] if c.get("_set") in config.SETS]
    with conn:
        for card in cards:
            dex_ids = card.get("dexId") or []
            dex_id = int(dex_ids[0]) if dex_ids else None
            if dex_id not in valid_dex:
                dex_id = None
            hp = card.get("hp")
            conn.execute("""
                INSERT INTO cards
                    (card_id, set_id, local_id, name, category, rarity, hp,
                     illustrator, stage, dex_id, image_url, primary_printing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (card_id) DO UPDATE SET
                    set_id = excluded.set_id,
                    local_id = excluded.local_id,
                    name = excluded.name,
                    category = excluded.category,
                    rarity = excluded.rarity,
                    hp = excluded.hp,
                    illustrator = excluded.illustrator,
                    stage = excluded.stage,
                    dex_id = excluded.dex_id,
                    image_url = excluded.image_url,
                    primary_printing = excluded.primary_printing
            """, (card["id"], card["_set"], str(card["localId"]), card["name"],
                  card["category"], card.get("rarity"),
                  int(hp) if hp not in (None, "") else None,
                  card.get("illustrator"), card.get("stage"), dex_id,
                  card.get("image"), primary_printing(card_printings(card))))
    return cards


def load_printings(conn, cards):
    """Build a product/printing index for archive and snapshot joins."""
    product_index = {}
    by_card = {}
    with conn:
        for card in cards:
            cid = card["id"]
            by_card[cid] = set()
            for printing, pid in card_printings(card):
                conn.execute("""
                    INSERT INTO card_printings
                        (card_id, printing, tcgplayer_product_id)
                    VALUES (?, ?, ?)
                    ON CONFLICT (card_id, printing) DO UPDATE SET
                        tcgplayer_product_id = excluded.tcgplayer_product_id
                """, (cid, printing, pid))
                product_index.setdefault((pid, printing), []).append((cid, printing))
                by_card[cid].add(printing)
    return product_index, by_card


def load_prices(conn, cards, product_index, by_card):
    timestamp = utc_now()

    def put(card_id, printing, market, date, amount, source):
        price = positive_price(amount)
        if price is None or not date:
            return
        conn.execute(PRICE_UPSERT, (card_id, printing, market, date, price,
                                    "USD" if market == "tcgplayer" else "EUR",
                                    source, timestamp))

    def from_tcgcsv(product_id, subtype, date, amount, source):
        try:
            key = (int(product_id), config.norm_printing(subtype))
        except (TypeError, ValueError, AttributeError):
            return
        for cid, printing in product_index.get(key, ()):
            put(cid, printing, "tcgplayer", date, amount, source)

    def from_cardmarket(cid, cm, date):
        if cid not in by_card or not isinstance(cm, dict):
            return
        printing = primary_by_card.get(cid)
        if printing:
            put(cid, printing, "cardmarket", date, cm.get("trend"), "tcgdex")
        if "reverse-holofoil" in by_card[cid]:
            put(cid, "reverse-holofoil", "cardmarket", date,
                cm.get("trend-holo"), "tcgdex")

    primary_by_card = {
        row[0]: row[1]
        for row in conn.execute("SELECT card_id, primary_printing FROM cards")
    }

    with conn:
        history_path = config.DATA_DIR / "history.json"
        if history_path.exists():
            for key, dates in read_json(history_path).items():
                if "|" not in key:
                    continue
                pid, subtype = key.split("|", 1)
                for day, amount in dates.items():
                    from_tcgcsv(pid, subtype, day, amount, "tcgcsv_archive")

        for card in cards:
            cid = card["id"]
            pricing = card.get("pricing") or {}
            tp = pricing.get("tcgplayer") or {}
            day = price_date(tp.get("updated"))
            for key, value in tp.items():
                if not isinstance(value, dict) or not value.get("productId"):
                    continue
                printing = config.norm_printing(key)
                if printing in by_card[cid]:
                    put(cid, printing, "tcgplayer", day,
                        value.get("marketPrice"), "tcgdex")

            cm = pricing.get("cardmarket") or {}
            from_cardmarket(cid, cm, price_date(cm.get("updated")))

        if config.SNAPSHOT_DIR.exists():
            for folder in sorted(config.SNAPSHOT_DIR.iterdir()):
                if not folder.is_dir() or not (folder / "_SUCCESS").exists():
                    continue
                day = folder.name
                tp_file = folder / "tcgplayer.json"
                if tp_file.exists():
                    for rows in read_json(tp_file).get("groups", {}).values():
                        for row in rows:
                            from_tcgcsv(row.get("productId"), row.get("subTypeName"),
                                        day, row.get("marketPrice"), "tcgcsv_daily")
                cm_file = folder / "cardmarket.json"
                if cm_file.exists():
                    for cid, cm in read_json(cm_file).get("cards", {}).items():
                        from_cardmarket(cid, cm, day)


def load_fx(conn):
    def put(fx):
        if not fx:
            return
        rate = positive_price((fx.get("rates") or {}).get("USD"))
        if rate is None:
            return
        conn.execute("""
            INSERT INTO fx_rates (rate_date, base, quote, rate)
            VALUES (?, ?, 'USD', ?)
            ON CONFLICT (rate_date) DO UPDATE SET
                base = excluded.base, quote = excluded.quote, rate = excluded.rate
        """, (fx["date"], fx.get("base", "EUR"), rate))

    with conn:
        path = config.DATA_DIR / "fx.json"
        if path.exists():
            put(read_json(path))
        if config.SNAPSHOT_DIR.exists():
            for folder in sorted(config.SNAPSHOT_DIR.iterdir()):
                if folder.is_dir() and (folder / "_SUCCESS").exists():
                    fx_path = folder / "fx.json"
                    if fx_path.exists():
                        put(read_json(fx_path))


def load_database(db_path, rebuild=False):
    # Validate required inputs before touching an existing database.
    required = (config.DATA_DIR / "tcgdex.json", config.DATA_DIR / "pokeapi.json")
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing required data file(s): " + ", ".join(missing) +
            ". Run `python pipeline/collect.py` from the repository root first."
        )
    tcgdex = read_json(required[0])
    pokeapi = read_json(required[1])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if rebuild:
        db_path.unlink(missing_ok=True)

    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript((config.SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        load_sets(conn, tcgdex)
        load_pokemon(conn, pokeapi)
        cards = load_cards(conn, tcgdex)
        product_index, by_card = load_printings(conn, cards)
        load_prices(conn, cards, product_index, by_card)
        load_fx(conn)
        conn.executescript((config.SQL_DIR / "views.sql").read_text(encoding="utf-8"))
        counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("sets", "pokemon", "cards", "card_printings",
                                "price_observations", "fx_rates")}
        counts["as_of_date"] = conn.execute("SELECT as_of_date FROM v_as_of").fetchone()[0]
        return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="Delete and rebuild the database")
    parser.add_argument("--db", type=Path, default=config.DB_PATH, help="SQLite output path")
    args = parser.parse_args()
    try:
        summary = load_database(args.db, rebuild=args.rebuild)
        print(json.dumps(summary))  # The final stdout line is machine-readable.
        return 0
    except Exception as exc:
        print(f"load_db.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
