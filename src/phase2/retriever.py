from __future__ import annotations

"""
Phase 2 — Preference model and deterministic filtering.

Implements the Phase 2 responsibilities described in docs/phase-wise-architecture.md:
- Define a typed user preference object.
- Load the processed catalog from Phase 1.
- Apply deterministic filters (location, cuisine, rating, budget) in order.
- Produce a bounded shortlist suitable for LLM input.

This module is deliberately lightweight so it can be reused by a CLI, notebooks,
or the Phase 3 / Phase 4 orchestration.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd

from src.phase1.scraper import DEFAULT_CATALOG_PATH


class ShortlistReason(str, Enum):
    """High-level reason codes for empty / problematic outcomes."""

    OK = "OK"
    NO_LOCATION = "NO_LOCATION"
    NO_CUISINE_MATCH = "NO_CUISINE_MATCH"
    NO_RATING_MATCH = "NO_RATING_MATCH"
    NO_BUDGET_MATCH = "NO_BUDGET_MATCH"
    CATALOG_EMPTY = "CATALOG_EMPTY"


@dataclass
class UserPreferences:
    """
    Structured preferences aligned with the architecture document.

    - location: required city / locality string (matches against `city` or `address`).
    - budget_max_inr: optional numeric max approximate cost for two (filters by `cost_for_two`).
    - budget: optional legacy tier string ("low" | "medium" | "high") matched against `budget_tier`.
    - cuisine: single cuisine string.
    - min_rating: hard lower bound for rating.
    - extras: free-text hints forwarded to LLM; not used directly in filters here.
    """

    location: str
    cuisine: str
    min_rating: float = 0.0
    extras: str = ""
    budget_max_inr: Optional[float] = None
    budget: Optional[str] = None

    def normalized_location(self) -> str:
        return self.location.strip().title()

    def normalized_budget_tier(self) -> str:
        if not self.budget:
            return ""
        return self.budget.strip().lower()

    def normalized_cuisine(self) -> str:
        return self.cuisine.strip().lower()


@dataclass
class FilterResult:
    """
    Result of applying deterministic filters to the restaurant catalog.

    - shortlist: DataFrame of shortlisted venues, sorted for LLM input / UI.
    - reason: ShortlistReason summarizing why we might have zero rows.
    """

    shortlist: pd.DataFrame
    reason: ShortlistReason


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> pd.DataFrame:
    """
    Load the Phase 1 processed catalog (Parquet) into a DataFrame.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Processed catalog not found at {path}. "
            "Run Phase 1 ingestion first (src/phase1/scraper.py)."
        )
    df = pd.read_parquet(path)
    return df


def _apply_location_filter(df: pd.DataFrame, prefs: UserPreferences) -> Tuple[pd.DataFrame, bool]:
    loc_lower = prefs.location.strip().lower()
    if df.empty:
        return df, False
    city_mask = df["city"].astype(str).str.strip().str.lower() == loc_lower
    # `address` is treated as "locality" for dropdown purposes.
    if "address" in df.columns:
        addr_mask = df["address"].astype(str).str.strip().str.lower() == loc_lower
    else:
        addr_mask = False
    mask = city_mask | addr_mask
    filtered = df[mask]
    return filtered, not filtered.empty


def _apply_cuisine_filter(df: pd.DataFrame, prefs: UserPreferences) -> Tuple[pd.DataFrame, bool]:
    if df.empty:
        return df, False
    cuisine = prefs.normalized_cuisine()
    if not cuisine:
        return df, True

    def _has_cuisine(row_cuisines) -> bool:
        # Parquet round-trips can yield list, tuple, numpy array, or even a string.
        # Be careful: pd.isna(non-scalar) returns an array, which can't be used in boolean context.
        if row_cuisines is None:
            return False
        try:
            if pd.isna(row_cuisines):
                return False
        except Exception:
            # Non-scalar inputs (lists/arrays) aren't NA as a whole.
            pass
        if isinstance(row_cuisines, str):
            values = [row_cuisines]
        else:
            try:
                values = list(row_cuisines)
            except TypeError:
                values = [str(row_cuisines)]
        return any(cuisine in str(c).lower() for c in values)

    mask = df["cuisines"].apply(_has_cuisine)
    filtered = df[mask]
    return filtered, not filtered.empty


def _apply_rating_filter(df: pd.DataFrame, min_rating: float) -> Tuple[pd.DataFrame, bool]:
    if df.empty:
        return df, False
    filtered = df[df["rating"] >= float(min_rating)]
    if not filtered.empty:
        return filtered, True

    # Optional relax step: lower min_rating by 0.5 once if nothing matches.
    relaxed_min = max(0.0, float(min_rating) - 0.5)
    filtered_relaxed = df[df["rating"] >= relaxed_min]
    return filtered_relaxed, not filtered_relaxed.empty


def _apply_budget_filter(
    df: pd.DataFrame,
    *,
    budget_max_inr: Optional[float],
    budget_tier: Optional[str],
) -> Tuple[pd.DataFrame, bool]:
    if df.empty:
        return df, False
    if budget_max_inr is not None:
        try:
            max_inr = float(budget_max_inr)
        except (TypeError, ValueError):
            return df, True
        if "cost_for_two" not in df.columns:
            return df, True
        filtered = df[df["cost_for_two"].notna() & (df["cost_for_two"] <= max_inr)]
        return filtered, not filtered.empty

    if budget_tier:
        budget_norm = budget_tier.strip().lower()
        if not budget_norm:
            return df, True
        if "budget_tier" not in df.columns:
            return df, True
        filtered = df[df["budget_tier"].astype(str).str.lower() == budget_norm]
        return filtered, not filtered.empty

    # No budget provided => no-op.
    filtered = df
    return filtered, not filtered.empty


def filter_restaurants(
    catalog_df: pd.DataFrame,
    prefs: UserPreferences,
    max_shortlist_candidates: int = 40,
) -> FilterResult:
    """
    Deterministically filter the catalog according to the architecture pipeline:

    1. Location filter (required): exact/normalized match on city.
    2. Cuisine filter: at least one cuisine contains the requested cuisine.
    3. Rating filter: rating >= min_rating (with one relax step by -0.5).
    4. Budget filter: match numeric `cost_for_two` <= budget_max_inr (preferred),
       else fall back to legacy `budget_tier`.
    5. Ranking: sort by rating desc, then votes desc; cap to max_shortlist_candidates.
    """
    if catalog_df.empty:
        return FilterResult(shortlist=catalog_df, reason=ShortlistReason.CATALOG_EMPTY)

    # Location
    df_loc, ok_loc = _apply_location_filter(catalog_df, prefs)
    if not ok_loc:
        return FilterResult(shortlist=df_loc, reason=ShortlistReason.NO_LOCATION)

    # Cuisine
    df_cuisine, ok_cuisine = _apply_cuisine_filter(df_loc, prefs)
    if not ok_cuisine:
        return FilterResult(shortlist=df_cuisine, reason=ShortlistReason.NO_CUISINE_MATCH)

    # Rating
    df_rating, ok_rating = _apply_rating_filter(df_cuisine, prefs.min_rating)
    if not ok_rating:
        return FilterResult(shortlist=df_rating, reason=ShortlistReason.NO_RATING_MATCH)

    # Budget
    df_budget, ok_budget = _apply_budget_filter(
        df_rating,
        budget_max_inr=prefs.budget_max_inr,
        budget_tier=prefs.budget,
    )
    if not ok_budget:
        return FilterResult(shortlist=df_budget, reason=ShortlistReason.NO_BUDGET_MATCH)

    # Final shortlist ranking
    shortlist = df_budget.sort_values(
        by=["rating", "votes"],
        ascending=[False, False],
    ).head(max_shortlist_candidates)

    return FilterResult(shortlist=shortlist.reset_index(drop=True), reason=ShortlistReason.OK)


def main() -> None:
    """
    Simple manual test CLI:

    Run Phase 1 first, then:
        python src/phase2/retriever.py
    and follow the prompts.
    """
    catalog = load_catalog()
    print(f"Loaded catalog with {len(catalog)} rows.")

    location = input("Location (city, e.g. Bangalore): ").strip()
    budget_max_inr_str = input("Budget max INR for 2 (e.g. 800, optional): ").strip()
    cuisine = input("Cuisine (e.g. Italian): ").strip()
    min_rating_str = input("Minimum rating (e.g. 3.5): ").strip() or "0"

    try:
        min_rating = float(min_rating_str)
    except ValueError:
        min_rating = 0.0

    budget_max_inr: Optional[float] = None
    if budget_max_inr_str:
        try:
            budget_max_inr = float(budget_max_inr_str)
        except ValueError:
            budget_max_inr = None

    prefs = UserPreferences(
        location=location,
        cuisine=cuisine,
        min_rating=min_rating,
        budget_max_inr=budget_max_inr,
    )

    result = filter_restaurants(catalog, prefs)
    print(f"Filter reason: {result.reason}")
    print(f"Shortlist size: {len(result.shortlist)}")
    print(result.shortlist[["id", "name", "city", "cuisines", "rating", "budget_tier"]].head(10))


if __name__ == "__main__":
    main()

