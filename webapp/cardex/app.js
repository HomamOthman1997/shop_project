const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const state = {
  rules: [],
  isAdmin: false,
  view: "brands",
  brand: "",
  regionKey: "",
  search: "",
};

const BRAND_META = {
  AMAZON: { mark: "a", tone: "tone-amazon" },
  ITUNES: { mark: "IT", tone: "tone-itunes" },
  APPLE: { mark: "A", tone: "tone-itunes" },
  RAZER: { mark: "Z", tone: "tone-razer" },
  "RAZER GOLD": { mark: "Z", tone: "tone-razer" },
  STEAM: { mark: "S", tone: "tone-steam" },
  WALMART: { mark: "W", tone: "tone-walmart" },
  TARGET: { mark: "TG", tone: "tone-target" },
  MASTERCARD: { mark: "MC", tone: "tone-mastercard" },
  VISA: { mark: "V", tone: "tone-visa" },
  PAYPAL: { mark: "P", tone: "tone-paypal" },
  PAYEER: { mark: "P", tone: "tone-payeer" },
  USDT: { mark: "T", tone: "tone-usdt" },
  UBER: { mark: "U", tone: "tone-uber" },
  STARBUCKS: { mark: "SB", tone: "tone-starbucks" },
  PLAYSTATION: { mark: "PS", tone: "tone-playstation" },
};

const content = document.getElementById("content");
const statusEl = document.getElementById("status");
const searchInput = document.getElementById("searchInput");
const refreshBtn = document.getElementById("refreshBtn");
const modal = document.getElementById("modal");
const priceForm = document.getElementById("priceForm");
const closeModal = document.getElementById("closeModal");
const sellModal = document.getElementById("sellModal");
const sellForm = document.getElementById("sellForm");
const closeSellModal = document.getElementById("closeSellModal");
const sellSummary = document.getElementById("sellSummary");
const quoteBox = document.getElementById("quoteBox");

function initData() {
  return tg?.initData || new URLSearchParams(location.search).get("tgWebAppData") || "";
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-Telegram-Init-Data": initData() };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...options, headers, cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function norm(text) {
  return String(text || "").trim().toLowerCase();
}

function clear() {
  content.replaceChildren();
  statusEl.textContent = "";
  statusEl.classList.remove("error");
}

function setError(text) {
  statusEl.textContent = text;
  statusEl.classList.add("error");
}

function button(cls, text, fn) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = cls;
  el.textContent = text;
  el.addEventListener("click", fn);
  return el;
}

function heading(title, subtitle = "") {
  const box = document.createElement("div");
  box.className = "section-title";
  const wrap = document.createElement("div");
  const h = document.createElement("h2");
  h.textContent = title;
  wrap.append(h);
  if (subtitle) {
    const p = document.createElement("p");
    p.textContent = subtitle;
    wrap.append(p);
  }
  box.append(wrap);
  if (state.isAdmin) box.append(button("primary", "Add", openModal));
  return box;
}

function brandRows() {
  const map = new Map();
  for (const row of state.rules) {
    const brand = String(row.brand || "-").toUpperCase();
    if (!map.has(brand)) map.set(brand, { brand, count: 0, regions: new Set() });
    map.get(brand).count += 1;
    map.get(brand).regions.add(`${row.region || "GLOBAL"}|${row.currency || "USD"}`);
  }
  return Array.from(map.values()).sort((a, b) => a.brand.localeCompare(b.brand));
}

function regionRows(brand) {
  const map = new Map();
  for (const row of state.rules.filter((item) => item.brand === brand)) {
    const key = `${row.region || "GLOBAL"}|${row.currency || "USD"}`;
    if (!map.has(key)) map.set(key, { key, region: row.region || "GLOBAL", currency: row.currency || "USD", count: 0 });
    map.get(key).count += 1;
  }
  return Array.from(map.values()).sort((a, b) => a.region.localeCompare(b.region) || a.currency.localeCompare(b.currency));
}

function filtered(items, fields) {
  const q = norm(state.search);
  if (!q) return items;
  return items.filter((item) => fields.some((field) => norm(item[field]).includes(q)));
}

function brandMeta(brand) {
  const key = String(brand || "").toUpperCase();
  return BRAND_META[key] || { mark: key.slice(0, 2) || "CX", tone: "tone-generic" };
}

function regionPreview(row) {
  return Array.from(row.regions).slice(0, 3).map((item) => item.split("|")[0]).join(" / ");
}

function renderBrands() {
  state.view = "brands";
  state.brand = "";
  state.regionKey = "";
  clear();
  content.append(heading("Card Brands", "Choose a card type, then country, then price category"));
  const grid = document.createElement("div");
  grid.className = "brand-grid";
  for (const row of filtered(brandRows(), ["brand"])) {
    const meta = brandMeta(row.brand);
    const tile = button(`brand-card ${meta.tone}`, "", () => renderRegions(row.brand));
    tile.innerHTML = `
      <div class="brand-poster">
        <span class="brand-orb">${meta.mark}</span>
        <strong>${row.brand}</strong>
        <span>${regionPreview(row) || "GLOBAL"}</span>
      </div>
      <div class="brand-caption">${row.regions.size} regions - ${row.count} categories</div>
    `;
    grid.append(tile);
  }
  if (!grid.children.length) statusEl.textContent = "No brands found.";
  content.append(grid);
}

function renderRegions(brand) {
  state.view = "regions";
  state.brand = brand;
  state.regionKey = "";
  clear();
  content.append(button("ghost", "Back", renderBrands));
  content.append(heading(brand, "Choose country or region"));
  const grid = document.createElement("div");
  grid.className = "region-grid";
  for (const row of filtered(regionRows(brand), ["region", "currency"])) {
    const tile = button("region-card", "", () => renderRules(brand, row.key));
    tile.innerHTML = `<strong>${row.region}</strong><span>${row.currency}</span><small>${row.count} categories</small>`;
    grid.append(tile);
  }
  if (!grid.children.length) statusEl.textContent = "No regions found.";
  content.append(grid);
}

function renderRules(brand, regionKey) {
  state.view = "rules";
  state.brand = brand;
  state.regionKey = regionKey;
  const [region, currency] = String(regionKey).split("|");
  clear();
  content.append(button("ghost", "Back", () => renderRegions(brand)));
  content.append(heading(`${brand} - ${region}`, `${currency} price categories`));
  const list = document.createElement("div");
  list.className = "list";
  const rows = state.rules
    .filter((row) => row.brand === brand && `${row.region}|${row.currency}` === regionKey)
    .filter((row) => !state.search || norm(`${row.label} ${row.note} ${row.customer_rate}`).includes(norm(state.search)));
  for (const row of rows) {
    const item = document.createElement("article");
    item.className = "rule";
    item.innerHTML = `
      <div class="rule-top"><span class="value">${row.label}</span><span class="rate">${row.customer_rate}%</span></div>
      <div class="muted">${row.currency} - trader ${row.trader_rate || row.customer_rate}%</div>
      ${row.note ? `<div class="note">${row.note}</div>` : ""}
    `;
    if (state.isAdmin) {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("primary", "Sell", () => openSellModal(row)));
      actions.append(button("ghost danger", "Delete", () => deleteRule(row.id)));
      item.append(actions);
    } else {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("primary", "Sell", () => openSellModal(row)));
      item.append(actions);
    }
    list.append(item);
  }
  if (!list.children.length) statusEl.textContent = "No categories found.";
  content.append(list);
}

async function loadPrices() {
  statusEl.textContent = "Loading prices...";
  try {
    const data = await api("/mini/cardex/api/prices");
    state.rules = Array.isArray(data.rules) ? data.rules : [];
    state.isAdmin = Boolean(data.is_admin);
    renderBrands();
  } catch (err) {
    clear();
    setError("Could not load CardEX prices.");
  }
}

function openModal() {
  priceForm.reset();
  if (state.brand) priceForm.elements.brand.value = state.brand;
  if (state.regionKey) {
    const [region, currency] = state.regionKey.split("|");
    priceForm.elements.region.value = region || "";
    priceForm.elements.currency.value = currency || "USD";
  }
  modal.classList.remove("hidden");
}

function closePriceModal() {
  modal.classList.add("hidden");
}

function firstRuleValue(row) {
  if (row.range_min) return row.range_min;
  if (Array.isArray(row.denominations) && row.denominations.length) return row.denominations[0];
  const match = String(row.label || "").match(/\d+(?:\.\d+)?/);
  return match ? match[0] : "";
}

async function refreshQuote() {
  const body = Object.fromEntries(new FormData(sellForm).entries());
  if (!body.brand || !body.denomination) return;
  try {
    const data = await api("/mini/cardex/api/quote", { method: "POST", body: JSON.stringify(body) });
    const quote = data.quote || {};
    if (!quote.configured) {
      quoteBox.textContent = "No price is configured for this value.";
      quoteBox.classList.remove("hidden");
      return;
    }
    const amount = Number(quote.customer_value_usd || 0).toFixed(2);
    quoteBox.textContent = `Expected payout: $${amount} (${quote.customer_buy_rate_percent}%)`;
    quoteBox.classList.remove("hidden");
  } catch (err) {
    quoteBox.textContent = "Could not quote this value.";
    quoteBox.classList.remove("hidden");
  }
}

function openSellModal(row) {
  sellForm.reset();
  sellForm.elements.brand.value = row.brand || state.brand || "";
  sellForm.elements.region.value = row.region || "";
  sellForm.elements.currency.value = row.currency || "USD";
  sellForm.elements.denomination.value = firstRuleValue(row);
  sellSummary.textContent = `${row.brand} - ${row.region} - ${row.label} ${row.currency}`;
  quoteBox.classList.add("hidden");
  sellModal.classList.remove("hidden");
  refreshQuote();
}

function closeCardSellModal() {
  sellModal.classList.add("hidden");
}

async function deleteRule(id) {
  if (!confirm("Delete this price category?")) return;
  await api(`/mini/cardex/api/prices/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadPrices();
  if (state.brand && state.regionKey) renderRules(state.brand, state.regionKey);
}

priceForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(priceForm);
  const body = Object.fromEntries(form.entries());
  try {
    await api("/mini/cardex/api/prices", { method: "POST", body: JSON.stringify(body) });
    closePriceModal();
    await loadPrices();
  } catch (err) {
    alert("Could not save category. Check values.");
  }
});

sellForm.elements.denomination.addEventListener("input", () => {
  window.clearTimeout(sellForm._quoteTimer);
  sellForm._quoteTimer = window.setTimeout(refreshQuote, 250);
});

sellForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = Object.fromEntries(new FormData(sellForm).entries());
  try {
    const data = await api("/mini/cardex/api/submit", { method: "POST", body: JSON.stringify(body) });
    if (data.missing_pricing) {
      alert("This value has no price yet. Admin was notified.");
      return;
    }
    const amount = Number(data.quote?.customer_value_usd || 0).toFixed(2);
    closeCardSellModal();
    alert(`Card submitted. Expected payout: $${amount}`);
  } catch (err) {
    alert("Could not submit card. Check the value and code.");
  }
});

closeModal.addEventListener("click", closePriceModal);
modal.addEventListener("click", (event) => {
  if (event.target?.dataset?.close) closePriceModal();
});
closeSellModal.addEventListener("click", closeCardSellModal);
sellModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeSell) closeCardSellModal();
});
refreshBtn.addEventListener("click", loadPrices);
searchInput.addEventListener("input", () => {
  state.search = searchInput.value || "";
  if (state.view === "brands") renderBrands();
  else if (state.view === "regions") renderRegions(state.brand);
  else if (state.view === "rules") renderRules(state.brand, state.regionKey);
});

loadPrices();
