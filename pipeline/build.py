"""Transform the raw pulls in data/ into the website in site/ (one HTML file + card images).

Usage (from the repo root, after pipeline/collect.py):  python pipeline/build.py
"""
import json, os, sys, base64, statistics as st, urllib.request, time, datetime
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

tc = json.load(open(f"{D}/tcgdex.json"))
mons = {int(k): v for k, v in json.load(open(f"{D}/pokeapi.json")).items()}
hist = json.load(open(f"{D}/history.json"))
TODAY = datetime.date.today().isoformat()
dates = sorted({d for h in hist.values() for d in h})


def norm(s):
    return s.lower().replace(" ", "-")


hist_n = {}
for k, v in hist.items():
    pid, sub = k.split("|", 1)
    hist_n[(int(pid), norm(sub))] = v

fx_path = f"{D}/fx.json"
if not os.path.exists(fx_path):
    fx = json.load(urllib.request.urlopen(urllib.request.Request(
        "https://api.frankfurter.dev/v1/latest?from=EUR&to=USD", headers=UA), timeout=30))
    json.dump(fx, open(fx_path, "w"))
fx = json.load(open(fx_path))
EURUSD = fx["rates"]["USD"]
print("EURUSD", EURUSD, fx["date"])

cards = []
for c in tc["cards"]:
    tp = (c.get("pricing") or {}).get("tcgplayer") or {}
    vars_ = {k: v for k, v in tp.items() if isinstance(v, dict) and v.get("marketPrice")}
    if not vars_:
        continue
    # primary printing: the standard (non reverse-holo) version, which matches Cardmarket's base "trend"
    vk = next((k for k in ("holofoil", "normal") if k in vars_), next(iter(vars_)))
    vv = vars_[vk]
    series = dict(hist_n.get((vv["productId"], norm(vk)), {}))
    series[TODAY] = vv["marketPrice"]
    cm = (c.get("pricing") or {}).get("cardmarket") or {}
    eur = cm.get("trend")
    eu_usd = round(eur * EURUSD, 2) if eur else None
    # positive = Europe cheaper; only flag clear gaps on cards worth >= $1
    gap = None
    if eu_usd and vv["marketPrice"] >= 1 and eu_usd >= 1:
        g = 1 - eu_usd / vv["marketPrice"]
        gap = round(g, 3) if abs(g) >= 0.10 else 0
    dex = (c.get("dexId") or [None])[0]
    cards.append({
        "id": c["id"], "name": c["name"], "set": c["_set"], "num": c.get("localId"),
        "rarity": c.get("rarity") or "Unknown",
        "hp": c.get("hp"), "artist": c.get("illustrator"), "cat": c.get("category"), "dex": dex,
        "variant": vk, "usd": vv["marketPrice"], "eur": eur, "euUsd": eu_usd, "gap": gap,
        "vars": [{"k": k, "usd": v["marketPrice"]} for k, v in vars_.items()],
        "img": c.get("image"), "hist": {d: series[d] for d in sorted(series)},
    })
print("cards with price", len(cards), "of", len(tc["cards"]))
cov = sum(1 for c in cards if len(c["hist"]) > 1)
print("cards with history", cov)


def at(c, d):
    """price on or just after date d (first snapshot >= d)"""
    for k in c["hist"]:
        if k >= d:
            return c["hist"][k]
    return None


def back(months):
    t = datetime.date.today()
    y, m = t.year, t.month - months
    while m <= 0:
        y, m = y - 1, m + 12
    return datetime.date(y, m, 1).isoformat()


for c in cards:
    for mo in (3, 12):
        old = at(c, back(mo))
        first = next(iter(c["hist"]))
        c[f"chg{mo}"] = round(c["usd"] / old - 1, 4) if old and first <= back(mo)[:7] + "-31" and old > 0 else None

# Pokemon aggregates
by = {}
for c in cards:
    if c["dex"] in mons:
        by.setdefault(c["dex"], []).append(c)
poke = []
for dex, cs in by.items():
    m = mons[dex]
    chg = [c["chg12"] for c in cs if c["chg12"] is not None and c["usd"] >= 1]
    top = max(cs, key=lambda c: c["usd"])
    poke.append({
        "dex": dex, "name": m["name"], "types": m["types"], "gen": m["generation"].replace("generation-", "").upper(),
        "legendary": m["legendary"] or m["mythical"], "bst": sum(m["stats"].values()), "stats": m["stats"],
        "n": len(cs), "top": top["usd"], "topId": top["id"], "median": round(st.median([c["usd"] for c in cs]), 2),
        "chg12": round(st.median(chg), 4) if chg else None,
    })
print("pokemon", len(poke))

# Sets: value index over time (sum of market price of cards that have a price that month)
sets = []
for s in tc["sets"]:
    cs = [c for c in cards if c["set"] == s["id"]]
    series = {}
    for d in dates + [TODAY]:
        vals = [c["hist"][d] for c in cs if d in c["hist"]]
        if len(vals) >= 0.6 * len(cs):
            series[d] = round(sum(vals), 2)
    chase = sorted(cs, key=lambda c: -c["usd"])[:6]
    sets.append({**s, "n": len(cs), "value": round(sum(c["usd"] for c in cs), 2),
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

data = {"built": TODAY, "fx": {"rate": EURUSD, "date": fx["date"]}, "dates": dates + [TODAY], "sets": sets, "cards": cards, "pokemon": poke,
        "featured": featured_mons, "up": [c["id"] for c in up], "down": [c["id"] for c in down]}
js = "window.DATA=" + json.dumps(data, separators=(",", ":")) + ";"
tpl = open(f"{S}/web/template.html", encoding="utf-8").read()
html = tpl.replace("/*DATA*/", js.replace("</", "<\\/"))
open(f"{OUT}/index.html", "w", encoding="utf-8").write(html)
print("html KB", len(html) // 1024)
