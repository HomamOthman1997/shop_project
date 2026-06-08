(() => {
  const STORAGE_KEY = "phantom_site_language";
  const SUPPORTED = new Set(["ar", "en"]);
  const originalText = new WeakMap();
  const translatedText = new WeakMap();

  const EN = {
    "تسجيل الدخول | Phantom": "Sign in | Phantom",
    "تسجيل الدخول": "Sign in",
    "إنشاء حساب": "Create account",
    "أهلاً بعودتك": "Welcome back",
    "أهلا بعودتك": "Welcome back",
    "أدخل بريدك وكلمة المرور للمتابعة.": "Enter your email and password to continue.",
    "استخدم بريدا تستطيع الوصول إليه وكلمة مرور قوية.": "Use an email you can access and a strong password.",
    "إنشاء حساب جديد": "Create a new account",
    "البريد الإلكتروني": "Email",
    "كلمة المرور": "Password",
    "إظهار": "Show",
    "إخفاء": "Hide",
    "تسجيل آمن": "Secure sign-in",
    "تأكيد بريد": "Email verification",
    "محفظة واحدة": "One wallet",
    "اختر الخدمة التي تريدها من حساب واحد آمن.": "Choose the service you need from one secure account.",
    "تأكيد البريد الإلكتروني": "Email verification",
    "أرسل كود التأكيد إلى بريدك وأدخله هنا لتفعيل واجهة الموقع والخدمات.": "Send the verification code to your email and enter it here to activate the website services.",
    "الحساب": "Account",
    "إرسال كود التأكيد": "Send verification code",
    "كود التأكيد": "Verification code",
    "تأكيد البريد": "Verify email",
    "تسجيل الخروج": "Sign out",
    "الخدمات": "Services",
    "طلباتي": "My orders",
    "الدعم": "Support",
    "حسابي": "My account",
    "تأكيد الهوية": "Identity verification",
    "لوحة الإدارة": "Admin dashboard",
    "الرصيد": "Balance",
    "اختر الخدمة": "Choose service",
    "Choose your service · اختر الخدمة التي تريدها": "Choose your service",
    "منتجات رقمية": "Digital products",
    "بطاقات الألعاب، شحن الرصيد والمزيد": "Game cards, top-ups and more",
    "أرقام": "Numbers",
    "أرقام مؤقتة وأرقام للإيجار": "Temporary and rental numbers",
    "الطلبات الرقمية": "Digital orders",
    "طلبات الأرقام": "Numbers orders",
    "حالة الهوية": "Identity status",
    "غير مقدمة": "Not submitted",
    "الخدمة": "Service",
    "رجوع": "Back",
    "كل الطلبات المرتبطة بحساب الموقع.": "All orders linked to your website account.",
    "تحديث": "Refresh",
    "لا توجد طلبات.": "No orders.",
    "إدارة الوصول والربط.": "Manage access and linked accounts.",
    "مؤكد": "Verified",
    "غير مؤكد": "Not verified",
    "تأكيد البريد": "Verify email",
    "أرسل كود تأكيد إلى بريدك لتفعيل الشراء من الموقع.": "Send a verification code to activate purchases from the website.",
    "إرسال الكود": "Send code",
    "تأكيد": "Verify",
    "غير مربوط": "Not linked",
    "مربوط": "Linked",
    "ربط Telegram": "Link Telegram",
    "فك الربط": "Unlink",
    "معرّف العميل": "Customer ID",
    "داخلي": "Internal",
    "شحن الرصيد": "Add balance",
    "جاري تحميل طرق الشحن...": "Loading recharge methods...",
    "آخر نشاط": "Recent activity",
    "لا يوجد نشاط حتى الآن.": "No activity yet.",
    "لا توجد بيانات حتى الآن.": "No data yet.",
    "تعذر تحميل نشاط الحساب حالياً.": "Could not load account activity right now.",
    "تم تحميل الطلبات المتاحة فقط. تعذر تحميل أحد الأقسام مؤقتاً.": "Only available orders were loaded. One section could not be loaded temporarily.",
    "تعذر تحميل طرق الشحن حالياً.": "Could not load recharge methods right now.",
    "تعذر تحميل طلبات الشحن حالياً.": "Could not load recharge requests right now.",
    "تعذر تحميل خيارات الدعم حالياً.": "Could not load support options right now.",
    "تعذر تحميل تذاكر الدعم حالياً.": "Could not load support tickets right now.",
    "تعذر تحميل بيانات الحساب حالياً.": "Could not load account data right now.",
    "يمكنك نسخ بيانات الدفع من هنا. إذا لم يظهر نموذج رفع الإثبات، افتح تذكرة من مركز الدعم بعد التحويل.": "You can copy payment details here. If the proof upload form does not appear, open a support ticket after the transfer.",
    "مركز الدعم": "Support center",
    "اختر القسم المرتبط بطلبك حتى يصل للفريق المناسب.": "Choose the related support type so it reaches the right team.",
    "دعم مركزي لحساب Phantom": "Central support for your Phantom account",
    "طلبات الأرقام، المنتجات الرقمية، والرصيد مجمعة في مكان واحد.": "Numbers, digital products and balance support are handled in one place.",
    "جاري تحميل خيارات الدعم...": "Loading support options...",
    "القسم": "Section",
    "الرسالة": "Message",
    "اكتب المشكلة أو رقم الطلب إن وجد": "Write the issue or order number if available",
    "فتح تذكرة دعم": "Open support ticket",
    "فتح تذكرة": "Open ticket",
    "قريباً": "Soon",
    "الدعم غير مفعّل حالياً. جرّب مرة أخرى لاحقاً أو تواصل مع الإدارة.": "Support is not enabled right now. Try again later or contact management.",
    "تذاكري": "My tickets",
    "لا توجد تذاكر دعم حتى الآن.": "No support tickets yet.",
    "جاري فتح تذكرة الدعم...": "Opening support ticket...",
    "جاري تحميل التذكرة...": "Loading ticket...",
    "لا توجد رسائل بعد.": "No messages yet.",
    "الدعم": "Support",
    "أنت": "You",
    "ردك": "Your reply",
    "اكتب ردك أو أضف تفاصيل جديدة": "Write your reply or add more details",
    "إرسال": "Send",
    "جاري إرسال الرد...": "Sending reply...",
    "هذه التذكرة مغلقة.": "This ticket is closed.",
    "تذكرة": "Ticket",
    "مفتوحة": "Open",
    "مغلقة": "Closed",
    "بانتظارك": "Waiting for you",
    "بانتظار الدعم": "Waiting for support",
    "تم الرد": "Replied",
    "محلولة": "Solved",
    "الخدمات الرقمية": "Digital services",
    "الرصيد والمدفوعات": "Balance and payments",
    "مطلوب فقط لبيع البطاقات والسحب والعمليات الحساسة.": "Required only for card selling, withdrawals and sensitive actions.",
    "الحالة الحالية": "Current status",
    "الاسم الكامل": "Full name",
    "تاريخ الميلاد": "Birth date",
    "البلد": "Country",
    "نوع الوثيقة": "Document type",
    "هوية شخصية": "National ID",
    "جواز سفر": "Passport",
    "رفع صور الوثائق سيضاف بعد تجهيز تخزين خاص ومشفّر لها.": "Document uploads will be added after secure encrypted storage is ready.",
    "إرسال طلب المراجعة": "Submit review request",
    "نظام إداري منفصل بتبويبات لكل قسم بدل صفحة واحدة طويلة.": "A dedicated admin system with tabs for each section instead of one long page.",
    "النظرة العامة": "Overview",
    "المالية": "Finance",
    "المستخدمون": "Users",
    "المزودون": "Providers",
    "الطلبات": "Orders",
    "المالية والتسعير": "Finance and pricing",
    "إعدادات مشتركة بين الموقع والبوتات وتطبق مباشرة على عمليات الشراء.": "Shared website and bot settings applied directly to purchases.",
    "التوجيه والتنبيهات": "Routing and alerts",
    "طرق شحن الرصيد": "Payment methods",
    "مراجعات شحن الرصيد": "Recharge reviews",
    "مراجعات تأكيد الهوية": "Identity reviews",
    "صندوق الدعم": "Support inbox",
    "تكامل API": "API integrations",
    "تشخيص مزودي الأرقام": "Numbers provider diagnostics",
    "إدارة البوتات والأوامر": "Bot and command management",
    "طوابير المتابعة": "Follow-up queues",
    "إدارة الطلبات الرقمية": "Digital order management",
    "تنفيذ الطلبات اليدوية وإكمالها أو استردادها.": "Run manual orders, complete them or refund them.",
    "معلقة": "Pending",
    "قيد التنفيذ": "Processing",
    "مكتملة": "Completed",
    "مستردة": "Refunded",
    "الكل": "All",
    "جاري تحميل الطلبات الرقمية...": "Loading digital orders...",
    "مراجعات استرداد الأرقام": "Numbers refund reviews",
    "إظهار المغلقة": "Show resolved",
    "خصائص الإدارة": "Admin capabilities",
    "جاري تحميل المؤشرات...": "Loading metrics...",
    "جاري تحميل الإعدادات المالية...": "Loading finance settings...",
    "جاري تحميل إعدادات التوجيه...": "Loading routing settings...",
    "جاري تحميل طرق الدفع...": "Loading payment methods...",
    "جاري تحميل مراجعات الشحن...": "Loading recharge reviews...",
    "جاري تحميل مراجعات الهوية...": "Loading identity reviews...",
    "جاري تحميل تذاكر الدعم...": "Loading support tickets...",
    "جاري تحميل أدوات التكامل...": "Loading integration tools...",
    "جاري تحميل تشخيص المزودين...": "Loading provider diagnostics...",
    "جاري تحميل أدوات البوتات...": "Loading bot tools...",
    "جاري تحميل الطوابير...": "Loading queues...",
    "جاري تحميل مراجعات الأرقام...": "Loading numbers reviews...",
    "جاري تحميل خصائص الإدارة...": "Loading admin capabilities...",
    "تعذر تحميل مؤشرات المالك.": "Could not load owner metrics.",
    "تعذر تحميل خصائص الإدارة.": "Could not load admin capabilities.",
    "تعذر تحميل طوابير المتابعة.": "Could not load follow-up queues.",
    "تعذر تحميل الطلبات الرقمية.": "Could not load digital orders.",
    "تعذر تحميل مراجعات الأرقام.": "Could not load numbers reviews.",
    "تعذر تحميل الإعدادات المالية.": "Could not load finance settings.",
    "تعذر تحميل إعدادات التوجيه.": "Could not load routing settings.",
    "تعذر تحميل طرق الدفع.": "Could not load payment methods.",
    "تعذر تحميل مراجعات الشحن.": "Could not load recharge reviews.",
    "تعذر تحميل مراجعات الهوية.": "Could not load identity reviews.",
    "تعذر تحميل تذاكر الدعم.": "Could not load support tickets.",
    "تعذر تحميل أدوات API.": "Could not load API tools.",
    "تعذر تحميل تشخيص المزودين.": "Could not load provider diagnostics.",
    "تعذر تحميل أدوات البوتات.": "Could not load bot tools.",
    "لا توجد عناصر معلقة.": "No pending items.",
    "طلب رقمي": "Digital order",
    "السعر": "Price",
    "المزود": "Provider",
    "العميل": "Customer",
    "بيانات العميل": "Customer data",
    "هذا الطلب مغلق ولا يقبل إجراءات إضافية.": "This order is closed and has no available admin actions.",
    "استلام": "Claim",
    "إكمال": "Complete",
    "استرداد": "Refund",
    "لا توجد طلبات رقمية ضمن هذا الفلتر.": "No digital orders match this filter.",
    "سيتم إعادة المبلغ إلى محفظة العميل. هل تريد تنفيذ الاسترداد؟": "Refund this order back to the customer wallet?",
    "تم تنفيذ": "Finished",
    "جاري تنفيذ": "Running",
    "البريد أو كلمة المرور غير صحيحة.": "Email or password is incorrect.",
    "انتهت مهلة الطلب، حاول مرة أخرى.": "The request timed out. Try again.",
    "تعذر إكمال الطلب": "Could not complete the request.",
    "تم إرسال كود التأكيد إلى بريدك.": "Verification code sent to your email.",
    "البريد مؤكد مسبقا.": "Email is already verified.",
    "تم تأكيد البريد.": "Email verified.",
    "الكود غير صحيح أو منتهي.": "The code is invalid or expired.",
    "تم فك ربط Telegram.": "Telegram has been unlinked.",
    "رابط Telegram غير متوفر حاليا.": "Telegram link is not available right now.",
    "منصة واحدة لخدمات Phantom": "One platform for Phantom services",
    "استعرض الخدمات والأسعار قبل التسجيل، واشتر بعد تفعيل حسابك.": "Browse services and prices before signing up, then buy after activating your account.",
    "الموقع يجمع خدمات الأرقام والمنتجات الرقمية ضمن تجربة ويب واضحة. يمكنك تصفح الأقسام العامة والأسعار الآن، بينما الشراء، الطلبات، المحفظة، والدعم الداخلي تحتاج إنشاء حساب وتأكيد البريد.": "The website brings numbers and digital products into one clear web experience. You can browse public sections and prices now, while purchases, orders, wallet and internal support require an account and verified email.",
    "ابدأ بحساب جديد": "Start with a new account",
    "استعراض الخدمات": "Browse services",
    "عند فتح أي صفحة تحتاج حسابا، سننقلك لتسجيل الدخول أو إنشاء حساب بدل عرض بيانات داخلية للزائر.": "When you open a page that requires an account, we redirect you to sign in or create an account instead of exposing private data.",
    "ما يظهر للزائر؟": "What can visitors see?",
    "الأقسام والخدمات": "Sections and services",
    "متاحة للاستعراض": "Available to browse",
    "الأسعار": "Prices",
    "الشراء": "Purchasing",
    "بعد الحساب والتأكيد": "After account and verification",
    "المحفظة والطلبات": "Wallet and orders",
    "محمية بتسجيل الدخول": "Protected by sign-in",
    "محميّة بتسجيل الدخول": "Protected by sign-in",
    "الأقسام الرئيسية": "Main sections",
    "الزائر يستطيع معرفة طبيعة الخدمة ورؤية الأسعار عند توفرها، أما تنفيذ الطلبات فيبقى داخل الحساب.": "Visitors can understand the service and see prices when available; placing orders stays inside the account.",
    "الأرقام": "Numbers",
    "أرقام مؤقتة أو للإيجار، متابعة الطلبات، واستلام الأكواد من واجهة الحساب بعد تسجيل الدخول.": "Temporary or rental numbers, order tracking and code delivery from the account interface after sign-in.",
    "الدخول إلى قسم الأرقام ←": "Open numbers section →",
    "بطاقات ألعاب، توب أب، وباقات رقمية منظمة حسب التصنيفات، مع طلبات ومحفظة ضمن الحساب.": "Game cards, top-ups and digital packages organized by categories, with orders and wallet inside the account.",
    "الدخول إلى المنتجات الرقمية ←": "Open digital products →",
    "تبديل البطاقات": "Card exchange",
    "هذا القسم يحتاج سياسة هوية ومراجعة قبل الإتاحة الكاملة، لذلك سيبقى منفصلا إلى حين جاهزيته.": "This section needs identity policy and review before full availability, so it remains separate until ready.",
    "إنشاء حساب للمتابعة ←": "Create account to continue →",
    "بعد التسجيل": "After signing up",
    "الحساب الداخلي يحتوي على المحفظة، الطلبات، الدعم، ربط Telegram الاختياري، وتأكيد الهوية عند الحاجة.": "The account includes wallet, orders, support, optional Telegram linking and identity verification when needed.",
    "محفظة موحدة لشحن الرصيد ومتابعة الحركات.": "One wallet for balance top-ups and activity tracking.",
    "طلبات رقمية وأرقام ضمن تبويبات منفصلة وواضحة.": "Digital and numbers orders in separate clear tabs.",
    "دعم مركزي يفرز الطلب حسب نوع المشكلة.": "Central support routes each request by issue type.",
  };

  function normalize(value) {
    return String(value || "").replace(/\s+/g, " ").trim();
  }

  function phrase(value) {
    const text = normalize(value);
    return EN[text] || text;
  }

  function translateValue(value, lang) {
    const raw = String(value || "");
    const leading = raw.match(/^\s*/)?.[0] || "";
    const trailing = raw.match(/\s*$/)?.[0] || "";
    const compact = normalize(raw);
    if (!compact) return raw;
    return lang === "en" ? `${leading}${phrase(compact)}${trailing}` : raw;
  }

  function currentLanguage() {
    const saved = localStorage.getItem(STORAGE_KEY);
    return SUPPORTED.has(saved) ? saved : "ar";
  }

  function setDocumentLanguage(lang) {
    document.documentElement.lang = lang;
    document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
    document.body?.classList.toggle("lang-en", lang === "en");
    document.body?.classList.toggle("lang-ar", lang === "ar");
    document.title = lang === "en" ? phrase(originalTitle) : originalTitle;
  }

  const originalTitle = document.title || "Phantom";

  function translateTextNode(node, lang) {
    const current = node.nodeValue || "";
    if (!normalize(current)) return;
    const oldOriginal = originalText.get(node);
    const oldTranslated = translatedText.get(node);
    if (!oldOriginal || (lang === "en" && normalize(current) !== normalize(oldTranslated || "") && normalize(current) !== normalize(oldOriginal))) {
      originalText.set(node, current);
    }
    const source = originalText.get(node) || current;
    const next = lang === "en" ? translateValue(source, "en") : source;
    translatedText.set(node, next);
    if (current !== next) node.nodeValue = next;
  }

  function translateAttributes(element, lang) {
    ["placeholder", "aria-label", "title"].forEach((attr) => {
      if (!element.hasAttribute(attr)) return;
      const dataKey = `i18nOriginal${attr.replace(/(^|-)([a-z])/g, (_, __, char) => char.toUpperCase())}`;
      if (!element.dataset[dataKey]) element.dataset[dataKey] = element.getAttribute(attr) || "";
      const original = element.dataset[dataKey] || "";
      const next = lang === "en" ? translateValue(original, "en") : original;
      if (element.getAttribute(attr) !== next) element.setAttribute(attr, next);
    });
  }

  function translatePage() {
    const lang = currentLanguage();
    setDocumentLanguage(lang);
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || ["SCRIPT", "STYLE", "TEXTAREA"].includes(parent.tagName)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => translateTextNode(node, lang));
    document.querySelectorAll("[placeholder], [aria-label], [title]").forEach((node) => translateAttributes(node, lang));
    const toggle = document.querySelector("[data-language-toggle]");
    if (toggle) {
      const label = lang === "ar" ? "English" : "العربية";
      if (toggle.textContent !== label) toggle.textContent = label;
    }
  }

  function setLanguage(lang) {
    const next = SUPPORTED.has(lang) ? lang : "ar";
    localStorage.setItem(STORAGE_KEY, next);
    translatePage();
    window.dispatchEvent(new CustomEvent("phantom-language-change", { detail: { language: next } }));
  }

  function installToggle() {
    if (document.querySelector("[data-language-toggle]")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "language-toggle";
    button.dataset.languageToggle = "1";
    button.addEventListener("click", () => setLanguage(currentLanguage() === "ar" ? "en" : "ar"));
    document.body.appendChild(button);
  }

  function installStyle() {
    if (document.querySelector("#phantom-i18n-style")) return;
    const style = document.createElement("style");
    style.id = "phantom-i18n-style";
    style.textContent = `
      .language-toggle {
        position: fixed;
        top: max(12px, env(safe-area-inset-top));
        inset-inline-end: 12px;
        z-index: 9999;
        min-height: 36px;
        border: 1px solid rgba(255,255,255,.14);
        border-radius: 8px;
        padding: 0 12px;
        background: rgba(9,13,27,.84);
        color: #e5edff;
        font: 800 12px/1 Inter, Tajawal, system-ui, sans-serif;
        box-shadow: 0 14px 40px rgba(0,0,0,.26);
        backdrop-filter: blur(14px);
      }
      .language-toggle:hover { border-color: rgba(56,189,248,.42); color: #fff; }
      html[dir="ltr"] body { direction: ltr; }
      html[dir="ltr"] .sidebar nav,
      html[dir="ltr"] .form-panel,
      html[dir="ltr"] .app-main,
      html[dir="ltr"] .service-card,
      html[dir="ltr"] .service-detail,
      html[dir="ltr"] .owner-review-list,
      html[dir="ltr"] .data-list { text-align: left; }
      html[dir="ltr"] .brand,
      html[dir="ltr"] .app-header,
      html[dir="ltr"] .section-head,
      html[dir="ltr"] .workspace-head,
      html[dir="ltr"] .settings-row,
      html[dir="ltr"] .owner-order-head,
      html[dir="ltr"] .owner-action-row,
      html[dir="ltr"] .quick-row,
      html[dir="ltr"] .nav { direction: ltr; }
      @media (max-width: 640px) {
        .language-toggle { top: auto; bottom: max(12px, env(safe-area-inset-bottom)); }
      }
    `;
    document.head.appendChild(style);
  }

  let scheduled = false;
  function scheduleTranslate() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      translatePage();
    });
  }

  window.PhantomI18n = {
    currentLanguage,
    setLanguage,
    translatePage,
    t(value) {
      return currentLanguage() === "en" ? phrase(value) : String(value || "");
    },
  };

  document.addEventListener("DOMContentLoaded", () => {
    installStyle();
    installToggle();
    translatePage();
    new MutationObserver(scheduleTranslate).observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["placeholder", "aria-label", "title"],
    });
  });
})();
