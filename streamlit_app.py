import streamlit as st
import pandas as pd
import os
import json
import time
import concurrent.futures
from pathlib import Path
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from groq import Groq

# Import core logic from existing src
from src.phase1.scraper import DEFAULT_CATALOG_PATH
from src.phase2.retriever import UserPreferences, filter_restaurants, load_catalog, ShortlistReason

# --- Page Config ---
st.set_page_config(
    page_title="Zomato AI - Restaurant Recommender",
    page_icon="🍴",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Styling ---
st.markdown("""
    <style>
    .main {
        background-color: #f8f9fa;
    }
    .stButton>button {
        background-color: #E23744;
        color: white;
        border-radius: 8px;
        height: 3em;
        width: 100%;
        font-weight: bold;
    }
    .stButton>button:hover {
        background-color: #d12e3a;
        color: white;
    }
    .restaurant-card {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        margin-bottom: 20px;
        border-left: 5px solid #E23744;
    }
    .rating-badge {
        background-color: #24963F;
        color: white;
        padding: 2px 8px;
        border-radius: 4px;
        font-weight: bold;
    }
    .cuisine-tag {
        background-color: #EDF1F7;
        color: #4A5568;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.8em;
        margin-right: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- Logic Layer ---

def load_env():
    project_root = Path(__file__).resolve().parent
    dotenv_path = project_root / ".env"
    load_dotenv(dotenv_path=dotenv_path, override=False)

def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    # In Streamlit Cloud, we can also use st.secrets
    if not api_key:
        api_key = st.secrets.get("GROQ_API_KEY")
    
    if not api_key:
        return None
    return Groq(api_key=api_key)

def get_recommendation_ui(id, name, rating, cuisines, cost, explanation, rank):
    with st.container():
        st.markdown(f"""
            <div class="restaurant-card">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <h3 style="margin: 0; color: #1C1C1C;">{rank}. {name}</h3>
                    <span class="rating-badge">{rating} ★</span>
                </div>
                <div style="margin: 10px 0;">
                    {"".join([f'<span class="cuisine-tag">{c}</span>' for c in cuisines])}
                </div>
                <p style="color: #666; font-size: 0.9em;">{cost}</p>
                <div style="background-color: #FFF5F6; padding: 10px; border-radius: 8px; border: 1px dashed #E23744;">
                    <p style="margin: 0; color: #1C1C1C; font-style: italic;">"{explanation}"</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

# --- Refactored Phase 4 Helpers ---
# We keep these private and close to the streamlit app for simplicity

def _shortlist_to_prompt_rows(shortlist: pd.DataFrame, max_rows: int = 40) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for _, r in shortlist.head(max_rows).iterrows():
        cuisines_val = r.get("cuisines", [])
        if not isinstance(cuisines_val, list):
            cuisines_val = [str(cuisines_val)]
        rows.append({
            "restaurant_id": str(r.get("id", "")),
            "name": str(r.get("name", "")),
            "city": str(r.get("city", "")),
            "cuisines": cuisines_val,
            "rating": float(r.get("rating", 0.0) or 0.0),
            "budget_tier": (None if pd.isna(r.get("budget_tier")) else r.get("budget_tier")),
            "cost_for_two": (None if pd.isna(r.get("cost_for_two")) else r.get("cost_for_two")),
            "votes": int(r.get("votes", 0) or 0),
        })
    return rows

def _render_prompt(prefs: UserPreferences, shortlist_rows: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, str]]:
    prefs_summary = {
        "location": prefs.location,
        "cuisine": prefs.cuisine,
        "min_rating": prefs.min_rating,
        "extras": prefs.extras,
        "top_k": top_k,
    }
    return [
        {"role": "system", "content": "You are an expert restaurant recommender. Return JSON only with keys: summary, recommendations. recommendations should be a list of {restaurant_id, rank, explanation}."},
        {"role": "user", "content": f"Preferences: {json.dumps(prefs_summary)}\n\nShortlist: {json.dumps(shortlist_rows)}"}
    ]

def _call_groq(client, messages, model):
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        st.warning(f"LLM call failed: {e}")
        return {"summary": "Ranking fallback.", "recommendations": []}

# --- Main App ---

def main():
    load_env()
    
    # Sidebar
    st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/b/bd/Zomato_Logo.svg", width=150)
    st.sidebar.title("Settings")
    model = st.sidebar.selectbox("Groq Model", ["llama-3.1-8b-instant", "llama3-70b-8192", "mixtral-8x7b-32768"], index=0)
    
    st.image("https://upload.wikimedia.org/wikipedia/commons/b/bd/Zomato_Logo.svg", width=120)
    st.title("Zomato AI")
    st.markdown("### Find the perfect spot to eat, powered by AI.")

    # Load data
    try:
        catalog = load_catalog(DEFAULT_CATALOG_PATH)
    except Exception as e:
        st.error(f"Failed to load catalog: {e}")
        return

    # User Inputs
    col1, col2 = st.columns(2)
    
    with col1:
        cities = sorted(catalog["city"].unique().tolist())
        location = st.selectbox("Where are you?", [""] + cities)
        
        cuisine = st.text_input("What are you craving? (e.g. Italian, North Indian)", placeholder="Cuisine...")
    
    with col2:
        budget_max = st.slider("Max Budget for Two (INR)", 100, 5000, 1000, 100)
        min_rating = st.slider("Minimum Rating", 0.0, 5.0, 3.5, 0.1)

    extras = st.text_area("Anything else? (e.g. kid-friendly, outdoor seating, live music)", placeholder="Special requests...")

    if st.button("Discover Restaurants"):
        if not location:
            st.warning("Please select a location!")
            return

        prefs = UserPreferences(
            location=location,
            cuisine=cuisine,
            min_rating=min_rating,
            budget_max_inr=budget_max,
            extras=extras
        )

        with st.spinner("AI is curating your shortlist..."):
            filter_result = filter_restaurants(catalog, prefs)
            shortlist = filter_result.shortlist

            if shortlist.empty:
                st.info("No perfect matches found. Try relaxing your filters!")
                return

            st.success(f"Found {len(shortlist)} matches. AI is ranking them for you...")
            
            # Groq Ranking
            client = get_groq_client()
            if not client:
                st.error("GROQ_API_KEY not found. Please set it in .env or Streamlit Secrets.")
                # Show top 3 from shortlist as fallback
                recs_df = shortlist.sort_values(by="rating", ascending=False).head(3)
                st.markdown("### Top Recommendations (Fallback - No AI Ranking)")
                for i, (_, row) in enumerate(recs_df.iterrows(), 1):
                    get_recommendation_ui(
                        row["id"], 
                        row["name"], 
                        row["rating"], 
                        row["cuisines"], 
                        f"₹{row['cost_for_two']} for two", 
                        "Highly rated in your area.", 
                        i
                    )
                return

            # Call Groq
            rows = _shortlist_to_prompt_rows(shortlist)
            messages = _render_prompt(prefs, rows)
            llm_payload = _call_groq(client, messages, model)
            
            summary = llm_payload.get("summary", "Here are the best matches for you.")
            st.markdown(f"#### {summary}")

            recs = llm_payload.get("recommendations", [])
            by_id = {str(r["id"]): r for _, r in shortlist.iterrows()}
            
            if not recs:
                # Fallback to pure shortlist
                recs = [{"restaurant_id": str(r["id"]), "rank": i+1, "explanation": "Recommended based on your preferences."} for i, (_, r) in enumerate(shortlist.head(3).iterrows())]

            for rec in recs[:5]:
                rid = str(rec.get("restaurant_id"))
                if rid in by_id:
                    row = by_id[rid]
                    get_recommendation_ui(
                        row["id"],
                        row["name"],
                        row["rating"],
                        row["cuisines"],
                        f"₹{row['cost_for_two']} for two",
                        rec.get("explanation", ""),
                        rec.get("rank", 0)
                    )

if __name__ == "__main__":
    main()
