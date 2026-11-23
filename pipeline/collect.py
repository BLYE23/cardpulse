"""Collect raw data: TCGdex cards (5 sets) + PokeAPI species + tcgcsv monthly price history.

Usage (from the repo root):  python pipeline/collect.py
Writes to data/ (git-ignored). API responses are cached in data/_cache, so reruns resume.
Each tcgcsv archive is downloaded once: its prices for our groups are kept in data/_cache/archive/.
"""
import json, time, os, io, sys, urllib.request, datetime, shutil
from pathlib import Path
import py7zr

ROOT = Path(__file__).resolve().parents[1]
OUT = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "data")
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "CardPulse/0.1"}
SETS = ["base1", "swsh7", "sv03.5", "sv08.5", "me01"]


CACHE = f"{OUT}/_cache"
os.makedirs(CACHE, exist_ok=True)


def get(url, raw=False):
    key = None
    if not raw:
        key = os.path.join(CACHE, url.split("://", 1)[1].replace("/", "_") + ".json")
        if os.path.exists(key):
            return json.load(open(key))
    for i in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read()
                if raw: return b
                d = json.loads(b); json.dump(d, open(key, "w")); return d
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            print("retry", url, e, flush=True); time.sleep(min(60, 3 * 2 ** i))
        except Exception as e:
            print("retry", url, e, flush=True); time.sleep(min(60, 3 * 2 ** i))
    return None


# 1) TCGdex
cards, sets = [], []
for sid in SETS:
    s = get(f"https://api.tcgdex.net/v2/en/sets/{sid}")
    sets.append({"id": sid, "name": s["name"], "releaseDate": s.get("releaseDate"),
                 "serie": s["serie"]["name"], "logo": s.get("logo")})
    for c in s["cards"]:
        d = get(f"https://api.tcgdex.net/v2/en/cards/{c['id']}")
        if d: d["_set"] = sid; cards.append(d)
        time.sleep(0.03)
    print("set", sid, len(s["cards"]), flush=True)
json.dump({"sets": sets, "cards": cards}, open(f"{OUT}/tcgdex.json", "w"))

# 2) PokeAPI for every dexId on these cards
dex = sorted({i for c in cards for i in (c.get("dexId") or [])})
mons = {}
for i in dex:
    p = get(f"https://pokeapi.co/api/v2/pokemon/{i}")
    sp = get(f"https://pokeapi.co/api/v2/pokemon-species/{i}")
    if not p or not sp: continue
    mons[i] = {
        "id": i, "name": p["name"],
        "stats": {s["stat"]["name"]: s["base_stat"] for s in p["stats"]},
        "types": [t["type"]["name"] for t in p["types"]],
        "sprite": p["sprites"]["other"]["official-artwork"]["front_default"] or p["sprites"]["front_default"],
        "generation": sp["generation"]["name"], "legendary": sp["is_legendary"], "mythical": sp["is_mythical"],
        "capture_rate": sp["capture_rate"],
    }
    time.sleep(0.05)
print("pokeapi", len(mons), flush=True)
json.dump(mons, open(f"{OUT}/pokeapi.json", "w"))

# 3) tcgcsv monthly snapshots (day 8 of each month, archive starts 2024-02-08)
pids = set()
for c in cards:
    for k, v in ((c.get("pricing") or {}).get("tcgplayer") or {}).items():
        if isinstance(v, dict) and v.get("productId"): pids.add(v["productId"])
hist = {}  # "pid|subtype" -> {date: market}
d = datetime.date(2024, 2, 8)
today = datetime.date.today()
while d <= today:
    ds = d.isoformat()
    cached = f"{CACHE}/archive/{ds}.json"  # {"pid|subtype": market} for our groups, one file per archive day
    if os.path.exists(cached):
        for k, v in json.load(open(cached)).items():
            hist.setdefault(k, {})[ds] = v
        print("archive", ds, "cached", len(hist), flush=True)
        d = (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=8)
        continue
    b = get(f"https://tcgcsv.com/archive/tcgplayer/prices-{ds}.ppmd.7z", raw=True)
    if b:
        day = {}
        tmp = f"{OUT}/_arc"
        import shutil; shutil.rmtree(tmp, ignore_errors=True)
        with py7zr.SevenZipFile(io.BytesIO(b)) as z:
            z.extractall(path=tmp)
        base = f"{tmp}/{ds}/3"
        groups = ["604", "2848", "23237", "23821", "24380"]  # TCGplayer groups of the 5 demo sets
        paths = [f"{base}/{g}/prices" for g in groups]
        for pth in paths:
            if not os.path.isfile(pth): continue
            for r in json.load(open(pth)).get("results", []):
                if r.get("marketPrice") is not None:
                    day[f"{r['productId']}|{r['subTypeName']}"] = r["marketPrice"]
        os.makedirs(os.path.dirname(cached), exist_ok=True)
        with open(cached + ".tmp", "w") as f:  # write then rename, so an interrupted run never leaves a partial file
            json.dump(day, f)
        os.replace(cached + ".tmp", cached)
        for k, v in day.items():
            hist.setdefault(k, {})[ds] = v
    print("archive", ds, "ok" if b else "missing", len(hist), flush=True)
    time.sleep(1)
    d = (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=8)
json.dump(hist, open(f"{OUT}/history.json", "w"))
shutil.rmtree(f"{OUT}/_arc", ignore_errors=True)  # extracted archives are large and no longer needed
print("DONE", flush=True)
