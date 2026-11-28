# CardPulse

**A price tracker for Pokémon Trading Card Game (TCG) players and collectors.**

CardPulse answers the questions players ask before they buy, sell or trade a card:
_What is my card worth? Is it going up or down? Is it cheaper in the US or in Europe?
Which version of my favorite Pokémon can I afford?_

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

| User                   | What they want                                                                                                          |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| **Collectors**         | Track what their cards are worth, find the right moment to buy a chase card, and know what it costs to complete a set.  |
| **Casual fans**        | Find an affordable card of their favorite Pokémon and see why two cards of the same Pokémon have very different prices. |
| **Traders and buyers** | Spot cards that are rising or falling, and compare US and European prices before ordering.                              |

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

**Player need:** _"I have this card in my hand. What is it worth?"_ This is the most common
question, and it should take one search to answer.

### 2. Card detail page

Every card has its own page with a shareable link:

- large card image, set, card number, rarity, artist and HP
- current TCGplayer market price, plus the price of each printing when there are several
- 3-month and 12-month price change, and when tracking started
- **price history chart** (6 months, 1 year or all) from monthly snapshots since February 2024
- **US vs Europe comparison** (see feature 3)
- links to the other cards of the same Pokémon

**Player need:** _"Should I buy or sell this card now?"_ Price history shows whether today's
price is a peak, a dip or normal, and the link can be shared with a trading partner.

### 3. US vs Europe price comparison

Cards carry a tag such as **"EU 23% cheaper"** or **"US 18% cheaper"**. The card page puts
the TCGplayer (US, USD) price next to the Cardmarket (Europe, EUR) price and says which market is cheaper.

- Euros are converted to dollars at the European Central Bank reference rate of the build day.
- Only the same printing is compared (the standard or holofoil version against Cardmarket's base trend price).
- Gaps under 10% count as "about the same price". Gaps over 50% are not tagged, because they usually mean the
  two markets list different card conditions. The card page asks the user to compare condition instead.
- Shipping, fees and import costs are not included, and the page says so.

**Player need:** _"Where should I buy?"_ Many players can order from either market, and the
difference on a single card can be large.

### 4. Pokémon page

Pick a Pokémon (searchable list, sorted by its most valuable card) to see:

- sprite, generation, types and in-game base stats (from PokéAPI)
- number of cards, cheapest card, most valuable card, and the 12-month change of a typical card
- **price range strip**: all of its cards placed on one price axis, from cheapest to most valuable
- every card as a grid, sorted by most valuable or cheapest, with US/EU tags

**Player need:** _"I love Umbreon. Which Umbreon card fits my budget?"_ Fans usually collect by
Pokémon, not by set. This page shows the entry price and the top end side by side.

### 5. Movers

The biggest gainers and fallers, each with a sparkline:

- time window: 12 months or 3 months
- filters: set, rarity, minimum current price ($1, $5, $20, $100), and list length (12, 25, 50)
- every row opens the card page

**Player need:** _"What is hot right now, and did anything I own just jump?"_ Collectors also
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

**Player need:** _"Buy now or wait?"_ The map gives a one-screen overview of the market, and the
filters keep it readable.

### 7. Sets

For each set: release date, the **total cost of buying every single card in the set** today,
how that total changed month by month, and the set's six most valuable cards.

**Player need:** _"What will it cost to complete this set, and which cards make it expensive?"_
It also shows which sets as a whole are gaining value.

---

## Quick start

### View the site

The built site is committed in `site/`. Open `site/index.html` in a browser. An internet
connection is needed for the chart library and fonts.

### Rebuild with fresh data

Requires Python 3.12 on macOS or Linux. **On Windows, use Docker (next section):**
`pipeline/snapshot_prices.py` uses the Unix-only `fcntl` module, so the daily snapshot step
fails in Windows Python.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python pipeline/run_all.py   # all five steps, see "Pipeline steps" below
```

The first run takes about 30 minutes (measured in Docker, see below). Later runs take a few minutes.
`collect.py` caches every API response and every tcgcsv archive in `data/_cache/`, so an
interrupted run resumes where it stopped. `data/` is git-ignored. Each person builds their own copy.

### Run with Docker

Install and start Docker Desktop (and Git). Get the code, then run every command below
from the repository folder:

```bash
git clone https://github.com/BLYE23/cardpulse.git
cd cardpulse
```

#### Build and run the pipeline

```bash
docker compose build pipeline
docker compose run --rm pipeline
```

This runs all five pipeline steps (see [Pipeline steps](#pipeline-steps)).
Measured on a fresh clone with Docker Desktop on Windows:

| Run | Time |
| --- | ---- |
| `docker compose build pipeline` | under 1 minute (plus the one-time download of the Python base image) |
| First `docker compose run --rm pipeline`, empty `data/` | about 31 minutes: 26 min reference data and price history (42 tcgcsv archives, 914 TCGdex cards), then about 3 min for the snapshot, 1.5 min for the checks and 3 min for the website |
| Second run on the same day | about 3 minutes (reference data and today's snapshot are skipped) |
| Run on a new day | about 5–8 minutes (the snapshot adds about 3 minutes) |

Outputs are stored on your computer: raw data and the database `data/cardpulse.db` in
`data/`, the website in `site/`.

#### View the website

```bash
docker compose up -d web
```

Open http://localhost:8000. The service serves the existing contents of `site/`.

#### Start Airflow

```bash
docker compose --profile airflow up -d --build airflow
```

Airflow needs about 2 minutes to start. Then open http://localhost:8080 and log in as
`admin` with the password Airflow generated for your installation:

```bash
docker compose exec airflow cat /opt/airflow/standalone_admin_password.txt
```

Do not commit the password. Each local installation generates its own credentials.

The `cardpulse_daily` DAG is listed **paused**. Switch it on with the toggle left of its
name. Airflow then immediately runs the most recent missed day once (`catchup=False` means
only that one), and afterwards runs every day at 21:30 UTC. To run it now, press ▶
(*Trigger DAG*). A run is done when all 7 tasks (`start_run`, the five steps, `finish_run`)
are green. Airflow uses the same `data/` and `site/` folders as `docker compose run`.

On Linux, run `export AIRFLOW_UID=$(id -u)` before running any of these commands.
Docker Desktop on macOS and Windows does not require this setting. The pipeline and
Airflow containers run as the same user, so both can write `data/` and `site/`.

#### Stop the services

```bash
docker compose --profile airflow down
```

Files in `data/` and `site/` remain on your computer. Airflow metadata and logs
persist in the `airflow-home` Docker volume. Adding `-v` to the shutdown command
deletes that volume.

---

## Data sources

All sources are free and need no API key.

| Source                                 | What we use                                                                                                                         | Notes                                                                                                     |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| [TCGdex](https://tcgdex.dev)           | Sets, cards (name, rarity, HP, artist, Pokédex number, images) and current prices from **Cardmarket (EUR)** and **TCGplayer (USD)** | Prices are embedded in each card response. Updated daily.                                                 |
| [tcgcsv](https://tcgcsv.com)           | Daily archive of **TCGplayer** prices since 2024-02-08, used for price history                                                      | Requests must send a custom `User-Agent`. Download each archive once (one-time backfill), not repeatedly. |
| [PokéAPI](https://pokeapi.co)          | Species: types, generation, base stats, legendary flag, sprites                                                                     | Fair-use policy. Responses are cached locally.                                                            |
| [Frankfurter](https://frankfurter.dev) | EUR→USD reference rate (European Central Bank)                                                                                      | One call per build                                                                                        |

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
│   ├── config.py           # shared constants (sets, thresholds, paths)
│   ├── collect.py          # reference data: TCGdex, PokéAPI, tcgcsv archives → data/
│   ├── snapshot_prices.py  # daily prices → data/snapshots/<date>/
│   ├── load_db.py          # data/ → data/cardpulse.db (SQLite) + views
│   ├── validate.py         # data quality checks from sql/checks.sql
│   ├── build.py            # database views → site/index.html (data inlined) and site/img/
│   ├── steps.py            # the ordered step list shared by both runners
│   ├── run_all.py          # runs all steps without Airflow
│   └── runlog.py           # run and step timing → database
├── sql/                    # schema, views, data quality checks, example queries
├── dags/                   # Airflow DAG cardpulse_daily
├── docker/, Dockerfile, docker-compose.yml   # containers: pipeline, web, Airflow
├── scripts/publish_site.py # publishes site/ to GitHub Pages (gh-pages branch)
├── web/
│   └── template.html       # the website: layout, styles and all front-end logic (ECharts)
├── site/                   # built website: index.html and img/ (card images)
├── data/                   # raw API data, snapshots, database and caches (git-ignored)
├── docs/specs/         # development specs: shared contracts (00) and one spec per module
├── .github/            # pull request and issue templates
├── CONTRIBUTING.md     # team workflow: branches, pull requests, reviews
├── requirements.txt
└── README.md
```

### Database

The SQLite database is generated locally at `data/cardpulse.db` (git-ignored).

- `sets` — Pokémon TCG set metadata and TCGplayer group IDs.
- `pokemon` — Pokédex identifiers, types, and base stats.
- `cards` — individual TCG cards and their primary printings.
- `card_printings` — normalized printings mapped to TCGplayer products.
- `price_observations` — dated US/EU prices by card and printing.
- `fx_rates` — EUR-to-USD exchange rates.
- `pipeline_runs` — pipeline execution status and timing.
- `pipeline_steps` — individual pipeline step results.
- `data_quality_results` — persisted SQL validation results.

---

## Known limitations

- **Coverage:** 5 sets for now: Base Set (1999), Evolving Skies (2021), 151 (2023),
  Prismatic Evolutions (2025) and Mega Evolution (2025).
- **History granularity:** monthly points (the 8th of each month) from February 2024, then
  daily points from 20 November 2026 (a one-time backfill of tcgcsv daily archives, followed by
  the daily snapshots).
- **Images:** the 480 most valuable cards have images. Other cards show a placeholder.
- **Prices are estimates:** TCGplayer "market price" and Cardmarket "trend" summarize recent
  sales and listings across conditions. Vintage cards are most affected by condition differences.
- **Daily updates need a running machine:** Airflow runs inside Docker on a team member's
  computer, so a day is skipped while that computer or Docker is off. The public site is
  published by hand; check the **Prices updated** date in its header.

---

## Roadmap

Done: SQLite database with SQL views and data quality checks, a daily Airflow DAG with daily
price snapshots, and Docker packaging.

Next:

1. Expand to more sets.
2. Run the daily pipeline on an always-on host and publish the site automatically.

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
