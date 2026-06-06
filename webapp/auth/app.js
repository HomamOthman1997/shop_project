const $ = (selector) => document.querySelector(selector);

const authView = $("#auth-view");
const verifyView = $("#verify-view");
const accountView = $("#account-view");
const form = $("#auth-form");
const emailInput = $("#email");
const passwordInput = $("#password");
const formError = $("#form-error");
const submitButton = $("#submit-button");
const telegramAction = $("#telegram-action");
const accountMessage = $("#account-message");
const sendEmailCodeButton = $("#send-email-code");
const verifyEmailCodeButton = $("#verify-email-code");
const verifySendEmailCodeButton = $("#verify-send-email-code");
const verifyEmailCodeSubmit = $("#verify-email-code-button");

let mode = "login";
let currentAccount = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function csrfToken() {
  const item = document.cookie.split("; ").find((row) => row.startsWith("phantom_csrf="));
  return item ? decodeURIComponent(item.split("=").slice(1).join("=")) : "";
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers["X-CSRF-Token"] = csrfToken();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), options.timeoutMs || 20000);
  let response;
  let text = "";
  try {
    response = await fetch(path, { credentials: "same-origin", ...options, method, headers, signal: controller.signal });
    text = await response.text();
  } catch (error) {
    if (error.name === "AbortError") throw new Error("انتهت مهلة الطلب، حاول مرة أخرى.");
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = {}; }
  if (!response.ok) throw new Error(data.message || text || "تعذر إكمال الطلب");
  return data;
}

function setText(selector, value) {
  const node = $(selector);
  if (node) node.textContent = value;
}

function showVerifyOnly(account) {
  currentAccount = account;
  authView.hidden = true;
  accountView.hidden = true;
  verifyView.hidden = false;
  $(".form-wrap").classList.remove("dashboard-mode");
  setText("#verify-email", account.email || "");
  $("#verify-code-row").hidden = true;
  setText("#verify-message", "");
}

function showAccount(account) {
  currentAccount = account;
  if (!account.email_verified) {
    showVerifyOnly(account);
    return;
  }

  authView.hidden = true;
  verifyView.hidden = true;
  accountView.hidden = false;
  $(".form-wrap").classList.add("dashboard-mode");
  setText("#account-email", account.email);
  setText("#settings-email", account.email);
  setText("#customer-id", account.customer_id);
  setText("#telegram-status", account.telegram_linked ? "مربوط" : "غير مربوط");
  telegramAction.textContent = account.telegram_linked ? "فك الربط" : "ربط Telegram";
  applyEmailState(account);
  applyIdentityState(account.identity_status);
  loadDashboard();
}

function applyEmailState(account) {
  const verified = Boolean(account.email_verified);
  setText("#email-status", verified ? "مؤكد" : "غير مؤكد");
  const row = $("#email-verification-row");
  if (row) row.hidden = verified;
  const codeRow = $("#email-code-row");
  if (codeRow) codeRow.hidden = true;
  const readiness = $("#purchase-readiness");
  if (readiness) readiness.hidden = verified;
}

async function sendEmailCode({ button, codeRow, message }) {
  message.textContent = "";
  button.disabled = true;
  try {
    const data = await api("/api/v1/auth/email/send-code", { method: "POST" });
    if (data.status === "already_verified") {
      const fresh = await api("/api/v1/auth/me");
      showAccount(fresh.account);
      message.textContent = "البريد مؤكد مسبقا.";
      return;
    }
    codeRow.hidden = false;
    const debug = data.debug_code ? ` كود الاختبار: ${data.debug_code}` : "";
    message.textContent = data.status === "sent"
      ? "تم إرسال كود التأكيد إلى بريدك."
      : `تم إنشاء الكود.${debug}`;
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function verifyEmailCode({ button, input, message }) {
  message.textContent = "";
  button.disabled = true;
  try {
    const data = await api("/api/v1/auth/email/verify", {
      method: "POST",
      body: JSON.stringify({ code: input.value.trim() }),
    });
    showAccount(data.account);
    message.textContent = "تم تأكيد البريد.";
  } catch (error) {
    message.textContent = error.message === "invalid or expired code"
      ? "الكود غير صحيح أو منتهي."
      : error.message;
  } finally {
    button.disabled = false;
  }
}

const identityLabels = {
  not_submitted: "غير مقدمة",
  pending: "قيد المراجعة",
  approved: "موثقة",
  rejected: "مرفوضة",
  needs_changes: "تحتاج تعديل",
};

function applyIdentityState(status) {
  const label = identityLabels[status] || status;
  setText("#identity-status", label);
  setText("#identity-summary", label);
  const identityForm = $("#identity-form");
  if (identityForm) identityForm.hidden = ["pending", "approved"].includes(status);

  const cardexLink = $("#cardex-link");
  if (!cardexLink) return;
  const allowed = status === "approved";
  cardexLink.classList.toggle("locked", !allowed);
  cardexLink.href = allowed ? "/mini/cardex" : "#";
  const marker = cardexLink.querySelector("b");
  if (marker) marker.textContent = allowed ? "فتح" : "مقفل";
  setText("#cardex-reason", allowed ? "بيع البطاقات والسحب" : "يتطلب تأكيد الهوية");
}

function renderRows(target, rows, formatter) {
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length
    ? rows.map(formatter).join("")
    : "لا توجد بيانات حتى الآن.";
}

async function loadDashboard() {
  const activity = $("#activity-list");
  try {
    const [digitalAccount, digitalOrders, numberOrders] = await Promise.all([
      api("/api/v1/digital/account"),
      api("/api/v1/digital/orders?limit=20"),
      api("/api/v1/numbers/orders?limit=20"),
    ]);
    setText("#wallet-balance", digitalAccount.wallet?.balance_label || "$0.00");

    const digitalRows = digitalOrders.orders || digitalOrders.items || [];
    const numberRows = numberOrders.orders || numberOrders.items || [];
    setText("#digital-order-count", digitalRows.length);
    setText("#numbers-order-count", numberRows.length);

    renderRows(activity, digitalAccount.recent_activity || [], (row) => `
      <div class="data-row">
        <div><strong>${esc(row.reason || "حركة رصيد")}</strong><span>${esc(row.created_at || "")}</span></div>
        <b>${row.direction === "debit" ? "-" : "+"}${esc(row.amount_label || "")}</b>
      </div>`);
    renderOrders([
      ...digitalRows.map((row) => ({ ...row, channel: "رقمي" })),
      ...numberRows.map((row) => ({ ...row, channel: "أرقام" })),
    ]);
  } catch (error) {
    activity.textContent = "تعذر تحميل بيانات الحساب حاليا.";
  }
}

function renderOrders(rows) {
  const target = $("#orders-list");
  renderRows(target, rows, (row) => `
    <div class="data-row">
      <div>
        <strong>${esc(row.title || row.service_name || row.service_id || "طلب")}</strong>
        <span>${esc(row.channel)} · ${esc(row.created_at || "")}</span>
      </div>
      <b>${esc(row.status || "")}</b>
    </div>`);
}

function localized(value, fallback = "") {
  if (value && typeof value === "object") return value.ar || value.en || Object.values(value)[0] || fallback;
  return value || fallback;
}

function serviceRoot() {
  return $("#service-root");
}

function setWorkspaceTheme(service) {
  const workspace = document.querySelector(".service-workspace");
  const root = serviceRoot();
  if (workspace) workspace.dataset.serviceTheme = service || "";
  if (root) {
    root.className = "service-root";
    if (service) root.classList.add(`service-root-${service}`);
  }
}

function serviceLoading(label) {
  const root = serviceRoot();
  if (root) root.innerHTML = `<div class="service-loader">${esc(label || "جاري التحميل...")}</div>`;
}

function serviceError(message, retry) {
  const root = serviceRoot();
  if (!root) return;
  root.innerHTML = `
    <div class="service-empty">
      <strong>تعذر تحميل الخدمة</strong>
      <span>${esc(message)}</span>
      ${retry ? '<button class="secondary compact" type="button" data-service-retry>إعادة المحاولة</button>' : ""}
    </div>`;
  root.querySelector("[data-service-retry]")?.addEventListener("click", retry);
}

function idempotencyKey(prefix) {
  if (window.crypto?.randomUUID) return `${prefix}-${window.crypto.randomUUID()}`;
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function fieldsFormHtml(fields, fallback = []) {
  const rows = (fields && fields.length ? fields : fallback).map((field) => {
    const id = String(field.id || field.key || "").trim();
    if (!id) return "";
    const label = localized(field.label, id);
    const required = field.required === false ? "" : "required";
    return `
      <label>
        <span>${esc(label)}${required ? " *" : ""}</span>
        <input name="${esc(id)}" ${required} autocomplete="off">
      </label>`;
  });
  return rows.join("");
}

function fieldData(form) {
  return Object.fromEntries([...new FormData(form).entries()].map(([key, value]) => [key, String(value).trim()]));
}

async function loadDigitalWorkspace() {
  serviceLoading("جاري تحميل المنتجات الرقمية...");
  try {
    const payload = await api("/api/v1/digital/catalog");
    renderDigitalCatalog(payload);
  } catch (error) {
    serviceError(error.message, loadDigitalWorkspace);
  }
}

function renderDigitalCatalog(payload) {
  const root = serviceRoot();
  const products = payload.products || [];
  const games = payload.games || [];
  root.innerHTML = `
    <div class="service-toolbar">
      <input id="digital-search" type="search" placeholder="ابحث عن لعبة أو خدمة">
      <button class="secondary compact" type="button" data-digital-refresh>تحديث</button>
    </div>
    <div class="service-split">
      <div class="service-list-panel">
        <h4>الألعاب</h4>
        <div class="service-grid" id="digital-games"></div>
        <h4>الخدمات الرقمية</h4>
        <div class="service-grid" id="digital-products"></div>
      </div>
      <div class="service-detail" id="digital-detail">
        <div class="service-empty">اختر خدمة لعرض الباقات والأسعار.</div>
      </div>
    </div>`;

  const renderItems = () => {
    const query = $("#digital-search").value.trim().toLowerCase();
    const filter = (row) => !query || JSON.stringify(row).toLowerCase().includes(query);
    $("#digital-games").innerHTML = games.filter(filter).slice(0, 80).map((row) => digitalItemButton("game", row)).join("")
      || '<div class="service-muted">لا توجد ألعاب مطابقة.</div>';
    $("#digital-products").innerHTML = products.filter(filter).slice(0, 80).map((row) => digitalItemButton("product", row)).join("")
      || '<div class="service-muted">لا توجد خدمات مطابقة.</div>';
    root.querySelectorAll("[data-digital-kind]").forEach((button) => {
      button.addEventListener("click", () => loadDigitalQuotes(button.dataset.digitalKind, button.dataset.digitalId));
    });
  };
  $("#digital-search").addEventListener("input", renderItems);
  root.querySelector("[data-digital-refresh]").addEventListener("click", loadDigitalWorkspace);
  renderItems();
}

function digitalItemButton(kind, row) {
  const name = localized(row.label, row.name || row.title || row.id);
  const meta = localized(row.category_label, row.category || row.provider || kind);
  return `
    <button class="mini-card" type="button" data-digital-kind="${esc(kind)}" data-digital-id="${esc(row.id)}">
      <strong>${esc(name)}</strong>
      <span>${esc(meta)}</span>
    </button>`;
}

async function loadDigitalQuotes(kind, id) {
  const detail = $("#digital-detail");
  detail.innerHTML = `<div class="service-loader">جاري تحميل الباقات...</div>`;
  try {
    const path = `/api/v1/digital/quotes?kind=${encodeURIComponent(kind)}&${kind === "game" ? "game_id" : "product_id"}=${encodeURIComponent(id)}`;
    const payload = await api(path);
    renderDigitalQuotes(kind, id, payload);
  } catch (error) {
    detail.innerHTML = `<div class="service-empty">${esc(error.message)}</div>`;
  }
}

function renderDigitalQuotes(kind, id, payload) {
  const detail = $("#digital-detail");
  const offers = payload.offers || payload.items || [];
  const title = localized(payload.product?.label || payload.game?.label, payload.product?.name || payload.game?.name || id);
  detail.innerHTML = `
    <div class="service-detail-head">
      <div><h4>${esc(title)}</h4><span>${kind === "game" ? "Game top-up" : "Digital product"}</span></div>
    </div>
    <div class="quote-list">
      ${offers.length ? offers.map((offer, index) => digitalOfferHtml(kind, offer, index)).join("") : '<div class="service-empty">لا توجد باقات متاحة حالياً.</div>'}
    </div>`;
  detail.querySelectorAll("[data-digital-offer]").forEach((button) => {
    button.addEventListener("click", () => renderDigitalOrderForm(kind, offers[Number(button.dataset.digitalOffer)], () => renderDigitalQuotes(kind, id, payload)));
  });
}

function digitalOfferHtml(kind, offer, index) {
  const name = offer.item_name || offer.name || offer.title || offer.package_name || "Package";
  const price = offer.sale_price_label || offer.price_label || (offer.sale_price ? `$${Number(offer.sale_price).toFixed(2)}` : "-");
  return `
    <button class="quote-row" type="button" data-digital-offer="${index}">
      <div><strong>${esc(name)}</strong><span>${esc(offer.duration || offer.provider || kind)}</span></div>
      <b>${esc(price)}</b>
    </button>`;
}

function renderDigitalOrderForm(kind, offer, back) {
  const detail = $("#digital-detail");
  const fallback = kind === "game"
    ? [{ id: "player_id", label: "Player ID", required: true }, { id: "server_id", label: "Server ID", required: false }]
    : [{ id: "account", label: "بيانات الحساب", required: true }];
  detail.innerHTML = `
    <form class="service-order-form" id="digital-order-form">
      <div class="service-detail-head">
        <div><h4>${esc(offer.item_name || offer.name || "تأكيد الطلب")}</h4><span>${esc(offer.sale_price_label || offer.price_label || "")}</span></div>
        <button class="secondary compact" type="button" data-back-quotes>رجوع</button>
      </div>
      ${fieldsFormHtml(offer.input_fields, fallback)}
      <p class="message">سيتم خصم قيمة الطلب من محفظتك بعد التأكيد.</p>
      <button class="primary" type="submit">تأكيد الطلب</button>
      <p class="message" id="digital-order-message"></p>
    </form>`;
  detail.querySelector("[data-back-quotes]").addEventListener("click", back);
  $("#digital-order-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = $("#digital-order-message");
    message.textContent = "";
    const values = fieldData(event.currentTarget);
    const body = kind === "game"
      ? { quote_token: offer.quote_token, player_id: values.player_id, server_id: values.server_id, customer_data: values }
      : { quote_token: offer.quote_token, customer_data: values };
    try {
      const result = await api("/api/v1/digital/orders", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey("digital") },
        body: JSON.stringify(body),
      });
      message.textContent = `تم إنشاء الطلب: ${result.order?.id || ""}`;
      await loadDashboard();
    } catch (error) {
      message.textContent = error.message;
    }
  });
}

async function loadNumbersWorkspace() {
  serviceLoading("جاري تحميل خدمات الأرقام...");
  try {
    const payload = await api("/api/v1/numbers/catalog/bootstrap");
    renderNumbersCatalog(payload);
  } catch (error) {
    serviceError(error.message, loadNumbersWorkspace);
  }
}

function renderNumbersCatalog(payload) {
  const root = serviceRoot();
  const services = payload.services || [];
  const countries = payload.countries || [];
  const states = payload.states_us || [];
  const modes = payload.modes || [];
  root.innerHTML = `
    <form class="numbers-picker" id="numbers-picker">
      <label><span>نوع الرقم</span><select name="mode">${modes.map((row) => `<option value="${esc(row.key)}">${esc(localized(row.label, row.key))}</option>`).join("")}</select></label>
      <label><span>الخدمة</span><select name="service">${services.map((row) => `<option value="${esc(row.key)}">${esc(localized(row.label, row.name || row.key))}</option>`).join("")}</select></label>
      <label><span>الدولة</span><select name="country">${countries.map((row) => `<option value="${esc(row.code)}">${esc(localized(row.label, row.name || row.code))}</option>`).join("")}</select></label>
      <label><span>الولاية</span><select name="state">${states.map((row) => `<option value="${esc(row.code)}">${esc(localized(row.label, row.name || row.code))}</option>`).join("")}</select></label>
      <button class="primary" type="submit">عرض الأسعار</button>
    </form>
    <div id="numbers-quotes" class="quote-list"><div class="service-empty">اختر الخدمة والدولة لعرض الأسعار.</div></div>`;
  const serviceSelect = root.querySelector("[name='service']");
  const preferred = [...serviceSelect.options].find((option) => option.value === "telegram") || serviceSelect.options[0];
  if (preferred) serviceSelect.value = preferred.value;
  const countrySelect = root.querySelector("[name='country']");
  if ([...countrySelect.options].some((option) => option.value === "1")) countrySelect.value = "1";
  $("#numbers-picker").addEventListener("submit", loadNumbersQuotes);
}

async function loadNumbersQuotes(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = fieldData(form);
  const target = $("#numbers-quotes");
  target.innerHTML = '<div class="service-loader">جاري تحميل الأسعار...</div>';
  const params = new URLSearchParams(values);
  try {
    const payload = await api(`/api/v1/numbers/quotes?${params.toString()}`);
    renderNumbersQuotes(payload);
  } catch (error) {
    target.innerHTML = `<div class="service-empty">${esc(error.message)}</div>`;
  }
}

function renderNumbersQuotes(payload) {
  const target = $("#numbers-quotes");
  const rows = [];
  (payload.providers || []).forEach((provider) => {
    if (Array.isArray(provider.options)) {
      provider.options.forEach((option) => rows.push({ ...option, provider: provider.provider, provider_id: provider.provider_id }));
    } else {
      rows.push(provider);
    }
  });
  target.innerHTML = rows.length ? rows.map((row, index) => `
    <button class="quote-row" type="button" data-number-offer="${index}">
      <div><strong>${esc(row.provider || row.provider_id || "Provider")}</strong><span>${esc(row.duration_label || payload.mode || "")}</span></div>
      <b>${esc(row.price_label || (row.price ? `$${Number(row.price).toFixed(2)}` : "-"))}</b>
    </button>`).join("") : '<div class="service-empty">لا توجد أسعار متاحة حالياً.</div>';
  target.querySelectorAll("[data-number-offer]").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = rows[Number(button.dataset.numberOffer)];
      button.disabled = true;
      try {
        const result = await api("/api/v1/numbers/orders", {
          method: "POST",
          headers: { "Idempotency-Key": idempotencyKey("numbers") },
          body: JSON.stringify({ quote_token: row.quote_token, language: "ar" }),
        });
        target.insertAdjacentHTML("afterbegin", `<div class="notice">تم إنشاء الطلب: ${esc(result.order?.id || "")}</div>`);
        await loadDashboard();
      } catch (error) {
        target.insertAdjacentHTML("afterbegin", `<div class="notice error">${esc(error.message)}</div>`);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function openPanel(view, title = "") {
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  document.querySelectorAll(".app-view").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.panel === view);
  });
  if (title) setText("#view-title", title);
}

function openService(service) {
  const serviceMap = {
    digital: {
      title: "منتجات رقمية",
      kicker: "DIGITAL PRODUCTS",
      load: loadDigitalWorkspace,
    },
    numbers: {
      title: "أرقام",
      kicker: "NUMBERS SERVICE",
      load: loadNumbersWorkspace,
    },
  };
  const config = serviceMap[service];
  if (!config) return;
  setWorkspaceTheme(service);
  setText("#workspace-title", config.title);
  setText("#workspace-kicker", config.kicker);
  openPanel("workspace", config.title);
  config.load();
}

document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
  button.addEventListener("click", () => {
    const view = button.dataset.view;
    if (view !== "workspace" && serviceRoot()) {
      serviceRoot().innerHTML = "";
      setWorkspaceTheme("");
    }
    openPanel(view, button.textContent.trim());
  });
});

document.querySelectorAll("[data-open-service]").forEach((button) => {
  button.addEventListener("click", () => openService(button.dataset.openService));
});

$("#workspace-close")?.addEventListener("click", () => {
  if (serviceRoot()) serviceRoot().innerHTML = "";
  setWorkspaceTheme("");
  openPanel("home", "الخدمات");
});

$("#cardex-link")?.addEventListener("click", (event) => {
  if (event.currentTarget.classList.contains("locked")) event.preventDefault();
});

$("#refresh-orders")?.addEventListener("click", loadDashboard);

sendEmailCodeButton.addEventListener("click", async () => {
  await sendEmailCode({
    button: sendEmailCodeButton,
    codeRow: $("#email-code-row"),
    message: accountMessage,
  });
});

verifyEmailCodeButton.addEventListener("click", async () => {
  await verifyEmailCode({
    button: verifyEmailCodeButton,
    input: $("#email-code"),
    message: accountMessage,
  });
});

verifySendEmailCodeButton.addEventListener("click", async () => {
  await sendEmailCode({
    button: verifySendEmailCodeButton,
    codeRow: $("#verify-code-row"),
    message: $("#verify-message"),
  });
});

verifyEmailCodeSubmit.addEventListener("click", async () => {
  await verifyEmailCode({
    button: verifyEmailCodeSubmit,
    input: $("#verify-email-code-input"),
    message: $("#verify-message"),
  });
});

$("#identity-form")?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  try {
    const data = await api("/api/v1/auth/identity", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(formData.entries())),
    });
    currentAccount.identity_status = data.status;
    applyIdentityState(data.status);
  } catch (error) {
    accountMessage.textContent = error.message;
  }
});

function setMode(nextMode) {
  mode = nextMode;
  formError.textContent = "";
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.mode === mode));
  setText("#form-title", mode === "login" ? "أهلا بعودتك" : "إنشاء حساب جديد");
  setText("#form-subtitle", mode === "login"
    ? "أدخل بريدك وكلمة المرور للمتابعة."
    : "استخدم بريدا تستطيع الوصول إليه وكلمة مرور قوية.");
  submitButton.textContent = mode === "login" ? "تسجيل الدخول" : "إنشاء الحساب";
  passwordInput.autocomplete = mode === "login" ? "current-password" : "new-password";
}

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));

$("#toggle-password").addEventListener("click", (event) => {
  const visible = passwordInput.type === "text";
  passwordInput.type = visible ? "password" : "text";
  event.currentTarget.textContent = visible ? "إظهار" : "إخفاء";
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";
  if (!form.reportValidity()) return;
  submitButton.disabled = true;
  try {
    const data = await api(`/api/v1/auth/${mode}`, {
      method: "POST",
      body: JSON.stringify({ email: emailInput.value.trim(), password: passwordInput.value }),
    });
    passwordInput.value = "";
    showAccount(data.account);
  } catch (error) {
    formError.textContent = error.message === "invalid credentials"
      ? "البريد أو كلمة المرور غير صحيحة."
      : error.message;
  } finally {
    submitButton.disabled = false;
  }
});

telegramAction.addEventListener("click", async () => {
  accountMessage.textContent = "";
  try {
    if (currentAccount.telegram_linked) {
      await api("/api/v1/auth/telegram/link", { method: "DELETE" });
      const data = await api("/api/v1/auth/me");
      showAccount(data.account);
      accountMessage.textContent = "تم فك ربط Telegram.";
      return;
    }
    const data = await api("/api/v1/auth/telegram/link", { method: "POST" });
    if (!data.telegram_url) throw new Error("رابط Telegram غير متوفر حاليا.");
    window.location.href = data.telegram_url;
  } catch (error) {
    accountMessage.textContent = error.message;
  }
});

async function logout() {
  await api("/api/v1/auth/logout", { method: "POST" });
  window.location.reload();
}

$("#logout-button").addEventListener("click", logout);
$("#verify-logout-button").addEventListener("click", logout);

api("/api/v1/auth/me").then((data) => showAccount(data.account)).catch(() => {});
