const tg = window.Telegram?.WebApp;
const params = new URLSearchParams(window.location.search);

const state = {
  lang: "ar",
  view: "buy",
  mode: "temp",
  service: "",
  country: "none",
  stateCode: "none",
  bootstrap: null,
  services: [],
  countries: [],
  states: [],
  countrySuggestions: [],
  suggestionsLoading: false,
  clientActions: {},
  offers: [],
  hasCheckedPrices: false,
  orders: [],
  account: null,
  recharge: null,
  support: { categories: [], orders: [] },
  pendingPurchase: null,
  picker: null,
  loading: false,
  viewLoading: {},
  orderFilter: "active",
};

const $ = (id) => document.getElementById(id);
const els = {
  boot: $("bootScreen"),
  balance: $("balanceLabel"),
  balanceButton: $("balanceButton"),
  menuButton: $("menuButton"),
  menuDrawer: $("menuDrawer"),
  menuClose: $("menuClose"),
  menuList: $("menuList"),
  modeSegments: $("modeSegments"),
  serviceButton: $("serviceButton"),
  serviceLabel: $("serviceLabel"),
  countryButton: $("countryButton"),
  countryLabel: $("countryLabel"),
  stateButton: $("stateButton"),
  stateLabel: $("stateLabel"),
  countrySuggestions: $("countrySuggestions"),
  checkPrices: $("checkPricesButton"),
  liveLine: $("liveLine"),
  offersCount: $("offersCount"),
  offerList: $("offerList"),
  bottomNav: $("bottomNav"),
  ordersList: $("ordersList"),
  orderFilters: $("orderFilters"),
  refreshOrders: $("refreshOrdersButton"),
  rechargeContent: $("rechargeContent"),
  rechargeForm: $("rechargeForm"),
  rechargeMethod: $("rechargeMethod"),
  rechargeMethodDetails: $("rechargeMethodDetails"),
  rechargeAmount: $("rechargeAmount"),
  rechargeProof: $("rechargeProof"),
  rechargeStatus: $("rechargeStatus"),
  accountContent: $("accountContent"),
  supportForm: $("supportForm"),
  supportCategory: $("supportCategory"),
  supportOrder: $("supportOrder"),
  supportMessage: $("supportMessage"),
  supportStatus: $("supportStatus"),
  pickerDrawer: $("pickerDrawer"),
  drawerTitle: $("drawerTitle"),
  drawerClose: $("drawerClose"),
  drawerSearch: $("drawerSearch"),
  drawerList: $("drawerList"),
  confirmDrawer: $("confirmDrawer"),
  confirmClose: $("confirmClose"),
  confirmBody: $("confirmBody"),
  confirmPurchase: $("confirmPurchaseButton"),
  toast: $("toast"),
  busyOverlay: $("busyOverlay"),
  busyTitle: $("busyTitle"),
};

const labels = {
  temp: "مؤقت",
  rental: "إيجار",
  voice: "اتصال",
  buy: "شراء",
  orders: "طلباتي",
  recharge: "شحن",
  account: "حسابي",
  support: "الدعم",
};

const providerAliases = [
  ["S1", "Alpha"],
  ["S2", "Bravo"],
  ["S3", "Charlie"],
  ["S4", "Delta"],
  ["S5", "Echo"],
  ["S6", "Foxtrot"],
  ["S7", "Golf"],
  ["S8", "Hotel"],
  ["S9", "India"],
  ["S10", "Juliet"],
];

const aliasById = Object.fromEntries(providerAliases);
const prefsKey = "phantom_numbers_v2_prefs_country_required";
const suggestedRegionIsos = new Set([
  "US", "GB", "IE", "FR", "DE", "NL", "BE", "LU", "CH", "AT", "IT", "ES", "PT",
  "SE", "NO", "DK", "FI", "IS", "PL", "CZ", "SK", "HU", "RO", "BG", "GR",
  "HR", "SI", "RS", "BA", "ME", "MK", "AL", "XK", "EE", "LV", "LT", "UA",
  "MD", "BY", "MT", "CY",
]);

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(prefsKey) || "{}") || {};
  } catch (_error) {
    return {};
  }
}

function savePrefs() {
  const payload = {
    mode: state.mode,
    service: state.service,
    country: state.country,
    stateCode: state.stateCode,
  };
  try {
    localStorage.setItem(prefsKey, JSON.stringify(payload));
  } catch (_error) {
    // Telegram WebView storage can be unavailable in strict privacy modes.
  }
}

function applyRuntimeTheme() {
  const scheme = String(tg?.colorScheme || "").toLowerCase();
  const bg = String(tg?.themeParams?.bg_color || "").toLowerCase();
  const darkBg = /^#(?:0[0-9a-f]|1[0-9a-f]|2[0-9a-f])/.test(bg);
  document.body.classList.toggle("telegram-dark", scheme === "dark" || darkBg || params.get("theme") === "dark");
}

function headers(extra = {}) {
  const base = { ...extra };
  const initData = tg?.initData || params.get("initData") || "";
  if (initData) base["X-Telegram-Init-Data"] = initData;
  return base;
}

function actionFor(key, fallback, method = "GET") {
  const action = state.clientActions?.[key] || {};
  return {
    endpoint: action.endpoint || fallback,
    method: action.method || method,
    enabled: action.enabled !== false,
  };
}

function mergeActions(payload) {
  if (payload?.actions && typeof payload.actions === "object") {
    state.clientActions = { ...state.clientActions, ...payload.actions };
  }
}

function labelForKey(key) {
  return {
    buy: "شراء",
    tabBuy: "شراء",
    orders: "طلباتي",
    tabOrders: "طلباتي",
    recharge: "شحن",
    tabRecharge: "شحن",
    account: "حسابي",
    tabAccount: "حسابي",
    support: "الدعم",
    tabSupport: "الدعم",
    copy_number: "نسخ الرقم",
    copy_code: "نسخ الكود",
    refresh: "تحديث",
    second_code: "كود ثاني",
    replace: "رقم بديل",
    alternate_provider: "مزود بديل",
    preview_recording: "استماع",
    download_recording: "تحميل",
    rental_sms: "الرسائل",
    rental_renew: "تجديد",
    rental_wake: "تنشيط",
    rental_notes: "ملاحظات",
    rental_finish: "إنهاء",
    working: "جاري التنفيذ",
    checkingOrder: "جاري التحديث",
    checkCall: "فحص المكالمة",
  }[key] || labels[key] || key;
}

let toastTimer = null;

function showToast(message, tone = "info") {
  if (!message || !els.toast) return;
  window.clearTimeout(toastTimer);
  els.toast.textContent = message;
  els.toast.className = `toast toast-${tone}`;
  toastTimer = window.setTimeout(() => els.toast.classList.add("hidden"), 3200);
}

function showBusy(title = labelForKey("working")) {
  if (!els.busyOverlay) return;
  els.busyTitle.textContent = title;
  els.busyOverlay.classList.remove("hidden");
}

function hideBusy() {
  els.busyOverlay?.classList.add("hidden");
}

function friendlyError(error) {
  const payload = error?.payload || {};
  const code = payload.code || payload.error_code || "";
  if (code === "insufficient_balance") return "الرصيد غير كاف. اشحن رصيدك ثم أعد المحاولة.";
  if (code === "quote_expired") return "انتهت صلاحية السعر. افحص الأسعار مرة أخرى.";
  if (code === "invalid_quote") return "العرض لم يعد متاحاً. افحص الأسعار مرة أخرى.";
  if (code === "telegram_auth_required") return "افتح الميني أب من داخل Telegram لتنفيذ هذا الإجراء.";
  return payload.message || payload.error || error?.message || "تعذر تنفيذ العملية";
}

async function api(endpoint, options = {}) {
  const requestHeaders = headers(options.headers || {});
  let body;
  if (options.body instanceof FormData) {
    body = options.body;
  } else if (options.body) {
    requestHeaders["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  const response = await fetch(endpoint, {
    method: options.method || "GET",
    headers: requestHeaders,
    body,
    signal: options.signal,
  });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (_error) {
    payload = { ok: false, message: text };
  }
  if (!response.ok) {
    const error = new Error(payload.message || payload.error || text || `HTTP ${response.status}`);
    error.payload = payload;
    error.status = response.status;
    throw error;
  }
  return payload;
}

function formatProvider(row, index) {
  const id = row.provider_id || row.public_provider_id || row.provider_code || providerAliases[index]?.[0] || `S${index + 1}`;
  return {
    id,
    name: row.provider_name || row.public_provider_name || aliasById[id] || providerAliases[index]?.[1] || "Provider",
  };
}

function serviceLabel(key) {
  return state.services.find((item) => item.key === key)?.label || state.services.find((item) => item.code === key)?.name || key || "اختر الخدمة";
}

function countryLabel(code) {
  if (String(code) === "1") return "الولايات المتحدة · US";
  if (String(code) === "none") return "اختر الدولة";
  const row = state.countries.find((item) => String(item.code) === String(code));
  return row ? `${row.name} · ${row.iso || row.code}` : "اختر الدولة";
}

function stateLabel(code) {
  if (String(code) === "none") return "أي ولاية";
  const row = state.states.find((item) => String(item.code) === String(code));
  return row?.name || "أي ولاية";
}

function countryIso(code) {
  const row = state.countries.find((item) => String(item.code) === String(code));
  return String(row?.iso || "").toUpperCase();
}

function isFastSuggestionCountry(row) {
  const code = String(row?.code || "");
  const iso = String(row?.iso || countryIso(code)).toUpperCase();
  return suggestedRegionIsos.has(iso);
}

function setBusy(button, busy) {
  if (!button) return;
  button.disabled = busy;
}

function emptyState(text) {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  return div;
}

function loadingStack(count = 3) {
  return Array.from({ length: count }, () => {
    const card = document.createElement("article");
    card.className = "info-card skeleton-panel";
    card.innerHTML = `<span></span><span></span><span></span>`;
    return card;
  });
}

function setViewLoading(view, busy) {
  state.viewLoading[view] = busy;
}

function renderModes() {
  const modes = state.bootstrap?.modes || [
    { key: "temp", label: labels.temp },
    { key: "rental", label: labels.rental },
    { key: "voice", label: labels.voice },
  ];
  els.modeSegments.replaceChildren(
    ...modes.map((mode) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `segment${state.mode === mode.key ? " active" : ""}`;
      button.textContent = labels[mode.key] || mode.label || mode.key;
      button.addEventListener("click", () => {
        state.mode = mode.key;
        if (state.mode === "voice") state.country = "1";
        state.countrySuggestions = [];
        clearPriceResults();
        savePrefs();
        renderBuy();
        if (state.service && state.country === "none") loadCountrySuggestions();
      });
      return button;
    })
  );
}

function renderBuy() {
  renderModes();
  els.serviceLabel.textContent = serviceLabel(state.service);
  els.countryLabel.textContent = state.mode === "voice" ? "الولايات المتحدة · US" : countryLabel(state.country);
  els.stateLabel.textContent = state.country === "1" ? stateLabel(state.stateCode) : "غير متاح";
  const showState = state.country === "1";
  els.stateButton.disabled = !showState;
  els.stateButton.classList.toggle("hidden", !showState);
  els.countryButton.parentElement?.classList.toggle("state-hidden", !showState);
  renderCountrySuggestions();
  renderOffers();
}

function renderCountrySuggestions() {
  if (!els.countrySuggestions) return;
  const rows = state.service && state.mode !== "voice" && state.country === "none"
    ? (state.countrySuggestions || []).filter(isFastSuggestionCountry).slice(0, 6)
    : [];
  if (!rows.length) {
    els.countrySuggestions.classList.add("hidden");
    els.countrySuggestions.replaceChildren();
    return;
  }
  els.countrySuggestions.classList.remove("hidden");
  els.countrySuggestions.replaceChildren(...rows.map((row) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "suggestion-chip";
    button.textContent = [countryLabel(row.code), row.price_label].filter(Boolean).join(" · ");
    button.addEventListener("click", () => {
      state.country = row.code || "none";
      state.stateCode = state.country === "1" ? state.stateCode : "none";
      clearPriceResults();
      savePrefs();
      renderBuy();
    });
    return button;
  }));
}

function normalizedOffers() {
  const rows = [];
  (state.offers || []).forEach((row) => {
    if (Array.isArray(row.options) && row.options.length) {
      row.options.forEach((option) => {
        rows.push({
          ...row,
          ...option,
          provider_id: row.provider_id,
          provider_name: row.provider_name,
          option_label: option.duration_label || option.label,
          purchase_action: option.purchase_action || row.purchase_action,
        });
      });
      return;
    }
    rows.push(row);
  });
  return rows;
}

function renderOffers() {
  const rows = normalizedOffers();
  els.offersCount.textContent = state.loading ? "جاري الفحص" : `${rows.length} عروض`;
  if (state.loading) {
    els.offerList.replaceChildren(...Array.from({ length: 4 }, () => {
      const card = document.createElement("article");
      card.className = "offer-card skeleton-card";
      card.innerHTML = `<span></span><span></span><span></span><span></span>`;
      return card;
    }));
    return;
  }
  if (!rows.length) {
    const emptyMessage = !state.hasCheckedPrices
      ? (state.service ? "اختر الدولة ثم افحص الأسعار" : "اختر خدمة ثم دولة لعرض الأسعار")
      : "لا توجد عروض متاحة لهذه الخيارات";
    const empty = emptyState(emptyMessage);
    if (!state.service) {
      const button = document.createElement("button");
      button.className = "inline-action";
      button.type = "button";
      button.textContent = "اختيار الخدمة";
      button.addEventListener("click", () => openPicker("service"));
      empty.append(button);
    }
    els.offerList.replaceChildren(empty);
    return;
  }
  els.offerList.replaceChildren(
    ...rows.map((row, index) => {
      const provider = formatProvider(row, index);
      const card = document.createElement("article");
      card.className = `offer-card${row.recommended || index === 0 ? " recommended" : ""}`;

      const buy = document.createElement("button");
      buy.className = "offer-buy";
      buy.type = "button";
      buy.textContent = "شراء";
      buy.disabled = row.available === false || row.purchase_action?.enabled === false;
      buy.addEventListener("click", () => openConfirm(row));

      const rate = document.createElement("div");
      rate.className = "offer-rate";
      rate.textContent = `${row.success_rate || row.successRate || "98%"}\nنجاح`;

      const price = document.createElement("div");
      price.className = "offer-price";
      price.textContent = row.price_label || row.priceLabel || "$0.00";

      const providerEl = document.createElement("div");
      providerEl.className = "offer-provider";
      providerEl.innerHTML = `<strong>${provider.id}</strong><small>${row.option_label || provider.name}</small>`;

      if (row.recommended || index === 0 || row.available === false) {
        const tag = document.createElement("em");
        tag.className = `offer-tag${row.available === false ? " unavailable" : ""}`;
        tag.textContent = row.available === false ? "غير متاح" : "مقترح";
        providerEl.append(tag);
      }
      card.append(buy, rate, price, providerEl);
      return card;
    })
  );
}

function openPicker(kind) {
  const configs = {
    service: {
      kind: "service",
      title: "اختر الخدمة",
      rows: state.services.map((row) => ({ key: row.key || row.code, title: row.label || row.name || row.key, sub: row.category || "" })),
      onSelect: (key) => { state.service = key; clearPriceResults(); },
    },
    country: {
      kind: "country",
      title: "اختر الدولة",
      rows: countryPickerRows(),
      onSelect: (key) => { state.country = key; if (key !== "1") state.stateCode = "none"; clearPriceResults(); },
    },
    state: {
      kind: "state",
      title: "اختر الولاية",
      rows: state.states.map((row) => ({ key: row.code, title: row.name, sub: row.code })),
      onSelect: (key) => { state.stateCode = key; clearPriceResults(); },
    },
  };
  state.picker = configs[kind];
  els.drawerTitle.textContent = state.picker.title;
  els.drawerSearch.value = "";
  renderPickerOptions();
  els.pickerDrawer.classList.remove("hidden");
  if (kind === "country") loadCountrySuggestions();
  els.drawerSearch.focus();
}

function renderPickerOptions() {
  const query = els.drawerSearch.value.trim().toLowerCase();
  const rows = (state.picker?.rows || []).filter((row) => `${row.title} ${row.sub}`.toLowerCase().includes(query));
  els.drawerList.replaceChildren(
    ...rows.slice(0, 80).map((row) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `picker-option${row.suggested ? " suggested" : ""}`;
      button.innerHTML = `${row.title}${row.sub ? `<small>${row.sub}</small>` : ""}`;
      button.addEventListener("click", () => {
        const selectedKind = state.picker?.kind;
        state.picker.onSelect(row.key);
        savePrefs();
        closePicker();
        renderBuy();
        if (selectedKind === "service") loadCountrySuggestions();
      });
      return button;
    })
  );
}

function closePicker() {
  state.picker = null;
  els.pickerDrawer.classList.add("hidden");
}

function countryPickerRows() {
  const seen = new Set();
  const suggestions = (state.countrySuggestions || []).map((row) => {
    const key = String(row.code || "");
    if (!isFastSuggestionCountry({ ...row, code: key })) return null;
    seen.add(key);
    return {
      key,
      title: countryLabel(key),
      sub: ["مقترح", row.price_label].filter(Boolean).join(" · "),
      suggested: true,
    };
  }).filter(Boolean);
  const countries = state.countries
    .filter((row) => !seen.has(String(row.code || "")))
    .map((row) => ({ key: row.code, title: countryLabel(row.code), sub: row.price_label || "" }));
  return [...suggestions, ...countries];
}

async function loadCountrySuggestions() {
  if (!state.service || state.mode === "voice") {
    state.countrySuggestions = [];
    state.suggestionsLoading = false;
    if (state.picker?.kind === "country") {
      state.picker.rows = countryPickerRows();
      renderPickerOptions();
    }
    return;
  }
  state.suggestionsLoading = true;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 4500);
  try {
    const action = actionFor("country_suggestions", "/mini/numbers/api/country-suggestions");
    const qs = new URLSearchParams({
      mode: state.mode,
      service: state.service,
      _: String(Date.now()),
    });
    const payload = await api(`${action.endpoint}?${qs}`, { signal: controller.signal });
    mergeActions(payload);
    state.countrySuggestions = (payload.countries || []).filter(isFastSuggestionCountry);
  } catch (_error) {
    state.countrySuggestions = [];
  } finally {
    window.clearTimeout(timeout);
    state.suggestionsLoading = false;
    if (state.picker?.kind === "country") {
      state.picker.rows = countryPickerRows();
      renderPickerOptions();
    }
    renderCountrySuggestions();
  }
}

function clearPriceResults() {
  state.offers = [];
  state.hasCheckedPrices = false;
}

async function checkPrices() {
  if (!state.service) {
    els.liveLine.textContent = "اختر خدمة أولا";
    openPicker("service");
    return;
  }
  if (state.mode !== "voice" && state.country === "none") {
    els.liveLine.textContent = "اختر الدولة أولا";
    openPicker("country");
    return;
  }
  setBusy(els.checkPrices, true);
  state.loading = true;
  state.hasCheckedPrices = true;
  els.liveLine.textContent = "جاري فحص المزودين";
  state.offers = [];
  renderOffers();
  try {
    const action = actionFor("prices", "/mini/numbers/api/prices");
    const qs = new URLSearchParams({
      mode: state.mode,
      service: state.service,
      country: state.mode === "voice" ? "1" : state.country,
      state: state.country === "1" ? state.stateCode : "none",
      _: String(Date.now()),
    });
    const payload = await api(`${action.endpoint}?${qs}`);
    state.offers = payload.providers || [];
    els.liveLine.textContent = state.offers.length ? "أسعار محدثة · quote TTL 5 دقائق" : (payload.message || "لا توجد عروض متاحة");
  } catch (error) {
    els.liveLine.textContent = friendlyError(error);
    showToast(friendlyError(error), "danger");
  } finally {
    state.loading = false;
    setBusy(els.checkPrices, false);
    renderOffers();
  }
}

function openConfirm(row) {
  state.pendingPurchase = row;
  const provider = formatProvider(row, normalizedOffers().indexOf(row));
  els.confirmBody.replaceChildren();
  const card = document.createElement("div");
  card.className = "info-card";
  card.innerHTML = `
    <h3>${serviceLabel(state.service)}</h3>
    <div class="meta-grid">
      <div><span>المزود</span><strong>${provider.id} · ${provider.name}</strong></div>
      <div><span>السعر</span><strong>${row.price_label || "$0.00"}</strong></div>
      <div><span>النجاح</span><strong>${row.success_rate || "غير محدد"}</strong></div>
      ${row.option_label ? `<div><span>المدة</span><strong>${row.option_label}</strong></div>` : ""}
    </div>
  `;
  els.confirmBody.append(card);
  els.confirmDrawer.classList.remove("hidden");
}

function closeConfirm() {
  state.pendingPurchase = null;
  els.confirmDrawer.classList.add("hidden");
}

async function confirmPurchase() {
  const row = state.pendingPurchase;
  if (!row) return;
  const action = row.purchase_action || actionFor("purchase", "/mini/numbers/api/purchase", "POST");
  setBusy(els.confirmPurchase, true);
  showBusy(labelForKey(action.busy_label_key || "working"));
  try {
    const payload = await api(action.endpoint, {
      method: action.method || "POST",
      body: action.body || { quote_token: row.quote_token },
      headers: action.idempotency_key ? { "Idempotency-Key": action.idempotency_key } : {},
    });
    closeConfirm();
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
    mergeActions(payload);
    showToast(payload.message || "تم إنشاء الطلب", "success");
    await loadOrders();
    setView("orders");
  } catch (error) {
    showToast(friendlyError(error), "danger");
  } finally {
    hideBusy();
    setBusy(els.confirmPurchase, false);
  }
}

function statusLabel(order) {
  const customerState = order.customer_state || {};
  if (customerState.status_label) return customerState.status_label;
  const status = order.public_status || order.status || "";
  return {
    waiting: "بانتظار الكود",
    code_received: "تم استلام الكود",
    refunded: "تم الاسترجاع",
    refund_pending: "استرجاع قيد المعالجة",
    waiting_for_call: "بانتظار المكالمة",
    waiting_for_recording: "بانتظار التسجيل",
    finished: "منتهي",
  }[status] || status || "نشط";
}

function customerStateText(order) {
  const customerState = order.customer_state || {};
  const key = customerState.key || order.public_status || "";
  const map = {
    awaiting_provider_webhook: "بانتظار وصول الكود من المزود عبر webhook. الاسترجاع تلقائي إذا انتهت المهلة.",
    code_received: "وصل الكود. انسخه وأكمل عملية التحقق.",
    refund_pending: "الاسترجاع قيد المعالجة من السيرفر.",
    support_review_pending: "الحالة تحتاج مراجعة الدعم.",
    refunded: "تم إرجاع المبلغ للمحفظة.",
    waiting_for_recording: "تم رصد المكالمة وننتظر التسجيل.",
    call_received: "تم استلام المكالمة.",
  };
  return map[key] || customerState.message || customerState.message_key || "";
}

function orderTone(order) {
  const tone = order.customer_state?.tone || order.public_status || "";
  if (String(tone).includes("refund")) return "refund";
  if (String(tone).includes("success") || order.code) return "success";
  if (String(tone).includes("danger")) return "danger";
  return "waiting";
}

function orderBucket(order) {
  const status = String(order.customer_state?.key || order.public_status || order.status || "").toLowerCase();
  if (status.includes("refund")) return "refund";
  if (status.includes("finished") || status.includes("expired") || status.includes("cancel")) return "closed";
  return "active";
}

function renderOrderFilters() {
  const rows = state.orders || [];
  const counts = {
    all: rows.length,
    active: rows.filter((order) => orderBucket(order) === "active").length,
    refund: rows.filter((order) => orderBucket(order) === "refund").length,
    closed: rows.filter((order) => orderBucket(order) === "closed").length,
  };
  const filters = [
    ["active", "نشطة"],
    ["all", "الكل"],
    ["refund", "استرجاع"],
    ["closed", "منتهية"],
  ];
  els.orderFilters.replaceChildren(...filters.map(([key, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = state.orderFilter === key ? "active" : "";
    button.textContent = `${label} ${counts[key]}`;
    button.addEventListener("click", () => {
      state.orderFilter = key;
      renderOrders();
    });
    return button;
  }));
}

function renderOrders() {
  if (state.viewLoading.orders) {
    renderOrderFilters();
    els.ordersList.replaceChildren(...loadingStack(3));
    return;
  }
  renderOrderFilters();
  const allRows = state.orders || [];
  const rows = state.orderFilter === "all" ? allRows : allRows.filter((order) => orderBucket(order) === state.orderFilter);
  if (!rows.length) {
    const messages = {
      active: "لا توجد طلبات نشطة حاليا",
      refund: "لا توجد طلبات استرجاع حاليا",
      closed: "لا توجد طلبات منتهية حاليا",
      all: "لا توجد طلبات حاليا",
    };
    els.ordersList.replaceChildren(emptyState(messages[state.orderFilter] || messages.all));
    return;
  }
  els.ordersList.replaceChildren(
    ...rows.map((order) => {
      const card = document.createElement("article");
      card.className = `order-card order-${orderTone(order)}`;
      const note = customerStateText(order);
      const details = Array.isArray(order.details) ? order.details.slice(0, 4) : [];
      card.innerHTML = `
        <h3>${order.service_label || order.service || "طلب رقم"}</h3>
        <div class="meta-grid">
          <div><span>الحالة</span><strong>${statusLabel(order)}</strong></div>
          <div><span>الرقم</span><strong>${order.number || order.provider_number || "-"}</strong></div>
          <div><span>السعر</span><strong>${order.price_label || "-"}</strong></div>
          ${details.map((item) => `<div><span>${item.label || item.key || ""}</span><strong>${item.value || "-"}</strong></div>`).join("")}
        </div>
      `;
      if (note) {
        const stateNote = document.createElement("p");
        stateNote.className = "status-text";
        stateNote.textContent = note;
        card.append(stateNote);
      }
      if (order.code) {
        const code = document.createElement("div");
        code.className = "code-box";
        code.textContent = order.code;
        card.append(code);
      }
      const events = Array.isArray(order.events) ? order.events.slice(0, 5) : [];
      if (events.length) {
        const timeline = document.createElement("div");
        timeline.className = "timeline";
        timeline.innerHTML = events.map((event) => `
          <div class="timeline-row">
            <span></span>
            <strong>${event.label || event.event || "تحديث"}</strong>
            <small>${event.time || ""}</small>
          </div>
        `).join("");
        card.append(timeline);
      }
      const actions = order.actions || {};
      const actionRow = document.createElement("div");
      actionRow.className = "action-row";
      ["copy_number", "copy_code", "refresh", "second_code", "replace", "alternate_provider", "preview_recording", "download_recording", "rental_sms", "rental_finish", "rental_renew", "rental_wake", "rental_notes"].forEach((key) => {
        const action = actions[key];
        if (!action || action.enabled === false) return;
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = action.label || labelForKey(action.label_key || key);
        button.addEventListener("click", () => runOrderAction(order, key, button));
        actionRow.append(button);
      });
      if (actionRow.children.length) card.append(actionRow);
      return card;
    })
  );
}

async function runOrderAction(order, key, button) {
  const action = order.actions?.[key];
  if (action?.confirm_label_key && !window.confirm(labelForKey(action.confirm_label_key))) return;
  if (action?.method === "CLIENT") {
    const value = key === "copy_code" ? order.code : (order.number || order.provider_number || "");
    if (value) await navigator.clipboard?.writeText(value);
    showToast("تم النسخ", "success");
    return;
  }
  if (!action?.endpoint) return;
  setBusy(button, true);
  showBusy(labelForKey(action.busy_label_key || "working"));
  try {
    const payload = await api(action.endpoint, {
      method: action.method || "POST",
      body: action.body || {},
      headers: action.idempotency_key ? { "Idempotency-Key": action.idempotency_key } : {},
    });
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
    mergeActions(payload);
    showToast(payload.message || "تم تحديث الطلب", "success");
    await loadOrders();
  } catch (error) {
    showToast(friendlyError(error), "danger");
  } finally {
    hideBusy();
    setBusy(button, false);
  }
}

async function loadOrders() {
  setViewLoading("orders", true);
  renderOrders();
  try {
    const action = actionFor("orders", "/mini/numbers/api/orders");
    const payload = await api(action.endpoint);
    mergeActions(payload);
    state.orders = payload.orders || [];
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
  } catch (_error) {
    state.orders = [];
    showToast("تعذر تحميل الطلبات", "danger");
  } finally {
    setViewLoading("orders", false);
  }
  renderOrders();
  renderSupportOrders();
}

function renderAccount() {
  if (state.viewLoading.account) {
    els.accountContent.replaceChildren(...loadingStack(3));
    return;
  }
  const payload = state.account;
  if (!payload?.user) {
    els.accountContent.replaceChildren(emptyState("افتح التطبيق من Telegram لعرض الحساب"));
    return;
  }
  const hero = document.createElement("section");
  hero.className = "account-hero";
  const activeOrders = (state.orders || []).length;
  const rechargeRequests = (state.recharge?.requests || []).length;
  hero.innerHTML = `
    <span>الرصيد المتاح</span>
    <strong>${payload.balance_label || "-"}</strong>
    <p>${payload.user.username ? `@${payload.user.username}` : "Telegram Mini App"}</p>
  `;
  const actions = document.createElement("div");
  actions.className = "quick-actions";
  [
    ["شراء رقم", "buy"],
    ["طلباتي", "orders"],
    ["شحن الرصيد", "recharge"],
    ["الدعم", "support"],
  ].forEach(([label, view]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => setView(view));
    actions.append(button);
  });
  els.accountContent.replaceChildren(
    hero,
    actions,
    infoCard("الطلبات النشطة", String(activeOrders)),
    infoCard("طلبات الشحن", String(rechargeRequests)),
    infoCard("User ID", String(payload.user.id || "-")),
    infoCard("اللغة", payload.user.language_label || payload.user.language || "-")
  );
}

function infoCard(title, value) {
  const card = document.createElement("div");
  card.className = "info-card";
  card.innerHTML = `<h3>${title}</h3><div class="meta-grid"><div><span></span><strong>${value}</strong></div></div>`;
  return card;
}

async function loadAccount() {
  setViewLoading("account", true);
  renderAccount();
  try {
    const action = actionFor("account", "/mini/numbers/api/account");
    state.account = await api(action.endpoint);
    mergeActions(state.account);
    if (state.account.balance_label) els.balance.textContent = state.account.balance_label;
    state.recharge = state.account.recharge || state.recharge;
    state.support.categories = state.account.support_categories || state.support.categories;
  } catch (_error) {
    state.account = null;
    showToast("تعذر تحميل الحساب", "danger");
  } finally {
    setViewLoading("account", false);
  }
  renderAccount();
  renderRecharge();
  renderSupportCategories();
}

function renderRecharge() {
  if (state.viewLoading.recharge) {
    els.rechargeForm.classList.add("hidden");
    els.rechargeContent.replaceChildren(...loadingStack(3));
    return;
  }
  const payload = state.recharge;
  if (!payload) {
    els.rechargeContent.replaceChildren(emptyState("افتح التطبيق من Telegram لشحن الرصيد"));
    return;
  }
  const methods = payload.methods || [];
  const requests = payload.requests || [];
  renderRechargeForm(methods);
  const cards = [
    ...methods.map((method) => {
      const card = document.createElement("div");
      card.className = "method-card";
      card.innerHTML = `<h3>${method.title || method.code || "طريقة دفع"}</h3><div class="meta-grid"><div><span>التفاصيل</span><strong>${method.target || "-"}</strong></div><div><span>السعر</span><strong>${method.rate_label || "-"}</strong></div></div>`;
      return card;
    }),
    ...requests.slice(0, 4).map((request) => infoCard(request.status_label || "طلب شحن", request.credits_label || request.paid_label || "-")),
  ];
  els.rechargeContent.replaceChildren(...(cards.length ? cards : [emptyState("لا توجد طلبات شحن سابقة")]));
}

async function loadRecharge() {
  setViewLoading("recharge", true);
  renderRecharge();
  try {
    const action = actionFor("recharge", "/mini/numbers/api/recharge");
    const payload = await api(action.endpoint);
    mergeActions(payload);
    state.recharge = payload.recharge || payload;
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
  } catch (_error) {
    state.recharge = null;
    showToast("تعذر تحميل الشحن", "danger");
  } finally {
    setViewLoading("recharge", false);
  }
  renderRecharge();
}

function renderRechargeForm(methods = []) {
  if (!methods.length) {
    els.rechargeForm.classList.add("hidden");
    return;
  }
  els.rechargeForm.classList.remove("hidden");
  const current = els.rechargeMethod.value;
  els.rechargeMethod.replaceChildren(
    ...methods.map((method) => {
      const option = document.createElement("option");
      option.value = method.code || "";
      option.textContent = method.title || method.code || "-";
      option.selected = option.value === current;
      return option;
    })
  );
  updateRechargeMethodDetails();
}

function selectedRechargeMethod() {
  const methods = state.recharge?.methods || [];
  return methods.find((method) => String(method.code || "") === String(els.rechargeMethod.value || "")) || methods[0] || null;
}

function updateRechargeMethodDetails() {
  const method = selectedRechargeMethod();
  if (!method) {
    els.rechargeMethodDetails.replaceChildren();
    return;
  }
  els.rechargeAmount.placeholder = method.currency || "USD";
  els.rechargeMethodDetails.innerHTML = `
    <p>الوجهة: <strong>${method.target || "-"}</strong></p>
    <p>السعر: <strong>${method.rate_label || "-"}</strong></p>
    ${method.instructions ? `<p>${method.instructions}</p>` : ""}
  `;
}

async function submitRecharge(event) {
  event.preventDefault();
  const method = selectedRechargeMethod();
  if (!method) return;
  els.rechargeStatus.textContent = "";
  const amount = Number(els.rechargeAmount.value || 0);
  if (!Number.isFinite(amount) || amount <= 0) {
    els.rechargeStatus.textContent = "أدخل مبلغ شحن صحيح";
    showToast(els.rechargeStatus.textContent, "danger");
    return;
  }
  const action = actionFor("submit_recharge", "/mini/numbers/api/recharge/submit", "POST");
  const formData = new FormData();
  formData.append("method_code", method.code || "");
  formData.append("paid_amount", String(amount));
  const file = els.rechargeProof.files?.[0];
  if (file) formData.append("proof", file);
  const button = els.rechargeForm.querySelector("button[type='submit']");
  setBusy(button, true);
  showBusy("إرسال طلب الشحن");
  try {
    const payload = await api(action.endpoint, { method: action.method || "POST", body: formData });
    mergeActions(payload);
    state.recharge = payload.recharge || state.recharge;
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
    els.rechargeAmount.value = "";
    els.rechargeProof.value = "";
    els.rechargeStatus.textContent = payload.message || "تم إرسال طلب الشحن";
    showToast(els.rechargeStatus.textContent, "success");
    renderRecharge();
  } catch (error) {
    els.rechargeStatus.textContent = friendlyError(error);
    showToast(els.rechargeStatus.textContent, "danger");
  } finally {
    hideBusy();
    setBusy(button, false);
  }
}

function renderSupportCategories() {
  if (state.viewLoading.support) {
    els.supportCategory.replaceChildren(new Option("جاري التحميل", ""));
    return;
  }
  const categories = state.support.categories || [];
  els.supportCategory.replaceChildren(
    ...(categories.length ? categories : [{ key: "numbers", label: "Numbers orders" }]).map((item) => {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = item.label;
      return option;
    })
  );
}

function renderNav() {
  const tabs = state.bootstrap?.client?.tabs || [
    { key: "buy", label_key: "tabBuy", icon: "bag" },
    { key: "orders", label_key: "tabOrders", icon: "list" },
    { key: "recharge", label_key: "recharge", icon: "card" },
    { key: "account", label_key: "account", icon: "user" },
    { key: "support", label_key: "support", icon: "help" },
  ];
  const iconMap = { buy: "bag", orders: "list", recharge: "card", account: "user", support: "help" };
  const navTarget = els.menuList || els.bottomNav;
  if (!navTarget) return;
  navTarget.replaceChildren(
    ...tabs.filter((tab) => tab.enabled !== false).map((tab) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `menu-item${state.view === tab.key ? " active" : ""}`;
      button.dataset.view = tab.key;
      const icon = iconMap[tab.icon] || iconMap[tab.key] || tab.icon || tab.key;
      button.innerHTML = `<span class="nav-icon ${icon}"></span><span>${tab.label || labelForKey(tab.label_key || tab.key)}</span>`;
      return button;
    })
  );
}

function openMenu() {
  els.menuDrawer?.classList.remove("hidden");
  els.menuButton?.setAttribute("aria-expanded", "true");
}

function closeMenu() {
  els.menuDrawer?.classList.add("hidden");
  els.menuButton?.setAttribute("aria-expanded", "false");
}

function renderSupportOrders() {
  const rows = state.orders || [];
  const options = [new Option("بدون طلب محدد", "")];
  rows.slice(0, 12).forEach((order) => {
    options.push(new Option([order.service_label, order.number, statusLabel(order)].filter(Boolean).join(" · "), order.id || ""));
  });
  els.supportOrder.replaceChildren(...options);
}

async function loadSupport() {
  setViewLoading("support", true);
  renderSupportCategories();
  try {
    const action = actionFor("support", "/mini/numbers/api/support");
    const payload = await api(action.endpoint);
    mergeActions(payload);
    state.support.categories = payload.categories || [];
  } catch (_error) {
    state.support.categories = [];
    showToast("تعذر تحميل الدعم", "danger");
  } finally {
    setViewLoading("support", false);
  }
  renderSupportCategories();
  renderSupportOrders();
}

async function submitSupport(event) {
  event.preventDefault();
  els.supportStatus.textContent = "";
  if (!headers()["X-Telegram-Init-Data"]) {
    els.supportStatus.textContent = "افتح التطبيق من Telegram لإرسال تذكرة دعم";
    showToast(els.supportStatus.textContent, "danger");
    return;
  }
  const rawMessage = els.supportMessage.value.trim();
  if (rawMessage.length < 6) {
    els.supportStatus.textContent = "اكتب وصفاً أوضح للمشكلة";
    showToast(els.supportStatus.textContent, "danger");
    return;
  }
  const orderId = els.supportOrder.value;
  const order = state.orders.find((item) => String(item.id || "") === String(orderId));
  const context = order ? [`Order: ${order.id}`, order.service_label ? `Service: ${order.service_label}` : "", order.number ? `Number: ${order.number}` : ""].filter(Boolean).join("\n") : "";
  const message = [context, rawMessage].filter(Boolean).join("\n\n");
  const button = els.supportForm.querySelector("button[type='submit']");
  setBusy(button, true);
  showBusy("إرسال التذكرة");
  try {
    const action = actionFor("submit_support_ticket", "/mini/numbers/api/support/ticket", "POST");
    const payload = await api(action.endpoint, { method: action.method || "POST", body: { category: els.supportCategory.value || "numbers", message } });
    mergeActions(payload);
    els.supportMessage.value = "";
    els.supportStatus.textContent = payload.message || "تم إرسال التذكرة";
    showToast(els.supportStatus.textContent, "success");
  } catch (error) {
    els.supportStatus.textContent = friendlyError(error);
    showToast(els.supportStatus.textContent, "danger");
  } finally {
    hideBusy();
    setBusy(button, false);
  }
}

function setView(view) {
  state.view = view;
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  document.querySelectorAll(".nav-item, .menu-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  closeMenu();
  if (view === "orders") loadOrders();
  if (view === "account") loadAccount();
  if (view === "recharge") loadRecharge();
  if (view === "support") loadSupport();
}

async function boot() {
  applyRuntimeTheme();
  tg?.ready?.();
  tg?.expand?.();
  tg?.onEvent?.("themeChanged", applyRuntimeTheme);
  document.body.classList.toggle("telegram-runtime", Boolean(tg) || params.get("telegram_runtime") === "1");
  const bootstrap = await api("/mini/numbers/api/bootstrap");
  state.bootstrap = bootstrap;
  state.services = bootstrap.services || [];
  state.countries = bootstrap.countries || [];
  state.states = bootstrap.states_us || [];
  state.clientActions = bootstrap.client?.actions || {};
  const defaults = bootstrap.defaults || {};
  const prefs = loadPrefs();
  state.mode = prefs.mode || (defaults.mode && defaults.mode !== "none" ? defaults.mode : "temp");
  state.service = prefs.service || defaults.service || "";
  state.country = prefs.country || (defaults.country && defaults.country !== "none" ? defaults.country : "none");
  state.stateCode = prefs.stateCode || defaults.state || "none";
  renderBuy();
  renderNav();
  renderSupportCategories();
  renderSupportOrders();
  if (state.service && state.country === "none") loadCountrySuggestions();
  if (headers()["X-Telegram-Init-Data"]) {
    await Promise.allSettled([loadAccount(), loadOrders()]);
  }
}

els.serviceButton.addEventListener("click", () => openPicker("service"));
els.countryButton.addEventListener("click", () => {
  if (state.mode !== "voice") openPicker("country");
});
els.stateButton.addEventListener("click", () => {
  if (state.country === "1") openPicker("state");
});
els.checkPrices.addEventListener("click", checkPrices);
els.drawerClose.addEventListener("click", closePicker);
els.drawerSearch.addEventListener("input", renderPickerOptions);
els.pickerDrawer.addEventListener("click", (event) => {
  if (event.target === els.pickerDrawer) closePicker();
});
els.confirmClose.addEventListener("click", closeConfirm);
els.confirmPurchase.addEventListener("click", confirmPurchase);
els.confirmDrawer.addEventListener("click", (event) => {
  if (event.target === els.confirmDrawer) closeConfirm();
});
els.menuButton?.addEventListener("click", openMenu);
els.menuClose?.addEventListener("click", closeMenu);
els.menuDrawer?.addEventListener("click", (event) => {
  if (event.target === els.menuDrawer) closeMenu();
});
(els.menuList || els.bottomNav)?.addEventListener("click", (event) => {
  const button = event.target.closest(".menu-item, .nav-item");
  if (button?.dataset.view) setView(button.dataset.view);
});
els.refreshOrders.addEventListener("click", loadOrders);
els.balanceButton.addEventListener("click", () => setView("recharge"));
els.supportForm.addEventListener("submit", submitSupport);
els.rechargeForm.addEventListener("submit", submitRecharge);
els.rechargeMethod.addEventListener("change", updateRechargeMethodDetails);

boot().catch((error) => {
  els.offerList.replaceChildren(emptyState(error.message || "تعذر تحميل التطبيق"));
}).finally(() => {
  document.body.classList.remove("app-booting");
});
