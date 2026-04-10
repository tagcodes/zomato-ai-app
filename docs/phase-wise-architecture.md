Phase-Wise Architecture: AI-Powered Restaurant Recommendation System
This document expands the build plan for the Zomato-style recommendation service described in problemStatement.md. Each phase lists objectives, components, interfaces, data artifacts, and exit criteria.

System context
Purpose: Combine a real restaurant dataset with user preferences and an LLM to produce ranked recommendations with natural-language explanations.
High-level flow:
Offline or on-demand: load and normalize restaurant records.
Online: accept preferences → filter catalog to a shortlist → prompt Groq (Phase 3) → return structured UI payload.
Non-goals (unless you add them later): user accounts, live Zomato scraping, training custom embedding models.

Phase 1 — Foundation, dataset contract, and catalog
1.1 Objectives
Establish a single source of truth for restaurant data after Hugging Face ingest.
Define a canonical schema so filtering, prompting, and UI do not depend on raw column names.
Make ingestion repeatable (same command → same artifact).
1.2 Dataset source
Primary: ManikaSaini/zomato-restaurant-recommendation via datasets library or export script.
1.3 Canonical schema (recommended fields)
Map HF columns to internal names (exact mapping depends on dataset columns; validate after first load):
Internal field
Role
id
Stable string or hash (if missing, derive from name+location)
name
Restaurant name
location / city
For location filter (normalize: trim, title case, alias map e.g. "Bengaluru" → "Bangalore" if needed)
cuisines
List of strings or single pipe/comma-separated field parsed to list
rating
Float 0–5 (or dataset scale; document and normalize)
cost_for_two or approx_cost
Numeric or categorical; derive budget_tier: low | medium | high
votes / review_count
Optional; use for tie-breaking in shortlist
address or locality
Optional; richer prompts and UI
raw_features
Optional blob for “family-friendly” style hints if present in text columns

1.4 Components
Component
Responsibility
Ingestion script
Download/load split, select columns, rename to canonical schema
Validators
Row-level checks (rating range, required name/location), quarantine or drop bad rows with counts logged
Transformers
Parse cuisines, normalize city, compute budget_tier from rules (e.g. quantiles or fixed thresholds)
Catalog store
Versioned file: Parquet (preferred), SQLite, or JSON Lines for small prototypes

Implementation lives under restaurant_rec.phase1 (ingest, transform, validate, schema) and scripts/ingest_zomato.py.
1.5 Artifacts and layout (suggested)
data/
  raw/              # optional: snapshot of downloaded slice
  processed/
    restaurants.parquet   # or restaurants.db
scripts/
  ingest_zomato.py   # or notebooks/01_ingest.ipynb for exploration-only phase
src/restaurant_rec/
  config.py          # shared: AppConfig, paths, dataset + filter tuning
  phase1/            # catalog ingest + schema
  phase2/            # preferences, load catalog, deterministic filter
  phase3/            # Groq prompts, JSON parse, `recommend()` orchestration

1.6 Configuration
Path to catalog file, encoding, and threshold constants (rating scale, budget cutoffs) in config.yaml or environment variables.
1.7 Exit criteria
Documented schema with example row (JSON).
One command reproduces processed/restaurants.* from HF.
Documented row counts before/after cleaning and top reasons for drops.

Phase 2 — Preference model and deterministic filtering
2.1 Objectives
Convert user input into a typed preference object.
Produce a bounded shortlist (e.g. 20–50 venues) that is small enough for one LLM call but diverse enough to rank.
2.2 Preference model (API / domain)
Structured input (align with problem statement):
Field
Type
Notes
location
string
Required for first version; fuzzy match optional later
budget
enum
low | medium | high
cuisine
string or list
Match against cuisines (substring or token match)
min_rating
float
Hard filter: rating >= min_rating
extras
string (optional)
Free text: “family-friendly”, “quick service”; used in LLM prompt and optional keyword boost

Optional extensions: max_results_shortlist, dietary, neighborhood.
2.3 Filtering pipeline (order matters)
Location filter: Exact or normalized match on city / location.
Cuisine filter: At least one cuisine matches user selection (case-insensitive).
Rating filter: rating >= min_rating; if too few results, optional relax step (document policy: e.g. lower min by 0.5 once).
Budget filter: Match budget_tier to user budget.
Ranking for shortlist: Sort by rating desc, then votes desc; take top N.
2.4 Component boundaries
Module (package path)
Responsibility
restaurant_rec.phase2.preferences
Pydantic validation, defaults (UserPreferences)
restaurant_rec.phase2.filter
filter_restaurants(catalog_df, prefs) -> FilterResult
restaurant_rec.phase2.catalog_loader
Load Parquet into a DataFrame at startup

2.5 Edge cases
Zero matches: Return empty shortlist with reason codes (NO_LOCATION, NO_CUISINE, etc.) for UI messaging.
Missing rating/cost: Exclude from strict filters or treat as unknown with explicit rules in docs.
2.6 Exit criteria
Unit tests for filter combinations and empty results.
Shortlist size and latency predictable (log timing for 100k rows if applicable).

Phase 3 — LLM integration: prompt contract and orchestration
Phase 3 uses Groq (GroqCloud / Groq API) as the LLM for ranking, explanations, and optional summaries. The Groq API key is loaded from a .env file (see §3.6); never commit real keys to version control.
3.1 Objectives
Given preferences + shortlist JSON, produce ordered recommendations with per-item explanations and optional overall summary.
Keep behavior testable (template version, structured output where possible).
Call Groq over HTTP with the official Groq Python SDK or OpenAI-compatible client pointed at Groq’s base URL, using credentials supplied via environment variables populated from .env.
3.2 Inputs to the LLM
System message: Role (expert recommender), constraints (only recommend from provided list; respect min rating and budget; if list empty, say so).
User message: Serialized shortlist (compact JSON or markdown table) + preference summary + extras text.
3.3 Output contract
Preferred: JSON from the model (with schema validation and repair retry):
{
  "summary": "string",
  "recommendations": [
    {
      "restaurant_id": "string",
      "rank": 1,
      "explanation": "string"
    }
  ]
}

Fallback: parse markdown numbered list if JSON fails; log and degrade gracefully.
3.4 Prompt engineering checklist
Include only restaurants from the shortlist (by id) to reduce hallucination.
Ask for top K (e.g. 5) with one paragraph max per explanation.
Instruct to cite concrete attributes (cuisine, rating, cost) from the data.
3.5 Orchestration service
Step
Action
1
Build shortlist (Phase 2)
2
If empty, return structured empty response (skip LLM or single small call explaining no matches)
3
Render prompt from template + data
4
Call Groq API with timeout and max tokens
5
Parse/validate response; on failure, retry once with “JSON only” reminder or fall back to heuristic order

3.6 Configuration
API key (Groq): Keep the Groq API key in a .env file in the project root (or the directory the app loads env from). Use python-dotenv or your framework’s equivalent so values are available as environment variables at runtime. Add .env to .gitignore and commit only a .env.example (or README snippet) listing required variable names with empty or placeholder values.
Typical variable name: GROQ_API_KEY (confirm against Groq API documentation when implementing).
Non-secret settings: Model id (e.g. Groq-hosted model name), temperature (low for consistency), max_tokens, and display top_k can live in config.yaml or additional env vars as needed.
3.7 Exit criteria
Golden-file or manual eval sheet for ~10 preference profiles.
Documented latency and token usage for typical shortlist sizes.

Phase 4 — Application layer: API and presentation
4.1 Objectives
Expose a single recommendation endpoint (or CLI) that returns everything the UI needs.
Render Restaurant Name, Cuisine, Rating, Estimated Cost, AI explanation per row.
4.2 Backend API (recommended shape)
POST /api/v1/recommend
Request body: JSON matching Preferences (Phase 2).
Response body:
{
  "summary": "string",
  "items": [
    {
      "id": "string",
      "name": "string",
      "cuisines": ["string"],
      "rating": 4.2,
      "estimated_cost": "medium",
      "cost_display": "₹800 for two",
      "explanation": "string",
      "rank": 1
    }
  ],
  "meta": {
    "shortlist_size": 35,
    "model": "string",
    "prompt_version": "v1"
  }
}

Implementation note: Merge LLM output with catalog rows by restaurant_id to fill cuisine, rating, and cost for display (do not trust the LLM for numeric facts).
Backend (implemented): restaurant_rec.phase4.app — FastAPI app with CORS enabled. Run from repo root after pip install -e .:
uvicorn restaurant_rec.phase4.app:app --reload
Open http://127.0.0.1:8000/ for the browser UI (web/). Interactive API: http://127.0.0.1:8000/docs.
Loads config.yaml and paths.processed_catalog at startup; GROQ_API_KEY from .env applies to recommend calls.

Implementation plan (this repo):
- Backend first: implement FastAPI backend + run 2–3 smoke tests for /health and /api/v1/recommend.
- Frontend next: implement the web UI after backend contract is stable (update §4.3 when starting UI work).
4.3 UI — basic web app (end-to-end)
web/ holds a small static app (index.html, styles.css, app.js) served at / and /static/*. It posts to POST /api/v1/recommend on the same origin.
Option
Status / use when
Web app
Basic — form + result cards + meta; easy to extend later
Backend API
Current — JSON as in §4.2
CLI
Optional; curl or /docs
Notebook
Teaching/demo only

4.4 Cross-cutting concerns
CORS if SPA on different origin.
Rate limiting if exposed publicly.
Input validation return 422 with field errors.
4.5 Exit criteria
Backend: POST /api/v1/recommend returns structured summary, items, and meta; validation errors return 422; if deterministic filters yield no matches, the API falls back to a small built-in sample shortlist (so the UI still shows recommendations), with `meta.reason="SAMPLE_FALLBACK"`.
Browser: user opens /, submits preferences → sees summary and ranked cards (or empty-state message).
Empty and error states copy-reviewed for clarity.

Improvements (tracked)
The following were implemented in code, API, UI, and phase-wise-architecture.md:
Locality dropdown — Added `GET /api/v1/locations` and `GET /api/v1/localities` (treating catalog `address` as locality). The web UI now has `city` + `locality` selects and sends `location` as either the chosen locality (`address`) or the city. Phase 2 matches `location` against both `city` and `address`.
Numeric budget — The recommend request uses `budget_max_inr` (numeric max approximate cost for two). Phase 2 filters by `cost_for_two <= budget_max_inr` (with legacy `budget` tier still accepted). Groq prompts describe `budget_max_inr`/`budget_tier` accordingly.
Fixed shortlist size — No user input for max shortlist size. Deterministic filtering caps candidates (default 40) and the LLM receives a capped prompt shortlist (`MAX_SHORTLIST_ROWS_FOR_LLM`, default 40).

Phase 5 — Hardening, observability, and quality
5.1 Objectives
Improve reliability, debuggability, and iterative prompt/dataset updates without breaking clients.
5.2 Caching
Key: hash of (preferences, shortlist content hash, prompt_version, model).
TTL or LRU for repeated queries in demos.
5.3 Logging and metrics
Structured logs: shortlist_size, duration_filter_ms, duration_llm_ms, outcome (success / empty / error).
Avoid logging full prompts if they contain sensitive data; truncate or redact.
5.4 Testing strategy
Layer
Tests
Filter
Unit tests, property tests optional
Prompt
Snapshot of rendered template with fixture data
API
Contract tests for /recommend
LLM
Marked optional integration tests with recorded responses

5.5 Deployment
The system is designed for a decoupled deployment strategy, separating the AI-powered backend from the high-fidelity user interface.

- **Backend**: Deployed on **Streamlit** (Streamlit Cloud).
- **Frontend**: Deployed on **Vercel**.

5.6 Exit criteria
Runbook: how to refresh data, bump prompt version, rotate API keys.
Basic load/latency note for expected concurrency.

Phase 6 — Deployment Details

6.1 Backend Deployment (Streamlit)
The backend service (FastAPI) will be deployed using **Streamlit Cloud**. This provides a managed Python environment that can host the recommendation logic and API endpoints.

- **Source**: `src/phase4/app.py`
- **Environment**: Streamlit Cloud (Python 3.11+)
- **Secrets**: `GROQ_API_KEY` and other sensitive variables will be configured in the Streamlit secrets management dashboard.
- **Data Persistence**: The processed restaurant catalog (`data/processed/restaurants.parquet`) will be bundled with the deployment.

6.2 Frontend Deployment (Vercel)
The high-fidelity mobile-first frontend (Next.js) will be deployed on **Vercel**. This ensures high performance and seamless integration with the Next.js framework.

- **Source**: `frontend/` (Next.js 15)
- **Environment**: Vercel Managed Infrastructure
- **Base URL**: The frontend will interact with the backend API hosted on Streamlit Cloud via the `NEXT_PUBLIC_API_URL` environment variable.
- **Continuous Integration**: Every push to the main branch will trigger an automatic build and deployment on Vercel.


Dependency graph between phases
Phase 1 (Catalog)
    │
    ▼
Phase 2 (Filter + Preferences)
    │
    ▼
Phase 3 (LLM orchestration)
    │
    ▼
Phase 4 (API + UI)
    │
    ▼
Phase 5 (Hardening)
    │
    ▼
Phase 6 (Deployment)


Phases 2–3 can be prototyped in a notebook before extraction into modules; Phase 4 should consume stable interfaces from 2 and 3.

Technology stack (suggestion, not mandatory)
Concern | Suggested default
--- | ---
Language | Python 3.11+
Data | pandas or polars + Parquet
Validation | Pydantic v2
API | FastAPI
LLM | Groq via Groq API; key in .env → env (e.g. GROQ_API_KEY)
Backend Host | Streamlit Cloud
Frontend Host | Vercel (Next.js)

Adjust to your course constraints; the phase boundaries stay the same.

Traceability to problem statement
Problem statement item
Phase
Load HF Zomato dataset, extract fields
1
User preferences (location, budget_max_inr, cuisine, rating, extras)
2, 4
Filter + prepare data for LLM
2, 3
Prompt for reasoning and ranking
3
LLM rank + explanations + summary
3
Display name, cuisine, rating, cost, explanation
4


Document version: 1.8 — web-next/ Next.js + Tailwind UI from design/ mock; dual frontend (web/ + web-next/) documented in §4.3.

