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
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = { ...(isFormData ? {} : { "Content-Type": "application/json" }), ...(options.headers || {}) };
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
  document.querySelectorAll(".owner-nav").forEach((item) => { item.hidden = !account.is_owner; });
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
      ...digitalRows.map((row) => ({ ...row, channel: "رقمي", channel_key: "digital" })),
      ...numberRows.map((row) => ({ ...row, channel: "أرقام", channel_key: "numbers" })),
    ]);
    loadAccountExtras();
  } catch (error) {
    activity.textContent = "تعذر تحميل بيانات الحساب حاليا.";
  }
}

async function loadAccountExtras() {
  const rechargeTarget = $("#recharge-list");
  const supportTarget = $("#support-list");
  try {
    const [recharge, support] = await Promise.all([
      api("/api/v1/numbers/recharge"),
      api("/api/v1/numbers/support"),
    ]);
    renderRechargeOptions(recharge);
    renderSupportOptions(support);
  } catch (error) {
    if (rechargeTarget) rechargeTarget.textContent = "تعذر تحميل طرق الشحن حاليا.";
    if (supportTarget) supportTarget.textContent = "تعذر تحميل خيارات الدعم حاليا.";
  }
}

function renderRechargeOptions(payload) {
  const target = $("#recharge-list");
  const methods = payload.methods || [];
  const canSubmitProof = Boolean(payload.capabilities?.submit_recharge_proof);
  const options = methods.map((method) => `<option value="${esc(method.code)}">${esc(method.title || method.code)}</option>`).join("");
  const form = canSubmitProof && methods.length ? `
    <form class="recharge-submit-form" id="recharge-submit-form">
      <label><span>طريقة الدفع</span><select name="method_code" required>${options}</select></label>
      <label><span>المبلغ المدفوع</span><input name="paid_amount" inputmode="decimal" required placeholder="0.00"></label>
      <label><span>إثبات الدفع</span><input name="proof" type="file" accept="image/*,.pdf" required></label>
      <input name="language" type="hidden" value="ar">
      <button class="primary compact" type="submit">إرسال طلب الشحن</button>
      <p class="message" id="recharge-submit-message"></p>
    </form>` : "";
  renderRows(target, methods, (method) => `
    <div class="payment-method-row">
      <div>
        <strong>${esc(method.title || method.code || "طريقة دفع")}</strong>
        <span>${esc(method.rate_label || "")}</span>
      </div>
      <div class="payment-target">
        <span>بيانات الدفع</span>
        <code>${esc(method.target || "-")}</code>
      </div>
      ${method.instructions ? `<p>${esc(method.instructions)}</p>` : ""}
      ${method.support ? `<small>الدعم: ${esc(method.support)}</small>` : ""}
    </div>`);
  if (!methods.length) target.textContent = "لا توجد طرق شحن متاحة حالياً.";
  else if (canSubmitProof) {
    target.insertAdjacentHTML("afterbegin", form);
    $("#recharge-submit-form")?.addEventListener("submit", submitRechargeProof);
  } else {
    target.insertAdjacentHTML("afterbegin", '<div class="notice">يمكنك نسخ بيانات الدفع من هنا. إرسال إثبات الدفع من الموقع غير مفعّل بعد، لذلك أرسل الإثبات عبر Telegram أو الدعم بعد التحويل.</div>');
  }
}

async function submitRechargeProof(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const message = $("#recharge-submit-message");
  const button = form.querySelector("button[type='submit']");
  message.textContent = "جاري إرسال طلب الشحن...";
  button.disabled = true;
  try {
    const data = new FormData(form);
    const result = await api("/api/v1/numbers/recharge/submit", {
      method: "POST",
      body: data,
      timeoutMs: 45000,
    });
    message.textContent = result.message || "تم إرسال طلب الشحن.";
    form.reset();
    await loadDashboard();
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

function renderSupportOptions(payload) {
  const target = $("#support-list");
  const rows = payload.categories || [];
  const submitEnabled = Boolean(payload.actions?.submit_ticket?.enabled);
  const categoryMeta = {
    numbers: { icon: "📱", description: "مشاكل الطلبات، الأكواد، الأرقام المؤقتة والإيجار." },
    services: { icon: "🎮", description: "طلبات المنتجات الرقمية، الشحن، والأسعار." },
    user_balance: { icon: "💳", description: "شحن الرصيد، الدفعات، والاستردادات." },
  };
  renderRows(target, rows, (row) => `
    <div class="support-category">
      <span class="support-category-icon">${categoryMeta[row.key]?.icon || "💬"}</span>
      <div>
        <strong>${esc(row.label || row.key || "Support")}</strong>
        <span>${esc(categoryMeta[row.key]?.description || "تواصل مع فريق الدعم.")}</span>
      </div>
      <b>${submitEnabled ? "فتح تذكرة" : "قريباً"}</b>
    </div>`);
  if (!rows.length) target.textContent = "لا توجد قنوات دعم مفعّلة حالياً.";
  else if (!submitEnabled) {
    target.insertAdjacentHTML("beforeend", '<div class="notice support-roadmap">نعمل على صندوق تذاكر داخل الموقع ليستقبل ردود الدعم مباشرة، بدون اشتراط ربط Telegram.</div>');
  }
}

const ownerMetricLabels = {
  website_accounts: "حسابات الموقع",
  verified_accounts: "حسابات مؤكدة",
  pending_identity: "هويات قيد المراجعة",
  pending_user_topups: "شحن مستخدمين معلق",
  pending_reseller_topups: "شحن وكلاء معلق",
  open_support_tickets: "تذاكر دعم مفتوحة",
  open_numbers_orders: "طلبات أرقام مفتوحة",
  pending_digital_orders: "طلبات رقمية معلقة",
  active_bots: "بوتات فعالة",
};

const ownerStatusLabels = {
  available: "جاهز",
  read_only: "قراءة فقط",
  telegram_only: "داخل Telegram",
  miniapp: "Mini App",
};

const ownerQueueLabels = {
  recharge: "طلبات شحن الرصيد",
  identity: "تأكيد الهوية",
  digital: "الطلبات الرقمية اليدوية",
  support: "تذاكر الدعم",
};

async function loadOwnerDashboard() {
  const metricsTarget = $("#owner-metrics");
  const queuesTarget = $("#owner-queues");
  const sectionsTarget = $("#owner-sections");
  const message = $("#owner-message");
  if (!currentAccount?.is_owner) return;
  message.textContent = "";
  try {
    const digitalFilter = $("#owner-digital-filter")?.value || "pending";
    const showResolvedReviews = $("#owner-refunds-resolved")?.checked ? "1" : "0";
    const rechargeFilter = $("#owner-recharge-filter")?.value || "pending";
    const identityFilter = $("#owner-identity-filter")?.value || "pending";
    const supportFilter = $("#owner-support-filter")?.value || "open";
    const [payload, queuePayload, digitalPayload, refundPayload, settingsPayload, rechargePayload, identityPayload, supportPayload, apiKeysPayload, webhooksPayload, providerPayload, providerEventsPayload, botsPayload] = await Promise.all([
      api("/api/v1/owner/dashboard"),
      api("/api/v1/owner/queues"),
      api(`/api/v1/owner/digital/orders?status=${encodeURIComponent(digitalFilter)}&limit=30`),
      api(`/api/v1/owner/numbers/refund-reviews?include_resolved=${showResolvedReviews}&limit=30`),
      api("/api/v1/owner/settings"),
      api(`/api/v1/owner/recharge-reviews?status=${encodeURIComponent(rechargeFilter)}&limit=30`),
      api(`/api/v1/owner/identity-reviews?status=${encodeURIComponent(identityFilter)}&limit=30`),
      api(`/api/v1/owner/support-tickets?status=${encodeURIComponent(supportFilter)}&limit=30`),
      api("/api/v1/owner/api-keys?status=all&limit=30"),
      api("/api/v1/owner/webhooks?status=all&limit=30"),
      api("/api/v1/owner/provider-readiness"),
      api("/api/v1/owner/provider-webhook-events?limit=12"),
      api("/api/v1/owner/bots?status=all&limit=30"),
    ]);
    const metrics = Object.entries(payload.metrics || {});
    metricsTarget.classList.toggle("empty", !metrics.length);
    metricsTarget.innerHTML = metrics.map(([key, value]) => `
      <div class="owner-metric">
        <span>${esc(ownerMetricLabels[key] || key)}</span>
        <strong>${esc(value)}</strong>
      </div>`).join("");
    const queues = Object.entries(queuePayload.queues || {});
    queuesTarget.classList.toggle("empty", !queues.length);
    queuesTarget.innerHTML = queues.map(([key, rows]) => `
      <section class="owner-queue">
        <div class="owner-queue-head"><strong>${esc(ownerQueueLabels[key] || key)}</strong><b>${esc(rows.length)}</b></div>
        <div class="owner-queue-list">
          ${rows.length ? rows.map((row) => `
            <div class="owner-queue-row">
              <div><strong>${esc(row.title || row.id)}</strong><span>${esc(row.detail || "")}</span></div>
              <b>${esc(row.status || "")}</b>
            </div>`).join("") : '<span class="owner-queue-empty">لا توجد عناصر معلقة.</span>'}
        </div>
      </section>`).join("");
    renderOwnerDigitalOrders(digitalPayload.orders || []);
    renderOwnerRefundReviews(refundPayload.reviews || []);
    renderOwnerSettings(settingsPayload);
    renderOwnerRechargeReviews(rechargePayload.reviews || []);
    renderOwnerIdentityReviews(identityPayload.reviews || []);
    renderOwnerSupportTickets(supportPayload.tickets || []);
    renderOwnerApiTools(apiKeysPayload, webhooksPayload);
    renderOwnerProviderDiagnostics(providerPayload.providers || [], providerEventsPayload.events || []);
    renderOwnerBotTools(botsPayload.bots || []);
    const sections = payload.sections || [];
    sectionsTarget.classList.toggle("empty", !sections.length);
    sectionsTarget.innerHTML = sections.map((section) => `
      <section class="owner-section">
        <h4>${esc(section.title || section.key)}</h4>
        <div class="owner-action-list">
          ${(section.items || []).map((item) => `
            <div class="owner-action-row">
              <div><strong>${esc(item.title || item.key)}</strong><span>${esc(item.endpoint || "سيتم نقل الإجراء للموقع")}</span></div>
              <b data-owner-status="${esc(item.status || "")}">${esc(ownerStatusLabels[item.status] || item.status)}</b>
            </div>`).join("")}
        </div>
      </section>`).join("");
  } catch (error) {
    metricsTarget.textContent = "تعذر تحميل مؤشرات المالك.";
    queuesTarget.textContent = "تعذر تحميل طوابير المتابعة.";
    $("#owner-digital-orders").textContent = "تعذر تحميل الطلبات الرقمية.";
    $("#owner-refund-reviews").textContent = "تعذر تحميل مراجعات الأرقام.";
    $("#owner-finance-settings").textContent = "تعذر تحميل الإعدادات المالية.";
    $("#owner-routing-settings").textContent = "تعذر تحميل إعدادات التوجيه.";
    $("#owner-payment-methods").textContent = "تعذر تحميل طرق الدفع.";
    $("#owner-recharge-reviews").textContent = "تعذر تحميل مراجعات الشحن.";
    $("#owner-identity-reviews").textContent = "تعذر تحميل مراجعات الهوية.";
    $("#owner-support-tickets").textContent = "تعذر تحميل تذاكر الدعم.";
    $("#owner-api-tools").textContent = "تعذر تحميل أدوات API.";
    $("#owner-provider-diagnostics").textContent = "تعذر تحميل تشخيص المزودين.";
    $("#owner-bot-tools").textContent = "تعذر تحميل أدوات البوتات.";
    sectionsTarget.textContent = "تعذر تحميل خصائص الإدارة.";
    message.textContent = error.message;
  }
}

function renderOwnerApiTools(keysPayload, webhooksPayload) {
  const keyScopes = keysPayload.scopes || [];
  const webhookEvents = webhooksPayload.events || [];
  const keys = keysPayload.keys || [];
  const hooks = webhooksPayload.webhooks || [];
  const target = $("#owner-api-tools");
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <h4>إنشاء API Key</h4>
      <form class="owner-review-form" id="owner-api-key-form">
        <label><span>الاسم</span><input name="name" placeholder="Client name"></label>
        <label><span>Reseller ID</span><input name="reseller_id" inputmode="numeric" placeholder="اتركه للمالك"></label>
        <label><span>User ID</span><input name="user_id" inputmode="numeric" placeholder="اتركه للمالك"></label>
        <label><span>Scopes</span><select name="scopes" multiple size="5">${keyScopes.map((scope) => `<option value="${esc(scope)}">${esc(scope)}</option>`).join("")}</select></label>
        <div class="owner-order-actions"><button class="primary compact" type="submit">إنشاء المفتاح</button></div>
      </form>
      <div id="owner-api-secret" class="notice" hidden></div>
    </article>
    <article class="owner-review-card">
      <h4>مفاتيح API</h4>
      ${keys.length ? keys.map((key) => `<div class="owner-action-row"><div><strong>${esc(key.name || key.prefix)}</strong><span>${esc(key.prefix)} · ${esc((key.scopes || []).join(", "))}</span></div><b>${esc(key.status)}</b>${key.status === "active" ? `<button class="danger compact" data-owner-api-key="${esc(key.id)}">إلغاء</button>` : ""}</div>`).join("") : '<div class="notice">لا توجد مفاتيح API.</div>'}
    </article>
    <article class="owner-review-card">
      <h4>إنشاء Webhook</h4>
      <form class="owner-review-form" id="owner-webhook-form">
        <label><span>URL</span><input name="url" type="url" placeholder="https://example.com/webhook"></label>
        <label><span>Reseller ID</span><input name="reseller_id" inputmode="numeric" placeholder="اتركه للمالك"></label>
        <label><span>User ID</span><input name="user_id" inputmode="numeric" placeholder="اتركه للمالك"></label>
        <label><span>Events</span><select name="events" multiple size="4">${webhookEvents.map((event) => `<option value="${esc(event)}">${esc(event)}</option>`).join("")}</select></label>
        <div class="owner-order-actions"><button class="primary compact" type="submit">إنشاء webhook</button></div>
      </form>
      <div id="owner-webhook-secret" class="notice" hidden></div>
    </article>
    <article class="owner-review-card">
      <h4>Webhooks</h4>
      ${hooks.length ? hooks.map((hook) => `<div class="owner-action-row"><div><strong>${esc(hook.url)}</strong><span>${esc((hook.events || []).join(", "))}</span></div><b>${esc(hook.status)}</b>${hook.status === "active" ? `<button class="danger compact" data-owner-webhook="${esc(hook.id)}">إلغاء</button>` : ""}</div>`).join("") : '<div class="notice">لا توجد webhooks.</div>'}
    </article>`;
  $("#owner-api-key-form")?.addEventListener("submit", createOwnerApiKey);
  $("#owner-webhook-form")?.addEventListener("submit", createOwnerWebhook);
  target.querySelectorAll("[data-owner-api-key]").forEach((button) => button.addEventListener("click", () => revokeOwnerApiKey(button)));
  target.querySelectorAll("[data-owner-webhook]").forEach((button) => button.addEventListener("click", () => revokeOwnerWebhook(button)));
}

function selectedValues(select) {
  return Array.from(select?.selectedOptions || []).map((option) => option.value);
}

async function createOwnerApiKey(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  body.scopes = selectedValues(form.elements.scopes);
  try {
    const result = await api("/api/v1/owner/api-keys", {method: "POST", body: JSON.stringify(body)});
    const box = $("#owner-api-secret");
    box.hidden = false;
    box.textContent = `API key يظهر مرة واحدة فقط: ${result.api_key}`;
    setText("#owner-message", "تم إنشاء المفتاح. احفظه الآن لأنه لن يظهر مرة ثانية.");
  } catch (error) { setText("#owner-message", error.message); }
}

async function createOwnerWebhook(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  body.events = selectedValues(form.elements.events);
  try {
    const result = await api("/api/v1/owner/webhooks", {method: "POST", body: JSON.stringify(body)});
    const box = $("#owner-webhook-secret");
    box.hidden = false;
    box.textContent = `Webhook secret يظهر مرة واحدة فقط: ${result.secret}`;
    setText("#owner-message", "تم إنشاء webhook. احفظ السر الآن لأنه لن يظهر مرة ثانية.");
  } catch (error) { setText("#owner-message", error.message); }
}

async function revokeOwnerApiKey(button) {
  if (!window.confirm("إلغاء هذا المفتاح؟")) return;
  await api(`/api/v1/owner/api-keys/${encodeURIComponent(button.dataset.ownerApiKey)}/revoke`, {method: "POST"});
  await loadOwnerDashboard();
}

async function revokeOwnerWebhook(button) {
  if (!window.confirm("إلغاء هذا webhook؟")) return;
  await api(`/api/v1/owner/webhooks/${encodeURIComponent(button.dataset.ownerWebhook)}/revoke`, {method: "POST"});
  await loadOwnerDashboard();
}

function renderOwnerProviderDiagnostics(providers, events) {
  const target = $("#owner-provider-diagnostics");
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <h4>جاهزية المزودين</h4>
      ${providers.map((provider) => `<div class="owner-action-row"><div><strong>${esc(provider.provider)}</strong><span>${esc(provider.reason || "")}</span></div><b>${esc(provider.status)}</b></div>`).join("") || '<div class="notice">لا توجد بيانات جاهزية.</div>'}
    </article>
    <article class="owner-review-card">
      <h4>آخر provider webhooks</h4>
      ${events.map((event) => `<div class="owner-action-row"><div><strong>${esc(event.provider)} · ${esc(event.event_type)}</strong><span>${esc(event.provider_order_id)} · ${esc(event.reason || event.created_at || "")}</span></div><b>${esc(event.status)}</b><button class="secondary compact" data-provider-event="${esc(event.id)}">Replay</button></div>`).join("") || '<div class="notice">لا توجد أحداث webhook حديثة.</div>'}
    </article>`;
  target.querySelectorAll("[data-provider-event]").forEach((button) => button.addEventListener("click", () => replayOwnerProviderEvent(button)));
}

async function replayOwnerProviderEvent(button) {
  if (!window.confirm("إعادة تشغيل هذا الحدث قد يغير حالة الطلب المرتبط. متابعة؟")) return;
  try {
    await api(`/api/v1/owner/provider-webhook-events/${encodeURIComponent(button.dataset.providerEvent)}/replay`, {method: "POST"});
    setText("#owner-message", "تم تنفيذ replay للحدث.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerBotTools(bots) {
  const target = $("#owner-bot-tools");
  target.classList.remove("empty");
  target.innerHTML = `
    <article class="owner-review-card">
      <h4>بث عبر بوت المنصة</h4>
      <form class="owner-review-form" id="owner-broadcast-form">
        <label><span>Chat ID</span><input name="chat_id" required inputmode="numeric" placeholder="-100..."></label>
        <label><span>Topic ID</span><input name="message_thread_id" inputmode="numeric" placeholder="اختياري"></label>
        <label><span>نص البث</span><textarea name="text" required minlength="2" maxlength="3500" rows="3" placeholder="اكتب الرسالة التي ستصل للقناة أو المجموعة"></textarea></label>
        <div class="owner-order-actions"><button class="primary compact" type="submit">إرسال البث</button></div>
      </form>
    </article>
    <article class="owner-review-card">
      <h4>إيداع رصيد وكيل</h4>
      <form class="owner-review-form" id="owner-reseller-deposit-form">
        <label><span>Reseller ID</span><input name="reseller_id" required inputmode="numeric"></label>
        <label><span>المبلغ</span><input name="amount" required type="number" min="0.01" max="10000000" step="0.01"></label>
        <label><span>ملاحظة</span><input name="note" maxlength="300" placeholder="اختياري"></label>
        <div class="owner-order-actions"><button class="primary compact" type="submit">إضافة الرصيد</button></div>
      </form>
    </article>
    <article class="owner-review-card">
      <h4>بوتات الوكلاء والاشتراكات</h4>
      ${bots.length ? bots.map((bot) => {
        const sub = bot.subscription || {};
        return `<div class="owner-action-row owner-bot-row">
          <div>
            <strong>${esc(bot.username || `Bot ${bot.bot_id}`)}</strong>
            <span>owner ${esc(bot.owner_id)} · ${esc(bot.active ? "active" : "inactive")} · ${esc(sub.status || "-")} · end ${esc(sub.subscription_ends_at || "-")}</span>
          </div>
          <form class="owner-inline-action" data-owner-bot="${esc(bot.bot_id)}">
            <select name="months">
              <option value="1" ${sub.renewal_plan_months === 1 ? "selected" : ""}>1 شهر</option>
              <option value="6" ${sub.renewal_plan_months === 6 ? "selected" : ""}>6 أشهر</option>
              <option value="12" ${sub.renewal_plan_months === 12 ? "selected" : ""}>12 شهر</option>
            </select>
            <input name="note" placeholder="ملاحظة">
            <button class="secondary compact" name="action" value="sync">Sync</button>
            <button class="secondary compact" name="action" value="set_plan">حفظ الخطة</button>
            <button class="primary compact" name="action" value="activate">تفعيل</button>
          </form>
        </div>`;
      }).join("") : '<div class="notice">لا توجد بوتات مسجلة حاليا.</div>'}
    </article>`;
  $("#owner-broadcast-form")?.addEventListener("submit", sendOwnerBroadcastForm);
  $("#owner-reseller-deposit-form")?.addEventListener("submit", createOwnerResellerDeposit);
  target.querySelectorAll("[data-owner-bot]").forEach((form) => form.addEventListener("submit", runOwnerBotSubscriptionAction));
}

async function sendOwnerBroadcastForm(event) {
  event.preventDefault();
  const form = event.currentTarget;
  if (!window.confirm("سيتم إرسال هذه الرسالة فعليا عبر بوت المنصة. متابعة؟")) return;
  const body = Object.fromEntries(new FormData(form).entries());
  try {
    await api("/api/v1/owner/broadcast", {method: "POST", body: JSON.stringify(body)});
    setText("#owner-message", "تم إرسال البث.");
    form.reset();
  } catch (error) { setText("#owner-message", error.message); }
}

async function createOwnerResellerDeposit(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  if (!window.confirm(`سيتم إضافة ${body.amount || 0} إلى محفظة الوكيل ${body.reseller_id || ""}. متابعة؟`)) return;
  try {
    await api("/api/v1/owner/reseller-deposits", {method: "POST", body: JSON.stringify(body)});
    setText("#owner-message", "تم إضافة رصيد الوكيل.");
    form.reset();
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

async function runOwnerBotSubscriptionAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "sync";
  const body = Object.fromEntries(new FormData(form).entries());
  body.action = action;
  if (action === "activate" && !window.confirm("سيتم تمديد اشتراك هذا البوت. متابعة؟")) return;
  try {
    await api(`/api/v1/owner/bots/${encodeURIComponent(form.dataset.ownerBot)}/subscription/action`, {method: "POST", body: JSON.stringify(body)});
    setText("#owner-message", "تم تحديث اشتراك البوت.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerRechargeReviews(rows) {
  const target = $("#owner-recharge-reviews");
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => `
    <article class="owner-review-card">
      <div class="owner-order-head"><div><strong>${esc(row.method || "طلب شحن")}</strong><span>${esc(row.id)}</span></div><b>${esc(row.status)}</b></div>
      <div class="owner-order-meta"><span>المستخدم: ${esc(row.user_id)}</span><span>المحفظة: ${esc(row.wallet_type)}</span><span>المبلغ: ${esc(row.amount)}</span><span>${row.has_proof ? "يوجد إثبات" : "بدون إثبات"}</span></div>
      ${row.decision_note ? `<div class="notice">${esc(row.decision_note)}</div>` : ""}
      ${row.status === "pending" ? `<form class="owner-review-form" data-owner-recharge="${esc(row.id)}">
        <label><span>المبلغ المقبول</span><input name="approved_amount" type="number" min="0.0001" step="0.0001" value="${esc(row.amount)}"></label>
        <label><span>ملاحظة</span><input name="note" placeholder="ملاحظة القرار أو طلب إثبات جديد"></label>
        <div class="owner-order-actions"><button class="primary compact" name="action" value="accept">قبول</button><button class="danger compact" name="action" value="reject">رفض</button><button class="secondary compact" name="action" value="need_more_proof">طلب إثبات</button></div>
      </form>` : ""}
    </article>`).join("") : '<div class="notice">لا توجد طلبات شحن ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-recharge]").forEach((form) => form.addEventListener("submit", runOwnerRechargeAction));
}

async function runOwnerRechargeAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "";
  const values = Object.fromEntries(new FormData(form).entries());
  if (action === "accept" && !window.confirm("سيتم إضافة الرصيد فعلياً إلى المحفظة. متابعة؟")) return;
  try {
    await api(`/api/v1/owner/recharge-reviews/${encodeURIComponent(form.dataset.ownerRecharge)}/action`, {method: "POST", body: JSON.stringify({...values, action})});
    setText("#owner-message", "تم تنفيذ إجراء طلب الشحن.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerIdentityReviews(rows) {
  const target = $("#owner-identity-reviews");
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => `
    <article class="owner-review-card">
      <div class="owner-order-head"><div><strong>${esc(row.full_name || "طلب هوية")}</strong><span>${esc(row.id)}</span></div><b>${esc(row.status)}</b></div>
      <div class="owner-order-meta"><span>العميل: ${esc(row.customer_id)}</span><span>${esc(row.country)}</span><span>${esc(row.id_type)}</span><span>${esc(row.birth_date)}</span></div>
      ${row.review_note ? `<div class="notice">${esc(row.review_note)}</div>` : ""}
      ${row.status === "pending" ? `<form class="owner-review-form" data-owner-identity="${esc(row.id)}">
        <label><span>ملاحظة المراجعة</span><input name="note" placeholder="سبب الرفض مطلوب عند الرفض"></label>
        <div class="owner-order-actions"><button class="primary compact" name="action" value="approve">قبول الهوية</button><button class="danger compact" name="action" value="reject">رفض الهوية</button></div>
      </form>` : ""}
    </article>`).join("") : '<div class="notice">لا توجد مراجعات هوية ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-identity]").forEach((form) => form.addEventListener("submit", runOwnerIdentityAction));
}

async function runOwnerIdentityAction(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const action = event.submitter?.value || "";
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    await api(`/api/v1/owner/identity-reviews/${encodeURIComponent(form.dataset.ownerIdentity)}/action`, {method: "POST", body: JSON.stringify({...values, action})});
    setText("#owner-message", "تم تنفيذ قرار الهوية.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
}

function renderOwnerSupportTickets(rows) {
  const target = $("#owner-support-tickets");
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((row) => `
    <article class="owner-review-card">
      <div class="owner-order-head"><div><strong>تذكرة #${esc(row.ticket_no)} · ${esc(row.category)}</strong><span>${esc(row.full_name || row.username || row.user_id)}</span></div><b>${esc(row.status)}</b></div>
      <div class="owner-order-meta"><span>المستخدم: ${esc(row.user_id)}</span><span>المصدر: ${esc(row.scope)}</span><span>عدد الرسائل: ${esc(row.payload_count)}</span><span>فرز الخطأ: ${esc(row.bug_triage?.status || "-")}</span></div>
      ${row.status !== "solved" ? `<form class="owner-support-reply" data-owner-support-reply="${esc(row.id)}"><input name="message" required minlength="2" maxlength="3500" placeholder="اكتب الرد الذي سيصل للمستخدم عبر البوت"><button class="secondary compact" type="submit">إرسال الرد</button></form>` : ""}
      <div class="owner-order-actions">
        ${row.status !== "solved" ? `<button class="primary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="solve">حل التذكرة</button>` : ""}
        <button class="secondary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="bug_confirmed">تأكيد الخطأ</button>
        <button class="secondary compact" data-owner-ticket="${esc(row.id)}" data-ticket-action="not_bug">ليس خطأ</button>
      </div>
    </article>`).join("") : '<div class="notice">لا توجد تذاكر دعم ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-ticket]").forEach((button) => button.addEventListener("click", () => runOwnerSupportAction(button)));
  target.querySelectorAll("[data-owner-support-reply]").forEach((form) => form.addEventListener("submit", runOwnerSupportReply));
}

async function runOwnerSupportReply(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await api(`/api/v1/owner/support-tickets/${encodeURIComponent(form.dataset.ownerSupportReply)}/action`, {method: "POST", body: JSON.stringify({action: "reply", message: form.elements.message.value})});
    setText("#owner-message", "تم إرسال الرد للمستخدم.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

async function runOwnerSupportAction(button) {
  button.disabled = true;
  try {
    await api(`/api/v1/owner/support-tickets/${encodeURIComponent(button.dataset.ownerTicket)}/action`, {method: "POST", body: JSON.stringify({action: button.dataset.ticketAction})});
    setText("#owner-message", "تم تحديث تذكرة الدعم.");
    await loadOwnerDashboard();
  } catch (error) { setText("#owner-message", error.message); }
  finally { button.disabled = false; }
}

function routingLabel(target) {
  if (!target?.bound) return "غير مربوط";
  return `${target.chat_id}${target.message_thread_id ? ` / topic ${target.message_thread_id}` : ""}`;
}

function routingForm(key, title, target) {
  return `<form class="owner-setting-card owner-routing-card" data-owner-routing="${esc(key)}">
    <div><strong>${esc(title)}</strong><span>${esc(routingLabel(target))}</span></div>
    <input name="chat_id" required inputmode="numeric" placeholder="Chat ID" value="${esc(target?.chat_id || "")}">
    <input name="message_thread_id" inputmode="numeric" placeholder="Topic ID" value="${esc(target?.message_thread_id || "")}">
    <button class="secondary compact" type="submit">حفظ</button>
  </form>`;
}

function renderOwnerSettings(payload) {
  const finance = payload.finance || {};
  const alerts = payload.alerts || {};
  const routing = payload.routing || {};
  const financeTarget = $("#owner-finance-settings");
  financeTarget.classList.remove("empty");
  financeTarget.innerHTML = `
    <form class="owner-setting-card" data-owner-setting="exchange_rate">
      <div><strong>سعر الصرف</strong><span>قيمة الدولار بالعملة المحلية</span></div>
      <input name="value" type="number" min="0.01" max="10000000" step="0.01" value="${esc(finance.exchange_rate || 0)}" required>
      <button class="secondary compact" type="submit">حفظ</button>
    </form>
    <form class="owner-setting-card" data-owner-setting="digital_markup_percent">
      <div><strong>هامش المنتجات الرقمية</strong><span>نسبة تضاف إلى سعر المزود</span></div>
      <input name="value" type="number" min="0" max="500" step="0.01" value="${esc(finance.digital_markup_percent || 0)}" required>
      <button class="secondary compact" type="submit">حفظ</button>
    </form>
    <div class="owner-setting-card">
      <div><strong>هامش الأرقام</strong><span>معطل مؤقتاً داخل محرك الأسعار</span></div>
      <b>${esc(finance.numbers_markup_percent || 0)}%</b>
    </div>`;

  const routingTarget = $("#owner-routing-settings");
  const support = routing.support || {};
  routingTarget.classList.remove("empty");
  routingTarget.innerHTML = `
    <form class="owner-setting-card" data-owner-setting="provider_alert_threshold">
      <div><strong>حد تنبيه رصيد المزود</strong><span>${routingLabel(routing.provider_alerts)}</span></div>
      <input name="value" type="number" min="0.01" max="10000" step="0.01" value="${esc(alerts.threshold_usd || 1)}" required>
      <button class="secondary compact" type="submit">حفظ</button>
    </form>
    <label class="owner-setting-card owner-setting-toggle">
      <div><strong>تنبيه رصيد المزود</strong><span>تشغيل أو إيقاف التنبيهات منخفضة الرصيد</span></div>
      <input id="owner-provider-alert-enabled" type="checkbox" ${alerts.enabled ? "checked" : ""}>
    </label>
    ${routingForm("owner_notifications", "إشعارات المالك", routing.owner_notifications)}
    ${routingForm("reseller_topups", "إشعارات شحن الوكلاء", routing.reseller_topups)}
    ${routingForm("logs", "سجلات النظام", routing.logs)}
    ${routingForm("provider_alerts", "تنبيهات رصيد المزود", routing.provider_alerts)}
    ${routingForm("support_numbers", "دعم الأرقام", support.numbers)}
    ${routingForm("support_services", "دعم الخدمات", support.services)}
    ${routingForm("support_user_balance", "دعم الرصيد", support.user_balance)}`;

  renderOwnerPaymentMethods(finance.payment_methods || []);
  document.querySelectorAll("[data-owner-setting]").forEach((form) => form.addEventListener("submit", saveOwnerSetting));
  document.querySelectorAll("[data-owner-routing]").forEach((form) => form.addEventListener("submit", saveOwnerRoutingTarget));
  $("#owner-provider-alert-enabled")?.addEventListener("change", saveOwnerAlertEnabled);
}

function renderOwnerPaymentMethods(methods) {
  const target = $("#owner-payment-methods");
  target.classList.toggle("empty", !methods.length);
  target.innerHTML = methods.length ? methods.map((method) => `
    <form class="owner-payment-method" data-owner-payment-method="${esc(method.code)}">
      <div class="owner-order-head">
        <div><strong>${esc(method.title || method.code)}</strong><span>${esc(method.code)}</span></div>
        <label class="owner-toggle"><input name="enabled" type="checkbox" ${method.enabled ? "checked" : ""}> مفعلة</label>
      </div>
      <div class="owner-payment-fields">
        <label><span>اسم الوسيلة</span><input name="title" value="${esc(method.title || "")}" required></label>
        <label><span>الحساب أو العنوان</span><input name="target" value="${esc(method.target || "")}" required></label>
        <label><span>الدعم</span><input name="support" value="${esc(method.support || "")}"></label>
        <label><span>العملة</span><select name="currency"><option value="SYP" ${method.currency === "SYP" ? "selected" : ""}>SYP</option><option value="USD" ${method.currency === "USD" ? "selected" : ""}>USD</option></select></label>
      </div>
      <label><span>تعليمات الدفع</span><textarea name="instructions" rows="3">${esc(method.instructions || "")}</textarea></label>
      <button class="secondary compact" type="submit">حفظ طريقة الدفع</button>
    </form>`).join("") : '<div class="notice">لا توجد طرق دفع معرفة.</div>';
  target.querySelectorAll("[data-owner-payment-method]").forEach((form) => form.addEventListener("submit", saveOwnerPaymentMethod));
}

async function saveOwnerSetting(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await api("/api/v1/owner/settings", {
      method: "PUT",
      body: JSON.stringify({ key: form.dataset.ownerSetting, value: Number(form.elements.value.value) }),
    });
    setText("#owner-message", "تم حفظ الإعداد.");
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

async function saveOwnerRoutingTarget(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  const body = Object.fromEntries(new FormData(form).entries());
  try {
    await api(`/api/v1/owner/routing-targets/${encodeURIComponent(form.dataset.ownerRouting)}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    setText("#owner-message", "تم حفظ وجهة التوجيه.");
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

async function saveOwnerAlertEnabled(event) {
  try {
    await api("/api/v1/owner/settings", {
      method: "PUT",
      body: JSON.stringify({ key: "provider_alert_enabled", value: event.currentTarget.checked }),
    });
    setText("#owner-message", "تم تحديث حالة التنبيه.");
  } catch (error) {
    event.currentTarget.checked = !event.currentTarget.checked;
    setText("#owner-message", error.message);
  }
}

async function saveOwnerPaymentMethod(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button[type='submit']");
  const values = Object.fromEntries(new FormData(form).entries());
  values.enabled = form.elements.enabled.checked;
  button.disabled = true;
  try {
    await api(`/api/v1/owner/payment-methods/${encodeURIComponent(form.dataset.ownerPaymentMethod)}`, {
      method: "PATCH",
      body: JSON.stringify(values),
    });
    setText("#owner-message", "تم حفظ طريقة الدفع.");
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

function renderOwnerRefundReviews(rows) {
  const target = $("#owner-refund-reviews");
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((review) => `
    <article class="owner-refund-review">
      <div class="owner-order-head">
        <div><strong>${esc(review.order?.service_name || review.order?.service || "طلب أرقام")}</strong><span>${esc(review.id || "")}</span></div>
        <b>${esc(review.status || "")}</b>
      </div>
      <div class="owner-order-meta">
        <span>السبب: ${esc(review.reason || "-")}</span>
        <span>حالة الطلب: ${esc(review.order?.public_status || review.order?.status || "-")}</span>
        <span>المزود: ${esc(review.order?.provider || "-")}</span>
      </div>
      ${review.status === "resolved" ? `
        <div class="notice">القرار: ${esc(review.resolution || "-")}${review.notes ? ` · ${esc(review.notes)}` : ""}</div>` : `
        <form class="owner-refund-form" data-owner-refund="${esc(review.id)}">
          <label><span>القرار</span><input name="resolution" required minlength="3" placeholder="مثال: تم التحقق وإغلاق المراجعة"></label>
          <label><span>ملاحظات</span><input name="notes" placeholder="ملاحظات اختيارية"></label>
          <button class="primary compact" type="submit">إغلاق المراجعة</button>
        </form>`}
    </article>`).join("") : '<div class="notice">لا توجد مراجعات استرداد معلقة.</div>';
  target.querySelectorAll("[data-owner-refund]").forEach((form) => {
    form.addEventListener("submit", resolveOwnerRefundReview);
  });
}

async function resolveOwnerRefundReview(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const orderId = form.dataset.ownerRefund;
  if (!window.confirm("سيتم إغلاق علامة المراجعة فقط، ولن يتم تنفيذ استرداد مالي. متابعة؟")) return;
  const button = form.querySelector("button[type='submit']");
  button.disabled = true;
  try {
    const values = Object.fromEntries(new FormData(form).entries());
    await api(`/api/v1/owner/numbers/refund-reviews/${encodeURIComponent(orderId)}/resolve`, {
      method: "POST",
      body: JSON.stringify(values),
    });
    setText("#owner-message", "تم إغلاق مراجعة طلب الأرقام.");
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

function renderOwnerDigitalOrders(rows) {
  const target = $("#owner-digital-orders");
  target.classList.toggle("empty", !rows.length);
  target.innerHTML = rows.length ? rows.map((order) => {
    const status = String(order.public_status || order.status || "").toLowerCase();
    const closed = ["completed", "success", "done", "refunded", "failed", "cancelled"].includes(status);
    return `
    <article class="owner-digital-order">
      <div class="owner-order-head">
        <div>
          <strong>${esc(order.item_name || order.product_name || order.game_name || "طلب رقمي")}</strong>
          <span>${esc(order.id || "")}</span>
        </div>
        <b>${esc(order.public_status || order.status || "")}</b>
      </div>
      <div class="owner-order-meta">
        <span>السعر: ${esc(order.price_label || order.price || "-")}</span>
        <span>المزود: ${esc(order.provider || "-")}</span>
        <span>اللاعب: ${esc(order.player_id || Object.values(order.customer_data || {}).filter(Boolean).slice(0, 2).join(" / ") || "-")}</span>
      </div>
      <details><summary>بيانات العميل</summary><pre>${esc(JSON.stringify(order.customer_data || {}, null, 2))}</pre></details>
      ${closed ? '<div class="notice">هذا الطلب مغلق ولا يقبل إجراءات إضافية.</div>' : `<div class="owner-order-actions">
        <button class="secondary compact" type="button" data-owner-order="${esc(order.id)}" data-owner-action="claim">استلام</button>
        <button class="secondary compact" type="button" data-owner-order="${esc(order.id)}" data-owner-action="auto_api">Auto API</button>
        <button class="secondary compact" type="button" data-owner-order="${esc(order.id)}" data-owner-action="future">Future</button>
        <button class="primary compact" type="button" data-owner-order="${esc(order.id)}" data-owner-action="complete">إكمال</button>
        <button class="danger compact" type="button" data-owner-order="${esc(order.id)}" data-owner-action="refund">استرداد</button>
      </div>`}
    </article>`;
  }).join("") : '<div class="notice">لا توجد طلبات رقمية ضمن هذا الفلتر.</div>';
  target.querySelectorAll("[data-owner-order]").forEach((button) => {
    button.addEventListener("click", () => runOwnerDigitalAction(button));
  });
}

async function runOwnerDigitalAction(button) {
  const orderId = button.dataset.ownerOrder;
  const action = button.dataset.ownerAction;
  const warning = action === "refund"
    ? "سيتم إعادة المبلغ إلى محفظة العميل. هل تريد تنفيذ الاسترداد؟"
    : `هل تريد تنفيذ الإجراء ${action} على هذا الطلب؟`;
  if (!window.confirm(warning)) return;
  button.disabled = true;
  setText("#owner-message", `جاري تنفيذ ${action}...`);
  try {
    const result = await api(`/api/v1/owner/digital/orders/${encodeURIComponent(orderId)}/action`, {
      method: "POST",
      body: JSON.stringify({ action, notify_user: true }),
      timeoutMs: 45000,
    });
    setText("#owner-message", `تم تنفيذ ${result.action || action}.`);
    await loadOwnerDashboard();
  } catch (error) {
    setText("#owner-message", error.message);
  } finally {
    button.disabled = false;
  }
}

function renderOrders(rows) {
  const target = $("#orders-list");
  renderRows(target, rows, (row) => `
    <button class="data-row order-row-button" type="button" data-order-channel="${esc(row.channel_key || "")}" data-order-id="${esc(row.id || "")}">
      <div>
        <strong>${esc(orderTitle(row))}</strong>
        <span>${esc(row.channel)} · ${esc(row.created_at || "")}</span>
      </div>
      <b>${esc(orderStatus(row))}</b>
    </button>`);
  target.querySelectorAll("[data-order-id]").forEach((button) => {
    button.addEventListener("click", () => loadOrderDetail(button.dataset.orderChannel, button.dataset.orderId));
  });
}

function orderTitle(row, fallback = "طلب") {
  return row.title || row.item_name || row.product_name || row.game_name || row.service_name || row.service || row.service_id || fallback;
}

function orderStatus(row) {
  return row.public_status || row.status || "";
}

function orderMetaRows(order, channel) {
  const rows = [
    ["القناة", channel === "numbers" ? "أرقام" : "رقمي"],
    ["رقم الطلب", order.id],
    ["الحالة", orderStatus(order)],
    ["السعر", order.price_label || (order.selling_price ? `$${Number(order.selling_price).toFixed(2)}` : "")],
    ["التاريخ", order.created_at || ""],
  ];
  if (channel === "numbers") {
    rows.push(["النوع", order.mode || ""]);
    rows.push(["الرقم", order.number || ""]);
    rows.push(["الكود", order.code || ""]);
    rows.push(["الوقت المتبقي", order.seconds_left ? `${order.seconds_left}s` : ""]);
  } else {
    rows.push(["المنتج", order.product_name || order.game_name || ""]);
    rows.push(["بيانات العميل", Object.entries(order.customer_data || {}).map(([key, value]) => `${key}: ${value}`).join(" · ")]);
  }
  return rows.filter(([, value]) => value !== undefined && value !== null && String(value).trim()).map(([label, value]) => `
    <div><span>${esc(label)}</span><strong>${esc(String(value))}</strong></div>
  `).join("");
}

async function loadOrderDetail(channel, orderId) {
  const target = $("#orders-list");
  if (!channel || !orderId) return;
  target.insertAdjacentHTML("afterbegin", '<div class="notice" id="order-detail-loading">جاري تحميل تفاصيل الطلب...</div>');
  try {
    const path = channel === "numbers" ? `/api/v1/numbers/orders/${encodeURIComponent(orderId)}` : `/api/v1/digital/orders/${encodeURIComponent(orderId)}`;
    const payload = await api(path);
    renderOrderDetail(channel, payload.order || {});
  } catch (error) {
    $("#order-detail-loading")?.remove();
    target.insertAdjacentHTML("afterbegin", `<div class="notice error">${esc(error.message)}</div>`);
  }
}

function renderOrderDetail(channel, order) {
  const target = $("#orders-list");
  const messages = (order.messages || []).filter((value) => String(value || "").trim());
  target.innerHTML = `
    <div class="order-detail-card">
      <div class="service-detail-head">
        <div><h4>${esc(orderTitle(order))}</h4><span>${esc(order.id || "")}</span></div>
        <button class="secondary compact" type="button" data-back-orders>رجوع</button>
      </div>
      <div class="order-meta-grid">${orderMetaRows(order, channel)}</div>
      ${messages.length ? `<div class="order-messages">${messages.map((message) => `<pre>${esc(message)}</pre>`).join("")}</div>` : ""}
      <div class="order-actions">${channel === "numbers" ? numbersOrderActionsHtml(order) : ""}</div>
      <p class="message" id="order-action-message"></p>
    </div>`;
  target.querySelector("[data-back-orders]").addEventListener("click", loadDashboard);
  target.querySelectorAll("[data-order-action]").forEach((button) => {
    button.addEventListener("click", () => runOrderAction(order, button.dataset.orderAction));
  });
}

function numbersOrderActionsHtml(order) {
  const labels = {
    refresh: "تحديث الكود",
    resend: "طلب كود ثاني",
    replace: "تبديل الرقم",
    alternate_provider: "مزود آخر",
    cancel: "إلغاء",
    rental_sms: "جلب رسائل الإيجار",
    rental_finish: "إنهاء الإيجار",
    rental_renew: "تجديد الإيجار",
    rental_wake: "تنشيط الإيجار",
  };
  return Object.entries(order.api_actions || {})
    .filter(([key, action]) => labels[key] && action?.enabled && action?.endpoint)
    .map(([key]) => `<button class="secondary compact" type="button" data-order-action="${esc(key)}">${esc(labels[key])}</button>`)
    .join("");
}

async function runOrderAction(order, actionKey) {
  const action = (order.api_actions || {})[actionKey] || {};
  const message = $("#order-action-message");
  if (!action.endpoint || !action.enabled) return;
  message.textContent = "جاري تنفيذ الإجراء...";
  try {
    const options = { method: action.method || "POST" };
    if (action.requires_idempotency_key) options.headers = { "Idempotency-Key": idempotencyKey(`order-${actionKey}`) };
    const payload = await api(action.endpoint, options);
    if (payload.order) {
      renderOrderDetail("numbers", payload.order);
      return;
    }
    const fresh = await api(`/api/v1/numbers/orders/${encodeURIComponent(order.id || "")}`);
    renderOrderDetail("numbers", fresh.order || order);
  } catch (error) {
    message.textContent = error.message;
  }
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
    $("#digital-products").innerHTML = products.filter(filter).sort(compareDigitalAvailability).slice(0, 80).map((row) => digitalItemButton("product", row)).join("")
      || '<div class="service-muted">لا توجد خدمات مطابقة.</div>';
    root.querySelectorAll("[data-digital-kind]").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.unavailable === "1") {
          $("#digital-detail").innerHTML = '<div class="service-empty">هذه الخدمة غير متاحة حالياً لأنها بدون مصدر أسعار فعال.</div>';
          return;
        }
        loadDigitalQuotes(button.dataset.digitalKind, button.dataset.digitalId);
      });
    });
  };
  $("#digital-search").addEventListener("input", renderItems);
  root.querySelector("[data-digital-refresh]").addEventListener("click", loadDigitalWorkspace);
  renderItems();
}

function compareDigitalAvailability(left, right) {
  const leftAvailable = digitalProductAvailable(left) ? 1 : 0;
  const rightAvailable = digitalProductAvailable(right) ? 1 : 0;
  if (leftAvailable !== rightAvailable) return rightAvailable - leftAvailable;
  return String(localized(left.label, left.name || left.id)).localeCompare(String(localized(right.label, right.name || right.id)), "ar");
}

function digitalProductAvailable(row) {
  if (!row) return false;
  if (row.orderable === false) return false;
  if ("sources_count" in row) return Number(row.sources_count || 0) > 0;
  return true;
}

function digitalItemButton(kind, row) {
  const name = localized(row.label, row.name || row.title || row.id);
  const meta = localized(row.category_label, row.category || row.provider || kind);
  const isProduct = kind === "product";
  const available = !isProduct || digitalProductAvailable(row);
  const sourcesCount = Number(row.sources_count || 0);
  const status = isProduct ? (available ? "متاح" : "غير متاح") : "";
  const sourceText = isProduct && sourcesCount > 0 ? `${sourcesCount} source${sourcesCount > 1 ? "s" : ""}` : meta;
  return `
    <button class="mini-card ${available ? "is-available" : "is-unavailable"}" type="button" data-digital-kind="${esc(kind)}" data-digital-id="${esc(row.id)}" ${available ? "" : 'data-unavailable="1" aria-disabled="true"'}>
      <span class="product-icon">${esc(name.slice(0, 1).toUpperCase())}</span>
      <span class="product-copy">
        <strong>${esc(name)}</strong>
        <span>${esc(sourceText)}</span>
      </span>
      ${isProduct ? `<b class="availability">${esc(status)}</b>` : ""}
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
    if (view === "owner") loadOwnerDashboard();
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
$("#refresh-owner")?.addEventListener("click", loadOwnerDashboard);
$("#owner-digital-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-refunds-resolved")?.addEventListener("change", loadOwnerDashboard);
$("#owner-recharge-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-identity-filter")?.addEventListener("change", loadOwnerDashboard);
$("#owner-support-filter")?.addEventListener("change", loadOwnerDashboard);

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
