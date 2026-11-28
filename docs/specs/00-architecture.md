# 00 — Architecture and Shared Contracts

**Read this file before any module spec.** It defines everything modules share: folders, file
formats, identifiers, commands, and who owns which file. If a module spec and this file disagree,
this file wins. Contracts here are fixed by the project lead. Do not change a contract in a
module PR. Open an issue instead.

> **For AI coding assistants:** you are implementing one module of an existing project. Read this
> file, then your module spec (`01-sql.md`, `02-dag.md` or `03-docker.md`). Create or modify **only**
> the files your spec lists under "Files you own". Use the exact names, columns, commands and exit
> codes given. Do not rename, reformat or "improve" other files. Python 3.12, standard library
> preferred, and add a dependency only if your spec allows it.

---

## 1. What the system does

CardPulse is a daily-updated price pipeline for Pokémon TCG cards with a player-facing website.

```
                 ┌───────────── reference data (run once / weekly) ─────────────┐
 TCGdex API ───► │ collect.py  → data/tcgdex.json, data/pokeapi.json,           │
 PokéAPI    ───► │               data/history.json (tcgcsv monthly backfill),   │
 tcgcsv     ───► │               data/fx.json                                   │
 Frankfurter ──► └──────────────────────────────────────────────────────────────┘
                 ┌───────────── daily prices ────────────────────────────────────┐
 tcgcsv     ───► │ snapshot_prices.py → data/snapshots/YYYY-MM-DD/*.json        │
 TCGdex     ───► │                                                              │
 Frankfurter ──► └──────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                 load_db.py  → data/cardpulse.db  (tables + views, sql/)
                                   │
                 validate.py → data quality results (fails the run on errors)
                                   │
                 build.py    → site/index.html + site/img/   (website)

 Orchestration: dags/cardpulse_daily.py (Airflow) and pipeline/run_all.py (no Airflow)
               both run the same step list from pipeline/steps.py
 Packaging:    Dockerfile + docker-compose.yml run all of the above in containers
```

## 2. Repository layout

| Path | Purpose | Owner |
|---|---|---|
| `pipeline/config.py` | Shared constants and `norm_printing()` | Lead (fixed, read-only for modules) |
| `pipeline/collect.py` | Reference data + monthly price backfill (exists) | Lead (unchanged) |
| `pipeline/build.py` | Builds the website (exists, reads JSON today) | Lead / website task |
| `web/template.html` | Website front end (exists) | Website task |
| `sql/schema.sql` | Table definitions | SQL module |
| `sql/views.sql` | Derived views | SQL module |
| `sql/checks.sql` | Data quality checks | SQL module |
| `sql/queries/*.sql` | Example analysis queries | SQL module |
| `pipeline/load_db.py` | JSON → SQLite loader | SQL module |
| `pipeline/validate.py` | Runs checks, records results | SQL module |
| `pipeline/snapshot_prices.py` | Daily price snapshot | DAG module |
| `pipeline/steps.py` | The ordered list of pipeline steps | DAG module |
| `pipeline/run_all.py` | Runs the steps without Airflow | DAG module |
| `pipeline/runlog.py` | Writes run/step timing to the database | DAG module |
| `dags/cardpulse_daily.py` | Airflow DAG | DAG module |
| `Dockerfile`, `docker/airflow.Dockerfile`, `docker-compose.yml`, `.dockerignore` | Containers | Docker module |
| `README.md` | Docs. Modules edit only the section their spec names | Lead |

`data/` (including the database and snapshots) is git-ignored. `site/` is committed, but only the
lead commits rebuilt `site/` files (see CONTRIBUTING.md).

## 3. Identifiers and normalization (all modules)

| Concept | Rule | Example |
|---|---|---|
| Card id | TCGdex card `id`, unchanged | `sv03.5-199` |
| Set id | TCGdex set `id`, unchanged | `sv03.5` |
| Pokémon id | National Pokédex number (int). A card's Pokémon = **first** element of TCGdex `dexId`. Trainer/Energy cards have none (NULL). | `6` |
| Printing | `config.norm_printing()` of the source label | `holofoil`, `normal`, `reverse-holofoil` |
| Primary printing | First of `config.PRIMARY_PRINTING_ORDER` that the card has in TCGdex `pricing.tcgplayer`; else its first TCGplayer printing | Charizard ex SIR → `holofoil` |
| TCGplayer product | `pricing.tcgplayer.<printing>.productId` from TCGdex; joins to tcgcsv `productId` + normalized `subTypeName` | `517045` + `holofoil` |
| Market | `tcgplayer` (USD) or `cardmarket` (EUR) | |
| Dates | ISO `YYYY-MM-DD` text, UTC | `2026-11-16` |
| Timestamps | ISO 8601 UTC text with `Z` | `2026-11-23T21:05:00Z` |
| Money | REAL, in the market's currency; never pre-converted in tables | |

## 4. File contracts

### 4.1 Existing raw files (produced by `collect.py`, do not change their format)

| File | Shape |
|---|---|
| `data/tcgdex.json` | `{"sets": [{"id","name","releaseDate","serie","logo"}], "cards": [<full TCGdex card object> + "_set": <set id>]}`. Card fields used: `id, localId, name, category, rarity, hp, illustrator, stage, dexId, image, pricing` |
| `data/pokeapi.json` | `{"<dex id as string>": {"id", "name", "stats": {"hp","attack","defense","special-attack","special-defense","speed"}, "types": [..], "sprite", "generation": "generation-i", "legendary", "mythical", "capture_rate"}}` |
| `data/history.json` | `{"<productId>|<subTypeName>": {"YYYY-MM-DD": marketPrice}}`. tcgcsv archive, one point per month (the 8th) since 2024-02-08. Contains products outside our cards; ignore those. |
| `data/history_daily.json` | Same shape as `history.json`: tcgcsv **daily** archives for one fixed week (2026-11-20 to 2026-11-27), a one-time backfill for the 7-day change (issue #12). |
| `data/fx.json` | `{"amount": 1.0, "base": "EUR", "date": "YYYY-MM-DD", "rates": {"USD": <float>}}` (written by `build.py` today) |

TCGdex price blocks inside each card:
- `pricing.tcgplayer = {"unit":"USD","updated":<ts>, "<printing>": {"productId","lowPrice","midPrice","highPrice","marketPrice","directLowPrice"}}`
- `pricing.cardmarket = {"unit":"EUR","updated":<ts>, "trend", "trend-holo", "avg", "low", "avg1","avg7","avg30", ... "-holo" variants}`.
  Cardmarket `trend` is the card's standard printing (= our primary printing). `trend-holo` is the
  reverse holofoil.

### 4.2 New: daily snapshot folder (written by `snapshot_prices.py`, read by `load_db.py`)

One folder per UTC date: `data/snapshots/YYYY-MM-DD/`. A folder is complete only when
`_SUCCESS` exists. Readers must skip folders without it.

| File | Content |
|---|---|
| `tcgplayer.json` | `{"date": "YYYY-MM-DD", "source": "tcgcsv_daily", "groups": {"<groupId>": [<tcgcsv price rows as returned: productId, subTypeName, lowPrice, midPrice, highPrice, marketPrice, directLowPrice>]}}` |
| `cardmarket.json` | `{"date": "YYYY-MM-DD", "source": "tcgdex", "cards": {"<card id>": <the card's pricing.cardmarket object>}}` |
| `fx.json` | Frankfurter response, same shape as `data/fx.json` |
| `_SUCCESS` | Empty file written last |

## 5. Database (summary — full DDL in `01-sql.md`)

SQLite file `data/cardpulse.db`. Tables: `sets`, `pokemon`, `cards`, `card_printings`,
`price_observations`, `fx_rates`, `pipeline_runs`, `pipeline_steps`, `data_quality_results`.
Views: `v_as_of`, `v_card_history`, `v_card_metrics`, `v_set_value_series`. Other modules read the
database **only through these names and columns**.

## 6. Commands (the interface between modules)

Every script runs from the repo root with no required arguments, uses `config.py` paths, and
returns exit code `0` on success and non-zero on failure. Optional flags may exist but defaults
must work. Scripts import shared code as top-level modules (`import config`). This works because
each script runs as `python pipeline/<file>.py`, which puts `pipeline/` on `sys.path`. There is no
`pipeline/__init__.py`. Code running from elsewhere (the Airflow DAG) inserts `<repo>/pipeline` into
`sys.path` first.

| Command | Does | Exit code |
|---|---|---|
| `python pipeline/collect.py` | Reference data + monthly backfill (slow first time, cached) | 0 / 1 |
| `python pipeline/snapshot_prices.py [--date YYYY-MM-DD]` | Today's prices into `data/snapshots/<date>/`. Skips if that folder already has `_SUCCESS`. | 0 / 1 |
| `python pipeline/load_db.py [--rebuild]` | Creates schema if missing, loads all raw files and complete snapshots idempotently, (re)creates views | 0 / 1 |
| `python pipeline/validate.py [--run-id ID]` | Runs `sql/checks.sql`, stores results | 0 = no `error` checks failed, 2 = an `error` check failed, 1 = crash |
| `python pipeline/build.py` | Builds `site/` | 0 / 1 |
| `python pipeline/run_all.py` | All steps in order, with run logging | 0 if all succeed |

Environment variable `CARDPULSE_RUN_ID` (optional): when set, scripts that log (`validate.py`,
`runlog.py`) attach their records to that run.

## 7. Milestones

| Milestone | Date | Must be true |
|---|---|---|
| **M1 — Check-in** | Mon 2026-11-23 | Database built from existing JSON with all tables, views and checks; `run_all.py` runs collect (skipped if done) → snapshot → load → validate → build locally; Dockerfile runs that pipeline; DAG file exists and parses |
| **M2 — Final** | Mon 2026-11-30 | Daily snapshots flowing into the database; DAG runs in Airflow inside Docker; `build.py` reads from the database (website task); README run instructions verified on a clean machine |

## 8. Definition of done (every module PR)

- Only files listed in your spec are added or changed.
- Fresh clone + your spec's verification steps pass, and the PR description pastes their output.
- No secrets, no absolute local paths, no generated files (`data/`, `site/`) committed.
- PR targets `develop`, links its issue, and has one approval (see CONTRIBUTING.md).
