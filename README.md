# CardPulse

**A price tracker for Pokémon Trading Card Game (TCG) players and collectors.**

CardPulse answers the questions players ask before they buy, sell or trade a card:
*What is my card worth? Is it going up or down? Is it cheaper in the US or in Europe?
Which version of my favorite Pokémon can I afford?*

It combines three free public APIs: card data, US and European market prices, and
Pokémon species data. The result is a single website with price history going back to February 2024.

> Status: working prototype. It covers 5 sets (913 cards, 403 Pokémon) as a proof of
> concept. See [Roadmap](#roadmap) for what comes next.

---

## Contents

- [Who it is for](#who-it-is-for)
- [Features and the player needs they solve](#features-and-the-player-needs-they-solve)
- [Quick start](#quick-start)
- [Data sources](#data-sources)
- [How the data fits together](#how-the-data-fits-together)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)

---

## Who it is for

| User | What they want |
|---|---|
| **Collectors** | Track what their cards are worth, find the right moment to buy a chase card, and know what it costs to complete a set. |
| **Casual fans** | Find an affordable card of their favorite Pokémon and see why two cards of the same Pokémon have very different prices. |
| **Traders and buyers** | Spot cards that are rising or falling, and compare US and European prices before ordering. |

A quick note on the domain: one Pokémon (for example Charizard) is printed on many
different cards. Each card has a set, a rarity, artwork and a printing (normal, holofoil,
reverse holofoil), and each card is sold on several marketplaces. The same Pokémon with the
same in-game stats can sell for **$8 or $288** depending on the card. CardPulse is built
around that layering: **Pokémon → card → printing → market price over time**.

---

## Features and the player needs they solve

### 1. Global card search
A search box on every page. Search by card name, set, rarity or card number, alone or
combined (for example `151 charizard` or `umbreon vmax`). Results show a thumbnail and the
current price; arrow keys and Enter work.

**Player need:** *"I have this card in my hand. What is it worth?"* This is the most common
question, and it should take one search to answer.

### 2. Card detail page
Every card has its own page with a shareable link:
- large card image, set, card number, rarity, artist and HP
- current TCGplayer market price, plus the price of each printing when there are several
- 3-month and 12-month price change, and when tracking started
- **price history chart** (6 months, 1 year or all) from monthly snapshots since February 2024
- **US vs Europe comparison** (see feature 3)
- links to the other cards of the same Pokémon

**Player need:** *"Should I buy or sell this card now?"* Price history shows whether today's
price is a peak, a dip or normal, and the link can be shared with a trading partner.

### 3. US vs Europe price comparison
Cards carry a tag such as **"EU 23% cheaper"** or **"US 18% cheaper"**. The card page puts
the TCGplayer (US, USD) price next to the Cardmarket (Europe, EUR) price and says which market is cheaper.
- Euros are converted to dollars at the European Central Bank reference rate of the build day.
- Only the same printing is compared (the standard or holofoil version against Cardmarket's base trend price).
- Gaps under 10% count as "about the same price". Gaps over 50% are not tagged, because they usually mean the
  two markets list different card conditions. The card page asks the user to compare condition instead.
- Shipping, fees and import costs are not included, and the page says so.

**Player need:** *"Where should I buy?"* Many players can order from either market, and the
difference on a single card can be large.

### 4. Pokémon page
Pick a Pokémon (searchable list, sorted by its most valuable card) to see:
- sprite, generation, types and in-game base stats (from PokéAPI)
- number of cards, cheapest card, most valuable card, and the 12-month change of a typical card
- **price range strip**: all of its cards placed on one price axis, from cheapest to most valuable
- every card as a grid, sorted by most valuable or cheapest, with US/EU tags

**Player need:** *"I love Umbreon. Which Umbreon card fits my budget?"* Fans usually collect by
Pokémon, not by set. This page shows the entry price and the top end side by side.

### 5. Movers
The biggest gainers and fallers, each with a sparkline:
- time window: 12 months or 3 months
- filters: set, rarity, minimum current price ($1, $5, $20, $100), and list length (12, 25, 50)
- every row opens the card page

**Player need:** *"What is hot right now, and did anything I own just jump?"* Collectors also
use fallers to time purchases. In the current data, newly released sets drop sharply in the
months after release while 1999 Base Set cards keep rising.

### 6. Market Map
A quadrant chart where each sprite is a Pokémon:
- **x-axis:** 12-month price change of its typical card
- **y-axis:** its most valuable card today (log scale)
- four zones: **Hot** (pricey and climbing), **Cooling off** (pricey but falling: waiting may pay),
  **Rising stars** (cheap but climbing: early-buy candidates), **Quiet** (cheap and stable: easy to collect)
- filters: set, generation, type, and Top 50 / Top 100 / All. When a set is selected, the map is
  recalculated from that set's cards only.
- highlight a Pokémon by name, zoom by dragging or scrolling, click a sprite to open its Pokémon page

**Player need:** *"Buy now or wait?"* The map gives a one-screen overview of the market, and the
filters keep it readable.

### 7. Sets
For each set: release date, the **total cost of buying every single card in the set** today,
how that total changed month by month, and the set's six most valuable cards.

**Player need:** *"What will it cost to complete this set, and which cards make it expensive?"*
It also shows which sets as a whole are gaining value.

---

## Quick start

### View the site
The built site is committed in `site/`. Open `site/index.html` in a browser. An internet
connection is needed for the chart library and fonts.

### Rebuild with fresh data
Requires Python 3.12.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python pipeline/collect.py   # pull raw data into data/ (about 15–30 min the first time; cached afterwards)
python pipeline/build.py     # transform data/ into site/index.html + site/img/
```

`collect.py` caches every API response in `data/_cache/`, so an interrupted run resumes
where it stopped. `data/` is git-ignored. Each person builds their own copy.

---

## Data sources

All sources are free and need no API key.

| Source | What we use | Notes |
|---|---|---|
| [TCGdex](https://tcgdex.dev) | Sets, cards (name, rarity, HP, artist, Pokédex number, images) and current prices from **Cardmarket (EUR)** and **TCGplayer (USD)** | Prices are embedded in each card response. Updated daily. |
| [tcgcsv](https://tcgcsv.com) | Daily archive of **TCGplayer** prices since 2024-02-08, used for price history | Requests must send a custom `User-Agent`. Download each archive once (one-time backfill), not repeatedly. |
| [PokéAPI](https://pokeapi.co) | Species: types, generation, base stats, legendary flag, sprites | Fair-use policy. Responses are cached locally. |
| [Frankfurter](https://frankfurter.dev) | EUR→USD reference rate (European Central Bank) | One call per build |

We looked at the Pokémon TCG API (pokemontcg.io). It is now part of Scrydex, its price history
is paid, and its free prices were stale when we checked, so we use TCGdex instead.

---

## How the data fits together

```
TCGdex card ──dexId──────────────────────► PokéAPI species (types, generation, stats, sprite)
     │
     └─ pricing.tcgplayer.productId + printing ─► tcgcsv daily price archive (history)
     └─ pricing.cardmarket.trend × ECB rate ────► Europe price in USD (US vs EU comparison)
```

- **Card ↔ Pokémon:** joined on the National Pokédex number (`dexId`), not on names, because card
  names include suffixes such as "ex" or "VMAX". Trainer and Energy cards have no Pokémon.
- **Card ↔ price history:** TCGdex exposes the TCGplayer `productId`. Together with the printing
  (`Normal`, `Holofoil`, …) it is the key into tcgcsv. All 913 cards matched.
- **Main price:** the TCGplayer market price of the standard printing (holofoil if the card has one,
  otherwise normal). This keeps the price comparable with Cardmarket and the history consistent.
- **Price change:** current price divided by the price at the first snapshot on or after the
  start of the window, minus 1. Pokémon-level change is the median over its cards worth at least $1.

---

## Project structure

```
cardpulse/
├── pipeline/
│   ├── collect.py      # extract: TCGdex, PokéAPI, tcgcsv → data/
│   └── build.py        # transform + load: data/ → site/index.html (data inlined) and site/img/
├── web/
│   └── template.html   # the website: layout, styles and all front-end logic (ECharts)
├── site/               # built output, committed so anyone can open it right away
│   ├── index.html
│   └── img/            # card images for the most valuable cards
├── data/               # raw API data and caches (git-ignored)
├── docs/specs/         # development specs: shared contracts (00) and one spec per module
├── .github/            # pull request and issue templates
├── CONTRIBUTING.md     # team workflow: branches, pull requests, reviews
├── requirements.txt
└── README.md
```

---

## Known limitations

- **Coverage:** 5 sets for now: Base Set (1999), Evolving Skies (2021), 151 (2023),
  Prismatic Evolutions (2025) and Mega Evolution (2025).
- **History granularity:** monthly snapshots (the 8th of each month) plus today. Daily history is
  available from tcgcsv and planned.
- **Images:** the 480 most valuable cards have images. Other cards show a placeholder.
- **Prices are estimates:** TCGplayer "market price" and Cardmarket "trend" summarize recent
  sales and listings across conditions. Vintage cards are most affected by condition differences.
- **Static build:** the site is regenerated by running the pipeline. There is no scheduler or
  database yet (see Roadmap).

---

## Roadmap

Planned, roughly in order:
1. Store data in a database (SQLite) instead of JSON files.
2. Schedule the pipeline as a daily Airflow DAG, and switch history from monthly to daily snapshots.
3. Expand to more sets.
4. Package everything in Docker so the project runs the same way on any machine.

Feature ideas from the team go in GitHub Issues (see [CONTRIBUTING.md](CONTRIBUTING.md)).

---

## Contributing

We work in feature branches and merge through reviewed pull requests. Read
[CONTRIBUTING.md](CONTRIBUTING.md) before your first change.

---

## Disclaimer

Unofficial fan project. Not affiliated with Nintendo, The Pokémon Company, TCGplayer or
Cardmarket. Card images and names belong to their respective owners. Prices are market
estimates for information only, not financial advice.
