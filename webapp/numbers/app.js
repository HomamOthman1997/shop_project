const tg = window.Telegram?.WebApp;

const state = {
  lang: "ar",
  view: "buy",
  mode: "temp",
  services: [],
  countries: [],
  states: [],
  selectedService: "telegram",
  selectedCountry: "none",
  selectedState: "none",
  loading: false,
  activeOrders: [],
  account: null,
  supportCategories: [],
  supportBotUrl: null,
  orderPollTimer: null,
};

const els = {
  viewTabs: document.getElementById("viewTabs"),
  buyView: document.getElementById("buyView"),
  modeSwitch: document.getElementById("modeSwitch"),
  serviceSearch: document.getElementById("serviceSearch"),
  servicesList: document.getElementById("servicesList"),
  countrySelect: document.getElementById("countrySelect"),
  stateSelect: document.getElementById("stateSelect"),
  stateField: document.getElementById("stateField"),
  quickServices: document.getElementById("quickServices"),
  quoteButton: document.getElementById("quoteButton"),
  providerList: document.getElementById("providerList"),
  statusLine: document.getElementById("statusLine"),
  resultCount: document.getElementById("resultCount"),
  selectionTitle: document.getElementById("selectionTitle"),
  sessionPill: document.getElementById("sessionPill"),
  activeBand: document.getElementById("activeBand"),
  activeOrders: document.getElementById("activeOrders"),
  accountView: document.getElementById("accountView"),
  accountDetails: document.getElementById("accountDetails"),
  langArButton: document.getElementById("langArButton"),
  langEnButton: document.getElementById("langEnButton"),
  rechargeButton: document.getElementById("rechargeButton"),
  supportView: document.getElementById("supportView"),
  supportCategory: document.getElementById("supportCategory"),
  supportMessage: document.getElementById("supportMessage"),
  sendSupportButton: document.getElementById("sendSupportButton"),
  supportStatus: document.getElementById("supportStatus"),
};

const copy = {
  ar: {
    eyebrow: "CyberZone Numbers",
    title: "الأرقام",
    tabBuy: "شراء",
    tabOrders: "طلباتي",
    tabAccount: "حسابي",
    tabSupport: "الدعم",
    service: "الخدمة",
    country: "الدولة",
    state: "الولاية",
    check: "فحص الأسعار",
    providers: "المزودين",
    loading: "جاري فحص المزودين",
    ready: "اختر الخدمة والدولة ثم افحص السعر",
    empty: "لا توجد عروض متاحة لهذا الاختيار",
    error: "تعذر تحميل البيانات حاليا",
    temp: "أرقام مؤقتة",
    rental: "أرقام للإيجار",
    voice: "رقم اتصال",
    success: "نجاح",
    base: "التكلفة",
    options: "خيارات",
    unavailable: "غير متاح",
    active: "الطلبات النشطة",
    waiting: "بانتظار الكود",
    noOrders: "لا توجد طلبات نشطة حاليا",
    buy: "شراء",
    refresh: "تحديث",
    cancel: "إلغاء واسترجاع",
    purchasing: "جاري تنفيذ الطلب",
    purchased: "تم حجز الرقم",
    authRequired: "افتح التطبيق من تيليغرام للمتابعة",
    confirmBuy: "تأكيد شراء الرقم؟",
    code: "الكود",
    number: "الرقم",
    refunded: "تم الاسترجاع",
    refundPending: "بانتظار الاسترجاع",
    cancelWait: "الإلغاء بعد",
    left: "متبقي",
    finish: "إنهاء",
    finished: "منتهي",
    account: "الحساب",
    accountTitle: "حسابي",
    balance: "الرصيد",
    userId: "User ID",
    username: "Username",
    language: "اللغة",
    joined: "تاريخ الانضمام",
    recharge: "شحن الرصيد",
    support: "الدعم",
    supportTitle: "فتح تذكرة دعم",
    supportCategory: "القسم",
    supportMessage: "الرسالة",
    supportPlaceholder: "اكتب المشكلة أو رقم الطلب إن وجد",
    sendSupport: "إرسال تذكرة الدعم",
    supportSent: "تم إرسال التذكرة",
    loadingAccount: "جاري تحميل الحساب",
    openBot: "فتح البوت",
  },
  en: {
    eyebrow: "CyberZone Numbers",
    title: "Numbers",
    tabBuy: "Buy",
    tabOrders: "My numbers",
    tabAccount: "Account",
    tabSupport: "Support",
    service: "Service",
    country: "Country",
    state: "State",
    check: "Check prices",
    providers: "Providers",
    loading: "Checking providers",
    ready: "Choose a service and country, then check prices",
    empty: "No offers are available for this selection",
    error: "Could not load data right now",
    temp: "Temporary SMS",
    rental: "Rental numbers",
    voice: "Call number",
    success: "Success",
    base: "Cost",
    options: "Options",
    unavailable: "Unavailable",
    active: "Active orders",
    waiting: "Waiting for code",
    noOrders: "No active orders right now",
    buy: "Buy",
    refresh: "Refresh",
    cancel: "Cancel & refund",
    purchasing: "Placing order",
    purchased: "Number reserved",
    authRequired: "Open from Telegram to continue",
    confirmBuy: "Confirm number purchase?",
    code: "Code",
    number: "Number",
    refunded: "Refunded",
    refundPending: "Refund pending",
    cancelWait: "Cancel after",
    left: "left",
    finish: "Finish",
    finished: "Finished",
    account: "Account",
    accountTitle: "My account",
    balance: "Balance",
    userId: "User ID",
    username: "Username",
    language: "Language",
    joined: "Joined",
    recharge: "Recharge",
    support: "Support",
    supportTitle: "Open support ticket",
    supportCategory: "Category",
    supportMessage: "Message",
    supportPlaceholder: "Describe the issue or include an order number",
    sendSupport: "Send support ticket",
    supportSent: "Support ticket sent",
    loadingAccount: "Loading account",
    openBot: "Open bot",
  },
};

function t(key) {
  return (copy[state.lang] || copy.en)[key] || copy.en[key] || key;
}

function applyLanguage(languageCode) {
  state.lang = String(languageCode || "ar").toLowerCase().startsWith("ar") ? "ar" : "en";
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  if (els.supportMessage) {
    els.supportMessage.placeholder = t("supportPlaceholder");
  }
}

function setLanguage() {
  const languageCode = tg?.initDataUnsafe?.user?.language_code || navigator.language || "ar";
  applyLanguage(languageCode);
  els.statusLine.textContent = t("ready");
}

function headers(extra = {}) {
  const initData = tg?.initData || "";
  return {
    ...(initData ? { "X-Telegram-Init-Data": initData } : {}),
    ...extra,
  };
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: headers(options.body ? { "Content-Type": "application/json" } : {}),
    body: options.body ? JSON.stringify(options.body) : undefined,
    cache: "no-store",
  });
  let payload = null;
  try {
    payload = await response.json();
  } catch (_error) {
    payload = null;
  }
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.message || response.statusText || t("error"));
  }
  return payload;
}

function canUseTelegramAuth() {
  return Boolean(tg?.initData);
}

function openTelegramUrl(url) {
  if (!url) return;
  if (tg?.openTelegramLink) {
    tg.openTelegramLink(url);
    return;
  }
  window.location.href = url;
}

function renderViewTabs() {
  const tabs = [
    ["buy", t("tabBuy")],
    ["orders", t("tabOrders")],
    ["account", t("tabAccount")],
    ["support", t("tabSupport")],
  ];
  els.viewTabs.replaceChildren(
    ...tabs.map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `view-tab${state.view === key ? " active" : ""}`;
      button.textContent = label;
      button.addEventListener("click", () => setView(key));
      return button;
    })
  );
}

function setView(view) {
  state.view = view;
  els.buyView.classList.toggle("hidden", view !== "buy");
  els.activeBand.classList.toggle("hidden", view !== "orders");
  els.accountView.classList.toggle("hidden", view !== "account");
  els.supportView.classList.toggle("hidden", view !== "support");
  renderViewTabs();
  if (view === "orders") refreshOrders({ quiet: true });
  if (view === "account") loadAccount();
  if (view === "support") loadSupportInfo();
}

function serviceLabel(key) {
  const found = state.services.find((item) => item.key === key);
  return found?.label || key;
}

function selectedServiceFromInput() {
  const raw = els.serviceSearch.value.trim();
  if (!raw) return state.selectedService;
  const lowered = raw.toLowerCase();
  const matches = (item) => {
    const aliases = Array.isArray(item.aliases) ? item.aliases : [];
    return [item.label, item.key, ...aliases].map((value) => String(value || "").toLowerCase());
  };
  const exact = state.services.find((item) => matches(item).some((value) => value === lowered));
  if (exact) return exact.key;
  const partial = state.services.find((item) => matches(item).some((value) => value.includes(lowered)));
  return partial?.key || state.selectedService;
}

function renderModes() {
  const modes = [
    ["temp", t("temp")],
    ["rental", t("rental")],
    ["voice", t("voice")],
  ];
  els.modeSwitch.replaceChildren(
    ...modes.map(([key, label]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `mode-button${state.mode === key ? " active" : ""}`;
      button.textContent = label;
      button.setAttribute("role", "tab");
      button.setAttribute("aria-selected", state.mode === key ? "true" : "false");
      button.addEventListener("click", () => {
        state.mode = key;
        updateStateVisibility();
        renderModes();
        renderProviders([]);
      });
      return button;
    })
  );
}

function renderSelectors() {
  els.servicesList.replaceChildren(
    ...state.services.map((item) => {
      const option = document.createElement("option");
      option.value = item.label;
      option.dataset.key = item.key;
      return option;
    })
  );
  els.serviceSearch.value = serviceLabel(state.selectedService);

  els.countrySelect.replaceChildren(
    ...state.countries.map((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.textContent = item.iso ? `${item.name} (${item.iso})` : item.name;
      return option;
    })
  );
  els.countrySelect.value = state.selectedCountry;

  els.stateSelect.replaceChildren(
    ...state.states.map((item) => {
      const option = document.createElement("option");
      option.value = item.code;
      option.textContent = item.name;
      return option;
    })
  );
  els.stateSelect.value = state.selectedState;
  updateStateVisibility();
}

function updateStateVisibility() {
  const showState = state.selectedCountry === "1" && state.mode !== "rental";
  els.stateField.classList.toggle("hidden", !showState);
  if (!showState) {
    state.selectedState = "none";
    els.stateSelect.value = "none";
  }
}

function renderQuickServices() {
  const top = state.services.filter((item) => item.top).slice(0, 10);
  els.quickServices.replaceChildren(
    ...top.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `quick-chip${state.selectedService === item.key ? " active" : ""}`;
      button.textContent = item.label;
      button.addEventListener("click", () => {
        state.selectedService = item.key;
        els.serviceSearch.value = item.label;
        renderQuickServices();
      });
      return button;
    })
  );
}

function setLoading(loading) {
  state.loading = loading;
  els.quoteButton.disabled = loading;
  els.quoteButton.textContent = loading ? t("loading") : t("check");
}

function formatDuration(seconds) {
  const sec = Math.max(0, Number(seconds || 0));
  if (sec < 60) return `${sec}s`;
  const minutes = Math.ceil(sec / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}h ${rest}m` : `${hours}h`;
}

function statusLabel(order) {
  const status = String(order.public_status || "");
  if (status === "code_received") return t("code");
  if (status === "refunded") return t("refunded");
  if (status === "refund_pending") return t("refundPending");
  if (status === "finished") return t("finished");
  return t("waiting");
}

function askConfirm(message) {
  return new Promise((resolve) => {
    if (tg?.showConfirm) {
      tg.showConfirm(message, resolve);
      return;
    }
    resolve(window.confirm(message));
  });
}

function emptyState(text) {
  const div = document.createElement("div");
  div.className = "empty-state";
  div.textContent = text;
  return div;
}

function renderActiveOrders(rows = state.activeOrders) {
  state.activeOrders = rows || [];
  if (!state.activeOrders.length) {
    els.activeOrders.replaceChildren(emptyState(canUseTelegramAuth() ? t("noOrders") : t("authRequired")));
    return;
  }
  els.activeOrders.replaceChildren(
    ...state.activeOrders.map((order) => {
      const card = document.createElement("article");
      card.className = "order-card";

      const main = document.createElement("div");
      main.className = "order-main";

      const title = document.createElement("p");
      title.className = "order-title";
      const id = document.createElement("span");
      id.className = "provider-id";
      id.textContent = order.provider_id || "";
      title.append(id, document.createTextNode(`${order.service_label || order.service || ""} · ${statusLabel(order)}`));

      const meta = document.createElement("p");
      meta.className = "order-meta";
      const details = [];
      if (order.number) details.push(`${t("number")}: ${order.number}`);
      details.push(`${order.price_label || ""}`);
      if (order.public_status === "waiting") details.push(`${formatDuration(order.seconds_left)} ${t("left")}`);
      meta.textContent = details.filter(Boolean).join(" · ");
      main.append(title, meta);

      if (order.code) {
        const code = document.createElement("span");
        code.className = "order-code";
        code.textContent = order.code;
        main.append(code);
      }

      const actions = document.createElement("div");
      actions.className = "order-actions";
      const refresh = document.createElement("button");
      refresh.type = "button";
      refresh.className = "small-action";
      refresh.textContent = t("refresh");
      refresh.addEventListener("click", () => refreshSingleOrder(order.id, refresh));
      actions.append(refresh);

      if (order.public_status === "waiting" && order.mode !== "rental") {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "danger-action";
        cancel.disabled = !order.can_cancel;
        cancel.textContent = order.can_cancel ? t("cancel") : `${t("cancelWait")} ${formatDuration(order.cancel_wait_sec)}`;
        cancel.addEventListener("click", () => cancelOrder(order.id, cancel));
        actions.append(cancel);
      }
      if (order.mode === "rental" && order.can_finish) {
        const finish = document.createElement("button");
        finish.type = "button";
        finish.className = "danger-action";
        finish.textContent = t("finish");
        finish.addEventListener("click", () => finishOrder(order.id, finish));
        actions.append(finish);
      }

      card.append(main, actions);
      return card;
    })
  );
}

async function refreshOrders({ quiet = false } = {}) {
  if (!canUseTelegramAuth()) {
    renderActiveOrders([]);
    return;
  }
  try {
    const payload = await api("/mini/numbers/api/orders");
    renderActiveOrders(payload.orders || []);
  } catch (error) {
    if (!quiet) els.statusLine.textContent = error.message || t("error");
  }
}

async function refreshSingleOrder(orderId, button) {
  if (!orderId) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/refresh`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
  } finally {
    button.disabled = false;
  }
}

async function cancelOrder(orderId, button) {
  if (!orderId) return;
  const confirmed = await askConfirm(t("cancel"));
  if (!confirmed) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/cancel`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    els.statusLine.textContent = payload.message || "";
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    button.disabled = false;
  }
}

async function finishOrder(orderId, button) {
  if (!orderId) return;
  const confirmed = await askConfirm(t("finish"));
  if (!confirmed) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/finish`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    els.statusLine.textContent = payload.message || "";
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    button.disabled = false;
  }
}

async function buyProvider(row, button) {
  if (!canUseTelegramAuth()) {
    els.statusLine.textContent = t("authRequired");
    return;
  }
  const confirmed = await askConfirm(`${t("confirmBuy")} ${row.price_label || ""}`);
  if (!confirmed) return;
  button.disabled = true;
  els.statusLine.textContent = t("purchasing");
  try {
    const payload = await api("/mini/numbers/api/purchase", {
      method: "POST",
      body: { quote_token: row.quote_token },
    });
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    renderActiveOrders([payload.order, ...state.activeOrders].filter(Boolean));
    els.statusLine.textContent = t("purchased");
    await refreshOrders({ quiet: true });
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
  } finally {
    button.disabled = false;
  }
}

function renderProviders(rows) {
  els.resultCount.textContent = String(rows.length);
  if (!rows.length) {
    els.providerList.replaceChildren(emptyState(t("empty")));
    return;
  }
  els.providerList.replaceChildren(
    ...rows.map((row) => {
      const card = document.createElement("article");
      card.className = `provider-card${row.available ? "" : " unavailable"}`;

      const main = document.createElement("div");
      main.className = "provider-main";

      const name = document.createElement("p");
      name.className = "provider-name";
      const id = document.createElement("span");
      id.className = "provider-id";
      id.textContent = row.provider_id;
      name.append(id, document.createTextNode(row.provider));

      const meta = document.createElement("p");
      meta.className = "provider-meta";
      const details = [`${t("success")}: ${row.success_rate}`];
      if (row.base_price_label && row.base_price_label !== "-") details.push(`${t("base")}: ${row.base_price_label}`);
      if (!row.available && row.reason) details.push(row.reason);
      meta.textContent = details.join(" · ");

      main.append(name, meta);
      if (row.options?.length) {
        const options = document.createElement("div");
        options.className = "option-row";
        row.options.slice(0, 5).forEach((option) => {
          const pill = document.createElement(state.mode === "rental" && option.quote_token ? "button" : "span");
          pill.className = "option-pill";
          if (pill.tagName === "BUTTON") {
            pill.type = "button";
            pill.classList.add("buyable");
            pill.addEventListener("click", () => buyProvider({ ...row, price_label: option.price_label, quote_token: option.quote_token }, pill));
          }
          const optionText = `${option.duration_label || option.duration || t("options")} ${option.price_label}`;
          pill.textContent = pill.tagName === "BUTTON" ? `${t("buy")} ${optionText}` : optionText;
          options.append(pill);
        });
        main.append(options);
      }

      if (row.available && state.mode === "temp" && row.quote_token) {
        const actions = document.createElement("div");
        actions.className = "provider-actions";
        const price = document.createElement("div");
        price.className = "action-price";
        price.textContent = row.price_label;
        const buy = document.createElement("button");
        buy.type = "button";
        buy.className = "small-action";
        buy.textContent = t("buy");
        buy.addEventListener("click", () => buyProvider(row, buy));
        actions.append(price, buy);
        card.append(main, actions);
      } else {
        const price = document.createElement("div");
        price.className = "provider-price";
        price.textContent = row.available ? (state.mode === "rental" && row.options?.length ? row.options[0].price_label : row.price_label) : t("unavailable");
        card.append(main, price);
      }
      return card;
    })
  );
}

function infoCard(label, value) {
  const card = document.createElement("div");
  card.className = "info-card";
  const key = document.createElement("span");
  key.className = "info-label";
  key.textContent = label;
  const val = document.createElement("strong");
  val.className = "info-value";
  val.textContent = value || "-";
  card.append(key, val);
  return card;
}

function renderAccount(payload) {
  state.account = payload;
  if (!payload?.user) {
    els.accountDetails.replaceChildren(emptyState(t("authRequired")));
    return;
  }
  const user = payload.user;
  els.sessionPill.textContent = payload.balance_label || user.full_name || user.username || "Mini App";
  state.supportCategories = payload.support_categories || state.supportCategories;
  state.supportBotUrl = payload.links?.numbers_bot || state.supportBotUrl;
  renderSupportCategories();
  els.accountDetails.replaceChildren(
    infoCard(t("balance"), payload.balance_label || "-"),
    infoCard(t("userId"), String(user.id || "-")),
    infoCard(t("username"), user.username ? `@${user.username}` : "-"),
    infoCard(t("language"), user.language_label || user.language || "-"),
    infoCard(t("joined"), user.joined_at || "-")
  );
}

async function loadAccount() {
  if (!canUseTelegramAuth()) {
    renderAccount(null);
    return;
  }
  els.accountDetails.replaceChildren(emptyState(t("loadingAccount")));
  try {
    const payload = await api("/mini/numbers/api/account");
    if (payload.user?.language) {
      applyLanguage(payload.user.language);
      renderViewTabs();
      renderModes();
    }
    renderAccount(payload);
  } catch (error) {
    els.accountDetails.replaceChildren(emptyState(error.message || t("error")));
  }
}

async function changeLanguage(language, button) {
  if (!canUseTelegramAuth()) {
    els.accountDetails.replaceChildren(emptyState(t("authRequired")));
    return;
  }
  button.disabled = true;
  try {
    const payload = await api("/mini/numbers/api/account/language", {
      method: "POST",
      body: { language },
    });
    applyLanguage(payload.user?.language || language);
    renderViewTabs();
    renderModes();
    renderSelectors();
    renderQuickServices();
    renderActiveOrders();
    renderAccount(payload);
  } catch (error) {
    els.accountDetails.replaceChildren(emptyState(error.message || t("error")));
  } finally {
    button.disabled = false;
  }
}

function renderSupportCategories(categories = state.supportCategories) {
  state.supportCategories = categories || [];
  els.supportCategory.replaceChildren(
    ...state.supportCategories.map((item) => {
      const option = document.createElement("option");
      option.value = item.key;
      option.textContent = item.label;
      return option;
    })
  );
}

async function loadSupportInfo() {
  if (!canUseTelegramAuth()) {
    els.supportStatus.textContent = t("authRequired");
    renderSupportCategories([]);
    return;
  }
  try {
    const payload = await api("/mini/numbers/api/support");
    state.supportBotUrl = payload.bot_url || state.supportBotUrl;
    renderSupportCategories(payload.categories || []);
    if (!els.supportStatus.textContent) els.supportStatus.textContent = "";
  } catch (error) {
    els.supportStatus.textContent = error.message || t("error");
  }
}

async function sendSupportTicket() {
  if (!canUseTelegramAuth()) {
    els.supportStatus.textContent = t("authRequired");
    return;
  }
  const category = els.supportCategory.value || "numbers";
  const message = els.supportMessage.value.trim();
  els.sendSupportButton.disabled = true;
  try {
    const payload = await api("/mini/numbers/api/support/ticket", {
      method: "POST",
      body: { category, message },
    });
    els.supportMessage.value = "";
    els.supportStatus.textContent = payload.message || t("supportSent");
  } catch (error) {
    els.supportStatus.textContent = error.message || t("error");
  } finally {
    els.sendSupportButton.disabled = false;
  }
}

async function checkPrices() {
  state.selectedService = selectedServiceFromInput();
  state.selectedCountry = els.countrySelect.value || "none";
  state.selectedState = els.stateSelect.value || "none";
  updateStateVisibility();
  renderQuickServices();
  els.selectionTitle.textContent = serviceLabel(state.selectedService);
  els.statusLine.textContent = t("loading");
  setLoading(true);
  try {
    const params = new URLSearchParams({
      mode: state.mode,
      service: state.selectedService,
      country: state.selectedCountry,
      state: state.selectedState,
    });
    const payload = await api(`/mini/numbers/api/prices?${params.toString()}`);
    els.statusLine.textContent = payload.ok === false ? payload.message || t("error") : "";
    renderProviders(payload.providers || []);
  } catch (_error) {
    els.statusLine.textContent = t("error");
    renderProviders([]);
  } finally {
    setLoading(false);
  }
}

async function boot() {
  tg?.ready();
  tg?.expand();
  setLanguage();
  els.sessionPill.textContent = tg?.initDataUnsafe?.user?.first_name || "Mini App";
  const payload = await api("/mini/numbers/api/bootstrap");
  state.services = payload.services || [];
  state.countries = payload.countries || [];
  state.states = payload.states_us || [];
  state.selectedService = payload.defaults?.service || "telegram";
  state.selectedCountry = payload.defaults?.country || "none";
  state.selectedState = payload.defaults?.state || "none";
  renderViewTabs();
  renderModes();
  renderSelectors();
  renderQuickServices();
  renderProviders([]);
  renderActiveOrders([]);
  refreshOrders({ quiet: true });
  if (canUseTelegramAuth()) loadAccount();
  state.orderPollTimer = window.setInterval(() => refreshOrders({ quiet: true }), 8000);
  els.countrySelect.addEventListener("change", () => {
    state.selectedCountry = els.countrySelect.value || "none";
    updateStateVisibility();
  });
  els.stateSelect.addEventListener("change", () => {
    state.selectedState = els.stateSelect.value || "none";
  });
  els.quoteButton.addEventListener("click", checkPrices);
  els.langArButton.addEventListener("click", () => changeLanguage("ar", els.langArButton));
  els.langEnButton.addEventListener("click", () => changeLanguage("en", els.langEnButton));
  els.rechargeButton.addEventListener("click", () => openTelegramUrl(state.account?.links?.recharge || state.supportBotUrl));
  els.sendSupportButton.addEventListener("click", sendSupportTicket);
}

boot().catch(() => {
  setLanguage();
  renderViewTabs();
  els.statusLine.textContent = t("error");
  renderProviders([]);
  renderActiveOrders([]);
});
