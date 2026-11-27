"""The ordered steps shared by the standalone runner and Airflow."""

from dataclasses import dataclass
import os
from typing import Callable

import config


@dataclass(frozen=True)
class Step:
    name: str
    script: str
    args: tuple[str, ...] = ()
    skip_if: Callable[[], bool] | None = None


def reference_ready() -> bool:
    return os.environ.get("CARDPULSE_FORCE_COLLECT") != "1" and all(
        (config.DATA_DIR / name).is_file()
        for name in ("tcgdex.json", "pokeapi.json", "history.json")
    )


STEPS = [
    Step("collect_reference", "pipeline/collect.py", skip_if=reference_ready),
    Step("snapshot_prices", "pipeline/snapshot_prices.py"),
    Step("load_db", "pipeline/load_db.py"),
    Step("validate", "pipeline/validate.py"),
    Step("build_site", "pipeline/build.py"),
]
