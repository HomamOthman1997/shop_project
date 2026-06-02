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
  clientActions: {},
  offers: [],
  rentalDurationFilter: "",
  fallbackOffer: null,
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
  numberModeFilter: "temp",
  pendingSupportReport: null,
  accountActivityExpanded: false,
  accountActivityAll: null,
};

const $ = (id) => document.getElementById(id);
const els = {
  boot: $("bootScreen"),
  balance: $("balanceLabel"),
  balanceButton: $("balanceButton"),
  balanceText: $("balanceText"),
  rechargeButton: $("rechargeButton"),
  themeToggle: $("themeToggle"),
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
  resultModal: $("resultModal"),
  resultTitle: $("resultTitle"),
  resultMessage: $("resultMessage"),
  resultClose: $("resultClose"),
  busyOverlay: $("busyOverlay"),
  busyTitle: $("busyTitle"),
};

const i18n = {
  ar: {
    temp: "مؤقت",
    rental: "إيجار",
    voice: "اتصال",
    buy: "شراء",
    orders: "أرقامي",
    recharge: "شحن",
    account: "حسابي",
    support: "الدعم",
    tabBuy: "شراء",
    tabOrders: "أرقامي",
    tabRecharge: "شحن",
    tabAccount: "حسابي",
    tabSupport: "الدعم",
    balance: "الرصيد",
    newNumber: "شراء رقم جديد",
    chooseService: "اختر الخدمة",
    checkPrices: "فحص الأسعار",
    liveIntro: "أسعار محدثة",
    bestOffersTop: "أفضل",
    bestOffersBottom: "العروض",
    offers: "عروض",
    checking: "جاري الفحص",
    menu: "القائمة",
    close: "إغلاق",
    choose: "اختيار",
    search: "بحث",
    confirmPurchase: "تأكيد الشراء",
    confirm: "تأكيد",
    done: "تم",
    testActiveResult: "نتيجة الفحص",
    unavailable: "غير متاح",
    anyState: "أي ولاية",
    anyCountry: "أي دولة",
    noCountry: "اختر الدولة",
    noSpecificCountry: "بدون تحديد دولة",
    unitedStates: "الولايات المتحدة",
    unitedKingdom: "المملكة المتحدة",
    selectCountryFirst: "اختر الدولة أولا",
    selectServiceFirst: "اختر خدمة أولا",
    selectCountryThenCheck: "اختر الدولة ثم افحص الأسعار",
    selectServiceAndCountry: "اختر خدمة ثم دولة لعرض الأسعار",
    noOffers: "لا توجد عروض متاحة لهذه الخيارات",
    providersChecking: "جاري فحص المزودين",
    updatedPrices: "أسعار محدثة",
    noOffersAvailable: "لا توجد عروض متاحة",
    fallbackPrices: "لم تتوفر أرقام للخدمة المحددة · هذه أسعار Service Not Listed كبديل",
    chooseServiceAction: "اختيار الخدمة",
    serviceNotListed: "Service Not Listed",
    serviceNotListedSub: "خدمة احتياطية لها سعر عند مزودين محددين",
    serviceNotListedQuerySub: "اخترها إذا لم تجد أرقاما للخدمة المطلوبة",
    rentalUnlimited: "Unlimited service",
    rentalUnlimitedSub: "Rental only - supported providers",
    success: "نجاح",
    suggested: "مقترح",
    hours: "ساعات",
    days: "أيام",
    otherDurations: "مدد أخرى",
    provider: "المزود",
    country: "الدولة",
    price: "السعر",
    duration: "المدة",
    status: "الحالة",
    number: "الرقم",
    unknownSuccess: "غير محدد",
    copied: "تم النسخ",
    orderCreated: "تم إنشاء الطلب",
    orderUpdated: "تم تحديث الطلب",
    loadOrdersFailed: "تعذر تحميل الأرقام",
    loadAccountFailed: "تعذر تحميل الحساب",
    loadRechargeFailed: "تعذر تحميل الشحن",
    loadSupportFailed: "تعذر تحميل الدعم",
    openTelegramAccount: "افتح التطبيق من Telegram لعرض الحساب",
    openTelegramRecharge: "افتح التطبيق من Telegram لشحن الرصيد",
    availableBalance: "الرصيد المتاح",
    walletActivity: "سجل الرصيد والعمليات",
    walletActivityLimited: "آخر 4 عمليات",
    walletActivityAll: "كل العمليات",
    showAllActivity: "عرض كل السجل",
    hideActivity: "طي السجل",
    changeLanguage: "تبديل اللغة",
    languageChanged: "تم تغيير اللغة",
    userId: "معرف المستخدم",
    downloadActivity: "تنزيل كل السجل",
    noWalletActivity: "لا توجد عمليات مسجلة بعد",
    activeOrders: "الطلبات النشطة",
    myNumbers: "أرقامي",
    tempNumbers: "مؤقت",
    rentalNumbers: "إيجار",
    voiceNumbers: "اتصال",
    rechargeRequests: "طلبات الشحن",
    language: "اللغة",
    paymentMethod: "طريقة الدفع",
    paymentAddress: "عنوان الدفع",
    creditPrice: "سعر الكريدت",
    currency: "العملة",
    validRechargeAmount: "أدخل مبلغ شحن صحيح",
    submitRecharge: "إرسال طلب الشحن",
    rechargeSent: "تم إرسال طلب الشحن",
    paymentProof: "إثبات الدفع",
    paidAmount: "المبلغ المدفوع",
    noRechargeMethods: "لا توجد طرق شحن مفعلة حالياً",
    section: "القسم",
    linkedOrder: "الطلب المرتبط",
    message: "الرسالة",
    supportPlaceholder: "اكتب المشكلة أو رقم الطلب",
    sendSupport: "إرسال",
    noSpecificOrder: "بدون طلب محدد",
    reportIssue: "مشكلة في الرقم",
    testActive: "Test active",
    issuePrompt: "اكتب المشكلة التي ظهرت هنا:\n\n",
    issueStatus: "اكتب توضيح المشكلة ثم أرسل البلاغ",
    openTelegramSupport: "افتح التطبيق من Telegram لإرسال تذكرة دعم",
    clearerIssue: "اكتب وصفاً أوضح للمشكلة",
    ticketSent: "تم إرسال التذكرة",
    sendTicketBusy: "إرسال التذكرة",
    working: "جاري التنفيذ",
    checkingOrder: "جاري التحديث",
    checkCall: "فحص المكالمة",
    copyNumber: "نسخ الرقم",
    copyCode: "نسخ الكود",
    firstCode: "الكود الأول",
    codeIndex: "كود",
    waitingForCodeBox: "بانتظار الكود",
    refundSafetyTitle: "رصيدك محفوظ",
    refundSafetyText: "إذا لم يصل الكود خلال المهلة، يرجع المبلغ تلقائياً.",
    requestTimeout: "العملية تأخرت. جرّب مرة ثانية بعد لحظات.",
    numberActiveNoNewCode: "الرقم ما زال نشط. لا يوجد كود جديد بعد.",
    numberActiveCodeReceived: "الرقم نشط والكود متاح.",
    callStillActive: "الطلب نشط. لا يوجد تسجيل جديد بعد.",
    rentalStillActive: "الإيجار نشط. تم طلب التنشيط.",
    refresh: "تحديث",
    secondCode: "كود ثاني",
    tryAnother: "رقم بديل",
    alternateProvider: "مزود بديل",
    playRecording: "استماع",
    downloadRecording: "تحميل",
    rentalSms: "الرسائل",
    renew: "تجديد",
    wake: "تنشيط",
    notesTags: "ملاحظات",
    finish: "إنهاء",
    active: "نشطة",
    all: "الكل",
    refund: "استرجاع",
    closed: "منتهية",
    noActiveOrders: "لا توجد طلبات نشطة حاليا",
    noRefundOrders: "لا توجد طلبات استرجاع حاليا",
    noClosedOrders: "لا توجد طلبات منتهية حاليا",
    noOrders: "لا توجد طلبات حاليا",
    noTempNumbers: "لا توجد أرقام مؤقتة قابلة للإدارة حالياً",
    noRentalNumbers: "لا توجد أرقام إيجار قابلة للإدارة حالياً",
    noVoiceNumbers: "لا توجد أرقام اتصال قابلة للإدارة حالياً",
    orderNumber: "طلب رقم",
    update: "تحديث",
    waiting: "بانتظار الكود",
    waitingCall: "بانتظار المكالمة",
    code: "الكود جاهز",
    codeReceived: "تم استلام الكود",
    refunded: "تم الاسترجاع",
    refundPending: "استرجاع قيد المعالجة",
    failed: "فشل الطلب",
    expired: "انتهى الطلب",
    waitingForCall: "بانتظار المكالمة",
    waitingForRecording: "بانتظار التسجيل",
    recordingPending: "بانتظار التسجيل",
    recording: "التسجيل",
    finished: "منتهي",
    activeStatus: "نشط",
    waitForSms: "بانتظار وصول الكود.",
    waitForCall: "بانتظار وصول المكالمة.",
    waitForRentalSms: "بانتظار رسائل الإيجار.",
    waitForWebhook: "رصيدك محفوظ. إذا لم يصل الكود ضمن فترة الانتظار سيتم إرجاع المبلغ تلقائياً إلى محفظتك.",
    waitForCallWebhook: "بانتظار وصول المكالمة من المزود.",
    codeReady: "وصل الكود. انسخه وأكمل عملية التحقق.",
    recordingReady: "التسجيل جاهز.",
    autoRefundChecking: "جاري معالجة الاسترجاع تلقائياً.",
    supportReviewQueued: "الحالة تحتاج مراجعة الدعم.",
    refundedToWallet: "تم إرجاع المبلغ للمحفظة.",
    orderClosedNoCode: "أُغلق الطلب بدون كود. يمكنك طلب رقم بديل.",
    webhookWait: "رصيدك محفوظ. إذا لم يصل الكود ضمن فترة الانتظار سيتم إرجاع المبلغ تلقائياً إلى محفظتك.",
    codeReceivedHelp: "وصل الكود. انسخه وأكمل عملية التحقق.",
    refundPendingHelp: "الاسترجاع قيد المعالجة من السيرفر.",
    supportReviewHelp: "الحالة تحتاج مراجعة الدعم.",
    refundedHelp: "تم إرجاع المبلغ للمحفظة.",
    recordingWaitHelp: "تم رصد المكالمة وننتظر التسجيل.",
    callReceivedHelp: "تم استلام المكالمة.",
    appSlow: "التطبيق تأخر بالتحميل. أعد المحاولة بعد لحظات.",
    appLoadFailed: "تعذر تحميل التطبيق",
    serverUnavailable: "الخدمة غير متاحة حالياً. انتظر قليلا ثم أعد المحاولة.",
    invalidServerResponse: "تعذر قراءة رد السيرفر. أعد المحاولة بعد قليل.",
    insufficientBalance: "الرصيد غير كاف. اشحن رصيدك ثم أعد المحاولة.",
    quoteExpired: "انتهت صلاحية السعر. افحص الأسعار مرة أخرى.",
    invalidQuote: "العرض لم يعد متاحاً. افحص الأسعار مرة أخرى.",
    telegramAuthRequired: "افتح الميني أب من داخل Telegram لتنفيذ هذا الإجراء.",
    operationFailed: "تعذر تنفيذ العملية",
  },
  en: {
    temp: "Temporary",
    rental: "Rental",
    voice: "Call",
    buy: "Buy",
    orders: "My numbers",
    recharge: "Recharge",
    account: "Account",
    support: "Support",
    tabBuy: "Buy",
    tabOrders: "My numbers",
    tabRecharge: "Recharge",
    tabAccount: "Account",
    tabSupport: "Support",
    balance: "Balance",
    newNumber: "Buy a new number",
    chooseService: "Choose service",
    checkPrices: "Check prices",
    liveIntro: "Updated prices",
    bestOffersTop: "Best",
    bestOffersBottom: "offers",
    offers: "offers",
    checking: "Checking",
    menu: "Menu",
    close: "Close",
    choose: "Choose",
    search: "Search",
    confirmPurchase: "Confirm purchase",
    confirm: "Confirm",
    done: "OK",
    testActiveResult: "Check result",
    unavailable: "Unavailable",
    anyState: "Any state",
    anyCountry: "Any country",
    noCountry: "Choose country",
    noSpecificCountry: "No country selected",
    unitedStates: "United States",
    unitedKingdom: "United Kingdom",
    selectCountryFirst: "Choose a country first",
    selectServiceFirst: "Choose a service first",
    selectCountryThenCheck: "Choose a country, then check prices",
    selectServiceAndCountry: "Choose a service and country to show prices",
    noOffers: "No offers are available for these options",
    providersChecking: "Checking providers",
    updatedPrices: "Updated prices",
    noOffersAvailable: "No offers available",
    fallbackPrices: "No numbers were available for the selected service · showing Service Not Listed prices instead",
    chooseServiceAction: "Choose service",
    serviceNotListed: "Service Not Listed",
    serviceNotListedSub: "Fallback service priced by selected providers",
    serviceNotListedQuerySub: "Use this if you cannot find numbers for the requested service",
    rentalUnlimited: "Unlimited service",
    rentalUnlimitedSub: "Rental only - supported providers",
    success: "success",
    suggested: "Suggested",
    hours: "Hours",
    days: "Days",
    otherDurations: "Other durations",
    provider: "Provider",
    country: "Country",
    price: "Price",
    duration: "Duration",
    status: "Status",
    number: "Number",
    unknownSuccess: "Not specified",
    copied: "Copied",
    orderCreated: "Order created",
    orderUpdated: "Order updated",
    loadOrdersFailed: "Could not load numbers",
    loadAccountFailed: "Could not load account",
    loadRechargeFailed: "Could not load recharge",
    loadSupportFailed: "Could not load support",
    openTelegramAccount: "Open the app from Telegram to view the account",
    openTelegramRecharge: "Open the app from Telegram to recharge",
    availableBalance: "Available balance",
    walletActivity: "Wallet and activity log",
    walletActivityLimited: "Latest 4 entries",
    walletActivityAll: "All entries",
    showAllActivity: "Show full log",
    hideActivity: "Collapse log",
    changeLanguage: "Switch language",
    languageChanged: "Language changed",
    userId: "User ID",
    downloadActivity: "Download full log",
    noWalletActivity: "No activity recorded yet",
    activeOrders: "Active orders",
    myNumbers: "My numbers",
    tempNumbers: "Temporary",
    rentalNumbers: "Rental",
    voiceNumbers: "Call",
    rechargeRequests: "Recharge requests",
    language: "Language",
    paymentMethod: "Payment method",
    paymentAddress: "Payment address",
    creditPrice: "Credit price",
    currency: "Currency",
    validRechargeAmount: "Enter a valid recharge amount",
    submitRecharge: "Submit recharge request",
    rechargeSent: "Recharge request submitted",
    paymentProof: "Payment proof",
    paidAmount: "Paid amount",
    noRechargeMethods: "No recharge methods are enabled right now",
    section: "Section",
    linkedOrder: "Linked order",
    message: "Message",
    supportPlaceholder: "Write the issue or order number",
    sendSupport: "Send",
    noSpecificOrder: "No specific order",
    reportIssue: "Report issue",
    testActive: "Test active",
    issuePrompt: "Write the issue that appeared here:\n\n",
    issueStatus: "Write a short explanation, then send the report",
    openTelegramSupport: "Open the app from Telegram to send a support ticket",
    clearerIssue: "Write a clearer issue description",
    ticketSent: "Ticket sent",
    sendTicketBusy: "Sending ticket",
    working: "Working",
    checkingOrder: "Refreshing",
    checkCall: "Check call",
    copyNumber: "Copy number",
    copyCode: "Copy code",
    firstCode: "First code",
    codeIndex: "Code",
    waitingForCodeBox: "Waiting for code",
    refundSafetyTitle: "Your balance is protected",
    refundSafetyText: "If no code arrives in time, the amount is refunded automatically.",
    requestTimeout: "The operation took too long. Try again in a moment.",
    numberActiveNoNewCode: "The number is still active. No new code yet.",
    numberActiveCodeReceived: "The number is active and the code is available.",
    callStillActive: "The order is active. No new recording yet.",
    rentalStillActive: "The rental is active. Wake was requested.",
    refresh: "Refresh",
    secondCode: "Second code",
    tryAnother: "Replacement",
    alternateProvider: "Alternate provider",
    playRecording: "Play",
    downloadRecording: "Download",
    rentalSms: "Messages",
    renew: "Renew",
    wake: "Wake",
    notesTags: "Notes",
    finish: "Finish",
    active: "Active",
    all: "All",
    refund: "Refunds",
    closed: "Closed",
    noActiveOrders: "No active orders right now",
    noRefundOrders: "No refund orders right now",
    noClosedOrders: "No closed orders right now",
    noOrders: "No orders right now",
    noTempNumbers: "No manageable temporary numbers right now",
    noRentalNumbers: "No manageable rental numbers right now",
    noVoiceNumbers: "No manageable call numbers right now",
    orderNumber: "Number order",
    update: "Update",
    waiting: "Waiting for code",
    waitingCall: "Waiting for call",
    code: "Code ready",
    codeReceived: "Code received",
    refunded: "Refunded",
    refundPending: "Refund processing",
    failed: "Order failed",
    expired: "Order expired",
    waitingForCall: "Waiting for call",
    waitingForRecording: "Waiting for recording",
    recordingPending: "Waiting for recording",
    recording: "Recording",
    finished: "Finished",
    activeStatus: "Active",
    waitForSms: "Waiting for the code.",
    waitForCall: "Waiting for the call.",
    waitForRentalSms: "Waiting for rental messages.",
    waitForWebhook: "Your balance is protected. If the code does not arrive during the waiting window, the amount is refunded to your wallet automatically.",
    waitForCallWebhook: "Waiting for the call from the provider.",
    codeReady: "The code arrived. Copy it and complete verification.",
    recordingReady: "The recording is ready.",
    autoRefundChecking: "Automatic refund is being processed.",
    supportReviewQueued: "This status needs support review.",
    refundedToWallet: "The amount was returned to your wallet.",
    orderClosedNoCode: "The order closed without a code. You can request a replacement.",
    webhookWait: "Your balance is protected. If the code does not arrive during the waiting window, the amount is refunded to your wallet automatically.",
    codeReceivedHelp: "The code arrived. Copy it and complete verification.",
    refundPendingHelp: "Refund is being processed by the server.",
    supportReviewHelp: "This status needs support review.",
    refundedHelp: "The amount was returned to your wallet.",
    recordingWaitHelp: "The call was detected. Waiting for the recording.",
    callReceivedHelp: "The call was received.",
    appSlow: "The app is taking longer than expected. Try again in a few moments.",
    appLoadFailed: "Could not load the app",
    serverUnavailable: "The service is currently unavailable. Wait a moment and try again.",
    invalidServerResponse: "Could not read the server response. Try again shortly.",
    insufficientBalance: "Insufficient balance. Recharge and try again.",
    quoteExpired: "The price expired. Check prices again.",
    invalidQuote: "This offer is no longer available. Check prices again.",
    telegramAuthRequired: "Open the mini app from Telegram to perform this action.",
    operationFailed: "Could not complete the operation",
  },
};

function t(key) {
  return (i18n[state.lang] && i18n[state.lang][key]) || i18n.en[key] || i18n.ar[key] || key;
}

function setLanguage(lang) {
  state.lang = String(lang || "").toLowerCase().startsWith("ar") ? "ar" : "en";
  document.documentElement.lang = state.lang;
  document.documentElement.dir = state.lang === "ar" ? "rtl" : "ltr";
  document.body.classList.toggle("lang-en", state.lang === "en");
  document.body.classList.toggle("lang-ar", state.lang === "ar");
  applyStaticText();
}

function initialLanguage() {
  const fromQuery = params.get("lang") || params.get("language");
  const fromTelegram = tg?.initDataUnsafe?.user?.language_code;
  return fromQuery || fromTelegram || "ar";
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value;
}

function applyStaticText() {
  setText("#balanceText", t("balance"));
  setText(".panel-title h2", t("newNumber"));
  setText("#serviceLabel", state.service ? serviceLabel(state.service) : t("chooseService"));
  setText("#checkPricesButton", t("checkPrices"));
  setText("#liveLine", t("liveIntro"));
  setText(".offers-section .section-head h2", `${t("bestOffersTop")}\n${t("bestOffersBottom")}`);
  setText("#view-orders .page-head h2", t("orders"));
  setText("#refreshOrdersButton", t("refresh"));
  setText("#view-recharge .page-head h2", t("recharge"));
  setText("#view-account .page-head h2", t("account"));
  setText("#view-support .page-head h2", t("support"));
  setText("#supportForm label:nth-of-type(1) span", t("section"));
  setText("#supportForm label:nth-of-type(2) span", t("linkedOrder"));
  setText("#supportForm label:nth-of-type(3) span", t("message"));
  setText("#supportForm button[type='submit']", t("sendSupport"));
  setText("#rechargeForm label:nth-of-type(1) span", t("paymentMethod"));
  setText("#rechargeForm label:nth-of-type(2) span", t("paidAmount"));
  setText("#rechargeForm label:nth-of-type(3) span", t("paymentProof"));
  setText("#rechargeForm button[type='submit']", t("submitRecharge"));
  setText("#menuDrawer h3", t("menu"));
  setText("#drawerTitle", t("choose"));
  setText("#confirmDrawer h3", t("confirmPurchase"));
  setText("#confirmPurchaseButton", t("confirm"));
  setText("#resultClose", t("done"));
  if (els.menuButton) els.menuButton.setAttribute("aria-label", t("menu"));
  if (els.menuClose) els.menuClose.setAttribute("aria-label", t("close"));
  if (els.drawerClose) els.drawerClose.setAttribute("aria-label", t("close"));
  if (els.confirmClose) els.confirmClose.setAttribute("aria-label", t("close"));
  if (els.resultClose) els.resultClose.setAttribute("aria-label", t("close"));
  if (els.drawerSearch) els.drawerSearch.placeholder = t("search");
  if (els.supportMessage) els.supportMessage.placeholder = t("supportPlaceholder");
  if (!state.hasCheckedPrices && els.offersCount) els.offersCount.textContent = `0 ${t("offers")}`;
  if (els.countryLabel && state.country === "none") els.countryLabel.textContent = state.mode === "voice" ? `${t("unitedStates")} · US` : countryLabel(state.country);
  if (els.stateLabel && state.stateCode === "none") els.stateLabel.textContent = state.country === "1" ? t("anyState") : t("unavailable");
}

const labels = new Proxy({}, {
  get: (_target, key) => t(String(key)),
});

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
const RENTAL_UNLIMITED_SERVICE_KEY = "rental_unlimited";
const TEMP_NOT_LISTED_SERVICE_KEY = "not_listed_generic";
const hiddenServiceNeedles = ["my custom app", "mycustomapp"];

function applyRuntimeTheme() {
  const override = localStorage.getItem("numbers_v2_theme");
  const scheme = String(tg?.colorScheme || "").toLowerCase();
  const bg = String(tg?.themeParams?.bg_color || "").toLowerCase();
  const darkBg = /^#(?:0[0-9a-f]|1[0-9a-f]|2[0-9a-f])/.test(bg);
  const dark = override ? override === "dark" : (scheme === "dark" || darkBg || params.get("theme") === "dark");
  document.body.classList.toggle("telegram-dark", dark);
  if (els.themeToggle) {
    els.themeToggle.textContent = dark ? "☀" : "☾";
    els.themeToggle.setAttribute("aria-label", dark ? "Light theme" : "Dark theme");
  }
}

function toggleTheme(event) {
  event?.stopPropagation?.();
  const dark = !document.body.classList.contains("telegram-dark");
  localStorage.setItem("numbers_v2_theme", dark ? "dark" : "light");
  applyRuntimeTheme();
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
    buy: t("buy"),
    tabBuy: t("tabBuy"),
    orders: t("orders"),
    tabOrders: t("tabOrders"),
    recharge: t("recharge"),
    tabRecharge: t("tabRecharge"),
    account: t("account"),
    tabAccount: t("tabAccount"),
    support: t("support"),
    tabSupport: t("tabSupport"),
    copy_number: t("copyNumber"),
    copyNumber: t("copyNumber"),
    copy_code: t("copyCode"),
    copyCode: t("copyCode"),
    refresh: t("refresh"),
    second_code: t("secondCode"),
    secondCode: t("secondCode"),
    replace: t("tryAnother"),
    tryAnother: t("tryAnother"),
    alternate_provider: t("alternateProvider"),
    alternateProvider: t("alternateProvider"),
    preview_recording: t("playRecording"),
    playRecording: t("playRecording"),
    download_recording: t("downloadRecording"),
    downloadRecording: t("downloadRecording"),
    rental_sms: t("rentalSms"),
    rentalSms: t("rentalSms"),
    rental_renew: t("renew"),
    rental_wake: t("wake"),
    rental_notes: t("notesTags"),
    rental_finish: t("finish"),
    renew: t("renew"),
    wake: t("wake"),
    notesTags: t("notesTags"),
    finish: t("finish"),
    reportIssue: t("reportIssue"),
    testActive: t("testActive"),
    working: t("working"),
    checkingOrder: t("checkingOrder"),
    checkCall: t("checkCall"),
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

function showResultModal(message, title = t("testActiveResult")) {
  if (!message || !els.resultModal) {
    showToast(message, "success");
    return;
  }
  if (els.resultTitle) els.resultTitle.textContent = title;
  if (els.resultMessage) els.resultMessage.textContent = message;
  els.resultModal.classList.remove("hidden");
  els.resultClose?.focus();
}

function closeResultModal() {
  els.resultModal?.classList.add("hidden");
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
  if (error?.name === "AbortError") return t("requestTimeout");
  const payload = error?.payload || {};
  const code = payload.code || payload.error_code || "";
  if (code === "server_unavailable") return t("serverUnavailable");
  if (code === "invalid_server_response") return t("invalidServerResponse");
  if (code === "insufficient_balance") return t("insufficientBalance");
  if (code === "quote_expired") return t("quoteExpired");
  if (code === "invalid_quote") return t("invalidQuote");
  if (code === "telegram_auth_required") return t("telegramAuthRequired");
  return payload.message || payload.error || error?.message || t("operationFailed");
}

function looksLikeHtmlResponse(text) {
  return /^\s*<!doctype html/i.test(String(text || "")) || /^\s*<html[\s>]/i.test(String(text || ""));
}

function responseErrorPayload(response, text, parsedPayload) {
  if (looksLikeHtmlResponse(text) || response.status >= 500) {
    return {
      ok: false,
      code: "server_unavailable",
      message: t("serverUnavailable"),
    };
  }
  return parsedPayload || {
    ok: false,
    code: "invalid_server_response",
    message: t("invalidServerResponse"),
  };
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
  try {
    const response = await fetch(endpoint, {
      method: options.method || "GET",
      headers: requestHeaders,
      body,
      signal: options.signal,
    });
    const text = await response.text();
    let payload = {};
    let parsed = false;
    try {
      payload = text ? JSON.parse(text) : {};
      parsed = true;
    } catch (_error) {
      payload = responseErrorPayload(response, text, null);
    }
    if (!parsed && response.ok) {
      const error = new Error(payload.message || "Invalid server response");
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    if (!response.ok) {
      payload = responseErrorPayload(response, text, payload);
      const error = new Error(payload.message || payload.error || `HTTP ${response.status}`);
      error.payload = payload;
      error.status = response.status;
      throw error;
    }
    return payload;
  } catch (error) {
    throw error;
  }
}

function formatProvider(row, index) {
  const id = row.provider_id || row.public_provider_id || row.provider_code || providerAliases[index]?.[0] || `S${index + 1}`;
  return {
    id,
    name: row.provider_name || row.public_provider_name || aliasById[id] || providerAliases[index]?.[1] || "Provider",
  };
}

function serviceLabel(key) {
  if (key === RENTAL_UNLIMITED_SERVICE_KEY) return t("rentalUnlimited");
  if (key === TEMP_NOT_LISTED_SERVICE_KEY) return t("serviceNotListed");
  return state.services.find((item) => item.key === key)?.label || state.services.find((item) => item.code === key)?.name || key || t("chooseService");
}

function isHiddenService(row) {
  const text = `${row.key || ""} ${row.code || ""} ${row.label || ""} ${row.name || ""}`.toLowerCase();
  return hiddenServiceNeedles.some((needle) => text.includes(needle));
}

function servicePickerRows() {
  const rows = state.services
    .filter((row) => !isHiddenService(row))
    .map((row) => ({
      key: row.key || row.code,
      title: row.label || row.name || row.key || row.code,
      sub: row.category || "",
    }));
  if (state.mode !== "rental") return rows;
  return [
    {
      key: RENTAL_UNLIMITED_SERVICE_KEY,
      title: t("rentalUnlimited"),
      sub: t("rentalUnlimitedSub"),
      special: true,
    },
    ...rows.filter((row) => row.key !== RENTAL_UNLIMITED_SERVICE_KEY),
  ];
}

function notListedServiceRow(query) {
  return {
    key: TEMP_NOT_LISTED_SERVICE_KEY,
    title: t("serviceNotListed"),
    sub: query ? `"${query}" - ${t("serviceNotListedQuerySub")}` : t("serviceNotListedSub"),
    special: true,
  };
}

function resetBuySelections({ mode = state.mode } = {}) {
  state.service = "";
  state.country = mode === "voice" ? "1" : "none";
  state.stateCode = "none";
  clearPriceResults();
}

function rentalAllowsAnyCountry() {
  return state.mode === "rental" && state.service === RENTAL_UNLIMITED_SERVICE_KEY;
}

function pickerAllowsAnyCountry() {
  return state.mode !== "rental" || rentalAllowsAnyCountry();
}

function countryLabel(code) {
  if (String(code) === "1") return `${t("unitedStates")} · US`;
  if (String(code) === "any") return t("anyCountry");
  if (String(code) === "none") return t("noCountry");
  const row = state.countries.find((item) => String(item.code) === String(code));
  return row ? `${row.name} · ${row.iso || row.code}` : t("noCountry");
}

function countryNameFromValue(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  const country = state.countries.find((item) => (
    String(item.code) === raw ||
    String(item.iso || "").toLowerCase() === raw.toLowerCase() ||
    String(item.name || "").toLowerCase() === raw.toLowerCase()
  ));
  if (country?.name) return country.name;
  const code = raw.toUpperCase();
  if (code === "US") return t("unitedStates");
  if (code === "UK" || code === "GB") return t("unitedKingdom");
  if (!code || code === "NONE" || code === "ANY") return "";
  return raw;
}

function selectedCountryName() {
  if (state.mode === "voice") return t("unitedStates");
  if (state.country === "1") return countryNameFromValue("US");
  if (state.country === "none" || state.country === "any") return "";
  return countryNameFromValue(state.country);
}

function offerCountryDisplay(row) {
  return countryNameFromValue(
    row.location_tag ||
    row.country_label ||
    row.country_iso ||
    row.provider_country_iso ||
    row.provider_country ||
    row.country_code ||
    row.country
  ) || selectedCountryName();
}

function stateLabel(code) {
  if (String(code) === "none") return t("anyState");
  const row = state.states.find((item) => String(item.code) === String(code));
  return row?.name || t("anyState");
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
        if (state.mode === mode.key) return;
        state.mode = mode.key;
        resetBuySelections({ mode: state.mode });
        renderBuy();
      });
      return button;
    })
  );
}

function renderBuy() {
  renderModes();
  els.serviceLabel.textContent = serviceLabel(state.service);
  els.countryLabel.textContent = state.mode === "voice" ? `${t("unitedStates")} · US` : countryLabel(state.country);
  els.stateLabel.textContent = state.country === "1" ? stateLabel(state.stateCode) : t("unavailable");
  const showState = state.country === "1";
  els.stateButton.disabled = !showState;
  els.stateButton.classList.toggle("hidden", !showState);
  els.countryButton.parentElement?.classList.toggle("state-hidden", !showState);
  renderOffers();
}

function normalizedOffers() {
  const rows = [];
  const seen = new Set();
  (state.offers || []).forEach((row) => {
    if (Array.isArray(row.options) && row.options.length) {
      row.options.forEach((option) => {
        const payload = {
          ...row,
          ...option,
          provider_id: row.provider_id,
          provider_name: row.provider_name,
          option_label: option.duration_label || option.label,
          purchase_action: option.purchase_action || row.purchase_action,
        };
        const key = [
          payload.provider_id || payload.provider_name || payload.provider,
          rentalDurationKey(payload),
          payload.price_label || payload.price,
          payload.country || payload.location_tag || "",
        ].join("|");
        if (state.mode === "rental" && seen.has(key)) return;
        seen.add(key);
        rows.push(payload);
      });
      return;
    }
    rows.push(row);
  });
  return rows;
}

function rentalDurationHours(row) {
  const label = String(row?.option_label || row?.duration_label || row?.label || "").trim().toLowerCase();
  const match = label.match(/(\d+(?:\.\d+)?)\s*(d|day|days|h|hr|hour|hours)/i);
  if (match) {
    const value = Number(match[1]);
    if (Number.isFinite(value) && value > 0) return match[2].startsWith("d") ? value * 24 : value;
  }
  const direct = Number(row?.duration || row?.hours || 0);
  return Number.isFinite(direct) && direct > 0 ? direct : 0;
}

function rentalDurationLabelFromHours(hours) {
  if (!hours) return "";
  if (hours % 24 === 0) return `${hours / 24}d`;
  return `${hours}h`;
}

function rentalDurationKey(row) {
  const hours = rentalDurationHours(row);
  return hours ? String(hours) : String(row?.option_label || row?.duration_label || row?.label || "").trim();
}

function rentalDurationLabel(row) {
  return String(row?.option_label || row?.duration_label || row?.label || "").trim() || rentalDurationLabelFromHours(rentalDurationHours(row));
}

function rentalDurationChoices(rows) {
  const choices = new Map();
  rows.forEach((row) => {
    const key = rentalDurationKey(row);
    if (!key) return;
    if (!choices.has(key)) {
      const hours = rentalDurationHours(row) || 999999;
      choices.set(key, { key, label: rentalDurationLabel(row), hours, group: rentalDurationGroup(hours) });
    }
  });
  return [...choices.values()].sort((a, b) => a.hours - b.hours || a.label.localeCompare(b.label));
}

function rentalDurationGroup(hours) {
  if (!Number.isFinite(hours) || hours <= 0 || hours >= 999999) return "other";
  return hours < 24 ? "hours" : "days";
}

function rentalDurationGroupLabel(group) {
  if (group === "hours") return t("hours");
  if (group === "days") return t("days");
  return t("otherDurations");
}

function ensureRentalDurationFilter(rows) {
  if (state.mode !== "rental") return "";
  const choices = rentalDurationChoices(rows);
  if (!choices.length) {
    state.rentalDurationFilter = "";
    return "";
  }
  if (!choices.some((choice) => choice.key === state.rentalDurationFilter)) {
    state.rentalDurationFilter = choices[0].key;
  }
  return state.rentalDurationFilter;
}

function rentalDurationSelector(rows) {
  const choices = rentalDurationChoices(rows);
  if (state.mode !== "rental" || choices.length <= 1) return null;
  const wrapper = document.createElement("div");
  wrapper.className = "rental-duration-selector";
  ["hours", "days", "other"].forEach((group) => {
    const groupChoices = choices.filter((choice) => choice.group === group);
    if (!groupChoices.length) return;
    const section = document.createElement("div");
    section.className = "rental-duration-group";
    const label = document.createElement("span");
    label.className = "rental-duration-label";
    label.textContent = rentalDurationGroupLabel(group);
    const bar = document.createElement("div");
    bar.className = "rental-duration-bar";
    groupChoices.forEach((choice) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = choice.key === state.rentalDurationFilter ? "active" : "";
      button.textContent = choice.label;
      button.addEventListener("click", () => {
        state.rentalDurationFilter = choice.key;
        renderOffers();
      });
      bar.append(button);
    });
    section.append(label, bar);
    wrapper.append(section);
  });
  return wrapper;
}

function renderOffers() {
  const allRows = normalizedOffers();
  const rentalFilter = ensureRentalDurationFilter(allRows);
  const rows = state.mode === "rental" && rentalFilter
    ? allRows.filter((row) => rentalDurationKey(row) === rentalFilter)
    : allRows;
  els.offersCount.textContent = state.loading ? t("checking") : `${rows.length} ${t("offers")}`;
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
      ? (state.service ? t("selectCountryThenCheck") : t("selectServiceAndCountry"))
      : t("noOffers");
    const empty = emptyState(emptyMessage);
    if (!state.service) {
      const button = document.createElement("button");
      button.className = "inline-action";
      button.type = "button";
      button.textContent = t("chooseServiceAction");
      button.addEventListener("click", () => openPicker("service"));
      empty.append(button);
    }
    els.offerList.replaceChildren(empty);
    return;
  }
  const durationSelector = rentalDurationSelector(allRows);
  els.offerList.replaceChildren(
    ...(durationSelector ? [durationSelector] : []),
    ...rows.map((row, index) => {
      const provider = formatProvider(row, index);
      const card = document.createElement("article");
      card.className = `offer-card${row.recommended || index === 0 ? " recommended" : ""}`;

      const buy = document.createElement("button");
      buy.className = "offer-buy";
      buy.type = "button";
      buy.textContent = t("buy");
      buy.disabled = row.available === false || row.purchase_action?.enabled === false;
      buy.addEventListener("click", () => openConfirm(row));

      const rate = document.createElement("div");
      rate.className = "offer-rate";
      rate.textContent = `${row.success_rate || row.successRate || "98%"}\n${t("success")}`;

      const price = document.createElement("div");
      price.className = "offer-price";
      price.textContent = row.price_label || row.priceLabel || "$0.00";

      const providerEl = document.createElement("div");
      providerEl.className = "offer-provider";
      const providerName = document.createElement("strong");
      providerName.textContent = provider.name;
      const providerMeta = document.createElement("small");
      const countryTag = offerCountryDisplay(row);
      providerMeta.textContent = [countryTag, row.option_label].filter(Boolean).join(" · ");
      providerEl.append(providerName, providerMeta);

      if (row.fallback_service || row.recommended || index === 0 || row.available === false) {
        const tag = document.createElement("em");
        tag.className = `offer-tag${row.available === false ? " unavailable" : ""}`;
        tag.textContent = row.available === false ? t("unavailable") : (row.fallback_service ? t("serviceNotListed") : t("suggested"));
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
      title: t("chooseService"),
      rows: servicePickerRows(),
      onSelect: (key) => {
        state.service = key;
        if (state.mode === "rental" && key !== RENTAL_UNLIMITED_SERVICE_KEY && state.country === "any") {
          state.country = "none";
          state.stateCode = "none";
        }
        clearPriceResults();
      },
    },
    country: {
      kind: "country",
      title: t("noCountry"),
      rows: countryPickerRows(),
      onSelect: (key) => { state.country = key; if (key !== "1") state.stateCode = "none"; clearPriceResults(); },
    },
    state: {
      kind: "state",
      title: t("anyState"),
      rows: state.states.map((row) => ({ key: row.code, title: row.name, sub: row.code })),
      onSelect: (key) => { state.stateCode = key; clearPriceResults(); },
    },
  };
  state.picker = configs[kind];
  els.drawerTitle.textContent = state.picker.title;
  els.drawerSearch.value = "";
  renderPickerOptions();
  els.pickerDrawer.classList.remove("hidden");
  els.drawerSearch.focus();
}

function renderPickerOptions() {
  const query = els.drawerSearch.value.trim().toLowerCase();
  let rows = (state.picker?.rows || []).filter((row) => `${row.title} ${row.sub}`.toLowerCase().includes(query));
  if (state.picker?.kind === "service" && state.mode === "temp" && query) {
    rows = [
      ...rows.filter((row) => row.key !== TEMP_NOT_LISTED_SERVICE_KEY),
      notListedServiceRow(els.drawerSearch.value.trim()),
    ];
  }
  els.drawerList.replaceChildren(
    ...rows.slice(0, 80).map((row) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `picker-option${row.special ? " suggested" : ""}`;
      button.append(document.createTextNode(row.title || ""));
      if (row.sub) {
        const sub = document.createElement("small");
        sub.textContent = row.sub;
        button.append(sub);
      }
      button.addEventListener("click", () => {
        state.picker.onSelect(row.key);
        closePicker();
        renderBuy();
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
  const anyCountry = { key: "any", title: t("anyCountry"), sub: t("noSpecificCountry") };
  const countries = state.countries
    .filter((row) => !["", "none", "any"].includes(String(row.code || "").trim().toLowerCase()))
    .map((row) => ({ key: row.code, title: countryLabel(row.code), sub: row.price_label || "" }));
  return pickerAllowsAnyCountry() ? [anyCountry, ...countries] : countries;
}

function clearPriceResults() {
  state.offers = [];
  state.rentalDurationFilter = "";
  state.fallbackOffer = null;
  state.hasCheckedPrices = false;
}

async function fetchPricePayload(service) {
  const action = actionFor("prices", "/mini/numbers/api/prices");
  const qs = new URLSearchParams({
    mode: state.mode,
    service,
    country: state.mode === "voice" ? "1" : (state.country === "any" ? "none" : state.country),
    state: state.country === "1" ? state.stateCode : "none",
    _: String(Date.now()),
  });
  return api(`${action.endpoint}?${qs}`);
}

function shouldTryNotListedFallback() {
  return state.mode === "temp" && state.service && state.service !== TEMP_NOT_LISTED_SERVICE_KEY;
}

async function checkPrices() {
  if (!state.service) {
    els.liveLine.textContent = t("selectServiceFirst");
    openPicker("service");
    return;
  }
  if (state.mode !== "voice" && state.country === "none") {
    els.liveLine.textContent = t("selectCountryFirst");
    openPicker("country");
    return;
  }
  setBusy(els.checkPrices, true);
  state.loading = true;
  state.hasCheckedPrices = true;
  state.fallbackOffer = null;
  state.rentalDurationFilter = "";
  els.liveLine.textContent = t("providersChecking");
  state.offers = [];
  renderOffers();
  try {
    const payload = await fetchPricePayload(state.service);
    state.offers = payload.providers || [];
    if (!state.offers.length && shouldTryNotListedFallback()) {
      const fallbackPayload = await fetchPricePayload(TEMP_NOT_LISTED_SERVICE_KEY);
      const fallbackProviders = fallbackPayload.providers || [];
      if (fallbackProviders.length) {
        state.fallbackOffer = {
          requestedService: serviceLabel(state.service),
          service: { ...(fallbackPayload.service || {}), key: TEMP_NOT_LISTED_SERVICE_KEY, label: serviceLabel(TEMP_NOT_LISTED_SERVICE_KEY) },
        };
        state.offers = fallbackProviders.map((row) => ({
          ...row,
          fallback_service: true,
          service_label: state.fallbackOffer.service.label,
        }));
      }
    }
    els.liveLine.textContent = state.offers.length
      ? (state.fallbackOffer ? t("fallbackPrices") : t("updatedPrices"))
      : (payload.message || t("noOffersAvailable"));
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
  const countryTag = offerCountryDisplay(row);
  const serviceTitle = row.fallback_service ? (row.service_label || serviceLabel(TEMP_NOT_LISTED_SERVICE_KEY)) : serviceLabel(state.service);
  els.confirmBody.replaceChildren();
  const card = document.createElement("div");
  card.className = "info-card";
  card.innerHTML = `
    <h3>${serviceTitle}</h3>
    <div class="meta-grid">
      ${row.fallback_service ? `<div><span>${t("serviceNotListed")}</span><strong>${state.fallbackOffer?.requestedService || serviceLabel(state.service)}</strong></div>` : ""}
      <div><span>${t("provider")}</span><strong>${provider.name}</strong></div>
      ${countryTag ? `<div><span>${t("country")}</span><strong>${countryTag}</strong></div>` : ""}
      <div><span>${t("price")}</span><strong>${row.price_label || "$0.00"}</strong></div>
      <div><span>${t("success")}</span><strong>${row.success_rate || t("unknownSuccess")}</strong></div>
      ${row.option_label ? `<div><span>${t("duration")}</span><strong>${row.option_label}</strong></div>` : ""}
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
    showToast(payload.message || t("orderCreated"), "success");
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
  if (customerState.status_label_key) return labelForKey(customerState.status_label_key);
  const status = order.public_status || order.status || "";
  return {
    waiting: t("waiting"),
    code_received: t("codeReceived"),
    refunded: t("refunded"),
    refund_pending: t("refundPending"),
    waiting_for_call: t("waitingForCall"),
    waiting_for_recording: t("waitingForRecording"),
    failed: t("failed"),
    expired: t("expired"),
    finished: t("finished"),
  }[status] || status || t("activeStatus");
}

function customerStateText(order) {
  const customerState = order.customer_state || {};
  const key = customerState.key || order.public_status || "";
  const map = {
    awaiting_provider_webhook: t("webhookWait"),
    code_received: t("codeReceivedHelp"),
    refund_pending: t("refundPendingHelp"),
    support_review_pending: t("supportReviewHelp"),
    refunded: t("refundedHelp"),
    waiting_for_recording: t("recordingWaitHelp"),
    call_received: t("callReceivedHelp"),
  };
  return map[key] || customerState.message || (customerState.message_key ? labelForKey(customerState.message_key) : "");
}

function formatPhoneNumber(value) {
  const raw = String(value || "").trim();
  if (!raw) return "-";
  const digits = raw.replace(/[^\d]/g, "");
  if (!digits) return raw;
  const withoutPrefix = digits.startsWith("00") ? digits.slice(2) : digits;
  let codeLength = 2;
  if (withoutPrefix.startsWith("1") && withoutPrefix.length >= 11) codeLength = 1;
  if (withoutPrefix.length <= codeLength + 3) return raw.startsWith("+") ? raw : `+${withoutPrefix}`;
  return `+${withoutPrefix.slice(0, codeLength)} ${withoutPrefix.slice(codeLength)}`;
}

function orderWaitingForCode(order) {
  const status = String(order?.customer_state?.key || order?.public_status || order?.status || "").toLowerCase();
  return orderMode(order) === "temp" && !order?.code && !orderCodes(order).length && ["waiting", "awaiting_provider_webhook", "refund_pending"].includes(status);
}

function renderRefundSafetyNote() {
  const note = document.createElement("div");
  note.className = "refund-safety-note";
  note.innerHTML = `<strong>${t("refundSafetyTitle")}</strong><span>${t("refundSafetyText")}</span>`;
  return note;
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

function orderMode(order) {
  const mode = String(order?.mode || order?.number_mode || "").toLowerCase();
  return ["temp", "rental", "voice"].includes(mode) ? mode : "temp";
}

function numberModeFilters() {
  return [
    ["temp", t("tempNumbers")],
    ["rental", t("rentalNumbers")],
    ["voice", t("voiceNumbers")],
  ];
}

function renderOrderFilters() {
  const rows = state.orders || [];
  const counts = {
    temp: rows.filter((order) => orderMode(order) === "temp").length,
    rental: rows.filter((order) => orderMode(order) === "rental").length,
    voice: rows.filter((order) => orderMode(order) === "voice").length,
  };
  if (!numberModeFilters().some(([key]) => key === state.numberModeFilter)) {
    state.numberModeFilter = "temp";
  }
  const filters = numberModeFilters();
  els.orderFilters.replaceChildren(...filters.map(([key, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = state.numberModeFilter === key ? "active" : "";
    button.textContent = `${label} ${counts[key]}`;
    button.addEventListener("click", () => {
      state.numberModeFilter = key;
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
  const rows = allRows.filter((order) => orderMode(order) === state.numberModeFilter);
  if (!rows.length) {
    const messages = {
      temp: t("noTempNumbers"),
      rental: t("noRentalNumbers"),
      voice: t("noVoiceNumbers"),
    };
    els.ordersList.replaceChildren(emptyState(messages[state.numberModeFilter] || t("noOrders")));
    return;
  }
  els.ordersList.replaceChildren(
    ...rows.map((order) => {
      const card = document.createElement("article");
      card.className = `order-card order-${orderTone(order)}`;
      const note = customerStateText(order);
      const details = Array.isArray(order.details) ? order.details.slice(0, 4) : [];
      const numberValue = formatPhoneNumber(order.number || order.provider_number || "");
      card.innerHTML = `
        <h3>${order.service_label || order.service || t("orderNumber")}</h3>
        <div class="meta-grid">
          <div><span>${t("status")}</span><strong>${statusLabel(order)}</strong></div>
          <div class="number-detail"><span>${t("number")}</span><strong>${numberValue}</strong></div>
          <div><span>${t("price")}</span><strong>${order.price_label || "-"}</strong></div>
          ${details.map((item) => `<div><span>${item.label || item.key || ""}</span><strong>${item.value || "-"}</strong></div>`).join("")}
        </div>
      `;
      const waitingForCode = orderWaitingForCode(order);
      if (note && !waitingForCode) {
        const stateNote = document.createElement("p");
        stateNote.className = "status-text";
        stateNote.textContent = note;
        card.append(stateNote);
      }
      if (order.code && !(Array.isArray(order.codes) && order.codes.length)) {
        const code = document.createElement("div");
        code.className = "code-box";
        code.textContent = order.code;
        card.append(code);
      } else if (waitingForCode) {
        const waiting = document.createElement("div");
        waiting.className = "code-box code-box-waiting";
        waiting.textContent = t("waitingForCodeBox");
        card.append(waiting);
      }
      const codeValues = orderCodes(order);
      if (codeValues.length) {
        const codes = document.createElement("div");
        codes.className = "code-list";
        codeValues.forEach((value, index) => {
          const row = document.createElement("button");
          row.type = "button";
          row.className = "code-row";
          const label = index === 0 ? t("firstCode") : `${t("codeIndex")} ${index + 1}`;
          row.innerHTML = `<span>${label}</span><strong></strong>`;
          row.querySelector("strong").textContent = value;
          row.addEventListener("click", async () => {
            await navigator.clipboard?.writeText(value);
            showToast(t("copied"), "success");
          });
          codes.append(row);
        });
        card.append(codes);
      }
      if (waitingForCode) {
        card.append(renderRefundSafetyNote());
      }
      const events = Array.isArray(order.events) ? order.events.slice(0, 5) : [];
      if (events.length) {
        const timeline = document.createElement("div");
        timeline.className = "timeline";
        timeline.innerHTML = events.map((event) => `
          <div class="timeline-row">
            <span></span>
            <strong>${event.label || event.event || t("update")}</strong>
            <small>${event.time || ""}</small>
          </div>
        `).join("");
        card.append(timeline);
      }
      const actions = order.actions || {};
      const actionRow = document.createElement("div");
      actionRow.className = "action-row";
      ["copy_number", "copy_code", "test_active", "second_code", "replace", "alternate_provider", "preview_recording", "download_recording", "rental_sms", "rental_finish", "rental_renew", "rental_wake", "rental_notes", "report_issue"].forEach((key) => {
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

function orderCodes(order) {
  const values = [];
  (Array.isArray(order?.codes) ? order.codes : []).forEach((code) => {
    const value = String(code || "").trim();
    if (value && !values.includes(value)) values.push(value);
  });
  const latest = String(order?.code || "").trim();
  if (latest && !values.includes(latest)) values.push(latest);
  return values;
}

async function runOrderAction(order, key, button) {
  const action = order.actions?.[key];
  if (action?.confirm_label_key && !window.confirm(labelForKey(action.confirm_label_key))) return;
  if (action?.method === "CLIENT") {
    if (key === "report_issue") {
      openIssueReport(order);
      return;
    }
    const value = key === "copy_code" ? order.code : (order.number || order.provider_number || "");
    if (value) await navigator.clipboard?.writeText(value);
    showToast(t("copied"), "success");
    return;
  }
  if (!action?.endpoint) return;
  setBusy(button, true);
  showBusy(labelForKey(action.busy_label_key || "working"));
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), key === "test_active" ? 20000 : 30000);
  try {
    const payload = await api(action.endpoint, {
      method: action.method || "POST",
      body: action.body || {},
      headers: action.idempotency_key ? { "Idempotency-Key": action.idempotency_key } : {},
      signal: controller.signal,
    });
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
    mergeActions(payload);
    if (payload.order) updateOrderInState(payload.order);
    if (key === "test_active") {
      renderOrders();
      renderSupportOrders();
      showResultModal(testActiveMessage(payload.order || order));
      return;
    }
    showToast(payload.message || t("orderUpdated"), "success");
    await loadOrders();
  } catch (error) {
    showToast(friendlyError(error), "danger");
  } finally {
    window.clearTimeout(timeout);
    hideBusy();
    setBusy(button, false);
  }
}

function updateOrderInState(order) {
  if (!order?.id) return;
  const rows = Array.isArray(state.orders) ? state.orders : [];
  const index = rows.findIndex((item) => String(item.id || "") === String(order.id));
  if (index >= 0) {
    state.orders = rows.map((item, idx) => idx === index ? { ...item, ...order } : item);
    return;
  }
  state.orders = [order, ...rows];
}

function testActiveMessage(order) {
  const mode = orderMode(order);
  const status = String(order?.public_status || order?.status || "").toLowerCase();
  if (mode === "rental") return t("rentalStillActive");
  if (mode === "voice") return status.includes("call") || order?.recording_available ? t("numberActiveCodeReceived") : t("callStillActive");
  if (status === "code_received" || order?.code || (Array.isArray(order?.codes) && order.codes.length > 1)) {
    return t("numberActiveCodeReceived");
  }
  return t("numberActiveNoNewCode");
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
    showToast(t("loadOrdersFailed"), "danger");
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
    els.accountContent.replaceChildren(emptyState(t("openTelegramAccount")));
    return;
  }
  const activity = payload.recent_activity || [];
  const fullActivity = state.accountActivityAll || [];
  const visibleActivity = state.accountActivityExpanded && fullActivity.length ? fullActivity : activity;
  const activityLabel = state.accountActivityExpanded ? t("walletActivityAll") : t("walletActivityLimited");
  const hero = document.createElement("section");
  hero.className = "account-hero";
  hero.innerHTML = `
    <div class="account-hero-top">
      <div>
        <span>${t("availableBalance")}</span>
        <strong>${payload.balance_label || "-"}</strong>
      </div>
      <div class="account-user-id">
        <span>${t("userId")}</span>
        <b>${payload.user.id || "-"}</b>
      </div>
    </div>
    <p>${payload.user.username ? `@${payload.user.username}` : "Telegram Mini App"}</p>
  `;
  const languagePanel = document.createElement("section");
  languagePanel.className = "account-language-panel";
  const nextLanguage = state.lang === "ar" ? "en" : "ar";
  languagePanel.innerHTML = `
    <div>
      <span>${t("language")}</span>
      <strong>${payload.user.language_label || payload.user.language || "-"}</strong>
    </div>
  `;
  const languageButton = document.createElement("button");
  languageButton.type = "button";
  languageButton.className = "inline-action account-language-button";
  languageButton.textContent = `${t("changeLanguage")} · ${nextLanguage.toUpperCase()}`;
  languageButton.addEventListener("click", () => changeAccountLanguage(nextLanguage, languageButton));
  languagePanel.append(languageButton);
  const activityList = document.createElement("section");
  activityList.className = "account-activity";
  activityList.innerHTML = `
    <div class="account-activity-head">
      <div>
        <h3>${t("walletActivity")}</h3>
        <p class="status-text">${activityLabel}</p>
      </div>
    </div>
  `;
  const toggleButton = document.createElement("button");
  toggleButton.type = "button";
  toggleButton.className = "activity-toggle";
  toggleButton.setAttribute("aria-expanded", String(state.accountActivityExpanded));
  toggleButton.textContent = state.accountActivityExpanded ? "⌃" : "⌄";
  toggleButton.addEventListener("click", () => toggleAccountActivity(toggleButton));
  activityList.querySelector(".account-activity-head")?.append(toggleButton);
  const activityRows = visibleActivity.length
    ? visibleActivity.map(renderAccountActivity)
    : [emptyState(t("noWalletActivity"))];
  activityList.append(...activityRows);
  els.accountContent.replaceChildren(
    hero,
    languagePanel,
    activityList
  );
}

async function changeAccountLanguage(language, button) {
  const previous = state.lang;
  const action = actionFor("change_language", "/mini/numbers/api/account/language", "POST");
  setBusy(button, true);
  try {
    const payload = await api(action.endpoint, { method: action.method || "POST", body: { language } });
    mergeActions(payload);
    state.account = payload;
    state.recharge = payload.recharge || state.recharge;
    state.accountActivityExpanded = false;
    state.accountActivityAll = null;
    setLanguage(payload.user?.language || language);
    showToast(t("languageChanged"), "success");
    renderNav();
    renderModes();
    renderBuy();
    renderOrders();
    renderRecharge();
    renderSupportCategories();
    renderAccount();
  } catch (error) {
    setLanguage(previous);
    showToast(friendlyError(error), "danger");
    renderAccount();
  } finally {
    setBusy(button, false);
  }
}

async function toggleAccountActivity(button) {
  if (state.accountActivityExpanded) {
    state.accountActivityExpanded = false;
    renderAccount();
    return;
  }
  state.accountActivityExpanded = true;
  if (!state.accountActivityAll) {
    const action = actionFor("account_activity", "/mini/numbers/api/account/activity");
    setBusy(button, true);
    try {
      const payload = await api(action.endpoint, { method: action.method || "GET" });
      mergeActions(payload);
      state.accountActivityAll = payload.activity || [];
    } catch (error) {
      state.accountActivityExpanded = false;
      showToast(friendlyError(error), "danger");
    } finally {
      setBusy(button, false);
    }
  }
  renderAccount();
}

async function downloadActivityCsv(button) {
  const action = state.account?.actions?.account_activity_export || state.clientActions?.account_activity_export || {};
  if (!action.endpoint) return;
  setBusy(button, true);
  try {
    const response = await fetch(action.endpoint, { method: action.method || "GET", headers: headers() });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "phantom-numbers-wallet-activity.csv";
    document.body.append(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  } catch (error) {
    showToast(friendlyError(error), "danger");
  } finally {
    setBusy(button, false);
  }
}

function renderAccountActivity(item) {
  const row = document.createElement("article");
  row.className = `activity-row ${Number(item.amount || 0) >= 0 ? "positive" : "negative"}`;
  row.innerHTML = `
    <div>
      <strong>${item.label || item.subject || t("update")}</strong>
      <span>${item.created_at || ""}</span>
    </div>
    <b>${item.amount_label || ""}</b>
  `;
  return row;
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
    if (state.account.user?.language) setLanguage(state.account.user.language);
    if (state.account.balance_label) els.balance.textContent = state.account.balance_label;
    state.recharge = state.account.recharge || state.recharge;
    state.support.categories = state.account.support_categories || state.support.categories;
  } catch (_error) {
    state.account = null;
    showToast(t("loadAccountFailed"), "danger");
  } finally {
    setViewLoading("account", false);
  }
  renderAccount();
  renderRecharge();
  renderSupportCategories();
}

function rechargeRateLabel(method) {
  const rate = Number(method?.per_credit ?? method?.rate ?? 0);
  const currency = method?.currency || "USD";
  if (!Number.isFinite(rate) || rate <= 0) return "-";
  return `1 credit = ${rate.toLocaleString("en-US", { maximumFractionDigits: 4 })} ${currency}`;
}

function renderRechargeMethodCard(method) {
  const card = document.createElement("button");
  card.type = "button";
  card.className = `recharge-method-card${String(els.rechargeMethod.value || "") === String(method.code || "") ? " selected" : ""}`;
  card.textContent = method.title || method.code || t("paymentMethod");
  card.setAttribute("aria-pressed", String(els.rechargeMethod.value || "") === String(method.code || ""));
  card.addEventListener("click", () => {
    els.rechargeMethod.value = method.code || "";
    updateRechargeMethodDetails();
    renderRecharge();
  });
  return card;
}

function renderRecharge() {
  if (state.viewLoading.recharge) {
    els.rechargeForm.classList.add("hidden");
    els.rechargeContent.replaceChildren(...loadingStack(3));
    return;
  }
  const payload = state.recharge;
  if (!payload) {
    els.rechargeContent.replaceChildren(emptyState(t("openTelegramRecharge")));
    return;
  }
  const methods = payload.methods || [];
  renderRechargeForm(methods);
  const methodsGrid = document.createElement("section");
  methodsGrid.className = "recharge-method-grid";
  methodsGrid.append(...methods.map(renderRechargeMethodCard));
  const cards = [
    ...(methods.length ? [methodsGrid] : []),
  ];
  els.rechargeContent.replaceChildren(...(cards.length ? cards : [emptyState(t("noRechargeMethods"))]));
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
    showToast(t("loadRechargeFailed"), "danger");
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
      option.textContent = `${method.title || method.code || "-"} · ${method.rate_label || rechargeRateLabel(method)}`;
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
    <p>${t("paymentAddress")}: <strong>${method.target || "-"}</strong></p>
    <p>${t("price")}: <strong>${method.rate_label || "-"}</strong></p>
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
    els.rechargeStatus.textContent = t("validRechargeAmount");
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
  showBusy(t("submitRecharge"));
  try {
    const payload = await api(action.endpoint, { method: action.method || "POST", body: formData });
    mergeActions(payload);
    state.recharge = payload.recharge || state.recharge;
    if (payload.balance_label) els.balance.textContent = payload.balance_label;
    els.rechargeAmount.value = "";
    els.rechargeProof.value = "";
    els.rechargeStatus.textContent = payload.message || t("rechargeSent");
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
    els.supportCategory.replaceChildren(new Option(t("loading"), ""));
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

function orderDetailValue(order, key) {
  const detail = (Array.isArray(order?.details) ? order.details : [])
    .find((item) => String(item.key || "").toLowerCase() === key);
  return String(detail?.value || "").trim();
}

function supportOrderContext(order) {
  if (!order) return "";
  const parts = [
    order.id ? `Order: ${order.id}` : "",
    order.mode ? `Mode: ${order.mode}` : "",
    order.service_label ? `Service: ${order.service_label}` : "",
    order.number || order.provider_number ? `Number: ${order.number || order.provider_number}` : "",
    statusLabel(order) ? `Status: ${statusLabel(order)}` : "",
    order.price_label ? `Price: ${order.price_label}` : "",
    orderDetailValue(order, "provider") ? `Provider: ${orderDetailValue(order, "provider")}` : "",
    orderDetailValue(order, "country") ? `Country: ${orderDetailValue(order, "country")}` : "",
    orderDetailValue(order, "duration") ? `Duration: ${orderDetailValue(order, "duration")}` : "",
  ];
  return parts.filter(Boolean).join("\n");
}

function openIssueReport(order) {
  state.pendingSupportReport = {
    orderId: String(order?.id || ""),
    category: "numbers",
    message: t("issuePrompt"),
  };
  setView("support");
}

function applyPendingSupportReport() {
  const report = state.pendingSupportReport;
  if (!report) return;
  if (report.category && [...els.supportCategory.options].some((option) => option.value === report.category)) {
    els.supportCategory.value = report.category;
  }
  if (report.orderId && [...els.supportOrder.options].some((option) => option.value === report.orderId)) {
    els.supportOrder.value = report.orderId;
  }
  if (!els.supportMessage.value.trim()) {
    els.supportMessage.value = report.message || "";
  }
  els.supportStatus.textContent = t("issueStatus");
  els.supportMessage.focus();
  state.pendingSupportReport = null;
}

function supportMessageText(value) {
  return String(value || "")
    .replace(i18n.ar.issuePrompt.trim(), "")
    .replace(i18n.en.issuePrompt.trim(), "")
    .trim();
}

function supportMessageHasUserText(value) {
  const text = supportMessageText(value);
  return text.length >= 6;
}

function renderSupportOrders() {
  const rows = state.orders || [];
  const options = [new Option(t("noSpecificOrder"), "")];
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
    showToast(t("loadSupportFailed"), "danger");
  } finally {
    setViewLoading("support", false);
  }
  renderSupportCategories();
  renderSupportOrders();
  applyPendingSupportReport();
}

async function submitSupport(event) {
  event.preventDefault();
  els.supportStatus.textContent = "";
  if (!headers()["X-Telegram-Init-Data"]) {
    els.supportStatus.textContent = t("openTelegramSupport");
    showToast(els.supportStatus.textContent, "danger");
    return;
  }
  const rawMessage = els.supportMessage.value.trim();
  const userMessage = supportMessageText(rawMessage);
  if (!supportMessageHasUserText(rawMessage)) {
    els.supportStatus.textContent = t("clearerIssue");
    showToast(els.supportStatus.textContent, "danger");
    return;
  }
  const orderId = els.supportOrder.value;
  const order = state.orders.find((item) => String(item.id || "") === String(orderId));
  const context = supportOrderContext(order);
  const message = [context, userMessage].filter(Boolean).join("\n\n");
  const button = els.supportForm.querySelector("button[type='submit']");
  setBusy(button, true);
  showBusy(t("sendTicketBusy"));
  try {
    const action = actionFor("submit_support_ticket", "/mini/numbers/api/support/ticket", "POST");
    const payload = await api(action.endpoint, { method: action.method || "POST", body: { category: els.supportCategory.value || "numbers", message } });
    mergeActions(payload);
    els.supportMessage.value = "";
    els.supportStatus.textContent = payload.message || t("ticketSent");
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
  const wasView = state.view;
  state.view = view;
  document.querySelectorAll(".view").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  document.querySelectorAll(".nav-item, .menu-item").forEach((el) => el.classList.toggle("active", el.dataset.view === view));
  closeMenu();
  if (view === "buy" && wasView !== "buy") {
    resetBuySelections({ mode: state.mode });
    renderBuy();
  }
  if (view === "orders") loadOrders();
  if (view === "account") loadAccount();
  if (view === "recharge") loadRecharge();
  if (view === "support") loadSupport();
}

async function boot() {
  applyRuntimeTheme();
  setLanguage(initialLanguage());
  tg?.ready?.();
  tg?.expand?.();
  tg?.onEvent?.("themeChanged", applyRuntimeTheme);
  document.body.classList.toggle("telegram-runtime", Boolean(tg) || params.get("telegram_runtime") === "1");
  const bootstrap = await api("/mini/numbers/api/bootstrap");
  state.bootstrap = bootstrap;
  if (bootstrap.language) setLanguage(bootstrap.language);
  state.services = bootstrap.services || [];
  state.countries = bootstrap.countries || [];
  state.states = bootstrap.states_us || [];
  state.clientActions = bootstrap.client?.actions || {};
  const defaults = bootstrap.defaults || {};
  state.mode = defaults.mode && defaults.mode !== "none" ? defaults.mode : "temp";
  resetBuySelections({ mode: state.mode });
  renderBuy();
  renderNav();
  renderSupportCategories();
  renderSupportOrders();
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
els.resultClose?.addEventListener("click", closeResultModal);
els.resultModal?.addEventListener("click", (event) => {
  if (event.target === els.resultModal) closeResultModal();
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
els.rechargeButton?.addEventListener("click", () => setView("recharge"));
els.balanceButton.addEventListener("click", () => setView("account"));
els.balanceButton.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    setView("account");
  }
});
els.themeToggle?.addEventListener("click", toggleTheme);
els.supportForm.addEventListener("submit", submitSupport);
els.rechargeForm.addEventListener("submit", submitRecharge);
els.rechargeMethod.addEventListener("change", updateRechargeMethodDetails);

const bootWatchdog = window.setTimeout(() => {
  document.body.classList.remove("app-booting");
  els.offerList?.replaceChildren(emptyState(t("appSlow")));
}, 14000);

boot().catch((error) => {
  els.offerList.replaceChildren(emptyState(error.message || t("appLoadFailed")));
}).finally(() => {
  window.clearTimeout(bootWatchdog);
  document.body.classList.remove("app-booting");
});
