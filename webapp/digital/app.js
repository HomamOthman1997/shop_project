const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const SERVICE_KEYS = [
  "games",
  "chat_apps",
  "communications_data",
  "numbers_services",
  "paid_subscriptions",
  "store_cards",
];

const copy = {
  en: {
    title: "Digital Store",
    refresh: "R",
    switchLang: "AR",
    search: "Search",
    loading: "Loading store...",
    unavailable: "Digital store is not available right now.",
    noResults: "No results.",
    noProducts: "No products found.",
    sections: "Sections",
    categories: "Categories",
    offers: "Offers",
    products: "products",
    packages: "packages",
    unavailableShort: "Unavailable",
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
    simKindTitle: "Telecom & Data",
    simBalance: "Balance Top Up",
    simData: "Data Packages",
    esimDirect: "eSIM",
  },
  ar: {
    title: "المتجر الرقمي",
    refresh: "R",
    switchLang: "EN",
    search: "بحث",
    loading: "جار تحميل المتجر...",
    unavailable: "المتجر الرقمي غير متاح حالياً.",
    noResults: "لا توجد نتائج.",
    noProducts: "لا توجد عروض.",
    sections: "الأقسام",
    categories: "الفئات",
    offers: "العروض",
    products: "عروض",
    packages: "باقات",
    unavailableShort: "غير متاح",
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
    simKindTitle: "قسم الاتصالات والبيانات",
    simBalance: "شحن رصيد",
    simData: "باقات بيانات",
    esimDirect: "eSIM",
  },
};

const serviceLabelFallback = {
  games: { en: "قسم الألعاب", ar: "قسم الألعاب" },
  chat_apps: { en: "قسم تطبيقات الدردشة", ar: "قسم تطبيقات الدردشة" },
  communications_data: { en: "قسم الاتصالات والبيانات", ar: "قسم الاتصالات والبيانات" },
  numbers_services: { en: "قسم خدمات الأرقام", ar: "قسم خدمات الأرقام" },
  paid_subscriptions: { en: "قسم الاشتراكات المدفوعة", ar: "قسم الاشتراكات المدفوعة" },
  store_cards: { en: "قسم بطاقات متاجر", ar: "قسم بطاقات متاجر" },
};

const state = {
  lang: detectLang(),
  catalog: null,
  view: "services", // services | categories | items | simkind
  service: "",
  search: "",
  categories: [],
  selectedId: "",
  selectedName: "",
  selectedCategoryKind: "gift", // gift | game
  itemGroup: "all",
  itemGroups: [],
  items: [],
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
  refreshBtn.setAttribute("aria-label", state.lang === "ar" ? "تحديث" : "Refresh");
  if (langBtn) {
    langBtn.textContent = t("switchLang");
    langBtn.setAttribute("aria-label", state.lang === "ar" ? "تغيير اللغة" : "Switch language");
  }
  searchInput.placeholder = t("search");
  // تحديث رسالة الترحيب حسب اللغة
  const welcomeMsg = document.getElementById("welcomeMsg");
  if (welcomeMsg) {
    welcomeMsg.textContent = state.lang === "ar" ? "مرحباً بك في المتجر الرقمي!" : "Welcome to the Digital Store!";
  }
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
  if (tg?.initData) return tg.initData;
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const search = new URLSearchParams(window.location.search);
  return hash.get("tgWebAppData") || search.get("tgWebAppData") || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const telegramInitData = initData();
  if (telegramInitData) headers.set("X-Telegram-Init-Data", telegramInitData);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function clear() {
  content.replaceChildren();
}

function button(className, text, onClick, disabled = false) {
  const el = document.createElement("button");
  el.className = className;
  el.type = "button";
  el.textContent = text;
  el.disabled = disabled;
  if (!disabled) el.addEventListener("click", onClick);
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

function heading(text) {
  const h = document.createElement("h2");
  h.className = "section-title";
  h.textContent = text;
  return h;
}

function card(title, meta, onClick, disabled = false) {
  const el = button("dept-tile", "", onClick, disabled);
  const strong = document.createElement("strong");
  strong.textContent = title;
  const span = document.createElement("span");
  span.textContent = meta;
  el.append(strong, span);
  return el;
}

function listTile(name, meta, onClick) {
  const el = button("tile", "", onClick);
  const body = document.createElement("div");
  body.className = "tile-body";
  const strong = document.createElement("strong");
  strong.textContent = name;
  const span = document.createElement("span");
  span.textContent = meta;
  body.append(strong, span);
  const chev = document.createElement("b");
  chev.className = "tile-chevron";
  chev.textContent = "›";
  el.append(body, chev);
  return el;
}

function itemRow(item) {
  const row = document.createElement("article");
  row.className = "item";

  // السعر في الأعلى
  const priceDiv = document.createElement("div");
  priceDiv.className = "item-price-top";
  priceDiv.append(stat(t("price"), money(item.price_usd), "price-stat"));
  row.append(priceDiv);

  // قيمة UC في الوسط
  const title = document.createElement("strong");
  title.textContent = `${item.name} UC`;
  title.style.textAlign = "center";
  title.style.display = "block";
  row.append(title);

  // زر Continue في الأسفل
  const buy = button("buy", t("continue"), () => createSelection(item));
  if (item.kind === "gift" && Number(item.stock || 0) <= 0) {
    buy.disabled = true;
    buy.textContent = t("out");
  }
  const btnDiv = document.createElement("div");
  btnDiv.style.display = "flex";
  btnDiv.style.justifyContent = "center";
  btnDiv.append(buy);
  row.append(btnDiv);

  return row;
}

function serviceRows() {
  const lookup = new Map((state.catalog?.services || []).map((row) => [String(row.key || ""), row]));
  return SERVICE_KEYS.map((key) => {
    const row = lookup.get(key) || {};
    return {
      key,
      enabled: Boolean(row.enabled),
      count: Number(row.count || 0),
      label: row.label || serviceLabelFallback[key],
    };
  });
}

function filteredCategories() {
  const q = state.search.trim().toLowerCase();
  return state.categories.filter((row) => !q || String(row.name || "").toLowerCase().includes(q));
}

function filteredItems() {
  const q = state.search.trim().toLowerCase();
  return state.items.filter((row) => {
    const byGroup = state.itemGroup === "all" || row.group_key === state.itemGroup;
    const bySearch = !q || String(row.name || "").toLowerCase().includes(q);
    return byGroup && bySearch;
  });
}

function renderServices() {
  clear();
  state.view = "services";
  state.service = "";
  state.categories = [];
  state.selectedId = "";
  state.selectedName = "";
  state.selectedCategoryKind = "gift";
  state.itemGroups = [];
  state.items = [];
  state.itemGroup = "all";
  state.search = "";
  searchInput.value = "";
  setStatus("");

  content.append(heading(t("sections")));
  const grid = document.createElement("section");
  grid.className = "dept-grid";
  serviceRows().forEach((row) => {
    const meta = row.enabled
      ? `${row.count} ${row.key === "games" ? t("packages") : t("categories")}`
      : t("unavailableShort");
    grid.append(card(label(row.label), meta, () => enterService(row.key), !row.enabled));
  });
  content.append(grid);
}

function buildCategoriesForService(key) {
  if (!state.catalog) return [];
  if (key === "games") {
    const gameRows = (state.catalog.games || []).map((row) => ({
      id: String(row.id || ""),
      name: String(row.name || "-"),
      count: 0,
      entry_kind: "game",
      meta_label: t("packages"),
    }));
    const giftRows = (state.catalog.gift_categories || [])
      .filter((row) => String(row.service_key || "") === "games")
      .map((row) => ({
        id: String(row.id || ""),
        name: String(row.name || "-"),
        count: Number(row.count || 0),
        entry_kind: "gift",
        meta_label: `${Number(row.count || 0)} ${t("products")}`,
      }));
    return [...gameRows, ...giftRows];
  }
  return (state.catalog.gift_categories || [])
    .filter((row) => String(row.service_key || "") === key)
    .map((row) => ({
      id: String(row.id || ""),
      name: String(row.name || "-"),
      count: Number(row.count || 0),
      entry_kind: "gift",
      meta_label: `${Number(row.count || 0)} ${t("products")}`,
    }));
}

function enterService(key) {
  state.service = key;
  state.search = "";
  searchInput.value = "";
  state.itemGroup = "all";
  state.itemGroups = [];
  setStatus("");

  if (key === "communications_data") {
    renderSimKinds();
    return;
  }
  if (key === "numbers_services") {
    createServiceSelection("numbers_services");
    return;
  }
  state.categories = buildCategoriesForService(key);
  renderCategories();
}

function renderCategories() {
  clear();
  state.view = "categories";
  content.append(button("back-btn", t("back"), renderServices));
  content.append(heading(t("categories")));

  const rows = filteredCategories();
  setStatus(rows.length ? "" : t("noResults"));

  const list = document.createElement("section");
  list.className = "category-list";
  for (let i = 0; i < rows.length; i += 2) {
    const row1 = rows[i];
    const row2 = rows[i + 1];
    const wrapper = document.createElement("div");
    wrapper.style.display = "contents";
    wrapper.append(
      listTile(String(row1.name || "-"), row1.meta_label || "", () =>
        openItems({
          id: String(row1.id || ""),
          name: String(row1.name || "-"),
          entry_kind: String(row1.entry_kind || "gift"),
        })
      )
    );
    if (row2) {
      wrapper.append(
        listTile(String(row2.name || "-"), row2.meta_label || "", () =>
          openItems({
            id: String(row2.id || ""),
            name: String(row2.name || "-"),
            entry_kind: String(row2.entry_kind || "gift"),
          })
        )
      );
    }
    list.append(wrapper);
  }
  content.append(list);
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

async function openItems(category) {
  clear();
  setStatus(t("loading"));
  state.view = "items";
  state.selectedId = category.id;
  state.selectedName = category.name;
  state.selectedCategoryKind = category.entry_kind === "game" ? "game" : "gift";
  state.itemGroup = "all";
  state.itemGroups = [];
  try {
    if (state.selectedCategoryKind === "game") {
      const data = await api(`/mini/digital/api/games/${encodeURIComponent(category.id)}`);
      state.items = data.items || [];
      state.itemGroups = data.groups || [];
    } else {
      const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(category.id)}`);
      state.items = data.items || [];
      state.itemGroups = [];
    }
    renderItems();
  } catch (err) {
    setStatus(`${t("productLoadFailed")}: ${err.message}`, true);
  }
}

function renderItems() {
  clear();
  content.append(button("back-btn", t("back"), renderCategories));
  content.append(heading(`${t("offers")} • ${state.selectedName}`));
  if (state.itemGroups.length > 1) {
    const groups = [{ key: "all", label: { en: t("all"), ar: t("all") } }, ...state.itemGroups];
    content.append(
      segment(groups, state.itemGroup, (key) => {
        state.itemGroup = key;
        renderItems();
      })
    );
  }
  const rows = filteredItems();
  setStatus(rows.length ? "" : t("noProducts"));
  const grid = document.createElement("section");
  grid.className = "items-grid";
  for (let i = 0; i < rows.length; i += 2) {
    const row1 = rows[i];
    const row2 = rows[i + 1];
    const wrapper = document.createElement("div");
    wrapper.style.display = "contents";
    wrapper.append(itemRow(row1));
    if (row2) wrapper.append(itemRow(row2));
    grid.append(wrapper);
  }
  content.append(grid);
}

function renderSimKinds() {
  clear();
  state.view = "simkind";
  setStatus("");
  content.append(button("back-btn", t("back"), renderServices));
  content.append(heading(t("simKindTitle")));
  const grid = document.createElement("section");
  grid.className = "dept-grid";
  grid.append(card(t("simBalance"), t("continue"), () => createServiceSelection("simtopup", { section: "balance" })));
  grid.append(card(t("simData"), t("continue"), () => createServiceSelection("simtopup", { section: "data" })));
  grid.append(card(t("esimDirect"), t("continue"), () => createServiceSelection("esim")));
  content.append(grid);
}

async function createServiceSelection(kind, extra = {}) {
  if (!tg?.sendData) {
    setStatus(t("openTelegram"), true);
    return;
  }
  try {
    const data = await api("/mini/digital/api/selection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, ...extra }),
    });
    tg.sendData(JSON.stringify({ digital_selection_token: data.token }));
    tg.close();
  } catch (err) {
    setStatus(`${t("selectionFailed")}: ${err.message}`, true);
  }
}

async function createSelection(item) {
  const payload =
    item.kind === "gift"
      ? { kind: "gift", category_id: item.category_id, product_id: item.id }
      : { kind: "game", game_id: item.game_id, item_id: item.id, group_key: item.group_key };
  await createServiceSelection(payload.kind, payload);
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
    renderServices();
  } catch (err) {
    setStatus(`${t("loadFailed")}: ${err.message}`, true);
  }
}

searchInput.addEventListener("input", () => {
  state.search = String(searchInput.value || "");
  if (!state.catalog) return;
  if (state.view === "categories") renderCategories();
  if (state.view === "items") renderItems();
});

refreshBtn.addEventListener("click", loadCatalog);
if (langBtn) {
  langBtn.addEventListener("click", () => {
    state.lang = state.lang === "ar" ? "en" : "ar";
    applyLang();
    if (!state.catalog) return;
    if (state.view === "services") renderServices();
    else if (state.view === "categories") renderCategories();
    else if (state.view === "items") renderItems();
    else if (state.view === "simkind") renderSimKinds();
  });
}

applyLang();
loadCatalog();
