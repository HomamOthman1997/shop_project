const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const copy = {
  en: {
    title: "Digital Store",
    refresh: "R",
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
    title: "المتجر الرقمي",
    refresh: "R",
    gifts: "بطاقات وقسائم",
    games: "شحن ألعاب",
    search: "بحث",
    loading: "جار تحميل المتجر...",
    loadingProducts: "جار تحميل العروض...",
    unavailable: "المتجر الرقمي غير متاح حاليا.",
    noResults: "لا توجد نتائج.",
    noProducts: "لا توجد عروض.",
    products: "عروض",
    packages: "باقات",
    all: "الكل",
    price: "السعر",
    stock: "المخزون",
    inStock: "متوفر",
    out: "غير متوفر",
    continue: "متابعة",
    back: "رجوع",
    serverRequired: "يتطلب Server ID",
    serverOptional: "Player ID فقط",
    selectionFailed: "فشل إرسال الاختيار",
    openTelegram: "افتح الصفحة من زر البوت داخل تيليغرام.",
    loadFailed: "فشل تحميل المتجر",
    productLoadFailed: "فشل تحميل العروض",
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
  refreshBtn.setAttribute("aria-label", state.lang === "ar" ? "تحديث" : "Refresh");
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
  content.append(segment(groups, state.group, (key) => {
    state.group = key;
    rootList();
  }));

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
    content.append(segment(groups, state.itemGroup, (key) => {
      state.itemGroup = key;
      renderItems();
    }));
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
  const payload = item.kind === "gift"
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
applyLang();
loadCatalog();
