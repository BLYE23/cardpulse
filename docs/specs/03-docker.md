# 03 — Docker Module: Reproducible Containers

Read `00-architecture.md` first.

## Goal

Anyone (a teammate, the instructor, us in five years) can run the whole project on Windows, macOS or Linux with
Docker and no local Python setup:

| Command | Result |
|---|---|
| `docker compose run --rm pipeline` | Runs the full pipeline once (`pipeline/run_all.py`). Data stays in `./data`, the website in `./site` |
| `docker compose up -d web` | Serves the website at http://localhost:8000 |
| `docker compose --profile airflow up -d airflow` | Starts Airflow at http://localhost:8080 with the `cardpulse_daily` DAG (M2) |

Docker is for developers and graders. Players only ever see the website.

## Files you own

| File | Create |
|---|---|
| `Dockerfile` | Pipeline image (§2) |
| `docker/airflow.Dockerfile` | Airflow image (§4, M2) |
| `docker-compose.yml` | Services (§3) |
| `.dockerignore` | §2 |
| `README.md` | Only add a "Run with Docker" subsection under "Quick start" with the three commands above, first-run time, and where outputs appear |

Do not edit other files. If a step fails because of another module's script, report it in your PR
or issue; do not patch their file.

## 1. Constraints

- Pin every base image to the exact tags below. Python dependencies come only from `requirements.txt` (already pinned).
- Containers write only to the bind-mounted `./data` and `./site`. No data is baked into images.
- No secrets are needed. Do not add `.env` requirements.
- Shell files (if any) must use LF line endings (`.gitattributes` already enforces this).
- Everything runs as described on Docker Desktop for Windows and macOS.

## 2. Pipeline image (`Dockerfile`)

```dockerfile
FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pipeline/ pipeline/
COPY sql/ sql/
COPY web/ web/
CMD ["python", "pipeline/run_all.py"]
```

`.dockerignore`:
```
.git
data/
site/
.venv/
venv/
**/__pycache__/
*.pyc
docs/
```

Code is copied in (immutable image). Data and site are mounted at runtime (§3). The code paths
work because `config.py` resolves the root from its own location (`/app`).

## 3. `docker-compose.yml`

```yaml
services:
  pipeline:
    build: .
    image: cardpulse-pipeline:0.1
    volumes:
      - ./data:/app/data
      - ./site:/app/site
    # default CMD runs pipeline/run_all.py

  web:
    image: python:3.12-slim-bookworm
    working_dir: /srv
    command: ["python", "-m", "http.server", "8000", "--directory", "/srv/site", "--bind", "0.0.0.0"]
    ports:
      - "8000:8000"
    volumes:
      - ./site:/srv/site:ro

  airflow:                      # M2
    profiles: ["airflow"]
    build:
      context: .
      dockerfile: docker/airflow.Dockerfile
    image: cardpulse-airflow:0.1
    command: ["standalone"]
    user: "${AIRFLOW_UID:-50000}:0"
    environment:
      CARDPULSE_HOME: /opt/cardpulse
      AIRFLOW__CORE__LOAD_EXAMPLES: "False"
      AIRFLOW__CORE__DAGS_FOLDER: /opt/cardpulse/dags
      AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL: "30"
    ports:
      - "8080:8080"
    volumes:
      - ./:/opt/cardpulse          # whole repo: code, dags, data, site
      - airflow-home:/opt/airflow  # Airflow metadata DB and logs persist across restarts

volumes:
  airflow-home:
```

Notes:
- `pipeline` and the DAG both run the same `pipeline/run_all.py` steps (see `02-dag.md`), against the same `./data`.
- On Linux hosts set `AIRFLOW_UID=$(id -u)` so files written to `./data` are owned by the user. Docker Desktop on Windows/macOS needs nothing.

## 4. Airflow image (`docker/airflow.Dockerfile`, M2)

```dockerfile
FROM apache/airflow:2.10.5-python3.12
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
```

`airflow standalone` creates the metadata database and an `admin` user, and prints the generated
password in the logs (`docker compose logs airflow | grep -i password`). Document this in the README subsection.

## 5. Milestones

- **M1 (11/23):** `Dockerfile`, `.dockerignore`, `docker-compose.yml` with `pipeline` and `web`. If the SQL and DAG modules are not merged yet, verify with a temporary override command `python pipeline/collect.py && python pipeline/build.py` locally (do not commit the override). The default `CMD` stays `run_all.py`.
- **M2 (11/30):** `airflow` service and image. DAG visible and runnable. README subsection complete and verified on a second teammate's machine.

## 6. Verification (paste outputs into the PR)

1. `docker compose build` succeeds with no warnings about unpinned images.
2. `docker compose run --rm pipeline` exits 0. `data/cardpulse.db` and an updated `site/index.html` exist on the host.
   First run on an empty `./data` takes about 20–40 minutes (backfill). Later runs take a few minutes.
3. `docker compose up -d web`, then open http://localhost:8000: the site loads, including card images.
4. Run step 2 a second time: still exits 0, and `collect_reference` is logged as `skipped`.
5. M2: `docker compose --profile airflow up -d airflow`. The UI at http://localhost:8080 lists
   `cardpulse_daily` with no import errors. A manual trigger finishes green, and
   `SELECT trigger, status FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;` returns `airflow | success`.
6. `docker compose down` leaves `./data` and `./site` intact.
