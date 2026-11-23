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
