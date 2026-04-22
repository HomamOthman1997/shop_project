const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const state = {
  tab: "gifts",
  catalog: null,
  view: "root",
  selectedId: "",
  selectedName: "",
  items: [],
};

const content = document.getElementById("content");
const statusEl = document.getElementById("status");
const searchInput = document.getElementById("searchInput");

function money(value) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function setStatus(text, error = false) {
  statusEl.textContent = text || "";
  statusEl.classList.toggle("error", Boolean(error));
}

function initData() {
  if (tg?.initData) {
    return tg.initData;
  }
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const search = new URLSearchParams(window.location.search);
  return hash.get("tgWebAppData") || search.get("tgWebAppData") || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const telegramInitData = initData();
  if (telegramInitData) {
    headers.set("X-Telegram-Init-Data", telegramInitData);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function clear() {
  content.replaceChildren();
}

function button(className, text, onClick) {
  const el = document.createElement("button");
  el.className = className;
  el.type = "button";
  el.textContent = text;
  el.addEventListener("click", onClick);
  return el;
}

function tile(title, meta, onClick) {
  const el = button("tile", "", onClick);
  const strong = document.createElement("strong");
  strong.textContent = title;
  const span = document.createElement("span");
  span.textContent = meta;
  el.append(strong, span);
  return el;
}

function itemRow(item) {
  const row = document.createElement("article");
  row.className = "item";
  const left = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.name;
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.innerHTML = `<span class="price">${money(item.price_usd)}</span>`;
  if (item.kind === "gift") {
    meta.innerHTML += ` - Stock ${item.stock}`;
  }
  if (item.requires_server) {
    meta.innerHTML += " - Server ID required";
  }
  left.append(title, meta);
  const buy = button("buy", "Continue", () => createSelection(item));
  if (item.kind === "gift" && Number(item.stock || 0) <= 0) {
    buy.disabled = true;
    buy.textContent = "Out";
  }
  row.append(left, buy);
  return row;
}

function rootList() {
  clear();
  state.view = "root";
  state.selectedId = "";
  const q = searchInput.value.trim().toLowerCase();
  const rows = state.tab === "gifts" ? state.catalog.gift_categories : state.catalog.games;
  const filtered = rows.filter((row) => !q || row.name.toLowerCase().includes(q));
  setStatus(filtered.length ? "Select a category." : "No results.");
  const grid = document.createElement("section");
  grid.className = "grid";
  filtered.forEach((row) => {
    grid.append(
      tile(
        row.name,
        state.tab === "gifts" ? `${row.count} products` : "Top-up packages",
        () => openList(row.id, row.name),
      ),
    );
  });
  content.append(grid);
}

async function openList(id, name) {
  state.view = "items";
  state.selectedId = id;
  state.selectedName = name;
  searchInput.value = "";
  clear();
  setStatus("Loading products...");
  const back = button("back-btn", "Back", rootList);
  content.append(back);
  try {
    if (state.tab === "gifts") {
      const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(id)}`);
      state.items = data.items || [];
    } else {
      const data = await api(`/mini/digital/api/games/${encodeURIComponent(id)}`);
      state.items = data.items || [];
    }
    renderItems();
  } catch (err) {
    setStatus(`Could not load products: ${err.message}`, true);
  }
}

function renderItems() {
  clear();
  content.append(button("back-btn", "Back", rootList));
  const q = searchInput.value.trim().toLowerCase();
  const rows = state.items.filter((row) => !q || row.name.toLowerCase().includes(q));
  setStatus(rows.length ? `${state.selectedName}` : "No products found.");
  rows.forEach((row) => content.append(itemRow(row)));
}

async function createSelection(item) {
  if (!initData()) {
    setStatus("Open this page from Telegram to continue in the bot.", true);
    return;
  }
  const payload = item.kind === "gift"
    ? { kind: "gift", category_id: item.category_id, product_id: item.id }
    : { kind: "game", game_id: item.game_id, item_id: item.id, group_key: item.group_key };
  setStatus("Sending selection to bot...");
  try {
    const data = await api("/mini/digital/api/selection", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    tg.sendData(JSON.stringify({ digital_selection_token: data.token }));
    tg.close();
  } catch (err) {
    setStatus(`Selection failed: ${err.message}`, true);
  }
}

async function loadCatalog() {
  clear();
  if (!initData()) {
    setStatus("Open Digital Store from the Telegram bot button.", true);
    return;
  }
  setStatus("Loading store...");
  try {
    state.catalog = await api("/mini/digital/api/catalog");
    if (!state.catalog.enabled) {
      setStatus("Digital store is not available right now.", true);
      return;
    }
    rootList();
  } catch (err) {
    setStatus(`Store failed to load: ${err.message}`, true);
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    tab.classList.add("active");
    state.tab = tab.dataset.tab;
    searchInput.value = "";
    rootList();
  });
});

searchInput.addEventListener("input", () => {
  if (!state.catalog) return;
  if (state.view === "items") renderItems();
  else rootList();
});

document.getElementById("refreshBtn").addEventListener("click", loadCatalog);
loadCatalog();
