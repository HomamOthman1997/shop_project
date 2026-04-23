const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const SERVICE_KEYS = [
  "games",
  "chat_apps",
  "communications_data",
  "internet_providers",
  "paid_apps",
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

const extraCopy = {
  en: {
    all: "All",
    playerId: "Player ID",
    serverId: "Server ID",
    quantity: "Quantity",
    required: "Required",
    optional: "Optional",
    close: "Close",
    continueWithData: "Continue",
    invalidQuantity: "Invalid quantity.",
    missingRequiredField: "Missing required field.",
    gamePurchaseData: "Enter game account data",
    giftPurchaseData: "Enter purchase data",
    priceByQuantity: "By quantity",
    creditsRange: "Credits range",
  },
  ar: {
    all: "\u0627\u0644\u0643\u0644",
    playerId: "Player ID",
    serverId: "Server ID",
    quantity: "\u0627\u0644\u0643\u0645\u064a\u0629",
    required: "\u0645\u0637\u0644\u0648\u0628",
    optional: "\u0627\u062e\u062a\u064a\u0627\u0631\u064a",
    close: "\u0625\u063a\u0644\u0627\u0642",
    continueWithData: "\u0645\u062a\u0627\u0628\u0639\u0629",
    invalidQuantity: "\u0627\u0644\u0643\u0645\u064a\u0629 \u063a\u064a\u0631 \u0635\u062d\u064a\u062d\u0629.",
    missingRequiredField: "\u0647\u0646\u0627\u0643 \u062d\u0642\u0644 \u0645\u0637\u0644\u0648\u0628.",
    gamePurchaseData: "\u0623\u062f\u062e\u0644 \u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0634\u0631\u0627\u0621 \u0644\u0644\u0639\u0628\u0629",
    giftPurchaseData: "\u0623\u062f\u062e\u0644 \u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0634\u0631\u0627\u0621",
    priceByQuantity: "\u062d\u0633\u0628 \u0627\u0644\u0643\u0645\u064a\u0629",
    creditsRange: "\u0645\u062f\u0649 \u0627\u0644\u0643\u0631\u064a\u062f\u062a",
  },
};

const serviceLabelFallback = {
  games: { en: "قسم الألعاب", ar: "قسم الألعاب" },
  chat_apps: { en: "قسم تطبيقات الدردشة", ar: "قسم تطبيقات الدردشة" },
  communications_data: { en: "قسم الاتصالات والبيانات", ar: "قسم الاتصالات والبيانات" },
  internet_providers: { en: "مزودات الإنترنت", ar: "مزودات الإنترنت" },
  paid_apps: { en: "تطبيقات مدفوعة", ar: "تطبيقات مدفوعة" },
  numbers_services: { en: "قسم خدمات الأرقام", ar: "قسم خدمات الأرقام" },
  paid_subscriptions: { en: "قسم الاشتراكات المدفوعة", ar: "قسم الاشتراكات المدفوعة" },
  store_cards: { en: "قسم بطاقات متاجر", ar: "قسم بطاقات متاجر" },
};

const state = {
  lang: detectLang(),
  catalog: null,
  view: "services", // services | categories | subcategories | items | simkind
  service: "",
  search: "",
  categories: [],
  variantParent: null,
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
const inputModalEl = document.getElementById("inputModal");
const modalTitleEl = document.getElementById("modalTitle");
const modalSubtitleEl = document.getElementById("modalSubtitle");
const modalFormEl = document.getElementById("modalForm");
const modalCloseBtn = document.getElementById("modalCloseBtn");

function t(key) {
  return (
    copy[state.lang]?.[key] ||
    extraCopy[state.lang]?.[key] ||
    copy.en?.[key] ||
    extraCopy.en?.[key] ||
    key
  );
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
  if (modalCloseBtn) {
    modalCloseBtn.setAttribute("aria-label", t("close"));
  }
  searchInput.placeholder = t("search");
  const subtitle = document.querySelector(".topbar-subtitle");
  if (subtitle) {
    subtitle.textContent = state.lang === "ar" ? "متجرك الرقمي" : "Your Digital Marketplace";
  }
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
  const dynamicGiftPrice = item.kind === "gift" && Boolean(item.za3em_requires_input);
  const priceText = dynamicGiftPrice ? t("priceByQuantity") : money(item.price_usd);

  // السعر في الأعلى
  const priceDiv = document.createElement("div");
  priceDiv.className = "item-price-top";
  const priceStat = stat(t("price"), priceText, "price-stat");
  const priceValue = priceStat.querySelector("b");
  priceDiv.append(priceStat);
  row.append(priceDiv);

  // قيمة UC في الوسط
  const title = document.createElement("strong");
  title.textContent = String(item.name || "-");
  title.style.textAlign = "center";
  title.style.display = "block";
  row.append(title);
  if (dynamicGiftPrice) {
    const minQty = Number(item.za3em_qty_min || 1);
    const maxQty = Number(item.za3em_qty_max || minQty);
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.style.textAlign = "center";
    meta.textContent = `${t("creditsRange")}: ${minQty} - ${maxQty}`;
    row.append(meta);
    const form = document.createElement("section");
    form.className = "inline-form";
    const qtyField = document.createElement("div");
    qtyField.className = "field";
    const qtyLabel = document.createElement("label");
    qtyLabel.textContent = `${t("quantity")} (${t("required")})`;
    const qtyInput = document.createElement("input");
    qtyInput.type = "number";
    qtyInput.min = String(minQty);
    qtyInput.max = String(maxQty);
    qtyInput.value = String(Number(item.display_quantity || minQty));
    qtyField.append(qtyLabel, qtyInput);
    form.append(qtyField);

    const paramInputs = [];
    const params = Array.isArray(item.za3em_params) ? item.za3em_params : [];
    params.forEach((key) => {
      const field = document.createElement("div");
      field.className = "field";
      const lbl = document.createElement("label");
      const labelText = String(key || "").replaceAll("_", " ").trim() || String(key || "");
      lbl.textContent = `${labelText} (${t("required")})`;
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = labelText;
      field.append(lbl, input);
      form.append(field);
      paramInputs.push({ key, input });
    });

    const quoteLine = document.createElement("span");
    quoteLine.className = "meta inline-quote";
    quoteLine.style.textAlign = "center";
    const refreshQuote = () => {
      const qty = Number(qtyInput.value || minQty);
      const clamped = Math.max(minQty, Math.min(maxQty, Number.isFinite(qty) ? qty : minQty));
      const quoted = giftQuotePrice(item, clamped);
      quoteLine.textContent = `${t("price")}: $${quoted.toFixed(2)}`;
      if (priceValue) priceValue.textContent = `$${quoted.toFixed(2)}`;
    };
    qtyInput.addEventListener("input", refreshQuote);
    refreshQuote();
    form.append(quoteLine);

    const actionWrap = document.createElement("div");
    actionWrap.className = "inline-actions";
    const submitBtn = button("buy", t("continue"), async () => {
      const qty = Number(qtyInput.value || 0);
      if (!Number.isInteger(qty) || qty < minQty || qty > maxQty) {
        setStatus(t("invalidQuantity"), true);
        return;
      }
      const extraParams = {};
      for (const entry of paramInputs) {
        const value = String(entry.input.value || "").trim();
        if (!value) {
          setStatus(t("missingRequiredField"), true);
          return;
        }
        extraParams[String(entry.key)] = value;
      }
      const quoted = giftQuotePrice(item, qty);
      await createServiceSelection("gift", {
        kind: "gift",
        category_id: item.category_id,
        product_id: item.id,
        quantity: qty,
        extra_params: extraParams,
        quoted_price_usd: quoted,
      });
    });
    if (Number(item.stock || 0) <= 0) {
      submitBtn.disabled = true;
      submitBtn.textContent = t("out");
      qtyInput.disabled = true;
      paramInputs.forEach((entry) => {
        entry.input.disabled = true;
      });
    }
    actionWrap.append(submitBtn);
    form.append(actionWrap);
    row.append(form);
  } else {
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
  }

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

function inferServiceForGameName(name) {
  const n = String(name || "").toLowerCase();
  const chatHints = [
    "discord",
    "imo",
    "telegram",
    "whatsapp",
    "messenger",
    "viber",
    "line",
    "wechat",
    "tada",
    "bigo",
    "coco",
    "azal",
    "chat",
    "social",
    "live",
  ];
  if (chatHints.some((k) => n.includes(k))) return "chat_apps";
  return "games";
}

function normalizeGameCategoryName(name) {
  const raw = String(name || "-").trim();
  if (!raw) return "-";
  const normalized = raw.replace(/\s+/g, " ").trim();
  const regionTokens = [
    "global",
    "usa",
    "us",
    "uk",
    "europe",
    "eu",
    "mena",
    "ksa",
    "saudi arabia",
    "uae",
    "turkey",
    "india",
    "indonesia",
    "malaysia",
    "singapore",
    "cambodia",
    "philippines",
    "thailand",
    "vietnam",
    "pakistan",
    "bangladesh",
    "brazil",
    "mexico",
    "japan",
    "korea",
    "hong kong",
    "taiwan",
  ];
  const escaped = regionTokens.map((token) => token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const suffixPattern = new RegExp(`^(.*?)(?:\\s*[-/|]\\s*|\\s+)(${escaped.join("|")})$`, "i");
  const match = normalized.match(suffixPattern);
  if (!match) return normalized;
  const base = String(match[1] || "").trim();
  return base || normalized;
}

function normalizeChatCategoryName(name) {
  const n = String(name || "").toLowerCase();
  if (n.includes("bigo")) return "Bigo Live";
  if (n.includes("coco")) return "Coco Live";
  if (n.includes("azal")) return "Azal Live";
  if (n.includes("tada")) return "Tada Chat";
  if (n.includes("discord")) return "Discord";
  if (n.includes("imo")) return "IMO";
  if (n.includes("telegram")) return "Telegram";
  if (n.includes("whatsapp")) return "WhatsApp";
  if (n.includes("messenger") || n.includes("facebook")) return "Messenger";
  if (n.includes("viber")) return "Viber";
  if (n.includes("wechat")) return "WeChat";
  if (n.includes("line")) return "LINE";
  return String(name || "-");
}

function renderServices() {
  clear();
  state.view = "services";
  state.service = "";
  state.categories = [];
  state.variantParent = null;
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
    const merged = new Map();
    const mergeKey = (name) => String(name || "").toLowerCase().trim();
    (state.catalog.games || []).forEach((row) => {
      const name = normalizeGameCategoryName(String(row.name || "-"));
      if (inferServiceForGameName(name) !== "games") return;
      const keyName = mergeKey(name);
      if (!merged.has(keyName)) {
        merged.set(keyName, {
          id: keyName,
          name,
          count: 0,
          entry_kind: "game",
          game_ids: [],
          gift_category_ids: [],
          variants: [],
          meta_label: t("packages"),
        });
      }
      const cur = merged.get(keyName);
      cur.game_ids.push(String(row.id || ""));
      cur.count += 1;
      cur.variants.push({
        id: String(row.id || ""),
        name: String(row.name || "-"),
        entry_kind: "game",
        game_ids: [String(row.id || "")],
        gift_category_ids: [],
        meta_label: t("packages"),
      });
    });
    (state.catalog.gift_categories || [])
      .filter((row) => String(row.service_key || "") === "games")
      .forEach((row) => {
        const name = normalizeGameCategoryName(String(row.name || "-"));
        const keyName = mergeKey(name);
        if (!merged.has(keyName)) {
          merged.set(keyName, {
            id: keyName,
            name,
            count: 0,
            entry_kind: "gift",
            game_ids: [],
            gift_category_ids: [],
            variants: [],
            meta_label: `${Number(row.count || 0)} ${t("products")}`,
          });
        }
        const cur = merged.get(keyName);
        cur.gift_category_ids.push(String(row.id || ""));
        cur.count += Number(row.count || 0);
        cur.variants.push({
          id: String(row.id || ""),
          name: String(row.name || "-"),
          entry_kind: "gift",
          game_ids: [],
          gift_category_ids: [String(row.id || "")],
          meta_label: `${Number(row.count || 0)} ${t("products")}`,
        });
      });
    const rows = Array.from(merged.values()).map((row) => {
      const hasGame = row.game_ids.length > 0;
      const hasGift = row.gift_category_ids.length > 0;
      let id = row.id;
      let entry_kind = "gift";
      const variantRows = Array.isArray(row.variants) ? row.variants : [];
      const dedupVariants = [];
      const seenVariant = new Set();
      variantRows.forEach((v) => {
        const key = `${String(v.entry_kind || "")}:${String(v.id || "")}`;
        if (seenVariant.has(key)) return;
        seenVariant.add(key);
        dedupVariants.push(v);
      });
      dedupVariants.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
      if (hasGame && hasGift) {
        entry_kind = "mixed";
      } else if (hasGame) {
        if (row.game_ids.length > 1) {
          entry_kind = "mixed";
        } else {
          entry_kind = "game";
          id = String(row.game_ids[0] || row.id);
        }
      }
      if (dedupVariants.length > 1) {
        entry_kind = "group";
      } else if (dedupVariants.length === 1) {
        id = String(dedupVariants[0].id || id);
        entry_kind = String(dedupVariants[0].entry_kind || entry_kind);
      }
      return {
        ...row,
        id,
        entry_kind,
        variants: dedupVariants,
        meta_label: entry_kind === "group" ? `${dedupVariants.length} ${t("categories")}` : hasGame && hasGift ? `${t("offers")}` : row.meta_label,
      };
    });
    rows.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
    return rows;
  }
  if (key === "chat_apps") {
    const merged = new Map();
    const mergeKey = (name) => String(name || "").toLowerCase().trim();
    (state.catalog.gift_categories || [])
      .filter((row) => String(row.service_key || "") === "chat_apps")
      .forEach((row) => {
        const name = normalizeChatCategoryName(String(row.name || "-"));
        const keyName = mergeKey(name);
        if (!merged.has(keyName)) {
          merged.set(keyName, {
            id: keyName,
            name,
            count: 0,
            entry_kind: "gift",
            game_ids: [],
            gift_category_ids: [],
            meta_label: `${Number(row.count || 0)} ${t("products")}`,
          });
        }
        const cur = merged.get(keyName);
        cur.gift_category_ids.push(String(row.id || ""));
        cur.count += Number(row.count || 0);
      });
    (state.catalog.games || []).forEach((row) => {
      const name = normalizeChatCategoryName(String(row.name || "-"));
      if (inferServiceForGameName(name) !== "chat_apps") return;
      const keyName = mergeKey(name);
      if (!merged.has(keyName)) {
        merged.set(keyName, {
          id: keyName,
          name,
          count: 0,
          entry_kind: "game",
          game_ids: [],
          gift_category_ids: [],
          meta_label: t("packages"),
        });
      }
      const cur = merged.get(keyName);
      cur.game_ids.push(String(row.id || ""));
      cur.count += 1;
    });
    const rows = Array.from(merged.values()).map((row) => {
      const hasGame = row.game_ids.length > 0;
      const hasGift = row.gift_category_ids.length > 0;
      const entry_kind = hasGame && hasGift ? "mixed" : hasGame ? "game" : "gift";
      return {
        ...row,
        entry_kind,
        meta_label: hasGame && hasGift ? `${t("offers")}` : row.meta_label,
      };
    });
    rows.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
    return rows;
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
  state.variantParent = null;
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
          game_ids: Array.isArray(row1.game_ids) ? row1.game_ids : [],
          gift_category_ids: Array.isArray(row1.gift_category_ids) ? row1.gift_category_ids : [],
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
            game_ids: Array.isArray(row2.game_ids) ? row2.game_ids : [],
            gift_category_ids: Array.isArray(row2.gift_category_ids) ? row2.gift_category_ids : [],
          })
        )
      );
    }
    list.append(wrapper);
  }
  content.append(list);
}

function renderVariantCategories(parent) {
  clear();
  state.view = "subcategories";
  state.variantParent = parent;
  content.append(
    button("back-btn", t("back"), () => {
      state.variantParent = null;
      renderCategories();
    })
  );
  content.append(heading(`${t("categories")} • ${String(parent?.name || "-")}`));
  const q = state.search.trim().toLowerCase();
  const rows = (Array.isArray(parent?.variants) ? parent.variants : []).filter((row) => {
    const n = String(row?.name || "").toLowerCase();
    return !q || n.includes(q);
  });
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
          game_ids: Array.isArray(row1.game_ids) ? row1.game_ids : [],
          gift_category_ids: Array.isArray(row1.gift_category_ids) ? row1.gift_category_ids : [],
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
            game_ids: Array.isArray(row2.game_ids) ? row2.game_ids : [],
            gift_category_ids: Array.isArray(row2.gift_category_ids) ? row2.gift_category_ids : [],
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
  if (category.entry_kind === "group" && Array.isArray(category.variants) && category.variants.length > 1) {
    setStatus("");
    renderVariantCategories(category);
    return;
  }
  state.view = "items";
  state.selectedId = category.id;
  state.selectedName = category.name;
  state.selectedCategoryKind = category.entry_kind === "game" ? "game" : "gift";
  state.itemGroup = "all";
  state.itemGroups = [];
  try {
    if (category.entry_kind === "mixed") {
      const allItems = [];
      const allGroups = [];
      for (const gid of category.game_ids || []) {
        const data = await api(`/mini/digital/api/games/${encodeURIComponent(gid)}`);
        allItems.push(...(data.items || []));
        allGroups.push(...(data.groups || []));
      }
      for (const cid of category.gift_category_ids || []) {
        const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(cid)}`);
        const giftRows = (data.items || []).map((item) => ({ ...item, group_key: "vouchers" }));
        allItems.push(...giftRows);
      }
      state.items = allItems;
      const groupMap = new Map();
      (allGroups || []).forEach((g) => {
        if (g && g.key && !groupMap.has(g.key)) groupMap.set(g.key, g);
      });
      if (!groupMap.has("vouchers")) {
        groupMap.set("vouchers", { key: "vouchers", label: { en: "Vouchers", ar: "قسائم" } });
      }
      state.itemGroups = Array.from(groupMap.values());
    } else if (state.selectedCategoryKind === "game") {
      const data = await api(`/mini/digital/api/games/${encodeURIComponent(category.id)}`);
      state.items = data.items || [];
      state.itemGroups = data.groups || [];
    } else {
      const sourceGiftIds = Array.isArray(category.gift_category_ids) ? category.gift_category_ids.filter(Boolean) : [];
      if (sourceGiftIds.length > 0) {
        const allItems = [];
        for (const cid of sourceGiftIds) {
          const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(cid)}`);
          allItems.push(...(data.items || []));
        }
        const seen = new Set();
        state.items = allItems.filter((item) => {
          const key = `${String(item.kind || "")}:${String(item.id || "")}:${String(item.category_id || "")}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      } else {
        const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(category.id)}`);
        state.items = data.items || [];
      }
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

function promptText(en, ar) {
  return state.lang === "ar" ? ar : en;
}

function giftQuotePrice(item, quantity) {
  const qty = Math.max(1, Number(quantity || 1));
  const unit = Number(item?.unit_price_usd || item?.price_usd || 0);
  return Number((unit * qty).toFixed(2));
}

function closeInputModal() {
  if (!inputModalEl) return;
  inputModalEl.classList.add("hidden");
  inputModalEl.setAttribute("aria-hidden", "true");
  document.body.classList.remove("modal-open");
  if (modalFormEl) modalFormEl.replaceChildren();
}

function openInputModal({ title, subtitle, fields, onSubmit, onChange }) {
  if (!inputModalEl || !modalFormEl || !modalTitleEl || !modalSubtitleEl) return;
  modalTitleEl.textContent = title || t("continue");
  modalSubtitleEl.textContent = subtitle || "";
  modalFormEl.replaceChildren();

  fields.forEach((field) => {
    const wrap = document.createElement("div");
    wrap.className = "field";
    const lbl = document.createElement("label");
    lbl.setAttribute("for", `f_${field.name}`);
    lbl.textContent = `${field.label}${field.required ? ` (${t("required")})` : ` (${t("optional")})`}`;
    const input = document.createElement("input");
    input.id = `f_${field.name}`;
    input.name = field.name;
    input.type = field.type || "text";
    input.required = Boolean(field.required);
    input.placeholder = field.placeholder || "";
    if (field.value !== undefined && field.value !== null) input.value = String(field.value);
    if (field.min !== undefined) input.min = String(field.min);
    if (field.max !== undefined) input.max = String(field.max);
    wrap.append(lbl, input);
    modalFormEl.append(wrap);
  });
  if (typeof onChange === "function") {
    const refreshValues = () => {
      const values = {};
      for (const field of fields) {
        const el = modalFormEl.querySelector(`[name="${field.name}"]`);
        values[field.name] = String(el?.value || "").trim();
      }
      onChange(values);
    };
    modalFormEl.querySelectorAll("input").forEach((el) => el.addEventListener("input", refreshValues));
    refreshValues();
  }

  const actions = document.createElement("div");
  actions.className = "modal-actions";
  const cancelBtn = button("back-btn", t("close"), () => closeInputModal());
  const submitBtn = button("buy", t("continueWithData"), () => {});
  submitBtn.type = "submit";
  actions.append(cancelBtn, submitBtn);
  modalFormEl.append(actions);

  modalFormEl.onsubmit = async (event) => {
    event.preventDefault();
    const values = {};
    for (const field of fields) {
      const el = modalFormEl.querySelector(`[name="${field.name}"]`);
      const raw = String(el?.value || "").trim();
      if (field.required && !raw) {
        setStatus(t("missingRequiredField"), true);
        return;
      }
      if (field.type === "number" && raw) {
        const parsed = Number(raw);
        if (!Number.isFinite(parsed)) {
          setStatus(t("invalidQuantity"), true);
          return;
        }
        if (field.min !== undefined && parsed < Number(field.min)) {
          setStatus(t("invalidQuantity"), true);
          return;
        }
        if (field.max !== undefined && parsed > Number(field.max)) {
          setStatus(t("invalidQuantity"), true);
          return;
        }
        values[field.name] = Math.trunc(parsed);
      } else {
        values[field.name] = raw;
      }
    }
    closeInputModal();
    await onSubmit(values);
  };

  inputModalEl.classList.remove("hidden");
  inputModalEl.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

async function createSelection(item) {
  if (item.kind === "gift") {
    const fields = [];
    const qtyMin = Number(item.za3em_qty_min || 1);
    const qtyMax = Number(item.za3em_qty_max || qtyMin);
    if (Boolean(item.za3em_requires_input) && qtyMax > 1) {
      fields.push({
        name: "quantity",
        label: t("quantity"),
        type: "number",
        required: true,
        min: qtyMin,
        max: qtyMax,
        value: qtyMin,
      });
    }
    const params = Array.isArray(item.za3em_params) ? item.za3em_params : [];
    params.forEach((key) => {
      const labelText = String(key || "").replaceAll("_", " ").trim() || String(key || "");
      fields.push({ name: `p__${key}`, label: labelText, required: true, type: "text" });
    });

    if (!fields.length) {
      const quoted = giftQuotePrice(item, 1);
      await createServiceSelection("gift", {
        kind: "gift",
        category_id: item.category_id,
        product_id: item.id,
        quoted_price_usd: quoted,
      });
      return;
    }

    const baseSubtitle = item.name || "";
    openInputModal({
      title: t("giftPurchaseData"),
      subtitle: baseSubtitle,
      fields,
      onChange: (values) => {
        const qty = Number(values.quantity || item.display_quantity || 1);
        const quoted = giftQuotePrice(item, qty);
        if (modalSubtitleEl) {
          modalSubtitleEl.textContent = `${baseSubtitle} • ${t("price")}: $${quoted.toFixed(2)}`;
        }
      },
      onSubmit: async (values) => {
        const extraParams = {};
        Object.entries(values).forEach(([key, value]) => {
          if (key.startsWith("p__")) extraParams[key.slice(3)] = value;
        });
        const qty = Number(values.quantity || item.display_quantity || 1);
        const quoted = giftQuotePrice(item, qty);
        await createServiceSelection("gift", {
          kind: "gift",
          category_id: item.category_id,
          product_id: item.id,
          quantity: qty,
          extra_params: extraParams,
          quoted_price_usd: quoted,
        });
      },
    });
    return;
  }

  const gameFields = [{ name: "player_id", label: t("playerId"), type: "text", required: true }];
  gameFields.push({
    name: "server_id",
    label: t("serverId"),
    type: "text",
    required: Boolean(item.requires_server),
  });
  openInputModal({
    title: t("gamePurchaseData"),
    subtitle: item.name || "",
    fields: gameFields,
    onSubmit: async (values) => {
      await createServiceSelection("game", {
        kind: "game",
        game_id: item.game_id,
        item_id: item.id,
        group_key: item.group_key,
        player_id: String(values.player_id || "").trim(),
        server_id: String(values.server_id || "").trim(),
        quoted_price_usd: Number(Number(item.price_usd || 0).toFixed(2)),
      });
    },
  });
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
  if (state.view === "subcategories") renderVariantCategories(state.variantParent);
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
    else if (state.view === "subcategories") renderVariantCategories(state.variantParent);
    else if (state.view === "items") renderItems();
    else if (state.view === "simkind") renderSimKinds();
  });
}
if (modalCloseBtn) {
  modalCloseBtn.addEventListener("click", closeInputModal);
}
if (inputModalEl) {
  inputModalEl.addEventListener("click", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && target.dataset.closeModal === "1") {
      closeInputModal();
    }
  });
}

applyLang();
loadCatalog();
