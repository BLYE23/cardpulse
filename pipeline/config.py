"""Shared constants for every pipeline module. Import from here; never redefine these values.

See docs/specs/00-architecture.md for how each value is used.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---- paths (all relative to the repo root) ----
DATA_DIR = ROOT / "data"                 # raw inputs, git-ignored
SNAPSHOT_DIR = DATA_DIR / "snapshots"    # daily price snapshots: data/snapshots/YYYY-MM-DD/
DB_PATH = DATA_DIR / "cardpulse.db"      # SQLite database, git-ignored
SQL_DIR = ROOT / "sql"
SITE_DIR = ROOT / "site"

# ---- sets in scope: TCGdex set id -> TCGplayer group id (used by tcgcsv) ----
# pipeline/collect.py keeps its own copy of the set list; keep both in sync until it imports this module.
SETS = {
    "base1": 604,      # Base Set (1999)
    "swsh7": 2848,     # Evolving Skies (2021)
    "sv03.5": 23237,   # 151 (2023)
    "sv08.5": 23821,   # Prismatic Evolutions (2025)
    "me01": 24380,     # Mega Evolution (2025)
}
TCGPLAYER_CATEGORY_ID = 3  # Pokemon on tcgcsv

# ---- HTTP ----
USER_AGENT = "CardPulse/0.1"   # tcgcsv rejects generic or missing user agents

# ---- business rules shared by SQL views and the website ----
PRIMARY_PRINTING_ORDER = ("holofoil", "normal")  # first one the card has; else its first TCGplayer printing
GAP_MIN_USD = 1.0         # compare US vs EU only when both prices are at least this
GAP_SAME_THRESHOLD = 0.10  # |gap| below this counts as "about the same"
GAP_WILD_THRESHOLD = 0.50  # |gap| above this is flagged "compare condition", not tagged
RANGE_LOW_POS = 0.20       # 12-month range position <= this -> "low"
RANGE_HIGH_POS = 0.80      # 12-month range position >= this -> "high"
SET_VALUE_MIN_COVERAGE = 0.60  # a set-value point needs prices for at least 60% of the set's cards


def norm_printing(name: str) -> str:
    """Normalize a printing label from any source to one key.

    TCGdex uses 'reverse-holofoil'; tcgcsv uses 'Reverse Holofoil'. Both become 'reverse-holofoil'.
    """
    return name.strip().lower().replace(" ", "-")
