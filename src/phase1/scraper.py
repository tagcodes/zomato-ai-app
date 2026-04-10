from __future__ import annotations

"""
Phase 1 – Dataset ingestion and canonical catalog builder.

Implements the Phase 1 responsibilities described in docs/phase-wise-architecture.md:
- Load the Zomato dataset from Hugging Face.
- Map raw columns into a canonical schema.
- Validate and transform rows (normalize city, parse cuisines, derive budget_tier).
- Persist a repeatable catalog artifact under data/processed/.

Usage (from project root):
    python -m src.phase1.scraper
or:
    python src/phase1/scraper.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

try:
    from datasets import load_dataset
except ImportError as exc:  # pragma: no cover - import error path
    raise SystemExit(
        "The 'datasets' package is required for Phase 1 ingestion. "
        "Install with: pip install datasets pandas pyarrow"
    ) from exc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DEFAULT_CATALOG_PATH = PROCESSED_DIR / "restaurants.parquet"


HF_DATASET_ID = "ManikaSaini/zomato-restaurant-recommendation"


@dataclass
class IngestionStats:
    raw_rows: int
    processed_rows: int
    dropped_missing_core: int
    dropped_invalid_rating: int


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def load_raw_dataset() -> pd.DataFrame:
    """
    Load the raw Zomato dataset from Hugging Face into a DataFrame.

    This uses the datasets library so that repeated runs are cached locally and
    deterministic.
    """
    ds = load_dataset(HF_DATASET_ID, split="train")
    df = ds.to_pandas()
    return df


def _find_column(df: pd.DataFrame, candidates: Iterable[str], required: bool = True) -> Optional[str]:
    """
    Find the first existing column name from a list of candidates (case-insensitive).

    This makes the ingestion script resilient to small schema differences.
    """
    lower_map = {c.lower(): c for c in df.columns}
    for cand in candidates:
        col = lower_map.get(cand.lower())
        if col is not None:
            return col
    if required:
        joined = ", ".join(candidates)
        raise KeyError(f"None of the expected columns [{joined}] were found in dataset columns: {list(df.columns)}")
    return None


def _normalize_city(raw: str | float | None) -> Optional[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    city = str(raw).strip()
    if not city:
        return None
    # Simple normalization and aliasing; can be extended as needed.
    normalized = city.title()
    alias_map = {
        "Bengaluru": "Bangalore",
    }
    return alias_map.get(normalized, normalized)


def _parse_cuisines(raw: str | float | None) -> list[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return []
    text = str(raw).strip()
    if not text:
        return []
    # Common patterns: "Italian, Chinese", "Italian | Chinese"
    if "|" in text:
        parts = [p.strip() for p in text.split("|")]
    else:
        parts = [p.strip() for p in text.split(",")]
    return [p for p in parts if p]


def _derive_budget_tier(cost_for_two: float | int | None) -> Optional[str]:
    if cost_for_two is None:
        return None
    try:
        value = float(cost_for_two)
    except (TypeError, ValueError):
        return None

    # Simple, clearly documented thresholds; adjust as needed.
    if value <= 500:
        return "low"
    if value <= 1500:
        return "medium"
    return "high"


def build_canonical_catalog(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Map raw dataset columns into the canonical schema described in the architecture doc.

    Canonical fields:
    - id
    - name
    - city
    - cuisines (list[str])
    - rating (float)
    - cost_for_two (float)
    - budget_tier (low | medium | high | None)
    - votes (int, optional)
    - address (str, optional)
    - raw_features (str, optional)
    """
    df = raw_df.copy()

    # Column discovery
    name_col = _find_column(df, ["name", "restaurant_name", "Restaurant Name"])
    city_col = _find_column(df, ["city", "location", "City"])
    cuisine_col = _find_column(df, ["cuisines", "cuisine", "Cuisines"])
    rating_col = _find_column(df, ["aggregate_rating", "rating", "rate", "Rating"])
    cost_col = _find_column(df, ["approx_cost(for two people)", "cost_for_two", "Average Cost for two"], required=False)
    votes_col = _find_column(df, ["votes", "rating_count", "Votes"], required=False)
    address_col = _find_column(df, ["address", "locality", "Location Address"], required=False)

    # If the dataset already has an id-like column, use it; otherwise derive later.
    id_col = _find_column(df, ["id", "restaurant_id"], required=False)

    canonical = pd.DataFrame()
    canonical["name"] = df[name_col].astype(str).str.strip()
    canonical["city"] = df[city_col].apply(_normalize_city)
    canonical["cuisines"] = df[cuisine_col].apply(_parse_cuisines)

    # Ratings: dataset may store as strings like "4.1/5" or "NEW".
    rating_series = df[rating_col]
    if rating_series.dtype == object:
        rating_series = (
            rating_series.astype(str)
            .str.strip()
            .str.replace("/5", "", regex=False)
            .str.extract(r"([0-9]+(?:\.[0-9]+)?)", expand=False)
        )
    canonical["rating"] = pd.to_numeric(rating_series, errors="coerce")

    if cost_col is not None:
        canonical["cost_for_two"] = pd.to_numeric(df[cost_col], errors="coerce")
    else:
        canonical["cost_for_two"] = pd.NA

    canonical["budget_tier"] = canonical["cost_for_two"].apply(_derive_budget_tier)

    if votes_col is not None:
        canonical["votes"] = pd.to_numeric(df[votes_col], errors="coerce").fillna(0).astype(int)
    else:
        canonical["votes"] = 0

    if address_col is not None:
        canonical["address"] = df[address_col].astype(str).str.strip()
    else:
        canonical["address"] = ""

    # Optional raw_features placeholder – attach any free-text column if needed.
    text_col = _find_column(
        df,
        ["highlights", "description", "reviews", "Review Text"],
        required=False,
    )
    if text_col is not None:
        canonical["raw_features"] = df[text_col].astype(str)
    else:
        canonical["raw_features"] = ""

    if id_col is not None:
        canonical["id"] = df[id_col].astype(str)
    else:
        # Derive a stable-ish id from name + city + index.
        canonical["id"] = (
            canonical["name"].fillna("unknown")
            + "::"
            + canonical["city"].fillna("unknown")
            + "::"
            + canonical.index.astype(str)
        )

    # Reorder columns for readability.
    column_order = [
        "id",
        "name",
        "city",
        "cuisines",
        "rating",
        "cost_for_two",
        "budget_tier",
        "votes",
        "address",
        "raw_features",
    ]
    canonical = canonical[column_order]
    return canonical


def validate_catalog(catalog: pd.DataFrame) -> tuple[pd.DataFrame, IngestionStats]:
    """
    Apply row-level validation and drop/quarantine invalid records.

    - Require non-empty name and city.
    - Require rating within a plausible range [0, 5]; drop rows outside or NaN.
    """
    raw_rows = len(catalog)

    valid = catalog.copy()

    mask_core = valid["name"].notna() & valid["name"].str.len().gt(0) & valid["city"].notna()
    dropped_missing_core = int((~mask_core).sum())
    valid = valid[mask_core]

    # Ratings: keep rows with 0 <= rating <= 5; others are dropped.
    rating = valid["rating"]
    mask_rating = rating.notna() & (rating >= 0.0) & (rating <= 5.0)
    dropped_invalid_rating = int((~mask_rating).sum())
    valid = valid[mask_rating]

    processed_rows = len(valid)

    stats = IngestionStats(
        raw_rows=raw_rows,
        processed_rows=processed_rows,
        dropped_missing_core=dropped_missing_core,
        dropped_invalid_rating=dropped_invalid_rating,
    )

    return valid.reset_index(drop=True), stats


def save_catalog(catalog: pd.DataFrame, path: Path = DEFAULT_CATALOG_PATH) -> Path:
    """
    Persist the catalog to disk as Parquet (preferred) to be consumed by later phases.
    """
    _ensure_dirs()
    catalog.to_parquet(path, index=False)
    return path


def run_ingestion() -> tuple[Path, IngestionStats]:
    """
    Orchestrate full Phase 1 ingestion:
    - Load raw dataset.
    - Build canonical catalog.
    - Validate and drop bad rows.
    - Save processed catalog to data/processed/restaurants.parquet.
    """
    print(f"Loading raw dataset from Hugging Face: {HF_DATASET_ID}")
    raw_df = load_raw_dataset()
    print(f"Loaded {len(raw_df)} raw rows.")

    print("Building canonical catalog...")
    canonical = build_canonical_catalog(raw_df)

    print("Validating catalog...")
    valid_catalog, stats = validate_catalog(canonical)

    print(
        "Validation summary:\n"
        f"  Raw rows: {stats.raw_rows}\n"
        f"  Dropped (missing core fields): {stats.dropped_missing_core}\n"
        f"  Dropped (invalid rating): {stats.dropped_invalid_rating}\n"
        f"  Final processed rows: {stats.processed_rows}"
    )

    output_path = save_catalog(valid_catalog)
    print(f"Saved processed catalog to: {output_path}")

    # Also persist a small raw snapshot for debugging if desired.
    snapshot_path = RAW_DIR / "zomato_sample.parquet"
    raw_df.head(1000).to_parquet(snapshot_path, index=False)
    print(f"Saved raw snapshot sample to: {snapshot_path}")

    return output_path, stats


def main() -> None:
    """
    CLI entrypoint for Phase 1 ingestion.
    """
    run_ingestion()


if __name__ == "__main__":
    main()

