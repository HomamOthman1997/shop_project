from __future__ import annotations

from html import escape

from aiohttp import web

_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Phantom Services</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      color-scheme: dark;
      --bg: #0b1020;
      --panel: rgba(255, 255, 255, 0.055);
      --panel-strong: rgba(255, 255, 255, 0.09);
      --line: rgba(255, 255, 255, 0.12);
      --text: #eef2ff;
      --muted: #a5b4fc;
      --soft: #8b95b8;
      --deep: #07131f;
      --navy: #0b1020;
      --steel: #1f3143;
      --blue: #38bdf8;
      --green: #34d399;
      --amber: #f59e0b;
      --violet: #a78bfa;
    }
    body {
      min-height: 100vh;
      background:
        linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px),
        linear-gradient(135deg, #111827 0%, #0b1020 45%, #07131f 100%);
      background-size: 44px 44px, 44px 44px, auto;
      font-family: "Segoe UI", "Tahoma", Arial, sans-serif;
      color: var(--text);
    }
    a { color: inherit; text-decoration: none; }
    .shell {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 22px 0 34px;
    }
    .nav {
      min-height: 56px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-weight: 800;
      letter-spacing: 0;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: linear-gradient(145deg, rgba(167, 139, 250, 0.26), rgba(56, 189, 248, 0.18));
      border: 1px solid var(--line);
      box-shadow: 0 0 28px rgba(56, 189, 248, 0.16);
    }
    .nav-links {
      display: flex;
      align-items: center;
      gap: 18px;
      color: #c7d2fe;
      font-size: .9rem;
      font-weight: 700;
    }
    .nav-links a { color: inherit; opacity: .86; }
    .nav-links a:hover { opacity: 1; color: var(--green); }
    .actions { display: flex; align-items: center; gap: 10px; }
    .button {
      min-height: 40px;
      padding: 0 16px;
      border-radius: 8px;
      border: 1px solid var(--line);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.92rem;
      font-weight: 700;
      white-space: nowrap;
      background: rgba(255, 255, 255, 0.045);
    }
    .button.primary {
      border-color: rgba(56, 189, 248, 0.48);
      background: linear-gradient(135deg, rgba(52, 211, 153, 0.22), rgba(56, 189, 248, 0.22));
    }
    .hero {
      min-height: 390px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(340px, 0.78fr);
      gap: clamp(28px, 4vw, 54px);
      align-items: center;
      padding: 38px 0 16px;
    }
    h1 {
      max-width: 680px;
      font-size: clamp(2rem, 4.2vw, 3.25rem);
      line-height: 1.1;
      letter-spacing: 0;
      margin-bottom: 18px;
    }
    .lead {
      max-width: 640px;
      color: #c7d2fe;
      font-size: 1rem;
      line-height: 1.76;
      margin-bottom: 20px;
    }
    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-bottom: 22px;
    }
    .notice {
      max-width: 620px;
      color: var(--soft);
      font-size: 0.9rem;
      line-height: 1.65;
    }
    .quick-panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background:
        linear-gradient(180deg, rgba(255, 255, 255, 0.075), rgba(255, 255, 255, 0.035)),
        linear-gradient(135deg, rgba(52,211,153,.08), transparent 42%);
      padding: 20px;
      box-shadow: 0 20px 70px rgba(0,0,0,.24);
    }
    .quick-title {
      font-weight: 800;
      margin-bottom: 14px;
    }
    .quick-row {
      min-height: 58px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.09);
      background: rgba(0,0,0,0.18);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      margin-top: 8px;
    }
    .quick-row span:first-child { color: #e0e7ff; font-weight: 700; }
    .quick-row span:last-child { color: var(--soft); font-size: 0.82rem; }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 20px;
      margin: 28px 0 16px;
    }
    .section-head h2 { font-size: 1.55rem; letter-spacing: 0; }
    .section-head p { color: var(--soft); max-width: 520px; line-height: 1.7; }
    .services {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
    }
    .service-card {
      min-height: 238px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 13px;
      transition: transform 0.18s ease, border-color 0.18s ease, background 0.18s ease;
    }
    .service-card:hover {
      transform: translateY(-3px);
      border-color: rgba(255,255,255,0.24);
      background: var(--panel-strong);
    }
    .icon {
      width: 48px;
      height: 48px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      font-size: 1.55rem;
      background: rgba(255,255,255,0.075);
    }
    .service-card h3 { font-size: 1.24rem; letter-spacing: 0; }
    .service-card p {
      color: var(--soft);
      line-height: 1.75;
      font-size: 0.94rem;
      flex: 1;
    }
    .card-link {
      color: var(--muted);
      font-weight: 800;
      font-size: 0.92rem;
    }
    .numbers .icon, .numbers .card-link { color: var(--violet); }
    .digital .icon, .digital .card-link { color: var(--green); }
    .cards .icon, .cards .card-link { color: var(--amber); }
    .public-grid {
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .public-item {
      border: 1px solid rgba(255,255,255,0.09);
      border-radius: 8px;
      background: rgba(255,255,255,0.04);
      padding: 14px;
      color: #cbd5e1;
      line-height: 1.7;
    }
    .public-item strong {
      display: block;
      color: var(--text);
      margin-bottom: 5px;
    }
    .footer {
      margin-top: 34px;
      padding-top: 20px;
      border-top: 1px solid rgba(255,255,255,0.08);
      color: #6f7898;
      display: flex;
      justify-content: space-between;
      gap: 14px;
      font-size: 0.86rem;
    }
    @media (max-width: 820px) {
      .shell { width: min(100% - 24px, 680px); padding-top: 14px; }
      .nav { align-items: flex-start; flex-wrap: wrap; }
      .nav-links { order: 3; width: 100%; justify-content: center; overflow-x: auto; padding: 4px 0; }
      .actions { flex-wrap: wrap; justify-content: flex-end; }
      .button { min-height: 38px; padding: 0 12px; }
      .hero { grid-template-columns: 1fr; min-height: auto; padding: 26px 0 14px; gap: 18px; }
      .services, .public-grid { grid-template-columns: 1fr; }
      .section-head { display: block; }
      .section-head h2 { margin-bottom: 8px; }
      .footer { flex-direction: column; }
    }
    @media (max-width: 430px) {
      .brand span:last-child { display: none; }
      .actions { gap: 8px; }
      .button { font-size: 0.84rem; }
      h1 { font-size: 1.9rem; line-height: 1.14; }
      .lead { font-size: .98rem; line-height: 1.75; }
      .hero-actions .button { flex: 1 1 100%; }
      .notice { display: none; }
      .quick-panel { display: none; }
      .service-card { min-height: 0; }
    }
  </style>
  <script src="/auth/static/i18n.js" defer></script>
</head>
<body>
  <main class="shell">
    <nav class="nav" aria-label="التنقل الرئيسي">
      <a class="brand" href="/">
        <span class="mark">👻</span>
        <span>Phantom Services</span>
      </a>
      <div class="nav-links" aria-label="روابط الموقع">
        <a href="/catalog">الكتالوغ</a>
        <a href="#services">الخدمات</a>
        <a href="#account">الحساب</a>
        <a href="/login">الدخول</a>
      </div>
      <div class="actions">
        <a class="button" href="/login">تسجيل الدخول</a>
        <a class="button primary" href="/register">إنشاء حساب</a>
      </div>
    </nav>

    <section class="hero">
      <div>
        <h1>استعرض الخدمات والأسعار قبل التسجيل، واشتر بعد تفعيل حسابك.</h1>
        <p class="lead">
          الموقع يجمع خدمات الأرقام والمنتجات الرقمية ضمن تجربة ويب واضحة. يمكنك تصفح الأقسام العامة والأسعار الآن،
          بينما الشراء، الطلبات، المحفظة، والدعم الداخلي تحتاج إنشاء حساب وتأكيد البريد.
        </p>
        <div class="hero-actions">
          <a class="button primary" href="/register">ابدأ بحساب جديد</a>
          <a class="button" href="/catalog">استعراض الكتالوغ</a>
        </div>
        <p class="notice">
          عند فتح أي صفحة تحتاج حسابا، سننقلك لتسجيل الدخول أو إنشاء حساب بدل عرض بيانات داخلية للزائر.
        </p>
      </div>
      <aside class="quick-panel" aria-label="ملخص الوصول">
        <p class="quick-title">ما يظهر للزائر؟</p>
        <div class="quick-row"><span>الأقسام والخدمات</span><span>متاحة للاستعراض</span></div>
        <div class="quick-row"><span>الأسعار</span><span>متاحة للاستعراض</span></div>
        <div class="quick-row"><span>الشراء</span><span>بعد الحساب والتأكيد</span></div>
        <div class="quick-row"><span>المحفظة والطلبات</span><span>محميّة بتسجيل الدخول</span></div>
      </aside>
    </section>

    <section id="services" aria-labelledby="services-title">
      <div class="section-head">
        <h2 id="services-title">الأقسام الرئيسية</h2>
        <p>الزائر يستطيع معرفة طبيعة الخدمة ورؤية الأسعار عند توفرها، أما تنفيذ الطلبات فيبقى داخل الحساب.</p>
      </div>
      <div class="services">
        <a class="service-card numbers" href="/catalog/numbers">
          <span class="icon">📱</span>
          <h3>الأرقام</h3>
          <p>أرقام مؤقتة أو للإيجار، متابعة الطلبات، واستلام الأكواد من واجهة الحساب بعد تسجيل الدخول.</p>
          <span class="card-link">استعراض قسم الأرقام ←</span>
        </a>
        <a class="service-card digital" href="/catalog/digital">
          <span class="icon">🎮</span>
          <h3>Digital Services</h3>
          <p>بطاقات ألعاب، توب أب، وباقات رقمية منظمة حسب التصنيفات، مع طلبات ومحفظة ضمن الحساب.</p>
          <span class="card-link">استعراض المنتجات الرقمية ←</span>
        </a>
        <a class="service-card cards" href="/register">
          <span class="icon">💳</span>
          <h3>تبديل البطاقات</h3>
          <p>هذا القسم يحتاج سياسة هوية ومراجعة قبل الإتاحة الكاملة، لذلك سيبقى منفصلا إلى حين جاهزيته.</p>
          <span class="card-link">إنشاء حساب للمتابعة ←</span>
        </a>
      </div>
    </section>

    <section id="account" aria-labelledby="account-title">
      <div class="section-head">
        <h2 id="account-title">بعد التسجيل</h2>
        <p>الحساب الداخلي يحتوي على المحفظة، الطلبات، الدعم، ربط Telegram الاختياري، وتأكيد الهوية عند الحاجة.</p>
      </div>
      <div class="public-grid">
        <div class="public-item"><strong>المحفظة</strong>شحن الرصيد ومتابعة الحركات من مكان واحد.</div>
        <div class="public-item"><strong>الطلبات</strong>طلبات رقمية وأرقام ضمن تبويبات منفصلة وواضحة.</div>
        <div class="public-item"><strong>الدعم</strong>مركز دعم يفرز الطلب حسب نوع المشكلة.</div>
      </div>
    </section>

    <footer class="footer">
      <span>phantom-app.net</span>
      <span>Phantom Services Website</span>
    </footer>
  </main>
</body>
</html>
"""

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

_CATALOG_SECTIONS: tuple[dict[str, object], ...] = (
    {
        "slug": "numbers",
        "title": "الأرقام",
        "subtitle": "أرقام مؤقتة وإيجار لاستلام الأكواد من خدمات عالمية.",
        "accent": "violet",
        "items": (
            ("أرقام مؤقتة", "شراء رقم لمدة قصيرة واستلام الكود داخل لوحة الحساب."),
            ("أرقام للإيجار", "إيجارات أطول للخدمات التي تحتاج متابعة متكررة."),
            ("تأكيد SMS أو Voice", "اختيار نوع الاستلام حسب توفر المزود والخدمة."),
            ("دول وخدمات عالمية", "تصفح حسب الدولة والخدمة قبل تنفيذ الطلب."),
        ),
        "categories": (
            {
                "slug": "temporary",
                "title": "أرقام مؤقتة",
                "subtitle": "أرقام قصيرة المدة لاستلام كود واحد أو جلسة تحقق واحدة.",
                "items": (
                    ("أرقام لتطبيقات التواصل", "واتساب، تيليغرام، سوشيال وخدمات تحقق حسب التوفر."),
                    ("أرقام لخدمات مالية", "استخدام مسؤول مع مزودين موثوقين وخيارات دولة واضحة."),
                    ("أرقام حسب الدولة", "اختيار الدولة والخدمة قبل إنشاء الطلب داخل الحساب."),
                ),
            },
            {
                "slug": "rental",
                "title": "أرقام للإيجار",
                "subtitle": "خيارات أطول مدة للخدمات التي تحتاج أكثر من كود.",
                "items": (
                    ("إيجار يومي", "مناسب للمتابعة القصيرة وتأكيدات متعددة خلال اليوم."),
                    ("إيجار أسبوعي", "للخدمات التي تحتاج استقراراً أطول وسجل رسائل."),
                    ("إيجار حسب الدولة", "يعرض حسب المزود والدولة بعد الدخول للحساب."),
                ),
            },
            {
                "slug": "verification",
                "title": "توثيق الحسابات",
                "subtitle": "تصنيفات تحقق SMS أو Voice حسب الخدمة والمزود.",
                "items": (
                    ("SMS", "استلام الأكواد النصية ومتابعتها من لوحة الطلبات."),
                    ("Voice", "خيارات مكالمة عند توفرها من المزود."),
                    ("مزود آخر", "إمكانية تبديل المزود من إجراءات الطلب عند الفشل."),
                ),
            },
        ),
    },
    {
        "slug": "digital",
        "aliases": ("games",),
        "title": "المنتجات الرقمية",
        "subtitle": "شدات، نقاط، بطاقات ألعاب، وباقات تطبيقات ضمن قسم المنتجات الرقمية.",
        "accent": "green",
        "items": (
            ("PUBG و BGMI", "باقات UC وخيارات تسليم حسب معرف اللاعب أو الكود."),
            ("بطاقات الألعاب", "منتجات رقمية جاهزة أو تنفيذ يدوي حسب المصدر."),
            ("تطبيقات واشتراكات", "خدمات رقمية وباقات اشتراك قابلة للإضافة للكتالوغ."),
            ("كوتات وباقات", "عرض الباقات والأسعار قبل تأكيد الطلب."),
        ),
        "categories": (
            {
                "slug": "games",
                "title": "شحن الألعاب",
                "subtitle": "شدات وأرصدة ألعاب وتوب أب حسب معرف اللاعب أو الباقة.",
                "items": (
                    ("PUBG Mobile UC", "باقات UC مع تحقق اسم اللاعب عند توفر المزود."),
                    ("BGMI و ألعاب مشابهة", "تصنيفات قابلة للتوسيع حسب مصادر المنتجات."),
                    ("بطاقات ألعاب", "أكواد أو تنفيذ يدوي حسب المخزون والمصدر."),
                ),
            },
            {
                "slug": "apps",
                "title": "التطبيقات والاشتراكات",
                "subtitle": "اشتراكات وباقات تطبيقات رقمية ضمن الكتالوغ.",
                "items": (
                    ("Streaming", "اشتراكات مشاهدة وخدمات محتوى عند توفرها."),
                    ("Productivity", "أدوات وتصميم وتطبيقات إنتاجية."),
                    ("Mobile apps", "باقات داخل تطبيقات وخدمات موبايل."),
                ),
            },
            {
                "slug": "social",
                "title": "السوشيال ميديا",
                "subtitle": "خدمات ومنتجات مرتبطة بحسابات ومنصات التواصل.",
                "items": (
                    ("Instagram", "خدمات حسابات ومنتجات رقمية مرتبطة بالحساب."),
                    ("X و YouTube", "تصنيفات قابلة للإضافة حسب المصادر المتاحة."),
                    ("توثيق وربط", "خدمات تحتاج بيانات حساب واضحة قبل التنفيذ."),
                ),
            },
            {
                "slug": "accounts",
                "title": "حسابات جاهزة",
                "subtitle": "حسابات ومنتجات رقمية تحتاج سياسة تسليم واضحة.",
                "items": (
                    ("حسابات تطبيقات", "منتجات جاهزة أو تسليم يدوي حسب المصدر."),
                    ("حسابات ألعاب", "خيارات تتطلب وصفاً وشروط استخدام قبل الشراء."),
                    ("مخزون محدود", "يعرض فقط عند توفر stock قابل للبيع."),
                ),
            },
            {
                "slug": "proxy",
                "title": "بروكسي و VPN",
                "subtitle": "منتجات اتصال وحماية وبيانات قابلة للربط لاحقاً بالمزودين.",
                "items": (
                    ("VPN", "اشتراكات وخيارات اتصال حسب المدة."),
                    ("Proxy", "بروكسيات حسب الدولة أو الاستخدام."),
                    ("بيانات و eSIM", "ربط لاحق مع منتجات السفر والبيانات."),
                ),
            },
        ),
    },
    {
        "slug": "mobile-recharge",
        "title": "شحن خطوط وباقات",
        "subtitle": "شحن أرصدة وباقات اتصالات، مع قابلية التوسع لدول ومزودين مختلفين.",
        "accent": "blue",
        "items": (
            ("أوكرانيا", "قسم مخصص لشحن الأرصدة والباقات الأوكرانية عند تفعيل المصدر."),
            ("باقات عالمية", "تقسيم حسب الدولة والمشغل ونوع الباقة."),
            ("eSIM وبيانات", "منتجات اتصال وسفر قابلة للربط مع مزودي الديجيتال."),
            ("تحقق قبل الشراء", "المستخدم يرى تفاصيل الخدمة، والشراء يتطلب حساباً ورصيداً."),
        ),
        "categories": (
            {
                "slug": "ukraine",
                "title": "شحن أوكرانيا",
                "subtitle": "قسم مخصص للأرصدة والباقات الأوكرانية عند توفر المصدر.",
                "items": (
                    ("Kyivstar", "شحن رصيد أو باقات حسب الرقم والتوفر."),
                    ("Vodafone Ukraine", "باقات ومبالغ قابلة للتوسيع داخل الكتالوغ."),
                    ("lifecell", "خيارات شحن حسب سياسة المزود."),
                ),
            },
            {
                "slug": "global",
                "title": "شحن عالمي",
                "subtitle": "تقسيم حسب الدولة والمشغل ونوع الباقة.",
                "items": (
                    ("حسب الدولة", "اختيار دولة ثم مشغل قبل الشراء."),
                    ("حسب المشغل", "عروض متغيرة حسب المصدر والتوفر."),
                    ("باقات بيانات", "تصنيفات بيانات واتصالات عند توفرها."),
                ),
            },
            {
                "slug": "esim",
                "title": "eSIM وبيانات",
                "subtitle": "منتجات سفر وبيانات رقمية قابلة للتفعيل لاحقاً.",
                "items": (
                    ("باقات سفر", "حسب الدولة والمدة وحجم البيانات."),
                    ("بيانات عالمية", "خطط متعددة الدول عند توفرها."),
                    ("تسليم رقمي", "التنفيذ والتسليم يتمان من داخل الحساب."),
                ),
            },
        ),
    },
    {
        "slug": "wallet",
        "title": "المحفظة والطلبات",
        "subtitle": "الشحن، الطلبات، الدعم، وربط Telegram بعد التسجيل.",
        "accent": "amber",
        "items": (
            ("شحن الرصيد", "رفع إثبات الدفع ومتابعة حالة طلب الشحن."),
            ("طلباتي", "أرقام وديجيتال ضمن سجل موحد وفلاتر واضحة."),
            ("الدعم المركزي", "فتح تذكرة حسب نوع المشكلة: أرقام، ديجيتال، أو رصيد."),
            ("ربط Telegram", "اختياري، ويفعل استخدام البوتات بعد إنشاء الحساب."),
        ),
    },
)

_SHOWCASE_TILES: tuple[dict[str, str], ...] = (
    {
        "title": "الألعاب",
        "subtitle": "شدات وباقات ألعاب",
        "href": "/catalog/digital/games",
        "image": "/mini/digital/static/games-rtl.png",
        "accent": "green",
    },
    {
        "title": "التطبيقات",
        "subtitle": "اشتراكات وخدمات تطبيقات",
        "href": "/catalog/digital/apps",
        "image": "/mini/digital/static/communications-rtl.png",
        "accent": "blue",
    },
    {
        "title": "الرصيد والمعاملات",
        "subtitle": "شحن خطوط وباقات",
        "href": "/catalog/mobile-recharge",
        "image": "/mini/digital/static/section-communications.jpg",
        "accent": "amber",
    },
    {
        "title": "السوشيال ميديا",
        "subtitle": "خدمات حسابات ومنصات",
        "href": "/catalog/digital/social",
        "image": "/mini/digital/static/store-cards-rtl.png",
        "accent": "violet",
    },
    {
        "title": "حسابات جاهزة",
        "subtitle": "حسابات ومنتجات رقمية",
        "href": "/catalog/digital/accounts",
        "image": "/mini/digital/static/section-store-cards.jpg",
        "accent": "green",
    },
    {
        "title": "بروكسي و VPN",
        "subtitle": "اتصال وحماية وبيانات",
        "href": "/catalog/digital/proxy",
        "image": "/mini/digital/static/numbers-rtl.png",
        "accent": "blue",
    },
    {
        "title": "الأرقام",
        "subtitle": "مؤقتة وإيجار",
        "href": "/catalog/numbers",
        "image": "/mini/digital/static/section-numbers.jpg",
        "accent": "violet",
    },
    {
        "title": "توثيق الحسابات",
        "subtitle": "أرقام وخيارات تحقق",
        "href": "/catalog/numbers",
        "image": "/mini/digital/static/section-games.jpg",
        "accent": "amber",
    },
)


def _section_by_slug(slug: str) -> dict[str, object] | None:
    normalized = str(slug or "").strip().lower()
    return next(
        (
            section
            for section in _CATALOG_SECTIONS
            if section["slug"] == normalized or normalized in set(section.get("aliases", ()))  # type: ignore[arg-type]
        ),
        None,
    )


def _category_by_slug(section: dict[str, object] | None, slug: str) -> dict[str, object] | None:
    normalized = str(slug or "").strip().lower()
    if not section or not normalized:
        return None
    return next(
        (
            category
            for category in section.get("categories", ())  # type: ignore[union-attr]
            if str(category.get("slug") or "").strip().lower() == normalized
        ),
        None,
    )


def _category_tabs(section: dict[str, object] | None, *, active_category: str = "") -> str:
    if not section:
        return ""
    categories = tuple(section.get("categories", ()))  # type: ignore[union-attr]
    if not categories:
        return ""
    section_slug = escape(str(section["slug"]))
    links = [
        f'<a class="category-tab {"active" if not active_category else ""}" href="/catalog/{section_slug}">الكل</a>'
    ]
    for category in categories:
        slug = str(category.get("slug") or "")
        title = escape(str(category.get("title") or slug))
        active = " active" if slug == active_category else ""
        links.append(f'<a class="category-tab{active}" href="/catalog/{section_slug}/{escape(slug)}">{title}</a>')
    return f'<nav class="category-tabs" aria-label="تصنيفات {escape(str(section["title"]))}">{"".join(links)}</nav>'


def _catalog_cards(*, active_slug: str = "") -> str:
    cards: list[str] = []
    for section in _CATALOG_SECTIONS:
        slug = str(section["slug"])
        title = escape(str(section["title"]))
        subtitle = escape(str(section["subtitle"]))
        accent = escape(str(section["accent"]))
        active = " active" if slug == active_slug else ""
        search_text = escape(f"{title} {subtitle}")
        cards.append(
            f"""
            <a class="catalog-card {accent}{active}" href="/catalog/{escape(slug)}" data-catalog-search="{search_text}">
              <span class="catalog-mark" aria-hidden="true"></span>
              <strong>{title}</strong>
              <span>{subtitle}</span>
            </a>
            """
        )
    return "\n".join(cards)


def _catalog_items(section: dict[str, object] | None, category: dict[str, object] | None = None) -> str:
    sections = (section,) if section else _CATALOG_SECTIONS
    rows: list[str] = []
    for group in sections:
        current = category if category and group is section else group
        title = escape(str(current["title"]))
        slug = escape(str(group["slug"]))
        accent = escape(str(group["accent"]))
        group_search = escape(f'{current["title"]} {current.get("subtitle", "")}')
        rows.append(f'<div class="product-group {accent}" data-catalog-search="{group_search}"><div class="group-head"><h2>{title}</h2><a href="/register?next=/app/services">شراء بعد التسجيل</a></div><div class="product-grid">')
        for name, description in current["items"]:  # type: ignore[index]
            item_search = escape(f"{name} {description} {current['title']}")
            rows.append(
                f"""
                <article class="product-tile" data-catalog-search="{item_search}">
                  <div>
                    <h3>{escape(str(name))}</h3>
                    <p>{escape(str(description))}</p>
                  </div>
                  <div class="tile-actions">
                    <a href="/login?next=/app/services">تسجيل الدخول</a>
                    <a class="primary" href="/register?next=/catalog/{slug}">إنشاء حساب للشراء</a>
                  </div>
                </article>
                """
            )
        rows.append("</div></div>")
    return "\n".join(rows)


def _showcase_tiles() -> str:
    tiles: list[str] = []
    for tile in _SHOWCASE_TILES:
        title = escape(tile["title"])
        subtitle = escape(tile["subtitle"])
        href = escape(tile["href"])
        image = escape(tile["image"])
        accent = escape(tile["accent"])
        search_text = escape(f"{title} {subtitle}")
        tiles.append(
            f"""
            <a class="showcase-tile {accent}" href="{href}" data-catalog-search="{search_text}">
              <span class="tile-image" style="background-image: url('{image}')"></span>
              <strong>{title}</strong>
              <small>{subtitle}</small>
            </a>
            """
        )
    return "\n".join(tiles)


def catalog_page_html(slug: str = "", *, category_slug: str = "") -> str:
    section = _section_by_slug(slug)
    if slug and not section:
        section = None
    category = _category_by_slug(section, category_slug)
    active_slug = str(section["slug"]) if section else ""
    title = str((category or section)["title"]) if (category or section) else "كتالوغ Phantom"
    subtitle = (
        str((category or section)["subtitle"])
        if (category or section)
        else "استعرض أقسام الخدمات والأسعار المتاحة قبل التسجيل. الشراء وتنفيذ الطلبات يحتاجان حساباً مؤكداً ورصيداً في المحفظة."
    )
    items_html = _catalog_items(section, category)
    cards_html = _catalog_cards(active_slug=active_slug)
    category_tabs_html = _category_tabs(section, active_category=str(category["slug"]) if category else "")
    showcase_html = _showcase_tiles()
    return f"""\
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(title)} - Phantom Services</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    :root {{
      color-scheme: dark;
      --bg: #0b1020;
      --panel: rgba(255, 255, 255, 0.058);
      --panel-strong: rgba(255, 255, 255, 0.095);
      --line: rgba(255, 255, 255, 0.12);
      --text: #eef2ff;
      --soft: #95a1c5;
      --muted: #a5b4fc;
      --green: #34d399;
      --blue: #38bdf8;
      --violet: #a78bfa;
      --amber: #f59e0b;
    }}
    body {{
      min-height: 100vh;
      background:
        linear-gradient(rgba(255,255,255,0.022) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.018) 1px, transparent 1px),
        linear-gradient(135deg, #111827 0%, #0b1020 45%, #07131f 100%);
      background-size: 44px 44px, 44px 44px, auto;
      font-family: "Segoe UI", "Tahoma", Arial, sans-serif;
      color: var(--text);
    }}
    a {{ color: inherit; text-decoration: none; }}
    .shell {{ width: min(1160px, calc(100% - 32px)); margin: 0 auto; padding: 22px 0 40px; }}
    .nav {{ min-height: 56px; display: flex; align-items: center; justify-content: space-between; gap: 14px; }}
    .brand {{ display: flex; align-items: center; gap: 10px; font-weight: 800; }}
    .mark {{ width: 38px; height: 38px; border-radius: 8px; display: grid; place-items: center; background: linear-gradient(145deg, rgba(167,139,250,.26), rgba(56,189,248,.18)); border: 1px solid var(--line); }}
    .nav-links, .actions {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .nav-links {{ color: #c7d2fe; font-weight: 700; font-size: .9rem; gap: 18px; }}
    .button {{ min-height: 40px; padding: 0 16px; border-radius: 8px; border: 1px solid var(--line); display: inline-flex; align-items: center; justify-content: center; font-weight: 800; background: rgba(255,255,255,.045); }}
    .button.primary {{ border-color: rgba(56,189,248,.48); background: linear-gradient(135deg, rgba(52,211,153,.22), rgba(56,189,248,.22)); }}
    .hero {{ padding: 34px 0 18px; display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, .45fr); gap: 28px; align-items: end; }}
    .hero h1 {{ font-size: clamp(2rem, 4vw, 3.3rem); line-height: 1.1; margin-bottom: 16px; letter-spacing: 0; }}
    .hero p {{ color: #c7d2fe; line-height: 1.8; max-width: 760px; }}
    .buy-note {{ border: 1px solid rgba(52,211,153,.22); background: rgba(52,211,153,.075); border-radius: 8px; padding: 16px; color: #d1fae5; line-height: 1.7; }}
    .search-band {{ display: grid; justify-items: center; gap: 12px; margin: 8px 0 26px; }}
    .rate-strip {{ width: min(660px, 100%); min-height: 34px; border-radius: 8px; border: 1px solid rgba(255,255,255,.07); background: rgba(0,0,0,.18); display: flex; align-items: center; justify-content: center; color: #e0e7ff; font-weight: 800; font-size: .86rem; text-align: center; padding: 0 12px; }}
    .search-box {{ width: min(760px, 100%); min-height: 48px; border-radius: 999px; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.07); display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 18px; color: #cbd5e1; }}
    .search-box input {{ width: 100%; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; direction: rtl; }}
    .search-box input::placeholder {{ color: #8b95b8; opacity: 1; }}
    .search-box span {{ color: #8b95b8; }}
    .catalog-empty {{ display: none; border: 1px solid rgba(245,158,11,.24); border-radius: 8px; background: rgba(245,158,11,.07); color: #fde68a; padding: 14px; line-height: 1.7; margin: 12px 0 22px; text-align: center; }}
    .catalog-empty.visible {{ display: block; }}
    [data-catalog-search][hidden] {{ display: none !important; }}
    .showcase-head {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 18px 0 14px; }}
    .showcase-head h2 {{ font-size: 1.35rem; }}
    .showcase-head p {{ color: var(--soft); line-height: 1.65; }}
    .showcase-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin-bottom: 28px; }}
    .showcase-tile {{ min-height: 208px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 8px; text-align: center; color: var(--text); }}
    .tile-image {{ width: 100%; aspect-ratio: 1 / .86; border-radius: 8px; border: 1px solid rgba(255,255,255,.14); background-size: cover; background-position: center; display: block; box-shadow: 0 18px 38px rgba(0,0,0,.26); transition: transform .18s ease, box-shadow .18s ease; }}
    .showcase-tile:hover .tile-image {{ transform: translateY(-4px); box-shadow: 0 22px 48px rgba(0,0,0,.34), 0 0 26px currentColor; }}
    .showcase-tile strong {{ font-size: .98rem; }}
    .showcase-tile small {{ color: #a7b0d0; font-size: .78rem; }}
    .catalog-nav {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 12px 0 26px; }}
    .catalog-card {{ min-height: 150px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: transform .18s ease, border-color .18s ease, background .18s ease; }}
    .catalog-card:hover, .catalog-card.active {{ transform: translateY(-2px); border-color: rgba(255,255,255,.28); background: var(--panel-strong); }}
    .catalog-mark {{ width: 42px; height: 8px; border-radius: 999px; background: currentColor; box-shadow: 0 0 24px currentColor; opacity: .84; }}
    .catalog-card strong {{ font-size: 1.05rem; }}
    .catalog-card span:last-child {{ color: var(--soft); line-height: 1.65; font-size: .9rem; }}
    .violet {{ color: var(--violet); }} .green {{ color: var(--green); }} .blue {{ color: var(--blue); }} .amber {{ color: var(--amber); }}
    .category-tabs {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 24px; }}
    .category-tab {{ min-height: 38px; border: 1px solid var(--line); border-radius: 8px; padding: 0 13px; display: inline-flex; align-items: center; color: #c7d2fe; background: rgba(255,255,255,.045); font-size: .9rem; font-weight: 800; }}
    .category-tab.active {{ border-color: rgba(52,211,153,.38); background: rgba(52,211,153,.11); color: #d1fae5; }}
    .product-group {{ margin-top: 20px; }}
    .group-head {{ display: flex; align-items: center; justify-content: space-between; gap: 14px; margin-bottom: 12px; }}
    .group-head h2 {{ color: var(--text); font-size: 1.35rem; }}
    .group-head a {{ color: currentColor; font-weight: 900; font-size: .9rem; }}
    .product-grid {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }}
    .product-tile {{ min-height: 178px; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,.045); padding: 16px; display: flex; flex-direction: column; justify-content: space-between; gap: 16px; }}
    .product-tile h3 {{ color: var(--text); font-size: 1.04rem; margin-bottom: 7px; }}
    .product-tile p {{ color: var(--soft); line-height: 1.75; font-size: .92rem; }}
    .tile-actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .tile-actions a {{ min-height: 36px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; display: inline-flex; align-items: center; font-weight: 800; font-size: .86rem; }}
    .tile-actions a.primary {{ border-color: rgba(56,189,248,.36); background: rgba(56,189,248,.11); color: #dff6ff; }}
    .footer {{ margin-top: 34px; padding-top: 20px; border-top: 1px solid rgba(255,255,255,.08); color: #6f7898; display: flex; justify-content: space-between; gap: 14px; font-size: .86rem; }}
    @media (max-width: 900px) {{
      .hero {{ grid-template-columns: 1fr; padding-top: 30px; }}
      .catalog-nav, .product-grid, .showcase-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    }}
    @media (max-width: 560px) {{
      .shell {{ width: min(100% - 24px, 680px); padding-top: 14px; }}
      .nav {{ align-items: flex-start; flex-wrap: wrap; }}
      .nav-links {{ order: 3; width: 100%; justify-content: center; overflow-x: auto; padding: 4px 0; gap: 14px; }}
      .actions {{ justify-content: flex-end; }}
      .button {{ min-height: 38px; padding: 0 12px; font-size: .84rem; }}
      .hero h1 {{ font-size: 1.9rem; line-height: 1.14; }}
      .search-band {{ margin-top: 4px; }}
      .rate-strip {{ font-size: .78rem; }}
      .search-box {{ min-height: 44px; border-radius: 8px; }}
      .showcase-head {{ display: block; }}
      .showcase-head h2 {{ margin-bottom: 6px; }}
      .catalog-nav, .product-grid, .showcase-grid {{ grid-template-columns: 1fr; }}
      .category-tab {{ flex: 1 1 auto; justify-content: center; }}
      .showcase-tile {{ min-height: 0; }}
      .tile-image {{ aspect-ratio: 1 / .72; }}
      .product-tile {{ min-height: 0; }}
      .tile-actions a {{ flex: 1 1 100%; justify-content: center; }}
      .footer {{ flex-direction: column; }}
    }}
  </style>
  <script src="/auth/static/i18n.js" defer></script>
</head>
<body>
  <main class="shell">
    <nav class="nav" aria-label="التنقل الرئيسي">
      <a class="brand" href="/">
        <span class="mark">👻</span>
        <span>Phantom Services</span>
      </a>
      <div class="nav-links" aria-label="روابط الموقع">
        <a href="/">الرئيسية</a>
        <a href="/catalog">الكتالوغ</a>
        <a href="/login">الدخول</a>
      </div>
      <div class="actions">
        <a class="button" href="/login">تسجيل الدخول</a>
        <a class="button primary" href="/register">إنشاء حساب</a>
      </div>
    </nav>
    <section class="hero">
      <div>
        <h1>{escape(title)}</h1>
        <p>{escape(subtitle)}</p>
      </div>
      <aside class="buy-note">
        يمكنك تصفح التصنيفات والأسعار العامة بدون حساب. عند محاولة الشراء أو فتح المحفظة والطلبات سيطلب الموقع تسجيل الدخول وتأكيد البريد.
      </aside>
    </section>
    <section class="search-band" aria-label="بحث الكتالوغ">
      <div class="rate-strip">سعر صرف تقريبي: يتم تحديث الأسعار حسب المزود والتوفر قبل تنفيذ الطلب.</div>
      <label class="search-box" for="catalog-search">
        <input id="catalog-search" type="search" autocomplete="off" placeholder="ابحث عن خدمة أو منتج..." aria-label="بحث في الكتالوغ" />
        <span aria-hidden="true">⌕</span>
      </label>
    </section>
    <section aria-labelledby="showcase-title">
      <div class="showcase-head">
        <h2 id="showcase-title">اختر القسم الذي تريده</h2>
        <p>هذه الأقسام متاحة للتصفح قبل تسجيل الدخول. تنفيذ الطلب يتم من داخل الحساب.</p>
      </div>
      <div class="showcase-grid">
        {showcase_html}
      </div>
    </section>
    <section class="catalog-nav" aria-label="أقسام الكتالوغ">
      {cards_html}
    </section>
    {category_tabs_html}
    <p class="catalog-empty" id="catalog-empty">لا توجد نتائج مطابقة. جرّب كلمة مثل ألعاب، أوكرانيا، أرقام، PUBG، أو VPN.</p>
    <section aria-label="خدمات الكتالوغ">
      {items_html}
    </section>
    <footer class="footer">
      <span>phantom-app.net</span>
      <span>Public catalog, protected checkout</span>
    </footer>
  </main>
  <script>
    (() => {{
      const input = document.getElementById("catalog-search");
      const empty = document.getElementById("catalog-empty");
      const searchable = Array.from(document.querySelectorAll("[data-catalog-search]"));
      if (!input || !empty || !searchable.length) return;
      const normalize = (value) => String(value || "").trim().toLowerCase();
      const applySearch = () => {{
        const query = normalize(input.value);
        let visibleProducts = 0;
        searchable.forEach((node) => {{
          const haystack = normalize(node.getAttribute("data-catalog-search") + " " + node.textContent);
          const isVisible = !query || haystack.includes(query);
          node.hidden = !isVisible;
          if (isVisible && node.classList.contains("product-tile")) visibleProducts += 1;
        }});
        document.querySelectorAll(".product-group").forEach((group) => {{
          const groupTiles = Array.from(group.querySelectorAll(".product-tile"));
          if (groupTiles.length) {{
            group.hidden = query ? !groupTiles.some((tile) => !tile.hidden) : false;
          }}
        }});
        const visibleShowcase = document.querySelectorAll(".showcase-tile:not([hidden])").length;
        const visibleCatalogCards = document.querySelectorAll(".catalog-card:not([hidden])").length;
        empty.classList.toggle("visible", Boolean(query) && visibleProducts === 0 && visibleShowcase === 0 && visibleCatalogCards === 0);
      }};
      input.addEventListener("input", applySearch);
      const params = new URLSearchParams(window.location.search);
      const initialQuery = params.get("q");
      if (initialQuery) {{
        input.value = initialQuery;
        applySearch();
      }}
    }})();
  </script>
</body>
</html>
"""


def landing_page_html() -> str:
    return _LANDING_HTML


async def catalog_page(request: web.Request) -> web.Response:
    """Public browseable catalog. Checkout remains inside authenticated website account."""
    slug = str(request.match_info.get("slug") or "")
    if slug and _section_by_slug(slug) is None:
        raise web.HTTPNotFound(text="catalog section not found")
    category_slug = str(request.match_info.get("category") or request.query.get("category") or "")
    return web.Response(
        text=catalog_page_html(slug, category_slug=category_slug),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )


async def landing_page(_request: web.Request) -> web.Response:
    """Public website homepage for anonymous visitors."""
    return web.Response(
        text=landing_page_html(),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )
