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
      --blue: #38bdf8;
      --green: #34d399;
      --amber: #f59e0b;
      --violet: #a78bfa;
    }
    body {
      min-height: 100vh;
      background:
        radial-gradient(ellipse at 18% 12%, rgba(56, 189, 248, 0.16), transparent 42%),
        radial-gradient(ellipse at 86% 22%, rgba(52, 211, 153, 0.12), transparent 38%),
        linear-gradient(135deg, #111029 0%, #0b1020 48%, #071629 100%);
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
      background: linear-gradient(135deg, rgba(56, 189, 248, 0.24), rgba(167, 139, 250, 0.24));
    }
    .hero {
      min-height: 380px;
      display: grid;
      grid-template-columns: minmax(0, 1.08fr) minmax(310px, 0.92fr);
      gap: 36px;
      align-items: center;
      padding: 54px 0 34px;
    }
    .eyebrow {
      color: var(--green);
      font-size: 0.86rem;
      font-weight: 800;
      margin-bottom: 12px;
    }
    h1 {
      max-width: 720px;
      font-size: clamp(2.25rem, 6vw, 4.7rem);
      line-height: 1.05;
      letter-spacing: 0;
      margin-bottom: 18px;
    }
    .lead {
      max-width: 640px;
      color: #c7d2fe;
      font-size: 1.06rem;
      line-height: 1.9;
      margin-bottom: 24px;
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
      line-height: 1.8;
    }
    .quick-panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.075), rgba(255, 255, 255, 0.035));
      padding: 18px;
    }
    .quick-title {
      font-weight: 800;
      margin-bottom: 14px;
    }
    .quick-row {
      min-height: 58px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.09);
      background: rgba(0,0,0,0.16);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px;
      margin-top: 10px;
    }
    .quick-row span:first-child { color: #e0e7ff; font-weight: 700; }
    .quick-row span:last-child { color: var(--soft); font-size: 0.82rem; }
    .section-head {
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 20px;
      margin: 18px 0 16px;
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
      .nav { align-items: flex-start; }
      .actions { flex-wrap: wrap; justify-content: flex-end; }
      .button { min-height: 38px; padding: 0 12px; }
      .hero { grid-template-columns: 1fr; min-height: auto; padding: 40px 0 24px; gap: 22px; }
      .quick-panel { order: -1; }
      .services, .public-grid { grid-template-columns: 1fr; }
      .section-head { display: block; }
      .section-head h2 { margin-bottom: 8px; }
      .footer { flex-direction: column; }
    }
    @media (max-width: 430px) {
      .brand span:last-child { display: none; }
      .actions { gap: 8px; }
      .button { font-size: 0.84rem; }
      .service-card { min-height: 0; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <nav class="nav" aria-label="التنقل الرئيسي">
      <a class="brand" href="/">
        <span class="mark">👻</span>
        <span>Phantom Services</span>
      </a>
      <div class="actions">
        <a class="button" href="/login">تسجيل الدخول</a>
        <a class="button primary" href="/register">إنشاء حساب</a>
      </div>
    </nav>

    <section class="hero">
      <div>
        <p class="eyebrow">منصة واحدة لخدمات Phantom</p>
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

    <section aria-labelledby="account-title">
      <div class="section-head">
        <h2 id="account-title">بعد التسجيل</h2>
        <p>الحساب الداخلي يحتوي على المحفظة، الطلبات، الدعم، ربط Telegram الاختياري، وتأكيد الهوية عند الحاجة.</p>
      </div>
      <div class="public-grid">
        <div class="public-item">محفظة موحدة لشحن الرصيد ومتابعة الحركات.</div>
        <div class="public-item">طلبات رقمية وأرقام ضمن تبويبات منفصلة وواضحة.</div>
        <div class="public-item">دعم مركزي يفرز الطلب حسب نوع المشكلة.</div>
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
