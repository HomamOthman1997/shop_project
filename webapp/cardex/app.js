const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const state = {
  rules: [],
  isAdmin: false,
  hasAuth: false,
  view: "brands",
  brand: "",
  regionKey: "",
  search: "",
};

const lang = String(tg?.initDataUnsafe?.user?.language_code || navigator.language || "en").toLowerCase().startsWith("ar") ? "ar" : "en";
const rtl = lang === "ar";
const I18N = {
  en: {
    title: "CardEX Prices",
    subtitle: "Browse card brands, regions, and price categories",
    search: "Search brand or region",
    prices: "Prices",
    myCards: "My Cards",
    wallet: "Wallet",
    withdraw: "Withdraw",
    admin: "Admin",
    add: "Add",
    back: "Back",
    sell: "Sell",
    delete: "Delete",
    loadingPrices: "Loading prices...",
    brandsTitle: "Card Brands",
    brandsHint: "Choose a card type, then country, then price category",
    regionsHint: "Choose country or region",
    categories: "categories",
    regions: "regions",
    noBrands: "No brands found.",
    noRegions: "No regions found.",
    noCategories: "No categories found.",
    priceCategories: "price categories",
    trader: "trader",
    loginNeeded: "This section needs Telegram login",
    reopen: "Telegram did not send initData. Reopen CardEX from the inline bot button.",
    loadPricesFailed: "Could not load CardEX prices.",
    cardsHint: "Submitted cards and review status",
    loadingCards: "Loading cards...",
    noCards: "No cards submitted yet.",
    loadCardsFailed: "Could not load your cards.",
    walletHint: "CardEX balance summary",
    loadingWallet: "Loading wallet...",
    available: "Available",
    pending: "Pending",
    locked: "Locked",
    requestWithdrawal: "Request withdrawal",
    withdrawalHistory: "Withdrawal history",
    loadWalletFailed: "Could not load wallet.",
    withdrawals: "Withdrawals",
    withdrawalsHint: "Request payout and follow status",
    request: "Request",
    loadingWithdrawals: "Loading withdrawals...",
    noWithdrawals: "No withdrawal requests yet.",
    loadWithdrawalsFailed: "Could not load withdrawals.",
    payout: "payout",
    close: "Close",
    confirmDelete: "Delete this price category?",
    noPrice: "No price is configured for this value.",
    expectedPayout: "Expected payout",
    quoteFailed: "Could not quote this value.",
    missingPriceNotice: "This value has no price yet. Admin was notified.",
    submitted: "Card submitted. Expected payout",
    submitFailed: "Could not submit card. Check the value and code.",
    withdrawalCreated: "Withdrawal request created",
    withdrawalFailed: "Could not create withdrawal. Check available balance and payout details.",
    saving: "Saving...",
    submitting: "Submitting...",
    sending: "Sending...",
    saveCategory: "Save category",
    submitCard: "Submit card",
    sendRequest: "Send request",
    addPriceCategory: "Add price category",
    sellCard: "Sell card",
    requestWithdrawalTitle: "Request withdrawal",
    brand: "Brand",
    region: "Region",
    currency: "Currency",
    values: "Values",
    customerRate: "Customer rate %",
    traderRate: "Trader rate %",
    note: "Note",
    publicNotePlaceholder: "Optional public note",
    value: "Value",
    cardCode: "Card code",
    cardCodePlaceholder: "Enter card code",
    pinOptional: "PIN (optional)",
    pinPlaceholder: "Enter PIN if available",
    amountUsd: "Amount USD",
    payoutCurrency: "Payout currency",
    payoutDetails: "Payout details",
    payoutDetailsPlaceholder: "Wallet, account, or pickup details",
    adminAction: "Admin action",
    save: "Save",
    adminQueue: "Admin Queue",
    adminQueueHint: "Review submitted cards and open withdrawals",
    loadingAdmin: "Loading admin queue...",
    loadAdminFailed: "Could not load admin queue.",
    accept: "Accept",
    approve: "Approve",
    paid: "Paid",
    reject: "Reject",
    setPrice: "Set price",
    statement: "Statement",
    batchCards: "Batch cards",
    payment: "Payment",
    none: "none",
    todayReport: "Today Report",
    todayExports: "Today Exports",
    copy: "Copy",
    copied: "Export copied.",
    noExportContent: "No export content.",
    noCardsExport: "No cards to export today.",
    cards: "Cards",
    seller: "seller",
    code: "Code",
    noCardsReview: "No cards waiting for review.",
    missingPricing: "Missing Pricing",
    requested: "Requested",
    times: "time(s)",
    user: "user",
    noMissingPricingRows: "No missing pricing rows.",
    batchableCards: "Batchable Cards",
    noBatchableCards: "No cards ready for trader batching.",
    traders: "Traders",
    addTrader: "Add trader",
    noTraders: "No traders yet.",
    auditLogs: "Audit Logs",
    noAuditLogs: "No audit logs yet.",
    notes: "Notes",
    optional: "Optional",
    setMissingPrice: "Set missing price",
    savePrice: "Save price",
    publicNote: "Public note",
    createTrader: "Create trader",
    traderName: "Trader name",
    recordTraderPayment: "Record trader payment",
    recordPayment: "Record payment",
    amount: "Amount USD",
    method: "Method",
    methodPlaceholder: "Cash / USDT / bank",
    reference: "Reference",
    createBatch: "Create batch",
    cardIds: "Card IDs",
    cardIdsPlaceholder: "Paste IDs separated by commas or new lines",
    batchNotes: "Batch notes",
    batchCreated: "Batch created",
    referenceLabel: "Reference",
    expected: "Expected",
    profit: "Profit",
    traderStatement: "Trader statement",
    noStatement: "No statement entries.",
    loadStatementFailed: "Could not load trader statement.",
    saveCategoryFailed: "Could not save category. Check values.",
    adminActionFailed: "Could not complete this admin action.",
  },
  ar: {
    title: "أسعار CardEX",
    subtitle: "تصفح أنواع البطاقات والدول وفئات الأسعار",
    search: "ابحث عن نوع بطاقة أو دولة",
    prices: "الأسعار",
    myCards: "بطاقاتي",
    wallet: "المحفظة",
    withdraw: "السحب",
    admin: "الإدارة",
    add: "إضافة",
    back: "رجوع",
    sell: "بيع",
    delete: "حذف",
    loadingPrices: "جار تحميل الأسعار...",
    brandsTitle: "أنواع البطاقات",
    brandsHint: "اختر النوع ثم الدولة ثم فئة السعر",
    regionsHint: "اختر الدولة أو المنطقة",
    categories: "فئات",
    regions: "دول",
    noBrands: "لا توجد أنواع مطابقة.",
    noRegions: "لا توجد دول مطابقة.",
    noCategories: "لا توجد فئات مطابقة.",
    priceCategories: "فئات سعر",
    trader: "التاجر",
    loginNeeded: "هذا القسم يحتاج فتح من زر Telegram",
    reopen: "Telegram لم يرسل بيانات الدخول. افتح CardEX من زر البوت inline.",
    loadPricesFailed: "تعذر تحميل أسعار CardEX.",
    cardsHint: "البطاقات المرسلة وحالة المراجعة",
    loadingCards: "جار تحميل البطاقات...",
    noCards: "لا توجد بطاقات مرسلة بعد.",
    loadCardsFailed: "تعذر تحميل بطاقاتك.",
    walletHint: "ملخص رصيد CardEX",
    loadingWallet: "جار تحميل المحفظة...",
    available: "المتاح",
    pending: "المعلق",
    locked: "المقفل",
    requestWithdrawal: "طلب سحب",
    withdrawalHistory: "سجل السحوبات",
    loadWalletFailed: "تعذر تحميل المحفظة.",
    withdrawals: "السحوبات",
    withdrawalsHint: "اطلب السحب وتابع الحالة",
    request: "طلب",
    loadingWithdrawals: "جار تحميل السحوبات...",
    noWithdrawals: "لا توجد طلبات سحب بعد.",
    loadWithdrawalsFailed: "تعذر تحميل السحوبات.",
    payout: "سحب",
    close: "إغلاق",
    confirmDelete: "حذف فئة السعر هذه؟",
    noPrice: "لا يوجد سعر مضبوط لهذه القيمة.",
    expectedPayout: "المبلغ المتوقع",
    quoteFailed: "تعذر تسعير هذه القيمة.",
    missingPriceNotice: "هذه القيمة لا يوجد لها سعر بعد. تم تنبيه الإدارة.",
    submitted: "تم إرسال البطاقة. المبلغ المتوقع",
    submitFailed: "تعذر إرسال البطاقة. تحقق من القيمة والكود.",
    withdrawalCreated: "تم إنشاء طلب السحب",
    withdrawalFailed: "تعذر إنشاء طلب السحب. تحقق من الرصيد وتفاصيل السحب.",
    saving: "جار الحفظ...",
    submitting: "جار الإرسال...",
    sending: "جار الإرسال...",
    saveCategory: "حفظ الفئة",
    submitCard: "إرسال البطاقة",
    sendRequest: "إرسال الطلب",
    addPriceCategory: "إضافة فئة سعر",
    sellCard: "بيع بطاقة",
    requestWithdrawalTitle: "طلب سحب",
    brand: "النوع",
    region: "الدولة",
    currency: "العملة",
    values: "القيم",
    customerRate: "نسبة المستخدم %",
    traderRate: "نسبة التاجر %",
    note: "تنويه",
    publicNotePlaceholder: "تنويه يظهر للمستخدم",
    value: "القيمة",
    cardCode: "كود البطاقة",
    cardCodePlaceholder: "أدخل كود البطاقة",
    pinOptional: "PIN (اختياري)",
    pinPlaceholder: "أدخل PIN إن وجد",
    amountUsd: "المبلغ بالدولار",
    payoutCurrency: "عملة السحب",
    payoutDetails: "تفاصيل السحب",
    payoutDetailsPlaceholder: "محفظة، حساب، أو تفاصيل الاستلام",
    adminAction: "إجراء إداري",
    save: "حفظ",
    adminQueue: "قائمة الإدارة",
    adminQueueHint: "مراجعة البطاقات المرسلة والسحوبات المفتوحة",
    loadingAdmin: "جار تحميل قائمة الإدارة...",
    loadAdminFailed: "تعذر تحميل قائمة الإدارة.",
    accept: "قبول",
    approve: "موافقة",
    paid: "مدفوع",
    reject: "رفض",
    setPrice: "تسعير",
    statement: "كشف حساب",
    batchCards: "تجميع بطاقات",
    payment: "دفعة",
    none: "لا يوجد",
    todayReport: "تقرير اليوم",
    todayExports: "تصديرات اليوم",
    copy: "نسخ",
    copied: "تم نسخ التصدير.",
    noExportContent: "لا يوجد محتوى للتصدير.",
    noCardsExport: "لا توجد بطاقات للتصدير اليوم.",
    cards: "البطاقات",
    seller: "البائع",
    code: "الكود",
    noCardsReview: "لا توجد بطاقات بانتظار المراجعة.",
    missingPricing: "تسعير ناقص",
    requested: "طُلبت",
    times: "مرة",
    user: "المستخدم",
    noMissingPricingRows: "لا توجد قيم ناقصة التسعير.",
    batchableCards: "بطاقات جاهزة للتاجر",
    noBatchableCards: "لا توجد بطاقات جاهزة للتجميع.",
    traders: "التجار",
    addTrader: "إضافة تاجر",
    noTraders: "لا يوجد تجار بعد.",
    auditLogs: "سجل العمليات",
    noAuditLogs: "لا توجد عمليات بعد.",
    notes: "ملاحظات",
    optional: "اختياري",
    setMissingPrice: "تسعير قيمة ناقصة",
    savePrice: "حفظ السعر",
    publicNote: "تنويه للمستخدم",
    createTrader: "إنشاء تاجر",
    traderName: "اسم التاجر",
    recordTraderPayment: "تسجيل دفعة للتاجر",
    recordPayment: "تسجيل الدفعة",
    amount: "المبلغ بالدولار",
    method: "الطريقة",
    methodPlaceholder: "كاش / USDT / بنك",
    reference: "المرجع",
    createBatch: "إنشاء تجميعة",
    cardIds: "معرفات البطاقات",
    cardIdsPlaceholder: "الصق المعرفات مفصولة بفواصل أو أسطر",
    batchNotes: "ملاحظات التجميعة",
    batchCreated: "تم إنشاء التجميعة",
    referenceLabel: "المرجع",
    expected: "المتوقع",
    profit: "الربح",
    traderStatement: "كشف حساب التاجر",
    noStatement: "لا توجد حركات في الكشف.",
    loadStatementFailed: "تعذر تحميل كشف حساب التاجر.",
    saveCategoryFailed: "تعذر حفظ الفئة. تحقق من القيم.",
    adminActionFailed: "تعذر تنفيذ الإجراء الإداري.",
  },
};

function t(key) {
  return I18N[lang]?.[key] || I18N.en[key] || key;
}

document.documentElement.lang = lang;
document.documentElement.dir = rtl ? "rtl" : "ltr";

const BRAND_META = {
  AMAZON: { mark: "a", tone: "tone-amazon", logo: "logo-amazon" },
  ITUNES: { mark: "IT", tone: "tone-itunes", logo: "logo-itunes" },
  APPLE: { mark: "A", tone: "tone-itunes", logo: "logo-itunes" },
  RAZER: { mark: "Z", tone: "tone-razer", logo: "logo-razer" },
  "RAZER GOLD": { mark: "Z", tone: "tone-razer", logo: "logo-razer" },
  STEAM: { mark: "S", tone: "tone-steam", logo: "logo-steam" },
  WALMART: { mark: "W", tone: "tone-walmart", logo: "logo-walmart" },
  TARGET: { mark: "TG", tone: "tone-target", logo: "logo-target" },
  MASTERCARD: { mark: "MC", tone: "tone-mastercard", logo: "logo-mastercard" },
  MASTERSWAG: { mark: "MS", tone: "tone-masterswag", logo: "logo-masterswag" },
  "MASTER SWAG": { mark: "MS", tone: "tone-masterswag", logo: "logo-masterswag" },
  VISA: { mark: "V", tone: "tone-visa", logo: "logo-visa" },
  TREMENDOUS: { mark: "TR", tone: "tone-visa", logo: "logo-visa" },
  PAYPAL: { mark: "P", tone: "tone-paypal", logo: "logo-paypal" },
  PAYEER: { mark: "P", tone: "tone-payeer", logo: "logo-payeer" },
  USDT: { mark: "T", tone: "tone-usdt", logo: "logo-usdt" },
  UBER: { mark: "U", tone: "tone-uber", logo: "logo-uber" },
  STARBUCKS: { mark: "SB", tone: "tone-starbucks", logo: "logo-starbucks" },
  PLAYSTATION: { mark: "PS", tone: "tone-playstation", logo: "logo-playstation" },
  NINTENDO: { mark: "NI", tone: "tone-nintendo", logo: "logo-nintendo" },
};

const content = document.getElementById("content");
const statusEl = document.getElementById("status");
const searchInput = document.getElementById("searchInput");
const refreshBtn = document.getElementById("refreshBtn");
const pricesTab = document.getElementById("pricesTab");
const cardsTab = document.getElementById("cardsTab");
const walletTab = document.getElementById("walletTab");
const withdrawTab = document.getElementById("withdrawTab");
const adminTab = document.getElementById("adminTab");
const modal = document.getElementById("modal");
const priceForm = document.getElementById("priceForm");
const closeModal = document.getElementById("closeModal");
const sellModal = document.getElementById("sellModal");
const sellForm = document.getElementById("sellForm");
const closeSellModal = document.getElementById("closeSellModal");
const sellSummary = document.getElementById("sellSummary");
const quoteBox = document.getElementById("quoteBox");
const withdrawModal = document.getElementById("withdrawModal");
const withdrawForm = document.getElementById("withdrawForm");
const closeWithdrawModal = document.getElementById("closeWithdrawModal");
const adminFormModal = document.getElementById("adminFormModal");
const adminForm = document.getElementById("adminForm");
const adminFormTitle = document.getElementById("adminFormTitle");
const adminFormSubtitle = document.getElementById("adminFormSubtitle");
const adminFormFields = document.getElementById("adminFormFields");
const adminFormSubmit = document.getElementById("adminFormSubmit");
const closeAdminFormModal = document.getElementById("closeAdminFormModal");
let adminFormHandler = null;

function localizeStaticUi() {
  document.title = t("title");
  document.querySelector("h1").textContent = t("title");
  document.getElementById("subtitle").textContent = t("subtitle");
  searchInput.placeholder = t("search");
  refreshBtn.textContent = "↻";
  pricesTab.textContent = t("prices");
  cardsTab.textContent = t("myCards");
  walletTab.textContent = t("wallet");
  withdrawTab.textContent = t("withdraw");
  adminTab.textContent = t("admin");
  statusEl.textContent = t("loadingPrices");
  document.querySelector("#priceForm h2").textContent = t("addPriceCategory");
  document.querySelector("#sellForm h2").textContent = t("sellCard");
  document.querySelector("#withdrawForm h2").textContent = t("requestWithdrawalTitle");
  document.getElementById("adminFormTitle").textContent = t("adminAction");
  priceForm.querySelector("button[type='submit']").textContent = t("saveCategory");
  sellForm.querySelector("button[type='submit']").textContent = t("submitCard");
  withdrawForm.querySelector("button[type='submit']").textContent = t("sendRequest");
  adminFormSubmit.textContent = t("save");
  document.querySelectorAll("[data-i18n]").forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
}

function telegramStoredParams() {
  const webViewParams = window.Telegram?.WebView?.initParams;
  if (webViewParams && typeof webViewParams === "object") return webViewParams;

  try {
    const utilsParams = window.Telegram?.Utils?.sessionStorageGet?.("initParams");
    if (utilsParams && typeof utilsParams === "object") return utilsParams;
  } catch (err) {
    // Ignore unavailable Telegram storage helpers.
  }

  try {
    const raw = window.sessionStorage?.getItem("__telegram__initParams");
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && typeof parsed === "object") return parsed;
  } catch (err) {
    // Ignore private-mode or malformed storage.
  }

  return {};
}

function telegramLaunchParam(name) {
  const storedValue = telegramStoredParams()[name];
  if (storedValue) return storedValue;

  const searchValue = new URLSearchParams(location.search).get(name);
  if (searchValue) return searchValue;

  const hash = location.hash.startsWith("#") ? location.hash.slice(1) : location.hash;
  if (!hash) return "";
  const hashQuery = hash.includes("?") ? hash.slice(hash.indexOf("?") + 1) : hash;
  return new URLSearchParams(hashQuery).get(name) || "";
}

function initData() {
  return tg?.initData || telegramLaunchParam("tgWebAppData") || "";
}

function hasInitData() {
  return Boolean(initData());
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), "X-Telegram-Init-Data": initData() };
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { ...options, headers, cache: "no-store" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function norm(text) {
  return String(text || "").trim().toLowerCase();
}

function clear() {
  content.replaceChildren();
  statusEl.textContent = "";
  statusEl.classList.remove("error");
}

function setActiveTab(tab) {
  for (const item of [pricesTab, cardsTab, walletTab, withdrawTab, adminTab]) item.classList.remove("active");
  tab.classList.add("active");
  searchInput.value = "";
  state.search = "";
}

function updateAuthTabs() {
  state.hasAuth = hasInitData();
  for (const tab of [cardsTab, walletTab, withdrawTab]) tab.classList.remove("hidden");
}

function renderAuthRequired(title) {
  setActiveTab(pricesTab);
  state.view = "brands";
  clear();
  content.append(heading(title, t("loginNeeded")));
  setNotice(t("reopen"));
  renderBrands();
}

function setError(text) {
  statusEl.textContent = text;
  statusEl.classList.add("error");
}

function setNotice(text) {
  statusEl.textContent = text;
  statusEl.classList.remove("error");
}

async function withSubmitLock(form, label, fn) {
  if (form.dataset.busy === "1") return;
  const submit = form.querySelector('button[type="submit"]');
  const oldText = submit?.textContent || "";
  form.dataset.busy = "1";
  if (submit) {
    submit.disabled = true;
    submit.textContent = label;
  }
  try {
    await fn();
  } finally {
    form.dataset.busy = "0";
    if (submit) {
      submit.disabled = false;
      submit.textContent = oldText;
    }
  }
}

function button(cls, text, fn) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = cls;
  el.textContent = text;
  el.addEventListener("click", fn);
  return el;
}

function fieldLabel(field) {
  const label = document.createElement("label");
  label.textContent = field.label;
  let input;
  if (field.type === "textarea") {
    input = document.createElement("textarea");
    input.rows = field.rows || 4;
  } else {
    input = document.createElement("input");
    input.type = field.type || "text";
  }
  input.name = field.name;
  input.value = field.value || "";
  input.placeholder = field.placeholder || "";
  input.required = Boolean(field.required);
  if (field.inputmode) input.inputMode = field.inputmode;
  label.append(input);
  return label;
}

function openAdminForm({ title, subtitle = "", submitText = "Save", fields = [], onSubmit }) {
  adminForm.reset();
  adminFormTitle.textContent = title;
  adminFormSubtitle.textContent = subtitle;
  adminFormSubtitle.classList.toggle("hidden", !subtitle);
  adminFormSubmit.textContent = submitText;
  adminFormFields.replaceChildren(...fields.map(fieldLabel));
  adminFormHandler = onSubmit;
  adminFormModal.classList.remove("hidden");
}

function closeAdminForm() {
  adminFormModal.classList.add("hidden");
  adminFormHandler = null;
}

function openAdminInfo({ title, subtitle = "", text = "" }) {
  adminForm.reset();
  adminFormTitle.textContent = title;
  adminFormSubtitle.textContent = subtitle;
  adminFormSubtitle.classList.toggle("hidden", !subtitle);
  adminFormSubmit.textContent = t("close");
  const pre = document.createElement("pre");
  pre.className = "info-box";
  pre.textContent = text;
  adminFormFields.replaceChildren(pre);
  adminFormHandler = async () => {};
  adminFormModal.classList.remove("hidden");
}

function heading(title, subtitle = "") {
  const box = document.createElement("div");
  box.className = "section-title";
  const wrap = document.createElement("div");
  const h = document.createElement("h2");
  h.textContent = title;
  wrap.append(h);
  if (subtitle) {
    const p = document.createElement("p");
    p.textContent = subtitle;
    wrap.append(p);
  }
  box.append(wrap);
  if (state.isAdmin && ["brands", "regions", "rules"].includes(state.view)) box.append(button("primary", t("add"), openModal));
  return box;
}

function brandRows() {
  const map = new Map();
  for (const row of state.rules) {
    const brand = String(row.brand || "-").toUpperCase();
    if (!map.has(brand)) map.set(brand, { brand, count: 0, regions: new Set() });
    map.get(brand).count += 1;
    map.get(brand).regions.add(`${row.region || "GLOBAL"}|${row.currency || "USD"}`);
  }
  return Array.from(map.values()).sort((a, b) => a.brand.localeCompare(b.brand));
}

function regionRows(brand) {
  const map = new Map();
  for (const row of state.rules.filter((item) => item.brand === brand)) {
    const region = row.region || "GLOBAL";
    if (!map.has(region)) map.set(region, { key: region, region, currencies: new Set(), count: 0 });
    map.get(region).count += 1;
    map.get(region).currencies.add(row.currency || "USD");
  }
  return Array.from(map.values()).sort((a, b) => a.region.localeCompare(b.region));
}

function filtered(items, fields) {
  const q = norm(state.search);
  if (!q) return items;
  return items.filter((item) => fields.some((field) => norm(item[field]).includes(q)));
}

function brandMeta(brand) {
  const key = String(brand || "").toUpperCase();
  const fallbackMark = key
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("") || key.slice(0, 2) || "CX";
  return BRAND_META[key] || { mark: fallbackMark, tone: "tone-generic", logo: "logo-generic" };
}

function currenciesForRegion(brand, region) {
  return Array.from(
    new Set(
      state.rules
        .filter((row) => row.brand === brand && row.region === region)
        .map((row) => row.currency || "USD"),
    ),
  ).sort();
}

function shouldShowCurrency(brand, region) {
  return currenciesForRegion(brand, region).length > 1;
}

function displayRuleLabel(row) {
  const label = String(row.label || "");
  if (rtl && label.toLowerCase() === "mixed") return "ميكس";
  if (rtl && label.toLowerCase() === "custom amount") return "قيمة حرة";
  return label;
}

function ruleSortKey(row) {
  const kind = String(row.price_kind || row.lona_kind || "").toLowerCase();
  if (row.requires_custom_value || ["mixed", "amount"].includes(kind)) return 0;
  return 1;
}

function renderBrands() {
  state.view = "brands";
  state.brand = "";
  state.regionKey = "";
  clear();
  content.append(heading(t("brandsTitle"), t("brandsHint")));
  const grid = document.createElement("div");
  grid.className = "brand-grid";
  for (const row of filtered(brandRows(), ["brand"])) {
    const meta = brandMeta(row.brand);
    const tile = button(`brand-card ${meta.tone}`, "", () => renderRegions(row.brand));
    tile.innerHTML = `
      <div class="brand-poster">
        <span class="brand-logo ${meta.logo}" aria-hidden="true"><span>${meta.mark}</span></span>
        <strong>${row.brand}</strong>
      </div>
    `;
    grid.append(tile);
  }
  if (!grid.children.length) statusEl.textContent = t("noBrands");
  content.append(grid);
}

function renderRegions(brand) {
  state.view = "regions";
  state.brand = brand;
  state.regionKey = "";
  clear();
  content.append(button("ghost", t("back"), renderBrands));
  content.append(heading(brand, t("regionsHint")));
  const grid = document.createElement("div");
  grid.className = "region-grid";
  for (const row of filtered(regionRows(brand), ["region"])) {
    const tile = button("region-card", "", () => renderRules(brand, row.key));
    tile.innerHTML = `<strong>${row.region}</strong><small>${row.count} ${t("categories")}</small>`;
    grid.append(tile);
  }
  if (!grid.children.length) statusEl.textContent = t("noRegions");
  content.append(grid);
}

function renderRules(brand, regionKey) {
  state.view = "rules";
  state.brand = brand;
  state.regionKey = regionKey;
  const region = String(regionKey);
  clear();
  content.append(button("ghost", t("back"), () => renderRegions(brand)));
  const currencies = currenciesForRegion(brand, region);
  const currencyText = currencies.length > 1 ? `${currencies.join(" / ")} - ` : "";
  content.append(heading(`${brand} - ${region}`, `${currencyText}${t("priceCategories")}`));
  const list = document.createElement("div");
  list.className = "list rules-list";
  const rows = state.rules
    .filter((row) => row.brand === brand && row.region === region)
    .filter((row) => !state.search || norm(`${row.label} ${row.note} ${row.customer_rate}`).includes(norm(state.search)))
    .sort((a, b) => ruleSortKey(a) - ruleSortKey(b) || Number(a.range_min || a.denominations?.[0] || a.label || 0) - Number(b.range_min || b.denominations?.[0] || b.label || 0));
  for (const row of rows) {
    const item = document.createElement("article");
    item.className = "rule";
    const currencyBadge = shouldShowCurrency(brand, region) ? `<span class="currency-badge">${row.currency}</span>` : "";
    item.innerHTML = `
      <div class="rule-top"><span class="value">${displayRuleLabel(row)} ${currencyBadge}</span><span class="rate">${row.customer_rate}%</span></div>
      ${state.isAdmin ? `<div class="muted">${t("trader")} ${row.trader_rate || row.customer_rate}%</div>` : ""}
      ${row.note ? `<div class="note">${row.note}</div>` : ""}
    `;
    if (state.isAdmin) {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("primary", t("sell"), () => openSellModal(row)));
      if (!row.readonly) actions.append(button("ghost danger", t("delete"), () => deleteRule(row.id)));
      item.append(actions);
    } else {
      const actions = document.createElement("div");
      actions.className = "actions";
      actions.append(button("primary", t("sell"), () => openSellModal(row)));
      item.append(actions);
    }
    list.append(item);
  }
  if (!list.children.length) statusEl.textContent = t("noCategories");
  content.append(list);
}

async function loadPrices() {
  updateAuthTabs();
  setActiveTab(pricesTab);
  statusEl.textContent = t("loadingPrices");
  try {
    const data = await api("/mini/cardex/api/prices");
    state.rules = Array.isArray(data.rules) ? data.rules : [];
    state.isAdmin = Boolean(data.is_admin);
    adminTab.classList.toggle("hidden", !state.isAdmin);
    renderBrands();
  } catch (err) {
    clear();
    setError(t("loadPricesFailed"));
  }
}

function money(value) {
  const amount = Number(value || 0);
  return `$${amount.toFixed(2)}`;
}

function statusLabel(value) {
  return String(value || "-").replaceAll("_", " ");
}

async function renderMyCards() {
  if (!hasInitData()) return renderAuthRequired(t("myCards"));
  setActiveTab(cardsTab);
  state.view = "mycards";
  clear();
  content.append(heading(t("myCards"), t("cardsHint")));
  statusEl.textContent = t("loadingCards");
  try {
    const data = await api("/mini/cardex/api/cards");
    clear();
    content.append(heading(t("myCards"), t("cardsHint")));
    const list = document.createElement("div");
    list.className = "list";
    for (const row of data.cards || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${money(row.customer_value_usd)}</span></div>
        <div class="muted">${row.region} - ${statusLabel(row.status)} - ${row.customer_rate}%</div>
        ${row.review_notes ? `<div class="note">${row.review_notes}</div>` : ""}
      `;
      list.append(item);
    }
    if (!list.children.length) statusEl.textContent = t("noCards");
    content.append(list);
  } catch (err) {
    clear();
    setError(t("loadCardsFailed"));
  }
}

async function renderWallet() {
  if (!hasInitData()) return renderAuthRequired(t("wallet"));
  setActiveTab(walletTab);
  state.view = "wallet";
  clear();
  content.append(heading(t("wallet"), t("walletHint")));
  statusEl.textContent = t("loadingWallet");
  try {
    const data = await api("/mini/cardex/api/wallet");
    clear();
    content.append(heading(t("wallet"), t("walletHint")));
    const wallet = data.wallet || {};
    const grid = document.createElement("div");
    grid.className = "wallet-grid";
    for (const row of [
      [t("available"), wallet.available_usd],
      [t("pending"), wallet.pending_usd],
      [t("locked"), wallet.locked_usd],
    ]) {
      const tile = document.createElement("article");
      tile.className = "wallet-card";
      tile.innerHTML = `<span>${row[0]}</span><strong>${money(row[1])}</strong>`;
      grid.append(tile);
    }
    content.append(grid);
    const actions = document.createElement("div");
    actions.className = "wallet-actions";
    actions.append(button("primary", t("requestWithdrawal"), openWithdrawModal));
    actions.append(button("ghost", t("withdrawalHistory"), renderWithdrawals));
    content.append(actions);
  } catch (err) {
    clear();
    setError(t("loadWalletFailed"));
  }
}

async function renderWithdrawals() {
  if (!hasInitData()) return renderAuthRequired(t("withdrawals"));
  setActiveTab(withdrawTab);
  state.view = "withdrawals";
  clear();
  const title = heading(t("withdrawals"), t("withdrawalsHint"));
  title.append(button("primary", t("request"), openWithdrawModal));
  content.append(title);
  statusEl.textContent = t("loadingWithdrawals");
  try {
    const data = await api("/mini/cardex/api/withdrawals");
    clear();
    const refreshedTitle = heading(t("withdrawals"), t("withdrawalsHint"));
    refreshedTitle.append(button("primary", t("request"), openWithdrawModal));
    content.append(refreshedTitle);
    const list = document.createElement("div");
    list.className = "list";
    for (const row of data.withdrawals || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${money(row.amount_usd)}</span><span class="rate">${statusLabel(row.status)}</span></div>
        <div class="muted">${row.payout_currency} ${t("payout")} - ${row.id}</div>
        ${row.notes ? `<div class="note">${row.notes}</div>` : ""}
      `;
      list.append(item);
    }
    if (!list.children.length) statusEl.textContent = t("noWithdrawals");
    content.append(list);
  } catch (err) {
    clear();
    setError(t("loadWithdrawalsFailed"));
  }
}

function adminCardActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(button("primary", t("accept"), () => updateAdminCard(row.id, "accept")));
  actions.append(button("ghost danger", t("reject"), () => updateAdminCard(row.id, "reject")));
  return actions;
}

function adminWithdrawalActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  if (row.status !== "approved") actions.append(button("primary", t("approve"), () => updateAdminWithdrawal(row.id, "approve")));
  actions.append(button("ghost", t("paid"), () => updateAdminWithdrawal(row.id, "paid")));
  actions.append(button("ghost danger", t("reject"), () => updateAdminWithdrawal(row.id, "reject")));
  return actions;
}

function adminMissingPricingActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(button("primary", t("setPrice"), () => setMissingPricing(row)));
  return actions;
}

function adminTraderActions(row) {
  const actions = document.createElement("div");
  actions.className = "actions";
  actions.append(button("primary", t("statement"), () => showTraderStatement(row)));
  actions.append(button("ghost", t("batchCards"), () => createTraderBatch(row)));
  actions.append(button("ghost", t("payment"), () => recordTraderPayment(row)));
  return actions;
}

function miniList(items) {
  return Object.entries(items || {}).map(([key, value]) => `${key}: ${value}`).join(" - ") || t("none");
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  document.execCommand("copy");
  area.remove();
}

async function renderAdmin() {
  if (!state.isAdmin) return loadPrices();
  setActiveTab(adminTab);
  state.view = "admin";
  clear();
  content.append(heading(t("adminQueue"), t("adminQueueHint")));
  statusEl.textContent = t("loadingAdmin");
  try {
    const data = await api("/mini/cardex/api/admin/queue");
    clear();
    content.append(heading(t("adminQueue"), t("adminQueueHint")));

    const report = data.today_report || {};
    const reportTitle = document.createElement("div");
    reportTitle.className = "section-title";
    reportTitle.innerHTML = `<h2>${t("todayReport")}</h2>`;
    content.append(reportTitle);
    const reportBox = document.createElement("article");
    reportBox.className = "rule";
    reportBox.innerHTML = `
      <div class="rule-top"><span class="value">${report.date || ""}</span><span class="rate">${report.cards_total || 0} cards</span></div>
      <div class="muted">Pending ${report.pending_reviews || 0} - Missing ${report.missing_pricing || 0} - Withdrawals ${report.open_withdrawals || 0}</div>
      <div class="note">Customer value ${money(report.customer_value_usd)} - Trader value ${money(report.trader_value_usd)}</div>
      <div class="note">Status: ${miniList(report.by_status)}</div>
      <div class="note">Brands: ${miniList(report.by_brand)}</div>
    `;
    content.append(reportBox);

    const exportTitle = document.createElement("div");
    exportTitle.className = "section-title";
    exportTitle.innerHTML = `<h2>${t("todayExports")}</h2>`;
    content.append(exportTitle);
    const exportsList = document.createElement("div");
    exportsList.className = "list";
    for (const row of data.today_exports || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand}</span><span class="rate">${row.count} cards</span></div>
        <div class="muted">${row.filename}</div>
      `;
      item.append(button("primary", t("copy"), async () => {
        try {
          await copyText(row.content || "");
          statusEl.textContent = t("copied");
        } catch (err) {
          openAdminInfo({ title: row.filename, text: row.content || t("noExportContent") });
        }
      }));
      exportsList.append(item);
    }
    if (!exportsList.children.length) exportsList.append(emptyLine(t("noCardsExport")));
    content.append(exportsList);

    const cardTitle = document.createElement("div");
    cardTitle.className = "section-title";
    cardTitle.innerHTML = `<h2>${t("cards")}</h2>`;
    content.append(cardTitle);
    const cards = document.createElement("div");
    cards.className = "list";
    for (const row of data.cards || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${money(row.customer_value_usd)}</span></div>
        <div class="muted">${row.region} - ${statusLabel(row.status)} - ${t("seller")} ${row.seller_user_id}</div>
        <div class="note">${t("code")}: ${row.code}${row.pin ? ` | PIN: ${row.pin}` : ""}</div>
      `;
      item.append(adminCardActions(row));
      cards.append(item);
    }
    if (!cards.children.length) cards.append(emptyLine(t("noCardsReview")));
    content.append(cards);

    const withdrawalTitle = document.createElement("div");
    withdrawalTitle.className = "section-title";
    withdrawalTitle.innerHTML = `<h2>${t("withdrawals")}</h2>`;
    content.append(withdrawalTitle);
    const withdrawals = document.createElement("div");
    withdrawals.className = "list";
    for (const row of data.withdrawals || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${money(row.amount_usd)}</span><span class="rate">${statusLabel(row.status)}</span></div>
        <div class="muted">${row.payout_currency} ${t("payout")} - ${row.id}</div>
        ${row.notes ? `<div class="note">${row.notes}</div>` : ""}
      `;
      item.append(adminWithdrawalActions(row));
      withdrawals.append(item);
    }
    if (!withdrawals.children.length) withdrawals.append(emptyLine(t("noWithdrawals")));
    content.append(withdrawals);

    const missingTitle = document.createElement("div");
    missingTitle.className = "section-title";
    missingTitle.innerHTML = `<h2>${t("missingPricing")}</h2>`;
    content.append(missingTitle);
    const missing = document.createElement("div");
    missing.className = "list";
    for (const row of data.missing_pricing || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${row.region}</span></div>
        <div class="muted">${t("requested")} ${row.seen_count} ${t("times")} - ${t("user")} ${row.created_by_user_id}</div>
      `;
      item.append(adminMissingPricingActions(row));
      missing.append(item);
    }
    if (!missing.children.length) missing.append(emptyLine(t("noMissingPricingRows")));
    content.append(missing);

    const batchableTitle = document.createElement("div");
    batchableTitle.className = "section-title";
    batchableTitle.innerHTML = `<h2>${t("batchableCards")}</h2>`;
    content.append(batchableTitle);
    const batchable = document.createElement("div");
    batchable.className = "list";
    for (const row of data.batchable_cards || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.brand} ${row.denomination} ${row.currency}</span><span class="rate">${money(row.trader_value_usd)}</span></div>
        <div class="muted">${row.region} - ${statusLabel(row.status)} - ${row.id}</div>
        <div class="note">${t("code")}: ${row.code}${row.pin ? ` | PIN: ${row.pin}` : ""}</div>
      `;
      batchable.append(item);
    }
    if (!batchable.children.length) batchable.append(emptyLine(t("noBatchableCards")));
    content.append(batchable);

    const traderTitle = document.createElement("div");
    traderTitle.className = "section-title";
    traderTitle.innerHTML = `<h2>${t("traders")}</h2>`;
    traderTitle.append(button("primary", t("addTrader"), createTrader));
    content.append(traderTitle);
    const traders = document.createElement("div");
    traders.className = "list";
    for (const row of data.traders || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${row.name}</span><span class="rate">${statusLabel(row.status)}</span></div>
        <div class="muted">${row.default_currency} - ${row.id}</div>
        ${row.notes ? `<div class="note">${row.notes}</div>` : ""}
      `;
      item.append(adminTraderActions(row));
      traders.append(item);
    }
    if (!traders.children.length) traders.append(emptyLine(t("noTraders")));
    content.append(traders);

    const auditTitle = document.createElement("div");
    auditTitle.className = "section-title";
    auditTitle.innerHTML = `<h2>${t("auditLogs")}</h2>`;
    content.append(auditTitle);
    const audit = document.createElement("div");
    audit.className = "list";
    for (const row of data.audit_logs || []) {
      const item = document.createElement("article");
      item.className = "rule";
      item.innerHTML = `
        <div class="rule-top"><span class="value">${statusLabel(row.action)}</span><span class="rate">${row.actor_user_id}</span></div>
        <div class="muted">${row.entity_type}:${row.entity_id}</div>
      `;
      audit.append(item);
    }
    if (!audit.children.length) audit.append(emptyLine(t("noAuditLogs")));
    content.append(audit);
  } catch (err) {
    clear();
    setError(t("loadAdminFailed"));
  }
}

function emptyLine(text) {
  const item = document.createElement("article");
  item.className = "rule";
  item.textContent = text;
  return item;
}

function openModal() {
  priceForm.reset();
  if (state.brand) priceForm.elements.brand.value = state.brand;
  if (state.regionKey) {
    const currencies = currenciesForRegion(state.brand, state.regionKey);
    priceForm.elements.region.value = state.regionKey || "";
    priceForm.elements.currency.value = currencies[0] || "USD";
  }
  modal.classList.remove("hidden");
}

function closePriceModal() {
  modal.classList.add("hidden");
}

function firstRuleValue(row) {
  if (row.requires_custom_value) return "";
  if (row.range_min) return row.range_min;
  if (Array.isArray(row.denominations) && row.denominations.length) return row.denominations[0];
  const match = String(row.label || "").match(/\d+(?:\.\d+)?/);
  return match ? match[0] : "";
}

async function refreshQuote() {
  const body = Object.fromEntries(new FormData(sellForm).entries());
  if (!body.brand || !body.denomination) return;
  try {
    const data = await api("/mini/cardex/api/quote", { method: "POST", body: JSON.stringify(body) });
    const quote = data.quote || {};
    if (!quote.configured) {
      quoteBox.textContent = t("noPrice");
      quoteBox.classList.remove("hidden");
      return;
    }
    const amount = Number(quote.customer_value_usd || 0).toFixed(2);
    quoteBox.textContent = `${t("expectedPayout")}: $${amount} (${quote.customer_buy_rate_percent}%)`;
    quoteBox.classList.remove("hidden");
  } catch (err) {
    quoteBox.textContent = t("quoteFailed");
    quoteBox.classList.remove("hidden");
  }
}

function openSellModal(row) {
  sellForm.reset();
  sellForm.elements.brand.value = row.brand || state.brand || "";
  sellForm.elements.region.value = row.region || "";
  sellForm.elements.currency.value = row.currency || "USD";
  const denominationInput = sellForm.elements.denomination;
  denominationInput.value = firstRuleValue(row);
  denominationInput.placeholder = row.requires_custom_value ? "87" : "25";
  sellSummary.textContent = `${row.brand} - ${row.region} - ${row.label} ${row.currency}`;
  quoteBox.classList.add("hidden");
  sellModal.classList.remove("hidden");
  refreshQuote();
}

function closeCardSellModal() {
  sellModal.classList.add("hidden");
}

function openWithdrawModal() {
  withdrawForm.reset();
  withdrawModal.classList.remove("hidden");
}

function closeWithdrawalModal() {
  withdrawModal.classList.add("hidden");
}

async function deleteRule(id) {
  if (!confirm(t("confirmDelete"))) return;
  await api(`/mini/cardex/api/prices/${encodeURIComponent(id)}`, { method: "DELETE" });
  await loadPrices();
  if (state.brand && state.regionKey) renderRules(state.brand, state.regionKey);
}

async function updateAdminCard(id, action) {
  openAdminForm({
    title: `${statusLabel(action)} card`,
    subtitle: id,
    submitText: statusLabel(action),
    fields: [{ name: "notes", label: t("notes"), type: "textarea", placeholder: t("optional") }],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/cards/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ action, notes: body.notes || "" }) });
      await renderAdmin();
    },
  });
}

async function updateAdminWithdrawal(id, action) {
  openAdminForm({
    title: `${statusLabel(action)} withdrawal`,
    subtitle: id,
    submitText: statusLabel(action),
    fields: [{ name: "notes", label: t("notes"), type: "textarea", placeholder: t("optional") }],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/withdrawals/${encodeURIComponent(id)}`, { method: "POST", body: JSON.stringify({ action, notes: body.notes || "" }) });
      await renderAdmin();
    },
  });
}

async function setMissingPricing(row) {
  openAdminForm({
    title: t("setMissingPrice"),
    subtitle: `${row.brand} ${row.denomination} ${row.currency} - ${row.region}`,
    submitText: t("savePrice"),
    fields: [
      { name: "customer_rate", label: t("customerRate"), required: true, inputmode: "decimal", placeholder: "80" },
      { name: "trader_rate", label: t("traderRate"), inputmode: "decimal", placeholder: "78" },
      { name: "note", label: t("publicNote"), placeholder: t("optional") },
    ],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/missing-pricing/${encodeURIComponent(row.id)}`, {
        method: "POST",
        body: JSON.stringify({ ...body, trader_rate: body.trader_rate || body.customer_rate }),
      });
      await loadPrices();
      await renderAdmin();
    },
  });
}

async function createTrader() {
  openAdminForm({
    title: t("addTrader"),
    submitText: t("createTrader"),
    fields: [
      { name: "name", label: t("traderName"), required: true, placeholder: t("traderName") },
      { name: "notes", label: t("notes"), type: "textarea", placeholder: t("optional") },
    ],
    onSubmit: async (body) => {
      await api("/mini/cardex/api/admin/traders", { method: "POST", body: JSON.stringify(body) });
      await renderAdmin();
    },
  });
}

async function recordTraderPayment(row) {
  openAdminForm({
    title: t("recordTraderPayment"),
    subtitle: row.name,
    submitText: t("recordPayment"),
    fields: [
      { name: "amount_usd", label: t("amount"), required: true, inputmode: "decimal", placeholder: "100" },
      { name: "method", label: t("method"), placeholder: t("methodPlaceholder") },
      { name: "reference_no", label: t("reference"), placeholder: t("optional") },
      { name: "notes", label: t("notes"), type: "textarea", placeholder: t("optional") },
    ],
    onSubmit: async (body) => {
      await api(`/mini/cardex/api/admin/traders/${encodeURIComponent(row.id)}/payments`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      window.setTimeout(() => showTraderStatement(row), 0);
    },
  });
}

async function createTraderBatch(row) {
  openAdminForm({
    title: t("batchCards"),
    subtitle: row.name,
    submitText: t("createBatch"),
    fields: [
      { name: "card_ids", label: t("cardIds"), type: "textarea", required: true, placeholder: t("cardIdsPlaceholder") },
      { name: "notes", label: t("batchNotes"), type: "textarea", placeholder: t("optional") },
    ],
    onSubmit: async (body) => {
      const data = await api(`/mini/cardex/api/admin/traders/${encodeURIComponent(row.id)}/batches`, {
        method: "POST",
        body: JSON.stringify({ ...body, mark_sent: true }),
      });
      const batch = data.batch || {};
      await renderAdmin();
      window.setTimeout(() => {
        openAdminInfo({
          title: t("batchCreated"),
          subtitle: row.name,
          text: `${t("referenceLabel")}: ${batch.id}\n${t("cards")}: ${batch.total_count}\n${t("expected")}: ${money(batch.total_expected_from_trader_usd)}\n${t("profit")}: ${money(batch.gross_profit_usd)}`,
        });
      }, 0);
    },
  });
}

async function showTraderStatement(row) {
  try {
    const data = await api(`/mini/cardex/api/admin/traders/${encodeURIComponent(row.id)}/statement`);
    const lines = (data.statement || []).map((item) => {
      return `${statusLabel(item.entry_type)} | debit ${money(item.debit_usd)} | credit ${money(item.credit_usd)} | balance ${money(item.running_balance_usd)}`;
    });
    openAdminInfo({ title: t("traderStatement"), subtitle: row.name, text: lines.length ? lines.join("\n") : t("noStatement") });
  } catch (err) {
    openAdminInfo({ title: t("traderStatement"), subtitle: row.name, text: t("loadStatementFailed") });
  }
}

priceForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withSubmitLock(priceForm, t("saving"), async () => {
    const form = new FormData(priceForm);
    const body = Object.fromEntries(form.entries());
    try {
      await api("/mini/cardex/api/prices", { method: "POST", body: JSON.stringify(body) });
      closePriceModal();
      await loadPrices();
    } catch (err) {
      setError(t("saveCategoryFailed"));
    }
  });
});

sellForm.elements.denomination.addEventListener("input", () => {
  window.clearTimeout(sellForm._quoteTimer);
  sellForm._quoteTimer = window.setTimeout(refreshQuote, 250);
});

sellForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withSubmitLock(sellForm, t("submitting"), async () => {
    const body = Object.fromEntries(new FormData(sellForm).entries());
    try {
      const data = await api("/mini/cardex/api/submit", { method: "POST", body: JSON.stringify(body) });
      if (data.missing_pricing) {
        closeCardSellModal();
        setNotice(t("missingPriceNotice"));
        return;
      }
      const amount = Number(data.quote?.customer_value_usd || 0).toFixed(2);
      closeCardSellModal();
      setNotice(`${t("submitted")}: $${amount}`);
    } catch (err) {
      setError(t("submitFailed"));
    }
  });
});

withdrawForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  await withSubmitLock(withdrawForm, t("sending"), async () => {
    const body = Object.fromEntries(new FormData(withdrawForm).entries());
    try {
      const data = await api("/mini/cardex/api/withdrawals", { method: "POST", body: JSON.stringify(body) });
      closeWithdrawalModal();
      await renderWithdrawals();
      setNotice(`${t("withdrawalCreated")}: ${data.withdrawal?.id || ""}`);
    } catch (err) {
      setError(t("withdrawalFailed"));
    }
  });
});

closeModal.addEventListener("click", closePriceModal);
modal.addEventListener("click", (event) => {
  if (event.target?.dataset?.close) closePriceModal();
});
closeSellModal.addEventListener("click", closeCardSellModal);
sellModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeSell) closeCardSellModal();
});
closeWithdrawModal.addEventListener("click", closeWithdrawalModal);
withdrawModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeWithdraw) closeWithdrawalModal();
});
closeAdminFormModal.addEventListener("click", closeAdminForm);
adminFormModal.addEventListener("click", (event) => {
  if (event.target?.dataset?.closeAdminForm) closeAdminForm();
});
adminForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!adminFormHandler) return;
  await withSubmitLock(adminForm, "Saving...", async () => {
    const body = Object.fromEntries(new FormData(adminForm).entries());
    try {
      await adminFormHandler(body);
      closeAdminForm();
    } catch (err) {
      setError(t("adminActionFailed"));
    }
  });
});
refreshBtn.addEventListener("click", () => {
  if (state.view === "mycards") renderMyCards();
  else if (state.view === "wallet") renderWallet();
  else if (state.view === "withdrawals") renderWithdrawals();
  else if (state.view === "admin") renderAdmin();
  else loadPrices();
});
pricesTab.addEventListener("click", loadPrices);
cardsTab.addEventListener("click", renderMyCards);
walletTab.addEventListener("click", renderWallet);
withdrawTab.addEventListener("click", renderWithdrawals);
adminTab.addEventListener("click", renderAdmin);
searchInput.addEventListener("input", () => {
  state.search = searchInput.value || "";
  if (state.view === "brands") renderBrands();
  else if (state.view === "regions") renderRegions(state.brand);
  else if (state.view === "rules") renderRules(state.brand, state.regionKey);
});

localizeStaticUi();
loadPrices();
