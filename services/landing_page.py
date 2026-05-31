from __future__ import annotations

from html import escape

from aiohttp import web

from utils.bot_menu_context import card_ex_bot_url, digital_products_bot_url, numbers_bot_url

_LANDING_HTML = """\
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Phantom Services</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      min-height: 100vh;
      background: #0d0d1a;
      background-image:
        radial-gradient(ellipse at 20% 20%, rgba(99, 60, 180, 0.18) 0%, transparent 60%),
        radial-gradient(ellipse at 80% 80%, rgba(30, 120, 200, 0.14) 0%, transparent 60%);
      font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
      color: #e8e8f0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 2rem 1rem;
    }

    .logo-wrap {
      margin-bottom: 0.5rem;
      font-size: 3rem;
      line-height: 1;
      filter: drop-shadow(0 0 18px rgba(140, 90, 255, 0.55));
    }

    h1 {
      font-size: 1.75rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      background: linear-gradient(135deg, #c084fc 0%, #818cf8 50%, #38bdf8 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 0.35rem;
      text-align: center;
    }

    .subtitle {
      font-size: 0.9rem;
      color: #8888aa;
      margin-bottom: 2.5rem;
      text-align: center;
      letter-spacing: 0.02em;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1.25rem;
      width: 100%;
      max-width: 900px;
    }

    .card {
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.09);
      border-radius: 18px;
      padding: 2rem 1.5rem;
      text-decoration: none;
      color: inherit;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.75rem;
      transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
      cursor: pointer;
      position: relative;
      overflow: hidden;
    }

    .card::before {
      content: '';
      position: absolute;
      inset: 0;
      border-radius: inherit;
      opacity: 0;
      transition: opacity 0.2s ease;
    }

    .card:hover {
      transform: translateY(-4px);
      border-color: rgba(255, 255, 255, 0.22);
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
      background: rgba(255, 255, 255, 0.07);
    }

    .card:active {
      transform: translateY(-1px);
    }

    /* Per-card accent colours */
    .card-numbers { --accent: #a78bfa; --glow: rgba(167, 139, 250, 0.25); }
    .card-digital { --accent: #34d399; --glow: rgba(52, 211, 153, 0.25); }
    .card-cardex  { --accent: #f59e0b; --glow: rgba(245, 158, 11, 0.25); }

    .card:hover {
      box-shadow: 0 12px 40px var(--glow, rgba(0,0,0,0.4));
    }

    .card-icon {
      font-size: 2.8rem;
      line-height: 1;
      filter: drop-shadow(0 0 10px var(--accent, #fff));
    }

    .card-title-ar {
      font-size: 1.3rem;
      font-weight: 700;
      color: var(--accent, #e8e8f0);
      text-align: center;
    }

    .card-title-en {
      font-size: 0.8rem;
      font-weight: 500;
      color: #6666aa;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      text-align: center;
    }

    .card-desc {
      font-size: 0.85rem;
      color: #9999bb;
      text-align: center;
      line-height: 1.55;
      margin-top: 0.25rem;
    }

    .card-arrow {
      margin-top: auto;
      padding-top: 0.75rem;
      font-size: 1.1rem;
      color: var(--accent, #e8e8f0);
      opacity: 0.6;
      transition: opacity 0.2s ease, transform 0.2s ease;
    }

    .card:hover .card-arrow {
      opacity: 1;
      transform: translateX(-4px);
    }

    .footer {
      margin-top: 3rem;
      font-size: 0.75rem;
      color: #44445a;
      text-align: center;
      letter-spacing: 0.03em;
    }

    @media (max-width: 600px) {
      h1 { font-size: 1.4rem; }
      .cards { grid-template-columns: 1fr; }
      .card { padding: 1.5rem 1.25rem; }
    }
  </style>
</head>
<body>
  <div class="logo-wrap">👻</div>
  <h1>Phantom Services</h1>
  <p class="subtitle">اختر الخدمة التي تريدها &nbsp;·&nbsp; Choose your service</p>

  <div class="cards">

    <!-- Numbers -->
    <a class="card card-numbers" href="/mini/numbers">
      <div class="card-icon">📱</div>
      <div class="card-title-ar">أرقام</div>
      <div class="card-title-en">Numbers Service</div>
      <p class="card-desc">
        أرقام مؤقتة وأرقام للإيجار<br />
        <span style="font-size:0.78rem;color:#6666aa;">Temporary &amp; Rental Numbers</span>
      </p>
      <div class="card-arrow">←</div>
    </a>

    <!-- Digital Products -->
    <a class="card card-digital" href="/mini/digital">
      <div class="card-icon">🎮</div>
      <div class="card-title-ar">منتجات رقمية</div>
      <div class="card-title-en">Digital Products</div>
      <p class="card-desc">
        بطاقات الألعاب، شحن الرصيد والمزيد<br />
        <span style="font-size:0.78rem;color:#6666aa;">Game Cards, Top-ups &amp; More</span>
      </p>
      <div class="card-arrow">←</div>
    </a>

    <!-- Card Exchange -->
    <a class="card card-cardex" href="/mini/cardex">
      <div class="card-icon">💳</div>
      <div class="card-title-ar">تبديل البطاقات</div>
      <div class="card-title-en">Card Exchange</div>
      <p class="card-desc">
        شراء وبيع البطاقات الرقمية<br />
        <span style="font-size:0.78rem;color:#6666aa;">Buy &amp; Sell Cards</span>
      </p>
      <div class="card-arrow">←</div>
    </a>

  </div>

  <p class="footer">phantom-app.net &nbsp;·&nbsp; Powered by Phantom Bot</p>
</body>
</html>
"""

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _landing_links() -> dict[str, str]:
    return {
        "numbers": numbers_bot_url("numbers") or "/mini/numbers",
        "digital": digital_products_bot_url("store") or "/mini/digital",
        "cardex": card_ex_bot_url("cards") or "/mini/cardex",
    }


def landing_page_html() -> str:
    links = _landing_links()
    return (
        _LANDING_HTML
        .replace('href="/mini/numbers"', f'href="{escape(links["numbers"], quote=True)}"')
        .replace('href="/mini/digital"', f'href="{escape(links["digital"], quote=True)}"')
        .replace('href="/mini/cardex"', f'href="{escape(links["cardex"], quote=True)}"')
    )


async def landing_page(_request: web.Request) -> web.Response:
    """Root landing page — lets users navigate to each mini-app service."""
    return web.Response(
        text=landing_page_html(),
        content_type="text/html",
        headers=dict(_NO_STORE_HEADERS),
    )
