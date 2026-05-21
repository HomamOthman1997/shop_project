const tg = window.Telegram?.WebApp;

const state = {
  lang: "ar",
  view: "buy",
  mode: "temp",
  services: [],
  countries: [],
  states: [],
  selectedService: "",
  selectedCountry: "none",
  selectedState: "none",
  loading: false,
  activeOrders: [],
  account: null,
  supportCategories: [],
  supportBotUrl: null,
  rechargeUrl: null,
  orderPollTimer: null,
  providerRows: [],
  showAllProviders: false,
  serviceMenuOpen: false,
  busyCount: 0,
};

const ORDER_POLL_INTERVAL_MS = 12000;

const els = {
  viewTabs: document.getElementById("viewTabs"),
  buyView: document.getElementById("buyView"),
  modeSwitch: document.getElementById("modeSwitch"),
  serviceTrigger: document.getElementById("serviceTrigger"),
  serviceLabel: document.getElementById("serviceLabel"),
  serviceMenu: document.getElementById("serviceMenu"),
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
  busyOverlay: document.getElementById("busyOverlay"),
  busyTitle: document.getElementById("busyTitle"),
  busyText: document.getElementById("busyText"),
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
    active: "طلباتي",
    numbersList: "أرقامي",
    waiting: "بانتظار الكود",
    waitingCall: "بانتظار المكالمة",
    callReceived: "وصلت المكالمة",
    recording: "تسجيل المكالمة",
    downloadRecording: "تحميل التسجيل",
    noOrders: "لا توجد أرقام حاليا",
    buy: "شراء",
    refresh: "تحديث",
    cancel: "إلغاء واسترجاع",
    tryAnother: "رقم بديل",
    alternateProvider: "مزود بديل",
    confirmTryAnother: "تأكيد طلب رقم بديل؟",
    confirmAlternateProvider: "تأكيد طلب رقم من مزود بديل؟",
    replacementRequested: "تم طلب رقم بديل",
    secondCode: "كود ثاني",
    confirmSecondCode: "تأكيد طلب كود ثاني؟",
    secondCodeRequested: "تم طلب كود ثاني",
    purchasing: "جاري تنفيذ الطلب",
    purchased: "تم حجز الرقم",
    authRequired: "افتح التطبيق من تيليغرام للمتابعة",
    confirmBuy: "تأكيد شراء الرقم؟",
    code: "الكود",
    number: "الرقم",
    copyCode: "نسخ الكود",
    copyNumber: "نسخ الرقم",
    copied: "تم النسخ",
    detailProvider: "المزود",
    detailCountry: "الدولة",
    detailState: "الولاية",
    detailCreated: "تاريخ الطلب",
    detailReuseUntil: "نافذة الكود الثاني",
    detailSecondCodes: "أكواد إضافية",
    detailDuration: "المدة",
    detailEnds: "النهاية",
    detailCalls: "المكالمات",
    detailRetry: "محاولات الاسترجاع",
    recentActivity: "آخر الحركات",
    noActivity: "لا توجد حركات بعد",
    afterBalance: "الرصيد بعد العملية",
    refunded: "تم الاسترجاع",
    refundPending: "بانتظار الاسترجاع",
    cancelWait: "الإلغاء بعد",
    left: "متبقي",
    finish: "إنهاء",
    finished: "منتهي",
    renew: "تجديد",
    wake: "تنشيط",
    notesTags: "ملاحظات",
    notes: "ملاحظات",
    tags: "Tags",
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
    chooseService: "Choose service",
    chooseServiceFirst: "Choose a service first",
    country: "Country",
    state: "State",
    stateHint: "Any state usually gives better prices than a specific state.",
    check: "Check prices",
    providers: "Providers",
    bestChoice: "Best choice",
    showOtherProviders: "Show other providers",
    hideOtherProviders: "Show best choice only",
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
    active: "My numbers",
    numbersList: "Numbers list",
    waiting: "Waiting for code",
    waitingCall: "Waiting for call",
    callReceived: "Call received",
    recording: "Call recording",
    downloadRecording: "Download recording",
    noOrders: "No numbers right now",
    buy: "Buy",
    refresh: "Refresh",
    cancel: "Cancel & refund",
    tryAnother: "Try another",
    alternateProvider: "Alternate provider",
    confirmTryAnother: "Confirm replacement number request?",
    confirmAlternateProvider: "Confirm alternate provider request?",
    replacementRequested: "Replacement number requested",
    secondCode: "Second code",
    confirmSecondCode: "Confirm second code request?",
    secondCodeRequested: "Second code requested",
    purchasing: "Placing order",
    purchased: "Number reserved",
    authRequired: "Open from Telegram to continue",
    confirmBuy: "Confirm number purchase?",
    code: "Code",
    number: "Number",
    copyCode: "Copy code",
    copyNumber: "Copy number",
    copied: "Copied",
    detailProvider: "Provider",
    detailCountry: "Country",
    detailState: "State",
    detailCreated: "Created",
    detailReuseUntil: "Second-code window",
    detailSecondCodes: "Extra codes",
    detailDuration: "Duration",
    detailEnds: "Ends",
    detailCalls: "Calls",
    detailRetry: "Refund retries",
    recentActivity: "Recent activity",
    noActivity: "No activity yet",
    afterBalance: "Balance after",
    refunded: "Refunded",
    refundPending: "Refund pending",
    cancelWait: "Cancel after",
    left: "left",
    finish: "Finish",
    finished: "Finished",
    renew: "Renew",
    wake: "Wake",
    notesTags: "Notes",
    notes: "Notes",
    tags: "Tags",
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
    refundWorking: "Refund in progress",
    refundWait: "Checking provider and wallet. Please wait.",
    voiceFallback: "Generic voice route",
  },
};

Object.assign(copy.ar, {
  title: "الأرقام",
  tabBuy: "شراء",
  tabOrders: "طلباتي",
  tabAccount: "حسابي",
  tabSupport: "الدعم",
  service: "الخدمة",
  chooseService: "اختر الخدمة",
  chooseServiceFirst: "اختر الخدمة أولاً",
  country: "الدولة",
  state: "الولاية",
  stateHint: "بدون ولاية منجيبلك أفضل الأسعار غالباً.",
  check: "فحص الأسعار",
  providers: "المزودين",
  bestChoice: "أفضل خيار",
  showOtherProviders: "عرض باقي المزودات",
  hideOtherProviders: "عرض أفضل خيار فقط",
  loading: "جاري فحص المزودين",
  ready: "اختر الخدمة والدولة ثم افحص السعر",
  empty: "لا توجد عروض متاحة لهذا الاختيار",
  error: "تعذر تحميل البيانات حالياً",
  temp: "أرقام مؤقتة",
  rental: "أرقام للإيجار",
  voice: "رقم اتصال",
  success: "نجاح",
  base: "التكلفة",
  options: "خيارات",
  unavailable: "غير متاح",
  active: "طلباتي",
  numbersList: "أرقامي",
  waiting: "بانتظار الكود",
  waitingCall: "بانتظار المكالمة",
  callReceived: "وصلت المكالمة",
  recording: "تسجيل المكالمة",
  downloadRecording: "تحميل التسجيل",
  noOrders: "لا توجد أرقام حالياً",
  buy: "شراء",
  refresh: "تحديث",
  cancel: "إلغاء واسترجاع",
  tryAnother: "رقم بديل",
  alternateProvider: "مزود بديل",
  confirmTryAnother: "تأكيد طلب رقم بديل؟",
  confirmAlternateProvider: "تأكيد طلب رقم من مزود بديل؟",
  replacementRequested: "تم طلب رقم بديل",
  secondCode: "كود ثاني",
  confirmSecondCode: "تأكيد طلب كود ثاني؟",
  secondCodeRequested: "تم طلب كود ثاني",
  purchasing: "جاري تنفيذ الطلب",
  purchased: "تم حجز الرقم",
  authRequired: "افتح التطبيق من تيليغرام للمتابعة",
  confirmBuy: "تأكيد شراء الرقم؟",
  code: "الكود",
  number: "الرقم",
  copyCode: "نسخ الكود",
  copyNumber: "نسخ الرقم",
  copied: "تم النسخ",
  detailProvider: "المزود",
  detailCountry: "الدولة",
  detailState: "الولاية",
  detailCreated: "تاريخ الطلب",
  detailReuseUntil: "نافذة الكود الثاني",
  detailSecondCodes: "أكواد إضافية",
  detailDuration: "المدة",
  detailEnds: "النهاية",
  detailCalls: "المكالمات",
  detailRetry: "محاولات الاسترجاع",
  recentActivity: "آخر الحركات",
  noActivity: "لا توجد حركات بعد",
  afterBalance: "الرصيد بعد العملية",
  refunded: "تم الاسترجاع",
  refundPending: "بانتظار الاسترجاع",
  refundWorking: "جاري الاسترجاع",
  refundWait: "عم نفحص المزود والمحفظة، يرجى الانتظار.",
  cancelWait: "الإلغاء بعد",
  left: "متبقي",
  finish: "إنهاء",
  finished: "منتهي",
  renew: "تجديد",
  wake: "تنشيط",
  notesTags: "ملاحظات",
  notes: "ملاحظات",
  tags: "وسوم",
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
  voiceFallback: "مسار اتصال عام",
});

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
  if (els.serviceSearch) {
    els.serviceSearch.placeholder = t("chooseService");
  }
  updateServiceLabel();
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

function showBusy(title, text) {
  state.busyCount += 1;
  if (els.busyTitle) els.busyTitle.textContent = title || t("loading");
  if (els.busyText) els.busyText.textContent = text || "";
  els.busyOverlay?.classList.remove("hidden");
}

function hideBusy() {
  state.busyCount = Math.max(0, state.busyCount - 1);
  if (!state.busyCount) {
    els.busyOverlay?.classList.add("hidden");
  }
}

function renderViewTabs() {
  const tabs = [
    ["buy", t("tabBuy"), "01"],
    ["orders", t("tabOrders"), "02"],
    ["account", t("tabAccount"), "03"],
    ["support", t("tabSupport"), "04"],
  ];
  els.viewTabs.replaceChildren(
    ...tabs.map(([key, label, index]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `view-tab${state.view === key ? " active" : ""}`;
      const icon = document.createElement("span");
      icon.className = "nav-index";
      icon.textContent = index;
      const text = document.createElement("span");
      text.className = "nav-label";
      text.textContent = label;
      button.append(icon, text);
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
  if (view === "orders") {
    refreshOrders({ quiet: true });
  } else {
    clearOrderPoll();
  }
  if (view === "account") loadAccount();
  if (view === "support") loadSupportInfo();
}

function serviceLabel(key) {
  if (!key) return t("chooseService");
  const found = state.services.find((item) => item.key === key);
  return found?.label || key;
}

function selectedServiceFromInput() {
  const raw = els.serviceSearch.value.trim() || state.selectedService;
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

function updateServiceLabel() {
  if (els.serviceLabel) {
    els.serviceLabel.textContent = state.selectedService ? serviceLabel(state.selectedService) : t("chooseService");
  }
  if (els.selectionTitle) {
    els.selectionTitle.textContent = state.selectedService ? serviceLabel(state.selectedService) : t("chooseService");
  }
}

function setServiceMenuOpen(open) {
  state.serviceMenuOpen = Boolean(open);
  els.serviceMenu?.classList.toggle("hidden", !state.serviceMenuOpen);
  els.serviceTrigger?.setAttribute("aria-expanded", state.serviceMenuOpen ? "true" : "false");
  if (state.serviceMenuOpen) {
    renderServiceOptions();
    window.setTimeout(() => els.serviceSearch?.focus(), 0);
  }
}

function setServiceSelection(key) {
  state.selectedService = key || "";
  els.serviceSearch.value = "";
  state.showAllProviders = false;
  updateServiceLabel();
  renderProviders([]);
  setServiceMenuOpen(false);
}

function serviceMatches(item, query) {
  const lowered = String(query || "").trim().toLowerCase();
  if (!lowered) return true;
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  return [item.label, item.key, ...aliases].some((value) => String(value || "").toLowerCase().includes(lowered));
}

function renderServiceOptions() {
  const query = els.serviceSearch.value || "";
  const filtered = state.services.filter((item) => serviceMatches(item, query)).slice(0, 80);
  if (!filtered.length) {
    els.servicesList.replaceChildren(emptyState(t("empty")));
    return;
  }
  els.servicesList.replaceChildren(
    ...filtered.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `service-option${state.selectedService === item.key ? " active" : ""}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", state.selectedService === item.key ? "true" : "false");
      const label = document.createElement("strong");
      label.textContent = item.label;
      const key = document.createElement("span");
      key.textContent = item.key;
      button.append(label, key);
      button.addEventListener("click", () => setServiceSelection(item.key));
      return button;
    })
  );
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
        state.showAllProviders = false;
        updateStateVisibility();
        renderModes();
        renderProviders([]);
      });
      return button;
    })
  );
}

function renderSelectors() {
  renderServiceOptions();
  updateServiceLabel();

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
  els.countrySelect.disabled = false;
  const showState = state.selectedCountry === "1";
  els.stateField.classList.toggle("hidden", !showState);
  if (!showState) {
    state.selectedState = "none";
    els.stateSelect.value = "none";
  }
}

function renderQuickServices() {
  els.quickServices.replaceChildren();
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
  if (order.mode === "voice" && status === "call_received") return t("callReceived");
  if (order.mode === "voice") return t("waitingCall");
  return t("waiting");
}

function clearOrderPoll() {
  if (state.orderPollTimer) {
    window.clearTimeout(state.orderPollTimer);
    state.orderPollTimer = null;
  }
}

function orderNeedsPolling(order) {
  if (!order || order.can_refresh === false) return false;
  return ["waiting", "refund_pending"].includes(order.public_status);
}

function scheduleOrderPoll() {
  clearOrderPoll();
  if (state.view !== "orders" || !canUseTelegramAuth() || !state.activeOrders.some(orderNeedsPolling)) {
    return;
  }
  state.orderPollTimer = window.setTimeout(async () => {
    state.orderPollTimer = null;
    if (state.view === "orders") {
      await refreshOrders({ quiet: true });
    }
  }, ORDER_POLL_INTERVAL_MS);
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

async function copyText(value, button) {
  const text = String(value || "").trim();
  if (!text) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.append(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    if (button) {
      const previous = button.textContent;
      button.textContent = t("copied");
      window.setTimeout(() => {
        button.textContent = previous;
      }, 1100);
    }
    els.statusLine.textContent = t("copied");
  } catch (_error) {
    els.statusLine.textContent = t("error");
  }
}

function detailLabel(key) {
  const normalized = String(key || "").trim();
  if (!normalized) return "";
  return t(`detail${normalized.charAt(0).toUpperCase()}${normalized.slice(1)}`);
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
    clearOrderPoll();
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

      if (Array.isArray(order.details) && order.details.length) {
        const detailGrid = document.createElement("div");
        detailGrid.className = "order-detail-grid";
        order.details.slice(0, 7).forEach((item) => {
          const row = document.createElement("div");
          row.className = "order-detail";
          const label = document.createElement("span");
          label.textContent = detailLabel(item.key);
          const value = document.createElement("strong");
          value.textContent = item.value || "-";
          row.append(label, value);
          detailGrid.append(row);
        });
        main.append(detailGrid);
      }

      if (order.code) {
        const code = document.createElement("span");
        code.className = "order-code";
        code.textContent = order.code;
        main.append(code);
      }
      if (order.mode === "rental" && (order.notes || order.tags?.length)) {
        const notes = document.createElement("p");
        notes.className = "order-meta";
        const parts = [];
        if (order.notes) parts.push(`${t("notes")}: ${order.notes}`);
        if (order.tags?.length) parts.push(`${t("tags")}: ${order.tags.slice(0, 6).join(", ")}`);
        notes.textContent = parts.join(" · ");
        main.append(notes);
      }
      if (order.mode === "voice" && order.recording_available) {
        const recording = document.createElement("span");
        recording.className = "order-code";
        recording.textContent = t("recording");
        main.append(recording);
      }

      const actions = document.createElement("div");
      actions.className = "order-actions";
      if (order.number) {
        const copyNumber = document.createElement("button");
        copyNumber.type = "button";
        copyNumber.className = "small-action secondary-small";
        copyNumber.textContent = t("copyNumber");
        copyNumber.addEventListener("click", () => copyText(order.number, copyNumber));
        actions.append(copyNumber);
      }
      if (order.code) {
        const copyCode = document.createElement("button");
        copyCode.type = "button";
        copyCode.className = "small-action secondary-small";
        copyCode.textContent = t("copyCode");
        copyCode.addEventListener("click", () => copyText(order.code, copyCode));
        actions.append(copyCode);
      }
      if (order.can_refresh !== false) {
        const refresh = document.createElement("button");
        refresh.type = "button";
        refresh.className = "small-action";
        refresh.textContent = t("refresh");
        refresh.addEventListener("click", () => refreshSingleOrder(order.id, refresh));
        actions.append(refresh);
      }

      if (order.mode === "voice" && order.recording_url) {
        const recording = document.createElement("button");
        recording.type = "button";
        recording.className = "small-action";
        recording.textContent = t("downloadRecording");
        recording.addEventListener("click", () => downloadRecording(order, recording));
        actions.append(recording);
      }

      if (order.mode === "temp" && order.can_second_code) {
        const second = document.createElement("button");
        second.type = "button";
        second.className = "small-action";
        second.textContent = `${t("secondCode")} ${order.second_code_price_label || ""}`.trim();
        second.addEventListener("click", () => requestSecondCode(order, second));
        actions.append(second);
      }

      if ((order.mode === "temp" || order.mode === "voice") && order.can_replace) {
        const replace = document.createElement("button");
        replace.type = "button";
        replace.className = "small-action";
        replace.textContent = t("tryAnother");
        replace.addEventListener("click", () => replaceOrder(order, replace));
        actions.append(replace);
      }
      if (order.mode === "temp" && order.can_alternate_provider) {
        const alternate = document.createElement("button");
        alternate.type = "button";
        alternate.className = "small-action";
        alternate.textContent = [t("alternateProvider"), order.alternate_provider_id, order.alternate_provider_price_label].filter(Boolean).join(" ");
        alternate.addEventListener("click", () => alternateOrder(order, alternate));
        actions.append(alternate);
      }

      if (order.public_status === "waiting" && order.mode !== "rental") {
        const cancel = document.createElement("button");
        cancel.type = "button";
        cancel.className = "danger-action";
        cancel.disabled = !order.can_cancel;
        cancel.textContent = order.can_cancel ? t("cancel") : `${t("cancelWait")} ${formatDuration(order.cancel_wait_sec)}`;
        cancel.addEventListener("click", () => cancelOrder(order.id, cancel));
        actions.append(cancel);
      }
      if (order.mode === "rental" && order.can_renew) {
        const renew = document.createElement("button");
        renew.type = "button";
        renew.className = "small-action";
        renew.textContent = t("renew");
        renew.addEventListener("click", () => rentalProviderAction(order.id, "renew", renew));
        actions.append(renew);
      }
      if (order.mode === "rental" && order.can_wake) {
        const wake = document.createElement("button");
        wake.type = "button";
        wake.className = "small-action";
        wake.textContent = t("wake");
        wake.addEventListener("click", () => rentalProviderAction(order.id, "wake", wake));
        actions.append(wake);
      }
      if (order.mode === "rental" && order.can_notes) {
        const notes = document.createElement("button");
        notes.type = "button";
        notes.className = "small-action";
        notes.textContent = t("notesTags");
        notes.addEventListener("click", () => rentalProviderAction(order.id, "notes", notes));
        actions.append(notes);
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
  scheduleOrderPoll();
}

async function refreshOrders({ quiet = false } = {}) {
  if (!canUseTelegramAuth()) {
    renderActiveOrders([]);
    return;
  }
  try {
    const payload = await api("/mini/numbers/api/orders");
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    renderActiveOrders(payload.orders || []);
  } catch (error) {
    if (!quiet) els.statusLine.textContent = error.message || t("error");
    scheduleOrderPoll();
  }
}

async function refreshSingleOrder(orderId, button) {
  if (!orderId) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/refresh`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
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
  showBusy(t("refundWorking"), t("refundWait"));
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/cancel`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || "";
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    hideBusy();
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

async function rentalProviderAction(orderId, action, button) {
  if (!orderId || !action) return;
  const confirmed = action === "renew" ? await askConfirm(t("renew")) : true;
  if (!confirmed) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/${action}`, { method: "POST", body: {} });
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

async function requestSecondCode(order, button) {
  if (!order?.id) return;
  const confirmed = await askConfirm(`${t("confirmSecondCode")} ${order.second_code_price_label || ""}`);
  if (!confirmed) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(order.id)}/second-code`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== order.id);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || t("secondCodeRequested");
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    button.disabled = false;
  }
}

async function replaceOrder(order, button) {
  if (!order?.id) return;
  const confirmed = await askConfirm(t("confirmTryAnother"));
  if (!confirmed) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(order.id)}/replace`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== order.id);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || t("replacementRequested");
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    button.disabled = false;
  }
}

async function alternateOrder(order, button) {
  if (!order?.id) return;
  const confirmed = await askConfirm([t("confirmAlternateProvider"), order.alternate_provider_id, order.alternate_provider_price_label].filter(Boolean).join(" "));
  if (!confirmed) return;
  button.disabled = true;
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(order.id)}/alternate`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== order.id);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || t("replacementRequested");
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    button.disabled = false;
  }
}

async function downloadRecording(order, button) {
  if (!order?.recording_url) return;
  button.disabled = true;
  try {
    const response = await fetch(order.recording_url, {
      headers: headers(),
      cache: "no-store",
    });
    if (!response.ok) {
      let message = t("error");
      try {
        const payload = await response.json();
        message = payload?.message || message;
      } catch (_error) {
        message = response.statusText || message;
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "call-recording";
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
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

function renderProviders(rows, { preserve = false } = {}) {
  if (!preserve) {
    state.providerRows = rows || [];
  }
  const allRows = preserve ? state.providerRows : rows || [];
  els.resultCount.textContent = String(allRows.length);
  if (!allRows.length) {
    els.providerList.replaceChildren(emptyState(t("empty")));
    return;
  }

  const recommended = allRows.find((row) => row.recommended) || allRows[0];
  const visibleRows = state.showAllProviders ? allRows : [recommended];
  const cards = visibleRows.map((row) => {
    const card = document.createElement("article");
    card.className = `provider-card${row.recommended ? " best" : ""}`;

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
    const details = [];
    if (row.recommended) details.push(t("bestChoice"));
    if (row.voice_fallback) details.push(t("voiceFallback"));
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

    if ((state.mode === "temp" || state.mode === "voice") && row.quote_token) {
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
      price.textContent = state.mode === "rental" && row.options?.length ? row.options[0].price_label : row.price_label;
      card.append(main, price);
    }
    return card;
  });

  if (allRows.length > 1) {
    const showAll = document.createElement("button");
    showAll.type = "button";
    showAll.className = "show-providers-action";
    showAll.textContent = state.showAllProviders ? t("hideOtherProviders") : `${t("showOtherProviders")} (${allRows.length - 1})`;
    showAll.addEventListener("click", () => {
      state.showAllProviders = !state.showAllProviders;
      renderProviders([], { preserve: true });
    });
    cards.push(showAll);
  }

  els.providerList.replaceChildren(...cards);
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

function activityCard(rows = []) {
  const card = document.createElement("div");
  card.className = "activity-card";
  const title = document.createElement("h3");
  title.textContent = t("recentActivity");
  card.append(title);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "order-meta";
    empty.textContent = t("noActivity");
    card.append(empty);
    return card;
  }
  rows.slice(0, 8).forEach((row) => {
    const item = document.createElement("div");
    item.className = `activity-row ${Number(row.amount || 0) >= 0 ? "credit" : "debit"}`;
    const main = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = row.label || "-";
    const meta = document.createElement("span");
    meta.textContent = [row.created_at, row.balance_label ? `${t("afterBalance")}: ${row.balance_label}` : ""].filter(Boolean).join(" · ");
    main.append(label, meta);
    const amount = document.createElement("b");
    amount.textContent = row.amount_label || "-";
    item.append(main, amount);
    card.append(item);
  });
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
  state.rechargeUrl = payload.links?.recharge || state.rechargeUrl;
  renderSupportCategories();
  els.accountDetails.replaceChildren(
    infoCard(t("balance"), payload.balance_label || "-"),
    infoCard(t("userId"), String(user.id || "-")),
    infoCard(t("username"), user.username ? `@${user.username}` : "-"),
    infoCard(t("language"), user.language_label || user.language || "-"),
    infoCard(t("joined"), user.joined_at || "-"),
    activityCard(payload.recent_activity || [])
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
  if (!state.selectedService) {
    els.statusLine.textContent = t("chooseServiceFirst");
    renderProviders([]);
    updateServiceLabel();
    return;
  }
  setServiceMenuOpen(false);
  updateStateVisibility();
  updateServiceLabel();
  state.showAllProviders = false;
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
  state.selectedService = payload.defaults?.service || "";
  state.selectedCountry = payload.defaults?.country || "none";
  state.selectedState = payload.defaults?.state || "none";
  state.supportBotUrl = payload.links?.numbers_bot || state.supportBotUrl;
  state.rechargeUrl = payload.links?.recharge || state.rechargeUrl;
  renderViewTabs();
  renderModes();
  renderSelectors();
  renderQuickServices();
  renderProviders([]);
  renderActiveOrders([]);
  refreshOrders({ quiet: true });
  if (canUseTelegramAuth()) loadAccount();
  els.countrySelect.addEventListener("change", () => {
    state.selectedCountry = els.countrySelect.value || "none";
    updateStateVisibility();
  });
  els.stateSelect.addEventListener("change", () => {
    state.selectedState = els.stateSelect.value || "none";
  });
  els.serviceTrigger.addEventListener("click", () => setServiceMenuOpen(!state.serviceMenuOpen));
  els.serviceSearch.addEventListener("input", renderServiceOptions);
  document.addEventListener("click", (event) => {
    if (!state.serviceMenuOpen) return;
    const target = event.target;
    if (els.serviceMenu.contains(target) || els.serviceTrigger.contains(target)) return;
    setServiceMenuOpen(false);
  });
  els.quoteButton.addEventListener("click", checkPrices);
  els.langArButton.addEventListener("click", () => changeLanguage("ar", els.langArButton));
  els.langEnButton.addEventListener("click", () => changeLanguage("en", els.langEnButton));
  els.sessionPill.addEventListener("click", () => openTelegramUrl(state.rechargeUrl || state.account?.links?.recharge || state.supportBotUrl));
  els.rechargeButton.addEventListener("click", () => openTelegramUrl(state.rechargeUrl || state.account?.links?.recharge || state.supportBotUrl));
  els.sendSupportButton.addEventListener("click", sendSupportTicket);
}

boot().catch(() => {
  setLanguage();
  renderViewTabs();
  els.statusLine.textContent = t("error");
  renderProviders([]);
  renderActiveOrders([]);
});
