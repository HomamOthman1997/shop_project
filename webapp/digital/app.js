const tg = window.Telegram?.WebApp;
if (tg) {
  tg.ready();
  tg.expand();
}

const SERVICE_KEYS = [
  "games",
  "chat_apps",
  "social_services",
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
    simChooseCountry: "Choose country",
    simChooseOffer: "Choose package",
    simEnterPhone: "Phone number",
    simPhonePlaceholder: "e.g. +12025550123",
    invalidPhone: "Enter a valid phone number.",
    esimChooseCountry: "Choose eSIM country",
    esimChooseDays: "Choose duration",
    esimChooseUsage: "Choose usage level",
    esimChooseOffer: "Choose eSIM package",
    usageLow: "Less than 5 GB",
    usageMid: "5 to 10 GB",
    usageHigh: "More than 10 GB",
    numbersKindTitle: "Numbers Services",
    numbersKindHint: "Pick a popular service, then continue in the bot to choose country and live provider price.",
    numbersMore: "More numbers services",
    numbersMoreHint: "Open the full numbers flow in the bot.",
    gameFinderTitle: "Game Search",
    gameFinderHint: "Type game name to see available titles.",
    gameFinderCta: "Search Games",
    pickGame: "Select a game first.",
    pickCountry: "Select country/region",
    regions: "regions",
    region: "region",
    optionsWord: "options",
    optionWord: "option",
    offerWord: "offer",
    offersWord: "offers",
    searchGames: "Search games",
    searchSections: "Search sections",
    searchCategories: "Search categories",
    searchOptions: "Search options",
    searchOffers: "Search offers",
    browseHint: "Browse the available results below.",
    refineSearch: "Try another search term.",
    availableNow: "Available now",
    temporaryProblem: "This service is not available right now. Please try again shortly.",
    selectionUnavailable: "This offer is no longer available. Refresh the store and try again.",
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
    simChooseCountry: "اختر الدولة",
    simChooseOffer: "اختر الباقة",
    simEnterPhone: "رقم الهاتف",
    simPhonePlaceholder: "مثال: +12025550123",
    invalidPhone: "الرجاء إدخال رقم هاتف صحيح.",
    esimChooseCountry: "اختر دولة eSIM",
    esimChooseDays: "اختر المدة",
    esimChooseUsage: "اختر حجم الاستخدام",
    esimChooseOffer: "اختر باقة eSIM",
    usageLow: "أقل من 5 جيجا",
    usageMid: "من 5 إلى 10 جيجا",
    usageHigh: "أكثر من 10 جيجا",
    numbersKindTitle: "خدمات الأرقام",
    numbersKindHint: "اختر خدمة مطلوبة، ثم أكمل في البوت لاختيار الدولة والسعر الحي من المزود.",
    numbersMore: "المزيد من خدمات الأرقام",
    numbersMoreHint: "فتح فلو الأرقام الكامل داخل البوت.",
    gameFinderTitle: "بحث الألعاب",
    gameFinderHint: "اكتب اسم اللعبة لتظهر النتائج المتاحة.",
    gameFinderCta: "بحث الألعاب",
    pickGame: "اختر لعبة أولاً.",
    pickCountry: "اختر الدولة/المنطقة",
    regions: "مناطق",
    region: "منطقة",
    optionsWord: "خيارات",
    optionWord: "خيار",
    offerWord: "عرض",
    offersWord: "عروض",
    searchGames: "ابحث عن لعبة",
    searchSections: "ابحث في الأقسام",
    searchCategories: "ابحث في الفئات",
    searchOptions: "ابحث في الخيارات",
    searchOffers: "ابحث في العروض",
    browseHint: "تصفح النتائج المتاحة بالأسفل.",
    refineSearch: "جرّب كلمة بحث مختلفة.",
    availableNow: "المتاح الآن",
    temporaryProblem: "الخدمة غير متاحة حالياً. جرّب بعد قليل.",
    selectionUnavailable: "هذا العرض لم يعد متاحاً. حدّث المتجر وجرّب مرة أخرى.",
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
    playerIdWarning:
      "Make sure the Player ID is correct. If it is wrong, the top-up will be sent to the entered account and cannot be recovered.",
    priceByQuantity: "By quantity",
    creditsRange: "Credits range",
    pickOption: "Select option",
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
    playerIdWarning:
      "\u062a\u0623\u0643\u062f \u0645\u0646 \u0623\u0646 Player ID \u0635\u062d\u064a\u062d. \u0625\u0630\u0627 \u0643\u0627\u0646 \u062e\u0627\u0637\u0626\u0627\u064b \u0633\u064a\u062a\u0645 \u0627\u0644\u0634\u062d\u0646 \u0639\u0644\u0649 \u0627\u0644\u062d\u0633\u0627\u0628 \u0627\u0644\u0645\u062f\u062e\u0644 \u0648\u0644\u0627 \u064a\u0645\u0643\u0646 \u0627\u0633\u062a\u0631\u062c\u0627\u0639 \u0627\u0644\u0639\u0645\u0644\u064a\u0629.",
    priceByQuantity: "\u062d\u0633\u0628 \u0627\u0644\u0643\u0645\u064a\u0629",
    creditsRange: "\u0645\u062f\u0649 \u0627\u0644\u0643\u0631\u064a\u062f\u062a",
    pickOption: "\u0627\u062e\u062a\u0631 \u0627\u0644\u0646\u0648\u0639",
  },
};

const serviceLabelFallback = {
  games: { en: "قسم الألعاب", ar: "قسم الألعاب" },
  chat_apps: { en: "قسم تطبيقات الدردشة", ar: "قسم تطبيقات الدردشة" },
  social_services: { en: "قسم خدمات المتابعين", ar: "قسم خدمات المتابعين" },
  communications_data: { en: "قسم الاتصالات والبيانات", ar: "قسم الاتصالات والبيانات" },
  internet_providers: { en: "مزودات الإنترنت", ar: "مزودات الإنترنت" },
  paid_apps: { en: "تطبيقات مدفوعة", ar: "تطبيقات مدفوعة" },
  numbers_services: { en: "قسم خدمات الأرقام", ar: "قسم خدمات الأرقام" },
  paid_subscriptions: { en: "قسم الاشتراكات المدفوعة", ar: "قسم الاشتراكات المدفوعة" },
  store_cards: { en: "قسم بطاقات متاجر", ar: "قسم بطاقات متاجر" },
};

const serviceVisuals = {
  games: { icon: "🎮", tone: "tone-games" },
  chat_apps: { icon: "💬", tone: "tone-chat" },
  social_services: { icon: "📈", tone: "tone-chat" },
  communications_data: { icon: "📶", tone: "tone-comms" },
  internet_providers: { icon: "🌐", tone: "tone-net" },
  paid_apps: { icon: "🧰", tone: "tone-tools" },
  numbers_services: { icon: "🔢", tone: "tone-numbers" },
  paid_subscriptions: { icon: "⭐", tone: "tone-subs" },
  store_cards: { icon: "🛍️", tone: "tone-store" },
};

Object.assign(copy.ar, {
  title: "المتجر الرقمي",
  search: "بحث",
  loading: "جاري تحميل المتجر...",
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
  simKindTitle: "الاتصالات والبيانات",
  simBalance: "شحن رصيد",
  simData: "باقات بيانات",
  numbersKindTitle: "خدمات الأرقام",
  numbersKindHint: "اختر الخدمة، ثم أكمل داخل البوت لاختيار الدولة والسعر.",
  numbersMore: "كل خدمات الأرقام",
  numbersMoreHint: "فتح فلو الأرقام الكامل داخل البوت.",
  gameFinderTitle: "بحث الألعاب",
  gameFinderHint: "اكتب اسم اللعبة لتظهر النتائج المتاحة.",
  gameFinderCta: "بحث الألعاب",
  pickGame: "اختر لعبة أولاً.",
  pickCountry: "اختر الدولة/المنطقة",
  regions: "مناطق",
  region: "منطقة",
  optionsWord: "خيارات",
  optionWord: "خيار",
  offerWord: "عرض",
  offersWord: "عروض",
  searchGames: "ابحث عن لعبة",
  searchSections: "ابحث في الأقسام",
  searchCategories: "ابحث في الفئات",
  searchOptions: "ابحث في الخيارات",
  searchOffers: "ابحث في العروض",
  browseHint: "تصفح النتائج المتاحة بالأسفل.",
  refineSearch: "جرّب كلمة بحث مختلفة.",
  availableNow: "متاح الآن",
  temporaryProblem: "الخدمة غير متاحة حالياً. جرّب بعد قليل.",
  selectionUnavailable: "هذا العرض لم يعد متاحاً. حدّث المتجر وجرّب مرة أخرى.",
});

Object.assign(copy.en, {
  title: "PHanToOoM Digital Store",
});

Object.assign(copy.ar, {
  title: "متجر فانتوم الرقمي",
});

Object.assign(serviceLabelFallback, {
  games: { en: "Games", ar: "الألعاب" },
  chat_apps: { en: "Chat Apps", ar: "تطبيقات الدردشة" },
  social_services: { en: "Followers Services", ar: "خدمات المتابعين" },
  communications_data: { en: "Telecom & Data", ar: "الاتصالات والبيانات" },
  internet_providers: { en: "Internet Providers", ar: "مزودات الإنترنت" },
  paid_apps: { en: "Paid Apps", ar: "التطبيقات المدفوعة" },
  numbers_services: { en: "Numbers Services", ar: "خدمات الأرقام" },
  paid_subscriptions: { en: "Paid Subscriptions", ar: "الاشتراكات المدفوعة" },
  store_cards: { en: "Store Cards", ar: "بطاقات المتاجر" },
});

Object.assign(serviceVisuals, {
  games: { icon: "🎮", tone: "tone-games" },
  chat_apps: { icon: "💬", tone: "tone-chat" },
  social_services: { icon: "↗", tone: "tone-chat" },
  communications_data: { icon: "▣", tone: "tone-comms" },
  internet_providers: { icon: "◇", tone: "tone-net" },
  paid_apps: { icon: "◎", tone: "tone-tools" },
  numbers_services: { icon: "#", tone: "tone-numbers" },
  paid_subscriptions: { icon: "★", tone: "tone-subs" },
  store_cards: { icon: "▤", tone: "tone-store" },
});

const popularNumberServices = [
  { key: "whatsapp", label: "WhatsApp", image_url: "https://cdn.simpleicons.org/whatsapp/25D366", brand_color: "#25D366" },
  { key: "telegram", label: "Telegram", image_url: "https://cdn.simpleicons.org/telegram/26A5E4", brand_color: "#26A5E4" },
  { key: "gmail", label: "Gmail / Google", image_url: "https://cdn.simpleicons.org/gmail/EA4335", brand_color: "#EA4335" },
  { key: "anthropic", label: "Claude / Anthropic", image_url: "https://cdn.simpleicons.org/anthropic/D8DEE9", brand_color: "#D8DEE9" },
  { key: "openai", label: "OpenAI / ChatGPT", image_url: "https://cdn.simpleicons.org/openai/D8DEE9", brand_color: "#10A37F" },
  { key: "discord", label: "Discord", image_url: "https://cdn.simpleicons.org/discord/5865F2", brand_color: "#5865F2" },
  { key: "facebook", label: "Facebook", image_url: "https://cdn.simpleicons.org/facebook/0866FF", brand_color: "#0866FF" },
  { key: "instagram", label: "Instagram", image_url: "https://cdn.simpleicons.org/instagram/E4405F", brand_color: "#E4405F" },
  { key: "tiktok", label: "TikTok", image_url: "https://cdn.simpleicons.org/tiktok/F8FAFC", brand_color: "#00F2EA" },
  { key: "amazon", label: "Amazon", image_url: "https://cdn.simpleicons.org/amazon/FF9900", brand_color: "#FF9900" },
];

Object.assign(copy.ar, {
  title: "\u0645\u062a\u062c\u0631 \u0641\u0627\u0646\u062a\u0648\u0645 \u0627\u0644\u0631\u0642\u0645\u064a",
  refresh: "\u062a\u062d\u062f\u064a\u062b",
  switchLang: "EN",
  search: "\u0628\u062d\u062b",
  loading: "\u062c\u0627\u0631\u064a \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0645\u062a\u062c\u0631...",
  unavailable: "\u0627\u0644\u0645\u062a\u062c\u0631 \u0627\u0644\u0631\u0642\u0645\u064a \u063a\u064a\u0631 \u0645\u062a\u0627\u062d \u062d\u0627\u0644\u064a\u0627.",
  noResults: "\u0644\u0627 \u062a\u0648\u062c\u062f \u0646\u062a\u0627\u0626\u062c.",
  noProducts: "\u0644\u0627 \u062a\u0648\u062c\u062f \u0639\u0631\u0648\u0636.",
  sections: "\u0627\u0644\u0623\u0642\u0633\u0627\u0645",
  categories: "\u0627\u0644\u0641\u0626\u0627\u062a",
  offers: "\u0627\u0644\u0639\u0631\u0648\u0636",
  products: "\u0639\u0631\u0648\u0636",
  packages: "\u0628\u0627\u0642\u0627\u062a",
  unavailableShort: "\u063a\u064a\u0631 \u0645\u062a\u0627\u062d",
  price: "\u0627\u0644\u0633\u0639\u0631",
  stock: "\u0627\u0644\u0645\u062e\u0632\u0648\u0646",
  inStock: "\u0645\u062a\u0648\u0641\u0631",
  out: "\u063a\u064a\u0631 \u0645\u062a\u0648\u0641\u0631",
  continue: "\u0645\u062a\u0627\u0628\u0639\u0629",
  back: "\u0631\u062c\u0648\u0639",
  serverRequired: "\u064a\u062a\u0637\u0644\u0628 Server ID",
  serverOptional: "Player ID \u0641\u0642\u0637",
  selectionFailed: "\u0641\u0634\u0644 \u0625\u0631\u0633\u0627\u0644 \u0627\u0644\u0627\u062e\u062a\u064a\u0627\u0631",
  openTelegram: "\u0627\u0641\u062a\u062d \u0627\u0644\u0635\u0641\u062d\u0629 \u0645\u0646 \u0632\u0631 \u0627\u0644\u0628\u0648\u062a \u062f\u0627\u062e\u0644 \u062a\u064a\u0644\u064a\u063a\u0631\u0627\u0645.",
  loadFailed: "\u0641\u0634\u0644 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0645\u062a\u062c\u0631",
  productLoadFailed: "\u0641\u0634\u0644 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0639\u0631\u0648\u0636",
  simKindTitle: "\u0627\u0644\u0627\u062a\u0635\u0627\u0644\u0627\u062a \u0648\u0627\u0644\u0628\u064a\u0627\u0646\u0627\u062a",
  simBalance: "\u0634\u062d\u0646 \u0631\u0635\u064a\u062f",
  simData: "\u0628\u0627\u0642\u0627\u062a \u0628\u064a\u0627\u0646\u0627\u062a",
  esimDirect: "eSIM",
  simChooseCountry: "\u0627\u062e\u062a\u0631 \u0627\u0644\u062f\u0648\u0644\u0629",
  simChooseOffer: "\u0627\u062e\u062a\u0631 \u0627\u0644\u0628\u0627\u0642\u0629",
  simEnterPhone: "\u0631\u0642\u0645 \u0627\u0644\u0647\u0627\u062a\u0641",
  invalidPhone: "\u0623\u062f\u062e\u0644 \u0631\u0642\u0645 \u0647\u0627\u062a\u0641 \u0635\u062d\u064a\u062d.",
  esimChooseCountry: "\u0627\u062e\u062a\u0631 \u062f\u0648\u0644\u0629 eSIM",
  esimChooseDays: "\u0627\u062e\u062a\u0631 \u0627\u0644\u0645\u062f\u0629",
  esimChooseUsage: "\u0627\u062e\u062a\u0631 \u062d\u062c\u0645 \u0627\u0644\u0627\u0633\u062a\u062e\u062f\u0627\u0645",
  esimChooseOffer: "\u0627\u062e\u062a\u0631 \u0628\u0627\u0642\u0629 eSIM",
  usageLow: "\u0623\u0642\u0644 \u0645\u0646 5 GB",
  usageMid: "\u0645\u0646 5 \u0625\u0644\u0649 10 GB",
  usageHigh: "\u0623\u0643\u062b\u0631 \u0645\u0646 10 GB",
  numbersKindTitle: "\u062e\u062f\u0645\u0627\u062a \u0627\u0644\u0623\u0631\u0642\u0627\u0645",
  numbersKindHint: "\u0627\u062e\u062a\u0631 \u062e\u062f\u0645\u0629 \u0645\u0637\u0644\u0648\u0628\u0629\u060c \u062b\u0645 \u0623\u0643\u0645\u0644 \u062f\u0627\u062e\u0644 \u0627\u0644\u0628\u0648\u062a \u0644\u0627\u062e\u062a\u064a\u0627\u0631 \u0627\u0644\u062f\u0648\u0644\u0629 \u0648\u0627\u0644\u0633\u0639\u0631.",
  numbersMore: "\u0643\u0644 \u062e\u062f\u0645\u0627\u062a \u0627\u0644\u0623\u0631\u0642\u0627\u0645",
  numbersMoreHint: "\u0641\u062a\u062d \u0627\u0644\u0645\u0633\u0627\u0631 \u0627\u0644\u0643\u0627\u0645\u0644 \u062f\u0627\u062e\u0644 \u0627\u0644\u0628\u0648\u062a.",
  pickCountry: "\u0627\u062e\u062a\u0631 \u0627\u0644\u062f\u0648\u0644\u0629/\u0627\u0644\u0645\u0646\u0637\u0642\u0629",
  regions: "\u0645\u0646\u0627\u0637\u0642",
  region: "\u0645\u0646\u0637\u0642\u0629",
  optionsWord: "\u062e\u064a\u0627\u0631\u0627\u062a",
  optionWord: "\u062e\u064a\u0627\u0631",
  offerWord: "\u0639\u0631\u0636",
  offersWord: "\u0639\u0631\u0648\u0636",
  searchGames: "\u0627\u0628\u062d\u062b \u0639\u0646 \u0644\u0639\u0628\u0629",
  searchSections: "\u0627\u0628\u062d\u062b \u0641\u064a \u0627\u0644\u0623\u0642\u0633\u0627\u0645",
  searchCategories: "\u0627\u0628\u062d\u062b \u0641\u064a \u0627\u0644\u0641\u0626\u0627\u062a",
  searchOptions: "\u0627\u0628\u062d\u062b \u0641\u064a \u0627\u0644\u062e\u064a\u0627\u0631\u0627\u062a",
  searchOffers: "\u0627\u0628\u062d\u062b \u0641\u064a \u0627\u0644\u0639\u0631\u0648\u0636",
  browseHint: "\u062a\u0635\u0641\u062d \u0627\u0644\u0646\u062a\u0627\u0626\u062c \u0627\u0644\u0645\u062a\u0627\u062d\u0629 \u0628\u0627\u0644\u0623\u0633\u0641\u0644.",
  refineSearch: "\u062c\u0631\u0628 \u0643\u0644\u0645\u0629 \u0628\u062d\u062b \u0645\u062e\u062a\u0644\u0641\u0629.",
  availableNow: "\u0645\u062a\u0627\u062d \u0627\u0644\u0622\u0646",
  temporaryProblem: "\u0627\u0644\u062e\u062f\u0645\u0629 \u063a\u064a\u0631 \u0645\u062a\u0627\u062d\u0629 \u062d\u0627\u0644\u064a\u0627. \u062c\u0631\u0628 \u0628\u0639\u062f \u0642\u0644\u064a\u0644.",
  selectionUnavailable: "\u0647\u0630\u0627 \u0627\u0644\u0639\u0631\u0636 \u0644\u0645 \u064a\u0639\u062f \u0645\u062a\u0627\u062d\u0627. \u062d\u062f\u062b \u0627\u0644\u0645\u062a\u062c\u0631 \u0648\u062c\u0631\u0628 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649.",
});

Object.assign(extraCopy.ar, {
  all: "\u0627\u0644\u0643\u0644",
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
  pickOption: "\u0627\u062e\u062a\u0631 \u0627\u0644\u0646\u0648\u0639",
});

Object.assign(serviceLabelFallback, {
  games: { en: "Games", ar: "\u0627\u0644\u0623\u0644\u0639\u0627\u0628" },
  chat_apps: { en: "Chat Apps", ar: "\u062a\u0637\u0628\u064a\u0642\u0627\u062a \u0627\u0644\u062f\u0631\u062f\u0634\u0629" },
  social_services: { en: "Social Growth", ar: "\u062e\u062f\u0645\u0627\u062a \u0627\u0644\u062a\u0648\u0627\u0635\u0644" },
  communications_data: { en: "Telecom & Data", ar: "\u0627\u062a\u0635\u0627\u0644\u0627\u062a \u0648\u0628\u064a\u0627\u0646\u0627\u062a" },
  internet_providers: { en: "Internet", ar: "\u0627\u0644\u0625\u0646\u062a\u0631\u0646\u062a" },
  paid_apps: { en: "Paid Apps", ar: "\u062a\u0637\u0628\u064a\u0642\u0627\u062a \u0645\u062f\u0641\u0648\u0639\u0629" },
  numbers_services: { en: "Numbers", ar: "\u062e\u062f\u0645\u0627\u062a \u0627\u0644\u0623\u0631\u0642\u0627\u0645" },
  paid_subscriptions: { en: "Subscriptions", ar: "\u0627\u0634\u062a\u0631\u0627\u0643\u0627\u062a" },
  store_cards: { en: "Store Cards", ar: "\u0628\u0637\u0627\u0642\u0627\u062a \u0627\u0644\u0645\u062a\u0627\u062c\u0631" },
});

Object.assign(serviceVisuals, {
  games: { icon: "GAME", tone: "tone-games" },
  chat_apps: { icon: "CHAT", tone: "tone-chat" },
  social_services: { icon: "SOCIAL", tone: "tone-social" },
  communications_data: { icon: "SIM", tone: "tone-comms" },
  internet_providers: { icon: "NET", tone: "tone-net" },
  paid_apps: { icon: "APP", tone: "tone-tools" },
  numbers_services: { icon: "123", tone: "tone-numbers" },
  paid_subscriptions: { icon: "SUB", tone: "tone-subs" },
  store_cards: { icon: "CARD", tone: "tone-store" },
});

function iconSvg(kind) {
  const common = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
  const icons = {
    GAME: `<svg ${common}><path d="M6 11h4l1.4 2.2h1.2L14 11h4"/><path d="M6.5 7.5h11A3.5 3.5 0 0 1 21 11v4.2a2.3 2.3 0 0 1-4 1.6l-1.2-1.3H8.2L7 16.8a2.3 2.3 0 0 1-4-1.6V11a3.5 3.5 0 0 1 3.5-3.5Z"/><path d="M7.5 11.5v3"/><path d="M6 13h3"/><path d="M16.5 12h.01"/><path d="M18.5 14h.01"/></svg>`,
    CHAT: `<svg ${common}><path d="M21 11.5a7.5 7.5 0 0 1-8 7.45 8.6 8.6 0 0 1-3.4-.95L3 20l2-5.3A7.4 7.4 0 0 1 4.5 11.5a7.5 7.5 0 0 1 16.5 0Z"/><path d="M8 11h8"/><path d="M8 14h5"/></svg>`,
    SOCIAL: `<svg ${common}><path d="M4 18V9"/><path d="M10 18V6"/><path d="M16 18v-4"/><path d="M22 18H2"/><path d="m15 8 3-3 3 3"/><path d="M18 5v8"/></svg>`,
    SIM: `<svg ${common}><rect x="4" y="3" width="16" height="18" rx="3"/><path d="M9 7h6"/><path d="M8 15h8"/><path d="M8 18h5"/><path d="M8.5 11.5h.01"/><path d="M12 11.5h.01"/><path d="M15.5 11.5h.01"/></svg>`,
    NET: `<svg ${common}><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.4 2.5 3.6 5.5 3.6 9S14.4 18.5 12 21"/><path d="M12 3C9.6 5.5 8.4 8.5 8.4 12S9.6 18.5 12 21"/></svg>`,
    APP: `<svg ${common}><rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><path d="M16.5 13v7"/><path d="M13 16.5h7"/></svg>`,
    "123": `<svg ${common}><path d="M5 8h3v8"/><path d="M4 16h5"/><path d="M11 9.5A2.5 2.5 0 0 1 15.5 11c0 2.5-4.5 2.5-4.5 5h5"/><path d="M18 9h2.5l-1.8 2.4A2.2 2.2 0 1 1 17.8 15"/></svg>`,
    SUB: `<svg ${common}><path d="M12 3 14.7 8.5 21 9.4 16.5 13.8 17.6 20 12 17.1 6.4 20 7.5 13.8 3 9.4 9.3 8.5 12 3Z"/></svg>`,
    CARD: `<svg ${common}><rect x="3" y="5" width="18" height="14" rx="3"/><path d="M3 10h18"/><path d="M7 15h4"/><path d="M15 15h2"/></svg>`,
  };
  return icons[kind] || "";
}

const CATALOG_CACHE_KEY = "phantom_digital_catalog_v4";
const CATALOG_CACHE_TTL_MS = 2 * 60 * 1000;

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
  telecom: {
    section: "",
    countryCode: "",
    countryName: "",
    simOffers: [],
    esimCountry: "",
    esimDays: 0,
    esimUsage: "low",
    esimOffers: [],
  },
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
let modalCloseTimer = 0;

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
  setSearchPlaceholder();
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
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return "$0.00";
  return `$${amount.toFixed(2)}`;
}

function roundSalePrice(value) {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount <= 0) return 0;
  return Math.round(amount * 100) / 100;
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

function readCachedCatalog() {
  try {
    const raw = sessionStorage.getItem(CATALOG_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    const ts = Number(parsed?.ts || 0);
    if (!ts || Date.now() - ts > CATALOG_CACHE_TTL_MS) return null;
    if (!parsed?.catalog || typeof parsed.catalog !== "object") return null;
    return parsed.catalog;
  } catch (_err) {
    return null;
  }
}

function writeCachedCatalog(catalog) {
  try {
    sessionStorage.setItem(CATALOG_CACHE_KEY, JSON.stringify({ ts: Date.now(), catalog }));
  } catch (_err) {
    // Telegram WebView storage can be restricted; the store still works without cache.
  }
}

function renderLoadingSkeleton() {
  clear();
  setStatus(t("loading"));
  const grid = document.createElement("section");
  grid.className = "dept-grid skeleton-grid";
  for (let i = 0; i < 4; i += 1) {
    const tile = document.createElement("div");
    tile.className = "dept-tile skeleton-tile";
    const icon = document.createElement("span");
    icon.className = "skeleton-block skeleton-icon";
    const line = document.createElement("span");
    line.className = "skeleton-block skeleton-line";
    tile.append(icon, line);
    grid.append(tile);
  }
  content.append(grid);
}

function normalizeSearchText(value) {
  return String(value || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u064b-\u065f\u0670]/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function searchNeedle() {
  const q = normalizeSearchText(state.search);
  const aliases = {
    pubg: "pubg ببجي بوبجي playerunknown battlegrounds",
    ببجي: "pubg ببجي بوبجي playerunknown battlegrounds",
    coc: "clash clans كلاش اوف كلانس",
    كلاش: "clash clans كلاش اوف كلانس",
    lol: "league legends ليغ اوف ليجيند",
    ليغ: "league legends ليغ اوف ليجيند",
    cod: "call duty كول اوف ديوتي",
    فري: "free fire فري فاير",
    فريفاير: "free fire فري فاير",
  };
  return aliases[q] ? normalizeSearchText(`${q} ${aliases[q]}`) : q;
}

function matchesSearch(row, ...extraParts) {
  const q = searchNeedle();
  if (!q) return true;
  const haystack = normalizeSearchText([
    row?.name,
    row?.label,
    row?.meta_label,
    row?.group_key,
    ...(Array.isArray(row?.variants) ? row.variants.map((variant) => variant?.name) : []),
    ...extraParts,
  ].join(" "));
  return q.split(" ").every((part) => !part || haystack.includes(part));
}

function friendlyApiError(error) {
  const raw = String(error?.message || error || "").trim();
  const lower = raw.toLowerCase();
  if (lower.includes("selection unavailable") || lower.includes("bad request") || lower.includes("400")) {
    return t("selectionUnavailable");
  }
  if (
    lower.includes("500") ||
    lower.includes("502") ||
    lower.includes("application failed") ||
    lower.includes("internal server") ||
    raw.startsWith("{")
  ) {
    return t("temporaryProblem");
  }
  return raw || t("temporaryProblem");
}

function recordUsage(category) {
  const name = String(category?.name || "").trim();
  if (!name || !tg?.initData) return;
  api("/mini/digital/api/usage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, service: state.service || "" }),
  }).catch(() => {});
}

function setSearchPlaceholder() {
  let key = "searchSections";
  if (state.view === "categories") key = state.service === "games" ? "searchGames" : "searchCategories";
  else if (state.view === "subcategories") key = "searchOptions";
  else if (state.view === "items") key = "searchOffers";
  else if (state.view === "simcountries" || state.view === "esimcountries") key = "searchCategories";
  else if (state.view === "simoffers" || state.view === "esimoffers") key = "searchOffers";
  searchInput.placeholder = t(key);
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
  const response = await fetch(path, { ...options, headers, cache: "no-store" });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function clear() {
  content.replaceChildren();
}

function resetTelecomState() {
  state.telecom = {
    section: "",
    countryCode: "",
    countryName: "",
    simOffers: [],
    esimCountry: "",
    esimDays: 0,
    esimUsage: "low",
    esimOffers: [],
  };
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

function initialsFromName(name) {
  const parts = String(name || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2);
  if (!parts.length) return "?";
  return parts.map((part) => part[0]).join("").toUpperCase();
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

function contextCard(eyebrow, title, meta = "") {
  const box = document.createElement("section");
  box.className = "context-card";
  const top = document.createElement("small");
  top.className = "context-eyebrow";
  top.textContent = eyebrow;
  const strong = document.createElement("strong");
  strong.className = "context-title";
  strong.textContent = title;
  box.append(top, strong);
  if (meta) {
    const span = document.createElement("span");
    span.className = "context-meta";
    span.textContent = meta;
    box.append(span);
  }
  return box;
}

function emptyState(title, body = "") {
  const box = document.createElement("section");
  box.className = "empty-state";
  const strong = document.createElement("strong");
  strong.textContent = title;
  box.append(strong);
  if (body) {
    const text = document.createElement("p");
    text.textContent = body;
    box.append(text);
  }
  return box;
}

function card(title, meta, onClick, disabled = false, opts = {}) {
  const tone = String(opts.tone || "").trim();
  const icon = String(opts.icon || "").trim();
  const fullSpan = Boolean(opts.fullSpan);
  const el = button(`dept-tile ${tone} ${fullSpan ? "full-span" : ""}`.trim(), "", onClick, disabled);
  const head = document.createElement("div");
  head.className = "dept-head";
  if (icon) {
    const ico = document.createElement("span");
    ico.className = "dept-icon";
    const svg = iconSvg(icon);
    if (svg) {
      ico.innerHTML = svg;
    } else {
      ico.textContent = icon;
    }
    head.append(ico);
  }
  const strong = document.createElement("strong");
  strong.textContent = title;
  head.append(strong);
  el.append(head);
  if (opts.showMeta === true && meta) {
    const metaPill = document.createElement("span");
    metaPill.className = "meta-pill";
    metaPill.textContent = meta;
    el.append(metaPill);
  }
  return el;
}

function listTile(name, meta, onClick, opts = {}) {
  const imageUrl = String(opts.imageUrl || "").trim();
  const tileIcon = String(opts.icon || "").trim();
  const logoMode = Boolean(opts.logoMode);
  const storeCardMode = Boolean(opts.storeCardMode);
  const brandColor = String(opts.brandColor || "").trim();
  const hasMedia = Boolean(imageUrl) || Boolean(opts.forceMedia);
  const showMeta = opts.showMeta !== false && Boolean(meta);
  const showChevron = opts.showChevron !== false;
  const el = button(
    `tile ${hasMedia ? "tile-media tile-media-cover" : ""} ${logoMode ? "tile-logo-card" : ""} ${storeCardMode ? "tile-store-card" : ""}`.trim(),
    "",
    onClick
  );
  if (brandColor) {
    el.style.setProperty("--brand-color", brandColor);
  }
  const buildMediaFallback = () => {
    const fallback = document.createElement("div");
    fallback.className = "tile-media-fallback";
    const badge = document.createElement("div");
    badge.className = "tile-media-badge";
    badge.textContent = initialsFromName(name);
    fallback.append(badge);
    return fallback;
  };
  if (hasMedia) {
    const media = document.createElement("div");
    media.className = "tile-media-frame";
    if (imageUrl) {
      const img = document.createElement("img");
      img.className = "tile-media-image";
      img.src = imageUrl;
      img.alt = name;
      img.loading = "lazy";
      img.addEventListener("error", () => {
        media.replaceChildren(buildMediaFallback());
      });
      media.append(img);
    } else {
      media.append(buildMediaFallback());
    }
    el.append(media);
  }
  const body = document.createElement("div");
  body.className = "tile-body";
  const strong = document.createElement("strong");
  strong.textContent = name;
  body.append(strong);
  if (showMeta) {
    const span = document.createElement("span");
    span.className = "meta-pill";
    span.textContent = meta;
    body.append(span);
  }
  if (hasMedia) {
    const overlay = document.createElement("div");
    overlay.className = "tile-media-overlay";
    overlay.append(body);
    el.append(overlay);
  } else {
    if (tileIcon) {
      const iconWrap = document.createElement("span");
      iconWrap.className = "tile-icon";
      const svg = iconSvg(tileIcon);
      if (svg) {
        iconWrap.innerHTML = svg;
      } else {
        iconWrap.textContent = tileIcon;
      }
      el.append(iconWrap);
    }
    el.append(body);
  }
  if (showChevron) {
    const chev = document.createElement("b");
    chev.className = "tile-chevron";
    chev.textContent = ">";
    el.append(chev);
  }
  return el;
}

function itemRow(item) {
  const row = document.createElement("article");
  row.className = "item";
  const dynamicGiftPrice = item.kind === "gift" && Boolean(item.requires_quantity_input);
  const priceText = dynamicGiftPrice ? t("priceByQuantity") : money(item.price_usd);

  const content = document.createElement("div");
  content.className = "item-content";
  const title = document.createElement("strong");
  title.className = "item-name";
  title.textContent = String(item.name || "-");
  content.append(title);

  const price = document.createElement("span");
  price.className = "item-price-line";
  price.textContent = priceText;
  content.append(price);

  const buy = button("buy", t("continue"), () => createSelection(item));
  if (item.kind === "gift" && Number(item.stock || 0) <= 0) {
    buy.disabled = true;
    buy.textContent = t("out");
  }
  content.append(buy);
  if (dynamicGiftPrice) {
    const minQty = Number(item.za3em_qty_min || 1);
    const maxQty = Number(item.za3em_qty_max || minQty);
    const meta = document.createElement("span");
    meta.className = "meta item-hint";
    meta.textContent = `${t("creditsRange")}: ${minQty} - ${maxQty}`;
    content.append(meta);
  }
  row.append(content);

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

async function resolveVisibleServiceRows(rows) {
  return (rows || []).filter((row) => {
    if (!row?.enabled) return false;
    if (["communications_data", "numbers_services"].includes(String(row.key || ""))) return true;
    return Number(row.count || 0) > 0;
  });
}

function filteredCategories() {
  return state.categories.filter((row) => matchesSearch(row));
}

function filteredItems() {
  return state.items.filter((row) => {
    if (!isSellableItem(row)) return false;
    return matchesSearch(row);
  });
}

function isSellableItem(item) {
  if (!item) return false;
  if (String(item.kind || "") === "gift") {
    return Number(item.stock || 0) > 0;
  }
  return true;
}

function filterSellableItems(items) {
  return (items || []).filter(isSellableItem);
}

function normalizeOfferName(name) {
  return String(name || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[()]/g, "")
    .trim();
}

function isPubgTopupName(name) {
  const n = normalizeOfferName(name);
  return /^(\d+)\s*(uc|nc)?$/.test(n) || /\b(uc|nc)\b/.test(n);
}

function isTopupLikeOfferName(name) {
  const n = normalizeOfferName(name);
  return (
    /^(\d+)\s*(uc|nc|cp|vp|rp|diamonds?|gems?|coins?|cash|crystals?)?$/.test(n) ||
    /\b(uc|nc|cp|vp|rp|diamond|diamonds|gem|gems|coin|coins|cash|crystal|crystals|jade|token|tokens|voucher|vouchers|credits)\b/.test(n) ||
    /(جوهرة|جواهر|شدة|شدات|عملة|عملات|كاش|كوين|كوينز|كريستال|كريستالات|روبوت)/.test(String(name || ""))
  );
}

function filterItemsByOfferMode(items, offerMode) {
  const mode = String(offerMode || "all");
  if (mode === "topup") {
    return (items || []).filter((item) => {
      if (String(item?.kind || "") === "game") {
        return String(item?.group_key || "") === "topup";
      }
      if (String(item?.fulfillment_mode || "") === "manual_topup") {
        return String(item?.group_key || "topup") === "topup";
      }
      return isTopupLikeOfferName(item?.name);
    });
  }
  if (mode === "addons") {
    return (items || []).filter((item) => {
      if (String(item?.kind || "") === "game") {
        return String(item?.group_key || "") !== "topup";
      }
      if (String(item?.fulfillment_mode || "") === "manual_topup") {
        return String(item?.group_key || "topup") !== "topup";
      }
      return !isTopupLikeOfferName(item?.name);
    });
  }
  return items || [];
}

function mergeCheapestOffers(items) {
  const dedup = new Map();
  for (const item of items || []) {
    const key = String(item?.compare_key || "").trim() || normalizeOfferName(item?.name);
    if (!key) continue;
    const existing = dedup.get(key);
    const price = Number(item?.price_usd || 0);
    const existingPrice = Number(existing?.price_usd || 0);
    if (!existing || price < existingPrice) {
      dedup.set(key, item);
    }
  }
  return Array.from(dedup.values());
}

async function loadPubgAddonItems(parent) {
  const allItems = [];
  const variants = Array.isArray(parent?.variants) ? parent.variants : [];
  for (const variant of variants) {
    if (String(variant?.name || "") === "Turkey") {
      continue;
    }
    if (String(variant?.entry_kind || "") === "game") {
      const data = await api(`/mini/digital/api/games/${encodeURIComponent(String(variant.id || ""))}`);
      allItems.push(...filterSellableItems((data.items || []).filter((item) => String(item.group_key || "") !== "topup")));
      continue;
    }
    const sourceGiftIds = Array.isArray(variant?.gift_category_ids) ? variant.gift_category_ids.filter(Boolean) : [];
    for (const cid of sourceGiftIds) {
      const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(String(cid))}`);
      allItems.push(...filterSellableItems((data.items || []).filter((item) => !isTopupLikeOfferName(item?.name))));
    }
  }
  return mergeCheapestOffers(allItems);
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
  let canonical = normalized
    .replace(/^honou?r of kings?$/i, "Honor of Kings")
    .replace(/^honou?r of king$/i, "Honor of Kings")
    .replace(/^eafc\s*24$/i, "EAFC Mobile")
    .replace(/^eafc\s*mobile$/i, "EAFC Mobile")
    .replace(/^clash of clans.*$/i, "Clash of Clans")
    .replace(/^league of legends.*$/i, "League of Legends")
    .replace(/^legends of runeterra.*$/i, "Legends of Runeterra")
    .replace(/^teamfight tactics.*$/i, "League of Legends")
    .replace(/^pubg.*$/i, "PUBG")
    .replace(/^new state.*$/i, "PUBG")
    .replace(/^free\s*fire.*$/i, "Free Fire")
    .replace(/^freefire.*$/i, "Free Fire")
    .replace(/^blood strike.*$/i, "Blood Strike")
    .replace(/^brawel star.*$/i, "Brawl Stars")
    .replace(/^brawl stars?.*$/i, "Brawl Stars")
    .replace(/^garena\s*delta\s*force$/i, "Delta Force")
    .replace(/^delta\s*force.*$/i, "Delta Force")
    .replace(/^war robots.*$/i, "War Robots")
    .replace(/^whiteout survival.*$/i, "Whiteout Survival")
    .replace(/^yalla ludo.*$/i, "Yalla Ludo");
  const regionTokens = [
    "global",
    "usa",
    "us",
    "uk",
    "europe",
    "americas",
    "america",
    "eu",
    "sea",
    "asia",
    "mena",
    "na",
    "sa",
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
    "latam",
    "sg",
    "my",
    "sgmy",
    "ph",
    "kh",
    "vn",
    "naeu",
    "middle east",
    "germany",
    "german",
  ];
  const escaped = regionTokens.map((token) => token.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parenPattern = new RegExp(`^(.*?)\\s*\\(([^)]+)\\)\\s*$`, "i");
  const parenMatch = canonical.match(parenPattern);
  if (parenMatch) {
    const base = String(parenMatch[1] || "").trim();
    const region = String(parenMatch[2] || "").trim().toLowerCase();
    if (escaped.some((token) => new RegExp(`^${token}$`, "i").test(region))) {
      canonical = base || canonical;
    }
  }
  const suffixPattern = new RegExp(`^(.*?)(?:\\s*[-/|]\\s*|\\s+)(${escaped.join("|")})$`, "i");
  const match = canonical.match(suffixPattern);
  if (!match) return canonical;
  const base = String(match[1] || "").trim();
  return base || canonical;
}

function isStoreCardLikeName(name) {
  const n = String(name || "").toLowerCase();
  return [
    "playstation",
    "psn",
    "xbox",
    "nintendo",
    "steam",
    "itunes",
    "apple",
    "google play",
    "razer",
    "visa",
    "gift card",
    "gift cards",
    "giftcards",
  ].some((k) => n.includes(k));
}

function isLikelyGameName(name) {
  const n = String(name || "").toLowerCase().trim();
  if (!n) return false;
  if (isStoreCardLikeName(n)) return false;
  const nonGameHints = [
    "net",
    "internet",
    "provider",
    "amt",
    "unlock tool",
    "dft pro",
    "eft pro",
  ];
  if (nonGameHints.some((k) => n.includes(k))) return false;
  return true;
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

async function renderServices() {
  clear();
  resetTelecomState();
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
  setSearchPlaceholder();
  setStatus("");

  content.append(heading(t("sections")));
  const grid = document.createElement("section");
  grid.className = "dept-grid";
  const rows = await resolveVisibleServiceRows(serviceRows());
  rows.forEach((row) => {
    const visual = serviceVisuals[String(row.key || "")] || {};
    grid.append(card(label(row.label), "", () => enterService(row.key), !row.enabled, visual));
  });
  setStatus(rows.length ? "" : t("noResults"));
  content.append(grid);
}

function buildCategoriesForService(key) {
  if (!state.catalog) return [];
  const localizedMetaLabel = (selectionKind, count) => {
    const total = Math.max(0, Number(count || 0));
    if (selectionKind === "general") {
      return `${total} ${total === 1 ? t("offerWord") : t("offersWord")}`;
    }
    if (selectionKind === "option") {
      return `${total} ${total === 1 ? t("optionWord") : t("optionsWord")}`;
    }
    return `${total} ${total === 1 ? t("region") : t("regions")}`;
  };
  const serviceTree = Array.isArray(state.catalog.service_tree) ? state.catalog.service_tree : [];
  const treeNode = serviceTree.find((row) => String(row.key || "") === key);
  if (treeNode && Array.isArray(treeNode.families)) {
    const rows = treeNode.families.map((row) => ({
      id: String(row.id || ""),
      name: String(row.name || "-"),
      count: Number(row.count || (Array.isArray(row.variants) ? row.variants.length : 0) || 0),
      entry_kind: String(row.entry_kind || "group"),
      selection_kind: String(row.selection_kind || "region"),
      image_url: String(row.image_url || ""),
      game_ids: Array.isArray(row.game_ids) ? row.game_ids : [],
      gift_category_ids: Array.isArray(row.gift_category_ids) ? row.gift_category_ids : [],
      variants: Array.isArray(row.variants)
        ? row.variants.map((variant) => ({
            id: String(variant.id || ""),
            name: String(variant.name || "-"),
            entry_kind: String(variant.entry_kind || "gift"),
            variant_kind: String(variant.variant_kind || "general"),
            image_url: String(variant.image_url || ""),
            game_ids: Array.isArray(variant.game_ids) ? variant.game_ids : [],
            gift_category_ids: Array.isArray(variant.gift_category_ids) ? variant.gift_category_ids : [],
            offer_mode: String(variant.offer_mode || "all"),
            meta_label:
              String(variant.name || "") === "General"
                ? t("offers")
                : `${String(variant.variant_kind || row.selection_kind || "region") === "option" ? t("pickOption") : t("pickCountry")}: ${String(variant.name || "-")}`,
          }))
        : [],
      meta_label: localizedMetaLabel(String(row.selection_kind || "region"), Number(row.count || (Array.isArray(row.variants) ? row.variants.length : 0) || 0)),
    }));
    rows.sort((a, b) => String(a.name || "").localeCompare(String(b.name || "")));
    return rows;
  }
  return (state.catalog.gift_categories || [])
    .filter((row) => String(row.service_key || "") === key)
    .filter((row) => {
      if (key !== "store_cards") return true;
      const n = String(row.name || "").toLowerCase().trim();
      return !(
        n === "gift cards" ||
        n === "gift card" ||
        n === "بطاقات هدايا" ||
        n === "بطاقات"
      );
    })
    .map((row) => ({
      id: String(row.id || ""),
      name: String(row.name || "-"),
      count: Number(row.count || 0),
      entry_kind: "gift",
      game_ids: [],
      gift_category_ids: [String(row.id || "")],
      variants: [],
      meta_label: `${Number(row.count || 0)} ${t("products")}`,
    }));
}

function enterService(key) {
  state.service = key;
  state.search = "";
  searchInput.value = "";
  setSearchPlaceholder();
  state.itemGroup = "all";
  state.itemGroups = [];
  setStatus("");

  if (key === "communications_data") {
    renderSimKinds();
    return;
  }
  if (key === "numbers_services") {
    renderNumbersServices();
    return;
  }
  state.categories = buildCategoriesForService(key);
  renderCategories();
}

async function renderCategories() {
  clear();
  state.view = "categories";
  state.variantParent = null;
  setSearchPlaceholder();
  content.append(button("back-btn bottom-back", t("back"), renderServices));
  const serviceLabel = label(serviceRows().find((row) => row.key === state.service)?.label || serviceLabelFallback[state.service]);
  content.append(heading(serviceLabel));

  const rows = filteredCategories();
  setStatus(rows.length ? "" : t("noResults"));
  if (!rows.length) {
    content.append(emptyState(t("noResults"), t("refineSearch")));
    return;
  }

  const list = document.createElement("section");
  list.className = "category-list";
  for (let i = 0; i < rows.length; i += 2) {
    const row1 = rows[i];
    const row2 = rows[i + 1];
    list.append(
      listTile(String(row1.name || "-"), row1.meta_label || "", () =>
        openItems({
          id: String(row1.id || ""),
          name: String(row1.name || "-"),
          entry_kind: String(row1.entry_kind || "gift"),
          image_url: String(row1.image_url || ""),
          game_ids: Array.isArray(row1.game_ids) ? row1.game_ids : [],
          gift_category_ids: Array.isArray(row1.gift_category_ids) ? row1.gift_category_ids : [],
          variants: Array.isArray(row1.variants) ? row1.variants : [],
          offer_mode: String(row1.offer_mode || "all"),
        }),
        {
          imageUrl: ["games", "store_cards"].includes(state.service) ? String(row1.image_url || "") : "",
          forceMedia: ["games", "store_cards"].includes(state.service),
          storeCardMode: state.service === "store_cards",
          icon: ["games", "store_cards"].includes(state.service) ? "" : String((serviceVisuals[state.service] || {}).icon || ""),
          showMeta: false,
        }
      )
    );
    if (row2) {
      list.append(
        listTile(String(row2.name || "-"), row2.meta_label || "", () =>
          openItems({
            id: String(row2.id || ""),
            name: String(row2.name || "-"),
            entry_kind: String(row2.entry_kind || "gift"),
            image_url: String(row2.image_url || ""),
            game_ids: Array.isArray(row2.game_ids) ? row2.game_ids : [],
            gift_category_ids: Array.isArray(row2.gift_category_ids) ? row2.gift_category_ids : [],
            variants: Array.isArray(row2.variants) ? row2.variants : [],
            offer_mode: String(row2.offer_mode || "all"),
          }),
          {
            imageUrl: ["games", "store_cards"].includes(state.service) ? String(row2.image_url || "") : "",
            forceMedia: ["games", "store_cards"].includes(state.service),
            storeCardMode: state.service === "store_cards",
            icon: ["games", "store_cards"].includes(state.service) ? "" : String((serviceVisuals[state.service] || {}).icon || ""),
            showMeta: false,
          }
        )
      );
    }
  }
  content.append(list);
}

function renderVariantCategories(parent) {
  clear();
  state.view = "subcategories";
  state.variantParent = parent;
  setSearchPlaceholder();
  content.append(
    button("back-btn bottom-back", t("back"), () => {
      state.variantParent = null;
      renderCategories();
    })
  );
  content.append(heading(String(parent?.name || "-")));
  const q = state.search.trim().toLowerCase();
  const rows = (Array.isArray(parent?.variants) ? parent.variants : []).filter((row) => {
    const n = String(row?.name || "").toLowerCase();
    return !q || n.includes(q);
  });
  setStatus(rows.length ? "" : t("noResults"));
  if (!rows.length) {
    content.append(emptyState(t("noResults"), t("refineSearch")));
    return;
  }
  const list = document.createElement("section");
  list.className = "category-list";
  for (let i = 0; i < rows.length; i += 2) {
    const row1 = rows[i];
    const row2 = rows[i + 1];
    list.append(
      listTile(
        String(row1.name || "-"),
        "",
        () =>
          openItems({
            id: String(row1.id || ""),
            name: String(row1.name || "-"),
            entry_kind: String(row1.entry_kind || "gift"),
            game_ids: Array.isArray(row1.game_ids) ? row1.game_ids : [],
            gift_category_ids: Array.isArray(row1.gift_category_ids) ? row1.gift_category_ids : [],
            selection_kind: String(parent?.selection_kind || "region"),
            offer_mode: String(row1.offer_mode || "all"),
          }),
        { showMeta: false, icon: String((serviceVisuals[state.service] || {}).icon || "") }
      )
    );
    if (row2) {
      list.append(
        listTile(String(row2.name || "-"), "", () =>
          openItems({
            id: String(row2.id || ""),
            name: String(row2.name || "-"),
            entry_kind: String(row2.entry_kind || "gift"),
            game_ids: Array.isArray(row2.game_ids) ? row2.game_ids : [],
            gift_category_ids: Array.isArray(row2.gift_category_ids) ? row2.gift_category_ids : [],
            selection_kind: String(parent?.selection_kind || "region"),
            offer_mode: String(row2.offer_mode || "all"),
          }),
          { showMeta: false, icon: String((serviceVisuals[state.service] || {}).icon || "") }
        )
      );
    }
  }
  content.append(list);
}

async function resolveGroupVariants(category) {
  const variants = Array.isArray(category?.variants) ? category.variants : [];
  const resolved = [];
  for (const variant of variants) {
    try {
      let count = 0;
      if (String(variant.entry_kind || "") === "game") {
        const data = await api(`/mini/digital/api/games/${encodeURIComponent(String(variant.id || ""))}`);
        count = mergeCheapestOffers(filterSellableItems(filterItemsByOfferMode(data?.items || [], variant.offer_mode))).length;
      } else {
        const sourceGiftIds = Array.isArray(variant.gift_category_ids) ? variant.gift_category_ids.filter(Boolean) : [];
        if (sourceGiftIds.length > 0) {
          for (const cid of sourceGiftIds) {
            const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(String(cid))}?mode=${encodeURIComponent(String(variant.offer_mode || "all"))}`);
            count += mergeCheapestOffers(filterSellableItems(data?.items || [])).length;
          }
        } else if (variant.id) {
          const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(String(variant.id))}?mode=${encodeURIComponent(String(variant.offer_mode || "all"))}`);
          count = mergeCheapestOffers(filterSellableItems(data?.items || [])).length;
        }
      }
      if (count > 0) {
        resolved.push({
          ...variant,
          meta_label: `${count} ${t("offers")}`,
        });
      }
    } catch (_err) {
      // Ignore broken variant to avoid dead-end entries in UI.
    }
  }
  return resolved;
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
  recordUsage(category);
  clear();
  setStatus(t("loading"));
  if (category.entry_kind === "group" && Array.isArray(category.variants) && category.variants.length > 0) {
    const validVariants = Array.isArray(category.variants) ? category.variants : [];
    if (validVariants.length === 1) {
      await openItems({
        ...validVariants[0],
        name: category.name,
      });
      return;
    }
    state.search = "";
    searchInput.value = "";
    setSearchPlaceholder();
    const prepared = { ...category, variants: validVariants };
    setStatus(validVariants.length ? "" : t("noProducts"), !validVariants.length);
    renderVariantCategories(prepared);
    return;
  }
  state.view = "items";
  state.search = "";
  searchInput.value = "";
  setSearchPlaceholder();
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
        allItems.push(...filterSellableItems(filterItemsByOfferMode(data.items || [], category.offer_mode)));
        const mode = String(category.offer_mode || "all");
        const sourceGroups =
          mode === "topup"
            ? (data.groups || []).filter((group) => String(group?.key || "") === "topup")
            : mode === "addons"
              ? (data.groups || []).filter((group) => String(group?.key || "") !== "topup")
              : (data.groups || []);
        allGroups.push(...sourceGroups);
      }
      for (const cid of category.gift_category_ids || []) {
        const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(cid)}?mode=${encodeURIComponent(String(category.offer_mode || "all"))}`);
        const giftRows = filterSellableItems(data.items || []).map((item) => ({ ...item, group_key: String(item.group_key || "vouchers") }));
        allItems.push(...giftRows);
      }
      state.items = mergeCheapestOffers(allItems);
      const groupMap = new Map();
      (allGroups || []).forEach((g) => {
        if (g && g.key && !groupMap.has(g.key)) groupMap.set(g.key, g);
      });
      const hasVoucherRows = allItems.some((item) => String(item?.group_key || "") === "vouchers");
      if (hasVoucherRows && !groupMap.has("vouchers")) {
        groupMap.set("vouchers", { key: "vouchers", label: { en: "Vouchers", ar: "قسائم" } });
      }
      state.itemGroups = Array.from(groupMap.values());
    } else if (state.selectedCategoryKind === "game") {
      const data = await api(`/mini/digital/api/games/${encodeURIComponent(category.id)}`);
      let rows = filterSellableItems(filterItemsByOfferMode(data.items || [], category.offer_mode));
      state.items = mergeCheapestOffers(filterSellableItems(rows));
      state.itemGroups =
        String(category.offer_mode || "all") === "topup"
          ? (data.groups || []).filter((group) => String(group?.key || "") === "topup")
          : String(category.offer_mode || "all") === "addons"
            ? (data.groups || []).filter((group) => String(group?.key || "") !== "topup")
            : (data.groups || []);
    } else {
      const sourceGiftIds = Array.isArray(category.gift_category_ids) ? category.gift_category_ids.filter(Boolean) : [];
      if (sourceGiftIds.length > 0) {
        const allItems = [];
        for (const cid of sourceGiftIds) {
          const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(cid)}?mode=${encodeURIComponent(String(category.offer_mode || "all"))}`);
          allItems.push(...filterSellableItems(data.items || []));
        }
        const seen = new Set();
        state.items = allItems.filter((item) => {
          const key = `${String(item.kind || "")}:${String(item.id || "")}:${String(item.category_id || "")}`;
          if (seen.has(key)) return false;
            seen.add(key);
            return true;
          });
      } else {
          const data = await api(`/mini/digital/api/gifts/${encodeURIComponent(category.id)}?mode=${encodeURIComponent(String(category.offer_mode || "all"))}`);
          state.items = filterSellableItems(data.items || []);
        }
        if (String(state.variantParent?.name || "").toUpperCase() === "PUBG" && String(category?.name || "") === "Add-ons") {
          state.items = await loadPubgAddonItems(state.variantParent);
        }
        state.items = mergeCheapestOffers(filterSellableItems(state.items || []));
      state.itemGroups = [];
    }
    renderItems();
  } catch (err) {
    setStatus(`${t("productLoadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

function renderItems() {
  clear();
  setSearchPlaceholder();
  content.append(
    button("back-btn bottom-back", t("back"), () => {
      if (state.variantParent) {
        renderVariantCategories(state.variantParent);
        return;
      }
      renderCategories();
    })
  );
  content.append(heading(`${t("offers")} • ${state.selectedName}`));
  const rows = filteredItems();
  setStatus(rows.length ? "" : t("noProducts"));
  if (!rows.length) {
    content.append(emptyState(t("noProducts"), t("refineSearch")));
    return;
  }
  const grid = document.createElement("section");
  grid.className = "items-grid";
  for (let i = 0; i < rows.length; i += 2) {
    const row1 = rows[i];
    const row2 = rows[i + 1];
    grid.append(itemRow(row1));
    if (row2) grid.append(itemRow(row2));
  }
  content.append(grid);
}

function renderSimKinds() {
  clear();
  state.view = "simkind";
  resetTelecomState();
  state.search = "";
  searchInput.value = "";
  setSearchPlaceholder();
  setStatus("");
  content.append(button("back-btn bottom-back", t("back"), renderServices));
  content.append(heading(t("simKindTitle")));
  const grid = document.createElement("section");
  grid.className = "dept-grid";
  grid.append(
    card(t("simBalance"), t("continue"), () => {
      state.search = "";
      searchInput.value = "";
      renderSimCountries("balance");
    })
  );
  grid.append(
    card(t("simData"), t("continue"), () => {
      state.search = "";
      searchInput.value = "";
      renderSimCountries("data");
    })
  );
  grid.append(
    card(t("esimDirect"), t("continue"), () => {
      state.search = "";
      searchInput.value = "";
      renderEsimCountries();
    })
  );
  content.append(grid);
}

function telecomOfferCard({ title, subtitle = "", price = "", onContinue }) {
  const row = document.createElement("article");
  row.className = "item";
  const contentBox = document.createElement("div");
  contentBox.className = "item-content";

  const nameEl = document.createElement("strong");
  nameEl.className = "item-name";
  nameEl.textContent = String(title || "-");
  contentBox.append(nameEl);

  if (subtitle) {
    const subEl = document.createElement("span");
    subEl.className = "meta item-hint";
    subEl.textContent = subtitle;
    contentBox.append(subEl);
  }

  const priceEl = document.createElement("span");
  priceEl.className = "item-price-line";
  priceEl.textContent = String(price || "");
  contentBox.append(priceEl);

  contentBox.append(button("buy", t("continue"), onContinue));
  row.append(contentBox);
  return row;
}

async function renderSimCountries(section) {
  clear();
  state.view = "simcountries";
  state.telecom.section = String(section || "").trim().toLowerCase();
  state.telecom.countryCode = "";
  state.telecom.countryName = "";
  state.telecom.simOffers = [];
  setSearchPlaceholder();
  setStatus(t("loading"));
  content.append(button("back-btn bottom-back", t("back"), renderSimKinds));
  content.append(heading(`${t("simChooseCountry")} • ${state.telecom.section === "data" ? t("simData") : t("simBalance")}`));
  try {
    const data = await api(`/mini/digital/api/simtopup/countries?section=${encodeURIComponent(state.telecom.section)}&q=${encodeURIComponent(String(state.search || ""))}`);
    const rows = Array.isArray(data?.countries) ? data.countries : [];
    if (!rows.length) {
      setStatus(t("noResults"));
      content.append(emptyState(t("noResults"), t("refineSearch")));
      return;
    }
    setStatus("");
    const list = document.createElement("section");
    list.className = "category-list";
    rows.forEach((row) => {
      const countryName = String(row.country_name || row.country_code || "-");
      const countryCode = String(row.country_code || "").toUpperCase();
      const minPrice = Number(row.min_price_usd || 0);
      list.append(
        listTile(
          countryName,
          `${money(minPrice)}`,
          () => renderSimOffers(state.telecom.section, countryCode, countryName),
          { showMeta: true }
        )
      );
    });
    content.append(list);
  } catch (err) {
    setStatus(`${t("loadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

async function renderSimOffers(section, countryCode, countryName) {
  clear();
  state.view = "simoffers";
  state.telecom.section = String(section || "").trim().toLowerCase();
  state.telecom.countryCode = String(countryCode || "").toUpperCase();
  state.telecom.countryName = String(countryName || state.telecom.countryCode || "-");
  setSearchPlaceholder();
  setStatus(t("loading"));
  content.append(button("back-btn bottom-back", t("back"), () => renderSimCountries(state.telecom.section)));
  content.append(heading(`${t("simChooseOffer")} • ${state.telecom.countryName}`));
  try {
    const data = await api(
      `/mini/digital/api/simtopup/offers?section=${encodeURIComponent(state.telecom.section)}&country=${encodeURIComponent(state.telecom.countryCode)}`
    );
    const allRows = Array.isArray(data?.offers) ? data.offers : [];
    state.telecom.simOffers = allRows;
    const rows = allRows.filter((row) =>
      matchesSearch(
        { name: String(row?.brand_name || ""), meta: String(row?.value_label || "") },
        String(row?.country_name || ""),
        String(row?.price_usd || "")
      )
    );
    if (!rows.length) {
      setStatus(t("noResults"));
      content.append(emptyState(t("noResults"), t("refineSearch")));
      return;
    }
    setStatus("");
    const grid = document.createElement("section");
    grid.className = "items-grid";
    rows.forEach((row) => {
      grid.append(
        telecomOfferCard({
          title: String(row?.brand_name || state.telecom.countryName || "-"),
          subtitle: String(row?.value_label || ""),
          price: money(row?.price_usd || 0),
          onContinue: () => openSimPhoneModal(row),
        })
      );
    });
    content.append(grid);
  } catch (err) {
    setStatus(`${t("productLoadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

function openSimPhoneModal(offerRow) {
  const selected = offerRow && typeof offerRow === "object" ? offerRow : {};
  openInputModal({
    title: t("simEnterPhone"),
    subtitle: `${state.telecom.countryName} • ${String(selected.value_label || "")} • ${money(selected.price_usd || 0)}`,
    fields: [
      {
        name: "phone",
        label: t("simEnterPhone"),
        required: true,
        type: "text",
        placeholder: t("simPhonePlaceholder"),
      },
    ],
    onSubmit: async (values) => {
      const phone = String(values.phone || "").trim();
      const digits = phone.replace(/[^\d]/g, "");
      if (!digits || digits.length < 7) {
        setStatus(t("invalidPhone"), true);
        return;
      }
      await createServiceSelection("simtopup", {
        section: state.telecom.section,
        country_code: state.telecom.countryCode,
        phone,
        offer: dictClone(selected.offer || {}),
      });
    },
  });
}

async function renderEsimCountries() {
  clear();
  state.view = "esimcountries";
  state.telecom.esimCountry = "";
  state.telecom.esimDays = 0;
  state.telecom.esimUsage = "low";
  state.telecom.esimOffers = [];
  setSearchPlaceholder();
  setStatus(t("loading"));
  content.append(button("back-btn bottom-back", t("back"), renderSimKinds));
  content.append(heading(t("esimChooseCountry")));
  try {
    const data = await api(`/mini/digital/api/esim/countries?q=${encodeURIComponent(String(state.search || ""))}`);
    const rows = Array.isArray(data?.countries) ? data.countries : [];
    if (!rows.length) {
      setStatus(t("noResults"));
      content.append(emptyState(t("noResults"), t("refineSearch")));
      return;
    }
    setStatus("");
    const list = document.createElement("section");
    list.className = "category-list";
    rows.forEach((row) => {
      const country = String(row.country || "").trim();
      if (!country) return;
      list.append(listTile(country, "", () => renderEsimDays(country), { showMeta: false }));
    });
    content.append(list);
  } catch (err) {
    setStatus(`${t("loadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

async function renderEsimDays(country) {
  const selectedCountry = String(country || "").trim();
  if (!selectedCountry) return;
  clear();
  state.view = "esimdays";
  state.telecom.esimCountry = selectedCountry;
  state.telecom.esimDays = 0;
  state.telecom.esimOffers = [];
  setSearchPlaceholder();
  setStatus(t("loading"));
  content.append(button("back-btn bottom-back", t("back"), renderEsimCountries));
  content.append(heading(`${t("esimChooseDays")} • ${selectedCountry}`));
  try {
    const data = await api(`/mini/digital/api/esim/days?country=${encodeURIComponent(selectedCountry)}`);
    const days = (Array.isArray(data?.days) ? data.days : []).map((value) => Number(value)).filter((value) => Number.isFinite(value) && value > 0);
    if (!days.length) {
      setStatus(t("noResults"));
      content.append(emptyState(t("noResults"), t("temporaryProblem")));
      return;
    }
    setStatus("");
    const grid = document.createElement("section");
    grid.className = "dept-grid";
    days.forEach((day) => {
      grid.append(card(`${day} days`, "", () => renderEsimUsage(selectedCountry, day)));
    });
    content.append(grid);
  } catch (err) {
    setStatus(`${t("loadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

function renderEsimUsage(country, days) {
  const selectedCountry = String(country || "").trim();
  const selectedDays = Number(days || 0);
  if (!selectedCountry || !Number.isFinite(selectedDays) || selectedDays <= 0) return;
  clear();
  state.view = "esimusage";
  state.telecom.esimCountry = selectedCountry;
  state.telecom.esimDays = selectedDays;
  state.telecom.esimUsage = "low";
  setSearchPlaceholder();
  setStatus("");
  content.append(button("back-btn bottom-back", t("back"), () => renderEsimDays(selectedCountry)));
  content.append(heading(`${t("esimChooseUsage")} • ${selectedCountry}`));
  const grid = document.createElement("section");
  grid.className = "dept-grid";
  grid.append(card(t("usageLow"), "", () => renderEsimOffers(selectedCountry, selectedDays, "low")));
  grid.append(card(t("usageMid"), "", () => renderEsimOffers(selectedCountry, selectedDays, "mid")));
  grid.append(card(t("usageHigh"), "", () => renderEsimOffers(selectedCountry, selectedDays, "high")));
  content.append(grid);
}

async function renderEsimOffers(country, days, usageKey) {
  const selectedCountry = String(country || "").trim();
  const selectedDays = Number(days || 0);
  const selectedUsage = String(usageKey || "low").trim().toLowerCase();
  if (!selectedCountry || !Number.isFinite(selectedDays) || selectedDays <= 0) return;
  clear();
  state.view = "esimoffers";
  state.telecom.esimCountry = selectedCountry;
  state.telecom.esimDays = selectedDays;
  state.telecom.esimUsage = selectedUsage;
  setSearchPlaceholder();
  setStatus(t("loading"));
  content.append(button("back-btn bottom-back", t("back"), () => renderEsimUsage(selectedCountry, selectedDays)));
  content.append(heading(`${t("esimChooseOffer")} • ${selectedCountry}`));
  try {
    const data = await api(
      `/mini/digital/api/esim/offers?country=${encodeURIComponent(selectedCountry)}&days=${encodeURIComponent(String(selectedDays))}&usage=${encodeURIComponent(selectedUsage)}`
    );
    const allRows = Array.isArray(data?.offers) ? data.offers : [];
    state.telecom.esimOffers = allRows;
    const rows = allRows.filter((row) =>
      matchesSearch(
        { name: String(row?.summary || ""), meta: String(row?.country || "") },
        String(row?.price_usd || "")
      )
    );
    if (!rows.length) {
      setStatus(t("noResults"));
      content.append(emptyState(t("noResults"), t("refineSearch")));
      return;
    }
    setStatus("");
    const grid = document.createElement("section");
    grid.className = "items-grid";
    rows.forEach((row) => {
      const summary = String(row?.summary || "").replace(/\s+/g, " ").trim();
      grid.append(
        telecomOfferCard({
          title: summary || `${selectedCountry} eSIM`,
          subtitle: `${selectedDays} days`,
          price: money(row?.price_usd || 0),
          onContinue: () =>
            createServiceSelection("esim", {
              country: selectedCountry,
              days: selectedDays,
              usage_key: selectedUsage,
              offer_index: Number(row?.id || 0),
            }),
        })
      );
    });
    content.append(grid);
  } catch (err) {
    setStatus(`${t("productLoadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

function renderNumbersServices() {
  clear();
  state.view = "numbers";
  setSearchPlaceholder();
  setStatus("");
  content.append(button("back-btn bottom-back", t("back"), renderServices));
  content.append(heading(t("numbersKindTitle")));

  const intro = document.createElement("p");
  intro.className = "helper-text";
  intro.textContent = t("numbersKindHint");
  content.append(intro);

  const grid = document.createElement("section");
  grid.className = "category-list";
  for (const service of popularNumberServices) {
    grid.append(
      listTile(
        service.label,
        "",
        () =>
          createServiceSelection("numbers_services", {
            service_key: service.key,
            service_label: service.label,
          }),
        { imageUrl: service.image_url || "", forceMedia: true, logoMode: true, brandColor: service.brand_color || "", showMeta: false }
      )
    );
  }
  grid.append(card(t("numbersMore"), t("numbersMoreHint"), () => createServiceSelection("numbers_services"), false, { tone: "tone-numbers", fullSpan: true }));
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
    setStatus(`${t("selectionFailed")}: ${friendlyApiError(err)}`, true);
  }
}

function promptText(en, ar) {
  return state.lang === "ar" ? ar : en;
}

function dictClone(value) {
  if (!value || typeof value !== "object") return {};
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_err) {
    return {};
  }
}

function giftQuotePrice(item, quantity) {
  const qty = Math.max(1, Number(quantity || 1));
  const unit = Number(item?.unit_price_usd || item?.price_usd || 0);
  return roundSalePrice(unit * qty);
}

function closeInputModal() {
  if (!inputModalEl) return;
  if (modalCloseTimer) {
    window.clearTimeout(modalCloseTimer);
    modalCloseTimer = 0;
  }
  inputModalEl.classList.remove("is-open");
  inputModalEl.classList.add("is-closing");
  modalCloseTimer = window.setTimeout(() => {
    inputModalEl.classList.remove("is-closing");
    inputModalEl.classList.add("hidden");
    inputModalEl.setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    if (modalFormEl) modalFormEl.replaceChildren();
    modalCloseTimer = 0;
  }, 170);
}

function fieldLooksLikePlayerId(field) {
  const name = String(field?.name || "").toLowerCase();
  const label = String(field?.label || "").toLowerCase();
  return (
    name.includes("player_id") ||
    name.includes("playerid") ||
    name.includes("user_id") ||
    name.includes("userid") ||
    name.includes("uid") ||
    label.includes("player id") ||
    label.includes("playerid") ||
    label.includes("user id") ||
    label.includes("\u0627\u064a\u062f\u064a") ||
    label.includes("\u0627\u0644\u0627\u064a\u062f\u064a") ||
    label.includes("\u0623\u064a\u062f\u064a") ||
    label.includes("\u0627\u0644\u0623\u064a\u062f\u064a")
  );
}

function openInputModal({ title, subtitle, fields, notice, onSubmit, onChange }) {
  if (!inputModalEl || !modalFormEl || !modalTitleEl || !modalSubtitleEl) return;
  modalTitleEl.textContent = title || t("continue");
  modalSubtitleEl.textContent = subtitle || "";
  modalFormEl.replaceChildren();

  if (notice) {
    const note = document.createElement("div");
    note.className = "input-warning";
    note.textContent = notice;
    modalFormEl.append(note);
  }

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
  if (modalCloseTimer) {
    window.clearTimeout(modalCloseTimer);
    modalCloseTimer = 0;
  }
  requestAnimationFrame(() => {
    inputModalEl.classList.remove("is-closing");
    inputModalEl.classList.add("is-open");
  });
  inputModalEl.setAttribute("aria-hidden", "false");
  document.body.classList.add("modal-open");
}

async function createSelection(item) {
  if (item.kind === "gift") {
    const fields = [];
    const qtyMin = Number(item.za3em_qty_min || 1);
    const qtyMax = Number(item.za3em_qty_max || qtyMin);
    if (Boolean(item.requires_quantity_input) && qtyMax > 1) {
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
      subtitle: `${baseSubtitle} • ${t("price")}: ${money(item.price_usd)}`,
      fields,
      notice: fields.some(fieldLooksLikePlayerId) ? t("playerIdWarning") : "",
      onChange: (values) => {
        const qty = Number(values.quantity || item.display_quantity || 1);
        const quoted = giftQuotePrice(item, qty);
        if (modalSubtitleEl) {
          modalSubtitleEl.textContent = `${baseSubtitle} • ${t("price")}: ${money(quoted)}`;
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

  openInputModal({
    title: t("gamePurchaseData"),
    subtitle: `${item.name || ""} • ${t("price")}: ${money(item.price_usd)}`,
    fields: [{ name: "player_id", label: t("playerId"), type: "text", required: true }],
    notice: t("playerIdWarning"),
    onSubmit: async (values) => {
      await createServiceSelection("game", {
        kind: "game",
        game_id: item.game_id,
        item_id: item.id,
        group_key: item.group_key,
        player_id: String(values.player_id || "").trim(),
        server_id: "",
        quoted_price_usd: roundSalePrice(item.price_usd || 0),
      });
    },
  });
}

async function loadCatalog() {
  const cached = readCachedCatalog();
  if (!state.catalog && cached?.enabled) {
    state.catalog = cached;
    renderServices();
  } else if (!state.catalog) {
    renderLoadingSkeleton();
  } else {
    setStatus(t("loading"));
  }
  try {
    const catalog = await api("/mini/digital/api/catalog");
    state.catalog = catalog;
    writeCachedCatalog(catalog);
    if (!state.catalog.enabled) {
      clear();
      setStatus(t("unavailable"), true);
      return;
    }
    renderServices();
  } catch (err) {
    setStatus(`${t("loadFailed")}: ${friendlyApiError(err)}`, true);
  }
}

searchInput.addEventListener("input", () => {
  state.search = String(searchInput.value || "");
  if (!state.catalog) return;
  if (state.view === "categories") renderCategories();
  if (state.view === "subcategories") renderVariantCategories(state.variantParent);
  if (state.view === "items") renderItems();
  if (state.view === "simcountries") renderSimCountries(state.telecom.section || "balance");
  if (state.view === "simoffers") renderSimOffers(state.telecom.section, state.telecom.countryCode, state.telecom.countryName);
  if (state.view === "esimcountries") renderEsimCountries();
  if (state.view === "esimoffers") renderEsimOffers(state.telecom.esimCountry, state.telecom.esimDays, state.telecom.esimUsage);
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
    else if (state.view === "numbers") renderNumbersServices();
    else if (state.view === "simcountries") renderSimCountries(state.telecom.section || "balance");
    else if (state.view === "simoffers") renderSimOffers(state.telecom.section, state.telecom.countryCode, state.telecom.countryName);
    else if (state.view === "esimcountries") renderEsimCountries();
    else if (state.view === "esimdays") renderEsimDays(state.telecom.esimCountry);
    else if (state.view === "esimusage") renderEsimUsage(state.telecom.esimCountry, state.telecom.esimDays);
    else if (state.view === "esimoffers") renderEsimOffers(state.telecom.esimCountry, state.telecom.esimDays, state.telecom.esimUsage);
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

