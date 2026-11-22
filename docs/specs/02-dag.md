# 02 — DAG Module: Daily Snapshot, Step List, Run Logging, Airflow DAG

Read `00-architecture.md` first. This module depends on the SQL module's **interface** (table names
and commands in `01-sql.md`), not on its code being finished.

## Goal

Run the whole pipeline once a day, in order, and **measure it from start to finish**: every run and
every step gets a start time, end time, duration and status in the database. The same step list
drives both the Airflow DAG and a plain-Python runner, so the two can never drift apart.

## Files you own

| File | Create |
|---|---|
| `pipeline/snapshot_prices.py` | Daily price snapshot (§2) |
| `pipeline/steps.py` | The single ordered step list (§3) |
| `pipeline/runlog.py` | Run/step logging helpers (§4) |
| `pipeline/run_all.py` | Runs all steps without Airflow (§5) |
| `dags/cardpulse_daily.py` | Airflow DAG (§6) |
| `README.md` | Only add a "Pipeline steps" subsection under "Quick start": the step table from §3 and the `run_all.py` command |

Do not edit other files. Standard library only for `pipeline/*` (`urllib`, `json`, `subprocess`,
`sqlite3`, `dataclasses`, `datetime`). The DAG file may import `airflow`. Shared code is imported as
top-level modules (`import config`, `import steps`, `import runlog`), because scripts run as
`python pipeline/<file>.py` and `pipeline/` has no `__init__.py`.

## 1. Run flow

```
collect_reference ─► snapshot_prices ─► load_db ─► validate ─► build_site
  (skips when reference
   files already exist)
```

A run stops at the first failed step. Downstream steps do not run.

## 2. `pipeline/snapshot_prices.py`

CLI: `python pipeline/snapshot_prices.py [--date YYYY-MM-DD]`. Default date = today in UTC.
Writes the folder defined in `00-architecture.md` §4.2.

1. If `data/snapshots/<date>/_SUCCESS` exists: print `snapshot <date> already complete, skipping`, exit 0.
2. Requires `data/tcgdex.json` (for the card list). If missing: exit 1 with "run collect.py first".
3. Create (or reuse) the folder. Fetch, with header `User-Agent: config.USER_AGENT`, timeout 60 s:
   - **TCGplayer** for each group id in `config.SETS`:
     `GET https://tcgcsv.com/tcgplayer/{config.TCGPLAYER_CATEGORY_ID}/{groupId}/prices` → keep `results` as returned.
     Sleep 0.1 s between requests (tcgcsv rule). Any group failing after retries → exit 1.
   - **Cardmarket** for every card id in `data/tcgdex.json` whose `_set` is in `config.SETS`:
     `GET https://api.tcgdex.net/v2/en/cards/{card_id}` with **no cache** (prices must be fresh) → keep `pricing.cardmarket`.
     Sleep 0.05 s between requests. Cards that still fail after retries are left out. If more than 10% of cards are missing → exit 1.
   - **FX:** `GET https://api.frankfurter.dev/v1/latest?from=EUR&to=USD`.
4. Retries: up to 6 attempts with backoff `min(60, 3 * 2**attempt)` seconds on network errors and HTTP 429/5xx. HTTP 404 → no retry.
5. Write `tcgplayer.json`, `cardmarket.json`, `fx.json` (formats in 00 §4.2), then the empty `_SUCCESS` last.
6. Print a summary line: `snapshot <date>: tcgplayer rows=<n>, cardmarket cards=<n>/<total>, fx=<rate>`. Exit 0.

Expected runtime: about 3–5 minutes (one TCGdex request per card).

## 3. `pipeline/steps.py`

```python
from dataclasses import dataclass, field
from typing import Callable, Optional

@dataclass(frozen=True)
class Step:
    name: str                      # used as Airflow task_id and pipeline_steps.step
    script: str                    # path relative to the repo root
    args: tuple = ()
    skip_if: Optional[Callable[[], bool]] = None   # True -> step is logged as 'skipped'

def reference_ready() -> bool:
    """True when collect.py output exists, unless CARDPULSE_FORCE_COLLECT=1 is set."""
    ...  # data/tcgdex.json, data/pokeapi.json and data/history.json all exist

STEPS = [
    Step("collect_reference", "pipeline/collect.py", skip_if=reference_ready),
    Step("snapshot_prices",   "pipeline/snapshot_prices.py"),
    Step("load_db",           "pipeline/load_db.py"),
    Step("validate",          "pipeline/validate.py"),
    Step("build_site",        "pipeline/build.py"),
]
```

`collect.py` is skipped on normal runs. It downloads 34 monthly tcgcsv archives, and tcgcsv asks
users not to download archives repeatedly. Never pass `--rebuild` to `load_db.py` from a pipeline step.

## 4. `pipeline/runlog.py`

Writes the `pipeline_runs` and `pipeline_steps` tables defined in `01-sql.md` §2. On first use,
execute `sql/schema.sql` (it is all `CREATE ... IF NOT EXISTS`) so logging works before `load_db`
has ever run. Until the SQL PR is merged, test with a local copy of the DDL from `01-sql.md` §2;
do not commit that copy.

```python
def start_run(trigger: str, run_id: str | None = None) -> str: ...
    # trigger in {'airflow','run_all','manual'}; default run_id f"{trigger}-{UTC %Y%m%dT%H%M%SZ}"
    # inserts pipeline_runs(status='running'); returns run_id
def start_step(run_id: str, step: str) -> None: ...          # upsert pipeline_steps(status='running')
def finish_step(run_id: str, step: str, status: str, message: str | None = None) -> None: ...
    # status in {'success','failed','skipped'}; sets finished_at, duration_s
def finish_run(run_id: str, status: str) -> None: ...        # 'success' | 'failed'; sets finished_at
```

Timestamps are ISO 8601 UTC with `Z`. Use `config.DB_PATH`. Each call opens and closes its own
connection, so it is safe across subprocesses. `message` stores the last 500 characters of stderr on failure.

## 5. `pipeline/run_all.py`

CLI: `python pipeline/run_all.py`. For each step in `STEPS`, in order:

1. `run_id = runlog.start_run("run_all")`. Export it to children as env `CARDPULSE_RUN_ID`.
2. If `step.skip_if` returns True: log `skipped`, continue.
3. Else `start_step`, run `subprocess.run([sys.executable, step.script, *step.args], cwd=config.ROOT, env=...)`,
   stream its output to the console, then `finish_step` with `success` (exit 0) or `failed`.
4. On the first failure: `finish_run(run_id, "failed")` and exit with that step's exit code
   (so a failed data quality check exits 2).
5. After all steps: `finish_run(run_id, "success")`, print a table of step durations, exit 0.

## 6. `dags/cardpulse_daily.py` (Airflow 2.10.x)

| Setting | Value |
|---|---|
| `dag_id` | `cardpulse_daily` |
| `schedule` | `"30 21 * * *"` (21:30 UTC daily; tcgcsv refreshes around 20:00 UTC) |
| `start_date` | `pendulum.datetime(2026, 11, 20, tz="UTC")` |
| `catchup` | `False` |
| `max_active_runs` | `1` |
| `default_args` | `retries=1, retry_delay=timedelta(minutes=10), owner="cardpulse"` |
| `tags` | `["cardpulse"]` |

Project location: env `CARDPULSE_HOME` (default `/opt/cardpulse`, set by the Docker module).
At the top of the DAG file insert `f"{CARDPULSE_HOME}/pipeline"` into `sys.path`, then `import steps, runlog, config`.

Tasks (all `PythonOperator`):
- `start_run`: `runlog.start_run("airflow", run_id=context["run_id"])`.
- One task per entry in `steps.STEPS`, with `task_id = step.name`, chained in list order after
  `start_run`. Callable: same logic as one iteration of `run_all.py` (skip check, subprocess with
  `env CARDPULSE_RUN_ID=context["run_id"]`, `start_step`/`finish_step`). A non-zero exit raises
  `AirflowException` with the step's stderr tail. A skip is logged as `skipped` and returns normally
  (do **not** raise `AirflowSkipException`, which would skip downstream tasks).
- `finish_run`: `trigger_rule="all_done"`. Status `failed` if any task instance in the DAG run
  failed, else `success`.

Do not duplicate step definitions in the DAG. Always build tasks from `steps.STEPS`.

## 7. Milestones

- **M1 (11/23):** `snapshot_prices.py`, `steps.py`, `runlog.py`, `run_all.py` work locally. The DAG file parses (`python -c "import ast,sys; ast.parse(open('dags/cardpulse_daily.py').read())"`).
- **M2 (11/30):** The DAG runs end to end in the Docker module's Airflow container. Triggered manually once, and once on schedule.

## 8. Verification (paste outputs into the PR)

1. `python pipeline/snapshot_prices.py` → folder with three JSON files and `_SUCCESS`; running it again prints the skip message.
2. `python pipeline/run_all.py` exits 0 (after the SQL module is merged). Then:
   ```sql
   SELECT run_id, trigger, status, started_at, finished_at FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;
   SELECT step, status, ROUND(duration_s, 1) FROM pipeline_steps WHERE run_id = (SELECT MAX(run_id) FROM pipeline_runs);
   -- 5 rows: collect_reference 'skipped', the other four 'success'
   ```
3. Failure path: temporarily make `validate.py` exit 2 (local edit, not committed). `run_all.py` must exit 2, the run must be `failed`, and `build_site` must have no row.
4. M2: `airflow dags list-import-errors` is empty, and `airflow dags test cardpulse_daily 2026-11-23` succeeds inside the container. The run appears in `pipeline_runs` with `trigger = 'airflow'`.
