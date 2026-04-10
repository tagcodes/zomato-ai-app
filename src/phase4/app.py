from __future__ import annotations

"""
Phase 4 — Backend API (FastAPI).

Implements the Phase 4 backend contract from docs/phase-wise-architecture.md:
- POST /api/v1/recommend
- Returns summary + ranked items + meta

Backend wires:
- Phase 1 catalog (data/processed/restaurants.parquet)
- Phase 2 deterministic filtering (shortlist)
- Phase 3 Groq call (rank + explanations)

Run locally (from repo root):
    .venv/bin/python -m uvicorn src.phase4.app:app --reload
"""

import json
import os
import time
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi import HTTPException
from pydantic import BaseModel, Field

from groq import Groq

from src.phase1.scraper import DEFAULT_CATALOG_PATH
from src.phase2.retriever import FilterResult, ShortlistReason, UserPreferences, filter_restaurants, load_catalog


PROMPT_VERSION = "v1"
DEFAULT_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
DEFAULT_LLM_TIMEOUT_S = float(os.getenv("GROQ_TIMEOUT_S", "20"))
MAX_SHORTLIST_ROWS_FOR_LLM = int(os.getenv("MAX_SHORTLIST_ROWS_FOR_LLM", "40"))


class RecommendRequest(BaseModel):
    location: str = Field(..., examples=["Bangalore"])
    cuisine: str = Field(..., examples=["Italian"])
    min_rating: float = Field(0.0, ge=0.0, le=5.0, examples=[3.5])
    extras: str = Field("", examples=["family-friendly, quick service"])
    budget_max_inr: Optional[float] = Field(
        None,
        ge=0.0,
        description="Numeric budget_max_inr (max approximate cost for two in INR). Preferred over legacy `budget`.",
        examples=[800.0],
    )
    # Legacy compatibility: supports low|medium|high from older UI/tests.
    budget: Optional[str] = Field(None, description="Legacy budget_tier: low | medium | high", examples=["medium"])


class RecommendItem(BaseModel):
    id: str
    name: str
    cuisines: List[str]
    rating: float
    estimated_cost: Optional[str] = None  # budget tier
    cost_display: Optional[str] = None
    explanation: str
    rank: int


class RecommendMeta(BaseModel):
    shortlist_size: int
    model: str
    prompt_version: str
    reason: Optional[str] = None


class RecommendResponse(BaseModel):
    summary: str
    items: List[RecommendItem]
    meta: RecommendMeta


_SAMPLE_RESTAURANTS: List[Dict[str, Any]] = [
    {
        "id": "sample-1",
        "name": "Indigo Spice",
        "city": "Bangalore",
        "cuisines": ["Chinese"],
        "rating": 4.6,
        "cost_for_two": 900,
        "budget_tier": "medium",
        "votes": 1200,
        "address": "MG Road",
        "raw_features": "family-friendly, quick service",
    },
    {
        "id": "sample-2",
        "name": "The Urban Noodle House",
        "city": "Bangalore",
        "cuisines": ["Chinese", "Thai"],
        "rating": 4.4,
        "cost_for_two": 650,
        "budget_tier": "medium",
        "votes": 820,
        "address": "Jayanagar",
        "raw_features": "good for groups, fast delivery",
    },
    {
        "id": "sample-3",
        "name": "Golden Wok Cafe",
        "city": "Bangalore",
        "cuisines": ["Chinese"],
        "rating": 4.2,
        "cost_for_two": 420,
        "budget_tier": "low",
        "votes": 430,
        "address": "Koramangala",
        "raw_features": "budget-friendly, casual seating",
    },
    {
        "id": "sample-4",
        "name": "Saffron & Soy",
        "city": "Bangalore",
        "cuisines": ["Indian", "Chinese"],
        "rating": 4.7,
        "cost_for_two": 1800,
        "budget_tier": "high",
        "votes": 2100,
        "address": "Indiranagar",
        "raw_features": "premium ambiance, excellent flavors",
    },
    {
        "id": "sample-5",
        "name": "Bamboo Leaf Kitchen",
        "city": "Bangalore",
        "cuisines": ["Chinese", "Vietnamese"],
        "rating": 4.3,
        "cost_for_two": 1100,
        "budget_tier": "medium",
        "votes": 650,
        "address": "HSR Layout",
        "raw_features": "family-friendly, clean and cozy",
    },
    {
        "id": "sample-6",
        "name": "Chopsticks Corner",
        "city": "Bangalore",
        "cuisines": ["Chinese"],
        "rating": 4.1,
        "cost_for_two": 520,
        "budget_tier": "medium",
        "votes": 520,
        "address": "Banashankari",
        "raw_features": "quick service, good portion sizes",
    },
    {
        "id": "sample-7",
        "name": "Wok & Smile",
        "city": "Bangalore",
        "cuisines": ["Chinese"],
        "rating": 4.5,
        "cost_for_two": 1400,
        "budget_tier": "high",
        "votes": 980,
        "address": "Electronic City",
        "raw_features": "date-friendly, flavorful dishes",
    },
    {
        "id": "sample-8",
        "name": "SpiceRoute Noodles",
        "city": "Bangalore",
        "cuisines": ["Chinese", "Japanese"],
        "rating": 4.0,
        "cost_for_two": 300,
        "budget_tier": "low",
        "votes": 210,
        "address": "South Bangalore",
        "raw_features": "budget meals, casual vibe",
    },
]


def _sample_restaurants_df() -> pd.DataFrame:
    # Parity with the Phase 1 canonical schema fields we use in Phase 2/3/4.
    df = pd.DataFrame(_SAMPLE_RESTAURANTS)
    df["cuisines"] = df["cuisines"].apply(lambda x: x if isinstance(x, list) else [str(x)])
    return df


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_env() -> None:
    load_dotenv(dotenv_path=_project_root() / ".env", override=False)


def _get_groq_client() -> Groq:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not set. Put it in .env.")
    # Groq SDK uses httpx under the hood; passing timeout keeps requests bounded.
    try:
        return Groq(api_key=api_key, timeout=DEFAULT_LLM_TIMEOUT_S)
    except TypeError:
        # Older SDK versions may not support timeout on init.
        return Groq(api_key=api_key)


def _shortlist_to_prompt_rows(shortlist: pd.DataFrame, max_rows: int = MAX_SHORTLIST_ROWS_FOR_LLM) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for _, r in shortlist.head(max_rows).iterrows():
        cuisines_val = r.get("cuisines", [])
        if cuisines_val is None or (isinstance(cuisines_val, float) and pd.isna(cuisines_val)):
            cuisines_list: List[str] = []
        elif isinstance(cuisines_val, str):
            cuisines_list = [cuisines_val]
        else:
            try:
                cuisines_list = list(cuisines_val)
            except TypeError:
                cuisines_list = [str(cuisines_val)]

        rows.append(
            {
                "restaurant_id": str(r.get("id", "")),
                "name": str(r.get("name", "")),
                "city": str(r.get("city", "")),
                "cuisines": cuisines_list,
                "rating": float(r.get("rating", 0.0) or 0.0),
                "budget_tier": (None if pd.isna(r.get("budget_tier")) else r.get("budget_tier")),
                "cost_for_two": (None if pd.isna(r.get("cost_for_two")) else r.get("cost_for_two")),
                "votes": int(r.get("votes", 0) or 0),
            }
        )
    return rows


def _render_prompt(prefs: RecommendRequest, shortlist_rows: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, str]]:
    prefs_summary = {
        "location": prefs.location,
        "budget_max_inr": prefs.budget_max_inr,
        "budget_tier": prefs.budget,
        "cuisine": prefs.cuisine,
        "min_rating": prefs.min_rating,
        "extras": prefs.extras,
        "top_k": top_k,
    }
    return [
        {
            "role": "system",
            "content": (
                "You are an expert restaurant recommender. "
                "You MUST only recommend restaurants from the provided shortlist and reference them by restaurant_id. "
                "Respect budget_max_inr/budget_tier, cuisine, and min_rating. "
                "Return JSON only with keys: summary, recommendations."
            ),
        },
        {
            "role": "user",
            "content": (
                "Preferences:\n"
                f"{json.dumps(prefs_summary, ensure_ascii=False)}\n\n"
                "Shortlist (use only these):\n"
                f"{json.dumps(shortlist_rows, ensure_ascii=False)}\n\n"
                "Return JSON in this exact shape:\n"
                "{\n"
                '  "summary": "string",\n'
                '  "recommendations": [\n'
                "    {\n"
                '      "restaurant_id": "string",\n'
                '      "rank": 1,\n'
                '      "explanation": "string"\n'
                "    }\n"
                "  ]\n"
                "}\n"
            ),
        },
    ]


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """
    Parse LLM output as JSON. Raises on failure.
    """
    return json.loads(text)


def _call_groq_ranker(
    *,
    client: Groq,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int = 700,
    temperature: float = 0.2,
) -> Dict[str, Any]:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=DEFAULT_LLM_TIMEOUT_S,
        )
    except TypeError:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    content = (resp.choices[0].message.content or "").strip()
    try:
        return _parse_llm_json(content)
    except Exception:
        # One repair attempt: remind JSON-only.
        repair_messages = messages + [
            {"role": "assistant", "content": content},
            {"role": "user", "content": "Your last response was not valid JSON. Return JSON only, no markdown."},
        ]
        try:
            resp2 = client.chat.completions.create(
                model=model,
                messages=repair_messages,
                temperature=0.0,
                max_tokens=max_tokens,
                timeout=DEFAULT_LLM_TIMEOUT_S,
            )
        except TypeError:
            resp2 = client.chat.completions.create(
                model=model,
                messages=repair_messages,
                temperature=0.0,
                max_tokens=max_tokens,
            )
        content2 = (resp2.choices[0].message.content or "").strip()
        return _parse_llm_json(content2)


def _merge_llm_with_catalog(
    *,
    shortlist_df: pd.DataFrame,
    llm_payload: Dict[str, Any],
    top_k: int = 5,
) -> RecommendResponse:
    summary = str(llm_payload.get("summary", "")).strip()
    recs = llm_payload.get("recommendations") or []
    if not isinstance(recs, list):
        recs = []

    by_id = {str(r["id"]): r for _, r in shortlist_df.iterrows()}

    items: List[RecommendItem] = []
    for rec in recs[:top_k]:
        rid = str(rec.get("restaurant_id", "")).strip()
        if not rid or rid not in by_id:
            continue
        row = by_id[rid]

        cost_for_two = row.get("cost_for_two")
        cost_display = None
        if cost_for_two is not None and not pd.isna(cost_for_two):
            try:
                cost_display = f"₹{int(float(cost_for_two))} for two"
            except Exception:
                cost_display = None

        cuisines_val = row.get("cuisines", [])
        if cuisines_val is None or (isinstance(cuisines_val, float) and pd.isna(cuisines_val)):
            cuisines_list: List[str] = []
        elif isinstance(cuisines_val, str):
            cuisines_list = [cuisines_val]
        else:
            try:
                cuisines_list = list(cuisines_val)
            except TypeError:
                cuisines_list = [str(cuisines_val)]

        items.append(
            RecommendItem(
                id=str(row.get("id", "")),
                name=str(row.get("name", "")),
                cuisines=cuisines_list,
                rating=float(row.get("rating", 0.0) or 0.0),
                estimated_cost=(None if pd.isna(row.get("budget_tier")) else row.get("budget_tier")),
                cost_display=cost_display,
                explanation=str(rec.get("explanation", "")).strip(),
                rank=int(rec.get("rank", len(items) + 1) or (len(items) + 1)),
            )
        )

    # If model returned nothing usable, fall back to heuristic shortlist order.
    if not items:
        fallback = shortlist_df.sort_values(by=["rating", "votes"], ascending=[False, False]).head(top_k)
        for i, (_, row) in enumerate(fallback.iterrows(), start=1):
            cost_for_two = row.get("cost_for_two")
            cost_display = None
            if cost_for_two is not None and not pd.isna(cost_for_two):
                try:
                    cost_display = f"₹{int(float(cost_for_two))} for two"
                except Exception:
                    cost_display = None
            cuisines_val = row.get("cuisines", [])
            if cuisines_val is None or (isinstance(cuisines_val, float) and pd.isna(cuisines_val)):
                cuisines_list: List[str] = []
            elif isinstance(cuisines_val, str):
                cuisines_list = [cuisines_val]
            else:
                try:
                    cuisines_list = list(cuisines_val)
                except TypeError:
                    cuisines_list = [str(cuisines_val)]

            items.append(
                RecommendItem(
                    id=str(row.get("id", "")),
                    name=str(row.get("name", "")),
                    cuisines=cuisines_list,
                    rating=float(row.get("rating", 0.0) or 0.0),
                    estimated_cost=(None if pd.isna(row.get("budget_tier")) else row.get("budget_tier")),
                    cost_display=cost_display,
                    explanation="Recommended based on your preferences and high rating.",
                    rank=i,
                )
            )
        if not summary:
            summary = "Here are a few good matches based on your preferences."

    return RecommendResponse(
        summary=summary or "Here are recommendations based on your preferences.",
        items=items,
        meta=RecommendMeta(shortlist_size=int(len(shortlist_df)), model=DEFAULT_MODEL, prompt_version=PROMPT_VERSION),
    )


def create_app() -> FastAPI:
    _load_env()
    app = FastAPI(title="Restaurant Recommendation API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    web_dir = _project_root() / "web"
    static_dir = web_dir / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Load catalog once at startup
    @app.on_event("startup")
    def _startup() -> None:
        app.state.catalog = load_catalog(DEFAULT_CATALOG_PATH)
        app.state.groq_client = _get_groq_client()

    @app.get("/")
    def home() -> FileResponse:
        """
        Serve the basic UI for end-to-end testing.
        """
        index_path = web_dir / "index.html"
        return FileResponse(str(index_path))

    @app.get("/health")
    def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/locations")
    def locations() -> Dict[str, List[str]]:
        """
        Distinct catalog cities for the UI.
        """
        catalog_df: pd.DataFrame = app.state.catalog
        if "city" not in catalog_df.columns:
            return {"locations": []}
        locs = (
            catalog_df["city"]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        return {"locations": sorted(locs, key=lambda s: s.lower())}

    @app.get("/api/v1/localities")
    def localities(city: Optional[str] = None) -> Dict[str, List[str]]:
        """
        Distinct catalog localities for the UI.
        Implementation: treat `address` as locality.
        """
        catalog_df: pd.DataFrame = app.state.catalog
        if "address" not in catalog_df.columns:
            return {"localities": []}

        df = catalog_df
        if city:
            city_lower = city.strip().lower()
            if "city" in df.columns:
                df = df[df["city"].astype(str).str.strip().str.lower() == city_lower]

        locs = (
            df["address"]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .unique()
            .tolist()
        )
        return {"localities": sorted(locs, key=lambda s: s.lower())}

    @app.post("/api/v1/recommend", response_model=RecommendResponse)
    def recommend(req: RecommendRequest) -> RecommendResponse:
        t0 = time.time()

        prefs = UserPreferences(
            location=req.location,
            cuisine=req.cuisine,
            min_rating=req.min_rating,
            extras=req.extras,
            budget_max_inr=req.budget_max_inr,
            budget=req.budget,
        )

        catalog_df: pd.DataFrame = app.state.catalog
        filter_result: FilterResult = filter_restaurants(catalog_df, prefs)
        shortlist_df = filter_result.shortlist
        used_sample = False

        # If deterministic filtering yields nothing, fall back to predefined sample
        # restaurants so the UI always has something to show (and we still call the LLM).
        if shortlist_df.empty:
            print("Using fallback sample data")
            shortlist_df = _sample_restaurants_df()
            used_sample = True

        shortlist_rows = _shortlist_to_prompt_rows(shortlist_df)
        messages = _render_prompt(req, shortlist_rows, top_k=5)

        def _llm_call() -> Dict[str, Any]:
            return _call_groq_ranker(
                client=app.state.groq_client,
                model=DEFAULT_MODEL,
                messages=messages,
                max_tokens=450,
                temperature=0.2,
            )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_llm_call)
                llm_payload = fut.result(timeout=DEFAULT_LLM_TIMEOUT_S)
        except Exception:
            llm_payload = {"summary": "", "recommendations": []}

        response = _merge_llm_with_catalog(shortlist_df=shortlist_df, llm_payload=llm_payload, top_k=5)
        response.meta.reason = "SAMPLE_FALLBACK" if used_sample else filter_result.reason.value

        # tiny timing hook (kept in meta-free; can be logged later)
        _ = time.time() - t0
        return response

    return app


app = create_app()

