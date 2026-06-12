from __future__ import annotations

from html import escape
from urllib.parse import urlencode

from aiohttp import web

from services.digital_products.custom_catalog import FAMILY_TABLE

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

_LANDING_HTML_V2 = """\
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
      --soft: #96a0c3;
      --blue: #38bdf8;
      --green: #34d399;
      --violet: #a78bfa;
      --amber: #f59e0b;
    }
    body {
      min-height: 100vh;
      background:
        linear-gradient(rgba(255,255,255,.022) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px),
        linear-gradient(135deg, #111827 0%, #0b1020 48%, #07131f 100%);
      background-size: 44px 44px, 44px 44px, auto;
      font-family: "Segoe UI", "Tahoma", Arial, sans-serif;
      color: var(--text);
    }
    a { color: inherit; text-decoration: none; }
    .app-shell {
      width: min(1860px, calc(100% - 40px));
      min-height: calc(100vh - 40px);
      margin: 20px auto;
      border: 1px solid rgba(255,255,255,.08);
      border-radius: 8px;
      display: grid;
      grid-template-columns: 330px minmax(0, 1fr);
      overflow: hidden;
      background: rgba(7, 13, 28, .78);
    }
    .sidebar {
      border-left: 1px solid rgba(255,255,255,.08);
      background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.025));
      padding: 34px 18px;
    }
    .brand {
      min-height: 66px;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      gap: 12px;
      padding: 0 14px 24px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      font-size: 1.5rem;
      font-weight: 900;
    }
    .mark {
      width: 38px;
      height: 38px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: rgba(255,255,255,.07);
    }
    .side-nav { display: grid; gap: 10px; margin-top: 32px; }
    .side-nav a {
      min-height: 52px;
      border-radius: 8px;
      padding: 0 18px;
      display: flex;
      align-items: center;
      justify-content: flex-start;
      color: #c7d2fe;
      font-weight: 900;
      font-size: 1.05rem;
    }
    .side-nav a.active { background: rgba(56, 189, 248, .15); color: white; }
    .main {
      min-width: 0;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      min-height: 166px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      padding: 32px 60px;
      background: rgba(7, 10, 24, .62);
    }
    .top-title strong {
      display: block;
      color: var(--green);
      font-size: 1.1rem;
      margin-bottom: 12px;
    }
    .top-title h1 {
      font-size: clamp(2rem, 4vw, 3rem);
      line-height: 1.05;
      letter-spacing: 0;
    }
    .auth-panel {
      min-width: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
      background: rgba(255,255,255,.045);
      display: grid;
      gap: 10px;
    }
    .auth-panel span { color: var(--soft); font-weight: 800; }
    .auth-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .button {
      min-height: 42px;
      border-radius: 8px;
      border: 1px solid var(--line);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      background: rgba(255,255,255,.045);
    }
    .button.primary {
      border-color: rgba(52, 211, 153, .38);
      background: rgba(52, 211, 153, .14);
      color: #d1fae5;
    }
    .content { padding: 36px 60px 56px; }
    .hero-card {
      min-height: 186px;
      border: 1px solid rgba(56, 189, 248, .18);
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(167,139,250,.14), rgba(56,189,248,.08));
      display: grid;
      place-items: center;
      text-align: center;
      margin-bottom: 34px;
      padding: 22px;
    }
    .hero-card .ghost { font-size: 3rem; margin-bottom: 12px; }
    .hero-card h2 {
      font-size: clamp(2.2rem, 5vw, 3.7rem);
      line-height: 1;
      color: transparent;
      background: linear-gradient(90deg, var(--violet), var(--blue));
      -webkit-background-clip: text;
      background-clip: text;
      margin-bottom: 12px;
    }
    .hero-card p { color: #b7c0ff; font-size: 1.05rem; }
    .service-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 22px;
    }
    .service-card {
      min-height: 250px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255,255,255,.035);
      padding: 26px;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      justify-content: space-between;
      transition: transform .18s ease, border-color .18s ease, background .18s ease;
    }
    .service-card:hover {
      transform: translateY(-3px);
      border-color: rgba(52, 211, 153, .34);
      background: rgba(255,255,255,.06);
    }
    .icon {
      width: 64px;
      height: 64px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: rgba(255,255,255,.075);
      font-size: 1.9rem;
      margin-bottom: 24px;
    }
    .service-card h3 { font-size: 1.65rem; margin-bottom: 8px; color: var(--green); }
    .service-card small { display: block; color: #818cf8; font-weight: 900; letter-spacing: 1.8px; margin-bottom: 24px; }
    .service-card p { color: #b7c0ff; line-height: 1.75; }
    .arrow { color: var(--green); font-size: 1.3rem; }
    .service-card.blue h3, .service-card.blue .arrow { color: var(--blue); }
    .service-card.violet h3, .service-card.violet .arrow { color: var(--violet); }
    .service-card.amber h3, .service-card.amber .arrow { color: var(--amber); }
    @media (max-width: 1020px) {
      .app-shell { grid-template-columns: 1fr; }
      .sidebar { order: 2; border-left: 0; border-top: 1px solid rgba(255,255,255,.08); }
      .side-nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .topbar, .content { padding-left: 24px; padding-right: 24px; }
      .service-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .app-shell { width: min(100% - 20px, 560px); margin: 10px auto; }
      .topbar { display: grid; min-height: 0; padding: 22px 16px; }
      .auth-panel { min-width: 0; }
      .content { padding: 20px 16px 28px; }
      .hero-card { min-height: 150px; }
      .service-grid, .side-nav { grid-template-columns: 1fr; }
      .service-card { min-height: 210px; }
      .auth-actions { grid-template-columns: 1fr; }
    }
  </style>
  <script src="/auth/static/i18n.js" defer></script>
</head>
<body>
  <main class="app-shell">
    <aside class="sidebar" aria-label="التنقل">
      <a class="brand" href="/">
        <span>Phantom</span>
        <span class="mark">👻</span>
      </a>
      <nav class="side-nav">
        <a class="active" href="/catalog">الخدمات</a>
        <a href="/login">طلباتي</a>
        <a href="/login">شحن الرصيد</a>
        <a href="/login">الدعم</a>
        <a href="/login">حسابي</a>
        <a href="/login">تأكيد الهوية</a>
      </nav>
    </aside>
    <section class="main">
      <header class="topbar">
        <div class="auth-panel" aria-label="الدخول إلى الحساب">
          <span>ابدأ الآن</span>
          <div class="auth-actions">
            <a class="button primary" href="/register">تسجيل حساب جديد</a>
            <a class="button" href="/login">تسجيل الدخول</a>
          </div>
        </div>
        <div class="top-title">
          <strong>Phantom Services</strong>
          <h1>الخدمات</h1>
        </div>
      </header>
      <div class="content">
        <section class="hero-card">
          <div>
            <div class="ghost">👻</div>
            <h2>Phantom Services</h2>
            <p>اختر القسم الذي تريده، التصفح متاح بدون حساب والشراء بعد التسجيل وشحن الرصيد.</p>
          </div>
        </section>
        <section class="service-grid" aria-label="الأقسام الرئيسية">
          <a class="service-card" href="/catalog/games">
            <div><span class="icon">🎮</span><h3>الألعاب</h3><small>GAME TOP-UPS</small><p>شدات، بطاقات ألعاب، وتوب أب للألعاب.</p></div>
            <span class="arrow">←</span>
          </a>
          <a class="service-card blue" href="/catalog/chat-apps">
            <div><span class="icon">💬</span><h3>تطبيقات دردشة</h3><small>CHAT APPS</small><p>خدمات Telegram وWhatsApp ومنصات التواصل.</p></div>
            <span class="arrow">←</span>
          </a>
          <a class="service-card violet" href="/catalog/subscriptions">
            <div><span class="icon">💎</span><h3>اشتراكات برامج</h3><small>SUBSCRIPTIONS</small><p>Adobe، Telegram Premium، وخدمات البرامج.</p></div>
            <span class="arrow">←</span>
          </a>
          <a class="service-card amber" href="/catalog/verification-numbers">
            <div><span class="icon">📱</span><h3>أرقام تأكيد</h3><small>VERIFY NUMBERS</small><p>أرقام مؤقتة وإيجار لاستلام الأكواد.</p></div>
            <span class="arrow">←</span>
          </a>
          <a class="service-card blue" href="/catalog/mobile-recharge">
            <div><span class="icon">🌍</span><h3>شحن أرصدة وباقات</h3><small>MOBILE RECHARGE</small><p>شحن دولي، أوكرانيا، و eSIM وباقات بيانات.</p></div>
            <span class="arrow">←</span>
          </a>
        </section>
      </div>
    </section>
  </main>
</body>
</html>
"""

_LANDING_HTML_V3 = """\
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
      --surface: rgba(15, 23, 42, .78);
      --surface-strong: rgba(30, 41, 59, .82);
      --line: rgba(148, 163, 184, .18);
      --text: #f8fafc;
      --muted: #a5b4fc;
      --soft: #94a3b8;
      --cyan: #22d3ee;
      --green: #34d399;
      --violet: #a78bfa;
      --amber: #f59e0b;
    }
    body {
      min-height: 100vh;
      background:
        linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.018) 1px, transparent 1px),
        radial-gradient(circle at 82% 8%, rgba(34, 211, 238, .13), transparent 32%),
        linear-gradient(135deg, #111827 0%, #0b1020 52%, #07131f 100%);
      background-size: 44px 44px, 44px 44px, auto, auto;
      font-family: "Segoe UI", "Tahoma", Arial, sans-serif;
      color: var(--text);
    }
    a { color: inherit; text-decoration: none; }
    .page {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 20px 0 42px;
    }
    .topbar {
      min-height: 72px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 34px;
    }
    .brand {
      display: inline-flex;
      align-items: center;
      gap: 12px;
      font-size: 1.32rem;
      font-weight: 900;
    }
    .mark {
      width: 42px;
      height: 42px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: rgba(255,255,255,.075);
      border: 1px solid var(--line);
    }
    .auth-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }
    .button {
      min-height: 42px;
      border-radius: 8px;
      border: 1px solid var(--line);
      padding: 0 16px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: .92rem;
      font-weight: 900;
      background: rgba(255,255,255,.055);
      white-space: nowrap;
    }
    .button.primary {
      border-color: rgba(52, 211, 153, .38);
      background: rgba(52, 211, 153, .14);
      color: #d1fae5;
    }
    .section-head {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      margin-bottom: 20px;
    }
    .section-head h1 {
      font-size: clamp(1.8rem, 4vw, 2.8rem);
      line-height: 1.1;
      letter-spacing: 0;
    }
    .catalog-link {
      color: var(--muted);
      font-weight: 900;
      font-size: .93rem;
    }
    .service-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 18px;
    }
    .service-card {
      min-height: 238px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background:
        linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03)),
        var(--surface);
      padding: 24px;
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      justify-content: space-between;
      transition: transform .18s ease, border-color .18s ease, background .18s ease;
    }
    .service-card:hover {
      transform: translateY(-3px);
      border-color: rgba(52, 211, 153, .32);
      background:
        linear-gradient(180deg, rgba(255,255,255,.085), rgba(255,255,255,.04)),
        var(--surface-strong);
    }
    .icon {
      width: 62px;
      height: 62px;
      border-radius: 8px;
      display: grid;
      place-items: center;
      background: rgba(255,255,255,.075);
      border: 1px solid rgba(255,255,255,.08);
      font-size: 1.8rem;
      margin-bottom: 24px;
    }
    .service-card h2 {
      color: var(--green);
      font-size: 1.55rem;
      line-height: 1.2;
      margin-bottom: 8px;
      letter-spacing: 0;
    }
    .service-card small {
      display: block;
      color: #818cf8;
      font-weight: 900;
      letter-spacing: 1.6px;
      margin-bottom: 18px;
    }
    .service-card p {
      color: #b7c0ff;
      line-height: 1.72;
      font-size: .95rem;
    }
    .arrow { color: var(--green); font-size: 1.28rem; margin-top: 22px; }
    .service-card.cyan h2, .service-card.cyan .arrow { color: var(--cyan); }
    .service-card.violet h2, .service-card.violet .arrow { color: var(--violet); }
    .service-card.amber h2, .service-card.amber .arrow { color: var(--amber); }
    @media (max-width: 900px) {
      .service-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .page { width: min(100% - 20px, 560px); padding-top: 12px; }
      .topbar { display: grid; gap: 14px; margin-bottom: 24px; }
      .brand { justify-content: center; }
      .auth-actions { justify-content: stretch; }
      .button { flex: 1 1 150px; }
      .section-head { display: block; margin-bottom: 16px; }
      .section-head h1 { margin-bottom: 10px; font-size: 1.82rem; }
      .service-grid { grid-template-columns: 1fr; gap: 14px; }
      .service-card { min-height: 205px; padding: 20px; }
    }
  </style>
  <script src="/auth/static/i18n.js" defer></script>
</head>
<body>
  <main class="page">
    <header class="topbar">
      <a class="brand" href="/">
        <span class="mark">👻</span>
        <span>Phantom</span>
      </a>
      <nav class="auth-actions" aria-label="روابط الحساب">
        <a class="button primary" href="/register">تسجيل حساب جديد</a>
        <a class="button" href="/login">تسجيل الدخول</a>
      </nav>
    </header>

    <section aria-labelledby="services-title">
      <div class="section-head">
        <h1 id="services-title">الخدمات</h1>
        <a class="catalog-link" href="/catalog">عرض الكتالوغ الكامل ←</a>
      </div>
      <div class="service-grid">
        <a class="service-card" href="/catalog/games">
          <div>
            <span class="icon">🎮</span>
            <h2>الألعاب</h2>
            <small>GAME TOP-UPS</small>
            <p>شدات، بطاقات ألعاب، وتوب أب للألعاب.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card cyan" href="/catalog/chat-apps">
          <div>
            <span class="icon">💬</span>
            <h2>تطبيقات دردشة</h2>
            <small>CHAT APPS</small>
            <p>خدمات Telegram وWhatsApp ومنصات التواصل.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card violet" href="/catalog/social-services">
          <div>
            <span class="icon">📣</span>
            <h2>خدمات المتابعين</h2>
            <small>SOCIAL SERVICES</small>
            <p>خدمات تيك توك، إنستغرام، يوتيوب ومنصات التواصل.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card violet" href="/catalog/subscriptions">
          <div>
            <span class="icon">💎</span>
            <h2>اشتراكات برامج</h2>
            <small>SUBSCRIPTIONS</small>
            <p>Adobe، Telegram Premium، وخدمات البرامج.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card amber" href="/catalog/store-cards">
          <div>
            <span class="icon">🎟️</span>
            <h2>بطاقات المتاجر</h2>
            <small>STORE CARDS</small>
            <p>Apple، Steam، Google Play، PlayStation وبطاقات متاجر.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card amber" href="/catalog/verification-numbers">
          <div>
            <span class="icon">📱</span>
            <h2>أرقام تأكيد</h2>
            <small>VERIFY NUMBERS</small>
            <p>أرقام مؤقتة وإيجار لاستلام الأكواد.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card cyan" href="/catalog/mobile-recharge">
          <div>
            <span class="icon">🌍</span>
            <h2>شحن أرصدة وباقات</h2>
            <small>MOBILE RECHARGE</small>
            <p>شحن دولي، أوكرانيا، و eSIM وباقات بيانات.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card" href="/catalog/internet-providers">
          <div>
            <span class="icon">📡</span>
            <h2>مزودات الإنترنت</h2>
            <small>INTERNET PROVIDERS</small>
            <p>باقات ومزودات إنترنت محلية حسب التوفر.</p>
          </div>
          <span class="arrow">←</span>
        </a>
        <a class="service-card violet" href="/catalog/paid-apps">
          <div>
            <span class="icon">🧩</span>
            <h2>تطبيقات مدفوعة</h2>
            <small>PAID APPS</small>
            <p>تفعيلات وأدوات مدفوعة مثل Unlock Tool و DFT.</p>
          </div>
          <span class="arrow">←</span>
        </a>
      </div>
    </section>
  </main>
</body>
</html>
"""

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

_CATALOG_SECTIONS = (
    {
        "slug": "games",
        "aliases": ("digital",),
        "title": "الألعاب",
        "subtitle": "شحن ألعاب، بطاقات، وتوب أب حسب اللعبة أو الباقة.",
        "accent": "green",
        "items": (
            ("شحن ألعاب", "منتجات ألعاب عامة قابلة للتوسع حسب المزود."),
        ),
    },
    {
        "slug": "chat-apps",
        "title": "تطبيقات دردشة",
        "subtitle": "خدمات ومنتجات مرتبطة بتطبيقات المحادثة والتواصل.",
        "accent": "blue",
        "items": (
            ("Telegram", "خدمات ومنتجات مرتبطة بتطبيق تيليغرام."),
            ("WhatsApp", "خيارات مرتبطة بالتحقق والخدمات الرقمية."),
        ),
        "categories": (
            {
                "slug": "telegram",
                "title": "Telegram",
                "subtitle": "خدمات تيليغرام، حسابات، وربط حسب التوفر.",
                "items": (
                    ("Telegram Premium", "اشتراكات وميزات مدفوعة حسب المصدر."),
                    ("Telegram accounts", "حسابات أو خدمات تحتاج سياسة تسليم واضحة."),
                    ("Telegram verification", "خيارات تحقق مرتبطة بالأرقام عند الحاجة."),
                ),
            },
            {
                "slug": "whatsapp",
                "title": "WhatsApp",
                "subtitle": "خدمات تحقق ومنتجات مرتبطة بواتساب.",
                "items": (
                    ("WhatsApp verification", "استلام كود عبر رقم مؤقت أو مزود مناسب."),
                    ("WhatsApp business", "تصنيفات قابلة للإضافة لاحقاً."),
                    ("دعم حسابات", "خدمات تحتاج بيانات واضحة قبل التنفيذ."),
                ),
            },
            {
                "slug": "social",
                "title": "منصات تواصل",
                "subtitle": "خدمات مرتبطة بمنصات التواصل والحسابات.",
                "items": (
                    ("Instagram", "منتجات وخدمات مرتبطة بالحساب."),
                    ("X و Discord", "تصنيفات تواصل قابلة للتوسع."),
                    ("YouTube", "خدمات رقمية حسب المصادر المتاحة."),
                ),
            },
        ),
    },
    {
        "slug": "social-services",
        "aliases": ("social_services", "followers-services"),
        "title": "خدمات المتابعين",
        "subtitle": "خدمات نمو وإدارة لمنصات التواصل حسب المصدر والتوفر.",
        "accent": "violet",
        "items": (
            ("TikTok Services", "خدمات تيك توك مثل التفاعل والنمو حسب السياسات والتوفر."),
            ("Instagram Services", "خدمات إنستغرام ومنتجات مرتبطة بالحساب."),
            ("YouTube Services", "خدمات يوتيوب ومنصات فيديو حسب المصدر."),
        ),
        "categories": (
            {
                "slug": "tiktok",
                "title": "TikTok",
                "subtitle": "خدمات تيك توك المتاحة ضمن كتالوغ الخدمات.",
                "items": (
                    ("TikTok followers", "طلبات نمو وتفاعل حسب الباقات المتاحة."),
                    ("TikTok likes", "باقات تفاعل حسب المصدر وسياسة التنفيذ."),
                    ("TikTok views", "خيارات مشاهدة وتفاعل عند توفرها."),
                ),
            },
            {
                "slug": "instagram",
                "title": "Instagram",
                "subtitle": "خدمات إنستغرام وحسابات التواصل.",
                "items": (
                    ("Instagram followers", "باقات متابعين حسب المصدر والتوفر."),
                    ("Instagram likes", "تفاعل للمنشورات عند توفر الباقات."),
                    ("Instagram services", "خدمات إضافية مرتبطة بالحساب."),
                ),
            },
            {
                "slug": "youtube",
                "title": "YouTube",
                "subtitle": "خدمات يوتيوب ومنصات الفيديو.",
                "items": (
                    ("YouTube views", "باقات مشاهدة حسب المصدر."),
                    ("YouTube subscribers", "باقات اشتراك عند توفرها."),
                    ("Video engagement", "خدمات تفاعل للفيديوهات."),
                ),
            },
            {
                "slug": "messaging",
                "title": "WhatsApp و Telegram",
                "subtitle": "خدمات مرتبطة بتطبيقات التواصل والرسائل.",
                "items": (
                    ("WhatsApp Services", "خدمات واتساب حسب المصدر والتوفر."),
                    ("Telegram Services", "خدمات تيليغرام وقنوات ومجموعات."),
                    ("Facebook و Kik", "خدمات إضافية لمنصات تواصل أخرى."),
                ),
            },
        ),
    },
    {
        "slug": "subscriptions",
        "aliases": ("apps",),
        "title": "اشتراكات برامج",
        "subtitle": "اشتراكات وخدمات برامج مثل Adobe وTelegram وخدمات رقمية أخرى.",
        "accent": "violet",
        "items": (
            ("Adobe", "اشتراكات وأدوات تصميم حسب التوفر."),
            ("Telegram Premium", "اشتراكات رقمية قابلة للشراء بعد التسجيل."),
        ),
        "categories": (
            {
                "slug": "adobe",
                "title": "Adobe",
                "subtitle": "اشتراكات وأدوات تصميم وإنتاجية.",
                "items": (
                    ("Adobe Creative Cloud", "اشتراكات حسب المدة والمصدر."),
                    ("Photoshop و Illustrator", "خيارات برامج مفردة عند توفرها."),
                    ("Design tools", "أدوات تصميم رقمية قابلة للإضافة."),
                ),
            },
            {
                "slug": "telegram-premium",
                "title": "Telegram Premium",
                "subtitle": "اشتراك تيليغرام بريميوم وخيارات مدة مختلفة.",
                "items": (
                    ("Premium شهري", "خيار قابل للتسعير حسب المصدر."),
                    ("Premium سنوي", "عروض أطول عند توفرها."),
                    ("Gift Premium", "هدايا رقمية عند توفر المنتج."),
                ),
            },
            {
                "slug": "streaming",
                "title": "اشتراكات مشاهدة",
                "subtitle": "Streaming وخدمات محتوى رقمية عند توفرها.",
                "items": (
                    ("Netflix", "اشتراكات حسب السياسة والمصدر."),
                    ("Prime Video", "خيارات مشاهدة عند توفرها."),
                    ("خدمات أخرى", "تصنيفات قابلة للتوسع."),
                ),
            },
        ),
    },
    {
        "slug": "store-cards",
        "aliases": ("store_cards", "gift-cards", "cards"),
        "title": "بطاقات المتاجر",
        "subtitle": "بطاقات رقمية ومتاجر إلكترونية مثل Apple، Steam، Google Play وPlayStation.",
        "accent": "amber",
        "items": (
            ("Apple / iTunes", "بطاقات Apple و iTunes حسب الدولة والقيمة."),
            ("Steam و Google Play", "بطاقات متاجر رقمية للألعاب والتطبيقات."),
            ("PlayStation و Xbox", "بطاقات منصات ألعاب حسب المنطقة."),
        ),
        "categories": (
            {
                "slug": "mobile-stores",
                "title": "متاجر الموبايل",
                "subtitle": "بطاقات تطبيقات وموبايل حسب الدولة.",
                "items": (
                    ("Apple / iTunes", "بطاقات Apple و iTunes حسب المنطقة."),
                    ("Google Play", "بطاقات Google Play وقيم مختلفة."),
                    ("Razer Gold", "بطاقات Razer Gold عند توفرها."),
                ),
            },
            {
                "slug": "platform-stores",
                "title": "متاجر ومنصات",
                "subtitle": "بطاقات متاجر ومنصات رقمية عامة.",
                "items": (
                    ("Steam", "بطاقات Steam حسب العملة والمنطقة."),
                    ("PlayStation", "بطاقات PSN حسب الدولة."),
                    ("Xbox و Nintendo", "بطاقات منصات حسب التوفر."),
                ),
            },
            {
                "slug": "payment-cards",
                "title": "بطاقات دفع وخدمات",
                "subtitle": "بطاقات رقمية عامة وخدمات مرتبطة بالمتاجر.",
                "items": (
                    ("Visa", "منتجات Visa رقمية عند توفرها."),
                    ("بطاقات دفع رقمية", "بطاقات وخدمات دفع عامة عند توفرها."),
                    ("قسائم متاجر", "قسائم شراء عامة غير مرتبطة بلعبة محددة."),
                ),
            },
        ),
    },
    {
        "slug": "verification-numbers",
        "aliases": ("numbers",),
        "title": "أرقام تأكيد",
        "subtitle": "أرقام مؤقتة وإيجار لاستلام أكواد التحقق.",
        "accent": "amber",
        "items": (
            ("أرقام مؤقتة", "استلام كود واحد أو جلسة تحقق قصيرة."),
            ("أرقام للإيجار", "مدة أطول للحسابات التي تحتاج متابعة."),
        ),
        "categories": (
            {
                "slug": "temporary",
                "title": "أرقام مؤقتة",
                "subtitle": "أرقام قصيرة المدة لاستلام كود واحد أو جلسة تحقق.",
                "items": (
                    ("أرقام لتطبيقات التواصل", "واتساب، تيليغرام، ومنصات تواصل حسب التوفر."),
                    ("أرقام للخدمات المالية", "اختيار الدولة والخدمة قبل الطلب."),
                    ("أرقام حسب الدولة", "تصفح الدولة والخدمة ثم نفذ بعد التسجيل."),
                ),
            },
            {
                "slug": "rental",
                "title": "أرقام للإيجار",
                "subtitle": "خيارات أطول مدة للخدمات التي تحتاج أكثر من كود.",
                "items": (
                    ("إيجار يومي", "متابعة قصيرة وتأكيدات متعددة خلال اليوم."),
                    ("إيجار أسبوعي", "استقرار أطول وسجل رسائل."),
                    ("إيجار حسب الدولة", "يعرض حسب المزود والدولة داخل الحساب."),
                ),
            },
            {
                "slug": "voice",
                "title": "SMS أو Voice",
                "subtitle": "استلام عبر رسالة أو مكالمة حسب توفر المزود.",
                "items": (
                    ("SMS", "استلام الأكواد النصية من لوحة الطلبات."),
                    ("Voice", "خيارات مكالمة عند توفرها."),
                    ("مزود آخر", "تبديل المزود عند فشل الطلب."),
                ),
            },
        ),
    },
    {
        "slug": "internet-providers",
        "aliases": ("internet_providers", "internet", "wifi"),
        "title": "مزودات الإنترنت",
        "subtitle": "باقات ومزودات إنترنت محلية حسب التوفر.",
        "accent": "green",
        "items": (
            ("Pro Net و Sama Net", "مزودات إنترنت محلية عند توفر الباقات."),
            ("View Net و Hifi Net", "باقات ومزودات حسب المنطقة."),
            ("MTS و Linet", "منتجات اتصال وإنترنت قابلة للإضافة."),
        ),
        "categories": (
            {
                "slug": "local-providers",
                "title": "مزودات محلية",
                "subtitle": "مزودات إنترنت محلية ضمن كتالوغ الخدمات.",
                "items": (
                    ("Pro Net", "باقات Pro Net حسب التوفر."),
                    ("Sama Net", "باقات Sama Net حسب التوفر."),
                    ("View Net و Hifi Net", "مزودات إضافية قابلة للتوسع."),
                ),
            },
            {
                "slug": "network-cards",
                "title": "بطاقات وباقات شبكة",
                "subtitle": "بطاقات ومزودات اتصال حسب المصدر.",
                "items": (
                    ("Lazer Net", "منتجات Lazer Net عند توفرها."),
                    ("MTS", "باقات MTS حسب المصدر."),
                    ("Cards M و Linet", "بطاقات وخدمات إنترنت إضافية."),
                ),
            },
        ),
    },
    {
        "slug": "paid-apps",
        "aliases": ("paid_apps", "tools", "activations"),
        "title": "تطبيقات مدفوعة",
        "subtitle": "تفعيلات وأدوات مدفوعة مثل Unlock Tool و DFT Pro.",
        "accent": "violet",
        "items": (
            ("Unlock Tool", "تفعيل أدوات وخدمات مدفوعة حسب المدة."),
            ("DFT Pro و EFT Pro", "أدوات صيانة وتفعيل حسب المصدر."),
            ("Direct Activation", "تفعيل مباشر لمنتجات مدفوعة عند توفرها."),
        ),
        "categories": (
            {
                "slug": "mobile-tools",
                "title": "أدوات موبايل",
                "subtitle": "أدوات وتفعيلات مرتبطة بصيانة الموبايل.",
                "items": (
                    ("Android AMT", "تفعيل Android AMT حسب المصدر."),
                    ("DFT Pro", "اشتراك أو تفعيل DFT Pro."),
                    ("EFT Pro", "اشتراك أو تفعيل EFT Pro."),
                ),
            },
            {
                "slug": "activations",
                "title": "تفعيلات مباشرة",
                "subtitle": "منتجات تحتاج تنفيذ أو تفعيل مباشر.",
                "items": (
                    ("Unlock Tool", "تفعيل Unlock Tool حسب المدة."),
                    ("Direct Activation", "تفعيل مباشر للخدمات المدفوعة."),
                    ("Software tools", "أدوات برامج قابلة للإضافة."),
                ),
            },
        ),
    },
    {
        "slug": "mobile-recharge",
        "title": "شحن أرصدة وباقات",
        "subtitle": "شحن دولي، أوكرانيا، وأرصدة وباقات اتصال.",
        "accent": "blue",
        "items": (
            ("أوكرانيا", "شحن أرصدة وباقات أوكرانية عند توفر المصدر."),
            ("باقات عالمية", "تقسيم حسب الدولة والمشغل."),
        ),
        "categories": (
            {
                "slug": "ukraine",
                "title": "شحن أوكرانيا",
                "subtitle": "أرصدة وباقات أوكرانية حسب المشغل والتوفر.",
                "items": (
                    ("Kyivstar", "شحن رصيد أو باقات حسب الرقم."),
                    ("Vodafone Ukraine", "باقات ومبالغ قابلة للتوسع."),
                    ("lifecell", "خيارات شحن حسب سياسة المزود."),
                ),
            },
            {
                "slug": "global",
                "title": "شحن عالمي",
                "subtitle": "شحن وباقات للدول الأخرى حسب المشغل.",
                "items": (
                    ("حسب الدولة", "اختيار الدولة ثم المشغل."),
                    ("حسب المشغل", "عروض متغيرة حسب المصدر."),
                    ("باقات بيانات", "تصنيفات بيانات واتصال."),
                ),
            },
        ),
    },
    {
        "slug": "esim",
        "title": "eSIM",
        "subtitle": "شرائح إلكترونية وباقات بيانات للسفر. الـ API غير مفعّل حالياً.",
        "accent": "amber",
        "enabled": False,
        "status": "قريباً - API غير مفعّل",
        "items": (
            ("باقات حسب الدولة", "اختيار الدولة والمدة وحجم البيانات بعد تفعيل الـ API."),
            ("باقات متعددة الدول", "خطط سفر إقليمية وعالمية بعد تفعيل المصدر."),
        ),
    },
)

_SHOWCASE_TILES: tuple[dict[str, str], ...] = (
    {
        "title": "الألعاب",
        "subtitle": "شدات وباقات ألعاب",
        "href": "/catalog/games",
        "image": "/mini/digital/static/games-rtl.png",
        "accent": "green",
    },
    {
        "title": "التطبيقات",
        "subtitle": "اشتراكات وخدمات تطبيقات",
        "href": "/catalog/subscriptions",
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
        "href": "/catalog/social-services",
        "image": "/mini/digital/static/store-cards-rtl.png",
        "accent": "violet",
    },
    {
        "title": "بطاقات المتاجر",
        "subtitle": "بطاقات ومنتجات رقمية",
        "href": "/catalog/store-cards",
        "image": "/mini/digital/static/section-store-cards.jpg",
        "accent": "green",
    },
    {
        "title": "مزودات الإنترنت",
        "subtitle": "اتصال وباقات محلية",
        "href": "/catalog/internet-providers",
        "image": "/mini/digital/static/numbers-rtl.png",
        "accent": "blue",
    },
    {
        "title": "الأرقام",
        "subtitle": "مؤقتة وإيجار",
        "href": "/catalog/verification-numbers",
        "image": "/mini/digital/static/section-numbers.jpg",
        "accent": "violet",
    },
    {
        "title": "توثيق الحسابات",
        "subtitle": "أرقام وخيارات تحقق",
        "href": "/catalog/verification-numbers",
        "image": "/mini/digital/static/section-games.jpg",
        "accent": "amber",
    },
)


_CATALOG_SECTION_FAMILIES = {
    "games": "games",
    "chat-apps": "chat_apps",
    "social-services": "social_services",
    "subscriptions": "paid_subscriptions",
    "store-cards": "store_cards",
    "verification-numbers": "numbers_services",
    "internet-providers": "internet_providers",
    "paid-apps": "paid_apps",
    "mobile-recharge": "communications_data",
}


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


def _family_section_key(section: dict[str, object] | None) -> str:
    if not section:
        return ""
    slug = str(section.get("slug") or "")
    if slug in _CATALOG_SECTION_FAMILIES:
        return _CATALOG_SECTION_FAMILIES[slug]
    aliases = {str(alias) for alias in section.get("aliases", ())}  # type: ignore[union-attr]
    for alias in aliases:
        if alias in _CATALOG_SECTION_FAMILIES:
            return _CATALOG_SECTION_FAMILIES[alias]
    return ""


def _family_alias_samples(row: dict[str, object], limit: int = 3) -> str:
    aliases = [str(alias).strip() for alias in row.get("aliases", ()) if str(alias).strip()]
    return "، ".join(aliases[:limit])


def _family_categories(section: dict[str, object] | None) -> tuple[dict[str, object], ...]:
    family_key = _family_section_key(section)
    if not family_key:
        return ()
    rows: list[dict[str, object]] = []
    for row in FAMILY_TABLE.get(family_key, ()):
        key = str(row.get("key") or "").strip()
        label = str(row.get("label") or key).strip()
        if not key or not label:
            continue
        aliases = _family_alias_samples(row)
        rows.append(
            {
                "slug": key,
                "title": label,
                "subtitle": f"منتجات وخدمات {label} حسب التوفر والأسعار الفعلية.",
                "items": (
                    (label, f"باقات وخدمات {label} من كاتالوغ الميني آب."),
                    ("الخيارات المتاحة", "تظهر الأسعار والباقات بعد تسجيل الدخول وفتح القسم المناسب."),
                    ("كلمات بحث", aliases or "تصنيف متوفر في الكاتالوغ الداخلي."),
                ),
                "search_terms": aliases,
                "generated": True,
                "service_key": family_key,
                "family_key": key,
            }
        )
    return tuple(rows)


def _section_categories(section: dict[str, object] | None) -> tuple[dict[str, object], ...]:
    if not section:
        return ()
    manual = tuple(section.get("categories", ()))  # type: ignore[union-attr]
    seen = {str(category.get("slug") or "").strip().lower() for category in manual}
    generated = tuple(
        category
        for category in _family_categories(section)
        if str(category.get("slug") or "").strip().lower() not in seen
    )
    return manual + generated


def public_catalog_payload() -> dict[str, object]:
    sections: list[dict[str, object]] = []
    for section in _CATALOG_SECTIONS:
        slug = str(section.get("slug") or "")
        categories = [
            {
                "slug": str(category.get("slug") or ""),
                "title": str(category.get("title") or ""),
                "subtitle": str(category.get("subtitle") or ""),
                "search_terms": str(category.get("search_terms") or ""),
                "generated": bool(category.get("generated")),
                "service_key": str(category.get("service_key") or ""),
                "family_key": str(category.get("family_key") or ""),
            }
            for category in _section_categories(section)
        ]
        sections.append(
            {
                "slug": slug,
                "title": str(section.get("title") or ""),
                "subtitle": str(section.get("subtitle") or ""),
                "accent": str(section.get("accent") or "green"),
                "service": "numbers" if slug == "verification-numbers" else "digital",
                "enabled": bool(section.get("enabled", True)),
                "status": str(section.get("status") or ""),
                "categories": categories,
                "categories_count": len(categories),
            }
        )
    return {"ok": True, "sections": sections}


def _category_by_slug(section: dict[str, object] | None, slug: str) -> dict[str, object] | None:
    normalized = str(slug or "").strip().lower()
    if not section or not normalized:
        return None
    return next(
        (
            category
            for category in _section_categories(section)
            if str(category.get("slug") or "").strip().lower() == normalized
        ),
        None,
    )


def _catalog_link_attrs() -> str:
    return 'data-preserve-catalog-query'


def _category_tabs(section: dict[str, object] | None, *, active_category: str = "") -> str:
    if not section:
        return ""
    categories = _section_categories(section)
    if not categories:
        return ""
    section_slug = escape(str(section["slug"]))
    visible_categories = list(categories)
    hidden_count = 0
    if len(visible_categories) > 24:
        active = next((category for category in visible_categories if str(category.get("slug") or "") == active_category), None)
        visible_categories = visible_categories[:18]
        if active and all(str(category.get("slug") or "") != active_category for category in visible_categories):
            visible_categories.append(active)
        hidden_count = max(0, len(categories) - len(visible_categories))
    links = [
        f'<a class="category-tab {"active" if not active_category else ""}" href="/catalog/{section_slug}" {_catalog_link_attrs()}>الكل</a>'
    ]
    for category in visible_categories:
        slug = str(category.get("slug") or "")
        title = escape(str(category.get("title") or slug))
        active = " active" if slug == active_category else ""
        links.append(f'<a class="category-tab{active}" href="/catalog/{section_slug}/{escape(slug)}" {_catalog_link_attrs()}>{title}</a>')
    if hidden_count:
        links.append(f'<a class="category-tab more" href="/catalog/{section_slug}" {_catalog_link_attrs()}>+{hidden_count} أصناف</a>')
    return f'<nav class="category-tabs" aria-label="تصنيفات {escape(str(section["title"]))}">{"".join(links)}</nav>'


def _catalog_breadcrumbs(section: dict[str, object] | None, category: dict[str, object] | None) -> str:
    parts = [f'<a href="/catalog" {_catalog_link_attrs()}>الكتالوغ</a>']
    back_href = "/catalog"
    back_label = "رجوع إلى الأقسام"
    if section:
        section_slug = escape(str(section["slug"]))
        section_title = escape(str(section["title"]))
        if category:
            parts.append(f'<a href="/catalog/{section_slug}" {_catalog_link_attrs()}>{section_title}</a>')
            parts.append(f'<span>{escape(str(category["title"]))}</span>')
            back_href = f"/catalog/{section_slug}"
            back_label = "رجوع إلى الأصناف"
        else:
            parts.append(f"<span>{section_title}</span>")
    crumb_html = '<span aria-hidden="true">/</span>'.join(parts)
    back_link = f'<a class="back-link" href="{back_href}" data-preserve-catalog-query>{back_label}</a>' if section else ""
    return (
        '<div class="catalog-path">'
        f'<nav class="breadcrumbs" aria-label="مسار الكتالوغ">{crumb_html}</nav>'
        f"{back_link}"
        "</div>"
    )


def _broader_catalog_search_path(section: dict[str, object] | None, category: dict[str, object] | None) -> str:
    if category and section:
        return f"/catalog/{escape(str(section['slug']))}"
    if section:
        return "/catalog"
    return ""


def _catalog_cards(*, active_slug: str = "") -> str:
    cards: list[str] = []
    for section in _CATALOG_SECTIONS:
        slug = str(section["slug"])
        title = escape(str(section["title"]))
        subtitle = escape(str(section["subtitle"]))
        accent = escape(str(section["accent"]))
        active = " active" if slug == active_slug else ""
        search_text = escape(f"{title} {subtitle}")
        enabled = bool(section.get("enabled", True))
        status = escape(str(section.get("status") or ""))
        state_class = "" if enabled else " unavailable"
        cards.append(
            f"""
            <a class="catalog-card {accent}{active}{state_class}" href="/catalog/{escape(slug)}" data-catalog-search="{search_text}" {_catalog_link_attrs()}>
              <span class="catalog-mark" aria-hidden="true"></span>
              <strong>{title}</strong>
              <span>{subtitle}</span>
              {f'<small class="catalog-status">{status}</small>' if status else ''}
            </a>
            """
        )
    return "\n".join(cards)


def _category_cards(section: dict[str, object]) -> str:
    section_slug = escape(str(section["slug"]))
    cards: list[str] = []
    for category in _section_categories(section):
        slug = escape(str(category.get("slug") or ""))
        title = escape(str(category.get("title") or slug))
        subtitle = escape(str(category.get("subtitle") or ""))
        search_text = escape(f"{title} {subtitle} {category.get('search_terms', '')}")
        cards.append(
            f"""
            <a class="catalog-card {escape(str(section["accent"]))}" href="/catalog/{section_slug}/{slug}" data-catalog-search="{search_text}" {_catalog_link_attrs()}>
              <span class="catalog-mark" aria-hidden="true"></span>
              <strong>{title}</strong>
              <span>{subtitle}</span>
            </a>
            """
        )
    return "\n".join(cards)


def _root_family_search_cards() -> str:
    cards: list[str] = []
    for section in _CATALOG_SECTIONS:
        section_slug = escape(str(section["slug"]))
        accent = escape(str(section["accent"]))
        section_title = str(section["title"])
        section_label = escape(section_title)
        for category in _family_categories(section):
            slug = escape(str(category.get("slug") or ""))
            title = escape(str(category.get("title") or slug))
            subtitle = escape(str(category.get("subtitle") or ""))
            search_text = escape(f"{section_title} {category.get('title', '')} {category.get('subtitle', '')} {category.get('search_terms', '')}")
            cards.append(
                f"""
                <a class="catalog-card {accent} root-search-card" href="/catalog/{section_slug}/{slug}" data-catalog-search="{search_text}" data-root-search-result data-preserve-catalog-query hidden>
                  <span class="catalog-mark" aria-hidden="true"></span>
                  <small class="catalog-section-kicker">ضمن {section_label}</small>
                  <strong>{title}</strong>
                  <span>{subtitle}</span>
                </a>
                """
            )
    return "\n".join(cards)


def _section_checkout_path(section: dict[str, object] | None) -> str:
    slug = str((section or {}).get("slug") or "")
    aliases = {str(alias) for alias in (section or {}).get("aliases", ())}  # type: ignore[union-attr]
    if slug == "verification-numbers" or "numbers" in aliases:
        return "/app/numbers"
    return "/app/digital"


def _catalog_items(section: dict[str, object] | None, category: dict[str, object] | None = None) -> str:
    sections = (section,) if section else _CATALOG_SECTIONS
    rows: list[str] = []
    for group in sections:
        current = category if category and group is section else group
        title = escape(str(current["title"]))
        slug = escape(str(group["slug"]))
        accent = escape(str(group["accent"]))
        checkout_path = escape(_section_checkout_path(group))
        group_search = escape(f'{current["title"]} {current.get("subtitle", "")}')
        rows.append(f'<div class="product-group {accent}" data-catalog-search="{group_search}"><div class="group-head"><h2>{title}</h2><a href="/register?next={checkout_path}">شراء بعد التسجيل</a></div><div class="product-grid">')
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
                    <a href="/login?next={checkout_path}">تسجيل الدخول</a>
                    <a class="primary" href="/register?next={checkout_path}">إنشاء حساب للشراء</a>
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
            <a class="showcase-tile {accent}" href="{href}" data-catalog-search="{search_text}" {_catalog_link_attrs()}>
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
    title = str((category or section)["title"]) if (category or section) else "Phantom Services"
    breadcrumbs_html = _catalog_breadcrumbs(section, category)
    broader_search_path = _broader_catalog_search_path(section, category)
    if section and not bool(section.get("enabled", True)):
        stage_title = "الخدمة غير مفعّلة حالياً"
        stage_hint = str(section.get("status") or "قريباً")
        stage_html = '<div class="catalog-unavailable"><strong>eSIM قريباً</strong><span>سيتم فتح الباقات والشراء بعد تفعيل وربط الـ API.</span></div>'
        stage_class = "product-stage"
        category_tabs_html = ""
    elif category:
        stage_title = "اختر المنتج أو الخدمة"
        stage_hint = "هذه المنتجات متاحة للاستعراض. تنفيذ الطلب يتم بعد تسجيل الدخول وشحن الرصيد."
        stage_html = _catalog_items(section, category)
        stage_class = "product-stage"
        category_tabs_html = _category_tabs(section, active_category=str(category["slug"]))
    elif section and _section_categories(section):
        stage_title = "اختر الصنف الفرعي"
        stage_hint = "ادخل إلى الصنف المناسب حتى تصل إلى المنتجات المتاحة."
        stage_html = _category_cards(section)
        stage_class = "catalog-nav"
        category_tabs_html = ""
    else:
        stage_title = "اختر القسم"
        stage_hint = "ابدأ من قسم رئيسي، ثم تابع إلى الأصناف الفرعية والمنتجات."
        stage_html = f"{_catalog_cards(active_slug=active_slug)}{_root_family_search_cards()}"
        stage_class = "catalog-nav"
        category_tabs_html = ""
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
    .hero {{ padding: 34px 0 18px; display: grid; justify-items: end; }}
    .hero h1 {{ font-size: clamp(2rem, 4vw, 3.3rem); line-height: 1.1; margin-bottom: 16px; letter-spacing: 0; }}
    .search-band {{ display: grid; justify-items: center; gap: 12px; margin: 8px 0 26px; }}
    .search-box {{ width: min(760px, 100%); min-height: 48px; border-radius: 999px; border: 1px solid rgba(255,255,255,.14); background: rgba(255,255,255,.07); display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 18px; color: #cbd5e1; }}
    .search-box input {{ width: 100%; border: 0; outline: 0; background: transparent; color: var(--text); font: inherit; direction: rtl; }}
    .search-box input::placeholder {{ color: #8b95b8; opacity: 1; }}
    .search-box span {{ color: #8b95b8; }}
    .catalog-empty {{ display: none; border: 1px solid rgba(245,158,11,.24); border-radius: 8px; background: rgba(245,158,11,.07); color: #fde68a; padding: 14px; line-height: 1.7; margin: 12px 0 22px; text-align: center; }}
    .catalog-empty.visible {{ display: block; }}
    .catalog-empty a {{ color: #fff7ed; font-weight: 900; text-decoration: underline; text-underline-offset: 3px; }}
    [data-catalog-search][hidden] {{ display: none !important; }}
    .catalog-path {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 4px 0 12px; color: #a7b0d0; font-size: .9rem; }}
    .breadcrumbs {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .breadcrumbs a {{ color: #c7d2fe; font-weight: 800; }}
    .breadcrumbs span:last-child {{ color: var(--text); font-weight: 900; }}
    .back-link {{ min-height: 34px; border: 1px solid var(--line); border-radius: 8px; padding: 0 12px; display: inline-flex; align-items: center; justify-content: center; background: rgba(255,255,255,.045); color: #dbeafe; font-weight: 800; white-space: nowrap; }}
    .stage-head {{ display: flex; align-items: end; justify-content: space-between; gap: 16px; margin: 18px 0 14px; }}
    .stage-head h2 {{ font-size: 1.35rem; }}
    .stage-head p {{ color: var(--soft); line-height: 1.65; max-width: 560px; }}
    .showcase-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; margin-bottom: 28px; }}
    .showcase-tile {{ min-height: 208px; display: flex; flex-direction: column; align-items: center; justify-content: flex-start; gap: 8px; text-align: center; color: var(--text); }}
    .tile-image {{ width: 100%; aspect-ratio: 1 / .86; border-radius: 8px; border: 1px solid rgba(255,255,255,.14); background-size: cover; background-position: center; display: block; box-shadow: 0 18px 38px rgba(0,0,0,.26); transition: transform .18s ease, box-shadow .18s ease; }}
    .showcase-tile:hover .tile-image {{ transform: translateY(-4px); box-shadow: 0 22px 48px rgba(0,0,0,.34), 0 0 26px currentColor; }}
    .showcase-tile strong {{ font-size: .98rem; }}
    .showcase-tile small {{ color: #a7b0d0; font-size: .78rem; }}
    .catalog-nav {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 12px 0 26px; }}
    .product-stage {{ margin: 12px 0 26px; }}
    .catalog-card {{ min-height: 150px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: transform .18s ease, border-color .18s ease, background .18s ease; }}
    .catalog-card:hover, .catalog-card.active {{ transform: translateY(-2px); border-color: rgba(255,255,255,.28); background: var(--panel-strong); }}
    .catalog-card.unavailable {{ border-color: rgba(245,158,11,.28); opacity: .82; }}
    .catalog-status {{ margin-top: auto; color: #fde68a; font-weight: 900; }}
    .catalog-unavailable {{ min-height: 190px; border: 1px solid rgba(245,158,11,.3); border-radius: 8px; background: rgba(245,158,11,.08); display: grid; place-items: center; align-content: center; gap: 10px; text-align: center; color: #fde68a; padding: 24px; }}
    .catalog-unavailable strong {{ color: #fff7ed; font-size: 1.25rem; }}
    .catalog-mark {{ width: 42px; height: 8px; border-radius: 999px; background: currentColor; box-shadow: 0 0 24px currentColor; opacity: .84; }}
    .catalog-card strong {{ font-size: 1.05rem; }}
    .catalog-section-kicker {{ color: #c7d2fe; font-size: .78rem; font-weight: 900; line-height: 1.35; }}
    .root-search-card .catalog-section-kicker {{ color: currentColor; opacity: .82; }}
    .catalog-card span:last-child {{ color: var(--soft); line-height: 1.65; font-size: .9rem; }}
    .violet {{ color: var(--violet); }} .green {{ color: var(--green); }} .blue {{ color: var(--blue); }} .amber {{ color: var(--amber); }}
    .category-tabs {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 24px; }}
    .category-tab {{ min-height: 38px; border: 1px solid var(--line); border-radius: 8px; padding: 0 13px; display: inline-flex; align-items: center; color: #c7d2fe; background: rgba(255,255,255,.045); font-size: .9rem; font-weight: 800; }}
    .category-tab.active {{ border-color: rgba(52,211,153,.38); background: rgba(52,211,153,.11); color: #d1fae5; }}
    .category-tab.more {{ color: #fef3c7; border-color: rgba(245,158,11,.22); background: rgba(245,158,11,.08); }}
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
      .hero {{ padding-top: 30px; }}
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
      .search-box {{ min-height: 44px; border-radius: 8px; }}
      .catalog-path {{ align-items: stretch; flex-direction: column; }}
      .back-link {{ width: 100%; }}
      .stage-head {{ display: block; }}
      .stage-head h2 {{ margin-bottom: 6px; }}
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
      </div>
    </section>
    <section class="search-band" aria-label="بحث الكتالوغ">
      <label class="search-box" for="catalog-search">
        <input id="catalog-search" type="search" autocomplete="off" placeholder="ابحث عن خدمة أو منتج..." aria-label="بحث في الكتالوغ" />
        <span aria-hidden="true">⌕</span>
      </label>
        </section>
        {breadcrumbs_html}
        <section aria-labelledby="catalog-stage-title">
      <div class="stage-head">
        <h2 id="catalog-stage-title">{escape(stage_title)}</h2>
        <p>{escape(stage_hint)}</p>
      </div>
          <div class="{stage_class}" aria-label="مرحلة الكتالوغ">
            {stage_html}
          </div>
        </section>
        {category_tabs_html}
        <p class="catalog-empty" id="catalog-empty" data-broader-search="{broader_search_path}">لا توجد نتائج مطابقة. جرّب كلمة مثل ألعاب، أوكرانيا، أرقام، PUBG، أو VPN.</p>
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
      const queryLinks = Array.from(document.querySelectorAll("[data-preserve-catalog-query]"));
      const hrefWithQuery = (href, query) => {{
        if (!href || !query) return href;
        const [baseAndSearch, hash = ""] = String(href).split("#");
        const [path, search = ""] = baseAndSearch.split("?");
        const params = new URLSearchParams(search);
        params.set("q", query);
        return `${{path}}?${{params.toString()}}${{hash ? `#${{hash}}` : ""}}`;
      }};
      const syncQueryLinks = (query) => {{
        queryLinks.forEach((link) => {{
          if (!link.dataset.baseHref) link.dataset.baseHref = link.getAttribute("href") || "";
          link.setAttribute("href", query ? hrefWithQuery(link.dataset.baseHref, query) : link.dataset.baseHref);
        }});
      }};
      const applySearch = () => {{
        const query = normalize(input.value);
        syncQueryLinks(input.value.trim());
        let visibleProducts = 0;
        searchable.forEach((node) => {{
          const haystack = normalize(node.getAttribute("data-catalog-search") + " " + node.textContent);
          const rootOnly = node.hasAttribute("data-root-search-result");
          const isVisible = rootOnly ? Boolean(query) && haystack.includes(query) : (!query || haystack.includes(query));
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
        const hasNoResults = Boolean(query) && visibleProducts === 0 && visibleShowcase === 0 && visibleCatalogCards === 0;
        empty.classList.toggle("visible", hasNoResults);
        if (hasNoResults) {{
          const broader = empty.getAttribute("data-broader-search");
          empty.innerHTML = broader
            ? `لا توجد نتائج هنا. <a href="${{broader}}?q=${{encodeURIComponent(input.value.trim())}}">ابحث ضمن نطاق أوسع</a>`
            : "لا توجد نتائج مطابقة. جرّب كلمة مثل ألعاب، أوكرانيا، أرقام، PUBG، أو VPN.";
        }}
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
    return catalog_page_html()


async def catalog_page(request: web.Request) -> web.Response:
    """Public section browser. Final category selection continues inside the account."""
    slug = str(request.match_info.get("slug") or "")
    section = _section_by_slug(slug)
    if slug and section is None:
        raise web.HTTPNotFound(text="catalog section not found")
    category_slug = str(request.match_info.get("category") or request.query.get("category") or "")
    if slug and section and slug != str(section["slug"]):
        query = {key: value for key, value in request.query.items() if key != "category"}
        canonical = f"/catalog/{section['slug']}"
        if category_slug and category_slug != "games":
            canonical = f"{canonical}/{category_slug}"
        if query:
            canonical = f"{canonical}?{urlencode(query)}"
        raise web.HTTPFound(location=canonical)
    if category_slug and _category_by_slug(section, category_slug):
        raise web.HTTPFound(location=_section_checkout_path(section))
    return web.Response(
        text=catalog_page_html(slug, category_slug=category_slug),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )


async def public_catalog_api(_request: web.Request) -> web.Response:
    return web.json_response(public_catalog_payload(), headers=dict(_NO_STORE_HEADERS))


async def landing_page(_request: web.Request) -> web.Response:
    """Public website homepage for anonymous visitors."""
    return web.Response(
        text=landing_page_html(),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )
