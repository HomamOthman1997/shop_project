const tg = window.Telegram?.WebApp;
tg?.ready();
tg?.expand();

const copy = {
  ar: {
    store: "المتجر", orders: "طلباتي", account: "حسابي", search: "ابحث عن لعبة أو خدمة",
    games: "شحن الألعاب", products: "الخدمات الرقمية", all: "الكل", loading: "جاري التحميل...",
    noResults: "لا توجد نتائج مطابقة", loadError: "تعذر تحميل البيانات", retry: "إعادة المحاولة",
    from: "ابتداءً من", unavailable: "غير متاح حالياً", packages: "الباقات والأسعار",
    selectPackage: "اختر الباقة المناسبة", price: "السعر", continue: "متابعة", confirm: "تأكيد الطلب",
    playerId: "معرّف اللاعب", serverId: "معرّف السيرفر", required: "مطلوب", optional: "اختياري",
    customerData: "بيانات العميل", reviewOrder: "مراجعة الطلب", product: "الخدمة", balance: "الرصيد",
    payNow: "ادفع وأنشئ الطلب", processing: "جاري إنشاء طلبك...", success: "تم إنشاء الطلب بنجاح",
    orderNumber: "رقم الطلب", viewOrders: "عرض طلباتي", noOrders: "لم تنشئ أي طلب بعد",
    status: "الحالة", details: "التفاصيل", created: "تاريخ الإنشاء", recentActivity: "نشاط المحفظة",
    noActivity: "لا يوجد نشاط حديث", username: "اسم المستخدم", wallet: "المحفظة",
    telegramRequired: "افتح الميني آب من بوت Telegram للمتابعة.", insufficient_balance: "الرصيد غير كافٍ.",
    order_failed: "تعذر إنشاء الطلب.", refresh: "تحديث", pending: "قيد الانتظار", paid: "تم الدفع",
    completed: "مكتمل", processingStatus: "قيد المعالجة", refunded: "مسترجع", failed: "فشل",
    back: "رجوع", orderTotal: "إجمالي الطلب", secureNote: "سيتم الخصم من محفظتك مباشرة بعد التأكيد.",
    emptyPackages: "لا توجد باقات متاحة لهذه الخدمة.", fieldRequired: "يرجى تعبئة الحقول المطلوبة.",
  },
  en: {
    store: "Store", orders: "My orders", account: "Account", search: "Search games and services",
    games: "Game top-ups", products: "Digital services", all: "All", loading: "Loading...",
    noResults: "No matching results", loadError: "Could not load data", retry: "Try again",
    from: "From", unavailable: "Currently unavailable", packages: "Packages & prices",
    selectPackage: "Choose the right package", price: "Price", continue: "Continue", confirm: "Confirm order",
    playerId: "Player ID", serverId: "Server ID", required: "Required", optional: "Optional",
    customerData: "Customer details", reviewOrder: "Review order", product: "Product", balance: "Balance",
    payNow: "Pay and create order", processing: "Creating your order...", success: "Order created successfully",
    orderNumber: "Order number", viewOrders: "View my orders", noOrders: "You have not created any orders yet",
    status: "Status", details: "Details", created: "Created", recentActivity: "Wallet activity",
    noActivity: "No recent activity", username: "Username", wallet: "Wallet",
    telegramRequired: "Open this mini app from the Telegram bot to continue.", insufficient_balance: "Insufficient balance.",
    order_failed: "Could not create order.", refresh: "Refresh", pending: "Pending", paid: "Paid",
    completed: "Completed", processingStatus: "Processing", refunded: "Refunded", failed: "Failed",
    back: "Back", orderTotal: "Order total", secureNote: "Your wallet will be charged immediately after confirmation.",
    emptyPackages: "No packages are available for this service.", fieldRequired: "Complete the required fields.",
  },
};

const state = {
  lang: localStorage.getItem("digital-lang") || (String(tg?.initDataUnsafe?.user?.language_code || "").startsWith("ar") ? "ar" : "en"),
  tab: "store",
  catalog: null,
  account: null,
  orders: null,
  filter: "all",
  search: "",
  busy: false,
};

const content = document.getElementById("appContent");
const title = document.getElementById("pageTitle");
const langButton = document.getElementById("languageButton");
const refreshButton = document.getElementById("refreshButton");
const sheet = document.getElementById("sheet");
const sheetContent = document.getElementById("sheetContent");
const toast = document.getElementById("toast");

function t(key) { return copy[state.lang][key] || key; }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]); }
function money(value) { return `$${Number(value || 0).toFixed(2)}`; }
function initData() {
  if (tg?.initData) return tg.initData;
  const search = new URLSearchParams(location.search);
  const hash = new URLSearchParams(location.hash.replace(/^#/, ""));
  return search.get("tgWebAppData") || hash.get("tgWebAppData") || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const auth = initData();
  if (auth) headers.set("X-Telegram-Init-Data", auth);
  if (options.body) headers.set("Content-Type", "application/json");
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  try {
    const response = await fetch(path, { ...options, headers, cache: "no-store", signal: controller.signal });
    const payload = await response.json().catch(() => ({ message: response.statusText }));
    if (!response.ok) {
      const error = new Error(payload.message || payload.error || response.statusText);
      error.code = payload.code || `http_${response.status}`;
      throw error;
    }
    return payload;
  } catch (error) {
    if (error?.name === "AbortError") {
      const timeoutError = new Error(t("loadError"));
      timeoutError.code = "request_timeout";
      throw timeoutError;
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function setLanguage() {
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  langButton.textContent = state.lang === "ar" ? "EN" : "AR";
  document.querySelectorAll("[data-copy]").forEach((node) => { node.textContent = t(node.dataset.copy); });
}

function showToast(message, error = false) {
  toast.textContent = message;
  toast.className = `toast${error ? " error" : ""}`;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => { toast.className = "toast hidden"; }, 3200);
}

function openSheet(html) {
  sheetContent.innerHTML = html;
  sheet.classList.remove("hidden");
  sheet.setAttribute("aria-hidden", "false");
  document.body.classList.add("sheet-open");
}

function closeSheet() {
  sheet.classList.add("hidden");
  sheet.setAttribute("aria-hidden", "true");
  document.body.classList.remove("sheet-open");
  sheetContent.replaceChildren();
}

function loadingRows(count = 5) {
  return `<div class="skeleton-list">${Array.from({ length: count }, () => '<div class="skeleton-row"><i></i><span></span><b></b></div>').join("")}</div>`;
}

function errorState(error, retry) {
  const message = error?.code?.startsWith("http_401") || /initData|api key|Unauthorized/i.test(error?.message || "") ? t("telegramRequired") : t("loadError");
  content.innerHTML = `<section class="empty-state"><strong>${esc(message)}</strong><button class="primary-button" id="retryAction">${t("retry")}</button></section>`;
  document.getElementById("retryAction")?.addEventListener("click", retry);
}

function statusLabel(status) {
  const value = String(status || "pending").toLowerCase();
  if (["success", "done", "completed"].includes(value)) return t("completed");
  if (value === "processing") return t("processingStatus");
  if (value === "refunded") return t("refunded");
  if (["failed", "cancelled"].includes(value)) return t("failed");
  if (value === "paid") return t("paid");
  return t("pending");
}

function statusClass(status) {
  const value = String(status || "").toLowerCase();
  if (["success", "done", "completed"].includes(value)) return "success";
  if (value === "processing") return "processing";
  if (value === "refunded") return "refunded";
  if (["failed", "cancelled"].includes(value)) return "failed";
  return "pending";
}

function serviceInitial(name) { return String(name || "?").trim().charAt(0).toUpperCase(); }

async function loadCatalog(force = false) {
  if (state.catalog && !force) return state.catalog;
  state.catalog = await api(`/api/v1/digital/catalog${force ? "?force=1" : ""}`);
  return state.catalog;
}

async function renderStore(force = false) {
  state.tab = "store";
  title.textContent = t("store");
  content.innerHTML = loadingRows();
  try {
    const catalog = await loadCatalog(force);
    const chips = [
      ["all", t("all")],
      ["games", t("games")],
      ...catalog.product_categories.map((row) => [`product:${row.id}`, row.label?.[state.lang] || row.label?.en || row.id]),
    ];
    const query = state.search.trim().toLowerCase();
    const games = catalog.games.filter((row) => !query || row.name.toLowerCase().includes(query));
    const products = catalog.products.filter((row) => {
      const categoryMatch = state.filter === "all" || state.filter === `product:${row.category}`;
      return categoryMatch && (!query || row.name.toLowerCase().includes(query));
    });
    const showGames = ["all", "games"].includes(state.filter) && games.length;
    const showProducts = state.filter !== "games" && products.length;
    content.innerHTML = `
      <section class="search-section">
        <label class="search-box">
          <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
          <input id="storeSearch" type="search" value="${esc(state.search)}" placeholder="${t("search")}" autocomplete="off" />
        </label>
        <div class="filter-strip">${chips.map(([key, label]) => `<button type="button" class="filter-chip${state.filter === key ? " active" : ""}" data-filter="${esc(key)}">${esc(label)}</button>`).join("")}</div>
      </section>
      ${showGames ? `<section><div class="section-heading"><h2>${t("games")}</h2><span>${games.length}</span></div><div class="service-grid">${games.map(gameCard).join("")}</div></section>` : ""}
      ${showProducts ? `<section><div class="section-heading"><h2>${t("products")}</h2><span>${products.length}</span></div><div class="service-list">${products.map(productRow).join("")}</div></section>` : ""}
      ${!showGames && !showProducts ? `<section class="empty-state"><strong>${t("noResults")}</strong></section>` : ""}
    `;
    document.getElementById("storeSearch")?.addEventListener("input", (event) => {
      state.search = event.target.value;
      window.clearTimeout(renderStore.searchTimer);
      renderStore.searchTimer = window.setTimeout(() => renderStore(), 180);
    });
    content.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => { state.filter = button.dataset.filter; renderStore(); }));
    content.querySelectorAll("[data-game]").forEach((button) => button.addEventListener("click", () => openOffers("game", button.dataset.game, button.dataset.name)));
    content.querySelectorAll("[data-product]").forEach((button) => button.addEventListener("click", () => openOffers("product", button.dataset.product, button.dataset.name)));
  } catch (error) { errorState(error, () => renderStore(true)); }
}

function gameCard(row) {
  const image = row.image_url ? `<img src="${esc(row.image_url)}" alt="" loading="lazy" />` : `<span>${esc(serviceInitial(row.name))}</span>`;
  return `<button type="button" class="game-card" data-game="${esc(row.id)}" data-name="${esc(row.name)}"><div class="game-art">${image}</div><strong>${esc(row.name)}</strong><small>${t("packages")}</small></button>`;
}

function productRow(row) {
  return `<button type="button" class="product-row" data-product="${esc(row.id)}" data-name="${esc(row.name)}">
    <span class="product-icon">${esc(serviceInitial(row.name))}</span>
    <span class="product-copy"><strong>${esc(row.name)}</strong><small>${esc(row.public_note || (row.orderable ? t("packages") : t("unavailable")))}</small></span>
    <span class="availability ${row.orderable ? "available" : ""}">${row.orderable ? t("continue") : t("unavailable")}</span>
  </button>`;
}

async function openOffers(kind, id, name) {
  openSheet(`<header class="sheet-header"><div><h2>${esc(name)}</h2><p>${t("selectPackage")}</p></div><button class="close-button" type="button" data-sheet-close>×</button></header>${loadingRows(4)}`);
  try {
    const result = await api(`/api/v1/digital/quotes?kind=${encodeURIComponent(kind)}&${kind === "game" ? "game_id" : "product_id"}=${encodeURIComponent(id)}`);
    const offers = result.offers || [];
    sheetContent.innerHTML = `
      <header class="sheet-header"><div><h2>${esc(name)}</h2><p>${t("selectPackage")}</p></div><button class="close-button" type="button" data-sheet-close>×</button></header>
      <div class="offer-list">${offers.map((offer, index) => `<button type="button" class="offer-row" data-offer="${index}">
        <span><strong>${esc(offer.name)}</strong><small>${esc(offer.duration || offer.public_note || "")}</small></span>
        <b>${esc(offer.price_label || money(offer.price))}</b>
      </button>`).join("") || `<div class="empty-state"><strong>${t("emptyPackages")}</strong></div>`}</div>
    `;
    sheetContent.querySelectorAll("[data-offer]").forEach((button) => button.addEventListener("click", () => openCheckout(kind, result, offers[Number(button.dataset.offer)])));
  } catch (error) {
    sheetContent.innerHTML = `<header class="sheet-header"><h2>${esc(name)}</h2><button class="close-button" type="button" data-sheet-close>×</button></header><div class="empty-state"><strong>${esc(error.message || t("loadError"))}</strong></div>`;
  }
}

function openCheckout(kind, result, offer) {
  const fields = kind === "game"
    ? [
        { id: "player_id", label: t("playerId"), required: true },
        { id: "server_id", label: t("serverId"), required: Boolean(offer.requires_server) },
      ]
    : (result.product?.input_fields || []);
  sheetContent.innerHTML = `
    <header class="sheet-header"><div><h2>${t("customerData")}</h2><p>${esc(offer.name)}</p></div><button class="close-button" type="button" data-sheet-close>×</button></header>
    <form id="checkoutForm" class="checkout-form">
      ${fields.map((field) => `<label><span>${esc(field.label?.[state.lang] || field.label?.en || field.label || field.id)} <em>${field.required ? t("required") : t("optional")}</em></span><input name="${esc(field.id)}" type="${field.type === "number" ? "number" : "text"}" ${field.required ? "required" : ""} autocomplete="off" /></label>`).join("")}
      <div class="order-total"><span>${t("orderTotal")}</span><strong>${esc(offer.price_label || money(offer.price))}</strong></div>
      <button class="primary-button" type="submit">${t("continue")}</button>
    </form>`;
  document.getElementById("checkoutForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    reviewOrder(kind, result, offer, values);
  });
}

function reviewOrder(kind, result, offer, values) {
  const details = Object.entries(values).filter(([, value]) => String(value).trim());
  sheetContent.innerHTML = `
    <header class="sheet-header"><div><h2>${t("reviewOrder")}</h2><p>${esc(offer.name)}</p></div><button class="close-button" type="button" data-sheet-close>×</button></header>
    <div class="review-block">
      <div><span>${t("product")}</span><strong>${esc(result.game?.name || result.product?.name || "")} · ${esc(offer.name)}</strong></div>
      ${details.map(([key, value]) => `<div><span>${esc(key.replaceAll("_", " "))}</span><strong>${esc(value)}</strong></div>`).join("")}
      <div class="review-total"><span>${t("orderTotal")}</span><strong>${esc(offer.price_label || money(offer.price))}</strong></div>
    </div>
    <p class="secure-note">${t("secureNote")}</p>
    <button class="primary-button" id="confirmOrder" type="button">${t("payNow")}</button>`;
  document.getElementById("confirmOrder").addEventListener("click", () => createOrder(kind, offer, values));
}

async function createOrder(kind, offer, values) {
  if (state.busy) return;
  state.busy = true;
  const button = document.getElementById("confirmOrder");
  button.disabled = true;
  button.textContent = t("processing");
  const body = kind === "game"
    ? { quote_token: offer.quote_token, player_id: values.player_id || "", server_id: values.server_id || "" }
    : { quote_token: offer.quote_token, customer_data: values };
  try {
    const result = await api("/api/v1/digital/orders", {
      method: "POST",
      headers: { "Idempotency-Key": `miniapp-${Date.now()}-${Math.random().toString(16).slice(2)}` },
      body: JSON.stringify(body),
    });
    state.orders = null;
    state.account = null;
    sheetContent.innerHTML = `<div class="success-state"><span>✓</span><h2>${t("success")}</h2><p>${t("orderNumber")}</p><code>${esc(result.order.id)}</code><button class="primary-button" id="openOrders">${t("viewOrders")}</button></div>`;
    document.getElementById("openOrders").addEventListener("click", () => { closeSheet(); switchTab("orders"); });
    tg?.HapticFeedback?.notificationOccurred("success");
  } catch (error) {
    button.disabled = false;
    button.textContent = t("payNow");
    showToast(t(error.code || "order_failed"), true);
    tg?.HapticFeedback?.notificationOccurred("error");
  } finally { state.busy = false; }
}

async function renderOrders(force = false) {
  state.tab = "orders";
  title.textContent = t("orders");
  content.innerHTML = loadingRows();
  try {
    if (!state.orders || force) state.orders = await api("/api/v1/digital/orders?limit=50");
    const orders = state.orders.orders || [];
    content.innerHTML = `<section class="orders-list">${orders.map(orderCard).join("") || `<div class="empty-state"><strong>${t("noOrders")}</strong></div>`}</section>`;
    content.querySelectorAll("[data-order]").forEach((button) => button.addEventListener("click", () => openOrder(button.dataset.order)));
  } catch (error) { errorState(error, () => renderOrders(true)); }
}

function orderCard(order) {
  return `<button class="order-card" type="button" data-order="${esc(order.id)}">
    <span class="order-status ${statusClass(order.public_status)}">${statusLabel(order.public_status)}</span>
    <strong>${esc(order.item_name || order.product_name || order.game_name || t("product"))}</strong>
    <small>${esc(order.created_at ? new Date(order.created_at).toLocaleString(state.lang) : "")}</small>
    <b>${esc(order.price_label || money(order.price))}</b>
  </button>`;
}

async function openOrder(orderId) {
  openSheet(`<header class="sheet-header"><h2>${t("details")}</h2><button class="close-button" type="button" data-sheet-close>×</button></header>${loadingRows(3)}`);
  try {
    const { order } = await api(`/api/v1/digital/orders/${encodeURIComponent(orderId)}`);
    const details = Object.entries(order.customer_data || {}).filter(([, value]) => String(value).trim());
    sheetContent.innerHTML = `<header class="sheet-header"><div><h2>${esc(order.item_name || t("details"))}</h2><p>${esc(order.id)}</p></div><button class="close-button" type="button" data-sheet-close>×</button></header>
      <div class="order-detail"><span class="order-status ${statusClass(order.public_status)}">${statusLabel(order.public_status)}</span>
      <dl><div><dt>${t("price")}</dt><dd>${esc(order.price_label || money(order.price))}</dd></div><div><dt>${t("created")}</dt><dd>${esc(order.created_at ? new Date(order.created_at).toLocaleString(state.lang) : "-")}</dd></div>
      ${details.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl></div>`;
  } catch (error) { showToast(error.message || t("loadError"), true); }
}

async function renderAccount(force = false) {
  state.tab = "account";
  title.textContent = t("account");
  content.innerHTML = loadingRows();
  try {
    if (!state.account || force) state.account = await api("/api/v1/digital/account");
    const data = state.account;
    content.innerHTML = `
      <section class="balance-card"><span>${t("balance")}</span><strong>${esc(data.wallet.balance_label)}</strong><small>USD wallet</small></section>
      <section class="profile-row"><span class="profile-avatar">${esc(serviceInitial(data.user.username || data.user.id))}</span><div><small>${t("username")}</small><strong>${esc(data.user.username ? `@${data.user.username}` : data.user.id)}</strong></div></section>
      <section><div class="section-heading"><h2>${t("recentActivity")}</h2></div><div class="activity-list">${(data.recent_activity || []).map(activityRow).join("") || `<div class="empty-state compact"><strong>${t("noActivity")}</strong></div>`}</div></section>`;
  } catch (error) { errorState(error, () => renderAccount(true)); }
}

function activityRow(row) {
  const positive = String(row.direction).toLowerCase() === "credit" || Number(row.amount) > 0;
  return `<div class="activity-row"><span class="activity-icon ${positive ? "credit" : "debit"}">${positive ? "+" : "−"}</span><span><strong>${esc(row.reason || t("wallet"))}</strong><small>${esc(row.created_at ? new Date(row.created_at).toLocaleString(state.lang) : "")}</small></span><b class="${positive ? "credit" : "debit"}">${positive ? "+" : "−"}${esc(row.amount_label)}</b></div>`;
}

function switchTab(tab, force = false) {
  state.tab = tab;
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  if (tab === "orders") return renderOrders(force);
  if (tab === "account") return renderAccount(force);
  return renderStore(force);
}

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.tab)));
document.addEventListener("click", (event) => { if (event.target.closest("[data-sheet-close]")) closeSheet(); });
langButton.addEventListener("click", () => {
  state.lang = state.lang === "ar" ? "en" : "ar";
  localStorage.setItem("digital-lang", state.lang);
  setLanguage();
  switchTab(state.tab);
});
refreshButton.addEventListener("click", () => switchTab(state.tab, true));

setLanguage();
switchTab("store");
