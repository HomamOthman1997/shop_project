from __future__ import annotations

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
          <a class="button" href="#services">استعراض الخدمات</a>
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
        <a class="service-card numbers" href="/app/numbers">
          <span class="icon">📱</span>
          <h3>الأرقام</h3>
          <p>أرقام مؤقتة أو للإيجار، متابعة الطلبات، واستلام الأكواد من واجهة الحساب بعد تسجيل الدخول.</p>
          <span class="card-link">الدخول إلى قسم الأرقام ←</span>
        </a>
        <a class="service-card digital" href="/app/digital">
          <span class="icon">🎮</span>
          <h3>Digital Services</h3>
          <p>بطاقات ألعاب، توب أب، وباقات رقمية منظمة حسب التصنيفات، مع طلبات ومحفظة ضمن الحساب.</p>
          <span class="card-link">الدخول إلى المنتجات الرقمية ←</span>
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


def landing_page_html() -> str:
    return _LANDING_HTML


async def landing_page(_request: web.Request) -> web.Response:
    """Public website homepage for anonymous visitors."""
    return web.Response(
        text=landing_page_html(),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )
