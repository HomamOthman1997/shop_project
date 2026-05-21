const tg = window.Telegram?.WebApp;

const MODE_SELECTION_DEFAULTS = {
  temp: { service: "", country: "none", state: "none" },
  rental: { service: "", country: "none", state: "none" },
  voice: { service: "", country: "1", state: "none" },
};

function defaultModeSelection(mode) {
  return { ...(MODE_SELECTION_DEFAULTS[mode] || MODE_SELECTION_DEFAULTS.temp) };
}

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
  modeSelections: {
    temp: defaultModeSelection("temp"),
    rental: defaultModeSelection("rental"),
    voice: defaultModeSelection("voice"),
  },
  orderFlowOpen: false,
  pricesChecked: false,
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
  countryMenuOpen: false,
  stateMenuOpen: false,
  busyCount: 0,
};

const ORDER_POLL_INTERVAL_MS = 12000;

const els = {
  bootSplash: document.getElementById("bootSplash"),
  viewTabs: document.getElementById("viewTabs"),
  buyView: document.getElementById("buyView"),
  introBand: document.getElementById("introBand"),
  requestNumberButton: document.getElementById("requestNumberButton"),
  controlBand: document.getElementById("controlBand"),
  modeSwitch: document.getElementById("modeSwitch"),
  fieldGrid: document.getElementById("fieldGrid"),
  serviceTrigger: document.getElementById("serviceTrigger"),
  serviceLabel: document.getElementById("serviceLabel"),
  serviceMenu: document.getElementById("serviceMenu"),
  serviceSearch: document.getElementById("serviceSearch"),
  servicesList: document.getElementById("servicesList"),
  countryTrigger: document.getElementById("countryTrigger"),
  countryLabel: document.getElementById("countryLabel"),
  countryMenu: document.getElementById("countryMenu"),
  countrySearch: document.getElementById("countrySearch"),
  countryList: document.getElementById("countryList"),
  countrySelect: document.getElementById("countrySelect"),
  countryField: document.getElementById("countryField"),
  stateTrigger: document.getElementById("stateTrigger"),
  stateLabel: document.getElementById("stateLabel"),
  stateMenu: document.getElementById("stateMenu"),
  stateSearch: document.getElementById("stateSearch"),
  stateList: document.getElementById("stateList"),
  stateSelect: document.getElementById("stateSelect"),
  stateField: document.getElementById("stateField"),
  quickServices: document.getElementById("quickServices"),
  quoteButton: document.getElementById("quoteButton"),
  resultBand: document.getElementById("resultBand"),
  providerList: document.getElementById("providerList"),
  statusLine: document.getElementById("statusLine"),
  resultCount: document.getElementById("resultCount"),
  selectionTitle: document.getElementById("selectionTitle"),
  successLegend: document.getElementById("successLegend"),
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
    beforeOrder: "قبل الطلب",
    introTitle: "تنبيهات مهمة قبل طلب الرقم",
    introNotice1: "اختر الخدمة المطلوبة بدقة. الرقم يعمل للخدمة المحددة فقط.",
    introNotice2: "للأرقام الأمريكية، اختيار أي ولاية غالباً يعطي أسعار أفضل من ولاية محددة.",
    introNotice3: "إذا لم يصل الكود أو المكالمة، التطبيق يفحص المزود ويتابع الاسترجاع تلقائياً عند توفر شروطه.",
    requestNumber: "طلب رقم",
    service: "الخدمة",
    country: "الدولة",
    state: "الولاية",
    check: "فحص الأسعار",
    providers: "المزودين",
    successLegend: "★ تعني نسبة نجاح المزود",
    bestPrice: "أفضل سعر",
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
    openingRecharge: "فتح الشحن",
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
    beforeOrder: "Before ordering",
    introTitle: "Important notes before requesting a number",
    introNotice1: "Choose the exact service. The number is reserved for the selected service only.",
    introNotice2: "Leaving the state unset usually provides more options and better prices.",
    introNotice3: "If no code or call arrives, the app checks the provider and follows the refund flow when eligible.",
    requestNumber: "Request number",
    service: "Service",
    chooseService: "Choose service",
    chooseServiceFirst: "Choose a service first",
    country: "Country",
    chooseCountry: "Any country",
    searchCountry: "Search country",
    state: "State",
    chooseState: "Any state",
    searchState: "Search state",
    stateHint: "Leaving the state unset usually provides more options and better prices. Adding a custom state may increase the number price by 20%.",
    check: "Check prices",
    providers: "Providers",
    successLegend: "★ means provider success rate",
    bestPrice: "Best price",
    bestChoice: "Best choice",
    showOtherProviders: "Show other providers",
    hideOtherProviders: "Show best choice only",
    loading: "Checking providers",
    ready: "Choose a service and country, then check prices",
    empty: "No offers are available for this selection",
    emptyVoice: "No call route is available for this service right now.",
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
    openingRecharge: "Opening recharge",
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
    working: "Working",
    pleaseWait: "Please wait.",
    checkingOrder: "Checking order",
    voiceFallback: "Generic voice route",
    checkCall: "Check call",
    rentalSms: "Check SMS",
    noSmsYet: "No SMS yet",
    optionRenewable: "Renewable",
    optionSingle: "One time",
    optionState: "State",
  },
};

Object.assign(copy.ar, {
  title: "الأرقام",
  tabBuy: "شراء",
  tabOrders: "طلباتي",
  tabAccount: "حسابي",
  tabSupport: "الدعم",
  beforeOrder: "قبل الطلب",
  introTitle: "تنبيهات مهمة قبل طلب الرقم",
  introNotice1: "اختر الخدمة المطلوبة بدقة. الرقم يعمل للخدمة المحددة فقط.",
  introNotice2: "عدم استخدام ولاية محددة يساعد على الحصول على سعر أرخص ومزودات أكثر.",
  introNotice3: "إذا لم يصل الكود أو المكالمة، التطبيق يفحص المزود ويتابع الاسترجاع تلقائياً عند توفر شروطه.",
  requestNumber: "طلب رقم",
  service: "الخدمة",
  chooseService: "اختر الخدمة",
  chooseServiceFirst: "اختر الخدمة أولاً",
  country: "الدولة",
  chooseCountry: "أي دولة",
  searchCountry: "ابحث عن دولة",
  state: "الولاية",
  chooseState: "أي ولاية",
  searchState: "ابحث عن ولاية",
  stateHint: "عدم استخدام ولاية محددة يساعد على الحصول على سعر أرخص ومزودات أكثر. علماً أن إضافة ولاية مخصصة قد تزيد سعر الرقم بنسبة 20%.",
  check: "فحص الأسعار",
  providers: "المزودين",
  successLegend: "★ تعني نسبة نجاح المزود",
  bestPrice: "أفضل سعر",
  bestChoice: "أفضل خيار",
  showOtherProviders: "عرض باقي المزودات",
  hideOtherProviders: "عرض أفضل خيار فقط",
  loading: "جاري فحص المزودين",
  ready: "اختر الخدمة والدولة ثم افحص السعر",
  empty: "لا توجد عروض متاحة لهذا الاختيار",
  emptyVoice: "لا يوجد مسار اتصال متاح لهذه الخدمة حالياً.",
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
  working: "جاري التنفيذ",
  pleaseWait: "يرجى الانتظار.",
  checkingOrder: "جاري فحص الطلب",
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
  openingRecharge: "فتح الشحن",
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
  checkCall: "\u0641\u062d\u0635 \u0627\u0644\u0645\u0643\u0627\u0644\u0645\u0629",
  rentalSms: "\u062c\u0644\u0628 SMS",
  noSmsYet: "\u0644\u0627 \u064a\u0648\u062c\u062f SMS \u0628\u0639\u062f",
  optionRenewable: "\u0642\u0627\u0628\u0644 \u0644\u0644\u062a\u062c\u062f\u064a\u062f",
  optionSingle: "\u0645\u0631\u0629 \u0648\u0627\u062d\u062f\u0629",
  optionState: "\u0648\u0644\u0627\u064a\u0629",
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
  if (els.countrySearch) {
    els.countrySearch.placeholder = t("searchCountry");
  }
  if (els.stateSearch) {
    els.stateSearch.placeholder = t("searchState");
  }
  updateServiceLabel();
  updateSelectorLabels();
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

function telegramDeepLink(url) {
  try {
    const parsed = new URL(url);
    if (!/^(t\.me|telegram\.me)$/i.test(parsed.hostname)) return "";
    const domain = parsed.pathname.replace(/^\/+/, "").split("/")[0];
    if (!domain) return "";
    const params = new URLSearchParams({ domain });
    const start = parsed.searchParams.get("start");
    if (start) params.set("start", start);
    return `tg://resolve?${params.toString()}`;
  } catch (_error) {
    return "";
  }
}

function clickExternalLink(url) {
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener";
  document.body.append(link);
  link.click();
  link.remove();
}

function openTelegramUrl(url) {
  if (!url) return false;
  const deepLink = telegramDeepLink(url);
  try {
    if (tg?.openTelegramLink && /^https?:\/\/(t\.me|telegram\.me)\//i.test(url)) {
      tg.openTelegramLink(url);
      return true;
    }
  } catch (_error) {
    // Fall through to direct Telegram link navigation.
  }
  if (deepLink) {
    try {
      window.location.href = deepLink;
      window.setTimeout(() => {
        window.location.href = url;
      }, 450);
      return true;
    } catch (_error) {
      // Fall through to the generic opener.
    }
  }
  try {
    if (tg?.openLink) {
      tg.openLink(url);
      return true;
    }
  } catch (_error) {
    // Fall through to browser navigation.
  }
  try {
    clickExternalLink(url);
    return true;
  } catch (_error) {
    window.location.href = url;
    return true;
  }
}

function rechargeUrl() {
  return state.rechargeUrl || state.account?.links?.recharge || state.supportBotUrl || state.account?.links?.numbers_bot || "";
}

function openRecharge() {
  const url = rechargeUrl();
  if (url) {
    els.statusLine.textContent = t("openingRecharge");
    openTelegramUrl(url);
    return;
  }
  setView("account");
  els.statusLine.textContent = t("error");
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

function finishBoot() {
  document.body.classList.remove("app-booting");
  els.bootSplash?.remove();
  els.bootSplash = null;
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

function renderBuyFlow() {
  els.introBand?.classList.toggle("hidden", state.orderFlowOpen);
  els.controlBand?.classList.toggle("hidden", !state.orderFlowOpen);
  els.resultBand?.classList.toggle("hidden", !state.pricesChecked);
  els.successLegend?.classList.toggle("hidden", !state.pricesChecked);
}

function openOrderFlow() {
  state.orderFlowOpen = true;
  renderBuyFlow();
  window.setTimeout(() => {
    els.controlBand?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 0);
}

function showPriceResults() {
  state.pricesChecked = true;
  renderBuyFlow();
}

function clearPriceResults() {
  state.pricesChecked = false;
  renderBuyFlow();
}

function modeSelection(mode = state.mode) {
  if (!state.modeSelections[mode]) {
    state.modeSelections[mode] = defaultModeSelection(mode);
  }
  return state.modeSelections[mode];
}

function saveModeSelection(mode = state.mode) {
  const selection = modeSelection(mode);
  selection.service = state.selectedService || "";
  selection.country = mode === "voice" ? "1" : state.selectedCountry || "none";
  selection.state = (selection.country === "1" ? state.selectedState : "none") || "none";
}

function loadModeSelection(mode = state.mode) {
  const selection = modeSelection(mode);
  state.selectedService = selection.service || "";
  state.selectedCountry = mode === "voice" ? "1" : selection.country || "none";
  state.selectedState = state.selectedCountry === "1" ? selection.state || "none" : "none";
}

function scrollToResults() {
  window.setTimeout(() => {
    els.resultBand?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 60);
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
    setSelectorMenuOpen("country", false);
    setSelectorMenuOpen("state", false);
    renderServiceOptions();
    window.setTimeout(() => els.serviceSearch?.focus(), 0);
  }
}

function setServiceSelection(key) {
  state.selectedService = key || "";
  els.serviceSearch.value = "";
  state.showAllProviders = false;
  saveModeSelection();
  clearPriceResults();
  updateStateVisibility();
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

function optionText(item, kind) {
  if (!item) return "";
  if (kind === "country") {
    return item.iso ? `${item.name} (${item.iso})` : item.name;
  }
  return item.name || item.code || "";
}

function selectedOption(list, code) {
  return list.find((item) => String(item.code) === String(code));
}

function searchTokens(item) {
  const aliases = Array.isArray(item?.aliases) ? item.aliases : [];
  return [item?.name, item?.code, item?.iso, ...aliases].map((value) => String(value || "").toLowerCase());
}

function selectorMatches(item, query) {
  const lowered = String(query || "").trim().toLowerCase();
  if (!lowered) return true;
  return searchTokens(item).some((value) => value.includes(lowered));
}

function updateSelectorLabels() {
  const country = selectedOption(state.countries, state.selectedCountry);
  const stateRow = selectedOption(state.states, state.selectedState);
  if (els.countryLabel) {
    els.countryLabel.textContent = optionText(country, "country") || t("chooseCountry");
  }
  if (els.stateLabel) {
    els.stateLabel.textContent = optionText(stateRow, "state") || t("chooseState");
  }
  if (els.countrySelect) {
    els.countrySelect.value = state.selectedCountry;
  }
  if (els.stateSelect) {
    els.stateSelect.value = state.selectedState;
  }
}

function setSelectorMenuOpen(kind, open) {
  const isCountry = kind === "country";
  if (open && !state.selectedService && (isCountry || kind === "state")) {
    els.statusLine.textContent = t("chooseServiceFirst");
    return;
  }
  if (open && !isCountry && state.selectedCountry !== "1") {
    return;
  }
  const menuKey = isCountry ? "countryMenuOpen" : "stateMenuOpen";
  state[menuKey] = Boolean(open);
  const menu = isCountry ? els.countryMenu : els.stateMenu;
  const trigger = isCountry ? els.countryTrigger : els.stateTrigger;
  const search = isCountry ? els.countrySearch : els.stateSearch;
  menu?.classList.toggle("hidden", !state[menuKey]);
  trigger?.setAttribute("aria-expanded", state[menuKey] ? "true" : "false");
  if (state[menuKey]) {
    setServiceMenuOpen(false);
    if (isCountry) {
      setSelectorMenuOpen("state", false);
      renderCountryOptions();
    } else {
      setSelectorMenuOpen("country", false);
      renderStateOptions();
    }
    window.setTimeout(() => search?.focus(), 0);
  }
}

function setCountrySelection(code) {
  if (!state.selectedService) {
    els.statusLine.textContent = t("chooseServiceFirst");
    setSelectorMenuOpen("country", false);
    return;
  }
  state.selectedCountry = state.mode === "voice" ? "1" : code || "none";
  if (state.selectedCountry !== "1") {
    state.selectedState = "none";
    if (els.stateSearch) els.stateSearch.value = "";
    setSelectorMenuOpen("state", false);
  }
  if (els.countrySearch) els.countrySearch.value = "";
  state.showAllProviders = false;
  saveModeSelection();
  clearPriceResults();
  updateStateVisibility();
  updateSelectorLabels();
  renderProviders([]);
  setSelectorMenuOpen("country", false);
}

function setStateSelection(code) {
  if (!state.selectedService) {
    els.statusLine.textContent = t("chooseServiceFirst");
    setSelectorMenuOpen("state", false);
    return;
  }
  state.selectedState = code || "none";
  if (els.stateSearch) els.stateSearch.value = "";
  state.showAllProviders = false;
  saveModeSelection();
  clearPriceResults();
  updateSelectorLabels();
  renderProviders([]);
  setSelectorMenuOpen("state", false);
}

function renderCountryOptions() {
  const query = els.countrySearch?.value || "";
  const filtered = state.countries.filter((item) => selectorMatches(item, query)).slice(0, 90);
  if (!filtered.length) {
    els.countryList.replaceChildren(emptyState(t("empty")));
    return;
  }
  els.countryList.replaceChildren(
    ...filtered.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `select-option${state.selectedCountry === item.code ? " active" : ""}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", state.selectedCountry === item.code ? "true" : "false");
      const label = document.createElement("strong");
      label.textContent = optionText(item, "country");
      const key = document.createElement("span");
      key.textContent = item.code === "none" ? "" : item.code;
      button.append(label, key);
      button.addEventListener("click", () => setCountrySelection(item.code));
      return button;
    })
  );
}

function renderStateOptions() {
  const query = els.stateSearch?.value || "";
  const filtered = state.states.filter((item) => selectorMatches(item, query)).slice(0, 90);
  if (!filtered.length) {
    els.stateList.replaceChildren(emptyState(t("empty")));
    return;
  }
  els.stateList.replaceChildren(
    ...filtered.map((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `select-option${state.selectedState === item.code ? " active" : ""}`;
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", state.selectedState === item.code ? "true" : "false");
      const label = document.createElement("strong");
      label.textContent = optionText(item, "state");
      const key = document.createElement("span");
      key.textContent = item.code === "none" ? "" : item.code;
      button.append(label, key);
      button.addEventListener("click", () => setStateSelection(item.code));
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
        if (state.mode === key) return;
        saveModeSelection();
        state.mode = key;
        loadModeSelection(key);
        if (els.serviceSearch) els.serviceSearch.value = "";
        if (els.countrySearch) els.countrySearch.value = "";
        if (els.stateSearch) els.stateSearch.value = "";
        state.showAllProviders = false;
        clearPriceResults();
        setServiceMenuOpen(false);
        setSelectorMenuOpen("country", false);
        setSelectorMenuOpen("state", false);
        updateStateVisibility();
        updateSelectorLabels();
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
  renderCountryOptions();
  renderStateOptions();
  updateSelectorLabels();
  updateStateVisibility();
}

function updateStateVisibility() {
  const hasService = Boolean(state.selectedService);
  const showCountry = hasService;
  const showState = hasService && state.selectedCountry === "1";
  els.countryField?.classList.toggle("hidden", !showCountry);
  els.stateField.classList.toggle("hidden", !showState);
  els.countrySelect.disabled = !showCountry;
  els.stateSelect.disabled = !showState;
  if (els.countryTrigger) {
    els.countryTrigger.disabled = !showCountry;
    els.countryTrigger.setAttribute("aria-disabled", showCountry ? "false" : "true");
  }
  if (els.stateTrigger) {
    els.stateTrigger.disabled = !showState;
    els.stateTrigger.setAttribute("aria-disabled", showState ? "false" : "true");
  }
  els.fieldGrid?.classList.toggle("service-only", !showCountry);
  els.fieldGrid?.classList.toggle("service-country", showCountry && !showState);
  els.fieldGrid?.classList.toggle("service-country-state", showCountry && showState);
  if (!showCountry) {
    setSelectorMenuOpen("country", false);
  }
  if (!showState) {
    state.selectedState = "none";
    els.stateSelect.value = "none";
    setSelectorMenuOpen("state", false);
  }
  updateSelectorLabels();
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
      if (order.mode === "rental" && Array.isArray(order.messages) && order.messages.length > 1) {
        const messageList = document.createElement("div");
        messageList.className = "order-message-list";
        order.messages.slice(-5).forEach((message) => {
          const item = document.createElement("span");
          item.textContent = message;
          messageList.append(item);
        });
        main.append(messageList);
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
        refresh.textContent = order.mode === "voice" ? t("checkCall") : t("refresh");
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
      if (order.mode === "rental" && order.can_sms) {
        const sms = document.createElement("button");
        sms.type = "button";
        sms.className = "small-action";
        sms.textContent = t("rentalSms");
        sms.addEventListener("click", () => rentalProviderAction(order.id, "sms", sms));
        actions.append(sms);
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
  showBusy(t("checkingOrder"), t("pleaseWait"));
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
    hideBusy();
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
  showBusy(t("working"), t("pleaseWait"));
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/finish`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    els.statusLine.textContent = payload.message || "";
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    hideBusy();
    button.disabled = false;
  }
}

async function rentalProviderAction(orderId, action, button) {
  if (!orderId || !action) return;
  const confirmed = action === "renew" ? await askConfirm(t("renew")) : true;
  if (!confirmed) return;
  button.disabled = true;
  showBusy(t("working"), t("pleaseWait"));
  try {
    const payload = await api(`/mini/numbers/api/orders/${encodeURIComponent(orderId)}/${action}`, { method: "POST", body: {} });
    const next = state.activeOrders.filter((item) => item.id !== orderId);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    els.statusLine.textContent = payload.message || "";
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    hideBusy();
    button.disabled = false;
  }
}

async function requestSecondCode(order, button) {
  if (!order?.id) return;
  const confirmed = await askConfirm(`${t("confirmSecondCode")} ${order.second_code_price_label || ""}`);
  if (!confirmed) return;
  button.disabled = true;
  showBusy(t("working"), t("pleaseWait"));
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
    hideBusy();
    button.disabled = false;
  }
}

async function replaceOrder(order, button) {
  if (!order?.id) return;
  const confirmed = await askConfirm(t("confirmTryAnother"));
  if (!confirmed) return;
  button.disabled = true;
  showBusy(t("working"), t("pleaseWait"));
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
    hideBusy();
    button.disabled = false;
  }
}

async function alternateOrder(order, button) {
  if (!order?.id) return;
  const confirmed = await askConfirm([t("confirmAlternateProvider"), order.alternate_provider_id, order.alternate_provider_price_label].filter(Boolean).join(" "));
  if (!confirmed) return;
  button.disabled = true;
  showBusy(t("working"), t("pleaseWait"));
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
    hideBusy();
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
  showBusy(t("purchasing"), t("pleaseWait"));
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
    hideBusy();
    button.disabled = false;
  }
}

function rentalOptionLabel(option) {
  const parts = [option.duration_label || option.duration || t("options")];
  if (option.renewable) {
    parts.push(t("optionRenewable"));
  } else if (Object.prototype.hasOwnProperty.call(option, "renewable")) {
    parts.push(t("optionSingle"));
  }
  if (option.with_state && option.state_code && option.state_code !== "none") {
    parts.push(`${t("optionState")} ${option.state_code}`);
  }
  if (option.price_label) {
    parts.push(option.price_label);
  }
  return parts.filter(Boolean).join(" \u00b7 ");
}

function renderProviders(rows, { preserve = false } = {}) {
  if (!preserve) {
    state.providerRows = rows || [];
  }
  const allRows = preserve ? state.providerRows : rows || [];
  els.resultCount.textContent = String(allRows.length);
  if (!allRows.length) {
    els.providerList.replaceChildren();
    return;
  }

  const recommended = allRows.find((row) => row.recommended) || allRows[0];
  const visibleRows = state.showAllProviders ? allRows : [recommended];
  const cards = visibleRows.map((row) => {
    const card = document.createElement("article");
    card.className = `provider-card${row.recommended ? " best" : ""}`;

    const main = document.createElement("div");
    main.className = "provider-main";

    const successBadge = document.createElement("span");
    successBadge.className = "success-badge";
    successBadge.title = t("successLegend");
    successBadge.textContent = `\u2605 ${row.success_rate || "-"}`;
    card.append(successBadge);

    const name = document.createElement("p");
    name.className = "provider-name";
    name.textContent = row.provider;

    const meta = document.createElement("p");
    meta.className = "provider-meta";
    const details = [];
    if (row.recommended) details.push(t("bestPrice"));
    if (row.location_tag) details.push(`[${row.location_tag}]`);
    if (row.voice_fallback) details.push(t("voiceFallback"));
    meta.textContent = details.join(" · ");

    main.append(name, meta);
    if (row.options?.length) {
      const options = document.createElement("div");
      options.className = "option-row";
      row.options.forEach((option) => {
        const pill = document.createElement(state.mode === "rental" && option.quote_token ? "button" : "span");
        pill.className = "option-pill";
        if (pill.tagName === "BUTTON") {
          pill.type = "button";
          pill.classList.add("buyable");
          pill.addEventListener("click", () => buyProvider({ ...row, price_label: option.price_label, quote_token: option.quote_token }, pill));
        }
        const optionText = state.mode === "rental" ? rentalOptionLabel(option) : `${option.duration_label || option.duration || t("options")} ${option.price_label}`;
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

function rechargeActionCard(balanceLabel) {
  const card = document.createElement("div");
  card.className = "settings-action-card";
  const copy = document.createElement("div");
  const label = document.createElement("span");
  label.className = "info-label";
  label.textContent = t("balance");
  const value = document.createElement("strong");
  value.className = "info-value";
  value.textContent = balanceLabel || "-";
  copy.append(label, value);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "small-action";
  button.textContent = t("recharge");
  button.addEventListener("click", openRecharge);
  card.append(copy, button);
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
    rechargeActionCard(payload.balance_label || "-"),
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
  state.selectedCountry = state.mode === "voice" ? "1" : state.selectedCountry || els.countrySelect.value || "none";
  state.selectedState = state.selectedCountry === "1" ? state.selectedState || els.stateSelect.value || "none" : "none";
  saveModeSelection();
  if (!state.selectedService) {
    els.statusLine.textContent = t("chooseServiceFirst");
    renderProviders([]);
    updateServiceLabel();
    return;
  }
  showPriceResults();
  setServiceMenuOpen(false);
  setSelectorMenuOpen("country", false);
  setSelectorMenuOpen("state", false);
  updateStateVisibility();
  updateServiceLabel();
  updateSelectorLabels();
  state.showAllProviders = false;
  els.selectionTitle.textContent = serviceLabel(state.selectedService);
  els.statusLine.textContent = t("loading");
  clearPriceResults();
  renderProviders([]);
  setLoading(true);
  try {
    const params = new URLSearchParams({
      mode: state.mode,
      service: state.selectedService,
      country: state.selectedCountry,
      state: state.selectedState,
    });
    const payload = await api(`/mini/numbers/api/prices?${params.toString()}`);
    const rows = payload.providers || [];
    if (payload.ok === false || !rows.length) {
      els.statusLine.textContent = payload.message || (state.mode === "voice" ? t("emptyVoice") : t("empty"));
      renderProviders([]);
      return;
    }
    els.statusLine.textContent = "";
    showPriceResults();
    renderProviders(rows);
    scrollToResults();
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
  state.mode = ["temp", "rental", "voice"].includes(payload.defaults?.mode) ? payload.defaults.mode : "temp";
  state.modeSelections = {
    temp: {
      ...defaultModeSelection("temp"),
      service: payload.defaults?.service || "",
      country: payload.defaults?.country || "none",
      state: payload.defaults?.state || "none",
    },
    rental: defaultModeSelection("rental"),
    voice: defaultModeSelection("voice"),
  };
  loadModeSelection(state.mode);
  state.supportBotUrl = payload.links?.numbers_bot || state.supportBotUrl;
  state.rechargeUrl = payload.links?.recharge || state.rechargeUrl;
  renderViewTabs();
  renderBuyFlow();
  renderModes();
  renderSelectors();
  renderQuickServices();
  renderProviders([]);
  renderActiveOrders([]);
  refreshOrders({ quiet: true });
  if (canUseTelegramAuth()) {
    await loadAccount();
  }
  els.countrySelect.addEventListener("change", () => {
    setCountrySelection(els.countrySelect.value || "none");
  });
  els.stateSelect.addEventListener("change", () => {
    setStateSelection(els.stateSelect.value || "none");
  });
  els.serviceTrigger.addEventListener("click", () => setServiceMenuOpen(!state.serviceMenuOpen));
  els.serviceSearch.addEventListener("input", renderServiceOptions);
  els.countryTrigger.addEventListener("click", () => setSelectorMenuOpen("country", !state.countryMenuOpen));
  els.countrySearch.addEventListener("input", renderCountryOptions);
  els.stateTrigger.addEventListener("click", () => setSelectorMenuOpen("state", !state.stateMenuOpen));
  els.stateSearch.addEventListener("input", renderStateOptions);
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (state.serviceMenuOpen && !els.serviceMenu.contains(target) && !els.serviceTrigger.contains(target)) {
      setServiceMenuOpen(false);
    }
    if (state.countryMenuOpen && !els.countryMenu.contains(target) && !els.countryTrigger.contains(target)) {
      setSelectorMenuOpen("country", false);
    }
    if (state.stateMenuOpen && !els.stateMenu.contains(target) && !els.stateTrigger.contains(target)) {
      setSelectorMenuOpen("state", false);
    }
  });
  els.quoteButton.addEventListener("click", checkPrices);
  els.requestNumberButton.addEventListener("click", openOrderFlow);
  els.langArButton.addEventListener("click", () => changeLanguage("ar", els.langArButton));
  els.langEnButton.addEventListener("click", () => changeLanguage("en", els.langEnButton));
  els.sessionPill.addEventListener("click", openRecharge);
  els.rechargeButton.addEventListener("click", openRecharge);
  els.sendSupportButton.addEventListener("click", sendSupportTicket);
}

boot().catch(() => {
  setLanguage();
  renderViewTabs();
  renderBuyFlow();
  els.statusLine.textContent = t("error");
  renderProviders([]);
  renderActiveOrders([]);
}).finally(() => {
  finishBoot();
});
