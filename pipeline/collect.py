"""Collect raw data: TCGdex cards (5 sets) + PokeAPI species + tcgcsv monthly price history
(+ one fixed week of tcgcsv daily archives).

Usage (from the repo root):  python pipeline/collect.py
Writes to data/ (git-ignored). API responses are cached in data/_cache, so reruns resume.
Each tcgcsv archive is downloaded once: its prices for our groups are kept in data/_cache/archive/.
"""
import json, time, os, io, sys, urllib.request, datetime, tempfile
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
                d = json.loads(b)
                with open(key + ".tmp", "w") as f:  # write then rename, as for the archive cache
                    json.dump(d, f)
                os.replace(key + ".tmp", key)
                return d
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


def archive_day(ds):
    """{"pid|subtype": market} for our groups from the tcgcsv archive of day ds, or None if missing."""
    cached = f"{CACHE}/archive/{ds}.json"  # one file per archive day, so each archive is downloaded once
    if os.path.exists(cached):
        print("archive", ds, "cached", flush=True)
        return json.load(open(cached))
    b = get(f"https://tcgcsv.com/archive/tcgplayer/prices-{ds}.ppmd.7z", raw=True)
    print("archive", ds, "ok" if b else "missing", flush=True)
    time.sleep(1)
    if not b:
        return None
    day = {}
    # Extract to a local temp folder, not data/: writing the whole archive to a bind-mounted
    # data/ folder (Docker on Windows) is about 15x slower.
    with tempfile.TemporaryDirectory() as tmp:
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
    return day


hist = {}  # "pid|subtype" -> {date: market}
d = datetime.date(2024, 2, 8)
today = datetime.date.today()
while d <= today:
    ds = d.isoformat()
    for k, v in (archive_day(ds) or {}).items():
        hist.setdefault(k, {})[ds] = v
    d = (d.replace(day=1) + datetime.timedelta(days=32)).replace(day=8)
json.dump(hist, open(f"{OUT}/history.json", "w"))

# 4) tcgcsv daily archives for one fixed week: a one-time backfill so the 7-day change works
#    before daily snapshots have built up (issue #12). Daily snapshots continue from there.
DAILY_BACKFILL = (datetime.date(2026, 11, 20), datetime.date(2026, 11, 27))
daily = {}  # same shape as history.json
d = DAILY_BACKFILL[0]
while d <= DAILY_BACKFILL[1]:
    ds = d.isoformat()
    for k, v in (archive_day(ds) or {}).items():
        daily.setdefault(k, {})[ds] = v
    d += datetime.timedelta(days=1)
json.dump(daily, open(f"{OUT}/history_daily.json", "w"))
print("history_daily", len(daily), flush=True)
print("DONE", flush=True)
