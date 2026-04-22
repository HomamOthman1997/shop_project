const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const copy = {
  en: {
    title: "Digital Store",
    refresh: "R",
    switchLang: "AR",
    gifts: "Gift Cards",
    games: "Games",
    search: "Search",
    loading: "Loading store...",
    loadingProducts: "Loading products...",
    unavailable: "Digital store is not available right now.",
    noResults: "No results.",
    noProducts: "No products found.",
    products: "products",
    packages: "packages",
    all: "All",
    price: "Price",
    stock: "Stock",
    inStock: "In stock",
    out: "Out",
    continue: "Continue",
    back: "Back",
    serverRequired: "Server ID required",
    serverOptional: "Player ID only",
    selectionFailed: "Selection failed",
    openTelegram: "Open this page from Telegram to continue in the bot.",
    loadFailed: "Store failed to load",
    productLoadFailed: "Could not load products",
  },
  ar: {
    title: "\u0627\u0644\u0645\u062a\u062c\u0631 \u0627\u0644\u0631\u0642\u0645\u064a",
    refresh: "R",
    switchLang: "EN",
    gifts: "\u0628\u0637\u0627\u0642\u0627\u062a \u0648\u0642\u0633\u0627\u0626\u0645",
    games: "\u0634\u062d\u0646 \u0623\u0644\u0639\u0627\u0628",
    search: "\u0628\u062d\u062b",
    loading: "\u062c\u0627\u0631 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0645\u062a\u062c\u0631...",
    loadingProducts: "\u062c\u0627\u0631 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0639\u0631\u0648\u0636...",
    unavailable: "\u0627\u0644\u0645\u062a\u062c\u0631 \u0627\u0644\u0631\u0642\u0645\u064a \u063a\u064a\u0631 \u0645\u062a\u0627\u062d \u062d\u0627\u0644\u064a\u0627.",
    noResults: "\u0644\u0627 \u062a\u0648\u062c\u062f \u0646\u062a\u0627\u0626\u062c.",
    noProducts: "\u0644\u0627 \u062a\u0648\u062c\u062f \u0639\u0631\u0648\u0636.",
    products: "\u0639\u0631\u0648\u0636",
    packages: "\u0628\u0627\u0642\u0627\u062a",
    all: "\u0627\u0644\u0643\u0644",
    price: "\u0627\u0644\u0633\u0639\u0631",
    stock: "\u0627\u0644\u0645\u062e\u0632\u0648\u0646",
    inStock: "\u0645\u062a\u0648\u0641\u0631",
    out: "\u063a\u064a\u0631 \u0645\u062a\u0648\u0641\u0631",
    continue: "\u0645\u062a\u0627\u0628\u0639\u0629",
    back: "\u0631\u062c\u0648\u0639",
    serverRequired: "\u064a\u062a\u0637\u0644\u0628 Server ID",
    serverOptional: "Player ID \u0641\u0642\u0637",
    selectionFailed: "\u0641\u0634\u0644 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0627\u062e\u062a\u064a\u0627\u0631",
    openTelegram: "\u0627\u0641\u062a\u062d \u0627\u0644\u0635\u0641\u062d\u0629 \u0645\u0646 \u0632\u0631 \u0627\u0644\u0628\u0648\u062a \u062f\u0627\u062e\u0644 \u062a\u064a\u0644\u064a\u063a\u0631\u0627\u0645.",
    loadFailed: "\u0641\u0634\u0644 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0645\u062a\u062c\u0631",
    productLoadFailed: "\u0641\u0634\u0644 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0639\u0631\u0648\u0636",
  },
};

const state = {
  lang: detectLang(),
  tab: "gifts",
  group: "all",
  itemGroup: "all",
  catalog: null,
  view: "root",
  selectedId: "",
  selectedName: "",
  items: [],
  itemGroups: [],
};

const content = document.getElementById("content");
const statusEl = document.getElementById("status");
const searchInput = document.getElementById("searchInput");
const titleEl = document.getElementById("title");
const refreshBtn = document.getElementById("refreshBtn");
const langBtn = document.getElementById("langBtn");

function t(key) {
  return copy[state.lang][key] || copy.en[key] || key;
}

function detectLang() {
  const code = String(tg?.initDataUnsafe?.user?.language_code || navigator.language || "en").toLowerCase();
  return code.startsWith("ar") ? "ar" : "en";
}

function applyLang() {
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  titleEl.textContent = t("title");
  refreshBtn.textContent = t("refresh");
  refreshBtn.setAttribute("aria-label", state.lang === "ar" ? "\u062a\u062d\u062f\u064a\u062b" : "Refresh");
  if (langBtn) {
    langBtn.textContent = t("switchLang");
    langBtn.setAttribute("aria-label", state.lang === "ar" ? "\u062a\u063a\u064a\u064a\u0631 \u0627\u0644\u0644\u063a\u0629" : "Switch language");
  }
  document.querySelector('[data-tab="gifts"]').textContent = t("gifts");
  document.querySelector('[data-tab="games"]').textContent = t("games");
  searchInput.placeholder = t("search");
}

function money(value) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function label(obj) {
  if (!obj) return "";
  if (typeof obj === "string") return obj;
  return obj[state.lang] || obj.en || obj.ar || "";
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

function segment(items, active, onChange) {
  const wrap = document.createElement("section");
  wrap.className = "segments";
  items.forEach((item) => {
    const btn = button(`segment ${item.key === active ? "active" : ""}`, label(item.label), () => onChange(item.key));
    wrap.append(btn);
  });
  return wrap;
}

function tile(row, onClick) {
  const el = button("tile", "", onClick);
  const strong = document.createElement("strong");
  strong.textContent = row.name;
  const span = document.createElement("span");
  span.textContent = state.tab === "gifts" ? `${row.count} ${t("products")}` : t("packages");
  el.append(strong, span);
  return el;
}

function stat(labelText, valueText, className = "") {
  const el = document.createElement("span");
  el.className = `stat ${className}`.trim();
  const key = document.createElement("small");
  key.textContent = labelText;
  const value = document.createElement("b");
  value.textContent = valueText;
  el.append(key, value);
  return el;
}

function itemRow(item) {
  const row = document.createElement("article");
  row.className = "item";
  const top = document.createElement("div");
  top.className = "item-top";
  const title = document.createElement("strong");
  title.textContent = item.name;
  const buy = button("buy", t("continue"), () => createSelection(item));
  if (item.kind === "gift" && Number(item.stock || 0) <= 0) {
    buy.disabled = true;
    buy.textContent = t("out");
  }
  top.append(title, buy);

  const details = document.createElement("div");
  details.className = "details";
  details.append(stat(t("price"), money(item.price_usd), "price-stat"));
  if (item.kind === "gift") {
    const stockText = Number(item.stock || 0) > 0 ? `${item.stock} - ${t("inStock")}` : t("out");
    details.append(stat(t("stock"), stockText, Number(item.stock || 0) > 0 ? "ok" : "danger"));
  } else {
    details.append(stat("", item.requires_server ? t("serverRequired") : t("serverOptional")));
  }
  row.append(top, details);
  return row;
}

function rootRows() {
  const rows = state.tab === "gifts" ? state.catalog.gift_categories : state.catalog.games;
  const q = searchInput.value.trim().toLowerCase();
  return rows.filter((row) => {
    const matchesGroup = state.group === "all" || row.group_key === state.group;
    const matchesSearch = !q || row.name.toLowerCase().includes(q);
    return matchesGroup && matchesSearch;
  });
}

function rootList() {
  clear();
  state.view = "root";
  state.selectedId = "";
  state.selectedName = "";
  state.itemGroup = "all";
  state.itemGroups = [];
  const sourceGroups = state.tab === "gifts" ? state.catalog.gift_groups : state.catalog.game_groups;
  const groups = [{ key: "all", label: { en: t("all"), ar: t("all") } }, ...(sourceGroups || [])];
  content.append(
    segment(groups, state.group, (key) => {
      state.group = key;
      rootList();
    })
  );

  const rows = rootRows();
  setStatus(rows.length ? "" : t("noResults"));
  const grid = document.createElement("section");
  grid.className = "grid";
  rows.forEach((row) => grid.append(tile(row, () => openList(row.id, row.name))));
  content.append(grid);
}

async function openList(id, name) {
  state.view = "items";
  state.selectedId = id;
  state.selectedName = name;
  state.itemGroup = "all";
  searchInput.value = "";
  clear();
  setStatus(t("loadingProducts"));
  content.append(button("back-btn", t("back"), rootList));
  try {
    if (state.tab === "gifts") {
      const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(id)}`);
      state.items = data.items || [];
      state.itemGroups = [];
    } else {
      const data = await api(`/mini/digital/api/games/${encodeURIComponent(id)}`);
      state.items = data.items || [];
      state.itemGroups = data.groups || [];
    }
    renderItems();
  } catch (err) {
    setStatus(`${t("productLoadFailed")}: ${err.message}`, true);
  }
}

function itemRows() {
  const q = searchInput.value.trim().toLowerCase();
  return state.items.filter((row) => {
    const matchesGroup = state.itemGroup === "all" || row.group_key === state.itemGroup;
    const matchesSearch = !q || row.name.toLowerCase().includes(q);
    return matchesGroup && matchesSearch;
  });
}

function renderItems() {
  clear();
  content.append(button("back-btn", t("back"), rootList));
  if (state.itemGroups.length > 1) {
    const groups = [{ key: "all", label: { en: t("all"), ar: t("all") } }, ...state.itemGroups];
    content.append(
      segment(groups, state.itemGroup, (key) => {
        state.itemGroup = key;
        renderItems();
      })
    );
  }
  const rows = itemRows();
  setStatus(rows.length ? state.selectedName : t("noProducts"));
  rows.forEach((row) => content.append(itemRow(row)));
}

async function createSelection(item) {
  if (!tg?.sendData) {
    setStatus(t("openTelegram"), true);
    return;
  }
  const payload =
    item.kind === "gift"
      ? { kind: "gift", category_id: item.category_id, product_id: item.id }
      : { kind: "game", game_id: item.game_id, item_id: item.id, group_key: item.group_key };
  try {
    const data = await api("/mini/digital/api/selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    tg.sendData(JSON.stringify({ digital_selection_token: data.token }));
    tg.close();
  } catch (err) {
    setStatus(`${t("selectionFailed")}: ${err.message}`, true);
  }
}

async function loadCatalog() {
  clear();
  setStatus(t("loading"));
  try {
    state.catalog = await api("/mini/digital/api/catalog");
    if (!state.catalog.enabled) {
      setStatus(t("unavailable"), true);
      return;
    }
    rootList();
  } catch (err) {
    setStatus(`${t("loadFailed")}: ${err.message}`, true);
  }
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (!state.catalog) return;
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    tab.classList.add("active");
    state.tab = tab.dataset.tab;
    state.group = "all";
    searchInput.value = "";
    rootList();
  });
});

searchInput.addEventListener("input", () => {
  if (!state.catalog) return;
  if (state.view === "items") renderItems();
  else rootList();
});

refreshBtn.addEventListener("click", loadCatalog);
if (langBtn) {
  langBtn.addEventListener("click", () => {
    state.lang = state.lang === "ar" ? "en" : "ar";
    applyLang();
    if (!state.catalog) return;
    if (state.view === "items") renderItems();
    else rootList();
  });
}

applyLang();
loadCatalog();
