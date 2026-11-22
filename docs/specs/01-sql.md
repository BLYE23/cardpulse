# 01 — SQL Module: Database, Loader, Views, Checks

Read `00-architecture.md` first.

## Goal

Store every piece of data the pipeline collects in a SQLite database with a fixed schema, compute
the website's metrics with SQL views, and run data quality checks. The existing Python
(`collect.py`, `build.py`) stays unchanged. This module adds a database layer next to it.

## Files you own

| File | Create |
|---|---|
| `sql/schema.sql` | Exact DDL from §2 |
| `sql/views.sql` | Views from §4 |
| `sql/checks.sql` | Checks from §5 |
| `sql/queries/01_top_movers.sql`, `02_set_value.sql`, `03_us_vs_eu.sql`, `04_rarity_premium.sql` | Example queries from §6 |
| `pipeline/load_db.py` | Loader from §3 |
| `pipeline/validate.py` | Check runner from §5 |
| `README.md` | Only add a "Database" subsection under "Project structure" listing the tables in one line each |

Do not edit any other file. Standard library only (`sqlite3`, `json`, `argparse`, `pathlib`).
Import paths and `norm_printing` from `pipeline/config.py`.

## 1. Rules

- Database file: `config.DB_PATH`. Every connection runs `PRAGMA foreign_keys = ON;`.
- Load order inside one transaction per table group: `sets` → `pokemon` → `cards` → `card_printings` → `price_observations` → `fx_rates`. Then views.
- **Idempotent:** running `load_db.py` twice in a row gives the same row counts. Use
  `INSERT ... ON CONFLICT ... DO UPDATE` (upsert), never plain `INSERT` duplicates.
- `--rebuild` deletes the database file first and loads from scratch.
- Views are dropped and recreated on every run (`DROP VIEW IF EXISTS` then the `CREATE VIEW` statements in `sql/views.sql`).
- Business thresholds in SQL must equal the values in `config.py` (they are written as literals in `views.sql`, with a comment naming the config constant).

## 2. Schema (`sql/schema.sql`) — copy exactly

```sql
-- CardPulse schema. Contract: do not rename tables or columns without the project lead.
CREATE TABLE IF NOT EXISTS sets (
    set_id              TEXT PRIMARY KEY,           -- TCGdex set id, e.g. 'sv03.5'
    name                TEXT NOT NULL,
    series              TEXT,                       -- TCGdex 'serie', e.g. 'Scarlet & Violet'
    release_date        TEXT,                       -- YYYY-MM-DD
    logo_url            TEXT,
    tcgplayer_group_id  INTEGER NOT NULL UNIQUE     -- from config.SETS
);

CREATE TABLE IF NOT EXISTS pokemon (
    dex_id          INTEGER PRIMARY KEY,            -- National Pokedex number
    name            TEXT NOT NULL,                  -- PokeAPI name, lowercase, e.g. 'charizard'
    generation      TEXT NOT NULL,                  -- Roman numeral, e.g. 'I' (from 'generation-i')
    type_primary    TEXT NOT NULL,
    type_secondary  TEXT,
    hp              INTEGER NOT NULL,
    attack          INTEGER NOT NULL,
    defense         INTEGER NOT NULL,
    sp_attack       INTEGER NOT NULL,
    sp_defense      INTEGER NOT NULL,
    speed           INTEGER NOT NULL,
    base_stat_total INTEGER NOT NULL,               -- sum of the six stats
    is_legendary    INTEGER NOT NULL CHECK (is_legendary IN (0, 1)),
    is_mythical     INTEGER NOT NULL CHECK (is_mythical IN (0, 1)),
    capture_rate    INTEGER,
    sprite_url      TEXT
);

CREATE TABLE IF NOT EXISTS cards (
    card_id          TEXT PRIMARY KEY,              -- TCGdex card id, e.g. 'sv03.5-199'
    set_id           TEXT NOT NULL REFERENCES sets(set_id),
    local_id         TEXT NOT NULL,                 -- number within the set, e.g. '199'
    name             TEXT NOT NULL,
    category         TEXT NOT NULL CHECK (category IN ('Pokemon', 'Trainer', 'Energy')),
    rarity           TEXT,
    hp               INTEGER,
    illustrator      TEXT,
    stage            TEXT,
    dex_id           INTEGER REFERENCES pokemon(dex_id),  -- first TCGdex dexId; NULL for Trainer/Energy
    image_url        TEXT,                          -- TCGdex 'image' base URL (append '/low.webp')
    primary_printing TEXT                           -- see 00-architecture §3; NULL if no TCGplayer price
);

CREATE TABLE IF NOT EXISTS card_printings (
    card_id              TEXT NOT NULL REFERENCES cards(card_id),
    printing             TEXT NOT NULL,             -- normalized: 'normal' | 'holofoil' | 'reverse-holofoil' | ...
    tcgplayer_product_id INTEGER NOT NULL,
    PRIMARY KEY (card_id, printing)
);
CREATE INDEX IF NOT EXISTS ix_printings_product ON card_printings (tcgplayer_product_id, printing);

CREATE TABLE IF NOT EXISTS price_observations (
    card_id     TEXT NOT NULL,
    printing    TEXT NOT NULL,
    market      TEXT NOT NULL CHECK (market IN ('tcgplayer', 'cardmarket')),
    price_date  TEXT NOT NULL,                      -- YYYY-MM-DD
    price       REAL NOT NULL CHECK (price > 0),
    currency    TEXT NOT NULL CHECK (currency IN ('USD', 'EUR')),
    source      TEXT NOT NULL CHECK (source IN ('tcgcsv_daily', 'tcgcsv_archive', 'tcgdex')),
    loaded_at   TEXT NOT NULL,                      -- ISO 8601 UTC
    PRIMARY KEY (card_id, printing, market, price_date),
    FOREIGN KEY (card_id, printing) REFERENCES card_printings(card_id, printing)
);
CREATE INDEX IF NOT EXISTS ix_obs_market_date ON price_observations (market, price_date);

CREATE TABLE IF NOT EXISTS fx_rates (
    rate_date TEXT PRIMARY KEY,                     -- YYYY-MM-DD (Frankfurter 'date')
    base      TEXT NOT NULL DEFAULT 'EUR',
    quote     TEXT NOT NULL DEFAULT 'USD',
    rate      REAL NOT NULL CHECK (rate > 0)        -- USD per 1 EUR
);

-- Written by the DAG module (pipeline/runlog.py); defined here so one file owns the schema.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      TEXT PRIMARY KEY,                   -- e.g. 'run_all-20261123T210500Z' or Airflow run_id
    trigger     TEXT NOT NULL CHECK (trigger IN ('airflow', 'run_all', 'manual')),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed'))
);

CREATE TABLE IF NOT EXISTS pipeline_steps (
    run_id        TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    step          TEXT NOT NULL,                    -- step name from pipeline/steps.py
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    duration_s    REAL,
    status        TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    message       TEXT,
    PRIMARY KEY (run_id, step)
);

CREATE TABLE IF NOT EXISTS data_quality_results (
    run_id       TEXT NOT NULL,                     -- CARDPULSE_RUN_ID, or 'manual-<UTC timestamp>'
    check_name   TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('error', 'warn')),
    failing_rows INTEGER NOT NULL,
    passed       INTEGER NOT NULL CHECK (passed IN (0, 1)),
    checked_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, check_name)
);
```

## 3. Loader (`pipeline/load_db.py`)

CLI: `python pipeline/load_db.py [--rebuild] [--db PATH]`. Default db = `config.DB_PATH`.
Executes `sql/schema.sql`, loads in this order, recreates views, prints a summary, exits 0. Any
exception: print the error, exit 1. If a required input file is missing (`data/tcgdex.json`,
`data/pokeapi.json`), exit 1 with a message telling the user to run `collect.py`. `history.json`,
`fx.json` and snapshots are optional.

| Target | Source | Mapping |
|---|---|---|
| `sets` | `tcgdex.json["sets"]`, only ids in `config.SETS` | `set_id=id, name, series=serie, release_date=releaseDate, logo_url=logo, tcgplayer_group_id=config.SETS[id]` |
| `pokemon` | `pokeapi.json` values | `dex_id=id, name, generation=upper(text after 'generation-')`, `type_primary=types[0]`, `type_secondary=types[1] or NULL`, six stats from `stats` (`special-attack`→`sp_attack`, `special-defense`→`sp_defense`), `base_stat_total=sum`, `is_legendary`, `is_mythical` as 0/1, `capture_rate`, `sprite_url=sprite` |
| `cards` | `tcgdex.json["cards"]` with `_set` in `config.SETS` | `card_id=id, set_id=_set, local_id=localId, name, category, rarity, hp` (int or NULL), `illustrator, stage, image_url=image`, `dex_id = dexId[0]` if present **and** in `pokemon`, else NULL; `primary_printing` per 00-architecture §3 |
| `card_printings` | each card's `pricing.tcgplayer` entries that are objects with a `productId` | `printing=norm_printing(key)`, `tcgplayer_product_id=productId` |
| `price_observations` (archive) | `history.json` | Split key at the first `|` into `productId` and `subTypeName`. Join `(int(productId), norm_printing(subTypeName))` to `card_printings`. Unmatched keys are skipped (they are other products). Each `date: price` with price > 0 → `market='tcgplayer', currency='USD', source='tcgcsv_archive'` |
| `price_observations` (TCGdex, TCGplayer) | each card's `pricing.tcgplayer.<printing>.marketPrice` > 0 | `price_date = pricing.tcgplayer.updated[:10]`, `market='tcgplayer', currency='USD', source='tcgdex'` |
| `price_observations` (TCGdex, Cardmarket) | each card's `pricing.cardmarket` | `trend` > 0 → printing = card's `primary_printing` (skip if NULL). `trend-holo` > 0 → printing `'reverse-holofoil'` **only if** the card has that printing in `card_printings`. `price_date = pricing.cardmarket.updated[:10]`, `market='cardmarket', currency='EUR', source='tcgdex'` |
| `price_observations` (snapshots) | every `data/snapshots/<date>/` that has `_SUCCESS` | `tcgplayer.json`: each row in every group, join like the archive, `price=marketPrice` (skip NULL / ≤ 0), `source='tcgcsv_daily'`, `price_date=<date>`. `cardmarket.json`: same rules as the TCGdex Cardmarket row above, but `price_date=<date>` |
| `fx_rates` | `data/fx.json` and each snapshot `fx.json` | `rate_date=date, base, quote='USD', rate=rates.USD` |

**Conflict rule for `price_observations`** (same `card_id, printing, market, price_date`): keep the
row from the higher-priority source. Priority: `tcgcsv_daily` (3) > `tcgcsv_archive` (2) > `tcgdex` (1).
Equal priority: the newer load wins. Implement with:

```sql
INSERT INTO price_observations (card_id, printing, market, price_date, price, currency, source, loaded_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (card_id, printing, market, price_date) DO UPDATE SET
    price = excluded.price, currency = excluded.currency, source = excluded.source, loaded_at = excluded.loaded_at
WHERE (CASE excluded.source WHEN 'tcgcsv_daily' THEN 3 WHEN 'tcgcsv_archive' THEN 2 ELSE 1 END)
   >= (CASE price_observations.source WHEN 'tcgcsv_daily' THEN 3 WHEN 'tcgcsv_archive' THEN 2 ELSE 1 END);
```

**Summary output:** last line of stdout is one JSON object:
`{"sets": n, "pokemon": n, "cards": n, "card_printings": n, "price_observations": n, "fx_rates": n, "as_of_date": "YYYY-MM-DD"}`
(counts are totals in the database after the load).

## 4. Views (`sql/views.sql`)

All "current" values are relative to the **as-of date**, not the wall clock, so results are
reproducible. Prices below mean TCGplayer USD prices of the card's **primary printing** unless
stated otherwise. SQLite window functions are available (SQLite ≥ 3.25 ships with Python 3.12).

### `v_as_of`
One row, one column: `as_of_date = MAX(price_date)` over `price_observations` where `market='tcgplayer'`.

### `v_card_history`
`card_id, price_date, price`: all TCGplayer observations of each card's primary printing. Used for
price charts and set values.

### `v_card_metrics` — one row per card with a primary printing
| Column | Definition |
|---|---|
| `card_id, name, set_id, local_id, rarity, hp, illustrator, category, dex_id, image_url, primary_printing` | From `cards` |
| `usd`, `usd_date` | Latest `v_card_history` price for the card and its date |
| `first_date` | Earliest `v_card_history` date for the card |
| `eur`, `eur_date` | Latest Cardmarket price for (card, primary printing) and its date; NULL if none |
| `fx_rate` | Latest `fx_rates.rate`; NULL if table empty |
| `eu_usd` | `ROUND(eur * fx_rate, 2)` |
| `gap` | NULL if `eu_usd` is NULL or `usd < 1.0` or `eu_usd < 1.0` (GAP_MIN_USD). Else `g = 1 - eu_usd / usd`; `gap = 0` if `ABS(g) < 0.10` (GAP_SAME_THRESHOLD), otherwise `ROUND(g, 3)`. Positive = Europe cheaper |
| `gap_label` | NULL if `gap` is NULL; `'same'` if `gap = 0`; `'check_condition'` if `ABS(gap) > 0.50` (GAP_WILD_THRESHOLD); `'eu_cheaper'` if `gap > 0`; else `'us_cheaper'` |
| `chg_3m`, `chg_12m` | For `m` months: `start = date(as_of_date, 'start of month', '-m months')`, `month_end = date(start, '+1 month', '-1 day')`. `old` = price at the earliest history date ≥ `start`. Value = `ROUND(usd / old - 1, 4)` if `first_date <= month_end` and `old > 0`, else NULL |
| `chg_7d` | `start = date(as_of_date, '-7 days')`. `old` = price at the earliest history date in `[start, date(start, '+2 days')]`. `ROUND(usd / old - 1, 4)` if found, else NULL (NULL is expected until daily snapshots exist) |
| `low_12m`, `high_12m` | MIN / MAX history price with `price_date >= date(as_of_date, '-12 months')` |
| `range_pos_12m` | `ROUND((usd - low_12m) / (high_12m - low_12m), 3)`; NULL if fewer than 2 points in the window or `high_12m = low_12m` |
| `range_label_12m` | `'low'` if `range_pos_12m <= 0.20` (RANGE_LOW_POS), `'high'` if `>= 0.80` (RANGE_HIGH_POS), `'mid'` otherwise; NULL when `range_pos_12m` is NULL |

### `v_set_value_series`
`set_id, price_date, total_usd, cards_priced, cards_in_set, coverage`: for every distinct history
date, the sum of `v_card_history.price` over the set's cards on that date. `cards_in_set` = cards of
the set with a primary printing. `coverage = cards_priced * 1.0 / cards_in_set`. Keep only rows with
`coverage >= 0.60` (SET_VALUE_MIN_COVERAGE).

Pokémon-level medians stay in Python (`build.py`), because SQLite has no `MEDIAN`.

## 5. Data quality checks

`sql/checks.sql` is a list of blocks. Each block starts with a marker line and contains one SELECT
returning the **failing rows**:

```sql
-- check: price_non_positive | error
SELECT * FROM price_observations WHERE price IS NULL OR price <= 0;
```

Required checks:

| Name | Severity | Fails when |
|---|---|---|
| `cards_without_set` | error | a card's `set_id` is not in `sets` |
| `price_unknown_printing` | error | a `price_observations` (card_id, printing) is not in `card_printings` |
| `price_non_positive` | error | price NULL or ≤ 0 |
| `price_future_date` | error | `price_date > date('now', '+1 day')` |
| `price_currency_mismatch` | error | tcgplayer not USD or cardmarket not EUR |
| `fx_missing` | error | `fx_rates` is empty (return one row when empty) |
| `primary_without_price` | error | a card has `primary_printing` but no TCGplayer observation for it |
| `pokemon_card_without_dex` | warn | `category = 'Pokemon'` and `dex_id IS NULL` |
| `card_without_tcgplayer` | warn | `primary_printing IS NULL` |
| `price_jump_10x` | warn | consecutive history prices of a card differ by more than 10× either way (use `LAG`) |
| `history_too_short` | warn | a priced card has fewer than 2 history points |
| `prices_stale` | warn | `as_of_date < date('now', '-3 days')` |

`pipeline/validate.py`: CLI `python pipeline/validate.py [--run-id ID] [--db PATH]`. Run id: the flag,
else env `CARDPULSE_RUN_ID`, else `manual-<UTC YYYYMMDDTHHMMSSZ>`. Parse blocks by the marker regex
`^-- check: (\w+) \| (error|warn)$`, run `SELECT COUNT(*) FROM (<block without trailing ;>)`,
upsert into `data_quality_results`, print one line per check (`PASS`/`FAIL`, name, severity,
failing rows). Exit **2** if any `error` check fails, **0** otherwise, **1** on crash.

## 6. Example queries (`sql/queries/`)

Plain SELECTs on the views/tables, each with a header comment saying what question it answers.
They are used in the presentation to show SQL work. Use JOIN, GROUP BY and a window function at least once overall.

1. `01_top_movers.sql`: top 10 cards by `chg_12m` with `usd >= 5`, with set name (JOIN `sets`).
2. `02_set_value.sql`: latest `total_usd` per set, and the change since that set's first point.
3. `03_us_vs_eu.sql`: count of cards per `gap_label`, with the average gap, per set.
4. `04_rarity_premium.sql`: per rarity, card count, median-free summary (MIN, AVG, MAX of `usd`), ordered by AVG.

## 7. Verification (paste outputs into the PR)

With the lead's current data (collected 2026-11-16), a clean `python pipeline/load_db.py --rebuild` must print:

```
{"sets": 5, "pokemon": 403, "cards": 914, "card_printings": 1420, "price_observations": 41560, "fx_rates": 1, "as_of_date": "2026-11-15"}
```

(38,720 archive + 1,420 TCGdex TCGplayer + 1,420 Cardmarket observations.) If you ran
`collect.py` yourself on a later day, counts will differ slightly; the checks below must still hold.

1. Run `load_db.py` twice: identical summary both times.
2. `python pipeline/validate.py` exits 0; only `warn` checks may fail (`card_without_tcgplayer` = 1 is expected).
3. Spot checks:
   ```sql
   SELECT usd, eur, eu_usd, gap_label FROM v_card_metrics WHERE card_id = 'sv03.5-199';
   -- usd 287.6, eur 342.79, eu_usd 377.55 (fx 1.1014), gap_label 'us_cheaper'
   SELECT usd FROM v_card_metrics WHERE card_id = 'base1-4';   -- 987.13
   SELECT COUNT(*) FROM v_card_metrics;                          -- 913
   ```
4. Each file in `sql/queries/` runs without error: `sqlite3 data/cardpulse.db < sql/queries/01_top_movers.sql`
   (or the Python equivalent).
