"""Build the website in site/ (one HTML file + card images) from the database.

Usage (from the repo root, after pipeline/load_db.py):  python pipeline/build.py
Prices and metrics come from the views v_card_metrics, v_card_history and v_set_value_series in
data/cardpulse.db; names and stats from the sets, pokemon and price_observations tables.
"""
import json, os, sys, base64, sqlite3, statistics as st, urllib.request, time, datetime
from pathlib import Path

S = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1])
D, OUT = f"{S}/data", f"{S}/site"
os.makedirs(f"{OUT}/img", exist_ok=True)
UA = {"User-Agent": "CardPulse/0.1"}


def download(url, fn):
    """Save url to fn; write the file only after a successful read so failures leave no empty files."""
    b = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
    with open(fn, "wb") as f:
        f.write(b)

if not os.path.exists(f"{D}/cardpulse.db"):
    sys.exit("data/cardpulse.db not found. Run python pipeline/load_db.py first.")
db = sqlite3.connect(f"{D}/cardpulse.db")
db.row_factory = sqlite3.Row
TODAY = datetime.date.today().isoformat()
AS_OF = db.execute("SELECT as_of_date FROM v_as_of").fetchone()[0]
fx = db.execute("SELECT rate, rate_date FROM fx_rates ORDER BY rate_date DESC LIMIT 1").fetchone()
EURUSD = fx["rate"]
print("as of", AS_OF, "EURUSD", EURUSD, fx["rate_date"])

hist = {}
for r in db.execute("SELECT card_id, price_date, price FROM v_card_history ORDER BY card_id, price_date"):
    hist.setdefault(r["card_id"], {})[r["price_date"]] = r["price"]

# latest TCGplayer price of every printing (the card page lists them when a card has several)
vars_ = {}
for r in db.execute("""
        SELECT card_id, printing, price FROM (
            SELECT card_id, printing, price,
                   ROW_NUMBER() OVER (PARTITION BY card_id, printing ORDER BY price_date DESC) AS rn
            FROM price_observations WHERE market = 'tcgplayer')
        WHERE rn = 1 ORDER BY card_id, printing"""):
    vars_.setdefault(r["card_id"], []).append({"k": r["printing"], "usd": r["price"]})

cards = []
for m in db.execute("SELECT m.* FROM v_card_metrics AS m JOIN cards AS c USING (card_id) ORDER BY c.rowid"):
    cards.append({
        "id": m["card_id"], "name": m["name"], "set": m["set_id"], "num": m["local_id"],
        "rarity": m["rarity"] or "Unknown",
        "hp": m["hp"], "artist": m["illustrator"], "cat": m["category"], "dex": m["dex_id"],
        "variant": m["primary_printing"], "usd": m["usd"], "eur": m["eur"], "euUsd": m["eu_usd"], "gap": m["gap"],
        "chg7": m["chg_7d"], "chg3": m["chg_3m"], "chg12": m["chg_12m"],
        "lo": m["low_12m"], "hi": m["high_12m"], "pos": m["range_pos_12m"], "rl": m["range_label_12m"],
        "vars": vars_.get(m["card_id"], []), "img": m["image_url"], "hist": hist.get(m["card_id"], {}),
    })
print("cards with price", len(cards))
cov = sum(1 for c in cards if len(c["hist"]) > 1)
print("cards with history", cov)

# Pokemon aggregates (medians stay in Python: SQLite has no MEDIAN)
by = {}
for c in cards:
    if c["dex"] is not None:
        by.setdefault(c["dex"], []).append(c)
poke = []
for m in db.execute("SELECT * FROM pokemon ORDER BY dex_id"):
    cs = by.get(m["dex_id"])
    if not cs:
        continue
    chg = [c["chg12"] for c in cs if c["chg12"] is not None and c["usd"] >= 1]
    top = max(cs, key=lambda c: c["usd"])
    poke.append({
        "dex": m["dex_id"], "name": m["name"], "types": [t for t in (m["type_primary"], m["type_secondary"]) if t],
        "gen": m["generation"], "legendary": bool(m["is_legendary"] or m["is_mythical"]), "bst": m["base_stat_total"],
        "stats": {"hp": m["hp"], "attack": m["attack"], "defense": m["defense"], "special-attack": m["sp_attack"],
                  "special-defense": m["sp_defense"], "speed": m["speed"]},
        "n": len(cs), "top": top["usd"], "topId": top["id"], "median": round(st.median([c["usd"] for c in cs]), 2),
        "chg12": round(st.median(chg), 4) if chg else None,
    })
print("pokemon", len(poke))

# Sets: value of every card over time from v_set_value_series (dates with >= 60% of the set priced)
sets = []
for s in db.execute("SELECT * FROM sets ORDER BY rowid"):
    cs = [c for c in cards if c["set"] == s["set_id"]]
    series = {r["price_date"]: r["total_usd"] for r in db.execute(
        "SELECT price_date, total_usd FROM v_set_value_series WHERE set_id = ? ORDER BY price_date", (s["set_id"],))}
    chase = sorted(cs, key=lambda c: -c["usd"])[:6]
    sets.append({"id": s["set_id"], "name": s["name"], "releaseDate": s["release_date"], "serie": s["series"],
                 "logo": s["logo_url"], "n": len(cs), "value": round(sum(c["usd"] for c in cs), 2),
                 "series": series, "chase": [c["id"] for c in chase]})

# Images: sprites (data URI) for every pokemon, card images for a featured subset
for p in poke:
    url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{p['dex']}.png"
    fn = f"{D}/_sprite_{p['dex']}.png"
    if not os.path.exists(fn):
        try:
            download(url, fn)
        except Exception as e:
            print("sprite fail", p["dex"], e); continue
        time.sleep(0.02)
    p["sprite"] = "data:image/png;base64," + base64.b64encode(open(fn, "rb").read()).decode()

featured_mons = [p["dex"] for p in sorted(poke, key=lambda p: -p["top"])[:24]]
movers = [c for c in cards if c["chg12"] is not None and c["usd"] >= 5]
up = sorted(movers, key=lambda c: -c["chg12"])[:12]
down = sorted(movers, key=lambda c: c["chg12"])[:12]
want = {c["id"] for c in cards if c["dex"] in featured_mons} | {c["id"] for c in up + down} \
    | {i for s in sets for i in s["chase"]} | {p["topId"] for p in poke}
want |= {c["id"] for c in sorted(cards, key=lambda c: -c["usd"])[:480]}
want = sorted(want, key=lambda i: -next(c["usd"] for c in cards if c["id"] == i))[:480]
got = 0
for c in cards:
    if c["id"] in want and c["img"]:
        fn = f"{OUT}/img/{c['id']}.webp"
        if not os.path.exists(fn):
            try:
                download(c["img"] + "/low.webp", fn)
                time.sleep(0.05)
            except Exception as e:
                print("img fail", c["id"], e); continue
        c["local"] = f"img/{c['id']}.webp"; got += 1
    c.pop("img", None)
print("card images", got)
keep = {os.path.basename(c["local"]) for c in cards if c.get("local")}
for f in os.listdir(f"{OUT}/img"):
    if f not in keep:
        os.remove(f"{OUT}/img/{f}")  # drop images of cards no longer featured

data = {"built": TODAY, "asOf": AS_OF, "fx": {"rate": EURUSD, "date": fx["rate_date"]}, "sets": sets, "cards": cards,
        "pokemon": poke, "featured": featured_mons, "up": [c["id"] for c in up], "down": [c["id"] for c in down]}
js = "window.DATA=" + json.dumps(data, separators=(",", ":")) + ";"
tpl = open(f"{S}/web/template.html", encoding="utf-8").read()
html = tpl.replace("/*DATA*/", js.replace("</", "<\\/"))
open(f"{OUT}/index.html", "w", encoding="utf-8").write(html)
print("html KB", len(html) // 1024)
