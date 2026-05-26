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
  orderFlowOpen: true,
  pricesChecked: false,
  priceCheckFailed: false,
  loading: false,
  activeOrders: [],
  account: null,
  recharge: null,
  supportCategories: [],
  supportOrderRows: [],
  supportBotUrl: null,
  rechargeUrl: null,
  client: {},
  tabs: [],
  clientActions: {},
  providerRows: [],
  serviceMenuOpen: false,
  countryMenuOpen: false,
  stateMenuOpen: false,
  countrySuggestionRanks: {},
  countrySuggestionPrices: {},
  countrySuggestionRequestId: 0,
  priceRequestId: 0,
  busyCount: 0,
  priceProgressTimer: null,
  priceProgressStartedAt: 0,
  rechargeMethodCode: "",
  accountNotice: "",
  rechargeSubmitting: false,
};

const QUICK_COUNTRY_ISOS = ["US", "GB", "DE", "FR"];
const QUICK_STATE_CODES = ["CA", "NY", "TX", "FL", "WA"];

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
  rechargeView: document.getElementById("rechargeView"),
  rechargeDetails: document.getElementById("rechargeDetails"),
  langArButton: document.getElementById("langArButton"),
  langEnButton: document.getElementById("langEnButton"),
  rechargeButton: document.getElementById("rechargeButton"),
  supportView: document.getElementById("supportView"),
  supportCategory: document.getElementById("supportCategory"),
  supportOrder: document.getElementById("supportOrder"),
  supportMessage: document.getElementById("supportMessage"),
  sendSupportButton: document.getElementById("sendSupportButton"),
  supportStatus: document.getElementById("supportStatus"),
  busyOverlay: document.getElementById("busyOverlay"),
  busyTitle: document.getElementById("busyTitle"),
  busyText: document.getElementById("busyText"),
};

const copy = {
  ar: {
    eyebrow: "PHANTOM NUMBERS",
    title: "الأرقام",
    tabBuy: "شراء",
    tabOrders: "طلباتي",
    tabRecharge: "شحن",
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
    loading: "جاري فحص المزودين",
    loadingPhaseFast: "جاري فحص المزودين الأسرع",
    loadingPhaseSlow: "بانتظار المزودين الأبطأ قليلاً",
    loadingPhaseFinal: "جاري تجهيز أسعار المزودين المتاحة",
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
    callDetected: "تم رصد المكالمة",
    recordingPending: "بانتظار تجهيز التسجيل",
    callReceived: "وصلت المكالمة",
    recording: "تسجيل المكالمة",
    playRecording: "تشغيل التسجيل",
    downloadRecording: "تحميل التسجيل",
    noOrders: "لا توجد أرقام حاليا",
    buy: "شراء",
    refresh: "تحديث",
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
    recharge: "شراء",
    rechargeTab: "شحن الرصيد",
    openingRecharge: "فتح الشحن",
    support: "الدعم",
    supportTitle: "فتح تذكرة دعم",
    supportCategory: "القسم",
    supportOrder: "الطلب المرتبط",
    noOrderContext: "بدون طلب محدد",
    supportMessage: "الرسالة",
    supportPlaceholder: "اكتب المشكلة أو رقم الطلب إن وجد",
    sendSupport: "إرسال تذكرة الدعم",
    supportSent: "تم إرسال التذكرة",
    loadingAccount: "جاري تحميل الحساب",
    openBot: "فتح البوت",
  },
  en: {
    eyebrow: "PHANTOM NUMBERS",
    title: "Numbers",
    tabBuy: "Buy",
    tabOrders: "My numbers",
    tabRecharge: "Top up",
    tabAccount: "Account",
    tabSupport: "Support",
    beforeOrder: "Before ordering",
    introTitle: "Important notes before requesting a number",
    introNotice1: "Choose the exact service. The number is reserved for the selected service only.",
    introNotice2: "Leaving the state unset usually provides more options and better prices.",
    introNotice3: "If no code or call arrives, the app checks the provider and follows the refund flow when eligible.",
    orderConsole: "Order console",
    orderConsoleTitle: "Choose service and check provider prices",
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
    loading: "Checking providers",
    loadingPhaseFast: "Checking priority providers",
    loadingPhaseSlow: "Waiting for slower providers",
    loadingPhaseFinal: "Preparing available provider prices",
    ready: "Choose a service and country, then check prices",
    empty: "No offers are available for this selection",
    emptyVoice: "No call number is available for this service right now.",
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
    callDetected: "Call detected",
    recordingPending: "Waiting for recording",
    callReceived: "Call received",
    recording: "Call recording",
    playRecording: "Play recording",
    downloadRecording: "Download recording",
    noOrders: "No numbers right now",
    buy: "Buy",
    refresh: "Refresh",
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
    rechargeTab: "Top up balance",
    openingRecharge: "Opening recharge",
    rechargeTitle: "Top up balance",
    rechargeSubtitle: "Choose a payment method, enter the paid amount, and upload the proof inside the app.",
    rechargeMethod: "Payment method",
    choosePaymentMethod: "Choose payment method",
    paymentTarget: "Payment details",
    paymentRate: "Rate",
    paidAmount: "Paid amount",
    proofFile: "Payment proof",
    proofHint: "Upload the transfer receipt or payment proof screenshot.",
    submitRecharge: "Submit recharge request",
    submittingRecharge: "Submitting recharge request",
    rechargeSubmitted: "Recharge request submitted",
    rechargeRequests: "Recharge requests",
    noRechargeRequests: "No recharge requests yet",
    openRechargeBot: "Open recharge bot",
    refreshBalance: "Refresh balance",
    copiedPaymentTarget: "Payment details copied",
    noPaymentMethods: "No payment methods are available right now",
    support: "Support",
    supportTitle: "Open support ticket",
    supportCategory: "Category",
    supportOrder: "Related order",
    noOrderContext: "No specific order",
    supportMessage: "Message",
    supportPlaceholder: "Describe the issue or include an order number",
    sendSupport: "Send support ticket",
    supportSent: "Support ticket sent",
    loadingAccount: "Loading account",
    openBot: "Open bot",
    refundWorking: "Refund in progress",
    refundWait: "Checking provider and wallet. Please wait.",
    waitForSms: "Waiting for the SMS. Refunds are handled automatically if no code arrives.",
    waitForWebhook: "Waiting for the provider webhook. No polling is running in the app.",
    waitForCall: "Waiting for the call.",
    waitForCallWebhook: "Waiting for the provider call webhook.",
    waitForRecording: "Call detected. Waiting for the recording to be attached.",
    waitForRentalSms: "Waiting for rental SMS.",
    codeReady: "Code received. Copy it and continue.",
    recordingReady: "Recording is ready.",
    autoRefundChecking: "Automatic refund is being checked by the server.",
    supportReviewQueued: "This order needs support review before a refund decision.",
    refundedToWallet: "Refund completed to your wallet.",
    orderClosedNoCode: "Order closed without a received code.",
    failed: "Failed",
    expired: "Expired",
    working: "Working",
    pleaseWait: "Please wait.",
    checkingOrder: "Checking order",
    voiceFallback: "Generic voice number",
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
  tabRecharge: "شحن",
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
  orderConsole: "\u0644\u0648\u062d\u0629 \u0627\u0644\u0637\u0644\u0628",
  orderConsoleTitle: "\u0627\u062e\u062a\u0631 \u0627\u0644\u062e\u062f\u0645\u0629 \u0648\u0627\u0641\u062d\u0635 \u0623\u0633\u0639\u0627\u0631 \u0627\u0644\u0645\u0632\u0648\u062f\u064a\u0646",
  loading: "جاري فحص المزودين",
  loadingPhaseFast: "جاري فحص المزودين الأسرع",
  loadingPhaseSlow: "بانتظار المزودين الأبطأ قليلاً",
  loadingPhaseFinal: "جاري تجهيز أسعار المزودين المتاحة",
  ready: "اختر الخدمة والدولة ثم افحص السعر",
  empty: "لا توجد عروض متاحة لهذا الاختيار",
  emptyVoice: "لا يوجد رقم اتصال متاح لهذه الخدمة حالياً.",
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
  callDetected: "تم رصد المكالمة",
  recordingPending: "بانتظار تجهيز التسجيل",
  callReceived: "وصلت المكالمة",
  recording: "تسجيل المكالمة",
  playRecording: "تشغيل التسجيل",
  downloadRecording: "تحميل التسجيل",
  noOrders: "لا توجد أرقام حالياً",
  buy: "شراء",
  refresh: "تحديث",
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
  waitForSms: "\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0627\u0644\u0631\u0633\u0627\u0644\u0629. \u0627\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639 \u064a\u062a\u0645 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b \u0625\u0630\u0627 \u0644\u0645 \u064a\u0635\u0644 \u0643\u0648\u062f.",
  waitForWebhook: "\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0648\u064a\u0628 \u0647\u0648\u0643 \u0627\u0644\u0627\u0633\u062a\u0644\u0627\u0645. \u0627\u0644\u062a\u0637\u0628\u064a\u0642 \u0644\u0627 \u064a\u0639\u0645\u0644 \u0628\u0648\u0644\u064a\u0646\u063a.",
  waitForCall: "\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0627\u0644\u0645\u0643\u0627\u0644\u0645\u0629.",
  waitForCallWebhook: "\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0648\u064a\u0628 \u0647\u0648\u0643 \u0627\u0644\u0645\u0643\u0627\u0644\u0645\u0629.",
  waitForRecording: "\u062a\u0645 \u0631\u0635\u062f \u0627\u0644\u0645\u0643\u0627\u0644\u0645\u0629\u060c \u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0627\u0644\u062a\u0633\u062c\u064a\u0644.",
  waitForRentalSms: "\u0628\u0627\u0646\u062a\u0638\u0627\u0631 \u0631\u0633\u0627\u0644\u0629 \u0627\u0644\u0625\u064a\u062c\u0627\u0631.",
  codeReady: "\u0648\u0635\u0644 \u0627\u0644\u0643\u0648\u062f. \u0627\u0646\u0633\u062e\u0647 \u0648\u0643\u0645\u0644.",
  recordingReady: "\u0627\u0644\u062a\u0633\u062c\u064a\u0644 \u062c\u0627\u0647\u0632.",
  autoRefundChecking: "\u0627\u0644\u0633\u064a\u0631\u0641\u0631 \u064a\u0641\u062d\u0635 \u0627\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639 \u062a\u0644\u0642\u0627\u0626\u064a\u0627\u064b.",
  supportReviewQueued: "\u0647\u0630\u0627 \u0627\u0644\u0637\u0644\u0628 \u0628\u062d\u0627\u062c\u0629 \u0645\u0631\u0627\u062c\u0639\u0629 \u062f\u0639\u0645 \u0642\u0628\u0644 \u0642\u0631\u0627\u0631 \u0627\u0644\u0627\u0633\u062a\u0631\u062c\u0627\u0639.",
  refundedToWallet: "\u062a\u0645 \u0625\u0631\u062c\u0627\u0639 \u0627\u0644\u0631\u0635\u064a\u062f \u0644\u0645\u062d\u0641\u0638\u062a\u0643.",
  orderClosedNoCode: "\u0627\u0646\u062a\u0647\u0649 \u0627\u0644\u0637\u0644\u0628 \u0628\u062f\u0648\u0646 \u0643\u0648\u062f.",
  failed: "\u0641\u0634\u0644",
  expired: "\u0645\u0646\u062a\u0647\u064a",
  working: "جاري التنفيذ",
  pleaseWait: "يرجى الانتظار.",
  checkingOrder: "جاري فحص الطلب",
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
  recharge: "شراء",
  rechargeTab: "شحن الرصيد",
  openingRecharge: "فتح الشحن",
  rechargeTitle: "شحن الرصيد",
  rechargeSubtitle: "اختر طريقة الدفع وأرسل المبلغ والإثبات من داخل التطبيق.",
  rechargeMethod: "طريقة الدفع",
  choosePaymentMethod: "اختر طريقة الدفع",
  paymentTarget: "بيانات الدفع",
  paymentRate: "السعر",
  paidAmount: "المبلغ المدفوع",
  proofFile: "إثبات الدفع",
  proofHint: "ارفع صورة التحويل أو لقطة إثبات الدفع.",
  submitRecharge: "إرسال طلب الشحن",
  submittingRecharge: "جاري إرسال طلب الشحن",
  rechargeSubmitted: "تم إرسال طلب الشحن",
  rechargeRequests: "طلبات الشحن",
  noRechargeRequests: "لا توجد طلبات شحن بعد",
  openRechargeBot: "فتح بوت الشحن",
  refreshBalance: "تحديث الرصيد",
  copiedPaymentTarget: "تم نسخ بيانات الدفع",
  noPaymentMethods: "لا توجد طرق دفع متاحة حالياً",
  support: "الدعم",
  supportTitle: "فتح تذكرة دعم",
  supportCategory: "القسم",
  supportOrder: "الطلب المرتبط",
  noOrderContext: "بدون طلب محدد",
  supportMessage: "الرسالة",
  supportPlaceholder: "اكتب المشكلة أو رقم الطلب إن وجد",
  sendSupport: "إرسال تذكرة الدعم",
  supportSent: "تم إرسال التذكرة",
  loadingAccount: "جاري تحميل الحساب",
  openBot: "فتح البوت",
  voiceFallback: "رقم اتصال عام",
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

function statusIsAnyTranslation(key) {
  const text = els.statusLine?.textContent || "";
  return [copy.ar?.[key], copy.en?.[key]].filter(Boolean).includes(text);
}

function refreshTranslatedStatus() {
  if (!els.statusLine) return;
  if (!els.statusLine.textContent) {
    return;
  }
  if (statusIsAnyTranslation("ready")) {
    els.statusLine.textContent = t("ready");
  } else if (statusIsAnyTranslation("chooseServiceFirst")) {
    els.statusLine.textContent = t("chooseServiceFirst");
  } else if (statusIsAnyTranslation("loading")) {
    els.statusLine.textContent = t("loading");
  } else if (statusIsAnyTranslation("error")) {
    els.statusLine.textContent = t("error");
  }
}

function applyLanguage(languageCode, options = {}) {
  state.lang = String(languageCode || "ar").toLowerCase().startsWith("ar") ? "ar" : "en";
  if (options.persist) {
    try {
      window.localStorage?.setItem("numbersMiniAppLanguageChoice", state.lang);
    } catch (_error) {
      // Storage can be unavailable inside some embedded browsers.
    }
  }
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
  refreshTranslatedStatus();
}

function setLanguage() {
  let saved = "";
  try {
    saved = window.localStorage?.getItem("numbersMiniAppLanguageChoice") || "";
  } catch (_error) {
    saved = "";
  }
  const languageCode = saved || document.documentElement.lang || tg?.initDataUnsafe?.user?.language_code || "ar";
  applyLanguage(languageCode);
  els.statusLine.textContent = "";
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
    headers: headers({
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    }),
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

async function apiForm(path, formData) {
  const response = await fetch(path, {
    method: "POST",
    headers: headers(),
    body: formData,
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
  state.accountNotice = "";
  setView("recharge");
  window.setTimeout(() => {
    els.rechargeView?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, 0);
}

function openRechargeBot() {
  const url = rechargeUrl();
  if (url) {
    els.statusLine.textContent = t("openingRecharge");
    openTelegramUrl(url);
    return;
  }
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

const ICONS = {
  buy: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 7h12l-1 12H7L6 7Z"></path><path d="M9 7a3 3 0 0 1 6 0"></path></svg>',
  orders: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h11"></path><path d="M8 12h11"></path><path d="M8 18h11"></path><path d="M4 6h.01"></path><path d="M4 12h.01"></path><path d="M4 18h.01"></path></svg>',
  recharge: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v18"></path><path d="M17 8H9.5a3.5 3.5 0 0 0 0 7H14a3.5 3.5 0 0 1 0 7H6"></path></svg>',
  account: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 21a8 8 0 0 0-16 0"></path><circle cx="12" cy="7" r="4"></circle></svg>',
  support: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 12a8 8 0 0 1 16 0v4a2 2 0 0 1-2 2h-2"></path><path d="M4 12v3a2 2 0 0 0 2 2h1v-6H6a2 2 0 0 0-2 2Z"></path><path d="M20 12v3a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2Z"></path><path d="M13 18h3"></path></svg>',
  temp: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="3" width="12" height="18" rx="2"></rect><path d="M10 17h4"></path></svg>',
  rental: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 7h11v10H8z"></path><path d="M5 10h3"></path><path d="M5 14h3"></path><path d="M11 4v3"></path><path d="M16 4v3"></path></svg>',
  voice: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 2 .7 2.8a2 2 0 0 1-.4 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"></path></svg>',
};

function iconSvg(name) {
  return ICONS[name] || ICONS.buy;
}

function renderViewTabs() {
  const tabs = surfaceTabs();
  els.viewTabs.replaceChildren(
    ...tabs.map((tab) => {
      const key = tab.key || "buy";
      const button = document.createElement("button");
      button.type = "button";
      button.className = `view-tab${state.view === key ? " active" : ""}`;
      button.disabled = tab.enabled === false;
      const icon = document.createElement("span");
      icon.className = "nav-icon";
      icon.innerHTML = iconSvg(tab.icon || key);
      const text = document.createElement("span");
      text.className = "nav-label";
      text.textContent = t(tab.label_key || `tab${key.charAt(0).toUpperCase()}${key.slice(1)}`);
      button.append(icon, text);
      button.addEventListener("click", () => setView(key));
      return button;
    })
  );
}

function fallbackSurfaceTabs() {
  return [
    { key: "buy", label_key: "tabBuy", icon: "buy", enabled: true, requires_auth: false },
    { key: "orders", label_key: "tabOrders", icon: "orders", enabled: true, requires_auth: true },
    { key: "recharge", label_key: "tabRecharge", icon: "recharge", enabled: true, requires_auth: true },
    { key: "account", label_key: "tabAccount", icon: "account", enabled: true, requires_auth: true },
    { key: "support", label_key: "tabSupport", icon: "support", enabled: true, requires_auth: true },
  ];
}

function surfaceTabs() {
  const rows = Array.isArray(state.tabs) && state.tabs.length ? state.tabs : fallbackSurfaceTabs();
  return rows.filter((tab) => tab && tab.key && tab.enabled !== false);
}

function surfaceViewEnabled(view) {
  return surfaceTabs().some((tab) => tab.key === view);
}

function clientAction(key, fallbackUrl = "", fallbackMethod = "GET") {
  const actions = state.clientActions && typeof state.clientActions === "object" ? state.clientActions : {};
  const action = actions[key] && typeof actions[key] === "object" ? actions[key] : {};
  return {
    enabled: action.enabled !== false,
    endpoint: action.endpoint || fallbackUrl,
    method: String(action.method || fallbackMethod || "GET").toUpperCase(),
    reason: action.reason || "",
  };
}

function clientActionEndpoint(key, fallbackUrl = "") {
  return clientAction(key, fallbackUrl).endpoint || fallbackUrl;
}

function clientActionMethod(key, fallbackMethod = "GET") {
  return clientAction(key, "", fallbackMethod).method || fallbackMethod;
}

function resetBuyStatus() {
  if (!els.statusLine || state.loading || state.pricesChecked) return;
  state.priceCheckFailed = false;
  els.statusLine.textContent = "";
}

function clearTransientStatus({ clearPriceFailure = true } = {}) {
  if (!els.statusLine || state.loading || state.pricesChecked) return;
  if (clearPriceFailure) state.priceCheckFailed = false;
  els.statusLine.textContent = "";
}

function setView(view) {
  if (!surfaceViewEnabled(view)) {
    view = "buy";
  }
  state.view = view;
  els.buyView.classList.toggle("hidden", view !== "buy");
  els.activeBand.classList.toggle("hidden", view !== "orders");
  els.accountView.classList.toggle("hidden", view !== "account");
  els.rechargeView?.classList.toggle("hidden", view !== "recharge");
  els.supportView.classList.toggle("hidden", view !== "support");
  renderViewTabs();
  if (view === "orders") {
    refreshOrders({ quiet: true });
  }
  if (view === "buy") resetBuyStatus();
  if (view === "recharge") loadRecharge();
  if (view === "account") loadAccount();
  if (view === "support") loadSupportInfo();
}

function renderBuyFlow() {
  els.controlBand?.classList.remove("hidden");
  els.introBand?.classList.remove("hidden");
  els.introBand?.classList.toggle("compact", state.orderFlowOpen);
  els.requestNumberButton?.classList.toggle("hidden", state.orderFlowOpen);
  els.resultBand?.classList.toggle("hidden", !state.pricesChecked);
  els.successLegend?.classList.toggle("hidden", !state.pricesChecked);
  if (!state.pricesChecked && !state.loading && !state.priceCheckFailed && els.statusLine) {
    els.statusLine.textContent = "";
  }
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

function normalizeSearchText(value) {
  return String(value || "")
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

function orderedMatch(query, text) {
  const q = normalizeSearchText(query).replace(/\s+/g, "");
  const haystack = normalizeSearchText(text).replace(/\s+/g, "");
  if (!q) return true;
  let offset = 0;
  for (const char of q) {
    const next = haystack.indexOf(char, offset);
    if (next < 0) return false;
    offset = next + 1;
  }
  return true;
}

function rankedTokenMatch(tokens, query) {
  const q = normalizeSearchText(query);
  if (!q) return 0;
  let best = -1;
  for (const rawToken of tokens) {
    const token = normalizeSearchText(rawToken);
    if (!token) continue;
    if (token === q) best = Math.max(best, 500);
    else if (token.startsWith(q)) best = Math.max(best, 420);
    else if (token.includes(q)) best = Math.max(best, 320);
    else if (orderedMatch(q, token)) best = Math.max(best, 180);
  }
  return best;
}

function selectedServiceFromInput() {
  const raw = els.serviceSearch.value.trim() || state.selectedService;
  if (!raw) return state.selectedService;
  const lowered = normalizeSearchText(raw);
  const matches = (item) => {
    const aliases = Array.isArray(item.aliases) ? item.aliases : [];
    return [item.label, item.key, ...aliases].map((value) => normalizeSearchText(value));
  };
  const exact = state.services.find((item) => matches(item).some((value) => value === lowered));
  if (exact) return exact.key;
  const ranked = rankedServiceOptions(raw);
  return ranked[0]?.key || state.selectedService;
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
  state.priceCheckFailed = false;
  saveModeSelection();
  clearPriceResults();
  clearTransientStatus();
  loadCountrySuggestions();
  updateStateVisibility();
  updateServiceLabel();
  renderProviders([]);
  setServiceMenuOpen(false);
}

function serviceTokens(item) {
  const aliases = Array.isArray(item.aliases) ? item.aliases : [];
  return [item.label, item.key, ...aliases];
}

function rankedServiceOptions(query) {
  const q = normalizeSearchText(query);
  return state.services
    .map((item, index) => ({
      item,
      index,
      rank: rankedTokenMatch(serviceTokens(item), q),
    }))
    .filter((row) => !q || row.rank >= 0)
    .sort((a, b) => {
      if (q && b.rank !== a.rank) return b.rank - a.rank;
      if (Boolean(b.item.top) !== Boolean(a.item.top)) return Number(Boolean(b.item.top)) - Number(Boolean(a.item.top));
      return a.index - b.index;
    })
    .map((row) => row.item);
}

function renderServiceOptions() {
  const query = els.serviceSearch.value || "";
  const filtered = rankedServiceOptions(query).slice(0, 80);
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
  return [item?.name, item?.code, item?.iso, ...aliases];
}

function quickCountryRank(item) {
  if (String(item?.code) === "none") return 1000;
  const suggested = state.countrySuggestionRanks[String(item?.code || "")];
  if (suggested) return 2000 + suggested;
  const index = QUICK_COUNTRY_ISOS.indexOf(String(item?.iso || "").toUpperCase());
  return index >= 0 ? 900 - index : 0;
}

function quickStateRank(item) {
  if (String(item?.code) === "none") return 1000;
  const index = QUICK_STATE_CODES.indexOf(String(item?.code || "").toUpperCase());
  return index >= 0 ? 900 - index : 0;
}

function rankedSelectorOptions(list, kind, query, limit = 90) {
  const q = normalizeSearchText(query);
  const quickRank = kind === "country" ? quickCountryRank : quickStateRank;
  return list
    .map((item, index) => ({
      item,
      index,
      quick: quickRank(item),
      rank: rankedTokenMatch(searchTokens(item), q),
    }))
    .filter((row) => !q || row.rank >= 0)
    .sort((a, b) => {
      if (q && b.rank !== a.rank) return b.rank - a.rank;
      if (b.quick !== a.quick) return b.quick - a.quick;
      return a.index - b.index;
    })
    .slice(0, limit)
    .map((row) => row.item);
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
  if (open && isCountry && state.mode === "voice") {
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
  state.priceCheckFailed = false;
  if (state.selectedCountry !== "1") {
    state.selectedState = "none";
    if (els.stateSearch) els.stateSearch.value = "";
    setSelectorMenuOpen("state", false);
  }
  if (els.countrySearch) els.countrySearch.value = "";
  saveModeSelection();
  clearPriceResults();
  clearTransientStatus();
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
  state.priceCheckFailed = false;
  if (els.stateSearch) els.stateSearch.value = "";
  saveModeSelection();
  clearPriceResults();
  clearTransientStatus();
  updateSelectorLabels();
  renderProviders([]);
  setSelectorMenuOpen("state", false);
}

function renderCountryOptions() {
  const query = els.countrySearch?.value || "";
  const filtered = rankedSelectorOptions(state.countries, "country", query);
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
      key.textContent = state.countrySuggestionPrices[item.code] || (item.code === "none" ? "" : item.code);
      button.append(label, key);
      button.addEventListener("click", () => setCountrySelection(item.code));
      return button;
    })
  );
}

function renderStateOptions() {
  const query = els.stateSearch?.value || "";
  const filtered = rankedSelectorOptions(state.states, "state", query);
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
    ["temp", t("temp"), "temp"],
    ["rental", t("rental"), "rental"],
    ["voice", t("voice"), "voice"],
  ];
  els.modeSwitch.replaceChildren(
    ...modes.map(([key, label, iconName]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `mode-button${state.mode === key ? " active" : ""}`;
      const icon = document.createElement("span");
      icon.className = "mode-icon";
      icon.innerHTML = iconSvg(iconName);
      const text = document.createElement("span");
      text.className = "mode-label";
      text.textContent = label;
      button.append(icon, text);
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
        state.priceCheckFailed = false;
        clearPriceResults();
        clearTransientStatus();
        loadCountrySuggestions();
        setServiceMenuOpen(false);
        setSelectorMenuOpen("country", false);
        setSelectorMenuOpen("state", false);
        updateStateVisibility();
        updateServiceLabel();
        updateSelectorLabels();
        renderServiceOptions();
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
  els.countrySelect.disabled = !showCountry || state.mode === "voice";
  els.stateSelect.disabled = !showState;
  if (els.countryTrigger) {
    const countryLocked = state.mode === "voice";
    els.countryTrigger.disabled = !showCountry || countryLocked;
    els.countryTrigger.setAttribute("aria-disabled", showCountry && !countryLocked ? "false" : "true");
    els.countryField?.classList.toggle("locked", showCountry && countryLocked);
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

async function loadCountrySuggestions() {
  state.countrySuggestionRequestId += 1;
  const requestId = state.countrySuggestionRequestId;
  state.countrySuggestionRanks = {};
  state.countrySuggestionPrices = {};
  if (!state.selectedService || state.mode === "voice") {
    renderCountryOptions();
    return;
  }
  try {
    const params = new URLSearchParams({ mode: state.mode, service: state.selectedService });
    const payload = await api(`${clientActionEndpoint("country_suggestions", "/mini/numbers/api/country-suggestions")}?${params.toString()}`);
    if (requestId !== state.countrySuggestionRequestId) return;
    const ranks = {};
    const prices = {};
    (payload.countries || []).forEach((item, index) => {
      const code = String(item.code || "");
      if (!code) return;
      ranks[code] = Math.max(1, 999 - index);
      if (item.price_label) prices[code] = item.price_label;
    });
    state.countrySuggestionRanks = ranks;
    state.countrySuggestionPrices = prices;
    renderCountryOptions();
  } catch (_error) {
    if (requestId !== state.countrySuggestionRequestId) return;
    state.countrySuggestionRanks = {};
    state.countrySuggestionPrices = {};
    renderCountryOptions();
  }
}

function renderQuickServices() {
  els.quickServices.replaceChildren();
}

function priceProgressPhase(elapsedMs) {
  if (elapsedMs >= 12000) return t("loadingPhaseFinal");
  if (elapsedMs >= 5500) return t("loadingPhaseSlow");
  return t("loadingPhaseFast");
}

function renderPriceProgress() {
  if (!els.statusLine || !state.loading || !state.priceProgressStartedAt) return;
  const elapsedMs = Date.now() - state.priceProgressStartedAt;
  const percent = Math.min(94, Math.max(8, Math.round((elapsedMs / 18000) * 100)));
  const wrap = document.createElement("div");
  wrap.className = "price-progress";
  wrap.setAttribute("role", "progressbar");
  wrap.setAttribute("aria-valuemin", "0");
  wrap.setAttribute("aria-valuemax", "100");
  wrap.setAttribute("aria-valuenow", String(percent));

  const label = document.createElement("span");
  label.className = "price-progress-label";
  label.textContent = priceProgressPhase(elapsedMs);

  const track = document.createElement("span");
  track.className = "price-progress-track";
  const fill = document.createElement("span");
  fill.className = "price-progress-fill";
  fill.style.width = `${percent}%`;
  track.append(fill);

  wrap.append(label, track);
  els.statusLine.replaceChildren(wrap);
}

function startPriceProgress() {
  window.clearInterval(state.priceProgressTimer);
  state.priceProgressStartedAt = Date.now();
  renderPriceProgress();
  state.priceProgressTimer = window.setInterval(renderPriceProgress, 700);
}

function stopPriceProgress() {
  window.clearInterval(state.priceProgressTimer);
  state.priceProgressTimer = null;
  state.priceProgressStartedAt = 0;
}

function setLoading(loading) {
  state.loading = loading;
  els.quoteButton.disabled = loading;
  els.quoteButton.textContent = loading ? t("loading") : t("check");
  if (loading) {
    startPriceProgress();
  } else {
    stopPriceProgress();
  }
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

function customerState(order) {
  return order && typeof order.customer_state === "object" && order.customer_state ? order.customer_state : {};
}

function statusLabel(order) {
  const status = String(order.public_status || "");
  const display = customerState(order);
  if (status === "finished") return t("finished");
  if (display.status_label_key) return t(display.status_label_key);
  if (status === "code_received") return t("code");
  if (status === "refunded") return t("refunded");
  if (status === "refund_pending") return t("refundPending");
  if (order.mode === "voice" && status === "call_received") return t("callReceived");
  if (order.mode === "voice" && status === "waiting_for_recording") return t("recordingPending");
  if (order.mode === "voice") return t("waitingCall");
  return t("waiting");
}

function orderTimelineLabels(order) {
  const mode = String(order?.mode || "");
  const status = String(order?.public_status || "");
  if (mode === "voice") {
    const callStep = status === "call_received" || status === "waiting_for_recording" ? t("callDetected") : t("waitingCall");
    const recordingStep = status === "call_received" ? t("recording") : status === "waiting_for_recording" ? t("recordingPending") : t("checkCall");
    return [t("purchased"), callStep, recordingStep];
  }
  if (mode === "rental") {
    return [t("purchased"), t("waiting"), status === "finished" ? t("finished") : t("code")];
  }
  return [t("purchased"), t("waiting"), status === "code_received" ? t("code") : t("refresh")];
}

function orderTimelineState(order, index, total) {
  const status = String(order?.public_status || "");
  if (status === "refunded" || status === "failed" || status === "expired") {
    return index === total - 1 ? "danger" : "done";
  }
  if (status === "refund_pending") {
    return index === total - 1 ? "current" : "done";
  }
  if (status === "code_received" || status === "call_received" || status === "finished") {
    return "done";
  }
  if (status === "waiting_for_recording") {
    return index <= 1 ? "done" : "current";
  }
  if (status === "waiting") {
    return index === 0 ? "done" : index === 1 ? "current" : "pending";
  }
  return index === 0 ? "done" : "pending";
}

function renderOrderTimeline(order) {
  const status = String(order?.public_status || "");
  const labels = orderTimelineLabels(order);
  if (status === "refunded" || status === "failed" || status === "expired") {
    labels[labels.length - 1] = statusLabel(order);
  } else if (status === "refund_pending") {
    labels[labels.length - 1] = t("refundPending");
  }
  const timeline = document.createElement("ol");
  timeline.className = "order-timeline";
  labels.forEach((label, index) => {
    const item = document.createElement("li");
    item.className = `order-timeline-step ${orderTimelineState(order, index, labels.length)}`;
    const marker = document.createElement("span");
    marker.className = "timeline-marker";
    const text = document.createElement("span");
    text.textContent = label;
    item.append(marker, text);
    timeline.append(item);
  });
  return timeline;
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

function orderTone(order) {
  const status = String(order?.public_status || "");
  if (status === "code_received" || status === "call_received" || status === "finished") return "success";
  const displayTone = String(customerState(order).tone || "");
  if (["success", "refunded", "pending-refund", "danger", "waiting"].includes(displayTone)) return displayTone;
  if (status === "refunded") return "refunded";
  if (status === "refund_pending") return "pending-refund";
  if (status === "failed" || status === "expired") return "danger";
  return "waiting";
}

function refundStatusText(order) {
  const refund = order?.refund || {};
  if (refund.refunded || order?.public_status === "refunded") return t("refunded");
  if (refund.pending || order?.public_status === "refund_pending") return t("refundPending");
  return "";
}

function appendOrderFact(parent, label, value) {
  if (!value) return;
  const item = document.createElement("div");
  item.className = "order-fact";
  const key = document.createElement("span");
  key.textContent = label;
  const val = document.createElement("strong");
  val.textContent = value;
  item.append(key, val);
  parent.append(item);
}

function renderReceivePanel(order) {
  const panel = document.createElement("div");
  panel.className = `receive-panel ${orderTone(order)}`;
  const display = customerState(order);
  const label = document.createElement("span");
  label.className = "receive-label";
  label.textContent = display.receive_label_key ? t(display.receive_label_key) : statusLabel(order);
  const value = document.createElement("strong");
  value.className = "receive-value";
  if (order.code) {
    value.textContent = order.code;
  } else if (order.public_status === "refunded") {
    value.textContent = t("refunded");
  } else if (order.public_status === "refund_pending") {
    value.textContent = t("refundPending");
  } else if (order.mode === "voice" && order.public_status === "waiting_for_recording") {
    value.textContent = t("recordingPending");
  } else {
    value.textContent = ["waiting", "waiting_for_recording"].includes(order.public_status)
      ? `${formatDuration(order.seconds_left)} ${t("left")}`
      : statusLabel(order);
  }
  panel.append(label, value);
  return panel;
}

function renderOrderStateNote(order) {
  const key = String(customerState(order).message_key || "");
  if (!key) return null;
  const text = t(key);
  if (!text || text === key) return null;
  const note = document.createElement("p");
  note.className = `order-state-note ${orderTone(order)}`;
  note.textContent = text;
  return note;
}

function addOrderAction(actions, { label, className = "small-action", disabled = false, onClick }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.disabled = Boolean(disabled);
  if (onClick) button.addEventListener("click", () => onClick(button));
  actions.append(button);
  return button;
}

function orderAction(order, key) {
  const actions = order && typeof order.actions === "object" && order.actions ? order.actions : {};
  const action = actions[key];
  return action && typeof action === "object" ? action : null;
}

function orderActionEnabled(order, key, fallback = false) {
  const action = orderAction(order, key);
  if (action && Object.prototype.hasOwnProperty.call(action, "enabled")) {
    return Boolean(action.enabled);
  }
  return Boolean(fallback);
}

function orderActionEndpoint(order, key) {
  const action = orderAction(order, key);
  const endpoint = String(action?.endpoint || "").trim();
  return endpoint || "";
}

function orderActionMethod(order, key, fallback = "POST") {
  const action = orderAction(order, key);
  return String(action?.method || fallback || "POST").toUpperCase();
}

function orderActionLabel(order, key, fallbackKey) {
  const action = orderAction(order, key);
  return t(action?.label_key || fallbackKey || key);
}

function orderActionMetaText(order, key, field, fallbackKey = "") {
  const action = orderAction(order, key);
  const labelKey = String(action?.[field] || fallbackKey || "").trim();
  return labelKey ? t(labelKey) : "";
}

function orderActionIdempotencyKey(order, key) {
  const action = orderAction(order, key);
  return String(action?.idempotency_key || "").trim();
}

function orderActionHeaders(order, key, existing = {}) {
  const headers = { ...(existing || {}) };
  const idempotencyKey = orderActionIdempotencyKey(order, key);
  if (idempotencyKey && !headers["Idempotency-Key"]) {
    headers["Idempotency-Key"] = idempotencyKey;
  }
  return headers;
}

async function apiOrderAction(order, key, options = {}) {
  const endpoint = orderActionEndpoint(order, key);
  if (!endpoint) throw new Error(t("error"));
  return api(endpoint, {
    method: orderActionMethod(order, key, options.method || "POST"),
    body: options.body || {},
    headers: orderActionHeaders(order, key, options.headers),
  });
}

function purchaseAction(row) {
  const action = row && typeof row.purchase_action === "object" && row.purchase_action ? row.purchase_action : {};
  const fallbackToken = String(row?.quote_token || "").trim();
  if (action && Object.prototype.hasOwnProperty.call(action, "enabled") && !action.enabled) {
    return action;
  }
  return {
    enabled: Object.prototype.hasOwnProperty.call(action, "enabled") ? Boolean(action.enabled) : Boolean(fallbackToken),
    label_key: action.label_key || "buy",
    endpoint: action.endpoint || clientActionEndpoint("purchase", "/mini/numbers/api/purchase"),
    method: String(action.method || "POST").toUpperCase(),
    body: action.body && typeof action.body === "object" ? action.body : (fallbackToken ? { quote_token: fallbackToken } : {}),
    reason: action.reason || "",
  };
}

function renderOrderCard(order) {
  const card = document.createElement("article");
  card.className = `order-card order-card-v2 ${orderTone(order)}`;

  const main = document.createElement("div");
  main.className = "order-main";

  const header = document.createElement("div");
  header.className = "order-card-head";
  const titleWrap = document.createElement("div");
  titleWrap.className = "order-title-wrap";
  const title = document.createElement("h3");
  title.className = "order-title";
  title.textContent = order.service_label || order.service || "";
  const meta = document.createElement("p");
  meta.className = "order-meta";
  meta.textContent = [order.provider_id, order.price_label].filter(Boolean).join(" · ");
  titleWrap.append(title, meta);
  const status = document.createElement("span");
  status.className = `order-status-badge ${orderTone(order)}`;
  status.textContent = statusLabel(order);
  header.append(titleWrap, status);
  main.append(header, renderReceivePanel(order));
  const stateNote = renderOrderStateNote(order);
  if (stateNote) main.append(stateNote);

  const facts = document.createElement("div");
  facts.className = "order-facts";
  appendOrderFact(facts, t("number"), order.number || "-");
  appendOrderFact(facts, t("code"), order.code || "");
  appendOrderFact(facts, t("refundPending"), refundStatusText(order));
  if (order.mode === "rental" && Array.isArray(order.messages) && order.messages.length) {
    appendOrderFact(facts, t("rentalSms"), order.messages.slice(-1)[0]);
  }
  if (facts.children.length) main.append(facts);

  if (Array.isArray(order.events) && order.events.length) {
    const eventList = document.createElement("div");
    eventList.className = "order-event-list compact";
    order.events.slice(-2).forEach((event) => {
      const item = document.createElement("div");
      item.className = "order-event";
      const label = document.createElement("span");
      label.textContent = event.label || event.event || "";
      const time = document.createElement("small");
      time.textContent = event.time || "";
      item.append(label, time);
      eventList.append(item);
    });
    main.append(eventList);
  }

  const actions = document.createElement("div");
  actions.className = "order-actions order-actions-v2";
  if (orderActionEnabled(order, "copy_number", Boolean(order.number))) {
    addOrderAction(actions, { label: orderActionLabel(order, "copy_number", "copyNumber"), className: "small-action secondary-small", onClick: (button) => copyText(order.number, button) });
  }
  if (orderActionEnabled(order, "copy_code", Boolean(order.code))) {
    addOrderAction(actions, { label: orderActionLabel(order, "copy_code", "copyCode"), className: "small-action secondary-small", onClick: (button) => copyText(order.code, button) });
  }
  if (orderActionEnabled(order, "refresh", order.can_refresh !== false)) {
    addOrderAction(actions, { label: orderActionLabel(order, "refresh", order.mode === "voice" ? "checkCall" : "refresh"), onClick: (button) => refreshSingleOrder(order, button) });
  }
  if (order.mode === "temp" && orderActionEnabled(order, "second_code", order.can_second_code || order.can_resend)) {
    addOrderAction(actions, {
      label: `${orderActionLabel(order, "second_code", "secondCode")} ${order.second_code_price_label || ""}`.trim(),
      className: "small-action primary-small",
      onClick: (button) => requestSecondCode(order, button),
    });
  }
  if ((order.mode === "temp" || order.mode === "voice") && orderActionEnabled(order, "replace", order.can_replace)) {
    addOrderAction(actions, { label: orderActionLabel(order, "replace", "tryAnother"), className: "small-action secondary-small", onClick: (button) => replaceOrder(order, button) });
  }
  if (order.mode === "temp" && orderActionEnabled(order, "alternate_provider", order.can_alternate_provider)) {
    addOrderAction(actions, {
      label: [orderActionLabel(order, "alternate_provider", "alternateProvider"), order.alternate_provider_id, order.alternate_provider_price_label].filter(Boolean).join(" "),
      className: "small-action secondary-small",
      onClick: (button) => alternateOrder(order, button),
    });
  }
  if (order.mode === "voice" && orderActionEnabled(order, "preview_recording", Boolean(order.recording_url))) {
    addOrderAction(actions, { label: orderActionLabel(order, "preview_recording", "playRecording"), className: "small-action secondary-small", onClick: (button) => previewRecording(order, button, main) });
  }
  if (order.mode === "voice" && orderActionEnabled(order, "download_recording", Boolean(order.recording_url))) {
    addOrderAction(actions, { label: orderActionLabel(order, "download_recording", "downloadRecording"), onClick: (button) => downloadRecording(order, button) });
  }
  if (order.mode === "rental" && orderActionEnabled(order, "rental_sms", order.can_sms)) {
    addOrderAction(actions, { label: orderActionLabel(order, "rental_sms", "rentalSms"), onClick: (button) => rentalProviderAction(order, "rental_sms", button) });
  }
  if (order.mode === "rental" && orderActionEnabled(order, "rental_renew", order.can_renew)) {
    addOrderAction(actions, { label: orderActionLabel(order, "rental_renew", "renew"), onClick: (button) => rentalProviderAction(order, "rental_renew", button) });
  }
  if (order.mode === "rental" && orderActionEnabled(order, "rental_wake", order.can_wake)) {
    addOrderAction(actions, { label: orderActionLabel(order, "rental_wake", "wake"), className: "small-action secondary-small", onClick: (button) => rentalProviderAction(order, "rental_wake", button) });
  }
  if (order.mode === "rental" && orderActionEnabled(order, "rental_notes", order.can_notes)) {
    addOrderAction(actions, { label: orderActionLabel(order, "rental_notes", "notesTags"), className: "small-action secondary-small", onClick: (button) => rentalProviderAction(order, "rental_notes", button) });
  }
  if (order.mode === "rental" && orderActionEnabled(order, "rental_finish", order.can_finish)) {
    addOrderAction(actions, { label: orderActionLabel(order, "rental_finish", "finish"), className: "danger-action", onClick: (button) => finishOrder(order, button) });
  }

  card.append(main, actions);
  return card;
}

function renderActiveOrders(rows = state.activeOrders) {
  state.activeOrders = rows || [];
  if (!state.activeOrders.length) {
    els.activeOrders.replaceChildren(emptyState(canUseTelegramAuth() ? t("noOrders") : t("authRequired")));
    return;
  }
  els.activeOrders.replaceChildren(...state.activeOrders.map(renderOrderCard));
  return;
}

async function refreshOrders({ quiet = false } = {}) {
  if (!canUseTelegramAuth()) {
    renderActiveOrders([]);
    return;
  }
  try {
    const payload = await api(clientActionEndpoint("orders", "/mini/numbers/api/orders"));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    renderActiveOrders(payload.orders || []);
  } catch (error) {
    if (!quiet) els.statusLine.textContent = error.message || t("error");
  }
}

async function refreshSingleOrder(order, button) {
  const orderId = order?.id || "";
  if (!orderId) return;
  button.disabled = true;
  showBusy(orderActionMetaText(order, "refresh", "busy_label_key", "checkingOrder"), t("pleaseWait"));
  try {
    const payload = await apiOrderAction(
      order,
      "refresh"
    );
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

async function finishOrder(order, button) {
  const orderId = order?.id || "";
  if (!orderId) return;
  const confirmed = await askConfirm(orderActionMetaText(order, "rental_finish", "confirm_label_key", "finish"));
  if (!confirmed) return;
  button.disabled = true;
  showBusy(orderActionMetaText(order, "rental_finish", "busy_label_key", "working"), t("pleaseWait"));
  try {
    const payload = await apiOrderAction(
      order,
      "rental_finish"
    );
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

async function rentalProviderAction(order, actionKey, button) {
  const orderId = order?.id || "";
  if (!orderId || !actionKey) return;
  const confirmText = orderActionMetaText(order, actionKey, "confirm_label_key", "");
  const confirmed = confirmText ? await askConfirm(confirmText) : true;
  if (!confirmed) return;
  button.disabled = true;
  showBusy(orderActionMetaText(order, actionKey, "busy_label_key", "working"), t("pleaseWait"));
  try {
    const payload = await apiOrderAction(order, actionKey);
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
  const confirmed = await askConfirm(`${orderActionMetaText(order, "second_code", "confirm_label_key", "confirmSecondCode")} ${order.second_code_price_label || ""}`.trim());
  if (!confirmed) return;
  button.disabled = true;
  showBusy(orderActionMetaText(order, "second_code", "busy_label_key", "working"), t("pleaseWait"));
  try {
    const payload = await apiOrderAction(
      order,
      "second_code"
    );
    const next = state.activeOrders.filter((item) => item.id !== order.id);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || orderActionMetaText(order, "second_code", "success_label_key", "secondCodeRequested");
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
  const confirmed = await askConfirm(orderActionMetaText(order, "replace", "confirm_label_key", "confirmTryAnother"));
  if (!confirmed) return;
  button.disabled = true;
  showBusy(orderActionMetaText(order, "replace", "busy_label_key", "working"), t("pleaseWait"));
  try {
    const payload = await apiOrderAction(order, "replace");
    const next = state.activeOrders.filter((item) => item.id !== order.id);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || orderActionMetaText(order, "replace", "success_label_key", "replacementRequested");
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
  const confirmed = await askConfirm([orderActionMetaText(order, "alternate_provider", "confirm_label_key", "confirmAlternateProvider"), order.alternate_provider_id, order.alternate_provider_price_label].filter(Boolean).join(" "));
  if (!confirmed) return;
  button.disabled = true;
  showBusy(orderActionMetaText(order, "alternate_provider", "busy_label_key", "working"), t("pleaseWait"));
  try {
    const payload = await apiOrderAction(order, "alternate_provider");
    const next = state.activeOrders.filter((item) => item.id !== order.id);
    renderActiveOrders([payload.order, ...next].filter(Boolean));
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    els.statusLine.textContent = payload.message || orderActionMetaText(order, "alternate_provider", "success_label_key", "replacementRequested");
  } catch (error) {
    els.statusLine.textContent = error.message || t("error");
    await refreshOrders({ quiet: true });
  } finally {
    hideBusy();
    button.disabled = false;
  }
}

async function downloadRecording(order, button) {
  const url = orderActionEndpoint(order, "download_recording");
  if (!url) return;
  button.disabled = true;
  try {
    const response = await fetch(url, {
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

async function previewRecording(order, button, container) {
  const url = orderActionEndpoint(order, "preview_recording");
  if (!url || !container) return;
  const existing = container.querySelector(`[data-recording-preview="${order.id}"]`);
  if (existing) {
    existing.scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  const previous = button?.textContent || "";
  if (button) {
    button.disabled = true;
    button.textContent = t("loading");
  }
  try {
    const response = await fetch(url, {
      headers: headers(),
      cache: "no-store",
    });
    if (!response.ok) throw new Error(t("error"));
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const wrap = document.createElement("div");
    wrap.className = "recording-preview";
    wrap.dataset.recordingPreview = order.id;
    const label = document.createElement("span");
    label.textContent = t("recording");
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.preload = "metadata";
    audio.src = url;
    audio.addEventListener("ended", () => URL.revokeObjectURL(url), { once: true });
    wrap.append(label, audio);
    container.append(wrap);
    window.setTimeout(() => audio.play().catch(() => undefined), 0);
  } catch (_error) {
    els.statusLine.textContent = t("error");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = previous || t("playRecording");
    }
  }
}

async function buyProvider(row, button) {
  if (!canUseTelegramAuth()) {
    els.statusLine.textContent = t("authRequired");
    return;
  }
  const action = purchaseAction(row);
  if (!action.enabled || !action.endpoint) {
    els.statusLine.textContent = t("error");
    return;
  }
  const confirmed = await askConfirm(`${t("confirmBuy")} ${row.price_label || ""}`);
  if (!confirmed) return;
  button.disabled = true;
  showBusy(t("purchasing"), t("pleaseWait"));
  els.statusLine.textContent = t("purchasing");
  try {
    const purchaseKey = window.crypto?.randomUUID
      ? window.crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const payload = await api(action.endpoint, {
      method: action.method || "POST",
      body: action.body || {},
      headers: { "Idempotency-Key": `miniapp-purchase-${purchaseKey}` },
    });
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    renderActiveOrders([payload.order, ...state.activeOrders].filter(Boolean));
    els.statusLine.textContent = t("purchased");
    setView("orders");
    window.setTimeout(() => {
      els.activeBand?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 0);
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

function providerSuccessText(row) {
  const rate = String(row?.success_rate || "").trim();
  if (!rate || rate === "-" || /^n\/?a$/i.test(rate)) {
    return "";
  }
  return `\u2605 ${rate}`;
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

  const cards = allRows.map((row) => {
    const card = document.createElement("article");
    card.className = "provider-card";

    const main = document.createElement("div");
    main.className = "provider-main";

    const header = document.createElement("div");
    header.className = "provider-header";

    const name = document.createElement("p");
    name.className = "provider-name";
    name.textContent = row.provider_id || row.provider;

    const successBadge = document.createElement("span");
    successBadge.className = "success-badge";
    successBadge.title = t("successLegend");
    successBadge.textContent = providerSuccessText(row);
    header.append(name);
    if (successBadge.textContent) {
      header.append(successBadge);
    }

    const meta = document.createElement("p");
    meta.className = "provider-meta";
    const details = [];
    if (row.location_tag) details.push(`[${row.location_tag}]`);
    if (row.voice_fallback) details.push(t("voiceFallback"));
    meta.textContent = details.join(" · ");

    main.append(header, meta);
    if (row.options?.length) {
      const options = document.createElement("div");
      options.className = "option-row";
      row.options.forEach((option) => {
        const optionAction = purchaseAction(option);
        const pill = document.createElement(state.mode === "rental" && optionAction.enabled ? "button" : "span");
        pill.className = "option-pill";
        if (pill.tagName === "BUTTON") {
          pill.type = "button";
          pill.classList.add("buyable");
          pill.addEventListener("click", () => buyProvider({ ...row, ...option, price_label: option.price_label, purchase_action: optionAction }, pill));
        }
        const optionText = state.mode === "rental" ? rentalOptionLabel(option) : `${option.duration_label || option.duration || t("options")} ${option.price_label}`;
        pill.textContent = pill.tagName === "BUTTON" ? `${t("buy")} ${optionText}` : optionText;
        options.append(pill);
      });
      main.append(options);
    }

    const rowPurchaseAction = purchaseAction(row);
    if ((state.mode === "temp" || state.mode === "voice") && rowPurchaseAction.enabled) {
      const actions = document.createElement("div");
      actions.className = "provider-actions";
      const price = document.createElement("div");
      price.className = "action-price";
      price.textContent = row.price_label;
      const buy = document.createElement("button");
      buy.type = "button";
      buy.className = "small-action";
      buy.textContent = t("buy");
      buy.addEventListener("click", () => buyProvider({ ...row, purchase_action: rowPurchaseAction }, buy));
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

function selectedRechargeMethod(recharge) {
  const methods = recharge?.methods || [];
  if (!methods.length) {
    state.rechargeMethodCode = "";
    return null;
  }
  const current = methods.find((method) => method.code === state.rechargeMethodCode);
  if (current) return current;
  state.rechargeMethodCode = methods[0].code || "";
  return methods[0];
}

function accountNoticeCard(message) {
  const card = document.createElement("div");
  card.className = "account-notice";
  card.textContent = message || "";
  return card;
}

function paymentTargetBlock(method) {
  const block = document.createElement("div");
  block.className = "payment-target";

  const label = document.createElement("span");
  label.className = "info-label";
  label.textContent = t("paymentTarget");

  const target = document.createElement("strong");
  target.className = "payment-target-value";
  target.textContent = method?.target || "-";

  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "small-action secondary-small";
  copyButton.textContent = t("copyNumber");
  copyButton.disabled = !method?.target;
  copyButton.addEventListener("click", async () => {
    await copyText(method?.target || "", copyButton);
    els.statusLine.textContent = t("copiedPaymentTarget");
  });

  block.append(label, target, copyButton);
  return block;
}

function rechargeRequestsCard(rows = []) {
  const card = document.createElement("div");
  card.className = "recharge-requests-card";
  const title = document.createElement("h3");
  title.textContent = t("rechargeRequests");
  card.append(title);
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.className = "order-meta";
    empty.textContent = t("noRechargeRequests");
    card.append(empty);
    return card;
  }
  rows.slice(0, 6).forEach((row) => {
    const item = document.createElement("div");
    item.className = `recharge-request-row ${row.status || "pending"}`;
    const main = document.createElement("div");
    const label = document.createElement("strong");
    label.textContent = row.status_label || row.status || "-";
    const meta = document.createElement("span");
    meta.textContent = [row.method, row.paid_label, row.created_at].filter(Boolean).join(" · ");
    main.append(label, meta);
    const amount = document.createElement("b");
    amount.textContent = row.credits_label || "-";
    item.append(main, amount);
    card.append(item);
  });
  return card;
}

async function submitRechargeForm(form, statusNode) {
  if (!canUseTelegramAuth()) {
    statusNode.textContent = t("authRequired");
    return;
  }
  const formData = new FormData(form);
  const button = form.querySelector("button[type='submit']");
  if (!formData.get("method_code")) {
    statusNode.textContent = t("choosePaymentMethod");
    return;
  }
  if (!formData.get("paid_amount")) {
    statusNode.textContent = t("paidAmount");
    return;
  }
  const proof = formData.get("proof");
  if (!proof || !proof.size) {
    statusNode.textContent = t("proofHint");
    return;
  }
  state.rechargeSubmitting = true;
  if (button) button.disabled = true;
  showBusy(t("submittingRecharge"), t("pleaseWait"));
  statusNode.textContent = t("submittingRecharge");
  try {
    const payload = await apiForm(clientActionEndpoint("submit_recharge", "/mini/numbers/api/recharge/submit"), formData);
    state.accountNotice = payload.message || t("rechargeSubmitted");
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    await loadCurrentRechargeSurface();
  } catch (error) {
    state.accountNotice = error.message || t("error");
    if (state.view === "recharge") {
      renderRecharge(state.recharge);
    } else {
      renderAccount(state.account);
    }
  } finally {
    state.rechargeSubmitting = false;
    if (button) button.disabled = false;
    hideBusy();
  }
}

async function loadCurrentRechargeSurface() {
  if (state.view === "recharge") {
    await loadRecharge();
    return;
  }
  await loadAccount();
}

function rechargeActionCard(payload) {
  const recharge = payload?.recharge || {};
  const balanceLabel = payload?.balance_label || "-";
  const methods = recharge.methods || [];
  const method = selectedRechargeMethod(recharge);
  const card = document.createElement("div");
  card.className = "settings-action-card recharge-card";
  const header = document.createElement("div");
  header.className = "recharge-card-header";
  const copy = document.createElement("div");
  const label = document.createElement("span");
  label.className = "info-label";
  label.textContent = t("balance");
  const value = document.createElement("strong");
  value.className = "info-value";
  value.textContent = balanceLabel || "-";
  copy.append(label, value);
  const refresh = document.createElement("button");
  refresh.type = "button";
  refresh.className = "small-action secondary-small";
  refresh.textContent = t("refreshBalance");
  refresh.addEventListener("click", () => loadAccount());
  header.append(copy, refresh);

  const intro = document.createElement("div");
  intro.className = "recharge-intro";
  const title = document.createElement("h3");
  title.textContent = t("rechargeTitle");
  const subtitle = document.createElement("p");
  subtitle.textContent = t("rechargeSubtitle");
  intro.append(title, subtitle);

  const status = document.createElement("p");
  status.className = "recharge-status";

  if (!methods.length) {
    const empty = document.createElement("p");
    empty.className = "order-meta";
    empty.textContent = t("noPaymentMethods");
    card.append(header, intro, empty);
    return card;
  }

  const form = document.createElement("form");
  form.className = "recharge-form";

  const methodField = document.createElement("label");
  methodField.className = "field recharge-field";
  const methodText = document.createElement("span");
  methodText.textContent = t("rechargeMethod");
  const methodSelect = document.createElement("select");
  methodSelect.name = "method_code";
  methods.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.code || "";
    option.textContent = row.title || row.code || "-";
    option.selected = option.value === state.rechargeMethodCode;
    methodSelect.append(option);
  });
  methodSelect.addEventListener("change", () => {
    state.rechargeMethodCode = methodSelect.value;
    renderAccount(state.account);
  });
  methodField.append(methodText, methodSelect);

  const amountField = document.createElement("label");
  amountField.className = "field recharge-field";
  const amountText = document.createElement("span");
  amountText.textContent = t("paidAmount");
  const amountInput = document.createElement("input");
  amountInput.name = "paid_amount";
  amountInput.type = "number";
  amountInput.inputMode = "decimal";
  amountInput.min = "0";
  amountInput.step = "0.0001";
  amountInput.placeholder = method?.currency || "USD";
  amountField.append(amountText, amountInput);

  const proofField = document.createElement("label");
  proofField.className = "field recharge-field";
  const proofText = document.createElement("span");
  proofText.textContent = t("proofFile");
  const proofInput = document.createElement("input");
  proofInput.name = "proof";
  proofInput.type = "file";
  proofInput.accept = "image/*,.pdf";
  const proofHint = document.createElement("small");
  proofHint.className = "field-hint";
  proofHint.textContent = t("proofHint");
  proofField.append(proofText, proofInput, proofHint);

  const rate = document.createElement("div");
  rate.className = "recharge-rate";
  const rateKey = document.createElement("span");
  rateKey.textContent = t("paymentRate");
  const rateValue = document.createElement("strong");
  rateValue.textContent = method?.rate_label || "-";
  rate.append(rateKey, rateValue);

  const instructions = document.createElement("p");
  instructions.className = "recharge-instructions";
  instructions.textContent = method?.instructions || "";

  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "primary-action";
  submit.textContent = t("submitRecharge");

  form.append(
    methodField,
    paymentTargetBlock(method),
    rate,
    instructions,
    amountField,
    proofField,
    submit,
    status
  );
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submitRechargeForm(form, status);
  });

  card.append(header, intro, form);
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
  const cards = [
    ...(state.accountNotice ? [accountNoticeCard(state.accountNotice)] : []),
    infoCard(t("userId"), String(user.id || "-")),
    infoCard(t("username"), user.username ? `@${user.username}` : "-"),
    infoCard(t("language"), user.language_label || user.language || "-"),
    infoCard(t("joined"), user.joined_at || "-"),
    accountShortcutCard(t("rechargeTab"), payload.balance_label || "-", t("recharge"), openRecharge),
    rechargeRequestsCard(payload.recharge?.requests || []),
    activityCard(payload.recent_activity || []),
  ];
  els.accountDetails.replaceChildren(...cards);
}

function accountShortcutCard(title, value, actionLabel, onClick) {
  const card = document.createElement("div");
  card.className = "settings-action-card account-shortcut-card";
  const copy = document.createElement("div");
  const label = document.createElement("span");
  label.className = "info-label";
  label.textContent = title;
  const strong = document.createElement("strong");
  strong.className = "info-value";
  strong.textContent = value || "-";
  copy.append(label, strong);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "small-action";
  button.textContent = actionLabel;
  button.addEventListener("click", onClick);
  card.append(copy, button);
  return card;
}

function renderRecharge(payload) {
  state.recharge = payload;
  if (!payload) {
    els.rechargeDetails?.replaceChildren(emptyState(t("authRequired")));
    return;
  }
  const cards = [
    ...(state.accountNotice ? [accountNoticeCard(state.accountNotice)] : []),
    rechargeActionCard(payload),
    rechargeRequestsCard(payload.recharge?.requests || []),
  ];
  els.rechargeDetails?.replaceChildren(...cards);
}

async function loadRecharge() {
  if (!canUseTelegramAuth()) {
    renderRecharge(null);
    return;
  }
  els.rechargeDetails?.replaceChildren(emptyState(t("loadingAccount")));
  try {
    const payload = await api(clientActionEndpoint("recharge", "/mini/numbers/api/recharge"));
    state.clientActions = { ...state.clientActions, ...(payload.actions || {}) };
    state.recharge = payload;
    if (payload.balance_label) {
      els.sessionPill.textContent = payload.balance_label;
    }
    renderRecharge(payload);
  } catch (error) {
    els.rechargeDetails?.replaceChildren(emptyState(error.message || t("error")));
  }
}

async function loadAccount() {
  if (!canUseTelegramAuth()) {
    renderAccount(null);
    return;
  }
  els.accountDetails.replaceChildren(emptyState(t("loadingAccount")));
  try {
    const payload = await api(clientActionEndpoint("account", "/mini/numbers/api/account"));
    state.clientActions = { ...state.clientActions, ...(payload.actions || {}) };
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
    const payload = await api(clientActionEndpoint("change_language", "/mini/numbers/api/account/language"), {
      method: clientActionMethod("change_language", "POST"),
      body: { language },
    });
    state.clientActions = { ...state.clientActions, ...(payload.actions || {}) };
    applyLanguage(payload.user?.language || language, { persist: true });
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
  const options = state.supportCategories.map((item) => {
    const option = document.createElement("option");
    option.value = item.key;
    option.textContent = item.label;
    return option;
  });
  if (!options.length) {
    const option = document.createElement("option");
    option.value = "numbers";
    option.textContent = t("supportCategory");
    options.push(option);
  }
  els.supportCategory.replaceChildren(...options);
}

function renderSupportOrders(rows = state.supportOrderRows) {
  state.supportOrderRows = Array.isArray(rows) ? rows : [];
  if (!els.supportOrder) return;
  const options = [];
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = t("noOrderContext");
  options.push(empty);
  state.supportOrderRows.slice(0, 12).forEach((order) => {
    const option = document.createElement("option");
    option.value = order.id || "";
    const service = order.service_label || order.service || "";
    const status = statusLabel(order);
    option.textContent = [service, order.number, status].filter(Boolean).join(" · ");
    options.push(option);
  });
  els.supportOrder.replaceChildren(...options);
}

function setSupportFormEnabled(enabled) {
  els.supportCategory.disabled = !enabled;
  if (els.supportOrder) els.supportOrder.disabled = !enabled;
  els.supportMessage.disabled = !enabled;
  els.sendSupportButton.disabled = !enabled;
  els.supportView?.classList.toggle("support-locked", !enabled);
}

async function loadSupportInfo() {
  if (!canUseTelegramAuth()) {
    els.supportStatus.textContent = t("authRequired");
    renderSupportCategories([]);
    setSupportFormEnabled(false);
    return;
  }
  setSupportFormEnabled(true);
  try {
    const payload = await api(clientActionEndpoint("support", "/mini/numbers/api/support"));
    state.clientActions = { ...state.clientActions, ...(payload.actions || {}) };
    state.supportBotUrl = payload.bot_url || state.supportBotUrl;
    renderSupportCategories(payload.categories || []);
    try {
      const orders = await api(clientActionEndpoint("orders", "/mini/numbers/api/orders"));
      renderSupportOrders(orders.orders || []);
    } catch (_error) {
      renderSupportOrders([]);
    }
    if (!els.supportStatus.textContent) els.supportStatus.textContent = "";
  } catch (error) {
    els.supportStatus.textContent = error.message || t("error");
  }
}

async function sendSupportTicket() {
  if (!canUseTelegramAuth()) {
    els.supportStatus.textContent = t("authRequired");
    setSupportFormEnabled(false);
    return;
  }
  const category = els.supportCategory.value || "numbers";
  const selectedOrderId = String(els.supportOrder?.value || "").trim();
  const selectedOrder = state.supportOrderRows.find((order) => String(order.id || "") === selectedOrderId);
  const rawMessage = els.supportMessage.value.trim();
  const context = selectedOrder
    ? [
        `Order: ${selectedOrder.id}`,
        selectedOrder.service_label ? `Service: ${selectedOrder.service_label}` : "",
        selectedOrder.number ? `Number: ${selectedOrder.number}` : "",
        selectedOrder.public_status ? `Status: ${selectedOrder.public_status}` : "",
      ].filter(Boolean).join("\n")
    : "";
  const message = [context, rawMessage].filter(Boolean).join("\n\n");
  els.sendSupportButton.disabled = true;
  try {
    const payload = await api(clientActionEndpoint("submit_support_ticket", "/mini/numbers/api/support/ticket"), {
      method: clientActionMethod("submit_support_ticket", "POST"),
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
  const requestId = ++state.priceRequestId;
  state.selectedService = selectedServiceFromInput();
  state.selectedCountry = state.mode === "voice" ? "1" : state.selectedCountry || els.countrySelect.value || "none";
  state.selectedState = state.selectedCountry === "1" ? state.selectedState || els.stateSelect.value || "none" : "none";
  saveModeSelection();
  if (!state.selectedService) {
    state.priceCheckFailed = false;
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
  state.priceCheckFailed = false;
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
      _: String(Date.now()),
    });
    const payload = await api(`${clientActionEndpoint("prices", "/mini/numbers/api/prices")}?${params.toString()}`);
    if (requestId !== state.priceRequestId) return;
    const rows = payload.providers || [];
    if (payload.ok === false || !rows.length) {
      state.priceCheckFailed = true;
      els.statusLine.textContent = payload.message || (state.mode === "voice" ? t("emptyVoice") : t("empty"));
      renderProviders([]);
      return;
    }
    state.priceCheckFailed = false;
    els.statusLine.textContent = "";
    showPriceResults();
    renderProviders(rows);
    scrollToResults();
  } catch (_error) {
    if (requestId !== state.priceRequestId) return;
    state.priceCheckFailed = true;
    els.statusLine.textContent = t("error");
    renderProviders([]);
  } finally {
    if (requestId === state.priceRequestId) {
      setLoading(false);
    }
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
  state.client = payload.client || {};
  state.tabs = Array.isArray(state.client.tabs) ? state.client.tabs : [];
  state.clientActions = state.client.actions || {};
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
  loadCountrySuggestions();
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
