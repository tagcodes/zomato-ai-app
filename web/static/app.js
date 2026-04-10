const form = document.getElementById("prefsForm");
const submitBtn = document.getElementById("submitBtn");
const sampleBtn = document.getElementById("sampleBtn");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const metaEl = document.getElementById("meta");
const itemsEl = document.getElementById("items");
const emptyEl = document.getElementById("emptyState");
const citySelect = document.getElementById("citySelect");
const localitySelect = document.getElementById("localitySelect");

async function loadLocations() {
  const res = await fetch("/api/v1/locations");
  if (!res.ok) throw new Error(`Failed to load locations: HTTP ${res.status}`);
  const data = await res.json();
  const locations = data.locations || [];
  citySelect.innerHTML = "";
  if (!locations.length) {
    citySelect.innerHTML = `<option value="">No cities</option>`;
    return;
  }
  for (const loc of locations) {
    const opt = document.createElement("option");
    opt.value = loc;
    opt.textContent = loc;
    citySelect.appendChild(opt);
  }
}

async function loadLocalitiesForCity(city) {
  const url = city ? `/api/v1/localities?city=${encodeURIComponent(city)}` : "/api/v1/localities";
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to load localities: HTTP ${res.status}`);
  const data = await res.json();
  const localities = data.localities || [];
  localitySelect.innerHTML = "";
  const anyOpt = document.createElement("option");
  anyOpt.value = "";
  anyOpt.textContent = "(Any)";
  localitySelect.appendChild(anyOpt);
  for (const loc of localities) {
    const opt = document.createElement("option");
    opt.value = loc;
    opt.textContent = loc;
    localitySelect.appendChild(opt);
  }
}

function setStatus(text) {
  statusEl.textContent = text || "";
}

function setLoading(isLoading) {
  submitBtn.disabled = isLoading;
  sampleBtn.disabled = isLoading;
  submitBtn.textContent = isLoading ? "Working..." : "Get recommendations";
}

function readForm() {
  const data = new FormData(form);
  const city = String(data.get("city") || "").trim();
  const locality = String(data.get("locality") || "").trim();
  const budgetMaxInrRaw = data.get("budget_max_inr");
  const budgetMaxInr = budgetMaxInrRaw === null ? null : Number(budgetMaxInrRaw);
  return {
    location: locality || city,
    cuisine: String(data.get("cuisine") || "").trim(),
    min_rating: Number(data.get("min_rating") || 0),
    budget_max_inr: budgetMaxInr != null && !Number.isNaN(budgetMaxInr) ? budgetMaxInr : null,
    extras: String(data.get("extras") || "").trim(),
  };
}

function render(response) {
  itemsEl.innerHTML = "";
  summaryEl.textContent = response.summary || "";

  const meta = response.meta || {};
  metaEl.textContent = `shortlist=${meta.shortlist_size ?? "?"} | model=${meta.model ?? "?"} | reason=${
    meta.reason ?? "?"
  }`;

  const items = response.items || [];
  if (!items.length) {
    emptyEl.style.display = "block";
    return;
  }
  emptyEl.style.display = "none";

  for (const item of items) {
    const cuisines = Array.isArray(item.cuisines) ? item.cuisines.join(", ") : "";
    const rating = item.rating != null ? Number(item.rating).toFixed(1) : "?";
    const cost = item.cost_display || item.estimated_cost || "";

    const card = document.createElement("div");
    card.className = "item";
    card.innerHTML = `
      <div class="item-title">
        <h3>#${item.rank}. ${escapeHtml(item.name || "")}</h3>
        <span class="pill">⭐ ${rating}</span>
      </div>
      <p class="item-sub">${escapeHtml(cuisines)} ${cost ? " • " + escapeHtml(cost) : ""}</p>
      <p class="item-exp">${escapeHtml(item.explanation || "")}</p>
    `;
    itemsEl.appendChild(card);
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function recommend(payload) {
  const res = await fetch("/api/v1/recommend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return await res.json();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = readForm();
  if (!payload.location || !payload.cuisine) return;

  try {
    setLoading(true);
    setStatus("Calling backend...");
    const response = await recommend(payload);
    render(response);
    setStatus("Done.");
  } catch (err) {
    console.error(err);
    setStatus(String(err?.message || err));
  } finally {
    setLoading(false);
  }
});

sampleBtn.addEventListener("click", () => {
  // Fill with reasonable defaults; localities are loaded asynchronously.
  const desiredCity = "Bangalore";
  const options = Array.from(citySelect.options || []);
  const exists = options.some((o) => o.value === desiredCity);
  citySelect.value = exists ? desiredCity : (options[0]?.value || "");
  form.cuisine.value = "Chinese";
  form.budget_max_inr.value = "1200";
  form.min_rating.value = "3.0";
  form.extras.value = "family-friendly";
  setStatus("Sample filled. Click “Get recommendations”.");
});

// Initialize dropdowns on page load.
(async function init() {
  try {
    setStatus("Loading dropdowns...");
    await loadLocations();
    const initialCity = citySelect.value || citySelect.options?.[0]?.value || "";
    if (initialCity) {
      await loadLocalitiesForCity(initialCity);
    }
    setStatus("");
  } catch (err) {
    console.error(err);
    setStatus(String(err?.message || err));
  }
})();

citySelect.addEventListener("change", async () => {
  try {
    await loadLocalitiesForCity(citySelect.value);
  } catch (err) {
    console.error(err);
    setStatus(String(err?.message || err));
  }
});

